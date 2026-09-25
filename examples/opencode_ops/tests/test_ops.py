"""Tests that drive the whole loop, and one that fails if the loop does not change anything.

**The failure mode this file exists to catch.** An Ops loop is easy to write so that it records beautifully, reports
confidently and never moves a single request. Every test here is therefore about a *difference*: what the loop does
against what a fixed policy would have done, what it does before evidence arrives against after, what it reports when an
arm is measured against when it is not.

The second thing under test is the split the example exists to demonstrate. Nothing in `src/tierbook` knows what
`price_per_mtok` or `tenant_quota_left` mean, and nothing in it prefers a cheap candidate. So there is a test here that
**flips the measurement and demands the preference flip with it** -- if it does not, a preference has been built into the
mechanism or into the example's code rather than derived from what was recorded, and that is the defect this project has
been corrected on more than once.
"""
from __future__ import annotations

import random

import pytest

from tierbook import decide as dc
from tierbook import throughput as th

from examples.opencode_ops import policy as P
from examples.opencode_ops.adapter import ScriptedAgent, request_body
from examples.opencode_ops.ops import Ops
from examples.opencode_ops.state import World


def a_world(**over) -> World:
    kw = dict(price_per_mtok={P.CHEAP: 1.0, P.DEAR: 4.0}, tenant_quota_left=50.0, hour_of_day=14,
              inflight={P.CHEAP: 2})
    kw.update(over)
    return World(**kw)


def an_ops(*, box_accepts: float = 0.5, api_accepts: float = 1.0, seed: int = 0, **world) -> Ops:
    return Ops(world=a_world(**world), agent=ScriptedAgent(accepts={P.CHEAP: box_accepts, P.DEAR: api_accepts}),
               rng=random.Random(seed))


def run(ops: Ops, turns: int, *, start: float = 1000.0) -> list:
    return [ops.turn(f"task {i}", now=start + i) for i in range(turns)]


# --- the loop has to actually do something --------------------------------------------------------------------------

def test_the_loop_spends_less_per_accepted_answer_than_always_escalating():
    """The headline. A loop that records and never routes fails here, which is the whole reason this test is first.

    The comparison is against a fixed policy that always sends to the dear candidate -- the same tasks, the same fake,
    the same acceptance rates, so the only difference is who decided. Per **accepted** answer, because per request would
    reward refusing to answer.
    """
    looped = an_ops()
    run(looped, 40)

    always_dear = an_ops()
    for i in range(40):
        body = request_body(f"task {i}")
        reply = always_dear.agent(body, candidate=P.DEAR)
        price = always_dear.world.price_per_mtok[P.DEAR]
        always_dear.history.append({"candidate": P.DEAR, "accepted": reply.accepted, "price": price,
                                    "spend": reply.input_mtok * price + reply.output_mtok * price * 3.0,
                                    "harness": None, "harness_vocabulary": None, "propensity": 1.0,
                                    "explored": False, "why": "fixed", "capacity": "unknown"})

    assert looped.spend_per_accepted() is not None
    assert looped.spend_per_accepted() < always_dear.spend_per_accepted()


def test_the_loop_keeps_most_traffic_on_the_measured_cheaper_arm():
    """Not just cheaper on average -- the traffic actually moves, and stays moved.

    The dear share has to be small **and non-zero**: zero would mean the loop stopped exploring, and a loop that stops
    exploring cannot notice a price change. This asserts the band rather than a direction, because both edges are wrong.
    """
    ops = an_ops()
    turns = run(ops, 60)
    dear = sum(1 for t in turns if t.candidate == P.DEAR)
    assert 0 < dear <= 9, f"{dear} of 60 turns went to the dear candidate"


def test_exploration_is_what_makes_the_comparison_possible_at_all():
    """The cold-start deadlock, pinned so it cannot come back.

    Every threshold is derived from history and the price threshold needs history on the dear candidate, which a loop
    that only escalates when that threshold exists can never accrue. With exploration the dear arm gets measured and the
    comparison becomes available; with the rate forced to zero it never does.
    """
    explores = an_ops()
    run(explores, 30)
    assert {r["candidate"] for r in explores.history} == {P.CHEAP, P.DEAR}
    assert explores.preferred() is not None

    class NeverExplores(Ops):
        def exploration_rate(self) -> float:
            return 0.0

    stuck = NeverExplores(world=a_world(), agent=ScriptedAgent(accepts={P.CHEAP: 0.5, P.DEAR: 1.0}),
                          rng=random.Random(0))
    run(stuck, 30)
    assert {r["candidate"] for r in stuck.history} == {P.CHEAP}
    assert stuck.preferred() is None


