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

    def token_cost(self, fresh_in: int, cached_in: int, out: int, cache_write: int = 0) -> float:
        """What a call of this size costs at this tier's measured rates.

        Four legs, because that is how many a gateway in front bills: fresh input, a cache read, a cache
        write, and output. A caller that sums three of them reports a total below what it pays, and the leg
        it drops is the one that only appears on the threads long enough to be worth caching.

        A tier whose `cached_in` is null has its cached tokens charged as fresh. Unmeasured is not free --
        coercing that null to zero is how a tier with invisible cache economics comes out cheapest. A null
        `cache_write` is charged at the fresh rate rather than at zero for the same reason; that is a lower
        bound where the provider charges a write premium, and `write_rate_is_a_floor` says so.
        """
        card = self.record["price_card"]
        rate = card["cached_in"]
        if rate is None:
            fresh_in, cached_in, rate = fresh_in + cached_in, 0, 0.0
        write_rate = card.get("cache_write")
        if write_rate is None:
            write_rate = card["fresh_in"]
        return (
            fresh_in * card["fresh_in"]
            + cached_in * rate
            + cache_write * write_rate
            + out * card["output"]
        ) / 1e6

    @property
    def write_rate_is_a_floor(self) -> bool:
        """Whether this tier's cache-write leg is charged at a substitute rate.

        True means the card carries no write rate and `token_cost` used the fresh one, so any total
        involving a cache write is a lower bound on this tier and must be reported as one.
        """
        return self.record["price_card"].get("cache_write") is None

    #: How a reserved candidate's per-request charge relates to its reservation. Declared per family, because a
    #: contract can meter one workload and not another.
    RESERVED_CHARGE_KINDS = ("reservation_only", "reservation_plus_metered")

    def reserved_charge_kind(self, family: str) -> str | None:
        """Whether this reserved candidate also carries a per-request charge, as the record declares it."""
        v = (self.outcome(family) or {}).get("reserved_charge_kind")
        if v is not None and v not in self.RESERVED_CHARGE_KINDS:
            raise ValueError(f"{self.id!r} declares reserved_charge_kind={v!r} for {family!r}; expected one of "
                             f"{self.RESERVED_CHARGE_KINDS}")
        return v

    @property
    def is_reserved(self) -> bool:
        """Whether this candidate's bill is a period reservation rather than a per-request charge.

        The presence of an hourly price is what says so, and it is a policy input: a contract someone signed,
        not something observation supplies.
        """
        return bool(self.record["price_card"].get("hourly_fixed_usd"))

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

#: The classes a held-out fold may belong to for an entry to become `assigned`. A fixed-weight learned metric
#: is included and is defined below, after the reason it is not sorted into either pole.
MAY_ASSIGN = (EXECUTABLE_CHECK, HUMAN_LABEL, "fixed_weight_model_metric")

#: A fixed-weight learned metric is reproducible and is still a model, so it gets its own class rather than
#: being sorted into either pole. It MAY assign -- refusing COMET outright would leave translation with only
#: chrF, which measures surface overlap -- but a record scored that way carries the fact, because a learned
#: metric can be systematically wrong in a way a deterministic one cannot. Measured here: a calibrated
#: synthetic proxy reversed sign against the official metric, so reproducible is not the same as correct.
FIXED_WEIGHT_METRIC = "fixed_weight_model_metric"

MAY_ASSIGN_EXTENDED = (EXECUTABLE_CHECK, HUMAN_LABEL, FIXED_WEIGHT_METRIC)

