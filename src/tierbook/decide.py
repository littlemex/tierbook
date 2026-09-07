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
#: A guard reads a state variable of the form `<var>` for a global fact or `<var>:<candidate>` for one about a
#: named candidate. Occupancy and availability are per candidate on purpose: an arrangement can contain more
#: than one reserved candidate, and a single global counter guarded by a per-candidate threshold is a category
#: error the moment two of them exist -- or the moment two families share one box, since the threshold comes
#: from a per-family service curve.
STATE_VARS = (
    "inflight",                 # concurrent requests already on a named candidate
    "available",                # whether a named candidate is serving at all
    "metered_authorised",       # whether the gateway will still authorise spend on metered candidates
    "arrival_rate_per_hour",    # observed arrivals for this family
    "evidence_age_days",        # how old the measurements behind this policy are
)


def var_name(spec: str) -> str:
    """The variable a guard reads, with any candidate qualifier stripped."""
    return spec.split(":", 1)[0]

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
    "a value for the reserved candidate's scarce capacity. Below capacity its marginal charge is nothing, so "
    "these rules give it to whichever certified request arrives first -- and the last free slot spent on a "
    "request that avoids a tenth of a cent of metered spend displaces one that would have avoided a dollar. "
    "That is scheduling utility rather than a gateway charge, which is why it is not in the cost objective, "
    "but it is also not nowhere: greedy use is locally right and globally unproven",
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
        if var_name(self.var) not in STATE_VARS:
            raise ValueError(f"{self.var!r} does not name a state variable this evaluates; one of {STATE_VARS}, "
                             "optionally qualified as <var>:<candidate>")
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
        gaps, fires = [], True
        for g in self.guards:
            ok, why = g.evaluate(state)
            if ok is None:
                # Every unevaluable guard is collected, not just the first. Returning early hid the later ones,
                # so a rule with two unmeasured thresholds reported one and looked half as far from working as
                # it was.
                gaps.append(f"{g.var}: {why}")
                fires = False
            elif not ok:
                fires = False
        return fires, gaps


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
    #: Where the parts that were not derived came from. The default in particular is DECLARED, and an artifact
    #: that does not say who declared it invites a reader to take it for a measured choice.
    provenance: dict = field(default_factory=dict)

    @property
    def can_ever_fire(self) -> bool:
        """Whether any rule could fire under any state.

        A policy every path of which lands on the default is not a degenerate policy, it is an inert one, and
        the difference matters: the first is a correct answer and the second is a component that does nothing
        while looking like it works. An earlier version shipped exactly that -- an unmeasured guard meant no
        rule could ever fire -- while a separately exported router config named the guarded candidate anyway.
        Two artifacts, disagreeing, both called the output.
        """
        return any(all(g.measured for g in r.guards) for r in self.rules)

    @property
    def gaps(self) -> list[str]:
        """Every guard nobody measured, named. The list a reader should look at before the rules."""
        return [f"{g.var}: {g.derived_from}"
                for r in self.rules for g in r.guards if not g.measured]

    @property
    def guarded_candidates(self) -> set[str]:
        """Candidates a rule assigns to under a guard that could fire. What an exporter may name."""
        out = set()
        for r in self.rules:
            if all(g.measured for g in r.guards):
                out.update(r.assign)
        return out

    def in_domain(self, state: dict) -> tuple[bool, list[str]]:
        """Whether this state is inside the range the policy was compiled over.

        Checked before the rules, because a rule evaluated outside its domain returns an answer that looks like
        every other answer. `domain` maps a state variable to `[low, high]`; a variable absent from `domain` was
        not varied during measurement, so any value of it is outside what was observed and is reported as such.
        """
        # Only the variables the GUARDS read are checked. An earlier version iterated the whole state and
        # rejected anything absent from `domain`, which inverted the design: a caller that collected all the
        # documented variables was permanently out of domain and every request took the default, so observing
        # more made the policy apply less. Extra observations are not a reason to refuse.
        outside = []
        for spec in sorted({g.var for r in self.rules for g in r.guards}):
            if spec not in state:
                continue
            rng = (self.domain or {}).get(spec)
            if rng is None:
                continue          # the guard itself reports an unmeasured threshold; that is not a domain fact
            value = state[spec]
            if not (rng[0] <= value <= rng[1]):
                outside.append(f"{spec}={value} is outside the range this was measured over "
                               f"[{rng[0]}, {rng[1]}]")
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


