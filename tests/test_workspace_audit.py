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


def test_a_tool_whose_purpose_is_the_network_is_reported_but_not_a_wandering_run():
    """The first real cohort flagged a `webfetch` from a run that SOLVED. Using a granted tool is a tool-policy
    question for whoever granted it, not evidence that a run left its directory -- so it is recorded and kept out
    of the verdict, rather than being invisible."""
    f = call("webfetch", {"url": "https://matplotlib.org/stable/api.html"})
    assert f["network_via_granted_tool"] is True
    assert f["outside_workspace"] == [] and f["refused_for_a_path"] is False


def test_a_url_inside_file_content_is_not_a_network_call():
    """It flagged an `edit` whose file content contained a URL. A pass condition built on that would fail runs for
    writing a docstring."""
    assert call("edit", {"filePath": f"{WS}/a.py",
                         "newString": "# see https://docs.python.org/3/library/ast.html\nx = 1"}) is None


def test_a_command_that_reaches_the_network_is_still_caught():
    f = call("bash", {"command": "pip install requests --index-url https://pypi.org/simple"})
    assert f["network"] is True


def test_a_run_that_made_no_tool_calls_does_not_pass_by_doing_nothing(tmp_path):
    """It has zero out-of-workspace paths, which is the shape of the failure this check was built to find and must
    not be the shape of passing it."""
    traces = tmp_path / "t.jsonl"
    traces.write_text("")
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text(json.dumps({"trace_id": "t1", "item_id": "i1", "state": "unobserved",
                                    "returned": "/work/returned/opencode-abc.tar"}) + "\n")
    res = wa.audit(traces, outcomes, [])
    assert res["no_tool_calls"] == ["i1"]
    assert res["mechanism_pass"] is False
    assert "doing\nnothing" in res["mechanism_note"].replace(" nothing", "\nnothing") or \
        "doing nothing" in res["mechanism_note"]


def test_a_shell_command_naming_a_path_outside_the_workspace_is_caught():
    """A `bash` call has no path argument to read, so the command string is read instead. One real run did
    `find /tmp -name "*.py"` and the audit saw nothing."""
    f = call("bash", {"command": 'find /tmp -name "*.py" -path "*/xarray/*" | head -50'})
    assert f["shell_paths_outside"] == ["/tmp"]
    assert f["outside_workspace"] == [], "kept apart: one is a named argument, the other a parsed string"


def test_a_shell_command_inside_the_workspace_is_not_flagged():
    f = call("bash", {"command": f"cd {WS} && python -m pytest tests/test_x.py"})
    assert f is None


def test_directories_every_checkout_touches_are_not_flagged():
    """Reading /proc or writing to /dev/null is not a run leaving its workspace, and flagging it would make the
    check noise."""
    for cmd in ("cat /proc/cpuinfo", "python -c 'x' 2>/dev/null", "ls /usr/lib/python3",
                "echo hi > /dev/null"):
        assert call("bash", {"command": cmd}) is None, cmd


def test_a_bare_root_in_a_command_is_not_read_as_a_path():
    """A slash appears in flags, regexes and arithmetic. Treating every one as a directory would flag almost
    everything."""
    assert call("bash", {"command": "python -c 'print(3/4)'"}) is None
    assert call("bash", {"command": "grep -E 'a/b|c' file.txt"}) is None


def test_a_glob_pattern_is_not_read_as_an_absolute_path():
    """`*/xarray/*` was being read as the directory `/xarray/`. A pattern and a path look identical from the right,
    so the exclusion is on what precedes the slash."""
    f = call("bash", {"command": 'find . -path "*/xarray/*" -name "*.py"'})
    assert f is None
    f2 = call("bash", {"command": 'grep -rn "x" */src/*.py'})
    assert f2 is None


def test_a_relative_path_in_a_shell_command_is_not_read_as_absolute():
    """Two real commands: `find . -path ./tests -prune` was read as the directory `/tests`, and
    `find . -path ./.git -prune` as `/.git`."""
    for cmd in (f'cd {WS} && find . -path ./tests -prune -o -name "*.py" -print',
                f'cd {WS} && find . -path ./.git -prune -o -type f -print'):
        assert call("bash", {"command": cmd}) is None, cmd


