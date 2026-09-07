"""Compare two arms on the items they both attempted, which is the only comparison these cohorts support.

Two independent binomials is the wrong statistic here and it is the one everybody reaches for. The arms ran the
**same items**, so what carries information is the discordance: the items one arm solved and the other did not.
Ten solved against eleven solved is uninformative as two marginals; it is also compatible with nine items where
the arms disagreed, which is a real signal about where they differ, and with one, which is noise.

So this reports the 2x2 table, an exact test on the discordant pairs, and the items in each cell by name. The
names matter more than the p-value: "these three tasks the box got and the API did not" is something an operator
can read, and a p-value is not.

**What it refuses.** A comparison over items only one arm attempted, because a marginal built on different item
sets is not a comparison of arms. And a verdict: the exact test is reported with its interval and the discordant
counts beside it, because at these sample sizes the honest output is usually "this does not decide it".

SCOPE (see ../SCOPE.md, which governs this file): an instrument. It reports; it decides nothing.
"""
from __future__ import annotations

import argparse
import json
from math import comb, sqrt
from pathlib import Path

SOLVED = "solved"


def outcomes_by_item(path: Path) -> tuple[dict, list]:
    """Item -> whether that arm solved it, plus the items whose outcome was not observed at all.

    An unobserved item is kept apart rather than counted as a failure: this project's own rule, because a
    configuration fact recorded as incapability is how a harness defect becomes a model's score.
    """
    doc = json.loads(path.read_text())
    solved, unobserved = {}, []
    for r in doc.get("rows", []):
        item = r.get("item_id")
        if not item:
            continue
        if r.get("state") == "unobserved":
            unobserved.append({"item_id": item, "reason": r.get("unobserved_reason")})
            continue
        solved[item] = (r.get("state") == SOLVED)
    return solved, unobserved


