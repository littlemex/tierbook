"""The compiled policy as a function of observed state, and the domain it is valid over.

Two independent adversarial reviews said the same thing about the previous output, from different directions:
what the compiler emitted was a **point**, not a function. Every state-dependent quantity was evaluated at the
observation cohort's state and reduced to a scalar, so the table was valid at one occupancy of one cluster --
non-transferable to the *same* cluster an hour later. That is the definition of tuning a fixed environment,
and it is what this module exists to stop.

## What a compiled policy is here

A list of rules. Each carries a **guard** -- a predicate over observed state -- an **assignment**, and the
measurement the guard's threshold came from. `decide(state)` evaluates them in order and returns the first
match, with the rule that fired and why.

    rule 0:  when reserved_inflight < 8      assign [box]        threshold from the service curve
    rule 1:  otherwise                       assign [api-strong] the declared default

The important property is not the shape but where the numbers come from: **a threshold is a measurement or it
is a gap.** There is no third option and no configuration file. A guard whose threshold nobody measured is
emitted as `unmeasured`, naming the quantity and the probe that would supply it, and a state that lands on such
a guard falls to the default rather than being decided by a number somebody assumed.

## Why the domain is part of the output

A policy without a stated domain invites its reader to apply it everywhere, which is exactly how "the box costs
$0.25 a request" escaped from one idle experimenter's afternoon. So every compiled policy carries the domain it
was compiled over -- which state variables were observed, at what values, and which of them nobody has bounded.
`decide` reports whether the state it was given is inside that domain, and outside it the answer is the
declared default with the reason "outside the compiled domain", not a silent extrapolation.

## What this is not

It is not a runtime, and it does not collect state. It is the compiled object a runtime would evaluate, plus
the evaluator, so that the thing being shipped has the type the requirement asks for. What is still missing is
named in `MISSING_FOR_A_CLOSED_LOOP` rather than implied to be present.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: State variables a guard may read. Closed on purpose: a guard over a variable nobody collects is a guard that
#: cannot be evaluated, and discovering that at request time is worse than refusing to compile it.
STATE_VARS = (
    "reserved_inflight",        # concurrent requests already on the reserved candidate
    "reserved_available",       # whether the reserved candidate is serving at all
    "metered_authorised",       # whether the gateway will still authorise spend on metered candidates
    "arrival_rate_per_hour",    # observed arrivals for this family
    "evidence_age_days",        # how old the measurements behind this policy are
)

#: The parts of a closed loop this module does not contain, named so their absence is not mistaken for
#: presence. Every one of them was raised by review and none is disguised as done.
MISSING_FOR_A_CLOSED_LOOP = (
    "a collector for the state variables above; `decide` is given a state, it does not observe one",
    "logged selection probabilities, without which an off-policy estimate of a policy nobody ran is "
    "unidentified -- and data collected without them cannot support that estimate later, however much of it "
    "there is",
    "exploration or shadow allocation, without which a candidate that is routed away from never gets another "
    "label and the incumbent is entrenched by construction",
    "anytime-valid bounds; the margins here are fixed-sample, which is anti-conservative once bounds are "
    "recomputed as evidence accrues and admission happens at a data-dependent stopping time",
    "change-point detection, so a policy stays valid until its evidence expires by age rather than because "
    "the environment stopped resembling the one it was measured in",
)

#: Why a guard cannot be evaluated or was never given a threshold. Closed so a gap can be counted.
GAP_REASONS = (
    "unmeasured_threshold",     # the quantity exists but nobody measured it
    "uncollected_variable",     # the guard reads a state variable this state did not carry
    "outside_domain",           # the state is outside the range the policy was compiled over
)


@dataclass(frozen=True)
class Guard:
    """A predicate over observed state, and where its threshold came from.

    `threshold` is None exactly when nobody measured it. That is not a disabled guard and not a permissive one:
    a rule whose guard has no threshold cannot fire, and `decide` says so. The alternative -- picking a
    plausible number -- is what turns an unmeasured quantity into a decision.
    """

    var: str
    op: str                        # "<", "<=", "==", ">=", ">"
    threshold: float | bool | None
    derived_from: str              # the measurement, or the probe that would supply it

    def __post_init__(self):
        if self.var not in STATE_VARS:
            raise ValueError(f"{self.var!r} is not a collected state variable; one of {STATE_VARS}")
        if self.op not in ("<", "<=", "==", ">=", ">"):
            raise ValueError(f"{self.op!r} is not a comparison this evaluates")

    @property
    def measured(self) -> bool:
        return self.threshold is not None

    def evaluate(self, state: dict) -> tuple[bool | None, str | None]:
        """True, False, or None with a reason when it cannot be evaluated at all."""
        if not self.measured:
            return None, "unmeasured_threshold"
        if self.var not in state:
            return None, "uncollected_variable"
        v, t = state[self.var], self.threshold
        if self.op == "<":
            return v < t, None
        if self.op == "<=":
            return v <= t, None
        if self.op == "==":
            return v == t, None
        if self.op == ">=":
            return v >= t, None
        return v > t, None

    def describe(self) -> str:
        if not self.measured:
            return f"{self.var} {self.op} (unmeasured: {self.derived_from})"
        return f"{self.var} {self.op} {self.threshold} (from {self.derived_from})"


@dataclass(frozen=True)
class Rule:
    """One branch of the policy: all guards must hold, and then this assignment applies."""

    guards: tuple[Guard, ...]
    assign: tuple[str, ...]
    because: str

    def evaluate(self, state: dict) -> tuple[bool, list[str]]:
        """Whether this rule fires, and the reasons any guard could not be evaluated.

        A guard that cannot be evaluated does not pass. The rule is skipped and the reason travels, because
        "the policy fell through to the default" and "the policy fell through because nobody measured the
        capacity" call for different actions.
        """
        gaps = []
        for g in self.guards:
            ok, why = g.evaluate(state)
            if ok is None:
                gaps.append(f"{g.var}: {why}")
                return False, gaps
            if not ok:
                return False, gaps
        return True, gaps


@dataclass(frozen=True)
class Policy:
    """A compiled policy: rules in order, a declared default, and the domain it was compiled over.

    The default is **not the cheapest thing on offer**. It is what the family falls back to when no rule fires,
    when the state is outside the domain, or when nothing was certified -- and in each of those cases the
    cheapest candidate is the one there is least reason to trust.
    """

    family: str
    rules: tuple[Rule, ...]
    default: tuple[str, ...]
    domain: dict = field(default_factory=dict)
    certified: bool = False
    note: str = ""

    @property
    def gaps(self) -> list[str]:
        """Every guard nobody measured, named. The list a reader should look at before the rules."""
        return [f"{g.var}: {g.derived_from}"
                for r in self.rules for g in r.guards if not g.measured]

    def in_domain(self, state: dict) -> tuple[bool, list[str]]:
        """Whether this state is inside the range the policy was compiled over.

        Checked before the rules, because a rule evaluated outside its domain returns an answer that looks like
        every other answer. `domain` maps a state variable to `[low, high]`; a variable absent from `domain` was
        not varied during measurement, so any value of it is outside what was observed and is reported as such.
        """
        outside = []
        for var, value in sorted(state.items()):
            rng = (self.domain or {}).get(var)
            if rng is None:
                outside.append(f"{var}={value} was not varied when this was measured, so no observation "
                               "covers it")
            elif not (rng[0] <= value <= rng[1]):
                outside.append(f"{var}={value} is outside the observed range [{rng[0]}, {rng[1]}]")
        return (not outside), outside


def decide(policy: Policy, state: dict) -> dict:
    """Evaluate a compiled policy against observed state.

    Returns the assignment, the rule that produced it, and -- always -- what about the answer is not supported:
    an out-of-domain state, an unmeasured guard, an uncollected variable. The point of returning that beside
    the assignment rather than logging it is that a caller cannot use one without seeing the other.
    """
    ok, outside = policy.in_domain(state)
    if not ok:
        # The unmeasured guards travel even here. Out-of-domain and unmeasured-threshold are usually the same
        # situation seen from two sides -- a quantity nobody probed has no observed range either -- and
        # reporting only the domain buries the actionable half, which is "run the probe".
        return {
            "assign": list(policy.default),
            "rule": None,
            "reason": "outside the compiled domain, so the declared default applies rather than an "
                      "extrapolation from measurements that do not cover this state",
            "gaps": [f"{GAP_REASONS[2]}: {o}" for o in outside]
                    + [f"{GAP_REASONS[0]}: {g}" for g in policy.gaps],
            "certified": False,
        }
    gaps = []
    for i, rule in enumerate(policy.rules):
        fired, why = rule.evaluate(state)
        gaps.extend(why)
        if fired:
            return {"assign": list(rule.assign), "rule": i, "reason": rule.because,
                    "gaps": gaps, "certified": policy.certified}
    return {
        "assign": list(policy.default),
        "rule": None,
        "reason": ("no rule fired, so the declared default applies. The default is deliberately not the "
                   "cheapest candidate: when no rule holds there is least reason to trust the cheapest one"),
        "gaps": gaps,
        "certified": False,
    }


def as_dict(policy: Policy) -> dict:
    """The policy as plain data, for the artifact. Readable without importing this module."""
    return {
        "family": policy.family,
        "default": list(policy.default),
        "certified": policy.certified,
        "note": policy.note,
        "domain": policy.domain,
        "unmeasured_guards": policy.gaps,
        "missing_for_a_closed_loop": list(MISSING_FOR_A_CLOSED_LOOP),
        "rules": [{"when": [g.describe() for g in r.guards], "assign": list(r.assign),
                   "because": r.because} for r in policy.rules],
    }


def compile_policy(family: str, entry: dict, *, reserved_ids: set[str], default: tuple[str, ...],
                   capacity_bound: float | None = None,
                   capacity_source: str = "no load probe at several concurrencies has been run, so the "
                                          "concurrency at which the reserved candidate stops absorbing work "
                                          "is unmeasured") -> Policy:
    """Derive the policy from one compiled family entry. Every threshold is a measurement or a named gap.

    The shape falls out of the accounting rather than being chosen. A reserved candidate is free at the margin
    **while it has capacity**, so the assignment has exactly one derived boundary: the occupancy at which that
    stops being true. Below it, use the capacity already paid for. Above it, the metered candidate -- which is
    the only place "at this concurrency, route to the API" comes from, and it is derived here rather than
    written down.

    `capacity_bound` is that boundary, and it comes from a service curve. Absent, the guard is emitted
    unmeasured: the rule cannot fire, every state falls to the default, and the missing probe is named. That is
    the honest state of this project today, and it is more useful than a plausible number because it says what
    to measure next.

    When nothing was certified the rules are empty and the default carries everything. A named-but-uncertified
    assignment is a fallback, not a choice the evidence supports, so it does not become a rule.
    """
    chosen = tuple(entry.get("chosen") or ())
    certified = entry.get("status") == "assigned"
    if not chosen or not certified:
        why = (entry.get("validation") or {}).get("reason") or "no held-out fold supports this assignment"
        return Policy(family, (), default, domain={}, certified=False,
                      note=f"no rule: nothing was certified for this family ({why}), so every request takes "
                           "the declared default")

    reserved = [c for c in chosen if c in reserved_ids]
    if not reserved:
        # No reserved candidate in the assignment: the choice does not depend on occupancy, so there is no
        # derived boundary and the rule is unconditional. Stated rather than left as an empty guard list that
        # could be mistaken for a gap.
        return Policy(family, (Rule((), chosen, "certified, and no candidate in this assignment is reserved, "
                                                "so the choice does not turn on occupancy"),),
                      default, domain={}, certified=True,
                      note="unconditional: nothing here is capacity-bound")

    guards = (
        Guard("reserved_available", "==", True,
              derived_from="observed while the cohort ran; a candidate that is not serving cannot absorb work"),
        Guard("reserved_inflight", "<", capacity_bound, derived_from=capacity_source),
    )
    rules = (
        Rule(guards, chosen,
             "the reserved candidate is certified for this family and free at the margin while it has "
             "capacity, so paid-for capacity is used before anything metered is charged"),
    )
    return Policy(family, rules, default,
                  domain={"reserved_available": [False, True]} if capacity_bound is None else
                         {"reserved_available": [False, True], "reserved_inflight": [0, capacity_bound]},
                  certified=True,
                  note=("the boundary between the reserved candidate and the default is the occupancy at which "
                        "the reserved one stops absorbing work. That is the only derived threshold here, and "
                        "it is " + ("measured" if capacity_bound is not None else "NOT measured yet")))
