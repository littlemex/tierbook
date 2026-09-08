"""Tests for the precondition that says whether an arm can be read.

The rule they pin: a run's exit status and its archive's size both agreed with a broken environment, so neither is
evidence. What separates "the agent had nothing to work with" from "the agent had something and did nothing" is the
scorer having run the repository's own tests against the returned tree.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
import staging_check as sc  # noqa: E402

#: Cut from a real recorded tail, INCLUDING the fact that its newlines are the two literal characters `\` and `n`.
#: That is what defeated the first version of the pattern, and a fixture with real newlines would not have caught it.
PYTEST_TAIL = ('d_example\\nPASSED astropy/io/ascii/tests/test_qdp.py::test_roundtrip_example'
               '\\nPASSED astropy/io/ascii/tests/test_qdp.py::test_read_write_simple\\n')


def row(item="i1", state="incorrect", tail=PYTEST_TAIL, trace="t1", files=1):
    return {"item_id": item, "state": state, "trace_id": trace,
            "oracle": {"files_touched": files, "diff_bytes": 90, "tail": tail}}


def test_a_test_session_in_the_scorer_output_proves_a_checkout():
    assert sc.verdict(row(), None)[0] == "staged"


def test_the_several_spellings_a_test_session_takes_are_all_accepted():
    """The instances span pytest versions and some report only a summary line."""
    for tail in ("99 passed, 20 warnings in 3.12s", "1 failed, 98 passed in 2.9s",
                 "PASSED tests/test_x.py::test_y", "=========== test session starts ===========",
                 "3 error in 1.2s", "FAILED tests/test_x.py::test_y"):
        assert sc.verdict(row(tail=tail), None)[0] == "staged", tail


def test_a_tail_whose_newlines_are_literal_backslash_n_is_still_recognised():
    """The defect that made a first version of this precondition condemn all four recorded arms. The tails carry
    newlines as two characters, so in `\\nPASSED` the character before `P` is a word character and a leading `\\b`
    matches nothing. A precondition that fails this way is worse than none: it condemns every measurement on a regex.
    """
    assert sc.verdict(row(tail="d_example\\nPASSED astropy/io/ascii/tests/test_qdp.py::test_x\\n"), None)[0] \
        == "staged"
    assert sc.verdict(row(tail="x\\n99 passed, 20 warnings in 3.12s\\n"), None)[0] == "staged"


def test_scorer_output_with_no_test_session_is_a_missing_checkout():
    """What an empty or stale tree looks like: the scorer ran and found nothing to run."""
    v, why = sc.verdict(row(tail="ERROR: file or directory not found: xarray/tests\n"), None)
    assert v == "no-checkout" and "stale tree" in why


def test_no_scorer_output_at_all_is_unknown_rather_than_either_answer():
    v, why = sc.verdict(row(tail=""), None)
    assert v == "unknown" and "nothing here says" in why


def test_a_driver_reported_setup_failure_outranks_the_scorer():
    """It is not evidence about a candidate whatever the scorer went on to say."""
    for m in ({"setup_failed": True}, {"returncode": sc.SETUP_FAILED}):
        v, why = sc.verdict(row(), m)
        assert v == "setup-failed" and "not evidence about a candidate" in why


def test_a_normal_returncode_does_not_trigger_the_setup_verdict():
    assert sc.verdict(row(), {"returncode": 0, "setup_failed": False})[0] == "staged"
    assert sc.verdict(row(), {"returncode": 1, "setup_failed": False})[0] == "staged"


def _arm(tmp_path, rows, manifest_runs=None):
    out = tmp_path / "outcomes.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    manifests = []
    if manifest_runs:
        m = tmp_path / "runs-i1.json"
        m.write_text(json.dumps({"runs": manifest_runs}))
        manifests = [m]
    return sc.check(out, manifests)


def test_an_arm_where_every_run_was_staged_is_readable(tmp_path):
    res = _arm(tmp_path, [row(item=f"i{i}", trace=f"t{i}") for i in range(3)])
    assert res["readable"] is True and res["counts"] == {"staged": 3}


def test_one_run_without_a_checkout_makes_the_whole_arm_unreadable(tmp_path):
    """Leaving it in the denominator credits the arm with a failure the harness caused."""
    rows = [row(item="i0", trace="t0"), row(item="i1", trace="t1", tail="ERROR: not found\n")]
    res = _arm(tmp_path, rows)
    assert res["readable"] is False
    assert res["counts"]["no-checkout"] == 1


def test_an_empty_arm_is_not_readable(tmp_path):
    """Zero runs and 'every run was staged' are both technically true, and reading nothing as a pass is the shape of
    defect this whole file exists to stop."""
    res = _arm(tmp_path, [])
    assert res["readable"] is False


def test_a_setup_failure_makes_the_arm_unreadable_too(tmp_path):
    res = _arm(tmp_path, [row(trace="t1")], manifest_runs=[{"trace_id": "t1", "returncode": sc.SETUP_FAILED}])
    assert res["readable"] is False and res["counts"]["setup-failed"] == 1


def test_the_exit_status_carries_the_verdict(tmp_path, monkeypatch, capsys):
    out = tmp_path / "outcomes.jsonl"
    out.write_text(json.dumps(row()) + "\n")
    monkeypatch.setattr(sys, "argv", ["staging_check.py", "--outcomes", str(out)])
    assert sc.main() == 0
    out.write_text(json.dumps(row(tail="ERROR: not found\n")) + "\n")
    assert sc.main() == 1


def test_the_django_instances_use_unittest_and_are_not_missing_checkouts():
    """Three django runs per arm were reported as having no checkout because the pattern knew only pytest. Their
    trees were fine and their runner says so in unittest's words."""
    for tail in ("test_widget_output (forms_tests.tests.test_forms.FormsTestCase) ... ok\\n"
                 "----------------------------\\nRan 111 tests in 0.236s\\n\\nOK\\n",
                 "Ran 261 tests in 0.534s\\n\\nOK\\nDestroying test database for alias 'default'",
                 "Ran 4 tests in 0.01s\\n\\nFAILED (failures=1)"):
        assert sc.verdict(row(tail=tail), None)[0] == "staged", tail


