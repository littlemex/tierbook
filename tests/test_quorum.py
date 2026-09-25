"""The quorum stopping rule, pinned by the measurements that shaped it.

Four of these encode a fact that cost a measurement to learn: that agreement cannot be derived from
correctness, that an unparseable answer must escalate rather than be recovered, that an unpriced tier
must not be ranked as free, and that a conditional accuracy without its denominator is unreadable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.evidence import INCORRECT, SOLVED, UNOBSERVED, EvidenceError  # noqa: E402
from tierbook.outcomes import Cell, OutcomeTable  # noqa: E402
from tierbook.quorum import (  # noqa: E402
    agreement,
    cheapest_meeting,
    enumerate_policies,
    evaluate,
    frontier,
)


def _table(rows: dict[str, dict[str, tuple[str, str | None, float | None]]]) -> OutcomeTable:
    """`{item: {tier: (state, answer, usd)}}`."""
    t = OutcomeTable(suite="s", manifest_digest="d")
    for item, tiers in rows.items():
        t.cells[item] = {tier: Cell(state=st, usd=usd, answer=ans) for tier, (st, ans, usd) in tiers.items()}
    return t


def test_agreement_is_not_derivable_from_correctness():
    """Two candidates that are both wrong may agree or disagree, and only the answers say which.

    This is the reason `Cell.answer` exists. A table carrying correctness alone can express "both
    failed" but not "both failed the same way", and the second is what a stopping rule reads.
    """
    t = _table({
        "same-wrong": {"a": (INCORRECT, "B", 1.0), "b": (INCORRECT, "B", 1.0)},
        "diff-wrong": {"a": (INCORRECT, "B", 1.0), "b": (INCORRECT, "C", 1.0)},
    })
    stopped = agreement(t, ("a", "b"), ["same-wrong", "diff-wrong"])
    assert stopped == {"same-wrong": "B"}, "the selected answer travels with the stopped item now (round 3)"


def test_an_absent_answer_escalates_and_is_never_recovered():
    """A member that produced no answer cannot be shown to agree, so the item escalates.

    Measured on the corpus this rule came from: of 200 malformed cells, the 63 from which an answer
    could be recovered were graded incorrect in every case, so recovering them moves wrong answers
    into the set the policy stops on and costs 1.1 points of accuracy on that set.
    """
    t = _table({
        "one-silent": {"a": (SOLVED, "B", 1.0), "b": (INCORRECT, None, 1.0)},
        "both-spoke": {"a": (SOLVED, "B", 1.0), "b": (SOLVED, "B", 1.0)},
    })
    stopped = agreement(t, ("a", "b"), ["one-silent", "both-spoke"])
    assert stopped == {"both-spoke": "B"}, "two answers of which one is missing is not agreement"


def test_the_stop_rule_defaults_to_agreement_and_a_declared_rule_is_carried():
    """TB-034's fix applied to `evaluate`: `agreement` is the DEFAULT a caller who declares nothing still gets, and
    a different study's stop rule can be expressed through `stop_rule` without editing this module."""
    t = _table({
        "same-wrong": {"a": (INCORRECT, "B", 1.0), "b": (INCORRECT, "B", 1.0), "dear": (SOLVED, "B", 5.0)},
        "diff-wrong": {"a": (INCORRECT, "B", 1.0), "b": (INCORRECT, "C", 1.0), "dear": (SOLVED, "B", 5.0)},
    })
    default = evaluate(t, ("a", "b"), "dear")
    assert (default.stopped, default.items) == (1, 2), "unchanged: unanimity stops on the agreeing item only"

    def never_stop(table, members, items):
        return {}

    everything_escalates = evaluate(t, ("a", "b"), "dear", stop_rule=never_stop)
    assert everything_escalates.stopped == 0, "a declared rule overrides agreement entirely"


def test_evaluate_scores_the_rules_selected_answer_not_any_member_solved():
    """Round 3's fix: three members answer wrong "W", wrong "W", correct "C" on one item. A majority rule stops
    on "W" (two of three), which is WRONG -- but the old scoring read "did any member solve it", which is TRUE
    here because the third member (who did not even agree) happened to be right. `evaluate` must read the
    correctness of the SELECTED answer, not of the membership."""
    t = _table({"x": {"a": (INCORRECT, "W", 1.0), "b": (INCORRECT, "W", 1.0), "c": (SOLVED, "C", 1.0),
                     "dear": (SOLVED, "C", 5.0)}})

    def majority_of_three(table, members, items):
        out = {}
        for item in items:
            answers = [_cell_answer(table, item, m) for m in members]
            majority = max(set(answers), key=answers.count)
            out[item] = majority
        return out

    p = evaluate(t, ("a", "b", "c"), "dear", stop_rule=majority_of_three)
    assert p.stopped == 1, "the item stopped (a majority was reached)"
    assert p.solved == 0, "the SELECTED answer ('W') was wrong, so the item must not be scored as solved"


