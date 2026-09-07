"""Where each arm's tokens went, because that is what a break-even price is made of.

The first real pair made this necessary. Two arms doing the same 24 tasks came out at 14.3 million tokens and 23.6
million -- and the difference was not effort but **caching**: the self-hosted arm read 12.97 million of its 14.29
from a prefix cache, so only 1.22 million were fresh, while the metered path cached nothing and re-sent every
history as fresh input. A break-even of $0.69 per million tokens looks low until that 19-fold difference in fresh
input is visible, and then it is the whole story.

So the split is reported as its own step rather than buried in a total. A single number would have made the two
arms look like they did different amounts of work.

SCOPE (see ../SCOPE.md, which governs this file): an instrument. It reports; it decides nothing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BILLED = ("fresh_in", "cached_in", "cache_write", "out")


def split(path: Path) -> dict:
    doc = json.loads(path.read_text())
    legs = dict.fromkeys(BILLED, 0)
    turns = 0
    for r in doc.get("rows", []):
        for k in BILLED:
            legs[k] += int((r.get("legs") or {}).get(k) or 0)
        turns += int(r.get("turns") or 0)
    total_in = legs["fresh_in"] + legs["cached_in"] + legs["cache_write"]
    return {
        **legs,
        "total": sum(legs.values()),
        "input_total": total_in,
        # The figure that explained the pair. A cache hit rate near zero means every turn re-sends its history at
        # the fresh rate, which is where a token total goes when nothing is cached.
        "cache_hit_rate": (round(legs["cached_in"] / total_in, 4) if total_in else None),
        "turns": turns,
        "rows": len(doc.get("rows", [])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--joined", action="append", required=True)
    ap.add_argument("--label", action="append", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    if len(a.joined) != len(a.label):
        raise SystemExit("[FAIL] one --label per --joined")

    rows = []
    for path, label in zip(a.joined, a.label):
        rows.append({"label": label, **split(Path(path))})
    for r in rows:
        hit = "-" if r["cache_hit_rate"] is None else f"{r['cache_hit_rate']:.1%}"
        print(f"{r['label']:14s} fresh {r['fresh_in']:>12,}  cached {r['cached_in']:>12,}  "
              f"write {r['cache_write']:>9,}  out {r['out']:>9,}  cache hit {hit:>6}  turns {r['turns']:>5}")
    if len(rows) == 2 and rows[0]["fresh_in"] and rows[1]["fresh_in"]:
        a_, b_ = rows
        print(f"  fresh input ratio {b_['label']}/{a_['label']}: "
              f"{b_['fresh_in'] / a_['fresh_in']:.1f}x")
        print("  A break-even price is per token, so an arm that caches nothing pays the fresh rate on every "
              "turn's history. That ratio, not effort, is usually what separates two totals")
    if a.out:
        Path(a.out).write_text(json.dumps({"arms": rows}, indent=1) + "\n")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
