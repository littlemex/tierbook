"""Give one task to several coding agents under identical conditions, and say which calls were whose.

The comparison this serves holds the model constant -- every agent reaches the same engine through one
Service alias -- so the agent is the only variable and its contribution is what gets measured. That only
works if the conditions really are identical, and three of the ways they quietly stop being identical are
handled here rather than left to a convention.

**A fresh session per run.** Not hygiene: the experiment. One agent was observed sending 258 input tokens
on a call and 15,510 on the next, because the second inherited the first. A run that reuses a session
measures the previous run too.

**A fresh workspace per run.** One agent's leftover files are the next agent's context, and an agent that
finds a half-finished edit behaves differently from one that does not.

**Correlation by time window and address, asking nothing of the agent.** The driver records when a run
started and ended; the tap records every call with its caller's address. Intersecting the two attributes
calls to runs without a header the agent would have to be modified to send -- and modifying the agent is
the one thing this measurement must not do. It is sound because a run is one process in one pod and runs
are sequential per agent, which the driver enforces rather than assumes.

What this deliberately does not do: score anything, price anything, or interpret the agent's output. It
produces a run manifest. Scoring belongs to the task's own oracle and pricing to the ledger, and a driver
that also judged would be a second place that could be wrong about the answer.

Usage:
    python3 harness/agent_drive.py --task "reply with exactly: OK" --tag smoke
    python3 harness/agent_drive.py --task-file t.md --agents opencode,hermes --repeat 3

SCOPE (see ../SCOPE.md, which governs this file): this is an INSTRUMENT that supplies parameters to a
routing mechanism, not the mechanism and not a conclusion. Every environment-specific number it prints --
a seat count, a KV capacity, a break-even concurrency, an agent's token appetite -- is a parameter reading
for one moment in one cluster. The mechanism's job is to re-read them live and decide from them; turning
any of them into advice about a particular deployment is the error this project has made three times.
"""
from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task_prompt  # noqa: E402

HERE = Path(__file__).resolve().parent


def kubectl(context: str, namespace: str, *args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kubectl", "--context", context, "-n", namespace, *args],
        capture_output=True, text=True, timeout=timeout,
    )


def _fill(template: list[str], **kw) -> list[str]:
    return [a.format(**kw) for a in template]


def _shq(s: str) -> str:
    """Single-quote for `sh`. `pre` commands are composed into a shell line, so a value with a space in
    it would otherwise become two arguments."""
    return "'" + s.replace("'", "'\\''") + "'"


