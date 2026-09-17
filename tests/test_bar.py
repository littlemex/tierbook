"""Tests for a floor and the target it is claimed for.

The bar these are about was "hold floor 0.90 with at most 126 escalations per 1,187", and it was unsatisfiable on the
day it was written, twice over. Both proofs are arithmetic and neither needs a run: in one condition the floor was above
what escalating every item could reach, and in the other the permitted budget was below the minimum number of items
escalation would have to turn from wrong to right.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import bar as br  # noqa: E402

N = 1187
#: The counts the ledger's own figures pin down. The rate 0.608 is compatible with 721 solved and with 722, which give
#: 348 and 347 minimum rescues; the reported 347 is what says it was 722. Same for 0.7597 and 902 against 167.
TERSE_SOLVED, EXPLAINING_SOLVED = 722, 902
BAR_BUDGET = 141


def bar(**kw):
    base = dict(floor=0.90, target="api", box_solved=TERSE_SOLVED, items=N, target_rescued=280)
    base.update(kw)
    return br.Bar(**base)


# --- the ledger's own arithmetic ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("solved,expected", [(TERSE_SOLVED, 347), (EXPLAINING_SOLVED, 167)])
def test_the_minimum_net_rescues_reproduce_the_measured_figures(solved, expected):
    assert bar(box_solved=solved).minimum_net_rescues == expected


def test_inverting_a_rate_gives_the_wrong_count_by_one():
    """DEFECT the count-based fields close. My first version took the rate and did `floor(0.608 x 1187)` = 721, while the
    count the reported 347 implies is 722 -- an off-by-one in the number of items escalation must rescue. `round` happens
    to be right here and is not right in general: a rate stated to three decimals over 1,187 items covers a window more
    than one item wide, so the count is recoverable only when that window holds exactly one integer, which is not a
    property anybody checks. Taking the count removes the question."""
    assert math.floor(0.608 * N) == 721
    assert bar(box_solved=721).minimum_net_rescues == 348   # what the rate-based version computed
    assert bar(box_solved=722).minimum_net_rescues == 347   # what the ledger reports


def test_the_two_reported_figures_are_not_equally_consistent_with_their_rates():
    """A finding this implementation surfaced rather than a defect it fixes: 347 net rescues implies 722 solved, whose
    rate is 0.6083 and the prose says 0.608 -- consistent. But 167 implies 902 solved, whose rate is 0.7599 while the
    prose says 0.7597. No integer count over 1,187 items gives 0.7597, so the rate and the rescue count in that row came
    from slightly different computations. The ordinal comparisons the entry rests on survive it; the pair does not
    round-trip, and that is worth knowing before either number is quoted as the other's provenance."""
    assert bar(box_solved=722).minimum_net_rescues == 347
    assert bar(box_solved=902).minimum_net_rescues == 167
    assert round(902 / N, 4) == 0.7599
    assert round(901 / N, 4) == 0.7591
    assert not any(round(k / N, 4) == 0.7597 for k in range(N + 1))


def test_a_budget_below_the_minimum_is_unsatisfiable_by_anything():
    """141 is below 167, so no signal, no oracle and no mechanism could have met the bar in the better condition."""
    b = bar(box_solved=EXPLAINING_SOLVED, escalation_budget=BAR_BUDGET)
    with pytest.raises(br.Unsatisfiable, match="No signal, no oracle and no mechanism"):
        b.check()


def test_the_terse_condition_fails_for_the_other_reason_entirely():
    """A gamma above 1 needs a better target, not a bigger budget, and a single 'infeasible' would send a reader to look
    for the wrong one."""
    b = bar(box_solved=TERSE_SOLVED, escalation_budget=BAR_BUDGET)
    assert b.gamma > 1.0
    with pytest.raises(br.Unsatisfiable, match="needs a better target, not a better signal"):
        b.check()


def test_the_reachable_case_passes_both_checks():
    b = bar(floor=0.80, box_solved=EXPLAINING_SOLVED, escalation_budget=BAR_BUDGET)
    b.check()
    assert b.minimum_net_rescues == 48


# --- gamma is what makes two conditions comparable ---------------------------------------------------------------------

def test_one_absolute_floor_is_two_different_requirements():
    """Equal in the absolute, the two demand 347 and 167 rescues -- a factor of two -- and every comparison made between
    them before this was a comparison of two different things."""
    terse, explaining = bar(box_solved=TERSE_SOLVED), bar(box_solved=EXPLAINING_SOLVED)
    assert terse.floor == explaining.floor
    assert br.comparable([terse, explaining]) is False


