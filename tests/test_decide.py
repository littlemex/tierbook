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


def policy(chosen, *, reserved=("box",), metered=("strong", "cheap"), curve=None, age=30, **kw):
    """A compiled policy with the parts a caller must declare, so a test never gets them by default."""
    return D.compile_policy("f", entry(chosen, **kw), reserved_ids=set(reserved), metered_ids=set(metered),
                            default=("strong",), default_declared_by="the test",
                            service_curve=curve, max_evidence_age_days=age)


#: A probe whose throughput stops rising above 8 in flight.
CURVE = {"1": 60, "2": 118, "4": 230, "8": 420, "16": 415}


def st(**kw):
    """Observed state. Includes more than the guards read, which a real collector does."""
    base = {"evidence_age_days": 1, "metered_authorised": True, "arrival_rate_per_hour": 500}
    base.update(kw)
    return base


# --- a threshold is a measurement or a gap, and there is no third option --------------------------


def test_an_unmeasured_threshold_means_no_rule_can_ever_fire_and_that_is_reported():
    """Not a disabled guard and not a permissive one. And an inert policy is not a degenerate one: the first is
    a component that does nothing while looking like it works, and an earlier version shipped exactly that
    while a separately exported router config named the guarded candidate anyway."""
    p = policy(["box"])
    assert p.gaps and "inflight:box" in p.gaps[0]
    assert p.can_ever_fire is False
    assert p.guarded_candidates == set(), "nothing an exporter may name"
    out = D.decide(p, st(**{"available:box": True, "inflight:box": 3}))
    assert out["assign"] == ["strong"]
    assert any("unmeasured_threshold" in g for g in out["gaps"])


def test_the_bound_is_derived_from_the_curve_not_accepted_as_a_number():
    """A scalar a caller passes is a configured threshold whatever the documentation beside it says."""
    p = policy(["box"], curve=CURVE)
    assert p.can_ever_fire is True and p.gaps == []
    when = D.as_dict(p)["rules"][0]["when"]
    assert any("inflight:box < 8.0" in w and "throughput stopped rising above 8" in w for w in when)


def test_a_curve_with_one_point_cannot_show_where_throughput_stops_rising():
    p = policy(["box"], curve={"1": 60})
    assert p.can_ever_fire is False
    assert any("at least two concurrencies" in g for g in p.gaps)


def test_the_same_policy_gives_different_answers_at_different_occupancies():
    p = policy(["box"], curve=CURVE)
    below = D.decide(p, st(**{"available:box": True, "inflight:box": 3}))
    above = D.decide(p, st(**{"available:box": True, "inflight:box": 8}))
    assert below["assign"] == ["box"] and below["rule"] == 0
    assert above["assign"] == ["strong"]


def test_a_state_richer_than_the_guards_does_not_fall_out_of_domain():
    """The defect this replaces inverted the design: a caller that collected every documented variable was
    permanently out of domain and every request took the default, so observing more made the policy apply
    less."""
    p = policy(["box"], curve=CURVE)
    out = D.decide(p, st(**{"available:box": True, "inflight:box": 2,
                            "arrival_rate_per_hour": 9999, "metered_authorised": True}))
    assert out["assign"] == ["box"], "extra observations are not a reason to refuse"


def test_above_capacity_is_the_measured_branch_not_an_unknown_region():
    """Truncating the domain at the decision boundary classified the default branch as an unsupported
    extrapolation, which is the one thing it is not."""
    p = policy(["box"], curve=CURVE)
    out = D.decide(p, st(**{"available:box": True, "inflight:box": 500}))
    assert "outside the compiled domain" not in out["reason"]
    assert out["assign"] == ["strong"]


# --- guards nobody had written -------------------------------------------------------------------


def test_an_assignment_that_charges_stops_firing_when_spend_is_not_authorised():
    """The third case the gap model excluded: a guard that does not exist. `decide` used to return a confident
    assignment that could not be paid for, and report no gap at all."""
    p = policy(["cheap"])
    assert D.decide(p, st(metered_authorised=True))["assign"] == ["cheap"]
    out = D.decide(p, st(metered_authorised=False))
    assert out["assign"] == ["strong"] and out["rule"] is None


