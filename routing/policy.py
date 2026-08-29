"""The rule, as code: compile an assignment offline from the ledger, and keep the online path dumb.

Nothing here reads a model name. Every branch is taken on a measured field of a tier record, which is what
makes the mechanism survive a new checkpoint, a new vendor, a price change or a different tool dialect.

`assign_family` is an **offline compiler**, not something a request calls. With a handful of tiers and about
twenty paired observations per family it should run when the registry changes and emit a table plus the
reasoning behind each entry. The online path is a table lookup, `should_escalate`, a loop guard and a
breaker -- see `compile_table` and `run`.

Two things this module refuses to do, both because the evidence cannot support them:

  * decide from a point estimate. Comparisons are paired and the sample is small, so acceptance is a
    one-sided lower confidence bound on the *paired* difference, and a comparison that cannot be computed
    returns `not certified` rather than a winner.
  * second-guess an artifact. Escalation fires only on failures observable with certainty. Where the
    request carries a check that can reject the artifact, the check's own verdict is one of those; where it
    does not, a produced artifact is shipped.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path


# --- what a failure looks like ------------------------------------------------------------------
#
# Escalation may only fire on a condition that cannot be mistaken about failure. Each errs in the safe
# direction: a spurious escalation costs one attempt, and none of them can keep a wrong answer.
MECHANICAL_FAILURES = (
    "transport_error",               # the call did not complete
    "empty_stream",                  # http 200 whose stream ended with no content
    "unusable_action_stream",        # the adapter could not read a call out of the reply
    "budget_exhausted_no_artifact",  # steps, tokens or wall clock, with nothing produced
    "malformed_artifact",            # the artifact does not parse against its declared schema
)

# A check supplied with the request that *rejected* the artifact. Kept separate from the mechanical list
# because it is only available on requests that carry one, and because it is the only failure class that
# looks at the artifact's content. A check that can reject is not the same thing as a check that can
# certify: "the patch applies" and "the schema validates" are necessary conditions, not proof of a solved
# task, so a check that only passes is not evidence to keep anything.
CHECK_REJECTED = "check_rejected"

OBSERVABLE_FAILURES = MECHANICAL_FAILURES + (CHECK_REJECTED,)


# --- paired statistics --------------------------------------------------------------------------


def paired_difference_lcb(n11: int, n10: int, n01: int, n00: int, alpha: float = 0.05) -> float | None:
    """One-sided lower bound on (candidate rate - reference rate), from the paired 2x2.

    The comparison is paired -- the same items are given to both tiers -- so the marginal rates throw away
    exactly the information that decides it. On twenty items where the candidate solved 14 and the
    reference 20, the point difference is -0.30 but all six discordant pairs favour the reference, and the
    bound is far below that. Reporting -0.30 as the requirement to admit the tier understates it.

    Uses the normal approximation to the paired difference with a continuity-free variance from the
    discordant counts, which is adequate here and returns None when it is not: with no discordant pairs at
    all there is no information about the difference and the honest answer is that nothing was certified.
    """
    n = n11 + n10 + n01 + n00
    if n <= 0:
        return None
    discordant = n10 + n01
    if discordant == 0:
        # Identical outcomes on every item. The difference is zero, and the bound is set by how much a
        # sample this size could hide: rule of three on the discordant rate.
        return -3.0 / n
    diff = (n10 - n01) / n
    var = (n10 + n01 - (n10 - n01) ** 2 / n) / n**2
    if var <= 0:
        return diff
    z = 1.6449 if abs(alpha - 0.05) < 1e-9 else _z_for(alpha)
    return diff - z * math.sqrt(var)


def _z_for(alpha: float) -> float:
    """One-sided normal quantile, good enough for the few alphas a margin table uses."""
    table = {0.10: 1.2816, 0.05: 1.6449, 0.025: 1.9600, 0.01: 2.3263, 0.005: 2.5758}
    for a, z in sorted(table.items()):
        if alpha <= a + 1e-12:
            return z
    return 1.6449


# --- the ledger ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tier:
    """One record out of the ledger. Constructed from JSON; never from a model name."""

    id: str
    record: dict

    def token_cost(self, fresh_in: int, cached_in: int, out: int) -> float:
        """What a call of this size costs at this tier's measured rates.

        A tier whose `cached_in` is null has its cached tokens charged as fresh. Unmeasured is not free --
        coercing that null to zero is how a tier with invisible cache economics comes out cheapest.
        """
        card = self.record["price_card"]
        rate = card["cached_in"]
        if rate is None:
            fresh_in, cached_in, rate = fresh_in + cached_in, 0, 0.0
        return (fresh_in * card["fresh_in"] + cached_in * rate + out * card["output"]) / 1e6

    def amortised_cost_per_task(self, realised_tasks_per_hour: float | None) -> float:
        """The share of a fixed hourly bill one task carries, zero for a tier without one.

        An idle fixed-cost tier costs infinity, which is the switch that keeps a rented machine out of an
        assignment when nothing is keeping it busy.
        """
        hourly = self.record["price_card"].get("hourly_fixed_usd")
        if not hourly:
            return 0.0
        if not realised_tasks_per_hour:
            return math.inf
        return hourly / realised_tasks_per_hour

    @property
    def failure_rate(self) -> float:
        r = self.record["reliability"]
        n = r["attempts_observed"]
        return (r["failures"] / n) if n else 0.0

    @property
    def retry_premium(self) -> float:
        """Expected extra per *attempted* call: p/(1-p) x mean spend sunk before death.

        The accounting boundary matters and is stated in the schema: a family's `bill_usd` covers the items
        that produced a usable episode, and the attempts that died on transport are excluded from it. This
        term prices exactly those excluded attempts, so the two do not overlap. If a future record folds
        transport failures into `bill_usd`, this term has to be dropped for that record rather than added to
        it -- one accounting boundary, not both an observed cost and a modelled surcharge.
        """
        p = self.failure_rate
        sunk = self.record["reliability"].get("mean_sunk_usd") or 0.0
        if p <= 0.0 or p >= 1.0 or not sunk:
            return 0.0
        return p / (1.0 - p) * sunk

    def outcome(self, family: str) -> dict | None:
        return (self.record.get("families") or {}).get(family)

    def paired(self, family: str) -> dict | None:
        """The 2x2 against the family's reference, if this record carries it."""
        o = self.outcome(family) or {}
        p = o.get("paired_vs_reference")
        if not p:
            return None
        return p

    def cohort(self, family: str) -> str | None:
        """Hash of the exact item set this family's outcome was measured on.

        Without it there is no way to know two records were measured on the same items, and every paired
        computation above is illegitimate.
        """
        o = self.outcome(family) or {}
        return o.get("cohort")

    def fresh_as_of(self, today: str, max_age_days: int) -> bool:
        from datetime import date

        try:
            y, m, d = (int(x) for x in self.record["measured_at"].split("-"))
            t = date.fromisoformat(today)
        except Exception:
            return False
        return (t - date(y, m, d)).days <= max_age_days

    def eligible_for(self, need: dict) -> bool:
        """Hard constraints, checked before any arithmetic."""
        e = self.record.get("eligibility") or {}
        ctx = e.get("context_tokens")
        if need.get("context_tokens") and ctx is not None and need["context_tokens"] > ctx:
            return False
        for m in need.get("modalities", ()):
            if m not in (e.get("modalities") or []):
                return False
        if need.get("residency") and e.get("residency") not in (None, need["residency"]):
            return False
        rps = e.get("max_requests_per_second")
        if need.get("requests_per_second") and rps is not None and need["requests_per_second"] > rps:
            return False
        return True


