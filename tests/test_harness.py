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
from tierbook.evidence import (ABSENCE_REASONS, COLLECTION_STATUS, DIGEST_BOUNDARIES,  # noqa: E402
                              HARNESS_SOURCING, IDENTIFYING_BOUNDARIES, IDENTIFYING_SOURCING)

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
    assert set(full().missing) == {"turn_budget", "retry_policy", "readout", "decoding",
                                   "context_partitioning"}


def test_the_printed_form_carries_both():
    text = str(full())
    assert "unobserved" in text and "unrecorded" in text


# --- whose absence it is: a collector cannot record its own absence -------------------------------------------------------

def manifest(**kw):
    base = dict(collector="surround-shim", version="0.1", reaches=("instruction",))
    base.update(kw)
    return hn.Manifest(**base)


def test_every_absence_reason_is_classified_so_forgetting_one_is_a_failure():
    """Total on purpose. A reason added without deciding whose absence it is would default to the harmless answer, and
    the harmless answer is the one that hides a measurement failure."""
    assert set(hn.ABSENCE_BLAMES) == set(ABSENCE_REASONS)
    assert set(hn.ABSENCE_BLAMES.values()) == {"sender", "collector", "nobody"}


def test_the_senders_silence_and_our_blindness_are_different_records():
    """The defect that forced this vocabulary: both were one undifferentiated hole, so a shim losing the ability to read
    a part was indistinguishable from a sender that sent nothing."""
    assert hn.Absence(kind="decoding", reason="not_provided").blames == "sender"
    ours = hn.Absence(kind="decoding", reason="not_reachable", detail="SDK renamed the sampling block")
    assert ours.blames == "collector"


def test_our_own_failure_has_to_say_what_we_were_doing():
    with pytest.raises(hn.Unidentified, match="nobody can fix"):
        hn.Absence(kind="decoding", reason="extraction_failed")


def test_a_detail_is_refused_where_there_was_no_moment_to_describe():
    with pytest.raises(hn.Unidentified, match="no such moment"):
        hn.Absence(kind="decoding", reason="not_provided", detail="we were busy")


def test_a_reachable_part_cannot_be_recorded_as_structurally_invisible():
    """The direction that matters: it makes a collector's failure look like a fact about the world."""
    with pytest.raises(hn.Unidentified, match="structurally invisible"):
        hn.Absence(kind="decoding", reason="not_observable")


def test_an_unobservable_part_cannot_be_blamed_on_anybody():
    with pytest.raises(hn.Unidentified, match="claims somebody"):
        hn.Absence(kind="tool_behaviour", reason="not_provided")


def test_an_absence_of_something_the_vocabulary_does_not_name_is_refused():
    with pytest.raises(hn.Unidentified, match="hole in the vocabulary"):
        hn.Absence(kind="temperature_schedule", reason="not_provided")


# --- the manifest, so that not_reachable is checkable rather than merely spelled -------------------------------------------

def test_a_manifest_needs_a_collector_and_a_version():
    with pytest.raises(hn.Unidentified, match="nobody can attribute"):
        manifest(version="")


def test_a_manifest_cannot_claim_a_part_no_mode_reaches():
    """A collector claiming an impossible part reports a contradiction on every run it ever produces, which trains a
    reader to ignore the one signal this structure raises."""
    with pytest.raises(hn.Unidentified, match="no mode reaches"):
        manifest(reaches=("instruction", "tool_behaviour"))


def test_a_manifest_cannot_claim_an_unknown_part():
    with pytest.raises(hn.Unidentified, match="not parts in"):
        manifest(reaches=("instruction", "vibes"))


# --- the collection: permissive toward the sender, exact about itself ------------------------------------------------------

def test_a_record_with_one_part_is_valid_and_names_what_it_lacks():
    """The permissive half. A collector that refused a partial record would produce no record, and a run that emitted
    nothing is indistinguishable from a run that emitted a perfect record of nothing."""
    coll = hn.Collection(manifest=manifest(), harness=hn.Harness(parts=(part(),)))
    assert coll.admissible_to_a_verdict() is True
    assert "tool_schemas" in coll.unaccounted and "decoding" in coll.unaccounted


def test_a_record_with_nothing_identifying_still_exists_and_supports_no_claim():
    coll = hn.Collection(manifest=manifest(reaches=()), harness=None)
    assert coll.admissible_to_a_verdict() is False
    assert "the same for every" in coll.why_not()


