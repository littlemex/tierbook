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

from tierbook.evidence import EvidenceError
from tierbook.evidence import load as _load_evidence
from tierbook.evidence import paired as _evidence_paired


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


#: The day the legacy summary-only path (`paired_vs_reference`, hand-computed and never checked again)
#: stops being available to a record newly written or re-measured. Set to the day AFTER every record shipped
#: with this change (all stamped `measured_at: "2026-08-30"`): those are grandfathered rather than being
#: retroactively broken by a rule this same change introduces, because the finding this constant closes is
#: about a NEW record finding the legacy path still open (C8), not about rewriting the ledger's own history.
#: Compared as an ISO date string, which is safe because the format is fixed as YYYY-MM-DD throughout.
EVIDENCE_CUTOVER_DATE = "2026-08-31"


def cutover_violation(record: dict) -> str | None:
    """Which family of a record dated on/after `EVIDENCE_CUTOVER_DATE` has no evidence, or None if it may load.

    A record measured before the cutover is never checked here -- this is a sunset for what a NEW record may
    do, not a retroactive rewrite of records that predate the rule. Without it, nothing stops someone writing
    a new record into the legacy path forever, and a comparison recorded only as a hand-written 2x2 can never
    be recovered if it turns out to have been wrong.
    """
    if record.get("measured_at", "") < EVIDENCE_CUTOVER_DATE:
        return None
    for family, outcome in sorted((record.get("families") or {}).items()):
        if not (outcome or {}).get("evidence"):
            return (f"family {family!r} was measured {record.get('measured_at')!r}, on or after the "
                    f"{EVIDENCE_CUTOVER_DATE} evidence cutover, but carries a hand-written summary instead "
                    "of evidence. The legacy summary-only path is closed to records from this date forward.")
    return None


@dataclass(frozen=True)
class Tier:
    """One record out of the ledger. Constructed from JSON; never from a model name."""

    id: str
    record: dict
    ledger_root: str = "."

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

    def evidence(self, family: str) -> "Evidence | None":
        """This family's per-item evidence, re-verified now, or `None` if the family has no evidence.

        A family with no `evidence` key is not an error here -- it may be carrying the legacy summary
        instead, and `paired`/`cohort` fall back to that. Loaded fresh on every call rather than cached on
        the `Tier`, for the same reason `evidence.load` itself never caches: a `Tier` object can outlive the
        file on disk, and a cached `Evidence` is how a mutated artifact would keep being trusted.
        """
        o = self.outcome(family) or {}
        ev = o.get("evidence")
        if not ev:
            return None
        return _load_evidence(ev["path"], ledger_root=self.ledger_root)

    def paired(self, family: str, reference: "Tier | None" = None) -> dict | None:
        """The 2x2 against the family's reference.

        A single `Tier` cannot compute a candidate-vs-reference comparison from its own evidence alone -- a
        2x2 is a statement about two artifacts, not one. So this derives from evidence when THIS record
        carries it AND the caller passes `reference` (the other `Tier`, which also needs evidence for the
        derivation to run): `_quality`, `table._evidence` and `validate.rank_stability` already hold both
        tiers and pass it. `reference` is optional and keyword-compatible with every call site that predates
        it, so `t.paired(family)` alone keeps working exactly as before for a caller that only wants "does
        this record have something recorded" -- it falls back to the hand-written `paired_vs_reference`
        summary when there is no evidence, or when evidence exists but no reference was supplied to derive
        against, and returns `None` when neither is available.

        The returned dict carries `excluded` (see `evidence.Paired`) when it was derived, so a caller can
        surface what the intersection left out rather than silently dropping it (C9). A caller reading only
        `both`/`candidate_only`/`reference_only`/`neither` -- everything that predates this -- is unaffected.
        """
        ev = self.evidence(family)
        if ev is not None:
            if reference is not None:
                ref_ev = reference.evidence(family)
                if ref_ev is not None:
                    p = _evidence_paired(ev, ref_ev)
                    return {"both": p.both, "candidate_only": p.candidate_only,
                            "reference_only": p.reference_only, "neither": p.neither,
                            "excluded": p.excluded}
            # Evidence exists but nothing to derive it against yet. There is deliberately no summary to fall
            # back to here: a family migrated to evidence has had `paired_vs_reference` removed, because
            # keeping both would let the two silently disagree.
            return None
        o = self.outcome(family) or {}
        p = o.get("paired_vs_reference")
        if not p:
            return None
        return p

    def cohort(self, family: str) -> str | None:
        """Hash of the exact item set this family's outcome was measured on.

        Without it there is no way to know two records were measured on the same items, and every paired
        computation above is illegitimate. Derived from `evidence(family)` when present, because a
        hand-written cohort label is exactly how a fold silently reuses another fold's items under a
        different name (C10): renaming a label defeats a string comparison, but cannot change a
        content-addressed hash of the same underlying item set.
        """
        ev = self.evidence(family)
        if ev is not None:
            return ev.cohort
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


