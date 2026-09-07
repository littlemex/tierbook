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
    def overlaps(self) -> list[str]:
        """Pairs of rules that could both fire on one state, which makes tuple order the decision.

        `decide` returns the first match, so two rules whose guards can hold together mean the order they were
        appended in silently decides assignments. With one rule this was dormant; the capacity split made it two,
        and the two that matter here are provably disjoint -- `inflight < B` against `inflight >= B` -- which is
        exactly the kind of thing worth checking rather than asserting.
        """
        out = []
        for i, a in enumerate(self.rules):
            for j, b in list(enumerate(self.rules))[i + 1:]:
                if not _provably_disjoint(a, b):
                    out.append(f"rules {i} and {j} can both hold, so the order they are listed in decides "
                               f"between {list(a.assign)} and {list(b.assign)}")
        return out

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


#: Comparisons that cannot both hold for one value. Enough for the split this compiler emits, and deliberately
#: not a general solver: a check that quietly returns "disjoint" for a case it cannot analyse is worse than one
#: that admits the pair is unchecked.
_OPPOSED = {("<", ">="), (">=", "<"), ("<=", ">"), (">", "<=")}


def _provably_disjoint(a: Rule, b: Rule) -> bool:
    """Whether two rules provably cannot both fire, by finding one variable they oppose each other on."""
    for ga in a.guards:
        for gb in b.guards:
            if ga.var != gb.var or not (ga.measured and gb.measured):
                continue
            if (ga.op, gb.op) in _OPPOSED and ga.threshold == gb.threshold:
                return True
            if ga.op == "==" and gb.op == "==" and ga.threshold != gb.threshold:
                return True
    return False


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
        "provenance": policy.provenance,
        "unmeasured_guards": policy.gaps,
        "can_ever_fire": policy.can_ever_fire,
        "rule_overlaps": policy.overlaps,
        "missing_for_a_closed_loop": list(MISSING_FOR_A_CLOSED_LOOP),
        "rules": [{"when": [g.describe() for g in r.guards], "assign": list(r.assign),
                   "because": r.because} for r in policy.rules],
    }


