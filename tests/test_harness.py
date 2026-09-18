"""Tests for identifying what surrounds the model, and for being honest about what cannot be seen.

The measurement this module exists for: same box, same 1,187 items, and only the instruction changed -- 0.6243 terse
against 0.7447 explaining, with per-item agreement 0.7346, so one item in four flips. Twelve points from one sentence,
against a best routing saving of 7.9% that fell to 1.0% once the items were matched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import harness as hn  # noqa: E402
from tierbook.evidence import HARNESS_SOURCING, IDENTIFYING_SOURCING  # noqa: E402

TERSE = "Answer with the option letter only. Do not explain."
EXPLAIN = "Think step by step, then answer with the option letter."


def part(**kw):
    base = dict(kind="instruction", sourcing="in_the_request", label="terse", digest=hn.digest_bytes(TERSE))
    base.update(kw)
    return hn.Part(**base)


def full(instruction=TERSE):
    return hn.Harness(parts=(
        part(digest=hn.digest_bytes(instruction)),
        part(kind="tool_schemas", label="", digest=hn.digest_bytes("{search,fetch}")),
        part(kind="tool_behaviour", sourcing="not_observable", label="", digest=""),
        part(kind="loop", sourcing="pushed_by_owner", label="react v3", digest=hn.digest_bytes("react v3")),
    ))


# --- every part is classified for how it can be reached -------------------------------------------------------------------

def test_every_part_is_classified_so_forgetting_one_is_a_failure():
    """Total on purpose: adding a part without deciding how it is observed breaks this rather than defaulting the new
    part to observable."""
    assert set(hn.BEST_AVAILABLE_SOURCING) == set(hn.HARNESS_PARTS)
    assert set(hn.BEST_AVAILABLE_SOURCING.values()) <= set(HARNESS_SOURCING)


def test_a_tools_behaviour_is_structurally_unobservable_and_that_is_the_finding():
    """Its schema is in the request and its behaviour is not, so a change behind an unchanged schema is invisible from
    the bytes we hold."""
    assert hn.BEST_AVAILABLE_SOURCING["tool_behaviour"] == "not_observable"
    assert hn.BEST_AVAILABLE_SOURCING["tool_schemas"] == "in_the_request"
    with pytest.raises(hn.Unidentified, match="invisible from the bytes"):
        part(kind="tool_behaviour", sourcing="in_the_request", label="", digest="a" * 64)


def test_only_bytes_we_hold_may_key_an_identity():
    assert IDENTIFYING_SOURCING == ("in_the_request",)
    assert part().identifying is True
    assert part(kind="loop", sourcing="pushed_by_owner", label="x", digest="a" * 64).identifying is False


# --- a label is not the key -----------------------------------------------------------------------------------------------

def test_a_part_identified_by_a_label_alone_is_refused():
    """A version string the owner controls can stay v3 while the text under it changes. This project has that failure
    recorded twice already -- for a model name and for a prompt condition."""
    with pytest.raises(hn.Unidentified, match="label can stay fixed"):
        part(digest="")


def test_the_digest_is_over_bytes_and_an_empty_payload_is_refused():
    """A part that is genuinely empty is a part that was not applied, which is a different record."""
    assert hn.digest_bytes(TERSE) != hn.digest_bytes(EXPLAIN)
    for empty in ("", "   ", "\n"):
        with pytest.raises(hn.Unidentified, match="was not applied"):
            hn.digest_bytes(empty)


def test_an_unobservable_part_may_not_carry_a_digest():
    """If bytes exist, name the mode that produced them."""
    with pytest.raises(hn.Unidentified, match="something was hashed"):
        part(kind="tool_behaviour", sourcing="not_observable", label="", digest="a" * 64)


# --- a pulled fact carries its lag ----------------------------------------------------------------------------------------

def test_a_pulled_fact_without_its_lag_is_refused():
    """We read at one moment and the request ran at another; everything that changed inside that gap is invisible."""
    with pytest.raises(hn.Unidentified, match="lag nobody wrote down"):
        part(kind="loop", sourcing="pulled_by_us", label="x", digest="a" * 64)
    ok = part(kind="loop", sourcing="pulled_by_us", label="x", digest="a" * 64, read_lag_seconds=12.0)
    assert ok.read_lag_seconds == 12.0


def test_only_a_pulled_fact_has_a_lag():
    """Bytes in the request have no lag by definition, and a pushed claim's timing is the owner's word."""
    with pytest.raises(hn.Unidentified, match="only a pulled fact has"):
        part(read_lag_seconds=5.0)


def test_a_negative_lag_would_mean_it_was_read_after_the_request():
    with pytest.raises(hn.Unidentified, match="after the request"):
        part(kind="loop", sourcing="pulled_by_us", label="x", digest="a" * 64, read_lag_seconds=-1.0)


# --- the harness's identity is derived ------------------------------------------------------------------------------------

def test_the_identity_cannot_be_supplied():
    with pytest.raises(TypeError):
        hn.Harness(parts=(part(),), identity="v3")


def test_changing_the_instruction_changes_the_identity():
    assert full(TERSE).identity != full(EXPLAIN).identity


def test_the_owners_description_of_their_own_loop_does_not_move_the_identity():
    """A name that moved when the owner edited a sentence about themselves would not group anything."""
    a = full()
    b = hn.Harness(parts=tuple(
        part(kind="loop", sourcing="pushed_by_owner", label="react v4", digest=hn.digest_bytes("react v4"))
        if p.kind == "loop" else p for p in a.parts))
    assert a.identity == b.identity


def test_a_harness_with_nothing_we_hold_bytes_for_is_refused():
    """Its identity would be constant across every possible harness."""
    with pytest.raises(hn.Unidentified, match="constant across every possible harness"):
        hn.Harness(parts=(part(kind="loop", sourcing="pushed_by_owner", label="x", digest="a" * 64),
                          part(kind="tool_behaviour", sourcing="not_observable", label="", digest="")))


def test_two_parts_of_one_kind_leave_nothing_saying_which_applied():
    with pytest.raises(hn.Unidentified, match="which one applied"):
        hn.Harness(parts=(part(), part(label="also terse")))


def test_an_empty_harness_is_the_absence_of_a_record():
    with pytest.raises(hn.Unidentified, match="absence of a record"):
        hn.Harness(parts=())


# --- what it reports rather than hides ------------------------------------------------------------------------------------

def test_the_unobserved_parts_are_reported():
    """A record that hid them would look complete."""
    assert set(full().unobserved) == {"tool_behaviour", "loop"}


def test_the_parts_nothing_was_recorded_about_are_reported_too():
    assert set(full().missing) == {"turn_budget", "retry_policy", "readout", "decoding"}


def test_the_printed_form_carries_both():
    text = str(full())
    assert "unobserved" in text and "unrecorded" in text
