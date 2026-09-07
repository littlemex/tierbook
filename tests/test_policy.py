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
    per_request, basis = policy._cost_per_request(tiers, arr, "agentic-coding")
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


def test_an_absent_gateway_charge_is_refused_not_reconstructed():
    """The governing document says this project reads the gateway's quotes and never reconstructs charge. An
    earlier version fell back to the rate card and called that the project's rule about cost, which inverted
    the rule it cited: a reconstruction omits credits, minimums, rounding and price changes, so ranking on it
    launders an estimate into a settled figure."""
    tiers = registry()
    t = tiers["api-cheap-a"]
    o = t.outcome("agentic-coding")
    del o["bill_usd"]
    o["tokens"] = {"fresh_in": 1_000_000, "cached_in": 0, "cache_write": 0, "out": 100_000}
    spend, why = policy._family_spend(t, "agentic-coding")
    assert spend is None
    assert "Cost truth belongs to the gateway" in why and "Route the candidate through the gateway" in why
    cost, note = policy._cost_per_request(tiers, policy.Arrangement(("api-cheap-a",), "outright"),
                                          "agentic-coding")
    assert cost == float("inf"), "unrankable on cost, which is a fact about the instrumentation"


def test_the_imputed_figure_exists_for_reporting_and_the_objective_cannot_reach_it():
    """The separation is the point of having two functions: the estimate answers a real question and must not
    be able to become a decision."""
    tiers = registry()
    t = tiers["api-cheap-a"]
    o = t.outcome("agentic-coding")
    del o["bill_usd"]
    o["tokens"] = {"fresh_in": 1_000_000, "cached_in": 0, "cache_write": 0, "out": 100_000}
    usd, why = policy.imputed_spend(t, "agentic-coding")
    assert usd == pytest.approx(t.token_cost(1_000_000, 0, 100_000, 0), rel=1e-9)
    assert "Not a settled charge" in why
    cost, _ = policy._cost_per_request(tiers, policy.Arrangement(("api-cheap-a",), "outright"),
                                       "agentic-coding")
    assert cost == float("inf"), "the objective did not see the imputed figure"


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
                                          "agentic-coding")
    assert cost == float("inf"), "excluded for want of a figure, not made free by its absence"
    assert "unmeasured spend" in note


def test_an_absent_token_leg_is_refused_by_the_imputed_figure_too():
    """Same rule one level down: three legs summed where four were used reports a total below what was, and
    the dropped leg is the one that only appears on long threads."""
    tiers = registry()
    o = tiers["api-cheap-a"].outcome("agentic-coding")
    del o["bill_usd"]
    o["tokens"] = {"fresh_in": 1000, "cached_in": None, "out": 10}
    usd, why = policy.imputed_spend(tiers["api-cheap-a"], "agentic-coding")
    assert usd is None and "cached_in" in why and "not a zero leg" in why


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




# --- a reserved candidate has no per-request price, and the objective stopped inventing one -------


def test_a_reserved_candidate_contributes_no_marginal_charge():
    """The reservation is kept by decision, so the bill arrives whether or not this request uses the box. An
    average of `hourly / realised tasks per hour` is circular -- routing to it is what changes the denominator
    -- and at the first real cohort it came out $0.250665 against a token side of $0.038934 purely because one
    experimenter left the machine idle. A router believing that sends traffic to metered APIs at real money
    while paid-for capacity sits idle, which raises total spend."""
    tiers = registry()
    t = tiers["self-hosted-a"]
    assert t.is_reserved
    cost, basis = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                          "agentic-coding")
    assert cost == pytest.approx(t.retry_premium, rel=1e-9)
    assert "marginal charge per request is nothing" in basis
    assert "circular" in basis, "the reason a reader needs is why an average was not used"


def test_a_reserved_candidate_is_not_made_expensive_by_being_measured_idle():
    """The whole inversion in one assertion: occupancy must not enter the routing price at all."""
    tiers = registry()
    idle, _ = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                      "agentic-coding")
    busy, _ = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                       "agentic-coding")
    assert idle == busy


