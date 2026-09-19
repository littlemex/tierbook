"""The loop: observe, decide, call, record, adapt.

**Every threshold in this loop is derived from what the loop recorded.** That is this example's rule rather than the
mechanism's, and it is the reason `adapt` exists as a step instead of a configuration file: a loop whose numbers are
typed in is a fixed policy with extra machinery around it.

What the mechanism contributes, and what it refuses to contribute:

* it evaluates the guards this example wrote, over facts this example invented, and reports what fired **and what it
  could not read**;
* it records spend on the four legs a price card actually bills, and refuses to compare two costs billed differently;
* it reads the harness off the request and says which parts it could not see;
* it sorts a rate somebody measured from a rate somebody declared, and answers `unknown` when neither can settle the
  question -- which is most of the time and is the answer that keeps the other two honest;
* it will not tell this example which candidate to pick, what a good acceptance rate is, what rate the service must
  carry, how much traffic to spend exploring, or when to stop. Those are all here.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from tierbook import explore as ex
from tierbook import harness as hn
from tierbook import spend as sp
from tierbook import throughput as th

from . import policy as P
from .adapter import Agent, request_body
from .state import World


@dataclass
class Turn:
    """One pass of the loop, kept whole so a reader can see what a decision was made on.

    What is on it is chosen around the same idea: the interesting failures are about what was **not** seen. So the
    thresholds that were in force are here rather than recomputed later, the harness parts the request could not carry
    are named, and the capacity answer is the one that held on this turn rather than at report time.
    """

    candidate: str
    accepted: bool
    cost: sp.Spend
    harness_identity: str | None
    #: The harness parts the collector said it could not see here, each with a reason recorded on the collection. A
    #: request cannot carry a turn budget or a retry policy, and naming them is what keeps their absence from reading as
    #: a claim that the harness had none.
    unobserved: tuple[str, ...]
    #: Parts the collector said **nothing** about -- neither held nor explained. A different thing from `unobserved` and
    #: the reason both are here: an absence is a statement and this is the silence an absence was invented to replace, so
    #: a non-empty value here is the collector regressing rather than a property of the request.
    unaccounted: tuple[str, ...]
    thresholds: dict[str, float]
    reason: str
    #: What the capacity question answered per candidate this turn: `deliverable`, `refused` or `unknown`. Kept per turn
    #: rather than once for the run, because evidence arrives while the loop is running and the answer changes with it.
    capacity: dict[str, str] = field(default_factory=dict)


@dataclass
class Ops:
    """The loop, with its history and the numbers it has derived so far.

    `history` is the only state. Everything else -- the policy, its thresholds, which candidate is preferred -- is
    recomputed from it each turn, so there is no way for a derived number to drift from what produced it.
    """

    world: World
    agent: Agent
    #: The rate this example's service has to carry, per hour. Stated once and by this example, because the mechanism has
    #: no opinion about how fast anything must be -- it only says whether the evidence in hand can answer the question.
    required_per_hour: float = 100.0
    history: list[dict] = field(default_factory=list)
    #: Seeded, because a test that has to average over randomness cannot say whether the loop moved traffic or the coin
    #: did. A deployment passes its own.
    rng: random.Random = field(default_factory=lambda: random.Random(0))

    def thresholds(self) -> dict[str, float]:
        """This turn's numbers, derived from every turn before it."""
        return P.thresholds_from_history(self.history)

    def exploration_rate(self) -> float:
        """How much traffic to spend finding out, derived from whether a comparison is possible yet.

        This example's choice, stated rather than tuned: **while either arm is unmeasured the comparison cannot be made
        at all**, so exploration is the only thing that can change that and the rate is high. Once both arms have been
        seen it drops to a maintenance rate -- prices move, and a preference derived from history goes stale silently.

        Zero would be the wrong floor. A loop that stops exploring cannot notice the world changing under it, and this
        example's whole premise is that the world moves.
        """
        seen = {row["candidate"] for row in self.history}
        return 0.5 if len(seen) < 2 else 0.05

    def eligible(self) -> tuple[list[str], dict[str, str]]:
        """The candidates this example is willing to send to, and what the capacity question said about each.

        **The example's rule, and it is a choice rather than the only sensible one: `refused` is a veto, `unknown` is
        not.** A refusal comes from a declared limit or from a measurement that is not a lower bound, and in both cases
        sending traffic there is sending it somewhere known not to carry it. `unknown` means nobody has measured well
        enough to say, and treating that as a veto would let a weak load generator quietly shrink the pool -- which is
        the mistake this repository made twice before it had a word for it.

        What `unknown` does cost is a claim: the loop may still route there, and it may not report afterwards that the
        candidate was shown to carry the traffic. Those are different things and the mechanism keeps them apart.
        """
        answers: dict[str, str] = {}
        pool: list[str] = []
        for c in (P.CHEAP, P.DEAR):
            outcome, _why = self.world.can_deliver(c, self.required_per_hour)
            answers[c] = outcome
            if outcome != "refused":
                pool.append(c)
        return pool, answers

    def shown_to_carry_the_traffic(self, candidate: str) -> bool:
        """Whether the loop may say this candidate carries its rate, as opposed to merely having routed to it.

        `deliverable` and nothing else. This is separate from `eligible` on purpose: the loop routes on a weaker
        condition than it reports on, and collapsing the two is how "we sent traffic there" becomes "it holds".
        """
        return self.world.can_deliver(candidate, self.required_per_hour)[0] == "deliverable"

    def turn(self, task: str, *, now: float, terse: bool = True) -> Turn:
        """One pass: observe, decide, call, record.

        The order matters and is not arbitrary. The harness is read from the body **before** the call, because a request
        is the only place the instruction and the tool shapes are held as bytes; reading them afterwards would be reading
        whatever the agent still had in memory.
        """
        thresholds = self.thresholds()
        pol = P.build(thresholds)

        # Observe against the candidate the policy would prefer by default, then again for the one a guard names. The two
        # reads are separate because a per-candidate fact about `box` says nothing about `api`, and a single observation
        # carrying both would be a state nobody could attribute.
        observation = self.world.snapshot(P.CHEAP, now=now)
        deterministic = P.choose(pol, observation, thresholds=thresholds)

        # **The cold start, and why exploration is not optional here.** Every threshold is derived from history, and the
        # price threshold needs history on the dear candidate -- which never accrues, because with no price threshold
        # nothing ever escalates. The loop ran four turns on the cheap side and derived nothing, which is a deadlock in
        # this example's own logic rather than in the mechanism.
        #
        # So the example explores, using the mechanism's own randomiser so the propensity is recorded rather than
        # implied. The rate is this example's choice and it decays: exploration is worth paying for while a comparison is
        # impossible, and much less once it is possible.
        # Capacity comes before the draw, not after. Exploration that can land on a candidate known not to carry the
        # rate is exploration that pays for an answer already in hand.
        pool, capacity = self.eligible()
        if pool and deterministic not in pool:
            # The policy named a candidate whose capacity refuses the required rate. The example overrides it rather than
            # raising: the loop still owes the caller an answer, and the cheapest candidate that is not refused is the
            # honest place to send it. Recorded, because a silent override is a policy nobody can audit.
            deterministic = pool[0]
        candidate, propensity, why = ex.draw(deterministic, pool or [deterministic],
                                             self.exploration_rate(), self.rng)

        body = request_body(task, terse=terse)
        record = hn.collect_from_request(body, collector="opencode-ops-example", version="0.1")

        reply = self.agent(body, candidate=candidate)

        # Four legs, not two. The example has no cache to read from, so the cached and written legs are zero -- and they
        # are recorded as zero rather than omitted, because an omitted split is not a zero cache rate and a later
        # comparison against a cached arm has to be able to refuse.
        price = self.world.price_per_mtok[candidate]
        cost = sp.Spend(prefill=reply.input_mtok * price,
                        generation=reply.output_mtok * price * 3.0,
                        cached_in=0.0, cache_write=0.0)
        self.world.charge(candidate, reply.input_mtok + reply.output_mtok)

        self.history.append({
            "candidate": candidate,
            "accepted": reply.accepted,
            "price": price,
            "spend": cost.total,
            "harness": record.harness.identity if record.harness and record.harness.has_identity else None,
            # Recorded because a later comparison needs it: traffic that arrived here by exploration was not chosen by
            # the policy, and averaging the two together attributes the explorer's cost to the policy's decisions.
            "propensity": propensity,
            "explored": candidate != deterministic,
            "why": why,
            # Recorded per turn rather than derived later, because the evidence behind it changes while the loop runs and
            # a capacity answer recomputed at report time would be attributed to turns it was not true of.
            "capacity": capacity[candidate],
        })
        return Turn(candidate=candidate, accepted=reply.accepted, cost=cost,
                    harness_identity=self.history[-1]["harness"],
                    unobserved=tuple(a.kind for a in record.absences),
                    unaccounted=record.unaccounted,
                    thresholds=thresholds,
                    reason=P.build(thresholds).note,
                    capacity=capacity)

    # --- what the loop is optimising, and how it reports it -----------------------------------------------------------

    def spend_per_accepted(self, candidate: str | None = None) -> float | None:
        """Cost per answer that was taken. `None` when nothing was taken, rather than infinity.

        The denominator is the example's choice and it is the whole optimisation target: spend per **accepted** answer,
        not spend per request. A loop optimising spend per request is optimising for refusing to answer, which is cheap
        and useless -- and this repository has a rule about denominators that flatter the thing being measured.
        """
        rows = [r for r in self.history if candidate is None or r["candidate"] == candidate]
        taken = [r for r in rows if r["accepted"]]
        if not taken:
            return None
        return sum(r["spend"] for r in rows) / len(taken)

    def acceptance(self, candidate: str) -> float | None:
        rows = [r for r in self.history if r["candidate"] == candidate]
        return None if not rows else sum(1 for r in rows if r["accepted"]) / len(rows)

    def preferred(self) -> str | None:
        """Which candidate the recorded history says is cheaper per accepted answer.

        `None` when the comparison cannot be made -- either side unmeasured. Returning a default here is how a
        preference gets published on the strength of one arm, which is the failure this repository withdrew a number for.
        """
        scores = {c: self.spend_per_accepted(c) for c in (P.CHEAP, P.DEAR)}
        if any(v is None for v in scores.values()):
            return None
        return min(scores, key=lambda c: scores[c])
