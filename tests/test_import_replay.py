"""Tests for the import-resolution gate.

The rule these pin is unusual and easy to get backwards: a compiled submodule that cannot be found is a **pass**,
because once the editable-install artifacts are gone a missing `cpython-311` extension raises instead of being
supplied from another run's tree, and loud is what is wanted. The same answer for the top-level package is a fail --
a run that cannot import its own code at all is a different failure and not one this change may introduce.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
import import_replay as ir  # noqa: E402

WS = "/tmp/run-opencode-0ae4d3229d"
OTHER = "/tmp/run-opencode-acf4781c5e"


def test_a_module_inside_the_workspace_is_local():
    assert ir.verdict(f"{WS}/astropy/__init__.py", WS, compiled=False) == ir.LOCAL
    assert ir.verdict(f"{WS}/astropy/io/ascii/qdp.py", WS, compiled=False) == ir.LOCAL


def test_a_module_in_another_run_is_the_defect():
    """The measurement this whole gate exists for: with PYTHONPATH set, the top level came from the run's own tree
    while `astropy.convolution._convolve` came from `acf4781c5e`."""
    got = ir.verdict(f"{OTHER}/astropy/convolution/_convolve.cpython-311-x86_64-linux-gnu.so", WS, compiled=True)
    assert got == ir.ELSEWHERE


def test_a_missing_compiled_submodule_passes_but_a_missing_package_does_not():
    assert ir.verdict(ir.ABSENT, WS, compiled=True) == ir.ABSENT_V
    assert ir.verdict(ir.ABSENT, WS, compiled=False) == ir.UNKNOWN


def test_a_prefix_that_is_not_a_directory_boundary_is_not_inside():
    """`/tmp/run-opencode-0ae4d3229d-scratch` starts with the workspace string and is a different directory."""
    assert ir.verdict(f"{WS}-scratch/astropy/__init__.py", WS, compiled=False) == ir.ELSEWHERE


def test_the_workspace_itself_counts_as_inside():
    assert ir._inside(WS, WS) and ir._inside(WS + "/", WS)


def _origins(**kw):
    return {k: {"origin": v, "error": None} for k, v in kw.items()}


PROBES_ONE = {"astropy": {"pure": "astropy.io.ascii.qdp", "compiled": "astropy.convolution._convolve"}}


def test_the_whole_environment_fails_when_only_the_compiled_part_is_foreign():
    """The case a top-level-only check calls healthy. This is the reason the gate reads three modules."""
    origins = _origins(**{
        "astropy": f"{WS}/astropy/__init__.py",
        "astropy.io.ascii.qdp": f"{WS}/astropy/io/ascii/qdp.py",
        "astropy.convolution._convolve": f"{OTHER}/astropy/convolution/_convolve.cpython-311.so",
    })
    v = ir.evaluate(origins, WS, PROBES_ONE)
    assert v["astropy"]["verdict"] == ir.LOCAL
    assert v["astropy.convolution._convolve"]["verdict"] == ir.ELSEWHERE
    assert ir.passes(v) is False, "a top-level-only check would have passed this"


def test_the_environment_passes_when_the_compiled_part_is_merely_absent():
    origins = _origins(**{
        "astropy": f"{WS}/astropy/__init__.py",
        "astropy.io.ascii.qdp": f"{WS}/astropy/io/ascii/qdp.py",
    })
    origins["astropy.convolution._convolve"] = {"origin": ir.ABSENT, "error": "ModuleNotFoundError: _convolve"}
    v = ir.evaluate(origins, WS, PROBES_ONE)
    assert ir.passes(v) is True


def test_the_environment_fails_when_the_package_itself_is_absent():
    origins = {"astropy": {"origin": ir.ABSENT, "error": "ModuleNotFoundError"},
               "astropy.io.ascii.qdp": {"origin": ir.ABSENT, "error": "ModuleNotFoundError"},
               "astropy.convolution._convolve": {"origin": ir.ABSENT, "error": "ModuleNotFoundError"}}
    v = ir.evaluate(origins, WS, PROBES_ONE)
    assert ir.passes(v) is False, "a run that cannot import its own code is not this change succeeding"


def test_every_probed_name_is_asked_for():
    names = ir.module_names(PROBES_ONE)
    assert names == ["astropy", "astropy.io.ascii.qdp", "astropy.convolution._convolve"]
    full = ir.module_names()
    for pkg in ir.PROBES:
        assert pkg in full
        assert ir.PROBES[pkg]["pure"] in full


def test_a_package_without_a_compiled_submodule_still_gets_its_other_two_checked():
    v = ir.evaluate(_origins(**{"pylint": f"{WS}/pylint/__init__.py",
                                "pylint.checkers.base": f"{OTHER}/pylint/checkers/base.py"}),
                    WS, {"pylint": {"pure": "pylint.checkers.base", "compiled": None}})
    assert ir.passes(v) is False


def test_the_probe_source_reports_absent_rather_than_raising(tmp_path):
    """Run the real probe text against this interpreter, so a syntax error or a raised exception in it fails here
    rather than at the pod."""
    import subprocess
    p = subprocess.run([sys.executable, "-c", ir.PROBE_SOURCE, "json", "no_such_module_xyz"],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    got = json.loads(p.stdout.strip().splitlines()[-1])
    assert got["no_such_module_xyz"]["origin"] == ir.ABSENT
    assert got["json"]["origin"].endswith("json/__init__.py")


def test_the_probe_is_quoted_so_its_newlines_and_quotes_survive_sh():
    quoted = ir.json_quote(ir.PROBE_SOURCE)
    assert quoted.startswith("'") and quoted.endswith("'")
    assert "'\\''" in ir.json_quote("it's")


def test_the_default_cwd_is_the_failing_one_not_the_workspace_root(monkeypatch, capsys):
    """From the workspace root `sys.path[0]` already shadows the finder, so a replay that probes there cannot see the
    defect. The default has to be the directory the two affected runs actually used."""
    seen = {}

    def fake(context, namespace, deployment, workspace, cwd, env, names, timeout=300):
        seen.update(cwd=cwd, env=env, names=names)
        return _origins(**{n: f"{workspace}/x.py" for n in names})

    monkeypatch.setattr(ir, "run_probe", fake)
    monkeypatch.setattr(sys, "argv", ["import_replay.py", "--workspace", WS, "--packages", "astropy"])
    ir.main()
    assert seen["cwd"] == f"{WS}/astropy"
    assert seen["cwd"] != WS


def test_pythonpath_is_only_set_when_asked_so_the_before_side_is_the_real_before(monkeypatch):
    seen = {}

    def fake(context, namespace, deployment, workspace, cwd, env, names, timeout=300):
        seen.update(env=env)
        return _origins(**{n: f"{workspace}/x.py" for n in names})

    monkeypatch.setattr(ir, "run_probe", fake)
    monkeypatch.setattr(sys, "argv", ["import_replay.py", "--workspace", WS, "--packages", "astropy"])
    ir.main()
    assert seen["env"] == {}
    monkeypatch.setattr(sys, "argv", ["import_replay.py", "--workspace", WS, "--packages", "astropy",
                                      "--pythonpath", WS])
    ir.main()
    assert seen["env"] == {"PYTHONPATH": WS}


def test_an_unknown_package_is_refused_rather_than_silently_probing_nothing(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["import_replay.py", "--workspace", WS, "--packages", "nope"])
    with pytest.raises(SystemExit) as e:
        ir.main()
    assert "no known package" in str(e.value)


def test_the_exit_status_carries_the_verdict(monkeypatch):
    def foreign(context, namespace, deployment, workspace, cwd, env, names, timeout=300):
        return _origins(**{n: f"{OTHER}/x.py" for n in names})

    monkeypatch.setattr(ir, "run_probe", foreign)
    monkeypatch.setattr(sys, "argv", ["import_replay.py", "--workspace", WS, "--packages", "astropy"])
    assert ir.main() == 1


def test_the_simulation_flag_reaches_the_probe_as_an_environment_variable(monkeypatch):
    """D2's effect is predicted read-only, by dropping the finders inside the probe. A probe that mutated the pod to
    measure a proposal would change the environment the next run sees."""
    seen = {}

    def fake(context, namespace, deployment, workspace, cwd, env, names, timeout=300):
        seen.update(env=env)
        return {n: {"origin": f"{workspace}/x.py", "error": None} for n in names}

    monkeypatch.setattr(ir, "run_probe", fake)
    monkeypatch.setattr(sys, "argv", ["import_replay.py", "--workspace", WS, "--packages", "astropy",
                                      "--pythonpath", WS, "--drop-editable-finders"])
    ir.main()
    assert seen["env"] == {"PYTHONPATH": WS, "DROP_EDITABLE_FINDERS": "1", "OWN_WORKSPACE": WS}


def test_the_probe_still_parses_and_runs_with_the_simulation_off_and_on():
    import subprocess, os
    for extra in ({}, {"DROP_EDITABLE_FINDERS": "1"}):
        env = dict(os.environ, **extra)
        p = subprocess.run([sys.executable, "-c", ir.PROBE_SOURCE, "json"],
                           capture_output=True, text=True, env=env)
        assert p.returncode == 0, p.stderr
        assert json.loads(p.stdout.strip().splitlines()[-1])["json"]["origin"].endswith("json/__init__.py")


def test_the_simulation_keeps_the_runs_own_workspace_on_the_path():
    """A first version dropped every `/tmp/run-` entry from sys.path, which included the PYTHONPATH value it was
    supposed to be testing, and then reported the fix failing because it had removed the fix."""
    import os, subprocess, textwrap
    own = "/tmp/run-opencode-own"
    probe = ir.PROBE_SOURCE + textwrap.dedent("""
        import sys
        print(json.dumps({"path": [p for p in sys.path if "/tmp/run-" in p]}))
        """)
    env = dict(os.environ, DROP_EDITABLE_FINDERS="1", OWN_WORKSPACE=own,
               PYTHONPATH=f"{own}:/tmp/run-opencode-other")
    p = subprocess.run([sys.executable, "-c", probe, "json"], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    kept = json.loads(p.stdout.strip().splitlines()[-1])["path"]
    assert own in kept, "the run's own workspace must survive"
    assert "/tmp/run-opencode-other" not in kept, "another run's must not"


def test_the_simulation_matches_a_finder_placed_as_a_class_not_an_instance():
    """setuptools puts the editable finder on meta_path as a class, so `type(m).__module__` is `builtins` and a filter
    reading it matches nothing. That was the first version's bug."""
    import os, subprocess, textwrap
    probe = textwrap.dedent("""
        import sys, json, os
        class __editable___fake_finder:
            __module__ = "__editable___astropy_5_3_finder"
            @classmethod
            def find_spec(cls, *a, **k):
                return None
        sys.meta_path.append(__editable___fake_finder)
        """) + ir.PROBE_SOURCE + textwrap.dedent("""
        print(json.dumps({"names": [getattr(m, "__name__", "") for m in sys.meta_path]}))
        """)
    env = dict(os.environ, DROP_EDITABLE_FINDERS="1", OWN_WORKSPACE="/tmp/run-opencode-own")
    p = subprocess.run([sys.executable, "-c", probe, "json"], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    names = json.loads(p.stdout.strip().splitlines()[-1])["names"]
    assert not any("editable" in n.lower() for n in names), names
