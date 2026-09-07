"""The comparison two marginals cannot make, and the readings a marginal would have permitted."""
import json
import sys
from pathlib import Path

import pytest

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


# --- the interval belongs beside the p-value, never after it ---------------------------------------


def test_the_interval_says_how_large_a_difference_the_test_could_have_missed():
    """"No detectable difference" is a statement about power. At two discordant pairs out of twenty-one the
    interval spans about fourteen points, so quoting p = 1.0 alone reads as "no difference", which is false."""
    a = {f"i{n}": n < 10 for n in range(21)}
    b = dict(a)
    b["i10"] = True            # one item B solved and A did not
    b["i9"] = False            # one item A solved and B did not
    res = pa.paired(a, b)
    assert res["discordant"] == 2 and res["exact_p_two_sided"] == 1.0
    lo, hi = res["gap_ci95_points"]
    assert lo < 0 < hi
    # A review put it at roughly plus or minus fourteen points, i.e. a half-width near fourteen, not a span.
    half = (hi - lo) / 2
    assert 12 <= half <= 16, f"about fourteen points either side, got {half}"
    assert "how large a difference" in res["not_a_verdict"]


def test_a_wide_interval_shrinks_as_the_items_grow():
    """The same discordance over more items is a tighter statement, which is the thing more tasks buy."""
    def span(n):
        a = {f"i{k}": k < n // 2 for k in range(n)}
        b = dict(a)
        b[f"i{n // 2}"] = True
        b[f"i{n // 2 - 1}"] = False
        lo, hi = pa.paired(a, b)["gap_ci95_points"]
        return hi - lo
    assert span(21) > span(100) > span(500)


def test_a_lopsided_discordance_gives_an_interval_that_excludes_zero():
    a = {f"i{n}": True for n in range(10)}
    a.update({f"j{n}": False for n in range(10)})
    b = {f"i{n}": False for n in range(10)}
    b.update({f"j{n}": False for n in range(10)})
    res = pa.paired(a, b)
    lo, hi = res["gap_ci95"]
    assert lo > 0, "A is better and the interval says so"
    assert res["exact_p_two_sided"] < 0.01


def test_the_interval_is_zero_width_when_the_arms_never_disagree():
    a = {f"i{n}": n < 5 for n in range(10)}
    res = pa.paired(a, dict(a))
    assert res["gap_ci95"] == [0.0, 0.0] and res["gap_a_minus_b"] == 0.0


# --- exclusions concentrated on one arm can manufacture the result ---------------------------------


def test_one_sided_exclusions_are_flagged_because_they_can_manufacture_the_result():
    """Excluding items an arm did not observe is right, and if every exclusion sits on one arm then the comparison
    dropped that arm's hardest attempts. Both statements are true about the same act."""
    bal = pa.exclusion_balance(["x", "y", "z"], [], compared=21)
    assert bal["one_sided"] is True
    assert "flatters that arm" in bal["reading"]
    assert bal["share_of_compared"] == pytest.approx(3 / 24)


def test_a_split_exclusion_pattern_is_not_flagged():
    """The pair measured here was two and one, so it was not one-sided -- which is why the check had to exist
    rather than the outcome being assumed."""
    bal = pa.exclusion_balance(["x", "y"], ["z"], compared=21)
    assert bal["one_sided"] is False and "not concentrated on one arm" in bal["reading"]


def test_a_single_exclusion_is_not_called_one_sided():
    """One item is not a pattern, and calling it one would make the flag fire on ordinary runs."""
    assert pa.exclusion_balance(["x"], [], compared=23)["one_sided"] is False


def test_no_exclusions_says_so():
    bal = pa.exclusion_balance([], [], compared=24)
    assert bal["total"] == 0 and bal["reading"] == "no items were excluded"
