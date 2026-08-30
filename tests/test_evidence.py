"""The evidence loader's refusals, each pinned to the mistake it exists to make unreachable.

Two defects motivate most of this file. A digest that legitimises a merged file the moment nobody re-reads
it is not a digest, so `load()` must re-verify on every call rather than trust a cache keyed by path. And a
guard written after the data structure it is meant to protect has already been built can never fire, because
the second entry of a duplicate silently overwrote the first one line earlier -- this is why the manifest
check in `paired()` must run before any intersection, and why a duplicate `item_id` must be caught before a
mapping is built from the lines.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.evidence import (  # noqa: E402
    INCORRECT,
    SOLVED,
    UNOBSERVED,
    UNOBSERVED_REASONS,
    Evidence,
    EvidenceError,
    Paired,
    digest_of,
    load,
    paired,
)


# --- fixtures and small builders ---------------------------------------------------------------------


def _header(**over) -> dict:
    base = {
        "suite_manifest_digest": "sha256:" + "a" * 64,
        "run_id": "run-001",
        "scorer_version": "scorer-v1",
        "subject": "api-cheap-a",
        "family": "agentic-coding",
        "trials_per_item": 1,
        "produced_at": "2026-08-29T00:00:00Z",
    }
    base.update(over)
    return base


def _verdict(item_id: str, state: str, reason=None, note=None) -> dict:
    return {"item_id": item_id, "state": state, "unobserved_reason": reason, "note": note}


def _build(dir_path: Path, header: dict, verdicts: list, name: str = "artifact") -> Path:
    """Write a header line plus verdict lines, then name the file after the digest of those exact bytes.

    The filename is derived last and never handed in, which mirrors the property under test: the name is a
    function of the bytes, so a caller cannot pick a name to make a later mutation invisible.
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(header)] + [json.dumps(v) for v in verdicts]
    content = ("\n".join(lines) + "\n").encode("utf-8")
    digest_hex = hashlib.sha256(content).hexdigest()
    path = dir_path / f"{name}-{digest_hex[:16]}.jsonl"
    path.write_bytes(content)
    return path


def _pair_of_items(n: int, *, solved_frac=1.0) -> list:
    solved_count = int(n * solved_frac)
    return [_verdict(f"i{i}", SOLVED if i < solved_count else INCORRECT) for i in range(n)]


def test_digest_of_matches_an_independent_hash_of_the_same_bytes(tmp_path):
    """`digest_of` is the primitive the filename convention and the load-time check both rest on; if its
    shape drifts from plain sha256 hex, every digest embedded in a filename becomes uncheckable."""
    p = tmp_path / "some-file.jsonl"
    content = b"not necessarily even valid jsonl -- digest_of hashes bytes, not lines\n"
    p.write_bytes(content)

    result = digest_of(p)
    assert result == "sha256:" + hashlib.sha256(content).hexdigest()


# --- load(): verified on every read, not on write -------------------------------------------------


def test_a_mutated_artifact_refuses_on_a_later_read_not_only_the_first(tmp_path):
    """Verification that ran once and was trusted afterwards is how a merged file keeps its old name.

    The first read must succeed against the original bytes -- otherwise this test would not be exercising
    anything -- and a second, independent call to `load()` on the same path must see the corruption itself
    rather than an answer computed the first time and remembered.
    """
    ledger_root = tmp_path
    path = _build(ledger_root / "evidence", _header(), [_verdict("i0", SOLVED)])

    first = load(path, ledger_root=ledger_root)
    assert isinstance(first, Evidence)

    with open(path, "ab") as f:
        f.write(b"\n")  # one mutated byte's worth of drift, filename left exactly as it was

    with pytest.raises(EvidenceError):
        load(path, ledger_root=ledger_root)


def test_a_path_outside_the_ledger_root_refuses(tmp_path):
    """The ledger root is the boundary a reviewer can audit; a path that steps outside it cannot be."""
    ledger_root = tmp_path / "ledger"
    ledger_root.mkdir()
    outside = tmp_path / "elsewhere"
    path = _build(outside, _header(), [_verdict("i0", SOLVED)])

    with pytest.raises(EvidenceError, match="ledger root|outside"):
        load(path, ledger_root=ledger_root)


