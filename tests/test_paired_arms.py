"""The comparison two marginals cannot make, and the readings a marginal would have permitted."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import paired_arms as pa  # noqa: E402


def joined(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(json.dumps({"rows": rows}))
    return p


def row(item, state):
    return {"item_id": item, "state": state}


def test_equal_marginals_can_hide_many_disagreements():
    """The whole reason two binomials are the wrong statistic: 5 against 5 is compatible with the arms agreeing
    everywhere and with them disagreeing on ten items."""
    same = {f"i{i}": i < 5 for i in range(10)}
    res_agree = pa.paired(same, dict(same))
    assert res_agree["a_solved"] == res_agree["b_solved"] == 5
    assert res_agree["discordant"] == 0

    flipped = {f"i{i}": i >= 5 for i in range(10)}
    res_disagree = pa.paired(same, flipped)
    assert res_disagree["a_solved"] == res_disagree["b_solved"] == 5
    assert res_disagree["discordant"] == 10, "identical marginals, complete disagreement"


def test_the_named_items_are_reported_not_just_counts():
    """"These three tasks the box got and the API did not" is something an operator can read; a p-value is not."""
    a = {"x": True, "y": True, "z": False}
    b = {"x": True, "y": False, "z": True}
    res = pa.paired(a, b)
    assert res["items"]["a_only"] == ["y"] and res["items"]["b_only"] == ["z"]
    assert res["items"]["both"] == ["x"] and res["items"]["neither"] == []


def test_one_discordant_item_does_not_separate_the_arms():
    """10 against 11 with one disagreement: the exact test says what it should."""
    a = {f"i{i}": i < 10 for i in range(24)}
    b = dict(a)
    b["i10"] = True
    res = pa.paired(a, b)
    assert res["a_solved"] == 10 and res["b_solved"] == 11
    assert res["discordant"] == 1 and res["exact_p_two_sided"] == 1.0


def test_a_lopsided_discordance_is_what_would_separate_them():
    a = {f"i{i}": True for i in range(8)}
    a.update({f"j{i}": False for i in range(8)})
    b = {f"i{i}": False for i in range(8)}
    b.update({f"j{i}": False for i in range(8)})
    res = pa.paired(a, b)
    assert res["discordant"] == 8 and res["exact_p_two_sided"] < 0.01


def test_an_item_only_one_arm_attempted_is_excluded_and_named():
    """A marginal built on different item sets is not a comparison of arms."""
    res = pa.paired({"x": True, "only_a": True}, {"x": False, "only_b": True})
    assert res["items_compared"] == 1
    assert res["a_only_excluded"] == ["only_a"] and res["b_only_excluded"] == ["only_b"]


def test_an_unobserved_item_is_kept_apart_rather_than_counted_as_a_failure(tmp_path):
    """A configuration fact recorded as incapability is how a harness defect becomes a model's score."""
    p = joined(tmp_path, "a.json", [row("x", "solved"), row("y", "incorrect"),
                                    {"item_id": "z", "state": "unobserved",
                                     "unobserved_reason": "unsupported"}])
    solved, unobs = pa.outcomes_by_item(p)
    assert solved == {"x": True, "y": False}
    assert unobs == [{"item_id": "z", "reason": "unsupported"}]


def test_the_result_says_a_high_p_is_not_evidence_of_sameness():
    res = pa.paired({"x": True}, {"x": True})
    assert "not evidence they are the same" in res["not_a_verdict"]
    assert "WHERE the arms differ" in res["not_a_verdict"]