# ---------------------------------------------------------------------------------------------------
# What a record is evidence OF, and what it may therefore do.
#
# Three classes, derived from the record's oracle rather than declared separately, so the two cannot
# disagree. The distinction is load-bearing rather than descriptive: this project measured a model's
# opinion about another model's output at keep-precision 0.78 against a bar of 1.00, and separately found
# the strongest tier solving 95 of 115 items while cheaper tiers solved 101 -- so a benchmark scored by
# agreement with the strongest model would have marked the cheaper tiers DOWN on precisely the six to nine
# items where they were right. That is not added noise. It inverts the ranking exactly where the ranking
# decides something.
#
# So: a model-referenced record may be compiled, reported, and read. It may never assign, and may never
# validate anything -- including another model-referenced record, because agreement about agreement
# compounds rather than confirms.
# ---------------------------------------------------------------------------------------------------

EXECUTABLE_CHECK = "executable_check"
HUMAN_LABEL = "human_label"
MODEL_REFERENCE = "model_reference"

#: The classes a held-out fold may belong to for an entry to become `assigned`.
MAY_ASSIGN = (EXECUTABLE_CHECK, HUMAN_LABEL)

_ORACLE_CLASS = {
    "executable_acceptance": EXECUTABLE_CHECK,
    "external_outcome": EXECUTABLE_CHECK,
    "human_label": HUMAN_LABEL,
    "model_generated_reference": MODEL_REFERENCE,
    "model_judge": MODEL_REFERENCE,
}


def evidence_class(record: dict) -> str:
    """Which of the three classes a record's outcomes belong to.

    A record whose oracle is missing or unrecognised is treated as model-referenced. The safe default when
    nobody wrote down what decided an outcome is that it cannot assign: the alternative default silently
    promotes every record written before this field existed.
    """
    oracle = record.get("oracle") or {}
    cls = _ORACLE_CLASS.get(oracle.get("kind"), MODEL_REFERENCE)
    if cls != MODEL_REFERENCE and not oracle.get("independent_of_candidate", False):
        # A check the candidate itself produced is a model-referenced record wearing a shell script. This
        # project has the measurement: tests taken from the candidate's own output passed on 100% of the
        # items it failed to solve, because a model that cannot fix a bug writes a test that agrees with it.
        return MODEL_REFERENCE
    return cls


def may_assign(record: dict) -> bool:
    return evidence_class(record) in MAY_ASSIGN


def comparable(a: dict, b: dict) -> str | None:
    """Whether two records may be compared for non-inferiority at all, and why not when they may not.

    An agreement score of 0.85 sitting inside a 0.15 margin of a solve rate of 0.90 is a type error rather
    than a close call: the two numbers are about different questions and their difference denotes nothing.
    """
    ca, cb = evidence_class(a), evidence_class(b)
    if ca != cb:
        return (f"the two records are different classes of evidence ({ca} and {cb}); their difference is "
                "not a quality comparison, so no margin applies to it")
    ka = ((a.get("claim") or {}).get("kind")) or "correctness"
    kb = ((b.get("claim") or {}).get("kind")) or "correctness"
    if ka != kb:
        return (f"the two records claim different things ({ka} and {kb}); a margin between them would "
                "compare an agreement rate with a solve rate")
    return None


def tautological(candidate: dict, reference_record: dict) -> str | None:
    """Whether a candidate is being scored against a standard it produced.

    A model graded against its own output scores 1.0 by construction. Refused rather than warned about,
    because the resulting number looks like the best result in the table.
    """
    gen = ((reference_record.get("oracle") or {}).get("generator") or {})
    gen_model = gen.get("model")
    if not gen_model:
        return None
    for name in (candidate.get("id"), (candidate.get("serves") or {}).get("model"),
                 (candidate.get("measurement_target") or {}).get("model")):
        if name and name == gen_model:
            return (f"{candidate.get('id')!r} is the model that generated the reference answers, so its "
                    "score against them is 1.0 by construction; this is a tautology, not a measurement")
    return None


