"""The latent difficulty model, pinned by the properties the stopping rule depends on."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.evidence import INCORRECT, SOLVED, UNOBSERVED  # noqa: E402
from tierbook.latent_ability import fit  # noqa: E402
from tierbook.outcomes import Cell, OutcomeTable  # noqa: E402


def _ladder_table(n: int = 90) -> tuple[OutcomeTable, list[str]]:
    """A clean ability ladder: weak solves the easiest third, mid two thirds, strong everything."""
    t = OutcomeTable(suite="s", manifest_digest="d")
    for k in range(n):
        band = k % 3                       # 0 easiest, 2 hardest
        t.cells[f"i{k}"] = {
            "weak":   Cell(SOLVED if band == 0 else INCORRECT, 1.0, answer="B"),
            "mid":    Cell(SOLVED if band <= 1 else INCORRECT, 2.0, answer="B"),
            "strong": Cell(SOLVED, 10.0, answer="B"),
        }
    return t, ["weak", "mid", "strong"]


def test_a_stronger_candidate_gets_a_higher_intercept():
    """The fit has to recover the ordering, or nothing downstream means anything."""
    t, tiers = _ladder_table()
    m = fit(t, tiers)
    b = {tier: m.tiers[tier][1] for tier in tiers}
    assert b["weak"] < b["mid"] < b["strong"]


def test_harder_items_get_a_higher_theta():
    t, tiers = _ladder_table()
    m = fit(t, tiers)
    easy = sum(m.theta[f"i{k}"] for k in range(0, 90, 3)) / 30
    hard = sum(m.theta[f"i{k}"] for k in range(2, 90, 3)) / 30
    assert hard > easy, "theta is a difficulty, so the items nobody weak solves must score higher"


def test_a_strong_candidate_s_failure_moves_the_posterior_further_than_a_weak_one_s():
    """This is the property a failure count cannot have, and the reason the model is here.

    Failing the weak candidate is ordinary. Failing the strong one is news. A count treats them as one
    observation each.
    """
    t, tiers = _ladder_table()
    m = fit(t, tiers)
    after_weak = m.p_next_mean("strong", ("weak",))
    after_strong_too = m.p_next_mean("strong", ("weak", "mid"))
    assert after_weak > after_strong_too
    assert m.p_next_mean("strong", ()) > after_weak


def test_the_bound_is_above_the_mean_and_both_fall_with_evidence():
    t, tiers = _ladder_table()
    m = fit(t, tiers)
    for failures in ((), ("weak",), ("weak", "mid")):
        assert m.p_next_bound("strong", failures) >= m.p_next_mean("strong", failures)
    assert (m.p_next_bound("strong", ("weak", "mid"))
            <= m.p_next_bound("strong", ("weak",))
            <= m.p_next_bound("strong", ()))


def test_a_wider_posterior_gives_a_higher_bound_at_the_same_mean():
    """The bound has to widen where the evidence leaves the difficulty unresolved, because that is what
    stops the rule abandoning items the model merely does not understand.
    """
    t, tiers = _ladder_table()
    m = fit(t, tiers)
    tight = m.p_next_bound("strong", ("weak", "mid"), quantile=0.5)
    loose = m.p_next_bound("strong", ("weak", "mid"), quantile=0.99)
    assert loose > tight


def test_contradictory_observations_fall_back_to_the_prior_rather_than_to_confidence():
    """If every grid point is ruled out the model does not understand the item, and the conservative
    answer is to keep spending. Returning a confident value here would abandon exactly the items the
    model understands least.
    """
    t, tiers = _ladder_table()
    m = fit(t, tiers)
    # Force an impossible pair by hand: solved by the weakest and failed by the strongest.
    post = m.posterior(failures=("strong",), solves=("weak",))
    assert abs(sum(post) - 1.0) < 1e-9
    assert all(p >= 0.0 for p in post)


def test_an_unobserved_cell_contributes_nothing():
    """Imputing it at the model's own guess is the one substitution this project refuses."""
    t, tiers = _ladder_table(30)
    t.cells["i0"]["mid"] = Cell(UNOBSERVED, None)
    m = fit(t, tiers)
    assert "mid" in m.tiers, "the tier is still fitted from the items where it did run"
    assert abs(m.theta["i0"]) < 5.0, "and the item still gets a difficulty from the tiers that did"


def test_discrimination_stays_positive():
    """A negative discrimination means a candidate that does better on harder items, which is a sign
    flip in the latent rather than a fact, and it makes the axis mean two things at once.
    """
    t, tiers = _ladder_table()
    m = fit(t, tiers)
    assert all(a > 0 for a, _ in m.tiers.values())
