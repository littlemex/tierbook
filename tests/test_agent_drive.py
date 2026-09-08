"""The driver's outcomes row, which ran on a cluster and therefore had no tests.

It broke exactly the way an untested path breaks: a reference to a name that was not in scope raised inside the
row's dict, so thirteen instances ran to completion, cost real GPU time, and wrote no rows at all. Nothing failed
loudly; the sweep simply produced an empty outcomes file, and it was found by reading a stack trace out of a
state file afterwards.
"""
import json
import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import agent_drive as ad  # noqa: E402


def run_row(**kw):
    base = {"trace_id": "t" * 32, "returned": "/work/returned/x.tar", "timed_out": False,
            "returncode": 0, "wall_s": 12.5}
    base.update(kw)
    return base


def test_the_row_is_built_without_a_cluster():
    """The regression this file exists for: the row must be constructible from plain data."""
    row = ad.outcome_row(run_row(), {"agent_definition": "build"}, "opencode", 0,
                         item_id="astropy__astropy-14365", run_group="g1")
    assert row["trace_id"] == "t" * 32
    assert row["item_id"] == "astropy__astropy-14365" and row["run_group"] == "g1"
    assert row["agent_definition"] == "build" and row["agent"] == "opencode"
    assert row["wall_s"] == 12.5 and row["returncode"] == 0


def test_the_driver_never_states_an_outcome():
    """The oracle has not run. A driver that wrote "solved" here would be inventing the measurement."""
    row = ad.outcome_row(run_row(), {}, "opencode", 0, item_id="i", run_group=None)
    assert row["state"] == "pending_oracle"
    assert "solved" not in json.dumps(row)


def test_a_spec_with_no_definition_records_none_rather_than_an_empty_string():
    """An empty string would join as a candidate whose definition is the empty definition; None says absent."""
    assert ad.outcome_row(run_row(), {}, "a", 0, item_id="i", run_group=None)["agent_definition"] is None
    assert ad.outcome_row(run_row(), {"agent_definition": ""}, "a", 0,
                          item_id="i", run_group=None)["agent_definition"] is None


def test_a_timeout_and_a_nonzero_return_are_both_carried():
    """Both are things the driver OBSERVED, and the scorer needs them to tell a transport fault from a candidate
    that produced nothing."""
    row = ad.outcome_row(run_row(timed_out=True, returncode=124), {"agent_definition": "build"},
                         "opencode", 2, item_id="i", run_group="g")
    assert row["timed_out"] is True and row["returncode"] == 124 and row["iteration"] == 2


def test_a_run_that_returned_no_tree_says_so():
    row = ad.outcome_row(run_row(returned=None), {}, "a", 0, item_id="i", run_group=None)
    assert row["returned"] is None


def test_every_field_the_join_and_the_scorer_read_is_present():
    """The row is the contract between the driver, the oracle and the join. A field silently missing here surfaces
    as an unjoined row much later."""
    row = ad.outcome_row(run_row(), {"agent_definition": "build"}, "opencode", 0,
                         item_id="i", run_group="g")
    required = {"trace_id", "item_id", "run_group", "agent_definition", "agent", "iteration",
                "state", "returned", "timed_out", "returncode", "wall_s"}
    assert required <= set(row), f"missing {required - set(row)}"


def test_the_row_serialises():
    """It is written with json.dumps in an append loop, so a value that cannot serialise loses the whole run."""
    json.dumps(ad.outcome_row(run_row(), {"agent_definition": "build"}, "opencode", 0,
                              item_id="i", run_group="g"))


def test_the_run_records_the_prompt_it_was_actually_given(monkeypatch):
    """The manifest-level `prompt` is the template and still holds the workspace marker, so it cannot say whether
    the one sentence under measurement reached the agent. Each run records its own filled text."""
    ws = "/tmp/run-opencode-0ae4d3229d"
    text = ad.task_prompt.build("astropy/astropy", "an issue",
                                workspace=ad.task_prompt.WORKSPACE_MARKER, variant="workspace-bound")
    filled = ad.task_prompt.fill_workspace(text, ws)
    assert ad.task_prompt.WORKSPACE_MARKER not in filled
    assert ws in filled
    # The substitution is the driver's, done once, in run_one -- pinned here because a second caller doing it
    # again is how a prompt ends up half filled.
    assert filled.count(ws) == 1


