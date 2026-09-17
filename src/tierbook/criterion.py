"""A criterion registered with its null and its alternatives, so passing one test cannot be reported as support.

One mechanistic question in this study had a prediction on both sides, and the outcome is the reason this module exists:

| | value |
|---|---|
| the internal direction, held out | **0.8285** |
| the permutation null, 95th percentile | 0.7928 |
| the permutation null, **median** | 0.7584 |
| the free alternative on the same items | **0.8895** |
| fraction of the direction inside the answer-letter span | 75.4% |

**The first test passes and the conclusion is not supported.** 0.8285 clears the null's 95th percentile by 0.0357, so
"beats its null" is true -- and a freely available alternative scores **0.8895 on the same question**, and the direction
is nearly as letter-bound as the thing it was supposed to be distinguished from. A report of the first number alone is a
report that passed.

**Three things follow, and each is a refusal here.**

**The null is a distribution, not a scalar.** Its median is 0.7584 and its 95th percentile 0.7928; "beats the null"
without saying which quantile is a sentence that can mean either, and the gain over the median (0.036) is not the gain
over the tail. So a null carries both and the quantile the verdict uses must be **declared before the data**.

**A conclusion needs every criterion it was registered with.** Reporting the one that passed is not a partial result, it
is a different claim -- so a `Registration` answers `supported` only when all of its criteria hold, and there is no
method that reports one.

**And a null is not an alternative.** Beating a permutation of your own labels says the signal is not an artefact of the
label distribution; it says nothing about whether something cheaper already does the job. The alternatives are carried
separately and checked separately, because in this measurement the two answers disagreed.
"""
from __future__ import annotations

from dataclasses import dataclass

from tierbook.evidence import FIXED_ON, EvidenceError


class Unregistered(EvidenceError):
    """A verdict was asked of a criterion whose comparison was not fixed before the data was opened.

    Raised rather than answered, because the number is computable and the licence to read it as a verdict is what is
    missing -- the same distinction an operating point chosen on the scored items already draws. A criterion whose null
    was computed after the fact is a criterion whose threshold could have been chosen to clear it.
    """


@dataclass(frozen=True)
class Null:
    """A permutation or resampling null as a distribution, with the quantile a verdict is allowed to use.

    Both the median and the tail, because they answer different questions and the study's own numbers differ by 0.034
    between them. `quantile` is the one declared for the verdict, and it is part of the registration rather than a choice
    made when the result is read.
    """

    median: float
    at_quantile: float
    quantile: float
    draws: int
    preserves: str = ""

    def __post_init__(self) -> None:
        if self.draws < 1:
            raise Unregistered("a null over zero draws is not a null; the distribution it describes was never sampled")
        if not 0.0 < self.quantile < 1.0:
            raise Unregistered(
                f"quantile={self.quantile!r} must lie strictly between 0 and 1: at 0 or 1 the verdict is against an "
                f"extreme of a finite sample rather than against the distribution")
        if self.at_quantile < self.median:
            raise Unregistered(
                f"the value at quantile {self.quantile} is {self.at_quantile} and the median is {self.median}, so the "
                f"declared quantile sits below the middle of the distribution. That is a lower bar than the median and "
                f"is almost certainly the two numbers swapped")
        # The minimum attainable p of a permutation test is 1/draws, so a quantile the draw count cannot resolve is a
        # threshold nothing could have failed. At 95% that needs at least 20 draws; the study's own reruns used far more,
        # and the check exists because a cheap null is the one somebody runs when time is short.
        if self.draws < 1 / (1 - self.quantile):
            raise Unregistered(
                f"{self.draws} draws cannot resolve the {self.quantile:.2f} quantile: with that many, the tail this "
                f"verdict is compared against is a single draw or none, so nothing could have failed it")


@dataclass(frozen=True)
class Criterion:
    """One test, its null, and when the comparison was fixed.

    `direction` is required because "beats" is ambiguous: a discriminant should exceed its null and a fraction inside a
    span should fall below its bound, and a criterion that does not say which was silently satisfied by whichever
    inequality happened to hold.
    """

    name: str
    observed: float
    null: Null
    fixed_on: str
    #: `above` means the observed value must exceed the null's declared quantile; `below` means it must fall under a
    #: declared bound. Both occur in the measurement this module records, and they were reported as one kind of pass.
    direction: str = "above"
    bound: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise Unregistered("a criterion with no name cannot be reported as having passed or failed, so a "
                               "registration of several of them cannot say which one carried the conclusion")
        if self.fixed_on not in FIXED_ON:
            raise Unregistered(f"{self.fixed_on!r} is not one of {FIXED_ON}")
        if self.direction not in ("above", "below"):
            raise Unregistered(
                f"direction={self.direction!r} must be 'above' or 'below'. A discriminant should exceed its null and a "
                f"fraction inside a span should fall under a bound; a criterion that does not say which is satisfied by "
                f"whichever inequality happens to hold")
        if self.direction == "below" and self.bound is None:
            raise Unregistered(f"{self.name!r} tests that a value falls below something and names no bound; a null's "
                               f"quantile is not a bound in that direction")
        if self.direction == "above" and self.bound is not None:
            raise Unregistered(f"{self.name!r} tests against its null's quantile and also carries bound={self.bound!r}, "
                               f"so two thresholds describe one test and nothing says which was used")

    @property
    def target(self) -> float:
        return self.null.at_quantile if self.direction == "above" else self.bound

    def holds(self) -> bool:
        """Whether this test passed -- refused when the comparison was fixed on the data it is scored against."""
        if self.fixed_on == "scored_items":
            raise Unregistered(
                f"{self.name!r} had its comparison fixed on the items it is scored against, so its threshold could have "
                f"been chosen to clear the observed {self.observed}. The number is computable and is not a verdict; fix "
                f"the null on a fixture before the data is opened, or report it as the best case and say so")
        return self.observed > self.target if self.direction == "above" else self.observed < self.target

    @property
    def margin(self) -> float:
        """How far past the target the observation sits, signed so a failure reads as negative."""
        return (self.observed - self.target) if self.direction == "above" else (self.target - self.observed)

    def __str__(self) -> str:
        rel = ">" if self.direction == "above" else "<"
        return f"{self.name}: {self.observed:.4f} {rel} {self.target:.4f} ({self.fixed_on}, margin {self.margin:+.4f})"


