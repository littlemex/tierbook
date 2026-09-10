"""Tests for the decision record.

Every refusal here exists because the alternative is a log that looks complete and turns out not to identify the
estimate somebody wants from it -- a failure that arrives after the data is already collected.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import record as rec  # noqa: E402


def cand(cid="box", why="chosen", bound=0.82, cost=0.004):
    return rec.Candidate(id=cid, excluded_because=why, bound=bound, bound_kind="lcb95", cost_usd=cost,
                         evidence_as_of="2026-09-01")


def decision(**kw):
    base = dict(
        family="agentic-coding", request_id="r1", feature_vector_version="fv1", state_ref="obs:abc",
        candidates=[cand(), cand("api", "below_floor", 0.70, 0.012)], chosen="box",
        selection_probability=1.0, exploration=False, certified=True, policy_version="p1",
        mechanism_version="0.1.0", agent="opencode", model="Qwen/Qwen3.6-35B-A3B",
        endpoint="http://vllm:8000", gateway_quote_usd=0.004, gateway_authorised=True, decided_at=1000.0)
    base.update(kw)
    return rec.Decision(**base)


def test_a_complete_decision_is_accepted_and_serialises():
    d = decision()
    json.dumps(d.as_dict())
    assert d.as_dict()["chosen"] == "box"


def test_a_missing_propensity_is_refused_at_write_time():
    """Section 9's off-policy requirement. A propensity cannot be reconstructed afterwards from a deterministic
    policy: it is 1 for what was chosen and the counterfactual arm has no data at all."""
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(rec.Incomplete, match="selection_probability"):
            decision(selection_probability=bad)


def test_an_open_ended_exclusion_reason_is_refused():
    with pytest.raises(rec.Incomplete, match="cannot be aggregated"):
        rec.Candidate(id="x", excluded_because="it seemed expensive")


def test_the_chosen_candidate_must_be_in_the_set():
    with pytest.raises(rec.Incomplete, match="not in the candidate set"):
        decision(chosen="nobody")


def test_exactly_one_candidate_is_marked_chosen():
    """A candidate set with two winners has no meaning for an exclusion analysis."""
    with pytest.raises(rec.Incomplete, match="exactly one"):
        decision(candidates=[cand("box"), cand("api")])


# --- label missingness, which section 9 requires to be explicit -------------------------------------


def test_the_three_label_states_are_distinguished():
    assert rec.LABEL_STATES == ("labelled", "missing", "pending")
    decision(label_state="labelled", label=True)
    decision(label_state="missing", label=None)
    decision(label_state="pending", label=None)


def test_a_label_without_a_state_that_admits_one_is_refused():
    """This is the specific way a missing label becomes a failure in a success rate."""
    with pytest.raises(rec.Incomplete, match="a label nobody produced"):
        decision(label_state="pending", label=False)
    with pytest.raises(rec.Incomplete, match="no label was given"):
        decision(label_state="labelled", label=None)


def test_an_unknown_label_state_is_refused():
    with pytest.raises(rec.Incomplete, match="label_state"):
        decision(label_state="probably")


# --- admissibility, as SCOPE section 2 defines it ---------------------------------------------------


def test_all_three_parts_of_admissibility_can_refuse():
    ok, why = rec.admissible(cand(bound=0.70), floor=0.80, authorised=True, latency_feasible=True)
    assert not ok and why == "below_floor"
    ok, why = rec.admissible(cand(), floor=0.80, authorised=False, latency_feasible=True)
    assert not ok and why == "not_authorised"
    ok, why = rec.admissible(cand(), floor=0.80, authorised=True, latency_feasible=False)
    assert not ok and why == "latency_infeasible"
    ok, why = rec.admissible(cand(bound=None), floor=0.80, authorised=True, latency_feasible=True)
    assert not ok and why == "no_bound"


def test_an_absent_latency_constraint_is_absent_rather_than_satisfied():
    """Reading a missing constraint as a passed one would report a stronger admissibility than the definition grants.
    `None` means the operator set none, so the condition does not participate."""
    ok, _ = rec.admissible(cand(), floor=0.80, authorised=True, latency_feasible=None)
    assert ok is True


# --- section 12's falsifier, computed rather than asserted ------------------------------------------


def test_a_certified_assignment_whose_candidate_was_not_admissible_is_caught():
    """The falsifier: the mechanism is broken, not mistuned, if this happens."""
    d = decision(candidates=[cand("box", "chosen", bound=0.70), cand("api", "below_floor", 0.65)],
                 certified=True)
    bad = rec.check_certification(d, floor=0.80, latency_feasible=True)
    assert bad and "not admissible" in bad[0] and "below_floor" in bad[0]


def test_a_certified_assignment_that_was_admissible_is_clean():
    assert rec.check_certification(decision(), floor=0.80, latency_feasible=True) == []


def test_the_default_used_while_something_admissible_existed_is_caught():
    """Section 12's 'default is not a hiding place'."""
    d = decision(chosen="fallback", certified=False,
                 candidates=[cand("fallback", "chosen", bound=0.50, cost=0.02),
                             cand("box", "not_priced", bound=0.90, cost=0.004)])
    bad = rec.check_certification(d, floor=0.80, latency_feasible=True)
    assert bad and "hiding place" in bad[0]


def test_an_uncertified_assignment_with_nothing_admissible_is_clean():
    d = decision(chosen="fallback", certified=False,
                 candidates=[cand("fallback", "chosen", bound=0.50), cand("box", "below_floor", bound=0.60)])
    assert rec.check_certification(d, floor=0.80, latency_feasible=True) == []


# --- the log is append-only, because a criterion over a rewritable log is a criterion over the rewrite


def test_an_outcome_is_appended_rather_than_editing_the_decision(tmp_path):
    log = rec.Log(tmp_path / "log.jsonl")
    log.append(decision())
    first = log.path.read_text()
    log.attach_outcome("r1", label_state="labelled", label=True, tokens=1234, latency_s=41.0)
    assert log.path.read_text().startswith(first), "the decision line was not rewritten"
    decisions, outcomes = log.read()
    assert len(decisions) == 1 and outcomes["r1"]["label"] is True
    assert outcomes["r1"]["tokens"] == 1234


def test_a_decision_with_no_outcome_is_visible_as_such(tmp_path):
    log = rec.Log(tmp_path / "log.jsonl")
    log.append(decision())
    decisions, outcomes = log.read()
    assert decisions[0]["request_id"] == "r1" and "r1" not in outcomes


def test_an_outcome_whose_label_state_disagrees_with_its_label_is_refused(tmp_path):
    log = rec.Log(tmp_path / "log.jsonl")
    for state, label in (("labelled", None), ("missing", True), ("pending", False)):
        with pytest.raises(rec.Incomplete):
            log.attach_outcome("r1", label_state=state, label=label)


def test_reading_an_absent_log_is_empty_rather_than_an_error(tmp_path):
    assert rec.Log(tmp_path / "nope.jsonl").read() == ([], {})


def test_the_last_outcome_for_a_request_wins(tmp_path):
    log = rec.Log(tmp_path / "log.jsonl")
    log.append(decision())
    log.attach_outcome("r1", label_state="pending")
    log.attach_outcome("r1", label_state="labelled", label=False)
    _, outcomes = log.read()
    assert outcomes["r1"]["label_state"] == "labelled" and outcomes["r1"]["label"] is False
