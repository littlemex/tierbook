"""Where a package's parts actually come from, inside a real run's environment.

The gate for the import-resolution change, and it exists because the obvious check passes while the defect is
present. Asking `import astropy; print(astropy.__file__)` says the run's own workspace. Asking for
`astropy.convolution._convolve` says a *different run's* workspace, because the staged tree's extensions are built
for cpython-39, the pod runs 3.11, and the editable-install finder answers for what `PathFinder` cannot satisfy.

So a check that reads the top-level package is not weaker evidence of the same thing -- it is evidence of something
else, and it agrees with a broken environment. Three probes per package, and the compiled one is the whole point:

  top level        must resolve inside the run's own workspace
  a pure submodule  must resolve inside the run's own workspace
  a compiled submodule  must resolve inside the run's own workspace, or NOT RESOLVE AT ALL

The third verdict is deliberate. Once the editable artifacts are gone, a missing `cpython-311` extension raises, and
that is the wanted behaviour: a run must not silently exercise a foreign binary, and an `ImportError` naming the
extension tells the agent what is wrong. `absent` passes; `elsewhere` does not.

Origins are compared after `realpath`, because a workspace can be a symlink and a string prefix would then call a
foreign path local. That was a review's point and it costs one syscall.

This runs a probe in the pod rather than in this process: the question is what a *run* resolves, and this process has
neither the finders nor the workspaces.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import PurePosixPath

#: One entry per package that has an editable-install artifact pointing at a leftover workspace, with a pure-Python
#: submodule and a compiled one. The compiled name is what separates a passing environment from a broken one, so a
#: package without one is recorded as `None` rather than left out: the probe still checks the other two.
PROBES = {
    "astropy": {"pure": "astropy.io.ascii.qdp", "compiled": "astropy.convolution._convolve"},
    "django": {"pure": "django.db.models.query", "compiled": None},
    "flask": {"pure": "flask.app", "compiled": None},
    "pylint": {"pure": "pylint.checkers.base", "compiled": None},
}

#: What the probe reports for a module it could not find. Distinguished from an origin because `absent` is a PASS for
#: a compiled submodule and a FAIL for the other two.
ABSENT = "__absent__"

#: The verdicts. `elsewhere` is the defect; `absent` is the fix working on a tree whose extensions were built for
#: another interpreter; `local` is the fix working on a tree that has usable ones.
LOCAL, ABSENT_V, ELSEWHERE, UNKNOWN = "local", "absent", "elsewhere", "unknown"

#: The probe, run by the pod's interpreter. Kept as source rather than a file on the pod so there is one copy of it
#: and it cannot drift from the rules below.
PROBE_SOURCE = r'''
import json, os, sys
import importlib.util
# Optionally answer the question D2 asks -- "what happens once the editable-install artifacts are gone" -- WITHOUT
# touching the pod, by dropping the finders those artifacts registered from this process's meta_path. It predicts the
# change's effect rather than asserting it, and it is read-only: a probe that mutated the pod to measure a proposal
# would have changed the environment the next run sees.
if os.environ.get("DROP_EDITABLE_FINDERS"):
    # setuptools puts the editable finder on meta_path as a CLASS, not an instance, so `type(m)` is `type` and its
    # module is `builtins`. Read the attributes off the object itself, which is right either way. A first version of
    # this filter looked at `type(m)` and matched nothing.
    own = (os.environ.get("OWN_WORKSPACE") or "").rstrip("/")
    kept = []
    for m in sys.meta_path:
        mod = (getattr(m, "__module__", "") or "")
        nom = (getattr(m, "__name__", "") or "")
        if "__editable__" in mod or "__editable__" in nom or "editable" in nom.lower():
            continue
        kept.append(m)
    sys.meta_path = kept
    # `easy-install.pth` puts its target straight on sys.path, so that route goes too -- but only entries that are
    # NOT this run's own workspace. A first version dropped every `/tmp/run-` entry, which included the PYTHONPATH
    # value it was supposed to be testing, and reported the fix failing when it had removed the fix.
    sys.path = [q for q in sys.path
                if "/tmp/run-" not in q or (own and (q == own or q.startswith(own + "/")))]
out = {}
for name in sys.argv[1:]:
    try:
        spec = importlib.util.find_spec(name)
        origin = spec.origin if spec is not None else None
    except Exception as exc:
        out[name] = {"origin": "__absent__", "error": f"{type(exc).__name__}: {exc}"}
        continue
    if not origin:
        out[name] = {"origin": "__absent__", "error": None}
        continue
    out[name] = {"origin": os.path.realpath(origin), "error": None}
print(json.dumps(out))
'''


def _inside(path: str, workspace: str) -> bool:
    """Containment, not a string prefix. Both sides are already real paths when this is called."""
    if not path or not workspace:
        return False
    base = PurePosixPath(workspace.rstrip("/"))
    target = PurePosixPath(path)
    return target == base or str(target).startswith(str(base) + "/")


def verdict(origin: str, workspace: str, *, compiled: bool) -> str:
    """One module's answer.

    `absent` passes only for a compiled submodule. For the top level or a pure module it means the run cannot import
    its own code at all, which is a different failure and not the one this change is allowed to introduce.
    """
    if origin == ABSENT:
        return ABSENT_V if compiled else UNKNOWN
    if not origin:
        return UNKNOWN
    return LOCAL if _inside(origin, workspace) else ELSEWHERE


def passes(verdicts: dict) -> bool:
    """Every module local, except that a compiled one may be absent."""
    for _, v in verdicts.items():
        if v["verdict"] == LOCAL:
            continue
        if v["verdict"] == ABSENT_V and v["compiled"]:
            continue
        return False
    return True


def evaluate(origins: dict, workspace: str, probes: dict = None) -> dict:
    """The probe's raw origins turned into verdicts, keyed by module name."""
    probes = PROBES if probes is None else probes
    compiled_names = {p["compiled"] for p in probes.values() if p["compiled"]}
    out = {}
    for name, got in sorted(origins.items()):
        is_compiled = name in compiled_names
        out[name] = {
            "origin": got.get("origin"),
            "error": got.get("error"),
            "compiled": is_compiled,
            "verdict": verdict(got.get("origin"), workspace, compiled=is_compiled),
        }
    return out


