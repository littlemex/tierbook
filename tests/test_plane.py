"""Tests for the outcome plane.

The defect every refusal here closes is the same one, seen from a different side: a system that works, performs
plausibly, and decides differently when the same traffic is replayed. There is no error and no log line for that,
which is why each check happens at registration or construction rather than at replay.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import plane as p  # noqa: E402


def out(**kw):
    base = dict(request_id="req-7", decision_id="dec-3f9c", policy_version="gate/0.1", terminal_state="answered",
                correct=True, cost_usd=0.004, latency_s=1.8)
    base.update(kw)
    return p.Outcome(**base)


def cal(**kw):
    base = dict(constants={"threshold": 0.62}, built_from=("2026-09-01", "2026-09-08"), observation_count=253)
    base.update(kw)
    return p.Calibration(**base)


# --- an outcome names what it judges -----------------------------------------------------------------------------

@pytest.mark.parametrize("f", ["request_id", "decision_id", "policy_version"])
def test_an_unattributable_outcome_is_refused(f):
    """Worse than a missing one: it still counts in every rate computed over the log."""
    with pytest.raises(p.Unreplayable, match="worse than a missing one"):
        out(**{f: ""})


def test_an_open_ended_terminal_state_is_refused():
    with pytest.raises(p.Unreplayable, match="cannot be grouped over"):
        out(terminal_state="finished-ish")


def test_unobserved_is_a_first_class_outcome():
    """A request whose fate is unknown must be representable, or it is recorded as a failure and biases every rate."""
    assert out(terminal_state="unobserved", correct=None).terminal_state == "unobserved"


def test_unobserved_with_a_known_correctness_is_a_contradiction():
    """Recording both is how an unobserved request gets counted as a labelled one."""
    with pytest.raises(p.Unreplayable, match="contradict"):
        out(terminal_state="unobserved", correct=False)


# --- the observer cannot reach what it observes -------------------------------------------------------------------

@pytest.mark.parametrize("handle", p.FORBIDDEN_HANDLES)
def test_an_observer_that_can_reach_the_live_policy_is_refused(handle):
    """An observer adjusting a live threshold makes decision N depend on how many outcomes arrived before it, which
    is network timing. The system still works; it just stops being replayable."""
    ns: dict = {}
    exec(f"def watch(observation, {handle}): pass", ns)
    with pytest.raises(p.Unreplayable, match="stops reproducing the decisions"):
        p.register(ns["watch"])


def test_the_check_is_case_insensitive():
    def watch(observation, Scorer): pass  # noqa: N803
    with pytest.raises(p.Unreplayable, match="stops reproducing"):
        p.register(watch)


def test_an_observer_accepting_anything_defeats_the_check_and_is_refused():
    """A signature that accepts **kwargs is a signature that accepts a policy, so the inspection above sees
    nothing."""
    def watch(observation, **kw): pass
    with pytest.raises(p.Unreplayable, match=r"\*\*kwargs"):
        p.register(watch)


def test_a_plain_appending_observer_is_accepted():
    def watch(observation): pass
    p.register(watch)


def test_something_that_is_not_callable_is_refused():
    """The plane would be silently empty rather than wrong, which is harder to notice."""
    with pytest.raises(p.Unreplayable, match="silently empty"):
        p.register({"not": "callable"})


def test_a_callable_with_no_signature_is_refused_rather_than_trusted():
    """A C callable exposes nothing to inspect, so the handle check above cannot run on it at all. Admitting one is
    admitting an observer on trust, which is the thing being refused rather than an inconvenience."""
    with pytest.raises(p.Unreplayable, match="trust is what this refuses"):
        p.register(map)


# --- the snapshot is immutable and its name is derived ------------------------------------------------------------

def test_the_snapshot_id_cannot_be_supplied():
    """An id somebody supplies is an id somebody keeps after changing the contents, and then two different sets of
    numbers wear one name."""
    with pytest.raises(TypeError):
        p.Calibration(constants={"threshold": 0.62}, built_from=("a", "b"), observation_count=1,
                      snapshot_id="v1")


def test_changing_a_constant_changes_the_name():
    assert cal().snapshot_id != cal(constants={"threshold": 0.63}).snapshot_id


def test_changing_the_range_or_the_count_changes_the_name():
    assert cal().snapshot_id != cal(built_from=("2026-09-01", "2026-09-09")).snapshot_id
    assert cal().snapshot_id != cal(observation_count=254).snapshot_id


def test_the_name_is_stable_for_the_same_contents():
    assert cal().snapshot_id == cal().snapshot_id
    assert cal(constants={"threshold": 0.62}).snapshot_id == cal(constants={"threshold": 0.62}).snapshot_id


def test_an_open_ended_range_is_refused_because_it_cannot_be_rebuilt():
    """'Everything up to now' cannot be rebuilt, because now has moved, so no claim made from it can be rechecked."""
    with pytest.raises(p.Unreplayable, match="cannot be rebuilt"):
        cal(built_from=("2026-09-01", ""))
    with pytest.raises(p.Unreplayable, match="runs backwards"):
        cal(built_from=("2026-09-08", "2026-09-01"))


def test_an_empty_snapshot_is_refused_because_a_policy_would_use_defaults():
    with pytest.raises(p.Unreplayable, match="nobody measured"):
        cal(constants={})


def test_a_snapshot_over_no_observations_is_refused():
    with pytest.raises(p.Unreplayable, match="came from somewhere other than"):
        cal(observation_count=0)


def test_a_constant_the_snapshot_lacks_is_refused_rather_than_defaulted():
    assert cal().constant("threshold") == 0.62
    with pytest.raises(p.Unreplayable, match="cannot account for"):
        cal().constant("amplitude")


# --- one policy version, one snapshot ------------------------------------------------------------------------------

def test_a_version_that_read_two_snapshots_is_refused():
    """The check the module builds towards: two decisions credited to one policy, made with different constants, so
    any rate over that version is over a mixture."""
    readings = [p.Reading(policy_version="gate/0.1", snapshot_id="aaa"),
                p.Reading(policy_version="gate/0.1", snapshot_id="bbb")]
    with pytest.raises(p.Unreplayable, match="over a mixture"):
        p.refuse_drift(readings)


def test_two_versions_reading_two_snapshots_is_exactly_right():
    """Bumping the version when the snapshot changes is the intended shape, not a workaround."""
    p.refuse_drift([p.Reading(policy_version="gate/0.1", snapshot_id="aaa"),
                    p.Reading(policy_version="gate/0.2", snapshot_id="bbb"),
                    p.Reading(policy_version="gate/0.1", snapshot_id="aaa")])


def test_a_reading_needs_both_halves():
    with pytest.raises(p.Unreplayable, match="leaves the other unknowable"):
        p.Reading(policy_version="gate/0.1", snapshot_id="")


# --- the store appends, and reports its own lag -------------------------------------------------------------------

def test_the_store_appends_and_refuses_a_loose_dict():
    s = p.Store()
    s.append(out())
    assert len(s.observations) == 1
    with pytest.raises(p.Unreplayable, match="never checked"):
        s.append({"request_id": "req-8"})


def test_the_lag_is_reported_rather_than_hidden():
    """The separation costs something real: an outcome observed now changes nothing until the next snapshot. A number
    naming that lag is what lets somebody choose the rebuild cadence instead of assuming the loop is closed."""
    s = p.Store()
    live = cal(observation_count=2)
    for i in range(5):
        s.append(out(request_id=f"req-{i}"))
    assert s.staleness(live_snapshot=live) == 3


def test_the_lag_is_never_negative():
    """A snapshot built from a longer history than this store holds is normal -- the store may be a window -- and
    must not report a negative lag that a caller would compare against a threshold."""
    assert p.Store().staleness(live_snapshot=cal(observation_count=253)) == 0