def test_a_scratch_file_written_outside_the_workspace_is_caught():
    """A real run wrote /tmp/test_typehints.py and ran a tool against it. That is work happening outside the
    directory the run is supposed to be confined to, and no named argument records it."""
    f = call("bash", {"command": f"cd {WS} && cat > /tmp/test_typehints.py << 'EOF'\nclass C: pass\nEOF"})
    assert f["shell_paths_outside"] == ["/tmp/test_typehints.py"]


# --- every clause of the contract's pass condition, including the one the code used to drop -------


def test_the_refusal_string_is_pinned_to_a_real_span():
    """Cut from the telemetry rather than guessed: a change in the tool's wording must fail here rather than
    silently zeroing the count, which would make the verdict pass on ignorance."""
    observed = "The user rejected permission to use this specific tool call."
    assert wa.REFUSED in observed
    f = call("grep", {"path": "/", "pattern": "x"}, success=False, error=observed)
    assert f["refused"] is True and f["refused_for_a_path"] is True


def test_a_path_refusal_counts_against_the_verdict(tmp_path):
    """The contract's pass condition says zero permission rejections attributable to a path. The code counted them,
    printed them, and then left them out of the verdict -- keeping the fragile half of a deliberately redundant
    pair and dropping the robust one."""
    span = {"traceId": "t1", "name": "opencode.tool.grep",
            "attributes": [{"key": "tool.name", "value": {"stringValue": "grep"}},
                           {"key": "tool.parameters",
                            "value": {"stringValue": json.dumps({"path": "/", "pattern": "x"})}},
                           {"key": "tool.success", "value": {"boolValue": False}},
                           {"key": "tool.error", "value": {"stringValue":
                                                           "The user rejected permission to use this call."}}]}
    traces = tmp_path / "t.jsonl"
    traces.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}) + "\n")
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text(json.dumps({"trace_id": "t1", "item_id": "i1", "state": "incorrect",
                                    "returned": "/work/returned/opencode-abc.tar"}) + "\n")
    res = wa.audit(traces, outcomes, [])
    assert res["with_path_refusals"] == 1
    assert res["mechanism_pass"] is False


def test_a_refusal_about_a_tools_own_arguments_does_not_count_against():
    """Otherwise a `todowrite` refused for omitting a schema key would fail a change about workspaces."""
    f = call("todowrite", {"todos": [{"content": "x"}]}, success=False,
             error='rejected permission is not the reason; SchemaError(Missing key ["priority"])')
    assert f["refused"] is True and f["refused_for_a_path"] is False


def test_the_module_says_it_does_decide_this_one_thing():
    """The other instruments here report and decide nothing. This one is a pass condition, so it returns a verdict
    and an exit status -- and saying both would be a contradiction."""
    doc = Path(ROOT / "harness" / "workspace_audit.py").read_text()
    assert "This one does decide something" in doc
    assert "It reports; it decides nothing." not in doc


# --- attempted, as the contract means it after being amended ---------------------------------------


def test_attempted_is_a_change_to_the_repository_not_activity():
    """A review pointed out that "files touched" is satisfied by a scratch file, and the contract was amended before
    any run. Both figures come from the oracle and are measured against the staged tree."""
    did, why = wa.attempted({"files_touched": 1, "diff_bytes": 428})
    assert did is True and "428 bytes" in why


def test_zero_files_is_not_an_attempt():
    did, why = wa.attempted({"files_touched": 0, "diff_bytes": 0})
    assert did is False and "nothing was attempted" in why


def test_files_touched_with_an_empty_diff_is_reported_as_neither():
    """A run that opened files and changed nothing is a third thing, and folding it into either answer would hide
    it."""
    did, why = wa.attempted({"files_touched": 3, "diff_bytes": 0})
    assert did is False and "which is not a change" in why


def test_a_missing_oracle_record_with_no_state_is_not_read_as_an_attempt():
    assert wa.attempted(None)[0] is False
    assert wa.attempted({})[0] is False
    assert "nothing says this run changed anything" in wa.attempted({"rc": 0})[1]


