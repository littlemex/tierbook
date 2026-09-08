"""Whether a run stayed inside its own workspace, read from the telemetry it already emits.

The mechanism check a change contract made a pass condition. A run's outcome cannot say this: an agent that
wandered outside its workspace, was refused, and gave up produces the same `unobserved` as one that had nothing to
say, and an agent that wandered and recovered produces a `solved` with the wandering invisible. Both happened in
one 24-item cohort.

What the recordings showed, and why the check is worth having as code rather than as a query somebody remembers to
run: in the first baseline, 6 of 24 runs had a refused tool call and **none of the 10 that solved did**; in its
replicate, 10 of 24 did. One agent truncated its own workspace path by a single character and was refused for naming
a directory that did not exist; another asked to search `/`; another tried to clone the repository from the internet.
None of it appears in a solve rate.

The "none that solved" half holds for refusals and not for the wandering itself: one run in the replicate wrote its
own workspace id wrong in a call the permission system allowed -- it checks the named argument and that call put the
wrong id in the command string -- and went on to solve. So this reports two different things, and only the refusals
line up with failing.

**What counts as outside.** A tool argument naming a path that resolves outside the run's own workspace, or a
shell command naming one. The run's workspace comes from the driver's manifest. When that is missing it can be
recovered from the returned tar's name -- which is how it had to be recovered once, after a second sweep overwrote
the manifest -- but only for an arm whose workspaces were named after the session. The driver now names a workspace
after its item, so that fallback is dated, says so, and is no longer needed: manifests are keyed by run group and a
later sweep cannot overwrite an earlier one's record.

**What this cannot see, stated because a review found the prose claiming otherwise.** It reads the arguments a
model passed, not the syscalls that followed. A repository script, a build step, a hook or a subprocess can reach
anywhere and only the outer command is recorded. A symlink under the workspace can resolve outside it and this has
no filesystem to check against. A path assembled from a variable at run time is invisible. A delegated subagent
carries its own trace and is audited as its own run or not at all. And an earlier version of this paragraph said a
path without a leading slash is "relative to the workspace by construction" -- `../..` is relative and leaves,
which is now checked, but the general claim was false and is withdrawn. Proving containment needs the sandbox's own
audit events; this reports what the model asked for.

**This one does decide something**, unlike the other instruments here, and the difference is deliberate: a change
contract made "no run left its workspace" a pass condition, so there has to be one place that says whether it
held. It returns a non-zero exit status when it did not. What it still does not decide is anything about a
candidate -- no outcome, no rate, no policy.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath

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

#: Arguments that can actually reach the network. **Reported, and not part of the verdict.** Two reviews landed on
#: this from opposite sides: the contract's mechanism condition is about the workspace, so failing a run for a URL
#: was a clause nothing licensed -- and the check was incoherent besides, exempting a real `webfetch` while failing
#: a URL inside a shell string. Since the prompt no longer claims the environment is offline, there is nothing left
#: for a network clause to verify. It stays as an observation because "did any run try to fetch the repository" is
#: worth being able to answer.
#:
#: Scanning the whole argument blob over-fired on the first real cohort: it flagged a `webfetch` -- a tool whose
#: entire purpose is the network, used by a run that solved -- and an `edit` whose file content contained a URL.
NETWORK_KEYS = ("command", "url")
NETWORK = re.compile(r"https?://|git@|github\.com|pypi\.org")

#: Tools whose job is to reach the network. Using one is a tool-policy question for whoever granted it, not
#: evidence that a run wandered out of its directory. They are still reported: one solved run fetched 5,010 bytes
#: from raw.githubusercontent.com, which is how the prompt's claim to be offline was found to be false.
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
SHELL_PATH = re.compile(r"(?<![\w/*?\].)])(/[\w./~-]+)")

#: Commands whose arguments are filesystem locations. This is what let the shell signal back into the verdict after
#: the bare regex had to be taken out of it: a review pointed out that removing it left the verdict blind to an
#: absolute path in a `bash` string that does not happen to look like a workspace -- `/repo`, `/workspace`, `/etc`.
#:
#: Reading paths only from the arguments of these commands separates the two cases that the bare regex could not. A
#: `python3 -c "...J/m/s/kpc2..."` never reaches the scan, because its first token is not one of these; an
#: `ls /tmp/run-opencode-c4cd6ae898/...` does, because it is. Both are real commands from the cohort.
SHELL_FS_COMMANDS = frozenset({
    "ls", "cat", "cd", "cp", "mv", "rm", "find", "head", "tail", "grep", "touch", "mkdir", "rmdir", "stat",
    "chmod", "chown", "ln", "du", "wc", "diff", "sed", "awk", "tar", "rsync", "less", "more", "file", "realpath",
})
#: Where one command ends and the next begins, so `cd /a && ls /b` is read as two commands rather than one.
SHELL_SPLIT = re.compile(r"(?:&&|\|\||[;\n|])")
SHELL_BENIGN = ("/dev", "/proc", "/sys", "/usr", "/bin", "/lib", "/etc/ssl", "/opt", "/var/tmp/pytest",
                "/sbin", "/tmp/pytest-of-")

#: A workspace-shaped path: the driver's workspaces are `/tmp/run-<agent>-<id>`, and one of that shape which is not
#: this run's is precise enough to carry a verdict, unlike the general shell-path scan. `_classify_foreign` splits
#: it three ways -- see there for why two was not enough.
#:
#: What this check added, stated precisely because a review pointed out it had been overstated. Of the six runs
#: below, **four were already flagged by the named-argument scan** as holding a path outside the workspace, and only
#: two -- both astropy -- were visible through the shell string alone. So the shell scan did not discover the class;
#: it was necessary for two of six. What is entirely new is the RECOGNITION: the named-argument scan reported
#: `path=/tmp/run-opencode-9ef07f4b` the same way it reports `path=/` or `path=/tmp`, and nothing said that string
#: was a near-miss of the run's own workspace. That is the difference between "the agent looked outside" and "the
#: agent could not reproduce its own path", and only the second says anything about why.
#:
#: The largest class is the agent writing its own ten-character random id wrong: `0ae4d3229d` as `d3229d` (its own
#: six-character suffix), `9ef07f454b` as `9ef07f4b`, `daf8d8a993` as `daf8d8a93` and `8c042ffb40` as `8c042ffb4`
#: (characters dropped), and `415edc1dee` as `415edc17` -- which is **not** a dropped character: it keeps the
#: seven-character prefix `415edc1` and then invents a `7` that appears nowhere in the source. A review caught that
#: "dropping characters" was wrong for one of the five, and the difference matters, because an invented character is
#: not a truncation of anything and cannot be explained by a display that cut the string short.
#: **Six runs over the two baselines, on five distinct items of the twenty-four** -- 12.5% of runs and
#: 20.8% of items, and an earlier version of this note called it "a quarter of the cohort", which was wrong on both
#: readings. It is still much sharper evidence for the premise behind the workspace-binding change than the two
#: zero-edit runs the contract was written from, and it points at a harness-side fix the contract put out of scope:
#: a workspace name short enough to reproduce would remove the failure at the source, where prompt text only asks
#: the model to try.
#:
#: Two things that note also got wrong, both of which weaken the association it was drawing. Not every such call was
#: refused, and one of the six runs **solved**: `astropy__astropy-14995` ran `ls /tmp/run-opencode-daf8d8a93/` with
#: `workdir` set to the correct `daf8d8a993`, so the permission system -- which checks the argument, not the command
#: string -- allowed it, and the run went on to solve. A path written wrong is therefore not by itself a doomed run.
#:
#: That same call is the strongest evidence about *why* these appear, because it carries the correct id and the wrong
#: one in one tool call: whatever the model was working from, it had the right string in front of it. Against the
#: alternative that the wrong string was copied from something the agent read, every occurrence of all five wrong
#: ids across both baselines sits in `tool.parameters` -- the field the model writes -- and in no other recorded
#: field. That check is bounded: the telemetry carries `tool.result_size_bytes` and not tool results, so a result
#: containing the wrong id cannot be excluded from telemetry alone.
#:
#: The narrowest class is contamination. One agent **attempted** it and was refused:
#: `cp /tmp/run-opencode-700cd74ee4/.../qdp.py /tmp/run-opencode-c4cd6ae898/.../qdp.py`, aiming its edit at a
#: DIFFERENT run's directory left on disk by an earlier sweep. **The `cp` was refused, so no copy happened** -- an
#: earlier version of this note said it did, which the audit's own `refused` field contradicts. What did go through
#: was the `ls` of both paths immediately before it, so the other run's tree was readable. A run that writes into
#: another run's workspace could change that run's result with nothing downstream showing where it came from, and
#: the only reason this one did not is the permission system.
#: Both naming schemes, because the recorded arms used one and everything after uses the other, and an audit that
#: only knew the current one would report a clean arm for every cohort already measured.
OTHER_WORKSPACE = re.compile(r"/tmp/(?:run-[\w.-]+|w/[\w.-]+)")


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
            # Only valid for a run whose workspace was named after its session. The driver now names a workspace
            # after its ITEM, so this reconstruction is right for the recorded arms and wrong for anything measured
            # after that change -- and it says which it is rather than returning a path with no provenance. What
            # replaced the need for it is manifests keyed by run group, so a later sweep no longer overwrites the
            # record this was invented to recover.
            return f"/tmp/run-{stem}", ("recovered from the returned tar's name, valid only for an arm whose "
                                        "workspaces were named after the session; no manifest carried this trace")
    return None, "no manifest and no returned tree, so nothing says where this run was supposed to work"


def _inside(candidate: str, workspace: str | None) -> bool:
    """Whether a path lies within the workspace, after normalising `..`.

    String prefixes are not containment: `/w/../etc` starts with `/w` and is not in it. Normalised lexically
    because there is no filesystem here to resolve against -- which also means a symlink under the workspace
    pointing outside it passes this, and the module docstring says so rather than the check pretending otherwise.
    """
    if not workspace:
        return False
    base = PurePosixPath(workspace)
    target = PurePosixPath(candidate) if candidate.startswith("/") else base / candidate
    # `os.path.normpath` semantics without touching the filesystem.
    parts: list[str] = []
    for part in target.parts:
        if part == "..":
            if parts and parts[-1] not in ("/", ""):
                parts.pop()
            continue
        if part == ".":
            continue
        parts.append(part)
    resolved = PurePosixPath(*parts) if parts else PurePosixPath("/")
    return resolved == base or str(resolved).startswith(str(base).rstrip("/") + "/")


def _id_lengths(known_workspaces) -> set:
    """How long a real workspace id is, taken from the workspaces the driver actually created rather than written
    here as a constant. If a future driver changes the length this follows it."""
    out = set()
    for w in known_workspaces or ():
        tail = str(w).rstrip("/").rsplit("-", 1)[-1]
        if tail:
            out.add(len(tail))
    return out


def _fs_command_paths(cmd: str, workspace: str | None) -> list:
    """Absolute paths sitting where a filesystem command expects one.

    Unlike `SHELL_PATH` over the whole string, this one carries the verdict, because the thing that made the bare
    regex unusable -- arithmetic in a `python3 -c` string reading as directories -- cannot appear here: a segment
    whose first word is not a filesystem command is not read at all.
    """
    out = []
    for segment in SHELL_SPLIT.split(cmd):
        words = segment.split()
        if not words:
            continue
        # Skip a leading environment assignment or `sudo`-style prefix so `FOO=1 ls /x` is still an `ls`.
        i = 0
        while i < len(words) and ("=" in words[i] and not words[i].startswith("/")):
            i += 1
        if i >= len(words):
            continue
        name = words[i].rsplit("/", 1)[-1]
        if name not in SHELL_FS_COMMANDS:
            continue
        for w in words[i + 1:]:
            w = w.strip("\"'`()")
            if not w.startswith("/"):
                continue
            if w.startswith(tuple(SHELL_BENIGN)) or w in ("/", "//"):
                continue
            if not _inside(w, workspace):
                out.append(w)
    return out


def _edits(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein distance, stopping once it exceeds `cap`.

    Here to catch the case the length rule cannot: a same-length single-character substitution. The changed-prompt
    arm produced `a933f30189` where the run's own workspace was `a932f30189` -- ten characters either way, so a rule
    that only compares lengths files it as undecidable and the count stops being comparable across arms.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


#: How far a written id may be from the run's own before it stops being a plausible transcription of it. Two, because
#: every observed case is one or two edits away -- a dropped character, a substituted one, a kept suffix -- and
#: because a random ten-hex id is astronomically unlikely to land that close by chance.
MAX_ID_EDITS = 2


def own_workspace_refs(params_json: str, workspace: str | None) -> int:
    """How many times one call named the run's own workspace correctly.

    The denominator a review asked for. "Zero near-misses" is also what a run that never wrote an absolute path
    produces, and those two are opposite results -- one is the fix working and the other is a run with nothing to say.
    Separate from `audit_call` because it is a tally rather than a finding, and folding it into that return value
    would give every consumer a dict shape it does not expect.
    """
    if not workspace:
        return 0
    try:
        args = json.loads(params_json or "{}")
    except json.JSONDecodeError:
        return 0
    n = 0
    for v in list(args.values()):
        if isinstance(v, str):
            n += sum(1 for hit in OTHER_WORKSPACE.findall(v) if _inside(hit, workspace))
    return n


def _classify_foreign(hit: str, workspace: str | None, known_workspaces: set | None,
                      known_items: set | None = None) -> str:
    """Three answers, not two, because the evidence supports three.

    A path in `known_workspaces` is another run's real directory: contamination. One whose id is not even the right
    LENGTH was never a directory -- it is the agent reproducing its own ten-character random id from memory and
    dropping characters, which happened six times across two baseline runs. And one that is well formed but absent
    from the manifests is genuinely undecidable, because the manifests are not a complete history: they are keyed by
    item, so a later sweep overwrites an earlier one's files. Calling that third case a mangled id is what this
    function did first, and it mislabelled `c4cd6ae898` -- a real workspace from the first baseline whose manifest
    the second baseline had overwritten."""
    if hit.rstrip("/") in (known_workspaces or ()):
        return "other_run"
    leaf = hit.rstrip("/").rsplit("/", 1)[-1]
    # A leaf that IS another item's id is that item's workspace, whatever its edit distance from this run's. Under the
    # old random-hex naming an id within two edits of the run's own was almost certainly a mistranscription; under
    # item naming it is often a real sibling -- `astropy__astropy-14365` and `astropy__astropy-14369` are one edit
    # apart and both are in the 24-item set, `pydata__xarray-4695` and `pydata__xarray-4094` are two. Without this,
    # reaching into a sibling's workspace (contamination) gets filed as writing your own id wrong (a slip), which is
    # the less serious of the two readings. The manifest check above catches it only for items that have already run,
    # so mid-arm it was live.
    if known_items and leaf in known_items and leaf != (workspace or "").rstrip("/").rsplit("/", 1)[-1]:
        return "other_run"
    tail = hit.rstrip("/").rsplit("-", 1)[-1]
    own_tail = (workspace or "").rstrip("/").rsplit("-", 1)[-1]
    # First: is it a near-miss of THIS run's own id? That is the strongest evidence available and it does not depend
    # on the manifests being complete, which they are not.
    if own_tail and 0 < _edits(tail, own_tail, MAX_ID_EDITS) <= MAX_ID_EDITS:
        return "mangled_own"
    if not known_workspaces:
        return "other_run"
    lengths = _id_lengths(known_workspaces)
    if lengths and len(tail) not in lengths:
        return "mangled_own"
    return "shaped_but_unknown"


def audit_call(name: str, params: str, success, error: str, workspace: str | None,
               known_workspaces: set | None = None, known_items: set | None = None) -> dict | None:
    """One finding for one tool call, or None when there is nothing to say about it."""
    try:
        args = json.loads(params or "{}")
    except json.JSONDecodeError:
        args = {}
    refused = success is False and REFUSED in (error or "")
    outside = []
    for key in PATH_KEYS:
        v = args.get(key)
        if isinstance(v, str) and v and (v.startswith("/") or ".." in v):
            if not _inside(v, workspace):
                outside.append(f"{key}={v}")
    network = any(isinstance(args.get(k), str) and NETWORK.search(args[k]) for k in NETWORK_KEYS)
    network_tool = name in NETWORK_TOOLS
    # A shell command's own paths. Read from the string because there is no argument to read, which makes this the
    # weakest part of the audit and better than the alternative of not looking.
    shell_outside = []
    shell_fs_outside = []
    other_workspaces = []
    cmd = args.get("command")
    if isinstance(cmd, str) and workspace:
        for hit in SHELL_PATH.findall(cmd):
            if hit.startswith(tuple(SHELL_BENIGN)) or hit in ("/", "//"):
                continue
            if _inside(hit, workspace):
                continue
            if hit not in shell_outside:
                shell_outside.append(hit)
        for hit in _fs_command_paths(cmd, workspace):
            if hit not in shell_fs_outside:
                shell_fs_outside.append(hit)
    mangled = []
    shaped_unknown = []

    def _foreign(text):
        for hit in OTHER_WORKSPACE.findall(text):
            if _inside(hit, workspace):
                continue
            kind = _classify_foreign(hit, workspace, known_workspaces, known_items)
            bucket = {"other_run": other_workspaces, "mangled_own": mangled}.get(kind, shaped_unknown)
            if hit not in bucket:
                bucket.append(hit)

    if isinstance(cmd, str) and workspace:
        _foreign(cmd)
    for key in PATH_KEYS:
        v = args.get(key)
        if isinstance(v, str) and workspace:
            _foreign(v)
    if not (outside or network or network_tool or refused or shell_outside or other_workspaces or mangled
            or shaped_unknown or shell_fs_outside):
        return None
    return {"tool": name, "outside_workspace": outside, "network": network or network_tool,
            "network_via_granted_tool": network_tool, "refused": refused,
            # Attribution, which the contract's pass condition asks for: a refusal that came with an
            # out-of-workspace path or a fetch is this change's business, and one the tool raised about its own
            # arguments is not.
            "refused_for_a_path": bool(refused and (outside or shell_outside or network)),
            # Kept apart from `outside_workspace`: one is a named argument the tool contract defines, the other is
            # a string this file parsed, and they do not deserve the same confidence.
            "shell_paths_outside": shell_outside,
            # The half of the shell signal that carries the verdict: a path where a filesystem command expects one.
            "shell_fs_paths_outside": shell_fs_outside,
            "other_run_workspaces": other_workspaces,
            "mangled_own_workspace": mangled,
            "workspace_shaped_but_unknown": shaped_unknown,
            "args": (params or "")[:200]}


def audit(traces: Path, outcomes: Path, manifests: list[Path], expect_items: int | None = None) -> dict:
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

    # Which naming scheme this cohort used. Reported because the near-miss rule reads differently under each, so a
    # column compared across schemes is not one metric measured twice -- a review's point, and the reason this is a
    # field rather than something a reader has to infer from the paths.
    #
    # `session-named` is `/tmp/run-<agent>-<10 random hex>`, where any id within two edits of the run's own was
    # almost certainly a mistranscription. `item-named` is `/tmp/w/<instance-id>`, where an id that close is often a
    # real sibling item -- which is now discriminated by the item set, but the false-negative profile still differs.

    # Every workspace the driver ever created, so a shape-matching path that is not among them can be told apart
    # from one that is: the first is an id the agent wrote wrong, the second is a directory belonging to another run.
    known = set()
    for m in manifests:
        try:
            doc = json.loads(m.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for r in (doc if isinstance(doc, list) else doc.get("runs", [])):
            if isinstance(r, dict) and r.get("workspace"):
                known.add(str(r["workspace"]).rstrip("/"))

    # Every item in the cohort, so a path naming a sibling item can be told from a mistranscription of this run's own
    # name. Read from the outcomes rather than configured, because the outcomes are the cohort by definition.
    items = {r.get("item_id") for r in rows.values() if r.get("item_id")}

    schemes = set()
    per_run = []
    for t, row in sorted(rows.items(), key=lambda kv: kv[1].get("item_id") or ""):
        ws, ws_source = workspace_of(t, manifests, row.get("returned"))
        if ws:
            schemes.add("item-named" if ws.startswith("/tmp/w/") else "session-named")
        findings = [f for f in (audit_call(n, p, ok, e, ws, known, items) for n, p, ok, e in calls[t]) if f]
        refs = sum(own_workspace_refs(p, ws) for _, p, _, _ in calls[t])
        did, why = attempted(row.get("oracle"), row.get("state"))
        per_run.append({
            "item_id": row.get("item_id"), "state": row.get("state"), "trace_id": t,
            "workspace": ws, "workspace_source": ws_source,
            "attempted": did, "attempted_note": why,
            # The denominator: how often this run named its own workspace correctly.
            "own_workspace_refs": refs,
            "tool_calls": len(calls[t]),
            "outside_workspace": sum(1 for f in findings if f["outside_workspace"]),
            "shell_paths_outside": sum(1 for f in findings if f["shell_paths_outside"]),
            "shell_fs_paths_outside": sum(1 for f in findings if f["shell_fs_paths_outside"]),
            "other_run_workspaces": sum(1 for f in findings if f["other_run_workspaces"]),
            "mangled_own_workspace": sum(1 for f in findings if f["mangled_own_workspace"]),
            "workspace_shaped_but_unknown": sum(1 for f in findings if f["workspace_shaped_but_unknown"]),
            "network": sum(1 for f in findings if f["network"]),
            "refused": sum(1 for f in findings if f["refused"]),
            "refused_for_a_path": sum(1 for f in findings if f["refused_for_a_path"]),
            "findings": findings,
        })
    clean = [r for r in per_run if not r["outside_workspace"] and not r["network"] and not r["refused"]
             and not r["shell_paths_outside"] and not r["shell_fs_paths_outside"]
             and not r["other_run_workspaces"]
             and not r["mangled_own_workspace"] and not r["workspace_shaped_but_unknown"]]
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
        "with_shell_fs_paths_outside": sum(1 for r in per_run if r["shell_fs_paths_outside"]),
        "naming_scheme": (sorted(schemes)[0] if len(schemes) == 1 else
                          ("mixed:" + ",".join(sorted(schemes)) if schemes else "unknown")),
        "own_workspace_refs": sum(r["own_workspace_refs"] for r in per_run),
        "runs_that_named_their_own_workspace": sum(1 for r in per_run if r["own_workspace_refs"]),
        "with_other_run_workspaces": sum(1 for r in per_run if r["other_run_workspaces"]),
        "with_mangled_own_workspace": sum(1 for r in per_run if r["mangled_own_workspace"]),
        "with_workspace_shaped_but_unknown": sum(1 for r in per_run if r["workspace_shaped_but_unknown"]),
        "with_network": sum(1 for r in per_run if r["network"]),
        "with_refusals": sum(1 for r in per_run if r["refused"]),
        "with_path_refusals": sum(1 for r in per_run if r["refused_for_a_path"]),
        "solved_with_refusals": sum(1 for r in per_run if r["refused"] and r["state"] == "solved"),
        "workspace_unknown": unknown_ws,
        "no_tool_calls": silent,
        # The cohort has to be the one the pass condition names. An empty outcomes file has no out-of-workspace
        # paths, no unknown workspaces and no silent runs, so it would otherwise pass -- a verdict manufactured by
        # missing data rather than by behaviour.
        "expected_items": expect_items,
        "cohort_complete": (expect_items is None or len(per_run) == expect_items),
        "not_attempted": [r["item_id"] for r in per_run if not r["attempted"]],
        "per_run": per_run,
        # Every clause of the contract's pass condition, including the refusal one it used to drop. The two halves
        # are redundant on purpose: the refusal count is the backstop for exactly the paths the argument scan
        # cannot see, and an earlier version kept the fragile half and ignored the robust one.
        "mechanism_pass": (bool(per_run)
                           and (expect_items is None or len(per_run) == expect_items)
                           # Shell-parsed paths are NOT in the verdict: on real data the parser read unit
                           # expressions like `J/m/s/kpc2` out of a Python comment as directories, and a pass
                           # condition cannot rest on that. What replaces them is precise -- another run's
                           # workspace, which has an unambiguous shape and a real consequence.
                           and sum(1 for r in per_run
                                   if r["outside_workspace"] or r["other_run_workspaces"]
                                   or r["mangled_own_workspace"] or r["workspace_shaped_but_unknown"]
                                   or r["shell_fs_paths_outside"] or r["refused_for_a_path"]) == 0
                           and not unknown_ws and not silent),
        "mechanism_note": ("across every run and without reference to any outcome, the verdict is against: an "
                           "out-of-workspace path in a named argument; one parsed out of a shell command, which is "
                           "weaker evidence, reported and NOT counted because it read unit expressions out of a "
                           "Python comment as directories; a workspace-shaped path that is not this run's, split "
                           "three ways because two was not enough -- one the manifests know (contamination, found "
                           "happening), one whose id is not even the right length (the agent writing its own id "
                           "wrong, six times across two baselines), and one well formed but absent from a manifest "
                           "set that is not a complete history -- all three counting; a permission refusal "
                           "attributable to one of "
                           "those or to a fetch, which is the backstop for paths the argument scan cannot see; a run "
                           "whose workspace could not be established, since an unknown workspace cannot be "
                           "audited; and a run that made no tool calls, since doing nothing would otherwise "
                           "satisfy staying put. Two things are reported and do NOT count against: a refusal the "
                           "tool raised about its own arguments, and reaching the network -- the contract's "
                           "condition is about the workspace, and since the prompt no longer claims to be offline "
                           "there is nothing for a network clause to verify"),
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
    ap.add_argument("--expect-items", type=int, default=None,
                    help="how many runs this cohort must contain. Without it an outcomes file missing rows -- or "
                         "empty -- passes the check, which is a verdict manufactured by absent data")
    ap.add_argument("--manifests", default=None,
                    help="directory holding the driver's runs-*.json, for the workspace of each trace")
    ap.add_argument("--out")
    a = ap.parse_args()
    # Both spellings: sweeps before the run group was added to the name wrote `runs-{instance}.json`, and those
    # manifests are still the only record of where those runs worked.
    manifests = sorted(Path(a.manifests).glob("runs-*.json")) if a.manifests else []
    res = audit(Path(a.traces), Path(a.outcomes), manifests, a.expect_items)

    print(f"[{res['naming_scheme']}] {res['runs']} runs   clean {res['clean']}   out-of-workspace {res['with_outside_paths']}   "
          f"other run's workspace {res['with_other_run_workspaces']}   "
          f"own id written wrong {res['with_mangled_own_workspace']}   "
          f"workspace-shaped but unknown {res['with_workspace_shaped_but_unknown']}   "
          f"named own ws {res['runs_that_named_their_own_workspace']}/{res['runs']} runs "
          f"({res['own_workspace_refs']} refs)   "
          f"shell fs-arg {res['with_shell_fs_paths_outside']}   "
          f"shell parsed (reported only) {res['with_shell_paths_outside']}   network {res['with_network']}   "
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
            if f["workspace_shaped_but_unknown"]:
                bits.append("WORKSPACE-SHAPED, NOT IN ANY MANIFEST "
                            + ", ".join(f["workspace_shaped_but_unknown"][:2]))
            if f["mangled_own_workspace"]:
                bits.append("OWN ID WRITTEN WRONG " + ", ".join(f["mangled_own_workspace"][:2]))
            if f["other_run_workspaces"]:
                bits.append("ANOTHER RUN'S WORKSPACE " + ", ".join(f["other_run_workspaces"][:2]))
            if f["shell_fs_paths_outside"]:
                bits.append("shell fs-arg " + ", ".join(f["shell_fs_paths_outside"][:3]))
            if f["shell_paths_outside"]:
                bits.append("shell " + ", ".join(f["shell_paths_outside"][:3]))
            if f["network"]:
                bits.append("network")
            if f["refused"]:
                bits.append("refused")
            print(f"      {f['tool']:10s} {'; '.join(bits)}")
    if not res["cohort_complete"]:
        print(f"  COHORT INCOMPLETE: {res['runs']} runs against {res['expected_items']} expected")
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
