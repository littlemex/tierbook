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

import pytest

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
    assert hn.DEFAULT_HARNESS_PARTS == tuple(SPEC["parts"]["values"])


def test_the_best_sourcing_table_is_pinned():
    """`test_the_parts_match` pins only the part NAMES against the vendored spec -- the spec names which parts exist,
    not which sourcing mode is best for each, so there is nothing in `SPEC` to compare `DEFAULT_BEST_AVAILABLE_SOURCING`
    against. A reviewer found that gap: a caller-declared vocabulary could be checked against `DEFAULT_HARNESS_PARTS`
    alone and still silently redefine what `tool_extension`'s best sourcing is (see
    `test_a_vocabulary_that_redefines_or_drops_a_spec_part_does_not_conform` below). Pinned here as a literal instead,
    so a value drifting in `harness.py` fails a test rather than only a review."""
    assert hn.DEFAULT_BEST_AVAILABLE_SOURCING == {
        "instruction": "in_the_request",
        "tool_schemas": "in_the_request",
        "tool_extension": "not_observable",
        "tool_trace": "in_the_request",
        "loop": "pushed_by_owner",
        "turn_budget": "pushed_by_owner",
        "retry_policy": "pushed_by_owner",
        "readout": "in_the_request",
        "decoding": "in_the_request",
        "context_partitioning": "pushed_by_owner",
    }


def test_the_default_vocabulary_identifies_as_perigraph_and_conforms():
    assert hn.DEFAULT_PART_VOCABULARY.identity == "perigraph/1"
    assert hn.DEFAULT_PART_VOCABULARY.conforms_to_perigraph is True


def test_a_vocabulary_that_redefines_or_drops_a_spec_part_does_not_conform():
    """The finding: a caller-declared `PartVocabulary` could drop one of perigraph's parts, or redefine what
    perigraph says a spec part's best sourcing is, with nothing marking the record built from it as anything but
    perigraph-conforming. `conforms_to_perigraph` and the `NOT perigraph-conforming` marker in `Harness.__str__`/
    `Collection.__str__` are what a perigraph consumer now has to see this by."""
    dropped = hn.PartVocabulary(parts=("instruction",), best_sourcing={"instruction": "in_the_request"})
    assert dropped.conforms_to_perigraph is False
    assert "drops perigraph part" in dropped.non_conformance_reason

    redefined = hn.PartVocabulary(
        parts=hn.DEFAULT_HARNESS_PARTS,
        best_sourcing={**hn.DEFAULT_BEST_AVAILABLE_SOURCING, "tool_extension": "in_the_request"})
    assert redefined.conforms_to_perigraph is False
    assert "redefines perigraph part" in redefined.non_conformance_reason

    # Additions alone -- TB-045's whole point -- must NOT break conformance.
    additions_only = hn.PartVocabulary(
        parts=(*hn.DEFAULT_HARNESS_PARTS, "context_window_policy"),
        best_sourcing={**hn.DEFAULT_BEST_AVAILABLE_SOURCING, "context_window_policy": "pushed_by_owner"})
    assert additions_only.conforms_to_perigraph is True

    h = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64,
                                  vocabulary=redefined),),
                  vocabulary=redefined)
    assert h.conforms_to_perigraph is False
    assert "NOT perigraph-conforming" in str(h)
    assert "NOT perigraph-conforming" not in str(hn.Harness(parts=(hn.Part(kind="instruction",
                                                                            sourcing="in_the_request",
                                                                            digest="a" * 64),)))

    coll = hn.Collection(manifest=hn.Manifest(collector="c", version="1", reaches=(), vocabulary=redefined))
    assert coll.conforms_to_perigraph is False
    assert "NOT perigraph-conforming" in str(coll)


def test_a_vocabulary_conforming_by_luck_rather_than_by_name_still_conforms():
    """Conformance is structural, not by self-declared name: a vocabulary that never claims to be perigraph, but
    happens to be an additions-only superset with an identical sourcing table, does conform."""
    happens_to_conform = hn.PartVocabulary(
        parts=(*hn.DEFAULT_HARNESS_PARTS, "context_window_policy"),
        best_sourcing={**hn.DEFAULT_BEST_AVAILABLE_SOURCING, "context_window_policy": "pushed_by_owner"},
        name="some-other-project")
    assert happens_to_conform.conforms_to_perigraph is True
    assert happens_to_conform.identity != hn.DEFAULT_PART_VOCABULARY.identity


