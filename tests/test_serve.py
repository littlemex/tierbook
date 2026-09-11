"""Tests for the composition: observe, decide, record, once.

The properties under test are the ones that make the loop honest rather than merely wired: every request is assigned
somewhere, the record is complete enough for section 9, both kinds of gap travel, and nothing is certified on a state
that was not observed.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import accept as ac  # noqa: E402
from tierbook import decide as dc  # noqa: E402
from tierbook import observe as ob  # noqa: E402
from tierbook import record as rec  # noqa: E402
from tierbook import serve as sv  # noqa: E402

BOUNDS = {"box": 0.90, "api": 0.70}
COSTS = {"box": 0.004, "api": 0.012}


def policy(validated=True, domain=None):
    """A two-rule policy: the box below a capacity bound, the API above it. `validated` (CONTRACT C1): the
    non-inferiority status, renamed from `certified` -- this keyword names the same judgment it always did,
    only the word changed."""
    pol = dc.Policy(
        family="agentic-coding",
        rules=(
            dc.Rule(guards=(dc.Guard(var="inflight:box", op="<", threshold=8.0,
                                     derived_from="a measured capacity bound"),),
                    assign=("box",), because="the reserved candidate has a free seat"),
            dc.Rule(guards=(dc.Guard(var="inflight:box", op=">=", threshold=8.0,
                                     derived_from="a measured capacity bound"),),
                    assign=("api",), because="the reserved candidate is full"),
        ),
        default=("api",),
        domain=domain or {"inflight:box": (0.0, 128.0)},
        validated=validated,
        note="a fixture",
        # CONTRACT v0.3.0 C6: `serve.candidate_set` now derives the candidate set from `policy.candidates`
        # rather than from `policy.rules`/`policy.default`, so a hand-built policy has to name the ledger's own
        # set itself. Same ids and same values as `BOUNDS` above -- this is not a new fact the fixture did not
        # already carry, only a new place it also has to be written for the set to keep naming "box" and "api".
        candidates=tuple(BOUNDS), # C6/amendment 10: ids only, no bound
    )
    # CONTRACT C2: a policy built by hand carries no digest until stamped -- the same stamp `compile_policy`
    # applies -- so `route_once` (whose `policy_version` default now reads the policy's own digest) has one to
    # confirm against.
    return dataclasses.replace(pol, policy_digest=dc.policy_digest(pol))


def obs(**state):
    """A fixture in the keys `decide` reads: a candidate's quantities are qualified, the family's are not."""
    o = ob.Observation(candidate="box")
    for k, v in state.items():
        key = f"{k}:box" if k in ob.PER_CANDIDATE else k
        o.state[key] = v
        o.readings[key] = ob.Reading(value=v, as_of=1000.0, source="a fixture")
    return o


def route(o, pol=None, **kw):
    base = dict(policy=pol or policy(), observation=o, request_id="r1", feature_vector_version="fv1",
                mechanism_version="0.1.0", agent="opencode", model="m",
                endpoint="http://e", gateway_quote_usd=0.004, bounds=BOUNDS, costs=COSTS,
                evidence_as_of="2026-09-01", floor=0.80,
                bound_provenance=rec.BoundProvenance(estimator="clopper_pearson_fixed_sample", confidence=0.95))
    base.update(kw)
    return sv.route_once(**base)


def test_a_free_seat_goes_to_the_reserved_candidate_and_is_recorded():
    got, d = route(obs(inflight=2.0, metered_authorised=True))
    assert got["assign"] == ["box"] and d.chosen == "box"
    assert d.certified is True


def test_a_full_engine_goes_to_the_metered_candidate():
    got, d = route(obs(inflight=20.0, metered_authorised=True))
    assert d.chosen == "api" and got["rule"] == 1


def test_an_unobserved_variable_produces_an_assignment_and_no_certification():
    """Section 2: there is no 'choose nothing'. The request is served either way, so the default assigns and the
    record says the floor is not claimed."""
    o = obs(metered_authorised=True)
    o.not_observed["inflight:box"] = "the metrics endpoint did not answer"
    got, d = route(o)
    assert d.chosen == "api", "the declared default"
    assert d.certified is False
    assert any("inflight:box" in g for g in d.gaps)


def test_both_kinds_of_gap_travel_into_the_record():
    """The policy's own and the collector's. A caller that saw only one would think the other had been checked."""
    o = obs(inflight=2.0)
    o.not_observed["metered_authorised"] = "not passed"
    _, d = route(o)
    assert any("metered_authorised" in g for g in d.gaps)
    assert all(isinstance(g, str) for g in d.gaps)


def test_a_state_outside_the_compiled_domain_falls_to_the_default():
    got, d = route(obs(inflight=9999.0, metered_authorised=True), pol=policy(domain={"inflight:box": (0.0, 128.0)}))
    assert d.chosen == "api" and d.certified is False
    assert "outside the compiled domain" in got["reason"]


# --- the candidate set, which is what an exclusion analysis reads ------------------------------------


def test_the_candidate_set_holds_every_candidate_the_policy_can_name():
    _, d = route(obs(inflight=2.0, metered_authorised=True))
    assert {c.id for c in d.candidates} == {"box", "api"}
    assert [c.excluded_because for c in d.candidates if c.id == "box"] == ["chosen"]


def test_a_candidate_with_no_bound_is_recorded_rather_than_omitted():
    """Omitting it would make a candidate nobody could evaluate look like a candidate nobody considered."""
    _, d = route(obs(inflight=2.0, metered_authorised=True), bounds={"box": 0.9})
    api = next(c for c in d.candidates if c.id == "api")
    assert api.excluded_because == "no_bound" and api.bound is None


def test_a_candidate_with_a_bound_and_no_price_says_not_priced():
    _, d = route(obs(inflight=2.0, metered_authorised=True), costs={"box": 0.004})
    api = next(c for c in d.candidates if c.id == "api")
    assert api.excluded_because == "not_priced"


def test_exactly_one_candidate_is_the_chosen_one():
    _, d = route(obs(inflight=20.0, metered_authorised=True))
    assert [c.id for c in d.candidates if c.excluded_because == "chosen"] == ["api"]


# --- the propensity, and what it costs later --------------------------------------------------------


def test_the_propensity_is_one_and_that_is_named_rather_than_a_literal():
    _, d = route(obs(inflight=2.0, metered_authorised=True))
    assert d.selection_probability == sv.DETERMINISTIC_PROPENSITY == 1.0
    assert d.exploration is False


def test_a_log_of_these_cannot_support_a_spend_regret_estimate():
    """The consequence of the line above, asserted end to end so the two cannot drift apart."""
    _, d = route(obs(inflight=2.0, metered_authorised=True))
    got = {v.criterion: v for v in ac.check_all([d.as_dict()], {}, floor=0.80)}
    assert got["spend_regret"].verdict == ac.UNSUPPORTED
    assert "propensity 1" in got["spend_regret"].detail


# --- the state reference ----------------------------------------------------------------------------


def test_the_record_references_the_state_rather_than_embedding_it():
    """Section 9 forbids the snapshot: it would be unbounded and would carry tenant content."""
    _, d = route(obs(inflight=2.0, metered_authorised=True))
    assert d.state_ref.startswith("obs:") and len(d.state_ref) == 20
    assert "inflight" not in d.state_ref


def test_two_observations_with_the_same_values_at_different_times_do_not_collide():
    """A reference that collided on them would let a reader join a decision to the wrong state."""
    a = obs(inflight=2.0)
    b = obs(inflight=2.0)
    b.readings["inflight:box"] = ob.Reading(value=2.0, as_of=2000.0, source="a fixture")
    assert sv.state_ref(a) != sv.state_ref(b)


def test_the_same_observation_gives_the_same_reference():
    a = obs(inflight=2.0, metered_authorised=True)
    assert sv.state_ref(a) == sv.state_ref(a)


# --- and the whole loop, through a real log ---------------------------------------------------------


def test_the_loop_writes_a_log_the_acceptance_checker_reads(tmp_path):
    log = rec.Log(tmp_path / "log.jsonl")
    for i in range(3):
        route(obs(inflight=2.0, metered_authorised=True), request_id=f"r{i}", log=log)
    log.attach_outcome("r0", label_state="labelled", label=True, latency_s=30.0)
    log.attach_outcome("r1", label_state="missing")
    decisions, outcomes = log.read()
    assert len(decisions) == 3
    got = {v.criterion: v for v in ac.check_all(decisions, outcomes, floor=0.80)}
    assert got["no_false_certification"].verdict == ac.PASS
    # One labelled of three certified: too few to say anything, and it says so rather than passing.
    assert got["floor_compliance"].verdict == ac.UNSUPPORTED
    assert got["floor_compliance"].numbers["unlabelled_certified"] == 2


def test_the_loop_cannot_write_a_certified_decision_below_the_floor(tmp_path):
    """Deliberately changed by C1 amendment 3, and the change is the evidence. This used to drive a below-floor
    bound through `route_once` and catch the resulting record with the falsifier -- which worked because
    `route_once` set `certified` from `policy.validated` and never compared the bound to the floor. Now the
    decision and the falsifier share one predicate by construction, so the loop refuses to produce the record at
    all. What the falsifier catches is asserted on its own below, against a row that reached the log by some other
    writer, which is the only way that row can now exist."""
    log = rec.Log(tmp_path / "log.jsonl")
    _, d = route(obs(inflight=2.0, metered_authorised=True), request_id="r1", log=log,
                 bounds={"box": 0.10, "api": 0.05})
    assert d.certified is False
    decisions, _ = log.read()
    assert ac.no_false_certification(decisions, floor=0.80, latency_feasible=True).verdict != ac.FAIL


def test_the_falsifier_catches_a_certified_row_below_the_floor_from_any_writer(tmp_path):
    """The falsifier's own subject, separated from the loop: a record claiming certification for a candidate whose
    bound is under the floor is caught by reading the record, not by trusting whoever wrote it. `Decision` accepts
    this combination on purpose -- refusing it at construction would move the check into the writer and leave
    nothing able to audit a log written by an older mechanism version or a second implementation."""
    log = rec.Log(tmp_path / "log.jsonl")
    prov = rec.BoundProvenance(estimator="clopper_pearson_fixed_sample", confidence=0.95)
    log.append(rec.Decision(
        family="agentic-coding", request_id="r1", feature_vector_version="fv1", state_ref="obs:a",
        candidates=[rec.Candidate(id="box", excluded_because="chosen", bound=0.10, cost_usd=0.004,
                                  evidence_as_of="2026-09-01", bound_provenance=prov)],
        chosen="box", selection_probability=1.0, exploration=False, certified=True, policy_version="p1",
        policy_digest="0123456789abcdef",
        mechanism_version="0.1.0", agent="opencode", model="m", endpoint="http://e", gateway_quote_usd=0.004,
        gateway_authorised=True, decided_at=1000.0, exploration_reason="no_mechanism", eligible_set=[]))
    decisions, _ = log.read()
    v = ac.no_false_certification(decisions, floor=0.80, latency_feasible=True)
    assert v.verdict == ac.FAIL and "not admissible" in v.detail


def test_an_uncertified_policy_never_certifies_however_the_state_looks():
    _, d = route(obs(inflight=2.0, metered_authorised=True), pol=policy(validated=False))
    assert d.certified is False
