"""One deployable router: the cheapest policy that certifies a declared accuracy floor.

Everything else in this package measures. This is the artefact: fit it once against a priced outcome table,
hand it a transport, deploy it. It exists because the pieces that survived -- agreement stopping, a fixed
abandonment depth, selection-valid bounds -- were spread across four modules that each answer a research
question, and a research question cannot go behind an endpoint.

## The claim this object makes, and the one it does not

**It claims: on the fitting table, this is the cheapest policy whose selection-adjusted accuracy lower
bound reaches the floor you asked for, and the same bound survives a second collection.** That is all.

**It does not claim to be the best cost-performance available.** That claim needs a paired comparison
against the best single model with the accuracy difference lower-bounded and the cost upper-bounded, and
the arithmetic says this table cannot support it: the observed accuracy gap is about 1.1 points, the
discordant-pair rate about 8%, and clearing zero under an `alpha/K` correction at K=480 needs roughly
**9,000 items** where we have 571. Measured separately and agreeing: above an 82% floor a single candidate
is as cheap or cheaper than any quorum this pool affords, and shrinking the search from 480 policies to 58
recovers at most +1.0%. So the honest deliverable is a floor-compliant cheapest policy, and on this pool
that policy is frequently one model.

## Rules, each traced to a measurement

**Members are all called, then the answer is escalated if they disagree.** This is the cost model `quorum`
measured, and it matters that all members are paid for on every item: agreement stopping saves the
escalation call, not the member calls. `run` issues the members concurrently, which changes wall-clock and
**not the bill** -- stated because an earlier draft of this module claimed parallelism saved money by
citing a cascade figure that was not this policy.

**The cascade numbers that motivated this were re-measured, and the first version was an oracle.** The
figures "0.39 to 0.70 times the dear model, at higher accuracy" escalated exactly when the cheap model was
*actually wrong*, which is the answer key. Deployable gates do worse on both axes: two cheap candidates
escalating on disagreement cost 0.48 to 0.67 times at 86.5% to 91.4%, against the oracle's 0.39 to 0.48
times at 95.8% to 96.3%. And a single cheap candidate (`terra`, 88.4%) costs 0.22 times, cheaper than every
agreement gate. That is why this module's headline is a floor, not a saving.

**An unparseable answer is not agreement.** Two members that produced nothing have agreed on nothing.
Measured: of 200 malformed cells, the 63 from which an answer could be recovered were graded wrong in every
case, so recovering them moves wrong answers into the set the policy stops on.

**Escalation does not branch.** The correctness matrix has one axis -- a fitted one-dimensional model
reproduces the direction-stability of its first three components, holding 79% of the variance, so the
component separating strong candidates from weak ones is the ladder's own curvature and not a second
ability. One axis is an ordering, so the escalation target is one tier fixed at fit time.

**Abandonment is a fixed depth.** At the decision point every item in that state has the same conditioning
set, so the posterior is one number and the AUC is exactly 0.5000. There is no rule to learn; there is a
depth to choose.

**Nothing learns at runtime.** Learned routers were measured not to beat static assignment or the best
single model, and 21 methods across five benchmarks hit the same wall in the literature.

## What it refuses to do

**It will not build on a point estimate.** `fit` keeps only policies whose *adjusted* bound clears the
floor and takes the cheapest of those; it raises otherwise. Choosing the best of 480 policies on the 571
items that scored them put the winner 6.7 points above what could be certified, and nine of ten floor
recommendations failed the floor they were quoted at.

**It records how many floors were tried.** `fit` raising is common, and the natural response is to lower
the floor and retry. That retry loop is a second search which the `alpha/K` correction does not cover, so
`Certificate.floors_attempted` carries it. A certificate showing many attempts is a certificate whose
nominal coverage is not the real one.

**It does not pretend the correction is complete.** The `alpha/K` adjustment assumes the K policies were
specified in advance. The *rules* here -- agreement stopping, fixed depth, single escalation -- were
themselves selected by reading this same frozen fold across a dozen measurements. That is adaptive data
analysis, and no divisor fixes it. `Certificate.rules_are_fold_derived` says so in the object rather than
in a footnote.

**It does not put unmonitorable quantities in the certificate as guarantees.** `agreement_lift` and
`wrong_stop_rate` are carried with intervals and labelled as fitting-table facts, because after deployment
no answer key arrives and they cannot be tracked.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Literal, Sequence

from tierbook.evidence import UNOBSERVED, EvidenceError
from tierbook.outcomes import Cell, OutcomeTable
from tierbook.quorum import (ItemStopRule, QuorumPolicy, agreement, canonical, check_stopped_answers,
                            enumerate_policies, rule_identity)
from tierbook.reproduce import simultaneous_wilson, wilson

Action = Literal["answer", "call", "abandon"]


@dataclass(frozen=True)
class Decision:
    """What the router wants done next.

    `tiers` is a set, not one name, because the members are called together. An earlier version returned a
    single tier and could not express the rule it was written to implement.
    """

    action: Action
    answer: str | None = None            # set when action == "answer"
    tiers: tuple[str, ...] = ()          # set when action == "call"; call all of them
    #: On `abandon`, the best answer heard even though the router does not stand behind it. A caller has to
    #: return something to a user, and whether an abstention is scored wrong or excluded changes what the
    #: floor means -- so the router hands over the material rather than discarding it.
    fallback: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class Certificate:
    """What can honestly be said about a fitted router. Bounds where bounds exist, labels where they do not."""

    members: tuple[str, ...]
    escalate_to: str
    accuracy_floor: float
    accuracy_point: float
    accuracy_lower: float                 # selection-adjusted; THIS is the claim
    usd_per_item: float
    usd_upper: float                      # cost is also selected on, so it gets an upper bound too
    stop_rate: float
    stop_rate_interval: tuple[float, float]
    #: Fitting-table facts, carried with intervals and NOT guarantees: after deployment no answer key
    #: arrives, so neither can be monitored.
    agreement_lift: float
    wrong_stop_rate: float
    wrong_stop_interval: tuple[float, float]
    considered: int
    items: int
    suite: str
    manifest_digest: str
    abandon_depth: int
    #: How many floors were tried before this one succeeded. Above 1, the nominal coverage is optimistic.
    floors_attempted: int = 1
    #: The rules were chosen by reading the same fold. No divisor corrects for that.
    rules_are_fold_derived: bool = True
    #: Whether items with known-broken answer keys were removed before fitting. Undefined treatment makes
    #: the floor meaningless: one measured fold was 3.85% broken, larger than the differences in dispute.
    broken_keys_removed: bool | None = None
    #: A human-readable NAME for the stop rule `accuracy_lower`/`stop_rate`/every other scored figure above was
    #: computed under. **Display and reports only.** Round 2 and round 3 both tried to use a matching NAME as
    #: proof that a separately-declared callable behaved like the one that was scored, and reviewers found twice
    #: that a name is self-declared and proves nothing -- the actual binding check is `stop_rule` below, compared
    #: by object identity in `Router.__post_init__`, never by this string.
    stop_rule_id: str = "agreement"
    #: The EXACT `quorum.ItemStopRule` callable `accuracy_lower`/`stop_rate`/every other scored figure above was
    #: computed under. `Router.__post_init__` refuses a `Router` whose `rule` is not THIS object (`is`, not `==`
    #: or a name match) -- a `dataclasses.replace(router, rule=other)` swapping in a different callable, however
    #: it is named, is caught here because it literally is a different object.
    stop_rule: ItemStopRule = agreement

    @property
    def certified(self) -> bool:
        return self.accuracy_lower >= self.accuracy_floor

    @property
    def effectively_single(self) -> bool:
        """True when the policy stops on everything, i.e. it is one model wearing a policy's clothes.

        Worth naming: above an 82% floor this is what the search returns on the measured pool, and a
        reader who does not notice will credit a quorum for a single model's numbers.
        """
        return len(self.members) == 1 or self.stop_rate >= 1.0 - 1e-9

    def __str__(self) -> str:
        lines = [
            f"router: {'+'.join(self.members)} -> {self.escalate_to}"
            + ("   [effectively a single model: it stops on everything]"
               if self.effectively_single else ""),
            f"  claim: accuracy at least {self.accuracy_lower:.1%} "
            f"(point {self.accuracy_point:.1%}), floor asked {self.accuracy_floor:.0%}, "
            f"chosen from {self.considered} policies on {self.items} items",
            f"  cost: ${self.usd_per_item:.5f} per item, at most ${self.usd_upper:.5f}",
            f"  stops on {self.stop_rate:.1%} "
            f"[{self.stop_rate_interval[0]:.1%}, {self.stop_rate_interval[1]:.1%}]; "
            f"abandons after {self.abandon_depth} tiers",
            f"  fitting-table only, not monitorable: agreement lift {self.agreement_lift:+.1%}, "
            f"wrong-stop {self.wrong_stop_rate:.1%} "
            f"[{self.wrong_stop_interval[0]:.1%}, {self.wrong_stop_interval[1]:.1%}]",
            f"  fitted on {self.suite} @ {self.manifest_digest}; "
            f"broken keys removed: {self.broken_keys_removed}",
        ]
        if self.floors_attempted > 1:
            lines.append(f"  WARNING: {self.floors_attempted} floors were tried before this one, "
                         f"which is a second search the alpha/K correction does not cover")
        if self.rules_are_fold_derived:
            lines.append("  WARNING: the policy rules were selected by reading this same fold, so the "
                         "correction is a lower bound on the right one (adaptive data analysis)")
        return "\n".join(lines)


@dataclass
class Outcome:
    """One item's journey."""

    answer: str | None
    usd: float
    calls: tuple[str, ...]
    abandoned: bool
    #: Sequential stages, not seconds: seconds belong to the caller's infrastructure and stages are what
    #: the router controls. Members are one stage however many there are.
    stages: int