def test_a_collector_that_died_cannot_present_its_failure_as_the_senders_silence():
    """The exact half. Fully usable as a log, refused by anything that publishes a claim."""
    coll = hn.Collection(manifest=manifest(), status="collector_failed",
                         harness=hn.Harness(parts=(part(),)))
    assert coll.admissible_to_a_verdict() is False
    assert "does not describe the run" in coll.why_not()
    assert set(COLLECTION_STATUS) == {"complete", "aborted", "collector_failed"}


def test_a_manifest_claiming_a_part_the_record_lacks_is_a_contradiction_not_a_fact():
    """The one alarm this structure exists to raise. The absence is spelled exactly the way a legitimate one is, so it
    is invisible in every other reading."""
    coll = hn.Collection(
        manifest=manifest(reaches=("instruction", "decoding")),
        harness=hn.Harness(parts=(part(),)),
        absences=(hn.Absence(kind="decoding", reason="not_reachable", detail="SDK renamed the sampling block"),))
    assert coll.contradictions == ("decoding",)
    assert coll.admissible_to_a_verdict() is False
    assert "did not deliver" in coll.why_not()


def test_our_failures_are_separated_because_only_they_are_ours_to_fix():
    coll = hn.Collection(
        manifest=manifest(), harness=hn.Harness(parts=(part(),)),
        absences=(hn.Absence(kind="decoding", reason="not_provided"),
                  hn.Absence(kind="readout", reason="extraction_failed", detail="no letter span matched")))
    assert coll.our_failures == ("readout",)


def test_a_part_cannot_be_held_and_absent_at_once():
    with pytest.raises(hn.Unidentified, match="two ways"):
        hn.Collection(manifest=manifest(), harness=hn.Harness(parts=(part(),)),
                      absences=(hn.Absence(kind="instruction", reason="not_provided"),))


def test_two_absences_cannot_share_a_kind():
    with pytest.raises(hn.Unidentified, match="nothing says why"):
        hn.Collection(manifest=manifest(), harness=hn.Harness(parts=(part(),)),
                      absences=(hn.Absence(kind="decoding", reason="not_provided"),
                                hn.Absence(kind="decoding", reason="redacted")))


def test_unaccounted_is_not_the_same_as_absent():
    """An absence is a statement; unaccounted is the silence an absence was invented to replace."""
    coll = hn.Collection(manifest=manifest(), harness=hn.Harness(parts=(part(),)),
                         absences=(hn.Absence(kind="decoding", reason="not_provided"),))
    assert "decoding" not in coll.unaccounted
    assert "readout" in coll.unaccounted


def test_a_bad_status_is_refused():
    with pytest.raises(hn.Unidentified, match="is not one of"):
        hn.Collection(manifest=manifest(), status="probably_fine",
                      harness=hn.Harness(parts=(part(),)))


# --- a digest says which of three things it is a digest of ----------------------------------------------------------------

def test_only_the_text_the_model_read_may_key_an_identity():
    """The two mistakes run in opposite directions, so neither is fixed by being careful."""
    assert DIGEST_BOUNDARIES == ("transport", "parsed", "model_visible")
    assert IDENTIFYING_BOUNDARIES == ("model_visible",)
    with pytest.raises(hn.Unidentified, match="opposite directions"):
        part(boundary="transport")


def test_a_non_identifying_part_may_carry_any_boundary():
    """A pushed loop description is recorded and does not key the identity, so what its digest is over cannot corrupt
    a grouping."""
    p = part(kind="loop", sourcing="pushed_by_owner", label="react v3",
             digest=hn.digest_bytes("react v3"), boundary="parsed")
    assert p.identifying is False


def test_an_unknown_boundary_is_refused():
    with pytest.raises(hn.Unidentified, match="not one of"):
        part(boundary="whatever_the_sdk_sent")


def test_the_collision_is_unrepresentable_rather_than_hashed_around():
    """The first attempt at this hashed the boundary into the identity so two digests of different things could not
    collide. That is variation which cannot occur: every part that enters an identity has already been refused unless
    its boundary is `model_visible`, so the extra term was dead. The refusal is the mechanism; the hash was decoration.

    What this pins is the reachability claim -- there is no way to construct an identifying part on another boundary."""
    for boundary in DIGEST_BOUNDARIES:
        if boundary in IDENTIFYING_BOUNDARIES:
            assert part(boundary=boundary).identifying is True
        else:
            with pytest.raises(hn.Unidentified):
                part(boundary=boundary)


def test_the_default_boundary_is_the_true_statement_about_existing_callers():
    """Every caller before this field hashed the text the model read, so the default is honest rather than convenient."""
    assert part().boundary == "model_visible"