def test_the_exploration_rate_falls_once_both_arms_have_been_seen():
    ops = an_ops()
    assert ops.exploration_rate() == 0.5
    run(ops, 30)
    assert {r["candidate"] for r in ops.history} == {P.CHEAP, P.DEAR}
    assert ops.exploration_rate() == 0.05


def test_every_turn_records_the_propensity_it_was_chosen_with():
    """Traffic that arrived by exploration was not chosen by the policy, and a later comparison needs to know which."""
    ops = an_ops()
    run(ops, 30)
    assert all(0.0 < r["propensity"] <= 1.0 for r in ops.history)
    explored = [r for r in ops.history if r["explored"]]
    assert explored, "no turn was explored, so the propensity field is untested"
    assert all(r["why"] == "explored" for r in explored)
    assert all(r["propensity"] < 1.0 for r in explored)


# --- the preference is derived, not built in ------------------------------------------------------------------------

def test_the_preference_follows_the_measurement_and_flips_when_the_measurement_does():
    """**The meta-rule, as a test.** Nothing prefers the cheap candidate. The recorded numbers do, or do not.

    Same prices, same loop, same seed. Only the acceptance rates differ, and they differ enough to invert cost per
    accepted answer: at 0.5 the cheap arm costs 0.032 an answer against the dear arm's 0.064, and at 0.2 it costs 0.08.
    If both runs report the same preference, something has an opinion that is not coming from the evidence.
    """
    cheap_wins = an_ops(box_accepts=0.5)
    run(cheap_wins, 60)
    assert cheap_wins.preferred() == P.CHEAP

    dear_wins = an_ops(box_accepts=0.2)
    run(dear_wins, 60)
    assert dear_wins.preferred() == P.DEAR


def test_a_preference_is_withheld_while_either_arm_is_unmeasured():
    ops = an_ops()
    run(ops, 1)
    assert ops.preferred() is None
    assert ops.spend_per_accepted(P.DEAR) is None


def test_the_denominator_is_accepted_answers_not_requests():
    """Every request costs; only accepted ones count. A loop optimising cost per request optimises for refusing."""
    ops = an_ops(box_accepts=0.5)
    run(ops, 4)
    rows = [r for r in ops.history if r["candidate"] == P.CHEAP]
    accepted = sum(1 for r in rows if r["accepted"])
    assert accepted < len(rows), "the fake accepted everything, so the denominator is untested"
    expected = sum(r["spend"] for r in rows) / accepted
    assert ops.spend_per_accepted(P.CHEAP) == pytest.approx(expected)
    assert ops.spend_per_accepted(P.CHEAP) > sum(r["spend"] for r in rows) / len(rows)


def test_nothing_is_derived_from_no_history():
    """A cold start derives nothing and says so, rather than falling back to a plausible constant."""
    assert P.thresholds_from_history([]) == {}
    assert an_ops().thresholds() == {}


def test_the_thresholds_are_derived_from_what_was_recorded():
    ops = an_ops()
    run(ops, 30)
    got = ops.thresholds()
    assert got["quota_floor"] == max(r["spend"] for r in ops.history)
    dear = [r["price"] for r in ops.history if r["candidate"] == P.DEAR]
    assert got["price_cross"] == pytest.approx(sum(dear) / len(dear))


def test_the_quota_runs_down_as_the_loop_spends_it():
    ops = an_ops(tenant_quota_left=1.0)
    before = ops.world.tenant_quota_left
    run(ops, 10)
    assert ops.world.tenant_quota_left < before


# --- capacity: the performance currency, and what it may and may not decide ------------------------------------------

def a_measured(goodput: float, *, per_hour: float | None = None, understated: str = "") -> th.Throughput:
    return th.Throughput(per_hour=per_hour if per_hour is not None else goodput,
                         offered=th.Offered(concurrency=64, seats=64, generator="two load clients"),
                         arrivals="open_loop", deadline_seconds=8.0, goodput_per_hour=goodput,
                         understated_because=understated)


def test_a_declared_ceiling_below_the_requirement_vetoes_that_candidate_entirely():
    ops = an_ops(capacity={P.DEAR: th.Ceiling(per_hour=50.0, declared_by="the vendor's published rate limit")})
    turns = run(ops, 40)
    assert all(t.capacity[P.DEAR] == "refused" for t in turns)
    assert all(t.candidate == P.CHEAP for t in turns)
    assert not ops.shown_to_carry_the_traffic(P.DEAR)