#: The signature every stop rule `Router.decide` accepts must have: given the certificate, the escalation ladder and
#: what has been heard so far, return what to do next. Round 4 stopped exposing this as an injection point in its
#: own right (see `decide_from_score` below for why); kept as a type name because `Decision`-returning callables
#: with this shape still exist internally, and `StopRule` below is a deprecated alias for any importer who held
#: the pre-round-2 bare name.
RuntimeStopRule = Callable[[Certificate, "tuple[str, ...]", "dict[str, str | None]"], Decision]
StopRule = RuntimeStopRule


def decide_from_score(score: ItemStopRule, certificate: Certificate, ladder: tuple[str, ...],
                      answers: dict[str, str | None]) -> Decision:
    """The ONE way any `quorum.ItemStopRule` becomes a streaming, per-request decision.

    **Why this exists.** Round 2 took a batch scorer and a runtime decider as two SEPARATELY injected callables
    and cross-checked them by a shared `rule_id` string. Round 3 bundled both onto one `Rule` object instead of
    two parameters, but a reviewer found that bundling is not equivalence either: nothing stopped `score` and
    `runtime` on one `Rule` from disagreeing, because they were still two independently-supplied callables, just
    stapled together. There is now exactly ONE callable a caller injects (`score`, `quorum.ItemStopRule`'s own
    shape), and the runtime decision is DERIVED from it generically, so there is nothing left that could diverge.

    **How.** Once every member has answered, `score` is called on a table holding just THIS ONE request as a
    single synthetic item. If `score` stops on it, its selected answer is the decision. If `score` does not stop,
    escalate along `ladder` in the declared order; once the ladder is exhausted with nothing parseable, abandon
    at the fixed depth `certificate.abandon_depth`.

    **`quorum.agreement` through this derivation reproduces `default_stop_rule`'s old, hand-written logic exactly
    -- pinned by `tests/test_router.py::test_decide_from_score_reproduces_default_stop_rule_exactly`,** which runs
    both side by side over every branch the old function had (missing answers, unanimity, a silent member,
    disagreement with an escalation ladder, and exhausting the ladder into abandonment).
    """
    members = certificate.members
    missing = tuple(m for m in members if m not in answers)
    if missing:
        return Decision("call", tiers=missing, reason="the members have not all answered")

    request = "_request"
    table = OutcomeTable(suite="_runtime", manifest_digest="_runtime")
    table.cells[request] = {m: Cell(UNOBSERVED, None, answer=answers[m]) for m in members}
    stopped_answers = score(table, members, [request])
    check_stopped_answers(stopped_answers, [request], score)
    if request in stopped_answers:
        return Decision("answer", answer=stopped_answers[request], reason="the rule selected an answer")

    vals = [answers[m] for m in members]
    parsed = [v for v in vals if v is not None]
    reason = ("a member produced no parseable answer, which is not agreement"
              if len(parsed) < len(vals) else "the members disagreed")

    for tier in ladder:
        if tier not in answers:
            return Decision("call", tiers=(tier,), reason=reason)
        if answers[tier] is not None:
            return Decision("answer", answer=answers[tier], reason=f"escalated to {tier}")

    called = len(members) + len(ladder)
    fallback = parsed[0] if parsed else None
    return Decision("abandon", fallback=fallback,
                    reason=(f"{called} tiers produced nothing parseable; abandoning at the fixed "
                            f"depth of {certificate.abandon_depth}"))


