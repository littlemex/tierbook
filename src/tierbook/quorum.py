"""Stop when cheap candidates agree, and let the price vector choose which ones.

A cheap candidate's own uncertainty answers "do I know this". A routing policy needs "does anyone
cheaper than the dear tier know this", and those are different questions: measured on a
nine-candidate corpus, the box's prefill entropy predicts "every candidate solves it" at 0.83 AUC and
"no candidate solves it" at 0.51, because self-doubt carries no information about what the others
know. Three independent answers do carry it. Where three cheap candidates agree, the agreed answer was
right 89.7% of the time -- as often as the frontier tier is right on the whole corpus, at a quarter of
the price -- and where they disagree the item is escalated.

**This module deliberately does not decide which candidates form the quorum.** That is a function of
the price vector, and the price vector changes: the answer on one pool at one set of prices was
"the self-hosted box plus two cheap APIs, escalating to the frontier tier", and quoting that as the
design is the error this module exists to prevent. `frontier()` enumerates the policies, prices each
one, and returns the ones nothing else dominates; `cheapest_meeting()` picks from that under a quality
floor. A price change is a re-evaluation over the same matrix, never a re-measurement.

## What the rule is, exactly

A policy is a set of **members** and one **escalation tier**. For each item:

  * every member answers;
  * if they all produced an answer and the answers are identical, the policy stops and returns it;
  * otherwise the escalation tier answers, and its answer is the policy's.

**An absent answer breaks the quorum.** A member that abstained, or whose reply did not parse into an
answer, cannot be shown to agree with anything, so the item escalates. This is not a convenience: on
the corpus that motivated the module, 200 of 10,485 cells were malformed, and the 63 from which an
answer could be recovered were graded incorrect in every single case -- so "recovering" them moves
wrong answers into the set the policy stops on. Refusing to guess costs a few extra escalations and
buys a stop set that is 1.1 points more accurate.

**A one-member policy stops on everything**, because there is nothing for one candidate to disagree
with. That is a real policy -- "the cheap tier answers, nobody checks" -- and it is the cheap end of
the frontier rather than a degenerate case to exclude.

## What it refuses to do

**It will not price a policy it cannot price.** If any cell a policy needs carries no cost, the
policy's cost is `None` and it is excluded from the frontier rather than being treated as free. An
unpriced tier that appears free is how a self-hosted candidate wins every comparison it should lose.

**It reports the denominator.** A three-member policy that agrees on eleven items can show a very
high accuracy on agreement, and that number means nothing. `stopped` travels with every point so a
reader can see what the conditional accuracy was computed over, and `min_stopped` refuses the ones
too thin to read.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from tierbook.evidence import UNOBSERVED
from tierbook.outcomes import Cell, OutcomeTable


@dataclass(frozen=True)
class QuorumPolicy:
    """One policy, priced on one matrix. Everything here is observed or arithmetic on the observed."""

    members: tuple[str, ...]
    escalate_to: str
    items: int
    stopped: int                          # items the members agreed on, so no escalation happened
    solved: int                           # items the policy got right, over `items`
    solved_when_stopped: int              # of `stopped`, how many the agreed answer got right
    usd_per_item: float | None            # None when any needed cell is unpriced

    @property
    def stop_rate(self) -> float:
        return self.stopped / self.items if self.items else 0.0

    @property
    def accuracy(self) -> float:
        return self.solved / self.items if self.items else 0.0

    @property
    def accuracy_when_stopped(self) -> float:
        """How often the agreed answer was right. Read it against `stopped`, not on its own."""
        return self.solved_when_stopped / self.stopped if self.stopped else 0.0

    @property
    def priced(self) -> bool:
        return self.usd_per_item is not None


def _cell(table: OutcomeTable, item: str, tier: str) -> Cell:
    return table.cells.get(item, {}).get(tier) or Cell(UNOBSERVED, None)


def agreement(table: OutcomeTable, members: tuple[str, ...], items: list[str]) -> tuple[list[str], list[str]]:
    """Split `items` into the ones the members agree on and the ones they do not.

    Agreement requires every member to have produced an answer AND all answers to be identical. See
    the module docstring for why an absent answer escalates rather than being filled in.
    """
    stopped, escalated = [], []
    for item in items:
        answers = [_cell(table, item, m).answer for m in members]
        if all(a is not None for a in answers) and len(set(answers)) == 1:
            stopped.append(item)
        else:
            escalated.append(item)
    return stopped, escalated


def evaluate(table: OutcomeTable, members: tuple[str, ...], escalate_to: str, *,
             prices: dict[str, float] | None = None, items: list[str] | None = None) -> QuorumPolicy:
    """Price and score one policy on the matrix.

    `prices` is a per-item cost per tier, overriding the matrix's own recorded cost. That override is
    the whole point of the separation: re-pricing a policy must not require re-running it, so a new
    rate card is an argument here and not a new measurement.
    """
    subject = list(items if items is not None else table.items)
    stopped, escalated = agreement(table, members, subject)

    def cost_of(item: str, tier: str) -> float | None:
        if prices is not None:
            return prices.get(tier)
        return _cell(table, item, tier).usd

    total = 0.0
    unpriced = False
    for item in subject:
        for tier in members:
            usd = cost_of(item, tier)
            if usd is None:
                unpriced = True
            else:
                total += usd
    for item in escalated:
        usd = cost_of(item, escalate_to)
        if usd is None:
            unpriced = True
        else:
            total += usd

    # A stopped item is right when the answer the members agreed on is right. Because they all gave the
    # same answer, any member's own verdict settles it -- but reading it off one member would be a
    # coincidence of that encoding, so it is read as "some member solved it", which is the same set.
    right_stopped = sum(1 for i in stopped if any(_cell(table, i, m).solved for m in members))
    right_escalated = sum(1 for i in escalated if _cell(table, i, escalate_to).solved)

    return QuorumPolicy(
        members=tuple(members),
        escalate_to=escalate_to,
        items=len(subject),
        stopped=len(stopped),
        solved=right_stopped + right_escalated,
        solved_when_stopped=right_stopped,
        usd_per_item=None if unpriced or not subject else total / len(subject),
    )


def enumerate_policies(table: OutcomeTable, *, candidates: list[str], escalate_to: list[str],
                       max_members: int = 4, prices: dict[str, float] | None = None,
                       items: list[str] | None = None, min_stopped: int = 30) -> list[QuorumPolicy]:
    """Every policy worth pricing, with the unreadable ones dropped.

    A member is never also the escalation tier: escalating to a candidate that already answered and
    was overruled by the disagreement is not a policy, it is a no-op that would score as one.

    `min_stopped` drops policies whose stop set is too small for `accuracy_when_stopped` to mean
    anything. A one-member policy stops on everything so it is never dropped by this, which is
    correct -- its conditional accuracy is just its accuracy.
    """
    out: list[QuorumPolicy] = []
    for size in range(1, max_members + 1):
        for members in combinations(candidates, size):
            for tier in escalate_to:
                if tier in members:
                    continue
                policy = evaluate(table, members, tier, prices=prices, items=items)
                if policy.stopped < min_stopped and policy.stopped != policy.items:
                    continue
                out.append(policy)
    return out


def frontier(policies: list[QuorumPolicy]) -> list[QuorumPolicy]:
    """The policies nothing else beats on both accuracy and cost.

    Unpriced policies are excluded rather than ranked, because a policy whose cost is unknown cannot
    be said to be dominated or dominating.
    """
    priced = [p for p in policies if p.priced]
    keep: list[QuorumPolicy] = []
    for p in priced:
        if any(q is not p and q.accuracy >= p.accuracy and q.usd_per_item <= p.usd_per_item
               and (q.accuracy > p.accuracy or q.usd_per_item < p.usd_per_item)
               for q in priced):
            continue
        keep.append(p)
    return sorted(keep, key=lambda p: p.usd_per_item)


def cheapest_meeting(policies: list[QuorumPolicy], *, accuracy_floor: float) -> QuorumPolicy | None:
    """The cheapest policy that clears a quality floor, or `None` if none does.

    This is the operator-facing shape of the question. A floor is a sentence an owner can say -- "I
    will not go below this accuracy" -- where a weight on cost against quality is not.
    """
    eligible = [p for p in policies if p.priced and p.accuracy >= accuracy_floor]
    return min(eligible, key=lambda p: p.usd_per_item) if eligible else None
