"""What a served box actually delivers, and the four things a rate has to carry before it means anything.

This is the third currency. `spend` prices a request and `outcomes` scores it; neither can say whether the box can
carry the traffic at all, and **the numbers this module refuses were all produced here first and believed.**

## The five measurements this exists for

**A rate without the load generator's own saturation is a lower bound.** The same experiment against one client and
against two read **425,879** and **584,739** requests an hour. Worse than the level being wrong: short shapes are
suppressed harder, because they demand more requests per second to saturate, so the *shape* of the surface was wrong
too. "Peak at 300-600 input tokens" became a monotone "shorter is better" once the generator stopped being the
bottleneck, and the admission rule that came out of it changed.

**A rate without the engine's seat count is measuring your own configuration.** `max_num_seqs` was **27** while 384
concurrent requests were being offered. Raising it to 256 moved value per box-hour by **+33%** at 60 output tokens,
+18% at 300 and +5% at 600 -- and that pattern, **the gain being largest on the short side, is the signature of a
seat limit rather than a compute limit.**

**A closed loop cannot answer a service-level question, and opening it reverses the answer.** Closed-loop is
self-limiting: when the server slows, the client offers less, so no queue forms and the number measures capacity while
saying nothing about service. Opened to Poisson arrivals at 10% of capacity, the verdict flipped from "never
co-locate" to a box earning **+$18.88 per box-hour instead of losing $8.63**.

**The mean is blind to the question co-residency asks.** Mean throughput and mean cost per box-second are both
conserved when box-time moves between request families, so neither can decide whether to mix. Only **requests
returned inside a declared deadline** can: 225,730 an hour with 100% inside one second, against 102,022 with a single
long request resident.

**Seats are decided by the shape of the work rather than the length of the window.** The engine does not reserve the
maximum model length, so a seat count derived from geometry is a hypothesis and not a measurement.
"""
from __future__ import annotations

from dataclasses import dataclass

from tierbook.evidence import EvidenceError

#: How requests arrived. Closed, and the two are not two settings of one thing: they answer different questions.
#:
#: `closed_loop` holds a fixed number of clients in flight, so the offered rate falls as the server slows. That measures
#: **capacity** and structurally cannot produce a queue, so it cannot measure a service level. `open_loop` draws arrivals
#: independently of how the server is doing, which is the only form in which a deadline means anything -- and the form in
#: which this project's own co-residency verdict reversed.
ARRIVALS = ("closed_loop", "open_loop")

#: Why a rate is known to be a lower bound rather than a measurement. Closed, because each entry is a different thing to
#: go and fix, and "we are not sure" is not one of them.
UNDERSTATED_BECAUSE = (
    "generator_saturated",        # the load generator, not the box, was the limit
    "offered_below_seats",        # fewer requests were offered than the engine would have admitted
    "generator_not_checked",      # nobody demonstrated the generator was not the limit
)


class Unmeasured(EvidenceError):
    """A rate was reported in a way that makes it a property of the harness around the box rather than of the box.

    Raised at construction. A rate is quotable immediately and its conditions are what decide whether it means anything,
    so a rate that cannot state them has to fail where it is made -- by the time it is in a table, the generator and the
    seat count are not recoverable from the number.
    """


@dataclass(frozen=True)
class Offered:
    """The load that was actually offered, and the engine's own admission limit beside it.

    Both, because the interesting cases are the ones where they disagree. Offering 384 against 27 seats measures the
    seats; offering 8 against 256 measures the client.
    """

    concurrency: int
    #: The engine's admission limit -- `max_num_seqs` in the engine this was measured against. `None` means nobody read
    #: it, which is left representable because the engine's own startup log is where it lives and not every run has one.
    #: What it is NOT is "unlimited": a rate with an unread seat count cannot be compared against one with a known seat
    #: count, and `comparable_load` refuses that rather than assuming.
    seats: int | None = None
    #: How the load was generated, in enough detail that somebody could raise it. Required, because "we saturated it" is
    #: the claim this field exists to make checkable, and a run whose generator nobody described cannot be re-run harder.
    generator: str = ""

    def __post_init__(self) -> None:
        if self.concurrency < 1:
            raise Unmeasured("a run that offered no concurrent requests measured nothing")
        if self.seats is not None and self.seats < 1:
            raise Unmeasured(f"seats={self.seats} is not an admission limit")
        if not self.generator.strip():
            raise Unmeasured(
                "the load generator is not described. 'We saturated it' is exactly the claim that needs checking -- one "
                "client against two moved the same measurement from 425,879 to 584,739 an hour -- and a generator nobody "
                "wrote down cannot be run harder by the next person")

    @property
    def starves_the_engine(self) -> bool:
        """Whether fewer requests were offered than the engine would have admitted.

        When true the box was never asked for its capacity, so the rate is a property of the client. `None` seats cannot
        answer this, and it returns False rather than guessing -- the refusal lives in `comparable_load`, where it has
        another rate to be refused against.
        """
        return self.seats is not None and self.concurrency < self.seats

    def __str__(self) -> str:
        seats = "seats unread" if self.seats is None else f"{self.seats} seats"
        return f"{self.concurrency} concurrent against {seats} via {self.generator}"