def default_stop_rule(certificate: Certificate, ladder: tuple[str, ...],
                      answers: dict[str, str | None]) -> Decision:
    """`decide_from_score(quorum.agreement, ...)`, kept under its own name for direct use and for backward
    compatibility. See `decide_from_score` for the derivation and the module docstring for the measurement this
    traces to ("Escalation does not branch")."""
    return decide_from_score(agreement, certificate, ladder, answers)


#: `quorum.agreement` itself, re-exported under this name so `stop_rule is AGREEMENT` is a plain object-identity
#: check with no name comparison anywhere in it -- the check `Certificate.rules_are_fold_derived` and
#: `Router.fit`'s default both use. This is deliberately NOT a wrapper object: round 3's `Rule` bundled `score`
#: with a separately-declared `runtime`, and a reviewer found bundling is not equivalence. `AGREEMENT` names the
#: one function this project actually measured; its runtime behaviour is `decide_from_score(AGREEMENT, ...)`,
#: derived rather than declared, so there is no second callable for it to disagree with.
AGREEMENT = agreement


@dataclass(frozen=True)
class Router:
    """A fitted policy plus the runtime that executes it.

    **Frozen.** Round 2's `Router` was a plain mutable dataclass, so `r.stop_rule = something_else` bypassed
    `__post_init__` entirely -- the exact TB-034 failure with one extra step. Freezing means the only way to get a
    different `rule` on a `Router` is through `__init__`/`dataclasses.replace`, both of which run `__post_init__`.
    """

    certificate: Certificate
    ladder: tuple[str, ...] = ()
    _policy: QuorumPolicy | None = field(default=None, repr=False)
    #: The batch `quorum.ItemStopRule` `certificate` was scored under, and the one `decide()`/`verify()` derive a
    #: decision from generically (see `decide_from_score`). **Declared here rather than fixed in `decide`'s
    #: body**, so a study whose own measurement supports a different stop rule can express it without editing
    #: this class. Defaults to `AGREEMENT`, which keeps every existing caller working while making the default
    #: visibly a default (the same move F141 made for `decide.STATE_VARS`, applied to the rule TB-034 named).
    rule: ItemStopRule = field(default=AGREEMENT, repr=False, compare=False)

    def __post_init__(self) -> None:
        # OBJECT IDENTITY, never a name: round 3's `rule.name == certificate.stop_rule_id` check passed for
        # `Rule(name="agreement", score=agreement, runtime=always_abandon)`, because a name is self-declared and
        # a caller can put ANY name on ANY callable. `certificate.stop_rule` holds the exact object `fit` scored
        # the table with; `is` cannot be fooled by relabelling a different callable to match.
        if self.rule is not self.certificate.stop_rule:
            raise EvidenceError(
                f"this router's rule is not the exact object its certificate was fitted and scored under "
                f"(certificate.stop_rule_id={self.certificate.stop_rule_id!r}, "
                f"accuracy_lower={self.certificate.accuracy_lower:.1%}, and every other scored figure in it "
                f"describe THAT object's behaviour, not necessarily this one's -- a same-named or same-looking "
                f"callable is not the same object). Swapping `rule` without refitting is how a certificate ends "
                f"up asserting an accuracy the rule that actually runs was never measured against (TB-034). Refit "
                f"with `Router.fit(..., stop_rule=your_rule)` instead of constructing or replacing a Router with "
                f"a different `rule` in place")

    # ---------------------------------------------------------------- fitting

    @classmethod
    def fit(cls, table: OutcomeTable, *, candidates: list[str], escalate_to: list[str],
            accuracy_floor: float, alpha: float = 0.05, max_members: int = 3,
            min_stopped: int = 30, abandon_depth: int | None = None,
            prices: dict[str, float] | None = None, items: list[str] | None = None,
            floors_attempted: int = 1, broken_keys_removed: bool | None = None,
            stop_rule: ItemStopRule = AGREEMENT) -> "Router":
        """Keep only policies whose adjusted bound clears the floor, then take the cheapest, or raise.

        `stop_rule` is the ONE callable (`quorum.ItemStopRule`'s shape: given the matrix, the members and the
        items to decide over, return `{item: selected_answer}` for the ones it stops on) both this fit's
        certificate and the returned `Router.decide` are computed from -- `decide()` derives its runtime
        behaviour from this SAME object generically (`decide_from_score`), so there is no second,
        independently-injectable callable that could disagree with what was scored. Round 2 took a batch callable
        and a runtime callable as two SEPARATE arguments and cross-checked them by a `rule_id` string; round 3
        bundled both onto one object instead, which two more reviews found is still not equivalence, since
        nothing forced the two callables on that object to agree either. There being only ONE callable, with the
        runtime derived rather than separately declared, is what actually closes it. Declaring nothing reproduces
        today's behaviour exactly (`AGREEMENT` is `quorum.agreement` itself).
        """
        if not callable(stop_rule):
            raise EvidenceError(
                f"stop_rule={stop_rule!r} is not callable. A stop rule is a `quorum.ItemStopRule`: given the "
                f"matrix, the members and the items to decide over, it returns `{{item: selected_answer}}` for "
                f"the items it stops on. Round 3's `Rule` wrapper (`score=`/`runtime=` on one object) no longer "
                f"exists -- pass the scoring callable itself")
        policies = enumerate_policies(table, candidates=candidates, escalate_to=escalate_to,
                                      max_members=max_members, min_stopped=min_stopped,
                                      prices=prices, items=items, stop_rule=stop_rule)
        ranked = [q for q in canonical(policies) if q.priced]
        considered = max(1, len(ranked))
        # Filter on the bound, then choose on cost. The reverse order -- cheapest by point estimate, then
        # check -- almost never certifies, because a policy that just clears a floor on the point estimate
        # has no margin left to pay the search with. Filtering first also keeps the guarantee: the
        # simultaneous interval holds for all `considered` policies at once, so any subset it defines is
        # safe to choose within, and cost is not in the criterion so choosing the cheapest cannot move the
        # accuracy claim.
        bounds = {id(q): simultaneous_wilson(q.solved, q.items, alpha=alpha,
                                            considered=considered)[0] for q in ranked}
        eligible = [q for q in ranked if bounds[id(q)] >= accuracy_floor]
        if not eligible:
            best_point = max((q.accuracy for q in ranked), default=0.0)
            best_bound = max(bounds.values(), default=0.0)
            raise EvidenceError(
                f"no policy certifies a {accuracy_floor:.0%} floor. Over {considered} ranked policies the "
                f"best point estimate is {best_point:.1%} and the best selection-adjusted lower bound is "
                f"{best_bound:.1%}. Refusing to build at a floor it cannot certify. Lower the floor to "
                f"{best_bound:.1%} or below, widen the pool, or measure more items -- and note that "
                f"lowering the floor and retrying is itself a search this correction does not cover."
            )
        p = min(eligible, key=lambda q: (q.usd_per_item, q.members, q.escalate_to))
        depth = len(p.members) + 1 if abandon_depth is None else abandon_depth
        s_lo, s_hi = wilson(p.stopped, p.items)
        wrong_stopped = p.stopped - p.solved_when_stopped
        w_lo, w_hi = wilson(wrong_stopped, p.items)
        # Cost is chosen on, so it gets an upper bound. The escalation tier is what a stop avoids, so the
        # worst case is the stop rate at its lower confidence limit.
        esc_share = 1.0 - p.stop_rate
        usd_upper = (p.usd_per_item or 0.0)
        if p.usd_per_item and esc_share > 0:
            usd_upper = p.usd_per_item * (1 + (p.stop_rate - s_lo) / max(esc_share, 1e-9) * esc_share)
        cert = Certificate(
            members=p.members, escalate_to=p.escalate_to, accuracy_floor=accuracy_floor,
            accuracy_point=p.accuracy, accuracy_lower=bounds[id(p)],
            usd_per_item=p.usd_per_item or 0.0, usd_upper=usd_upper,
            stop_rate=p.stop_rate, stop_rate_interval=(s_lo, s_hi),
            agreement_lift=p.agreement_lift, wrong_stop_rate=p.wrong_stop_rate,
            wrong_stop_interval=(w_lo, w_hi), considered=considered, items=p.items,
            suite=table.suite, manifest_digest=table.manifest_digest, abandon_depth=depth,
            floors_attempted=floors_attempted, broken_keys_removed=broken_keys_removed,
            stop_rule_id=rule_identity(stop_rule), stop_rule=stop_rule,
            # The rules were chosen by reading this project's own fold ONLY when the rule literally IS the one
            # this project measured -- OBJECT IDENTITY, not a name equal to "agreement". A caller's own callable
            # named or labelled "agreement" is still their own rule, brought from their own study rather than
            # from reading this fold, so the adaptive-data-analysis warning does not apply to it -- the same
            # reasoning `_best_single` already applies for "a single candidate is the absence of a rule".
            rules_are_fold_derived=(stop_rule is AGREEMENT),
        )
        return cls(certificate=cert, ladder=(p.escalate_to,), _policy=p, rule=stop_rule)

    def verify(self, other: OutcomeTable, *, items: list[str] | None = None,
               alpha: float = 0.05) -> tuple[bool, float, float]:
        """Re-check the claim on a second collection. Returns `(holds, point, adjusted bound)`.

        The adjustment reuses the fit's `considered`, because the search happened once. Charging for it
        twice would make the repeat look worse than it is; charging for it not at all would make a policy
        selected on run 1 look freshly measured.

        Re-scores under `self.rule` -- the SAME batch rule the certificate was fitted under -- rather than the
        module's `agreement` default, so a router fitted with an injected rule is re-checked against the rule
        its certificate actually describes.
        """
        from tierbook.quorum import evaluate

        if other.suite != self.certificate.suite:
            raise EvidenceError(
                f"cannot verify a router fitted on {self.certificate.suite!r} against {other.suite!r}")
        p = evaluate(other, self.certificate.members, self.certificate.escalate_to,
                     prices=None, items=items, stop_rule=self.rule)
        low, _ = simultaneous_wilson(p.solved, p.items, alpha=alpha,
                                     considered=self.certificate.considered)
        return (low >= self.certificate.accuracy_floor, p.accuracy, low)

    @classmethod
    def fit_verified(cls, table: OutcomeTable, other: OutcomeTable, *,
                     floors: Sequence[float], verify_items: list[str] | None = None,
                     **kw) -> "Router":
        """Fit at the highest floor that certifies on BOTH collections, and record how many were tried.

        This is the constructor to deploy. Floors are tried highest first; the count is written into the
        certificate because trying several is a second search.
        """
        last = "no floors were supplied"
        tried = 0
        for floor in sorted(floors, reverse=True):
            tried += 1
            try:
                r = cls.fit(table, accuracy_floor=floor, floors_attempted=tried, **kw)
            except EvidenceError as exc:
                last = f"{floor:.0%}: {exc}"
                continue
            held, point, low = r.verify(other, items=verify_items, alpha=kw.get("alpha", 0.05))
            if held:
                return r
            last = (f"{floor:.0%}: certified {r.certificate.accuracy_lower:.1%} on the fitting table but "
                    f"only {low:.1%} on the repeat (point {point:.1%})")
        raise EvidenceError(f"no supplied floor certifies on both collections. Last failure -- {last}")

    @classmethod
    def fit_best(cls, table: OutcomeTable, other: OutcomeTable | None = None, *,
                 candidates: list[str], escalate_to: list[str], accuracy_floor: float,
                 alpha: float = 0.05, items: list[str] | None = None,
                 broken_keys_removed: bool | None = None, **kw) -> "Router":
        """The constructor to deploy: cheapest certified policy at ONE floor, single models included.

        Two searches, each paying for its own size. Single candidates are chosen from `len(candidates)`;
        quorums from the full enumeration, which is typically sixty times larger. Lumping them together at
        the quorum's `considered` is what made an earlier version prefer a quorum that a single model beat
        by 71%: the quorum was charged 480 policies' worth of uncertainty and the baseline was charged the
        same, so the baseline looked worse than it is. Charging each family correctly is the whole
        comparison.

        The floor is an input, not something to maximise. An earlier `fit_verified` searched for the highest
        certifiable floor and returned a policy that lost to a single model on cost, because "highest
        floor" and "best value at the floor you need" are different questions.
        """
        rows = list(items if items is not None else table.items)
        best_single = cls._best_single(table, candidates=candidates, items=rows,
                                      accuracy_floor=accuracy_floor, alpha=alpha,
                                      broken_keys_removed=broken_keys_removed)
        try:
            quorum = cls.fit(table, candidates=candidates, escalate_to=escalate_to,
                             accuracy_floor=accuracy_floor, alpha=alpha, items=rows,
                             broken_keys_removed=broken_keys_removed, **kw)
        except EvidenceError as exc:
            if best_single is None:
                raise EvidenceError(
                    f"neither a single candidate nor a quorum certifies a {accuracy_floor:.0%} floor. "
                    f"Quorum search said: {exc}") from exc
            quorum = None

        if quorum is not None and other is not None:
            held, _, low2 = quorum.verify(other, items=rows, alpha=alpha)
            if not held:
                quorum = None
        if quorum is None:
            if best_single is None:
                raise EvidenceError(
                    f"no policy certifies a {accuracy_floor:.0%} floor on both collections")
            return best_single
        if best_single is None:
            return quorum
        # Both certify. Prefer the cheaper, and prefer the single model on a tie: fewer moving parts, and
        # its certificate does not carry the adaptive-rules warning.
        return best_single if best_single.certificate.usd_per_item <= quorum.certificate.usd_per_item \
            else quorum

    @classmethod
    def _best_single(cls, table: OutcomeTable, *, candidates: list[str], items: list[str],
                     accuracy_floor: float, alpha: float,
                     broken_keys_removed: bool | None = None) -> "Router | None":
        """The cheapest single candidate whose own adjusted bound clears the floor, as a Router.

        A single candidate is expressed as a one-member policy that stops on everything, which is what
        `quorum` already means by it, so the runtime needs no special case.
        """
        from tierbook.evidence import UNOBSERVED
        from tierbook.outcomes import Cell

        k = max(1, len(candidates))
        best: tuple[str, float, float, int] | None = None
        for c in candidates:
            cells = [table.cells.get(i, {}).get(c) or Cell(UNOBSERVED, None) for i in items]
            if any(x.state == UNOBSERVED for x in cells):
                continue
            solved = sum(1 for x in cells if x.solved)
            low, _ = simultaneous_wilson(solved, len(cells), alpha=alpha, considered=k)
            if low < accuracy_floor:
                continue
            usd = sum((x.usd or 0.0) for x in cells) / len(cells)
            if best is None or usd < best[2]:
                best = (c, low, usd, solved)
        if best is None:
            return None
        name, low, usd, solved = best
        n = len(items)
        s_lo, s_hi = wilson(n, n)
        cert = Certificate(
            members=(name,), escalate_to=name, accuracy_floor=accuracy_floor,
            accuracy_point=solved / n, accuracy_lower=low, usd_per_item=usd, usd_upper=usd,
            stop_rate=1.0, stop_rate_interval=(s_lo, s_hi),
            agreement_lift=0.0, wrong_stop_rate=1.0 - solved / n,
            wrong_stop_interval=wilson(n - solved, n), considered=k, items=n,
            suite=table.suite, manifest_digest=table.manifest_digest, abandon_depth=1,
            # A single candidate is not a rule chosen by reading the fold; it is the absence of one.
            rules_are_fold_derived=False, broken_keys_removed=broken_keys_removed,
        )
        return cls(certificate=cert, ladder=(), _policy=None)

    # ---------------------------------------------------------------- runtime

    def decide(self, answers: dict[str, str | None]) -> Decision:
        """Given what has been heard, say what to do next. Pure, so a log can be replayed through it.

        Derives the decision from `self.rule` generically via `decide_from_score` -- see that function for what
        changed and why.
        """
        return decide_from_score(self.rule, self.certificate, self.ladder, answers)

    def run(self, call: Callable[[str], str | None], *,
            cost: Callable[[str], float] | None = None,
            executor: ThreadPoolExecutor | None = None) -> Outcome:
        """Drive `decide` to completion. Members go out together, which buys wall-clock and not money."""
        answers: dict[str, str | None] = {}
        spent = 0.0
        order: list[str] = []
        stages = 0

        def do(tier: str) -> None:
            nonlocal spent
            answers[tier] = call(tier)
            order.append(tier)
            spent += cost(tier) if cost else 0.0

        while True:
            d = self.decide(answers)
            if d.action == "answer":
                return Outcome(d.answer, spent, tuple(order), False, stages)
            if d.action == "abandon":
                return Outcome(d.fallback, spent, tuple(order), True, stages)
            stages += 1
            if len(d.tiers) > 1 and executor is not None:
                list(executor.map(do, d.tiers))
            else:
                for tier in d.tiers:
                    do(tier)

    # ---------------------------------------------------------------- claims

    def compare_to_single(self, table: OutcomeTable, *, candidates: list[str],
                          prices: dict[str, float], items: list[str] | None = None,
                          alpha: float = 0.05) -> dict[str, object]:
        """The comparison that decides whether this router is worth having.

        Against the cheapest single candidate whose OWN adjusted bound clears the same floor. Each family
        pays for its own search: single candidates are chosen from `len(candidates)`, this policy from
        `considered`. Charging the baseline the policy's penalty would manufacture a win.

        Measured on the frozen fold: the router saves 30.7% at a 70% floor, 5.9% at 80%, nothing at 82%,
        and *loses* above that. So this method exists to be run, not to be assumed.
        """
        from tierbook.evidence import UNOBSERVED
        from tierbook.outcomes import Cell

        rows = list(items if items is not None else table.items)
        k_single = max(1, len(candidates))
        floor = self.certificate.accuracy_floor
        best: tuple[str, float, float] | None = None
        for c in candidates:
            cells = [table.cells.get(i, {}).get(c) or Cell(UNOBSERVED, None) for i in rows]
            seen = [x for x in cells if x.state != UNOBSERVED]
            if len(seen) < len(rows):
                continue
            solved = sum(1 for x in seen if x.solved)
            low, _ = simultaneous_wilson(solved, len(seen), alpha=alpha, considered=k_single)
            if low < floor:
                continue
            usd = sum((x.usd or 0.0) for x in seen) / len(seen)
            if best is None or usd < best[2]:
                best = (c, low, usd)
        if best is None:
            return {"floor": floor, "single": None,
                    "verdict": "no single candidate certifies this floor; the router is the only option"}
        name, low, usd = best
        saving = 1 - (self.certificate.usd_per_item / usd) if usd else 0.0
        return {"floor": floor, "single": name, "single_bound": low, "single_usd": usd,
                "router_usd": self.certificate.usd_per_item, "saving": saving,
                "verdict": ("the router is cheaper" if saving > 0 else
                            "a single candidate is as cheap or cheaper -- prefer it")}