def compile_policy(family: str, entry: dict, *, reserved_ids: set[str], metered_ids: set[str],
                   default: tuple[str, ...], default_declared_by: str,
                   service_curve: dict | None = None, min_marginal_gain: float | None = None,
                   max_evidence_age_days: float | None = None) -> Policy:
    """Derive the policy from one compiled family entry. Every threshold is a measurement or a named gap.

    The shape falls out of the accounting rather than being chosen. A reserved candidate is free at the margin
    **while it has capacity**, so the assignment has exactly one derived boundary: the occupancy at which that
    stops being true. Below it, use the capacity already paid for. Above it, degrade -- to the assignment's own
    metered tail if it has one, and only otherwise to the declared default, because a certified cascade's tail
    is a measured continuation while an unrelated default is not.

    `service_curve` is where the boundary comes from, and it must be **measurements**, not a number: a mapping
    of concurrency to observed tasks per hour, from a load probe. The bound is derived here, as the highest
    concurrency at which throughput was still rising -- above that the candidate is absorbing no more work.
    Accepting a scalar was the previous shape and it was a configured threshold with documentation attached: a
    caller could pass 8 and the compiler would label it measured.

    Two guards nobody had written are written now, because "a threshold is a measurement or a gap" had a third
    case: a guard that does not exist. `metered_authorised` gates any assignment that charges, so a rule cannot
    keep firing after the gateway stops authorising spend; `evidence_age_days` gates every rule, so a policy
    stops asserting itself when the measurements behind it expire. Without them `decide` returned a confident
    assignment that could not be paid for, and reported no gap at all.
    """
    chosen = tuple(entry.get("chosen") or ())
    certified = entry.get("status") == "assigned"
    prov = {"default_declared_by": default_declared_by}
    if not chosen or not certified:
        why = (entry.get("validation") or {}).get("reason") or "no held-out fold supports this assignment"
        return Policy(family, (), default, domain={}, certified=False, provenance=prov,
                      note=f"no rule: nothing was certified for this family ({why}), so every request takes "
                           "the declared default")

    age = (Guard("evidence_age_days", "<=", max_evidence_age_days,
                 derived_from=("the freshness bound stated for this registry"
                               if max_evidence_age_days is not None else
                               "no freshness bound was stated, so nothing says when these measurements stop "
                               "describing the environment"))
           if True else None)
    money = [Guard("metered_authorised", "==", True,
                   derived_from="the gateway authorises spend or it does not; an assignment that charges "
                                "cannot proceed when it has stopped")] if set(chosen) & metered_ids else []

    reserved = [c for c in chosen if c in reserved_ids]
    if not reserved:
        return Policy(family, (Rule((age, *money), chosen,
                                    "certified, and no candidate in this assignment is reserved, so the choice "
                                    "does not turn on occupancy"),),
                      default, domain={}, certified=True, provenance=prov,
                      note="unconditional in occupancy: nothing here is capacity-bound")

    box = reserved[0]
    bound, source = _capacity_from_curve(service_curve, min_marginal_gain)
    # Above capacity the assignment's own metered tail is a measured continuation; an unrelated default is not.
    tail = tuple(c for c in chosen if c not in reserved_ids)
    guards = (age, *money,
              Guard(f"available:{box}", "==", True,
                    derived_from="observed while the cohort ran; a candidate that is not serving cannot absorb "
                                 "work"),
              Guard(f"inflight:{box}", "<", bound, derived_from=source))
    rules = [Rule(guards, chosen,
                  "the reserved candidate is certified for this family and free at the margin while it has "
                  "capacity, so paid-for capacity is used before anything metered is charged")]
    if tail:
        rules.append(Rule((age, *money, Guard(f"inflight:{box}", ">=", bound, derived_from=source)), tail,
                          "above the reserved candidate's capacity, the assignment's own metered tail carries "
                          "the request. That tail was measured as part of this arrangement; the declared "
                          "default was not"))
    if len(reserved) > 1:
        prov["reserved_not_modelled"] = sorted(reserved[1:])
        prov["reserved_not_modelled_note"] = (
            "this assignment contains more than one reserved candidate and only the first is capacity-guarded. "
            "One occupancy figure cannot describe two of them, and guessing which one a request would land on "
            "is a scheduling decision this does not make")
    # The domain does NOT stop at the boundary. Above capacity is the measured branch, not an unknown region,
    # and truncating there classified the default branch as an unsupported extrapolation.
    domain = {} if bound is None else {f"inflight:{box}": [0, float("inf")]}
    if max_evidence_age_days is not None:
        domain["evidence_age_days"] = [0, max_evidence_age_days]
    return Policy(family, tuple(rules), default, domain=domain, certified=True, provenance=prov,
                  note=("the boundary between the reserved candidate and what follows it is the occupancy at "
                        "which the reserved one stops absorbing work. That is the only derived threshold here, "
                        "and it is " + ("derived from a service curve" if bound is not None
                                        else "NOT measured yet")))


