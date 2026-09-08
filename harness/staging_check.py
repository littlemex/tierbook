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

#: What a test session leaves in the scorer's output, across **every runner family in the item set** rather than the
#: one that was looked at first. This pattern was wrong twice, in the two ways a precondition can be worse than no
#: precondition:
#:
#: 1. It had a leading `\b`. The recorded tails carry newlines as the two literal characters `\` and `n`, so in
#:    `\nPASSED` the character before `P` is a word character and `\bPASSED` matches nothing. All four arms were
#:    reported unreadable.
#: 2. It knew only pytest. Django's instances run unittest and report `Ran 111 tests in 0.236s` followed by `OK`, so
#:    three django runs per arm were reported as having no checkout when their trees were fine.
#:
#: 3. It equated "tests ran" with "a checkout was there". A run on `pytest-dev__pytest-7432` had a real tree --
#:    `/testbed/src/_pytest/skipping.py` appears in its traceback -- and the agent's own edit crashed pytest with
#:    `INTERNALERROR`, so `no tests ran in 0.06s`. That is a legitimate result about the candidate, and calling it a
#:    missing checkout blames the harness for the agent's patch.
#:
#: So what this actually detects is **the runner having started against a tree**, which is the thing that separates a
#: staged workspace from an empty one. Whether the tests then passed, failed, or could not run at all is the scorer's
#: business, not this file's.
#:
#: The rule the second mistake teaches: a detector for a precondition has to be validated against every family in the
#: item set, not against the first family read. The families here are pytest and unittest.
RUNNER_STARTED = re.compile(
    r"\d+ (?:passed|failed|error)"            # pytest summary
    r"|PASSED |FAILED "                       # pytest verbose
    r"|=+ (?:test session starts|short test)"  # pytest header
    r"|Ran \d+ tests? in "                    # unittest, which django uses
    r"|OK \(skipped=|FAILED \(failures=|FAILED \(errors="  # unittest verdicts
    r"|no tests ran in |INTERNALERROR|ERROR collecting |ImportError while loading"  # the runner started and died
)

#: The scorer saying an instance cannot be scored HERE, whatever the tree contained. `pylint-dev__pylint-4551` reports
#: `fail_to_pass=ids this checkout does not contain` in all three recorded arms: pytest collected its test module, so
#: the checkout was real, and the instance is still permanently unscoreable. That is a different fact from a missing
#: checkout and it belongs in a different bucket -- it is a fact about the ITEM SET, not about a run.
UNSCOREABLE = re.compile(r'"scoreable":\s*false|cannot be scored|could not be scored')

#: The status the driver exits with when setup failed before the agent started. A run carrying it is not evidence
#: about a candidate at all.
SETUP_FAILED = 91

#: Reasons the harness recorded for not observing a run, which are facts about the harness rather than the candidate.
#: `execution_error` is the one that happened: a run edited a file and then the kubectl stream died with
#: `read: can't assign requested address`, so its work exists and was never scored. Treating that as an agent that
#: failed would charge the candidate for the operator's network.
HARNESS_REASONS = frozenset({"execution_error", "transport_error", "timeout"})


def verdict(row: dict, manifest_run: dict | None) -> tuple[str, str]:
    """One run: `staged`, `setup-failed`, `no-checkout`, or `unknown`, and why."""
    if manifest_run is not None and (manifest_run.get("setup_failed")
                                     or manifest_run.get("returncode") == SETUP_FAILED):
        return "setup-failed", ("the driver reported a setup failure, so this run is not evidence about a candidate")
    if row.get("unobserved_reason") in HARNESS_REASONS:
        return "harness-error", (f"the harness recorded {row['unobserved_reason']!r}, so this run's work exists and "
                                 f"was never scored; it is a fact about the harness and not the candidate")
    oracle = row.get("oracle") or {}
    tail = oracle.get("tail") or ""
    if UNSCOREABLE.search(tail):
        # Checked before the test-session pattern, because such a run often shows collection output too and the
        # question "was there a checkout" is the less useful of the two answers when the item can never be scored.
        return "unscoreable", ("the scorer says this instance cannot be scored in this environment, so the run's "
                               "outcome is fixed regardless of what the agent did")
    if RUNNER_STARTED.search(tail):
        return "staged", ("the test runner started against the returned tree, which an empty or stale workspace "
                          "cannot produce; whether the tests then passed is the scorer's business")
    if not tail:
        return "unknown", ("no scorer output was recorded, so nothing here says whether a checkout was present")
    return "no-checkout", ("the scorer produced output but no test session, which is what an empty or stale tree "
                           "looks like")


def check(outcomes: Path, manifests: list, expect_items: int | None = None) -> dict:
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
    # A truncated arm. The reason this is here: a DNS failure on the operator's machine ended a 24-item sweep after 18,
    # and every instrument downstream read 18 rows as a complete cohort. An arm missing a quarter of its items is not
    # a smaller arm, it is an arm whose missing items are correlated with whatever broke.
    short = expect_items is not None and len(per_run) < expect_items
    return {
        "expected_items": expect_items,
        "short": short,
        "runs": len(per_run),
        "counts": counts,
        "per_run": per_run,
        # The arm is readable only when every run had a checkout. One that did not is not a data point about a
        # candidate, and leaving it in the denominator credits the arm with a failure the harness caused.
        # An unscoreable item does not make an arm unreadable -- it is constant across arms and cannot flatter one --
        # but it must come out of the denominator, so it is reported separately and named.
        "unscoreable_items": [r["item_id"] for r in per_run if r["verdict"] == "unscoreable"],
        "scoreable_runs": counts.get("staged", 0),
        "readable": (len(per_run) > 0 and not short
                     and counts.get("staged", 0) + counts.get("unscoreable", 0) == len(per_run)),
        "note": ("a precondition rather than an analysis: an arm with any run that did not get a checkout cannot be "
                 "read, because a run whose tree was never staged looks exactly like an agent that ran and edited "
                 "nothing -- the distinction the workspace-binding investigation turned on"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outcomes", required=True)
    ap.add_argument("--manifests", default=None, help="directory holding the driver's runs-*.json")
    ap.add_argument("--expect-items", type=int, default=None,
                    help="how many runs this arm should have. A transient network failure truncated one sweep at 18 "
                         "of 24 and every instrument downstream read it as complete")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    manifests = sorted(Path(a.manifests).glob("runs-*.json")) if a.manifests else []
    res = check(Path(a.outcomes), manifests, a.expect_items)
    print(f"{res['runs']} runs  " + "  ".join(f"{k} {v}" for k, v in sorted(res['counts'].items())))
    for r in res["per_run"]:
        if r["verdict"] != "staged":
            print(f"  {r['verdict']:14} {r['item_id']}  -- {r['why']}")
    if res["unscoreable_items"]:
        print(f"  NOT IN THE DENOMINATOR of any rate, in any arm: {res['unscoreable_items']}")
    if res["short"]:
        print(f"  TRUNCATED: {res['runs']} runs recorded of {res['expected_items']} expected")
    print(f"\nreadable = {res['readable']}   scoreable runs = {res['scoreable_runs']}/{res['runs']}")
    if not res["readable"]:
        print("  " + res["note"])
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1))
    return 0 if res["readable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