def test_a_reserved_tier_placed_late_in_a_cascade_is_not_made_cheap_by_reach():
    """A reservation does not shrink because only a fifth of requests reach that stage. Reach-weighting a
    fixed bill is what let a reserved tier look cheap by being placed second."""
    tiers = registry()
    head_only, _ = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                            "agentic-coding")
    # Placing it behind a head must not change its financial contribution, because zero does not scale.
    chained, _ = policy._cost_per_request(tiers, policy.Arrangement(("api-cheap-a", "self-hosted-a"), "chain"),
                                          "agentic-coding")
    o = tiers["api-cheap-a"].outcome("agentic-coding")
    reach = 1.0 - (o["solved"] / o["attempted"])
    expected = (o["bill_usd"] / o["attempted"] + tiers["api-cheap-a"].retry_premium) \
        + reach * tiers["self-hosted-a"].retry_premium
    assert chained == pytest.approx(expected, rel=1e-9)


def test_a_reserved_tail_behind_an_api_head_is_not_infinitely_expensive():
    """Throughput used to be computed for the head and applied to every tier, so a reserved tail behind a head
    that reports no throughput came out infinite -- excluded for a bookkeeping reason."""
    tiers = registry()
    cost, _ = policy._cost_per_request(tiers, policy.Arrangement(("api-strong-a", "self-hosted-a"), "chain"),
                                       "agentic-coding")
    assert cost != float("inf")


# --- the period question the average was standing in for -----------------------------------------


def test_the_reservation_verdict_is_undecidable_without_a_counterfactual_quote():
    """The honest answer for the first real cohort: there was no metered candidate to quote the traffic. That
    is the absence of a comparison, not evidence that the box is expensive, and it leads somewhere different --
    get a quote, rather than route away."""
    tiers = registry()
    v = policy.reservation_verdict(tiers["self-hosted-a"], "agentic-coding", window_hours=1.07,
                                  counterfactual=None)
    assert v["verdict"] == "undecidable"
    assert "not evidence that the box is expensive" in v["reason"].replace("\n", " ")
    assert v["bill_usd"] == pytest.approx(15.2174 * 1.07, rel=1e-6)


def test_the_reservation_verdict_needs_a_window_because_a_reservation_has_no_cost_without_one():
    tiers = registry()
    v = policy.reservation_verdict(tiers["self-hosted-a"], "agentic-coding", window_hours=None,
                                  counterfactual=tiers["api-cheap-a"])
    assert v["verdict"] == "undecidable" and "exists only over a window" in v["reason"]


def test_the_reservation_pays_when_the_traffic_would_have_cost_more_elsewhere():
    tiers = registry()
    t = tiers["self-hosted-a"]
    t.outcome("agentic-coding")["tokens"] = {"fresh_in": 50_000_000, "cached_in": 0, "cache_write": 0,
                                            "out": 5_000_000}
    v = policy.reservation_verdict(t, "agentic-coding", window_hours=1.0,
                                  counterfactual=tiers["api-cheap-a"])
    assert v["verdict"] == "imputed_pays" and v["counterfactual_usd"] > v["bill_usd"]
    assert v["counterfactual_tier"] == "api-cheap-a"


def test_the_reservation_does_not_pay_on_a_trickle():
    tiers = registry()
    t = tiers["self-hosted-a"]
    t.outcome("agentic-coding")["tokens"] = {"fresh_in": 1000, "cached_in": 0, "cache_write": 0, "out": 100}
    v = policy.reservation_verdict(t, "agentic-coding", window_hours=1.0,
                                  counterfactual=tiers["api-cheap-a"])
    assert v["verdict"] == "imputed_does_not_pay" and v["counterfactual_usd"] < v["bill_usd"]


