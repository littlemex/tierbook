"""Measure a served candidate's throughput against concurrency, so a capacity bound can be derived.

This exists because the compiler has exactly one derived threshold -- the occupancy at which a reserved
candidate stops absorbing work -- and nothing measured it. Without it no rule can fire, every request takes the
declared default, and the box the owner decided to keep is unreachable through the policy. One measurement
unblocks that, and it is this one.

**Why a curve and not a number.** A single reading at concurrency 1 says how fast a continuously busy
sequential worker completes tasks. It is not throughput under load and it does not bound it: contention, cache
pressure, batching behaviour, replica imbalance and throttling can leave throughput flat or lower it as
concurrency rises. So the shape has to be observed, and the bound read off where it stops rising.

**Why the workload has to be the real one.** Throughput is a property of the pair, not of the engine: a
prefill-heavy agent turn and a short chat turn saturate a batching engine at different concurrencies. So this
replays a captured request rather than generating a synthetic one, and refuses to run without it -- a curve
measured on the wrong shape is a threshold for a workload nobody has.

What this does NOT establish, stated because a curve invites more confidence than it earns:

- Any statement about a different model, request shape, or serving configuration. Those need their own curve,
  which is the point of the curve being data rather than a constant.
- A steady state. Each point is a closed batch: startup and drain are inside the window, so a small `--rounds`
  measures the transient as much as the plateau. Points run once, in increasing order, with no warm-up and no
  interval -- so a bound read off one run is a reading, not an estimate with a confidence.
- Correctness. An HTTP 200 counts as completed work here; whether the reply was right, or truncated at the
  token cap, is the oracle's question and this does not ask it.
- Independence between families. Replaying one request encourages prefix caching and homogeneous batching, and a
  production mix does neither.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def one_call(endpoint: str, payload: dict, timeout: int) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions", data=body,
                                headers={"content-type": "application/json"})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            doc = json.load(r)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        return {"ok": False, "wall_s": time.time() - started, "error": str(e)[:200]}
    u = doc.get("usage") or {}
    return {"ok": True, "wall_s": time.time() - started,
            "prompt_tokens": int(u.get("prompt_tokens") or 0),
            "completion_tokens": int(u.get("completion_tokens") or 0)}


def measure(endpoint: str, payload: dict, *, concurrency: int, rounds: int, timeout: int) -> dict:
    """Tasks per hour at one concurrency, measured over a closed window.

    Throughput is completed work divided by the wall time the whole batch took, not the reciprocal of a mean
    latency. Those differ once requests queue, and the second is the one that reads high.
    """
    calls = concurrency * rounds
    started = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda _: one_call(endpoint, payload, timeout), range(calls)))
    elapsed = time.time() - started
    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    return {
        "concurrency": concurrency,
        "calls": calls,
        "completed": len(ok),
        "failed": len(failed),
        "failures": [r["error"] for r in failed[:3]],
        "elapsed_s": round(elapsed, 2),
        # Completed work over the window. A failed call consumed capacity and produced nothing, so it is
        # excluded from the numerator and NOT from the window -- which is what makes an overloaded point look
        # overloaded instead of fast.
        "tasks_per_hour": round(len(ok) / elapsed * 3600, 1) if elapsed > 0 else None,
        "mean_latency_s": round(statistics.mean(r["wall_s"] for r in ok), 2) if ok else None,
        "p95_latency_s": (round(sorted(r["wall_s"] for r in ok)[min(len(ok) - 1, int(0.95 * len(ok)))], 2)
                          if ok else None),
        "output_tokens_total": sum(r.get("completion_tokens", 0) for r in ok),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--request", required=True,
                    help="a captured request to replay, from harness/trajectory.py --out. Required: a curve "
                         "measured on a synthetic shape is a threshold for a workload nobody has")
    ap.add_argument("--concurrency", default="1,2,4,8,16",
                    help="the concurrencies to probe. At least two, or nothing can be said about where "
                         "throughput stops rising")
    ap.add_argument("--rounds", type=int, default=2, help="batches per concurrency, so each point is not one "
                                                          "sample")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    doc = json.loads(Path(a.request).read_text())
    ctx = doc.get("context") or doc.get("messages")
    if not ctx:
        raise SystemExit(f"[FAIL] {a.request} carries no context to replay")
    payload = {"model": a.model, "max_tokens": a.max_tokens, "temperature": 0,
               "messages": [{k: v for k, v in m.items()
                             if k in ("role", "content", "name", "tool_calls", "tool_call_id")
                             and v is not None}
                            for m in ctx if m.get("content") or m.get("tool_calls")]}
    levels = [int(x) for x in a.concurrency.split(",") if x.strip()]
    if len(levels) < 2:
        raise SystemExit("[FAIL] at least two concurrencies are needed; one point cannot show where "
                         "throughput stops rising")

    print(f"probing {a.model} at {levels}, {a.rounds} round(s) each, "
          f"{len(payload['messages'])} messages per call")
    points = []
    for c in levels:
        r = measure(a.endpoint, payload, concurrency=c, rounds=a.rounds, timeout=a.timeout)
        points.append(r)
        print(f"  c={c:3d}  completed {r['completed']}/{r['calls']}  {r['elapsed_s']:7.2f}s  "
              f"{r['tasks_per_hour']} tasks/hour  mean {r['mean_latency_s']}s"
              + (f"  FAILED {r['failed']}" if r["failed"] else ""))

    # Every point, including one that completed nothing. Dropping zero-throughput points removes total overload
    # from the data the compiler reads, so the curve would show a candidate that never fails.
    curve = {str(p["concurrency"]): p["tasks_per_hour"] for p in points}
    Path(a.out).write_text(json.dumps({
        "endpoint": a.endpoint, "model": a.model, "request": a.request,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "rounds_per_point": a.rounds, "max_tokens": a.max_tokens,
        "points": points, "curve": curve,
        "workload_note": "measured by replaying a captured request, so this curve describes THIS request shape "
                         "on THIS serving configuration and nothing else. A different shape saturates a "
                         "batching engine at a different concurrency",
    }, indent=1) + "\n")
    failed_points = [p["concurrency"] for p in points if p["failed"]]
    if failed_points:
        print(f"\n[WARN] calls failed at concurrencies {failed_points}. A point with failures is not a clean "
              "capacity reading, and the bound derivation excludes it rather than treating a partial batch as a "
              "throughput")
    print(f"\ncurve: {curve}")
    print(f"wrote {a.out}")
    rising = [c for c, _ in sorted(((int(k), v) for k, v in curve.items()))]
    if len(rising) < 2:
        print("[WARN] fewer than two usable points; no bound can be derived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
