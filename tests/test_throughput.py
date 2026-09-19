"""Tests for what a measured rate is allowed to support.

Every number here is one this project measured and then had to take back:

| | |
|---|---|
| one load client against two, same experiment | 425,879 against **584,739** an hour |
| `max_num_seqs` 27 while 384 were offered; raised to 256 | **+33%** value per box-hour at 60 output tokens, +18% at 300, +5% at 600 |
| no long request resident, open loop, 1s deadline | **225,730** an hour, 100% inside the deadline |
| one long request resident | **102,022** an hour |
| the same co-residency question, closed loop against open loop | the verdict **reversed**: -$8.63 against +$18.88 per box-hour |
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import throughput as tp  # noqa: E402

GENERATOR = "2 pods x 8 processes, anti-affinity"


def offered(**over):
    base = dict(concurrency=256, seats=256, generator=GENERATOR)
    base.update(over)
    return tp.Offered(**base)


def rate(**over):
    base = dict(per_hour=225730.0, arrivals="open_loop", offered=offered(),
                deadline_seconds=1.0, goodput_per_hour=225730.0)
    base.update(over)
    return tp.Throughput(**base)


# --- the load generator has to be described, because "we saturated it" is the claim that needs checking -------------------

def test_a_generator_nobody_described_cannot_be_run_harder_by_the_next_person():
    with pytest.raises(tp.Unmeasured, match="cannot be run harder"):
        offered(generator="   ")


def test_offering_fewer_requests_than_the_engine_admits_makes_the_rate_a_property_of_the_client():
    assert offered(concurrency=8, seats=256).starves_the_engine is True
    assert offered(concurrency=256, seats=256).starves_the_engine is False


def test_an_unread_seat_count_does_not_answer_whether_the_engine_was_starved():
    """It returns False rather than guessing. The refusal belongs where there is another rate to refuse against."""
    assert offered(seats=None).starves_the_engine is False


# --- a rate is a lower bound by default ----------------------------------------------------------------------------------

def test_a_rate_whose_generator_was_never_checked_is_a_lower_bound():
    """Treating silence as a measurement is how a client's limit gets published as a box's capacity."""
    assert rate(understated_because="generator_not_checked").is_lower_bound is True
    assert "LOWER BOUND" in str(rate(understated_because="generator_saturated"))


def test_a_starved_engine_makes_the_rate_a_lower_bound_without_anybody_saying_so():
    assert rate(offered=offered(concurrency=8, seats=256)).is_lower_bound is True


def test_a_fully_offered_checked_run_is_not_a_lower_bound():
    assert rate().is_lower_bound is False


def test_the_reasons_a_rate_understates_are_closed_because_each_is_a_different_thing_to_fix():
    assert tp.UNDERSTATED_BECAUSE == ("generator_saturated", "offered_below_seats", "generator_not_checked")
    with pytest.raises(tp.Unmeasured, match="not one of"):
        rate(understated_because="probably_fine")


# --- a closed loop cannot support a service level, at any sample size -----------------------------------------------------

def test_a_closed_loop_measures_capacity_and_is_silent_about_service():
    """Structural rather than a matter of rigour: the client offers less when the server slows, so no queue forms and a
    deadline has nothing to be missed against."""
    closed = rate(arrivals="closed_loop")
    assert closed.supports_a_service_level_claim() is False
    assert "no queue forms" in closed.why_not_a_service_level()


def test_an_open_loop_with_no_deadline_is_also_not_a_service_level():
    """The mean is conserved when box-time moves between request families, so it cannot see whether anything arrived in
    time."""
    bare = rate(deadline_seconds=None, goodput_per_hour=None)
    assert bare.supports_a_service_level_claim() is False
    assert "blind" in bare.why_not_a_service_level()


def test_an_open_loop_with_a_deadline_is_a_service_level():
    assert rate().supports_a_service_level_claim() is True
    assert "landed inside it" in rate().why_not_a_service_level()


def test_the_two_arrival_processes_are_not_two_settings_of_one_thing():
    assert tp.ARRIVALS == ("closed_loop", "open_loop")
    with pytest.raises(tp.Unmeasured, match="reversed this project's own"):
        rate(arrivals="poisson_ish")


# --- a deadline and a goodput travel together ----------------------------------------------------------------------------

def test_a_goodput_with_no_deadline_is_a_number_nobody_can_check():
    with pytest.raises(tp.Unmeasured, match="nobody can check"):
        rate(deadline_seconds=None)
    with pytest.raises(tp.Unmeasured, match="nobody measured"):
        rate(goodput_per_hour=None)


def test_more_requests_cannot_return_inside_the_deadline_than_returned_at_all():
    with pytest.raises(tp.Unmeasured, match="came back at all"):
        rate(per_hour=1000.0, goodput_per_hour=1001.0)


def test_a_goodput_equal_to_the_rate_is_the_measured_case_and_is_allowed():
    """The zero-long-request arm returned 100% inside one second, so equality has to be representable."""
    assert rate(per_hour=225730.0, goodput_per_hour=225730.0).goodput_per_hour == 225730.0


# --- two rates are comparable only when the load, not the box, is what is held --------------------------------------------

def test_two_arrival_processes_are_not_comparable_because_opening_the_loop_reversed_the_verdict():
    with pytest.raises(tp.Unmeasured, match=r"\$8.63"):
        tp.comparable_load(rate(), rate(arrivals="closed_loop"))


def test_an_unread_seat_count_is_not_an_unlimited_one():
    with pytest.raises(tp.Unmeasured, match="unread limit is not an unlimited one"):
        tp.comparable_load(rate(), rate(offered=offered(seats=None)))


def test_two_seat_counts_are_a_difference_in_configuration_rather_than_in_the_box():
    with pytest.raises(tp.Unmeasured, match="the difference between them is the configuration"):
        tp.comparable_load(rate(), rate(offered=offered(seats=27)))


def test_a_capacity_and_a_service_level_are_two_different_quantities():
    with pytest.raises(tp.Unmeasured, match="two different quantities"):
        tp.comparable_load(rate(), rate(deadline_seconds=None, goodput_per_hour=None))


def test_two_deadlines_make_two_numbers_by_construction():
    with pytest.raises(tp.Unmeasured, match="different number by construction"):
        tp.comparable_load(rate(), rate(deadline_seconds=2.0))


def test_the_measured_pair_is_comparable():
    tp.comparable_load(rate(), rate(per_hour=102022.0, goodput_per_hour=73200.0))


# --- a co-residency claim needs the arm nobody ran -----------------------------------------------------------------------

def test_a_co_residency_claim_without_the_zero_arm_is_refused():
    """The defect in the shape it happened: every arm contained some long requests, so 'mixing is economically neutral'
    came out of comparing one mixture with another. The unmeasured arm read 225,730 against 102,022."""
    mixed = rate(per_hour=102022.0, goodput_per_hour=73200.0)
    with pytest.raises(tp.Unmeasured, match="225,730"):
        tp.refuse_coresidency_claim_without_a_zero_arm({"one_long": mixed, "two_long": mixed})


def test_a_co_residency_claim_with_the_zero_arm_is_allowed():
    tp.refuse_coresidency_claim_without_a_zero_arm(
        {"zero": rate(), "one_long": rate(per_hour=102022.0, goodput_per_hour=73200.0)})


def test_a_co_residency_claim_is_a_service_level_question_so_every_arm_needs_a_deadline():
    with pytest.raises(tp.Unmeasured, match="cannot support a service-level claim"):
        tp.refuse_coresidency_claim_without_a_zero_arm(
            {"zero": rate(deadline_seconds=None, goodput_per_hour=None), "one_long": rate()})


# --- the shapes a rate refuses outright ----------------------------------------------------------------------------------

def test_a_run_that_offered_nothing_measured_nothing():
    with pytest.raises(tp.Unmeasured, match="measured nothing"):
        offered(concurrency=0)


def test_a_bare_concurrency_cannot_say_whether_the_engine_or_the_client_was_the_limit():
    with pytest.raises(tp.Unmeasured, match="bare concurrency"):
        rate(offered=256)


def test_a_negative_rate_is_not_a_rate():
    with pytest.raises(tp.Unmeasured, match="is not a rate"):
        rate(per_hour=-1.0)


def test_a_deadline_of_zero_is_not_a_deadline():
    with pytest.raises(tp.Unmeasured, match="is not a deadline"):
        rate(deadline_seconds=0.0)


# --- deliverability, and the asymmetry between what was declared and what was measured ------------------------------------

def ceiling(**over):
    base = dict(per_hour=50000.0, declared_by="vendor contract")
    base.update(over)
    return tp.Ceiling(**base)


def lower_bound_rate():
    """A measurement that understates the box: 8 offered against 256 seats."""
    return rate(per_hour=100000.0, goodput_per_hour=100000.0, offered=offered(concurrency=8, seats=256))


def test_a_measured_goodput_that_covers_the_requirement_makes_it_deliverable():
    outcome, why = tp.deliverable(50000.0, measured=rate())
    assert outcome == "deliverable" and "covers the requirement" in why


def test_a_lower_bound_can_prove_sufficiency_because_the_box_did_at_least_that_much():
    """The asymmetry, first direction. This is the case a naive 'lower bounds are unusable' rule would get wrong."""
    outcome, why = tp.deliverable(50000.0, measured=lower_bound_rate())
    assert outcome == "deliverable"
    assert "the margin is at least this large" in why


def test_a_lower_bound_cannot_refuse_because_the_shortfall_may_be_our_own_generator():
    """The asymmetry, other direction, and the case that keeps the two honest: without `unknown`, a shortfall against a
    lower bound would read as a refusal and this project would decline assignments on the strength of its load client."""
    outcome, why = tp.deliverable(150000.0, measured=lower_bound_rate())
    assert outcome == "unknown"
    assert "may be the load generator" in why


def test_a_full_measurement_that_falls_short_does_refuse():
    outcome, why = tp.deliverable(300000.0, measured=rate())
    assert outcome == "refused" and "not a lower bound" in why


def test_a_declared_ceiling_refuses_whatever_the_hardware_would_have_managed():
    outcome, why = tp.deliverable(150000.0, ceiling=ceiling())
    assert outcome == "refused" and "declared limit refuses" in why


def test_a_declared_ceiling_refuses_even_when_a_measurement_says_the_box_could_do_it():
    """A contractual limit is a limit. The ceiling is checked before the measurement for exactly this case."""
    outcome, _ = tp.deliverable(150000.0, measured=rate(), ceiling=ceiling())
    assert outcome == "refused"


def test_a_declared_ceiling_alone_can_never_show_a_requirement_is_met():
    outcome, why = tp.deliverable(10000.0, ceiling=ceiling())
    assert outcome == "unknown"
    assert "can never show one is met" in why


def test_no_evidence_at_all_is_unknown_rather_than_either_default():
    assert tp.deliverable(50000.0)[0] == "unknown"


def test_a_measurement_that_cannot_support_a_service_level_cannot_answer_deliverability():
    outcome, why = tp.deliverable(50000.0, measured=rate(arrivals="closed_loop"))
    assert outcome == "unknown" and "service-level question" in why


def test_the_outcomes_and_the_two_kinds_of_evidence_are_closed():
    assert tp.DELIVERABILITY == ("deliverable", "refused", "unknown")
    assert tp.RATE_KINDS == ("declared_ceiling", "measured_goodput")


def test_a_ceiling_needs_somebody_attached_to_it():
    with pytest.raises(tp.Unmeasured, match="cannot be renegotiated"):
        ceiling(declared_by="  ")


def test_a_ceiling_of_zero_is_a_closed_endpoint_rather_than_a_rate():
    with pytest.raises(tp.Unmeasured, match="closed endpoint"):
        ceiling(per_hour=0.0)


def test_a_requirement_of_nothing_is_not_a_requirement():
    with pytest.raises(tp.Unmeasured, match="not a requirement"):
        tp.deliverable(0.0, measured=rate())


def test_reading_a_ceiling_as_a_measurement_is_refused_by_name():
    """The substitution is tempting and silent: a configured max_requests_per_second is the only rate many records carry.
    A configured value is a hypothesis."""
    with pytest.raises(tp.Unmeasured, match="a configured value is a hypothesis"):
        tp.refuse_a_ceiling_read_as_a_measurement(ceiling())
