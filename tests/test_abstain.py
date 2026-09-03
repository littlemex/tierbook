"""The abstention rule and the two free repairs that come before it.

Each test here encodes a measured fact rather than an intention. The unanimity detector's exactness,
the collapse when it is relaxed by one candidate, the direction the unpriced case must round, and the
lost-success cap are all numbers that were paid for.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.abstain import (  # noqa: E402
    broken_key_candidates,
    duplicate_groups,
    sequential_stop,
)
from tierbook.evidence import INCORRECT, SOLVED  # noqa: E402
from tierbook.outcomes import Cell, OutcomeTable  # noqa: E402


def _table(rows: dict[str, dict[str, tuple[str, str | None, float | None]]]) -> OutcomeTable:
    t = OutcomeTable(suite="s", manifest_digest="d")
    for item, tiers in rows.items():
        t.cells[item] = {tier: Cell(state=st, usd=usd, answer=ans) for tier, (st, ans, usd) in tiers.items()}
    return t


# --- broken keys ----------------------------------------------------------------------------------

def test_unanimous_and_all_wrong_is_flagged():
    t = _table({"bad": {"a": (INCORRECT, "B", 1.0), "b": (INCORRECT, "B", 1.0), "c": (INCORRECT, "B", 1.0)}})
    assert broken_key_candidates(t, ["a", "b", "c"]) == ["bad"]


def test_one_dissenter_is_enough_to_clear_it():
    """Relaxing unanimity to 'all but one' dropped the measured hit rate from 19/19 to 3/9.

    One dissenter no longer distinguishes 'the key is wrong' from 'the question is hard', so the rule
    requires all of them.
    """
    t = _table({"hard": {"a": (INCORRECT, "B", 1.0), "b": (INCORRECT, "B", 1.0), "c": (INCORRECT, "C", 1.0)}})
    assert broken_key_candidates(t, ["a", "b", "c"]) == []


def test_unanimous_and_right_is_not_flagged():
    """452 of 471 unanimous items on the measured corpus were graded correct. Only the rejected ones
    are suspicious, and the detector must not report the agreeing majority as a data-quality problem.
    """
    t = _table({"easy": {"a": (SOLVED, "B", 1.0), "b": (SOLVED, "B", 1.0)}})
    assert broken_key_candidates(t, ["a", "b"]) == []


def test_a_missing_answer_clears_it_rather_than_completing_the_unanimity():
    """An abstention is not agreement, here for the same reason it is not agreement in a quorum."""
    t = _table({"i": {"a": (INCORRECT, "B", 1.0), "b": (INCORRECT, None, 1.0)}})
    assert broken_key_candidates(t, ["a", "b"]) == []


# --- duplicates -----------------------------------------------------------------------------------

def test_duplicates_are_found_across_case_punctuation_and_whitespace():
    groups = duplicate_groups({
        "a": "Which  is LARGEST?",
        "b": "which is largest",
        "c": "Something else entirely",
    })
    assert groups == [["a", "b"]]


def test_a_triple_is_one_group_not_three_pairs():
    """One eminent-domain question appeared three times on the measured corpus, unsolved in every
    copy, so one bad answer key contributed three items to the 'nobody solves it' tail.
    """
    groups = duplicate_groups({"a": "same q", "b": "same q", "c": "same q", "d": "other"})
    assert groups == [["a", "b", "c"]]


def test_normalisation_does_not_merge_different_questions():
    """Stemming or stopword removal here would merge items about one topic and shrink the corpus
    silently, so the normaliser folds only case, punctuation and whitespace.
    """
    groups = duplicate_groups({
        "a": "Is the resistance halved?",
        "b": "Is the resistance doubled?",
    })
    assert groups == []


# --- the sequential rule --------------------------------------------------------------------------

def _always(p: float):
    return lambda item, tier, failures: p


def test_it_stops_when_the_bound_no_longer_pays_for_the_next_call():
    t = _table({"i": {"cheap": (INCORRECT, "C", 1.0), "dear": (SOLVED, "B", 100.0)}})
    # A 1% chance of a $10 success does not justify a $100 call.
    r = sequential_stop(t, ["cheap", "dear"], p_next=_always(0.01), value_of_success=10.0)
    assert r.stopped == ["i"]
    assert r.calls_saved == 2, "it stopped before the first call, so both were saved"
    assert r.usd_saved == 101.0, "the cascade would have called both, since the dear tier solves it"


def test_it_keeps_spending_while_the_bound_still_pays():
    t = _table({"i": {"cheap": (INCORRECT, "C", 1.0), "dear": (SOLVED, "B", 100.0)}})
    r = sequential_stop(t, ["cheap", "dear"], p_next=_always(0.99), value_of_success=1000.0)
    assert r.completed == ["i"] and r.stopped == []
    assert r.usd_saved == 0.0


def test_the_bound_and_not_the_point_estimate_is_what_stops():
    """An item the model is unsure about must keep spending.

    `p_next` is an upper bound by contract, so a wide interval yields a high bound and the rule
    continues. This test is the contract, expressed as the only behaviour that distinguishes the two.
    """
    t = _table({"i": {"dear": (SOLVED, "B", 50.0)}})
    confident = sequential_stop(t, ["dear"], p_next=_always(0.02), value_of_success=100.0)
    unsure = sequential_stop(t, ["dear"], p_next=_always(0.80), value_of_success=100.0)
    assert confident.stopped == ["i"], "confidently hopeless: stop"
    assert unsure.completed == ["i"], "uncertain: keep paying"


def test_stopping_reports_the_successes_it_gave_up():
    """A rule that cannot say what it abandoned cannot be held to a cap."""
    t = _table({
        "rescuable": {"cheap": (INCORRECT, "C", 1.0), "dear": (SOLVED, "B", 100.0)},
        "hopeless": {"cheap": (INCORRECT, "C", 1.0), "dear": (INCORRECT, "D", 100.0)},
    })
    r = sequential_stop(t, ["cheap", "dear"], p_next=_always(0.0), value_of_success=10.0)
    assert sorted(r.stopped) == ["hopeless", "rescuable"]
    assert r.lost == ["rescuable"], "the dear tier would have solved this one"
    assert r.lost_rate == 0.5


def test_a_rule_outside_its_cap_may_not_gate_traffic():
    t = _table({
        "rescuable": {"dear": (SOLVED, "B", 100.0)},
        "hopeless": {"dear": (INCORRECT, "D", 100.0)},
    })
    r = sequential_stop(t, ["dear"], p_next=_always(0.0), value_of_success=1.0)
    assert r.lost_rate == 0.5
    assert not r.within_cap(0.05), "a rule losing half the solvable items stays in shadow mode"
    assert r.within_cap(0.5)


def test_an_unpriced_tier_is_never_the_reason_to_stop():
    """The one place an unpriced cell rounds to zero, and it rounds in the conservative direction.

    Everywhere else in this project an unpriced tier makes a number `None` rather than free, because
    there the error would flatter a policy. Here a call that looks free is simply never skipped, so
    the rule cannot abandon an item on the strength of a cost it does not know.
    """
    t = _table({"i": {"unpriced": (SOLVED, "B", None)}})
    r = sequential_stop(t, ["unpriced"], p_next=_always(0.0), value_of_success=1.0)
    assert r.completed == ["i"], "a free-looking call is always made"
    assert r.stopped == []


def test_the_failures_so_far_are_passed_to_the_predictor():
    """The evidence the rule updates on is the failures that already happened, which is why it needs
    no new signal: each failed tier is an observation that the item is harder than that tier.
    """
    seen = []

    def spy(item, tier, failures):
        seen.append((tier, failures))
        return 1.0

    t = _table({"i": {"a": (INCORRECT, "C", 1.0), "b": (INCORRECT, "D", 1.0), "c": (SOLVED, "B", 1.0)}})
    sequential_stop(t, ["a", "b", "c"], p_next=spy, value_of_success=100.0)
    assert seen == [("a", ()), ("b", ("a",)), ("c", ("a", "b"))]


def test_an_item_solved_early_costs_nothing_further():
    t = _table({"i": {"cheap": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 100.0)}})
    r = sequential_stop(t, ["cheap", "dear"], p_next=_always(1.0), value_of_success=100.0)
    assert r.completed == ["i"]
    assert r.usd_saved == 0.0, "usd_saved counts only what stopping skipped, not what solving skipped"


def test_the_saving_counts_only_the_calls_the_cascade_would_have_made():
    """Counting every remaining tier credits the rule with calls that were never going to happen.

    The cascade stops at the first success, so a stop before a cheap tier that solves the item saves
    exactly that one call -- not that call plus every dearer tier behind it. The version that counted
    all of them reported a saving of 242% of the entire bill, which is how the error announced itself.
    """
    t = _table({"i": {"cheap": (SOLVED, "B", 1.0), "mid": (SOLVED, "B", 10.0), "dear": (SOLVED, "B", 100.0)}})
    r = sequential_stop(t, ["cheap", "mid", "dear"], p_next=_always(0.0), value_of_success=1.0)
    assert r.stopped == ["i"]
    assert r.calls_saved == 1, "the cascade would have stopped at `cheap`"
    assert r.usd_saved == 1.0


def test_when_nothing_would_have_solved_it_the_whole_tail_is_saved():
    t = _table({"i": {"cheap": (INCORRECT, "C", 1.0), "dear": (INCORRECT, "D", 100.0)}})
    r = sequential_stop(t, ["cheap", "dear"], p_next=_always(0.0), value_of_success=1.0)
    assert r.calls_saved == 2 and r.usd_saved == 101.0
    assert r.lost == [], "nothing solvable was given up"