def test_two_bars_asking_the_same_fraction_of_the_headroom_are_comparable():
    a = br.Bar(floor=0.80, target="api", box_solved=600, items=1000, target_rescued=400)
    b = br.Bar(floor=0.80, target="api", box_solved=600, items=1000, target_rescued=400)
    assert br.comparable([a, b]) is True
    assert br.comparable([a]) is True


def test_a_target_that_rescues_nothing_puts_gamma_beyond_any_floor():
    """There is no headroom at all, so no floor above the box is reachable, and infinity says that rather than dividing
    by zero."""
    assert bar(target_rescued=0).gamma == math.inf


def test_the_ceiling_is_exact_because_it_comes_from_counts():
    b = bar(box_solved=EXPLAINING_SOLVED, target_rescued=280)
    assert b.ceiling == pytest.approx((EXPLAINING_SOLVED + 280) / N)


# --- what a bar may not be --------------------------------------------------------------------------------------------

def test_a_floor_with_no_target_cannot_have_its_feasibility_decided():
    """0.90 is reachable against one target and not against another, and the infeasibility was in the pairing."""
    with pytest.raises(br.Unsatisfiable, match="feasibility cannot be decided"):
        bar(target="")


def test_a_floor_the_box_already_clears_asks_for_nothing():
    """It is met by never escalating, and two conditions' bars stated that way are not comparable."""
    with pytest.raises(br.Unsatisfiable, match="asks for nothing"):
        bar(floor=0.50, box_solved=EXPLAINING_SOLVED)


def test_a_target_cannot_rescue_an_item_that_was_already_right():
    """Counting those would put the ceiling above what escalation can actually reach."""
    with pytest.raises(br.Unsatisfiable, match="items the box missed"):
        bar(box_solved=EXPLAINING_SOLVED, target_rescued=N - EXPLAINING_SOLVED + 1)


def test_a_solved_count_larger_than_the_item_count_is_refused():
    with pytest.raises(br.Unsatisfiable, match="not a count of"):
        bar(box_solved=N + 1)


def test_a_budget_above_the_item_count_is_not_a_constraint():
    with pytest.raises(br.Unsatisfiable, match="not a constraint"):
        bar(escalation_budget=N + 1)


def test_a_floor_outside_the_unit_interval_is_refused():
    with pytest.raises(br.Unsatisfiable, match="not a rate"):
        bar(floor=1.5)


def test_no_derived_number_can_be_supplied():
    """A stored gamma or ceiling can disagree with the floor it was computed from, and this study's own failure was a
    pair of numbers whose provenance was a label somebody attached to them."""
    for field in ("gamma", "ceiling", "minimum_net_rescues", "box_accuracy"):
        with pytest.raises(TypeError):
            br.Bar(floor=0.9, target="api", box_solved=700, items=N, target_rescued=280, **{field: 0.5})


# --- the door ---------------------------------------------------------------------------------------------------------

def _run(capsys, extra):
    from tierbook import cli
    code = cli.main(["floor-feasibility", "--items", str(N), "--target", "api", *extra])
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def test_the_door_exits_two_for_an_unsatisfiable_bar(capsys):
    """Not 1: nothing is malformed and no policy is at fault. Reporting it as a failure of the thing being measured is
    the confusion this door exists to end."""
    code, text = _run(capsys, ["--floor", "0.90", "--box-solved", str(EXPLAINING_SOLVED),
                               "--target-rescued", "280", "--escalation-budget", str(BAR_BUDGET)])
    assert code == 2
    assert "at least 167 net rescues" in text


def test_the_door_names_which_impossibility_applies(capsys):
    code, text = _run(capsys, ["--floor", "0.90", "--box-solved", str(TERSE_SOLVED),
                               "--target-rescued", "280", "--escalation-budget", str(BAR_BUDGET)])
    assert code == 2
    assert "escalating EVERY item" in text


def test_the_door_reports_a_satisfiable_bar_with_what_it_will_take(capsys):
    code, text = _run(capsys, ["--floor", "0.80", "--box-solved", str(EXPLAINING_SOLVED),
                               "--target-rescued", "280", "--escalation-budget", str(BAR_BUDGET)])
    assert code == 0
    assert "satisfiable" in text and "48 net rescues" in text


def test_the_door_exits_one_for_a_malformed_bar(capsys):
    """A different exit code from the unsatisfiable one, because a bar this door could not read and a bar nobody could
    meet send the operator to different places."""
    code, text = _run(capsys, ["--floor", "0.50", "--box-solved", str(EXPLAINING_SOLVED), "--target-rescued", "280"])
    assert code == 1
    assert "asks for nothing" in text