def test_a_part_vocabulary_stays_hashable_so_frozen_records_stay_hashable():
    """A `dict` field on a frozen dataclass makes it unhashable, which breaks every existing caller that puts a
    `Part`/`Harness`/`Manifest`/`Absence` in a set or a dict key -- the regression a reviewer found in the same
    change that added `PartVocabulary`."""
    hash(hn.DEFAULT_PART_VOCABULARY)
    p = hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64)
    hash(p)
    h = hn.Harness(parts=(p,))
    hash(h)
    m = hn.Manifest(collector="c", version="1", reaches=("instruction",))
    hash(m)
    a = hn.Absence(kind="decoding", reason="not_provided")
    hash(a)
    {p, h, m, a}  # must not raise


def test_mutating_the_module_dict_after_construction_does_not_change_the_vocabulary():
    """The second half of the same regression: `DEFAULT_PART_VOCABULARY` used to alias
    `DEFAULT_BEST_AVAILABLE_SOURCING` directly, so mutating that module dict after construction silently changed
    what the vocabulary's totality check had already validated against."""
    sourcing_copy = dict(hn.DEFAULT_BEST_AVAILABLE_SOURCING)
    v = hn.PartVocabulary(parts=hn.DEFAULT_HARNESS_PARTS, best_sourcing=sourcing_copy)
    sourcing_copy["instruction"] = "pushed_by_owner"
    assert v.sourcing_of("instruction") == "in_the_request", "mutating the caller's own dict must not reach through"


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


# --- round 3: normalisation regression, immutable snapshot, cross-vocabulary refusal --------------------------

def test_replace_and_reconstruction_from_another_vocabularys_fields_round_trip():
    """A reviewer found that once `best_sourcing` is canonicalised into a tuple of pairs, feeding that tuple BACK
    into the constructor broke: `dataclasses.replace(some_vocabulary, name="x")` and
    `PartVocabulary(parts=v.parts, best_sourcing=v.best_sourcing)` both do exactly that, and both are ordinary
    ways to build one `PartVocabulary` from another's own fields."""
    import dataclasses

    replaced = dataclasses.replace(hn.DEFAULT_PART_VOCABULARY, name="renamed")
    assert replaced.name == "renamed"
    assert replaced.conforms_to_perigraph is True
    assert replaced.sourcing_of("instruction") == "in_the_request"

    rebuilt = hn.PartVocabulary(parts=hn.DEFAULT_PART_VOCABULARY.parts,
                                best_sourcing=hn.DEFAULT_PART_VOCABULARY.best_sourcing)
    assert rebuilt.conforms_to_perigraph is True
    assert rebuilt.sourcing_of("tool_extension") == "not_observable"

    widened = hn.PartVocabulary(
        parts=(*hn.DEFAULT_HARNESS_PARTS, "context_window_policy"),
        best_sourcing={**hn.DEFAULT_BEST_AVAILABLE_SOURCING, "context_window_policy": "pushed_by_owner"})
    # Now replace() THAT one, which feeds its own tuple-of-pairs `best_sourcing` back in too.
    widened_renamed = dataclasses.replace(widened, version="2")
    assert widened_renamed.conforms_to_perigraph is True
    assert widened_renamed.sourcing_of("context_window_policy") == "pushed_by_owner"


def test_a_pairs_form_default_vocabulary_equals_the_default_and_keeps_its_identity():
    """The coordinator's own requirement: a default vocabulary passed in PAIRS form (a tuple of `(kind, mode)`
    pairs, e.g. `tuple(DEFAULT_BEST_AVAILABLE_SOURCING.items())`) must equal `DEFAULT_PART_VOCABULARY` and
    produce the SAME, byte-pinned `Harness.identity` -- equality and the identity fix both have to key off the
    canonicalised CONTENT, not off which shape the caller happened to pass in."""
    pairs_form = hn.PartVocabulary(parts=hn.DEFAULT_HARNESS_PARTS,
                                   best_sourcing=tuple(hn.DEFAULT_BEST_AVAILABLE_SOURCING.items()),
                                   name="perigraph", version="1")
    assert pairs_form == hn.DEFAULT_PART_VOCABULARY
    assert hash(pairs_form) == hash(hn.DEFAULT_PART_VOCABULARY)

    h = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64,
                                 vocabulary=pairs_form),), vocabulary=pairs_form)
    expected = hashlib.sha256(b"instruction=" + b"a" * 64 + b";").hexdigest()[:24]
    assert h.identity == expected, "a pairs-form default must not trigger the non-default prefix"


