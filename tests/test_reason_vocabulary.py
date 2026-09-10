"""Every reason a producer can return is in the closed vocabulary, checked by calling the producers.

`Candidate.__post_init__` refuses an `excluded_because` outside `EXCLUSION_REASONS`, which is what makes the value
aggregable: a log whose exclusion reasons are an open set cannot be counted. But the tuple was checked against itself
and against nothing that generates it. Deleting each of its nine values in turn and running the whole suite:

    chosen              105 tests fail
    below_floor          51
    not_evaluated        30
    not_priced            5
    evidence_expired      1
    not_authorised        0
    latency_infeasible    0
    unavailable           0
    no_bound              0

Four of nine could be removed with the suite green -- while `record.admissible` still returns those strings and
`serve._why_not` still writes them. So a production path could produce a reason the constructor refuses, and the
refusal would arrive at write time, in production, on a path no test covered. The membership check that makes the
enum closed is exactly what made the gap invisible.

The subject here is therefore the PRODUCERS, not the values. A second list of the nine strings typed into a test
would be the same defect one level up: it would go stale the same way and nothing would tie it to the code either.
Instead each test drives a producer into every branch it has and asserts what comes back is in the vocabulary. A new
producer is covered by being called; a value dropped from the tuple fails because something still returns it.

The four redundant values stay. A guard over a set protects the elements something else already depends on and
silently permits removing the rest -- which are exactly the elements that exist for the case that has not happened
yet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import explore as ex  # noqa: E402
from tierbook import record as rec  # noqa: E402
from tierbook import serve as sv  # noqa: E402


def cand(**kw):
    base = dict(id="c", excluded_because="chosen", bound=0.90, bound_kind="lcb95", cost_usd=0.004,
                evidence_as_of="2026-09-01")
    base.update(kw)
    return rec.Candidate(**base)


# --- record.admissible -------------------------------------------------------------------------------


#: Every input shape that steers `admissible` down a different branch. The point is coverage of the FUNCTION, so a
#: branch added later without an entry here is caught by the reachability test at the bottom, not by this list.
ADMISSIBLE_CASES = [
    ("no bound at all", dict(candidate=cand(bound=None), floor=0.80, authorised=True, latency_feasible=True)),
    ("bound under the floor", dict(candidate=cand(bound=0.10), floor=0.80, authorised=True, latency_feasible=True)),
    ("gateway refuses", dict(candidate=cand(), floor=0.80, authorised=False, latency_feasible=True)),
    ("latency infeasible", dict(candidate=cand(), floor=0.80, authorised=True, latency_feasible=False)),
    ("evidence past the limit", dict(candidate=cand(), floor=0.80, authorised=True, latency_feasible=True,
                                     evidence_age_days=120.0, max_age_days=90.0)),
    ("everything holds", dict(candidate=cand(), floor=0.80, authorised=True, latency_feasible=True)),
    ("no latency constraint declared", dict(candidate=cand(), floor=0.80, authorised=True, latency_feasible=None)),
    ("no freshness limit declared", dict(candidate=cand(), floor=0.80, authorised=True, latency_feasible=True,
                                         evidence_age_days=9999.0, max_age_days=None)),
]


@pytest.mark.parametrize("label,kwargs", ADMISSIBLE_CASES, ids=[c[0] for c in ADMISSIBLE_CASES])
def test_every_reason_admissible_returns_is_in_the_vocabulary(label, kwargs):
    """Catches a value dropped from `EXCLUSION_REASONS` that `admissible` still returns. Four of the nine could be
    dropped with the whole suite green, so nothing tied the tuple to its own producer."""
    _ok, why = rec.admissible(**kwargs)
    assert why in rec.EXCLUSION_REASONS, f"{label}: admissible returned {why!r}, outside the vocabulary"


def test_admissible_reaches_every_refusal_the_vocabulary_has_a_word_for():
    """Catches the case above being vacuous. If the parametrised inputs only ever reach two branches, every one of
    them passes while the other reasons stay unproduced and unchecked -- which is the state this file was written to
    end, not to reproduce with more steps."""
    produced = {rec.admissible(**kw)[1] for _label, kw in ADMISSIBLE_CASES}
    for expected in ("no_bound", "below_floor", "not_authorised", "latency_infeasible", "evidence_expired"):
        assert expected in produced, f"no input above reaches {expected!r}, so nothing checks it"


# --- explore.clears_floor ----------------------------------------------------------------------------


#: `clears_floor` has its own vocabulary of two values that are NOT exclusion reasons -- `eligible` and
#: `too_stale_to_explore` -- because it answers a different question: who may be drawn, not whether the floor is
#: claimed. It shares `no_bound` and `below_floor` with `admissible`, and those must stay in the shared tuple.
CLEARS_FLOOR_CASES = [
    ("no bound", dict(candidate=cand(bound=None), floor=0.80)),
    ("under the floor", dict(candidate=cand(bound=0.10), floor=0.80)),
    ("past the staleness ceiling", dict(candidate=cand(), floor=0.80, staleness_limit_days=30.0,
                                        evidence_age_days=90.0)),
    ("eligible", dict(candidate=cand(), floor=0.80, staleness_limit_days=30.0, evidence_age_days=5.0)),
]

#: Values `clears_floor` owns rather than shares. Kept as a named set so that a value moving from one vocabulary to
#: the other is a visible edit here rather than a silent widening of the assertion below.
EXPLORE_ONLY_REASONS = frozenset({"eligible", "too_stale_to_explore"})


@pytest.mark.parametrize("label,kwargs", CLEARS_FLOOR_CASES, ids=[c[0] for c in CLEARS_FLOOR_CASES])
def test_every_reason_clears_floor_returns_is_accounted_for(label, kwargs):
    """Catches `clears_floor` growing a third refusal that lands in a record as an exclusion reason without being
    in the vocabulary -- the same gap as `admissible`'s, in the newer of the two producers."""
    _ok, why = ex.clears_floor(**kwargs)
    assert why in rec.EXCLUSION_REASONS or why in EXPLORE_ONLY_REASONS, (
        f"{label}: clears_floor returned {why!r}, which is in neither vocabulary")


