"""Hand a SWE-bench testbed to an agent that lives somewhere else, and score what comes back.

The comparison this serves has the model fixed and the coding agent varying. The agents are CLIs in
their own pods; the task's environment is the instance's own evaluation image, with the repository, its
dependencies and a working interpreter already in it. Neither can move into the other:

- Installing the agents into the evaluation image is out, because that image's environment is what the
  result is attributed to, and adding a Node runtime and an npm tree to it changes what is being
  attributed.
- Rebuilding the repository inside the agent pods is out, because they have no git, no interpreter for
  the project's version, and none of the instance's dependencies.

So the testbed travels. This script runs the evaluation image as a long-lived pod with the shared volume
mounted, exports `/testbed` onto it, and later imports an agent's edited copy back and scores it.

**The scoring contract is `agent/score.py`'s and is not reimplemented here.** The agent works on a copy
and never sees the tests; the diff is taken before the test patch is applied; `FAIL_TO_PASS` must pass and
`PASS_TO_PASS` must still pass; an agent that edited a test file has changed its own examiner and fails.
This script's whole job is to put files in the right places and to invoke that.

**The diff is computed here, not asked of the agent.** The agent pods have no git, so they could not
produce one — but that is a convenience, not the reason. The reason is that a previous measurement of a
self-hosted model scored zero on capability grounds and the true cause was its failure to serialise a
patch into a hand-rolled format. Asking an agent to emit a diff makes patch formatting part of the score.
Here it edits files and the diff is taken from a git checkout it never touched.

Usage:
    python3 harness/testbed.py up      --instance django__django-11880
    python3 harness/testbed.py export  --instance django__django-11880
    python3 harness/testbed.py score   --instance django__django-11880 --workspace /work/runs/<session>
    python3 harness/testbed.py down    --instance django__django-11880

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
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The published evaluation images encode `__` as `_1776_`. Not a choice here -- it is how they are named.
IMAGE_TEMPLATE = "swebench/sweb.eval.x86_64.{slug}:latest"
SHARED_CLAIM = "agent-workspace"


def image_for(instance_id: str) -> str:
    return IMAGE_TEMPLATE.format(slug=instance_id.replace("__", "_1776_"))


def pod_name(instance_id: str) -> str:
    # A Kubernetes name is lowercase alphanumeric and dashes, and an instance id has underscores.
    return "testbed-" + instance_id.replace("__", "-").replace("_", "-").lower()[:50]


def kubectl(ctx: str, ns: str, *args: str, timeout: int = 900, stdin: str | None = None):
    return subprocess.run(["kubectl", "--context", ctx, "-n", ns, *args],
                          capture_output=True, text=True, timeout=timeout, input=stdin)


def manifest(instance_id: str) -> str:
    """A pod that holds the image and does nothing, so its filesystem can be reached with `exec`.

    A Job would be wrong: this has to outlive one command, because the sequence is export, then an agent
    run that takes minutes, then import and score. A pod that sleeps is the honest shape for "I need this
    image's filesystem available for a while", and `down` removes it.
    """
    return json.dumps({
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": pod_name(instance_id),
                     "labels": {"app.kubernetes.io/name": "testbed",
                                "tierbook.io/instance": instance_id.replace("__", "-")[:63]}},
        "spec": {
            "restartPolicy": "Never",
            "containers": [{
                "name": "testbed",
                "image": image_for(instance_id),
                "command": ["sleep", "86400"],
                "volumeMounts": [{"name": "work", "mountPath": "/work"}],
                # The image is 1-3 GB and the repository's test suite is the heavy part of scoring.
                # Requests, not just limits, so scoring is not evicted halfway through PASS_TO_PASS.
                "resources": {"requests": {"cpu": "2", "memory": "4Gi"},
                              "limits": {"cpu": "4", "memory": "8Gi"}},
            }],
            "volumes": [{"name": "work",
                         "persistentVolumeClaim": {"claimName": SHARED_CLAIM}}],
        },
    })


def instance_json(instance_id: str, cache: Path, agent_dir: Path) -> dict:
    """The instance record, built by the existing dataset loader rather than a second parser."""
    code = (
        "import json,sys;sys.path.insert(0,%r);import dataset;"
        "m=[i for i in dataset.load(__import__('pathlib').Path(%r)) if i.instance_id==%r];"
        "i=m[0] if m else None;"
        "print(json.dumps({'instance_id':i.instance_id,'repo':i.repo,'base_commit':i.base_commit,"
        "'problem_statement':i.problem_statement,'difficulty':i.difficulty,"
        "'fail_to_pass':list(i.fail_to_pass),'pass_to_pass':list(i.pass_to_pass),"
        "'gold_patch':i.gold_patch,'test_patch':i.test_patch}) if i else '')"
        % (str(agent_dir), str(cache), instance_id)
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    out = proc.stdout.strip()
    if not out:
        raise SystemExit(f"[FAIL] {instance_id} is not in {cache}: {proc.stderr[-300:]}")
    return json.loads(out)


def sh(ctx: str, ns: str, instance_id: str, script: str, timeout: int = 1800):
    return kubectl(ctx, ns, "exec", pod_name(instance_id), "--", "bash", "-lc", script, timeout=timeout)


def cmd_up(a) -> int:
    proc = kubectl(a.context, a.namespace, "apply", "-f", "-", stdin=manifest(a.instance))
    print(proc.stdout.strip() or proc.stderr.strip())
    if proc.returncode:
        return 1
    print("waiting for the image to pull (1-3 GB) ...")
    w = kubectl(a.context, a.namespace, "wait", f"pod/{pod_name(a.instance)}",
                "--for=condition=Ready", "--timeout=900s", timeout=960)
    print(w.stdout.strip() or w.stderr.strip())
    return 0 if w.returncode == 0 else 1


def cmd_export(a) -> int:
    """Copy `/testbed` onto the shared volume, and keep a pristine git copy for the diff.

    Two archives with different jobs. `staged.tar` is what the agent gets: no `.git`, because the agent
    pods have no git to use it and shipping history doubles the bytes. `pristine.tar` is what the agent's
    returned tree is diffed against, so the diff comes from a checkout the agent never had access to.

    **Archives, not loose files.** The first version wrote the trees out expanded and it does not finish:
    the shared volume is EFS, and a Django checkout is over six thousand files, twice. Every one is a
    round trip. One sequential write of one archive is a different order of magnitude, and the receiving
    pod expands it onto its own local disk, which is NVMe with 140 GB free. The volume is a transport,
    not a filesystem to work in.
    """
    base = f"/work/testbeds/{a.instance}"
    script = f"""
