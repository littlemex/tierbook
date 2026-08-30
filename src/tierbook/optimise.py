"""Choosing a policy over an outcome table, and saying honestly whether it beat what it replaced.

A policy here maps a request to an action: send it to one tier, or refuse. Refusing is an action rather than the
absence of one, because if nothing satisfies the constraints its owner stated then refusing is the correct
answer and the optimiser should be able to return it.

Three things this module refuses to do, each because the alternative was measured to mislead in this
repository:

  * **it does not collapse quality and cost into one score.** The exchange rate between a defect and a dollar
    cannot be stated from inside: at $1 a defect a cheap tier ships, at $10,000 no affordable sample can
    certify one. So the output is a set of options nothing else dominates, and the owner picks a quality floor
    and a cost ceiling.
  * **it does not fit and report on the same items.** A twenty-item calibration fold here chose a tier whose
    quality bound was outside the margin on a held-out fold, and the ranking of two close candidates swapped
    between folds. So `fit` takes calibration items and `evaluate` takes held-out ones, and a call that passes
    the same items to both is refused rather than warned about.
  * **it does not report a two-valued verdict.** Passes the stated target, fails it, and *not determined by
    this sample* are three different answers. Reporting the third as a failure is how a small sample gets
    over-read -- which is exactly the error this project made when one twenty-item arm lost and the conclusion
    drawn was that a whole class of approach was out of scope. On the real corpus this is not hypothetical: at a
    margin of 0.02 the interval is [-0.0534, -0.0181] and straddles the target, so a two-valued verdict would
    have called it a defeat.

And one naming rule, because the first version broke it. A verdict names what happened to the **stated
target**, never to quality. A candidate five points worse and inside a ten-point margin has passed the test its
owner set; calling that "better" would be a falsehood about the quality figure printed beside it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from tierbook.evidence import EvidenceError
from tierbook.outcomes import REFUSE, OutcomeTable
from tierbook.policy import paired_difference_lcb

#: The three answers a comparison can have. Named for what they mean about the *stated target*, not about
#: quality: a candidate that is five points worse and inside a ten-point margin has passed the test its owner
#: set, and calling that "better" would be a plain falsehood about the quality figure sitting next to it.
PASSES = "passes_target"
FAILS = "fails_target"
UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class Constraints:
    """What the owner stated. Nothing here has a default that trades quality for money silently."""

    #: Solve rate a policy may not fall below, as an absolute rate on the evaluation fold. `None` means the
    #: owner stated no floor, which is legal and is recorded rather than replaced with a guess.
    min_solve_rate: float | None = None
    #: Non-inferiority margin against the comparison policy, in solve-rate points. Separate from
    #: `min_solve_rate` because "at least this good" and "not much worse than that" are different statements.
    margin: float | None = None
    max_usd_per_answered: float | None = None
    max_refusal_rate: float | None = None
    alpha: float = 0.05

    def unstated(self) -> list[str]:
        """Which constraints the owner did not state, so a report can say what was not bounded.

        An unstated constraint is not a satisfied one. Listing them is how a reader tells "cost was within
        budget" from "nobody set a budget".
        """
        return [n for n, v in (("min_solve_rate", self.min_solve_rate), ("margin", self.margin),
                               ("max_usd_per_answered", self.max_usd_per_answered),
                               ("max_refusal_rate", self.max_refusal_rate)) if v is None]


def bucket_policy(assignment: dict, *, feature: str, default) -> object:
    """A policy that looks one feature up in a table. The simplest thing that is not a single tier.

    Deliberately this dumb. It is the baseline every learned predictor has to beat, and a baseline that is
    itself clever cannot tell you whether the learning was worth it. `default` is what unseen feature values
    get -- and it should be the reference tier, not the cheapest one, because an unseen bucket is one there is
    no evidence about.
    """
    def pick(item_id: str, features: dict):
        return assignment.get(features.get(feature), default)
    return pick


def single_tier(tier: str) -> object:
    def pick(item_id: str, features: dict):
        return tier
    return pick


def fit_bucket_policy(table: OutcomeTable, calibration: list[str], *, feature: str,
                      constraints: Constraints, tiers: list[str] | None = None,
                      default: str | None = None) -> tuple[object, dict]:
    """Choose, per feature bucket, the cheapest tier whose calibration solve rate is within the margin.

    Fitted on `calibration` only. The returned assignment is a draft: it says what the calibration fold
    prefers, and nothing about whether that holds anywhere else. `verdict()` is what decides that.
    """
    priced, unpriced = table.priced_tiers()
    ts = [t for t in (tiers or table.tiers) if t in priced]
    if not ts:
        raise EvidenceError(
            f"no tier has a cost on every item, so no cost comparison is possible. Unpriced: {unpriced}. "
            "An unpriced tier is excluded rather than charged as zero -- treating one as free made it win "
            "every comparison here once."
        )
    if not calibration:
        raise EvidenceError("no calibration items were given, so there is nothing to fit on")
    best_overall = max(ts, key=lambda t: table.solved_by(t, calibration))
    default = default or best_overall
    # Averaged over complete cases only, so "cheapest" is not decided by which tier happened to lose fewer
    # token counts.
    cost_items, _ = table.priced_items(ts, calibration)
    avg_cost = {t: ((table.spend_of(t, cost_items) if cost_items else None) or math.inf)
                   / max(1, len(cost_items)) for t in ts}
    cheap_first = sorted(ts, key=lambda t: avg_cost[t])

    buckets: dict[object, list[str]] = {}
    for i in calibration:
        buckets.setdefault(table.features.get(i, {}).get(feature), []).append(i)

    assignment: dict = {}
    detail: dict = {}
    margin = constraints.margin if constraints.margin is not None else 0.0
    for value, items in buckets.items():
        rates = {t: table.solved_by(t, items) / len(items) for t in ts}
        top = max(rates.values())
        eligible = [t for t in cheap_first if rates[t] >= top - margin]
        if constraints.min_solve_rate is not None:
            eligible = [t for t in eligible if rates[t] >= constraints.min_solve_rate]
        chosen = eligible[0] if eligible else REFUSE
        assignment[value] = chosen
        detail[str(value)] = {"items": len(items), "chosen": chosen,
                              "best_rate_here": round(top, 4),
                              "chosen_rate_here": (None if chosen == REFUSE else round(rates[chosen], 4))}
    return bucket_policy(assignment, feature=feature, default=default), {
        "feature": feature, "buckets": detail, "default": default,
        "excluded_unpriced_tiers": unpriced,
        "note": ("Fitted on the calibration fold only. Bucket rates here are in-sample and are not evidence "
                 "that the choice holds out of fold; that is what the verdict is for."),
    }


def verdict(table: OutcomeTable, candidate, baseline, holdout: list[str], *,
            constraints: Constraints, calibration: list[str] | None = None) -> dict:
    """Compare two policies on held-out items and return one of three answers.

    The paired bound is computed on the items both policies answered, because a policy that refuses an item has
    not been compared with one that answered it. The refusal counts are reported alongside so the reader can
    see how much of the population the comparison covers.
    """
    if calibration is not None:
        overlap = set(calibration) & set(holdout)
        if overlap:
            raise EvidenceError(
                f"{len(overlap)} items appear in both the calibration and held-out folds "
                f"(for example {sorted(overlap)[:3]}). Fitting and judging on the same items is how a "
                "twenty-item fold here produced a choice whose quality bound failed out of fold."
            )
    cand = table.evaluate(candidate, holdout)
    base = table.evaluate(baseline, holdout)

    both_answered = []
    n11 = n10 = n01 = n00 = 0
    for i in holdout:
        c = candidate(i, table.features.get(i, {}))
        b = baseline(i, table.features.get(i, {}))
        if c == REFUSE or b == REFUSE or c is None or b is None:
            continue
        both_answered.append(i)
        cs = table.cells[i][c].solved
        bs = table.cells[i][b].solved
        n11 += cs and bs
        n10 += cs and not bs
        n01 += (not cs) and bs
        n00 += (not cs) and (not bs)
    lcb = paired_difference_lcb(n11, n10, n01, n00, alpha=constraints.alpha)
    # The upper bound of the same interval, which is what separates "worse" from "not determined". Without it
    # every inconclusive result reads as a defeat.
    diff = ((n10 - n01) / len(both_answered)) if both_answered else 0.0
    # The other end of the same interval. `paired_difference_lcb` uses a normal approximation, which is
    # symmetric, so reflecting the point estimate is the matching upper bound rather than a separate
    # construction -- stated because a reader could reasonably assume this was computed independently.
    ucb = None if lcb is None else diff + (diff - lcb)

    breaches = []
    if constraints.min_solve_rate is not None and (cand["solve_rate"] or 0) < constraints.min_solve_rate:
        breaches.append(f"solve rate {cand['solve_rate']:.4f} below the stated floor {constraints.min_solve_rate}")
    if constraints.max_usd_per_answered is not None and (cand["usd_per_answered"] or 0) > constraints.max_usd_per_answered:
        breaches.append(f"cost per answered {cand['usd_per_answered']:.6f} above the stated ceiling "
                        f"{constraints.max_usd_per_answered}")
    if constraints.max_refusal_rate is not None:
        rr = cand["refused"] / cand["items"] if cand["items"] else 0.0
        if rr > constraints.max_refusal_rate:
            breaches.append(f"refusal rate {rr:.4f} above the stated ceiling {constraints.max_refusal_rate}")

    target = -(constraints.margin if constraints.margin is not None else 0.0)
    if breaches:
        answer = FAILS
        why = "a stated constraint was breached: " + "; ".join(breaches)
    elif lcb is None:
        answer = UNDETERMINED
        why = ("the paired bound could not be computed, so this sample does not decide the comparison. Not the "
               "same as worse.")
    elif lcb >= target:
        answer = PASSES
        why = (f"the paired lower bound {lcb:+.4f} is at or above the target {target:+.2f} on "
               f"{len(both_answered)} items both policies answered. Note this says the candidate is "
               f"acceptable at the margin its owner stated, not that it is better: the observed difference is "
               f"{diff:+.4f}.")
    elif ucb is not None and ucb < target:
        answer = FAILS
        why = (f"the paired upper bound {ucb:+.4f} is below the target {target:+.2f}, so this sample does "
               "decide against the candidate")
    else:
        answer = UNDETERMINED
        why = (f"the interval [{lcb:+.4f}, {ucb:+.4f}] straddles the target {target:+.2f}: this sample does "
               "not decide the comparison either way. Reporting this as a failure would over-read it, which "
               "is the error that once removed a whole class of approach from this project's scope on the "
               "strength of one twenty-item arm.")

    return {
        "answer": answer, "why": why,
        "target": target, "alpha": constraints.alpha,
        "paired": {"both": n11, "candidate_only": n10, "baseline_only": n01, "neither": n00},
        "difference": round(diff, 4),
        "lower_bound": None if lcb is None else round(lcb, 4),
        "upper_bound": None if ucb is None else round(ucb, 4),
        "compared_on": len(both_answered),
        "holdout_items": len(holdout),
        "candidate": cand, "baseline": base,
        "constraints_not_stated": constraints.unstated(),
        "cost_change": (None if not base["spend_usd"] else
                        round(cand["spend_usd"] / base["spend_usd"] - 1.0, 4)),
    }
