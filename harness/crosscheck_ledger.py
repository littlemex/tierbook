"""Reconcile the gateway's aggregate ledger against the sum of the per-call usage it reported.

**A reconciliation, not a cross-check, and the difference is not pedantic.** Both figures come from the gateway's
own accounting, so a systematic error in that accounting produces perfect agreement here. A review caught the
overclaim -- this file had been described as two independent views, while its own text said "the same authority
at two granularities". What it can find is a bookkeeping gap: traffic outside the run, replies that went
unrecorded, or a leg the aggregate counts and the replies do not. What it cannot find is the gateway being wrong
about tokens.

    ledger      the gateway's usage figure, read before and after a run        (the gateway, aggregate)
    per call    the usage each reply reported, summed                          (the gateway, per request)

A genuinely independent view would be a different producer: the agent's own telemetry, the translator's byte and
message counts, or an invoice generated outside this path. Those exist in this project and are compared
elsewhere; this file is the cheap consistency step, and it is worth running because two of the three defects
found in this project's accounting were bookkeeping gaps of exactly this kind.

A disagreement is never averaged: either something consumed the ledger that was not part of this run, or replies
were not all recorded, and those point in opposite directions.

**The ledger is a rolling window**, so a delta is attributable to a run only if the interval is shorter than that
window and nothing else consumed it. Entries expiring between the two reads move the delta down with no traffic
at all, which is a second way a contaminated reading can look clean.

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


def sum_calls(path: Path, keep: set[str] | None = None) -> dict:
    """Sum what the replies reported, over the requests the translator forwarded.

    An unparseable line is counted and named rather than skipped: an audit instrument that silently ignores what
    it cannot read is reporting a total over an unknown subset.
    """
    fresh = read = write = out = calls = refused = undelivered = 0
    unparseable = []
    for n, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            unparseable.append(n)
            continue
        if keep is not None and r.get("trace_id") not in keep:
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
            "unparseable_lines": unparseable,
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
        "not_an_independent_check": ("both figures come from the gateway's own accounting, so a systematic error "
                                    "there produces agreement here. This finds bookkeeping gaps, not a wrong "
                                    "meter"),
        "reading": ("the ledger exceeds the replies, which is what other traffic in the same window looks like, "
                    "or entries expiring from a rolling window"
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
    ap.add_argument("--trace-ids", default=None,
                    help="file of trace ids, one per line, restricting the sum to one cohort. Without it every "
                         "parseable record is summed, which is right for a log written by one run and wrong for "
                         "one that outlived another")
    ap.add_argument("--out")
    a = ap.parse_args()

    keep = None
    if a.trace_ids:
        keep = {x.strip() for x in Path(a.trace_ids).read_text().splitlines() if x.strip()}
    calls = sum_calls(Path(a.requests), keep)
    if calls["unparseable_lines"]:
        # Fail closed. A total over an unknown subset is not a total, and this is the one file whose job is to
        # notice that.
        raise SystemExit(f"[FAIL] {len(calls['unparseable_lines'])} unparseable line(s) in {a.requests} at "
                        f"{calls['unparseable_lines'][:8]}; a reconciliation over an unknown subset is not one")
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