set -euo pipefail
# EFS refuses `rm -rf` on a tree another writer touched recently -- "Directory not empty" on a directory
# whose children are gone -- so the old contents are renamed out of the way first and deleted with
# retries. A failed cleanup must not leave a half-old testbed that looks whole.
mkdir -p {base}
for old in {base}/staged {base}/pristine {base}/staged.tar {base}/pristine.tar; do
  [ -e "$old" ] && mv "$old" "{base}/.trash-$$-$(basename $old)" || true
done
for i in 1 2 3; do rm -rf {base}/.trash-* 2>/dev/null && break; sleep 2; done
cd /testbed
git status --porcelain >/dev/null 2>&1 || {{ echo "[FAIL] /testbed is not a git checkout"; exit 1; }}
# Refuse to export a dirty testbed: a diff taken later would attribute someone else's edits to the agent.
if [ -n "$(git status --porcelain)" ]; then echo "[FAIL] /testbed has uncommitted changes"; exit 1; fi
echo "base_commit: $(git rev-parse HEAD)"
tar cf {base}/staged.tar --exclude=.git .
tar cf {base}/pristine.tar .
ls -la {base}/staged.tar {base}/pristine.tar
"""
    proc = sh(a.context, a.namespace, a.instance, script)
    print(proc.stdout.strip())
    if proc.returncode:
        print(proc.stderr.strip()[-2000:], file=sys.stderr)
        return 1
    print(f"\nstage agents from: {base}/staged.tar")
    return 0


def cmd_score(a) -> int:
    """Diff the agent's tree against the pristine copy, then score the diff.

    The order is the contract: the diff is taken before the test patch exists anywhere near the tree.
    """
    base = f"/work/testbeds/{a.instance}"
    inst = instance_json(a.instance, Path(a.cache).expanduser(), Path(a.agent_dir))
    out_dir = f"{base}/scored/{Path(a.workspace).name}"

    # Written through the pod rather than kubectl cp: the instance record can be several hundred KB and
    # this keeps every path in one place.
    prep = f"mkdir -p {out_dir} && cat > {out_dir}/instance.json"
    proc = kubectl(a.context, a.namespace, "exec", "-i", pod_name(a.instance), "--",
                   "bash", "-lc", prep, stdin=json.dumps(inst), timeout=300)
    if proc.returncode:
        print(proc.stderr[-1000:], file=sys.stderr)
        return 1

    script = f"""
set -euo pipefail
test -f {a.workspace} || {{ echo "[FAIL] no returned archive at {a.workspace}"; exit 1; }}
test -f {base}/pristine.tar || {{ echo "[FAIL] no pristine archive; run export first"; exit 1; }}

