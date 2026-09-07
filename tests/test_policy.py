"""The decisions that would produce a plausible wrong number if they were wrong.

Expected values are figures from the record the tier files cite, so a change that breaks the arithmetic
breaks a test rather than a report.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tierbook import policy  # noqa: E402

TODAY = "2026-08-30"
FAMILIES = {"agentic-coding": "api-strong-a"}


def registry():
    return policy.load_registry(ROOT / "examples" / "ledger" / "tiers")


# --- the ledger reads back ----------------------------------------------------------------------


def test_the_three_measured_tiers_load():
    assert set(registry()) == {"self-hosted-a", "api-cheap-a", "api-strong-a"}


def test_every_record_carries_the_cohort_it_was_measured_on():
    # Without it a paired comparison across two records is not a paired comparison.
    tiers = registry()
    cohorts = {t.cohort("agentic-coding") for t in tiers.values()}
    assert None not in cohorts and len(cohorts) == 1


def test_a_tier_that_does_not_report_cached_tokens_is_charged_as_fresh():
    tiers = registry()
    t = tiers["api-cheap-a"]
    assert round(t.token_cost(1_000_000, 1_000_000, 0), 4) == round(2.20 + 0.22, 4)
    blind = policy.Tier("blind", {**t.record, "price_card": {**t.record["price_card"], "cached_in": None}})
    assert round(blind.token_cost(1_000_000, 1_000_000, 0), 4) == round(2.20 * 2, 4)


# --- reliability is a cost, not a footnote ------------------------------------------------------


def test_the_retry_premium_reproduces_the_measured_figure():
    # 4 failures in 24 attempts, mean $4.4212 sunk before death -> $0.8842 per attempted call.
    tiers = registry()
    assert round(tiers["api-strong-a"].retry_premium, 4) == 0.8842
    assert tiers["api-cheap-a"].retry_premium == 0.0
    assert tiers["self-hosted-a"].retry_premium == 0.0


def test_the_accounting_boundary_is_recorded_so_the_premium_is_not_double_counted():
    tiers = registry()
    o = tiers["api-strong-a"].outcome("agentic-coding")
    assert "excluded" in (o.get("accounting_boundary") or "")


# --- the fixed-cost switch ----------------------------------------------------------------------


def test_an_idle_fixed_cost_tier_costs_infinity():
    tiers = registry()
    assert tiers["self-hosted-a"].amortised_cost_per_task(None) == float("inf")
    assert tiers["api-cheap-a"].amortised_cost_per_task(None) == 0.0


def test_the_break_even_volume_is_where_the_record_put_it():
    tiers = registry()
    assert round(tiers["self-hosted-a"].amortised_cost_per_task(319), 4) == 0.0477


# --- paired statistics --------------------------------------------------------------------------


def test_the_paired_bound_is_far_below_the_point_difference():
    """14 of 20 against 20 of 20 is a point difference of -0.30, and that understates it.

    All six discordant pairs favour the reference, so the lower bound on the difference is much worse. An
    earlier version of this project published -0.30 as the margin needed to admit the self-hosted tier; the
    paired arithmetic says no margin anyone would pre-register admits it.
    """
    lcb = policy.paired_difference_lcb(14, 0, 6, 0)
    assert lcb < -0.30
    assert lcb == pytest.approx(-0.4686, abs=5e-4)


def test_identical_outcomes_still_carry_a_bound_from_the_sample_size():
    # No discordant pairs is not proof of equality; it bounds the difference by what n could hide.
    assert policy.paired_difference_lcb(20, 0, 0, 0) == pytest.approx(-0.15, abs=1e-9)


def test_no_observations_cannot_be_certified():
    assert policy.paired_difference_lcb(0, 0, 0, 0) is None


# --- the offline compiler -----------------------------------------------------------------------


def test_no_margin_a_person_would_register_admits_the_self_hosted_tier():
    """The rule declines it on the solve rate alone, without the utilisation or retry arguments."""
    tiers = registry()
    for margin in (0.05, 0.10, 0.25, 0.30, 0.45):
        d = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=margin,
                                 realised_tasks_per_hour=616, today=TODAY)
        assert d.chosen.head != "self-hosted-a", margin


def test_a_loose_margin_admits_the_cheap_api_and_a_tight_one_does_not():
    tiers = registry()
    loose = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.40,
                                 realised_tasks_per_hour=616, today=TODAY)
    assert loose.chosen.head == "api-cheap-a" and loose.certified
    tight = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.05,
                                 realised_tasks_per_hour=616, today=TODAY)
    assert tight.chosen.head == "api-strong-a" and not tight.certified


def test_nothing_certified_is_recorded_differently_from_the_reference_winning():
    # An incident review will care which of the two happened.
    tiers = registry()
    d = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.05,
                             realised_tasks_per_hour=616, today=TODAY)
    assert "not the same as the reference winning" in d.why


def test_a_record_without_a_paired_2x2_cannot_be_certified():
    tiers = registry()
    rec = {**tiers["api-cheap-a"].record}
    fam = {**rec["families"]["agentic-coding"]}
    fam["paired_vs_reference"] = None
    rec["families"] = {"agentic-coding": fam}
    tiers["api-cheap-a"] = policy.Tier("api-cheap-a", rec)
    d = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.40,
                             realised_tasks_per_hour=616, today=TODAY)
    assert d.chosen.head == "api-strong-a"
    assert any("no paired" in c.note for c in d.ranked)


def test_records_measured_on_different_item_sets_cannot_be_compared():
    tiers = registry()
    rec = {**tiers["api-cheap-a"].record}
    fam = {**rec["families"]["agentic-coding"], "cohort": "some-other-twenty"}
    rec["families"] = {"agentic-coding": fam}
    tiers["api-cheap-a"] = policy.Tier("api-cheap-a", rec)
    d = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.40,
                             realised_tasks_per_hour=616, today=TODAY)
    assert d.chosen.head == "api-strong-a"
    assert any("same item set" in c.note for c in d.ranked)


def test_a_stale_record_cannot_win():
    tiers = registry()
    d = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.40,
                             realised_tasks_per_hour=616, today="2027-06-01", max_age_days=90)
    assert d.chosen.head == "api-strong-a"


def test_a_family_with_no_reference_measured_refuses_rather_than_guessing():
    tiers = registry()
    with pytest.raises(ValueError):
        policy.assign_family(tiers, "no-such-family", "api-strong-a", margin=0.40, today=TODAY)


def test_eligibility_is_checked_before_any_arithmetic():
    tiers = registry()
    d = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.40,
                             realised_tasks_per_hour=616, today=TODAY,
                             need={"modalities": ["audio"]})
    assert d.chosen.head == "api-strong-a"


def test_a_chain_is_only_offered_when_the_request_can_reject_the_artifact():
    tiers = registry()
    without = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.40,
                                   realised_tasks_per_hour=616, today=TODAY, request_can_reject=False)
    assert all(c.arrangement.kind == "outright" for c in without.ranked)
    with_check = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.40,
                                      realised_tasks_per_hour=616, today=TODAY, request_can_reject=True)
    assert any(c.arrangement.kind == "chain" for c in with_check.ranked)


def test_cost_is_per_incoming_request_not_per_solved_task():
    # Per-solve would smuggle a second quality objective in after non-inferiority already constrained it.
    # Taken on a metered tier, so the subject stays per-request-versus-per-solve and does not also depend on
    # how a fixed hourly reservation combines with a token card.
    tiers = registry()
    arr = policy.Arrangement(("api-cheap-a",), "outright")
    per_request, basis = policy._cost_per_request(tiers, arr, "agentic-coding", 616)
    o = tiers["api-cheap-a"].outcome("agentic-coding")
    assert per_request == pytest.approx(o["bill_usd"] / o["attempted"]
                                        + tiers["api-cheap-a"].retry_premium, rel=1e-9)
    assert basis is None, "a gateway authored this charge, so nothing needs qualifying"


def test_the_decision_carries_the_registry_version_so_it_can_be_replayed():
    tiers = registry()
    d = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.40,
                             realised_tasks_per_hour=616, today=TODAY)
    assert len(d.registry_version) == 16
    assert d.registry_version == policy.registry_version(tiers)
    assert len(d.ranked) >= 2


def test_the_compiled_table_has_one_entry_per_family_per_check_condition():
    tiers = registry()
    table = policy.compile_table(tiers, FAMILIES, margin=0.40,
                                realised_tasks_per_hour=616, today=TODAY)
    assert set(table) == {"agentic-coding"}
    assert set(table["agentic-coding"]) == {"can_reject", "cannot_reject"}


# --- the online path has no cleverness in it ----------------------------------------------------


def test_an_artifact_is_shipped_and_never_second_guessed():
    assert policy.should_escalate("ok", artifact=True) is False
    assert policy.should_escalate("looked_doubtful", artifact=True) is False


def test_a_check_that_rejected_the_artifact_does_escalate():
    # The one failure class that reads the artifact. Without it a verified chain could not escalate on a
    # wrong-but-well-formed answer, which is the entire justification for having the chain.
    assert policy.should_escalate(policy.CHECK_REJECTED, artifact=True) is True


def test_escalation_fires_on_every_observable_failure_and_nothing_else():
    for outcome in policy.OBSERVABLE_FAILURES:
        assert policy.should_escalate(outcome, artifact=False) is True
    assert policy.should_escalate("model_said_it_was_unsure", artifact=False) is False


def test_a_run_stops_at_the_first_accepted_artifact_and_keeps_the_failed_bill():
    calls = []

    def execute(tier_id):
        calls.append(tier_id)
        if tier_id == "self-hosted-a":
            return policy.Attempt(tier_id, "empty_stream", billed_usd=0.05, artifact=False)
        return policy.Attempt(tier_id, "ok", billed_usd=0.70, artifact=True)

    ep = policy.run(("self-hosted-a", "api-strong-a"), execute)
    assert calls == ["self-hosted-a", "api-strong-a"]
    assert ep.shipped is True
    assert round(ep.billed_usd, 2) == 0.75


def test_an_arrangement_whose_every_stage_fails_terminates():
    def execute(tier_id):
        return policy.Attempt(tier_id, "transport_error", billed_usd=0.01)

    ep = policy.run(("a", "b", "c"), execute)
    assert len(ep.attempts) == 3
    assert ep.shipped is False
    assert "every stage" in ep.stopped_because


def test_a_chain_may_not_repeat_a_tier():
    with pytest.raises(ValueError):
        policy.run(("a", "a"), lambda t: policy.Attempt(t, "ok", artifact=True))


def test_a_spent_budget_stops_the_walk():
    def execute(tier_id):
        return policy.Attempt(tier_id, "empty_stream", billed_usd=1.0)

    ep = policy.run(("a", "b", "c"), execute, budget_usd=1.5)
    assert len(ep.attempts) == 2
    assert "budget" in ep.stopped_because


# --- an unmeasured spend is refused, never priced at zero ------------------------------------------


def test_an_absent_bill_is_priced_from_the_rate_card_and_says_so():
    """The record already carries what pricing needs -- a rate card and the token legs that were observed --
    so a missing gateway charge is not a missing cost. It is a cost from a different authority, and the
    difference is stated rather than hidden."""
    tiers = registry()
    t = tiers["api-cheap-a"]
    o = t.outcome("agentic-coding")
    del o["bill_usd"]
    o["tokens"] = {"fresh_in": 1_000_000, "cached_in": 0, "cache_write": 0, "out": 100_000}
    spend, basis = policy._family_spend(t, "agentic-coding")
    assert basis == "rate_card_and_observed_tokens"
    assert spend == pytest.approx(t.token_cost(1_000_000, 0, 100_000, 0), rel=1e-9)
    _, note = policy._cost_per_request(tiers, policy.Arrangement(("api-cheap-a",), "outright"),
                                       "agentic-coding", 616)
    assert note and "no gateway authored this charge" in note


def test_a_gateway_bill_wins_over_the_rate_card_when_both_exist():
    """Cost truth belongs to the billing gateway: it is what the money left through. A rate card is a model
    of that, and a model must not overrule the thing it models."""
    tiers = registry()
    t = tiers["api-cheap-a"]
    o = t.outcome("agentic-coding")
    o["tokens"] = {"fresh_in": 10 ** 9, "cached_in": 0, "cache_write": 0, "out": 10 ** 9}
    spend, basis = policy._family_spend(t, "agentic-coding")
    assert basis == "gateway_bill" and spend == pytest.approx(o["bill_usd"])


def test_neither_a_bill_nor_tokens_is_refused_rather_than_treated_as_free():
    """The defect this replaces. An absent `bill_usd` read as $0.00 makes a candidate free, and free wins a
    cost objective by construction -- so forgetting to measure would have been the cheapest thing a
    candidate could do."""
    tiers = registry()
    o = tiers["api-cheap-a"].outcome("agentic-coding")
    del o["bill_usd"]
    o.pop("tokens", None)
    spend, why = policy._family_spend(tiers["api-cheap-a"], "agentic-coding")
    assert spend is None
    assert "not zero spend" in why and "unmeasured spend" in why
    cost, note = policy._cost_per_request(tiers, policy.Arrangement(("api-cheap-a",), "outright"),
                                          "agentic-coding", 616)
    assert cost == float("inf"), "excluded for want of a figure, not made free by its absence"
    assert "unmeasured spend" in note


def test_an_absent_token_leg_is_refused_rather_than_summed_as_zero():
    """Same rule one level down: three legs summed where four were billed reports a total below what was
    paid, and the dropped leg is the one that only appears on long threads."""
    tiers = registry()
    o = tiers["api-cheap-a"].outcome("agentic-coding")
    del o["bill_usd"]
    o["tokens"] = {"fresh_in": 1000, "cached_in": None, "out": 10}
    spend, why = policy._family_spend(tiers["api-cheap-a"], "agentic-coding")
    assert spend is None and "cached_in" in why and "not a zero leg" in why


def test_a_candidate_excluded_for_want_of_a_figure_does_not_read_as_expensive():
    """An incident review cares which one it was: no measurement, or a measurement that came out high."""
    tiers = registry()
    o = tiers["api-cheap-a"].outcome("agentic-coding")
    del o["bill_usd"]
    o.pop("tokens", None)
    d = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.40, alpha=0.05,
                             realised_tasks_per_hour=616, today=TODAY)
    entry = next(c for c in d.ranked if list(c.arrangement.tiers) == ["api-cheap-a"])
    assert entry.cost_per_request == float("inf")
    assert "cost not computed" in entry.note


def test_a_fixed_cost_candidate_is_not_charged_for_its_hour_twice():
    """The schema says a non-null hourly price makes the effective rate `max(token rates, hourly / realised
    tasks per hour)`. The code summed them, which bills one GPU twice and inflates precisely the candidate
    the owner has decided to keep. The two figures describe one machine: the per-token card for a self-hosted
    engine is that same hour divided by throughput at saturation."""
    tiers = registry()
    t = tiers["self-hosted-a"]
    o = t.outcome("agentic-coding")
    cost, basis = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                           "agentic-coding", 616)
    token_side = o["bill_usd"] / o["attempted"]
    hour_side = t.amortised_cost_per_task(616)
    assert cost == pytest.approx(max(token_side, hour_side) + t.retry_premium, rel=1e-9)
    assert cost < token_side + hour_side, "the sum is the defect this replaces"
    assert "bills the GPU twice" in basis
    # Which side bound and at what occupancy, because that is the whole content of the figure: an hour spread
    # over an idle machine is an experimenter's cost, not a deployment's.
    assert "binds at $" in basis and "concurrency" in basis and "tasks/hour" in basis


def test_the_hour_binds_when_the_machine_is_idler_than_the_card_assumed():
    """Which figure binds is not a preference. A card measured at saturation understates the cost of a
    machine nobody is keeping busy, so the amortised share is the larger number exactly then -- and `max`
    picks it without anyone choosing."""
    tiers = registry()
    t = tiers["self-hosted-a"]
    o = t.outcome("agentic-coding")
    idle, busy = 1.0, 100_000.0
    cost_idle, _ = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                            "agentic-coding", idle)
    cost_busy, _ = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                            "agentic-coding", busy)
    assert cost_idle == pytest.approx(t.amortised_cost_per_task(idle) + t.retry_premium, rel=1e-9)
    assert cost_busy == pytest.approx(o["bill_usd"] / o["attempted"] + t.retry_premium, rel=1e-9)
    assert cost_idle > cost_busy


def test_an_idle_fixed_cost_candidate_is_infinite_not_cheap():
    """The switch that keeps a rented machine out of an assignment when nothing keeps it busy. Unchanged by
    the above, and checked here because the no-double-charge branch is where it now lives."""
    tiers = registry()
    tiers["self-hosted-a"].record["price_card"]["hourly_fixed_usd"] = 15.21742
    cost, basis = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                           "agentic-coding", None)
    assert cost == float("inf")
    # "inf" is the finding, not a formatting accident, so it is stated in words rather than printed as a
    # number a reader might take for a large price.
    assert "spread over no work" in basis and "unbounded cost per request" in basis


def test_a_fixed_cost_candidate_with_no_token_figure_rests_on_its_hour_and_says_so():
    """Not a refusal: an hourly reservation IS a cost figure, and `max` can only ignore an unmeasured token
    side, never make anything cheaper. But the figure then rests on one leg of a two-leg comparison, and a
    reader has to be told which."""
    tiers = registry()
    o = tiers["self-hosted-a"].outcome("agentic-coding")
    del o["bill_usd"]
    o.pop("tokens", None)
    cost, basis = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                          "agentic-coding", 616)
    assert cost == pytest.approx(tiers["self-hosted-a"].amortised_cost_per_task(616)
                                 + tiers["self-hosted-a"].retry_premium, rel=1e-9)
    assert "hourly reservation alone" in basis and "was not available to compare against" in basis
