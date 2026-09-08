"""Everything one arm supports, in an order that cannot be skipped.

The precondition is a gate here rather than a query somebody remembers to run, because that is the difference the
last few rounds cost. `staging_check.py` exists because a setup failure was indistinguishable from an agent that ran
and edited nothing; having written it, running it *after* reading an arm's solve counts would put it back to being a
footnote. So this refuses to print a rate at all when the arm is not readable.

Three things, in this order, and the first can stop the other two:

1. **Was every run given a checkout?** An arm with a run whose tree was never staged cannot be read: that run looks
   exactly like an agent that did nothing. Items the scorer reports as unscoreable are named and taken out of the
   denominator instead -- they are constant across arms and cannot flatter one.
2. **Did every run stay in its own workspace?** From the telemetry, with the count of correct self-references beside
   the errors, because "zero errors" and "never wrote an absolute path" are the same number otherwise. The naming
   scheme is printed too: the near-miss rule reads differently under each, so comparing that column across schemes is
   not one metric measured twice, and the reader should not have to infer which they are looking at.
3. **What did it solve**, over the scoreable items only, with the zero-edit count beside it -- which is where the
   effect of the last change actually showed, while the paired discordance table was structurally blind to it.

It prints no verdict about a candidate and compares no arms. `paired_arms.py` does that, and it should be run on an
arm this has already accepted.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_json(argv: list, out: Path) -> dict:
    """Run one instrument and read its artifact, so its own refusals are preserved rather than reimplemented here."""
    proc = subprocess.run([sys.executable, *argv, "--out", str(out)], capture_output=True, text=True)
    if not out.exists():
        raise SystemExit(f"REFUSED: {argv[0]} produced no artifact.\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}")
    return json.loads(out.read_text())


def solves(outcomes: Path, exclude: set) -> dict:
    rows = [json.loads(l) for l in outcomes.read_text().splitlines() if l.strip()]
    kept = [r for r in rows if r.get("item_id") not in exclude]
    solved = [r["item_id"] for r in kept if r.get("state") == "solved"]
    # A run that edited nothing. The failure the workspace-binding change was written from, and the metric that read
    # most cleanly across its three arms -- 2, 2, 0 -- while the paired table could not see it, because an item one
    # arm never attempted is excluded from a discordance rather than scored as a failure.
    #
    # `files_touched` must be PRESENT and zero. Absent is not zero: some oracle records carry only `rc` and `tail`,
    # and `astropy__astropy-14369` is one of them in an arm where it SOLVED. A first version read the missing key as
    # zero and reported 8, 9 and 6 zero-edit runs against the true 2, 2 and 0 -- including a solved run in all three.
    zero_edit = [r["item_id"] for r in kept
                 if (r.get("oracle") or {}).get("files_touched") == 0]
    return {"scoreable": len(kept), "solved": len(solved), "solved_items": sorted(solved),
            "zero_edit": len(zero_edit), "zero_edit_items": sorted(zero_edit),
            "excluded_unscoreable": sorted(exclude)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outcomes", required=True)
    ap.add_argument("--traces", required=True)
    ap.add_argument("--manifests", required=True, help="directory holding the driver's runs-*.json")
    ap.add_argument("--expect-items", type=int, default=None)
    ap.add_argument("--out", required=True, help="directory for the artifacts")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    outcomes = Path(a.outcomes)

    print("=== 1. was every run given a checkout? ===")
    staging = run_json([str(HERE / "staging_check.py"), "--outcomes", a.outcomes, "--manifests", a.manifests],
                       out / "staging.json")
    counts = "  ".join(f"{k} {v}" for k, v in sorted(staging["counts"].items()))
    print(f"    {staging['runs']} runs  {counts}")
    if staging["unscoreable_items"]:
        print(f"    out of the denominator in every arm: {staging['unscoreable_items']}")
    if not staging["readable"]:
        for r in staging["per_run"]:
            if r["verdict"] not in ("staged", "unscoreable"):
                print(f"    {r['verdict']:14} {r['item_id']} -- {r['why']}")
        # The gate. Printing a rate below this line would be the whole defect this file exists to prevent.
        raise SystemExit("REFUSED: this arm is not readable, so no rate is computed. A run whose tree was never "
                         "staged looks exactly like an agent that ran and edited nothing.")

    print("\n=== 2. did every run stay in its own workspace? ===")
    audit_argv = [str(HERE / "workspace_audit.py"), "--traces", a.traces, "--outcomes", a.outcomes,
                  "--manifests", a.manifests]
    if a.expect_items:
        audit_argv += ["--expect-items", str(a.expect_items)]
    audit = run_json(audit_argv, out / "workspace-audit.json")
    print(f"    naming scheme: {audit['naming_scheme']}")
    print(f"    clean {audit['clean']}/{audit['runs']}   "
          f"named own ws {audit['runs_that_named_their_own_workspace']}/{audit['runs']} "
          f"({audit['own_workspace_refs']} refs)   "
          f"own id wrong {audit['with_mangled_own_workspace']}   "
          f"another item's ws {audit['with_other_run_workspaces']}   "
          f"refused {audit['with_refusals']}")
    print(f"    mechanism_pass = {audit['mechanism_pass']}")

    print("\n=== 3. what it solved, over the scoreable items only ===")
    got = solves(outcomes, set(staging["unscoreable_items"]))
    print(f"    solved {got['solved']}/{got['scoreable']}   zero-edit runs {got['zero_edit']}")
    if got["zero_edit_items"]:
        print(f"    edited nothing: {got['zero_edit_items']}")

    (out / "arm.json").write_text(json.dumps({"staging": staging, "audit": audit, "solves": got}, indent=1))
    print(f"\nwrote {out}/arm.json")
    print("no verdict about a candidate is printed here, and no arms are compared: run paired_arms.py on an arm this "
          "has accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
