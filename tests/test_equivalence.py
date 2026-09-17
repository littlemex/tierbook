"""Tests for the two claims a paired comparison can and cannot make.

The ledger records the same error twice: "not significant" was read as "no difference". They are different claims and
the second needs its own test. Alongside it sits the arithmetic that makes the first claim empty at small samples -- an
exact sign test on few discordant pairs cannot reach any usual level, so a False from it describes the sample size.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import counterfactual as cf  # noqa: E402
from tierbook.evidence import EvidenceError, z_for_one_sided  # noqa: E402

NO_KNOB = cf.OperatingPoint(kind="not_applicable")


def cmp_(a_only=20, b_only=4, items=571, p_value=0.002, accuracy_delta=0.028, point=NO_KNOB):
    return cf.Comparison(a="gate", b="always-escalate", items=items, a_only=a_only, b_only=b_only,
                         p_value=p_value, cost_delta=-0.0012, accuracy_delta=accuracy_delta,
                         operating_point=point)


# --- the floor of the test, which is a property of the design and not of the data ----------------------------------

@pytest.mark.parametrize("d,floor,attainable", [(0, 1.0, False), (1, 1.0, False), (4, 0.125, False),
                                                (5, 0.0625, False), (6, 0.03125, True), (10, 0.001953125, True)])
def test_the_smallest_possible_p_depends_only_on_the_discordant_count(d, floor, attainable):
    """The exact two-sided sign test puts both extremes in the tail, so the floor is 2/2**d whatever the data said."""
    c = cmp_(a_only=d, b_only=0)
    assert c.discordant == d
    assert c.minimum_attainable_p == pytest.approx(floor)
    assert c.can_attain(0.05) is attainable


def test_a_test_that_could_not_have_been_significant_refuses_a_verdict():
    """A False here would describe the sample size rather than the world, and the danger is that it reads like
    evidence of no difference -- which is the error this ledger recorded twice."""
    c = cmp_(a_only=3, b_only=2, p_value=1.0)
    with pytest.raises(cf.Unsupported, match="describe the sample size rather than the world"):
        c.is_significant()


def test_the_refusal_points_at_the_two_ways_out():
    c = cmp_(a_only=3, b_only=2, p_value=1.0)
    with pytest.raises(cf.Unsupported) as exc:
        c.is_significant()
    assert "collect more units" in str(exc.value)
    assert "equivalent_within" in str(exc.value)


def test_a_test_that_could_have_been_significant_answers_normally():
    assert cmp_().is_significant() is True
    assert cmp_(p_value=0.40).is_significant() is False


def test_a_looser_alpha_can_make_a_small_test_attainable():
    """The guard is against alpha, not against a fixed number, because the level is the caller's to declare."""
    c = cmp_(a_only=5, b_only=0, p_value=0.0625)
    assert c.can_attain(0.05) is False
    assert c.can_attain(0.10) is True
    assert c.is_significant(alpha=0.10) is True


# --- the claim that "not significant" is not ------------------------------------------------------------------------

def test_a_post_hoc_margin_is_refused():
    """A margin chosen after seeing the difference is a margin chosen to contain it, and this is the one place where
    the order of operations decides whether the answer means anything."""
    with pytest.raises(cf.Unsupported, match="chosen to contain it"):
        cmp_().equivalent_within(0.05, margin_source="post_hoc")


def test_an_unknown_margin_source_is_refused():
    with pytest.raises(EvidenceError, match="not one of"):
        cmp_().equivalent_within(0.05, margin_source="probably fine")


def test_a_zero_or_negative_margin_is_refused():
    """It declares that only an exact tie counts as the same, which no finite sample can show."""
    for bad in (0.0, -0.01):
        with pytest.raises(EvidenceError, match="only an exact tie"):
            cmp_().equivalent_within(bad, margin_source="pre_justified")


def test_two_arms_differing_by_little_on_many_items_are_equivalent_within_a_wide_margin():
    c = cmp_(a_only=6, b_only=6, items=2000, p_value=1.0, accuracy_delta=0.0)
    assert c.equivalent_within(0.05, margin_source="pre_justified") is True


def test_the_same_arms_are_not_equivalent_within_a_margin_narrower_than_the_interval():
    """A wide interval is not equivalence, and this is exactly the case a non-significant p was being read as one."""
    c = cmp_(a_only=3, b_only=2, items=20, p_value=1.0, accuracy_delta=0.05)
    assert c.equivalent_within(0.01, margin_source="pre_justified") is False


def test_not_significant_and_equivalent_are_independent_answers():
    """The point of the whole entry: a comparison can fail to be significant and also fail to be equivalent, and
    reporting only the first invites the reader to conclude the second."""
    c = cmp_(a_only=8, b_only=6, items=40, p_value=0.79, accuracy_delta=0.05)
    assert c.is_significant() is False
    assert c.equivalent_within(0.02, margin_source="pre_justified") is False


# --- the interval the equivalence test rests on --------------------------------------------------------------------

def test_the_interval_is_built_from_the_discordant_counts_not_the_marginals():
    """Two marginals whose intervals overlap can hide a difference every item agrees on, which is the reason to pair
    at all."""
    lo, hi = cmp_(a_only=20, b_only=4, items=571).difference_interval()
    assert lo < (20 - 4) / 571 < hi


def test_the_interval_widens_with_a_stricter_alpha():
    c = cmp_(a_only=20, b_only=4, items=571)
    wide_lo, wide_hi = c.difference_interval(alpha=0.005)
    lo, hi = c.difference_interval(alpha=0.05)
    assert wide_lo < lo and hi < wide_hi


def test_an_empty_comparison_returns_the_whole_range_rather_than_dividing_by_zero():
    assert cmp_(a_only=0, b_only=0, items=0).difference_interval() == (-1.0, 1.0)


# --- the shared quantile table ---------------------------------------------------------------------------------------

def test_the_quantile_is_conservative_between_table_entries():
    """An interpolation would be a number nobody checked, sitting where it decides whether a result is claimed."""
    assert z_for_one_sided(0.05) == 1.6449
    assert z_for_one_sided(0.001) == 2.5758


def test_there_is_one_quantile_table_not_two():
    """policy had a private copy; two copies are one edit from disagreeing about what alpha=0.05 means."""
    assert "_z_for" not in (ROOT / "src/tierbook/policy.py").read_text()


# --- the printed form names which refusal applies -------------------------------------------------------------------

def test_the_printed_form_says_which_verdict_is_missing_and_why():
    """The two cases are named separately because the reader's next move differs: one needs the setting chosen
    elsewhere, the other needs more units."""
    small = str(cmp_(a_only=3, b_only=2, p_value=1.0))
    assert "only 5 discordant pair(s), so the smallest possible p is 0.0625" in small
    chosen = str(cmp_(point=cf.OperatingPoint(kind="fixed", value=0.3, chosen_on="scored_items", knob="coverage")))
    assert "the setting was chosen on the scored items" in chosen
