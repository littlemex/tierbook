"""The mechanism check a contract made a pass condition, and the readings an outcome would have permitted.

A run's outcome cannot say whether it stayed in its workspace: an agent that wandered, was refused and gave up
produces the same `unobserved` as one with nothing to say, and an agent that wandered and recovered produces a
`solved` with the wandering invisible. Both happened in one 24-item cohort.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import workspace_audit as wa  # noqa: E402

WS = "/tmp/run-opencode-8c042ffb40"


def call(name, args, success=True, error=None):
    return wa.audit_call(name, json.dumps(args), success, error, WS)


def test_a_path_under_the_workspace_says_nothing():
    assert call("read", {"filePath": f"{WS}/astropy/units/format/cds.py"}) is None
    assert call("grep", {"path": WS, "pattern": "x"}) is None, "the workspace root is inside itself"


def test_a_relative_path_is_not_inspected():
    """It is relative to the workspace by construction, and 34 of 44 real glob calls carried no path at all."""
    assert call("glob", {"pattern": "**/*.py"}) is None
    assert call("grep", {"path": "astropy/units", "pattern": "x"}) is None


def test_the_one_character_truncation_is_caught():
    """The sharpest evidence in the recordings: an agent reconstructed its own workspace path and lost a character
    off the end, so it named a directory that did not exist and was refused."""
    f = call("glob", {"pattern": "**/*.py", "path": "/tmp/run-opencode-8c042ffb4"},
             success=False, error="The user rejected permission to use this specific tool call.")
    assert f is not None
    assert f["outside_workspace"] == ["path=/tmp/run-opencode-8c042ffb4"]
    assert f["refused"] is True


def test_the_filesystem_root_and_a_sibling_are_caught():
    assert call("grep", {"path": "/", "pattern": "x"})["outside_workspace"] == ["path=/"]
    assert call("glob", {"path": "/tmp", "pattern": "x"})["outside_workspace"] == ["path=/tmp"]
    assert call("read", {"filePath": "/src/matplotlib/x.py"})["outside_workspace"]


def test_a_network_fetch_is_caught_even_though_it_names_no_path():
    """One run tried `cd /tmp && git clone https://github.com/pytest-dev/pytest.git` and stopped when refused."""
    f = call("bash", {"command": "cd /tmp && git clone --depth 1 https://github.com/pytest-dev/pytest.git"})
    assert f["network"] is True


def test_a_pattern_that_looks_like_a_path_is_not_read_as_one():
    """Path keys are named rather than every value being scanned, so `**/*.py` is a pattern and stays one."""
    assert call("glob", {"pattern": "/**/*.py"}) is None


def test_a_tool_schema_error_is_deliberately_not_this_audits_business():
    """One run's `todowrite` failed because the call omitted a required key. That is a tool-contract defect, not a
    workspace question, and reporting it here would fold two unrelated findings behind one result. It is recorded
    in the change's phase-1 notes instead, where it can be fixed on its own terms."""
    f = call("todowrite", {"todos": [{"content": "x", "status": "done"}]}, success=False,
             error='invalid arguments: SchemaError(Missing key at ["todos"][0]["priority"])')
    assert f is None, "no path outside the workspace, no network, and not a permission refusal"


def test_unparseable_arguments_do_not_hide_a_refusal():
    f = wa.audit_call("bash", "{not json", False,
                      "The user rejected permission to use this specific tool call.", WS)
    assert f["refused"] is True


def test_a_run_whose_workspace_is_unknown_fails_the_mechanism_check(tmp_path):
    """An unknown workspace cannot be audited, so counting it as clean would let the check pass on ignorance."""
    traces = tmp_path / "t.jsonl"
    span = {"traceId": "t1", "name": "opencode.tool.glob",
            "attributes": [{"key": "tool.name", "value": {"stringValue": "glob"}},
                           {"key": "tool.parameters",
                            "value": {"stringValue": json.dumps({"pattern": "**/*.py"})}},
                           {"key": "tool.success", "value": {"boolValue": True}}]}
    traces.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}) + "\n")
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text(json.dumps({"trace_id": "t1", "item_id": "i1", "state": "solved"}) + "\n")
    res = wa.audit(traces, outcomes, [])
    assert res["workspace_unknown"] == ["i1"]
    assert res["mechanism_pass"] is False
    assert "cannot be audited" in res["mechanism_note"]


def test_the_workspace_is_recovered_from_the_returned_tar_when_no_manifest_has_it(tmp_path):
    """It had to be, once: a second sweep over the same instances overwrote the first's manifests."""
    ws, why = wa.workspace_of("t1", [], "/work/returned/opencode-8c042ffb40.tar")
    assert ws == "/tmp/run-opencode-8c042ffb40"
    assert "overwrites the first" in why


def test_the_manifest_wins_over_the_recovered_name(tmp_path):
    m = tmp_path / "runs-x.json"
    m.write_text(json.dumps({"runs": [{"trace_id": "t1", "workspace": "/tmp/run-opencode-from-manifest"}]}))
    ws, why = wa.workspace_of("t1", [m], "/work/returned/opencode-other.tar")
    assert ws == "/tmp/run-opencode-from-manifest" and "manifest" in why


def test_a_clean_cohort_passes_the_mechanism_check(tmp_path):
    traces = tmp_path / "t.jsonl"
    spans = [{"traceId": "t1", "name": "opencode.tool.read",
              "attributes": [{"key": "tool.name", "value": {"stringValue": "read"}},
                             {"key": "tool.parameters",
                              "value": {"stringValue": json.dumps({"filePath": f"{WS}/a.py"})}},
                             {"key": "tool.success", "value": {"boolValue": True}}]}]
    traces.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}) + "\n")
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text(json.dumps({"trace_id": "t1", "item_id": "i1", "state": "solved",
                                    "returned": "/work/returned/opencode-8c042ffb40.tar"}) + "\n")
    res = wa.audit(traces, outcomes, [])
    assert res["mechanism_pass"] is True and res["clean"] == 1


def test_a_tool_whose_purpose_is_the_network_is_not_a_wandering_run():
    """The first real cohort flagged a `webfetch` from a run that SOLVED. Using a granted tool is a tool-policy
    question for whoever granted it, not evidence that a run left its directory."""
    assert call("webfetch", {"url": "https://matplotlib.org/stable/api.html"}) is None


def test_a_url_inside_file_content_is_not_a_network_call():
    """It flagged an `edit` whose file content contained a URL. A pass condition built on that would fail runs for
    writing a docstring."""
    assert call("edit", {"filePath": f"{WS}/a.py",
                         "newString": "# see https://docs.python.org/3/library/ast.html\nx = 1"}) is None


def test_a_command_that_reaches_the_network_is_still_caught():
    f = call("bash", {"command": "pip install requests --index-url https://pypi.org/simple"})
    assert f["network"] is True
