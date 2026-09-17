"""Tests for a rate that cannot be reported bare, and for the check that now reads its interval.

The measured failure: a conclusion rested on 0.8934, and it "would never have carried its conclusion if 0.9156 had been
printed beside it" -- the upper end of the same interval. The point estimate was not wrong. It was reported alone, and
alone it read as a fact about the world rather than about a sample.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import judge as j  # noqa: E402
from tierbook.evidence import EvidenceError  # noqa: E402
from tierbook.reproduce import Rate  # noqa: E402


# --- a rate carries its size and its interval --------------------------------------------------------------------------

def test_a_rate_over_nothing_is_not_a_rate():
    """Reporting one would put a number where the fact is that nothing was measured."""
    with pytest.raises(EvidenceError, match="not a rate"):
        Rate(successes=0, n=0)


def test_a_count_larger_than_the_total_is_refused():
    with pytest.raises(EvidenceError, match="not a count"):
        Rate(successes=5, n=4)


def test_the_printed_form_always_carries_the_count_and_the_interval():
    """There is no formatting of this that shows the centre alone, which is the whole mechanism."""
    text = str(Rate(successes=21, n=234))
    assert "21/234" in text and "0.0897" in text and "[0.0594, 0.1333]" in text


# --- ruling something out reads the interval, never the centre --------------------------------------------------------

def test_the_measured_case_cannot_rule_out_the_threshold_it_was_used_against():
    """0.8934 against 0.90: at every plausible sample size the interval contains 0.90, so the point estimate was never
    entitled to the conclusion it carried."""
    for n in (300, 500, 1000):
        r = Rate(successes=round(0.8934 * n), n=n)
        assert r.value == pytest.approx(0.8934, abs=1e-3)
        assert r.rules_out(0.90) is False
        assert r.cannot_decide(0.90) is True


def test_a_rate_whose_interval_clears_the_threshold_rules_it_out():
    r = Rate(successes=21, n=234)
    assert r.rules_out(0.20) is True
    assert r.cannot_decide(0.20) is False


def test_both_directions_are_available_and_neither_reads_the_centre():
    r = Rate(successes=180, n=253)
    assert r.rules_out(0.20, above=True) is True     # the whole interval sits above
    assert r.rules_out(0.90, above=True) is False    # the centre is 0.7115, and so is the interval
    assert r.rules_out(0.60) is False                # the centre is above 0.60, so this is not "below"


def test_cannot_decide_is_a_first_class_answer():
    """'The rate is below the floor' and 'this sample cannot tell which side it is on' send a reader to different
    places: the first is a finding, the second is a request for more items."""
    r = Rate(successes=50, n=234)                    # 0.2137, interval straddles 0.20
    assert r.rules_out(0.20) is False
    assert r.rules_out(0.20, above=True) is False
    assert r.cannot_decide(0.20) is True


# --- the base-rate check now reads it ----------------------------------------------------------------------------------

def test_a_base_rate_indistinguishable_from_the_floor_no_longer_clears_it():
    """DEFECT this closes: `clears` compared the point estimate to the floor, so 0.2137 over 234 items cleared a floor
    of 0.20 while its interval ran from 0.166 to 0.272 -- a sample that cannot tell which side of the floor it is on,
    admitted as evidence that the readout works."""
    b = j.BaseRate(correct=50, total=234, floor=0.20)
    assert b.rate > 0.20
    assert b.clears is False
    assert b.cannot_decide is True


def test_a_base_rate_well_above_the_floor_still_clears():
    b = j.BaseRate(correct=180, total=253, floor=0.20)
    assert b.clears is True and b.cannot_decide is False


def test_the_broken_readout_is_still_refused_and_for_the_right_reason():
    """21/234 has an interval entirely below 0.20, so refusing it was decisive rather than a point-estimate accident."""
    b = j.BaseRate(correct=21, total=234, floor=0.20)
    assert b.as_rate.rules_out(0.20) is True
    assert b.clears is False and b.cannot_decide is False


def contract(digest=None):
    d = digest or j.WeightDigest(hex="a" * 64)
    return j.JudgeContract(judge_id="g", weight_digest=d)


def test_admission_distinguishes_cannot_decide_from_below_the_floor():
    """Two refusals with different messages, because one asks for more items and the other says the readout is broken."""
    dig = j.WeightDigest(hex="a" * 64)
    with pytest.raises(j.Inadmissible, match="request for more items"):
        j.admissible(contract(), served=dig, base_rate=j.BaseRate(correct=50, total=234, floor=0.20))
    with pytest.raises(j.Inadmissible, match="ordering of noise"):
        j.admissible(contract(), served=dig, base_rate=j.BaseRate(correct=21, total=234, floor=0.20))


def test_admission_still_passes_a_clearly_working_readout():
    dig = j.WeightDigest(hex="a" * 64)
    j.admissible(contract(), served=dig, base_rate=j.BaseRate(correct=180, total=253, floor=0.20))


def test_the_refusals_print_the_interval_rather_than_the_bare_rate():
    """The point of the whole entry: the number that would have stopped the conclusion has to be beside it."""
    dig = j.WeightDigest(hex="a" * 64)
    with pytest.raises(j.Inadmissible) as exc:
        j.admissible(contract(), served=dig, base_rate=j.BaseRate(correct=21, total=234, floor=0.20))
    assert "[0.0594, 0.1333]" in str(exc.value)