@dataclass(frozen=True)
class Throughput:
    """A rate, the arrivals that produced it, and what it is allowed to support.

    `goodput` is the count that came back inside `deadline_seconds`, and it is **not derived from the rate**: the whole
    point is that a mean rate and a deadline-respecting count move independently. Mean throughput is conserved when
    box-time moves between request families, so it is blind to the only question co-residency asks.
    """

    #: Completed requests per hour, however they landed relative to the deadline.
    per_hour: float
    offered: Offered
    arrivals: str
    #: The deadline a request had to return inside to count, and the count that did. Paired: a goodput with no deadline
    #: is a number nobody can check, and a deadline with no goodput is a promise nobody measured.
    deadline_seconds: float | None = None
    goodput_per_hour: float | None = None
    #: Why this rate is known to understate the box, when it is. From a closed vocabulary because each entry names a
    #: different thing to go and fix.
    understated_because: str = ""

    def __post_init__(self) -> None:
        if self.per_hour < 0:
            raise Unmeasured(f"per_hour={self.per_hour!r} is not a rate")
        if self.arrivals not in ARRIVALS:
            raise Unmeasured(
                f"{self.arrivals!r} is not one of {ARRIVALS}. These are not two settings of one thing: a closed loop "
                f"cannot form a queue, so it measures capacity and is silent about service -- and opening the loop "
                f"reversed this project's own co-residency verdict")
        if not isinstance(self.offered, Offered):
            raise Unmeasured(f"offered={self.offered!r} is not an Offered; a bare concurrency cannot say whether the "
                             f"engine or the client was the limit")
        if self.understated_because and self.understated_because not in UNDERSTATED_BECAUSE:
            raise Unmeasured(f"{self.understated_because!r} is not one of {UNDERSTATED_BECAUSE}")
        if (self.deadline_seconds is None) != (self.goodput_per_hour is None):
            raise Unmeasured(
                f"deadline_seconds={self.deadline_seconds!r} and goodput_per_hour={self.goodput_per_hour!r}: a goodput "
                f"with no deadline is a number nobody can check, and a deadline with no goodput is a promise nobody "
                f"measured")
        if self.deadline_seconds is not None:
            if self.deadline_seconds <= 0:
                raise Unmeasured(f"deadline_seconds={self.deadline_seconds!r} is not a deadline")
            if self.goodput_per_hour < 0:
                raise Unmeasured(f"goodput_per_hour={self.goodput_per_hour!r} is not a rate")
            if self.goodput_per_hour > self.per_hour + 1e-9:
                raise Unmeasured(
                    f"goodput {self.goodput_per_hour} exceeds the completed rate {self.per_hour}: more requests came "
                    f"back inside the deadline than came back at all")

    @property
    def is_lower_bound(self) -> bool:
        """Whether this rate is known to understate the box.

        **The default is that it does.** A run whose generator was never shown to be off the critical path is a lower
        bound, and treating silence as a measurement is how a client's limit gets published as a box's capacity.
        """
        return bool(self.understated_because) or self.offered.starves_the_engine

    def supports_a_service_level_claim(self) -> bool:
        """Whether this rate may be read as "the box holds this traffic within the deadline".

        Two conditions, and the first is structural rather than a matter of rigour: a closed loop offers less when the
        server slows, so no queue forms and there is nothing for a deadline to be missed against. A capacity number from
        a closed loop is fine; a service level from one is not available at any sample size.
        """
        return self.arrivals == "open_loop" and self.deadline_seconds is not None

    def why_not_a_service_level(self) -> str:
        """One sentence naming what stands between this rate and a claim about service."""
        if self.supports_a_service_level_claim():
            return (f"open-loop arrivals with a {self.deadline_seconds:g}s deadline: "
                    f"{self.goodput_per_hour:.0f} of {self.per_hour:.0f} an hour landed inside it")
        reasons = []
        if self.arrivals != "open_loop":
            reasons.append("a closed loop offers less when the server slows, so no queue forms and a deadline has "
                           "nothing to be missed against")
        if self.deadline_seconds is None:
            reasons.append("no deadline was declared, and the mean is conserved when box-time moves between request "
                           "families, so it is blind to whether anything arrived in time")
        return "not a service-level claim -- " + "; and ".join(reasons)

    def __str__(self) -> str:
        head = f"{self.per_hour:.0f}/hour ({self.arrivals}, {self.offered})"
        if self.deadline_seconds is not None:
            head += f", {self.goodput_per_hour:.0f}/hour inside {self.deadline_seconds:g}s"
        if self.is_lower_bound:
            head += f" -- LOWER BOUND ({self.understated_because or 'offered below the seat count'})"
        return head