def test_evaluate_scores_a_majority_rule_correctly_when_the_majority_is_right():
    """The mirror of the case above: the majority's answer IS correct, and must score as solved even though one
    member (a minority) disagreed -- unlike `agreement`, which would have escalated this item entirely."""
    t = _table({"x": {"a": (SOLVED, "C", 1.0), "b": (SOLVED, "C", 1.0), "c": (INCORRECT, "W", 1.0),
                     "dear": (INCORRECT, "W", 5.0)}})

    def majority_of_three(table, members, items):
        out = {}
        for item in items:
            answers = [_cell_answer(table, item, m) for m in members]
            majority = max(set(answers), key=answers.count)
            out[item] = majority
        return out

    p = evaluate(t, ("a", "b", "c"), "dear", stop_rule=majority_of_three)
    assert p.stopped == 1
    assert p.solved == 1, "the majority's own answer ('C') was correct"


def _cell_answer(table, item, tier):
    return table.cells.get(item, {}).get(tier).answer


def test_an_injected_rule_that_invents_an_item_id_is_refused():
    t = _table({"x": {"a": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 5.0)}})

    def invents(table, members, items):
        return {i: "B" for i in items} | {"nonexistent": "B"}

    with pytest.raises(EvidenceError, match="not among the"):
        evaluate(t, ("a",), "dear", stop_rule=invents)


def test_an_injected_rule_that_stops_with_no_answer_is_refused():
    """Stopping on an item means committing to an answer for it; a falsy answer (empty string, None) is not a
    commitment, and letting it through would make `_answer_is_correct` silently read as 'wrong' for a reason
    that has nothing to do with correctness."""
    t = _table({"x": {"a": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 5.0)}})

    def stops_with_nothing(table, members, items):
        return {i: "" for i in items}

    with pytest.raises(EvidenceError, match="no answer"):
        evaluate(t, ("a",), "dear", stop_rule=stops_with_nothing)


def test_a_duplicate_item_in_the_callers_own_items_is_refused_before_the_rule_runs():
    """A reviewer found the earlier version of this check blamed the STOP RULE for a duplicate the CALLER
    supplied in `items` -- `agreement` just reflects whatever duplicate it is handed. The message must name the
    caller's own input, not the rule."""
    t = _table({"x": {"a": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 5.0)}})

    with pytest.raises(EvidenceError, match="items contains duplicate"):
        evaluate(t, ("a",), "dear", items=["x", "x"])


def test_a_single_member_policy_stops_on_everything():
    """One candidate has nothing to disagree with, so this is 'the cheap tier answers, nobody checks'.

    It is the cheap end of the frontier, not a case to exclude: pricing it is how the frontier shows
    what the checking is worth.
    """
    t = _table({
        "i1": {"a": (SOLVED, "B", 0.5), "dear": (SOLVED, "B", 5.0)},
        "i2": {"a": (INCORRECT, "C", 0.5), "dear": (SOLVED, "B", 5.0)},
    })
    p = evaluate(t, ("a",), "dear")
    assert p.stopped == p.items == 2
    assert p.solved == 1
    assert p.usd_per_item == 0.5, "no escalation happened, so the dear tier is not in the bill"


def test_escalation_uses_the_dear_tier_and_the_bill_reflects_it():
    t = _table({
        "agree": {"a": (SOLVED, "B", 0.5), "b": (SOLVED, "B", 0.5), "dear": (SOLVED, "B", 5.0)},
        "split": {"a": (INCORRECT, "C", 0.5), "b": (INCORRECT, "D", 0.5), "dear": (SOLVED, "B", 5.0)},
    })
    p = evaluate(t, ("a", "b"), "dear")
    assert (p.stopped, p.solved) == (1, 2)
    assert p.accuracy == 1.0
    # both members on both items, plus the dear tier on the one that split
    assert p.usd_per_item == (0.5 * 2 * 2 + 5.0) / 2


def test_an_unpriced_cell_makes_the_policy_unpriced_not_free():
    """A self-hosted tier with no recorded cost wins every comparison it should lose if it is zeroed.

    So the policy reports `None` and the frontier drops it, rather than ranking it first.
    """
    t = _table({
        "i1": {"a": (SOLVED, "B", None), "b": (SOLVED, "B", 0.5), "dear": (SOLVED, "B", 5.0)},
    })
    p = evaluate(t, ("a", "b"), "dear")
    assert p.usd_per_item is None
    assert not p.priced
    assert frontier([p]) == [], "an unpriced policy cannot be said to dominate or be dominated"


