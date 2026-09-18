"""What a request costs, split into the two things a router actually chooses between.

Everything in this project priced a request by its token count, which charges the same rate for reading the prompt and
for writing the answer. Those were measured on the same server and they are not the same size:

| leg | measured |
|---|---|
| reading the prompt (prefill) | **0.109 s** |
| writing the answer, at the box's own median of 687 tokens | **10.42 s** |

**A ratio of about 95.** Two consequences follow, and a scalar total hides both.

**A gate decides whether to generate, so it trades one leg against the other.** Priced as one number, the gate's own
depth looks like it matters; priced apart, it is 1% of what the gate saves and the decision is dominated entirely by
whether generation happens. A comparison that changes only one leg cannot be read from a total.

**A signal costs forward passes, and nothing recorded how many.** Every intervention feature measured here costs at
least a second read of the prompt, which at that ratio is 1% of the saving -- so **even a small additive gain is worth
buying**, and that is a statement no total can make. `SignalPrice` exists so the trade can be stated rather than
guessed at.

The unit vocabulary lives here rather than beside the comparison code, so there is one home for what a cost is: reading
this module tells a reader everything about how this package prices anything.
"""
from __future__ import annotations

from dataclasses import dataclass

from tierbook.evidence import EvidenceError

#: What a cost is measured in. Closed, because the three are not interchangeable and no conversion between them is
#: available here.
#:
#: `usd` is what a metered API bills and the only unit in which two candidates of different kinds are directly
#: comparable. `tokens` is what every experiment in this study actually measured, and it is a **weak proxy**: a policy
#: ahead in tokens can lose in `gpu_seconds`, because a token count does not see KV-cache occupancy or the effect of a
#: long trace on every other request sharing the batch. `gpu_seconds` is what a self-hosted machine actually spends,
#: and it is the one a serving system feels.
#:
#: There is deliberately no conversion function. `tokens` to `usd` needs a price card, `tokens` to `gpu_seconds` needs
#: a throughput measured under load rather than more items, and a coefficient assumed instead of measured once moved a
#: published figure in this project by a factor of six and changed which candidate was selected.
COST_UNITS = ("usd", "tokens", "gpu_seconds")

#: How a cost in this unit prints, so a token count is never rendered with a currency symbol.
_UNIT_FORMAT = {"usd": ("$", "{:.5f}"), "tokens": ("", "{:.1f} tokens"), "gpu_seconds": ("", "{:.3f} GPU-s")}

#: The legs a request's cost divides into. Closed, and exactly two, because these are the two a router chooses
#: between: reading the prompt happens whatever it decides, and writing the answer is what it decides about.
LEGS = ("prefill", "generation")

#: The legs the price card actually bills, which is four and not two. `prefill` above is the input side seen whole;
#: these are the three prices it can be made of, plus generation.
#:
#: The reason the split is not cosmetic: **the cache discount attaches to the SHAPE of a request, not to its text.**
#: Identical content sent as one long message hit a 0% cache rate where the same content as a growing conversation hit
#: 99.9%. So two runs can send the same words, be billed on different legs, and differ in cost by most of the input
#: side -- and a cost model that cannot say which leg was charged reports that as a difference between the arms.
BILLED_LEGS = ("fresh_in", "cached_in", "cache_write", "generation")


def format_cost(value: float, unit: str) -> str:
    """Render a cost with its unit, so a token count never appears behind a currency symbol.

    A number printed with the wrong unit is the report-level form of the defect the refusals here prevent: a reader
    comparing two figures assumes they are in the same thing, and a `$` in front of a token count is the strongest
    possible reason to assume it.
    """
    prefix, fmt = _UNIT_FORMAT[unit]
    return prefix + fmt.format(value)


