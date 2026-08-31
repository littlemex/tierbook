"""Which candidates may be routed to, and which are suppressed -- as evidence, not as a constant in a filter.

A candidate list arrives with more tiers than a router should use. Something has to decide which ones are worth
routing to, and the tempting implementation is to drop whatever loses on average cost and average quality. That
is refused here, for a reason measured on the corpus in this repository.

On knowledge multiple-choice, five of eight tiers were dominated on both averages. Removing them looked
obviously right and was wrong twice over.

**Averages hide the strata.** Cost is a function of token count, so dominance is a relation between cost
*curves*, not between two scalars. Recomputing the frontier per input-length bucket put three of those five
"dominated" tiers back on it, and the best tier on short inputs was not the best tier overall.

**Aggregate dominance is not the same as no routing value.** A tier worse on both averages can still cheaply
solve items the others miss. The self-hosted tier solved 456 of 699 against the cheapest API tier's 582 -- worse
by eighteen points -- and it solved **four items no API tier solved at all**, lifting any-correct from 667 to
671 while lowering the oracle's bill. A filter keyed on averages deletes that.

So suppression is decided on **incremental value to the achievable frontier**, per stratum, with an interval;
it is recorded with the price table and date it was conditioned on; and it has three states rather than two.

`undecided` is the default for anything whose ranking moved between folds, because that happened here: two close
candidates swapped rank between a 20-item and a 115-item fold.

One boundary worth stating because getting it wrong is expensive in the other direction: **suppression removes a
candidate from routing, not from measurement.** Keeping every tier in the complete panel costs about seventeen
dollars per five thousand items, and that seventeen dollars *is* the budget that notices when a price change
un-suppresses a tier. A suppressed tier that stops being measured can never come back.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from tierbook.evidence import EvidenceError
from tierbook.outcomes import OutcomeTable

ACTIVE = "active"
SUPPRESSED = "suppressed"
UNDECIDED = "undecided"


@dataclass(frozen=True)
class Verdict:
    """One candidate's admission status, with everything it was conditioned on."""

    candidate: str
    state: str
    why: str
    incremental_quality: float | None = None      # items only this candidate solved, as a rate
    incremental_quality_ci: tuple[float, float] | None = None
    strata_on_frontier: tuple[str, ...] = ()      # strata where it is not dominated
    conditioned_on: dict = field(default_factory=dict)

    @property
    def may_route(self) -> bool:
        return self.state == ACTIVE

    @property
    def must_keep_measuring(self) -> bool:
        """Always true. Suppression is about routing; the panel keeps every candidate.

        A property rather than a comment because the two decisions get conflated, and the consequence of
        conflating them is that a candidate suppressed at today's prices can never be found to have stopped
        being suppressed.
        """
        return True


def _solved_only_by(table: OutcomeTable, candidate: str, others: list[str],
                    items: list[str]) -> list[str]:
    return [i for i in items
            if (table.cells[i].get(candidate) and table.cells[i][candidate].solved)
            and not any(table.cells[i].get(o) and table.cells[i][o].solved for o in others)]


def _bootstrap_rate(hits: int, n: int, *, draws: int = 2000, seed: int = 7,
                    alpha: float = 0.05) -> tuple[float, float]:
    """Interval for a rate, by resampling items rather than by a formula.

    Resampled because the quantity of interest is a count over a specific item set, and the item set is the
    thing being generalised from. A normal approximation on a count of four out of six hundred and ninety-nine
    would give a symmetric interval crossing zero, which is exactly the wrong shape here.
    """
    if n <= 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    flags = [1] * hits + [0] * (n - hits)
    out = sorted(sum(rng.choice(flags) for _ in range(n)) / n for _ in range(draws))
    lo = out[int(draws * alpha / 2)]
    hi = out[int(draws * (1 - alpha / 2)) - 1]
    return (lo, hi)


