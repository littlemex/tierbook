"""Tests for the acceptance criteria.

The design under test is the third verdict. A checker with only pass and fail must choose between reporting a pass it
did not earn and a failure it cannot substantiate, so `unsupported` names the missing measurement instead -- and these
tests pin that it is used where it should be and NOT used where a criterion really was evaluated.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import accept as ac  # noqa: E402
from tierbook import record as rec  # noqa: E402


def cand(cid="box", why="chosen", bound=0.90, cost=0.004):
    return {"id": cid, "excluded_because": why, "bound": bound, "bound_kind": "lcb95", "cost_usd": cost,
            "evidence_as_of": "2026-09-01"}


def dec(rid="r1", certified=True, chosen="box", candidates=None, exploration=False, prob=1.0):
    return {
        "family": "agentic-coding", "request_id": rid, "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": candidates or [cand(), cand("api", "below_floor", 0.70, 0.012)], "chosen": chosen,
        "selection_probability": prob, "exploration": exploration, "certified": certified,
        "policy_version": "p1", "mechanism_version": "0.1.0", "agent": "opencode", "model": "m",
        "endpoint": "http://e", "gateway_quote_usd": 0.004, "gateway_authorised": True, "decided_at": 1000.0,
        "gaps": [], "label_state": "pending", "label": None, "outcome": {},
    }


def test_every_criterion_scope_names_gets_a_verdict():
    got = ac.check_all([dec()], {}, floor=0.80)
    assert [v.criterion for v in got] == list(ac.CRITERIA)


def test_the_falsifier_is_computable_from_one_decision():
    """It needs only the candidate set and the floor, both of which every record carries."""
    v = ac.no_false_certification([dec()], floor=0.80, latency_feasible=True)
    assert v.verdict == ac.PASS


def test_a_certified_decision_below_the_floor_fails_the_falsifier():
    rows = [dec(candidates=[cand("box", "chosen", 0.70), cand("api", "below_floor", 0.60)])]
    v = ac.no_false_certification(rows, floor=0.80, latency_feasible=True)
    assert v.verdict == ac.FAIL
    assert "broken rather than mistuned" in v.detail
    assert v.numbers["violations"] == 1


def test_an_empty_log_is_unsupported_rather_than_a_pass():
    """Zero violations over zero decisions is not a property of the mechanism."""
    assert ac.no_false_certification([], floor=0.80, latency_feasible=True).verdict == ac.UNSUPPORTED


def test_the_default_used_while_something_admissible_existed_fails_its_own_criterion():
    rows = [dec(chosen="fallback", certified=False,
                candidates=[cand("fallback", "chosen", 0.50), cand("box", "not_priced", 0.95)])]
    v = ac.default_is_not_a_hiding_place(rows, floor=0.80, latency_feasible=True)
    assert v.verdict == ac.FAIL and "hiding place" in v.detail


def test_that_violation_is_not_double_counted_as_a_false_certification():
    """They are opposite errors and section 12 lists them as separate criteria."""
    rows = [dec(chosen="fallback", certified=False,
                candidates=[cand("fallback", "chosen", 0.50), cand("box", "not_priced", 0.95)])]
    assert ac.no_false_certification(rows, floor=0.80, latency_feasible=True).verdict == ac.PASS


def test_the_uncertified_share_needs_a_declared_tolerance():
    """Inventing the tolerance would be grading our own work."""
    rows = [dec(rid="r1"), dec(rid="r2", certified=False, chosen="box")]
    v = ac.default_is_not_a_hiding_place(rows, floor=0.80, latency_feasible=True)
    assert v.verdict == ac.UNSUPPORTED and "no tolerance was declared" in v.detail
    assert v.numbers["uncertified_share"] == 0.5
    v = ac.default_is_not_a_hiding_place(rows, floor=0.80, latency_feasible=True, uncertified_tolerance=0.1)
    assert v.verdict == ac.FAIL
    v = ac.default_is_not_a_hiding_place(rows, floor=0.80, latency_feasible=True, uncertified_tolerance=0.9)
    assert v.verdict == ac.PASS


# --- floor compliance, and the two ways it must not flatter itself ----------------------------------


def test_an_unlabelled_certified_decision_does_not_count_as_a_failure():
    """A missing label read as a failure moves the rate in the direction that flatters the floor, which is why
    section 9 requires label-missingness to be explicit."""
    rows = [dec(rid=f"r{i}") for i in range(20)]
    v = ac.floor_compliance(rows, {}, floor=0.80)
    assert v.verdict == ac.UNSUPPORTED
    assert v.numbers["unlabelled_certified"] == 20 and v.numbers["labelled"] == 0


def test_uncertified_decisions_are_not_in_the_denominator():
    """The floor is claimed for certified assignments and disclaimed for the rest."""
    rows = [dec(rid="r1"), dec(rid="r2", certified=False)]
    outcomes = {"r1": {"label_state": "labelled", "label": True},
                "r2": {"label_state": "labelled", "label": False}}
    v = ac.floor_compliance(rows, outcomes, floor=0.80)
    assert v.numbers["labelled"] == 1 and v.numbers["successes"] == 1


def test_a_rate_far_below_the_floor_fails():
    rows = [dec(rid=f"r{i}") for i in range(40)]
    outcomes = {f"r{i}": {"label_state": "labelled", "label": i < 10} for i in range(40)}
    v = ac.floor_compliance(rows, outcomes, floor=0.80)
    assert v.verdict == ac.FAIL and v.numbers["rate"] == 0.25


def test_a_compliant_rate_over_enough_labels_passes():
    rows = [dec(rid=f"r{i}") for i in range(40)]
    outcomes = {f"r{i}": {"label_state": "labelled", "label": i < 36} for i in range(40)}
    v = ac.floor_compliance(rows, outcomes, floor=0.80)
    assert v.verdict == ac.PASS and v.numbers["rate"] == 0.9


def test_a_small_sample_is_unsupported_even_when_the_rate_looks_fine():
    """The number is reported so it is not mistaken for a pass."""
    rows = [dec(rid=f"r{i}") for i in range(5)]
    outcomes = {f"r{i}": {"label_state": "labelled", "label": True} for i in range(5)}
    v = ac.floor_compliance(rows, outcomes, floor=0.80)
    assert v.verdict == ac.UNSUPPORTED and v.numbers["rate"] == 1.0
    assert "cannot separate compliance from sampling error" in v.detail


# --- exploration and the SLO ------------------------------------------------------------------------


def test_exploration_share_needs_a_budget():
    rows = [dec(rid="r1", exploration=True), dec(rid="r2")]
    assert ac.exploration_cost(rows).verdict == ac.UNSUPPORTED
    assert ac.exploration_cost(rows, budgeted_share=0.1).verdict == ac.FAIL
    assert ac.exploration_cost(rows, budgeted_share=0.6).verdict == ac.PASS


def test_the_slo_applies_only_where_an_operator_imposed_one():
    """SCOPE section 1: performance is not what is being optimised and its treatment is explicitly unsettled."""
    v = ac.slo([dec()], {"r1": {"latency_s": 10.0}})
    assert v.verdict == ac.UNSUPPORTED and "explicitly unsettled" in v.detail


def test_a_declared_slo_is_evaluated():
    rows = [dec(rid=f"r{i}") for i in range(10)]
    outcomes = {f"r{i}": {"latency_s": 5.0 if i < 9 else 100.0} for i in range(10)}
    assert ac.slo(rows, outcomes, latency_limit_s=60.0, tolerance=0.05).verdict == ac.FAIL
    assert ac.slo(rows, outcomes, latency_limit_s=60.0, tolerance=0.2).verdict == ac.PASS


def test_a_declared_slo_with_no_recorded_latency_is_unsupported():
    v = ac.slo([dec()], {}, latency_limit_s=60.0, tolerance=0.05)
    assert v.verdict == ac.UNSUPPORTED and "no latency was recorded" in v.detail


# --- the three that a log cannot contain, each saying what it needs ---------------------------------


def test_the_three_experimental_criteria_name_what_they_need_individually():
    """A reader told 'insufficient data' learns nothing about what to collect."""
    got = {v.criterion: v for v in ac.check_all([dec()], {}, floor=0.80)}
    for name, phrase in (("bound_calibration", "where the estimand is known"),
                         ("spend_regret", "propensity 1"),
                         ("adaptation", "WITHOUT a code change"),
                         ("genericity_and_usefulness", "held-out environment")):
        assert got[name].verdict == ac.UNSUPPORTED
        assert phrase in got[name].detail, name
    assert len({got[n].detail for n in ("bound_calibration", "spend_regret", "adaptation")}) == 3


def test_the_summary_refuses_to_reduce_to_accepted():
    got = ac.check_all([dec()], {}, floor=0.80)
    s = ac.summarise(got)
    assert s["evaluated"] < s["of"]
    assert "accepted" not in s
    assert s["any_failure"] is False
    assert "neither a pass nor a failure" in s["note"]


def test_a_failure_anywhere_shows_in_the_summary():
    rows = [dec(candidates=[cand("box", "chosen", 0.10), cand("api", "below_floor", 0.05)])]
    s = ac.summarise(ac.check_all(rows, {}, floor=0.80))
    assert s["any_failure"] is True and s["counts"][ac.FAIL] >= 1


def test_a_verdict_serialises():
    import json

    json.dumps([v.as_dict() for v in ac.check_all([dec()], {}, floor=0.80)])


def test_the_checker_reads_what_the_log_writes(tmp_path):
    """End to end against the real record, so a field rename breaks a test rather than a criterion."""
    log = rec.Log(tmp_path / "log.jsonl")
    log.append(rec.Decision(
        family="f", request_id="r1", feature_vector_version="fv1", state_ref="obs:a",
        candidates=[rec.Candidate(id="box", excluded_because="chosen", bound=0.9, cost_usd=0.004),
                    rec.Candidate(id="api", excluded_because="below_floor", bound=0.7, cost_usd=0.012)],
        chosen="box", selection_probability=1.0, exploration=False, certified=True, policy_version="p1",
        mechanism_version="0.1.0", agent="opencode", model="m", endpoint="http://e",
        gateway_quote_usd=0.004, gateway_authorised=True))
    log.attach_outcome("r1", label_state="labelled", label=True, latency_s=30.0)
    decisions, outcomes = log.read()
    got = {v.criterion: v for v in ac.check_all(decisions, outcomes, floor=0.80)}
    assert got["no_false_certification"].verdict == ac.PASS
    assert got["floor_compliance"].numbers["labelled"] == 1