def test_a_solved_run_whose_counts_were_truncated_is_not_called_never_tried():
    """The counts are parsed out of the scorer's captured output, which truncates: six of one cohort's twenty-four
    runs lack them, including one that solved. Reading absence as "not attempted" put a solved run in that list."""
    did, why = wa.attempted({"rc": 0, "tail": "..."}, "solved")
    assert did is True
    assert "rests on the state" in why and "truncated" in why


def test_the_weaker_basis_is_not_used_where_the_counts_exist():
    """The counts are the strong form the contract asks for, and a state must not override them."""
    did, why = wa.attempted({"files_touched": 0, "diff_bytes": 0}, "solved")
    assert did is False and "nothing was attempted" in why


def test_an_unobserved_run_is_not_attempted_on_either_basis():
    assert wa.attempted({"rc": 0}, "unobserved")[0] is False


# --- the cohort, containment, and the clause that lost its contract basis --------------------------


def test_an_empty_cohort_does_not_pass_by_having_no_data(tmp_path):
    """No out-of-workspace paths, no unknown workspaces, no silent runs -- a verdict manufactured by absent data."""
    traces = tmp_path / "t.jsonl"
    traces.write_text("")
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text("")
    assert wa.audit(traces, outcomes, [])["mechanism_pass"] is False


def test_a_cohort_short_of_its_expected_size_is_reported_and_fails(tmp_path):
    span = {"traceId": "t1", "name": "opencode.tool.read",
            "attributes": [{"key": "tool.name", "value": {"stringValue": "read"}},
                           {"key": "tool.parameters",
                            "value": {"stringValue": json.dumps({"filePath": f"{WS}/a.py"})}},
                           {"key": "tool.success", "value": {"boolValue": True}}]}
    traces = tmp_path / "t.jsonl"
    traces.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}) + "\n")
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text(json.dumps({"trace_id": "t1", "item_id": "i1", "state": "solved",
                                    "oracle": {"files_touched": 1, "diff_bytes": 100},
                                    "returned": "/work/returned/opencode-8c042ffb40.tar"}) + "\n")
    assert wa.audit(traces, outcomes, [], expect_items=1)["mechanism_pass"] is True
    short = wa.audit(traces, outcomes, [], expect_items=24)
    assert short["cohort_complete"] is False and short["mechanism_pass"] is False


def test_a_prefix_is_not_containment():
    """`/w/../etc` starts with `/w` and is not inside it. A string comparison would have passed it."""
    assert wa._inside(f"{WS}/a/b.py", WS) is True
    assert wa._inside(WS, WS) is True
    assert wa._inside(f"{WS}/../etc/passwd", WS) is False
    assert wa._inside(f"{WS}-other/a.py", WS) is False, "a sibling sharing the prefix"


def test_a_relative_path_that_leaves_is_caught():
    """An earlier docstring said a path without a leading slash is relative to the workspace "by construction".
    `../..` is relative and leaves."""
    assert call("read", {"filePath": "../../etc/passwd"})["outside_workspace"]
    assert call("read", {"filePath": "astropy/units/cds.py"}) is None


def test_reaching_the_network_is_reported_and_does_not_fail_the_verdict(tmp_path):
    """The contract's condition is about the workspace, and since the prompt no longer claims to be offline there
    is nothing for a network clause to verify. The incoherence was worse than the overreach: a real webfetch was
    exempt while a URL inside a shell string failed the run."""
    f = call("webfetch", {"url": "https://raw.githubusercontent.com/x/y/z.py"})
    assert f is not None and f["network"] is True and f["network_via_granted_tool"] is True
    assert f["outside_workspace"] == [] and f["shell_paths_outside"] == []

    span = {"traceId": "t1", "name": "opencode.tool.webfetch",
            "attributes": [{"key": "tool.name", "value": {"stringValue": "webfetch"}},
                           {"key": "tool.parameters",
                            "value": {"stringValue": json.dumps({"url": "https://example.com/a"})}},
                           {"key": "tool.success", "value": {"boolValue": True}}]}
    traces = tmp_path / "t.jsonl"
    traces.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}) + "\n")
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text(json.dumps({"trace_id": "t1", "item_id": "i1", "state": "solved",
                                    "oracle": {"files_touched": 1, "diff_bytes": 50},
                                    "returned": "/work/returned/opencode-8c042ffb40.tar"}) + "\n")
    res = wa.audit(traces, outcomes, [], expect_items=1)
    assert res["with_network"] == 1
    assert res["mechanism_pass"] is True, "reported, not fatal"
    assert "nothing for a network clause to verify" in res["mechanism_note"]


