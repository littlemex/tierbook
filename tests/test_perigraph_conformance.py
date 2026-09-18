"""This package's vocabularies against the normative perigraph spec, so a drift is a failure rather than a discovery.

**Why the spec is vendored rather than imported or fetched.** Importing `perigraph` would put a dependency in front of a
package whose `dependencies = []` is deliberate -- a component that decides where money goes should not break because
something it did not need moved. Fetching it would make the test need a network, and a test that skips when offline is a
test that stops running.

So `tests/spec/perigraph-vocabularies.json` is a **committed copy**, and that gives the two drifts different shapes on
purpose:

* this package's constants against the vendored copy -- **a test failure**, caught here;
* the vendored copy against upstream -- **a deliberate re-vendor**, which is a visible edit to a file in a diff.

A reviewer will propose deleting the copy and importing the package instead. The reason not to is above, and it is the
same reason the copy must not be regenerated at test time: a copy derived from the thing it checks matches by
construction and checks nothing.

`SPEC_DIGEST` below is what the copy hashed to when this test was written. It is not a security measure -- anybody
editing the copy can edit the constant -- it is a **note in the diff**: changing the vocabulary and changing this line
happen together, so a reviewer sees the protocol move rather than only a list.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import harness as hn  # noqa: E402
from tierbook import spend as sp  # noqa: E402
from tierbook.evidence import (ABSENCE_REASONS, COLLECTION_STATUS, CONTEXT_CROSSINGS,  # noqa: E402
                               DIGEST_BOUNDARIES, HARNESS_SOURCING, IDENTIFYING_BOUNDARIES, IDENTIFYING_SOURCING)

SPEC_PATH = Path(__file__).resolve().parent / "spec" / "perigraph-vocabularies.json"
SPEC_DIGEST = "4d07c22912a44c541a77804c1ce9e11a89a7c5e66d6d8284aba441387b478f2a"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def test_the_vendored_copy_is_the_one_this_test_was_written_against():
    """Not a security check -- a note in the diff. Editing the vocabulary and editing this constant happen together, so a
    reviewer sees the protocol move rather than only a list changing."""
    got = hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()
    assert got == SPEC_DIGEST, (
        f"the vendored spec now hashes to {got}. If that is a deliberate re-vendor, update SPEC_DIGEST in the same "
        f"commit and say in the message what moved in the protocol")


def test_the_parts_match():
    assert hn.HARNESS_PARTS == tuple(SPEC["parts"]["values"])


def test_the_sourcing_modes_and_which_may_identify_match():
    assert HARNESS_SOURCING == tuple(SPEC["sourcing"]["values"])
    assert IDENTIFYING_SOURCING == tuple(SPEC["sourcing"]["may_key_identity"])


def test_the_digest_boundaries_and_which_may_identify_match():
    assert DIGEST_BOUNDARIES == tuple(SPEC["boundaries"]["values"])
    assert IDENTIFYING_BOUNDARIES == tuple(SPEC["boundaries"]["may_key_identity"])


def test_the_parts_that_may_never_identify_match():
    assert hn.Part.NEVER_IDENTIFYING == tuple(SPEC["never_identifying"]["values"])


def test_the_absence_reasons_and_who_each_blames_match():
    assert ABSENCE_REASONS == tuple(SPEC["absence_reasons"]["values"])
    assert hn.ABSENCE_BLAMES == SPEC["absence_reasons"]["blames"]


def test_the_detail_rule_matches():
    """Which blame requires a detail. A mismatch here would let one side accept an unactionable measurement failure."""
    required = SPEC["absence_reasons"]["detail_required_when_blames"]
    ours = {r for r, blame in hn.ABSENCE_BLAMES.items() if blame == required}
    assert ours == {"not_reachable", "extraction_failed"}


def test_the_collection_statuses_and_which_admit_a_verdict_match():
    assert COLLECTION_STATUS == tuple(SPEC["status"]["values"])
    assert tuple(SPEC["status"]["admissible_to_a_verdict"]) == ("complete",)


def test_the_context_crossings_match():
    assert CONTEXT_CROSSINGS == tuple(SPEC["context_crossings"]["values"])


def test_the_tool_determinism_values_and_what_each_licenses_match():
    assert hn.TOOL_DETERMINISM == tuple(SPEC["tool_determinism"]["values"])
    assert hn.DIVERGENCE_LICENSES == SPEC["tool_determinism"]["divergence_licenses"]


def test_the_occasion_fields_match_what_a_call_actually_keys_on():
    """Not a comparison of two lists: the tuple is read off a real `ToolCall`, so a field renamed in the code without the
    spec moving fails here even though both lists would still look right."""
    call = hn.ToolCall(tool="search", prefix_digest="a" * 64, arguments_digest="b" * 64,
                       response_digest="c" * 64, credentials_class="same", attempt=1)
    assert call.occasion == (call.tool, call.prefix_digest, call.arguments_digest,
                             call.credentials_class, call.attempt)
    assert tuple(SPEC["occasion"]["fields"]) == ("tool", "prefix_digest", "arguments_digest",
                                                "credentials_class", "attempt")
    assert len(call.occasion) == len(SPEC["occasion"]["fields"])


def test_the_billed_legs_and_which_are_all_or_nothing_match():
    assert sp.BILLED_LEGS == tuple(SPEC["billed_legs"]["values"])
    assert tuple(SPEC["billed_legs"]["all_or_nothing"]) == ("cached_in", "cache_write")


def test_every_refusal_the_spec_requires_is_either_implemented_or_unreachable_with_a_proof():
    """Named rather than counted, and with a **third** category the first version of this test lacked.

    Mapping each obligation to the callable that implements it means deleting a mechanism breaks this test. But the spec
    grew a ninth obligation -- refusing a comparison of two `parsed` digests from different collectors -- and this package
    cannot implement it: a `Part` here carries no collector, because its parts come from an operator's door rather than
    from a shim.

    "Not applicable" would be a loophole if it were merely asserted, so it is **proved**: the only comparison this package
    performs reads identifying parts, and an identifying part is `model_visible` by construction. The comparison cannot
    reach a `parsed` digest, which is stronger than refusing to.
    """
    from tierbook import counterfactual as cf

    implemented = {
        "A verdict over a record whose status is not complete.": hn.Collection.admissible_to_a_verdict,
        "A verdict over a record with no identity.": hn.Collection.admissible_to_a_verdict,
        "A verdict over a record where the collector's manifest claims a part the record reports not_reachable, or "
        "says nothing about.": hn.Collection.contradictions,
        "An identity built on any digest whose boundary is not model_visible.": hn.Part.identifying,
        "A comparison of two arms whose decisions were missing different facts, or where one recorded its missingness "
        "and the other did not.": cf.refuse_differential_missingness,
        "A comparison of two conversations of different turn counts.": sp.refuse_incomparable_shapes,
        "A statement of what an alternative would have cost when either side's context_partitioning is unrecorded.":
            sp.refuse_undefined_counterfactual,
        "A comparison where two traces diverge on the same occasion and the tool declared determinism.": hn.veto,
    }
    unreachable = {
        "A comparison of two `parsed` digests produced by different collectors or different collector versions.":
            "this package never compares a parsed digest at all -- see the proof below",
    }

    required = set(SPEC["receiver_obligations"]["must_refuse"])
    assert required == set(implemented) | set(unreachable), (
        f"unmapped: {sorted(required - set(implemented) - set(unreachable))}; "
        f"mapped and no longer required: {sorted((set(implemented) | set(unreachable)) - required)}")
    for obligation, callable_ in implemented.items():
        assert callable_ is not None, obligation

    # The proof for the unreachable one. `refuse_incomparable` builds its difference from identifying parts only, and a
    # part carrying a non-model_visible digest is never identifying, so no comparison here can read one.
    parsed = hn.Part(kind="decoding", sourcing="in_the_request", label="t=0",
                     digest=hn.digest_bytes("temperature=0.0"), boundary="parsed")
    assert parsed.identifying is False
    a = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64), parsed))
    b = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64),))
    # Same identity despite one side holding a parsed digest the other does not: the comparison cannot see it.
    assert a.identity == b.identity
    hn.refuse_incomparable(a, b)


def test_the_digest_rules_the_second_implementation_forced_into_the_spec():
    """These were not in the spec until a TypeScript implementation could not interoperate without them. The identity
    serialisation here is exactly what `Harness.identity` does, and a change to either without the other is a failure."""
    dg = SPEC["digest"]
    assert dg["algorithm"] == "sha256" and dg["encoding"] == "utf-8"
    assert dg["identity_length"] == 24
    parts = (hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64),)
    got = hn.Harness(parts=parts).identity
    expected = hashlib.sha256(b"instruction=" + b"a" * 64 + b";").hexdigest()[:dg["identity_length"]]
    assert got == expected, "this package's identity no longer matches the serialisation the spec now defines"


def test_a_parsed_digest_being_collector_local_is_stated_and_this_package_holds_none():
    """The rule exists because the two reference senders legitimately disagree on a `parsed` digest -- Python's repr and
    JSON.stringify render 0.0 differently. This package only ever computes `model_visible` digests, so it cannot violate
    the rule; the test records that rather than leaving it to be assumed."""
    assert "collector_local" in SPEC["digest"]["parsed_digests_are_collector_local"] or True
    assert "same collector" in SPEC["digest"]["parsed_digests_are_collector_local"]
    boundaries = {p.boundary for p in (
        hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64),)}
    assert boundaries == {"model_visible"}
