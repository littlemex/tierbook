"""The compiled policy as a function of state, and the ways it could pretend to be one.

Two adversarial reviews said the previous output was a point rather than a function: every state-dependent
quantity evaluated at the observation cohort's state and reduced to a scalar. Each test here is a way this
could look like a function while still being that point.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tierbook import decide as D  # noqa: E402


def entry(chosen, *, status="assigned", reason=None):
    return {"chosen": list(chosen), "status": status,
            "validation": {"reason": reason} if reason else {}}


# --- a threshold is a measurement or a gap, and there is no third option --------------------------


def test_an_unmeasured_threshold_cannot_fire_and_is_named():
    """Not a disabled guard and not a permissive one. Picking a plausible number is what turns an unmeasured
    quantity into a decision."""
    p = D.compile_policy("f", entry(["box"]), reserved_ids={"box"}, default=("strong",))
    assert p.gaps and "reserved_inflight" in p.gaps[0]
    out = D.decide(p, {"reserved_available": True, "reserved_inflight": 3})
    assert out["assign"] == ["strong"], "falls to the default rather than to an assumed capacity"
    assert any("unmeasured_threshold" in g for g in out["gaps"])


def test_a_measured_threshold_produces_the_derived_boundary():
    """The only place "at this concurrency, route to the API" comes from: the occupancy at which the reserved
    candidate stops absorbing work, derived rather than written down."""
    p = D.compile_policy("f", entry(["box"]), reserved_ids={"box"}, default=("strong",),
                         capacity_bound=8, capacity_source="load probe at 1,2,4,8,16 concurrency")
    assert p.gaps == []
    below = D.decide(p, {"reserved_available": True, "reserved_inflight": 3})
    above = D.decide(p, {"reserved_available": True, "reserved_inflight": 8})
    assert below["assign"] == ["box"] and below["rule"] == 0
    assert above["assign"] == ["strong"] and above["rule"] is None
    assert "paid-for capacity is used before anything metered" in below["reason"]


def test_the_same_policy_gives_different_answers_at_different_states():
    """The property the previous output could not have: it was a scalar valid at one occupancy."""
    p = D.compile_policy("f", entry(["box"]), reserved_ids={"box"}, default=("strong",),
                         capacity_bound=4, capacity_source="probe")
    answers = {D.decide(p, {"reserved_available": True, "reserved_inflight": n})["assign"][0]
               for n in (0, 1, 2, 3, 4, 9)}
    assert answers == {"box", "strong"}


def test_a_candidate_that_is_not_serving_does_not_absorb_work():
    p = D.compile_policy("f", entry(["box"]), reserved_ids={"box"}, default=("strong",),
                         capacity_bound=8, capacity_source="probe")
    out = D.decide(p, {"reserved_available": False, "reserved_inflight": 0})
    assert out["assign"] == ["strong"]


def test_a_guard_over_a_variable_nobody_collected_is_a_gap_not_a_pass():
    """Discovering at request time that a guard cannot be evaluated is worse than refusing to compile it, so
    the variable set is closed and an absent value is reported."""
    p = D.compile_policy("f", entry(["box"]), reserved_ids={"box"}, default=("strong",),
                         capacity_bound=8, capacity_source="probe")
    out = D.decide(p, {"reserved_available": True})
    assert out["assign"] == ["strong"]
    assert any("uncollected_variable" in g for g in out["gaps"])


def test_a_guard_cannot_be_written_over_a_variable_nobody_collects():
    with pytest.raises(ValueError) as e:
        D.Guard("gpu_temperature", "<", 80, derived_from="a thermometer")
    assert "not a collected state variable" in str(e.value)


# --- the domain is part of the output ------------------------------------------------------------


def test_a_state_outside_the_compiled_domain_takes_the_default_and_says_so():
    """A policy without a stated domain invites its reader to apply it everywhere, which is how one idle
    afternoon's figure escaped as a property of the machine."""
    p = D.compile_policy("f", entry(["box"]), reserved_ids={"box"}, default=("strong",),
                         capacity_bound=8, capacity_source="probe")
    out = D.decide(p, {"reserved_available": True, "reserved_inflight": 99})
    assert out["assign"] == ["strong"] and out["rule"] is None
    assert "outside the compiled domain" in out["reason"]
    assert any("outside the observed range" in g for g in out["gaps"])


def test_a_variable_that_was_never_varied_is_outside_the_domain_by_construction():
    """Absent from the domain means no observation covers it -- which is not the same as any value being fine."""
    p = D.compile_policy("f", entry(["box"]), reserved_ids={"box"}, default=("strong",),
                         capacity_bound=8, capacity_source="probe")
    out = D.decide(p, {"reserved_available": True, "reserved_inflight": 2, "arrival_rate_per_hour": 500})
    assert out["assign"] == ["strong"]
    assert any("was not varied when this was measured" in g for g in out["gaps"])


# --- uncertified is a fallback, not a rule -------------------------------------------------------


def test_nothing_certified_means_no_rules_and_the_default_carries_everything():
    """A named-but-uncertified assignment is what the evidence falls back to, not a choice it supports, so it
    must not become a rule that fires."""
    p = D.compile_policy("f", entry(["box"], status="provisional", reason="held out below the margin"),
                         reserved_ids={"box"}, default=("strong",))
    assert p.rules == () and p.certified is False
    assert "held out below the margin" in p.note
    out = D.decide(p, {"reserved_available": True, "reserved_inflight": 0})
    assert out["assign"] == ["strong"] and out["certified"] is False


def test_the_default_is_not_the_cheapest_and_the_answer_says_why():
    p = D.compile_policy("f", entry(["box"]), reserved_ids={"box"}, default=("strong",),
                         capacity_bound=2, capacity_source="probe")
    out = D.decide(p, {"reserved_available": True, "reserved_inflight": 2})
    assert "deliberately not the cheapest" in out["reason"]


def test_an_assignment_with_no_reserved_candidate_is_unconditional_and_says_that():
    p = D.compile_policy("f", entry(["cheap"]), reserved_ids={"box"}, default=("strong",))
    assert len(p.rules) == 1 and p.rules[0].guards == ()
    assert p.gaps == [] and "does not turn on occupancy" in p.rules[0].because
    out = D.decide(p, {})
    assert out["assign"] == ["cheap"] and out["rule"] == 0


# --- what is missing is named, not implied to be present -----------------------------------------


def test_the_artifact_names_what_a_closed_loop_still_needs():
    """Absence disguised as presence is the failure this list exists to prevent."""
    p = D.compile_policy("f", entry(["box"]), reserved_ids={"box"}, default=("strong",))
    d = D.as_dict(p)
    joined = " ".join(d["missing_for_a_closed_loop"])
    assert "selection probabilities" in joined and "exploration" in joined
    assert "anytime-valid" in joined and "change-point" in joined
    assert "it does not observe one" in joined


def test_the_artifact_is_readable_without_importing_this_module():
    p = D.compile_policy("f", entry(["box"]), reserved_ids={"box"}, default=("strong",),
                         capacity_bound=8, capacity_source="probe at 1,2,4,8,16")
    d = D.as_dict(p)
    assert d["rules"][0]["assign"] == ["box"]
    assert "reserved_inflight < 8 (from probe at 1,2,4,8,16)" in d["rules"][0]["when"]
    assert d["domain"]["reserved_inflight"] == [0, 8]