def two_sided_exact(b: int, c: int) -> float:
    """Exact two-sided p for the discordant pairs under the null that each is equally likely either way.

    A binomial sign test on b + c trials, which is McNemar's exact form. Written out rather than pulled from a
    dependency so the arithmetic is inspectable: at these counts the whole question is whether a handful of
    discordant items could have fallen the way they did by chance.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def discordance_interval(b: int, c: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """A confidence interval on the accuracy gap, from the discordant pairs.

    Required beside the test, not instead of it. "No detectable difference" is a statement about power, and at two
    discordant pairs out of twenty-one items the interval spans about fourteen points -- so quoting the p-value
    alone invites the reader to hear "no difference", which is a different and false claim.

    The gap is (b - c) / n and its variance under the paired design is (b + c - (b - c)^2 / n) / n^2, which is the
    standard McNemar-style interval. Written out so the arithmetic is inspectable at these small counts.
    """
    if n <= 0:
        return (0.0, 0.0)
    diff = (b - c) / n
    var = max(0.0, (b + c - (b - c) ** 2 / n)) / (n ** 2)
    half = z * sqrt(var)
    return (max(-1.0, diff - half), min(1.0, diff + half))


def paired(a_solved: dict, b_solved: dict) -> dict:
    shared = sorted(set(a_solved) & set(b_solved))
    both = [i for i in shared if a_solved[i] and b_solved[i]]
    a_only = [i for i in shared if a_solved[i] and not b_solved[i]]
    b_only = [i for i in shared if not a_solved[i] and b_solved[i]]
    neither = [i for i in shared if not a_solved[i] and not b_solved[i]]
    p = two_sided_exact(len(a_only), len(b_only))
    lo, hi = discordance_interval(len(a_only), len(b_only), len(shared))
    return {
        "items_compared": len(shared),
        "a_only_excluded": sorted(set(a_solved) - set(b_solved)),
        "b_only_excluded": sorted(set(b_solved) - set(a_solved)),
        "table": {"both": len(both), "a_only": len(a_only), "b_only": len(b_only),
                  "neither": len(neither)},
        "items": {"both": both, "a_only": a_only, "b_only": b_only, "neither": neither},
        "a_solved": len(both) + len(a_only),
        "b_solved": len(both) + len(b_only),
        "discordant": len(a_only) + len(b_only),
        "exact_p_two_sided": round(p, 6),
        # The interval belongs beside the p-value and never after it. At two discordant pairs this spans about
        # fourteen points, so a p of 1.0 quoted alone reads as "no difference", which it is not.
        "gap_a_minus_b": round((len(a_only) - len(b_only)) / len(shared), 6) if shared else None,
        "gap_ci95": [round(lo, 6), round(hi, 6)],
        "gap_ci95_points": [round(lo * 100, 1), round(hi * 100, 1)],
        "reading": (
            "the discordant pairs are what carry information here: the marginals can differ while the arms "
            f"agreed on all but {len(a_only) + len(b_only)} item(s). "
            + ("With no discordant items the arms were identical on this set."
               if len(a_only) + len(b_only) == 0 else
               f"Of those, {len(a_only)} went to A and {len(b_only)} to B, which under an even split has "
               f"two-sided p = {p:.4f}")),
        "not_a_verdict": ("at these counts an exact test rarely separates two arms, and a p above any threshold "
                          "is not evidence they are the same -- the interval above says how large a difference "
                          "this could still have missed. The named items are the useful output: they say WHERE "
                          "the arms differ, which a marginal cannot"),
    }


def exclusion_balance(a_unobs: list, b_unobs: list, compared: int) -> dict:
    """Whether the excluded items fall on one arm, which can manufacture the result.

    A review put this exactly right: excluding items an arm did not observe is correct, and if every exclusion sits
    on one arm then the comparison quietly dropped that arm's hardest attempts. On the pair measured here the split
    was two and one, so it did not -- but the check has to exist, because "excluding them is right" and "excluding
    them changed the answer" are both true statements about the same act.
    """
    a, b = len(a_unobs), len(b_unobs)
    total = a + b
    one_sided = total >= 2 and (a == 0 or b == 0)
    return {
        "excluded_a": a, "excluded_b": b, "total": total,
        "one_sided": one_sided,
        "share_of_compared": (round(total / (compared + total), 4) if compared + total else None),
        "reading": ("no items were excluded" if total == 0 else
                    (f"all {total} exclusions fall on one arm, so the comparison dropped that arm's attempts and "
                     "kept the other's. Read the transcripts before quoting the marginals: an exclusion that is "
                     "the model declining to act is a capability failure, and excluding it flatters that arm"
                     if one_sided else
                     f"{a} on A and {b} on B, so the exclusions are not concentrated on one arm")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="joined output for arm A")
    ap.add_argument("--b", required=True, help="joined output for arm B")
    ap.add_argument("--out")
    args = ap.parse_args()

    a_solved, a_unobs = outcomes_by_item(Path(args.a))
    b_solved, b_unobs = outcomes_by_item(Path(args.b))
    res = paired(a_solved, b_solved)
    res["unobserved"] = {"a": a_unobs, "b": b_unobs}
    res["exclusion_balance"] = exclusion_balance(a_unobs, b_unobs, res["items_compared"])

    t = res["table"]
    print(f"items compared {res['items_compared']}   A solved {res['a_solved']}   B solved {res['b_solved']}")
    print(f"  both {t['both']}   A only {t['a_only']}   B only {t['b_only']}   neither {t['neither']}")
    print(f"  gap (A - B) {res['gap_a_minus_b']:+.4f}, 95% interval "
          f"[{res['gap_ci95_points'][0]:+.1f}, {res['gap_ci95_points'][1]:+.1f}] points")
    print(f"  {res['reading']}")
    if res["items"]["a_only"]:
        print(f"  A solved and B did not: {res['items']['a_only']}")
    if res["items"]["b_only"]:
        print(f"  B solved and A did not: {res['items']['b_only']}")
    print(f"  exclusions: {res['exclusion_balance']['reading']}")
    for side in ("a", "b"):
        for u in res["unobserved"][side]:
            print(f"  [{side}] {u['item_id']} unobserved ({u['reason']}) -- excluded, not counted as a failure")
    excluded = res["a_only_excluded"] + res["b_only_excluded"]
    if excluded:
        print(f"  excluded for being attempted by one arm only: {excluded}")
    print(f"  {res['not_a_verdict']}")
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1) + "\n")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
