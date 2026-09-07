"""Two views of one quantity, and the readings a single view would have permitted.

This check was available when an arm was declared valid on one view alone, and not running it is how a run whose
requests carried no history got as far as a reported solve count.
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
