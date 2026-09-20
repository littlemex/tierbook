"""An open-loop load probe that reports what `throughput.Throughput` needs, including when it is lying.

**Why this exists rather than a one-line loop over requests.** Every rate this project has published so far came from a
closed loop -- send, wait, send again -- and a closed loop offers less work when the server slows down, so no queue ever
forms and there is nothing for a deadline to be missed against. Opening the loop reversed one of this project's own
verdicts outright, and it has twice published a load generator's own limit as a box's capacity.

So the probe does three things a naive loop does not:

1. **Arrivals are scheduled, not chained.** The next request goes out at its scheduled instant whether or not the
   previous one came back. That is what makes a queue, and a queue is what a deadline is measured against.
2. **It measures its own lateness.** If the probe could not dispatch an arrival at its scheduled time, the shortfall is
   the probe's and not the box's, and the result is marked `generator_saturated` so nothing downstream reads it as a
   measurement of the server.
3. **It reports a goodput beside the rate.** The mean rate is conserved when box-time moves between request families,
   which makes it blind to the only question a service level asks.

Output is JSON shaped for `throughput.Throughput(**...)`, so the refusals in that module apply to this probe's numbers
the same as to anyone else's.

Run it **beside the thing it measures**. Across a port-forward or a laptop's uplink the number produced is the tunnel's.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

#: How late a dispatch may be before the probe calls itself the bottleneck, in seconds. Not a tuning knob for the
#: result: it is the point past which the arrival process stopped being the one that was asked for, and a number chosen
#: to be well inside the deadlines anyone measures with.
LATENESS_BUDGET_SECONDS = 0.25


def _post(url: str, body: dict, headers: dict, timeout: float) -> tuple[bool, float, int]:
    """One request. Returns whether it completed, how long it took, and how many tokens came back."""
    started = time.monotonic()
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode())
    req.add_header("content-type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read() or b"{}")
        out = int((payload.get("usage") or {}).get("completion_tokens") or 0)
        return True, time.monotonic() - started, out
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False, time.monotonic() - started, 0


def probe(*, url: str, model: str, rate_per_second: float, seconds: float, deadline_seconds: float,
          max_tokens: int, prompt: str, headers: dict, seed: int = 0, seats: int | None = None) -> dict:
    """Drive open-loop arrivals for `seconds` and report the rate, the goodput and the probe's own honesty.

    Arrival instants are drawn as a Poisson process rather than spaced evenly, because an evenly spaced arrival stream
    is a weaker load at the same mean rate: the bursts are where a queue forms, and the queue is the thing under test.
    """
    rng = random.Random(seed)
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.0}

    schedule: list[float] = []
    t = 0.0
    while t < seconds:
        t += rng.expovariate(rate_per_second)
        if t < seconds:
            schedule.append(t)

    latencies: list[float] = []
    completed = 0
    tokens = 0
    lateness: list[float] = []
    inflight = 0
    peak_inflight = 0
    lock = threading.Lock()

    def fire() -> None:
        nonlocal completed, tokens, inflight, peak_inflight
        with lock:
            inflight += 1
            peak_inflight = max(peak_inflight, inflight)
        ok, took, out = _post(url, body, headers, timeout=max(deadline_seconds * 4, 30.0))
        with lock:
            inflight -= 1
            if ok:
                completed += 1
                tokens += out
                latencies.append(took)

    # The pool is sized well above the offered concurrency on purpose. A pool that runs out of threads turns an open
    # loop back into a closed one silently, which is the failure this whole module exists to avoid -- and it would show
    # up as the server slowing down.
    workers = max(32, int(rate_per_second * max(deadline_seconds, 1.0) * 4))
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for when in schedule:
            due = start + when
            now = time.monotonic()
            if now < due:
                time.sleep(due - now)
            else:
                lateness.append(now - due)
            pool.submit(fire)
    wall = time.monotonic() - start

    inside = [x for x in latencies if x <= deadline_seconds]
    worst_lateness = max(lateness) if lateness else 0.0
    saturated = worst_lateness > LATENESS_BUDGET_SECONDS

    # **The case the first real run was in, and the one the lateness check cannot see.** If every request offered came
    # back inside the deadline, no queue ever formed, and a ceiling nothing reached is a ceiling nobody measured -- the
    # rate reported is the rate that was asked for. This is not the generator being the limit (it kept up) and not an
    # offer below the seat count (444 concurrent against 256 seats), which is why it needed its own name.
    #
    # Ordered after saturation deliberately: a probe that fell behind AND absorbed everything is first of all a probe
    # that fell behind, and that is the thing to go and fix.
    absorbed = completed == len(schedule) and len(inside) == completed and completed > 0

    return {
        "per_hour": completed / wall * 3600.0 if wall > 0 else 0.0,
        "arrivals": "open_loop",
        "deadline_seconds": deadline_seconds,
        "goodput_per_hour": len(inside) / wall * 3600.0 if wall > 0 else 0.0,
        # Named from the vocabulary the record module carries, and empty when the probe has no reason to think it
        # understated anything. Empty is a claim, so it is only written when the lateness check passes.
        "understated_because": ("generator_saturated" if saturated else
                                "load_fully_absorbed" if absorbed else ""),
        # The PEAK number of requests actually in flight, not a concurrency derived from rate times latency. The first
        # version reported the derived figure and `Offered` refused it outright -- 0.73 against a field whose minimum is
        # 1 -- which was the right refusal: the field means the load that was offered, and a product of two averages is
        # not something anybody offered. Under an open loop the peak in flight is what the engine was actually asked to
        # admit at once, and it is the number that can be compared against a seat count.
        "offered": {"concurrency": peak_inflight,
                    "seats": seats,
                    "generator": f"open_loop_probe poisson rate={rate_per_second}/s over {wall:.1f}s, "
                                 f"{workers} dispatch threads"},
        "observed": {
            "offered_arrivals": len(schedule),
            "completed": completed,
            "inside_deadline": len(inside),
            "wall_seconds": round(wall, 3),
            "output_tokens": tokens,
            "latency_p50": round(statistics.median(latencies), 3) if latencies else None,
            "latency_p95": round(sorted(latencies)[int(len(latencies) * 0.95)], 3) if latencies else None,
            "worst_dispatch_lateness": round(worst_lateness, 4),
            "late_dispatches": len(lateness),
            "peak_inflight": peak_inflight,
            "absorbed_everything_offered": absorbed,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", required=True, help="the OpenAI-compatible chat completions endpoint")
    ap.add_argument("--model", required=True)
    ap.add_argument("--rate-per-second", type=float, required=True, help="mean arrival rate, not a concurrency")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--deadline-seconds", type=float, required=True,
                    help="what a request has to return inside to count toward goodput")
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--prompt", default="Summarise in one sentence why a queue forms.")
    ap.add_argument("--header", action="append", default=[], metavar="K:V")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seats", type=int, default=None,
                    help="the engine's own admission limit, read from its startup log. Without it nothing downstream "
                         "can tell a saturated box from a starved one")
    a = ap.parse_args(argv)

    headers = {}
    for h in a.header:
        k, _, v = h.partition(":")
        headers[k.strip()] = v.strip()

    got = probe(url=a.url, model=a.model, rate_per_second=a.rate_per_second, seconds=a.seconds,
                deadline_seconds=a.deadline_seconds, max_tokens=a.max_tokens, prompt=a.prompt,
                headers=headers, seed=a.seed, seats=a.seats)
    print(json.dumps(got, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - a command line
    sys.exit(main())
