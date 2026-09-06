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

    manifest = Path(a.workdir) / f"runs-{instance}.json"
    rc, out = run([
        sys.executable, str(HERE / "agent_drive.py"),
        "--task-file", str(Path(a.workdir) / f"task-{instance}.md"),
        "--tag", instance, "--repeat", str(a.repeat),
        "--stage-from", f"/work/testbeds/{instance}/staged.tar",
        "--timeout", str(a.agent_timeout),
        "--context", a.context, "--namespace", a.namespace,
        "--out", str(manifest),
    ], timeout=a.agent_timeout * 6 + 600)
    rec["steps"]["drive"] = {"rc": rc, "tail": out[-800:]}
    if not manifest.exists():
        rec["outcome"] = "drive produced no manifest"
        return rec

    for r in json.loads(manifest.read_text())["runs"]:
        if not r.get("returned"):
            rec["runs"][f"{r['agent']}#{r['iteration']}"] = {"outcome": "no returned tree"}
            continue
        rc, out = run(tb + ["score"] + common + ["--workspace", r["returned"]], a.score_timeout)
        verdict = None
        for line in out.splitlines():
            if '"resolved"' in line:
                verdict = "true" in line
        rec["runs"][f"{r['agent']}#{r['iteration']}"] = {
            "rc": rc,
            "resolved": verdict,
            "wall_s": r["wall_s"],
            "timed_out": r["timed_out"],
            "returned": r["returned"],
            "tail": out[-600:],
        }

    if not a.keep:
        # The image is the expensive thing to hold: it occupies a node's disk and its CPU request keeps a
        # node alive. Removed as soon as the instance is scored, which is why this is one at a time.
        run(tb + ["down"] + common, 300)
    rec["outcome"] = "done"
    rec["ended"] = time.time()
    return rec


def write_task(a, instance: str) -> bool:
    """The problem statement, as the task. Written once per instance and kept, so a re-run gives the
    identical prompt rather than one regenerated from a dataset that may have moved."""
    out = Path(a.workdir) / f"task-{instance}.md"
    if out.exists():
        return True
    code = f'''
import json, sys, pathlib
sys.path.insert(0, {str(Path(a.agent_dir))!r})
import dataset
m = [x for x in dataset.load(pathlib.Path({str(Path(a.cache).expanduser())!r}))
     if x.instance_id == {instance!r}]
if not m:
    raise SystemExit(1)
i = m[0]
print("You are working in a checkout of the {{}} repository in the current directory.".format(i.repo))
print("Fix the issue described below by editing the source files. Do not write any tests.")
print("When you are done, stop.\\n")
print("--- issue ---")
print(i.problem_statement)
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
    ap.add_argument("--keep", action="store_true", help="leave each testbed pod up (for debugging)")
    ap.add_argument("--limit", type=int, help="stop after this many new instances")
    a = ap.parse_args()

    instances = (a.instances.split(",") if a.instances
                 else json.loads(Path(a.subset).read_text()))
    state_path = Path(a.state)
    state = load_state(state_path)

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
        got = {k: v.get("resolved") for k, v in rec.get("runs", {}).items()}
        print(f"{rec['outcome']} in {int(time.time() - t0)}s  {got}")

    print(f"\nstate: {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
