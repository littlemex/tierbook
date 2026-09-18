"""Tests for a candidate whose output is schema-constrained and which returns a probability beside its answer.

Written against a real interface: a vendor shipping "unstructured state in, typed probabilistic decisions out", where
the model "never makes type errors" and "all answers are accompanied with calibrated probabilities". Two claims travel
together there and neither implies the other -- one is about form and is checkable, the other is about content and is a
measurement nobody here has taken. This project already measured what the gap looks like: 1,822 of 2,364 answers on one
option out of ten, every one of them perfectly well formed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import extraction as ex  # noqa: E402
from tierbook import quantity as qt  # noqa: E402
from tierbook.evidence import EvidenceError, elicitation_from_template  # noqa: E402
from tierbook.judge import WeightDigest  # noqa: E402
from tierbook.spend import SignalPrice, Spend  # noqa: E402

N, ON_A = 2364, 1822


# --- form: what a constrained decoder really guarantees ------------------------------------------------------------------

def test_every_rule_is_classified_for_whether_it_can_fail_to_parse():
    """A total map, so adding a rule without deciding this breaks a test rather than defaulting it to fallible."""
    assert set(ex.RULE_CAN_FAIL_TO_PARSE) == set(ex.EXTRACTION_RULES)


def test_a_constrained_decoder_cannot_fail_to_parse_and_nothing_else_can_claim_that():
    """The guarantee is real: a decoder held to a grammar emits a member of the enum or nothing."""
    assert ex.RULE_CAN_FAIL_TO_PARSE["schema_constrained"] is False
    assert all(v for k, v in ex.RULE_CAN_FAIL_TO_PARSE.items() if k != "schema_constrained")


def test_a_constrained_rule_carries_no_cue():
    """The constraint is on what may be emitted, not on where to look, so there is nothing to read after."""
    with pytest.raises(EvidenceError, match="no cue to read after"):
        ex.Extraction(rule="schema_constrained", options=10, cue="Answer:")
    assert ex.Extraction(rule="schema_constrained", options=10).cue == ""


def test_a_well_formed_run_is_still_refused_when_it_is_degenerate():
    """The whole point. Every answer valid, and 77.1% of them on one option out of ten -- which is the measured break,
    and skipping the check for a rule that cannot produce a parse failure would read 'no format errors' as 'no reader
    errors'."""
    answers = ["A"] * ON_A + [chr(66 + i % 9) for i in range(N - ON_A)]
    with pytest.raises(ex.Degenerate, match="landed on one option"):
        ex.refuse_degenerate(answers, ex.Extraction(rule="schema_constrained", options=10))


def test_a_constrained_run_that_spreads_is_admitted():
    ex.refuse_degenerate([chr(65 + i % 10) for i in range(N)],
                         ex.Extraction(rule="schema_constrained", options=10))


def test_the_unparsed_check_is_vacuous_for_it_and_that_is_a_fact_not_a_skip():
    """Its unparsed share is 0 by construction, so the check passes rather than being bypassed."""
    answers = [chr(65 + i % 10) for i in range(20)]
    assert ex.unparsed_share(answers) == 0.0


# --- content: what "calibrated probabilities" is until somebody bins it --------------------------------------------------

def test_a_vendor_claim_is_representable_and_cannot_be_read_as_a_probability():
    """Ranking by it needs no calibration; reading 0.85 as 85% does, and that is a measurement nobody here has taken."""
    c = qt.Confidence(evidence="vendor_asserted")
    with pytest.raises(qt.Inadmissible, match="reading a claim"):
        c.may_be_trusted(max_gap=0.05)


def test_the_refusal_names_the_use_that_needs_no_calibration():
    """A refusal that does not say what the number is still good for gets worked around by trusting it anyway."""
    with pytest.raises(qt.Inadmissible) as exc:
        qt.Confidence(evidence="unmeasured").may_be_trusted(max_gap=0.05)
    assert "Rank items by it" in str(exc.value)


def test_a_measurement_taken_here_can_be_trusted_within_its_own_gap():
    m = qt.Confidence(evidence="measured_here", reliability_gap=0.031, bins=10)
    assert m.may_be_trusted(max_gap=0.05) is True
    assert m.may_be_trusted(max_gap=0.02) is False


def test_claiming_a_measurement_without_its_numbers_is_the_weaker_claim_wearing_the_stronger_word():
    with pytest.raises(qt.Inadmissible, match="wearing the stronger word"):
        qt.Confidence(evidence="measured_here")


def test_an_asserted_calibration_may_not_carry_a_gap():
    """A gap nobody measured here is a number from somewhere this project cannot check."""
    with pytest.raises(qt.Inadmissible, match="cannot check"):
        qt.Confidence(evidence="vendor_asserted", reliability_gap=0.01, bins=10)


def test_one_bin_is_not_a_reliability_curve():
    """It is a single average, and says nothing about whether high confidence differs from low."""
    with pytest.raises(qt.Inadmissible, match="single average"):
        qt.Confidence(evidence="measured_here", reliability_gap=0.01, bins=1)


@pytest.mark.parametrize("gap", [-0.1, 1.5])
def test_a_gap_outside_the_unit_interval_is_refused(gap):
    with pytest.raises(qt.Inadmissible, match="not a gap"):
        qt.Confidence(evidence="measured_here", reliability_gap=gap, bins=10)


# --- and it travels on a quantity, at zero extra passes ------------------------------------------------------------------

TERSE = elicitation_from_template("terse", "Answer with one letter.")
DIG = WeightDigest(hex="a" * 64)


def typed_quantity(**kw):
    free = SignalPrice(passes=1, per_pass=Spend(prefill=0.109, generation=0.0, unit="gpu_seconds"))
    base = dict(name="returned_confidence", kind="scalar", availability="after_prefill",
                register="passive_observation", subject="own_competence", price=free, measured_on=DIG,
                elicitation=TERSE, validity=qt.Validity(calibrated_for=TERSE, fresh_for_days=30.0),
                readout_version="jev-1", confidence=qt.Confidence(evidence="vendor_asserted"))
    base.update(kw)
    return qt.Quantity(**base)


def test_a_returned_probability_costs_no_extra_pass_which_is_what_makes_it_worth_having():
    """It arrives with the answer, so a gate conditioning on it pays nothing beyond the call it was going to make."""
    q = typed_quantity()
    assert q.is_free is True
    assert q.usable_before_generating() is True


def test_it_is_admissible_to_a_gate_because_it_is_about_this_candidate():
    q = typed_quantity()
    assert qt.admissible_for_a_gate([q], elicitation=TERSE, served=DIG) == [q]


def test_a_bare_flag_is_refused_where_a_confidence_belongs():
    """It would record that a probability was returned and not whether anybody checked what it means."""
    with pytest.raises(qt.Inadmissible, match="whether anybody checked"):
        typed_quantity(confidence=True)


def test_a_quantity_that_is_not_a_probability_carries_none():
    """An entropy or a queue length has no calibration claim to check."""
    assert typed_quantity(confidence=None).confidence is None