def module_names(probes: dict = None) -> list:
    probes = PROBES if probes is None else probes
    names = []
    for pkg, p in probes.items():
        names.append(pkg)
        for key in ("pure", "compiled"):
            if p.get(key):
                names.append(p[key])
    return names


def run_probe(context: str, namespace: str, deployment: str, workspace: str, cwd: str,
              env: dict, names: list, timeout: int = 300) -> dict:
    """Run the probe in the pod, in a named directory and with a named environment.

    `cwd` is a parameter rather than the workspace because it is what decides the answer: from the workspace root
    `sys.path[0]` already shadows the finder, and from `<ws>/<package>` it does not. A replay that only probes from
    the root cannot see the defect it is checking for.
    """
    # Checked here rather than in argparse: a caller who supplies this function directly (a test, an import) gets
    # to choose its own context and namespace, but the one path that actually reaches a cluster -- this one -- must
    # not fall through to `kubectl --context None -n None`, which fails confusingly instead of cleanly.
    if not context or not namespace:
        raise SystemExit("no context/namespace given (--context/--namespace or TIERBOOK_K8S_CONTEXT/"
                         "TIERBOOK_K8S_NAMESPACE); this will not guess which cluster to run the probe on")
    assignments = " ".join(f"{k}={v}" for k, v in sorted(env.items()))
    inner = f"cd {cwd} && {assignments} python3 -c {json_quote(PROBE_SOURCE)} {' '.join(names)}"
    argv = ["kubectl", "--context", context, "-n", namespace, "exec", f"deploy/{deployment}", "--",
            "sh", "-c", inner]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    line = next((l for l in reversed((proc.stdout or "").splitlines()) if l.strip().startswith("{")), None)
    if not line:
        raise SystemExit(f"the probe produced no JSON.\nstdout: {proc.stdout[-800:]}\n"
                         f"stderr: {proc.stderr[-800:]}")
    return json.loads(line)


