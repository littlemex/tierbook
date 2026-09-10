"""Turn `pending_oracle` rows into stated outcomes, and never into a guess.

The driver records what it observed of a run — did the process exit, did it time out, did it leave a tree —
and writes `state: pending_oracle`, because at that moment nobody has judged anything. This applies the
oracle and replaces that state. Splitting the two is the point: a driver that wrote "solved" because the
process exited zero would be inventing the measurement, and an exit code is not a verdict.

Three states and one rule about them. `solved` and `incorrect` are **observed** outcomes: the oracle ran and
said so. `unobserved` means the oracle could not run or had nothing to judge, and it **carries a reason**.
Folding an unobserved run into `incorrect` is how a configuration fact becomes a capability number — three of
four agents in this cluster silently edited nothing until an autonomy flag was found, and each of those runs
exited zero.

SCOPE (see ../SCOPE.md, which governs this file): an instrument. It states outcomes; it decides nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SOLVED, INCORRECT, UNOBSERVED = "solved", "incorrect", "unobserved"
#: The vocabulary the ledger's evidence loader accepts. Reused rather than re-invented so a row written here
#: cannot be rejected there for a reason that is only a spelling.
REASONS = ("policy_refusal", "unsupported", "execution_error", "not_selected")


def oracle_verdict(instance: str, workspace: str, *, context: str, namespace: str,
                   timeout: int) -> tuple[str, str | None, dict]:
    """Apply the instance's own tests to a returned tree.

    Returns `(state, unobserved_reason, detail)`. The distinctions that matter:

    - the tree was never returned      -> unobserved / execution_error   (the run did not get that far)
    - the tree is identical to staged   -> unobserved / unsupported      (nothing was attempted; see the
                                          module docstring on why this is not `incorrect`)
    - the tests ran and passed          -> solved
    - the tests ran and failed          -> incorrect
    - the scorer itself could not run   -> unobserved / execution_error  (our fault, not the candidate's)
    """
    def score():
        return subprocess.run(
            [sys.executable, str(HERE / "testbed.py"), "score", "--instance", instance,
             "--workspace", workspace, "--context", context, "--namespace", namespace],
            capture_output=True, text=True, timeout=timeout,
        )

    proc = score()
    out = (proc.stdout or "") + (proc.stderr or "")
    # A testbed pod that is gone is our problem to fix, not a verdict about the candidate. It disappears for
    # ordinary reasons -- a node consolidated, a sweep tore it down after the previous instance -- and the
    # first version of this reported the resulting `unobserved/execution_error` as if the run were at fault.
    # Bring it back and judge, once. Still failing after that is a real execution error.
    if "not found" in out and "pods" in out:
        for step in ("up", "put-scorer"):
            subprocess.run([sys.executable, str(HERE / "testbed.py"), step, "--instance", instance,
                            "--context", context, "--namespace", namespace],
                           capture_output=True, text=True, timeout=1200)
        proc = score()
        out = (proc.stdout or "") + (proc.stderr or "")
    detail = {"rc": proc.returncode, "tail": out[-600:]}
    for line in out.splitlines():
        if line.startswith("files touched: "):
            detail["files_touched"] = int(line.split(": ", 1)[1])
        elif line.startswith("diff bytes: "):
            detail["diff_bytes"] = int(line.split(": ", 1)[1])

    if "no returned archive" in out or "no such workspace" in out:
        return UNOBSERVED, "execution_error", detail
    if detail.get("files_touched") == 0:
        return UNOBSERVED, "unsupported", detail
    if '"resolved": true' in out.lower():
        return SOLVED, None, detail
    if '"resolved": false' in out.lower():
        return INCORRECT, None, detail
    # The scorer neither passed nor failed it. That is our failure to judge, not the candidate's failure to
    # solve, and calling it `incorrect` would charge the candidate for our broken harness.
    return UNOBSERVED, "execution_error", detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outcomes", required=True, help="the JSONL the driver appended to, updated in place")
    ap.add_argument("--instance", required=True)
    # No cluster default here on purpose: a default that names one person's context or namespace is a
    # footgun in a public repo, not a convenience -- it lets `--help`'s own output run against somebody
    # else's cluster. Required via the flag or the environment; refused below rather than guessed.
    ap.add_argument("--context", default=os.environ.get("TIERBOOK_K8S_CONTEXT"))
    ap.add_argument("--namespace", default=os.environ.get("TIERBOOK_K8S_NAMESPACE"))
    ap.add_argument("--run-group", help="judge only rows from this invocation. A row from another group is "
                                       "another run's business and is left alone")
    ap.add_argument("--timeout", type=int, default=2400)
    a = ap.parse_args()
    if not a.context:
        ap.error("no --context given and TIERBOOK_K8S_CONTEXT is not set; this will not guess which "
                 "cluster to score against")
    if not a.namespace:
        ap.error("no --namespace given and TIERBOOK_K8S_NAMESPACE is not set; this will not guess which "
                 "namespace to score against")

    path = Path(a.outcomes)
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    pending = [r for r in rows
               if r.get("state") == "pending_oracle" and r.get("item_id") == a.instance
               and (a.run_group is None or r.get("run_group") == a.run_group)]
    if not pending:
        print(f"nothing pending for {a.instance}")
        return 0

    for r in pending:
        if not r.get("returned"):
            r["state"], r["unobserved_reason"] = UNOBSERVED, "execution_error"
            r["oracle"] = {"note": "no returned tree; the run did not reach the point of being judged"}
            print(f"  {r['agent']:11s} unobserved/execution_error (no returned tree)")
            continue
        state, reason, detail = oracle_verdict(a.instance, r["returned"], context=a.context,
                                               namespace=a.namespace, timeout=a.timeout)
        r["state"] = state
        if reason:
            r["unobserved_reason"] = reason
        elif "unobserved_reason" in r:
            del r["unobserved_reason"]
        r["oracle"] = detail
        assert state in (SOLVED, INCORRECT, UNOBSERVED)
        assert reason is None or reason in REASONS
        print(f"  {r['agent']:11s} {state}{'/' + reason if reason else ''} "
              f"(files {detail.get('files_touched')})")

    # Rewritten whole, sorted by trace id, so the file is stable under re-runs and a diff shows only what
    # the oracle changed.
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                            for r in sorted(rows, key=lambda x: (x.get("item_id", ""), x.get("trace_id", "")))))
    still = sum(1 for r in rows if r.get("state") == "pending_oracle")
    print(f"\n{len(pending)} judged, {still} still pending across all items -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