def load_registry(path: str | Path = "registry/tiers") -> dict[str, Tier]:
    out = {}
    for f in sorted(Path(path).glob("*.json")):
        d = json.loads(f.read_text())
        out[d["id"]] = Tier(id=d["id"], record=d)
    return out


def registry_version(tiers: dict[str, Tier]) -> str:
    """A hash of everything the decision was taken from, so a decision can be replayed."""
    blob = json.dumps({k: v.record for k, v in sorted(tiers.items())}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# --- arrangements, which are what is actually bought --------------------------------------------


@dataclass(frozen=True)
class Arrangement:
    """A whole way of serving a family, which is the object being chosen.

    A tier's own numbers cannot price a chain: the chain's cost depends on the probability the next tier is
    reached, on the correlation between the two tiers' outcomes, and on the cost of the second attempt
    conditional on the first having failed. Where a chain's own measurement exists it is used; where it does
    not, the chain is only offered when the request carries a check that can reject the first artifact --
    otherwise a chain is a way of shipping the cheaper tier's mistakes.
    """

    tiers: tuple[str, ...]
    kind: str  # "outright" or "chain"

    @property
    def head(self) -> str:
        return self.tiers[0]


@dataclass(frozen=True)
class Candidate:
    arrangement: Arrangement
    quality_lcb: float | None
    cost_per_request: float
    certified: bool
    note: str


@dataclass(frozen=True)
class Decision:
    """Everything an incident review needs, which `assign_family` already computed."""

    family: str
    reference: str
    chosen: Arrangement
    certified: bool
    ranked: tuple[Candidate, ...]
    registry_version: str
    margin: float
    alpha: float
    why: str


def _cost_per_request(tiers: dict[str, Tier], arr: Arrangement, family: str,
                      realised_tasks_per_hour: float | None) -> float:
    """Expected spend per *incoming request*, not per solved task.

    Per-solve would smuggle a second quality objective in after non-inferiority has already constrained
    quality: an arrangement that solves less looks cheaper per solve while costing the same per request.
    """
    total = 0.0
    reach = 1.0
    for tid in arr.tiers:
        t = tiers[tid]
        o = t.outcome(family) or {}
        n = o.get("attempted") or 0
        if not n:
            return math.inf
        per_request = (o.get("bill_usd") or 0.0) / n
        total += reach * (per_request + t.retry_premium + t.amortised_cost_per_task(realised_tasks_per_hour))
        solved = (o.get("solved") or 0) / n
        reach *= max(0.0, 1.0 - solved)
    return total


def _quality(tiers: dict[str, Tier], arr: Arrangement, family: str, reference: str,
             alpha: float) -> tuple[float | None, str]:
    """Lower bound on this arrangement's solve rate minus the reference's, and why it is what it is."""
    if arr.tiers[-1] == reference:
        # The reference is the last resort, so anything it would have solved is still solved. The only
        # loss is an item the head solved wrongly-but-plausibly, which is why a chain is offered only when
        # a check can reject the head's artifact.
        return 0.0, "the reference is the last stage, so no item it solves is lost"
    head = tiers[arr.head]
    pair = head.paired(family)
    if not pair:
        return None, "no paired 2x2 against the reference is recorded, so nothing can be certified"
    if head.cohort(family) != tiers[reference].cohort(family):
        return None, "the two records were not measured on the same item set"
    lcb = paired_difference_lcb(pair["both"], pair["candidate_only"], pair["reference_only"],
                               pair["neither"], alpha=alpha)
    if lcb is None:
        return None, "the paired bound could not be computed"
    return lcb, f"paired lower bound on the difference is {lcb:+.3f}"


def assign_family(
    tiers: dict[str, Tier],
    family: str,
    reference: str,
    *,
    margin: float,
    alpha: float = 0.05,
    realised_tasks_per_hour: float | None = None,
    request_can_reject: bool = False,
    need: dict | None = None,
    today: str | None = None,
    max_age_days: int = 90,
) -> Decision:
    """Compile one family's assignment. Offline: run it when the registry changes, not per request.

    `margin` is the non-inferiority margin in solve-rate points, fixed before the numbers are looked at.
    Acceptance is `paired lower bound >= -margin`; a comparison that cannot be computed is **not certified**
    and falls back to the reference, and the decision records which of those two happened, because an
    incident review will care whether the reference won or whether nothing was measurable.
    """
    need = need or {}
    today = today or "1970-01-01"
    if reference not in tiers:
        raise ValueError(f"family {family!r} has no reference tier recorded")
    if not (tiers[reference].outcome(family) or {}).get("attempted"):
        raise ValueError(f"the reference tier {reference!r} has no measured outcome for {family!r}")

    ref_only = Arrangement((reference,), "outright")
    arrangements = [ref_only]
    for t in tiers.values():
        if t.id == reference:
            continue
        if not t.eligible_for(need):
            continue
        if not t.fresh_as_of(today, max_age_days):
            continue
        if not (t.outcome(family) or {}).get("attempted"):
            continue
        arrangements.append(Arrangement((t.id,), "outright"))
        if request_can_reject:
            arrangements.append(Arrangement((t.id, reference), "chain"))

    ranked = []
    for arr in arrangements:
        lcb, note = _quality(tiers, arr, family, reference, alpha)
        certified = lcb is not None and lcb >= -margin
        ranked.append(Candidate(arr, lcb, _cost_per_request(tiers, arr, family, realised_tasks_per_hour),
                                certified, note))
    ranked.sort(key=lambda c: (not c.certified, c.cost_per_request))

    best = ranked[0]
    if not best.certified or best.arrangement == ref_only:
        # Three different facts end up here and an incident review will care which one it was: nothing was
        # measurable, something cheaper was measurable and failed the margin, or the reference genuinely was
        # the cheapest thing on offer. Saying "the reference won" for the first two would be a lie.
        cheapest_overall = min(ranked, key=lambda c: c.cost_per_request)
        if best.arrangement == ref_only and cheapest_overall.arrangement == ref_only:
            why = "the reference is also the cheapest arrangement per request"
        elif any(c.quality_lcb is None for c in ranked if c.arrangement != ref_only):
            why = ("nothing could be certified because a comparison was not computable -- an absent paired "
                   "2x2, a different item set, or a stale record; the reference is used by default and not "
                   "because it won")
        else:
            why = (f"a cheaper arrangement exists ({cheapest_overall.arrangement.head}) but failed the "
                   f"margin of {margin:+.2f}; the reference is used because nothing cheaper could be shown "
                   "non-inferior, which is not the same as the reference winning")
        return Decision(family, reference, ref_only, False, tuple(ranked),
                        registry_version(tiers), margin, alpha, why)
    return Decision(family, reference, best.arrangement, True, tuple(ranked),
                    registry_version(tiers), margin, alpha,
                    f"certified within the margin and cheapest per request; {best.note}")


def compile_table(
    tiers: dict[str, Tier],
    families: dict[str, str],
    **kw,
) -> dict[str, dict[str, Decision]]:
    """The whole offline output: per family, one decision for requests that carry a rejecting check and one
    for requests that do not. The online path reads this table and nothing else."""
    out = {}
    for family, reference in families.items():
        out[family] = {
            "can_reject": assign_family(tiers, family, reference, request_can_reject=True, **kw),
            "cannot_reject": assign_family(tiers, family, reference, request_can_reject=False, **kw),
        }
    return out


# --- the online path ----------------------------------------------------------------------------


@dataclass
class Attempt:
    tier: str
    outcome: str
    billed_usd: float = 0.0
    artifact: bool = False


@dataclass
class Episode:
    family: str = ""
    decision_version: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    stopped_because: str = ""

    @property
    def billed_usd(self) -> float:
        return sum(a.billed_usd for a in self.attempts)

    @property
    def shipped(self) -> bool:
        return any(a.artifact and a.outcome not in OBSERVABLE_FAILURES for a in self.attempts)


def should_escalate(outcome: str, artifact: bool) -> bool:
    """The whole online decision.

    An artifact that exists is shipped unless a check rejected it. Nothing here inspects the artifact
    itself: no signal that reads one has cleared the pre-registered bar, so a doubtful-looking artifact is
    still shipped, and the way to change that is to supply a check with the request.
    """
    return outcome in OBSERVABLE_FAILURES


def run(
    chain: tuple[str, ...],
    execute,
    *,
    budget_usd: float | None = None,
    decision_version: str = "",
    family: str = "",
) -> Episode:
    """Walk the chain once, stopping at the first attempt that produced an accepted artifact.

    The chain is consumed, so no tier is attempted twice and an arrangement whose every stage fails
    terminates instead of looping. `execute(tier_id) -> Attempt` is supplied by the caller: this module
    never makes a network call, so the rule can be tested against recorded episodes.
    """
    if len(set(chain)) != len(chain):
        raise ValueError(f"a chain may not repeat a tier: {chain}")
    episode = Episode(family=family, decision_version=decision_version)
    remaining = list(chain)
    while remaining:
        tier_id = remaining.pop(0)
        a = execute(tier_id)
        episode.attempts.append(a)
        if not should_escalate(a.outcome, a.artifact):
            episode.stopped_because = "an artifact was produced and accepted"
            return episode
        if budget_usd is not None and episode.billed_usd >= budget_usd:
            episode.stopped_because = "the per-request budget was spent"
            return episode
    episode.stopped_because = "every stage of the arrangement failed observably"
    return episode