_ORACLE_CLASS = {
    "executable_acceptance": EXECUTABLE_CHECK,
    "deterministic_metric": EXECUTABLE_CHECK,
    "fixed_weight_model_metric": FIXED_WEIGHT_METRIC,
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
    #: Candidates a stated constraint removed before ranking, and which constraint. Structured as well as
    #: written into `why`, because a reader downstream cannot parse prose: the report has to be able to say
    #: "the box was excluded by the latency SLO" rather than "the box is not on the frontier".
    excluded: tuple = ()
    #: Candidates certified on quality that no cost could be computed for. Separate from `excluded` because
    #: "your SLO removed this" and "nobody could price this" call for different actions.
    unpriced: tuple = ()


def _family_spend(t: Tier, family: str) -> tuple[float | None, str]:
    """What this tier's family cost, and on whose authority. Two authorities, both of them stated.

    **A settled charge wins.** If the gateway authored a dollar figure, that is what the money was.

    **Otherwise: gateway-authored tokens priced at a declared card.** This is a change of position and a
    measurement forced it, though the measurement establishes less than it first appeared to. The governing
    document assumed the gateway quotes every candidate in the objective's unit, so an absent charge was a
    refusal. Then the gateway in front of this deployment was measured: its ledger moved 22,009 units for 22,008
    input plus 1 output token, and 623 for 23 input plus 600 output.

    What that shows is narrower than "it counts tokens": two points fit any two-parameter linear meter exactly,
    and a money ledger denominated in micro-dollars at one rate for both legs would produce the same entries. It
    does show the unit is **1:1 with total tokens for this model and does not distinguish input from output**,
    which is enough for the decision here -- a unit blind to the input/output ratio cannot be converted to
    dollars, because that ratio is where most of a card's structure lives. An attempt to settle it by metering a
    differently priced model was contaminated by concurrent traffic on the same ledger and is not reported.

    So the position stated everywhere below is the narrow one both reviews arrived at independently: **no
    monetary settlement was supplied to this framework.** Not that the gateway meters no money, and not that no
    dollar figure exists -- a gateway can report token usage immediately and settle dollars elsewhere or later,
    and no audit of its quote, invoice or export surfaces has been done. What would settle it is the gateway's
    own unit metadata or an invoice reconciled against the ledger.

    The distinction that keeps this from being the reconstruction the rule forbade: what was forbidden is
    *inventing the quantity*. The quantity here is gateway-authored and settled; the card is a contract someone
    signed, exactly like the reservation price, and applying a stated price to a metered quantity is what every
    invoice does. What must not happen is the label going missing, so the basis travels with the figure and the
    report prints it.

    Absent is never zero. Read as $0.00, a record that simply forgot to state its spend wins a cost objective
    by construction -- forgetting to measure would be the cheapest thing a candidate can do.
    """
    o = t.outcome(family) or {}
    bill = o.get("bill_usd")
    if bill is not None:
        return float(bill), "gateway_bill"
    usd, why = imputed_spend(t, family)
    if usd is not None:
        return usd, "declared_card_on_gateway_tokens"
    return None, (f"{t.id!r} has no settled charge for {family!r} and no priceable token legs either: {why}. "
                  "That is not zero spend, it is unmeasured spend, and treating it as free would make "
                  "forgetting to measure the cheapest thing a candidate can do")


def imputed_spend(t: Tier, family: str) -> tuple[float | None, str]:
    """A family's gateway-metered token legs priced at this tier's declared card.

    Kept as its own function so the basis cannot be lost: a caller that wants the number has to go through the
    name that says what it is. It is not a settled charge -- it omits credits, minimums, rounding, retries and
    price changes -- and everything that consumes it says so.
    """
    tok = (t.outcome(family) or {}).get("tokens") or {}
    if not tok:
        return None, "no observed token legs"
    absent = [k for k in ("fresh_in", "cached_in", "out") if tok.get(k) is None]
    if absent:
        return None, (f"token legs {absent} are absent, and an absent leg is not a zero leg -- the total would "
                      "be below what was used")
    usd = t.token_cost(int(tok["fresh_in"]), int(tok["cached_in"]), int(tok["out"]),
                       int(tok.get("cache_write") or 0))
    return usd, ("imputed from this tier's rate card and its observed token legs. Not a settled charge: it "
                 "omits credits, minimums, rounding, retries and price changes")


def _cost_per_request(tiers: dict[str, Tier], arr: Arrangement, family: str) -> tuple[float, str | None]:
    """Expected **marginal** charge per incoming request, not an average, and not per solved task.

    Per-solve would smuggle a second quality objective in after non-inferiority has already constrained
    quality: an arrangement that solves less looks cheaper per solve while costing the same per request.

    The harder point, and the one two independent reviews reached from different directions: **a candidate
    whose bill is a period reservation has no policy-independent per-request cost, so this must not
    manufacture one.** The earlier version did, as `hourly / realised tasks per hour`, and that figure is
    wrong in three ways at once.

    It is *circular*. Routing more work to the box raises its denominator, which lowers its cost, which
    changes the routing. The compiler evaluated the average at the observation cohort's throughput and then
    ranked as though that were exogenous.

    It is the *wrong quantity for a routing decision*. Given the reservation is kept -- and it is, by explicit
    decision -- the marginal charge of sending one more request to a box below capacity is the FIXED component's
    zero plus whatever the contract also meters. Under `reservation_only` that is nothing, because the bill
    arrives either way; under `reservation_plus_metered` it is not, which is why the kind is declared and read
    rather than the zero being asserted generally. Consuming capacity also has a queueing and option cost, which
    this project's own scope classifies as scheduling utility and never as financial cost -- and which
    `slot_value` prices separately rather than folding into this total.

    And it *inverts the purpose*. At the first real cohort the average came out $0.250665 against a token side
    of $0.038934, purely because one experimenter at concurrency 1 left the machine idle. A router that
    believes the box costs a quarter of a dollar a request sends traffic to metered APIs at real money while
    paid-for capacity sits idle -- raising total spend, which is the opposite of the thing this exists to do.

    So: a reserved candidate contributes its *variable* charge only, which for a self-hosted engine behind no
    meter is nothing. Its reservation is evaluated at the period level by `reservation_verdict`, against the
    charge the traffic it absorbed would have drawn elsewhere. That comparison is the standing question "can
    the box be used" in the only form an operator can act on.

    Two further corrections, both from the reviews and both independent of the accounting argument:

    `retry_premium` is added only where the record says its charge EXCLUDES the attempts that died. That is a
    property of the accounting boundary the record declares, and adding the term to a bill which already
    contains those attempts counts them twice. For a purely reserved arrangement the term is the only nonzero
    quantity here, so getting it wrong would decide box-against-box comparisons on its own.

    Every quantity that enters this total is gateway-authored. Not every one of them is money: the gateway in
    front of this deployment meters tokens rather than dollars, so a declared price card converts them, and the
    basis says which candidates that applies to. What is refused is a candidate whose quantity nobody metered.

    - **A fixed bill is not reach-weighted.** A reservation does not shrink because only a fifth of requests
      reach that stage. Only variable charges are multiplied by `reach`, and placing a reserved tier late in a
      cascade no longer makes it look cheap.
    - **Throughput is not borrowed across tiers.** It used to be computed for the head and applied to every
      tier, so two reserved tiers shared one figure and a reserved tail behind an API head -- which reports no
      throughput at all -- came out infinitely expensive.
    """
    total = 0.0
    reach = 1.0
    reserved, imputed = [], []
    for tid in arr.tiers:
        t = tiers[tid]
        o = t.outcome(family) or {}
        n = o.get("attempted") or 0
        if not n:
            return math.inf, f"{tid!r} attempted nothing on {family!r}"

        if t.is_reserved:
            # Reserved and kept: the FIXED settlement is not a marginal charge, because the period bill arrives
            # whether or not this request uses the machine. Whether there is ALSO a per-request charge is not
            # something to infer -- and inferring it either way is wrong in the other case. A gateway charge on
            # a self-hosted engine is usually that same reservation re-expressed per token, and counting both
            # bills the machine twice; but a minimum-plus-meter contract, egress or an overage is genuinely
            # additional, and dropping it loses real money. So the record declares which, and without the
            # declaration this refuses rather than picking.
            reserved.append(tid)
            kind = t.reserved_charge_kind(family)
            if kind is None:
                return math.inf, (
                    f"{tid!r} is reserved and {family!r} does not declare `reserved_charge_kind`. A gateway "
                    "charge on a reserved candidate is either that reservation re-expressed per token -- in "
                    "which case counting both bills the machine twice -- or a genuinely additional meter, and "
                    "guessing either way is wrong in the other case. Declare `reservation_only` or "
                    f"`reservation_plus_metered` for {family!r}")
            if kind == "reservation_plus_metered":
                variable, why = _family_spend(t, family)
                if variable is None:
                    return math.inf, (f"{tid!r} declares an additional meter for {family!r} but {why}")
                total += reach * variable / n
            total += reach * _retry_term(t, family)
        else:
            spend, basis = _family_spend(t, family)
            if spend is None:
                return math.inf, basis
            if basis != "gateway_bill":
                imputed.append(tid)
            total += reach * (spend / n + _retry_term(t, family))
        solved = (o.get("solved") or 0) / n
        reach *= max(0.0, 1.0 - solved)

    notes = []
    if imputed:
        notes.append(
            f"{', '.join(sorted(imputed))} priced by applying a declared price card to token counts the "
            "gateway metered. The tokens are settled; the dollars are not, because the gateway in front of "
            "this deployment meters in a unit that does not distinguish input from output -- it moved 623 units "
            "for 23 input plus 600 output tokens -- and a unit blind to that ratio cannot be converted to "
            "dollars. Credits, minimums, rounding and price changes are outside this figure")
    if reserved:
        notes.append(
            f"{', '.join(sorted(reserved))} is reserved, so its marginal charge per request is nothing while "
            "it has capacity: the period bill arrives whether or not this request uses it. Its reservation is "
            "judged at the period level, not amortised into a per-request price -- an average would be "
            "circular, since routing to it is what changes the denominator")
    return total, ("; ".join(notes) or None)


def _retry_term(t: Tier, family: str) -> float:
    """The expected charge for attempts that died, or zero when the bill already contains them.

    The schema has a family-level `accounting_boundary`. When it says the charge covers only the attempts that
    produced a usable episode, the dead ones are outside it and this term prices them. When it says otherwise --
    or says nothing, which is the same thing for this purpose -- the term is zero, because a gateway bill
    normally does include what it charged for a failed attempt, and adding a modelled surcharge on top charges
    the same retries twice.
    """
    boundary = (t.outcome(family) or {}).get("accounting_boundary")
    if boundary == "usable_episodes_only":
        return t.retry_premium
    return 0.0


def capacity_note(t: Tier, family: str) -> str:
    """What is known about how much traffic a reserved candidate can absorb, and what is not.

    Separated from cost on purpose. "Can the box take this request" is a capacity question with a scheduling
    answer; "does the box pay" is a period question with a financial one. Collapsing them into a per-request
    price is what produced a figure that answered neither.
    """
    if not t.is_reserved:
        return "not a reserved candidate: its charge is per request and capacity is the provider's problem"
    per, conc = _family_latency_seconds(t.outcome(family) or {})
    if per is None:
        return (f"{t.id!r} is reserved and no latency was recorded for {family!r}, so nothing is known about "
                "how much of this family it can absorb")
    return (f"{t.id!r} served {family!r} at {per:.1f} s/task with {conc} in flight. That is one point on a "
            "service curve, not a saturation figure: throughput at higher concurrency may be higher, flat or "
            "lower, so this bounds nothing on its own. A capacity claim needs probes at several "
            "concurrencies")


def occupancy_at(points: list | None, concurrency: float | None) -> tuple[float | None, str]:
    """Slot-seconds one task consumes at a stated operating point.

    The history of this function is worth keeping, because two plausible answers were both wrong in turn.

    It first used the mean latency the load probe reported at that concurrency. A review objected on Little's
    law: at 64 in flight the probe completed 22,908 tasks an hour, so 6.363 a second, so `64 / 6.363 = 10.06`
    slot-seconds -- against a reported mean of 8.19, a 23 percent gap. The objection was acted on and the
    function switched to Little's law.

    Then the gap was measured rather than argued about, by running the same pool for longer. At 2 rounds Little's
    law read 23 percent above the observed mean; at 16 rounds it read 6.3 percent above (5.435 s against 5.113 s).
    The gap is startup and drain inside the measurement window, and it shrinks with the window. So the mean
    residency was never the wrong *quantity* -- in a closed pool each request holds exactly one slot for its own
    duration, which is what a slot-value denominator wants -- and Little's law over a short window is the figure
    that overstates. What had actually been wrong was borrowing a latency measured at a different concurrency on
    a different request shape.

    So: the observed mean residency is preferred, Little's law is carried as a convergence check, and the gap
    between them is reported because it says whether the window was long enough to mean anything.
    """
    if not points or concurrency is None:
        return None, "no probe point, or no operating point to read it at"
    at = next((pt for pt in points if float(pt.get("concurrency", -1)) == float(concurrency)), None)
    if at is None:
        probed = sorted(int(pt["concurrency"]) for pt in points if pt.get("concurrency") is not None)
        return None, (f"the probe has no point at {int(concurrency)} in flight (it probed {probed}), and "
                      "interpolating capacity across a batching engine's curve is not arithmetic")
    tph = at.get("tasks_per_hour")
    if not tph:
        return None, f"the probe completed no work at {int(concurrency)} in flight, so a slot bought nothing"
    littles = concurrency / (tph / 3600.0)
    observed = at.get("mean_latency_s")
    if observed:
        gap = littles / observed - 1
        return float(observed), (
            f"the mean residency observed at {int(concurrency)} in flight: {observed:.2f} slot-seconds a task. "
            f"In a closed pool one request holds one slot for its own duration, so this is the capacity it "
            f"consumes. Little's law over the same window says {littles:.2f} s, {gap:+.1%} -- that gap is "
            "startup and drain inside the window and it shrinks as the window grows (23% at 2 rounds, 6.3% at "
            "16 on this deployment), so a large gap here means the reading is a transient rather than a rate")
    return littles, (f"by Little's law at {int(concurrency)} in flight, {tph:.1f} tasks/hour: {littles:.2f} "
                     "slot-seconds a task. No mean residency was recorded at that point, so this is the only "
                     "figure available and it reads high by whatever the window's startup and drain were")


def occupancy_per_shape(interleaved: dict | None, label: str) -> tuple[float | None, str]:
    """One shape's occupancy, measured in a mix at a single operating point.

    What the slot-value index actually needs, and the only form of it that is comparable across families: shapes
    measured one at a time sit at different operating points. Measured on this deployment, two shapes at 64 in
    flight came out 9.455 and 0.770 slot-seconds a task -- a factor of 12 -- which is the premise the index rests
    on, confirmed rather than assumed.
    """
    if not interleaved:
        return None, "no interleaved measurement, so no shape has an occupancy at a shared operating point"
    per = (interleaved.get("per_shape") or {}).get(label)
    if not per:
        return None, (f"{label!r} was not in the interleaved run (it carried "
                      f"{sorted((interleaved.get('per_shape') or {}))}), and occupancy measured elsewhere is at "
                      "another operating point")
    v = per.get("slot_seconds_per_task")
    if v is None:
        return None, f"{label!r} completed nothing in the interleaved run"
    gap = interleaved.get("transient_gap")
    return float(v), (f"{v:.3f} slot-seconds a task for {label!r}, measured at "
                      f"{interleaved.get('concurrency')} in flight alongside "
                      f"{sorted(set((interleaved.get('per_shape') or {})) - {label})}"
                      + (f". The window's transient gap was {gap:+.1%}" if gap is not None else ""))


def slot_value(reserved: Tier, family: str, *, alternative: Tier | None,
               seconds_per_task: float | None, alternative_certified: bool | None = None) -> dict:
    """What one second of the reserved candidate's occupancy is worth to this family, and why it may be nothing.

    Below capacity a reservation is free at the margin, so any certified request may take it. Capacity is
    finite, and that leaves a question the marginal price cannot answer: the last free slot spent on a request
    that avoids a tenth of a cent displaces one that would have avoided a dollar. Both reviews raised it and
    neither the cost objective nor the guards addressed it.

    The quantity that does is derivable rather than invented: **the charge this family avoids by using the box,
    divided by the occupancy it consumes to do so.** The numerator is *incremental*, not the alternative's gross
    cost: a reserved candidate declared `reservation_plus_metered` charges for its own traffic, so what is saved
    is the difference. Getting that wrong overstates the saving by exactly the box's own meter, and it is
    positive only when the box is in fact cheaper -- a negative saving is a real answer and is returned as one.
    The denominator is seconds per task, which the service curve measures.

    What this is and is not. It prices the SAVING, not the delay a queued request suffers -- that is a latency
    constraint and belongs where the other constraints are. It is a greedy index, which is exactly optimal when
    slots divide and only near-optimal when they do not. And it is a ratio of two measurements taken at one
    operating point, so it moves when either does; that is why it is emitted with its inputs rather than as a
    number.
    """
    if not reserved.is_reserved:
        return {"usd_per_slot_second": None,
                "reason": f"{reserved.id!r} is not reserved, so its occupancy is not the scarce thing"}
    if alternative is None:
        return {"usd_per_slot_second": None,
                "reason": "no metered alternative for this family, so using the box avoids no charge and there "
                          "is nothing to weigh a slot against. That is not a slot worth nothing; it is a "
                          "comparison that does not exist"}
    if seconds_per_task is None:
        return {"usd_per_slot_second": None,
                "reason": "how much capacity a task consumes at the concurrency in use is unmeasured, so the "
                          "occupancy a saving costs is unknown. `occupancy_at` derives it from the probe"}
    if not (isinstance(seconds_per_task, (int, float)) and math.isfinite(seconds_per_task)
            and seconds_per_task > 0):
        # Zero divides, a negative inverts the ranking, and a NaN propagates silently through a sort.
        return {"usd_per_slot_second": None,
                "reason": f"an occupancy of {seconds_per_task!r} is not a duration a task can consume"}
    # A saving is only a saving if the alternative would have done the job. Passed in rather than inferred from
    # the record: whether two candidates are interchangeable on a family is the compiler's finding, and sniffing
    # for evidence fields here would be a second, weaker answer to a question already answered elsewhere.
    if alternative_certified is not True:
        missing = ("nobody said whether" if alternative_certified is None else "it is not recorded that")
        return {"usd_per_slot_second": None,
                "reason": f"{missing} {alternative.id!r} is non-inferior on {family!r}, so the difference in "
                          "charge is not a saving: it would be paid for by an accuracy change nobody measured. "
                          "This framework's objective is cost AND accuracy"}
    spend, why = _family_spend(alternative, family)
    o = alternative.outcome(family) or {}
    n = o.get("attempted") or 0
    if spend is None or not n:
        return {"usd_per_slot_second": None,
                "reason": f"the alternative {alternative.id!r} has no priceable spend for {family!r}, so the "
                          f"saving is unquantified: {why if spend is None else 'it attempted nothing'}"}
    # What the box itself charges for the same traffic. Zero for `reservation_only`; real for a
    # minimum-plus-meter contract, and subtracting it is the difference between a saving and a gross cost.
    own = 0.0
    kind = reserved.reserved_charge_kind(family)
    if kind is None:
        return {"usd_per_slot_second": None,
                "reason": f"{reserved.id!r} does not declare whether it also charges per request for "
                          f"{family!r}, so what using it SAVES cannot be computed -- only what the alternative "
                          "costs, which is not the same number"}
    if kind == "reservation_plus_metered":
        own_spend, own_why = _family_spend(reserved, family)
        ro = reserved.outcome(family) or {}
        rn = ro.get("attempted") or 0
        if own_spend is None or not rn:
            return {"usd_per_slot_second": None,
                    "reason": f"{reserved.id!r} charges per request for {family!r} but that charge is not "
                              f"priceable: {own_why if own_spend is None else 'it attempted nothing'}. The "
                              "saving is the difference, so it cannot be computed without both sides"}
        # Two means from two cohorts. If they were not measured on the same items in the same numbers, their
        # difference is not a paired saving, and the pairing is checked rather than assumed.
        if rn != n:
            return {"usd_per_slot_second": None,
                    "reason": f"the two sides were measured on different numbers of attempts ({n} for "
                              f"{alternative.id!r}, {rn} for {reserved.id!r}), so their means are not paired and "
                              "the difference is not a saving on the same work"}
        mine, theirs = reserved.cohort(family), alternative.cohort(family)
        if not mine or not theirs or mine != theirs:
            # Equal counts prove equal sizes, not the same items. Two unrelated cohorts of the same size pass a
            # count check and produce a difference between means of different work.
            return {"usd_per_slot_second": None,
                    "reason": f"the two sides carry {'no' if not (mine and theirs) else 'different'} item "
                              f"cohorts for {family!r}, so equal attempt counts do not make their means paired: "
                              "two unrelated cohorts of one size would pass a count check"}
        own = own_spend / rn
    avoided = spend / n - own
    return {
        "usd_per_slot_second": avoided / seconds_per_task,
        "avoided_usd_per_request": round(avoided, 6),
        "alternative_usd_per_request": round(spend / n, 6),
        "reserved_own_usd_per_request": round(own, 6),
        "alternative": alternative.id,
        "seconds_per_task": seconds_per_task,
        "reason": (f"using {reserved.id!r} for {family!r} saves ${avoided:.6f} a request -- ${spend / n:.6f} at "
                   f"{alternative.id!r} less ${own:.6f} the reserved candidate charges for the same traffic -- "
                   f"and occupies it for {seconds_per_task:.2f} s to do so. Both are measurements at one "
                   "operating point, so this moves when either does"),
        "assumes": [
            "the saving is the alternative's charge for the SAME traffic, which holds only where that "
            "candidate was measured on this family",
            "that occupancy is an independent quantity of capacity consumed. On a batching engine it is not: "
            "one request changes another's latency and the batch's efficiency, so this is a heuristic for a "
            "measured stationary mix rather than a property of the engine",
            "occupancy costs what it costs at the concurrency the curve was measured at; the figure changes "
            "with the operating point",
            "a greedy order, which is exactly optimal when slots divide and near-optimal when they do not",
            "nothing here prices the delay a displaced request suffers; that is a latency constraint",
        ],
    }


def break_even_price(reserved: Tier, alternative: Tier, family: str, *, window_hours: float | None,
                     family_share: float | None = None) -> dict:
    """A blended-price threshold at which the two arms cost the same, derived without knowing any price.

    Called a threshold and not a comparison, because that is what it is: one scalar on a locus. The alternative's
    charge has four legs with their own rates, so the true equality is a plane in that space, and this reports
    the point on it where all four are priced alike -- together with every leg, so a reader holding a real
    two-part or four-part card can substitute and solve. A single number is the right summary only at the mix
    that was observed.

    The most useful thing that can be said when the price card is not obtainable, and here it was not: the
    gateway in front of this deployment meters tokens and not money, and the cloud pricing API carries no entry
    for the model the metered arm ran on. Choosing a number would put an invented figure at the centre of the
    comparison.

    So invert the question. The reservation's cost over a stated window is measured. The alternative's token legs
    are gateway-metered. The unknown is one scalar -- the blended price the alternative charges -- and there is
    exactly one value of it at which the two arms cost the same. Above it the reservation is cheaper; below it,
    the alternative. The reader compares that figure against the price they actually pay, which they know and
    this does not.

    Blended at the *observed* input-to-output ratio, because a single price only exists at one mix. The ratio is
    reported so a reader can convert to a two-part card themselves.
    """
    if not reserved.is_reserved:
        return {"usd_per_mtok": None, "reason": f"{reserved.id!r} holds no reservation to break even against"}
    if window_hours is None:
        return {"usd_per_mtok": None,
                "reason": "a reservation has no cost without a stated window, so there is nothing to break "
                          "even against"}
    if window_hours <= 0:
        return {"usd_per_mtok": None,
                "reason": f"a window of {window_hours} hours is not a window; a reservation held for no time "
                          "costs nothing and equalises with everything"}
    tok = (alternative.outcome(family) or {}).get("tokens") or {}
    # All four legs, matching what `total` actually sums. Checking three and summing four let an absent
    # `cache_write` through the guard and deflate the total, which inflates the break-even price -- against the
    # guard's own message that absent is not zero.
    absent = [k for k in ("fresh_in", "cached_in", "cache_write", "out") if tok.get(k) is None]
    if not tok or absent:
        return {"usd_per_mtok": None,
                "reason": (f"the alternative's token legs for {family!r} are absent"
                           if not tok else
                           f"the alternative's token legs for {family!r} are incomplete: {absent} are missing, "
                           "and absent is not zero")
                          + ", so what it would have to charge cannot be computed"}
    share = 1.0 if family_share is None else float(family_share)
    if not 0.0 < share <= 1.0:
        return {"usd_per_mtok": None,
                "reason": f"a family share of {share} is not a share of one reservation"}
    hourly = (reserved.record.get("price_card") or {}).get("hourly_fixed_usd")
    if not hourly:
        return {"usd_per_mtok": None,
                "reason": f"{reserved.id!r} states no hourly reservation price, so there is no bill to break "
                          "even against"}
    bill = hourly * window_hours * share
    # The reservation is not the whole of the reserved arm's cost where the contract also meters. Omitting that
    # understates the break-even by exactly the box's own meter -- the error the sibling function calls the
    # difference between a saving and a gross cost.
    kind = reserved.reserved_charge_kind(family)
    own_meter = 0.0
    if kind is None:
        return {"usd_per_mtok": None,
                "reason": f"{reserved.id!r} does not declare whether it also charges per request for "
                          f"{family!r}, so its own side of the comparison is incomplete"}
    if kind == "reservation_plus_metered":
        own_spend, own_why = _family_spend(reserved, family)
        if own_spend is None:
            return {"usd_per_mtok": None,
                    "reason": f"{reserved.id!r} charges per request for {family!r} and that charge is not "
                              f"priceable: {own_why}"}
        own_meter = float(own_spend)
        bill += own_meter
    total = sum(int(tok.get(k) or 0) for k in ("fresh_in", "cached_in", "cache_write", "out"))
    if total <= 0:
        return {"usd_per_mtok": None, "reason": "the alternative used no tokens, so no price equalises the two"}
    out_tok = int(tok.get("out") or 0)
    return {
        "usd_per_mtok": bill / (total / 1e6),
        "reserved_side_usd": round(bill, 6),
        "reservation_usd": round(bill - own_meter, 6),
        "reserved_own_meter_usd": round(own_meter, 6),
        "alternative_tokens": total,
        "alternative_output_share": round(out_tok / total, 6),
        # Every leg, because output share alone cannot convert this threshold to a card with distinct fresh,
        # cached, cache-write and output rates. With these a reader solves the real equality themselves.
        "alternative_legs": {k: int(tok.get(k) or 0)
                             for k in ("fresh_in", "cached_in", "cache_write", "out")},
        "price_equation": (f"reserved side ${bill:.6f} = "
                           + " + ".join(f"{int(tok.get(k) or 0)}/1e6 * p_{k}"
                                        for k in ("fresh_in", "cached_in", "cache_write", "out"))
                           + ". The scalar below is the solution when every p is equal; substitute a real card "
                             "to solve for whichever leg is unknown"),
        "window_hours": window_hours,
        "family_share": share,
        "reason": (f"the reserved arm cost ${bill:.6f} over {window_hours:.2f} hours, and the alternative used "
                   f"{total:,} tokens on the same work. They cost the same when the alternative charges "
                   f"${bill / (total / 1e6):.4f} per million tokens blended at this cohort's mix "
                   f"({out_tok / total:.1%} output). Above that the reservation is cheaper; below it, the "
                   "alternative. No price was assumed to get here"),
        "assumes": [
            "the two arms did the same work, which the paired item set makes true of the tasks and not of the "
            "token counts: a different model tokenizes differently and takes a different number of turns",
            "one blended price, which exists only at this mix. The equality is really a plane over four leg "
            "rates and this is one point on it; the legs are reported so a real card can be substituted",
            "the window is the window the reservation was actually held for, and the reservation served nothing "
            "else in it unless a family share says otherwise",
        ],
    }


def capacity_priority(reserved: Tier, families: dict, *, alternatives: dict,
                      seconds_per_task: float | None, certified: dict | None = None,
                      interleaved: dict | None = None, shape_for_family: dict | None = None) -> dict:
    """The order families should be admitted to a contended reserved candidate, highest slot value first.

    Emitted as an order rather than applied, because admitting a request is a scheduling act and this project
    decides which candidate, not which request. A family whose slot value cannot be computed is placed last and
    says why -- not because it is worth least, but because nothing here can rank it, and putting it first would
    be ranking it on an absence.

    **An interleaved measurement is preferred over everything else**, and it is the only source that makes the
    families comparable: shapes measured one at a time sit at different operating points, so their capacities
    cannot be divided into savings and ranked. `interleaved` is the output of the mixed-traffic probe and
    `shape_for_family` maps a family to the label it was measured under. Measured on this deployment, two shapes
    at 64 in flight came out 9.455 and 0.770 slot-seconds a task -- a factor of twelve -- so this is not a
    refinement, it is the difference between a ranking and a guess.

    **Failing that, occupancy is per family where it was measured.** The probe's figure describes the shape it
    replayed,
    and a prefill-heavy agent turn does not occupy a batching engine for as long as a short retail turn -- the
    same "throughput is a property of the pair" that the curve's own note makes, one level in. So each family's
    own recorded latency on the reserved candidate is preferred, and the probe's figure is the fallback, labelled
    as borrowed. Using one number for every family silently favours whichever family is in fact slower.
    """
    scored, unranked = [], []
    for family in sorted(families):
        label = (shape_for_family or {}).get(family)
        mixed, _mixed_why = occupancy_per_shape(interleaved, label) if label else (None, "")
        own, conc = _family_latency_seconds(reserved.outcome(family) or {})
        if mixed is not None:
            secs, source = mixed, "interleaved_at_one_operating_point"
            at = (interleaved or {}).get("concurrency")
        elif own is not None:
            secs, source, at = own, "own_measurement", conc
        else:
            secs, source, at = seconds_per_task, "borrowed_from_probe", "the probe's"
        v = slot_value(reserved, family, alternative=alternatives.get(family), seconds_per_task=secs,
                       alternative_certified=(certified or {}).get(family))
        v["occupancy_source"] = source
        v["occupancy_concurrency"] = at
        if v["usd_per_slot_second"] is None:
            unranked.append({"family": family, "reason": v["reason"]})
        else:
            scored.append({"family": family, **v})

    # Comparable only if every denominator came from the same place. One family measured on its own traffic and
    # another borrowing the probe's figure are two different quantities, and labelling the borrowing does not
    # make the ratio between them a ranking: on the first real pair the numbers were $0.089 against $0.025 per
    # slot-second, and the order reverses if the borrowed family in fact occupies the engine for more than about
    # 29 seconds -- which nobody measured. So an incomparable set is returned UNRANKED rather than sorted.
    # Physical, not syntactic. An earlier gate compared label strings, which let two families whose concurrency
    # came back as None match on "None" while 63 and 64 did not match, and -- worse -- waved through the case
    # where EVERY family borrowed one constant denominator. That case carries no occupancy information at all,
    # so the ranking it produces is a ranking by per-request saving wearing occupancy's name, which is the exact
    # failure the borrowing was labelled to avoid. It contains strictly less information than the mixed case the
    # gate refused.
    own_only = [x for x in scored if x["occupancy_source"] == "own_measurement"]
    concs = {x["occupancy_concurrency"] for x in own_only}
    all_borrowed = scored and not own_only
    comparable = (len(scored) <= 1
                  or (len(own_only) == len(scored) and len(concs) == 1 and None not in concs))
    # A negative saving is not a low priority, it is a candidate that should not be admitted at all -- even
    # uncontended. Sorting it to the bottom of a list a scheduler reads would still offer it a slot.
    do_not_admit = [x for x in scored if x["usd_per_slot_second"] < 0]
    indifferent = [x for x in scored if x["usd_per_slot_second"] == 0]
    scored = [x for x in scored if x["usd_per_slot_second"] > 0]
    # Comparability is recomputed over what is left. Judged before the inadmissible families were separated, a
    # single loss-making family with an odd denominator could make the remaining one incomparable with itself.
    # Comparable when every denominator came from one place at one operating point. An interleaved set qualifies
    # by construction, which is the point of measuring that way.
    good = [x for x in scored if x["occupancy_source"] in ("interleaved_at_one_operating_point",
                                                          "own_measurement")]
    concs = {x["occupancy_concurrency"] for x in good}
    sources = {x["occupancy_source"] for x in good}
    all_borrowed = bool(scored) and not good
    comparable = (len(scored) <= 1
                  or (len(good) == len(scored) and len(sources) == 1 and len(concs) == 1
                      and None not in concs))
    if comparable:
        scored.sort(key=lambda x: -x["usd_per_slot_second"])
    return {
        "reserved": reserved.id,
        "comparable": comparable,
        # A partial order, not an operational one: unrankable families are listed separately rather than appended,
        # because appending them to a list a scheduler would read is ranking them on an absence.
        "order": [x["family"] for x in scored] if comparable else [],
        "scored": scored,
        "unranked": unranked,
        "do_not_admit": [{"family": x["family"], "usd_per_slot_second": x["usd_per_slot_second"],
                          "reason": "using the reserved candidate costs more than the alternative for this "
                                    "family, so a slot spent here loses money even when nothing is contended"}
                         for x in do_not_admit],
        # Exactly zero is financial indifference, not a loss. Something else -- latency, reliability, or a
        # deliberate exploration policy -- decides, and calling it a loss would foreclose that.
        "financially_indifferent": [{"family": x["family"],
                                     "reason": "the box and the alternative cost the same for this family, so "
                                               "cost does not decide it: latency, reliability or an exploration "
                                               "policy does"}
                                    for x in indifferent],
        "not_comparable_because": (
            None if comparable else
            ("every family borrowed one constant occupancy figure, so this would rank by per-request saving "
             "with no occupancy information at all -- less than the mixed case would carry"
             if all_borrowed else
             f"occupancy was measured for {len(good)} of {len(scored) + len(do_not_admit)} families, at "
             f"concurrencies {sorted(str(c) for c in concs)}. A saving per second is a ranking only when every "
             "second was measured the same way, at one operating point, on the reserved candidate")),
        "note": ("highest saving per second of occupancy first, when the denominators are comparable. Families "
                 "with no computable slot value are listed apart from the order, not at the end of it: nothing "
                 "here can rank them, which is not the same as their being worth least"),
        "not_wired_into_decide": ("this order is not consulted by `decide`, which assigns per request without "
                                  "seeing other families. Admitting the last free slot is an atomic decision "
                                  "among contenders and needs shared state -- several callers can each observe "
                                  "occupancy below the bound and each be sent to the box"),
    }


def reservation_verdict(t: Tier, family: str, *, window_hours: float | None,
                        counterfactual: Tier | None, settled_period_usd: float | None = None,
                        family_share: float | None = None) -> dict:
    """Whether a kept reservation looks like it paid for itself, and why it usually cannot be said.

    The period-level question the per-request average was standing in for. It is **imputed, not settled**, and
    that is a hard limit rather than a caveat: both sides of the comparison bypass the gateway. The bill from
    `hourly x window` is a rate-card reconstruction of the very kind this project's spend rule forbids, and the
    alternative from another candidate's card is the same imputation one step over. So the verdicts are named
    `imputed_pays` and `imputed_does_not_pay`, and a decisive settled verdict is possible only when the
    gateway's own period bill is supplied.

    `family_share` is the fraction of the reservation this family is answerable for, and it is required as soon
    as anything else uses the box. Without it the whole bill is compared against one family's traffic, which is
    biased towards not-paying and double-counts the reservation if two families' verdicts are ever added up:
    "can the box be used for this family" and "does the reservation pay" are questions at different scopes.

    Everything this comparison assumes is listed in the returned `assumes`, because a categorical verdict from
    a point comparison with no interval is exactly the shape of claim this project has been wrong with before.
    """
    if not t.is_reserved:
        return {"verdict": "not_applicable", "reason": "this candidate is not reserved"}
    hourly = t.record["price_card"]["hourly_fixed_usd"]
    o = t.outcome(family) or {}
    tok = o.get("tokens") or {}

    if settled_period_usd is not None:
        bill, bill_authority = float(settled_period_usd), "gateway_settled_period_bill"
    elif window_hours is None:
        return {"verdict": "undecidable", "reason":
                "no accounting window was stated and no settled bill was supplied. A reservation's cost exists "
                f"only over a window: the card says ${hourly:.6f} an hour and nothing here says for how many"}
    else:
        bill, bill_authority = hourly * window_hours, "rate_card_times_window"

    if family_share is None:
        share_note = ("no family share was given, so the WHOLE reservation is compared against this family's "
                      "traffic. That is right only if this family is the sole user of the box; otherwise it is "
                      "biased towards not-paying and cannot be summed across families")
        share = 1.0
    else:
        share = float(family_share)
        share_note = f"this family is charged {share:.3f} of the reservation, as declared"
    bill *= share

    absent = [k for k in ("fresh_in", "cached_in", "out") if tok.get(k) is None]
    if counterfactual is None or not tok or absent:
        missing = []
        if counterfactual is None:
            missing.append("a candidate to quote the same traffic")
        if not tok:
            missing.append("the token legs the traffic actually used")
        if absent:
            # Silently zeroed by an earlier version, which made a partial leg set look like a small bill.
            missing.append(f"token legs {absent}, which are absent and are not zero")
        return {"verdict": "undecidable", "bill_usd": round(bill, 6), "bill_authority": bill_authority,
                "window_hours": window_hours, "family_share": share, "share_note": share_note,
                "reason": (f"the reservation cost ${bill:.6f} on this reading, but whether that beat the "
                           f"alternative cannot be said without {' and '.join(missing)}. This is not evidence "
                           "that the box is expensive; it is the absence of the comparison")}

    elsewhere = counterfactual.token_cost(int(tok["fresh_in"]), int(tok["cached_in"]), int(tok["out"]),
                                          int(tok.get("cache_write") or 0))
    settled = bill_authority == "gateway_settled_period_bill"
    verdict = "imputed_pays" if bill < elsewhere else "imputed_does_not_pay"
    return {
        "verdict": verdict,
        "bill_usd": round(bill, 6),
        "bill_authority": bill_authority,
        "counterfactual_usd": round(elsewhere, 6),
        "counterfactual_authority": "rate_card_of_" + counterfactual.id,
        "counterfactual_tier": counterfactual.id,
        "window_hours": window_hours,
        "family_share": share,
        "share_note": share_note,
        "reason": (f"on this reading the reservation cost ${bill:.6f} and the traffic it absorbed would have "
                   f"been charged ${elsewhere:.6f} by {counterfactual.id!r}. Imputed on "
                   + ("one" if settled else "both")
                   + " side(s): a rate card is not a settled charge, so this ranks a hypothesis and not money "
                     "that left"),
        "assumes": [
            "the same token legs elsewhere, which holds only for the same model: a different tokenizer counts "
            "differently, and a different model's solve and retry behaviour produces different legs entirely",
            "a warm cache elsewhere, where a candidate that has never served this prefix would be charged the "
            "cached leg as fresh",
            "that the traffic in this record is exactly the traffic the window covers",
            "that the alternative was available, authorised, within capacity and within any latency floor",
            "a point comparison with no interval, on one window, which does not decide renewal under future "
            "demand or prices",
        ],
    }


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
        # Throughput no longer enters the objective at all: a reservation is not amortised into a per-request
        # price, so there is nothing for a tasks-per-hour figure to divide. It is still computed, because a
        # refusal from it is worth reporting -- it says the family has no latency recorded -- but the cost does
        # not depend on it.
        _, throughput_refusal = throughput_for(tiers[arr.head], family, realised_tasks_per_hour)
        cost, basis = _cost_per_request(tiers, arr, family)
        if throughput_refusal:
            note = f"{note}; throughput not computable: {throughput_refusal}"
        if cost == math.inf and basis:
            # Excluded for want of a spend figure rather than for being expensive, and the two must not read
            # the same: one is a measurement, the other is a gap in one.
            note = f"{note}; cost not computed: {basis}"
        elif basis:
            note = f"{note}; {basis}"
        ranked.append(Candidate(arr, lcb, cost, certified, note,
                                _latency_per_request(tiers, arr, family)))
    # One objective, chosen explicitly. Certification comes first in the key either way: the margin is a
    # constraint, so an uncertified arrangement never outranks a certified one however cheap or fast it is.
    ranked.sort(key=lambda c: (not c.certified, c.value_for(objective)))

    # A certified arrangement with an infinite cost sorts ahead of everything uncertified and would then be
    # selected: the sort key puts certification first, and infinity is still a number to `min`. Certified on
    # quality and unpriceable on cost is not a choice a cost objective can make, so it is dropped from
    # contention here rather than at the frontier, which only governs what is displayed.
    unpriceable = [c for c in ranked if c.certified and c.value_for(objective) == math.inf]
    contenders = [c for c in ranked if not (c.certified and c.value_for(objective) == math.inf)] or list(ranked)
    best = contenders[0]
    if unpriceable:
        # Kept apart from `excluded`, which is for constraints an operator stated. "Your SLO removed this" and
        # "nobody could price this" call for different actions, and the report labelled the second as the first.
        unpriced = {c.arrangement.head: f"certified on quality but its {objective} could not be computed, so it "
                                        "cannot be compared against anything"
                    for c in unpriceable}
    else:
        unpriced = {}
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
                        registry_version(tiers), margin, alpha, why, objective,
                        tuple(sorted(excluded.items())), tuple(sorted(unpriced.items())))
    unit = "per request" if objective == "cost" else "to an accepted answer"
    why = f"certified within the margin and lowest {objective} {unit}; {best.note}"
    if excluded:
        why += ". Excluded by constraint: " + "; ".join(f"{k} {v}" for k, v in excluded.items())
    return Decision(family, reference, best.arrangement, True, tuple(ranked),
                    registry_version(tiers), margin, alpha, why, objective,
                    tuple(sorted(excluded.items())), tuple(sorted(unpriced.items())))


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
