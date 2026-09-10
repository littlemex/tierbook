"""Tests for the composition: observe, decide, record, once.

The properties under test are the ones that make the loop honest rather than merely wired: every request is assigned
somewhere, the record is complete enough for section 9, both kinds of gap travel, and nothing is certified on a state
that was not observed.
"""
from __future__ import annotations

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


def policy(certified=True, domain=None):
    """A two-rule policy: the box below a capacity bound, the API above it."""
    return dc.Policy(
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
        certified=certified,
        note="a fixture",
    )


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
                policy_version="p1", mechanism_version="0.1.0", agent="opencode", model="m",
                endpoint="http://e", gateway_quote_usd=0.004, bounds=BOUNDS, costs=COSTS,
                evidence_as_of="2026-09-01")
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


def test_a_certified_decision_whose_chosen_candidate_is_below_the_floor_is_caught_end_to_end(tmp_path):
    """The falsifier, through the real loop: the policy says certified, the bound says otherwise, and the checker
    reads the record rather than the policy's claim."""
    log = rec.Log(tmp_path / "log.jsonl")
    route(obs(inflight=2.0, metered_authorised=True), request_id="r1", log=log, bounds={"box": 0.10, "api": 0.05})
    decisions, _ = log.read()
    v = ac.no_false_certification(decisions, floor=0.80, latency_feasible=True)
    assert v.verdict == ac.FAIL and "not admissible" in v.detail


def test_an_uncertified_policy_never_certifies_however_the_state_looks():
    _, d = route(obs(inflight=2.0, metered_authorised=True), pol=policy(certified=False))
    assert d.certified is False