# Expanded on this pod's OWN disk, not on the shared volume: `git add -A` over six thousand files on EFS
# is the same round-trip problem the export hit. The volume carries archives; work happens locally.
LOCAL=/tmp/score-$(basename {out_dir})
rm -rf "$LOCAL"; mkdir -p "$LOCAL/tree"
tar xf {a.workspace} --no-same-owner -C "$LOCAL/tree"
# The pristine .git is laid over the agent's tree so `git diff` compares like with like. The agent could
# not have touched it: its pod has no git, and this copy never left this pod.
mkdir -p "$LOCAL/pristine"
tar xf {base}/pristine.tar --no-same-owner -C "$LOCAL/pristine" ./.git
rm -rf "$LOCAL/tree/.git"
cp -a "$LOCAL/pristine/.git" "$LOCAL/tree/.git"
cd "$LOCAL/tree"
git add -A
git diff --cached > {out_dir}/diff.patch
echo "diff bytes: $(wc -c < {out_dir}/diff.patch)"
echo "files touched: $(git diff --cached --name-only | wc -l)"

# The scorer needs 3.7 or above and an evaluation image's default `python3` is whatever that
# repository's era shipped -- on this one it is old enough to reject `from __future__ import
# annotations`. The conda interpreter the image installs for the project is the one to use, and the
# search order is the same as the existing episode runner's so both find the same one.
HARNESS_PY=""
for c in /opt/miniconda3/bin/python3 /usr/bin/python3 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,7) else 1)' >/dev/null 2>&1; then
    HARNESS_PY="$c"; break
  fi
done
[ -n "$HARNESS_PY" ] || {{ echo "[FAIL] this image has no interpreter at 3.7 or above"; exit 1; }}
echo "scorer on $HARNESS_PY ($("$HARNESS_PY" -V 2>&1))"

# Score in the real /testbed, which score.py resets itself before applying anything.
cd /testbed
"$HARNESS_PY" /work/testbeds/{a.instance}/score.py \\
  --instance {out_dir}/instance.json --diff {out_dir}/diff.patch --out {out_dir}/score.json
cat {out_dir}/score.json
"""
    proc = sh(a.context, a.namespace, a.instance, script, timeout=a.timeout)
    print(proc.stdout.strip()[-4000:])
    if proc.returncode:
        print(proc.stderr.strip()[-2000:], file=sys.stderr)
        return 1
    return 0


#: What the scorer imports. Placed alongside it rather than vendored into this file: the scoring contract
#: lives in the episode harness and a second copy of it would be a second thing to keep correct.
SCORER_FILES = ("score.py", "tools.py", "policy.py")


def cmd_put_scorer(a) -> int:
    """Place the scorer and what it imports on the shared volume.

    The same files the episode runner uses, so a CLI agent and the project's own loop are judged by one
    scorer. Copying `score.py` alone fails at import: it depends on `tools` for the diff and test-id
    handling that both paths need.
    """
    dest_dir = f"/work/testbeds/{a.instance}"
    sent = []
    for name in SCORER_FILES:
        src = Path(a.agent_dir) / name
        if not src.exists():
            continue
        proc = kubectl(a.context, a.namespace, "exec", "-i", pod_name(a.instance), "--", "bash", "-lc",
                       f"mkdir -p {dest_dir} && cat > {dest_dir}/{name} && wc -c {dest_dir}/{name}",
                       stdin=src.read_text(), timeout=300)
        if proc.returncode:
            print(proc.stderr.strip()[-500:], file=sys.stderr)
            return proc.returncode
        sent.append(proc.stdout.strip())
    if not sent:
        raise SystemExit(f"[FAIL] no scorer files found in {a.agent_dir}")
    print("\n".join(sent))
    return 0


def cmd_down(a) -> int:
    proc = kubectl(a.context, a.namespace, "delete", "pod", pod_name(a.instance), "--ignore-not-found")
    print(proc.stdout.strip() or proc.stderr.strip())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["up", "export", "put-scorer", "score", "down"])
    ap.add_argument("--instance", required=True)
    ap.add_argument("--workspace",
                    help="the agent's returned tree as a tar on the shared volume, for `score`")
    ap.add_argument("--context", default="distai-eks")
    ap.add_argument("--namespace", default="qwen-trial")
    ap.add_argument("--cache", default="~/.cache/swebench-verified.json")
    ap.add_argument("--agent-dir",
                    default="/Users/akazawt/eks/distributed-ai/2026-08-24-mom-vsr-eks-benchmark/agent")
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args()
    if a.action == "score" and not a.workspace:
        ap.error("score needs --workspace")
    return {"up": cmd_up, "export": cmd_export, "put-scorer": cmd_put_scorer,
            "score": cmd_score, "down": cmd_down}[a.action](a)


if __name__ == "__main__":
    raise SystemExit(main())
