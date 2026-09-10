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


def policy(chosen, *, reserved=("box",), metered=("strong", "cheap"), curve=None, slo=20.0, age=30, **kw):
    """A compiled policy with the parts a caller must declare, so a test never gets them by default."""
    return D.compile_policy("f", entry(chosen, **kw), reserved_ids=set(reserved), metered_ids=set(metered),
                            default=("strong",), default_declared_by="the test",
                            service_curve=curve, latency_p95_slo_s=slo, max_evidence_age_days=age)


def pt(c, tph, p95, failed=0):
    return {"concurrency": c, "tasks_per_hour": tph, "p95_latency_s": p95, "failed": failed}


#: A probe where p95 crosses 20 s above 8 in flight, so 8 is the last occupancy that meets the constraint. TWO
#: runs that agree, because one run is refused: the real probe's bound moved by a factor of 2.6 between runs.
_RUN = [pt(1, 60, 3.0), pt(2, 118, 5.0), pt(4, 230, 9.0), pt(8, 420, 18.0), pt(16, 415, 40.0)]
_RUN2 = [pt(1, 58, 3.1), pt(2, 120, 5.2), pt(4, 233, 9.4), pt(8, 415, 18.6), pt(16, 410, 41.0)]
CURVE = [_RUN, _RUN2]

#: The real probe, run 1 (2 batches per point). Its throughput is monotone increasing; what is non-monotone is
#: the MARGINAL gain -- +0.55% from 64 to 128 and then +20.95% from 128 to 256.
REAL = [pt(16, 7957.3, 8.71), pt(32, 16024.5, 12.01), pt(64, 22908.1, 17.46),
        pt(128, 23034.9, 34.13), pt(256, 27860.7, 46.57)]

#: The real probe, run 2 (8 batches per point). Nothing survived: p95 at 64 went 17.46 to 45.68, throughput at 64
#: fell 21.8%, and the peak moved from 256 to 128.
REAL2 = [pt(64, 17918.9, 45.68), pt(128, 27379.8, 42.01), pt(256, 25635.0, 70.44)]


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


def test_the_bound_is_where_the_measured_curve_meets_the_declared_latency_constraint():
    """Nothing invented: the curve is measured, the p95 is declared for other purposes anyway, and the bound is
    where they meet."""
    p = policy(["box"], curve=CURVE, slo=20.0)
    assert p.can_ever_fire is True and p.gaps == []
    when = D.as_dict(p)["rules"][0]["when"]
    assert any("inflight:box < 8.0" in w and "declared 20.00s" in w for w in when)
    # Named for what it is: one short run's sample, not a physical capacity.
    assert any("TESTED OPERATING BOUND, not a physical capacity" in w for w in when)


def test_a_tighter_constraint_moves_the_bound_down():
    """The bound is a function of the constraint, which is what makes it derived rather than stored."""
    assert D._capacity_from_curve(CURVE, 20.0)[0] == 8.0
    assert D._capacity_from_curve(CURVE, 10.0)[0] == 4.0
    assert D._capacity_from_curve(CURVE, 4.0)[0] == 1.0


def test_a_single_probe_run_cannot_support_a_bound():
    """This deployment's own history is the argument. Repeating the probe moved p95 at 64 in flight from 17.5 s to
    45.7 s and the throughput peak from 256 to 128, so one run does not measure a property of the candidate."""
    bound, why = D._capacity_from_curve(REAL, 20.0)
    assert bound is None
    assert "SINGLE probe run" in why and "17.5 s to 45.7 s" in why
    assert "Probe again and pass both runs" in why


def test_runs_that_disagree_are_refused_with_both_values():
    """Taking either value would be choosing which run to believe."""
    bound, why = D._capacity_from_curve([REAL, REAL2], 20.0)
    assert bound is None
    assert "do not agree on a bound" in why
    assert "run 1: 64 in flight" in why and "run 2: no probed concurrency met" in why

    # And at a target both runs clear, they still disagree on where the bound is.
    bound60, why60 = D._capacity_from_curve([REAL, REAL2], 60.0)
    assert bound60 is None and "run 1: 256 in flight" in why60 and "run 2: 128 in flight" in why60


def test_agreeing_runs_produce_a_bound_that_says_it_reproduced():
    bound, why = D._capacity_from_curve(CURVE, 20.0)
    assert bound == 8.0
    assert "REPRODUCED across 2 probe runs" in why
    assert "run 1: 8 in flight" in why and "run 2: 8 in flight" in why


def test_a_throughput_knee_is_not_used_because_the_real_curve_has_none():
    """22,908 tasks/hour at 64 in flight, 23,035 at 128 (+0.55%), 27,861 at 256 (+20.95%). An earlier rule
    stopped at the first flat step and reported it as capacity; the repeat run then reversed the shape."""
    bound, why = D._capacity_from_curve([REAL, REAL2], None)
    assert bound is None
    assert "throughput alone does not locate a bound" in why
    assert "a repeat run reversed that shape entirely" in why
    # And the throughput itself is monotone, which an earlier statement of this got wrong.
    tph = [pt["tasks_per_hour"] for pt in REAL]
    assert tph == sorted(tph), "monotone increasing; it is the marginal gain that is not"


def test_a_bound_at_the_top_of_the_probed_range_says_it_is_censored():
    bound, why = D._capacity_from_curve([REAL, REAL], 60.0)
    assert bound == 256.0 and "CENSORED" in why


def test_no_probed_concurrency_meeting_the_constraint_is_reported_per_run():
    bound, why = D._capacity_from_curve([REAL, REAL], 1.0)
    assert bound is None and "the lowest point already misses it" in why


