"""Tests for the sweep's own failure reporting.

Written after a changed-prompt sweep skipped all 24 items, printed "not in the dataset cache" for every one, and
exited 0. The cache was fine. `task_prompt` lives beside the sweep while `--agent-dir` names the checkout holding
`dataset`, and only the second was on the subprocess's path -- so the message named the one cause it was not, and
the exit status said the arm had run.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
import sweep_agents as sa  # noqa: E402


def _args(tmp_path, **kw):
    a = types.SimpleNamespace(workdir=str(tmp_path), prompt_variant="workspace-bound",
                              agent_dir=str(tmp_path / "agent"), cache=str(tmp_path / "cache.json"))
    a.__dict__.update(kw)
    return a


def test_the_generated_code_puts_the_sweeps_own_directory_on_the_path(tmp_path, monkeypatch):
    """The defect itself: `task_prompt` is importable only from beside this file."""
    seen = {}

    def fake_run(argv, timeout):
        seen["code"] = argv[-1]
        return 0, "some task text"

    monkeypatch.setattr(sa, "run", fake_run)
    ok, why = sa.write_task(_args(tmp_path), "pydata__xarray-4695")
    assert ok and why == ""
    harness = str(Path(sa.__file__).resolve().parent)
    assert harness in seen["code"], "the directory holding task_prompt.py must be on the path"
    assert str(tmp_path / "agent") in seen["code"], "and the agent checkout holding dataset.py still is"


def test_a_missing_instance_is_reported_as_a_missing_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "run", lambda argv, timeout: (1, ""))
    ok, why = sa.write_task(_args(tmp_path), "nope__nope-1")
    assert not ok and why == "not in the dataset cache"


def test_an_import_failure_is_not_reported_as_a_missing_instance(tmp_path, monkeypatch):
    """The whole point. This is what actually happened, and it printed the sentence above 24 times."""
    monkeypatch.setattr(sa, "run", lambda argv, timeout:
                        (1, "Traceback (most recent call last):\nModuleNotFoundError: No module named 'task_prompt'"))
    ok, why = sa.write_task(_args(tmp_path), "pydata__xarray-4695")
    assert not ok
    assert "task_prompt" in why and "dataset cache" not in why


def test_a_timeout_is_reported_as_a_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "run", lambda argv, timeout: (124, "partial\n[timeout]"))
    ok, why = sa.write_task(_args(tmp_path), "pydata__xarray-4695")
    assert not ok and "124" in why


def test_empty_task_text_is_reported_as_empty_rather_than_written(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "run", lambda argv, timeout: (0, "   \n"))
    ok, why = sa.write_task(_args(tmp_path), "pydata__xarray-4695")
    assert not ok and "empty" in why
    assert not list(tmp_path.glob("task-*.md")), "an empty prompt must not be written and then reused"


def test_an_existing_task_file_is_reused(tmp_path, monkeypatch):
    (tmp_path / "task-pydata__xarray-4695-workspace-bound.md").write_text("kept")
    monkeypatch.setattr(sa, "run", lambda argv, timeout: pytest.fail("should not rebuild"))
    assert sa.write_task(_args(tmp_path), "pydata__xarray-4695") == (True, "")


def test_the_variant_is_in_the_task_filename_so_a_baseline_file_is_not_reused(tmp_path, monkeypatch):
    """Without this the changed run would silently measure the baseline prompt -- the quietest possible failure."""
    (tmp_path / "task-pydata__xarray-4695-baseline.md").write_text("the old wording")
    calls = []
    monkeypatch.setattr(sa, "run", lambda argv, timeout: (calls.append(1), (0, "new wording"))[1])
    ok, _ = sa.write_task(_args(tmp_path), "pydata__xarray-4695")
    assert ok and calls, "the baseline file must not satisfy the workspace-bound variant"
    assert (tmp_path / "task-pydata__xarray-4695-workspace-bound.md").read_text() == "new wording"


def test_the_manifest_name_is_keyed_by_run_group(tmp_path):
    assert sa.manifest_path(tmp_path, "i1", "box-qwen-bound").name == "runs-i1-box-qwen-bound.json"
    assert sa.manifest_path(tmp_path, "i1", None).name == "runs-i1.json"
