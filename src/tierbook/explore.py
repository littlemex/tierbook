"""C3: the eligible set to explore into, the draw, and the propensity it produces.

CONTRACT (docs/changes/v0.2.0-scope/CONTRACT.md, C3) fixes three things a review found under-specified in the
design that came before this module: which candidates exploration may reach, what "one draw" means arithmetically,
and what a caller records when nothing was drawn at all.

**Why this is not `record.admissible` with an extra keyword.** `admissible` decides expiry BEFORE comparing the
bound to the floor -- see its own docstring -- so a candidate whose evidence has expired is refused there before
its bound is ever looked at. The ratchet in section 10 locks such a candidate out for good: nothing recomputes its
bound, because nothing routes to it to generate the traffic that would. Reusing `admissible` for exploration could
therefore never reach the exact arm the door exists to reach. `clears_floor` is the same shape with expiry moved
to the far side of the floor comparison and given its own, looser limit -- `staleness_limit_days`, declared per
family (config.FamilyDeclaration, amendment 5) -- rather than the freshness limit every other rule in this project
already answers to.
"""
from __future__ import annotations

import random

from .record import Candidate


def clears_floor(candidate: Candidate, floor: float, *, staleness_limit_days: float | None = None,
                 evidence_age_days: float | None = None) -> tuple[bool, str]:
    """Whether exploration may draw INTO this candidate. Separate from `admissible` -- see the module docstring.

    Order matters and is the contract's own: no bound is checked first (there is nothing to compare), then the
    floor (the requirement exploration exists to respect), and only then staleness (the override this function
    exists to grant). Checking staleness before the floor would report "too stale" for a candidate that also
    fails the floor, which names the wrong reason for refusing it.
    """
    if candidate.bound is None:
        return False, "no_bound"
    if candidate.bound < floor:
        return False, "below_floor"
    if (staleness_limit_days is not None and evidence_age_days is not None
            and evidence_age_days > staleness_limit_days):
        return False, "too_stale_to_explore"
    return True, "eligible"


def eligible(candidates: list, *, floor: float, authorised: bool, latency_feasible: bool | None,
            available: dict, staleness_limit_days: float | None, evidence_age_days: float | None) -> list:
    """The candidate ids exploration may draw into.

    `not_authorised`, `latency_infeasible`, `unavailable` and `not_priced` are NOT overridden -- CONTRACT C3 is
    explicit that a review declined to route paid traffic through a randomiser whose eligible set it could not
    enumerate, so this checks every one of them, in the same order `serve._why_not` already uses (cheapest fact
    first): a candidate that is not serving is excluded before its bound or price are looked at at all. Only
    `clears_floor`'s staleness override reaches past the ratchet; nothing else here does.

    `authorised` and `latency_feasible` are decision-level facts, not per-candidate ones -- the same shape
    `record.admissible` already takes them in, because one decision has one gateway authorisation and one
    latency constraint, not one per candidate it could have assigned.
    """
    out = []
    for c in candidates:
        if available.get(c.id) is False:
            continue
        if not authorised:
            continue
        if latency_feasible is False:
            continue
        if c.cost_usd is None:
            continue
        ok, _why = clears_floor(c, floor, staleness_limit_days=staleness_limit_days,
                                evidence_age_days=evidence_age_days)
        if ok:
            out.append(c.id)
    return out


def draw(deterministic: str, eligible: list, rate: float, rng: random.Random) -> tuple[str, float, str]:
    """The chosen id, its propensity, and the reason exploration did or did not happen.

    Verified against the contract's own worked numbers (C3, and the arithmetic error in the first draft it
    corrects): two arms, rate 0.05, exploration over the one alternative -- 0.95 for the deterministic arm, 0.05
    for the alternative, not 0.975/0.025 (which spreads the rate over EVERY arm including the incumbent, a
    different mechanism) and not 0.95/0.025 (which needs three arms). Three arms, rate 0.05 over two
    alternatives: 0.95, 0.025, 0.025 -- `rate / k` per alternative, `1 - rate` for the deterministic arm.

    `rate == 0` is checked before the eligible set, so a family that declared no rate at all is reported as
    `rate_zero` even when it happens to have no alternative either -- the cheaper, more fundamental fact of the
    two. (The contract states both causes as alternatives of an "or" without ordering them when both hold; this
    is this implementation's resolution, and a place the contract could be read either way.)

    One `rng.random()` call, not one to pick "explore or not" and a second to pick which alternative: a single
    draw split into `k + 1` contiguous bins of width `1 - rate` and `rate / k` is uniform over the same
    distribution and makes a seeded `rng` reproduce one decision, not a sequence whose length depends on which
    branch it took.
    """
    if not (0.0 <= rate < 1.0):
        raise ValueError(f"rate must be in [0, 1), not {rate!r}: a rate of 1 would leave the deterministic arm "
                         "at propensity 0, which record.Decision refuses -- a zero propensity for an arm that "
                         "was chosen is a contradiction")
    if rate == 0.0:
        return deterministic, 1.0, "rate_zero"
    alternatives = [c for c in eligible if c != deterministic]
    if not alternatives:
        return deterministic, 1.0, "no_eligible_arm"
    k = len(alternatives)
    r = rng.random()
    if r >= rate:
        return deterministic, 1.0 - rate, "explored"
    idx = int(r / rate * k)
    if idx >= k:  # a float boundary landing exactly on r == rate's edge; the last bin owns it
        idx = k - 1
    return alternatives[idx], rate / k, "explored"
