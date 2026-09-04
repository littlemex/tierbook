"""Asking the same question twice, pinned by the three reversals that motivated the module."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.evidence import INCORRECT, SOLVED, UNOBSERVED, EvidenceError  # noqa: E402
from tierbook.outcomes import Cell, OutcomeTable  # noqa: E402
from tierbook.reproduce import compare, wilson  # noqa: E402


def _t(rows: dict[str, dict[str, tuple[str, str | None, float | None]]]) -> OutcomeTable:
    t = OutcomeTable(suite="s", manifest_digest="d")
    for item, tiers in rows.items():
        t.cells[item] = {k: Cell(state=st, usd=usd, answer=ans) for k, (st, ans, usd) in tiers.items()}
    return t


def _pair(n: int, flip_every: int | None = None):
    """Two runs of the same matrix; `flip_every` makes the cheap candidate disagree with itself."""
    a, b = {}, {}
    for i in range(n):
        cheap_ok = i % 3 != 0
        cheap_ok_2 = (not cheap_ok) if (flip_every and i % flip_every == 0) else cheap_ok
        a[f"i{i}"] = {"cheap": (SOLVED if cheap_ok else INCORRECT, "B" if cheap_ok else "C", 1.0),
                      "dear": (SOLVED, "B", 10.0)}
        b[f"i{i}"] = {"cheap": (SOLVED if cheap_ok_2 else INCORRECT, "B" if cheap_ok_2 else "C", 1.0),
                      "dear": (SOLVED, "B", 10.0)}
    return _t(a), _t(b)


def test_a_stable_matrix_fails_no_claim():
    one, two = _pair(90)
    r = compare(one, two, candidates=["cheap", "dear"], floors=(0.60, 0.90))
    assert r.items == 90
    assert r.flips == {"cheap": 0, "dear": 0}
    assert r.failed == [], "\n".join(str(c) for c in r.failed)


def test_a_flipping_candidate_is_reported_with_an_interval():
    one, two = _pair(90, flip_every=9)
    r = compare(one, two, candidates=["cheap", "dear"], floors=(0.60,))
    rate, low, high = r.flip_rate("cheap")
    assert r.flips["cheap"] == 10
    assert rate == pytest.approx(10 / 90)
    assert low < rate < high, "a bare point estimate invites arithmetic the interval forbids"
    assert 0.0 <= low and high <= 1.0


def test_only_items_complete_in_both_runs_are_compared():
    """A second run that lost a block of items leaves a subset that is biased, not merely smaller.

    A token expiring mid-run does exactly that when work is dispatched in order, and it happened here,
    so the item count travels with every figure rather than being a footnote.
    """
    one, two = _pair(60)
    for i in range(40, 60):                       # the second run never reached these
        two.cells[f"i{i}"]["cheap"] = Cell(UNOBSERVED, None)
    r = compare(one, two, candidates=["cheap", "dear"], floors=(0.60,))
    assert r.items == 40


def test_a_candidate_missing_from_one_run_is_refused():
    """Dropping it changes the pool, and a different pool is a different question."""
    one, two = _pair(60)
    for item in two.cells.values():
        item.pop("dear")
    with pytest.raises(EvidenceError) as exc:
        compare(one, two, candidates=["cheap", "dear"], floors=(0.60,))
    assert "different pool is a different question" in str(exc.value)


def test_no_shared_item_is_refused_rather_than_averaged():
    one = _t({"a": {"x": (SOLVED, "B", 1.0)}})
    two = _t({"b": {"x": (SOLVED, "B", 1.0)}})
    with pytest.raises(EvidenceError):
        compare(one, two, candidates=["x"], floors=(0.5,))


def test_the_cheapest_policy_at_a_floor_is_checked_by_identity_not_by_price():
    """Two policies at the same price are still two different things to operate.

    This is the claim an owner acts on, and it is the one that changed at two of four floors in the
    measurement that motivated the module.
    """
    # Run 2 makes `mid` better, so a floor it missed in run 1 is cleared in run 2 by a different policy.
    a, b = {}, {}
    for i in range(60):
        mid_ok_1 = i % 4 != 0                     # 75%
        mid_ok_2 = i % 12 != 0                    # 91.7%
        for src, ok in ((a, mid_ok_1), (b, mid_ok_2)):
            src[f"i{i}"] = {
                "cheap": (SOLVED if i % 2 else INCORRECT, "B" if i % 2 else "C", 1.0),
                "mid": (SOLVED if ok else INCORRECT, "B" if ok else "D", 4.0),
                "dear": (SOLVED, "B", 40.0),
            }
    r = compare(_t(a), _t(b), candidates=["cheap", "mid", "dear"], floors=(0.90,), min_stopped=5)
    floor_claims = [c for c in r.claims if c.kind == "cheapest_at_floor"]
    assert len(floor_claims) == 1
    assert not floor_claims[0].survived, floor_claims[0]
    assert "mid" in floor_claims[0].second


def test_an_ordering_swap_is_its_own_claim_when_run_1_s_margin_was_real():
    """A candidate crossing another is what moved the frontier in practice.

    The margin in run 1 has to be significant first, or the "swap" is noise reversing.
    """
    a, b = {}, {}
    for i in range(120):
        # Run 1: p right on 95%, q on 55%, and they disagree constantly -- a real margin.
        # Run 2: exactly reversed.
        p1, q1 = i % 20 != 0, i % 2 == 0
        a[f"i{i}"] = {"p": (SOLVED if p1 else INCORRECT, "B", 1.0),
                      "q": (SOLVED if q1 else INCORRECT, "B", 1.0)}
        b[f"i{i}"] = {"p": (SOLVED if q1 else INCORRECT, "B", 1.0),
                      "q": (SOLVED if p1 else INCORRECT, "B", 1.0)}
    r = compare(_t(a), _t(b), candidates=["p", "q"], floors=())
    orderings = [c for c in r.claims if c.kind == "ordering"]
    assert orderings, "run 1's margin was significant, so the ordering is a claim"
    assert orderings[0].p_value is not None and orderings[0].p_value < 0.05
    assert not orderings[0].survived, "and it reversed"


def test_an_ordering_that_was_never_significant_makes_no_claim():
    """"A beats B" at 80% against 75% over 60 items is two intervals crossing, not a fact.

    With eight candidates there are 28 such pairs, so without this gate most ordering claims would be
    flags planted in noise -- and their later reversal would be reported as a finding.
    """
    a, b = {}, {}
    for i in range(60):
        p1, q1 = i % 5 != 0, i % 4 != 0          # 80% vs 75%
        p2, q2 = i % 4 != 0, i % 5 != 0          # reversed
        a[f"i{i}"] = {"p": (SOLVED if p1 else INCORRECT, "B", 1.0),
                      "q": (SOLVED if q1 else INCORRECT, "B", 1.0)}
        b[f"i{i}"] = {"p": (SOLVED if p2 else INCORRECT, "B", 1.0),
                      "q": (SOLVED if q2 else INCORRECT, "B", 1.0)}
    r = compare(_t(a), _t(b), candidates=["p", "q"], floors=())
    assert not [c for c in r.claims if c.kind == "ordering"], (
        "the ordering reversed, but run 1 never had the margin to claim it in the first place")


def test_a_tie_in_either_run_makes_no_ordering_claim():
    """A tie cannot be said to have swapped or held, so it is not counted either way."""
    a = {f"i{i}": {"p": (SOLVED, "B", 1.0), "q": (SOLVED, "B", 1.0)} for i in range(30)}
    r = compare(_t(a), _t(dict(a)), candidates=["p", "q"], floors=())
    assert not [c for c in r.claims if c.kind == "ordering"]


def test_the_summary_never_calls_anything_reproducible():
    """Two runs give a difference, not a variance. A claim that survived one repeat has not yet failed.
    """
    one, two = _pair(60)
    text = compare(one, two, candidates=["cheap", "dear"], floors=(0.60,)).summary()
    assert "have not yet failed" in text
    assert "reproducible" not in text.lower()


def test_wilson_stays_inside_the_unit_interval_where_the_normal_approximation_does_not():
    low, high = wilson(0, 30)
    assert low == 0.0 and 0.0 < high < 1.0
    low, high = wilson(30, 30)
    assert high == 1.0 and 0.0 < low < 1.0
    # The textbook interval would put this one below zero.
    low, high = wilson(1, 137)
    assert low > 0.0


def test_the_drop_out_is_reported_and_its_shape_is_measured():
    """A contiguous block of losses is a token expiring; scattered ones are per-item pathology.

    The two need different responses -- one invalidates the subset, the other does not -- so the shape is
    measured rather than assumed.
    """
    one, two = _pair(100)
    for i in range(60, 100):                     # a contiguous tail, as an interrupted run loses
        two.cells[f"i{i}"]["cheap"] = Cell(UNOBSERVED, None)
    clustered = compare(one, two, candidates=["cheap", "dear"], floors=(0.60,))
    assert clustered.items == 60
    assert clustered.dropout == pytest.approx(0.40)
    assert clustered.dropped_are_clustered == pytest.approx(1.0), "one block"
    assert clustered.limiting_candidate == "cheap"

    one2, two2 = _pair(100)
    for i in range(0, 100, 5):                   # scattered, as content filtering does
        two2.cells[f"i{i}"]["cheap"] = Cell(UNOBSERVED, None)
    scattered = compare(one2, two2, candidates=["cheap", "dear"], floors=(0.60,))
    assert scattered.dropped_are_clustered < 0.2, "no block"


def test_a_candidate_with_thin_coverage_is_refused_by_name():
    """Three observations pass a presence check and then silently collapse the comparison to three
    items, so the failure shows up as an unexplained item count instead of as missing coverage.
    """
    one, two = _pair(100)
    for i in range(3, 100):
        two.cells[f"i{i}"]["cheap"] = Cell(UNOBSERVED, None)
    with pytest.raises(EvidenceError) as exc:
        compare(one, two, candidates=["cheap", "dear"], floors=(0.60,))
    assert "cheap" in str(exc.value) and "floor" in str(exc.value)


def test_subset_integrity_is_checked_before_anything_else():
    """If restricting to the shared items moves run 1's own answer, every later claim is about a
    reconstruction rather than a recollection, and the reader has to know that first.
    """
    a, b = {}, {}
    for i in range(120):
        # `mid` is right on the first 60 items and wrong on the rest, so dropping the tail changes
        # which policy is cheapest for run 1 itself.
        mid = i < 60
        for src in (a, b):
            src[f"i{i}"] = {"cheap": (SOLVED if i % 2 else INCORRECT, "B" if i % 2 else "C", 1.0),
                            "mid": (SOLVED if mid else INCORRECT, "B" if mid else "D", 3.0),
                            "dear": (SOLVED, "B", 30.0)}
    one, two = _t(a), _t(b)
    for i in range(60, 120):
        two.cells[f"i{i}"]["mid"] = Cell(UNOBSERVED, None)
    r = compare(one, two, candidates=["cheap", "mid", "dear"], floors=(0.80,), min_stopped=5)
    integrity = [c for c in r.claims if c.kind == "subset_integrity"]
    assert integrity, "the check must run whenever anything was dropped"
    assert r.claims[0].kind == "subset_integrity", "and it must be reported first"


def test_expected_failures_by_chance_is_reported_next_to_the_count():
    one, two = _pair(120)
    r = compare(one, two, candidates=["cheap", "dear"], floors=(0.60,))
    assert r.expected_failures_by_chance >= 0.0
    assert "expected by chance" in r.summary()
