"""The outcome table and the policy comparison, pinned by the mistakes each part prevents.

Two of these encode errors made in this repository within the last day: an unpriced tier charged as zero, which
produced a headline saving that rested on treating a model as free; and a two-valued verdict, which is how one
twenty-item arm losing became "a whole class of approach is out of scope".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.evidence import INCORRECT, SOLVED, UNOBSERVED, EvidenceError  # noqa: E402
from tierbook.optimise import (  # noqa: E402
    FAILS,
    PASSES,
    UNDETERMINED,
    Constraints,
    bucket_policy,
    fit_bucket_policy,
    single_tier,
    verdict,
)
from tierbook.outcomes import REFUSE, Cell, OutcomeTable  # noqa: E402


def _table(spec: dict, features: dict | None = None, suite="s", digest="d") -> OutcomeTable:
    """`spec` is {item: {tier: (state, usd)}}."""
    t = OutcomeTable(suite=suite, manifest_digest=digest)
    for item, row in spec.items():
        t.cells[item] = {tier: Cell(state=st, usd=usd) for tier, (st, usd) in row.items()}
    t.features = dict(features or {})
    return t


# --- an unpriced tier is not a free tier ----------------------------------------------------------


def test_an_unpriced_tier_is_excluded_and_named_never_charged_as_zero():
    """The exact error made here: a model with no price came out cheapest and carried a 3.0x headline.

    Exclusion is honest and reported. Coercing the missing price to zero makes that tier win every comparison,
    and the resulting figure looks like the best result in the table.
    """
    t = _table({
        "i1": {"cheap": (SOLVED, 0.01), "free": (SOLVED, None)},
        "i2": {"cheap": (SOLVED, 0.01), "free": (INCORRECT, None)},
    })
    priced, unpriced = t.priced_tiers()
    assert priced == ["cheap"] and unpriced == ["free"]
    # The oracle over priced tiers only must not pick the unpriced one, however well it did.
    solved, spend, chosen = t.oracle_cheapest(tiers=priced)
    assert set(chosen.values()) == {"cheap"}
    assert spend == pytest.approx(0.02)
    # And spend for the unpriced tier is None rather than 0.0, so a caller cannot add it up by accident.
    assert t.spend_of("free") is None

    with pytest.raises(EvidenceError, match="charged as zero"):
        fit_bucket_policy(_table({"i1": {"free": (SOLVED, None)}}), ["i1"], feature="c",
                          constraints=Constraints(margin=0.05), may_train_on=True)


# --- the floor, and what it does to a headroom claim ----------------------------------------------


def test_the_floor_is_subtracted_before_headroom_is_claimed():
    """Items no tier solved are unreachable, so progress measured against the oracle without them is inflated."""
    t = _table({
        "solved_by_all": {"a": (SOLVED, 0.1), "b": (SOLVED, 0.2)},
        "only_b": {"a": (INCORRECT, 0.1), "b": (SOLVED, 0.2)},
        "nobody": {"a": (INCORRECT, 0.1), "b": (INCORRECT, 0.2)},
    })
    assert t.floor() == ["nobody"]
    assert t.any_correct() == 2
    solved, spend, _ = t.oracle_cheapest()
    assert solved == 2
    # The unreachable item still costs something: a request nobody can answer is not a free request.
    assert spend == pytest.approx(0.1 + 0.2 + 0.1)


def test_the_solver_count_histogram_is_the_difficulty_axis():
    """It decides what a predictor must be good at, which an average cannot show.

    An item every tier solves needs the cheapest tier and no prediction; an item one tier solves needs the
    predictor to find that one. A table whose mass sits at the top is a cost problem, not a routing problem.
    """
    t = _table({
        "all": {"a": (SOLVED, 0.1), "b": (SOLVED, 0.2)},
        "one": {"a": (SOLVED, 0.1), "b": (INCORRECT, 0.2)},
        "none": {"a": (INCORRECT, 0.1), "b": (INCORRECT, 0.2)},
    })
    assert t.solver_count_histogram() == {2: 1, 1: 1, 0: 1}


# --- joins are on a manifest, not on an id --------------------------------------------------------


def test_evidence_from_two_suites_refuses_to_join():
    """Same defect as the paired derivation: an id-only join cannot see a reused id whose content changed."""
    from tierbook.evidence import Evidence

    a = Evidence(path="a", header={"suite_manifest_digest": "sha256:" + "a" * 64, "subject": "x",
                                  "family": "f"}, verdicts={"i1": (SOLVED, None)})
    b = Evidence(path="b", header={"suite_manifest_digest": "sha256:" + "b" * 64, "subject": "y",
                                  "family": "f"}, verdicts={"i1": (SOLVED, None)})
    with pytest.raises(EvidenceError, match="different suite manifest digests"):
        OutcomeTable.from_evidence([a, b])


def test_two_artifacts_claiming_one_subject_refuse():
    from tierbook.evidence import Evidence

    h = {"suite_manifest_digest": "sha256:" + "a" * 64, "subject": "x", "family": "f"}
    a = Evidence(path="a", header=h, verdicts={"i1": (SOLVED, None)})
    b = Evidence(path="b", header=dict(h), verdicts={"i1": (INCORRECT, None)})
    with pytest.raises(EvidenceError, match="same subject"):
        OutcomeTable.from_evidence([a, b])


# --- fitting and judging must not share items -----------------------------------------------------


def test_fitting_and_judging_on_the_same_items_refuses():
    """A twenty-item fold here chose a tier whose bound failed out of fold; in-sample it looked fine."""
    t = _table({f"i{n}": {"a": (SOLVED, 0.1), "b": (SOLVED, 0.2)} for n in range(6)},
               features={f"i{n}": {"c": "x"} for n in range(6)})
    cons = Constraints(margin=0.05)
    pol, _ = fit_bucket_policy(t, t.items, feature="c", constraints=cons, may_train_on=True)
    with pytest.raises(EvidenceError, match="both the calibration and held-out folds"):
        verdict(t, pol, single_tier("b"), t.items, constraints=cons, calibration=t.items)


# --- the three-valued verdict ---------------------------------------------------------------------


def _fold(n, *, cheap_solves, start=0):
    """n items where `b` always solves and `a` solves the first `cheap_solves` of them."""
    return {f"i{start+k}": {"a": (SOLVED if k < cheap_solves else INCORRECT, 0.01),
                            "b": (SOLVED, 1.00)} for k in range(n)}


def test_an_inconclusive_sample_is_undetermined_not_a_failure():
    """The correction that matters most, and it fires on the real corpus at a margin of 0.02.

    Reporting an interval that straddles the target as a failure over-reads the sample. That is precisely the
    error that removed a class of approach from this project's scope on the strength of one twenty-item arm.
    """
    t = _table(_fold(20, cheap_solves=17))
    cal = _table(_fold(20, cheap_solves=17, start=100))
    t.cells.update(cal.cells)
    holdout = [f"i{k}" for k in range(20)]
    v = verdict(t, single_tier("a"), single_tier("b"), holdout,
                constraints=Constraints(margin=0.15, alpha=0.05))
    assert v["answer"] == UNDETERMINED, v
    assert v["lower_bound"] < v["target"] < v["upper_bound"], v
    assert "would over-read" in v["why"] or "over-read" in v["why"]


def test_a_sample_that_does_decide_against_the_candidate_says_so():
    """`undetermined` must not swallow a real defeat, or the three-valued verdict buys nothing."""
    t = _table(_fold(60, cheap_solves=20))
    holdout = t.items
    v = verdict(t, single_tier("a"), single_tier("b"), holdout,
                constraints=Constraints(margin=0.05, alpha=0.05))
    assert v["answer"] == FAILS, v
    assert v["upper_bound"] < v["target"], v


def test_passing_the_target_is_not_a_claim_of_being_better():
    """The naming defect the first version shipped: a candidate inside the margin was called `better`.

    It can be five points worse and still pass the test its owner set. The verdict names the target, and the
    observed difference is printed beside it so the two cannot be confused.
    """
    t = _table(_fold(200, cheap_solves=196))
    v = verdict(t, single_tier("a"), single_tier("b"), t.items,
                constraints=Constraints(margin=0.10, alpha=0.05))
    assert v["answer"] == PASSES
    assert v["difference"] < 0, "this candidate is genuinely worse on quality"
    assert "not that it is better" in v["why"]


def test_a_breached_constraint_fails_regardless_of_the_bound():
    t = _table(_fold(100, cheap_solves=99))
    v = verdict(t, single_tier("a"), single_tier("b"), t.items,
                constraints=Constraints(margin=0.10, max_usd_per_answered=0.001))
    assert v["answer"] == FAILS
    assert "above the stated ceiling" in v["why"]


def test_constraints_nobody_stated_are_listed_not_treated_as_satisfied():
    """"Cost was within budget" and "nobody set a budget" must be distinguishable in the output."""
    t = _table(_fold(40, cheap_solves=39))
    v = verdict(t, single_tier("a"), single_tier("b"), t.items, constraints=Constraints(margin=0.10))
    assert set(v["constraints_not_stated"]) == {"min_solve_rate", "max_usd_per_answered", "max_refusal_rate"}


# --- refusal is an action -------------------------------------------------------------------------


def test_refusing_is_an_action_and_the_comparison_says_how_much_it_covered():
    """A policy that refuses half the traffic has not been compared with one that answered all of it."""
    t = _table(_fold(20, cheap_solves=20), features={f"i{k}": {"c": "keep" if k < 10 else "drop"}
                                                     for k in range(20)})
    pol = bucket_policy({"keep": "a", "drop": REFUSE}, feature="c", default="b")
    v = verdict(t, pol, single_tier("b"), t.items, constraints=Constraints(margin=0.10))
    assert v["candidate"]["refused"] == 10
    assert v["compared_on"] == 10 and v["holdout_items"] == 20


def test_a_policy_naming_a_tier_with_no_observation_refuses():
    t = _table(_fold(4, cheap_solves=4))
    with pytest.raises(EvidenceError, match="no observed outcome"):
        t.evaluate(single_tier("nonexistent"))


# --- the frontier -------------------------------------------------------------------------------


def test_the_frontier_marks_what_nothing_dominates_rather_than_scoring():
    """Collapsing quality and cost into one number picks an exchange rate nobody outside can state."""
    t = _table({
        "i1": {"cheap": (SOLVED, 0.01), "mid": (SOLVED, 0.5), "dear": (SOLVED, 1.0)},
        "i2": {"cheap": (INCORRECT, 0.01), "mid": (SOLVED, 0.5), "dear": (SOLVED, 1.0)},
    })
    rows = t.frontier({n: single_tier(n) for n in ("cheap", "mid", "dear")})
    by = {r["policy"]: r for r in rows}
    # `dear` costs more than `mid` for the same solve count, so it is dominated. `cheap` is cheapest and
    # therefore on the frontier even though it solves less -- that is the trade the owner has to make.
    assert by["dear"]["on_frontier"] is False and "mid" in by["dear"]["dominated_by"]
    assert by["mid"]["on_frontier"] and by["cheap"]["on_frontier"]


def test_fitting_on_a_corpus_nobody_checked_the_training_terms_for_refuses():
    """A licence fact that does not show up in the licence identifier, so it has to be asked for.

    OmniDocBench-JASyn is CC BY-4.0 and its own dataset card states that using it for model training or
    distillation is prohibited, because it was generated with a model whose usage policy forbids that. Fitting
    a policy on a corpus is training on it. `None` is treated as not permitted, because a licence question
    answered by omission is answered wrongly -- and the omission is silent whereas this refusal is not.
    """
    t = _table({f"i{n}": {"a": (SOLVED, 0.1), "b": (SOLVED, 0.2)} for n in range(4)},
               features={f"i{n}": {"c": "x"} for n in range(4)})
    for permission in (None, False):
        with pytest.raises(EvidenceError, match="training on it"):
            fit_bucket_policy(t, t.items, feature="c", constraints=Constraints(margin=0.05),
                              may_train_on=permission)
    pol, info = fit_bucket_policy(t, t.items, feature="c", constraints=Constraints(margin=0.05),
                                  may_train_on=True)
    assert pol is not None