def test_a_refused_deterministic_choice_is_overridden_rather_than_sent_to():
    """The policy can name a candidate whose capacity refuses the rate. The example moves it and records that it did."""
    ops = an_ops(capacity={P.CHEAP: th.Ceiling(per_hour=10.0, declared_by="the engine's own admission limit")})
    turns = run(ops, 20)
    assert all(t.capacity[P.CHEAP] == "refused" for t in turns)
    assert all(t.candidate == P.DEAR for t in turns)


def test_unknown_capacity_does_not_veto_but_cannot_be_reported_as_carrying_the_traffic():
    """`unknown` is the entry that keeps the other two honest, and the loop treats it as neither.

    A shortfall against a lower bound may be this project's own load generator -- which it has published as a box's
    capacity twice -- so it does not shrink the pool. What it does cost is the claim: the loop may route there and may
    not report that the candidate was shown to hold the traffic.
    """
    ops = an_ops(capacity={P.DEAR: a_measured(60.0, understated="generator_saturated")})
    turns = run(ops, 40)
    assert all(t.capacity[P.DEAR] == "unknown" for t in turns)
    assert any(t.candidate == P.DEAR for t in turns), "an unknown capacity vetoed the arm, which is not the rule"
    assert not ops.shown_to_carry_the_traffic(P.DEAR)


def test_a_closed_loop_measurement_cannot_answer_the_capacity_question():
    """A closed loop offers less when the server slows, so no queue forms and a deadline has nothing to be missed
    against. The example gets `unknown` for it whatever the rate says, which is the mechanism's refusal and not this
    example's."""
    closed = th.Throughput(per_hour=5000.0, offered=th.Offered(concurrency=64, seats=64, generator="one client"),
                           arrivals="closed_loop")
    ops = an_ops(capacity={P.DEAR: closed})
    outcome, why = ops.world.can_deliver(P.DEAR, ops.required_per_hour)
    assert outcome == "unknown"
    assert "closed loop" in why
    assert not ops.shown_to_carry_the_traffic(P.DEAR)


def test_a_measured_goodput_that_covers_the_requirement_is_reportable():
    ops = an_ops(capacity={P.CHEAP: a_measured(820.0, per_hour=900.0)})
    assert ops.shown_to_carry_the_traffic(P.CHEAP)
    assert ops.eligible()[1][P.CHEAP] == "deliverable"


def test_a_candidate_with_no_capacity_evidence_is_unknown_rather_than_either():
    ops = an_ops()
    assert ops.eligible()[1] == {P.CHEAP: "unknown", P.DEAR: "unknown"}
    assert ops.eligible()[0] == [P.CHEAP, P.DEAR]


# --- the seam between the example and the mechanism ------------------------------------------------------------------

def test_the_policy_declares_every_variable_its_guards_read():
    """The example invents three facts the mechanism has never heard of, and the mechanism carries guards over them
    because the policy declares them. Anything undeclared would be a guard nobody can supply a value for."""
    pol = P.build({"quota_floor": 0.1, "price_cross": 2.0})
    assert pol.undeclared_vars() == []
    assert "price_per_mtok" in pol.vocabulary
    assert "tenant_quota_left" in pol.vocabulary


def test_a_guard_over_an_undeclared_variable_is_named():
    """The other half of the same guarantee: declaring a vocabulary is worth nothing unless omission is detected.

    This reads over the rules' guards. An earlier version read a non-existent attribute on the rule itself and would
    have raised on any real policy -- it passed because its only test built a policy out of bare guards.
    """
    pol = P.build({"quota_floor": 0.1})
    broken = dc.Policy(pol.family,
                       pol.rules + (dc.Rule((dc.Guard("gpu_temperature", ">=", 80.0, derived_from="a thermometer"),),
                                            (P.DEAR,), "the box is hot"),),
                       pol.default, state_vars=pol.state_vars, per_candidate=pol.per_candidate, note=pol.note)
    assert broken.undeclared_vars() == ["gpu_temperature"]


def test_the_spend_is_recorded_on_four_legs_with_the_cache_legs_present_as_zero():
    """An omitted split is not a zero cache rate, and a later comparison against a cached arm has to be able to refuse."""
    ops = an_ops()
    turn = ops.turn("one task", now=1000.0)
    assert turn.cost.cached_in == 0.0
    assert turn.cost.cache_write == 0.0
    assert turn.cost.total == pytest.approx(turn.cost.prefill + turn.cost.generation)


def test_the_harness_is_read_from_the_request_and_the_instruction_changes_its_identity():
    """The two wordings differ by more than politeness -- one sentence moved accuracy 12.04 points on this project's own
    corpus -- so a loop that could not tell them apart would be reporting a comparison it never made."""
    ops = an_ops()
    terse = ops.turn("task", now=1000.0, terse=True)
    verbose = ops.turn("task", now=1001.0, terse=False)
    again = ops.turn("task", now=1002.0, terse=True)
    assert terse.harness_identity is not None
    assert terse.harness_identity != verbose.harness_identity
    assert terse.harness_identity == again.harness_identity


