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

One criterion needs no log at all. **floor reachability** (CONTRACT v0.3.0 C5) is a fact about the evidence budget,
not about traffic: a declared floor above `alpha ** (1/n)` for the cohort's own `n` cannot be cleared by any
measurement, however the traffic behaves, so it is checked at compile time and carried into the artifact rather than
computed here from `decisions` -- `floor_is_reachable` below reads what `decide.compile_policy` already worked out.

The rest need traffic, a randomised design, or an injected change, and each says so in its own words rather than
sharing a generic message -- a reader who is told "insufficient data" learns nothing about what to do next.

What this does not do: tune anything, or report a criterion SCOPE does not list. A criterion invented here would be one
nobody pre-registered, which is the thing section 12's first line forbids.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .record import _UNVERIFIABLE_PREFIX as UNVERIFIABLE_PREFIX
from .record import check_certification, from_row

PASS, FAIL, UNSUPPORTED = "pass", "fail", "unsupported"

#: The criteria SCOPE section 12 names, in its order. Named here so a checker that silently stopped evaluating one
#: would be visible as a missing row rather than as an absence.
CRITERIA = (
    "floor_compliance",
    # CONTRACT v0.3.0 C5: the tenth criterion. SCOPE section 12 previously named nine; this is a different
    # question about a different object -- the declared floor against its cohort's ceiling, not traffic
    # against the floor -- so it is a new row rather than a reading folded into `floor_compliance`.
    "floor_is_reachable",
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


def no_false_certification(decisions: list, *, floor: float, latency_feasible: bool | None,
                           max_age_days: float | None = None) -> Verdict:
    """Section 12's falsifier. Every certified decision, against section 2's four-part definition.

    `max_age_days` gained here (amendment 7, C6): before this entry, this function called
    `record.check_certification` with freshness absent since v0.1.0 -- the release in which `record.admissible`
    gained freshness as its fourth condition -- so the falsifier was blind to it. Unlike the age, which
    `check_certification` now derives per candidate, the limit is not in the record: it is the family's declared
    policy input, so it comes from outside, and `cli.cmd_accept` is the one caller that supplies it (from the
    policy artifact, never a flag). Absent here, the condition is absent rather than satisfied, as with
    `latency_feasible`.
    """
    if not decisions:
        return Verdict("no_false_certification", UNSUPPORTED,
                       "the log holds no decisions, so there is nothing to check against the definition")
    bad: list[str] = []
    unverifiable: list[str] = []
    certified_rows = 0
    for row in decisions:
        d, _ignored = from_row(row)
        certified_rows += bool(d.certified)
        for v in check_certification(d, floor=floor, latency_feasible=latency_feasible, max_age_days=max_age_days):
            if "hiding place" in v:
                continue
            # Amendment 5: a finding that cannot be CHECKED is not a violation. Before this split, every
            # certified decision written before C1 recorded a bound's provenance failed here -- not only the
            # wrong ones -- and section 12 reads this criterion's failure as the mechanism being broken, so a
            # correct historical log accused the mechanism. C11's rule, applied to a second way a population can
            # be incomplete: compute over what can be checked and say how much could not.
            (unverifiable if v.startswith(UNVERIFIABLE_PREFIX) else bad).append(f"{d.request_id}: {v}")
    if bad:
        return Verdict("no_false_certification", FAIL,
                       "the mechanism is broken rather than mistuned: " + "; ".join(bad[:5]),
                       {"decisions": len(decisions), "violations": len(bad),
                        "unverifiable": len(unverifiable)})
    if unverifiable and len(unverifiable) >= certified_rows:
        # Nothing certified here can be checked, so there is no population to compute over. A pass would claim a
        # verification that did not happen, and a failure would speak from absence.
        return Verdict("no_false_certification", UNSUPPORTED,
                       f"{len(unverifiable)} certified decision(s) carry a bound whose provenance was never "
                       f"recorded, so whether each cleared its floor cannot be established from the log. This "
                       f"needs decisions written by a mechanism that records what produced a bound",
                       {"decisions": len(decisions), "unverifiable": len(unverifiable),
                        "certified": certified_rows})
    detail = "every certified assignment's candidate was admissible under section 2"
    if unverifiable:
        detail += (f" -- computed over the {certified_rows - len(unverifiable)} certified decision(s) that could "
                   f"be checked; {len(unverifiable)} carry no recorded bound provenance")
    return Verdict("no_false_certification", PASS, detail,
                   {"decisions": len(decisions), "certified": certified_rows,
                    "unverifiable": len(unverifiable)})


def default_is_not_a_hiding_place(decisions: list, outcomes: dict | None = None, *, floor: float,
                                  latency_feasible: bool | None,
                                  uncertified_tolerance: float | None = None,
                                  max_age_days: float | None = None) -> Verdict:
    """An uncertified assignment made while something admissible existed, and the uncertified share against its
    stated tolerance.

    The share half is `unsupported` when no tolerance was declared, rather than compared against a number chosen
    here: section 12 says "exceeds its stated tolerance", and inventing the tolerance would be grading our own work.

    `max_age_days` gained here for the same reason `no_false_certification` gained it (amendment 7, C6): this is
    the mirror falsifier over the same `check_certification`, and a scalar age applied to every candidate would
    have been just as wrong for a default that hides behind a stale bound as for a certified one.

    `outcomes` gained here (amendment 13, C11): before this entry this function had no way to see either class
    of row `record.Log.read` drops (`__bad_lines__`, `__unreadable_rows__`), so its own uncertified share -- a
    rate over `decisions` -- could be narrowed by exactly the same rows `floor_compliance` was found narrowed
    by. Optional and defaulted to `None`/treated as empty, so a caller that does not pass it gets this
    criterion's ordinary behaviour rather than a newly-required argument.
    """
    incomplete = _incomplete_population(outcomes or {})
    if incomplete:
        return Verdict("default_is_not_a_hiding_place", UNSUPPORTED,
                       f"the uncertified share is a rate over the decisions that survived reading, and "
                       f"{incomplete}. Fix the log before reading a share from it",
                       {"unreadable": _unreadable(outcomes or {})})
    if not decisions:
        return Verdict("default_is_not_a_hiding_place", UNSUPPORTED, "the log holds no decisions")
    hid = []
    for row in decisions:
        d, _ignored = from_row(row)
        for v in check_certification(d, floor=floor, latency_feasible=latency_feasible, max_age_days=max_age_days):
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
    # DEFECT these two prevent, measured: the boundary below is `k >= n`, which is exact for k == n and was
    # applied to k > n as well -- so `cp(n=16, k=20)`, twenty successes in sixteen trials, returned 0.8293. That
    # is not a boundary, it is a contradiction, and the value is HIGH, so a transposed argument pair produced a
    # bound that flattered the candidate instead of a refusal. The true bound for that cohort is 0.4922, and the
    # transposition happened while reading whether a tier cleared a 0.80 floor.
    if n <= 0:
        raise ValueError(f"a lower bound needs at least one trial; n={n!r}. `alpha ** (1/n)` below would divide "
                         f"by zero, which is a better failure than a wrong answer but not a stated one")
    if k > n:
        raise ValueError(f"{k} successes in {n} trials is not a measurement. Check the argument order: this "
                         f"function takes (n, k, alpha) -- trials first -- and the mistake returns a HIGH bound "
                         f"rather than an obviously wrong one, so it reads as a candidate clearing its floor")
    if k <= 0:
        return 0.0
    if k == n:
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


def floor_reachable(n: int, floor: float, alpha: float) -> tuple[bool, float, int]:
    """CONTRACT v0.3.0 C5. Whether `floor` is reachable AT ALL on a cohort of `n` -- not whether traffic has
    shown it, but whether any measurement on `n` items could. `clopper_pearson_lower`'s own `k == n` case is
    the highest lower confidence bound `n` trials can ever produce: `alpha ** (1/n)`. A floor declared above
    that number cannot be cleared regardless of what the evidence says, because clearing it would need a
    perfect record on a cohort this size, and even a perfect record's bound tops out below the floor.

    Returns `(reachable, ceiling, smallest_n)`: whether `floor` is at or below the ceiling `n` imposes, the
    ceiling itself, and the smallest cohort size at which the ceiling first reaches `floor` -- what a cohort
    would have to grow to for this floor to stop being unreachable.

    `n <= 0` raises, by `clopper_pearson_lower`'s own C14 rule: `alpha ** (1/n)` divides by zero at `n == 0`,
    and a negative cohort is not a measurement.
    """
    if n <= 0:
        raise ValueError(f"a ceiling needs at least one trial; n={n!r}. `alpha ** (1/n)` would divide by zero "
                         f"at n=0, which is a better failure than a wrong answer but not a stated one")
    ceiling = alpha ** (1.0 / n)
    needed = _smallest_reachable_cohort(floor, alpha)
    return ceiling >= floor, ceiling, needed


def _smallest_reachable_cohort(floor: float, alpha: float, *, cap: int = 10_000_000) -> int:
    """The smallest `n` at which `alpha ** (1/n) >= floor`.

    `alpha ** (1/n)` increases toward 1 as `n` grows and is lowest, at `alpha` itself, when `n == 1` -- so a
    floor at or below `alpha` is reachable on a single trial, and a floor at or above 1 is not reachable on
    any finite cohort, which is refused rather than searched for forever.

    A closed-form estimate (`log(alpha) / log(floor)`) gets within one integer of the answer and is then
    walked to the exact boundary rather than trusted as-is: floating point put the estimate one past the true
    answer on this release's own worked example -- at `floor = alpha ** (1/20)` exactly, the estimate came
    back 21, not 20 -- so the walk is what makes this return value exact rather than approximately right.
    """
    if floor <= alpha:
        return 1
    if floor >= 1.0:
        raise ValueError(f"floor={floor!r} is not reachable on any finite cohort: alpha ** (1/n) < 1 for "
                         f"every n, however large")
    guess = max(1, math.ceil(math.log(alpha) / math.log(floor)))
    while guess > 1 and alpha ** (1.0 / (guess - 1)) >= floor:
        guess -= 1
    while guess <= cap and alpha ** (1.0 / guess) < floor:
        guess += 1
    if guess > cap:
        raise ValueError(f"floor={floor!r} against alpha={alpha!r} needs a cohort larger than {cap}, which is "
                         f"not a search worth trusting floating point for")
    return guess


def floor_is_reachable(floor: float, floor_ceiling: dict | None) -> Verdict:
    """CONTRACT v0.3.0 C5. SCOPE section 12's tenth criterion: the declared floor against the ceiling its own
    cohort imposes -- a fact about the evidence budget, checkable before a single request is served, and a
    different question from `floor_compliance`'s "did the traffic clear it."

    `floor_ceiling` is `decide.compile_policy`'s own computation (`floor_reachable`, above), carried in the
    compiled artifact's `parameters` and read here rather than recomputed, so this criterion and the number an
    operator already saw out of `tierbook compile` cannot drift into two answers to the same question.

    Its absence means the compiled artifact predates this entry (a v0.2.0 policy) or the family had no
    evidence to count a cohort from -- either way nothing was computed, so UNSUPPORTED names that rather than
    guessing a verdict from a fact this criterion was never given.
    """
    if not floor_ceiling:
        return Verdict("floor_is_reachable", UNSUPPORTED,
                       "the compiled policy carries no floor_ceiling, so either it predates CONTRACT v0.3.0 "
                       "C5 (a v0.2.0 artifact) or the family had no evidence to count a cohort from. This "
                       "needs a policy compiled by this release against a family the ledger records an "
                       "outcome for")
    ceiling = floor_ceiling["ceiling"]
    cohort_size = floor_ceiling["cohort_size"]
    needed = floor_ceiling["cohort_size_needed"]
    numbers = {"floor": floor, "ceiling": ceiling, "cohort_size": cohort_size, "cohort_size_needed": needed}
    if floor > ceiling:
        return Verdict("floor_is_reachable", FAIL,
                       f"the declared floor {floor:.4f} exceeds {ceiling:.4f}, the ceiling a {cohort_size}-item "
                       f"cohort imposes on any lower confidence bound; clearing it needs a cohort of at least "
                       f"{needed} items", numbers)
    return Verdict("floor_is_reachable", PASS,
                   f"the declared floor {floor:.4f} does not exceed {ceiling:.4f}, the ceiling a "
                   f"{cohort_size}-item cohort imposes", numbers)


def _unreadable(outcomes: dict) -> dict:
    """How many log lines/rows could not be read, one count per class `record.Log.read` distinguishes.

    CONTRACT C11 (Amendment 13): before this entry, this returned one merged count, read from
    `__bad_lines__` only. `__unreadable_rows__` -- the counter C1 added THIS RELEASE so that "the file was
    truncated" and "the record is from a newer schema" would be different operator actions -- was not
    consulted anywhere, so a criterion's population could be narrowed by rows from a schema this reader
    refuses with nothing reporting it. Returns both counts, separately, rather than one sum: merging them
    back into a single number here would undo C1's distinction from the other end of the pipeline.
    """
    o = outcomes or {}
    return {
        "bad_lines": int((o.get("__bad_lines__") or {}).get("count", 0)),
        "unreadable_rows": int((o.get("__unreadable_rows__") or {}).get("count", 0)),
    }


def _incomplete_population(outcomes: dict) -> str | None:
    """`None` when the log's `decisions` are the whole population a rate can be computed over; otherwise a
    detail naming each class of dropped row and its count, so a criterion whose value is a rate over a
    population can refuse rather than compute the rate over whichever rows happened to survive reading.

    CONTRACT C11: this is `floor_compliance`'s own pre-existing principle -- "a rate over 'all' decisions is
    not that when some are missing" -- extended to the second class C1 introduced. The two are named
    separately, never merged into one phrase: "the file was truncated" (`bad_lines`) calls for repairing or
    truncating the log, "the record is from a newer schema" (`unreadable_rows`) calls for upgrading the
    reader, and an operator handed one merged number cannot tell which action applies.
    """
    counts = _unreadable(outcomes)
    parts = []
    if counts["bad_lines"]:
        parts.append(f"{counts['bad_lines']} log line(s) unreadable as JSON, most likely a crash mid-append "
                     f"-- repair or truncate the file")
    if counts["unreadable_rows"]:
        parts.append(f"{counts['unreadable_rows']} row(s) parsed but could not be read as a record, most "
                     f"likely from a schema_version newer than this reader knows -- upgrade the reader")
    if not parts:
        return None
    return "; ".join(parts)


def _rate_against_floor(pairs: list, *, total_population: int, floor: float, significance: float) -> tuple[dict, str]:
    """One population's realised rate against the floor: the FAIL test, the PASS bound, and its own verdict.

    Shared between the two populations `floor_compliance` now reports (CONTRACT C3) so they cannot drift into two
    slightly different readings of section 12's one test -- the same failure mode C2's audit found for the floor
    itself, in a smaller shape here.

    Two questions, and they are not each other's negation.

    FAIL asks section 12's question directly: did the rate fall below the floor beyond sampling error. That is the
    one-sided tail P(X <= k) under the floor.

    PASS asks whether compliance was SHOWN, which needs the lower confidence bound to clear the floor. An earlier
    version passed when the failure test did not reject, which is accepting a null -- and it gated the middle case on
    `n < 30`, a constant nobody derived. The bound replaces it: with few labels the bound is far below the floor and
    the verdict is unsupported for a reason that is computed rather than chosen.
    """
    missing = total_population - len(pairs)
    if not pairs:
        return ({"labelled": 0, "successes": 0, "rate": None, "unlabelled": missing, "verdict": UNSUPPORTED},
                f"{total_population} decisions and none of them labelled, so no realised rate exists. This needs "
                f"the task's own oracle to have run and its verdict attached")
    n = len(pairs)
    k = sum(1 for _, o in pairs if o.get("label") is True)
    rate = k / n
    p_low = binom_tail_at_most(n, k, floor)
    lcb = clopper_pearson_lower(n, k, significance)
    out = {"labelled": n, "successes": k, "rate": round(rate, 4), "p_below_floor": round(p_low, 5),
          "lower_bound": round(lcb, 4), "unlabelled": missing}
    if p_low < significance:
        out["verdict"] = FAIL
        detail = (f"the realised rate {rate:.1%} over {n} labelled decisions is below the floor {floor:.1%} "
                  f"beyond sampling error (p={p_low:.4f} < {significance})")
    elif lcb >= floor:
        out["verdict"] = PASS
        detail = (f"the {1 - significance:.0%} lower bound on the realised rate is {lcb:.1%} over {n} labelled "
                  f"decisions, which clears the floor {floor:.1%}")
    else:
        out["verdict"] = UNSUPPORTED
        detail = (f"the realised rate is {rate:.1%} over {n} labelled decisions, and its {1 - significance:.0%} "
                  f"lower bound {lcb:.1%} does not clear the floor {floor:.1%}. Not a failure -- the rate is not "
                  "significantly below either -- so nothing is shown in either direction. Reported so the rate "
                  "is not mistaken for a pass")
    return out, detail


def floor_compliance(decisions: list, outcomes: dict, *, floor: float, significance: float = 0.05) -> Verdict:
    """Realised success rate against the family's floor -- over **two** populations (CONTRACT C3).

    `certified`, over certified and labelled decisions, exactly as before this entry: certified because the floor
    is claimed for those and disclaimed for the rest.

    `all_served`, over every served and labelled decision, certified or not. **Not** "explored assignments are
    uncertified by construction" (a rejected alternative, F8): that would let traffic below the floor be served
    and then removed from this criterion's own denominator, which preserves the metric rather than the floor.
    Since `explore.eligible` already requires a candidate's bound to clear the floor before exploration may draw
    into it, an explored assignment is certified when the rest of admissibility holds -- `serve.route_once`
    records it that way -- so this second population is not a hole the first one has; it is the check that the
    first one's denominator was not narrowed to hide a violation.

    Labelled either way, for the reason unchanged from before: a missing label read as a failure moves the rate
    in the direction that flatters the floor -- section 9 requires label-missingness to be explicit.

    The two verdicts are independent -- `all_served`'s population is a superset of `certified`'s but need not agree
    with it, since an uncertified decision can be labelled while a certified one is still pending. This function's
    own `verdict` is FAIL if either population fails, PASS if both pass, and UNSUPPORTED otherwise, so a caller
    reading only the top-level field never sees a pass that a second, wider population would have contradicted.
    """
    incomplete = _incomplete_population(outcomes)
    if incomplete:
        return Verdict("floor_compliance", UNSUPPORTED,
                       f"a rate over the routed traffic is a rate over the rows that survived reading, and "
                       f"{incomplete}. Fix the log before reading a rate from it",
                       {"unreadable": _unreadable(outcomes)})

    def _labelled(rows: list) -> list:
        pairs = ((r, outcomes.get(r["request_id"], {})) for r in rows)
        return [(r, o) for r, o in pairs if o.get("label_state") == "labelled"]

    certified_rows = [r for r in decisions if r["certified"]]
    c_numbers, c_detail = _rate_against_floor(_labelled(certified_rows), total_population=len(certified_rows),
                                              floor=floor, significance=significance)
    s_numbers, s_detail = _rate_against_floor(_labelled(decisions), total_population=len(decisions),
                                              floor=floor, significance=significance)

    # Flat, and every key `floor_compliance` wrote before C3 keeps exactly its old meaning -- the certified
    # population -- so a caller reading `numbers["rate"]` or `numbers["lower_bound"]` is unaffected by this
    # entry. The `served_` prefix is the new population; `numbers` gains `served_labelled` and `served_rate` at
    # minimum, per the interface, plus their own bound and verdict alongside for the same reason `certified`
    # already carries one -- "each with its own bound and verdict" cannot be satisfied by a name that gains only
    # a count and a rate.
    numbers = {
        "labelled": c_numbers["labelled"], "successes": c_numbers["successes"], "rate": c_numbers["rate"],
        "floor": floor, "significance": significance,
        "certified": len(certified_rows), "unlabelled_certified": c_numbers["unlabelled"],
        "verdict": c_numbers["verdict"],
        "served": len(decisions), "served_labelled": s_numbers["labelled"],
        "served_successes": s_numbers["successes"], "served_rate": s_numbers["rate"],
        "unlabelled_served": s_numbers["unlabelled"], "served_verdict": s_numbers["verdict"],
    }
    if "p_below_floor" in c_numbers:
        numbers["p_below_floor"] = c_numbers["p_below_floor"]
        numbers["lower_bound"] = c_numbers["lower_bound"]
    if "p_below_floor" in s_numbers:
        numbers["served_p_below_floor"] = s_numbers["p_below_floor"]
        numbers["served_lower_bound"] = s_numbers["lower_bound"]

    cv, sv = c_numbers["verdict"], s_numbers["verdict"]
    if FAIL in (cv, sv):
        verdict = FAIL
    elif cv == PASS and sv == PASS:
        verdict = PASS
    else:
        verdict = UNSUPPORTED
    detail = f"certified traffic: {c_detail}; all served traffic: {s_detail}"
    return Verdict("floor_compliance", verdict, detail, numbers)


def exploration_cost(decisions: list, outcomes: dict | None = None, *,
                     budgeted_share: float | None = None) -> Verdict:
    """The exploration share of the log against its budget.

    `outcomes` gained here (amendment 13, C11): the exploration share is a rate over `len(decisions)`, and
    `decisions` already had every unreadable row silently excluded by `record.Log.read` before this function
    ever saw it, so this rate needed the same guard `floor_compliance` has. Optional, for the same
    backward-compatibility reason `default_is_not_a_hiding_place` gained it.
    """
    incomplete = _incomplete_population(outcomes or {})
    if incomplete:
        return Verdict("exploration_cost", UNSUPPORTED,
                       f"the exploration share is a rate over the decisions that survived reading, and "
                       f"{incomplete}. Fix the log before reading a share from it",
                       {"unreadable": _unreadable(outcomes or {})})
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
    """Realised `P(latency > L)` per traffic class, against the stated tolerance.

    Guarded against an incomplete population for the same reason `floor_compliance` is (amendment 13, C11):
    `P(latency > L)` is a rate over the latencies recorded on `decisions`, and `decisions` already excludes
    every row `record.Log.read` could not turn into a `Decision` -- if any of those rows would have breached
    the limit, this rate looks better than it is with nothing saying so.
    """
    incomplete = _incomplete_population(outcomes)
    if incomplete:
        return Verdict("slo", UNSUPPORTED,
                       f"a latency rate is a rate over the decisions that survived reading, and {incomplete}. "
                       f"Fix the log before reading a rate from it",
                       {"unreadable": _unreadable(outcomes)})
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


def _version_counts(decisions: list) -> dict:
    """How many decisions came from each `schema_version`.

    Read through `record.from_row`, not through a second `row.get("schema_version", 1)` here: `from_row` is
    already the one place that knows an absent key means version 1 and a version newer than this reader raises
    (CONTRACT interface, C1). Re-deriving that rule in `accept.py` would be a second copy of it, and the two
    copies are exactly the kind of thing that drifts the day only one of them is updated.
    """
    counts: dict = {}
    for row in decisions:
        d, _ignored = from_row(row)
        counts[d.schema_version] = counts.get(d.schema_version, 0) + 1
    return counts


def _versions_named(version_counts: dict) -> str:
    """CONTRACT C5's interface: a mixture refusal names "the versions present and the count in each". One
    formatter so the four mixture-sensitive criteria below say it identically rather than as four hand-typed
    strings that could drift apart from each other."""
    return ", ".join(f"schema_version {v} ({n} decision{'' if n == 1 else 's'})"
                     for v, n in sorted(version_counts.items()))


def _mixture_guarded(criterion: str, compute, *, version_counts: dict, pool_across_versions: bool) -> Verdict:
    """CONTRACT C5. `floor_compliance`, `default_is_not_a_hiding_place`, `exploration_cost` and `spend_regret`
    each have a value that depends on which mechanism logged which decision, and pooling them silently is the
    defect this entry exists to make impossible to report as a pass.

    Measured, not hypothesised (amendment 8's journey pass): 8 v0.1.0 rows logged before any exploration
    mechanism existed (`exploration: false` because there was nothing to set it true), plus 2 v0.2.0 rows that
    both genuinely explored, made `exploration_cost` report one pooled number -- 20% -- which PASSED a 25%
    budget, while the v0.2.0 mechanism's own rate over the 2 decisions it was eligible to explore was 100%,
    four times over. Nothing in that report distinguished the two mechanisms. The same dilution applies to
    `floor_compliance` (its denominator moves with log length rather than behaviour), to
    `default_is_not_a_hiding_place` (a v0.1.0 log has no exploration mechanism to hide behind at all, so its
    uncertified share and a v0.2.0 log's are not one statistic), and to `spend_regret` (a v0.1.0 row reads as
    propensity 1 and contributes infinite-weight certainty to a weighted estimate built across the boundary).

    DEFECT this replaces (amendment 9, A9.1): an earlier version of this guard refused to even call `compute`
    when the log was mixed and unpooled, so `spend_regret` -- which is UNSUPPORTED in every log regardless of
    mixture, because no estimator is implemented -- was reported as blocked on "your log spans two schema
    versions" instead of on the real reason, its own message. That sends an operator to fix a log that was
    never the blocker. `compute` always runs now, and only a `PASS` or a `FAIL` -- a value the criterion
    actually produced by looking at the mixed traffic -- is replaced by the mixture refusal. An `UNSUPPORTED`
    `compute` already returned is left exactly as it was: it is already saying, in its own words, what it
    needs, which is the property `accept.py`'s own module docstring calls the reason `UNSUPPORTED` exists.
    Computing and discarding the result costs nothing and is what tells "would have answered" apart from
    "could not have answered anyway."

    With `pool_across_versions=True`, a `PASS` or `FAIL` that `compute` produced from the mixed traffic keeps
    its value and gains a note in its own detail -- "on the caller's instruction" -- because pooling across a
    policy version boundary is now something a caller asked for, not something that happened by not asking. An
    `UNSUPPORTED` result gains no such note either, for the same reason as above: it was not affected by the
    pooling, so there is nothing pooled to disclose.

    Not applied to `no_false_certification`: CONTRACT v0.2.0 C5 is explicit that it is a per-decision universal
    claim rather than a rate, so a mixture does not change what it means, and `check_all` below calls it
    directly, unguarded. Not applied to `floor_is_reachable` either, for the same reason from the other
    direction (CONTRACT v0.3.0 C5): it is a fact about the declared floor and the compiled cohort, not a rate
    over `decisions` at all, so there is nothing here for a schema-version mixture to blend.
    """
    verdict = compute()
    if len(version_counts) <= 1 or verdict.verdict == UNSUPPORTED:
        return verdict
    versions = _versions_named(version_counts)
    if not pool_across_versions:
        return Verdict(criterion, UNSUPPORTED,
                       f"the decisions span more than one schema_version ({versions}) and "
                       f"pool_across_versions is false, so this criterion's value would blend mechanisms that "
                       f"were not the same mechanism into one number. Pass pool_across_versions=True to "
                       f"compute it pooled anyway",
                       {"version_counts": dict(version_counts)})
    verdict.detail = (f"{verdict.detail} -- schema versions {versions} were pooled on the caller's "
                      f"instruction (pool_across_versions=True)")
    return verdict


def check_all(decisions: list, outcomes: dict, *, floor: float, latency_feasible: bool | None = None,
              uncertified_tolerance: float | None = None, budgeted_exploration: float | None = None,
              latency_limit_s: float | None = None, slo_tolerance: float | None = None,
              significance: float = 0.05, pool_across_versions: bool = False,
              max_age_days: float | None = None, floor_ceiling: dict | None = None) -> list:
    """Every criterion section 12 names, in its order, each with its own verdict.

    The three that cannot be computed from a log at all say what they need instead of sharing a message: a reader told
    "insufficient data" learns nothing about what to collect.

    `pool_across_versions` (CONTRACT v0.2.0 C5) now has the behaviour C1 only reserved the keyword for: `floor_compliance`,
    `default_is_not_a_hiding_place`, `exploration_cost` and `spend_regret` -- the criteria a mixture changes the
    value of -- go through `_mixture_guarded`, which always computes the criterion first (amendment 9, A9.1: an
    `UNSUPPORTED` a criterion returns for its own reason, such as `spend_regret` having no estimator at all, is
    left exactly as it was rather than replaced with a refusal that sends an operator to fix a log that was
    never the blocker). When `decisions` carries more than one `schema_version` and the criterion would
    otherwise have produced a `PASS` or a `FAIL`, that value is replaced with `UNSUPPORTED` naming the versions
    present and the count in each -- computing and discarding the result is how "would have answered" is told
    apart from "could not have answered anyway". `no_false_certification` and `floor_is_reachable` are each a
    per-decision or per-declaration claim rather than a rate, so a mixture does not change what either means
    and neither is ever guarded.
    `pool_across_versions=True` keeps a `PASS`/`FAIL` computed from the mixed traffic and says, in that verdict's
    own detail, that the versions were pooled on the caller's instruction.

    `max_age_days` (amendment 7, C6) is the family's declared freshness limit, passed down to the two falsifiers
    that call `record.check_certification`. It is not in the record the way an age is -- it is a policy input, so
    it comes from outside, and `cli.cmd_accept` is the one caller that supplies it, read from the compiled policy
    through `decide.parameter` rather than a second CLI flag.

    `floor_ceiling` (CONTRACT v0.3.0 C5) is the same kind of value for the same reason: `decide.compile_policy`
    already computed it and stamped it into the artifact's `parameters`, so `cli.cmd_accept` reads it through
    `decide.parameter` rather than this function re-deriving it from a ledger it is never given. `None` (a caller
    with no policy artifact, or a policy from before this entry) makes `floor_is_reachable` UNSUPPORTED rather
    than silently absent from this list -- it is still section 12's tenth row and still gets a verdict.
    """
    version_counts = _version_counts(decisions)

    def guard(criterion: str, compute) -> Verdict:
        return _mixture_guarded(criterion, compute, version_counts=version_counts,
                                pool_across_versions=pool_across_versions)

    return [
        guard("floor_compliance",
             lambda: floor_compliance(decisions, outcomes, floor=floor, significance=significance)),
        floor_is_reachable(floor, floor_ceiling),
        _needs_a_design("bound_calibration",
                        "this is a property of the confidence procedure, not of the log. It needs the "
                        "pre-registered resampling or simulation where the estimand is known, run against the "
                        "procedure -- no amount of routed traffic substitutes, because in traffic the estimand is "
                        "what is unknown"),
        no_false_certification(decisions, floor=floor, latency_feasible=latency_feasible, max_age_days=max_age_days),
        guard("default_is_not_a_hiding_place",
             lambda: default_is_not_a_hiding_place(decisions, outcomes, floor=floor,
                                                    latency_feasible=latency_feasible,
                                                    uncertified_tolerance=uncertified_tolerance,
                                                    max_age_days=max_age_days)),
        slo(decisions, outcomes, latency_limit_s=latency_limit_s, tolerance=slo_tolerance),
        guard("spend_regret",
             lambda: _needs_a_design(
                 "spend_regret",
                 "an off-policy estimate with an interval, by the method section 9 declares, and no estimator "
                 "for it exists yet -- that is the blocker, not the log. Amendment 9 corrects an earlier "
                 "version of this message, written a release before C3 shipped: a family with no declared "
                 "exploration_rate still gives every decision propensity 1, under which the counterfactual arm "
                 "has no data and the estimate stays unidentified, so that dependency is real and unchanged. "
                 "But where a family DOES declare a rate, C3's randomised draw already makes "
                 "selection_probability vary -- the prerequisite this criterion needed is now met for that "
                 "traffic, and what remains missing is the estimator and its confidence interval, not "
                 "exploration itself")),
        guard("exploration_cost", lambda: exploration_cost(decisions, outcomes,
                                                           budgeted_share=budgeted_exploration)),
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
