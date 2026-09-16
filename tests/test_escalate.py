"""Tests for the re-issue.

Every refusal here corresponds to an accident that was either measured on two real servers or is one the same run
would have hit at the next hop. A loop and a double charge are both cheap to detect after the fact and expensive to
have happened, so each is refused at construction instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import escalate as e  # noqa: E402


def esc(**kw):
    base = dict(parent_request_id="req-7", decision_id="dec-3f9c", policy_version="prefill-gate/0.1",
                target_profile="upper", hop_count=1)
    base.update(kw)
    return e.Escalation(**base)


# --- attribution -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["parent_request_id", "decision_id", "policy_version", "target_profile"])
def test_an_escalation_that_cannot_be_joined_to_its_cause_is_refused(field):
    """An outcome nothing can attribute is an outcome nothing can learn from, which is the only reason to record an
    escalation."""
    with pytest.raises(e.Untraceable, match="credited or blamed"):
        esc(**{field: ""})


@pytest.mark.parametrize("addr", ["10.0.8.64:8001", "upper:8001", "127.0.0.1"])
def test_a_target_that_looks_like_an_address_is_refused(addr):
    """The cheap side returns an action, not a destination. Naming an address is how a gate quietly becomes a second
    router, duplicating the endpoint selection the standard mechanism already performs."""
    with pytest.raises(e.Untraceable, match="becomes a second router"):
        esc(target_profile=addr)


def test_a_profile_is_a_class_of_candidate_not_a_place():
    assert esc(target_profile="upper").target_profile == "upper"
    assert esc(target_profile="reasoning-capable").headers()["x-tb-target-profile"] == "reasoning-capable"


# --- the hop bound -----------------------------------------------------------------------------------------------

def test_hop_zero_is_not_an_escalation():
    """The original request is hop zero. Allowing it here would let a first attempt be recorded as a re-issue, and
    then the bound counts one hop that never happened."""
    with pytest.raises(e.Loop, match="is not a hop"):
        esc(hop_count=0)


def test_the_bound_is_enforced_rather_than_logged():
    with pytest.raises(e.Loop, match="paper trail"):
        esc(hop_count=e.MAX_HOPS + 1)


@pytest.mark.parametrize("bad", [1.0, "1", True, None])
def test_a_depth_that_cannot_be_compared_cannot_bound(bad):
    with pytest.raises(e.Loop, match="cannot bound"):
        esc(hop_count=bad)


# --- the derived key ---------------------------------------------------------------------------------------------

def test_two_attempts_at_one_escalation_share_a_key():
    """A retry is not a second escalation. The key is derived from the parent and the hop, so two tries collide by
    construction and the ledger sees one decision with two attempts."""
    assert esc().idempotency_key == esc(decision_id="dec-other").idempotency_key


def test_two_different_escalations_do_not_share_a_key():
    assert esc(parent_request_id="req-7").idempotency_key != esc(parent_request_id="req-8").idempotency_key
    a = e.next_hop(esc(), parent_request_id="req-7", decision_id="d", policy_version="p", target_profile="best")
    assert a.idempotency_key != esc().idempotency_key


def test_the_key_is_not_a_field_the_caller_can_vary():
    """A key the caller supplies is a key a retry varies, and then one escalation is billed twice. There is no
    parameter for it."""
    with pytest.raises(TypeError):
        e.Escalation(parent_request_id="r", decision_id="d", policy_version="p", target_profile="upper",
                     hop_count=1, idempotency_key="chosen-by-me")


# --- chaining ----------------------------------------------------------------------------------------------------

def test_the_first_hop_needs_no_previous():
    first = e.next_hop(None, parent_request_id="req-7", decision_id="d", policy_version="p", target_profile="upper")
    assert first.hop_count == 1


def test_the_depth_is_derived_rather_than_asserted():
    first = e.next_hop(None, parent_request_id="req-7", decision_id="d", policy_version="p", target_profile="upper")
    second = e.next_hop(first, parent_request_id="req-7", decision_id="d", policy_version="p", target_profile="best")
    assert (first.hop_count, second.hop_count) == (1, 2)
    with pytest.raises(e.Loop, match="exceeds MAX_HOPS"):
        e.next_hop(second, parent_request_id="req-7", decision_id="d", policy_version="p", target_profile="beyond")


def test_repeating_the_profile_that_just_declined_is_refused_as_a_cycle():
    """The hop bound would stop this eventually, one paid attempt at a time. Refusing the repeat stops it now."""
    first = e.next_hop(None, parent_request_id="req-7", decision_id="d", policy_version="p", target_profile="upper")
    with pytest.raises(e.Loop, match="Repeating a stage"):
        e.next_hop(first, parent_request_id="req-7", decision_id="d", policy_version="p", target_profile="upper")


def test_a_chain_whose_links_name_different_parents_is_refused():
    first = e.next_hop(None, parent_request_id="req-7", decision_id="d", policy_version="p", target_profile="upper")
    with pytest.raises(e.Loop, match="two chains"):
        e.next_hop(first, parent_request_id="req-9", decision_id="d", policy_version="p", target_profile="best")


# --- commit semantics --------------------------------------------------------------------------------------------

def test_the_buyer_declares_whether_a_late_escalation_may_replace_an_answer():
    """Generation length is known only while decoding, by which point output may be streaming. Which of these
    applies is a declaration rather than a detail, so an unknown value is refused."""
    assert esc(commit_semantics="early").commit_semantics == "early"
    with pytest.raises(e.Untraceable, match="declaration the buyer makes"):
        esc(commit_semantics="whatever")


# --- reading the action out of the body ---------------------------------------------------------------------------

def test_the_sentinel_is_read_as_an_escalation():
    assert e.action_from_body(f"some prose {e.SENTINEL}") == "escalate"


def test_an_empty_completion_is_not_read_as_an_escalation():
    """It cannot be told apart from a request the model answered with nothing. A run that relied on it reported the
    right count for the wrong reason, so the ambiguous case is not silently claimed."""
    assert e.action_from_body("") == "commit"
    assert e.action_from_body("   \n ") == "commit"


def test_the_sentinel_is_multi_token_on_purpose():
    """No single rare token was available: four candidates each failed to be one token in a 248,320-entry
    vocabulary. A one-character sentinel here would be a design that only works on some tokenizers."""
    assert len(e.SENTINEL) > 4 and e.SENTINEL.isupper() or "_" in e.SENTINEL


def test_the_workaround_states_what_would_replace_it():
    """A workaround presented without its replacement gets mistaken for the design."""
    ask = e.upstream_ask()
    assert "response metadata" in ask and "248,320" in ask


# --- the wire ----------------------------------------------------------------------------------------------------

def test_the_header_names_are_fixed_so_both_sides_read_the_same_ones():
    h = esc().headers()
    assert set(h) == {"x-tb-parent-request-id", "x-tb-decision-id", "x-tb-policy-version",
                      "x-tb-target-profile", "x-tb-hop-count", "x-tb-idempotency-key"}
    assert h["x-tb-hop-count"] == "1"
    assert h["x-tb-idempotency-key"] == esc().idempotency_key