def load_registry(path: str | Path = "registry/tiers") -> dict[str, Tier]:
    """Read every tier record under `path`.

    `ledger_root` is set to `path`'s parent -- e.g. `examples/ledger/tiers` gives `examples/ledger` -- because
    that is the directory an evidence artifact's repo-relative path (`examples/ledger/evidence/...`) is
    expected to resolve inside of. A record with no `evidence` field never touches this at all.
    """
    out = {}
    ledger_root = str(Path(path).parent)
    for f in sorted(Path(path).glob("*.json")):
        d = json.loads(f.read_text())
        out[d["id"]] = Tier(id=d["id"], record=d, ledger_root=ledger_root)
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
    latency_ms_per_request: float = float("inf")

    def value_for(self, objective: str) -> float:
        return self.cost_per_request if objective == "cost" else self.latency_ms_per_request


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
    objective: str = "cost"


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


def _family_latency_seconds(o: dict) -> tuple[float | None, int]:
    """Mean seconds a task took on this family, and the concurrency it was measured at.

    The concurrency comes back with the number because it changes what the number means. A tier measured at
    concurrency 1 and one measured at concurrency 4 are not comparable as latencies and are not comparable as
    throughputs either, so a caller that wants either has to see both.
    """
    lat = o.get("latency") or {}
    if (lat.get("unit") or "seconds_per_task") != "seconds_per_task":
        return None, 1
    per = lat.get("mean") or lat.get("p50")
    return (float(per) if per else None), int(lat.get("concurrency_when_measured") or 1)


def _latency_per_request(tiers: dict[str, Tier], arr: Arrangement, family: str) -> float:
    """Expected seconds to an accepted answer, which is the same arithmetic as cost in other units.

    Written as a sibling of `_cost_per_request` deliberately. Reliability is not a component of either
    objective; it is the denominator of both. A failed attempt is paid for again -- in dollars when the
    objective is cost and in seconds when it is latency -- so an objective computed per *attempt* would
    reorder the arrangements. Cost was measured doing exactly that here, and seconds have no reason to
    behave differently.

    Read from the family's own record. One tier took 94 seconds a task on one family and 17 on another, so a
    figure borrowed across families is not an approximation, it is a different number.
    """
    total = 0.0
    reach = 1.0
    for tid in arr.tiers:
        t = tiers[tid]
        o = t.outcome(family) or {}
        n = o.get("attempted") or 0
        per, _ = _family_latency_seconds(o)
        if not n or not per:
            return math.inf
        p = t.failure_rate
        attempts = 1.0 / (1.0 - p) if 0.0 < p < 1.0 else 1.0
        total += reach * per * attempts
        reach *= max(0.0, 1.0 - (o.get("solved") or 0) / n)
    return total


def throughput_for(t: Tier, family: str, override: float | None) -> tuple[float | None, str | None]:
    """This family's realised tasks per hour for a fixed-cost tier, or a refusal naming what is missing.

    A fixed hourly bill divided by the wrong family's throughput is how a rented machine came out looking
    more expensive per request than a cheap API here ($0.0317 against $0.0293) when its own family's figure
    made it three times cheaper. So the figure is taken from the record for *this* family, an override is
    accepted, and the absence of both is a named condition rather than a silent infinity.

    Derived as `3600 / mean_seconds * concurrency_when_measured`, which is a **lower** bound whenever the
    recorded concurrency is lower than what the deployment will really run: one sequential worker at 17
    seconds a task sustains 207 tasks an hour, and sixteen of them sustain more. A low throughput produces a
    high amortised share, so this errs towards calling the rented machine expensive -- which is the safe
    direction, since the opposite error is a machine that looks cheap because someone assumed it was busy.

    That is not hypothetical. A figure published from this project's own run divided the hourly bill by a
    throughput obtained by multiplying the observed per-task time by an *assumed* sixteen in flight. The run
    recorded no timestamps, so its realised throughput was never measured, and the assumption was carrying a
    35x headline. Pass an override only when you measured it under load.
    """
    if not t.record["price_card"].get("hourly_fixed_usd"):
        return None, None                                     # per-token tier: no throughput needed
    if override:
        return override, None
    o = t.outcome(family) or {}
    per, concurrency = _family_latency_seconds(o)
    if per:
        return 3600.0 / per * concurrency, None
    return None, (f"{t.id!r} bills by the hour and {family!r} has no latency recorded, so its cost per "
                  "request cannot be computed. It must not be borrowed from another family: the same tier "
                  "ran 94 seconds a task on one family here and 17 on another. Measure this family, or pass "
                  "its throughput explicitly.")


