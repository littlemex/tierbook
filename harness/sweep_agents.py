"""Run every agent over every instance, resumably, one testbed at a time.

This is hours of work and the shape is dictated by two constraints that are not about the science.

**One testbed pod at a time.** The evaluation images are 1-3 GB each and a testbed pod asks for two of a
four-CPU node, so twenty-four at once means twenty-four image pulls and a dozen new nodes for something
that is inherently sequential anyway -- the agents share one engine, and running them concurrently would
make the recorded time-to-first-byte a measurement of this script's parallelism.

**Resumable, because it will be interrupted.** A sweep this long meets a laptop sleeping, a token
expiring, a node being consolidated. Every instance's outcome is written the moment it is known and an
instance already recorded is skipped, so re-running continues rather than restarting. The state file is
the deliverable; this script is how it gets filled in.

What each instance costs, measured on the first one: a few minutes to pull the image, a few more to
archive the checkout, then seconds to minutes per agent, then the test suite per agent. No GPU beyond the
engine that is already serving.

Usage:
    python3 harness/sweep_agents.py --state ~/tmp/e02/tap/sweep.json
    python3 harness/sweep_agents.py --state ... --instances django__django-11880,astropy__astropy-14365

SCOPE (see ../SCOPE.md, which governs this file): this is an INSTRUMENT that supplies parameters to a
routing mechanism, not the mechanism and not a conclusion. Every environment-specific number it prints --
a seat count, a KV capacity, a break-even concurrency, an agent's token appetite -- is a parameter reading
for one moment in one cluster. The mechanism's job is to re-read them live and decide from them; turning
any of them into advice about a particular deployment is the error this project has made three times.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SUBSET = Path(
    "/Users/akazawt/eks/distributed-ai/2026-08-24-mom-vsr-eks-benchmark/agent/pilot-subset.json"
)


def run(argv: list[str], timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        out = e.stdout or b""
        err = e.stderr or b""
        text = (out.decode("utf-8", "replace") if isinstance(out, bytes) else out) + \
               (err.decode("utf-8", "replace") if isinstance(err, bytes) else err)
        return 124, text + "\n[timeout]"


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"started": time.time(), "instances": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written through a temporary file: the point of the state is to survive an interruption, and an
    # interruption during the write of the state is exactly when a partial file would be created.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(path)


def sweep_one(a, instance: str) -> dict:
    """One instance, all agents, from image pull to scores."""
    rec: dict = {"instance": instance, "started": time.time(), "steps": {}, "runs": {}}
    tb = [sys.executable, str(HERE / "testbed.py")]
    common = ["--instance", instance, "--context", a.context, "--namespace", a.namespace]

    for step, argv, timeout in (
        ("up", tb + ["up"] + common, 1200),
        ("put-scorer", tb + ["put-scorer"] + common, 300),
        ("export", tb + ["export"] + common, 2400),
    ):
        rc, out = run(argv, timeout)
        rec["steps"][step] = {"rc": rc, "tail": out[-600:]}
        if rc != 0:
            rec["outcome"] = f"{step} failed"
            return rec

    # The run group is in the name. Without it a second sweep over the same instances overwrote the first, and
    # the workspace-to-trace mapping for a baseline was gone by the time an analysis wanted it -- the workspace had
    # to be recovered from a returned tar's filename instead. A manifest that a later run can silently replace is
    # not a record.
    manifest = manifest_path(Path(a.workdir), instance, a.run_group)
    outcomes = Path(a.outcomes)
    drive = [
        sys.executable, str(HERE / "agent_drive.py"),
        "--task-file", str(Path(a.workdir) / f"task-{instance}-{a.prompt_variant}.md"),
        "--tag", instance, "--repeat", str(a.repeat),
        "--stage-from", f"/work/testbeds/{instance}/staged.tar",
        "--timeout", str(a.agent_timeout),
        "--context", a.context, "--namespace", a.namespace,
        "--out", str(manifest),
        # One capture path: the agent's own telemetry produces the token and latency figures, and this
        # sweep produces none. The trace id the driver issues is what the outcome and the charge are
        # later joined on.
        "--outcomes", str(outcomes), "--item-id", instance,
        "--run-group", a.run_group,
        *(("--model", a.model) if a.model else ()),
    ]
    if a.otlp_endpoint:
        drive += ["--otlp-endpoint", a.otlp_endpoint]
    if a.span_attributes:
        drive += ["--span-attributes", a.span_attributes]
    if a.agents:
        drive += ["--agents", a.agents]
    rc, out = run(drive, timeout=a.agent_timeout * 6 + 600)
    rec["steps"]["drive"] = {"rc": rc, "tail": out[-800:]}
    if not manifest.exists():
        rec["outcome"] = "drive produced no manifest"
        return rec

    # The oracle is applied by the step that owns it, in place, on the rows the driver left pending. This
    # sweep no longer parses a verdict out of a log tail, and no longer computes a token or cost figure of
    # any kind.
    rc, out = run([sys.executable, str(HERE / "score_outcomes.py"),
                   "--outcomes", str(outcomes), "--instance", instance,
                   "--run-group", a.run_group,
                   "--context", a.context, "--namespace", a.namespace,
                   "--timeout", str(a.score_timeout)], timeout=a.score_timeout + 1800)
    rec["steps"]["oracle"] = {"rc": rc, "tail": out[-800:]}

    judged = [json.loads(x) for x in outcomes.read_text().splitlines() if x.strip()] if outcomes.exists() else []
    for r in [x for x in judged if x.get("item_id") == instance and x.get("run_group") == a.run_group]:
        rec["runs"][f"{r.get('agent')}#{r.get('iteration')}"] = {
            "trace_id": r.get("trace_id"),
            "state": r.get("state"),
            "unobserved_reason": r.get("unobserved_reason"),
            "wall_s": r.get("wall_s"),
            "timed_out": r.get("timed_out"),
            "returned": r.get("returned"),
            "files_touched": (r.get("oracle") or {}).get("files_touched"),
        }

    if not a.keep:
        # The image is the expensive thing to hold: it occupies a node's disk and its CPU request keeps a
        # node alive. Removed as soon as the instance is scored, which is why this is one at a time.
        run(tb + ["down"] + common, 300)
    rec["outcome"] = "done"
    rec["ended"] = time.time()
    return rec


def manifest_path(workdir: Path, instance: str, run_group: str | None) -> Path:
    """Where one instance's run manifest goes, keyed so a later sweep cannot overwrite an earlier one."""
    return workdir / (f"runs-{instance}-{run_group}.json" if run_group else f"runs-{instance}.json")


