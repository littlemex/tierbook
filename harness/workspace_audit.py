"""Whether a run stayed inside its own workspace, read from the telemetry it already emits.

The mechanism check a change contract made a pass condition. A run's outcome cannot say this: an agent that
wandered outside its workspace, was refused, and gave up produces the same `unobserved` as one that had nothing to
say, and an agent that wandered and recovered produces a `solved` with the wandering invisible. Both happened in
one 24-item cohort.

What the recordings showed, and why the check is worth having as code rather than as a query somebody remembers to
run: 6 of 24 runs had a refused tool call and **none of the 10 that solved did**. One agent truncated its own
workspace path by a single character and was refused for naming a directory that did not exist; another asked to
search `/`; another tried to clone the repository from the internet. The permission system was right every time,
and none of it appears in a solve rate.

**What counts as outside.** A tool argument naming an absolute path that is not the run's own workspace, or naming
a network location. A path with no leading slash is relative to the workspace by construction and is not
inspected. The run's workspace comes from the driver's manifest; when that is missing it is recovered from the
returned tar's name, which is how it had to be recovered once already after a second sweep overwrote the manifest.

**This one does decide something**, unlike the other instruments here, and the difference is deliberate: a change
contract made "no run left its workspace" a pass condition, so there has to be one place that says whether it
held. It returns a non-zero exit status when it did not. What it still does not decide is anything about a
candidate -- no outcome, no rate, no policy.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

#: Argument keys that carry a filesystem location. Named rather than pattern-matched over every value, so a
#: pattern like `**/*.py` is not read as a path.
PATH_KEYS = ("path", "filePath", "file_path", "cwd", "directory")

#: A refusal by the permission system, as the tool reports it. The literal string observed in the telemetry is
#: "The user rejected permission to use this specific tool call."; the fixture in the tests is cut from a real
#: span so a change in that wording fails here rather than silently zeroing the count.
REFUSED = "rejected permission"

#: A refusal whose cause is a path or a fetch, as opposed to one the tool raised about its own arguments. The
#: contract's pass condition says "zero permission rejections attributable to a path", and without this
#: distinction a `todowrite` refused for omitting a schema key would count against a change about workspaces.

#: Arguments that can actually reach the network. Scanning the whole argument blob over-fired on the first real
#: cohort: it flagged a `webfetch` -- a tool whose entire purpose is the network, used by a run that solved -- and
#: an `edit` whose *file content* happened to contain a URL. Neither is an agent leaving its workspace, and a
#: pass condition built on that noise would fail runs for writing a docstring.
NETWORK_KEYS = ("command", "url")
NETWORK = re.compile(r"https?://|git@|github\.com|pypi\.org")

#: Tools whose job is to reach the network. Using one is a tool-policy question for whoever granted it, not
#: evidence that a run wandered out of its directory.
NETWORK_TOOLS = frozenset({"webfetch", "websearch"})

#: Absolute paths appearing inside a shell command. A `bash` call can go anywhere and the audit sees only the
#: string, so the string is read: this is weaker than inspecting a named argument and it is the difference between
#: catching `find /tmp -name '*.py'` -- which a real run did -- and not looking at all.
#:
#: Directories every checkout legitimately touches are excluded by prefix rather than by guessing at intent. A
#: command reading /proc or writing /dev/null is not a run leaving its workspace, and flagging those would make
#: the check noise.
#: A slash preceded by a glob character, a bracket or a dot is not the start of an absolute path. Two real
#: commands showed why each exclusion is needed: `*/xarray/*` was read as the directory `/xarray/`, and
#: `find . -path ./tests -prune` was read as `/tests`. Excluded by what precedes the slash rather than by the shape
#: of what follows, because a pattern, a relative path and an absolute one look identical from the right.
SHELL_PATH = re.compile(r"(?<![\w/*?\].])(/[\w./~-]+)")
SHELL_BENIGN = ("/dev/", "/proc/", "/sys/", "/usr/", "/bin/", "/lib", "/etc/ssl", "/opt/", "/var/tmp/pytest",
                "/dev/null")


def workspace_of(trace_id: str, manifests: list[Path], returned: str | None) -> tuple[str | None, str]:
    """The run's workspace, from the driver's manifest, or recovered from the returned tar's name."""
    for m in manifests:
        try:
            doc = json.loads(m.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for r in doc.get("runs", []):
            if r.get("trace_id") == trace_id and r.get("workspace"):
                return r["workspace"], f"the driver's manifest {m.name}"
    if returned:
        stem = Path(returned).stem                      # opencode-8c042ffb40
        if "-" in stem:
            return f"/tmp/run-{stem}", ("recovered from the returned tar's name, because no manifest carried this "
                                        "trace -- a second sweep over the same instances overwrites the first")
    return None, "no manifest and no returned tree, so nothing says where this run was supposed to work"


def audit_call(name: str, params: str, success, error: str, workspace: str | None) -> dict | None:
    """One finding for one tool call, or None when there is nothing to say about it."""
    try:
        args = json.loads(params or "{}")
    except json.JSONDecodeError:
        args = {}
    refused = success is False and REFUSED in (error or "")
    outside = []
    for key in PATH_KEYS:
        v = args.get(key)
        if isinstance(v, str) and v.startswith("/"):
            if not workspace or not (v == workspace or v.startswith(workspace.rstrip("/") + "/")):
                outside.append(f"{key}={v}")
    network = (name not in NETWORK_TOOLS
               and any(isinstance(args.get(k), str) and NETWORK.search(args[k]) for k in NETWORK_KEYS))
    # A shell command's own paths. Read from the string because there is no argument to read, which makes this the
    # weakest part of the audit and better than the alternative of not looking.
    shell_outside = []
    cmd = args.get("command")
    if isinstance(cmd, str) and workspace:
        for hit in SHELL_PATH.findall(cmd):
            if hit.startswith(tuple(SHELL_BENIGN)) or hit in ("/", "//"):
                continue
            if hit == workspace or hit.startswith(workspace.rstrip("/") + "/"):
                continue
            if hit not in shell_outside:
                shell_outside.append(hit)
    if not outside and not network and not refused and not shell_outside:
        return None
    return {"tool": name, "outside_workspace": outside, "network": network, "refused": refused,
            # Attribution, which the contract's pass condition asks for: a refusal that came with an
            # out-of-workspace path or a fetch is this change's business, and one the tool raised about its own
            # arguments is not.
            "refused_for_a_path": bool(refused and (outside or shell_outside or network)),
            # Kept apart from `outside_workspace`: one is a named argument the tool contract defines, the other is
            # a string this file parsed, and they do not deserve the same confidence.
            "shell_paths_outside": shell_outside,
            "args": (params or "")[:200]}


def audit(traces: Path, outcomes: Path, manifests: list[Path]) -> dict:
    rows = {json.loads(l)["trace_id"]: json.loads(l)
            for l in outcomes.read_text().splitlines() if l.strip()}
    calls: dict[str, list] = {t: [] for t in rows}
    for line in traces.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        for rs in doc.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for sp in ss.get("spans", []):
                    t = sp.get("traceId")
                    if t not in calls or not sp.get("name", "").startswith("opencode.tool."):
                        continue
                    a = {x["key"]: next(iter((x.get("value") or {}).values()), None)
                         for x in sp.get("attributes", [])}
                    calls[t].append((a.get("tool.name"), a.get("tool.parameters"),
                                     a.get("tool.success"), a.get("tool.error")))

    per_run = []
    for t, row in sorted(rows.items(), key=lambda kv: kv[1].get("item_id") or ""):
        ws, ws_source = workspace_of(t, manifests, row.get("returned"))
        findings = [f for f in (audit_call(n, p, ok, e, ws) for n, p, ok, e in calls[t]) if f]
        did, why = attempted(row.get("oracle"), row.get("state"))
        per_run.append({
            "item_id": row.get("item_id"), "state": row.get("state"), "trace_id": t,
            "workspace": ws, "workspace_source": ws_source,
            "attempted": did, "attempted_note": why,
            "tool_calls": len(calls[t]),
            "outside_workspace": sum(1 for f in findings if f["outside_workspace"]),
            "shell_paths_outside": sum(1 for f in findings if f["shell_paths_outside"]),
            "network": sum(1 for f in findings if f["network"]),
            "refused": sum(1 for f in findings if f["refused"]),
            "refused_for_a_path": sum(1 for f in findings if f["refused_for_a_path"]),
            "findings": findings,
        })
    clean = [r for r in per_run if not r["outside_workspace"] and not r["network"] and not r["refused"]
             and not r["shell_paths_outside"]]
    unknown_ws = [r["item_id"] for r in per_run if not r["workspace"]]
    # A run that made no tool calls has no out-of-workspace paths, so "clean" would be satisfied by having done
    # nothing. That is the shape of the failure this check was built to find, and it must not be the shape of
    # passing it. Reported separately and counted against the mechanism verdict.
    silent = [r["item_id"] for r in per_run if r["tool_calls"] == 0]
    return {
        "runs": len(per_run),
        "clean": len(clean),
        "with_outside_paths": sum(1 for r in per_run if r["outside_workspace"]),
        "with_shell_paths_outside": sum(1 for r in per_run if r["shell_paths_outside"]),
        "with_network": sum(1 for r in per_run if r["network"]),
        "with_refusals": sum(1 for r in per_run if r["refused"]),
        "with_path_refusals": sum(1 for r in per_run if r["refused_for_a_path"]),
        "solved_with_refusals": sum(1 for r in per_run if r["refused"] and r["state"] == "solved"),
        "workspace_unknown": unknown_ws,
        "no_tool_calls": silent,
        "not_attempted": [r["item_id"] for r in per_run if not r["attempted"]],
        "per_run": per_run,
        # Every clause of the contract's pass condition, including the refusal one it used to drop. The two halves
        # are redundant on purpose: the refusal count is the backstop for exactly the paths the argument scan
        # cannot see, and an earlier version kept the fragile half and ignored the robust one.
        "mechanism_pass": (sum(1 for r in per_run
                               if r["outside_workspace"] or r["network"] or r["shell_paths_outside"]
                               or r["refused_for_a_path"]) == 0
                           and not unknown_ws and not silent),
        "mechanism_note": ("across every run and without reference to any outcome, the verdict is against: an "
                           "out-of-workspace path in a named argument; one parsed out of a shell command, which is "
                           "weaker evidence and is reported apart; a fetch; a permission refusal attributable to "
                           "one of those, which is the backstop for paths the argument scan cannot see; a run "
                           "whose workspace could not be established, since an unknown workspace cannot be "
                           "audited; and a run that made no tool calls, since doing nothing would otherwise "
                           "satisfy staying put. A refusal the tool raised about its own arguments is counted and "
                           "does not count against"),
    }


def attempted(oracle: dict | None, state: str | None = None) -> tuple[bool, str]:
    """Whether a run actually attempted the task, as the contract's second pass condition means it.

    Not "files touched", which a scratch file satisfies -- a review said so and the contract was amended before any
    run. The oracle reports how many files the returned tree differs in and by how many bytes, both measured
    against the staged tree, so a non-empty diff is a change to the repository rather than activity somewhere.

    **Two bases, and which one was used is reported.** The counts are parsed out of the scorer's captured output,
    which is truncated, so six of one cohort's twenty-four runs do not carry them -- including one that solved. The
    fallback is the state: `unobserved/unsupported` is what the scorer produces when zero files differ, so any other
    scored state means the tree did differ. That is weaker evidence and it says so, rather than a solved run being
    reported as never having tried.
    """
    o = oracle or {}
    files = o.get("files_touched")
    nbytes = o.get("diff_bytes")
    if files is not None:
        if not files:
            return False, "zero files differ from the staged tree: nothing was attempted"
        if nbytes is not None and nbytes <= 0:
            return False, f"{files} file(s) differ but the diff is {nbytes} bytes, which is not a change"
        return True, f"{files} file(s) differ from the staged tree, {nbytes} bytes"
    if state in ("solved", "incorrect"):
        return True, ("the oracle's counts were truncated out of its captured output, so this rests on the state: "
                      f"{state!r} means a tree that differed was scored, since zero files differing is recorded as "
                      "unobserved/unsupported instead")
    return False, (f"no diff counts and state {state!r}, so nothing says this run changed anything")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", required=True)
    ap.add_argument("--outcomes", required=True)
    ap.add_argument("--manifests", default=None,
                    help="directory holding the driver's runs-*.json, for the workspace of each trace")
    ap.add_argument("--out")
    a = ap.parse_args()
    # Both spellings: sweeps before the run group was added to the name wrote `runs-{instance}.json`, and those
    # manifests are still the only record of where those runs worked.
    manifests = sorted(Path(a.manifests).glob("runs-*.json")) if a.manifests else []
    res = audit(Path(a.traces), Path(a.outcomes), manifests)

    print(f"{res['runs']} runs   clean {res['clean']}   out-of-workspace {res['with_outside_paths']}   "
          f"shell paths {res['with_shell_paths_outside']}   network {res['with_network']}   "
          f"refused {res['with_refusals']}")
    print(f"  refusals attributable to a path or a fetch: {res['with_path_refusals']} runs; "
          f"of all runs with any refusal, {res['solved_with_refusals']} solved")
    if res["not_attempted"]:
        print(f"  not attempted (no change to the repository): {res['not_attempted']}")
    for r in res["per_run"]:
        if not (r["outside_workspace"] or r["network"] or r["refused"]):
            continue
        print(f"  {r['item_id']:34s} {r['state']:10s} calls {r['tool_calls']:3d}  "
              f"outside {r['outside_workspace']}  network {r['network']}  refused {r['refused']}")
        for f in r["findings"][:4]:
            bits = []
            if f["outside_workspace"]:
                bits.append("outside " + ", ".join(f["outside_workspace"]))
            if f["shell_paths_outside"]:
                bits.append("shell " + ", ".join(f["shell_paths_outside"][:3]))
            if f["network"]:
                bits.append("network")
            if f["refused"]:
                bits.append("refused")
            print(f"      {f['tool']:10s} {'; '.join(bits)}")
    if res["workspace_unknown"]:
        print(f"  workspace unknown for: {res['workspace_unknown']}")
    print(f"  mechanism_pass = {res['mechanism_pass']}")
    print(f"  {res['mechanism_note']}")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
        print(f"\nwrote {a.out}")
    return 0 if res["mechanism_pass"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