def _quality(tiers: dict[str, Tier], arr: Arrangement, family: str, reference: str,
             alpha: float) -> tuple[float | None, str]:
    """Lower bound on this arrangement's solve rate minus the reference's, and why it is what it is."""
    if arr.tiers[-1] == reference:
        # The reference is the last resort, so anything it would have solved is still solved. The only
        # loss is an item the head solved wrongly-but-plausibly, which is why a chain is offered only when
        # a check can reject the head's artifact.
        return 0.0, "the reference is the last stage, so no item it solves is lost"
    head = tiers[arr.head]
    try:
        pair = head.paired(family, tiers[reference])
    except EvidenceError as e:
        # A manifest mismatch or an empty intersection is a fact about this pair of records, not a crash:
        # it means this arrangement cannot be certified, exactly like the absent-2x2 case just below.
        return None, f"evidence could not be paired against the reference: {e}"
    if not pair:
        return None, "no paired 2x2 against the reference is recorded, so nothing can be certified"
    if head.cohort(family) != tiers[reference].cohort(family):
        return None, "the two records were not measured on the same item set"
    mismatch = comparable(head.record, tiers[reference].record)
    if mismatch:
        return None, mismatch
    tauto = tautological(head.record, tiers[reference].record)
    if tauto:
        return None, tauto
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
    objective: str = "cost",
    latency_slo_p95_ms: float | None = None,
    min_completion_probability: float | None = None,
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

    if objective not in ("cost", "latency"):
        raise ValueError(f"objective must be 'cost' or 'latency', not {objective!r}")
    excluded: dict[str, str] = {}
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
        # Reliability as an independent constraint, not a term folded into the objective. A tier that
        # completes 80% of attempts is cheap per attempt and may still be unusable for traffic that has to
        # finish; that is a requirement its owner states, not a rate the optimiser may trade away.
        if min_completion_probability is not None and (1.0 - t.failure_rate) < min_completion_probability:
            excluded[t.id] = (f"completes {1.0 - t.failure_rate:.3f} of attempts, below the required "
                              f"{min_completion_probability:.3f}")
            continue
        slo = ((t.outcome(family) or {}).get("latency") or {}).get("p95_ms")
        if latency_slo_p95_ms is not None and slo and slo > latency_slo_p95_ms:
            excluded[t.id] = f"p95 of {slo:.0f} ms exceeds the stated SLO of {latency_slo_p95_ms:.0f} ms"
            continue
        arrangements.append(Arrangement((t.id,), "outright"))
        if request_can_reject:
            arrangements.append(Arrangement((t.id, reference), "chain"))

    ranked = []
    for arr in arrangements:
        lcb, note = _quality(tiers, arr, family, reference, alpha)
        certified = lcb is not None and lcb >= -margin
        tph, refusal = throughput_for(tiers[arr.head], family, realised_tasks_per_hour)
        cost = math.inf if refusal else _cost_per_request(tiers, arr, family, tph)
        if refusal:
            note = f"{note}; cost not computed: {refusal}"
        ranked.append(Candidate(arr, lcb, cost, certified, note,
                                _latency_per_request(tiers, arr, family)))
    # One objective, chosen explicitly. Certification comes first in the key either way: the margin is a
    # constraint, so an uncertified arrangement never outranks a certified one however cheap or fast it is.
    ranked.sort(key=lambda c: (not c.certified, c.value_for(objective)))

    best = ranked[0]
    if not best.certified or best.arrangement == ref_only:
        # Three different facts end up here and an incident review will care which one it was: nothing was
        # measurable, something cheaper was measurable and failed the margin, or the reference genuinely was
        # the cheapest thing on offer. Saying "the reference won" for the first two would be a lie.
        cheapest_overall = min(ranked, key=lambda c: c.value_for(objective))
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
        if excluded:
            why = f"{why}. Excluded by constraint: " + "; ".join(f"{k} {v}" for k, v in excluded.items())
        return Decision(family, reference, ref_only, False, tuple(ranked),
                        registry_version(tiers), margin, alpha, why, objective)
    unit = "per request" if objective == "cost" else "to an accepted answer"
    why = f"certified within the margin and lowest {objective} {unit}; {best.note}"
    if excluded:
        why += ". Excluded by constraint: " + "; ".join(f"{k} {v}" for k, v in excluded.items())
    return Decision(family, reference, best.arrangement, True, tuple(ranked),
                    registry_version(tiers), margin, alpha, why, objective)


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