def audit(table: OutcomeTable, *, stratum_feature: str | None = None, min_stratum: int = 25,
          practical_difference: float = 0.005, conditioned_on: dict | None = None,
          fold_ranks: list[list[str]] | None = None, rank_tolerance: int = 1) -> dict[str, Verdict]:
    """Decide each candidate's admission status on this table.

    `practical_difference` is the incremental quality below which a candidate is not worth routing to, stated by
    the owner rather than defaulted to zero -- because with enough items every candidate solves *something*
    uniquely, and "non-zero" is not the same as "worth the operational cost of another endpoint".

    `fold_ranks` is the candidate ordering observed on other folds, if any. A candidate whose rank moved by more
    than `rank_tolerance` places is `undecided` regardless of what this fold says: rank instability between a
    20-item and a 115-item fold is measured in this repository, and the fold that moved was the one that had
    been used to choose.

    The tolerance exists because an exact-position comparison is useless at this width. Run on nine tiers whose
    solve rates differ by fractions of a point, exact matching declared eight of nine unstable and the audit
    stopped saying anything. Adjacent swaps between near-equal candidates are sampling noise; a candidate moving
    two places or more is the signal.
    """
    items = table.items
    tiers = table.tiers
    out: dict[str, Verdict] = {}
    cond = dict(conditioned_on or {})
    cond.setdefault("items", len(items))
    cond.setdefault("suite", table.suite)
    cond.setdefault("manifest_digest", table.manifest_digest)

    strata: dict[str, list[str]] = {}
    if stratum_feature:
        for i in items:
            strata.setdefault(str(table.features.get(i, {}).get(stratum_feature)), []).append(i)
    frontier_by_stratum: dict[str, set[str]] = {}
    for name, subset in strata.items():
        if len(subset) < min_stratum:
            continue
        from tierbook.optimise import single_tier
        rows = table.frontier({t: single_tier(t) for t in tiers}, subset)
        frontier_by_stratum[name] = {r["policy"] for r in rows if r["on_frontier"]}

    unstable: set[str] = set()
    if fold_ranks and len(fold_ranks) > 1:
        for t in tiers:
            positions = [r.index(t) for r in fold_ranks if t in r]
            if positions and max(positions) - min(positions) > rank_tolerance:
                unstable.add(t)

    for t in tiers:
        others = [o for o in tiers if o != t]
        uniq = _solved_only_by(table, t, others, items)
        rate = len(uniq) / len(items) if items else 0.0
        ci = _bootstrap_rate(len(uniq), len(items))
        on = tuple(sorted(n for n, f in frontier_by_stratum.items() if t in f))

        if t in unstable:
            state = UNDECIDED
            why = (f"this candidate's rank moved more than {rank_tolerance} place(s) between folds, so no fold "
                   "decides it. Rank instability between a 20-item and a 115-item fold is measured here, and "
                   "the fold that moved was the one that had been used to choose.")
        elif on:
            state = ACTIVE
            why = (f"not dominated in {len(on)} stratum/strata ({', '.join(on)}), so an average that dominates "
                   "it is aggregating over a boundary it is on the right side of. Three tiers dominated on "
                   "aggregate here returned to the frontier once input length was stratified.")
        elif ci[0] > practical_difference:
            state = ACTIVE
            why = (f"solves {len(uniq)} items nothing else solves ({rate:.4f}, lower bound {ci[0]:.4f} above "
                   f"the stated practical difference {practical_difference}). Dominated on averages and still "
                   "worth routing to: the self-hosted tier here is eighteen points worse than the cheapest API "
                   "and solves four items no API tier solves.")
        elif rate > 0:
            state = UNDECIDED
            why = (f"solves {len(uniq)} items uniquely ({rate:.4f}) but the interval {ci} does not clear the "
                   f"stated practical difference of {practical_difference}. Not enough evidence to route to it "
                   "and not enough to write it off.")
        else:
            state = SUPPRESSED
            why = ("dominated in every stratum measured and solves nothing uniquely. Suppressed for this price "
                   "table and this date only -- and still measured, because the panel is what notices when a "
                   "price change reverses this.")
        out[t] = Verdict(candidate=t, state=state, why=why, incremental_quality=rate,
                         incremental_quality_ci=ci, strata_on_frontier=on, conditioned_on=cond)
    return out


def headroom(table: OutcomeTable, policy, *, items: list[str] | None = None,
             draws: int = 2000, seed: int = 7) -> dict:
    """How much of the oracle a policy has not yet captured, with an interval.

    Run **before** building anything that learns, because it bounds what learning could win. If the residual
    interval includes zero there is nothing to learn towards, and that is worth knowing before a GPU is
    started -- which is the cheap end of a mistake this project has made at the expensive end.

    Reported as a residual against the *given* policy rather than against the cheapest tier, because the
    question a router has to answer is not "is there room above the floor" but "is there room above what I
    already have without learning".
    """
    items = items or table.items
    rng = random.Random(seed)
    oracle_flags, policy_flags = [], []
    for i in items:
        row = table.cells[i]
        oracle_flags.append(1 if any(c.solved for c in row.values()) else 0)
        chosen = policy(i, table.features.get(i, {}))
        policy_flags.append(1 if (row.get(chosen) and row[chosen].solved) else 0)
    n = len(items)
    point = (sum(oracle_flags) - sum(policy_flags)) / n if n else 0.0
    draws_out = []
    for _ in range(draws):
        idx = [rng.randrange(n) for _ in range(n)]
        draws_out.append((sum(oracle_flags[k] for k in idx) - sum(policy_flags[k] for k in idx)) / n)
    draws_out.sort()
    lo, hi = draws_out[int(draws * 0.025)], draws_out[int(draws * 0.975) - 1]
    return {
        "items": n,
        "oracle_solved": sum(oracle_flags),
        "policy_solved": sum(policy_flags),
        "residual": round(point, 4),
        "residual_ci": (round(lo, 4), round(hi, 4)),
        "floor_items": n - sum(oracle_flags),
        "reading": (
            "The residual is what a better policy could still win on these items, and the floor is what no "
            "policy can. If the interval includes zero, there is nothing here for a learned router to capture "
            "and the finding is that the existing policy is already at the ceiling of this feature set."
        ),
    }