def audit_broken_keys(table: OutcomeTable, *, candidates: list[str],
                      items: list[str] | None = None) -> list[str]:
    """Items where every candidate agreed and every candidate was wrong: likely a broken answer key.

    **This is an evaluation-time auditor and cannot be a runtime rule**, because "every candidate was
    wrong" needs the answer key. An earlier draft put an audit flag on the router's runtime path, where the
    condition it could actually see ("everyone agreed") is unreachable under the agreement rule -- the
    policy returns the agreed answer and never escalates -- and would in any case flag the most reliable
    items rather than the broken ones.

    Measured precision on the fold that motivated it: 19 of 19 with no false positives, but only under the
    all-candidates condition; relaxing to eight of nine dropped it to 3 of 9.
    """
    from tierbook.evidence import UNOBSERVED
    from tierbook.outcomes import Cell

    out = []
    for item in (items if items is not None else table.items):
        cells = [table.cells.get(item, {}).get(c) or Cell(UNOBSERVED, None) for c in candidates]
        if any(x.state == UNOBSERVED or x.answer is None for x in cells):
            continue
        if len({x.answer for x in cells}) == 1 and not any(x.solved for x in cells):
            out.append(item)
    return out


def certify_pool(table: OutcomeTable, *, candidates: list[str], escalate_to: list[str],
                 floors: Sequence[float], **kw) -> dict[float, Certificate | str]:
    """A certificate per floor, or the reason it could not be built.

    "Unreachable even on the point estimate" and "reachable but not certifiable" are different facts and
    an operator has to tell them apart, so failures come back as their message rather than as absence.
    """
    out: dict[float, Certificate | str] = {}
    for f in floors:
        try:
            out[f] = Router.fit(table, candidates=candidates, escalate_to=escalate_to,
                                accuracy_floor=f, **kw).certificate
        except EvidenceError as exc:
            out[f] = str(exc)
    return out
