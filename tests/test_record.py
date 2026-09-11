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
    """`bound_provenance` (CONTRACT C1) travels paired with `bound`, an honest bound this release could
    actually produce."""
    return rec.Candidate(id=cid, excluded_because=why, bound=bound, cost_usd=cost,
                         evidence_as_of="2026-09-01",
                         bound_provenance=(None if bound is None else
                                           rec.BoundProvenance(estimator="clopper_pearson_fixed_sample",
                                                               confidence=0.95)))


def decision(**kw):
    base = dict(
        family="agentic-coding", request_id="r1", feature_vector_version="fv1", state_ref="obs:abc",
        candidates=[cand(), cand("api", "below_floor", 0.70, 0.012)], chosen="box",
        selection_probability=1.0, exploration=False, certified=True, policy_version="p1",
        policy_digest="0123456789abcdef",
        mechanism_version="0.1.0", agent="opencode", model="Qwen/Qwen3.6-35B-A3B",
        endpoint="http://vllm:8000", gateway_quote_usd=0.004, gateway_authorised=True, decided_at=1000.0,
        exploration_reason="no_mechanism", eligible_set=[])
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


def test_a_pending_outcome_may_be_superseded_by_a_real_label(tmp_path):
    log = rec.Log(tmp_path / "log.jsonl")
    log.append(decision())
    log.attach_outcome("r1", label_state="pending")
    log.attach_outcome("r1", label_state="labelled", label=False)
    _, outcomes = log.read()
    assert outcomes["r1"]["label_state"] == "labelled" and outcomes["r1"]["label"] is False


# --- the fixes a review earned ----------------------------------------------------------------------


def test_freshness_is_part_of_admissibility():
    """`evidence_expired` was in the exclusion vocabulary with nothing able to produce it, so a candidate whose
    evidence had expired could be certified."""
    ok, why = rec.admissible(cand(), floor=0.80, authorised=True, latency_feasible=True,
                             evidence_age_days=120.0, max_age_days=90.0)
    assert not ok and why == "evidence_expired"
    ok, _ = rec.admissible(cand(), floor=0.80, authorised=True, latency_feasible=True,
                           evidence_age_days=30.0, max_age_days=90.0)
    assert ok


def test_an_undeclared_freshness_limit_is_absent_rather_than_passed():
    """Like the latency condition: no declared limit means the condition does not participate."""
    ok, _ = rec.admissible(cand(), floor=0.80, authorised=True, latency_feasible=None,
                           evidence_age_days=9999.0, max_age_days=None)
    assert ok


def test_an_uncertified_decision_whose_own_choice_was_admissible_is_a_hiding_place():
    """The purest case, and an earlier version skipped the chosen candidate in this scan -- which made exactly it
    undetectable. The mechanism declined to certify an assignment it could have."""
    d = decision(certified=False)
    bad = rec.check_certification(d, floor=0.80, latency_feasible=True)
    assert bad and "'box' was admissible" in bad[0]


def test_every_hiding_place_violation_is_reported_not_just_the_first():
    """An earlier version broke out of the loop and undercounted."""
    d = decision(certified=False, chosen="box",
                 candidates=[cand("box", "chosen", 0.95), cand("api", "not_priced", 0.90)])
    bad = rec.check_certification(d, floor=0.80, latency_feasible=True)
    assert len(bad) == 2


def test_a_bound_with_no_attribution_is_not_representable():
    """An earlier version wrote 'lcb' for whatever a caller passed, so a log of point estimates claimed to be a log of
    corrected lower bounds and the falsifier passed against them.

    Deliberately changed by v0.3.0 C1 and amendment 3. This asserted that the unattributed bound was representable
    and merely labelled `bound_kind == "unstated"`, and a sentinel is a field a writer can leave at its default
    while still logging the number -- which is how the point estimates got in. Refusing the construction removes
    the state instead of naming it, and the assertion moves with the mechanism."""
    with pytest.raises(rec.Incomplete, match="has no bound_provenance"):
        rec.Candidate(id="x", excluded_because="chosen", bound=0.9)
    # And the reverse, so the pair cannot be satisfied by dropping the number and keeping the claim.
    with pytest.raises(rec.Incomplete, match="bound_provenance"):
        rec.Candidate(id="x", excluded_because="chosen",
                      bound_provenance=rec.BoundProvenance(estimator="clopper_pearson_fixed_sample",
                                                           confidence=0.95))