@dataclass(frozen=True)
class Spend:
    """A cost with its legs kept apart, and a total derived rather than supplied.

    `total` is a property, not a field. A supplied total is a total that can disagree with the legs it claims to sum,
    and then two numbers describe one cost and nothing says which is right. It is also the field a caller reaches for
    when they have not thought about which leg their change touches, which is the defect this whole module records.
    """

    prefill: float
    generation: float
    unit: str = "usd"
    #: How much of `prefill` was billed as a read from cache, and as populating one. `None` on both means the legs were
    #: never split, which is the state of every cost recorded before these fields existed -- left representable because
    #: refusing it would make the module unusable on the data that exists.
    #:
    #: All-or-nothing, like `Run.legs`: a cost that records one and not the other reports a fresh remainder that is
    #: wrong by exactly the leg it left out, and gives a reader a discrepancy with nothing to attribute it to.
    cached_in: float | None = None
    cache_write: float | None = None

    def __post_init__(self) -> None:
        if self.unit not in COST_UNITS:
            raise EvidenceError(
                f"{self.unit!r} is not one of {COST_UNITS}. An open-ended unit cannot be checked for "
                f"commensurability, and the whole reason to name it is that a policy ahead in tokens can lose in "
                f"GPU-seconds")
        for leg in LEGS:
            if getattr(self, leg) < 0:
                raise EvidenceError(f"{leg}={getattr(self, leg)!r} is negative; a leg that gives cost back is not a "
                                    f"cost, and summing it would make a total smaller than one of its parts")
        if (self.cached_in is None) != (self.cache_write is None):
            raise EvidenceError(
                f"cached_in={self.cached_in!r} and cache_write={self.cache_write!r}: one is recorded and the other is "
                f"not. The fresh remainder is then wrong by exactly the leg that was left out, and a reader gets a "
                f"discrepancy with nothing to attribute it to -- so the input side is split on all three legs or on "
                f"none of them")
        if self.cached_in is not None:
            for name in ("cached_in", "cache_write"):
                if getattr(self, name) < 0:
                    raise EvidenceError(f"{name}={getattr(self, name)!r} is negative")
            if self.cached_in + self.cache_write > self.prefill + 1e-12:
                raise EvidenceError(
                    f"cached_in {self.cached_in} plus cache_write {self.cache_write} exceeds the input side "
                    f"{self.prefill}, so the fresh remainder would be negative. These are PARTS of the input cost, "
                    f"not additions to it: a caller adding them on top is double-charging the tokens the cache served")

    @property
    def total(self) -> float:
        return self.prefill + self.generation

    @property
    def cache_split(self) -> bool:
        """Whether this cost says which input leg it was billed on."""
        return self.cached_in is not None

    @property
    def fresh_in(self) -> float | None:
        """The input cost that was NOT served from cache and did not populate one. Derived, so it cannot disagree."""
        return None if not self.cache_split else self.prefill - self.cached_in - self.cache_write

    @property
    def served_from_cache(self) -> bool | None:
        """Whether any of this request's input was billed as a cache read. `None` when nobody recorded the split."""
        return None if not self.cache_split else self.cached_in > 0

    @property
    def generation_share(self) -> float:
        """How much of this cost is the part a gate can avoid. On the numbers measured here, 0.9896."""
        return 0.0 if self.total == 0 else self.generation / self.total

    def __add__(self, other: Spend) -> Spend:
        if not isinstance(other, Spend):
            return NotImplemented
        if self.unit != other.unit:
            raise EvidenceError(
                f"cannot add a cost in {self.unit!r} to one in {other.unit!r}: the sum would be a number in no unit at "
                f"all, and it would look exactly like a cost")
        # A sum of a split cost and an unsplit one is unsplit: the parts of the second are unknown, so claiming a
        # split for the total would attribute the whole of the second's input to the fresh leg.
        both = self.cache_split and other.cache_split
        return Spend(prefill=self.prefill + other.prefill, generation=self.generation + other.generation,
                     unit=self.unit,
                     cached_in=(self.cached_in + other.cached_in) if both else None,
                     cache_write=(self.cache_write + other.cache_write) if both else None)

    def __str__(self) -> str:
        if not self.cache_split:
            return (f"{format_cost(self.total, self.unit)} "
                    f"({format_cost(self.prefill, self.unit)} prefill + "
                    f"{format_cost(self.generation, self.unit)} generation)")
        return (f"{format_cost(self.total, self.unit)} "
                f"({format_cost(self.fresh_in, self.unit)} fresh + "
                f"{format_cost(self.cached_in, self.unit)} cached + "
                f"{format_cost(self.cache_write, self.unit)} cache write + "
                f"{format_cost(self.generation, self.unit)} generation)")


def refuse_mixed_cache(before: Spend, after: Spend) -> None:
    """Refuse to subtract two costs whose input was billed on different legs.

    A cached read and a fresh read of the same tokens are different prices for the same words, and the discount attaches
    to the request's SHAPE: identical content hit 0% as one long message and 99.9% as a growing conversation. So a
    difference between an arm served from cache and an arm that was not is mostly a cache effect wearing the name of
    whatever the arms were supposed to differ in.

    This is the refusal that would have stopped the withdrawn routing saving: routing breaks a cache prefix, so a
    decision that changes destination changes which leg the NEXT request is billed on -- and with no record of the shape,
    the sign of the saving is undetermined rather than merely imprecise.

    An unrecorded split is not a zero cache rate. Both unrecorded is allowed through, because refusing it would refuse
    every cost written before the legs existed.
    """
    if not before.cache_split and not after.cache_split:
        return
    if before.cache_split != after.cache_split:
        raise EvidenceError(
            f"cannot subtract these costs: one records which input leg it was billed on and the other does not. An "
            f"unrecorded split is not a zero cache rate, and reading it as one attributes the whole input side to the "
            f"fresh leg -- which is the direction that makes a cache effect look like a saving")
    if before.served_from_cache != after.served_from_cache:
        served, fresh = ((before, after) if before.served_from_cache else (after, before))
        raise EvidenceError(
            f"cannot subtract a cost whose input was served from cache ({served.cached_in} of {served.prefill}) from "
            f"one that was billed fresh ({fresh.prefill}): these are different prices for the same words, and the "
            f"discount attaches to the request's shape rather than to its text -- identical content measured 0% as one "
            f"long message and 99.9% as a growing conversation. The difference is mostly the cache, under whatever name "
            f"the arms were supposed to differ in")