def test_the_loop_reports_what_the_harness_could_not_see():
    """A request cannot carry every part of a harness, and the unseen ones are named rather than defaulted to absent.

    The two fields are not interchangeable, and writing this test is what found the example reading the wrong one. An
    absence is a statement -- "a request has no turn budget in it" -- and `unaccounted` is the silence an absence was
    invented to replace. Reporting the silence made the loop look like it had seen everything, because this collector
    explains every part it cannot reach; a non-empty `unaccounted` would mean the collector itself had regressed.
    """
    turn = an_ops().turn("task", now=1000.0)
    assert "turn_budget" in turn.unobserved
    assert "retry_policy" in turn.unobserved
    assert "instruction" not in turn.unobserved, "the instruction is in the request, so it is not unobserved"
    assert turn.unaccounted == (), f"the collector said nothing at all about {turn.unaccounted}"


# --- the fake itself, because every assertion above rests on it -----------------------------------------------------

@pytest.mark.parametrize("rate,calls,expected", [(0.5, 4, 2), (0.5, 5, 2), (1.0, 3, 3), (0.25, 8, 2), (0.0, 4, 0)])
def test_the_fake_accepts_exactly_the_stated_fraction(rate, calls, expected):
    """Guarding the instrument. The first version used `round` per call and accepted one in four at rate 0.5, which
    would have made every assertion about the loop actually an assertion about the fake."""
    agent = ScriptedAgent(accepts={P.CHEAP: rate})
    got = sum(1 for _ in range(calls) if agent(request_body("t"), candidate=P.CHEAP).accepted)
    assert got == expected


# --- a candidate that never answered is not a candidate that answered badly -----------------------------------------

class RefusesTheHarness:
    """A fake endpoint that rejects any request carrying tool schemas, the way a real one did.

    Not invented for the test. A served vLLM returned 400 -- `"auto" tool choice requires --enable-auto-tool-choice and
    --tool-call-parser to be set` -- for every request the example sends, because the example sends the tools a coding
    agent sends. Fourteen turns came back unaccepted and the loop reported a quality result.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, body: dict, *, candidate: str) -> object:
        from examples.opencode_ops.adapter import Reply
        self.calls += 1
        if candidate == P.CHEAP and body.get("tools"):
            return Reply(text="", accepted=False, input_mtok=0.0, output_mtok=0.0,
                         unobserved_because="unsupported")
        return Reply(text=f"answer from {candidate}", accepted=True, input_mtok=0.01, output_mtok=0.002)


def test_a_candidate_that_refused_the_request_is_not_reported_as_bad_at_it():
    ops = Ops(world=a_world(), agent=RefusesTheHarness(), rng=random.Random(0))
    run(ops, 20)

    assert ops.never_served(P.CHEAP) is True
    assert ops.unserved_reasons(P.CHEAP) == ("unsupported",)
    # The distinction a boolean cannot carry: no attempt was made, so there is no rate. An acceptance of 0.0 here would
    # be a claim about the model.
    assert ops.acceptance(P.CHEAP) is None
    assert ops.spend_per_accepted(P.CHEAP) is None
    # And the arm that did answer is not crowned on the strength of the other one being unable to take the request.
    assert ops.acceptance(P.DEAR) == 1.0
    assert ops.preferred() is None


def test_the_three_states_are_the_mechanisms_own_and_not_a_boolean():
    from tierbook import evidence as ev
    ops = Ops(world=a_world(), agent=RefusesTheHarness(), rng=random.Random(0))
    run(ops, 20)
    seen = {r["state"] for r in ops.history}
    assert seen <= ev.KNOWN_STATES
    assert ev.UNOBSERVED in seen and ev.SOLVED in seen


def test_a_reason_outside_the_mechanisms_classification_is_refused():
    from examples.opencode_ops.adapter import Reply
    with pytest.raises(ValueError, match="is not one of"):
        Reply(text="", accepted=False, input_mtok=0.0, output_mtok=0.0, unobserved_because="the box was grumpy")


def test_an_answer_cannot_be_accepted_and_never_have_been_produced():
    from examples.opencode_ops.adapter import Reply
    with pytest.raises(ValueError, match="cannot be accepted and never"):
        Reply(text="x", accepted=True, input_mtok=0.0, output_mtok=0.0, unobserved_because="unsupported")
