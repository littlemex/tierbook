"""Three controls on the solve metric, because one of them was not enough.

A review asked the right question in the right order. A run whose model received almost no conversation reported
11 solved of 24, which is prima facie evidence that the metric is generous -- and a generous metric invalidates
every arm, not just that one. The first answer was a negative control: an unmodified tree came back not-solved,
with 111 tests passing and the required failing set unmet. A second review then pointed out that a negative
control alone shows only that the grader does not rubber-stamp, and says nothing about whether it can recognise a
correct fix or whether it can be fooled.

So three controls, and all three ran on a real instance:

    negative   an unmodified staged tree            -> not solved   (the grader does not rubber-stamp)
    positive   the dataset's own gold patch          -> solved       (it recognises a correct fix)
    tamper     the graded test file deleted          -> unscoreable  (it cannot be fooled by removing its tests)

The tamper result is the interesting one. Deleting the file the instance grades on does not produce a pass; it
produces "cannot score", which is the honest answer and the one that keeps a deletion out of a solve rate.

What this does not establish: that every one of the 24 instances is configured correctly. Graders can be wrong
per task, so the battery is worth running across the set rather than on one member of it -- which needs no model
and does not compete for the reservation.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path("/Users/akazawt/tierbook/harness")
sys.path.insert(0, str(HERE))
import dataset  # noqa: E402

INSTANCE = sys.argv[1]
CTX, NS = "distai-eks", "qwen-trial"

inst = next(i for i in dataset.load() if i.instance_id == INSTANCE)
print(f"{INSTANCE}: gold patch {len(inst.gold_patch)} bytes, test patch {len(inst.test_patch)} bytes")

work = Path("/tmp/pc-work")
work.mkdir(exist_ok=True)
(work / "gold.patch").write_text(inst.gold_patch)

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=1800, **kw)

# Build the two trees inside the testbed pod, from the staged tar the agents were given.
script = f"""
set -e
cd /work/testbeds/{INSTANCE}
rm -rf /tmp/pc && mkdir -p /tmp/pc/gold /tmp/pc/tamper
tar xf staged.tar -C /tmp/pc/gold
tar xf staged.tar -C /tmp/pc/tamper
cd /tmp/pc/gold && git apply -p1 /tmp/gold.patch && echo GOLD_APPLIED
cd /tmp/pc/gold && tar cf /work/returned/pc-gold.tar . && echo GOLD_TARRED
# The tamper tree: delete every test file the instance's own test patch touches, so the required tests cannot run.
cd /tmp/pc/tamper
python3 - <<'EOF'
import re, os
patch = open('/tmp/test.patch').read()
paths = set(re.findall(r'^diff --git a/(\\S+) b/', patch, re.M))
for p in sorted(paths):
    if os.path.exists(p):
        os.remove(p)
        print('deleted', p)
EOF
tar cf /work/returned/pc-tamper.tar . && echo TAMPER_TARRED
"""
(work / "run.sh").write_text(script)
(work / "test.patch").write_text(inst.test_patch)

for f in ("gold.patch", "test.patch", "run.sh"):
    r = run(["kubectl", "--context", CTX, "-n", NS, "cp", str(work / f),
             f"testbed-{INSTANCE.replace('__', '-').replace('_', '-')}:/tmp/{f}"])
    if r.returncode:
        print(f"[FAIL] copying {f}: {r.stderr[-300:]}")
        raise SystemExit(1)

pod = f"testbed-{INSTANCE.replace('__', '-').replace('_', '-')}"
r = run(["kubectl", "--context", CTX, "-n", NS, "exec", pod, "--", "sh", "/tmp/run.sh"])
print(r.stdout[-800:])
if r.returncode:
    print(f"[FAIL] building the trees: {r.stderr[-600:]}")
    raise SystemExit(1)

for label, tar in (("gold patch (positive control)", "/work/returned/pc-gold.tar"),
                   ("tests deleted (tamper control)", "/work/returned/pc-tamper.tar")):
    r = run([sys.executable, str(HERE / "testbed.py"), "score", "--instance", INSTANCE,
             "--workspace", tar, "--context", CTX, "--namespace", NS])
    out = r.stdout + r.stderr
    verdict = ("solved" if '"resolved": true' in out.lower()
               else "not solved" if '"resolved": false' in out.lower() else "unscoreable")
    print(f"{label}: {verdict}")
    for line in out.splitlines():
        if line.startswith("files touched:") or line.startswith("diff bytes:"):
            print(f"    {line}")