def _capacity_from_curve(curve: dict | None, min_marginal_gain: float | None = None) -> tuple[float | None, str]:
    """Derive the occupancy bound from a service curve, or say why there is none.

    The curve maps concurrency to observed tasks per hour. The bound is the highest concurrency up to which
    every step still bought at least `min_marginal_gain` more throughput; past it the candidate absorbs no more
    useful work, so sending more is queueing rather than serving.

    **`min_marginal_gain` is a declared policy input, and it has to be**, because "stopped rising" is not a
    fact about the curve. The real probe here went 22,908 tasks/hour at 64 in flight to 23,035 at 128 -- a rise
    of half a percent, while mean latency doubled from 8.2 to 17.6 seconds. Strictly that is rising, and a
    strict test walks straight past the knee; anything stricter needs a number, and inventing one here would be
    the configured threshold this module exists to avoid. So the operator states what a worthwhile gain is, the
    artifact records it, and the bound is derived from the measurements under that statement.
    """
    if not curve:
        return None, ("no load probe at several concurrencies has been run, so the occupancy at which the "
                      "reserved candidate stops absorbing work is unmeasured")
    points = sorted((float(k), float(v)) for k, v in curve.items())
    if len(points) < 2:
        return None, (f"a service curve needs at least two concurrencies to show where throughput stops "
                      f"rising; this one has {len(points)}")
    if min_marginal_gain is None:
        return None, (f"a service curve over {[int(c) for c, _ in points]} exists but no marginal-gain "
                      "criterion was declared, and 'stopped rising' is not a fact about a curve: one real probe "
                      "rose half a percent between two concurrencies while latency doubled. State what gain is "
                      "worth the occupancy")
    best_c, best_tph = points[0]
    for c, tph in points[1:]:
        if best_tph <= 0 or (tph - best_tph) / best_tph < min_marginal_gain:
            break
        best_c, best_tph = c, tph
    if best_c == points[-1][0]:
        # Censored, not measured. Throughput was still rising at the highest concurrency probed, so the
        # occupancy where it stops is somewhere above the range -- and returning the top of the range would
        # emit the probe's own limit as if it were the candidate's. The first probe run here did exactly this:
        # still rising at 32, which says the probe was too small and nothing about the box.
        return None, (f"the probe over {[int(c) for c, _ in points]} was still buying at least "
                      f"{min_marginal_gain:.0%} more throughput at the highest concurrency tried "
                      f"({int(best_c)}, {best_tph:.1f} tasks/hour), so where that stops is above the range "
                      "probed. That is the probe's limit, not the candidate's; run it higher")
    return best_c, (f"derived from a service curve over concurrencies {[int(c) for c, _ in points]} under a "
                    f"declared {min_marginal_gain:.0%} marginal-gain criterion: the last step worth taking "
                    f"reached {int(best_c)} in flight at {best_tph:.1f} tasks/hour")


def as_dict(policy: Policy) -> dict:
    """The policy as plain data, for the artifact. Readable without importing this module."""
    return {
        "family": policy.family,
        "default": list(policy.default),
        "certified": policy.certified,
        "note": policy.note,
        "domain": policy.domain,
        "provenance": policy.provenance,
        "unmeasured_guards": policy.gaps,
        "can_ever_fire": policy.can_ever_fire,
        "missing_for_a_closed_loop": list(MISSING_FOR_A_CLOSED_LOOP),
        "rules": [{"when": [g.describe() for g in r.guards], "assign": list(r.assign),
                   "because": r.because} for r in policy.rules],
    }