def test_a_symlinked_artifact_refuses(tmp_path):
    """A symlink lets the name and the bytes it points at diverge independently of each other.

    The digest-in-filename property is only load-bearing if the path resolved is the path checked. A symlink
    reintroduces exactly the gap a content-addressed name was meant to close.
    """
    ledger_root = tmp_path
    real = _build(ledger_root / "evidence", _header(), [_verdict("i0", SOLVED)])
    link = real.parent / f"link-{real.name}"
    os.symlink(real, link)

    with pytest.raises(EvidenceError, match="symlink"):
        load(link, ledger_root=ledger_root)


def test_a_header_missing_a_required_field_refuses(tmp_path):
    """Provenance is not optional decoration; a derivation that cannot name its manifest cannot be trusted."""
    ledger_root = tmp_path
    header = _header()
    del header["suite_manifest_digest"]
    path = _build(ledger_root / "evidence", header, [_verdict("i0", SOLVED)])

    with pytest.raises(EvidenceError):
        load(path, ledger_root=ledger_root)


def test_trials_per_item_other_than_one_refuses(tmp_path):
    """The header's declared trial count is checked directly, independently of whether any line repeats.

    Single trial per item is the precondition the rest of the derivation assumes; a header that says
    otherwise must refuse before anyone asks what aggregating two trials would even mean.
    """
    ledger_root = tmp_path
    path = _build(ledger_root / "evidence", _header(trials_per_item=2), [_verdict("i0", SOLVED)])

    with pytest.raises(EvidenceError, match="trials_per_item"):
        load(path, ledger_root=ledger_root)


# --- C5: a duplicate item_id must be caught before the verdicts mapping is built -------------------
#
# `{item_id: (state, reason) for line in lines}` silently keeps the last line and drops the first. A
# uniqueness check that runs after that comprehension has nothing left to see, so these two tests build
# artifacts where the second line would overwrite the first and insist the refusal still fires.


def test_a_duplicate_item_id_refuses_rather_than_keeping_the_later_line(tmp_path):
    """The two lines agree on the state, which is deliberate: even when overwriting would be harmless by
    coincidence, the refusal must not be conditioned on whether the overwrite would have changed anything."""
    ledger_root = tmp_path
    verdicts = [_verdict("i0", SOLVED), _verdict("i0", SOLVED)]
    path = _build(ledger_root / "evidence", _header(), verdicts)

    with pytest.raises(EvidenceError, match="duplicate"):
        load(path, ledger_root=ledger_root)


def test_a_duplicate_item_id_with_contradicting_states_refuses_naming_the_duplicate(tmp_path):
    """The adversarial case: one line says solved, the other says incorrect for the same item_id. A loader
    that builds the mapping first and checks uniqueness second would silently keep whichever line came
    last and never notice the contradiction -- this is the exact shape of guard that can never fire once
    placed after the read it is supposed to protect."""
    ledger_root = tmp_path
    verdicts = [_verdict("i0", SOLVED), _verdict("i0", INCORRECT)]
    path = _build(ledger_root / "evidence", _header(), verdicts)

    with pytest.raises(EvidenceError, match="duplicate"):
        load(path, ledger_root=ledger_root)


# --- the state enum carries every distinction the derivation uses ---------------------------------


def test_an_unknown_state_refuses(tmp_path):
    """The enum is closed. A fifth state is a fifth cell nobody defined a rule for."""
    ledger_root = tmp_path
    path = _build(ledger_root / "evidence", _header(), [_verdict("i0", "maybe")])

    with pytest.raises(EvidenceError, match="state"):
        load(path, ledger_root=ledger_root)


def test_an_unknown_unobserved_reason_refuses(tmp_path):
    """The sub-reason enum is closed the same way the state enum is; a fifth reason hides which of the
    known four actually applied."""
    ledger_root = tmp_path
    path = _build(ledger_root / "evidence", _header(), [_verdict("i0", UNOBSERVED, reason="flaky_network")])

    with pytest.raises(EvidenceError, match="unobserved_reason"):
        load(path, ledger_root=ledger_root)