def test_a_label_that_changes_is_refused_rather_than_the_later_line_winning(tmp_path):
    """An earlier version kept the last outcome per request, which made the log append-only in bytes and mutable in
    meaning -- and the argument for trusting a criterion computed over it did not hold."""
    log = rec.Log(tmp_path / "log.jsonl")
    log.append(decision())
    log.attach_outcome("r1", label_state="labelled", label=False)
    log.attach_outcome("r1", label_state="labelled", label=True)
    with pytest.raises(rec.Incomplete, match="a criterion over the rewrite"):
        log.read()


def test_a_label_arriving_after_pending_is_not_a_change(tmp_path):
    log = rec.Log(tmp_path / "log.jsonl")
    log.append(decision())
    log.attach_outcome("r1", label_state="pending")
    log.attach_outcome("r1", label_state="labelled", label=True)
    _, outcomes = log.read()
    assert outcomes["r1"]["label"] is True


def test_a_corrupt_line_does_not_destroy_the_records_around_it(tmp_path):
    """A crash mid-append leaves a truncated line, and raising on it loses every intact record before it."""
    log = rec.Log(tmp_path / "log.jsonl")
    log.append(decision(request_id="r1"))
    with log.path.open("a") as fh:
        fh.write('{"request_id": "r2", "candi\n')
    log.append(decision(request_id="r3"))
    decisions, outcomes = log.read()
    assert [d["request_id"] for d in decisions] == ["r1", "r3"]
    assert outcomes["__bad_lines__"]["count"] == 1


def test_a_caller_that_wants_the_corrupt_line_to_raise_can_say_so(tmp_path):
    log = rec.Log(tmp_path / "log.jsonl")
    with log.path.open("a") as fh:
        fh.write("{not json\n")
    with pytest.raises(rec.Incomplete, match="not readable"):
        log.read(strict=True)


def test_the_observation_a_decision_points_at_is_stored(tmp_path):
    """`state_ref` was a dangling pointer: the record hashed an observation nothing persisted."""
    log = rec.Log(tmp_path / "log.jsonl")
    log.append_observation("obs:abc", {"state": {"inflight:box": 2.0}, "not_observed": {}})
    log.append(decision(state_ref="obs:abc"))
    decisions, outcomes = log.read()
    assert outcomes["__observations__"]["obs:abc"]["state"]["inflight:box"] == 2.0
    assert decisions[0]["state_ref"] in outcomes["__observations__"]


def test_a_confidence_is_paired_with_its_estimator_in_both_directions():
    """Found in phase 4 as a value written into every candidate's provenance and read by nothing.

    The pairing is the same move C1 already makes twice -- `bound` with `bound_provenance`, and `unrecorded` with
    `corrected_over` -- applied to the third field, which had been left free. A named estimator with no confidence
    is a bound at an unstated significance, and `clopper_pearson_fixed_sample` at 0.05 and the same estimator at
    0.20 are two different claims wearing one name: `bound_kind`'s exact defect, surviving inside the vocabulary
    built to end it. An `unrecorded` estimator cannot carry one either, because a significance is a property of a
    procedure and there is no recorded procedure to have had it."""
    with pytest.raises(rec.Incomplete, match="unstated significance"):
        rec.BoundProvenance(estimator="clopper_pearson_fixed_sample", confidence=None)
    with pytest.raises(rec.Incomplete, match="no record of one"):
        rec.BoundProvenance(estimator="unrecorded", confidence=0.95)
    # Both legitimate pairings still construct, so the guard refuses the unpaired states and not the field.
    assert rec.BoundProvenance(estimator="clopper_pearson_fixed_sample", confidence=0.95).confidence == 0.95
    assert rec.BoundProvenance(estimator="unrecorded", confidence=None).confidence is None
