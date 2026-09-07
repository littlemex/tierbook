"""Compare the gateway's own ledger against the sum of the per-call usage it reported.

Two independent views of one quantity, which is how this project found every real defect in its accounting so
far -- a fourth spelling of a cache-write leg, two conventions for one number, and an arm whose requests carried
no history. This is the check that was available last time and was not run.

The two views:

    ledger      the gateway's usage figure, read before and after a run        (the gateway, aggregate)
    per call    the usage each reply reported, summed                          (the gateway, per request)

They are the same authority at two granularities, so a disagreement is not a matter of opinion: either something
consumed the ledger that was not part of this run, or replies were not all recorded, or the ledger counts
something the replies do not report. Each of those is worth knowing and none of them is an average.

The ledger figure has a property worth stating because it decides how this is used: it is a rolling window over
the account, so any other traffic in the same window lands in it. A delta is attributable to a run only if
nothing else was running -- which is a condition on the experiment, not on this file, and it is exactly the
condition a contaminated reading here already violated once.

SCOPE (see ../SCOPE.md, which governs this file): an instrument. It reports; it decides nothing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def sum_calls(path: Path) -> dict:
    """Sum what the replies reported, over the requests the translator forwarded."""
    fresh = read = write = out = calls = refused = undelivered = 0
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("refused"):
            refused += 1
            continue
        if r.get("delivered") is False:
            undelivered += 1
        u = r.get("usage") or {}
        fresh += int(u.get("prompt_tokens") or 0)
        read += int(u.get("cache_read_input_tokens") or 0)
        write += int(u.get("cache_creation_input_tokens") or 0)
        out += int(u.get("completion_tokens") or 0)
        calls += 1
    return {"calls": calls, "refused": refused, "undelivered": undelivered,
            "fresh_in": fresh, "cached_in": read, "cache_write": write, "out": out,
            "total": fresh + read + write + out}


def compare(ledger_delta: int, calls: dict, *, tolerance: float) -> dict:
    """The two figures, their ratio, and whether the difference is inside a stated tolerance.

    Never averaged. A gap is reported with both numbers and the reader decides what it means, because the two
    explanations -- other traffic in the window, or replies that went unrecorded -- point in opposite directions.
    """
    total = calls["total"]
    gap = ledger_delta - total
    ratio = (ledger_delta / total) if total else None
    return {
        "ledger_delta": ledger_delta,
        "per_call_total": total,
        "gap": gap,
        "ratio": (round(ratio, 6) if ratio is not None else None),
        "within_tolerance": (ratio is not None and abs(ratio - 1.0) <= tolerance),
        "legs": {k: calls[k] for k in ("fresh_in", "cached_in", "cache_write", "out")},
        "calls": calls["calls"],
        "refused": calls["refused"],
        "undelivered": calls["undelivered"],
        "reading": ("the ledger exceeds the replies, which is what other traffic in the same window looks like"
                    if gap > 0 else
                    "the replies exceed the ledger, which is what an unrecorded ledger update or a "
                    "double-counted reply looks like" if gap < 0 else
                    "the two views agree exactly"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True, type=int, help="the ledger figure read before the run")
    ap.add_argument("--after", required=True, type=int, help="the ledger figure read after it")
    ap.add_argument("--requests", required=True, help="the translator's request log, one JSON object per line")
    ap.add_argument("--tolerance", type=float, default=0.02,
                    help="fractional difference treated as agreement. Not a pass mark: the gap is reported "
                         "either way, because a small gap and a large one have different causes")
    ap.add_argument("--out")
    a = ap.parse_args()

    calls = sum_calls(Path(a.requests))
    res = compare(a.after - a.before, calls, tolerance=a.tolerance)
    print(f"ledger delta {res['ledger_delta']:,}   per-call sum {res['per_call_total']:,}   "
          f"ratio {res['ratio']}")
    print(f"  legs {res['legs']}")
    print(f"  {res['calls']:,} calls recorded, {res['refused']} refused, {res['undelivered']} undelivered")
    print(f"  {res['reading']}")
    if not res["within_tolerance"]:
        print(f"\nDIVERGENCE beyond {a.tolerance:.1%}. Not averaged: either something outside this run consumed "
              "the ledger, or not every reply was recorded, and those point in opposite directions.")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
        print(f"\nwrote {a.out}")
    return 0 if res["within_tolerance"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
