"""A floor, the escalation target it is claimed for, and two checks that need no run at all.

An adoption bar in this project was "hold floor 0.90 with at most 126 escalations per 1,187". It was **unsatisfiable on
the day it was written**, twice over, and both proofs are arithmetic:

| condition | box accuracy | net rescues needed for floor 0.90 |
|---|---|---|
| terse | 0.608 | 347 |
| explaining | 0.7597 | **167** |

The bar allowed 141. **141 is below 167**, so no signal, no oracle and no mechanism could have met it in either
condition. And in the terse condition the floor was above what escalating *every single item* could reach, which is a
different impossibility and the one `gamma` names.

**Both checks run before anything is scored, and that is the point.** When the bar cannot be met by the best possible
policy, the finding belongs on the **bar** and not on the policy: a `FAIL` against a policy for missing an unreachable
floor blames the wrong object, and the study's own history is that the numbers were inherited with their labels and the
labels were treated as their provenance.

**A floor travels with the target it is claimed for.** The infeasibility here was in the *pairing*: 0.90 is reachable
against one escalation target and not against another, so a floor recorded alone is a floor whose feasibility cannot be
decided.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from tierbook.evidence import EvidenceError


class Unsatisfiable(EvidenceError):
    """The bar cannot be met by any policy, so the finding is about the bar.

    A distinct exception rather than a failing verdict, because the two send a reader to different places: a policy
    that failed might be improved, and a bar that is unsatisfiable will refuse every policy anybody writes. Reporting
    the second as the first is how a constraint nobody could satisfy survived several rounds of being blamed on
    signals.
    """


@dataclass(frozen=True)
class Bar:
    """A floor with everything needed to decide whether it can be met, and nothing derived stored beside it.

    Every scalar below is a property. A stored `gamma` or a stored ceiling is a number that can disagree with the
    floor it was computed from, and this study's own failure was a pair of numbers whose provenance was a label
    somebody attached to them.
    """

    floor: float
    target: str
    #: COUNTS, not rates, and that is not a preference. Computing this from a rate gave 348 net rescues where the
    #: measured figure is 347, and 168 where it is 167 -- because 0.608 x 1187 is 721.696 and no rounding of it is the
    #: number of items the box actually solved. A rate is a count divided by a total with the remainder thrown away, so
    #: inverting it reintroduces an ambiguity of exactly one item at every floor. Taking the counts makes the
    #: off-by-one unrepresentable rather than a convention to get right.
    box_solved: int
    items: int
    #: How many of the items the box MISSED the escalation target gets right. The target's accuracy over the whole set
    #: is a different quantity and using it overstates the ceiling, because the items the box already solves are not
    #: the ones escalation has to rescue.
    target_rescued: int
    #: The most escalations the bar permits, when it names one. `None` means the bar constrains only accuracy, which is
    #: a weaker bar rather than an unlimited budget -- and the distinction is why this is not defaulted to the item
    #: count.
    escalation_budget: int | None = None

    def __post_init__(self) -> None:
        if not self.target:
            raise Unsatisfiable(
                "a floor with no escalation target is a floor whose feasibility cannot be decided: 0.90 is reachable "
                "against one target and not against another, and the infeasibility this type exists to catch was in "
                "the pairing rather than in either number")
        if not 0.0 <= self.floor <= 1.0:
            raise Unsatisfiable(f"floor={self.floor!r} is not a rate")
        if self.items < 1:
            raise Unsatisfiable(f"items={self.items} is not a set to hold a floor over")
        if not 0 <= self.box_solved <= self.items:
            raise Unsatisfiable(f"box_solved={self.box_solved} is not a count of {self.items} items")
        if not 0 <= self.target_rescued <= self.items - self.box_solved:
            raise Unsatisfiable(
                f"target_rescued={self.target_rescued} is outside 0..{self.items - self.box_solved}, the items the box "
                f"missed. A target cannot rescue an item that was already right, and counting those would put the "
                f"ceiling above what escalation can actually reach")
        if self.escalation_budget is not None and not 0 <= self.escalation_budget <= self.items:
            raise Unsatisfiable(
                f"escalation_budget={self.escalation_budget} is outside 0..{self.items}; a budget above the item count "
                f"is not a constraint, and one below zero is not a budget")
        if self.floor * self.items <= self.box_solved:
            raise Unsatisfiable(
                f"floor {self.floor:.4f} is at or below the box's own accuracy {self.box_accuracy:.4f}, so the bar asks "
                f"for nothing: it is met by never escalating. Two conditions' bars stated this way are not comparable, "
                f"which is what `gamma` exists to make visible")

    @property
    def box_accuracy(self) -> float:
        return self.box_solved / self.items

    @property
    def ceiling(self) -> float:
        """The best any policy could reach: what the box solves plus everything escalating every remaining item rescues.

        Computed from the two counts, so it is exact. The rate form `p + (1 - p) q` is the same quantity and carries the
        rounding this type exists to avoid.
        """
        return (self.box_solved + self.target_rescued) / self.items

    @property
    def gamma(self) -> float:
        """The floor as a fraction of the headroom that exists, so two conditions' bars are comparable.

        `(floor - box) / (ceiling - box)`. Above 1 the floor is outside what escalating every single item could reach,
        which is not "hard" but impossible, and visible on sight in a way an absolute floor is not: 0.90 says nothing
        about which condition it is achievable in.
        """
        if self.target_rescued == 0:
            return math.inf
        return (self.floor * self.items - self.box_solved) / self.target_rescued

    @property
    def minimum_net_rescues(self) -> int:
        """How many items escalation must turn from wrong to right, at the least.

        `ceil(floor x N) - box x N`, and it is arithmetic rather than a measurement of how good an oracle can be -- which
        is exactly why a budget below it is unsatisfiable by anything at all.
        """
        return max(0, math.ceil(self.floor * self.items) - self.box_solved)

    def check(self) -> None:
        """Refuse a bar no policy could meet, naming which of the two impossibilities applies.

        Two, because they are different facts with different fixes: a `gamma` above 1 needs a better escalation target,
        and a budget below the arithmetic minimum needs a bigger budget or a lower floor. A single "infeasible" would
        send a reader to look for the wrong one.
        """
        if self.gamma > 1.0:
            raise Unsatisfiable(
                f"floor {self.floor:.4f} against {self.target!r} has gamma {self.gamma:.4f}, above 1: it is outside "
                f"what escalating EVERY item could reach, since the ceiling is {self.ceiling:.4f}. This needs a better "
                f"target, not a better signal -- and stated as 0.90 rather than as gamma it looked merely hard")
        if self.escalation_budget is not None and self.escalation_budget < self.minimum_net_rescues:
            raise Unsatisfiable(
                f"the bar permits {self.escalation_budget} escalations and reaching floor {self.floor:.4f} from a box "
                f"at {self.box_accuracy:.4f} over {self.items} items needs at least {self.minimum_net_rescues} net "
                f"rescues. No signal, no oracle and no mechanism can meet it; this is arithmetic, so the finding is "
                f"about the bar")

    def __str__(self) -> str:
        budget = "no budget" if self.escalation_budget is None else f"<={self.escalation_budget} escalations"
        return (f"floor {self.floor:.4f} vs {self.target} (box {self.box_accuracy:.4f}, ceiling {self.ceiling:.4f}, "
                f"gamma {self.gamma:.4f}, needs >={self.minimum_net_rescues} rescues, {budget})")


def comparable(bars: list[Bar]) -> bool:
    """Whether these bars are asking for the same thing, which is what `gamma` was introduced to answer.

    Two floors of 0.90 over boxes at 0.608 and 0.7597 are not one bar stated twice: the first needs 347 net rescues and
    the second 167. Equal in the absolute, they differ by a factor of two in what they demand, and every comparison
    made between them before this was a comparison of two different requirements.
    """
    if len(bars) < 2:
        return True
    first = bars[0].gamma
    return all(abs(b.gamma - first) < 1e-9 for b in bars)