def escalation_ceiling(table: OutcomeTable, default_tier: str, fallback, *, items: list[str] | None = None,
                       draws: int = 2000, seed: int = 7,
                       default_usd_per_item: float | None = None) -> dict:
    """The best an escalation construction could do: run `default_tier` on everything, escalate when it is wrong.

    For a tier billed by the hour rather than per token. Inside a fixed deployment window that tier's marginal
    cost is zero and its *capacity* is what is scarce, so the question is not "which candidate per item" but
    "which items are worth spending API money on when the box already has an answer". This computes the ceiling
    of that construction by escalating with the recorded outcome as the oracle: no judge can escalate better
    than one that already knows whether the answer is right.

    Run it before building the judge. It is free, and it is the shape of failure this project has already paid
    for at the expensive end -- a construction whose *oracle* does not beat the incumbent cannot be rescued by a
    better classifier.

    Two things it reports that the headline numbers hide, because both decide whether the ceiling is reachable.

    **`protected`** is the set of items the default tier solves and the fallback does not. Those items are the
    whole quality gain, and a real judge earns them only by keeping them -- that is, by being right precisely
    where the stronger tier is wrong. A judge tuned to escalate whenever it is unsure loses them first.

    **`break_even_usd_per_item`** is the amortised price at which the default tier's own bill eats the API
    saving. `default_usd_per_item` is a *parameter with no default* on purpose: the concurrency behind that
    amortisation is a measurement, and an assumed throughput once moved a published figure in this project by a
    factor of six.
    """
    items = items or table.items
    rng = random.Random(seed)
    if any(default_tier not in table.cells[i] for i in items):
        raise EvidenceError(
            f"{default_tier!r} has no observed outcome on every item, so it cannot be the default path. "
            "An escalation construction sends every request through the default tier by construction, and a "
            "ceiling computed on the subset it happens to have been run on is a different experiment."
        )
    default_ok, fallback_ok, escalated, spend = set(), set(), [], 0.0
    unpriced = 0
    for i in items:
        row = table.cells[i]
        if row[default_tier].solved:
            default_ok.add(i)
        choice = fallback(i, table.features.get(i, {}))
        cell = row.get(choice) if choice is not None else None
        if cell is not None and cell.solved:
            fallback_ok.add(i)
        if i not in default_ok:
            escalated.append(i)
            if cell is None or cell.usd is None:
                unpriced += 1
            else:
                spend += cell.usd
    ceiling_ok = default_ok | (fallback_ok & set(escalated))
    n = len(items)
    flags = [(1 if i in ceiling_ok else 0, 1 if i in fallback_ok else 0) for i in items]
    point = sum(a - b for a, b in flags) / n if n else 0.0
    draws_out = []
    for _ in range(draws):
        idx = [rng.randrange(n) for _ in range(n)]
        draws_out.append(sum(flags[k][0] - flags[k][1] for k in idx) / n)
    draws_out.sort()
    lo, hi = draws_out[int(draws * 0.025)], draws_out[int(draws * 0.975) - 1]
    fallback_spend = 0.0
    for i in items:
        choice = fallback(i, table.features.get(i, {}))
        cell = table.cells[i].get(choice) if choice is not None else None
        if cell is not None and cell.usd is not None:
            fallback_spend += cell.usd
    saving = fallback_spend - spend
    out = {
        "items": n,
        "default_tier": default_tier,
        "default_solved": len(default_ok),
        "fallback_solved": len(fallback_ok),
        "ceiling_solved": len(ceiling_ok),
        "escalated": len(escalated),
        "escalation_rate": round(len(escalated) / n, 4) if n else None,
        "protected": sorted(default_ok - fallback_ok),
        "quality_gain": round(point, 4),
        "quality_gain_ci": (round(lo, 4), round(hi, 4)),
        "api_spend_usd": round(spend, 6),
        "fallback_spend_usd": round(fallback_spend, 6),
        "api_saving_usd": round(saving, 6),
        "unpriced_escalations": unpriced,
        "break_even_usd_per_item": (round(saving / n, 6) if n else None),
        "total_usd": None if default_usd_per_item is None else round(spend + default_usd_per_item * n, 6),
        "reading": (
            "Escalation is decided by the recorded outcome, so this is a ceiling and not a policy. The quality "
            "gain interval excluding zero means a judge could win something; the protected set is what it has "
            "to keep to win it, and those are the items where the default tier is right and the stronger "
            "fallback is wrong. `total_usd` is None unless the default tier's amortised bill was passed in, "
            "because the concurrency that decides it is a measurement rather than an assumption."
        ),
    }
    return out