def test_unobserved_with_a_null_reason_refuses(tmp_path):
    """`unobserved` without a sub-reason is a state that cannot be told apart from any of the other three
    kinds of not-attempted, which defeats the reason the sub-reason exists."""
    ledger_root = tmp_path
    path = _build(ledger_root / "evidence", _header(), [_verdict("i0", UNOBSERVED, reason=None)])

    with pytest.raises(EvidenceError, match="unobserved_reason"):
        load(path, ledger_root=ledger_root)


@pytest.mark.parametrize("state", [SOLVED, INCORRECT])
def test_an_observed_state_with_a_non_null_reason_refuses(tmp_path, state):
    """The sub-reason field means something only for `unobserved`; carrying one on an observed result is
    either a mislabelled transport failure or a copy-paste, and either way the record is ambiguous."""
    ledger_root = tmp_path
    reason = next(iter(UNOBSERVED_REASONS))
    path = _build(ledger_root / "evidence", _header(), [_verdict("i0", state, reason=reason)])

    with pytest.raises(EvidenceError, match="unobserved_reason"):
        load(path, ledger_root=ledger_root)


# --- C4: the manifest must be compared before intersecting by item id ------------------------------
#
# The design added `suite_manifest_digest` because a reused item_id whose content changed rots silently,
# then intersected on ids without comparing manifests -- the same defect walking back in through the
# derivation. The adversarial case is the second test below: if the mismatch check were expressed in terms
# of the post-intersection key set, two artifacts that share no ids at all would produce an empty
# intersection and raise *that* refusal instead, never reaching the manifest check at all.


def test_paired_refuses_on_manifest_mismatch_even_though_item_ids_overlap(tmp_path):
    """Same item ids, different manifest digest. If intersection ran first this would look like ordinary
    overlap; the manifest disagreement must be caught before the ids are ever compared."""
    ledger_root = tmp_path
    candidate = load(_build(ledger_root / "evidence",
                            _header(suite_manifest_digest="sha256:" + "1" * 64, subject="cand"),
                            _pair_of_items(4), name="cand"), ledger_root=ledger_root)
    reference = load(_build(ledger_root / "evidence",
                             _header(suite_manifest_digest="sha256:" + "2" * 64, subject="ref"),
                             _pair_of_items(4), name="ref"), ledger_root=ledger_root)

    with pytest.raises(EvidenceError, match="manifest"):
        paired(candidate, reference)


def test_paired_refuses_on_manifest_mismatch_even_when_item_ids_are_disjoint(tmp_path):
    """The unreachable-guard case named in review: different manifests AND disjoint ids.

    If the target set were defined as the post-intersection key set, this pair would hit an empty
    intersection and refuse with that reason instead -- the manifest mismatch would never be reported, and
    a test that only checked the overlapping case above would not have caught it. The refusal here must be
    the manifest one, not the empty-intersection one.
    """
    ledger_root = tmp_path
    candidate = load(_build(ledger_root / "evidence",
                            _header(suite_manifest_digest="sha256:" + "1" * 64, subject="cand"),
                            [_verdict("only-in-candidate", SOLVED)], name="cand"), ledger_root=ledger_root)
    reference = load(_build(ledger_root / "evidence",
                             _header(suite_manifest_digest="sha256:" + "2" * 64, subject="ref"),
                             [_verdict("only-in-reference", SOLVED)], name="ref"), ledger_root=ledger_root)

    with pytest.raises(EvidenceError, match="manifest") as excinfo:
        paired(candidate, reference)
    assert "empty" not in str(excinfo.value).lower(), \
        "the manifest disagreement must be reported on its own terms, not relabelled as an empty intersection"


def test_paired_refuses_on_an_empty_intersection_when_manifests_agree(tmp_path):
    """Distinct from the two tests above: the manifests agree here, and the ids are still disjoint, so this
    is the one case where an empty-intersection refusal is the correct and only available diagnosis."""
    ledger_root = tmp_path
    same_manifest = "sha256:" + "3" * 64
    candidate = load(_build(ledger_root / "evidence",
                            _header(suite_manifest_digest=same_manifest, subject="cand"),
                            [_verdict("only-in-candidate", SOLVED)], name="cand"), ledger_root=ledger_root)
    reference = load(_build(ledger_root / "evidence",
                             _header(suite_manifest_digest=same_manifest, subject="ref"),
                             [_verdict("only-in-reference", SOLVED)], name="ref"), ledger_root=ledger_root)

    with pytest.raises(EvidenceError, match="empty|intersection"):
        paired(candidate, reference)