def test_prices_override_the_matrix_so_repricing_is_not_remeasuring():
    """The point of the separation: a new rate card is an argument, never a new run."""
    t = _table({
        "agree": {"a": (SOLVED, "B", 99.0), "b": (SOLVED, "B", 99.0), "dear": (SOLVED, "B", 99.0)},
        "split": {"a": (INCORRECT, "C", 99.0), "b": (INCORRECT, "D", 99.0), "dear": (SOLVED, "B", 99.0)},
    })
    p = evaluate(t, ("a", "b"), "dear", prices={"a": 1.0, "b": 1.0, "dear": 10.0})
    assert p.usd_per_item == (1.0 * 2 * 2 + 10.0) / 2
    assert p.accuracy == 1.0, "re-pricing must not move the accuracy"


def test_a_one_member_policy_cannot_use_the_escalation_tier_at_all():
    """Because one candidate always "agrees", it never escalates -- so it cannot be rescued.

    This is not obvious and it bounds what the rule can do. A cheap tier that answers everything with
    no second opinion is stuck at its own accuracy no matter how good the escalation tier is; buying a
    second member is what creates the disagreement the escalation tier is there to resolve. A router
    that escalates on a *confidence signal* has a third option, and that option is a different
    mechanism from this one.
    """
    rows = {f"i{n}": ({"a": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 5.0)} if n % 4 else
                      {"a": (INCORRECT, "C", 1.0), "dear": (SOLVED, "B", 5.0)})
            for n in range(40)}
    t = _table(rows)
    alone = evaluate(t, ("a",), "dear")
    assert alone.stopped == alone.items
    assert alone.accuracy == 0.75, "a's own accuracy, and the dear tier never gets a turn"
    assert alone.usd_per_item == 1.0, "so the dear tier is not in the bill either"


def test_the_chosen_escalation_tier_changes_with_the_price_vector():
    """The whole reason this is a mechanism and not an answer.

    Same matrix, same quality floor, two rate cards, two different cheapest policies. The measured
    version of this question was "should the tier that answers the escalated items be the frontier
    model or a mid-priced one", and the answer moved between folds and would move again on a new rate
    card -- so it has to be computed, not remembered.
    """
    rows = {}
    for n in range(40):
        if n % 4 == 3:
            # The cheap pair splits on ten items. `mid` gets eight of them right and `dear` all ten,
            # so `mid` clears a 0.9 floor at 0.95 and `dear` reaches 1.0.
            rows[f"i{n}"] = {"a": (INCORRECT, "C", None), "b": (INCORRECT, "D", None),
                             "mid": (SOLVED if n < 35 else INCORRECT, "B", None),
                             "dear": (SOLVED, "B", None)}
        else:
            rows[f"i{n}"] = {"a": (SOLVED, "B", None), "b": (SOLVED, "B", None),
                             "mid": (SOLVED, "B", None), "dear": (SOLVED, "B", None)}
    t = _table(rows)

    def best(prices, floor):
        ps = enumerate_policies(t, candidates=["a", "b"], escalate_to=["mid", "dear"],
                                prices=prices, min_stopped=10)
        return cheapest_meeting(ps, accuracy_floor=floor)

    # `mid` clears a 0.9 floor and is cheaper, so it wins.
    when_mid_is_cheap = best({"a": 1.0, "b": 1.0, "mid": 3.0, "dear": 100.0}, 0.9)
    # Re-price `mid` above `dear` and the same floor now picks `dear`, which is also more accurate.
    when_mid_is_dear = best({"a": 1.0, "b": 1.0, "mid": 200.0, "dear": 100.0}, 0.9)

    assert when_mid_is_cheap is not None and when_mid_is_dear is not None
    assert when_mid_is_cheap.escalate_to == "mid"
    assert when_mid_is_dear.escalate_to == "dear"
    assert when_mid_is_cheap.accuracy < when_mid_is_dear.accuracy, (
        "the cheaper choice gives up accuracy, and the floor is what bounds how much"
    )


