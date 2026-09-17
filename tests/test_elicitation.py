"""Tests for the condition a measured number was measured under.

The ledger names this defect five times -- F1, F15, F16, F22 and F31 -- and F15 asks for it "enforced rather than
documented: a number carrying the condition it was measured under, so that a comparison between two conditions is
refused instead of performed". The measured fact behind it: a box's accuracy under a terse instruction and under one
asking for reasoning are different numbers, and every economic threshold in this project is conditioned on "the box
accuracy" while naming no condition.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import counterfactual as cf  # noqa: E402
from tierbook.evidence import Elicitation, Substituted, elicitation_from_template  # noqa: E402

NO_KNOB = cf.OperatingPoint(kind="not_applicable")
TERSE = elicitation_from_template("terse", "Answer with one letter.")
EXPLAIN = elicitation_from_template("explaining", "Think step by step, then answer with one letter.")


def run(label="a", elicitation=None, solved=(True, False, True, False, True, False, True, True)):
    n = len(solved)
    return cf.Run(label=label, items=tuple(f"i{i}" for i in range(n)), solved=solved,
                  usd=(0.004,) * n, calls=(("cheap",),) * n, elicitation=elicitation)


# --- the key is the template's text, not what the template was called ----------------------------------------------

def test_two_templates_with_the_same_label_are_two_templates():
    """The study labelled its conditions "terse" and "explaining" and reused both labels across templates that were
    not the same text -- the same failure the model-identity digest records."""
    a = elicitation_from_template("terse", "Answer with one letter.")
    b = elicitation_from_template("terse", "Answer with one letter. ")
    assert a.name == b.name
    assert a != b and a.template_digest != b.template_digest


def test_the_same_template_gives_the_same_key_whatever_it_is_called():
    assert (elicitation_from_template("terse", "X").template_digest
            == elicitation_from_template("minimal", "X").template_digest)


def test_a_label_alone_cannot_be_the_key():
    with pytest.raises(Substituted, match="A label is not the key"):
        Elicitation(name="terse", template_digest="terse")


def test_an_unnamed_elicitation_is_refused_because_a_reader_needs_the_name():
    """A digest where the reader needed to know whether reasoning was asked for is not a report."""
    with pytest.raises(Substituted, match="cannot be reported to a reader"):
        Elicitation(name="", template_digest="a" * 64)


def test_an_empty_template_is_not_a_condition():
    for empty in ("", "   ", "\n"):
        with pytest.raises(Substituted, match="no condition to record"):
            elicitation_from_template("terse", empty)


def test_it_prints_the_name_and_enough_of_the_key_to_tell_two_apart():
    assert str(TERSE).startswith("terse/")
    assert str(TERSE) != str(elicitation_from_template("terse", "Answer with one letter. "))


# --- a run carries it, and a bare string is refused -----------------------------------------------------------------

def test_a_run_carries_its_elicitation():
    assert run(elicitation=TERSE).elicitation is TERSE


def test_a_bare_string_on_a_run_is_refused():
    """It would be the label-as-key this type exists to refuse, smuggled in past the type."""
    with pytest.raises(Substituted, match="not an Elicitation"):
        run(elicitation="terse")


def test_an_unrecorded_elicitation_is_left_representable():
    """Every run written before this field existed is in that state, and refusing it would make the mechanism unusable
    on the data that exists. What is not representable is comparing two DIFFERENT recorded conditions."""
    assert run().elicitation is None


# --- the refusal F15 asked for ---------------------------------------------------------------------------------------

def test_comparing_two_conditions_is_refused_instead_of_performed():
    """The difference between the two numbers is not a difference between the arms -- it is partly the difference
    between the questions."""
    with pytest.raises(Substituted, match="refused instead of performed"):
        cf.compare(run("box-terse", TERSE), run("box-explain", EXPLAIN), operating_point=NO_KNOB)


def test_the_refusal_names_both_conditions_so_the_reader_can_see_which_two():
    with pytest.raises(Substituted) as exc:
        cf.compare(run("a", TERSE), run("b", EXPLAIN), operating_point=NO_KNOB)
    assert "terse/" in str(exc.value) and "explaining/" in str(exc.value)


def test_the_same_condition_compares_and_the_condition_travels_onto_the_result():
    c = cf.compare(run("a", TERSE), run("b", TERSE), operating_point=NO_KNOB)
    assert c.elicitation == TERSE


def test_two_unrecorded_runs_still_compare():
    c = cf.compare(run("a"), run("b"), operating_point=NO_KNOB)
    assert c.elicitation is None


def test_one_recorded_side_carries_its_condition_onto_the_result():
    """Not a refusal: nothing is known to differ. But the condition that IS known is kept, because losing it would
    make the result indistinguishable from one where neither side recorded anything."""
    assert cf.compare(run("a", TERSE), run("b"), operating_point=NO_KNOB).elicitation == TERSE
    assert cf.compare(run("a"), run("b", TERSE), operating_point=NO_KNOB).elicitation == TERSE


# --- an unlabelled comparison is visible rather than silent ----------------------------------------------------------

def test_the_printed_form_says_when_the_condition_is_unrecorded():
    """Printing nothing would leave a reader unable to tell "both arms were asked the same way" from "nobody wrote
    down how either was asked"."""
    assert "elicitation unrecorded" in str(cf.compare(run("a"), run("b"), operating_point=NO_KNOB))


def test_the_printed_form_names_the_condition_when_there_is_one():
    text = str(cf.compare(run("a", TERSE), run("b", TERSE), operating_point=NO_KNOB))
    assert "elicited by terse/" in text
    assert "unrecorded" not in text