def test_paired_refuses_when_one_side_carries_no_evidence(tmp_path):
    """Order-of-checks item 1: a summary-only side must be named, not silently treated as zero items.

    The interface types both parameters as `Evidence`, but the order-of-checks list it hands down starts
    with "both sides carry evidence, else refuse naming which side is summary-only" -- a check that only
    makes sense if a caller (`Tier.paired`, falling back from a missing `Evidence`) can reach this function
    with one side absent. This test pins that reading; see the report for why the two could diverge here.
    """
    ledger_root = tmp_path
    candidate = load(_build(ledger_root / "evidence", _header(subject="cand"), _pair_of_items(4), name="cand"),
                     ledger_root=ledger_root)

    with pytest.raises(EvidenceError, match="summary-only|no evidence"):
        paired(candidate, None)


# --- C3 + C9: transport failure and wrong answer land in different places, and paired() says what it
# --- excluded, not just what it counted ------------------------------------------------------------


def _cells_fixture(tmp_path):
    """Six items chosen so every cell of the 2x2, plus both excluded shapes, has exactly one occupant.

    i0 both solve it. i1 only the candidate solves it. i2 only the reference solves it. i3 both attempt it
    and both fail it (neither). i4 the reference solves but the candidate never attempted (transport
    failure on the candidate side). i5 the candidate fails it but the reference never attempted (transport
    failure on the reference side). i4 and i5 must not appear in any of the four cells: a transport failure
    is not the same claim as a wrong answer, and only the latter is an attempted-and-failed result.
    """
    ledger_root = tmp_path
    manifest = "sha256:" + "9" * 64
    candidate_verdicts = [
        _verdict("i0", SOLVED), _verdict("i1", SOLVED), _verdict("i2", INCORRECT),
        _verdict("i3", INCORRECT), _verdict("i4", UNOBSERVED, reason="execution_error"),
        _verdict("i5", INCORRECT),
    ]
    reference_verdicts = [
        _verdict("i0", SOLVED), _verdict("i1", INCORRECT), _verdict("i2", SOLVED),
        _verdict("i3", INCORRECT), _verdict("i4", SOLVED),
        _verdict("i5", UNOBSERVED, reason="execution_error"),
    ]
    candidate = load(_build(ledger_root / "evidence", _header(suite_manifest_digest=manifest, subject="cand"),
                            candidate_verdicts, name="cand"), ledger_root=ledger_root)
    reference = load(_build(ledger_root / "evidence", _header(suite_manifest_digest=manifest, subject="ref"),
                             reference_verdicts, name="ref"), ledger_root=ledger_root)
    return candidate, reference


def test_a_transport_failure_and_a_wrong_answer_land_in_different_places(tmp_path):
    """`failed(transport)` is unobserved and excluded outright; `failed(wrong_answer)` is observed and
    contributes to a cell. Collapsing the two would move i4 and i5 into reference_only/candidate_only and
    change which tier a margin check would prefer."""
    candidate, reference = _cells_fixture(tmp_path)
    result = paired(candidate, reference)
    assert isinstance(result, Paired)
    assert (result.both, result.candidate_only, result.reference_only, result.neither) == (1, 1, 1, 1)


def test_paired_excluded_reports_a_count_and_a_breakdown_by_pair(tmp_path):
    """i4 and i5 are excluded because one side never attempted them, and both are excluded for the same
    recorded reason: `unobserved`. The breakdown must say so rather than folding them into a bare count."""
    candidate, reference = _cells_fixture(tmp_path)
    result = paired(candidate, reference)

    assert result.excluded["count"] == 2
    # Keyed by the PAIR of states rather than by one side's state, because which side failed to attempt an
    # item is the thing a reader needs and a per-side rollup throws it away. Both of these items are excluded
    # on account of an `unobserved` verdict on one side or the other.
    by_pair = result.excluded["by_pair"]
    assert sum(n for k, n in by_pair.items() if UNOBSERVED in k) == 2
    assert sum(by_pair.values()) == result.excluded["count"]