def test_a_policy_whose_stop_set_is_too_thin_is_dropped():
    """`accuracy_when_stopped` over eleven items is not a number anyone should read.

    A one-member policy is exempt because it stops on everything, so its conditional accuracy is just
    its accuracy.
    """
    rows = {f"i{n}": {"a": (SOLVED, "B", 1.0), "b": (SOLVED, f"ans{n}", 1.0), "dear": (SOLVED, "B", 5.0)}
            for n in range(50)}
    rows["agreed"] = {"a": (SOLVED, "B", 1.0), "b": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 5.0)}
    t = _table(rows)
    ps = enumerate_policies(t, candidates=["a", "b"], escalate_to=["dear"], min_stopped=30)
    pairs = [p for p in ps if p.members == ("a", "b")]
    assert pairs == [], "the pair agrees on one item, so its conditional accuracy is unreadable"
    assert any(p.members == ("a",) for p in ps), "a one-member policy stops on everything"


def test_a_member_is_never_also_the_escalation_tier():
    t = _table({f"i{n}": {"a": (SOLVED, "B", 1.0), "b": (SOLVED, "B", 1.0)} for n in range(40)})
    ps = enumerate_policies(t, candidates=["a", "b"], escalate_to=["a", "b"], min_stopped=1)
    assert all(p.escalate_to not in p.members for p in ps)


def test_the_denominator_travels_with_the_conditional_accuracy():
    t = _table({
        "agree": {"a": (SOLVED, "B", 1.0), "b": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 5.0)},
        "split": {"a": (INCORRECT, "C", 1.0), "b": (INCORRECT, "D", 1.0), "dear": (INCORRECT, "E", 5.0)},
    })
    p = evaluate(t, ("a", "b"), "dear")
    assert (p.stopped, p.solved_when_stopped) == (1, 1)
    assert p.accuracy_when_stopped == 1.0
    assert p.accuracy == 0.5, "the conditional accuracy is not the policy's accuracy"


def test_frontier_keeps_only_what_nothing_dominates():
    t = _table({
        "agree": {"a": (SOLVED, "B", 1.0), "b": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 5.0)},
        "split": {"a": (INCORRECT, "C", 1.0), "b": (INCORRECT, "D", 1.0), "dear": (SOLVED, "B", 5.0)},
    })
    ps = enumerate_policies(t, candidates=["a", "b"], escalate_to=["dear"], min_stopped=1)
    front = frontier(ps)
    assert front, "some policy must survive"
    assert front == sorted(front, key=lambda p: p.usd_per_item)
    for p in front:
        assert not any(q is not p and q.accuracy >= p.accuracy and q.usd_per_item < p.usd_per_item
                       for q in front)


def test_cheapest_meeting_returns_none_when_the_floor_is_unreachable():
    t = _table({
        "i1": {"a": (INCORRECT, "C", 1.0), "dear": (INCORRECT, "D", 5.0)},
    })
    ps = enumerate_policies(t, candidates=["a"], escalate_to=["dear"], min_stopped=1)
    assert cheapest_meeting(ps, accuracy_floor=0.5) is None


def test_an_unobserved_cell_is_an_absent_answer():
    """A tier that was never run on an item has no answer, so it cannot complete a quorum."""
    t = _table({"i1": {"a": (SOLVED, "B", 1.0)}})
    stopped = agreement(t, ("a", "missing"), ["i1"])
    assert stopped == {}
    assert Cell(UNOBSERVED, None).answer is None


# --- the third mechanism, on the same frontier ----------------------------------------------------

def test_a_signal_policy_can_escalate_where_a_one_member_quorum_cannot():
    """This is why the signal shape has to exist: it is strictly more expressive.

    One candidate always agrees with itself, so a one-member quorum never escalates and is stuck at
    that candidate's accuracy. A threshold escalates exactly the items the signal flags, so the same
    candidate plus a usable signal can reach past its own ceiling.
    """
    rows, signal = {}, {}
    for n in range(40):
        wrong = n % 4 == 3
        rows[f"i{n}"] = {"a": (INCORRECT if wrong else SOLVED, "C" if wrong else "B", 1.0),
                         "dear": (SOLVED, "B", 10.0)}
        # A perfect signal: high exactly on the items `a` gets wrong.
        signal[f"i{n}"] = 1.0 if wrong else 0.0
    t = _table(rows)

    from tierbook.quorum import evaluate_signal
    quorum_alone = evaluate(t, ("a",), "dear")
    with_signal = evaluate_signal(t, "a", "dear", signal=signal, about="own_competence", threshold=0.5)

    assert quorum_alone.accuracy == 0.75, "no escalation is possible, so a's own accuracy is the ceiling"
    assert with_signal.accuracy == 1.0, "the threshold sends exactly the items a gets wrong"
    assert with_signal.stopped == 30
    assert with_signal.mechanism == "signal" and quorum_alone.mechanism == "single"


