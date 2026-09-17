"""Tests for a criterion registered with its null and its alternatives.

Every number is the one that occurred. A held-out internal direction separated two conditions at 0.8285; its
category-preserving permutation null sat at 0.7584 median and 0.7928 at the 95th percentile; a freely available readout
scored 0.8895 on the same question; and 75.4% of the direction lay inside the answer-letter span it was supposed to be
distinguished from. The first test passes and the conclusion does not follow.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import criterion as cr  # noqa: E402
from tierbook.evidence import FIXED_ON  # noqa: E402

REAL, NULL_MED, NULL_95, FREE, INSIDE_SPAN = 0.8285, 0.7584, 0.7928, 0.8895, 0.754


def null(**kw):
    base = dict(median=NULL_MED, at_quantile=NULL_95, quantile=0.95, draws=1000,
                preserves="category escape rate")
    base.update(kw)
    return cr.Null(**base)


def crit(**kw):
    base = dict(name="beats its null", observed=REAL, null=null(), fixed_on="declared_in_advance")
    base.update(kw)
    return cr.Criterion(**base)


def span_crit():
    return cr.Criterion(name="lies outside the letter span", observed=INSIDE_SPAN, null=null(),
                        fixed_on="declared_in_advance", direction="below", bound=0.50)


# --- the null is a distribution -----------------------------------------------------------------------------------------

def test_the_gain_over_the_median_is_not_the_gain_over_the_tail():
    """0.036 and 0.0357 are different numbers about different questions, which is why both ends are carried."""
    c = crit()
    assert c.margin == pytest.approx(REAL - NULL_95, abs=1e-9)
    assert REAL - NULL_MED == pytest.approx(0.0701, abs=1e-4)


def test_a_quantile_outside_the_open_unit_interval_is_refused():
    for bad in (0.0, 1.0):
        with pytest.raises(cr.Unregistered, match="strictly between"):
            null(quantile=bad)


def test_a_tail_below_the_median_is_almost_certainly_the_two_numbers_swapped():
    with pytest.raises(cr.Unregistered, match="two numbers swapped"):
        null(median=NULL_95, at_quantile=NULL_MED)


def test_a_null_with_too_few_draws_to_resolve_its_quantile_is_refused():
    """With that many draws the tail the verdict is compared against is a single draw or none, so nothing could have
    failed it."""
    with pytest.raises(cr.Unregistered, match="cannot resolve"):
        null(draws=10, quantile=0.95)
    assert null(draws=20, quantile=0.95).draws == 20


def test_a_null_over_no_draws_is_not_a_null():
    with pytest.raises(cr.Unregistered, match="never sampled"):
        null(draws=0)


# --- a criterion says which direction it tests --------------------------------------------------------------------------

def test_the_direction_is_required_because_beats_is_ambiguous():
    """A discriminant should exceed its null and a fraction inside a span should fall under a bound; both occur in this
    measurement and were reported as one kind of pass."""
    with pytest.raises(cr.Unregistered, match="whichever inequality happens to hold"):
        crit(direction="sort of upward")


def test_a_below_test_needs_its_own_bound():
    with pytest.raises(cr.Unregistered, match="not a bound in that direction"):
        crit(direction="below")


def test_an_above_test_may_not_also_carry_a_bound():
    """Two thresholds would describe one test and nothing would say which was used."""
    with pytest.raises(cr.Unregistered, match="nothing says which was used"):
        crit(direction="above", bound=0.5)


def test_the_two_measured_criteria_come_out_as_the_ledger_reports_them():
    """(i) passes, (ii) fails."""
    assert crit().holds() is True
    assert span_crit().holds() is False
    assert span_crit().margin == pytest.approx(0.50 - INSIDE_SPAN, abs=1e-9)


def test_a_null_fixed_on_the_scored_items_cannot_support_a_verdict():
    """Its threshold could have been chosen to clear the observed value."""
    with pytest.raises(cr.Unregistered, match="could have been chosen to clear"):
        crit(fixed_on="scored_items").holds()


@pytest.mark.parametrize("fixed_on", ["declared_in_advance", "calibration"])
def test_the_other_two_provenances_answer(fixed_on):
    assert crit(fixed_on=fixed_on).holds() is True


def test_the_provenance_vocabulary_is_the_shared_one():
    """Written first for a comparison's operating point; a criterion's null needs the identical distinction, so two
    copies would be one edit from disagreeing about what declared-in-advance means."""
    from tierbook import counterfactual as cf
    assert cf.CHOSEN_ON is FIXED_ON


# --- a conclusion needs every criterion, and a null is not an alternative ------------------------------------------------

def reg(**kw):
    base = dict(conclusion="the fallback is a verbalizable strategy",
                criteria=(crit(), span_crit()),
                alternatives=(cr.Alternative(name="free output entropy", observed=FREE),))
    base.update(kw)
    return cr.Registration(**base)


def test_the_measured_conclusion_is_not_supported_and_the_sentence_says_both_reasons():
    r = reg()
    assert r.supported() is False
    assert r.failed() == ("lies outside the letter span",)
    assert r.lost_to() == ("free output entropy",)
    text = r.why_not()
    assert "did not hold" in text and "freely available alternative beat it" in text


def test_a_conclusion_that_clears_everything_is_supported():
    r = reg(criteria=(crit(),), alternatives=(cr.Alternative(name="weaker readout", observed=0.70),))
    assert r.supported() is True
    assert "supported by all 1 registered criteria" in r.why_not()


def test_losing_to_a_free_alternative_alone_is_enough_to_withhold_support():
    """Beating a permutation of your own labels says nothing about whether something cheaper already does the job, and
    here the two answers disagreed by 0.0610."""
    r = reg(criteria=(crit(),))
    assert r.failed() == ()
    assert r.lost_to() == ("free output entropy",)
    assert r.supported() is False


def test_a_conclusion_with_no_alternative_and_no_reason_is_refused():
    """An empty list is ambiguous between "nothing cheaper exists" and "nobody looked", and looking is what settled
    this."""
    with pytest.raises(cr.Unregistered, match="Name an alternative, or say why none exists"):
        reg(alternatives=())


def test_the_reason_and_a_listed_alternative_are_refused_together():
    with pytest.raises(cr.Unregistered, match="describes an absence that is not there"):
        reg(no_alternative_because="none exists")


def test_the_reason_alone_is_accepted():
    r = reg(alternatives=(), no_alternative_because="no free readout answers this question")
    assert r.supported() is False        # criterion (ii) still fails


def test_a_registration_with_no_criteria_records_the_opposite_of_the_fact():
    with pytest.raises(cr.Unregistered, match="opposite of the fact"):
        reg(criteria=())


def test_two_criteria_sharing_a_name_leave_a_report_unable_to_say_which_held():
    with pytest.raises(cr.Unregistered, match="cannot say which one held"):
        reg(criteria=(crit(), crit()))


def test_there_is_no_method_reporting_one_criterion_as_support():
    """Reporting the test that passed is not a partial result, it is a different claim."""
    assert not any(n in dir(cr.Registration) for n in ("any_supported", "best_criterion", "first_pass"))


# --- the door -----------------------------------------------------------------------------------------------------------

def _run(capsys, extra):
    from tierbook import cli
    code = cli.main(["registered-criteria", "--conclusion", "the fallback is a verbalizable strategy",
                     "--null-median", str(NULL_MED), "--null-at-quantile", str(NULL_95),
                     "--null-draws", "1000", "--null-preserves", "category escape rate", *extra])
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def test_the_door_reports_the_measured_case_as_unsupported(capsys):
    code, text = _run(capsys, ["--criterion", f"beats-its-null:{REAL}:above:-:declared_in_advance",
                               "--criterion", f"outside-the-span:{INSIDE_SPAN}:below:0.50:declared_in_advance",
                               "--alternative", f"free-output-entropy:{FREE}"])
    assert code == 2
    assert "holds: beats-its-null" in text
    assert "FAILS: outside-the-span" in text
    assert "is not supported" in text


def test_the_door_exits_two_rather_than_one_when_the_numbers_are_fine(capsys):
    """Every number is well formed and the conclusion does not follow, which is a finding about the claim rather than an
    error in the input."""
    code, _ = _run(capsys, ["--criterion", f"beats-its-null:{REAL}:above:-:declared_in_advance",
                            "--alternative", f"free-output-entropy:{FREE}"])
    assert code == 2


def test_the_door_refuses_a_conclusion_that_never_asked_the_cheaper_question(capsys):
    code, text = _run(capsys, ["--criterion", f"beats-its-null:{REAL}:above:-:declared_in_advance"])
    assert code == 1
    assert "say why none exists" in text


def test_the_door_accepts_the_declared_absence(capsys):
    code, text = _run(capsys, ["--criterion", f"beats-its-null:{REAL}:above:-:declared_in_advance",
                               "--no-alternative-because", "no free readout answers this question"])
    assert code == 0
    assert "is supported by all 1 registered criteria" in text


def test_the_door_refuses_a_malformed_criterion_with_the_shape_it_wanted(capsys):
    code, text = _run(capsys, ["--criterion", "beats-its-null:0.83"])
    assert code == 1
    assert "NAME:OBSERVED:DIRECTION:BOUND:FIXED_ON" in text
