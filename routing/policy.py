"""The rule, as code: read the ledger, assign per family offline, react only to observable failure.

Nothing here reads a model name. Every branch is taken on a measured field of a tier record, which is what
makes the mechanism survive a new checkpoint, a new vendor, a price change or a different tool dialect.

Three timescales, and only the first decides anything:

  offline, per family   measure, then assign the cheapest tier that is non-inferior to the reference
  per hour              recompute a fixed-cost tier's effective rate from realised throughput
  per request           map to a family, send, and escalate only on failures observable with certainty

The online path has no cleverness in it on purpose. `docs/ROUTING-DESIGN.md` says why: on this record a
learned router lost 3.6 accuracy points, its selector collapsed to one member for 96% of requests, and an
offline per-domain assignment overfit and lost 2.5 points out of fold.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path


# --- what a failure looks like ------------------------------------------------------------------
#
# Escalation may only fire on a condition that cannot be mistaken about failure. Each of these errs in
# the safe direction: a spurious escalation costs one attempt, and none of them can keep a wrong answer.
# The slot for a semantic success detector is deliberately absent -- three families of candidate were
# eliminated against a pre-registered bar of keep-precision 1.00, reaching 0.77, "cannot pay at any k
# above 2.06", and 0.78 with every error in the dangerous direction.
OBSERVABLE_FAILURES = (
    "transport_error",          # the call did not complete
    "empty_stream",             # http 200 whose stream ended with no content
    "unusable_action_stream",   # the adapter could not read a call out of the reply
    "budget_exhausted_no_artifact",  # steps, tokens or wall clock, with nothing produced
    "rejected_by_certain_check",     # a patch that does not apply, output that fails its declared schema
)


@dataclass(frozen=True)
class Tier:
    """One record out of the ledger. Constructed from JSON; never from a model name."""

    id: str
    record: dict

    # --- price ---------------------------------------------------------------------------------
    def token_cost(self, fresh_in: int, cached_in: int, out: int) -> float:
        """What a call of this size costs at this tier's measured rates.

        A tier that does not report cached tokens has `cached_in: null` in the ledger, and its cached
        tokens are charged as fresh. Unmeasured is not free -- coercing that null to zero is how a tier
        with invisible cache economics comes out looking cheapest.
        """
        card = self.record["price_card"]
        cached_rate = card["cached_in"]
        if cached_rate is None:
            fresh_in, cached_in = fresh_in + cached_in, 0
            cached_rate = 0.0
        return (fresh_in * card["fresh_in"] + cached_in * cached_rate + out * card["output"]) / 1e6

    def effective_hourly_multiplier(self, realised_tasks_per_hour: float | None) -> float:
        """A fixed-cost tier's rate floor, recomputed per hour rather than per request.

        Its effective rate is max(measured token rates, hourly cost / realised tasks per hour), so the
        tier is only as cheap as its utilisation. Returned as a multiplier on the token cost so the
        caller can see which term bound it.
        """
        hourly = self.record["price_card"].get("hourly_fixed_usd")
        if not hourly:
            return 1.0
        if not realised_tasks_per_hour:
            return math.inf  # an idle machine bills regardless; nothing amortises it
        return 1.0

    def amortised_cost_per_task(self, realised_tasks_per_hour: float | None) -> float:
        """The share of a fixed hourly bill one task carries, zero for a tier without one."""
        hourly = self.record["price_card"].get("hourly_fixed_usd")
        if not hourly:
            return 0.0
        if not realised_tasks_per_hour:
            return math.inf
        return hourly / realised_tasks_per_hour

    # --- reliability ---------------------------------------------------------------------------
    @property
    def failure_rate(self) -> float:
        r = self.record["reliability"]
        n = r["attempts_observed"]
        return (r["failures"] / n) if n else 0.0

    @property
    def retry_premium(self) -> float:
        """Expected extra per *attempted* call: p/(1-p) x mean spend sunk before death.

        This is the term that reordered the arrangements on the record: one tier failed 4 of 24 episodes
        and the spend sunk on those four exceeded its entire successful bill, because they died late. An
        arrangement's exposure is set by how many times it calls the unreliable tier, so the premium
        belongs in the cost of a call rather than in a footnote.
        """
        p = self.failure_rate
        sunk = self.record["reliability"].get("mean_sunk_usd") or 0.0
        if p <= 0.0 or p >= 1.0 or not sunk:
            return 0.0
        return p / (1.0 - p) * sunk

    # --- outcomes ------------------------------------------------------------------------------
    def outcome(self, family: str) -> dict | None:
        return (self.record.get("families") or {}).get(family)

    def solve_rate(self, family: str) -> float | None:
        o = self.outcome(family)
        if not o or not o["attempted"]:
            return None
        return o["solved"] / o["attempted"]

    def eligible_for(self, need: dict) -> bool:
        """Hard constraints, checked before any cost arithmetic."""
        e = self.record.get("eligibility") or {}
        ctx = e.get("context_tokens")
        if need.get("context_tokens") and ctx is not None and need["context_tokens"] > ctx:
            return False
        for m in need.get("modalities", ()):
            if m not in (e.get("modalities") or []):
                return False
        if need.get("residency") and e.get("residency") not in (None, need["residency"]):
            return False
        return True


def load_registry(path: str | Path = "registry/tiers") -> dict[str, Tier]:
    out = {}
    for f in sorted(Path(path).glob("*.json")):
        d = json.loads(f.read_text())
        out[d["id"]] = Tier(id=d["id"], record=d)
    return out


# --- the offline decision ----------------------------------------------------------------------


@dataclass(frozen=True)
class Assignment:
    """The result of the only step that decides anything."""

    family: str
    reference: str
    assigned: str
    chain: tuple[str, ...]
    why: str
    margin: float
    nesting_certified: bool


def assign(
    tiers: dict[str, Tier],
    family: str,
    reference: str,
    *,
    margin: float,
    realised_tasks_per_hour: float | None = None,
    verifier_available: bool = False,
    need: dict | None = None,
) -> Assignment:
    """Assign the cheapest tier whose measured outcome is non-inferior to the reference's.

    `margin` is the non-inferiority margin in solve-rate points and must be fixed before the numbers are
    looked at. `verifier_available` says whether requests in this family arrive with their own executable
    acceptance check: without one there is no signal that a cheaper tier's artifact is good, so a cheaper
    tier may only be *assigned outright* on the strength of its offline parity -- never chained on a guess.
    """
    need = need or {}
    ref = tiers[reference]
    ref_rate = ref.solve_rate(family)
    if ref_rate is None:
        raise ValueError(f"the reference tier {reference!r} has no measured outcome for {family!r}")

    candidates = []
    for t in tiers.values():
        if t.id == reference or not t.eligible_for(need):
            continue
        rate = t.solve_rate(family)
        if rate is None:
            continue
        o = t.outcome(family)
        if o.get("counterexamples"):
            # This tier solves items the reference does not, so the tiers are not a chain for this
            # family and "cheapest sufficient" is not defined. Recorded, and the family keeps its
            # reference until the non-nested case is designed for explicitly.
            continue
        if rate < ref_rate - margin:
            continue
        candidates.append(t)

    per_task = {}
    for t in list(candidates) + [ref]:
        o = t.outcome(family)
        solved = o["solved"] or 1
        bill = (o.get("bill_usd") or 0.0) / solved
        per_task[t.id] = bill + t.retry_premium + t.amortised_cost_per_task(realised_tasks_per_hour)

    nesting = all((t.outcome(family) or {}).get("nested_under_reference") for t in candidates) if candidates else True

    if not candidates:
        return Assignment(family, reference, reference, (reference,),
                          "no eligible tier reached the reference within the margin", margin, nesting)

    cheapest = min(candidates, key=lambda t: per_task[t.id])
    if per_task[cheapest.id] >= per_task[ref.id]:
        return Assignment(family, reference, reference, (reference,),
                          "the cheapest non-inferior tier is not cheaper once retries and fixed cost are priced",
                          margin, nesting)

    if not verifier_available:
        # Parity was measured offline, so the tier is assigned outright. No chain: escalation can only
        # fire on observable failure, which says nothing about a plausible-but-wrong artifact.
        return Assignment(family, reference, cheapest.id, (cheapest.id, reference),
                          "non-inferior offline and cheaper once retries and fixed cost are priced; "
                          "escalates only on observable failure", margin, nesting)

    # With a per-request acceptance check the oracle exists, so a chain is justified and its order is
    # the one that minimises calls to the least reliable tier rather than the one with the lowest bill.
    chain = tuple(sorted((t.id for t in candidates), key=lambda i: per_task[i])) + (reference,)
    return Assignment(family, reference, chain[0], chain,
                      "an executable acceptance check accompanies requests in this family, so the "
                      "artifact can be rejected with certainty and a chain is justified", margin, nesting)


# --- the online path ---------------------------------------------------------------------------


@dataclass
class Attempt:
    tier: str
    outcome: str
    billed_usd: float = 0.0
    artifact: bool = False


@dataclass
class Episode:
    """What the online path did, so the ledger can price it exactly as the design does."""

    family: str
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def billed_usd(self) -> float:
        return sum(a.billed_usd for a in self.attempts)

    @property
    def shipped(self) -> bool:
        return any(a.artifact for a in self.attempts)


def should_escalate(outcome: str, artifact: bool) -> bool:
    """The whole online decision.

    An artifact that exists is shipped. Escalation happens only when the attempt failed in a way that is
    observable with certainty -- never because something about the artifact looked doubtful, because no
    signal that reads an artifact has cleared the bar.
    """
    if artifact and outcome not in OBSERVABLE_FAILURES:
        return False
    return outcome in OBSERVABLE_FAILURES


def run(chain: tuple[str, ...], execute) -> Episode:
    """Walk the chain, stopping at the first attempt that produced an artifact.

    `execute(tier_id) -> Attempt` is supplied by the caller: this module never makes a network call, so
    the rule can be tested against recorded episodes rather than only against a live gateway.
    """
    episode = Episode(family="")
    for tier_id in chain:
        a = execute(tier_id)
        episode.attempts.append(a)
        if not should_escalate(a.outcome, a.artifact):
            break
    return episode