def test_an_item_with_no_signal_reading_escalates():
    """Defaulting a missing reading to 'confident' sends unmeasured items to the cheap tier, which is
    the direction that flatters the policy. So absence escalates, as it does in a quorum.
    """
    from tierbook.quorum import evaluate_signal
    t = _table({
        "read":   {"a": (INCORRECT, "C", 1.0), "dear": (SOLVED, "B", 10.0)},
        "unread": {"a": (INCORRECT, "C", 1.0), "dear": (SOLVED, "B", 10.0)},
    })
    p = evaluate_signal(t, "a", "dear", signal={"read": 0.0}, about="own_competence", threshold=0.5)
    assert p.stopped == 1, "the item with no reading escalated"
    assert p.accuracy == 0.5


def test_reading_the_signal_is_not_free():
    from tierbook.quorum import evaluate_signal
    t = _table({"i1": {"a": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 10.0)}})
    free = evaluate_signal(t, "a", "dear", signal={"i1": 0.0}, about="own_competence", threshold=0.5)
    paid = evaluate_signal(t, "a", "dear", signal={"i1": 0.0}, about="own_competence", threshold=0.5, probe_usd=0.25)
    assert paid.usd_per_item == free.usd_per_item + 0.25


def test_all_three_mechanisms_are_ranked_on_one_frontier():
    """A frontier that cannot express a mechanism cannot rule it out either.

    This encodes the comparison error the module was extended to prevent: a quorum was recommended
    after being compared only against a probe threshold and against the dear tier answering
    everything, while a single candidate answering everything dominated it and was never enumerated.
    """
    from tierbook.quorum import enumerate_signal_policies
    rows, signal = {}, {}
    for n in range(60):
        a_wrong, b_wrong = n % 3 == 0, n % 5 == 0
        rows[f"i{n}"] = {
            "a": (INCORRECT if a_wrong else SOLVED, "C" if a_wrong else "B", 1.0),
            "b": (INCORRECT if b_wrong else SOLVED, "D" if b_wrong else "B", 2.0),
            "dear": (SOLVED, "B", 20.0),
        }
        signal[f"i{n}"] = 1.0 if a_wrong else 0.0
    t = _table(rows)

    everything = (enumerate_policies(t, candidates=["a", "b"], escalate_to=["a", "b", "dear"],
                                     min_stopped=10)
                  + enumerate_signal_policies(t, candidates=["a", "b"], escalate_to=["dear"], about="own_competence",
                                              signal=signal))
    front = frontier(everything)
    assert front, "some policy must survive"
    mechanisms = {p.mechanism for p in front}
    assert "single" in mechanisms, "a single candidate answering everything is a policy"
    assert "signal" in mechanisms, "a perfect signal must appear; it reaches 100% cheaply"
    # And the frontier is a frontier: nothing on it is beaten on both axes.
    for p in front:
        assert not any(q is not p and q.accuracy >= p.accuracy and q.usd_per_item < p.usd_per_item
                       for q in front)


def test_policies_whose_escalation_never_fired_collapse_to_one():
    """With eight candidates a never-escalating policy is eight identical frontier rows.

    They differ in a field no request ever read, they crowd out the rows that represent a real choice,
    and they inflate the count of "how many frontier points use mechanism X" -- which this module
    reports, so the inflation would be read as a finding.
    """
    from tierbook.quorum import canonical
    rows = {f"i{n}": {"a": (SOLVED, "B", 1.0), "x": (SOLVED, "B", 5.0), "y": (SOLVED, "B", 9.0)}
            for n in range(40)}
    t = _table(rows)
    ps = enumerate_policies(t, candidates=["a"], escalate_to=["x", "y"], min_stopped=1)
    assert len(ps) == 2, "both escalation tiers are enumerated"
    assert all(p.stopped == p.items for p in ps), "and neither ever escalates"
    assert len(canonical(ps)) == 1, "so they are one decision"
    assert len(frontier(ps)) == 1


def test_a_policy_that_does_escalate_is_never_collapsed():
    from tierbook.quorum import canonical
    rows = {}
    for n in range(40):
        if n % 4:
            rows[f"i{n}"] = {"a": (SOLVED, "B", 1.0), "b": (SOLVED, "B", 1.0),
                             "x": (SOLVED, "B", 5.0), "y": (SOLVED, "B", 9.0)}
        else:
            rows[f"i{n}"] = {"a": (INCORRECT, "C", 1.0), "b": (INCORRECT, "D", 1.0),
                             "x": (SOLVED, "B", 5.0), "y": (SOLVED, "B", 9.0)}
    t = _table(rows)
    ps = [p for p in enumerate_policies(t, candidates=["a", "b"], escalate_to=["x", "y"],
                                       min_stopped=1) if p.members == ("a", "b")]
    assert len(ps) == 2 and all(p.stopped < p.items for p in ps)
    assert len(canonical(ps)) == 2, "the escalation tier was actually used, so the two differ"