def write_task(a, instance: str) -> bool:
    """The problem statement, as the task. Written once per instance and kept, so a re-run gives the
    identical prompt rather than one regenerated from a dataset that may have moved."""
    # The variant is in the filename. A cached task file from the baseline would otherwise be reused for the
    # changed run, and the "change" would measure nothing at all -- the quietest way a before/after can fail.
    out = Path(a.workdir) / f"task-{instance}-{a.prompt_variant}.md"
    if out.exists():
        return True
    # The text itself lives in `task_prompt.py` so it can be tested and so a change to it shows in a diff. It
    # used to be string literals in this heredoc, which mattered once the recordings identified the prompt as the
    # cause of two zero-edit runs.
    code = f'''
import json, sys, pathlib
sys.path.insert(0, {str(Path(a.agent_dir))!r})
import dataset, task_prompt
m = [x for x in dataset.load(pathlib.Path({str(Path(a.cache).expanduser())!r}))
     if x.instance_id == {instance!r}]
if not m:
    raise SystemExit(1)
i = m[0]
print(task_prompt.build(i.repo, i.problem_statement,
                        workspace=task_prompt.WORKSPACE_MARKER,
                        variant={a.prompt_variant!r}), end="")
'''
    rc, text = run([sys.executable, "-c", code], 300)
    if rc != 0 or not text.strip():
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=str(Path.home() / "tmp/e02/tap/sweep.json"))
    ap.add_argument("--workdir", default=str(Path.home() / "tmp/e02/tap"))
    ap.add_argument("--subset", default=str(DEFAULT_SUBSET))
    ap.add_argument("--instances", help="comma-separated override")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--agent-timeout", type=int, default=900)
    ap.add_argument("--score-timeout", type=int, default=2400)
    ap.add_argument("--context", default="distai-eks")
    ap.add_argument("--namespace", default="qwen-trial")
    ap.add_argument("--cache", default="~/.cache/swebench-verified.json")
    ap.add_argument("--agent-dir",
                    default="/Users/akazawt/eks/distributed-ai/2026-08-24-mom-vsr-eks-benchmark/agent")
    ap.add_argument("--outcomes", default=str(Path.home() / "tmp/e02/tap/outcomes.jsonl"),
                    help="the single JSONL every run appends to and the oracle updates in place")
    ap.add_argument("--otlp-endpoint", default="http://otel-collector:4318",
                    help="where the agent exports its telemetry. This sweep produces no telemetry itself")
    ap.add_argument("--span-attributes", default="tenant=default-org")
    ap.add_argument("--agents", help="comma-separated subset passed through to the driver")
    ap.add_argument("--model", default=None,
                    help="passed through to the driver, so a second arm differs only in the model")
    ap.add_argument("--prompt-variant", default="baseline",
                    help="which task wording to use, from harness/task_prompt.py. The variant is part of the "
                         "task file's name, because a cached baseline task file reused for a changed run would "
                         "measure nothing -- the quietest way a before/after can fail")
    ap.add_argument("--run-group", default=None,
                    help="id for this invocation, defaulting to a fresh one. Written on every outcomes row "
                         "so an orphaned driver from an aborted sweep cannot be mistaken for this one's")
    ap.add_argument("--keep", action="store_true", help="leave each testbed pod up (for debugging)")
    ap.add_argument("--limit", type=int, help="stop after this many new instances")
    a = ap.parse_args()

    instances = (a.instances.split(",") if a.instances
                 else json.loads(Path(a.subset).read_text()))
    state_path = Path(a.state)
    state = load_state(state_path)

    a.run_group = a.run_group or f"sweep-{int(time.time())}"
    print(f"run_group {a.run_group}")
    Path(a.outcomes).parent.mkdir(parents=True, exist_ok=True)
    done = {k for k, v in state["instances"].items() if v.get("outcome") == "done"}
    todo = [i for i in instances if i not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(instances)} instances, {len(done)} already done, {len(todo)} to run\n")

    for n, instance in enumerate(todo, 1):
        if not write_task(a, instance):
            state["instances"][instance] = {"outcome": "no task text"}
            save_state(state_path, state)
            print(f"[{n}/{len(todo)}] {instance}: SKIP, not in the dataset cache")
            continue
        print(f"[{n}/{len(todo)}] {instance} ... ", end="", flush=True)
        t0 = time.time()
        rec = sweep_one(a, instance)
        state["instances"][instance] = rec
        save_state(state_path, state)
        got = {k: (v.get("state") if not v.get("unobserved_reason")
                   else f"{v['state']}/{v['unobserved_reason']}")
               for k, v in rec.get("runs", {}).items()}
        print(f"{rec['outcome']} in {int(time.time() - t0)}s  {got}")

    print(f"\nstate: {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