def compile_policy(family: str, entry: dict, *, reserved_ids: set[str], metered_ids: set[str],
                   default: tuple[str, ...], default_declared_by: str,
                   service_curve: list | None = None, latency_p95_slo_s: float | None = None,
                   max_evidence_age_days: float | None = None) -> Policy:
    """Derive the policy from one compiled family entry. Every threshold is a measurement or a named gap.

    The shape falls out of the accounting rather than being chosen. A reserved candidate is free at the margin
    **while it has capacity**, so the assignment has exactly one derived boundary: the occupancy at which that
    stops being true. Below it, use the capacity already paid for. Above it, degrade -- to the assignment's own
    metered tail if it has one, and only otherwise to the declared default, because a certified cascade's tail
    is a measured continuation while an unrelated default is not.

    `service_curve` is where the boundary comes from, and it must be **measurements**: the probe's own points,
    each with a concurrency, a throughput and a p95 latency. The bound is derived from them against the p95 the
    operator already declares for this family -- see `_capacity_from_curve` for why a throughput knee cannot do
    the job. Accepting a scalar was an earlier shape and it was a configured threshold with documentation
    attached: a caller could pass 8 and the compiler would label it measured.

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

    if len(reserved) > 1:
        # Refused rather than partially guarded. An earlier version guarded the first reserved candidate and
        # recorded the others as "not modelled" -- but the whole assignment still fired and was exported, so the
        # unguarded legs ran with no capacity semantics at all. A degenerate output is a correct output here:
        # refusing to compile is better than emitting an assignment whose occupancy nobody can evaluate.
        return Policy(family, (), default, domain={}, certified=False, provenance=prov,
                      note=("no rule: this assignment contains reserved candidates "
                            f"{sorted(reserved)} and only one can be capacity-guarded. One occupancy figure "
                            "cannot describe several of them, and firing the assignment anyway would run the "
                            "unguarded legs with no capacity semantics. Compile one reserved candidate per "
                            "assignment, or give each its own availability and occupancy"))

    box = reserved[0]
    bound, source = _capacity_from_curve(service_curve, latency_p95_slo_s)
    tail = tuple(c for c in chosen if c not in reserved_ids)
    avail = Guard(f"available:{box}", "==", True,
                  derived_from="observed while the cohort ran; a candidate that is not serving cannot absorb "
                               "work")
    below = Guard(f"inflight:{box}", "<", bound, derived_from=source)
    at_or_above = Guard(f"inflight:{box}", ">=", bound, derived_from=source)
    unauthorised = Guard("metered_authorised", "==", False,
                         derived_from="the gateway authorises spend or it does not")

    # Four branches, because three of them were previously wrong or missing. The below-capacity rule used to
    # gate the WHOLE assignment on `metered_authorised`, so a spend refusal made paid-for box capacity
    # unreachable -- the box charges nothing and was being withheld for want of authorisation it does not need.
    # And the above-capacity tail carried no availability test, so with the box down and occupancy below the
    # bound neither rule fired even though the certified tail applied.
    rules = []
    if tail:
        rules.append(Rule((age, *money, avail, below), chosen,
                          "the reserved candidate is certified and free at the margin while it has capacity, "
                          "and its metered tail is authorised to catch what it cannot do"))
        # Explicitly the negation, not merely the absence, of the authorisation guard. Omitting it would leave
        # this rule a subset of the one above, and then which of them applied would be decided by the order they
        # happen to be listed in -- the thing the overlap check exists to catch.
        rules.append(Rule((age, unauthorised, avail, below), (box,),
                          "the reserved candidate has capacity but its metered tail is not authorised to "
                          "spend. Paid-for capacity is still usable, and withholding it for want of "
                          "authorisation the box does not need would be a refusal nothing requires"))
        rules.append(Rule((age, *money, avail, at_or_above), tail,
                          "at or above the reserved candidate's capacity, the assignment's own metered tail "
                          "carries the request. That tail was measured as part of this arrangement; the "
                          "declared default was not"))
        rules.append(Rule((age, *money, Guard(f"available:{box}", "==", False, derived_from=avail.derived_from)),
                          tail,
                          "the reserved candidate is not serving, so the assignment's own metered tail carries "
                          "the request rather than the unrelated default"))
    else:
        rules.append(Rule((age, *money, avail, below), chosen,
                          "the reserved candidate is certified for this family and free at the margin while it "
                          "has capacity, so paid-for capacity is used before anything metered is charged"))

    domain = {} if bound is None else {f"inflight:{box}": [0, float("inf")]}
    if max_evidence_age_days is not None:
        domain["evidence_age_days"] = [0, max_evidence_age_days]
    return Policy(family, tuple(rules), default, domain=domain, certified=True, provenance=prov,
                  note=("the boundary between the reserved candidate and what follows it is the occupancy at "
                        "which it stops meeting the declared latency constraint. That is the only derived "
                        "threshold here, and it is " + ("measured" if bound is not None else "NOT measured yet")))


def _bound_from_one_run(points: list, latency_p95_slo_s: float) -> tuple[float | None, str]:
    """The tested operating bound implied by ONE probe run. Not usable on its own -- see `_capacity_from_curve`."""
    usable = [pt for pt in points if pt.get("concurrency") is not None]
    if len(usable) < 2:
        return None, f"a run needs at least two concurrencies; this one has {len(usable)}"
    # Contiguous from the bottom: a point that meets the target above one that does not means the constraint is
    # not monotone in occupancy, and a bound with a hole under it is not a bound.
    within = []
    for pt in sorted(usable, key=lambda x: x["concurrency"]):
        ok = (pt.get("p95_latency_s") is not None and pt["p95_latency_s"] <= latency_p95_slo_s
              and (pt.get("failed") or 0) == 0)
        if not ok:
            break
        within.append(pt)
    if not within:
        return None, (f"no probed concurrency met {latency_p95_slo_s:.2f}s at p95 without failures; the lowest "
                      "point already misses it")
    best = within[-1]
    top = max(pt["concurrency"] for pt in usable)
    extra = ""
    if best["concurrency"] >= top:
        extra = " (CENSORED: the highest concurrency probed, so the true bound is at least this)"
    higher_ok = [pt for pt in sorted(usable, key=lambda x: x["concurrency"])
                 if pt["concurrency"] > best["concurrency"] and pt.get("p95_latency_s") is not None
                 and pt["p95_latency_s"] <= latency_p95_slo_s]
    if higher_ok:
        extra += (f" ({[int(pt['concurrency']) for pt in higher_ok]} also met the target above a point that did "
                  "not, so the constraint is not monotone in occupancy here)")
    return float(best["concurrency"]), (f"{int(best['concurrency'])} in flight, p95 {best.get('p95_latency_s')}s, "
                                        f"{best.get('tasks_per_hour')} tasks/hour{extra}")


def _capacity_from_curve(runs: list | None, latency_p95_slo_s: float | None = None) -> tuple[float | None, str]:
    """A tested operating bound, and only when repeated probes agree on it.

    Three answers have been tried here and the first two were wrong. A knee in throughput under a declared
    marginal-gain fraction: refuted, because the marginal gains were near-flat then twenty-one percent and the
    rule reported the first flat step. Then the highest probed occupancy meeting a declared p95: better, because
    the constraint is one the operator states anyway -- but derived from a single run.

    Then the run was repeated, which is this project's own rule about any conclusion, and **nothing survived**.
    At two batches per point the probe read p95 17.5 s at 64 in flight; at eight it read 45.7 s. Throughput at 64
    fell 21.8 percent, at 128 rose 18.9 percent, and the flat step that the first analysis had turned into a
    capacity vanished -- 128 became the peak. Against a 20-second target the first run yields a bound of 64 and
    the second yields none at all, because even 64 misses.

    So a bound requires replicates that agree. One run is refused with that history, because a threshold that
    changes by a factor of 2.6 between runs is not a property of the candidate. Replicates that disagree are
    refused with both values, which is more useful than either.
    """
    if not runs:
        return None, ("no load probe has been run, so nothing is known about the occupancy at which the reserved "
                      "candidate stops meeting its latency target")
    # A single point-list is one run. A list of point-lists is replicates.
    blocks = runs if runs and isinstance(runs[0], list) else [runs]
    if latency_p95_slo_s is None:
        shape = "; ".join(
            "run %d: %s" % (i + 1, ", ".join(f"c={int(pt['concurrency'])} {pt.get('tasks_per_hour')}/h p95 "
                                             f"{pt.get('p95_latency_s')}s"
                                             for pt in sorted(b, key=lambda x: x["concurrency"])))
            for i, b in enumerate(blocks))
        return None, ("a service curve exists but no p95 latency constraint was declared for this family, and "
                      "throughput alone does not locate a bound: on one real probe the marginal gain went half a "
                      "percent from 64 to 128 in flight and then 21 percent from 128 to 256, and a repeat run "
                      f"reversed that shape entirely. Declare the p95 this family must meet. Measured: {shape}")
    if len(blocks) < 2:
        one, why = _bound_from_one_run(blocks[0], latency_p95_slo_s)
        return None, ("a bound was computed from a SINGLE probe run and is refused on this deployment's own "
                      f"history: {why if one is None else 'it would be ' + why}. Repeating the probe changed p95 "
                      "at 64 in flight from 17.5 s to 45.7 s and moved the throughput peak from 256 to 128, so "
                      "one run does not measure a property of the candidate. Probe again and pass both runs")
    bounds, whys = [], []
    for i, b in enumerate(blocks):
        v, why = _bound_from_one_run(b, latency_p95_slo_s)
        bounds.append(v)
        whys.append(f"run {i + 1}: {why}")
    if len(set(bounds)) != 1 or bounds[0] is None:
        return None, (f"the probe runs do not agree on a bound at {latency_p95_slo_s:.2f}s -- {'; '.join(whys)}. "
                      "A threshold that moves between runs is not a property of the candidate, and taking either "
                      "value would be choosing which run to believe")
    return bounds[0], (f"a TESTED OPERATING BOUND, not a physical capacity, and it REPRODUCED across "
                       f"{len(blocks)} probe runs at a declared {latency_p95_slo_s:.2f}s p95: "
                       + "; ".join(whys))