def test_cheapest_meeting_does_not_pick_between_identical_decisions_at_random():
    """Two runs of the same data must not look like they disagree because a tie broke differently.

    A never-escalating policy exists once per candidate escalation tier, all identical in accuracy and
    cost. Returning any of them makes a reproducibility check report a difference that is not one --
    which is what happened before `cheapest_meeting` canonicalised.
    """
    rows = {f"i{n}": {"a": (SOLVED, "B", 1.0), "x": (SOLVED, "B", 5.0), "y": (SOLVED, "B", 9.0),
                      "z": (SOLVED, "B", 7.0)} for n in range(40)}
    t = _table(rows)
    ps = enumerate_policies(t, candidates=["a"], escalate_to=["x", "y", "z"], min_stopped=1)
    picks = {(cheapest_meeting(ps, accuracy_floor=0.5).members,
              cheapest_meeting(ps, accuracy_floor=0.5).escalate_to)}
    # And the same set in a different enumeration order still gives the same answer.
    picks.add((cheapest_meeting(list(reversed(ps)), accuracy_floor=0.5).members,
               cheapest_meeting(list(reversed(ps)), accuracy_floor=0.5).escalate_to))
    assert len(picks) == 1, f"the tie broke two ways: {picks}"


# --- is the quorum doing anything, or is it one model wearing two hats? ---------------------------

def test_joint_failure_is_measured_not_inferred_from_shared_weights():
    """Two candidates sharing weights are not necessarily correlated, and the matrix is what says so.

    Measured on one corpus: pairs sharing weights disagreed on 2.7% to 35.7% of answers and pairs from
    different families on 9.4% to 46.3%, with identical medians. So the mechanism reads the pair's own
    numbers rather than any label about provenance.
    """
    from tierbook.quorum import joint_failure
    # `a` and `b` fail together on every item either fails: a perfect echo.
    echo = _table({f"i{n}": {"a": (SOLVED if n % 3 else INCORRECT, "B", 1.0),
                             "b": (SOLVED if n % 3 else INCORRECT, "B", 1.0)} for n in range(30)})
    assert joint_failure(echo, "a", "b", list(echo.items)) == 1.0
    # `c` and `d` never fail on the same item.
    apart = _table({f"i{n}": {"c": (SOLVED if n % 2 else INCORRECT, "B", 1.0),
                              "d": (INCORRECT if n % 2 else SOLVED, "B", 1.0)} for n in range(30)})
    assert joint_failure(apart, "c", "d", list(apart.items)) == 0.0


def test_no_item_wrong_for_either_is_an_absent_measurement_not_a_low_correlation():
    from tierbook.quorum import joint_failure
    t = _table({f"i{n}": {"a": (SOLVED, "B", 1.0), "b": (SOLVED, "B", 1.0)} for n in range(10)})
    assert joint_failure(t, "a", "b", list(t.items)) is None


def test_agreement_lift_exposes_a_quorum_that_does_nothing():
    """A pair of near-duplicates stops on almost everything and adds almost nothing.

    Measured, the worst real pair lifted +0.8% while stopping on 97% of items -- one model wearing two
    hats. A stop rate cannot tell that from a real quorum, so the lift is carried alongside it.
    """
    # Two echoes of one model: they always agree, so the quorum stops everywhere and the agreed answer
    # is exactly what either member would have said.
    rows = {f"i{n}": {"a": (SOLVED if n % 4 else INCORRECT, "B" if n % 4 else "C", 1.0),
                      "b": (SOLVED if n % 4 else INCORRECT, "B" if n % 4 else "C", 1.0),
                      "dear": (SOLVED, "B", 10.0)}
            for n in range(80)}
    echo = evaluate(_table(rows), ("a", "b"), "dear")
    assert echo.stop_rate == 1.0
    assert echo.worst_joint_failure == 1.0
    assert echo.agreement_lift == pytest.approx(0.0, abs=1e-9), (
        "stopping on everything at the member's own accuracy is not a quorum")


def test_agreement_lift_is_positive_where_the_quorum_earns_its_place():
    """When the members fail on different items, agreement selects the ones both got right."""
    rows = {}
    for n in range(80):
        a_ok, b_ok = n % 3 != 0, n % 4 != 0        # they fail on different items
        rows[f"i{n}"] = {
            "a": (SOLVED if a_ok else INCORRECT, "B" if a_ok else "C", 1.0),
            "b": (SOLVED if b_ok else INCORRECT, "B" if b_ok else "D", 1.0),
            "dear": (SOLVED, "B", 10.0),
        }
    p = evaluate(_table(rows), ("a", "b"), "dear")
    assert p.worst_joint_failure < 0.5
    assert p.agreement_lift > 0.05, "agreement selects the items both members got right"
    assert p.stop_rate < 1.0


