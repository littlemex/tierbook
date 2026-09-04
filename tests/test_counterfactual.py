"""The counterfactual evaluator, pinned by what it must refuse and by the arithmetic it must get exact."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.counterfactual import (  # noqa: E402
    Run, abandonment_oracle, bracket_gated_escalation, compare, oracle, regret, simulate,
)
from tierbook.evidence import INCORRECT, SOLVED, UNOBSERVED, EvidenceError  # noqa: E402
from tierbook.outcomes import Cell, OutcomeTable  # noqa: E402


def _t(n: int = 100) -> OutcomeTable:
    """cheap solves 3 of 4; dear solves all but every 20th; nobody solves item 0 mod 20 and 0 mod 4."""
    t = OutcomeTable(suite="s", manifest_digest="d")
    for i in range(n):
        cheap_ok = i % 4 != 0
        dear_ok = i % 20 != 0
        t.cells[f"i{i}"] = {
            "cheap": Cell(SOLVED if cheap_ok else INCORRECT, usd=1.0, answer="B" if cheap_ok else "C"),
            "dear": Cell(SOLVED if dear_ok else INCORRECT, usd=10.0, answer="B" if dear_ok else "E"),
        }
    return t


def test_the_oracle_pays_the_cheapest_solver_not_the_best_model():
    t = _t()
    items = list(t.items)
    o = oracle(t, ["cheap", "dear"], items)
    # cheap solves 75 of 100 at 1.0; of the 25 it misses, dear solves 20 at 10.0 and 5 nobody solves.
    assert o.accuracy == pytest.approx(0.95)
    # 75 items at 1.0 + 20 at 10.0 + 5 unsolvable paying the cheapest (1.0) = 75 + 200 + 5 = 280
    assert o.usd_per_item == pytest.approx(2.80)


def test_the_abandonment_oracle_is_strictly_stronger_and_kept_separate():
    """The gap between the two oracles IS the prize for predicting unsolvability."""
    t = _t()
    items = list(t.items)
    o, a = oracle(t, ["cheap", "dear"], items), abandonment_oracle(t, ["cheap", "dear"], items)
    assert a.accuracy == o.accuracy, "abandonment does not change what gets solved"
    assert a.usd_per_item < o.usd_per_item
    assert a.usd_per_item == pytest.approx(2.75), "the 5 unsolvable items now cost nothing"


def test_a_rule_that_calls_an_unobserved_cell_is_refused_rather_than_imputed():
    t = _t()
    t.cells["i0"]["ghost"] = Cell(UNOBSERVED, None)
    with pytest.raises(EvidenceError) as exc:
        simulate(t, lambda tb, item: ("ghost",), list(t.items), label="x")
    assert "imputed" in str(exc.value)


def test_a_rule_that_calls_nothing_is_refused():
    t = _t()
    with pytest.raises(EvidenceError):
        simulate(t, lambda tb, item: (), list(t.items), label="x")


def test_comparing_runs_over_different_items_is_refused():
    t = _t()
    a = simulate(t, lambda tb, i: ("cheap",), list(t.items), label="a")
    b = simulate(t, lambda tb, i: ("cheap",), list(t.items)[:50], label="b")
    with pytest.raises(EvidenceError) as exc:
        compare(a, b)
    assert "subset it chose" in str(exc.value)


def test_the_paired_comparison_reports_both_discordant_counts():
    """1.0 points can be 34 against 28 or 200 against 194, and those are different facts."""
    t = _t()
    items = list(t.items)
    a = simulate(t, lambda tb, i: ("cheap",), items, label="cheap")
    b = simulate(t, lambda tb, i: ("dear",), items, label="dear")
    c = compare(a, b)
    assert c.a_only + c.b_only > 0
    assert c.accuracy_delta == pytest.approx(a.accuracy - b.accuracy)
    assert "discordant" in str(c)


def test_a_dominating_policy_shows_zero_losses_and_a_significant_test():
    t = _t()
    items = list(t.items)
    # "always dear" strictly dominates "always cheap" on accuracy here.
    a = simulate(t, lambda tb, i: ("dear",), items, label="dear")
    b = simulate(t, lambda tb, i: ("cheap",), items, label="cheap")
    c = compare(a, b)
    assert c.b_only == 0, "cheap never rescues an item dear misses in this fixture"
    assert c.significant


def test_regret_splits_the_two_currencies_and_they_move_independently():
    """The point of splitting: "just call the dear model" has zero accuracy regret and huge cost regret."""
    t = _t()
    items = list(t.items)
    o = oracle(t, ["cheap", "dear"], items)
    # In this fixture dear's solve set contains cheap's, so always-dear gives up no accuracy at all...
    dear = regret(simulate(t, lambda tb, i: ("dear",), items, label="always dear"), o)
    assert dear.accuracy_regret == pytest.approx(0.0)
    assert dear.items_lost == 0
    assert dear.usd_ratio > 3.0, "...and pays several times the oracle for it"
    # ...while always-cheap is the mirror image: cheap on money, expensive in accuracy.
    cheap = regret(simulate(t, lambda tb, i: ("cheap",), items, label="always cheap"), o)
    assert cheap.accuracy_regret > 0.15
    assert cheap.usd_ratio < 1.0
    assert "spends" in str(cheap)


def test_the_bracket_holds_the_call_budget_fixed_between_its_two_ends():
    """Otherwise the pessimistic end is a cheaper policy rather than a fair floor."""
    t = _t()
    items = list(t.items)
    b = bracket_gated_escalation(t, items, first="cheap", escalate_to="dear")
    assert b.optimistic.calls_per_item == pytest.approx(b.pessimistic.calls_per_item)
    assert b.optimistic.usd_per_item == pytest.approx(b.pessimistic.usd_per_item)
    assert b.optimistic.accuracy > b.pessimistic.accuracy
    assert b.gate_rate == pytest.approx(0.25)


def test_the_bracket_says_in_its_own_field_names_that_it_is_hypothetical():
    t = _t()
    b = bracket_gated_escalation(t, list(t.items), first="cheap", escalate_to="dear")
    assert "HYPOTHETICAL" in str(b)


def test_a_perfect_gate_cannot_beat_the_oracle():
    """A sanity bound: the ceiling has to actually be a ceiling."""
    t = _t()
    items = list(t.items)
    o = oracle(t, ["cheap", "dear"], items)
    b = bracket_gated_escalation(t, items, first="cheap", escalate_to="dear")
    assert b.optimistic.accuracy <= o.accuracy + 1e-12
    assert b.optimistic.usd_per_item >= o.usd_per_item - 1e-12