def avoided(before: Spend, after: Spend) -> Spend:
    """What a decision saved, leg by leg, so a saving cannot be reported without saying which leg it came from.

    The distinction is the reason this function exists rather than a subtraction at the call site: a saving that is all
    generation is a gate working, and a saving of the same size that is all prefill is a shorter prompt. Those need
    different things done next, and a scalar difference cannot tell them apart.
    """
    if before.unit != after.unit:
        raise EvidenceError(f"cannot subtract a cost in {after.unit!r} from one in {before.unit!r}")
    refuse_mixed_cache(before, after)
    both = before.cache_split and after.cache_split
    return Spend(prefill=max(0.0, before.prefill - after.prefill),
                 generation=max(0.0, before.generation - after.generation), unit=before.unit,
                 cached_in=max(0.0, before.cached_in - after.cached_in) if both else None,
                 cache_write=max(0.0, before.cache_write - after.cache_write) if both else None)


@dataclass(frozen=True)
class SignalPrice:
    """What a signal costs to obtain, counted in forward passes rather than guessed at.

    Nothing in this project recorded this, so the trade every intervention feature asks for could not be stated. A
    feature read from the prompt alone is one pass; anything that patches a hidden state and reads the effect is two,
    because the patched pass has to be run. At the measured leg ratio a second read of the prompt is about 1% of what
    a gate saves, which is why the conclusion is **buy even a small additive gain** -- but that conclusion needs the
    pass count to exist.
    """

    passes: int
    per_pass: Spend

    def __post_init__(self) -> None:
        if not isinstance(self.passes, int) or isinstance(self.passes, bool):
            raise EvidenceError(f"passes={self.passes!r} is not an integer; a fractional pass is not something a "
                                f"server runs, and a bool here would count True as one pass silently")
        if self.passes < 1:
            raise EvidenceError(
                "a signal costing zero passes is a signal read from nothing. Every feature measured here costs at "
                "least one read of the prompt, and recording zero would make the trade this type exists to state come "
                "out free")
        if not isinstance(self.per_pass, Spend):
            raise EvidenceError(f"per_pass={self.per_pass!r} is not a Spend. A scalar here is the defect this module "
                                f"records: it cannot say whether the pass costs a prompt read or a generation, and "
                                f"those differ by a factor of about 95")

    @property
    def cost(self) -> Spend:
        """What obtaining the signal costs in total, which is the per-pass cost as many times as there are passes."""
        return Spend(prefill=self.per_pass.prefill * self.passes,
                     generation=self.per_pass.generation * self.passes, unit=self.per_pass.unit)

    @property
    def extra_passes(self) -> int:
        """Passes beyond the one the request pays anyway.

        This distinction is not a refinement, it is the difference between two answers. A request that answers at all
        reads its prompt once, so a signal computed from that read costs **nothing extra** -- and the recorded
        conclusion, "a second prompt read is 1% of what the gate saves", is about the *extra* pass. Counting all passes
        instead doubles it to 2%, which was this implementation's first mistake: the number came out twice the
        ledger's and the ledger was right.
        """
        return self.passes - 1

    @property
    def marginal_cost(self) -> Spend:
        """What this signal adds to a request that was going to run anyway."""
        return Spend(prefill=self.per_pass.prefill * self.extra_passes,
                     generation=self.per_pass.generation * self.extra_passes, unit=self.per_pass.unit)

    def share_of(self, saving: Spend, *, marginal: bool = True) -> float:
        """What fraction of a saving this signal consumes -- the number that makes the trade statable.

        `marginal` defaults to True because that is the question a router asks: the prompt read happens whether or not
        the signal is computed, so charging the signal for it prices a cost nobody avoids. On the measured legs a
        two-pass signal is then **0.0105** of a whole generation avoided, which is the recorded 1% and the entire
        argument for buying even a small additive gain.

        `marginal=False` answers the other question -- what the signal costs in absolute terms -- and is here so a
        caller who wants it says so, rather than getting it by default and reading it as the trade.
        """
        if saving.unit != self.per_pass.unit:
            raise EvidenceError(
                f"the saving is in {saving.unit!r} and the signal costs {self.per_pass.unit!r}, so their ratio is not "
                f"a fraction of anything; converting needs a price card or a throughput measured under load")
        if saving.total <= 0:
            raise EvidenceError("a signal's share of a saving of zero is undefined, and returning a large number "
                                "instead would read as 'too expensive' when the fact is that nothing was saved")
        return (self.marginal_cost if marginal else self.cost).total / saving.total