def test_a_one_member_policy_has_no_pair_so_no_joint_failure():
    t = _table({f"i{n}": {"a": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 5.0)} for n in range(30)})
    p = evaluate(t, ("a",), "dear")
    assert p.worst_joint_failure is None
    assert p.agreement_lift == pytest.approx(0.0, abs=1e-9), (
        "one member agreeing with itself adds nothing by construction")


def test_the_wrong_stop_rate_is_what_an_operator_feels():
    """`stop_rate x (1 - accuracy_when_stopped)`: how often a confident wrong answer goes out.

    Neither figure it is built from says this on its own, and it is the one that decides whether a
    policy is shippable.
    """
    rows = {}
    for n in range(100):
        agree = n % 4 != 0                        # they agree on 75%
        right = n % 8 != 0                        # and are wrong on half of the disagreeing... no:
        rows[f"i{n}"] = {
            "a": (SOLVED if right else INCORRECT, "B" if agree else "C", 1.0),
            "b": (SOLVED if right else INCORRECT, "B" if agree else "D", 1.0),
            "dear": (SOLVED, "B", 10.0),
        }
    p = evaluate(_table(rows), ("a", "b"), "dear")
    expected = (p.stopped - p.solved_when_stopped) / p.items
    assert p.wrong_stop_rate == pytest.approx(expected)
    assert p.wrong_stop_rate == pytest.approx(p.stop_rate * (1 - p.accuracy_when_stopped), abs=1e-9)


def test_a_policy_score_is_never_a_product_of_marginals():
    """Two matrices with identical per-candidate accuracy and different joint structure must score
    differently, or the implementation is multiplying marginals somewhere.

    Both reviewers named this as the invariant that makes correlation a measured fact rather than a
    distortion needing correction: if no independence formula appears in the code, there is nothing to
    correct for.
    """
    # Both matrices: `a` right on 50%, `b` right on 50%. In the first they fail together; in the second
    # they fail on disjoint items.
    together, apart = {}, {}
    for n in range(80):
        half = n % 2 == 0
        together[f"i{n}"] = {"a": (SOLVED if half else INCORRECT, "B" if half else "C", 1.0),
                             "b": (SOLVED if half else INCORRECT, "B" if half else "C", 1.0),
                             "dear": (SOLVED, "B", 10.0)}
        apart[f"i{n}"] = {"a": (SOLVED if half else INCORRECT, "B" if half else "C", 1.0),
                          "b": (INCORRECT if half else SOLVED, "C" if half else "B", 1.0),
                          "dear": (SOLVED, "B", 10.0)}
    ta, tb = _table(together), _table(apart)
    for t in (ta, tb):
        for cand in ("a", "b"):
            acc = sum(1 for i in t.items if t.cells[i][cand].solved) / len(list(t.items))
            assert acc == pytest.approx(0.5), "the marginals are identical by construction"
    pa = evaluate(ta, ("a", "b"), "dear")
    pb = evaluate(tb, ("a", "b"), "dear")
    assert pa.stop_rate != pb.stop_rate, "the joint structure has to reach the score"
    assert pa.worst_joint_failure != pb.worst_joint_failure
    assert pa.accuracy != pb.accuracy


def test_no_candidate_is_pruned_by_its_own_accuracy():
    """The measured counterexample: a serving configuration 9 points weaker on its own was the best
    member of the best pair. Pruning on single accuracy would have removed it.
    """
    rows = {}
    for n in range(80):
        strong = n % 10 != 0                      # 90%
        weak = n % 2 == 0                         # 50%, and wrong where `strong` is right
        rows[f"i{n}"] = {
            "strong": (SOLVED if strong else INCORRECT, "B" if strong else "C", 1.0),
            "weak": (SOLVED if weak else INCORRECT, "B" if weak else "D", 1.0),
            "dear": (SOLVED, "B", 10.0),
        }
    ps = enumerate_policies(_table(rows), candidates=["strong", "weak"], escalate_to=["dear"],
                            min_stopped=1)
    assert any(p.members == ("strong", "weak") for p in ps), (
        "the weak candidate must still be enumerated as a member")


