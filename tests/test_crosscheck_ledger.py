"""A reconciliation within one authority, and the readings it does and does not license.

It was described as two independent views until a review pointed out that both figures come from the gateway's
own accounting, so a systematic error there produces agreement. What it finds is a bookkeeping gap, and two of
the three defects found in this project's accounting were exactly that.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import crosscheck_ledger as cc  # noqa: E402


def log(tmp_path, rows):
    p = tmp_path / "requests.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def usage(fresh=0, read=0, write=0, out=0):
    return {"prompt_tokens": fresh, "cache_read_input_tokens": read,
            "cache_creation_input_tokens": write, "completion_tokens": out}


def test_the_two_views_agreeing_exactly_is_stated_as_such(tmp_path):
    p = log(tmp_path, [{"usage": usage(fresh=100, out=10)}, {"usage": usage(fresh=200, out=20)}])
    res = cc.compare(330, cc.sum_calls(p), tolerance=0.02)
    assert res["gap"] == 0 and res["within_tolerance"] is True
    assert res["reading"] == "the two views agree exactly"


def test_a_ledger_above_the_replies_reads_as_other_traffic(tmp_path):
    """Which is what it was: a calibration call on the same account during a run."""
    p = log(tmp_path, [{"usage": usage(fresh=100, out=10)}])
    res = cc.compare(1110, cc.sum_calls(p), tolerance=0.02)
    assert res["gap"] == 1000 and res["within_tolerance"] is False
    assert "other traffic in the same window" in res["reading"]
    assert "entries expiring from a rolling window" in res["reading"]


def test_replies_above_the_ledger_read_as_an_accounting_gap(tmp_path):
    """The opposite cause, and the reason the gap is never averaged: these point in opposite directions."""
    p = log(tmp_path, [{"usage": usage(fresh=1000, out=100)}])
    res = cc.compare(110, cc.sum_calls(p), tolerance=0.02)
    assert res["gap"] < 0
    assert "unrecorded ledger update or a" in res["reading"]


def test_every_billed_leg_is_summed_not_just_the_fresh_one(tmp_path):
    """The disjoint convention puts most of an agent's input in the cache legs, so summing prompt_tokens alone
    would make a busy run look tiny -- the exact shape of the failure this project has already had."""
    p = log(tmp_path, [{"usage": usage(fresh=100, read=9000, write=500, out=50)}])
    got = cc.sum_calls(p)
    assert got["total"] == 9650
    assert got["cached_in"] == 9000 and got["cache_write"] == 500


def test_a_refused_request_is_counted_apart_and_not_summed(tmp_path):
    p = log(tmp_path, [{"refused": True, "usage": None}, {"usage": usage(fresh=10, out=1)}])
    got = cc.sum_calls(p)
    assert got["calls"] == 1 and got["refused"] == 1 and got["total"] == 11


def test_an_undelivered_reply_is_counted_and_still_summed(tmp_path):
    """The gateway charged for it whether or not the client received it, so it belongs in the total -- and the
    count is reported because a run losing replies is a different problem from a run costing more."""
    p = log(tmp_path, [{"delivered": False, "usage": usage(fresh=10, out=1)}])
    got = cc.sum_calls(p)
    assert got["undelivered"] == 1 and got["total"] == 11


def test_the_result_says_it_is_not_an_independent_check():
    """The overclaim a review caught: both figures come from one authority, so agreement proves no meter right."""
    res = cc.compare(10, {"total": 10, "calls": 1, "refused": 0, "undelivered": 0,
                          "fresh_in": 10, "cached_in": 0, "cache_write": 0, "out": 0}, tolerance=0.02)
    assert "systematic error" in res["not_an_independent_check"]
    assert "not a wrong" in res["not_an_independent_check"]


def test_an_unparseable_line_is_counted_and_named(tmp_path):
    """An audit instrument that silently ignores what it cannot read reports a total over an unknown subset."""
    p = tmp_path / "requests.jsonl"
    p.write_text('{"usage": {"prompt_tokens": 5}}\nnot json at all\n{"usage": {"completion_tokens": 1}}\n')
    got = cc.sum_calls(p)
    assert got["unparseable_lines"] == [2] and got["total"] == 6


def test_the_sum_can_be_restricted_to_one_cohort(tmp_path):
    """Without it every record is summed, which is right for a log written by one run and wrong for one that
    outlived another."""
    p = tmp_path / "requests.jsonl"
    p.write_text('{"trace_id": "a", "usage": {"prompt_tokens": 10}}\n'
                 '{"trace_id": "b", "usage": {"prompt_tokens": 999}}\n')
    assert cc.sum_calls(p)["total"] == 1009
    assert cc.sum_calls(p, {"a"})["total"] == 10
