"""Tests for how an answer was extracted, and the refusal when the result cannot be a distribution.

Every number here is the one that occurred: the convention "the option letter is the next token" was applied to replies
that explained themselves first, which put 1,822 of 2,364 items on `A` and gave accuracy 0.1599 against a 0.10 random
floor. The design driver is the sentence after that in the ledger -- the same failure at half the rate would have
produced a plausible middle value and been believed -- so half the break is what the bounds are answerable to.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import extraction as ex  # noqa: E402
from tierbook.evidence import EvidenceError  # noqa: E402

N = 2364
ON_A = 1822


def spread(n, options=10, first=0):
    """`n` answers spread as evenly as the option count allows, so the modal share is near uniform."""
    return [chr(65 + first + i % options) for i in range(n)]


def broken(on_a=ON_A):
    return ["A"] * on_a + spread(N - on_a, options=9, first=1)


def rule(kind="next_token", options=10, cue=""):
    return ex.Extraction(rule=kind, options=options, cue=cue)


# --- the rule travels with the answer -------------------------------------------------------------------------------

def test_an_open_ended_rule_is_refused():
    """Two outcomes produced by different rules are not comparable, and an open-ended value cannot be aggregated."""
    with pytest.raises(EvidenceError, match="not one of"):
        rule("whatever_worked")


def test_the_cue_rule_must_carry_its_cue():
    """The cue is the whole content of that rule: appending it in one condition and not the other is what made two
    runs' endpoints different kinds of position."""
    with pytest.raises(EvidenceError, match="nothing says where the answer"):
        rule("answer_cue")
    assert rule("answer_cue", cue="\nAnswer:").cue == "\nAnswer:"


def test_a_rule_that_reads_no_cue_may_not_carry_one():
    """It would describe something that did not happen."""
    with pytest.raises(EvidenceError, match="did not happen"):
        rule("next_token", cue="\nAnswer:")


def test_a_single_choice_is_not_something_to_extract_from():
    with pytest.raises(EvidenceError, match="extracts nothing"):
        rule(options=1)


def test_unrecorded_is_representable_because_it_is_the_true_statement_about_old_outcomes():
    assert rule("unrecorded", options=0).rule == "unrecorded"


# --- the bound is answerable to the measured break -------------------------------------------------------------------

def test_the_break_and_half_of_it_are_the_numbers_the_bounds_answer_to():
    assert ex.MEASURED_BREAK_MODAL_SHARE == pytest.approx(ON_A / N, abs=1e-9)
    assert ex.MUST_CATCH_TOLERANCE == pytest.approx(ex.MEASURED_BREAK_TOLERANCE / 2)


def test_a_tolerance_that_would_admit_the_quiet_version_of_the_failure_is_refused():
    assert ex.bound_from_options(10, tolerance=3.0) == pytest.approx(0.30)
    with pytest.raises(EvidenceError, match="quiet version of a failure"):
        ex.bound_from_options(10, tolerance=4.0)


def test_the_guard_is_in_multiples_of_uniform_not_in_absolute_share():
    """DEFECT the first version had: it compared a caller's bound against a share measured on a TEN-option task, so on
    two options it refused every tolerance -- uniform is already 0.5 there and 0.385 sits below it. A binary task could
    never have obtained a bound, and the check would have been switched off where it was most usable."""
    assert ex.bound_from_options(2, tolerance=1.5) == pytest.approx(0.75)
    assert ex.bound_from_options(4, tolerance=3.0) == pytest.approx(0.75)


def test_a_bound_that_would_refuse_a_working_reader_is_refused():
    """At or below uniform the check fires on every healthy run and gets switched off."""
    with pytest.raises(EvidenceError, match="switched off"):
        ex.bound_from_options(10, tolerance=1.0)


def test_a_derived_bound_that_admits_everything_is_refused_rather_than_clamped():
    """DEFECT this closes: at the default tolerance a two-option task derives 1.5. Clamped to 1.0 the check would be
    present, called, green, and incapable of refusing anything -- coverage that is not coverage."""
    with pytest.raises(EvidenceError, match="admits every answer set"):
        ex.bound_from_options(2)
    with pytest.raises(EvidenceError, match="admits every answer set"):
        ex.bound_from_options(3, tolerance=3.0)


def test_one_option_is_not_a_choice():
    with pytest.raises(EvidenceError, match="not a choice"):
        ex.bound_from_options(1)


# --- what the shares measure ----------------------------------------------------------------------------------------

def test_the_modal_share_reproduces_the_measured_break():
    assert ex.modal_share(broken()) == pytest.approx(ON_A / N, abs=1e-9)