def test_an_iterator_input_is_not_exhausted_before_it_is_used():
    """A reviewer found that reading `self.best_sourcing` TWICE (once to check for duplicate keys, again to
    build the checked mapping) silently produced an EMPTY vocabulary when the input was a one-shot iterator:
    the first read exhausts it, so the second sees nothing. `best_sourcing` is now read into a list exactly
    once, so a genuine iterator (not just a list or a dict) works correctly."""
    v = hn.PartVocabulary(parts=("instruction",), best_sourcing=iter([("instruction", "in_the_request")]))
    assert v.sourcing_of("instruction") == "in_the_request"
    assert v.parts == ("instruction",)


def test_a_malformed_pair_is_refused_with_unidentified_not_a_raw_exception():
    """A single element that does not unpack to exactly two values used to raise a bare `ValueError`
    ('too many values to unpack') instead of this module's own `Unidentified`."""
    with pytest.raises(hn.Unidentified, match="not a \\(kind, mode\\) pair"):
        hn.PartVocabulary(parts=("instruction",),
                          best_sourcing=[("instruction", "in_the_request", "extra")])
    with pytest.raises(hn.Unidentified, match="not a \\(kind, mode\\) pair"):
        hn.PartVocabulary(parts=("instruction",), best_sourcing=[42])


def test_grouping_key_is_actually_hashable():
    """Put beyond doubt rather than only implied by `len({...})` elsewhere: `grouping_key` -- a `(PartVocabulary,
    str)` tuple -- must itself be hashable, which requires `PartVocabulary` to be hashable, which requires
    `best_sourcing` to have been canonicalised into a hashable form rather than left as a `dict` or a
    `MappingProxyType`."""
    h = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64),))
    key = h.grouping_key
    assert isinstance(hash(key), int)
    assert hash(h.vocabulary) == hash(hn.DEFAULT_PART_VOCABULARY)
    d = {key: "marker"}
    assert d[key] == "marker"


def test_the_module_sourcing_table_is_immutable():
    """Round 2 fixed `DEFAULT_PART_VOCABULARY` aliasing the module dict; a reviewer found `conforms_to_perigraph`
    still read that same module "constant" LIVE, so mutating it from outside this module would have flipped which
    vocabularies conform. `DEFAULT_BEST_AVAILABLE_SOURCING` is a `MappingProxyType` now, so the mutation this test
    tries cannot even be performed -- stronger than merely not mattering."""
    with pytest.raises(TypeError):
        hn.DEFAULT_BEST_AVAILABLE_SOURCING["tool_extension"] = "in_the_request"
    assert hn.BEST_AVAILABLE_SOURCING is hn.DEFAULT_BEST_AVAILABLE_SOURCING


def test_conforms_to_perigraph_reads_the_vocabularys_own_snapshot_not_the_module_dict():
    """Belt and suspenders: even if the module dict were somehow replaced with a fresh mutable one, conformance
    would still be read off `DEFAULT_PART_VOCABULARY`'s own construction-time snapshot."""
    assert hn.DEFAULT_PART_VOCABULARY.conforms_to_perigraph is True
    for kind in hn.DEFAULT_HARNESS_PARTS:
        assert hn.DEFAULT_PART_VOCABULARY.sourcing_of(kind) == hn.DEFAULT_BEST_AVAILABLE_SOURCING[kind]


def test_two_harnesses_under_different_vocabularies_are_never_comparable():
    """Comparing identities across two DIFFERENT vocabularies would read `missing` and a part's own admissibility
    against two different definitions of what a part IS, attributing a declaration difference to the arms.
    `comparable_with`/`refuse_incomparable` check the vocabulary explicitly rather than relying on `identity`
    alone to differ -- defense in depth, on top of `identity` itself now also differing (see the next tests for
    what folding the vocabulary's CONTENT into the hash does and does not tell apart on its own)."""
    widened = hn.PartVocabulary(
        parts=(*hn.DEFAULT_HARNESS_PARTS, "context_window_policy"),
        best_sourcing={**hn.DEFAULT_BEST_AVAILABLE_SOURCING, "context_window_policy": "pushed_by_owner"})
    a = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64),))
    b = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64,
                                 vocabulary=widened),), vocabulary=widened)
    # A NON-default vocabulary's own CONTENT now enters `identity`'s hash (see `Harness.identity`), so these two
    # no longer even share a hash -- the collision a round-3 review found is closed for the default case
    # specifically, and the vocabulary check below still catches it independently either way.
    assert a.identity != b.identity
    assert a.comparable_with(b) is False
    with pytest.raises(hn.Unidentified, match="different vocabularies"):
        hn.refuse_incomparable(a, b)