@dataclass(frozen=True)
class Alternative:
    """Something freely available that answers the same question, carried because a null cannot stand in for one.

    Beating a permutation of your own labels says the signal is not an artefact of the label distribution. It says
    nothing about whether something cheaper already does the job -- and in the measurement behind this module the two
    answers disagreed: the direction cleared its null and **lost to the free alternative by 0.0610**.
    """

    name: str
    observed: float
    free: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise Unregistered("an unnamed alternative cannot be reported, so a conclusion that lost to it would lose "
                               "to nothing a reader can identify")


@dataclass(frozen=True)
class Registration:
    """Every criterion a conclusion was registered against, and every alternative it has to beat.

    `supported` is the only verdict, and it requires **all** of them. There is deliberately no method that reports one
    criterion's result as support: the measurement this module records passed its first test and the conclusion did not
    follow, so a partial report is not a partial result but a different claim.
    """

    conclusion: str
    criteria: tuple[Criterion, ...]
    alternatives: tuple[Alternative, ...] = ()
    #: Why no alternative is listed, when none is. Required in that case and refused otherwise, the same pairing as a
    #: bound and its provenance -- because an empty `alternatives` is ambiguous between "nothing cheaper exists" and
    #: "nobody looked", and the measurement behind this module is one where looking is what settled it.
    no_alternative_because: str = ""

    def __post_init__(self) -> None:
        if not self.conclusion:
            raise Unregistered("a registration with no conclusion records tests and not what they were for, which is "
                               "the state that lets a passing test be attached to whatever claim is convenient later")
        if not self.criteria:
            raise Unregistered("a conclusion registered against no criterion cannot be supported or refuted by "
                               "anything, so recording it as registered would be recording the opposite of the fact")
        names = [c.name for c in self.criteria]
        if len(set(names)) != len(names):
            raise Unregistered(f"two criteria share a name in {sorted(names)}, so a report cannot say which one held")
        # What this CAN close, and what it cannot. It cannot know how many criteria a claim needs -- registering only
        # the test that passed is still possible, and the registration's job there is to make the shortness visible.
        # What it can refuse is a conclusion that never asked the cheaper question at all: an empty `alternatives` with
        # no reason is ambiguous between "nothing cheaper exists" and "nobody looked", and in the measurement this
        # module records, looking is what settled it -- the direction cleared its null and lost to a free alternative by
        # 0.0610.
        if not self.alternatives and not self.no_alternative_because:
            raise Unregistered(
                f"{self.conclusion!r} is registered with no alternative and no reason for that. Beating a permutation of "
                f"your own labels says the signal is not an artefact of the label distribution; it says nothing about "
                f"whether something cheaper already does the job, and those two answers have disagreed here. Name an "
                f"alternative, or say why none exists")
        if self.alternatives and self.no_alternative_because:
            raise Unregistered(
                f"{len(self.alternatives)} alternative(s) are listed and no_alternative_because is also set to "
                f"{self.no_alternative_because!r}; the reason describes an absence that is not there")

    def failed(self) -> tuple[str, ...]:
        """Which criteria did not hold. Named rather than counted, because the fix differs per criterion."""
        return tuple(c.name for c in self.criteria if not c.holds())

    def lost_to(self) -> tuple[str, ...]:
        """Which alternatives beat the best criterion here -- the check a null cannot make."""
        if not self.alternatives or not self.criteria:
            return ()
        best = max(c.observed for c in self.criteria)
        return tuple(a.name for a in self.alternatives if a.observed > best)

    def supported(self) -> bool:
        """The conclusion holds only if every criterion held and nothing free beat it."""
        return not self.failed() and not self.lost_to()

    def why_not(self) -> str:
        """One sentence naming everything standing between these numbers and the conclusion."""
        if self.supported():
            return f"{self.conclusion!r} is supported by all {len(self.criteria)} registered criteria"
        parts = []
        if self.failed():
            parts.append(f"criteria {list(self.failed())} did not hold")
        if self.lost_to():
            parts.append(f"a freely available alternative beat it: {list(self.lost_to())}")
        return f"{self.conclusion!r} is not supported -- " + "; and ".join(parts)