def test_a_policy_stops_asserting_itself_when_its_evidence_expires():
    p = policy(["box"], curve=CURVE, age=30)
    fresh = D.decide(p, st(evidence_age_days=1, **{"available:box": True, "inflight:box": 1}))
    stale = D.decide(p, st(evidence_age_days=400, **{"available:box": True, "inflight:box": 1}))
    assert fresh["assign"] == ["box"] and stale["assign"] == ["strong"]


def test_with_no_freshness_bound_the_age_guard_is_a_named_gap():
    p = policy(["box"], curve=CURVE, age=None)
    assert p.can_ever_fire is False
    assert any("nothing says when these measurements stop describing" in g for g in p.gaps)


# --- degradation goes to the assignment's own tail ------------------------------------------------


def test_above_capacity_a_cascade_degrades_to_its_own_metered_tail():
    """The tail was measured as part of this arrangement; the declared default was not."""
    p = policy(["box", "cheap"], curve=CURVE)
    below = D.decide(p, st(**{"available:box": True, "inflight:box": 1}))
    above = D.decide(p, st(**{"available:box": True, "inflight:box": 99}))
    assert below["assign"] == ["box", "cheap"]
    assert above["assign"] == ["cheap"]
    assert "assignment's own metered tail" in above["reason"]


def test_a_second_reserved_candidate_is_named_as_unmodelled_rather_than_guessed():
    """One occupancy figure cannot describe two of them, and guessing which one a request would land on is a
    scheduling decision this does not make."""
    p = policy(["box", "box2"], reserved=("box", "box2"), curve=CURVE)
    assert p.provenance["reserved_not_modelled"] == ["box2"]
    assert "cannot describe two of them" in p.provenance["reserved_not_modelled_note"]


# --- what is declared says who declared it -------------------------------------------------------


def test_the_default_records_who_declared_it():
    """A declared default is permissible; an artifact that does not say who declared it invites a reader to
    take it for a measured choice."""
    assert D.as_dict(policy(["box"]))["provenance"]["default_declared_by"] == "the test"


def test_every_unevaluable_guard_is_collected_not_just_the_first():
    """Returning early hid the later ones, so a rule two measurements away from working looked one away."""
    p = policy(["box"], age=None)                       # both the age guard and the capacity guard unmeasured
    out = D.decide(p, st(**{"available:box": True, "inflight:box": 1}))
    kinds = [g for g in out["gaps"] if "unmeasured_threshold" in g]
    assert len(kinds) >= 2


# --- the closed variable set, and what is still missing ------------------------------------------


def test_a_guard_cannot_be_written_over_a_variable_this_does_not_evaluate():
    with pytest.raises(ValueError) as e:
        D.Guard("gpu_temperature", "<", 80, derived_from="a thermometer")
    assert "does not name a state variable" in str(e.value)


def test_a_guard_may_be_qualified_by_candidate():
    g = D.Guard("inflight:box-2", "<", 4, derived_from="probe")
    assert D.var_name(g.var) == "inflight"


def test_nothing_certified_means_no_rules_and_the_default_carries_everything():
    p = policy(["box"], status="provisional", reason="held out below the margin")
    assert p.rules == () and p.certified is False and p.can_ever_fire is False
    assert "held out below the margin" in p.note
    out = D.decide(p, st(**{"available:box": True, "inflight:box": 0}))
    assert out["assign"] == ["strong"] and out["certified"] is False


def test_the_artifact_names_what_a_closed_loop_still_needs():
    d = D.as_dict(policy(["box"]))
    joined = " ".join(d["missing_for_a_closed_loop"])
    assert "selection probabilities" in joined and "exploration" in joined
    assert "anytime-valid" in joined and "change-point" in joined


def test_the_artifact_is_readable_without_importing_this_module():
    d = D.as_dict(policy(["box"], curve=CURVE))
    assert d["rules"][0]["assign"] == ["box"] and d["can_ever_fire"] is True
    assert d["domain"]["inflight:box"] == [0, float("inf")]