def test_unparsed_replies_count_in_the_denominator_and_not_as_an_option():
    """A reader that fails on half the corpus and clusters the rest is two failures, and folding the unparsed into the
    mode would report one."""
    answers = ["A", "A", None, None]
    assert ex.modal_share(answers) == pytest.approx(0.5)
    assert ex.unparsed_share(answers) == pytest.approx(0.5)


def test_an_all_unparsed_set_has_no_mode_rather_than_a_share_of_one():
    assert ex.modal_share([None, None]) == 0.0
    assert ex.unparsed_share([None, None]) == 1.0


def test_empty_shares_are_zero_rather_than_a_division_by_zero():
    assert ex.modal_share([]) == 0.0 and ex.unparsed_share([]) == 0.0


# --- the refusal ------------------------------------------------------------------------------------------------------

def test_the_measured_break_is_refused():
    with pytest.raises(ex.Degenerate, match="landed on one option"):
        ex.refuse_degenerate(broken(), rule())


def test_the_same_failure_at_half_the_rate_is_also_refused():
    """This is the case the whole module exists for: it would have produced a plausible middle value and been
    believed."""
    with pytest.raises(ex.Degenerate):
        ex.refuse_degenerate(broken(on_a=ON_A // 2), rule())


def test_a_working_read_is_admitted():
    ex.refuse_degenerate(spread(N), rule())


def test_a_rule_that_could_not_read_most_replies_is_its_own_failure():
    """That is the rule failing, not the model answering badly, and an accuracy over the remainder is an accuracy over
    the items the rule happened to manage."""
    with pytest.raises(ex.Degenerate, match="could not be read"):
        ex.refuse_degenerate([None] * 60 + spread(40), rule())


def test_an_unrecorded_rule_cannot_be_checked_and_says_so():
    """The same letters are a working read under one convention and a broken one under another."""
    with pytest.raises(EvidenceError, match="nothing to check these answers against"):
        ex.refuse_degenerate(spread(N), rule("unrecorded", options=0))


def test_no_answers_at_all_is_not_a_passing_extraction():
    with pytest.raises(EvidenceError, match="not a passing extraction"):
        ex.refuse_degenerate([], rule())


def test_a_caller_may_state_the_bound_and_it_is_then_used():
    """The escape for a genuinely skewed answer key, and it is explicit at the call site."""
    ex.refuse_degenerate(broken(), rule(), modal_bound=0.99)


# --- the production path: the table cannot be built from a broken read -----------------------------------------------

def _evidence(subject, items):
    from tierbook.evidence import INCORRECT, SOLVED, Evidence
    return Evidence(path=subject,
                    header={"suite_manifest_digest": "sha256:" + "a" * 64, "subject": subject,
                            "family": "s", "trials_per_item": 1},
                    verdicts={i: (SOLVED if n % 10 == 0 else INCORRECT, None) for n, i in enumerate(items)})


def _items():
    return [f"i{n}" for n in range(N)]


def test_a_table_cannot_be_built_from_a_broken_read():
    """Refused at construction rather than returned for somebody to notice, because the accuracy it would have produced
    -- 0.1599 against a 0.10 floor -- reads as a weak model and sends nobody to look at the reader."""
    from tierbook.outcomes import OutcomeTable
    items = _items()
    answers = {"cheap": dict(zip(items, broken()))}
    with pytest.raises(ex.Degenerate):
        OutcomeTable.from_evidence([_evidence("cheap", items)], answers=answers,
                                   extraction={"cheap": rule()})


def test_a_table_built_from_a_working_read_carries_the_rule_on_every_cell():
    from tierbook.outcomes import OutcomeTable
    items = _items()
    t = OutcomeTable.from_evidence([_evidence("cheap", items)],
                                   answers={"cheap": dict(zip(items, spread(N)))},
                                   extraction={"cheap": rule()})
    assert t.cells["i0"]["cheap"].extraction == rule()
    assert t.cells["i0"]["cheap"].answer == "A"


def test_a_table_with_no_extraction_declared_is_built_without_the_check():
    """Every table built before this parameter existed is in that state, and refusing it would make the mechanism
    unusable on the data that exists."""
    from tierbook.outcomes import OutcomeTable
    items = _items()
    t = OutcomeTable.from_evidence([_evidence("cheap", items)], answers={"cheap": dict(zip(items, broken()))})
    assert t.cells["i0"]["cheap"].extraction is None


def test_a_caller_may_state_the_bound_through_the_loader():
    from tierbook.outcomes import OutcomeTable
    items = _items()
    OutcomeTable.from_evidence([_evidence("cheap", items)], answers={"cheap": dict(zip(items, broken()))},
                               extraction={"cheap": rule()}, modal_bounds={"cheap": 0.99})
