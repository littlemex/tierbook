"""Tests for the state collector.

The rule under test throughout: a variable that could not be read is ABSENT, never defaulted. A fabricated zero for
`inflight` reads as an idle engine and sends the next request to the reserved candidate, so the one value a collector
must not guess is the one a naive implementation defaults.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import observe as ob  # noqa: E402
from tierbook.decide import STATE_VARS  # noqa: E402

MODEL = "Qwen/Qwen3.6-35B-A3B"

# Cut from the live engine, including the label set it really exports.
METRICS = f"""# HELP vllm:num_requests_running Number of requests in model execution batches.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{{engine="0",model_name="{MODEL}"}} 3.0
vllm:num_requests_waiting{{engine="0",model_name="{MODEL}"}} 2.0
vllm:num_requests_waiting_by_reason{{engine="0",model_name="{MODEL}",reason="capacity"}} 2.0
vllm:request_success_total{{engine="0",finished_reason="stop",model_name="{MODEL}"}} 100.0
vllm:request_success_total{{engine="0",finished_reason="length",model_name="{MODEL}"}} 5.0
"""


def test_a_metric_is_read_with_its_labels():
    got = ob.parse_metrics(METRICS, ob.RUNNING)
    assert got == [({"engine": "0", "model_name": MODEL}, 3.0)]


def test_another_models_series_is_not_counted_as_this_ones():
    """A vLLM engine exports one series per model_name, and summing across them reports another candidate's
    occupancy as this one's."""
    two = METRICS + f'vllm:num_requests_running{{engine="0",model_name="other"}} 9.0\n'
    assert ob.inflight(two, MODEL) == 5.0
    # And the other model has a `running` series but no `waiting` one, so its occupancy is unknown rather than 9:
    # half a reading is not a reading, and this is the refusal that keeps it from becoming one.
    with pytest.raises(ob.NotObserved, match="absent"):
        ob.inflight(two, "other")


def test_inflight_counts_waiting_as_well_as_running():
    """`waiting` above zero means the seats are already full. Counting only `running` reports a saturated engine as
    having room."""
    assert ob.inflight(METRICS, MODEL) == 5.0


def test_a_missing_metric_refuses_rather_than_returning_zero():
    with pytest.raises(ob.NotObserved, match="absent"):
        ob.inflight("# nothing here\n", MODEL)


def test_a_comment_or_a_nan_does_not_become_a_value():
    """NaN parses as a float and then poisons every comparison: `inflight >= B` is false for NaN, so a saturated
    engine with one broken series would read as having room."""
    assert ob.parse_metrics("# vllm:num_requests_running 5.0", ob.RUNNING) == []
    assert ob.parse_metrics(f'vllm:num_requests_running{{model_name="{MODEL}"}} NaN', ob.RUNNING) == []
    with pytest.raises(ob.NotObserved, match="absent"):
        ob.inflight(f'vllm:num_requests_running{{model_name="{MODEL}"}} NaN', MODEL)


# --- a rate is a derivative, and one sample is not one ---------------------------------------------


def test_a_rate_needs_two_readings():
    assert ob.arrival_rate_per_hour((100.0, 0.0), (105.0, 3600.0)) == pytest.approx(5.0)
    assert ob.arrival_rate_per_hour((0.0, 0.0), (1.0, 60.0)) == pytest.approx(60.0)


def test_a_zero_interval_refuses():
    with pytest.raises(ob.NotObserved, match="apart"):
        ob.arrival_rate_per_hour((100.0, 10.0), (105.0, 10.0))


def test_a_counter_going_backwards_is_a_restart_not_a_negative_rate():
    with pytest.raises(ob.NotObserved, match="restart"):
        ob.arrival_rate_per_hour((100.0, 0.0), (5.0, 60.0))


def test_evidence_age_comes_from_the_policys_own_date():
    day = 86400.0
    # 2026-09-01 00:00 UTC plus ten days.
    at = 1788220800.0 + 10 * day
    assert ob.evidence_age_days("2026-09-01", at) == pytest.approx(10.0, abs=0.01)


def test_a_policy_with_no_usable_date_has_no_age():
    for bad in (None, "", "yesterday", "2026-13-40"):
        with pytest.raises(ob.NotObserved, match="ISO date"):
            ob.evidence_age_days(bad, 1788220800.0)


# --- the whole observation, and what it refuses to invent -------------------------------------------


def test_a_complete_observation_carries_every_state_variable():
    first = ob.observe(metrics_url="http://x/metrics", model_name=MODEL, gateway_authorised=True,
                       measured_on="2026-09-01", now=1000.0, fetcher=lambda url, timeout=5.0: METRICS)
    later = METRICS.replace("100.0", "160.0")
    got = ob.observe(metrics_url="http://x/metrics", model_name=MODEL, gateway_authorised=True,
                     measured_on="2026-09-01", now=4600.0, previous=first.as_dict()["readings"],
                     fetcher=lambda url, timeout=5.0: later)
    assert set(got.state) == set(STATE_VARS), set(STATE_VARS) - set(got.state)
    assert got.complete is True and got.not_observed == {}
    assert got.state["inflight"] == 5.0
    assert got.state["arrival_rate_per_hour"] == pytest.approx(60.0)


