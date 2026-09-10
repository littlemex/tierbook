"""SCOPE section 12's acceptance criteria, computed from the log -- and each one saying when the log cannot support it.

The criteria are pre-registered in SCOPE and were, until now, prose. This computes them. The design decision that
matters is the third verdict:

    pass        the criterion was evaluated and held
    fail        the criterion was evaluated and did not hold
    unsupported the log does not contain what the criterion needs, so nothing was evaluated

**Most of section 12 lands on `unsupported` for a log this project can currently produce, and that is the honest
output.** A checker with two verdicts has to choose between reporting a pass it did not earn and a failure it cannot
substantiate, and both of those are worse than saying which measurement is missing. `unsupported` is also the only
verdict that tells an operator what to go and collect.

Two criteria are computable from a small log and are the ones worth having first:

- **no false certification**, which is section 12's falsifier. It needs only the candidate set and the floor, both of
  which every record carries, so it is checkable from the first decision onwards.
- **default is not a hiding place**, its mirror image: an uncertified assignment made while an admissible candidate
  existed.

The rest need traffic, a randomised design, or an injected change, and each says so in its own words rather than
sharing a generic message -- a reader who is told "insufficient data" learns nothing about what to do next.

What this does not do: tune anything, or report a criterion SCOPE does not list. A criterion invented here would be one
nobody pre-registered, which is the thing section 12's first line forbids.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .record import check_certification, from_row

PASS, FAIL, UNSUPPORTED = "pass", "fail", "unsupported"

#: The criteria SCOPE section 12 names, in its order. Named here so a checker that silently stopped evaluating one
#: would be visible as a missing row rather than as an absence.
CRITERIA = (
    "floor_compliance",
    "bound_calibration",
    "no_false_certification",
    "default_is_not_a_hiding_place",
    "slo",
    "spend_regret",
    "exploration_cost",
    "adaptation",
    "genericity_and_usefulness",
)


@dataclass
class Verdict:
    criterion: str
    verdict: str
    detail: str
    numbers: dict = None

    def as_dict(self) -> dict:
        return {"criterion": self.criterion, "verdict": self.verdict, "detail": self.detail,
                "numbers": self.numbers or {}}


def no_false_certification(decisions: list, *, floor: float, latency_feasible: bool | None) -> Verdict:
    """Section 12's falsifier. Every certified decision, against section 2's three-part definition."""
    if not decisions:
        return Verdict("no_false_certification", UNSUPPORTED,
                       "the log holds no decisions, so there is nothing to check against the definition")
    bad = []
    for row in decisions:
        d, _ignored = from_row(row)
        for v in check_certification(d, floor=floor, latency_feasible=latency_feasible):
            if "hiding place" not in v:
                bad.append(f"{d.request_id}: {v}")
    if bad:
        return Verdict("no_false_certification", FAIL,
                       "the mechanism is broken rather than mistuned: " + "; ".join(bad[:5]),
                       {"decisions": len(decisions), "violations": len(bad)})
    return Verdict("no_false_certification", PASS,
                   "every certified assignment's candidate was admissible under section 2",
                   {"decisions": len(decisions), "certified": sum(1 for r in decisions if r["certified"])})


def default_is_not_a_hiding_place(decisions: list, *, floor: float, latency_feasible: bool | None,
                                  uncertified_tolerance: float | None = None) -> Verdict:
    """An uncertified assignment made while something admissible existed, and the uncertified share against its
    stated tolerance.

    The share half is `unsupported` when no tolerance was declared, rather than compared against a number chosen
    here: section 12 says "exceeds its stated tolerance", and inventing the tolerance would be grading our own work.
    """
    if not decisions:
        return Verdict("default_is_not_a_hiding_place", UNSUPPORTED, "the log holds no decisions")
    hid = []
    for row in decisions:
        d, _ignored = from_row(row)
        for v in check_certification(d, floor=floor, latency_feasible=latency_feasible):
            if "hiding place" in v:
                hid.append(f"{d.request_id}: {v}")
    share = sum(1 for r in decisions if not r["certified"]) / len(decisions)
    numbers = {"decisions": len(decisions), "uncertified_share": round(share, 4),
               "tolerance": uncertified_tolerance}
    if hid:
        return Verdict("default_is_not_a_hiding_place", FAIL,
                       "the default was used while an admissible candidate existed: " + "; ".join(hid[:5]), numbers)
    if uncertified_tolerance is None:
        return Verdict("default_is_not_a_hiding_place", UNSUPPORTED,
                       f"no assignment hid behind the default, but the uncertified share is {share:.1%} and no "
                       f"tolerance was declared, so the second half of this criterion has nothing to compare "
                       f"against", numbers)
    if share > uncertified_tolerance:
        return Verdict("default_is_not_a_hiding_place", FAIL,
                       f"the uncertified share {share:.1%} exceeds the declared tolerance "
                       f"{uncertified_tolerance:.1%}", numbers)
    return Verdict("default_is_not_a_hiding_place", PASS,
                   f"no assignment hid behind the default and the uncertified share {share:.1%} is within "
                   f"{uncertified_tolerance:.1%}", numbers)


def binom_tail_at_most(n: int, k: int, p: float) -> float:
    """P(X <= k) for X ~ Bin(n, p). Exact, because at these counts a normal approximation is the error."""
    return sum(math.comb(n, i) * p ** i * (1.0 - p) ** (n - i) for i in range(0, k + 1))


def clopper_pearson_lower(n: int, k: int, alpha: float) -> float:
    """A one-sided exact lower confidence bound on a success rate.

    Bisection on the binomial tail rather than a beta quantile, because this package has no dependencies and the
    inverse is monotone. `p` such that P(X >= k | p) = alpha, which is the standard construction; k == 0 has no
    positive lower bound.
    """
    if k <= 0:
        return 0.0
    if k >= n:
        return alpha ** (1.0 / n)
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        # P(X >= k | mid) = 1 - P(X <= k-1 | mid)
        if 1.0 - binom_tail_at_most(n, k - 1, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return lo


def _unreadable(outcomes: dict) -> int:
    """How many log lines could not be read. A rate over "all" decisions is not that when some are missing."""
    return int((outcomes.get("__bad_lines__") or {}).get("count", 0))


def floor_compliance(decisions: list, outcomes: dict, *, floor: float, significance: float = 0.05) -> Verdict:
    """Realised success rate on routed traffic against the family's floor.

    Over **certified and labelled** decisions only. Certified because the floor is claimed for those and disclaimed
    for the rest, and labelled because a missing label read as a failure moves the rate in the direction that
    flatters the floor -- which is why section 9 requires label-missingness to be explicit.

    The test is one-sided: the criterion fails if the rate falls below the floor beyond sampling error. A normal
    approximation is not used at these counts; the exact binomial tail is.
    """
    bad = _unreadable(outcomes)
    if bad:
        return Verdict("floor_compliance", UNSUPPORTED,
                       f"{bad} log line(s) could not be read, so a rate over the routed traffic is a rate over the "
                       f"lines that survived. Repair or truncate the log before reading a rate from it",
                       {"unreadable_lines": bad})
    eligible = [r for r in decisions if r["certified"]]
    labelled = [(r, outcomes.get(r["request_id"], {})) for r in eligible]
    labelled = [(r, o) for r, o in labelled if o.get("label_state") == "labelled"]
    missing = len(eligible) - len(labelled)
    if not labelled:
        return Verdict("floor_compliance", UNSUPPORTED,
                       f"{len(eligible)} certified decisions and none of them labelled, so no realised rate exists. "
                       f"This needs the task's own oracle to have run and its verdict attached",
                       # The same key names in both branches. A caller reading `numbers` should not have to know
                       # which branch produced it, and an earlier version used two spellings for one quantity.
                       {"labelled": 0, "successes": 0, "rate": None, "floor": floor,
                        "certified": len(eligible), "unlabelled_certified": missing})
    n = len(labelled)
    k = sum(1 for _, o in labelled if o.get("label") is True)
    rate = k / n
    # Two questions, and they are not each other's negation.
    #
    # FAIL asks section 12's question directly: did the rate fall below the floor beyond sampling error. That is the
    # one-sided tail P(X <= k) under the floor.
    #
    # PASS asks whether compliance was SHOWN, which needs the lower confidence bound to clear the floor. An earlier
    # version passed when the failure test did not reject, which is accepting a null -- and it gated the middle case on
    # `n < 30`, a constant nobody derived. The bound replaces it: with few labels the bound is far below the floor and
    # the verdict is unsupported for a reason that is computed rather than chosen.
    p_low = binom_tail_at_most(n, k, floor)
    lcb = clopper_pearson_lower(n, k, significance)
    numbers = {"labelled": n, "successes": k, "rate": round(rate, 4), "floor": floor,
               "p_below_floor": round(p_low, 5), "lower_bound": round(lcb, 4),
               "significance": significance, "unlabelled_certified": missing}
    if p_low < significance:
        return Verdict("floor_compliance", FAIL,
                       f"the realised rate {rate:.1%} over {n} labelled certified decisions is below the floor "
                       f"{floor:.1%} beyond sampling error (p={p_low:.4f} < {significance})", numbers)
    if lcb >= floor:
        return Verdict("floor_compliance", PASS,
                       f"the {1 - significance:.0%} lower bound on the realised rate is {lcb:.1%} over {n} labelled "
                       f"certified decisions, which clears the floor {floor:.1%}", numbers)
    return Verdict("floor_compliance", UNSUPPORTED,
                   f"the realised rate is {rate:.1%} over {n} labelled certified decisions, and its "
                   f"{1 - significance:.0%} lower bound {lcb:.1%} does not clear the floor {floor:.1%}. Not a "
                   f"failure -- the rate is not significantly below either -- so nothing is shown in either "
                   f"direction. Reported so the rate is not mistaken for a pass", numbers)


def exploration_cost(decisions: list, *, budgeted_share: float | None = None) -> Verdict:
    """The exploration share of the log against its budget."""
    if not decisions:
        return Verdict("exploration_cost", UNSUPPORTED, "the log holds no decisions")
    share = sum(1 for r in decisions if r.get("exploration")) / len(decisions)
    numbers = {"decisions": len(decisions), "exploration_share": round(share, 4), "budget": budgeted_share}
    if budgeted_share is None:
        return Verdict("exploration_cost", UNSUPPORTED,
                       f"the exploration share is {share:.1%} and no budget was declared, so there is nothing to "
                       f"exceed. A budget invented here would be grading our own work", numbers)
    if share > budgeted_share:
        return Verdict("exploration_cost", FAIL,
                       f"the exploration share {share:.1%} exceeds the budgeted {budgeted_share:.1%}", numbers)
    return Verdict("exploration_cost", PASS,
                   f"the exploration share {share:.1%} is within the budgeted {budgeted_share:.1%}", numbers)


def slo(decisions: list, outcomes: dict, *, latency_limit_s: float | None = None,
        tolerance: float | None = None) -> Verdict:
    """Realised `P(latency > L)` per traffic class, against the stated tolerance."""
    have = [o.get("latency_s") for o in (outcomes.get(r["request_id"], {}) for r in decisions)
            if o.get("latency_s") is not None]
    if latency_limit_s is None or tolerance is None:
        return Verdict("slo", UNSUPPORTED,
                       "no latency limit or tolerance was declared. SCOPE section 1 says performance is not what is "
                       "being optimised and its treatment is explicitly unsettled, so this criterion applies only "
                       "where an operator imposed a constraint",
                       {"latencies_recorded": len(have)})
    if not have:
        return Verdict("slo", UNSUPPORTED, "a limit was declared and no latency was recorded on any outcome",
                       {"latencies_recorded": 0})
    over = sum(1 for v in have if v > latency_limit_s) / len(have)
    numbers = {"latencies_recorded": len(have), "p_over_limit": round(over, 4),
               "limit_s": latency_limit_s, "tolerance": tolerance}
    if over > tolerance:
        return Verdict("slo", FAIL, f"P(latency > {latency_limit_s}s) = {over:.1%} exceeds {tolerance:.1%}", numbers)
    return Verdict("slo", PASS, f"P(latency > {latency_limit_s}s) = {over:.1%} is within {tolerance:.1%}", numbers)


def _needs_a_design(criterion: str, why: str) -> Verdict:
    return Verdict(criterion, UNSUPPORTED, why)


def check_all(decisions: list, outcomes: dict, *, floor: float, latency_feasible: bool | None = None,
              uncertified_tolerance: float | None = None, budgeted_exploration: float | None = None,
              latency_limit_s: float | None = None, slo_tolerance: float | None = None,
              significance: float = 0.05, pool_across_versions: bool = False) -> list:
    """Every criterion section 12 names, in its order, each with its own verdict.

    The three that cannot be computed from a log at all say what they need instead of sharing a message: a reader told
    "insufficient data" learns nothing about what to collect.

    `pool_across_versions` is accepted here so the signature does not move again under C5, which is the entry that
    gives it a behaviour -- refusing the mixture-sensitive criteria with `UNSUPPORTED` when decisions span more than
    one `schema_version` and this is false. C1 only reads a mixed log without raising; it does not yet detect or
    refuse the mixture.
    """
    del pool_across_versions  # threaded nowhere yet; C5 owns the refusal this keyword requests
    return [
        floor_compliance(decisions, outcomes, floor=floor, significance=significance),
        _needs_a_design("bound_calibration",
                        "this is a property of the confidence procedure, not of the log. It needs the "
                        "pre-registered resampling or simulation where the estimand is known, run against the "
                        "procedure -- no amount of routed traffic substitutes, because in traffic the estimand is "
                        "what is unknown"),
        no_false_certification(decisions, floor=floor, latency_feasible=latency_feasible),
        default_is_not_a_hiding_place(decisions, floor=floor, latency_feasible=latency_feasible,
                                      uncertified_tolerance=uncertified_tolerance),
        slo(decisions, outcomes, latency_limit_s=latency_limit_s, tolerance=slo_tolerance),
        _needs_a_design("spend_regret",
                        "an off-policy estimate with an interval, by the method section 9 declares. It needs logged "
                        "selection probabilities that vary -- every decision in a deterministic policy has "
                        "propensity 1, under which the counterfactual arm has no data and the estimate is "
                        "unidentified. Randomised exploration is the prerequisite, not a refinement"),
        exploration_cost(decisions, budgeted_share=budgeted_exploration),
        _needs_a_design("adaptation",
                        "an injected change -- a price change, a model release, an agent swap, a capacity loss -- and "
                        "then a check that the new candidate enters shadow evaluation within the adaptation window "
                        "and is admitted once its bound clears, WITHOUT a code change. It is an experiment on the "
                        "mechanism, so a log of ordinary traffic cannot contain it"),
        _needs_a_design("genericity_and_usefulness",
                        "a held-out environment and a candidate introduced after implementation freeze, reusing the "
                        "incumbent policy file except environment-owned rows. Also an experiment rather than a "
                        "reading, and the criterion's second half -- a certified share above its stated minimum "
                        "while a feasible admissible candidate exists -- needs the acceptance oracle that names one"),
    ]


def summarise(verdicts: list) -> dict:
    counts = {PASS: 0, FAIL: 0, UNSUPPORTED: 0}
    for v in verdicts:
        counts[v.verdict] += 1
    return {
        "counts": counts,
        # Named rather than reduced to a boolean: "accepted" over a set where most criteria were never evaluated
        # would be the claim this module exists to refuse.
        "any_failure": counts[FAIL] > 0,
        "evaluated": counts[PASS] + counts[FAIL],
        "of": len(CRITERIA),
        "note": ("a criterion is accepted only when it was evaluated and held. `unsupported` is neither a pass nor a "
                 "failure: it names a measurement that has not been made, and most of section 12 needs traffic, a "
                 "randomised design or an injected change rather than more of the same log"),
    }
