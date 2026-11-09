"""Send items to arms and record what came back, one JSON line per call, in the shape `tierbook ingest` reads.

Two ways to send, and they record different things:

* **direct** -- every item to every arm in the candidate file. This is how arms are measured before anything routes,
  and how an arm that is not serving gets re-measured.
* **routed** -- every item to a router's entrypoint. The arm is the one the router reports it chose
  (`x-vsr-selected-model`), so these lines are observations of the policy as deployed.

No grading happens here. The completion body is kept so the caller's grader can read it.

    python -I drive.py direct --items items.jsonl --candidates candidates.json --out calls.jsonl --run r1
    python -I drive.py routed --items items.jsonl --router http://127.0.0.1:8801/v1 --model tierbook/routed \
        --out routed.jsonl --run routed-1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone


def post(url: str, body: dict, headers: dict, timeout: float) -> tuple[int, dict, dict, str]:
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode())
    req.add_header("content-type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}"), dict(r.headers), ""
    except urllib.error.HTTPError as e:
        return e.code, {}, dict(e.headers or {}), f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"
    except Exception as e:  # noqa: BLE001 -- a transport failure is an observation, not a crash
        return 0, {}, {}, f"{type(e).__name__}: {e}"


def call(url, model, prompt, headers, max_tokens, timeout, retries):
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
    for attempt in range(retries + 1):
        t0 = time.monotonic()
        status, out, hdrs, err = post(url, body, headers, timeout)
        dt = time.monotonic() - t0
        # Throttling is retried because it says nothing about the arm's answer; anything else is recorded as is.
        if status in (429, 503) and attempt < retries:
            time.sleep(2 ** attempt)
            continue
        return status, out, hdrs, err, dt
    return status, out, hdrs, err, dt


def _auth(api_key_env: str | None) -> dict:
    if not api_key_env:
        return {}
    key = os.environ.get(api_key_env)
    if not key:
        raise SystemExit(f"{api_key_env} is not set")
    return {"authorization": f"Bearer {key}"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("direct", "routed"))
    p.add_argument("--items", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--candidates", help="direct: the arms to send to")
    p.add_argument("--arms", default="", help="direct: a comma list restricting the candidates")
    p.add_argument("--base-url", default=None, help="direct: replace every candidate's base_url (your gateway)")
    p.add_argument("--router", help="routed: the router's OpenAI base URL")
    p.add_argument("--model", default="tierbook/routed", help="routed: the entrypoint name")
    p.add_argument("--router-key-env", default=None)
    p.add_argument("--label-source", default="dataset")
    p.add_argument("--max-tokens", type=int, default=32)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--append", action="store_true", help="append to --out rather than replace it")
    a = p.parse_args(argv)

    items = [json.loads(line) for line in open(a.items) if line.strip()]
    jobs = []
    if a.mode == "direct":
        cands = json.load(open(a.candidates))["candidates"]
        # A cascade has no endpoint of its own: it is measured through its parts.
        wanted = [x for x in a.arms.split(",") if x] or sorted(c for c in cands if "cascade" not in cands[c])
        cascades = [x for x in wanted if "cascade" in cands[x]]
        if cascades:
            raise SystemExit(f"{cascades} are cascades, which have no endpoint; measure their parts")
        for arm in wanted:
            ep = cands[arm]["endpoint"]
            url = (a.base_url or ep["base_url"]).rstrip("/") + "/chat/completions"
            for it in items:
                jobs.append((it, arm, url, ep["model"], _auth(ep.get("api_key_env"))))
    else:
        url = a.router.rstrip("/") + "/chat/completions"
        for it in items:
            jobs.append((it, None, url, a.model, _auth(a.router_key_env)))

    lock = threading.Lock()
    done = [0]
    with open(a.out, "a" if a.append else "w") as f:
        def work(job):
            it, arm, url, model, headers = job
            status, body, hdrs, err, dt = call(url, model, it["prompt"], headers, a.max_tokens, a.timeout, a.retries)
            lower = {k.lower(): v for k, v in hdrs.items()}
            chosen = arm or lower.get("x-vsr-selected-model")
            row = {"item": it["item"], "task_type": it["task_type"], "arm": chosen or "unknown", "run": a.run,
                   "latency_s": round(dt, 4), "observed_at": datetime.now(timezone.utc).isoformat(),
                   "label_source": a.label_source}
            if a.mode == "routed":
                row["router"] = {k: lower[k] for k in lower if k.startswith("x-vsr-")}
            if err or status != 200:
                row["error"] = err or f"HTTP {status}"
            else:
                row["response"] = body
            with lock:
                f.write(json.dumps(row) + "\n")
                f.flush()
                done[0] += 1
                if done[0] % 100 == 0:
                    print(f"  {done[0]}/{len(jobs)}", file=sys.stderr)

        with ThreadPoolExecutor(a.concurrency) as ex:
            list(ex.map(work, jobs))
    print(f"wrote {len(jobs)} calls to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