def test_a_curve_with_one_point_cannot_locate_a_bound():
    p = policy(["box"], curve=[[pt(1, 60, 3.0)], [pt(1, 58, 3.1)]])
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


def test_a_spend_refusal_does_not_withhold_paid_for_capacity():
    """The box charges nothing. Gating the whole cascade on authorisation made usable capacity unreachable for
    want of permission the box does not need."""
    p = policy(["box", "cheap"], curve=CURVE)
    out = D.decide(p, st(metered_authorised=False, **{"available:box": True, "inflight:box": 1}))
    assert out["assign"] == ["box"]
    assert "a refusal nothing requires" in out["reason"]


def test_a_box_that_is_down_hands_over_to_the_tail_not_the_default():
    """Previously neither rule fired: the below-capacity rule needed the box up, and the above-capacity rule had
    no availability test -- so a certified tail sat unused while traffic went to an unrelated default."""
    p = policy(["box", "cheap"], curve=CURVE)
    out = D.decide(p, st(**{"available:box": False, "inflight:box": 0}))
    assert out["assign"] == ["cheap"] and "is not serving" in out["reason"]


def test_a_second_reserved_candidate_is_named_as_unmodelled_rather_than_guessed():
    """One occupancy figure cannot describe two of them, and guessing which one a request would land on is a
    scheduling decision this does not make."""
    p = policy(["box", "box2"], reserved=("box", "box2"), curve=CURVE)
    # Refused, not partially guarded. An earlier version guarded the first and recorded the others as "not
    # modelled" -- and the whole assignment still fired, so the unguarded legs ran with no capacity semantics.
    assert p.rules == () and p.certified is False
    assert "only one can be capacity-guarded" in p.note


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





# --- rule order must not be doing the deciding ----------------------------------------------------


def test_the_capacity_split_is_provably_disjoint():
    """`decide` returns the first match, so two rules that can both hold mean the order they were appended in
    silently decides assignments. With one rule this was dormant; the split made it two."""
    p = policy(["box", "cheap"], curve=CURVE)
    assert len(p.rules) == 4, "authorised/unauthorised x below/at-capacity, plus the box being down"
    assert p.overlaps == [], "no assignment depends on the order the rules happen to be listed in"
    assert D.as_dict(p)["rule_overlaps"] == []


def test_two_rules_that_can_both_hold_are_reported():
    """A check that quietly returns disjoint for a case it cannot analyse is worse than one that admits the pair
    is unchecked, so this reports rather than proves absence."""
    g = D.Guard("inflight:box", "<", 8, derived_from="probe")
    p = D.Policy("f", (D.Rule((g,), ("a",), "first"), D.Rule((g,), ("b",), "second")), ("strong",))
    assert len(p.overlaps) == 1
    assert "the order they are listed in decides" in p.overlaps[0]


def test_opposed_equalities_count_as_disjoint():
    p = D.Policy("f", (
        D.Rule((D.Guard("available:box", "==", True, derived_from="x"),), ("a",), "up"),
        D.Rule((D.Guard("available:box", "==", False, derived_from="x"),), ("b",), "down"),
    ), ("strong",))
    assert p.overlaps == []


def test_a_point_meeting_the_target_above_one_that_does_not_is_reported_not_jumped_to():
    """A bound with a hole under it is not a bound, and the constraint is not guaranteed monotone in occupancy on
    a batching engine."""
    holed = [pt(1, 60, 3.0), pt(2, 118, 25.0), pt(4, 230, 9.0)]
    bound, why = D._capacity_from_curve([holed, holed], 20.0)
    assert bound == 1.0
    assert "[4] also met the target" in why and "not monotone in occupancy" in why


# --- the artifact has to be readable back, or the deployable path rebuilds what it just wrote --------


def test_a_compiled_policy_round_trips():
    """An earlier version wrote guards only as prose, which made the artifact one-way."""
    pol = D.Policy(
        family="f",
        rules=(D.Rule(guards=(D.Guard(var="inflight:box", op="<", threshold=8.0, derived_from="a probe"),),
                       assign=("box",), because="a free seat"),),
        default=("api",), domain={"inflight:box": (0.0, 128.0)}, certified=True, note="n",
        provenance={"default_declared_by": "an operator"})
    back = D.from_dict(D.as_dict(pol))
    assert back == pol


def test_the_prose_form_is_kept_for_a_reader_beside_the_fields():
    pol = D.Policy(family="f",
                    rules=(D.Rule(guards=(D.Guard(var="inflight", op=">=", threshold=8.0, derived_from="a probe"),),
                                   assign=("api",), because="full"),),
                    default=("api",))
    d = D.as_dict(pol)
    assert d["rules"][0]["when"] == ["inflight >= 8.0 (from a probe)"]
    assert d["rules"][0]["guards"][0]["threshold"] == 8.0


def test_an_unmeasured_guard_round_trips_as_unmeasured():
    pol = D.Policy(family="f",
                    rules=(D.Rule(guards=(D.Guard(var="inflight", op="<", threshold=None,
                                                    derived_from="a probe nobody ran"),),
                                   assign=("box",), because="x"),),
                    default=("api",))
    back = D.from_dict(D.as_dict(pol))
    assert back.rules[0].guards[0].measured is False
    assert back.gaps == pol.gaps


def test_an_old_prose_only_artifact_refuses_rather_than_guessing():
    """Parsing the prose back would work until a threshold contained a space."""
    with pytest.raises(ValueError, match="Recompile it"):
        D.from_dict({"family": "f", "default": ["api"],
                      "rules": [{"when": ["inflight < 8.0 (from a probe)"], "assign": ["box"]}]})