def _small_signal_table():
    """Two candidates over eight items, built the way the tests above build one."""
    rows, signal = {}, {}
    for n in range(8):
        wrong = n % 4 == 3
        rows[f"i{n}"] = {"a": (INCORRECT if wrong else SOLVED, "C" if wrong else "B", 1.0),
                         "dear": (SOLVED, "B", 5.0)}
        signal[f"i{n}"] = 0.9 if wrong else 0.1
    return _table(rows), signal


def test_a_signal_has_to_say_what_it_is_about():
    """DEFECT this still closes: `evaluate_signal` took a bare dict of numbers with nothing saying what they were about,
    so a topic classifier and a confidence readout arrived identically and produced policies described identically. The
    measurement is brutal -- at one layer the same readout named the item's field at 0.7593 against a chance of 0.1429
    and predicted its own error at 0.4227, below the 0.5 a coin gets.

    What it no longer does is **decide which of them is worth escalating on.** It refused everything except competence
    and difficulty, from a list in the mechanism, so a study measuring topic to predict competence could not say so. The
    requirement that survives is only that the signal name what it is about."""
    from tierbook.quorum import evaluate_signal
    t, signal = _small_signal_table()
    with pytest.raises(EvidenceError, match="has to say what it is about"):
        evaluate_signal(t, "a", "dear", signal=signal, about="vibes", threshold=0.5)


@pytest.mark.parametrize("about", ["own_competence", "item_difficulty", "topic", "resource_state"])
def test_every_named_subject_is_admitted_and_the_policy_records_which(about):
    """All four, deliberately. Whether a topic signal earns a gate is decided by what somebody measures about it, and the
    policy carries the answer to 'about what' so a reader can check the claim rather than trust the name."""
    from tierbook.quorum import evaluate_signal
    t, signal = _small_signal_table()
    assert evaluate_signal(t, "a", "dear", signal=signal, about=about, threshold=0.5) is not None


def test_the_refusal_message_names_the_declared_vocabulary_without_a_nameerror():
    """A round-3 review flagged that the refusal message interpolates `{vocabulary}` and asked whether that name is
    actually bound -- if it were not, this would raise `NameError` instead of `EvidenceError`, and no test read the
    message closely enough to notice. It IS bound (`vocabulary = subjects or DEFAULT_SUBJECTS`, just above the
    raise); this test pins that down for both the default and a declared vocabulary."""
    from tierbook.quorum import evaluate_signal
    t, signal = _small_signal_table()
    with pytest.raises(EvidenceError) as exc:
        evaluate_signal(t, "a", "dear", signal=signal, about="vibes", threshold=0.5)
    assert type(exc.value) is EvidenceError
    assert "('topic', 'own_competence', 'item_difficulty', 'resource_state')" in str(exc.value)

    with pytest.raises(EvidenceError) as exc2:
        evaluate_signal(t, "a", "dear", signal=signal, about="vibes", threshold=0.5,
                        subjects=("own_competence",))
    assert type(exc2.value) is EvidenceError
    assert "('own_competence',)" in str(exc2.value)


def test_the_subject_vocabulary_is_declarable_and_the_default_reproduces_todays_refusal():
    """F141's move applied to the one closed vocabulary this module still checks membership against: a caller who
    declares nothing gets exactly today's refusal, and a caller whose signal is about something the default does not
    name can declare it rather than being unable to build a policy at all."""
    from tierbook.quorum import evaluate_signal
    t, signal = _small_signal_table()
    with pytest.raises(EvidenceError, match="is not one of"):
        evaluate_signal(t, "a", "dear", signal=signal, about="vibes", threshold=0.5)
    p = evaluate_signal(t, "a", "dear", signal=signal, about="vibes", threshold=0.5,
                        subjects=("vibes", "own_competence", "item_difficulty", "topic", "resource_state"))
    assert p is not None


def test_the_word_subject_no_longer_has_three_meanings_in_this_module():
    """"subject" already means a candidate in this package, and this function's own body used it for a list of item ids.
    The parameter is `about` and the local is `item_ids`, because three meanings of one word in one file is how the wrong
    one gets read."""
    import inspect

    from tierbook.quorum import evaluate_signal
    src = inspect.getsource(evaluate_signal)
    assert "item_ids" in src
    assert "subject = " not in src


def test_stoprule_is_a_deprecated_alias_for_itemstoprule():
    """Round 2 renamed `quorum.StopRule` to `ItemStopRule` (to stop colliding with `router.StopRule`'s
    incompatible signature) with no alias, which breaks any importer who held the old bare name -- the same
    import break round 1's fix for finding 8 was written to prevent."""
    import tierbook.quorum as quorum_mod
    assert quorum_mod.StopRule is quorum_mod.ItemStopRule
