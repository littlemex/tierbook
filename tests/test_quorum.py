"""The quorum stopping rule, pinned by the measurements that shaped it.

Four of these encode a fact that cost a measurement to learn: that agreement cannot be derived from
correctness, that an unparseable answer must escalate rather than be recovered, that an unpriced tier
must not be ranked as free, and that a conditional accuracy without its denominator is unreadable.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.evidence import INCORRECT, SOLVED, UNOBSERVED  # noqa: E402
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
    stopped, escalated = agreement(t, ("a", "b"), ["same-wrong", "diff-wrong"])
    assert stopped == ["same-wrong"]
    assert escalated == ["diff-wrong"]


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
    stopped, escalated = agreement(t, ("a", "b"), ["one-silent", "both-spoke"])
    assert stopped == ["both-spoke"]
    assert escalated == ["one-silent"], "two answers of which one is missing is not agreement"


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
    stopped, escalated = agreement(t, ("a", "missing"), ["i1"])
    assert stopped == []
    assert escalated == ["i1"]
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
    with_signal = evaluate_signal(t, "a", "dear", signal=signal, threshold=0.5)

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
    p = evaluate_signal(t, "a", "dear", signal={"read": 0.0}, threshold=0.5)
    assert p.stopped == 1, "the item with no reading escalated"
    assert p.accuracy == 0.5


def test_reading_the_signal_is_not_free():
    from tierbook.quorum import evaluate_signal
    t = _table({"i1": {"a": (SOLVED, "B", 1.0), "dear": (SOLVED, "B", 10.0)}})
    free = evaluate_signal(t, "a", "dear", signal={"i1": 0.0}, threshold=0.5)
    paid = evaluate_signal(t, "a", "dear", signal={"i1": 0.0}, threshold=0.5, probe_usd=0.25)
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
                  + enumerate_signal_policies(t, candidates=["a", "b"], escalate_to=["dear"],
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