def json_quote(s: str) -> str:
    """Single-quote for `sh -c`, since the probe contains double quotes and newlines."""
    return "'" + s.replace("'", "'\\''") + "'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", required=True, help="the run's own workspace, as the driver created it")
    ap.add_argument("--cwd", default=None,
                    help="where to invoke the probe. Defaults to <workspace>/<package-ish>, which is the case that "
                         "fails, NOT the workspace root, where sys.path[0] already shadows the finder")
    ap.add_argument("--pythonpath", default=None,
                    help="set PYTHONPATH for the probe. Omit for the 'before' side of the replay")
    # No cluster default here on purpose: a default that names one person's context or namespace is a
    # footgun in a public repo, not a convenience -- it lets `--help`'s own output run against somebody
    # else's cluster. Required via the flag or the environment; refused below rather than guessed.
    ap.add_argument("--context", default=os.environ.get("TIERBOOK_K8S_CONTEXT"))
    ap.add_argument("--namespace", default=os.environ.get("TIERBOOK_K8S_NAMESPACE"))
    ap.add_argument("--deployment", default="opencode")
    ap.add_argument("--packages", default=None, help="comma-separated subset of " + ",".join(PROBES))
    ap.add_argument("--drop-editable-finders", action="store_true",
                    help="predict what removing the editable-install artifacts (D2) will do, by dropping their "
                         "finders inside the probe. Read-only: it does not touch the pod")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    # Not refused here: `run_probe` is the seam a test replaces to run this without a cluster, and it is the
    # one that actually shells out to `kubectl`, so it is the one that refuses a missing context/namespace.

    probes = PROBES if not a.packages else {k: PROBES[k] for k in a.packages.split(",") if k in PROBES}
    if not probes:
        raise SystemExit(f"no known package in {a.packages!r}; known: {','.join(PROBES)}")

    ws = a.workspace.rstrip("/")
    cwd = a.cwd or f"{ws}/{next(iter(probes))}"
    env = {"PYTHONPATH": a.pythonpath} if a.pythonpath else {}
    if a.drop_editable_finders:
        env["DROP_EDITABLE_FINDERS"] = "1"
        env["OWN_WORKSPACE"] = ws
    names = module_names(probes)
    origins = run_probe(a.context, a.namespace, a.deployment, ws, cwd, env, names)
    verdicts = evaluate(origins, ws, probes)
    ok = passes(verdicts)

    print(f"workspace {ws}")
    print(f"cwd       {cwd}")
    print(f"env       {env or '(none)'}")
    for name, v in verdicts.items():
        mark = {LOCAL: "local", ABSENT_V: "absent", ELSEWHERE: "ELSEWHERE", UNKNOWN: "UNKNOWN"}[v["verdict"]]
        tag = " (compiled)" if v["compiled"] else ""
        print(f"  {mark:<10} {name}{tag}")
        if v["verdict"] == ELSEWHERE:
            print(f"             {v['origin']}")
    print(f"\nimports_local = {ok}")
    if not ok:
        print("  a compiled submodule may be absent, which is the fix working on a tree whose extensions were built\n"
              "  for another interpreter. Anything resolving ELSEWHERE is the defect, and a top-level or pure module\n"
              "  that is absent is a different failure this change is not allowed to introduce.")

    if a.out:
        with open(a.out, "w") as fh:
            json.dump({"workspace": ws, "cwd": cwd, "env": env, "verdicts": verdicts,
                       "imports_local": ok}, fh, indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