def test_excluded_is_zero_when_both_sides_attempted_every_item(tmp_path):
    """The migrated artifact this project ships has no transport failures on either arm, so the
    exclusion count for it must be exactly zero -- a non-zero default here would misreport every clean
    comparison as having dropped something."""
    ledger_root = tmp_path
    manifest = "sha256:" + "5" * 64
    verdicts = _pair_of_items(6, solved_frac=0.5)
    candidate = load(_build(ledger_root / "evidence", _header(suite_manifest_digest=manifest, subject="cand"),
                            verdicts, name="cand"), ledger_root=ledger_root)
    reference = load(_build(ledger_root / "evidence", _header(suite_manifest_digest=manifest, subject="ref"),
                             verdicts, name="ref"), ledger_root=ledger_root)

    result = paired(candidate, reference)
    assert result.excluded == {"count": 0, "by_pair": {}, "reason": result.excluded["reason"]}


# --- Evidence.cohort: derived, and covering the manifest digest as well as the item ids ------------


def test_identical_item_ids_under_different_manifests_do_not_share_a_cohort(tmp_path):
    """C6: a fingerprint over item ids alone cannot see a reused id whose underlying content changed.

    Two artifacts here have the exact same item ids -- the derived cohort must still tell them apart,
    because the manifest digest is the only signal that the suite behind those ids was not the same suite.
    """
    ledger_root = tmp_path
    verdicts = _pair_of_items(5)
    a = load(_build(ledger_root / "evidence",
                    _header(suite_manifest_digest="sha256:" + "1" * 64, subject="a"), verdicts, name="a"),
             ledger_root=ledger_root)
    b = load(_build(ledger_root / "evidence",
                    _header(suite_manifest_digest="sha256:" + "2" * 64, subject="b"), verdicts, name="b"),
             ledger_root=ledger_root)

    assert a.cohort != b.cohort


def test_the_same_items_and_manifest_share_a_cohort_regardless_of_line_order(tmp_path):
    """The cohort is a property of the set of items and the manifest, not of how a file happened to be
    written; a JSONL writer that emits lines in a different order must not manufacture a new cohort."""
    ledger_root = tmp_path
    manifest = "sha256:" + "4" * 64
    verdicts = _pair_of_items(5)
    reordered = list(reversed(verdicts))

    a = load(_build(ledger_root / "evidence", _header(suite_manifest_digest=manifest, subject="a"),
                    verdicts, name="a"), ledger_root=ledger_root)
    b = load(_build(ledger_root / "evidence", _header(suite_manifest_digest=manifest, subject="b"),
                    reordered, name="b"), ledger_root=ledger_root)

    assert a.cohort == b.cohort


def test_a_ledger_can_be_copied_somewhere_else_and_still_loads(tmp_path):
    """Found in audit: a ledger has to be relocatable, because nobody else's ledger lives where ours does.

    The first implementation stored evidence paths relative to the repository root while the loader took its
    containment boundary from the ledger directory. Those two bases coincide only in the shipped layout, so
    copying the ledger anywhere broke every evidence-backed record -- and it failed with "resolves outside the
    ledger root", which blames an attempted escape for what is actually a mismatched base. Paths are now
    relative to the ledger, so the boundary and the base are one thing.
    """
    import shutil

    src = ROOT / "examples" / "ledger"
    dst = tmp_path / "somebody-elses-ledger"
    shutil.copytree(src, dst)
    records = json.loads((dst / "tiers" / "api-cheap-a.json").read_text())
    ev = records["families"]["tool-agent-user-retail"]["evidence"]
    assert not ev["path"].startswith("examples/"), "a ledger-relative path must not name the repository layout"
    loaded = load(ev["path"], ledger_root=dst)
    assert loaded.subject == "api-cheap-a"
    assert len(loaded.verdicts) == 20