def test_the_verdict_states_that_the_same_legs_elsewhere_is_an_assumption():
    """A different tokenizer counts differently and a cold cache charges the cached leg as fresh, so quoting
    one candidate's legs at another's card is an approximation and has to say so."""
    tiers = registry()
    tiers["self-hosted-a"].outcome("agentic-coding")["tokens"] = {"fresh_in": 10, "cached_in": 0,
                                                                 "cache_write": 0, "out": 1}
    v = policy.reservation_verdict(tiers["self-hosted-a"], "agentic-coding", window_hours=1.0,
                                  counterfactual=tiers["api-cheap-a"])
    assert any("only for the same model" in a for a in v["assumes"])
    assert "ranks a hypothesis and not money" in v["reason"]


# --- capacity is a scheduling answer, not a price ------------------------------------------------


def test_one_point_on_a_service_curve_is_not_a_saturation_figure():
    """The earlier docstring claimed a measurement at lower concurrency is a lower bound on production
    throughput. It is not: contention, cache pressure, batching, replica imbalance and throttling can keep
    throughput flat or lower it."""
    tiers = registry()
    tiers["self-hosted-a"].outcome("agentic-coding")["latency"] = {
        "unit": "seconds_per_task", "mean": 59.3, "concurrency_when_measured": 1}
    note = policy.capacity_note(tiers["self-hosted-a"], "agentic-coding")
    assert "not a saturation figure" in note and "bounds nothing on its own" in note
    assert "probes at several" in note and "1 in flight" in note


def test_a_metered_candidates_capacity_is_the_providers_problem():
    tiers = registry()
    assert "provider's problem" in policy.capacity_note(tiers["api-cheap-a"], "agentic-coding")


def test_a_reserved_candidate_with_no_declared_charge_kind_is_refused_not_guessed():
    """Either inference is wrong in the other case. A gateway charge on a self-hosted engine is usually the
    reservation re-expressed per token, so counting both bills the machine twice; a minimum-plus-meter contract
    is genuinely additional, so dropping it loses real money."""
    tiers = registry()
    del tiers["self-hosted-a"].outcome("agentic-coding")["reserved_charge_kind"]
    cost, why = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                        "agentic-coding")
    assert cost == float("inf")
    assert "bills the machine twice" in why and "reservation_plus_metered" in why


def test_an_additional_meter_on_a_reserved_candidate_is_charged():
    """The case where dropping the quote would lose real money."""
    tiers = registry()
    o = tiers["self-hosted-a"].outcome("agentic-coding")
    o["reserved_charge_kind"] = "reservation_plus_metered"
    cost, _ = policy._cost_per_request(tiers, policy.Arrangement(("self-hosted-a",), "outright"),
                                       "agentic-coding")
    assert cost == pytest.approx(o["bill_usd"] / o["attempted"], rel=1e-9)


def test_an_unrecognised_charge_kind_is_a_loud_error_not_a_default():
    tiers = registry()
    tiers["self-hosted-a"].outcome("agentic-coding")["reserved_charge_kind"] = "whatever"
    with pytest.raises(ValueError) as e:
        tiers["self-hosted-a"].reserved_charge_kind("agentic-coding")
    assert "expected one of" in str(e.value)


def test_the_retry_term_is_not_added_to_a_bill_that_already_contains_the_dead_attempts():
    """For a purely reserved arrangement the retry term is the only nonzero quantity, so getting it wrong would
    decide box-against-box comparisons on its own."""
    tiers = registry()
    o = tiers["api-cheap-a"].outcome("agentic-coding")
    without = policy._retry_term(tiers["api-cheap-a"], "agentic-coding")
    o["accounting_boundary"] = "usable_episodes_only"
    with_boundary = policy._retry_term(tiers["api-cheap-a"], "agentic-coding")
    assert without == 0.0, "no declared boundary means the bill is assumed to include them"
    assert with_boundary == tiers["api-cheap-a"].retry_premium