def comparable_load(a: Throughput, b: Throughput) -> None:
    """Refuse to read two rates against each other when the load, not the box, is what differs.

    Each refusal is a number this project published and had to take back.
    """
    if a.arrivals != b.arrivals:
        raise Unmeasured(
            f"these rates were measured under {a.arrivals!r} and {b.arrivals!r} arrivals. Opening the loop reversed the "
            f"verdict here once -- from a box losing $8.63 a box-hour to one earning $18.88 -- so the difference between "
            f"them is partly the difference between the two questions")
    for side in (a, b):
        if side.offered.seats is None:
            raise Unmeasured(
                f"one of these rates has an unread seat count ({side.offered}). An unread limit is not an unlimited one: "
                f"384 requests were once offered against 27 seats, and raising the seats moved value per box-hour by 33% "
                f"on the short side -- which is the signature of a seat limit rather than a compute limit")
    if a.offered.seats != b.offered.seats:
        raise Unmeasured(
            f"these rates were measured with {a.offered.seats} and {b.offered.seats} seats. The seat count is a "
            f"configuration of the engine, so the difference between them is the configuration")
    if (a.deadline_seconds is None) != (b.deadline_seconds is None):
        raise Unmeasured("one of these rates declared a deadline and the other did not, so one is a service level and "
                         "the other is a capacity; the comparison is between two different quantities")
    if (a.deadline_seconds is not None and b.deadline_seconds is not None
            and abs(a.deadline_seconds - b.deadline_seconds) > 1e-9):
        raise Unmeasured(f"these goodputs were counted against {a.deadline_seconds:g}s and {b.deadline_seconds:g}s "
                         f"deadlines; a count inside a longer deadline is a different number by construction")


def refuse_coresidency_claim_without_a_zero_arm(arms: dict[str, Throughput]) -> None:
    """Refuse a claim about mixing request families unless the arm with none of the other family was measured.

    **The defect this closes, in the shape it happened.** Every arm measured here contained some long requests, so the
    comparison was between settings of a mixture, and the conclusion "mixing is economically neutral" came out of
    comparing a mixture against another mixture. The arm with zero long requests read 225,730 an hour against 102,022 --
    a factor of more than two, and it was the arm nobody had run.

    `arms` maps a label to a rate. A label of exactly `"zero"` is the arm where the other family is absent.
    """
    if "zero" not in arms:
        raise Unmeasured(
            f"no arm labelled 'zero' is present in {sorted(arms)}. A co-residency claim compares a mixture against the "
            f"absence of the other family, and every arm here being a mixture is how 'mixing is economically neutral' "
            f"was concluded from comparing one mixture with another. The unmeasured arm read 225,730 an hour against "
            f"102,022")
    for label, rate in arms.items():
        if not rate.supports_a_service_level_claim():
            raise Unmeasured(
                f"arm {label!r} cannot support a service-level claim ({rate.why_not_a_service_level()}), and a "
                f"co-residency decision is a service-level question: the mean is conserved when box-time moves between "
                f"families, so it cannot see the trade the decision is about")