# --- D1: the run's own code comes first -----------------------------------------------------------


def test_pythonpath_names_the_runs_own_workspace_and_its_src():
    """Two entries because layouts differ: `<ws>` for astropy, django and pylint, `<ws>/src` for flask."""
    got = ad.python_path_export("/tmp/run-opencode-0ae4d3229d")
    assert got == ("export PYTHONPATH='/tmp/run-opencode-0ae4d3229d:"
                   "/tmp/run-opencode-0ae4d3229d/src'; ")


def test_a_trailing_slash_does_not_produce_a_doubled_separator():
    assert "//" not in ad.python_path_export("/tmp/run-opencode-0ae4d3229d/")


def test_a_relative_workspace_is_refused_because_it_would_depend_on_cwd():
    """The whole defect is about cwd deciding what a run imports, so a relative entry would reintroduce it."""
    for bad in ("", ".", "run-opencode-0ae4d3229d", "~/work"):
        with pytest.raises(ValueError, match="absolute"):
            ad.python_path_export(bad)


def test_a_workspace_with_a_space_is_quoted():
    got = ad.python_path_export("/tmp/run opencode")
    assert "'" in got and got.endswith("; ")


def test_the_export_composes_before_the_telemetry_exports():
    """PYTHONPATH must be set whether or not telemetry is on, which an earlier shape got wrong by building the
    environment string only inside the telemetry branch."""
    assert ad.python_path_export("/tmp/x").endswith("; ")


# --- D3: the workspace goes when the run is done ---------------------------------------------------


WS_T = "/tmp/run-opencode-0ae4d3229d"
BACK = f" ; mkdir -p /work/returned && tar cf /work/returned/x.tar -C {WS_T} ."


def test_the_sweep_up_comes_after_the_hand_back_and_before_the_exit():
    """Order is the whole correctness of this. Removing the tree before the tar would hand back nothing, and removing
    it after the exit would never happen."""
    inner = ad.build_inner(WS_T, ad.python_path_export(WS_T), "", "", BACK, True)
    assert inner.index("tar cf") < inner.index("rm -rf") < inner.index("exit $")


def test_the_agents_status_survives_the_sweep_up():
    """`rm` must not become the command whose exit code the driver reads."""
    inner = ad.build_inner(WS_T, "", "", "", BACK, True)
    assert inner.endswith("exit ${exec_rc:-0}")


def test_nothing_is_removed_when_cleanup_is_off():
    inner = ad.build_inner(WS_T, "", "", "", BACK, False)
    assert "rm -rf" not in inner
    assert "tar cf" in inner


def test_the_environment_is_exported_before_the_agent_starts():
    """A `PYTHONPATH` set after the exec would reach nothing."""
    inner = ad.build_inner(WS_T, ad.python_path_export(WS_T), "", "", "", True)
    assert inner.index("export PYTHONPATH") < inner.index('"$@"')


def test_the_workspace_is_made_before_anything_is_staged_into_it():
    inner = ad.build_inner(WS_T, "", "", f"tar xf /work/x.tar -C {WS_T} && ", "", True)
    assert inner.index("mkdir -p") < inner.index("tar xf")


def test_a_run_with_no_staged_tree_neither_hands_back_nor_keeps_its_workspace():
    inner = ad.build_inner(WS_T, "", "", "", "", True)
    assert "tar cf" not in inner and "rm -rf" in inner


def test_the_pre_commands_run_before_the_agent_and_after_the_environment():
    inner = ad.build_inner(WS_T, ad.python_path_export(WS_T), "setup >/dev/null 2>&1 && ", "", "", True)
    assert inner.index("export PYTHONPATH") < inner.index("setup") < inner.index('"$@"')