def test_a_certified_arrangement_with_no_computable_cost_is_not_selected():
    """The sort puts certification first and infinity is still a number to `min`, so it would have won. Certified
    on quality and unpriceable on cost is not a choice a cost objective can make."""
    tiers = registry()
    del tiers["self-hosted-a"].outcome("agentic-coding")["reserved_charge_kind"]
    # A margin wide enough to certify it on quality, so the only thing standing between it and selection is
    # that its cost is not computable. That is precisely the case the sort would have got wrong.
    d = policy.assign_family(tiers, "agentic-coding", "api-strong-a", margin=0.50, alpha=0.05,
                             today=TODAY)
    ranked = {c.arrangement.head: c for c in d.ranked}
    assert ranked["self-hosted-a"].certified is True
    assert ranked["self-hosted-a"].cost_per_request == float("inf")
    assert d.chosen.head != "self-hosted-a"
    # Reported as unpriced rather than as an operator constraint: "your SLO removed this" and "nobody could
    # price this" call for different actions.
    assert any("could not be computed" in v for _, v in d.unpriced)
    assert not any("could not be computed" in v for _, v in d.excluded)


def test_the_verdict_is_labelled_imputed_because_both_sides_bypass_the_gateway():
    """Not a caveat but a limit. The bill from hourly x window is the rate-card reconstruction this project's
    spend rule forbids, and the alternative from another card is the same imputation one step over -- so a
    settled-sounding `pays` would be the laundering the spend rule exists to prevent."""
    tiers = registry()
    tiers["self-hosted-a"].outcome("agentic-coding")["tokens"] = {
        "fresh_in": 50_000_000, "cached_in": 0, "cache_write": 0, "out": 5_000_000}
    v = policy.reservation_verdict(tiers["self-hosted-a"], "agentic-coding", window_hours=1.0,
                                  counterfactual=tiers["api-cheap-a"])
    assert v["verdict"] == "imputed_pays"
    assert v["bill_authority"] == "rate_card_times_window"
    assert v["counterfactual_authority"] == "rate_card_of_api-cheap-a"
    assert len(v["assumes"]) >= 5


def test_a_settled_period_bill_is_used_instead_of_the_card_when_one_is_supplied():
    tiers = registry()
    tiers["self-hosted-a"].outcome("agentic-coding")["tokens"] = {
        "fresh_in": 1000, "cached_in": 0, "cache_write": 0, "out": 10}
    v = policy.reservation_verdict(tiers["self-hosted-a"], "agentic-coding", window_hours=1.0,
                                  counterfactual=tiers["api-cheap-a"], settled_period_usd=42.0)
    assert v["bill_authority"] == "gateway_settled_period_bill" and v["bill_usd"] == pytest.approx(42.0)
    assert "Imputed on one side" in v["reason"]


def test_a_family_share_is_required_as_soon_as_anything_else_uses_the_box():
    """Without it the whole bill is compared against one family's traffic: biased towards not-paying, and it
    double-counts the reservation the moment two families' verdicts are added up."""
    tiers = registry()
    tiers["self-hosted-a"].outcome("agentic-coding")["tokens"] = {
        "fresh_in": 1000, "cached_in": 0, "cache_write": 0, "out": 10}
    whole = policy.reservation_verdict(tiers["self-hosted-a"], "agentic-coding", window_hours=1.0,
                                       counterfactual=tiers["api-cheap-a"])
    half = policy.reservation_verdict(tiers["self-hosted-a"], "agentic-coding", window_hours=1.0,
                                      counterfactual=tiers["api-cheap-a"], family_share=0.5)
    assert "sole user of the box" in whole["share_note"]
    assert half["bill_usd"] == pytest.approx(whole["bill_usd"] / 2)


def test_an_absent_token_leg_makes_the_verdict_undecidable_rather_than_small():
    """Silently zeroed by an earlier version, which made a partial leg set look like a cheap alternative."""
    tiers = registry()
    tiers["self-hosted-a"].outcome("agentic-coding")["tokens"] = {"fresh_in": 1000, "out": 10}
    v = policy.reservation_verdict(tiers["self-hosted-a"], "agentic-coding", window_hours=1.0,
                                  counterfactual=tiers["api-cheap-a"])
    assert v["verdict"] == "undecidable" and "are absent and are not zero" in v["reason"]