# --- another run's workspace, which the noisy scan found happening ---------------------------------


KNOWN = {"/tmp/run-opencode-700cd74ee4", "/tmp/run-opencode-c4cd6ae898", "/tmp/run-opencode-0ae4d3229d"}


def test_writing_into_another_runs_workspace_is_caught_and_counts():
    """Found by the noisy shell scan, and precise enough to carry a verdict. One agent ran
    `cp /tmp/run-opencode-700cd74ee4/.../qdp.py /tmp/run-opencode-c4cd6ae898/.../qdp.py` -- copying its edit into a
    different run's directory, left on disk by an earlier sweep and still writable. That can change another run's
    result with nothing downstream showing where it came from."""
    mine = "/tmp/run-opencode-700cd74ee4"
    f = wa.audit_call("bash", json.dumps({"command":
                                          f"cp {mine}/astropy/io/ascii/qdp.py "
                                          "/tmp/run-opencode-c4cd6ae898/astropy/io/ascii/qdp.py"}),
                      True, None, mine, KNOWN)
    assert f["other_run_workspaces"] == ["/tmp/run-opencode-c4cd6ae898"]


def test_a_named_argument_pointing_at_another_run_is_caught_too():
    f = call("read", {"filePath": "/tmp/run-opencode-deadbeef/astropy/a.py"})
    assert f["other_run_workspaces"] == ["/tmp/run-opencode-deadbeef"]


def test_a_path_inside_this_runs_own_workspace_is_not_another_run():
    assert call("bash", {"command": f"ls {WS}/astropy"}) is None


def test_unit_expressions_are_why_shell_paths_do_not_carry_the_verdict(tmp_path):
    """On real data the parser read `J/m/s/kpc2` out of a Python comment as the directories /m/s/kpc2, /s and
    /kpc2. A pass condition cannot rest on that, so shell paths are reported and the verdict uses the precise
    check instead."""
    # Verbatim from the run. A closing bracket before a slash is never a path and is now excluded, but the second
    # form has a SPACE before `/m/s/kpc2`, which is exactly what a real absolute path looks like. No lookbehind can
    # separate them, which is the whole reason this signal is reported and not counted.
    assert call("bash", {"command": 'python3 -c "\n# should be ((J/m)/s)/kpc2 = J\n"'}) is None
    cmd = 'python3 -c "\n# after J, we see /m/s/kpc2\n"'
    f = call("bash", {"command": cmd})
    assert f is not None and f["shell_paths_outside"] == ["/m/s/kpc2"], "still reported"
    span = {"traceId": "t1", "name": "opencode.tool.bash",
            "attributes": [{"key": "tool.name", "value": {"stringValue": "bash"}},
                           {"key": "tool.parameters",
                            "value": {"stringValue": json.dumps({"command": cmd})}},
                           {"key": "tool.success", "value": {"boolValue": True}}]}
    traces = tmp_path / "t.jsonl"
    traces.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}) + "\n")
    outcomes = tmp_path / "o.jsonl"
    outcomes.write_text(json.dumps({"trace_id": "t1", "item_id": "i1", "state": "solved",
                                    "oracle": {"files_touched": 1, "diff_bytes": 90},
                                    "returned": "/work/returned/opencode-8c042ffb40.tar"}) + "\n")
    res = wa.audit(traces, outcomes, [], expect_items=1)
    assert res["with_shell_paths_outside"] == 1
    assert res["mechanism_pass"] is True, "reported, not counted"


def test_bare_system_directories_are_benign():
    """`find /usr -name git` was flagged because the benign list required a trailing slash."""
    assert call("bash", {"command": "find /usr -name git -type f | head -5"}) is None
    assert call("bash", {"command": "ls /proc"}) is None


# --- and the class that is much larger than contamination: the agent writing its own id wrong ---------------


