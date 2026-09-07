"""Run-to-run movement on a fixed item set, and the readings one run would have permitted.

This project applied the run-it-twice rule to policies and to load probes -- where the capacity bound died -- and
not to the arm's solve rate, which is what every comparison here rests on.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import replicates as rp  # noqa: E402


def test_a_reproducible_candidate_says_a_difference_would_mean_something():
    a = {f"i{n}": n < 10 for n in range(24)}
    res = rp.agreement([a, dict(a)])
    assert res["flipped"] == [] and res["spread"] == 0 and res["stdev"] == 0.0
    assert "candidate is reproducible" in res["reading"]


def test_flipped_items_are_named_because_they_cannot_carry_a_comparison():
    """A difference between arms resting on an item that flips between runs of one candidate is a difference
    between two draws of that candidate."""
    a = {"x": True, "y": True, "z": False}
    b = {"x": True, "y": False, "z": True}
    res = rp.agreement([a, b])
    flipped = {f["item_id"] for f in res["flipped"]}
    assert flipped == {"y", "z"}
    assert res["stable_solved"] == 1 and res["stable_unsolved"] == 0
    assert res["spread"] == 0, "identical counts, two items disagreeing"
    assert "cannot carry a comparison" in res["reading"]


def test_the_count_moving_is_reported_separately_from_the_items_moving():
    """Two different facts: how many the candidate solved, and which ones."""
    a = {"x": True, "y": True, "z": True}
    b = {"x": True, "y": False, "z": False}
    res = rp.agreement([a, b])
    assert res["solved_per_run"] == [3, 1] and res["spread"] == 2
    assert len(res["flipped"]) == 2


def test_an_item_missing_from_one_run_is_excluded_and_named():
    """A rate over a shifting item set is not a rate, and the shifting is usually the interesting part."""
    res = rp.agreement([{"x": True, "only_a": True}, {"x": True}])
    assert res["items_in_every_run"] == 1 and res["excluded_partial"] == ["only_a"]


def test_it_says_it_does_not_replace_item_sampling_noise():
    res = rp.agreement([{"x": True}, {"x": True}])
    assert "Item-sampling noise is separate" in res["not_a_substitute"]


def test_one_replicate_is_refused_by_the_cli(tmp_path, capsys):
    p = tmp_path / "j.json"
    p.write_text(json.dumps({"rows": [{"item_id": "x", "state": "solved"}]}))
    old = sys.argv
    sys.argv = ["replicates", "--joined", str(p)]
    try:
        with pytest.raises(SystemExit) as e:
            rp.main()
    finally:
        sys.argv = old
    assert "one run is a reading, not a rate" in str(e.value)


def test_unobserved_items_are_kept_apart_per_run(tmp_path):
    p = tmp_path / "j.json"
    p.write_text(json.dumps({"rows": [{"item_id": "x", "state": "solved"},
                                      {"item_id": "y", "state": "unobserved",
                                       "unobserved_reason": "unsupported"}]}))
    solved, unobs = rp.solved_by_item(p)
    assert solved == {"x": True} and unobs == ["y"]