def test_the_first_call_cannot_give_a_rate_and_says_so():
    got = ob.observe(metrics_url="http://x/metrics", model_name=MODEL, gateway_authorised=True,
                     measured_on="2026-09-01", now=1000.0, fetcher=lambda url, timeout=5.0: METRICS)
    assert "arrival_rate_per_hour" not in got.state
    assert "difference of two counter readings" in got.not_observed["arrival_rate_per_hour"]
    assert got.complete is False


def test_an_unreachable_endpoint_observes_unavailable_and_nothing_else():
    """The one thing a failed fetch does establish. Concluding an `inflight` of zero from it would send the next
    request to a candidate that is not serving."""
    def boom(url, timeout=5.0):
        raise ob.NotObserved("http://x/metrics did not answer: URLError: refused")

    got = ob.observe(metrics_url="http://x/metrics", model_name=MODEL, gateway_authorised=True,
                     measured_on="2026-09-01", now=1000.0, fetcher=boom)
    assert got.state["available"] is False
    assert "inflight" not in got.state
    assert "did not answer" in got.not_observed["inflight"]


def test_authorisation_is_not_inferred_from_reachability():
    got = ob.observe(metrics_url="http://x/metrics", model_name=MODEL, measured_on="2026-09-01",
                     now=1000.0, fetcher=lambda url, timeout=5.0: METRICS)
    assert "metered_authorised" not in got.state
    assert "budget and a tenant" in got.not_observed["metered_authorised"]


def test_with_no_metrics_url_nothing_about_the_engine_is_claimed():
    got = ob.observe(gateway_authorised=False, measured_on="2026-09-01", now=1000.0)
    assert set(got.state) == {"metered_authorised", "evidence_age_days"}
    for var in ("available", "inflight", "arrival_rate_per_hour"):
        assert var in got.not_observed


def test_the_spread_between_readings_is_reported():
    """A state assembled over minutes is not a state, and a caller cannot see that from the values."""
    got = ob.observe(gateway_authorised=True, measured_on="2026-09-01", now=1000.0)
    assert got.spread_s == 0.0
    assert ob.Observation().spread_s is None


def test_an_observation_serialises_to_something_a_record_can_hold():
    got = ob.observe(gateway_authorised=True, measured_on="2026-09-01", now=1000.0)
    d = got.as_dict()
    assert set(d) == {"state", "readings", "not_observed", "spread_s", "complete"}
    import json

    json.dumps(d)


def test_an_absent_variable_makes_decide_report_a_gap_rather_than_certifying():
    """The contract between this module and `decide`: absence is reported there as `uncollected_variable`, which is
    why absence here is safe and a default would not be."""
    from tierbook.decide import GAP_REASONS

    assert "uncollected_variable" in GAP_REASONS


# --- the keys `decide` actually reads ----------------------------------------------------------------


def test_a_candidates_quantities_are_qualified_by_its_name():
    """`decide`'s guards read `inflight:box`, not `inflight`. A bare key produces a state no guard matches, so every
    rule reports `uncollected_variable` and every request takes the default while the metrics endpoint answers
    perfectly."""
    got = ob.observe(candidate="box", metrics_url="http://x/metrics", model_name=MODEL,
                     gateway_authorised=True, measured_on="2026-09-01", now=1000.0,
                     fetcher=lambda url, timeout=5.0: METRICS)
    assert got.state["inflight:box"] == 5.0
    assert got.state["available:box"] is True
    assert "inflight" not in got.state


def test_the_familys_quantities_are_not_qualified():
    """One arrival rate, one authorisation and one evidence age belong to the family, not to a candidate."""
    got = ob.observe(candidate="box", gateway_authorised=True, measured_on="2026-09-01", now=1000.0)
    assert "metered_authorised" in got.state and "evidence_age_days" in got.state
    assert not any(k.endswith(":box") for k in got.state)


def test_a_refusal_is_qualified_the_same_way_as_a_reading():
    """Otherwise a caller cannot tell which candidate's occupancy was not observed."""
    got = ob.observe(candidate="box", gateway_authorised=True, measured_on="2026-09-01", now=1000.0)
    assert "inflight:box" in got.not_observed and "available:box" in got.not_observed


def test_completeness_is_judged_against_the_qualified_names():
    first = ob.observe(candidate="box", metrics_url="http://x/metrics", model_name=MODEL,
                       gateway_authorised=True, measured_on="2026-09-01", now=1000.0,
                       fetcher=lambda url, timeout=5.0: METRICS)
    later = METRICS.replace("100.0", "160.0")
    got = ob.observe(candidate="box", metrics_url="http://x/metrics", model_name=MODEL,
                     gateway_authorised=True, measured_on="2026-09-01", now=4600.0,
                     previous=first.as_dict()["readings"], fetcher=lambda url, timeout=5.0: later)
    assert got.expected == {"inflight:box", "available:box", "metered_authorised",
                            "arrival_rate_per_hour", "evidence_age_days"}
    assert got.complete is True, got.not_observed


def test_the_collector_and_the_decider_agree_on_the_key_names():
    """The integration test that caught the mismatch. Neither module read wrong on its own."""
    from tierbook import decide as dc

    got = ob.observe(candidate="box", metrics_url="http://x/metrics", model_name=MODEL,
                     gateway_authorised=True, measured_on="2026-09-01", now=1000.0,
                     fetcher=lambda url, timeout=5.0: METRICS)
    guard = dc.Guard(var="inflight:box", op="<", threshold=8.0, derived_from="a fixture")
    fired, why = guard.evaluate(got.state)
    assert why is None, f"the guard could not read the collector's state: {why}"
    assert fired is True