def _f(cmd, ws="/tmp/run-opencode-0ae4d3229d", known=None):
    return wa.audit_call("bash", json.dumps({"command": cmd}), True, None, ws,
                         KNOWN if known is None else known)


def test_a_shortened_own_id_is_reported_as_a_mangled_id_not_as_another_run():
    """Verbatim from the baselines. `0ae4d3229d` came back as `d3229d`, `415edc1dee` as `415edc17`, `9ef07f454b` as
    `9ef07f4b`, `daf8d8a993` as `daf8d8a93`, `8c042ffb40` as `8c042ffb4` -- six runs across two baselines. None of
    those directories ever existed, so calling them another run's workspace would have been wrong."""
    for wrong in ("/tmp/run-opencode-d3229d", "/tmp/run-opencode-415edc17", "/tmp/run-opencode-9ef07f4b",
                  "/tmp/run-opencode-daf8d8a93", "/tmp/run-opencode-8c042ffb4"):
        f = _f(f"ls {wrong}/astropy")
        assert f["mangled_own_workspace"] == [wrong], wrong
        assert f["other_run_workspaces"] == []
        assert f["workspace_shaped_but_unknown"] == []


def test_a_well_formed_id_absent_from_the_manifests_is_left_undecided():
    """The manifests are keyed by item, so a later sweep overwrites an earlier one's file. `c4cd6ae898` was the
    first baseline's real astropy workspace and the second baseline's manifest had replaced it -- an earlier version
    of this code called that a mangled id, which was wrong."""
    f = _f("ls /tmp/run-opencode-abcdef0123/astropy", known={"/tmp/run-opencode-0ae4d3229d"})
    assert f["workspace_shaped_but_unknown"] == ["/tmp/run-opencode-abcdef0123"]
    assert f["mangled_own_workspace"] == [] and f["other_run_workspaces"] == []


def test_the_id_length_is_derived_from_the_real_workspaces_not_written_here():
    """A driver that changes its id length must not turn every path into a mangled one."""
    assert wa._id_lengths({"/tmp/run-opencode-0ae4d3229d"}) == {10}
    assert wa._id_lengths({"/tmp/run-x-abc", "/tmp/run-y-defg"}) == {3, 4}
    long_known = {"/tmp/run-opencode-" + "a" * 16}
    f = _f("ls /tmp/run-opencode-" + "b" * 16, known=long_known)
    assert f["workspace_shaped_but_unknown"], "right length for this driver, so not a mangled id"


def test_with_no_manifests_the_softer_label_is_not_invented():
    f = _f("ls /tmp/run-opencode-d3229d", known=set())
    assert f["other_run_workspaces"] == ["/tmp/run-opencode-d3229d"]
    assert f["mangled_own_workspace"] == []


def test_all_three_classes_count_against_the_mechanism(tmp_path):
    for cmd in ("ls /tmp/run-opencode-d3229d", "ls /tmp/run-opencode-abcdef0123",
                "ls /tmp/run-opencode-c4cd6ae898"):
        span = {"traceId": "t1", "name": "opencode.tool.bash",
                "attributes": [{"key": "tool.name", "value": {"stringValue": "bash"}},
                               {"key": "tool.parameters", "value": {"stringValue": json.dumps({"command": cmd})}},
                               {"key": "tool.success", "value": {"boolValue": True}}]}
        traces = tmp_path / "t.jsonl"
        traces.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}) + "\n")
        outcomes = tmp_path / "o.jsonl"
        outcomes.write_text(json.dumps({"trace_id": "t1", "item_id": "i1", "state": "solved",
                                        "oracle": {"files_touched": 1, "diff_bytes": 90},
                                        "returned": "/work/returned/opencode-0ae4d3229d.tar"}) + "\n")
        manifest = tmp_path / "runs-i1.json"
        manifest.write_text(json.dumps({"runs": [{"trace_id": "t1", "workspace": "/tmp/run-opencode-0ae4d3229d"},
                                                 {"trace_id": "t2", "workspace": "/tmp/run-opencode-c4cd6ae898"}]}))
        res = wa.audit(traces, outcomes, [manifest], expect_items=1)
        assert res["mechanism_pass"] is False, cmd