def test_an_agent_that_crashed_the_runner_still_had_a_checkout():
    """`pytest-dev__pytest-7432` in the first baseline: the tree was real -- its traceback names
    /testbed/src/_pytest/skipping.py -- and the agent's own edit crashed pytest so no tests ran. Calling that a
    missing checkout blames the harness for the agent's patch."""
    tail = ('stbed/src/_pytest/skipping.py\\", line 296, in pytest_runtest_makereport\\nINTERNALERROR> '
            "TypeError: get() missing 1 required positional argument\\n\\nno tests ran in 0.06s\\n")
    v, why = sc.verdict(row(tail=tail), None)
    assert v == "staged"
    assert "whether the tests then passed is the scorer's business" in why


def test_a_permanently_unscoreable_instance_is_its_own_verdict():
    """`pylint-dev__pylint-4551` reports that this checkout does not contain its FAIL_TO_PASS ids, in all three
    recorded arms. Its tree was real -- pytest collected the module -- and it can never be anything but incorrect."""
    tail = ('[<Module tests/unittest_pyreverse_writer.py>])\\n"\n  },\n  "resolved": false,\n'
            '  "scoreable": false,\n  "reason": "this instance could not be scored here"\n}\n')
    v, why = sc.verdict(row(tail=tail), None)
    assert v == "unscoreable"
    assert "regardless of what the agent did" in why


def test_an_unscoreable_item_leaves_the_arm_readable_but_out_of_the_denominator(tmp_path):
    """It is constant across arms and cannot flatter one, so it does not condemn the measurement -- but a rate whose
    denominator includes it is wrong."""
    good = row(item="i0", trace="t0")
    uns = row(item="pylint-dev__pylint-4551", trace="t1",
              tail='"scoreable": false, "reason": "could not be scored"')
    res = _arm(tmp_path, [good, uns])
    assert res["readable"] is True
    assert res["unscoreable_items"] == ["pylint-dev__pylint-4551"]
    assert res["scoreable_runs"] == 1
