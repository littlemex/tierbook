"""Tests for the operating point a comparison holds at.

F18's measurement is the reason every refusal here exists: three signals that separate cleanly at one floor all
converge at the last tenth, so a comparison reported without its setting reads as a general ranking and is not one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import counterfactual as cf  # noqa: E402
from tierbook.evidence import EvidenceError  # noqa: E402


def fixed(value=0.30, chosen_on="calibration", knob="coverage"):
    return cf.OperatingPoint(kind="fixed", value=value, chosen_on=chosen_on, knob=knob)


# --- the point itself ---------------------------------------------------------------------------------------------

def test_an_open_ended_kind_is_refused():
    with pytest.raises(EvidenceError, match="not one of"):
        cf.OperatingPoint(kind="roughly-there")


def test_a_fixed_point_with_no_value_names_nothing():
    """'fixed' without the setting is exactly the unnamed comparison the field exists to stop."""
    with pytest.raises(EvidenceError, match="names nothing"):
        cf.OperatingPoint(kind="fixed", chosen_on="calibration", knob="coverage")


def test_a_fixed_point_must_say_where_the_setting_came_from():
    with pytest.raises(EvidenceError, match="measured rather than assumed"):
        cf.OperatingPoint(kind="fixed", value=0.3, knob="coverage")
    with pytest.raises(EvidenceError, match="measured rather than assumed"):
        cf.OperatingPoint(kind="fixed", value=0.3, chosen_on="somewhere", knob="coverage")


def test_a_fixed_point_must_name_the_knob():
    """A coverage of 0.30 and a price of accuracy of 0.30 are different facts and would read as the same one."""
    with pytest.raises(EvidenceError, match="without saying what it sets"):
        cf.OperatingPoint(kind="fixed", value=0.3, chosen_on="calibration")


@pytest.mark.parametrize("kind", ["integrated", "not_applicable"])
@pytest.mark.parametrize("extra", [{"value": 0.3}, {"chosen_on": "calibration"}])
def test_only_a_fixed_point_carries_a_setting(kind, extra):
    """A value on an integrated comparison would be read as the setting it holds at, when it spans them all."""
    with pytest.raises(EvidenceError, match="Only a fixed point has a setting"):
        cf.OperatingPoint(kind=kind, **extra)


def test_the_three_kinds_print_as_what_they_are():
    assert str(fixed()) == "at coverage=0.3 (chosen on calibration)"
    assert str(cf.OperatingPoint(kind="integrated")) == "over the whole curve"
    assert str(cf.OperatingPoint(kind="not_applicable")) == "no tunable setting"


# --- what it licenses ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("chosen_on,supports", [("calibration", True), ("declared_in_advance", True),
                                                ("scored_items", False)])
def test_only_a_setting_chosen_elsewhere_supports_a_verdict(chosen_on, supports):
    assert fixed(chosen_on=chosen_on).supports_a_verdict is supports


def test_an_integrated_comparison_supports_a_verdict():
    """Reporting over the whole curve is the other discharge F18 names, not a lesser one."""
    assert cf.OperatingPoint(kind="integrated").supports_a_verdict is True


def cmp_at(point, p_value=0.01):
    return cf.Comparison(a="gate", b="always-escalate", items=571, a_only=34, b_only=28, p_value=p_value,
                         cost_delta=-0.0012, accuracy_delta=0.010, operating_point=point)


def test_a_comparison_cannot_be_built_without_an_operating_point():
    """Defaulting it would put the unnamed comparison back, wearing a field that claims it was named."""
    with pytest.raises(TypeError):
        cf.Comparison(a="gate", b="always", items=1, a_only=1, b_only=0, p_value=0.5,
                      cost_delta=0.0, accuracy_delta=0.0)


def test_a_verdict_is_refused_when_the_setting_was_chosen_on_the_scored_items():
    """Choosing it there gave seven candidate settings at every price of accuracy, and taking the best inflated the
    reported interval, so the p-value is not the p-value of the procedure that produced the number."""
    c = cmp_at(fixed(chosen_on="scored_items"))
    with pytest.raises(cf.Unsupported, match="not the p-value of this result"):
        c.is_significant()


def test_the_escape_is_explicit_at_the_call_site():
    """The caller who wants the number anyway says so where a reader of that line can see the claim being made."""
    c = cmp_at(fixed(chosen_on="scored_items"))
    assert c.is_significant(allow_point_chosen_on_scored_items=True) is True


def test_a_properly_chosen_setting_gives_a_verdict_without_an_escape():
    assert cmp_at(fixed()).is_significant() is True
    assert cmp_at(fixed(), p_value=0.40).is_significant() is False


def test_the_printed_form_names_the_setting_and_withholds_the_verdict():
    """A comparison that cannot support a verdict prints what it is, in the place a reader looks for the verdict."""
    assert "at coverage=0.3 (chosen on calibration)" in str(cmp_at(fixed()))
    text = str(cmp_at(fixed(chosen_on="scored_items")))
    assert "no verdict: the setting was chosen on the scored items" in text
    assert "significant" not in text.replace("no verdict", "")