def test_clears_floor_shares_the_two_reasons_it_shares_and_no_more():
    """Catches the two vocabularies drifting into each other. `no_bound` and `below_floor` mean the same thing in
    both and must stay in the shared tuple; `eligible` and `too_stale_to_explore` answer a different question and
    must NOT be written into a record as exclusion reasons."""
    produced = {ex.clears_floor(**kw)[1] for _label, kw in CLEARS_FLOOR_CASES}
    assert {"no_bound", "below_floor"} <= produced
    assert produced & EXPLORE_ONLY_REASONS, "no input reaches the two reasons clears_floor owns"
    for owned in EXPLORE_ONLY_REASONS:
        assert owned not in rec.EXCLUSION_REASONS, (
            f"{owned!r} is in EXCLUSION_REASONS, so a record can now claim a candidate was excluded for a reason "
            f"that describes eligibility for a draw rather than admissibility")


# --- serve._why_not ---------------------------------------------------------------------------------


WHY_NOT_CASES = [
    ("not serving", dict(cand=cand(), cid="c", costs={"c": 0.004}, floor=0.80, authorised=True,
                         latency_feasible=True, available={"c": False},
                         evidence_age_days=None, max_age_days=None)),
    ("no bound", dict(cand=cand(bound=None), cid="c", costs={"c": 0.004}, floor=0.80, authorised=True,
                      latency_feasible=True, available={"c": True},
                      evidence_age_days=None, max_age_days=None)),
    ("no price", dict(cand=cand(), cid="c", costs={}, floor=0.80, authorised=True,
                      latency_feasible=True, available={"c": True},
                      evidence_age_days=None, max_age_days=None)),
    ("no floor to compare against", dict(cand=cand(), cid="c", costs={"c": 0.004}, floor=None, authorised=True,
                                         latency_feasible=True, available={"c": True},
                      evidence_age_days=None, max_age_days=None)),
    ("below the floor", dict(cand=cand(bound=0.10), cid="c", costs={"c": 0.004}, floor=0.80, authorised=True,
                             latency_feasible=True, available={"c": True},
                      evidence_age_days=None, max_age_days=None)),
    ("admissible", dict(cand=cand(), cid="c", costs={"c": 0.004}, floor=0.80, authorised=True,
                        latency_feasible=True, available={"c": True},
                      evidence_age_days=None, max_age_days=None)),
]


@pytest.mark.parametrize("label,kwargs", WHY_NOT_CASES, ids=[c[0] for c in WHY_NOT_CASES])
def test_every_reason_why_not_returns_is_in_the_vocabulary(label, kwargs):
    """Catches the producer that actually writes the value into a record returning something the constructor would
    refuse. This is the path where the gap would have surfaced in production rather than in a test."""
    why = sv._why_not(**kwargs)
    assert why in rec.EXCLUSION_REASONS, f"{label}: _why_not returned {why!r}, outside the vocabulary"


def test_why_not_reaches_the_reasons_only_it_produces():
    """Catches the `_why_not` cases above being vacuous. `unavailable` and `not_priced` are reachable from this
    producer and not from `admissible`, so if these inputs miss them nothing checks them at all."""
    produced = {sv._why_not(**kw) for _label, kw in WHY_NOT_CASES}
    for expected in ("unavailable", "not_priced", "not_evaluated"):
        assert expected in produced, f"no input above reaches {expected!r}, so nothing checks it"


# --- the value the constructor itself produces -------------------------------------------------------


def test_the_chosen_marker_is_part_of_the_same_vocabulary():
    """`chosen` is not a refusal, and it is in the same tuple because it occupies the same field. 105 tests depend
    on it, so it is the least likely to be dropped -- which is exactly why it is worth stating that the field holds
    one vocabulary rather than two overlapping ones."""
    assert "chosen" in rec.EXCLUSION_REASONS
    assert cand(excluded_because="chosen").excluded_because == "chosen"


def test_a_reason_outside_the_vocabulary_is_still_refused():
    """The guard this whole file exists to tie to its producers has to still be there. A file that checked only the
    producers would pass against a constructor that accepted anything."""
    with pytest.raises(rec.Incomplete, match="cannot be aggregated"):
        cand(excluded_because="it seemed expensive")
