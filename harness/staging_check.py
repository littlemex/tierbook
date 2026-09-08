"""Whether every run in an arm actually got a checkout, before any of its numbers are read.

A precondition, not an analysis. It exists because a defect made a setup failure indistinguishable from an agent that
ran and edited nothing: the environment exports ended in `; `, which terminated the setup chain, so a failed opening
`rm -rf` staged over a stale tree anyway -- and `exit ${exec_rc:-0}` returned 0 whenever the agent never started,
because that variable is assigned inside the braces. Both are fixed. This is what says whether an arm recorded
*before* the fix, or after it under some other failure, can be read at all.

**What proves a run had a checkout.** Not the archive's size, which a stale tree also has, and not the run's exit
status, which was the thing that lied. The scorer ran the repository's own test suite against the returned tree and
its output says so. A run whose tree was empty or stale cannot produce a test session for that instance.

**What this cannot tell you.** Whether the tree was the *right* revision. It says a repository was there and its
tests ran, which is what separates "the agent had nothing to work with" from "the agent had something and did
nothing" -- the distinction the whole workspace-binding investigation turned on and could not make.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

#: What a pytest session leaves in the scorer's output. Several spellings because the instances span pytest versions
#: and some report only a summary line.
RAN_TESTS = re.compile(r"\b\d+ (?:passed|failed|error)|\bPASSED\b|\bFAILED\b|=+ (?:test session starts|short test)")

#: The status the driver exits with when setup failed before the agent started. A run carrying it is not evidence
#: about a candidate at all.
SETUP_FAILED = 91


def verdict(row: dict, manifest_run: dict | None) -> tuple[str, str]:
    """One run: `staged`, `setup-failed`, `no-checkout`, or `unknown`, and why."""
    if manifest_run is not None and (manifest_run.get("setup_failed")
                                     or manifest_run.get("returncode") == SETUP_FAILED):
        return "setup-failed", ("the driver reported a setup failure, so this run is not evidence about a candidate")
    oracle = row.get("oracle") or {}
    tail = oracle.get("tail") or ""
    if RAN_TESTS.search(tail):
        return "staged", "the scorer ran the repository's own tests against the returned tree"
    if not tail:
        return "unknown", ("no scorer output was recorded, so nothing here says whether a checkout was present")
    return "no-checkout", ("the scorer produced output but no test session, which is what an empty or stale tree "
                           "looks like")


def check(outcomes: Path, manifests: list) -> dict:
    runs = {}
    for m in manifests:
        try:
            doc = json.loads(Path(m).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for r in doc.get("runs", []):
            if r.get("trace_id"):
                runs[r["trace_id"]] = r

    per_run = []
    for line in outcomes.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        v, why = verdict(row, runs.get(row.get("trace_id")))
        per_run.append({"item_id": row.get("item_id"), "state": row.get("state"),
                        "trace_id": row.get("trace_id"), "verdict": v, "why": why})

    counts = {}
    for r in per_run:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {
        "runs": len(per_run),
        "counts": counts,
        "per_run": per_run,
        # The arm is readable only when every run had a checkout. One that did not is not a data point about a
        # candidate, and leaving it in the denominator credits the arm with a failure the harness caused.
        "readable": len(per_run) > 0 and counts.get("staged", 0) == len(per_run),
        "note": ("a precondition rather than an analysis: an arm with any run that did not get a checkout cannot be "
                 "read, because a run whose tree was never staged looks exactly like an agent that ran and edited "
                 "nothing -- the distinction the workspace-binding investigation turned on"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outcomes", required=True)
    ap.add_argument("--manifests", default=None, help="directory holding the driver's runs-*.json")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    manifests = sorted(Path(a.manifests).glob("runs-*.json")) if a.manifests else []
    res = check(Path(a.outcomes), manifests)
    print(f"{res['runs']} runs  " + "  ".join(f"{k} {v}" for k, v in sorted(res['counts'].items())))
    for r in res["per_run"]:
        if r["verdict"] != "staged":
            print(f"  {r['verdict']:14} {r['item_id']}  -- {r['why']}")
    print(f"\nreadable = {res['readable']}")
    if not res["readable"]:
        print("  " + res["note"])
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1))
    return 0 if res["readable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
