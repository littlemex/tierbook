"""Tests for what a cost is measured in.

The ledger records this as unaddressed and gives the reason: tokens are a weak proxy for cost, and a policy ahead in
tokens can lose in GPU-seconds because a token count does not see KV-cache occupancy or the effect of a long trace on
every other request sharing the batch. Measuring GPU-seconds needs load rather than more items, so that half stays
owed. What is checkable without the measurement is that a cost names its unit and that two units are never subtracted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import counterfactual as cf  # noqa: E402
from tierbook.evidence import EvidenceError  # noqa: E402

NO_KNOB = cf.OperatingPoint(kind="not_applicable")


def run(label="a", unit="usd", cost=(0.004, 0.006), solved=(True, False)):
    return cf.Run(label=label, items=("i1", "i2"), solved=solved, usd=cost,
                  calls=(("cheap",), ("cheap",)), cost_unit=unit)


# --- the unit is named, and the vocabulary is closed ---------------------------------------------------------------

def test_an_open_ended_unit_is_refused():
    """An unchecked unit cannot be checked for commensurability, which is the only reason to name it."""
    with pytest.raises(EvidenceError, match="not one of"):
        run(unit="dollars-ish")


def test_the_default_is_usd_because_the_field_is_named_usd():
    """Honest rather than plausible-looking: every existing caller put dollars in a field called `usd`, so that is the
    true statement about those runs."""
    assert cf.Run(label="a", items=("i1",), solved=(True,), usd=(0.004,), calls=(("cheap",),)).cost_unit == "usd"


# --- the accessor that asserts a unit refuses when the unit is not that one ----------------------------------------

def test_usd_per_item_answers_for_a_dollar_run():
    assert run().usd_per_item == pytest.approx(0.005)


@pytest.mark.parametrize("unit", ["tokens", "gpu_seconds"])
def test_usd_per_item_refuses_for_a_run_that_is_not_in_dollars(unit):
    """A name asserting a unit the value is not in is what makes an incommensurable comparison look like arithmetic."""
    with pytest.raises(EvidenceError, match="no dollar figure to return"):
        run(unit=unit, cost=(120.0, 380.0)).usd_per_item


@pytest.mark.parametrize("unit", ["usd", "tokens", "gpu_seconds"])
def test_cost_per_item_answers_for_every_unit(unit):
    """The unit-agnostic accessor is the one a caller should reach for, so it must work everywhere."""
    assert run(unit=unit, cost=(2.0, 4.0)).cost_per_item == pytest.approx(3.0)


def test_there_is_no_conversion_function():
    """tokens to usd needs a price card, tokens to GPU-seconds needs a throughput measured under load, and a
    coefficient assumed instead of measured once moved a published figure by a factor of six and changed which
    candidate was selected."""
    for name in dir(cf):
        assert "convert" not in name.lower(), f"cf.{name} would invite exactly the assumed coefficient"


# --- two units are never subtracted --------------------------------------------------------------------------------

def test_comparing_two_units_is_refused():
    """Subtracting them produces a number in no unit at all, and it looks exactly like a cost advantage."""
    a, b = run("box", unit="tokens", cost=(200.0, 400.0)), run("api", unit="usd")
    with pytest.raises(EvidenceError, match="no unit at all"):
        cf.compare(a, b, operating_point=NO_KNOB)


def test_comparing_one_unit_carries_it_onto_the_comparison():
    a, b = run("box", unit="tokens", cost=(200.0, 400.0)), run("api", unit="tokens", cost=(500.0, 500.0))
    c = cf.compare(a, b, operating_point=NO_KNOB)
    assert c.cost_unit == "tokens"
    assert c.cost_delta == pytest.approx(300.0 - 500.0)


# --- the report never puts a currency symbol on something that is not currency -------------------------------------

@pytest.mark.parametrize("unit,expect,forbid", [("usd", "$0.00500", "tokens"),
                                                ("tokens", "300.0 tokens", "$"),
                                                ("gpu_seconds", "0.300 GPU-s", "$")])
def test_a_run_prints_its_cost_in_its_own_unit(unit, expect, forbid):
    """A `$` in front of a token count is the strongest possible reason for a reader to assume two figures are in the
    same thing."""
    cost = {"usd": (0.004, 0.006), "tokens": (200.0, 400.0), "gpu_seconds": (0.2, 0.4)}[unit]
    text = str(run(unit=unit, cost=cost))
    assert expect in text
    assert forbid not in text


def test_a_comparison_prints_its_cost_in_its_own_unit_with_a_sign():
    a, b = run("box", unit="tokens", cost=(200.0, 400.0)), run("api", unit="tokens", cost=(500.0, 500.0))
    text = str(cf.compare(a, b, operating_point=NO_KNOB))
    assert "cost -200.0 tokens/item" in text
    assert "$" not in text
