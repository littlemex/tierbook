"""The decisions that would produce a plausible wrong number if they were wrong.

Every expected value here is a figure measured in the record cited by the tier files, so a change that
breaks the arithmetic breaks a test rather than a report.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "routing"))
import policy  # noqa: E402


def registry():
    return policy.load_registry(ROOT / "registry" / "tiers")


# --- the ledger reads back ----------------------------------------------------------------------


def test_the_three_measured_tiers_load():
    tiers = registry()
    assert set(tiers) == {"self-hosted-a", "api-cheap-a", "api-strong-a"}


def test_per_solved_task_matches_the_record():
    tiers = registry()
    expected = {"self-hosted-a": 0.0643, "api-cheap-a": 0.1847, "api-strong-a": 0.7295}
    for tid, want in expected.items():
        o = tiers[tid].outcome("agentic-coding")
        assert round(o["bill_usd"] / o["solved"], 4) == want


def test_a_tier_that_does_not_report_cached_tokens_is_charged_as_fresh():
    # Unmeasured is not free. Coercing a null cached rate to zero is how a tier with invisible cache
    # economics comes out looking cheapest.
    tiers = registry()
    t = tiers["api-cheap-a"]
    with_cache = t.token_cost(fresh_in=1_000_000, cached_in=1_000_000, out=0)
    assert round(with_cache, 4) == round(2.20 + 0.22, 4)

    blind = policy.Tier("blind", {**t.record, "price_card": {**t.record["price_card"], "cached_in": None}})
    assert round(blind.token_cost(fresh_in=1_000_000, cached_in=1_000_000, out=0), 4) == round(2.20 * 2, 4)


# --- reliability is a cost, not a footnote ------------------------------------------------------


def test_the_retry_premium_reproduces_the_measured_figure():
    # 4 failures in 24 attempts, mean $4.4212 sunk before death -> $0.8842 per attempted call.
    tiers = registry()
    assert round(tiers["api-strong-a"].retry_premium, 4) == 0.8842
    assert tiers["api-cheap-a"].retry_premium == 0.0


def test_a_tier_with_no_observed_failures_carries_no_premium():
    tiers = registry()
    assert tiers["self-hosted-a"].retry_premium == 0.0


# --- the fixed-cost switch ----------------------------------------------------------------------


def test_an_idle_fixed_cost_tier_is_infinitely_expensive():
    tiers = registry()
    assert tiers["self-hosted-a"].amortised_cost_per_task(None) == float("inf")
    assert tiers["api-cheap-a"].amortised_cost_per_task(None) == 0.0


def test_the_break_even_volume_is_where_the_record_put_it():
    # $15.2174/h against a 4.8 cent per task oracle saving is 319 tasks an hour.
    tiers = registry()
    box = tiers["self-hosted-a"]
    assert round(box.amortised_cost_per_task(319), 4) == 0.0477
    assert box.amortised_cost_per_task(616) < box.amortised_cost_per_task(319)


# --- the offline assignment ---------------------------------------------------------------------


def test_without_a_verifier_the_admitted_tier_is_assigned_outright_not_chained():
    # Parity was measured offline, so the tier is used; but escalation can only fire on observable
    # failure, which says nothing about a plausible-but-wrong artifact.
    tiers = registry()
    a = policy.assign(tiers, "agentic-coding", "api-strong-a",
                      margin=0.25, realised_tasks_per_hour=616, verifier_available=False)
    assert a.assigned == "api-cheap-a"
    assert a.chain == ("api-cheap-a", "api-strong-a")
    assert "observable failure" in a.why


def test_the_self_hosted_tier_needs_a_thirty_point_margin_to_qualify_at_all():
    """The rule rejects the box for a reason the cost analysis never produced.

    It solves 14 of 20 against the reference's 20 of 20, so admitting it requires a non-inferiority
    margin of 0.30 -- thirty percentage points of solve rate. Nobody pre-registers a margin that loose.
    At 0.25 it is not admitted whatever it costs, and the cheap API is assigned instead. This is an
    argument against the box that arrives from the decision rule rather than from its economics.
    """
    tiers = registry()
    for margin, expected in ((0.20, "api-cheap-a"), (0.25, "api-cheap-a"), (0.30, "self-hosted-a")):
        a = policy.assign(tiers, "agentic-coding", "api-strong-a",
                          margin=margin, realised_tasks_per_hour=616)
        assert a.assigned == expected, (margin, a.assigned)


def test_an_idle_fixed_cost_tier_loses_to_the_api():
    # At a margin loose enough to admit the box, an idle machine still loses: its amortised cost is
    # unbounded, which is the switch that keeps a rented GPU out of the assignment when nothing is
    # keeping it busy.
    tiers = registry()
    a = policy.assign(tiers, "agentic-coding", "api-strong-a",
                      margin=0.30, realised_tasks_per_hour=None, verifier_available=False)
    assert a.assigned == "api-cheap-a"


def test_a_tight_margin_keeps_the_reference():
    # The box solves 14/20 against the reference's 20/20, so a 5-point margin admits nobody.
    tiers = registry()
    a = policy.assign(tiers, "agentic-coding", "api-strong-a", margin=0.05,
                      realised_tasks_per_hour=616)
    assert a.assigned == "api-strong-a"
    assert "within the margin" in a.why


def test_a_counterexample_withdraws_the_chain_assumption_for_that_family():
    # A tier that solves something the reference does not is not "cheaper and sufficient" -- the tiers
    # are not a chain for that family, and cheapest-sufficient is undefined until that case is designed for.
    tiers = registry()
    rec = {**tiers["self-hosted-a"].record}
    fam = {**rec["families"]["agentic-coding"], "counterexamples": 1}
    rec["families"] = {"agentic-coding": fam}
    tiers["self-hosted-a"] = policy.Tier("self-hosted-a", rec)
    a = policy.assign(tiers, "agentic-coding", "api-strong-a", margin=0.30,
                      realised_tasks_per_hour=616)
    assert a.assigned != "self-hosted-a"


def test_eligibility_is_checked_before_any_cost_arithmetic():
    tiers = registry()
    a = policy.assign(tiers, "agentic-coding", "api-strong-a", margin=0.25,
                      realised_tasks_per_hour=616,
                      need={"modalities": ["audio"]})
    assert a.assigned == "api-strong-a"


def test_a_verifier_justifies_a_chain_and_orders_it_by_loaded_cost():
    tiers = registry()
    # At a margin loose enough to admit both cheap tiers, the chain leads with the cheapest loaded cost.
    a = policy.assign(tiers, "agentic-coding", "api-strong-a", margin=0.30,
                      realised_tasks_per_hour=616, verifier_available=True)
    assert a.chain[0] == "self-hosted-a"
    assert a.chain[-1] == "api-strong-a"
    assert "acceptance check" in a.why


# --- the online path has no cleverness in it ----------------------------------------------------


def test_an_artifact_is_shipped_and_never_second_guessed():
    assert policy.should_escalate("ok", artifact=True) is False
    # A doubtful-looking artifact is still shipped: no signal that reads an artifact has cleared the bar.
    assert policy.should_escalate("suspicious", artifact=True) is False


def test_escalation_fires_on_every_observable_failure_and_nothing_else():
    for outcome in policy.OBSERVABLE_FAILURES:
        assert policy.should_escalate(outcome, artifact=False) is True
    assert policy.should_escalate("model_said_it_was_unsure", artifact=False) is False


def test_an_empty_stream_escalates_even_though_it_arrived_as_a_success():
    assert policy.should_escalate("empty_stream", artifact=False) is True


def test_a_run_stops_at_the_first_attempt_that_produced_an_artifact():
    calls = []

    def execute(tier_id):
        calls.append(tier_id)
        if tier_id == "self-hosted-a":
            return policy.Attempt(tier_id, "empty_stream", billed_usd=0.05, artifact=False)
        return policy.Attempt(tier_id, "ok", billed_usd=0.70, artifact=True)

    ep = policy.run(("self-hosted-a", "api-strong-a"), execute)
    assert calls == ["self-hosted-a", "api-strong-a"]
    assert ep.shipped is True
    # The failed attempt is billed and stays in the total: a ledger that dropped it would rank
    # arrangements wrong, which is exactly what happened on the record.
    assert round(ep.billed_usd, 2) == 0.75
