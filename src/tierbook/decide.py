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

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only: a runtime import here would close a cycle (`policy` -> `accept` -> `record` -> `observe` ->
    # `decide`). `compile_policy` below imports `candidates_for` locally, at call time, once every module in
    # that chain has already finished loading.
    from .policy import Tier

#: State variables a guard may read. Closed on purpose: a guard over a variable nobody collects is a guard that
#: cannot be evaluated, and discovering that at request time is worse than refusing to compile it.
#: A guard reads a state variable of the form `<var>` for a global fact or `<var>:<candidate>` for one about a
#: named candidate. Occupancy and availability are per candidate on purpose: an arrangement can contain more
#: than one reserved candidate, and a single global counter guarded by a per-candidate threshold is a category
#: error the moment two of them exist -- or the moment two families share one box, since the threshold comes
#: from a per-family service curve.
#: **A DEFAULT, not a gate.** These five are the variables this project happened to need, offered so a caller with the
#: same needs does not retype them. A `Rule` is **not** validated against this list.
#:
#: It used to be, and that was a violation of the rule at the top of `__init__.py`: the mechanism decided which facts a
#: policy was allowed to condition on. The governing document names price revisions, rate limits, degradation, request
#: shape, floors, SLOs, quotas and time of day as things this same mechanism must handle -- **and not one of them is in
#: this tuple.** A study needing `price_per_mtok` or `hour_of_day` could not write a guard at all.
#:
#: What the mechanism enforces instead is that a guard reads a variable **its own policy declares**, so a rule cannot
#: read a fact nobody supplies. The vocabulary is per policy and the contents are the caller's.
DEFAULT_STATE_VARS = (
    "inflight",                 # concurrent requests already on a named candidate
    "available",                # whether a named candidate is serving at all
    "metered_authorised",       # whether the gateway will still authorise spend on metered candidates
    "arrival_rate_per_hour",    # observed arrivals for this family
    "evidence_age_days",        # how old the measurements behind this policy are
)

#: Which of the defaults are read per candidate rather than globally. Also a default, for the same reason: whether a
#: variable is about one candidate or about the whole arrangement is a property of the variable a caller declares.
DEFAULT_PER_CANDIDATE = ("inflight", "available")


def var_name(spec: str) -> str:
    """The variable a guard reads, with any candidate qualifier stripped."""
    return spec.split(":", 1)[0]

#: The parts of a closed loop this module does not contain, named so their absence is not mistaken for
#: presence. `as_dict` ships this list inside every compiled policy, so an item that stops being true is a
#: false statement in a machine-readable artifact rather than a stale comment.
#:
#: Three items were removed in v0.2.0 because they had shipped: a state collector (`observe`, in v0.1.0), and
#: logged selection probabilities and exploration (both C3, this release). The first had been false for a
#: whole release, and a test asserted the artifact still claimed it -- so the guard over this set required the
#: artifact to lie. `CLOSED_LOOP_PROBES` below is why that cannot happen again: every claim here has to name
#: the symbol whose existence would falsify it.
MISSING_FOR_A_CLOSED_LOOP = (
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


#: One probe per claim above, keyed by a substring unique to it. Each probe returns True while the claim is
#: still true -- that is, while the named thing is still absent -- and the test beside it fails if any claim
#: and its probe disagree.
#:
#: This exists because the previous guard asserted four substrings were PRESENT in the artifact, which no new
#: mechanism can fail: shipping exploration left the guard green and the artifact wrong. A probe names the
#: symbol whose existence falsifies its claim, so shipping the mechanism and forgetting to retire the claim
#: breaks a test at merge time. A claim whose probe cannot be written is a claim too vague to ship inside an
#: artifact, and that is the bar for adding one here.
CLOSED_LOOP_PROBES = {
    "anytime-valid bounds": lambda: not _module_has("tierbook.evidence", "anytime_valid_lower_bound"),
    "change-point detection": lambda: not _module_has("tierbook.observe", "change_point"),
    "reserved candidate's scarce capacity": lambda: not _module_has("tierbook.policy", "capacity_value"),
}


def _module_has(module: str, symbol: str) -> bool:
    """Whether `module` defines `symbol`, with a missing module counting as not defining it.

    An ImportError here means the module does not exist yet, which is a stronger form of the symbol being
    absent rather than a failure to answer -- so it is not raised. What is NOT swallowed is the module
    existing and failing to import for its own reasons; that would make every probe silently agree with
    every claim, which is the failure this whole mechanism replaced.
    """
    import importlib

    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError:
        return False
    return hasattr(mod, symbol)

#: Why a guard cannot be evaluated or was never given a threshold. Closed so a gap can be counted.
GAP_REASONS = (
    "unmeasured_threshold",     # the quantity exists but nobody measured it
    "uncollected_variable",     # the guard reads a state variable this state did not carry
    "outside_domain",           # the state is outside the range the policy was compiled over
    # A cost was recorded and nothing says where it came from. Not a defect in the decision -- the choice is sound --
    # but the derivation behind it cannot be repeated, and that was measured to cost a day: a cheap/dear split over nine
    # candidates had to be reverse-engineered from prose in three documents, confirmable only because an item count
    # happened to be known. A gap rather than a refusal, because the alternative is a record that cannot hold a cost.
    "unrecorded_price_basis",
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
        # SHAPE only. Which names are meaningful belongs to the policy that declares them, and `Policy` checks that a
        # rule reads one its own vocabulary carries -- so a guard still cannot read a fact nobody supplies, without this
        # module deciding what facts exist.
        if not var_name(self.var).strip():
            raise ValueError(f"{self.var!r} names no state variable; the form is <var> for a global fact or "
                             f"<var>:<candidate> for one about a named candidate")
        if self.var.count(":") > 1:
            raise ValueError(f"{self.var!r} has more than one candidate qualifier, so nothing says which candidate the "
                             f"guard is about")
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
    #: The state variables this policy's guards may read, and which of them are per candidate. **Declared here rather
    #: than fixed in the module**, so a study conditioning on a price revision, a quota or an hour of the day can write a
    #: guard -- all three are named in the governing document as this mechanism's business, and none was in the old
    #: module-level list. Empty falls back to `DEFAULT_STATE_VARS`, which keeps every existing caller working while making
    #: the default visibly a default.
    state_vars: tuple[str, ...] = ()
    per_candidate: tuple[str, ...] = ()
    domain: dict = field(default_factory=dict)
    #: CONTRACT C1: named `validated`, not `certified` -- this is the non-inferiority validation status (a held-out
    #: fold supported this assignment against the reference), never SCOPE section 2 admissibility. Before this
    #: rename, `decide.py` set `certified = entry.get("status") == "assigned"` and `record.check_certification`
    #: computed something else under the identical word, and `tierbook route`'s online path returned the first to
    #: an operator who declared a floor and had every reason to read it as the second. `certified` now belongs to
    #: `record.Decision` alone, where it means section 2.
    validated: bool = False
    note: str = ""
    #: Where the parts that were not derived came from. The default in particular is DECLARED, and an artifact
    #: that does not say who declared it invites a reader to take it for a measured choice.
    provenance: dict = field(default_factory=dict)
    #: What this was compiled under -- at least `floor` and `max_evidence_age_days`, plus `staleness_limit_days`
    #: and `exploration_rate` for the door C3 opens. The compiled table used to carry `certified: true` and
    #: never write the floor down, so no criterion computed later could be known to have used the same number a
    #: shell prompt typed. This is the one home for that number; `parameter` is the one reader of it.
    parameters: dict = field(default_factory=dict)
    #: CONTRACT C2: a content hash of this artifact's own serialisation, the way `policy.registry_version`
    #: already hashes the ledger. Stamped by `compile_policy` (via `policy_digest`, below), never supplied by a
    #: direct `Policy(...)` call -- there is no `__post_init__` guard against that here because a test building a
    #: `Policy` by hand to exercise `decide()` has no artifact to be named after, and `""` reads as exactly that:
    #: no digest was ever computed for this object. `route_once` reads this attribute rather than recomputing it,
    #: so a record names the artifact `compile_policy` actually produced, not a hash of whatever the record's
    #: own reader would derive from it later.
    policy_digest: str = ""
    #: CONTRACT v0.3.0 C6, as amended by amendment 10: the ids of every candidate the ledger records an outcome
    #: for this family. MEMBERSHIP and no number -- a bound recorded here would be the fixed-sample single-test
    #: quantity R1 rejects, and nothing would read it. Stamped by `compile_policy`, never supplied by a direct
    #: `Policy(...)` call -- an empty set is the honest reading for a hand-built policy with no ledger behind it,
    #: the same default-for-an-incomplete-object treatment `policy_digest` above already gets. `serve.candidate_set`
    #: reads this instead of deriving from `rules`/`default`: a candidate with no rule used to be absent from the
    #: set entirely -- invisible to exploration, never labelled, its evidence never refreshed -- and a set built
    #: from what a rule happens to name cannot end that.
    candidates: tuple = ()

    @property
    def vocabulary(self) -> tuple[str, ...]:
        """The state variables this policy's guards may read. Falls back to the defaults when none was declared."""
        return self.state_vars or DEFAULT_STATE_VARS

    @property
    def per_candidate_vars(self) -> tuple[str, ...]:
        """Which of this policy's variables are read per candidate."""
        if self.per_candidate:
            return self.per_candidate
        return tuple(v for v in DEFAULT_PER_CANDIDATE if v in self.vocabulary)

    def undeclared_vars(self) -> list[str]:
        """Variables this policy's rules read and its vocabulary does not carry.

        The guarantee that survived moving the vocabulary out of the module: a guard cannot read a fact nobody supplies,
        because a rule reading a name the policy never declared has nothing to be evaluated against and discovering that
        at request time is worse than refusing to compile it. What changed is only **who decides which names exist.**
        """
        known = set(self.vocabulary)
        return sorted({var_name(r.var) for r in self.rules if var_name(r.var) not in known})

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

    CONTRACT C1: the key is `validated`, not `certified`. This is `policy.validated` -- the non-inferiority status
    a held-out fold gave this assignment against the reference -- and it is the value `serve.route_once` reads (as
    `got["validated"]`) for the deterministic path. Calling it `certified` here read as SCOPE section 2 admissibility
    to a caller who had no way to know it was something else, which is R5's finding in this module by name.
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
            "validated": False,
        }
    gaps = []
    for i, rule in enumerate(policy.rules):
        fired, why = rule.evaluate(state)
        gaps.extend(why)
        if fired:
            return {"assign": list(rule.assign), "rule": i, "reason": rule.because,
                    "gaps": gaps, "validated": policy.validated}
    return {
        "assign": list(policy.default),
        "rule": None,
        "reason": ("no rule fired, so the declared default applies. The default is deliberately not the "
                   "cheapest candidate: when no rule holds there is least reason to trust the cheapest one"),
        "gaps": gaps,
        "validated": False,
    }


def as_dict(policy: Policy) -> dict:
    """The policy as plain data, for the artifact. Readable without importing this module."""
    return {
        "family": policy.family,
        "default": list(policy.default),
        "validated": policy.validated,
        "note": policy.note,
        "domain": policy.domain,
        "provenance": policy.provenance,
        "parameters": policy.parameters,
        "policy_digest": policy.policy_digest,
        # CONTRACT v0.3.0 C6: written unconditionally, including `{}`, so a round trip through `as_dict` ->
        # `from_dict` always carries the key -- the same reason `parameters` is written even when empty.
        "candidates": list(policy.candidates),
        "unmeasured_guards": policy.gaps,
        "can_ever_fire": policy.can_ever_fire,
        "rule_overlaps": policy.overlaps,
        "missing_for_a_closed_loop": list(MISSING_FOR_A_CLOSED_LOOP),
        # Both forms, and both for a reason. `when` is the prose a reader needs; `guards` is the fields a loader
        # needs. An earlier version wrote only the prose, which made the artifact one-way: a policy written to disk
        # could not be read back, so the deployable path had to rebuild the object it had just serialised.
        "rules": [{"when": [g.describe() for g in r.guards],
                   "guards": [{"var": g.var, "op": g.op, "threshold": g.threshold,
                               "derived_from": g.derived_from} for g in r.guards],
                   "assign": list(r.assign), "because": r.because} for r in policy.rules],
    }


def from_dict(d: dict) -> Policy:
    """The inverse of `as_dict`, so a compiled policy on disk is a policy again.

    Reads `guards` rather than `when`: the prose is for a reader and cannot be parsed back without inventing a
    grammar, which is the sort of thing that works until a threshold contains a space.

    A policy carrying rules but no `parameters` key was compiled by a version that never wrote the floor or the
    evidence-age limit down -- a v0.1.0 artifact is exactly this case, and it is refused for the same reason the
    guards-as-prose case above is: an artifact that cannot say what it was compiled under is not the source, and
    guessing what a shell prompt typed at compile time is worse than recompiling.

    CONTRACT C1: a `certified` key is refused, named against `validated`, rather than read as this release's field
    under its old name. `certified` here was always the non-inferiority validation status computed by
    `entry.get("status") == "assigned"`; `record.Decision.certified` is a different judgment -- SCOPE section 2
    admissibility -- and reading a v0.2.0-or-earlier artifact's `certified` optimistically into `validated` would
    quietly relabel the first as if it always meant the second, which is the ambiguity this entry exists to close.
    A v0.2.0 artifact carries exactly this key and is exactly this case; recompiling under the current schema is
    what produces `validated` honestly.
    """
    if d.get("rules") and "parameters" not in d:
        raise ValueError(
            "this policy was written by a version that recorded rules with no 'parameters' key, so it cannot be "
            "loaded: nothing here can say what floor or evidence-age limit it was compiled under. Recompile it: "
            "the artifact is not the source, and re-deriving it is cheaper than trusting a number nobody wrote "
            "down")
    if "certified" in d:
        raise ValueError(
            "this policy carries a 'certified' key, which named the non-inferiority validation status in every "
            "version before this one -- 'validated' is what this reader calls that same judgment now, and "
            "'certified' is reserved for record.Decision's different one, SCOPE section 2 admissibility. Reading "
            "'certified' into 'validated' here would relabel the first judgment as if it had always been named "
            "correctly. Recompile it: the artifact is not the source, and re-deriving it under the current schema "
            "is what produces 'validated' honestly")
    # CONTRACT v0.3.0 C6: an artifact with no 'candidates' key was compiled by a version that built the candidate
    # set from `rules`/`default` rather than from the ledger's own outcomes. Refused rather than read as an empty
    # set: falling back silently is what made a candidate with no rule invisible in the first place, and `as_dict`
    # above writes this key unconditionally, so nothing this reader ever wrote itself can trigger this on a round
    # trip.
    #
    # NOT gated on the artifact carrying rules. A RULES-LESS artifact is the sharper case, not the exempt one: it
    # is exactly what the shipped ledger produced in the incident C6 exists to close -- the compiler certified
    # nothing on a 20-item cohort, so `rules` was empty, the set collapsed to one member and 400 consecutive
    # draws returned `no_eligible_arm`. Exempting that shape would read the incident's own artifact happily with
    # an empty candidate set, which is the defect wearing the fix's clothes.
    if "candidates" not in d:
        raise ValueError(
            "this policy was written by a version that recorded rules with no 'candidates' key, so it cannot be "
            "loaded: the candidate set used to be derived from 'rules' and 'default', which is exactly the "
            "omission CONTRACT C6 exists to end -- falling back to it here would make the same candidate "
            "invisible again through a different door. Recompile it: the artifact is not the source, and "
            "re-deriving it from the ledger is cheaper than trusting an incomplete set")
    rules = []
    for r in d.get("rules", []):
        if "guards" not in r:
            raise ValueError(
                "this policy was written by a version that recorded guards only as prose, so it cannot be loaded. "
                "Recompile it: the artifact is not the source, and re-deriving it is cheaper than parsing English")
        rules.append(Rule(guards=tuple(Guard(**g) for g in r["guards"]),
                          assign=tuple(r["assign"]), because=r.get("because", "")))
    return Policy(family=d["family"], rules=tuple(rules), default=tuple(d["default"]),
                  domain=d.get("domain", {}), validated=bool(d.get("validated", False)),
                  note=d.get("note", ""), provenance=d.get("provenance", {}),
                  parameters=d.get("parameters", {}),
                  # Absent in every artifact from before this entry (v0.2.0 and earlier): "" is the true
                  # statement that no digest was ever computed for it, not a guess at what compile_policy would
                  # have produced had this field existed then.
                  policy_digest=d.get("policy_digest", ""),
                  # CONTRACT v0.3.0 C6: absent only when `rules` is also empty (the guard above already refuses
                  # the non-degenerate case); `{}` there is the honest reading of a policy that never named a
                  # ledger-derived candidate set, the same as a hand-built `Policy()`'s own default.
                  candidates=tuple(d["candidates"]))


def parameter(policy: Policy, name: str, supplied: float | None = None) -> float | None:
    """The single reader of a value this policy was compiled under. Nothing else may hold a second copy.

    `supplied=None` reads the artifact and returns whatever it has, absent included. A `supplied` value is
    never substituted for the artifact's: equal, it is handed back; different, both are named and this
    raises, because a reader that could prefer one number over the other is a second home for it, which is
    the defect this entry exists to close. A `name` the artifact never recorded cannot confirm a supplied
    value either, for the same reason -- there is nothing here to confirm it against.
    """
    known = policy.parameters or {}
    if supplied is None:
        return known.get(name)
    if name not in known:
        raise ValueError(f"{supplied!r} was supplied for {name!r}, but this policy's parameters do not carry "
                         f"{name!r}: an artifact that did not record the parameter cannot confirm one")
    compiled = known[name]
    if compiled != supplied:
        raise ValueError(f"{name!r} supplied as {supplied!r} does not match {compiled!r}, the value this "
                         f"policy was compiled under. Refusing rather than preferring either")
    return supplied


def policy_digest(policy: Policy) -> str:
    """A hash of the compiled artifact's own serialisation, truncated the way `policy.registry_version` already
    truncates its hash over the ledger (CONTRACT C2).

    Computed over `as_dict(policy)` with the `policy_digest` key itself excluded first: hashing a field that
    would hold its own hash has no stable answer, and excluding it is what makes this reproducible across a
    compile -> write -> read round trip, whether the `Policy` passed in already carries a stamped digest or
    still carries the `""` an artifact never stamped gets. `compile_policy` calls this once, to stamp the value
    `route_once` later reads back rather than recomputing.
    """
    blob = as_dict(policy)
    blob.pop("policy_digest", None)
    encoded = json.dumps(blob, sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()[:16]


def _compiled(policy: Policy) -> Policy:
    """Stamp `policy_digest` onto a freshly built `Policy` before `compile_policy` returns it.

    One function for every return site in `compile_policy` (there are several, including the refusals), so the
    digest is computed once, over exactly what that call actually produced -- not re-derived separately at each
    site, which is how two of them could end up disagreeing about what the artifact's own hash is.
    """
    return replace(policy, policy_digest=policy_digest(policy))


def _floor_ceiling(tiers: dict, family: str, default: tuple[str, ...], floor: float, alpha: float) -> dict | None:
    """CONTRACT v0.3.0 C5's three numbers for `compile_policy`'s `params`, or `None` when there is no cohort to
    count them from.

    The cohort is the reference's own recorded outcome for `family` -- `default[0]`, since every caller of
    `compile_policy` compiles `default` as the family's declared reference (`cli.cmd_compile` and
    `table.compile_to_file` both key `families` by `family -> reference` and pass that single id straight
    through). This is the same count `table._evidence` already reports as `reference_attempted`; reading it a
    second way here -- say, from `policy.candidates_for`'s membership -- would mean picking one of possibly
    several different `attempted` counts across candidates with no stated rule for which, and `candidates_for`
    carries no counts at all since CONTRACT v0.3.0 C6's own amendment 10 (a bound recorded there is exactly the
    fixed-sample, single-test quantity R1 rejects).
    """
    if not default:
        return None
    ref = tiers.get(default[0])
    if ref is None:
        return None
    n = (ref.outcome(family) or {}).get("attempted")
    if not n:
        return None
    # Imported locally, at call time, for the same reason `candidates_for` is (CONTRACT v0.3.0 C6, above): a
    # module-level import here would close the cycle `accept` -> `record` -> `observe` -> `decide` -> `accept`.
    from .accept import floor_reachable
    _, ceiling, needed = floor_reachable(int(n), floor, alpha)
    return {"ceiling": ceiling, "cohort_size": int(n), "cohort_size_needed": needed}


def compile_policy(family: str, entry: dict, *, reserved_ids: set[str], metered_ids: set[str],
                   default: tuple[str, ...], default_declared_by: str,
                   service_curve: list | None = None, latency_p95_slo_s: float | None = None,
                   max_evidence_age_days: float | None = None, floor: float | None = None,
                   staleness_limit_days: float | None = None,
                   exploration_rate: float | None = None,
                   tiers: "dict[str, Tier] | None" = None,
                   alpha: float = 0.05) -> Policy:
    """Derive the policy from one compiled family entry. Every threshold is a measurement or a named gap.

    `tiers` (CONTRACT v0.3.0 C6): the ledger this family was compiled from, so `policy.candidates_for` can name
    every candidate it records an outcome for -- the replacement for a candidate set built from `rules`/
    `default`, which left a candidate with no rule invisible. `None` (a caller with no ledger to hand over, the
    shape every test that predates this entry uses) reads as `{}`: an honest "no ledger-derived set", not a
    guess at what one would have contained.

    `alpha` (CONTRACT v0.3.0 C5): the same significance level `cli.py`'s `--alpha` already threads into
    `compile_to_file` for the non-inferiority calibration -- reused here, not a second number, because
    `alpha ** (1/n)` is the ceiling a lower confidence bound at that same significance can ever reach. Defaults
    to 0.05 for a caller (every test that predates this entry) with no reason to pass anything else.

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
    # CONTRACT C1: this is the non-inferiority validation status, not SCOPE section 2 admissibility -- named
    # `validated` (Policy.validated) rather than `certified` for exactly that reason.
    validated = entry.get("status") == "assigned"
    prov = {"default_declared_by": default_declared_by}
    # Written once and carried into every return below, including the refusals: the numbers this function was
    # GIVEN, not ones it derives. `staleness_limit_days` and `exploration_rate` are the family's own declaration
    # (config.FamilyDeclaration, amendment 5 and S3) -- threaded through by the caller (cli.cmd_compile) the same
    # way `floor` already is, and never invented here: this function has no ledger to read a family's
    # declaration from, only what its caller hands it.
    params = {"floor": floor, "max_evidence_age_days": max_evidence_age_days,
             "staleness_limit_days": staleness_limit_days, "exploration_rate": exploration_rate}
    # CONTRACT v0.3.0 C5: the ceiling `alpha ** (1/n)` imposes on the declared floor, the cohort size `n` that
    # ceiling was computed from, and the smallest cohort the declared floor would need instead -- `accept.
    # floor_is_reachable`'s one input. Absent from `params` (rather than present as `None`) when there is
    # nothing to count it from: no floor was declared, there is no reference tier in `tiers`, or the reference
    # carries no usable `attempted` count for this family. Computed once, before any branch below, for the
    # same reason `candidates` is: it does not depend on whether THIS compile validated an assignment.
    floor_ceiling = _floor_ceiling(tiers or {}, family, default, floor, alpha) if floor is not None else None
    if floor_ceiling is not None:
        params["floor_ceiling"] = floor_ceiling
    # CONTRACT v0.3.0 C6: computed once, before any branch below, because the ledger's own outcomes do not
    # depend on whether THIS compile validated an assignment -- a candidate not chosen here is exactly the kind
    # of candidate the set exists to keep visible. Imported locally rather than at module scope, to avoid
    # closing an import cycle (`policy` -> `accept` -> `record` -> `observe` -> `decide`).
    from .policy import candidates_for

    # Amendment 8 (C6) needs no fold-back here. `assign_family` can `continue` a tier into its own `excluded`
    # map -- a stated `latency_slo_p95_ms` or `min_completion_probability` guard -- before it ever reaches
    # `ranked`, and a set derived from `ranked` would drop it. `candidates_for` reads each tier's own recorded
    # outcome and never calls `assign_family`, so an excluded tier is in this set for the same reason every
    # other measured tier is. That is the construction the omission cannot occur in, rather than a second pass
    # that puts back what the first pass dropped.
    candidates = candidates_for(tiers or {}, family)
    if not chosen or not validated:
        why = (entry.get("validation") or {}).get("reason") or "no held-out fold supports this assignment"
        return _compiled(Policy(family, (), default, domain={}, validated=False, provenance=prov,
                                parameters=params, candidates=candidates,
                                note=f"no rule: nothing was validated for this family ({why}), so every "
                                     "request takes the declared default"))

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
        return _compiled(Policy(family, (Rule((age, *money), chosen,
                                              "validated, and no candidate in this assignment is reserved, so "
                                              "the choice does not turn on occupancy"),),
                                default, domain={}, validated=True, provenance=prov, parameters=params,
                                candidates=candidates,
                                note="unconditional in occupancy: nothing here is capacity-bound"))

    if len(reserved) > 1:
        # Refused rather than partially guarded. An earlier version guarded the first reserved candidate and
        # recorded the others as "not modelled" -- but the whole assignment still fired and was exported, so the
        # unguarded legs ran with no capacity semantics at all. A degenerate output is a correct output here:
        # refusing to compile is better than emitting an assignment whose occupancy nobody can evaluate.
        return _compiled(Policy(family, (), default, domain={}, validated=False, provenance=prov,
                                parameters=params, candidates=candidates,
                                note=("no rule: this assignment contains reserved candidates "
                                      f"{sorted(reserved)} and only one can be capacity-guarded. One occupancy "
                                      "figure cannot describe several of them, and firing the assignment anyway "
                                      "would run the unguarded legs with no capacity semantics. Compile one "
                                      "reserved candidate per assignment, or give each its own availability and "
                                      "occupancy")))

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
    # bound neither rule fired even though the validated tail applied.
    rules = []
    if tail:
        rules.append(Rule((age, *money, avail, below), chosen,
                          "the reserved candidate is validated and free at the margin while it has capacity, "
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
                          "the reserved candidate is validated for this family and free at the margin while it "
                          "has capacity, so paid-for capacity is used before anything metered is charged"))

    domain = {} if bound is None else {f"inflight:{box}": [0, float("inf")]}
    if max_evidence_age_days is not None:
        domain["evidence_age_days"] = [0, max_evidence_age_days]
    return _compiled(Policy(family, tuple(rules), default, domain=domain, validated=True, provenance=prov,
                            parameters=params, candidates=candidates,
                            note=("the boundary between the reserved candidate and what follows it is the "
                                  "occupancy at which it stops meeting the declared latency constraint. That is "
                                  "the only derived threshold here, and it is "
                                  + ("measured" if bound is not None else "NOT measured yet"))))


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
