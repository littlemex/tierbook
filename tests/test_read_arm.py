"""Tests for the gate that keeps the precondition ahead of the numbers.

The point of the file under test is an ordering: an arm whose runs may not have had a checkout must not produce a
rate. So the test that matters is that it REFUSES, and that it refuses before computing anything.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
import read_arm as ra  # noqa: E402

TAIL = "x\\nPASSED tests/test_a.py::test_b\\n99 passed in 3.1s\\n"
UNSCOREABLE_TAIL = '"scoreable": false, "reason": "this instance could not be scored here"'


def row(item, state="incorrect", files=1, diff=90, tail=TAIL, trace=None):
    return {"item_id": item, "state": state, "trace_id": trace or f"t-{item}",
            "oracle": {"files_touched": files, "diff_bytes": diff, "tail": tail}}


def _arm(tmp_path, rows, spans=None):
    outcomes = tmp_path / "outcomes.jsonl"
    outcomes.write_text("".join(json.dumps(r) + "\n" for r in rows))
    traces = tmp_path / "traces.jsonl"
    traces.write_text("".join(
        json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [s]}]}]}) + "\n" for s in (spans or [])))
    man = tmp_path / "runs-all.json"
    man.write_text(json.dumps({"runs": [{"trace_id": r["trace_id"], "workspace": f"/tmp/w/{r['item_id']}"}
                                        for r in rows]}))
    return outcomes, traces, tmp_path


def _span(trace, ws, tool="read"):
    return {"traceId": trace, "name": f"opencode.tool.{tool}",
            "attributes": [{"key": "tool.name", "value": {"stringValue": tool}},
                           {"key": "tool.parameters",
                            "value": {"stringValue": json.dumps({"filePath": f"{ws}/a.py"})}},
                           {"key": "tool.success", "value": {"boolValue": True}}]}


def test_solves_counts_over_the_scoreable_items_only(tmp_path):
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text("".join(json.dumps(r) + "\n" for r in [
        row("i1", "solved"), row("i2", "incorrect"), row("bad-item", "incorrect")]))
    got = ra.solves(outcomes, {"bad-item"})
    assert got["scoreable"] == 2 and got["solved"] == 1
    assert got["excluded_unscoreable"] == ["bad-item"]


def test_a_run_that_edited_nothing_is_counted(tmp_path):
    """2, 2, 0 across the workspace-binding arms, which is where that change's effect showed while the paired table
    could not see it."""
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text("".join(json.dumps(r) + "\n" for r in [
        row("i1", "solved"), row("i2", "unobserved", files=0, diff=0)]))
    got = ra.solves(outcomes, set())
    assert got["zero_edit"] == 1 and got["zero_edit_items"] == ["i2"]


def test_a_readable_arm_reports_all_three_sections(tmp_path, monkeypatch, capsys):
    rows = [row("i1", "solved"), row("i2")]
    outcomes, traces, man = _arm(tmp_path, rows,
                                 [_span(r["trace_id"], f"/tmp/w/{r['item_id']}") for r in rows])
    monkeypatch.setattr(sys, "argv", ["read_arm.py", "--outcomes", str(outcomes), "--traces", str(traces),
                                      "--manifests", str(man), "--out", str(tmp_path / "art")])
    assert ra.main() == 0
    printed = capsys.readouterr().out
    assert "was every run given a checkout" in printed
    assert "stay in its own workspace" in printed
    assert "solved 1/2" in printed
    saved = json.loads((tmp_path / "art" / "arm.json").read_text())
    assert set(saved) == {"staging", "audit", "solves"}


def test_an_unreadable_arm_refuses_and_prints_no_rate(tmp_path, monkeypatch, capsys):
    """The whole point. A run whose tree was never staged looks exactly like an agent that did nothing, so a rate
    computed over it is not a rate."""
    rows = [row("i1", "solved"), row("i2", tail="ERROR: file or directory not found\\n")]
    outcomes, traces, man = _arm(tmp_path, rows,
                                 [_span(r["trace_id"], f"/tmp/w/{r['item_id']}") for r in rows])
    monkeypatch.setattr(sys, "argv", ["read_arm.py", "--outcomes", str(outcomes), "--traces", str(traces),
                                      "--manifests", str(man), "--out", str(tmp_path / "art")])
    with pytest.raises(SystemExit) as e:
        ra.main()
    assert "not readable" in str(e.value)
    printed = capsys.readouterr().out
    assert "solved" not in printed, "no rate may be printed above the refusal"
    assert not (tmp_path / "art" / "arm.json").exists()


def test_an_unscoreable_item_does_not_stop_the_arm(tmp_path, monkeypatch, capsys):
    rows = [row("i1", "solved"), row("bad", tail=UNSCOREABLE_TAIL)]
    outcomes, traces, man = _arm(tmp_path, rows,
                                 [_span(r["trace_id"], f"/tmp/w/{r['item_id']}") for r in rows])
    monkeypatch.setattr(sys, "argv", ["read_arm.py", "--outcomes", str(outcomes), "--traces", str(traces),
                                      "--manifests", str(man), "--out", str(tmp_path / "art")])
    assert ra.main() == 0
    printed = capsys.readouterr().out
    assert "solved 1/1" in printed, "the unscoreable item is out of the denominator, not a blocker"
    assert "out of the denominator" in printed


def test_a_missing_artifact_from_an_instrument_is_a_refusal_rather_than_an_empty_dict(tmp_path):
    with pytest.raises(SystemExit) as e:
        ra.run_json([str(tmp_path / "no_such_script.py")], tmp_path / "gone.json")
    assert "produced no artifact" in str(e.value)


def test_a_missing_files_touched_is_not_zero(tmp_path):
    """Some oracle records carry only `rc` and `tail`, and `astropy__astropy-14369` is one of them in an arm where it
    SOLVED. Reading the absent key as zero reported 8, 9 and 6 zero-edit runs against the true 2, 2 and 0."""
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text("".join(json.dumps(r) + "\n" for r in [
        {"item_id": "astropy__astropy-14369", "state": "solved", "trace_id": "t1",
         "oracle": {"rc": 0, "tail": TAIL}},
        {"item_id": "pydata__xarray-4695", "state": "unobserved", "trace_id": "t2",
         "oracle": {"rc": 0, "tail": TAIL, "files_touched": 0, "diff_bytes": 0}}]))
    got = ra.solves(outcomes, set())
    assert got["zero_edit_items"] == ["pydata__xarray-4695"]
    assert got["solved"] == 1


def test_a_run_with_no_oracle_at_all_is_not_counted_as_zero_edit(tmp_path):
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text(json.dumps({"item_id": "i1", "state": "incorrect", "trace_id": "t1"}) + "\n")
    assert ra.solves(outcomes, set())["zero_edit"] == 0