def preflight(spec: dict, agent: str, model: str, context: str, namespace: str,
              timeout: int) -> tuple[bool, str]:
    """Prove the agent reaches the alias and resolves the model, before anything is measured.

    A manifest full of 404s looks like a result, and this is not hypothetical: one agent keeps its model
    in pod-local state on the node's ephemeral disk, so a pod restart silently reverted it to a model the
    alias does not serve. Every agent in this cluster was in that state for days and nothing said so.
    """
    session = f"pf-{uuid.uuid4().hex[:8]}"
    argv = _fill(spec["preflight"], model=model, session=session, workspace=f"/tmp/{session}",
                 agent_definition=spec.get("agent_definition", ""),
                 prompt="reply with exactly: PREFLIGHT_OK")
    try:
        proc = kubectl(context, namespace, "exec", f"deploy/{spec['deployment']}", "--", *argv,
                       timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "preflight timed out"
    blob = (proc.stdout or "") + (proc.stderr or "")
    if "PREFLIGHT_OK" in proc.stdout:
        return True, "ok"
    for marker in ("does not exist", "NotFoundError", "404"):
        if marker in blob:
            return False, f"the agent reached the endpoint and the model was refused: {marker}"
    return False, f"rc={proc.returncode}, no PREFLIGHT_OK in output: {blob.strip()[-200:]}"


def new_traceparent() -> tuple[str, str]:
    """A W3C trace context issued BEFORE the run starts, so three sources can meet on it.

    The agent accepts one through an environment variable and emits spans under it, which is what replaces
    joining by time window -- a window join breaks as soon as two runs overlap, and overlapping runs are the
    normal case in a deployment. Issued here rather than read from the telemetry afterwards, because the
    outcome and the charge have to be labelled with the same id and neither of them has seen a span.
    """
    trace_id = secrets.token_hex(16)
    return trace_id, f"00-{trace_id}-{secrets.token_hex(8)}-01"


#: Where a run's own code lives, relative to its workspace. `src` covers the repositories that keep their package
#: under it -- flask and pytest on the pilot subset -- and naming a directory that does not exist costs nothing, which
#: is why this is a constant rather than a per-repository table. The shadowing risk it raises was checked: of the
#: leftover workspaces on the pod, `src/` holds importable names only for flask and pytest, each the repository's own
#: package, while matplotlib's holds C++ sources.
OWN_CODE_SUBDIRS = ("", "src")

#: Where run workspaces live. A workspace is refused unless it sits under this, because the driver removes it with
#: `rm -rf` and that is the one genuinely dangerous line here. Deliberately not `/tmp`: a bug that produced an empty
#: item id would then name `/tmp` itself, and `rm -rf /tmp` on a shared pod takes every other run's tree with it.
WORKSPACE_ROOT = "/tmp/w"

#: The status a run exits with when setup failed before the agent started. Distinct from any agent status so the two
#: can never be confused: a run whose workspace was never staged looks, in an outcome, exactly like an agent that ran
#: and edited nothing -- and that is the signature this whole line of work was chasing.
SETUP_FAILED = 91


def workspace_for(tag: str, template: str | None = None) -> str:
    """A run's workspace, named after its item.

    Named after the item because a model has to reproduce this string from its prompt on every call, and six runs
    across three arms failed to reproduce the ten-character random id it replaces -- one of them with the absolute
    path written in its prompt. `/tmp/w/pydata__xarray-4695` is shorter and every character of it is derivable from
    the task.

    What this gives up: the name identifies an item, not a run, so two concurrent runs of one item would collide.
    Runs are sequential today and this does not make them safe to parallelise.
    """
    if template:
        return guard_workspace(template.format(tag=tag))
    if not tag or not tag.strip():
        raise ValueError("a run needs an item id to name its workspace after")
    return guard_workspace(f"{WORKSPACE_ROOT}/{tag.strip()}")


def guard_workspace(path: str) -> str:
    """Refuse a workspace the driver must not `rm -rf`.

    A separate function with its own tests rather than a condition inside a shell string, because the failure mode is
    deleting something that is not a workspace and a shell string is where that goes unnoticed.
    """
    if not path or not path.startswith("/"):
        raise ValueError(f"a workspace must be an absolute path, and {path!r} is not")
    clean = path.rstrip("/")
    root = WORKSPACE_ROOT.rstrip("/")
    if not clean.startswith(root + "/"):
        raise ValueError(f"a workspace must sit under {root}/, and {path!r} does not; the driver removes it with "
                         f"rm -rf and will not do that outside a directory it owns")
    tail = clean[len(root) + 1:]
    if not tail or tail in (".", "..") or tail.startswith("/"):
        raise ValueError(f"{path!r} has no name below {root}/, so removing it would remove the root")
    if ".." in PurePosixPath(clean).parts:
        raise ValueError(f"{path!r} contains '..', which can resolve outside {root}/")
    # Refused rather than relied on quoting alone. The path is also quoted where it is interpolated, and both are
    # wanted: `rm -rf /tmp/w/x y` unquoted removes `/tmp/w/x` AND the relative path `y`, and a guard that accepts a
    # name it cannot see the consequences of is a guard that documents nothing. SWE-bench instance ids contain none
    # of these, which is the assumption being written down.
    bad = set(clean) & set(" \t\n'\"`$&;|<>()*?[]!#~\\")
    if bad:
        raise ValueError(f"{path!r} contains {sorted(bad)!r}, which the shell would read as syntax rather than as "
                         f"part of a directory name")
    return clean


def python_path_export(workspace: str) -> str:
    """`PYTHONPATH` for one run, as a shell export.

    Absolute and rooted at the run's own workspace, in the order the run's own code should be found. Returns a
    trailing `; ` so it composes with the other exports.
    """
    if not workspace or not workspace.startswith("/"):
        raise ValueError(f"the workspace must be an absolute path, and {workspace!r} is not")
    ws = workspace.rstrip("/")
    entries = [ws if not sub else f"{ws}/{sub}" for sub in OWN_CODE_SUBDIRS]
    return f"export PYTHONPATH={_shq(':'.join(entries))}; "


def build_inner(workspace: str, env: str, pre: str, stage: str, give_back: str, cleanup: bool) -> str:
    """The one shell command a run is: make the workspace, set the environment, stage, work, hand back, sweep up.

    `mkdir` then `cd` then exec, as one command, because the workspace must exist before the agent starts in it and
    `kubectl exec` has no working-directory option.

    Order is load-bearing in two places. The environment is exported **before** the agent starts, so every shell and
    subprocess it spawns inherits `PYTHONPATH`. And the sweep-up comes **after** the hand-back and **before** the
    exit, so the returned archive is complete and the status the driver sees is the agent's own rather than `rm`'s.
    """
    workspace = guard_workspace(workspace)
    quoted = _shq(workspace)
    # `&&` rather than `;` when there is an archive to hand back, so a failed `tar` keeps the tree instead of the
    # driver deleting the only copy of what the run did. A run whose hand-back failed is unscoreable either way; the
    # difference is whether it can be looked at. With no archive there is nothing to depend on, so `;`.
    joiner = " && " if give_back else " ; "
    sweep_up = f"{joiner}rm -rf {quoted}" if cleanup else ""
    # W2. Fresh, not merely present. With a deterministic name a leftover from an earlier run of the SAME item would
    # otherwise be inherited, which is worse than a random name -- and `tar x` over an existing tree keeps whatever
    # the archive does not overwrite. `guard_workspace` has already refused anything this must not remove.
    # Setup is one chain that cannot be broken by a stray separator, and a setup failure exits with its OWN status.
    #
    # Both reviewers landed on the same defect from opposite directions. The environment string ends in `; `, which
    # TERMINATED the `&&` chain: a failed `rm -rf` -- which happens when a previous run left a directory it had made
    # unwritable, something agents do while testing permission bugs -- skipped `mkdir` and the exports and then
    # staged over the stale tree anyway, ran the agent with no PYTHONPATH, handed back a contaminated archive, and
    # exited with the agent's status. The clause called "the one that makes W1 safe" was a no-op in the only
    # condition that triggers it.
    #
    # And `exit ${exec_rc:-0}` returned **0** whenever the agent never started, because `exec_rc` is assigned inside
    # the braces. A staging failure was therefore recorded as an agent that ran and did nothing -- which is exactly
    # the signature the whole workspace-binding investigation was chasing, so it must not be able to hide there.
    #
    # `SETUP_FAILED` is a distinct status the driver recognises, rather than a non-zero code that would read as the
    # agent failing.
    # The root itself, checked in the shell because the guard above is lexical and this is not. Two reviews made the
    # same point: `guard_workspace` compares strings and never looks at the filesystem, so if a previous run left
    # `/tmp/w` as a symlink -- every run executes arbitrary agent-chosen code as the same user on a shared pod -- then
    # `rm -rf /tmp/w/<item>` resolves through it and deletes outside the root the guard exists to protect. `rm -rf` on
    # a FINAL-component symlink removes the link, which is safe; an intermediate one is the dangerous case.
    root = _shq(WORKSPACE_ROOT)
    # Nobody else is working here. Two reviews raised the same risk and it is one this change CREATED: a `kubectl exec`
    # timeout does not reliably kill the remote process tree, so an orphan from an earlier run can still be alive. With
    # random names that orphan was harmless -- it held a directory nothing would reuse. With a name derived from the
    # item, the next run of that item takes its tree away mid-write, or the orphan writes into the freshly staged one.
    #
    # "Runs are sequential" is true of the driver and not of the pod, so it is checked rather than asserted. `/proc`
    # rather than `fuser` or `lsof`, neither of which the image has. This runs BEFORE `cd`, so the run's own shell
    # cannot match itself.
    busy = ("for d in /proc/[0-9]*; do case \"$(readlink $d/cwd 2>/dev/null)\" in {ws_glob}) "
            "echo \"[FATAL] another process is working in {ws_plain}\" >&2; exit {setup_rc};; esac; done").format(
                ws_glob=_shq(workspace) + "*", ws_plain=workspace, setup_rc=SETUP_FAILED)
    return ("{busy}; "
            "{{ ! test -L {root} && mkdir -p {root} && "
            "rm -rf {ws} && mkdir -p {ws} && {pre}{stage}cd {ws} ; }} || "
            "{{ echo '[FATAL] setup failed before the agent started' >&2; exit {setup_rc}; }}; "
            "{env}{{ exec_rc=0; \"$@\" || exec_rc=$?; }}{back}{sweep}; "
            "exit ${{exec_rc:-0}}").format(ws=quoted, root=root, busy=busy, env=env, pre=pre, stage=stage,
                                           back=give_back, sweep=sweep_up, setup_rc=SETUP_FAILED)


def run_one(spec: dict, agent: str, prompt: str, model: str, context: str, namespace: str,
            timeout: int, stage_from: str | None = None, telemetry: dict | None = None,
            cleanup: bool = True, tag: str = "") -> dict:
    """One agent, one task, one fresh session and workspace."""
    session = f"{agent}-{uuid.uuid4().hex[:10]}"
    trace_id, traceparent = new_traceparent()
    # W1. Named after the item, not after a random session id. See `workspace_for`.
    workspace = workspace_for(tag, spec.get("workspace_template"))
    # `agent_definition` is part of the candidate tuple, so it is substituted like any other field. A spec
    # that omits it gets an empty string and the run fails loudly rather than emitting telemetry whose
    # candidate is half unknown.
    # The workspace is a per-session directory this function creates, so a task text that names it carries a
    # marker until now. Filled here and nowhere else.
    prompt = task_prompt.check_deliverable(task_prompt.fill_workspace(prompt, workspace))
    fills = dict(prompt=prompt, session=session, workspace=workspace, model=model,
                 agent_definition=spec.get("agent_definition", ""))
    argv = _fill(spec["argv"], **fills)

    # `mkdir` then `cd` then exec, as one shell command, because the workspace must exist before the
    # agent starts in it and `kubectl exec` has no working-directory option.
    # Stage the task's starting state INTO the workspace when one is given, and hand the result back the
    # same way. The shared volume carries ONE archive in each direction and the pod expands it onto its
    # own local disk: expanded on the volume, a six-thousand-file checkout is six thousand EFS round
    # trips and the copy does not finish. Streaming through the operator's machine is worse still -- it
    # would put hundreds of megabytes through one laptop twice per agent per repeat.
    # Per-run setup for an agent that cannot be told on the command line where to work. Run inside the
    # same shell as the task so it cannot be skipped, and before the archive is expanded is fine: it
    # configures a path, it does not read one.
    pre = "".join(
        " ".join(_shq(x) for x in _fill(c, **fills)) + " >/dev/null 2>&1 && "
        for c in spec.get("pre", [])
    )
    stage = f"tar xf {stage_from} --no-same-owner -C {workspace} && " if stage_from else ""
    ret = f"/work/returned/{session}.tar"
    give_back = (f" ; mkdir -p /work/returned && tar cf {ret} -C {workspace} ." if stage_from else "")
    # Telemetry is exported by the agent itself, to a collector this project runs. Nothing here computes a
    # token count or a cost: one producer of those figures, not two, or the same number is computed twice
    # and the two disagree eventually.
    # D1. The run's own checkout, ahead of anything the pod has installed. Exported before the agent starts, so
    # every shell and subprocess it spawns inherits it -- measured on the pod: a nested `sh -c`, a `bash -lc` login
    # shell and a Python `subprocess` all see it, and only `env -i` does not.
    #
    # Without this a run that invokes Python from anywhere other than the workspace root imports another run's code.
    # `sys.path[0]` is the invoking directory, so from the root the checkout already wins; from `<ws>/<package>` --
    # which is where the source being edited lives, and the natural place to `cd` -- it does not, and an
    # editable-install finder left in the pod's `dist-packages` answers instead. Two recorded runs hit that, and both
    # noticed: one compared its tree against the other's and tried to copy its fix across, the other bypassed the
    # import system with `spec_from_file_location`.
    #
    # Two entries because layouts differ: `<ws>` for astropy, django and pylint, `<ws>/src` for flask. Both always,
    # since an entry naming a directory that does not exist costs nothing and a per-repository table is a second
    # thing to keep in step with the item set.
    #
    # What this does NOT fix: a compiled extension. Eleven of the twenty-four staged trees are built for a Python the
    # pod does not run, so `PathFinder` cannot satisfy those names from the run's own tree and the finder still
    # answers. See docs/changes/import-resolution/01-design/interpreter-mismatch.md -- the fix for that half is to
    # give a run the interpreter its own item was built with, which is upstream of this file.
    env = python_path_export(workspace)
    if telemetry:
        pairs = {
            "OPENCODE_ENABLE_TELEMETRY": "1",
            "OPENCODE_OTLP_ENDPOINT": telemetry["endpoint"],
            # `http/protobuf`, not `http`. The plugin accepts both spellings and `http` takes an http2 path
            # that dies with "authority must be of type string ... Received type number".
            "OPENCODE_OTLP_PROTOCOL": telemetry.get("protocol", "http/protobuf"),
            "OPENCODE_TRACEPARENT": traceparent,
            "OPENCODE_SPAN_ATTRIBUTES": telemetry.get("span_attributes", ""),
        }
        env += "".join(f"export {k}={_shq(v)}; " for k, v in pairs.items() if v)
    # D3. The workspace goes when the run is done, after the tree has been handed back. Not for the disk, though
    # 8.9 GB of leftovers on a shared node is real: a leftover tree holds an earlier run's edits, and 15 of 23
    # leftover astropy trees differed from the staged source -- two of them recorded workspaces for the very item a
    # later run would be asked to fix. A workspace that no longer exists cannot be read from, imported from, or
    # written into.
    #
    # After `give_back` and before `exit`, so the handed-back archive is complete and the agent's status is what the
    # driver sees. A run killed by the exec timeout skips this and leaves its tree, which is the debugging case and
    # the reason `--keep-workspace` exists rather than being the default.
    inner = build_inner(workspace, env, pre, stage, give_back, cleanup)

    started_wall = time.time()
    t0 = time.monotonic()
    try:
        proc = kubectl(
            context, namespace, "exec", f"deploy/{spec['deployment']}", "--",
            "sh", "-c", inner, "sh", *argv,
            timeout=timeout,
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        rc, timed_out = None, True
        out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    ended_wall = time.time()

    return {
        "agent": agent,
        "session": session,
        "workspace": workspace,
        # The text this run was actually given, after the workspace marker was filled. The manifest-level `prompt`
        # is the template and still contains the marker, so it is not what any run received -- and since the whole
        # change under measurement is one sentence of this text, a record that shows the template only cannot say
        # whether the change reached the agent. Per run because each run has its own workspace.
        "prompt_delivered": prompt,
        "argv": argv,
        "staged_from": stage_from,
        "pre": spec.get("pre", []),
        # The join key. Recorded even when the run failed: a failed run still emitted spans and may still
        # have been charged, and dropping its id is how a charge becomes unattributable.
        "trace_id": trace_id,
        # Where the edited tree was left, for the scorer. Named even when the run failed: an agent that
        # crashed halfway still edited files, and whether those files score is a fact about the agent.
        "returned": (f"/work/returned/{session}.tar" if stage_from else None),
        # The window the tap rows are matched against. Wall clock, because that is what the tap
        # records; the monotonic duration is kept separately because wall clock can step.
        "started_wall": started_wall,
        "ended_wall": ended_wall,
        "wall_s": round(time.monotonic() - t0, 2),
        "returncode": rc,
        # Named rather than left as a number, because the number would be read as the agent failing.
        "setup_failed": rc == SETUP_FAILED,
        "timed_out": timed_out,
        # Truncated: the agent's transcript is not the measurement and a full one would bury the
        # manifest. Enough to see what it answered and whether it errored.
        "stdout_tail": out[-4000:],
        "stderr_tail": err[-2000:],
    }


def outcome_row(row: dict, spec_for_agent: dict, name: str, iteration: int, *,
                item_id: str | None, run_group: str | None) -> dict:
    """One outcomes row for a completed run, as the DRIVER observed it.

    The driver records only what it saw of the run and never states an outcome, because the oracle has not run
    yet: `pending_oracle` is the honest value and a scorer replaces it. A driver that wrote "solved" here would be
    inventing the measurement.

    Pulled out of the loop so it can be exercised without a cluster. It is here because it broke: a reference to a
    name that was not in scope raised inside this dict, so thirteen instances ran to completion and wrote no rows
    at all, and nothing failed until the sweep was inspected. A cluster-only code path is a code path with no
    tests.
    """
    return {
        "trace_id": row["trace_id"],
        "item_id": item_id,
        "run_group": run_group,
        # The definition the driver ASKED for. The telemetry reports one per span, and a delegating agent emits a
        # different one per subagent, so the run's own definition has to come from the driver or a delegate's name
        # gets read as the candidate's.
        "agent_definition": spec_for_agent.get("agent_definition") or None,
        "agent": name,
        "iteration": iteration,
        "state": "pending_oracle",
        "returned": row.get("returned"),
        "timed_out": row["timed_out"],
        "returncode": row["returncode"],
        "wall_s": row["wall_s"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=str(HERE / "agents.json"))
    ap.add_argument("--task", help="the task text")
    ap.add_argument("--task-file", help="read the task text from a file")
    ap.add_argument("--agents", help="comma-separated subset; default is every agent in the spec")
    ap.add_argument("--repeat", type=int, default=1,
                    help="runs per agent. More than one is how run-to-run variation becomes visible "
                         "instead of being reported as an agent difference.")
    ap.add_argument("--context", default="distai-eks")
    ap.add_argument("--namespace", default="qwen-trial")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--order", choices=["rotate", "fixed", "shuffle"], default="rotate",
                    help="agent order per iteration. The engine's prefix cache survives a run and "
                         "cannot be flushed -- it exposes no reset endpoint -- so under a fixed order "
                         "the same agent always runs into the same warmth and the advantage is "
                         "systematic. `rotate` counterbalances it; `fixed` is for reproducing one "
                         "specific sequence.")
    ap.add_argument("--stage-from", help="a directory on the shared volume copied into each run's "
                                        "workspace before the agent starts, e.g. a testbed checkout")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="measure without proving the agents work first. For debugging the driver only: "
                         "the preflight exists because every agent here was silently 404ing for days.")
    ap.add_argument("--otlp-endpoint",
                    help="the collector the agent exports to, e.g. http://otel-collector:4318. Given, the "
                         "driver issues a trace id per run and the agent's own telemetry is the only "
                         "producer of token and latency figures")
    ap.add_argument("--otlp-protocol", default="http/protobuf")
    ap.add_argument("--span-attributes", default="",
                    help="comma-separated k=v put on every span, e.g. tenant=default-org")
    ap.add_argument("--outcomes",
                    help="append one JSONL row per run: trace_id, item_id and the run's own exit state. "
                         "The oracle's verdict is added later by whoever scores it")
    ap.add_argument("--item-id", help="the task's id, carried into the outcomes rows")
    ap.add_argument("--model", default=None,
                    help="override the model in agents.json. This is how a second arm is run: one element of "
                         "the candidate tuple changes and nothing else does, so the two runs are a comparison "
                         "rather than two experiments")
    ap.add_argument("--keep-workspace", action="store_true",
                    help="leave the run's workspace on the pod. Off by default: a leftover tree holds this run's "
                         "edits, and a later run of the same item can read them. Use it to debug one run, not to "
                         "measure an arm")
    ap.add_argument("--run-group",
                    help="an id for the invocation that launched this driver, written on every outcomes "
                         "row. Killing a sweep does not kill its already-launched driver, and an orphan "
                         "then appends to the outcomes file of whatever runs next -- which produced a "
                         "duplicate item the ledger refused. With this, rows from another invocation are "
                         "identifiable instead of silently mixed")
    ap.add_argument("--tag", default="untagged")
    ap.add_argument("--out", help="manifest path; default ~/tmp/e02/tap/runs-<tag>-<ts>.json")
    args = ap.parse_args()

    if not args.task and not args.task_file:
        ap.error("one of --task or --task-file is required")
    prompt = args.task or Path(args.task_file).read_text()

    doc = json.loads(Path(args.spec).read_text())
    spec, model = doc["agents"], (args.model or doc["model"])
    names = args.agents.split(",") if args.agents else sorted(spec)
    missing = [n for n in names if n not in spec]
    if missing:
        # Refused rather than skipped: a run that silently omits an agent produces a comparison
        # missing an arm, and the manifest would look complete.
        print(f"[FAIL] not in the spec: {', '.join(missing)}", file=sys.stderr)
        return 2

    if not args.skip_preflight:
        failed = []
        for name in names:
            ok, why = preflight(spec[name], name, model, args.context, args.namespace, 300)
            print(f"preflight {name}: {'ok' if ok else 'FAIL -- ' + why}")
            if not ok:
                failed.append(name)
        if failed:
            # Refused rather than reported per-run: a partial comparison is worse than none, because it
            # is the shape a reader trusts.
            print(f"\n[FAIL] {len(failed)} agent(s) cannot resolve {model!r}: {', '.join(failed)}",
                  file=sys.stderr)
            return 3
        print()

    out_path = Path(args.out) if args.out else (
        Path.home() / "tmp" / "e02" / "tap" / f"runs-{args.tag}-{int(time.time())}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    runs: list[dict] = []
    manifest = {
        "tag": args.tag,
        # The TEMPLATE, marker and all -- not what any run received, because each run's workspace differs. What a
        # run was given is `prompt_delivered` on that run. The key keeps its name because renaming it while a sweep
        # is in flight would leave one arm's manifests half under each name, and a record that changes shape
        # mid-arm is worse than one whose name is imprecise.
        "prompt": prompt,
        "context": args.context,
        "namespace": args.namespace,
        "repeat": args.repeat,
        "order": args.order,
        "model": model,
        "stage_from": args.stage_from,
        # Warmth is a condition of the experiment and not a nuisance: the engine's prefix cache
        # survives a run, so iteration 0 is nearly cold and later ones are not. Recorded per run so a
        # reader can separate the two rather than average across them.
        "cache_flushable": False,
        "runs": runs,
    }

    # Sequential, and sequential is load-bearing. Two agents running at once share the engine, so each
    # would queue behind the other and the time-to-first-byte being recorded would be a measurement of
    # the driver's concurrency rather than of the agent. It also keeps the correlation window
    # unambiguous per address.
    for i in range(args.repeat):
        if args.order == "rotate":
            # Rotate by one each iteration, so over `repeat` iterations no agent keeps the same
            # position and the cache advantage is spread rather than assigned.
            order = names[i % len(names):] + names[:i % len(names)]
        elif args.order == "shuffle":
            import random  # noqa: PLC0415
            order = random.sample(names, len(names))
        else:
            order = names
        for name in order:
            print(f"[{i + 1}/{args.repeat}] {name} ... ", end="", flush=True)
            row = run_one(spec[name], name, prompt, model, args.context, args.namespace,
                          args.timeout, args.stage_from,
                          telemetry=({"endpoint": args.otlp_endpoint,
                                      "protocol": args.otlp_protocol,
                                      "span_attributes": args.span_attributes}
                                     if args.otlp_endpoint else None),
                          cleanup=not args.keep_workspace, tag=args.tag)
            row["iteration"] = i
            row["position"] = order.index(name)
            runs.append(row)
            state = "timeout" if row["timed_out"] else f"rc={row['returncode']}"
            print(f"{state} in {row['wall_s']}s  trace={row['trace_id'][:16]}")
            out_path.write_text(json.dumps(manifest, indent=1))
            if args.outcomes:
                with open(args.outcomes, "a") as fh:
                    fh.write(json.dumps(outcome_row(row, spec[name], name, i,
                                                    item_id=args.item_id or args.tag,
                                                    run_group=args.run_group)) + "\n")

    print(f"\nmanifest: {out_path}")
    print("Pair it with the tap log to attribute calls:")
    print(f"  kubectl --context {args.context} -n {args.namespace} exec deploy/agent-tap -- "
          "sh -c 'cat /data/agent-tap/*.jsonl' > tap.jsonl")
    print(f"  python3 harness/agent_tap_join.py {out_path} tap.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
