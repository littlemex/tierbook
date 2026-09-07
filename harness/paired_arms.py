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
from math import comb
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


def paired(a_solved: dict, b_solved: dict) -> dict:
    shared = sorted(set(a_solved) & set(b_solved))
    both = [i for i in shared if a_solved[i] and b_solved[i]]
    a_only = [i for i in shared if a_solved[i] and not b_solved[i]]
    b_only = [i for i in shared if not a_solved[i] and b_solved[i]]
    neither = [i for i in shared if not a_solved[i] and not b_solved[i]]
    p = two_sided_exact(len(a_only), len(b_only))
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
        "reading": (
            "the discordant pairs are what carry information here: the marginals can differ while the arms "
            f"agreed on all but {len(a_only) + len(b_only)} item(s). "
            + ("With no discordant items the arms were identical on this set."
               if len(a_only) + len(b_only) == 0 else
               f"Of those, {len(a_only)} went to A and {len(b_only)} to B, which under an even split has "
               f"two-sided p = {p:.4f}")),
        "not_a_verdict": ("at these counts an exact test rarely separates two arms, and a p above any threshold "
                          "is not evidence they are the same. The named items are the useful output: they say "
                          "WHERE the arms differ, which a marginal cannot"),
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

    t = res["table"]
    print(f"items compared {res['items_compared']}   A solved {res['a_solved']}   B solved {res['b_solved']}")
    print(f"  both {t['both']}   A only {t['a_only']}   B only {t['b_only']}   neither {t['neither']}")
    print(f"  {res['reading']}")
    if res["items"]["a_only"]:
        print(f"  A solved and B did not: {res['items']['a_only']}")
    if res["items"]["b_only"]:
        print(f"  B solved and A did not: {res['items']['b_only']}")
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
