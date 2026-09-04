"""Provenance, kept separate from behaviour because the measurements say it predicts nothing."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.lineage import CandidateId, shares_lineage, single_lineage, stale_pairs  # noqa: E402


def _q(version: str, serving: str) -> CandidateId:
    return CandidateId(weights="qwen3.6-35b-a3b", weights_version=version, serving=serving)


def test_two_servings_of_one_model_share_lineage_and_are_still_distinct_candidates():
    """Measured at up to 35.7% answer disagreement, so the identity carries the distinction rather than
    flattening it -- while still recording that a weight change moves both.
    """
    a, b = _q("r1", "verbose"), _q("r1", "terse")
    assert str(a) != str(b)
    assert shares_lineage(a, b)


def test_the_lineage_excludes_the_version_because_a_bump_is_what_it_has_to_detect():
    assert _q("r1", "verbose").lineage == _q("r2", "verbose").lineage


def test_a_weight_change_invalidates_every_pair_the_candidate_is_in():
    """The asymmetry that matters: one weight change breaks the joint statistics against everything at
    once, where candidates from different families break one at a time.
    """
    pool = [_q("r1", "verbose"), _q("r1", "terse"),
            CandidateId("sonnet", "4-6", "default"),
            CandidateId("opus", "5", "default")]
    stale = stale_pairs(pool, changed="qwen3.6-35b-a3b", new_version="r2")
    names = {n for pair in stale for n in pair}
    assert str(_q("r1", "verbose")) in names
    assert str(_q("r1", "terse")) in names, "its own other serving configuration is stale too"
    assert str(CandidateId("sonnet", "4-6", "default")) in names
    # Two candidates neither of which is on the changed lineage are not invalidated by it.
    assert (str(CandidateId("opus", "5", "default")),
            str(CandidateId("sonnet", "4-6", "default"))) not in stale


def test_a_candidate_already_at_the_new_version_is_not_stale():
    pool = [_q("r2", "verbose"), CandidateId("opus", "5", "default")]
    assert stale_pairs(pool, changed="qwen3.6-35b-a3b", new_version="r2") == []


def test_single_lineage_is_a_note_and_not_an_exclusion():
    """On the corpus here the best policy at one accuracy floor WAS a single-lineage quorum, so this
    can only ever annotate. The test states the intent the API has to keep.
    """
    assert single_lineage([_q("r1", "verbose"), _q("r1", "terse")])
    assert not single_lineage([_q("r1", "verbose"), CandidateId("sonnet", "4-6", "default")])
