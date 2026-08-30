"""Candidate admission, pinned by the two ways an averages-based filter goes wrong.

Both were measured on the real corpus within a day of this file being written: three tiers dominated on
aggregate returned to the frontier once input length was stratified, and a tier eighteen points worse than the
cheapest API tier solved four items no API tier solved.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.audit import ACTIVE, SUPPRESSED, UNDECIDED, audit, headroom  # noqa: E402
from tierbook.evidence import INCORRECT, SOLVED  # noqa: E402
from tierbook.optimise import single_tier  # noqa: E402
from tierbook.outcomes import Cell, OutcomeTable  # noqa: E402


def _table(spec: dict, features: dict | None = None) -> OutcomeTable:
    t = OutcomeTable(suite="s", manifest_digest="d")
    for item, row in spec.items():
        t.cells[item] = {tier: Cell(state=st, usd=usd) for tier, (st, usd) in row.items()}
    t.features = dict(features or {})
    return t


def test_a_tier_dominated_on_averages_but_on_a_stratum_frontier_stays_active():
    """Cost is a function of token count, so dominance is a relation between curves, not scalars.

    On the real corpus, stratifying by input length put three of five aggregate-dominated tiers back on the
    frontier, and the best tier on short inputs was not the best tier overall. A filter keyed on averages
    deletes exactly those.
    """
    spec, feats = {}, {}
    # `short_specialist` is dear on long inputs and cheap on short ones, so on aggregate it loses.
    for k in range(40):
        spec[f"s{k}"] = {"generalist": (SOLVED, 0.10), "short_specialist": (SOLVED, 0.01)}
        feats[f"s{k}"] = {"len": "short"}
    for k in range(40):
        spec[f"l{k}"] = {"generalist": (SOLVED, 0.10), "short_specialist": (SOLVED, 5.00)}
        feats[f"l{k}"] = {"len": "long"}
    t = _table(spec, feats)
    assert t.spend_of("short_specialist") > t.spend_of("generalist"), "dominated on aggregate cost"

    without = audit(t, practical_difference=0.005)
    assert without["short_specialist"].state == SUPPRESSED, "an averages-only audit deletes it"

    withstrata = audit(t, stratum_feature="len", min_stratum=25, practical_difference=0.005)
    assert withstrata["short_specialist"].state == ACTIVE
    assert "short" in withstrata["short_specialist"].strata_on_frontier


def test_a_tier_worse_on_both_averages_that_solves_something_uniquely_stays_active():
    """The self-hosted tier: eighteen points worse than the cheapest API and the only solver of four items."""
    spec = {}
    for k in range(100):
        # `weak` loses almost everywhere and is the only one that gets these five.
        uniq = k < 5
        spec[f"i{k}"] = {
            "strong": (INCORRECT if uniq else SOLVED, 1.00),
            "weak": (SOLVED if uniq else INCORRECT, 2.00),
        }
    t = _table(spec)
    v = audit(t, practical_difference=0.005)
    assert v["weak"].state == ACTIVE
    assert v["weak"].incremental_quality == pytest.approx(0.05)
    assert v["weak"].incremental_quality_ci[0] > 0.005


def test_unique_solves_below_the_stated_practical_difference_are_undecided_not_suppressed():
    """With enough items every tier solves something uniquely; non-zero is not the same as worth an endpoint."""
    spec = {f"i{k}": {"a": (SOLVED if k else INCORRECT, 1.0), "b": (INCORRECT if k else SOLVED, 2.0)}
            for k in range(400)}
    t = _table(spec)
    v = audit(t, practical_difference=0.05)
    assert v["b"].state == UNDECIDED
    assert "does not clear the stated practical difference" in v["b"].why


def test_rank_instability_beyond_the_tolerance_forces_undecided():
    """A candidate whose rank moved is decided by no fold. The tolerance is why the check is usable at width.

    Exact-position matching declared eight of nine real tiers unstable and the audit stopped saying anything, so
    adjacent swaps between near-equal candidates are treated as noise and a move of two or more as signal.
    """
    spec = {f"i{k}": {"a": (SOLVED, 1.0), "b": (SOLVED, 2.0), "c": (SOLVED, 3.0)} for k in range(60)}
    t = _table(spec)
    adjacent = audit(t, fold_ranks=[["a", "b", "c"], ["b", "a", "c"]], rank_tolerance=1)
    assert adjacent["a"].state != UNDECIDED, "an adjacent swap is noise at this width"
    moved = audit(t, fold_ranks=[["a", "b", "c"], ["c", "b", "a"]], rank_tolerance=1)
    assert moved["a"].state == UNDECIDED and moved["c"].state == UNDECIDED


def test_suppression_never_stops_measurement():
    """Suppression is about routing. A suppressed tier that stops being measured can never come back.

    The panel costs about seventeen dollars per five thousand items to keep whole, and that seventeen dollars is
    the budget that notices when a price change un-suppresses a tier.
    """
    spec = {f"i{k}": {"good": (SOLVED, 1.0), "useless": (INCORRECT, 2.0)} for k in range(50)}
    v = audit(_table(spec), practical_difference=0.005)
    assert v["useless"].state == SUPPRESSED
    assert all(x.must_keep_measuring for x in v.values())
    assert "still measured" in v["useless"].why


def test_the_verdict_records_what_it_was_conditioned_on():
    """A suppression is a claim about a price table on a date, not about a model in general."""
    spec = {f"i{k}": {"a": (SOLVED, 1.0), "b": (INCORRECT, 2.0)} for k in range(30)}
    v = audit(_table(spec), conditioned_on={"price_table": "2026-08-30", "box_concurrency_measured": False})
    assert v["b"].conditioned_on["price_table"] == "2026-08-30"
    assert v["b"].conditioned_on["box_concurrency_measured"] is False
    assert v["b"].conditioned_on["items"] == 30


def test_headroom_bounds_what_learning_could_win_before_anything_is_trained():
    """Run before starting a GPU: if the residual interval includes zero there is nothing to learn towards."""
    # `a` solves the first 60, `b` the last 60, of 100 -- so the oracle beats either alone by a lot.
    spec = {f"i{k}": {"a": (SOLVED if k < 60 else INCORRECT, 1.0),
                      "b": (SOLVED if k >= 40 else INCORRECT, 1.0)} for k in range(100)}
    t = _table(spec)
    h = headroom(t, single_tier("a"))
    assert h["oracle_solved"] == 100 and h["policy_solved"] == 60
    assert h["residual"] == pytest.approx(0.40)
    assert h["residual_ci"][0] > 0.2
    assert h["floor_items"] == 0

    # And a policy already at the ceiling has a residual of zero, which is the finding that stops the work.
    perfect = _table({f"i{k}": {"a": (SOLVED, 1.0)} for k in range(50)})
    h2 = headroom(perfect, single_tier("a"))
    assert h2["residual"] == 0.0 and h2["residual_ci"] == (0.0, 0.0)
