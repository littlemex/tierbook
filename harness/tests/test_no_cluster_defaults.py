"""Nothing under `harness/` may carry a default that names a cluster or a namespace.

A default pointing at one person's context is worse than no default at all: it is a public repository handing a reader
a command that runs against somebody else's cluster, and it leaks the shape of a private environment on the way. Six
scripts carried one. Removing them was easy; the reason this file exists is that nothing then depended on their
absence, so the next script to be added would carry one again and every test would stay green.

So this is a closed-world scan rather than a check per script. It reads every file under `harness/`, finds every place
a cluster-ish value gets a default, and requires that default to come from the environment. A seventh script cannot
be added with a literal without failing here, which is the difference between a rule and a habit.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]

#: The two variables that carry a cluster's identity, and the only legitimate source of one.
CONTEXT_VAR = "TIERBOOK_K8S_CONTEXT"
NAMESPACE_VAR = "TIERBOOK_K8S_NAMESPACE"

#: Argparse flags and module constants whose value identifies a cluster. Adding a third kind of cluster-identifying
#: name means adding it here, and the scan below then covers it everywhere at once.
CLUSTER_FLAGS = ("--context", "--namespace")
CLUSTER_CONSTANTS = ("CTX", "NS")


def harness_sources() -> list[Path]:
    return sorted(p for p in HARNESS.glob("*.py") if p.name != "__init__.py")


def test_the_scan_actually_sees_files():
    """Catches the scan silently covering nothing -- a glob that matches no file makes every test below vacuous,
    and a vacuous ratchet is worse than none because it reads as coverage."""
    assert len(harness_sources()) >= 5


@pytest.mark.parametrize("path", harness_sources(), ids=lambda p: p.name)
def test_no_cluster_flag_carries_a_literal_default(path: Path):
    """Catches the leak coming back. A literal `default="some-cluster"` on `--context` or `--namespace` is the exact
    shape that was removed from six scripts, and without this scan the seventh script would carry one again."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        flag = next((a.value for a in node.args if isinstance(a, ast.Constant) and a.value in CLUSTER_FLAGS), None)
        if flag is None:
            continue
        default = next((kw.value for kw in node.keywords if kw.arg == "default"), None)
        assert default is not None, f"{path.name}: {flag} has no default at all, which is fine, but say so explicitly"
        # A literal string here is the defect. `os.environ.get(...)` is a Call, and `None` is a Constant whose value
        # is None -- both acceptable, because neither names a cluster.
        if isinstance(default, ast.Constant):
            assert default.value is None, (
                f"{path.name}: {flag} defaults to the literal {default.value!r}. A default that names a cluster "
                f"belongs to whoever wrote it, not to whoever clones this repository")


@pytest.mark.parametrize("path", harness_sources(), ids=lambda p: p.name)
def test_a_cluster_flags_default_comes_from_the_declared_variable(path: Path):
    """Catches a default read from the environment under the wrong name. `os.environ.get("KUBE_CONTEXT")` is not a
    leak but it is not the contract either, and two names for one value is how an operator sets the one nothing
    reads and gets a refusal they cannot explain."""
    tree = ast.parse(path.read_text())
    expected = {"--context": CONTEXT_VAR, "--namespace": NAMESPACE_VAR}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        flag = next((a.value for a in node.args if isinstance(a, ast.Constant) and a.value in CLUSTER_FLAGS), None)
        default = next((kw.value for kw in node.keywords if kw.arg == "default"), None)
        if flag is None or not isinstance(default, ast.Call):
            continue
        names = [a.value for a in ast.walk(default) if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        assert expected[flag] in names, (
            f"{path.name}: {flag} takes a default from {names} rather than {expected[flag]!r}")


@pytest.mark.parametrize("path", harness_sources(), ids=lambda p: p.name)
def test_a_module_level_cluster_constant_is_not_a_literal(path: Path):
    """Catches the form the flags do not cover. `CTX, NS = "a-cluster", "a-namespace"` at module scope was the sixth
    occurrence, and it is invisible to any check that only walks `add_argument` calls."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        # `node.targets` only, never `ast.walk(node)`: walking the whole statement reaches the value side, so a line
        # that USES the constants -- `run(["kubectl", "--context", CTX, "-n", NS, ...])` -- was read as a line that
        # assigns them, and the command's own literals were reported as the leak.
        targets = [t.id for tgt in node.targets for t in ast.walk(tgt) if isinstance(t, ast.Name)]
        if not any(c in targets for c in CLUSTER_CONSTANTS):
            continue
        literals = [v.value for v in ast.walk(node.value)
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                    and v.value not in (CONTEXT_VAR, NAMESPACE_VAR)]
        assert not literals, (
            f"{path.name}: {targets} is assigned the literal(s) {literals}. Read the cluster from "
            f"{CONTEXT_VAR}/{NAMESPACE_VAR} instead")


def test_no_harness_file_mentions_a_private_cluster_or_namespace():
    """The backstop for every form the two scans above do not model -- a docstring, a help string, an f-string, a
    comment, a recorded command line. Two occurrences of an internal hostname were already public in this repository
    before a scan like this existed, which is why the backstop is here and not only the structural checks."""
    # Deliberately the literal names, so this test is the record of what was removed. A future private name has to be
    # added here to be covered, and that is the known limit of a denylist -- the two structural scans above are what
    # cover the shape rather than the spelling.
    forbidden = re.compile(r"distai-eks|qwen-trial")
    here = Path(__file__).resolve()
    offenders = [f"{p.name}:{n}" for p in HARNESS.rglob("*")
                 # This file is excluded because it carries the two names on purpose, as the record of what was
                 # removed. Without the exclusion the scan reports itself, which reads exactly like a real leak.
                 if p.is_file() and p.resolve() != here and p.suffix in (".py", ".md", ".yaml", ".json", ".sh")
                 for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1)
                 if forbidden.search(line)]
    assert offenders == [], f"a private cluster or namespace is named in {offenders}"


@pytest.mark.parametrize("script", ["agent_drive.py", "score_outcomes.py", "sweep_agents.py", "testbed.py"],
                         ids=lambda s: s)
def test_a_script_refuses_rather_than_guessing_when_the_environment_is_unset(script: str):
    """Catches the removal being done by deleting the default and nothing else. Without a refusal the flag silently
    becomes `None` and the script builds a `kubectl` invocation with an empty context, which either talks to whatever
    the operator's kubeconfig happens to point at or fails somewhere far from the cause."""
    env = {k: v for k, v in os.environ.items() if k not in (CONTEXT_VAR, NAMESPACE_VAR)}
    # Each of these needs one more required argument to get past argparse; the point is only that it stops on the
    # cluster, so a placeholder for the rest is enough.
    extra = {"agent_drive.py": ["--spec", "x", "--task", "x"],
             "score_outcomes.py": ["--outcomes", "x", "--instance", "x"],
             "sweep_agents.py": ["--instances", "x"], "testbed.py": ["up", "--instance", "x"]}
    proc = subprocess.run([sys.executable, str(HARNESS / script), *extra[script]],
                          capture_output=True, text=True, env=env, cwd=str(HARNESS))
    assert proc.returncode != 0, f"{script} ran with no cluster named"
    combined = proc.stdout + proc.stderr
    assert CONTEXT_VAR in combined or NAMESPACE_VAR in combined, (
        f"{script} refused without naming the variable to set: {combined[-400:]!r}")
    assert "Traceback" not in combined, f"{script} refused by crashing: {combined[-400:]!r}"