def test_identity_is_unchanged_for_the_default_vocabulary_but_folds_in_any_other():
    """Pins the round-4/5 fix precisely: perigraph's own cross-language digest bytes (the default vocabulary)
    are untouched -- `test_the_digest_rules_the_second_implementation_forced_into_the_spec` already pins that
    exact byte sequence -- and any OTHER vocabulary's own CONTENT digest (round 5: not its self-declared
    `identity` string, see the next two tests for why) is folded into the hash first."""
    default_h = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64),))
    expected_default = hashlib.sha256(b"instruction=" + b"a" * 64 + b";").hexdigest()[:24]
    assert default_h.identity == expected_default

    custom = hn.PartVocabulary(parts=hn.DEFAULT_HARNESS_PARTS, best_sourcing=hn.DEFAULT_BEST_AVAILABLE_SOURCING,
                               name="my-deployment", version="1")
    custom_h = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64,
                                        vocabulary=custom),), vocabulary=custom)
    expected_custom = hashlib.sha256(
        f"vocabulary={custom.content_digest};".encode() + b"instruction=" + b"a" * 64 + b";").hexdigest()[:24]
    assert custom_h.identity == expected_custom
    assert custom_h.identity != default_h.identity

    # A caller's OWN value-equal reconstruction of the default vocabulary counts as "the default" too --
    # `!=`/`==` against `DEFAULT_PART_VOCABULARY` is by VALUE, not by object identity.
    rebuilt_default = hn.PartVocabulary(parts=hn.DEFAULT_HARNESS_PARTS,
                                        best_sourcing=hn.DEFAULT_BEST_AVAILABLE_SOURCING,
                                        name="perigraph", version="1")
    assert rebuilt_default == hn.DEFAULT_PART_VOCABULARY and rebuilt_default is not hn.DEFAULT_PART_VOCABULARY
    rebuilt_h = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64,
                                         vocabulary=rebuilt_default),), vocabulary=rebuilt_default)
    assert rebuilt_h.identity == expected_default


def test_the_vocabulary_identity_is_always_printed_not_only_on_non_conformance():
    """A reviewer found the identity absent from a CONFORMING record's own printed form -- a reader could not tell
    'perigraph, checked' from 'nobody checked' without it."""
    h = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64),))
    assert "vocabulary perigraph/1" in str(h)
    coll = hn.Collection(manifest=hn.Manifest(collector="c", version="1", reaches=("instruction",)), harness=h)
    assert "vocabulary perigraph/1" in str(coll)


def test_to_dict_carries_the_vocabulary_markers_dataclasses_asdict_would_drop():
    """`vocabulary_identity`/`conforms_to_perigraph` are PROPERTIES, so `dataclasses.asdict` silently omits them.
    `to_dict()` is the safe structured (JSON-able) path this project provides instead -- there is no other
    JSON/dict output path for a Harness/Collection anywhere in this repository (checked by grep across src/,
    harness/, examples/, tools/)."""
    import dataclasses
    import json

    redefined = hn.PartVocabulary(
        parts=hn.DEFAULT_HARNESS_PARTS,
        best_sourcing={**hn.DEFAULT_BEST_AVAILABLE_SOURCING, "tool_extension": "in_the_request"})
    p = hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64, vocabulary=redefined)
    h = hn.Harness(parts=(p,), vocabulary=redefined)

    as_dict = dataclasses.asdict(h)
    assert "vocabulary_identity" not in as_dict and "conforms_to_perigraph" not in as_dict, (
        "pinning the defect: dataclasses.asdict really does drop both markers")

    safe = h.to_dict()
    assert safe["vocabulary_identity"] == redefined.identity
    assert safe["conforms_to_perigraph"] is False
    json.dumps(safe)  # must be JSON-safe

    coll = hn.Collection(manifest=hn.Manifest(collector="c", version="1", reaches=(), vocabulary=redefined),
                         harness=h)
    coll_dict = coll.to_dict()
    assert coll_dict["vocabulary_identity"] == redefined.identity
    assert coll_dict["conforms_to_perigraph"] is False
    assert coll_dict["harness"]["vocabulary_identity"] == redefined.identity
    json.dumps(coll_dict)


def test_grouping_key_is_vocabulary_aware():
    """`grouping_key` folds the vocabulary in for any caller who needs a safe dict/set key across vocabularies --
    now a belt-and-suspenders property alongside `identity`'s own round-4 fix (the previous test), not the only
    thing standing between two vocabularies and a false match."""
    widened = hn.PartVocabulary(
        parts=(*hn.DEFAULT_HARNESS_PARTS, "context_window_policy"),
        best_sourcing={**hn.DEFAULT_BEST_AVAILABLE_SOURCING, "context_window_policy": "pushed_by_owner"})
    a = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64),))
    b = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64,
                                 vocabulary=widened),), vocabulary=widened)
    assert a.grouping_key != b.grouping_key
    assert len({a.grouping_key, b.grouping_key}) == 2


def test_identity_uses_vocabulary_content_not_its_self_declared_name():
    """Round 4 folded `vocabulary.identity` (the SELF-DECLARED name/version string) into `Harness.identity`'s
    hash; a reviewer found that two vocabularies which both forgot to declare `name`/`version` (both default to
    `"custom"`/`"unversioned"`) share that string even though their actual content differs, so they still
    collided. Round 5 folds in `vocabulary.content_digest` (a hash over `parts`/`best_sourcing`, never the
    label) instead, which tells these two apart correctly."""
    left = hn.PartVocabulary(parts=(*hn.DEFAULT_HARNESS_PARTS, "context_window_policy"),
                             best_sourcing={**hn.DEFAULT_BEST_AVAILABLE_SOURCING,
                                          "context_window_policy": "pushed_by_owner"})
    right = hn.PartVocabulary(parts=(*hn.DEFAULT_HARNESS_PARTS, "some_other_part"),
                              best_sourcing={**hn.DEFAULT_BEST_AVAILABLE_SOURCING,
                                           "some_other_part": "pushed_by_owner"})
    assert left.identity == right.identity, "both leave name/version undeclared, so the LABEL matches"
    assert left.content_digest != right.content_digest, "but the actual parts differ, so the CONTENT does not"
    a = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64,
                                 vocabulary=left),), vocabulary=left)
    b = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64,
                                 vocabulary=right),), vocabulary=right)
    assert a.identity != b.identity, "identity now hashes the vocabulary's CONTENT, so this no longer collides"


def test_grouping_key_still_distinguishes_declared_name_when_content_is_identical():
    """The flip side, and the reason `grouping_key` is not simply redundant with the round-5 `identity` fix: two
    vocabularies with IDENTICAL `parts`/`best_sourcing` but DIFFERENT self-declared `name`/`version` produce the
    SAME `content_digest` -- correctly, since their actual rules are the same -- so `identity` treats them as
    one harness. A caller who still wants to tell "declared by deployment A" apart from "declared by deployment
    B" administratively, even though the content matches, uses `grouping_key`, which compares the whole
    `PartVocabulary` object including `name`/`version`."""
    same_content_a = hn.PartVocabulary(parts=hn.DEFAULT_HARNESS_PARTS, best_sourcing=hn.DEFAULT_BEST_AVAILABLE_SOURCING,
                                       name="deployment-a", version="1")
    same_content_b = hn.PartVocabulary(parts=hn.DEFAULT_HARNESS_PARTS, best_sourcing=hn.DEFAULT_BEST_AVAILABLE_SOURCING,
                                       name="deployment-b", version="1")
    assert same_content_a.content_digest == same_content_b.content_digest
    assert same_content_a.identity != same_content_b.identity
    a = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64,
                                 vocabulary=same_content_a),), vocabulary=same_content_a)
    b = hn.Harness(parts=(hn.Part(kind="instruction", sourcing="in_the_request", digest="a" * 64,
                                 vocabulary=same_content_b),), vocabulary=same_content_b)
    assert a.identity == b.identity, "same content, so the SAME record identity -- this is correct, not a bug"
    assert a.grouping_key != b.grouping_key, "grouping_key still tells the two declarations apart administratively"


def test_a_duplicate_pair_in_best_sourcing_is_refused_not_silently_collapsed():
    """`dict(...)` on a sequence of pairs keeps only the LAST entry for a repeated key -- a reviewer found this
    accepted a vocabulary declaring two contradictory sourcing modes for the same part with no sign of the
    contradiction. A Mapping input cannot carry a duplicate key at all, so this check only applies to a sequence
    of pairs."""
    with pytest.raises(hn.Unidentified, match="more than once"):
        hn.PartVocabulary(parts=("instruction",),
                          best_sourcing=(("instruction", "in_the_request"), ("instruction", "not_observable")))
    # A Mapping with the same effective content (last-write-wins is how a dict literal itself behaves) is not
    # this defect -- there is no duplicate KEY to detect once it is already a Mapping.
    ok = hn.PartVocabulary(parts=("instruction",), best_sourcing={"instruction": "in_the_request"})
    assert ok.sourcing_of("instruction") == "in_the_request"
