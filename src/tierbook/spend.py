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

from tierbook.evidence import CONTEXT_CROSSINGS, EvidenceError

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


@dataclass(frozen=True)
class Partitioning:
    """How many contexts a run kept, and what crossed between them. The ninth harness part, priced.

    This is what makes a counterfactual definable. "What would this have cost unrouted" is a question about how many
    contexts there would have been and what would have crossed between them -- so with the partitioning unrecorded the
    alternative is **not computable** rather than merely unmeasured, which is a different kind of missing and needs
    saying differently.

    **Counting contexts is not enough, and that is the whole reason `crosses` exists.** Two contexts exchanging only
    briefs and results keep both caches warm, because neither context ever switches model; two contexts where the
    transcript is copied across bill the entire prefix as fresh input in the second one. The first arrangement is where a
    published 39.2% saving comes from and the second costs more than not splitting at all -- and a record that counts
    contexts without saying what crossed cannot tell them apart.
    """

    contexts: int
    crosses: str

    def __post_init__(self) -> None:
        if not isinstance(self.contexts, int) or isinstance(self.contexts, bool):
            raise EvidenceError(f"contexts={self.contexts!r} is not an integer")
        if self.contexts < 1:
            raise EvidenceError("a run with no context did not happen; there is always at least the one the request "
                               "arrived in")
        if self.crosses not in CONTEXT_CROSSINGS:
            raise EvidenceError(f"{self.crosses!r} is not one of {CONTEXT_CROSSINGS}")
        if self.contexts == 1 and self.crosses != "nothing":
            raise EvidenceError(
                f"one context and {self.crosses!r} crossing it: there is nothing for it to cross TO. Either a second "
                f"context went unrecorded -- and then the fresh input it was billed is attributed to the first -- or the "
                f"crossing is a description of something that did not happen")

    @property
    def duplicates_prefix(self) -> bool:
        """Whether the split re-bills a prefix as fresh input somewhere else, which makes it cost rather than save."""
        return self.crosses == "whole_history"

    def __str__(self) -> str:
        tail = " (re-bills the prefix as fresh input)" if self.duplicates_prefix else ""
        return f"{self.contexts} context(s), {self.crosses} crossing{tail}"


@dataclass(frozen=True)
class Conversation:
    """The turns that shared one context, and the cost of the whole of it rather than of any one request.

    **A per-request cost is incomplete by construction.** Whether a request's input is billed as a cache read depends on
    the request BEFORE it in the same context, so the cheapest turn in a sequence is cheap because an earlier one paid
    to populate the cache. Attributing that discount to the turn that received it credits the wrong request, and
    subtracting two such turns from different sequences subtracts two numbers that mean different things.

    This is the object the withdrawn routing saving needed and did not have. The ledger's own note on it says the
    replacement may not exist because the run's shape -- single calls against multi-turn sequences -- was never
    recorded. A cost with a `turns` count is that record.

    What this does NOT settle is the counterfactual. "What would this have cost unrouted" needs to know how many
    contexts exist and what crosses between them, which is the context-partitioning policy (T13). This type makes the
    shape recordable; it does not make the alternative computable.
    """

    context: str
    turns: tuple[Spend, ...]
    #: How the run this sequence belongs to was partitioned. `None` means nobody recorded it, which is the state of
    #: every cost written before the ninth harness part existed -- left representable for the same reason the cache legs
    #: are, and refused only where it is load-bearing: a counterfactual.
    partitioning: Partitioning | None = None

    def __post_init__(self) -> None:
        if self.partitioning is not None and not isinstance(self.partitioning, Partitioning):
            raise EvidenceError(f"partitioning={self.partitioning!r} is not a Partitioning; a bare context count would "
                                f"not say what crossed, and that is what decides whether splitting was cheap")
        if not self.context:
            raise EvidenceError(
                "a conversation with no context identifier cannot say which turns shared a cache prefix, which is the "
                "only thing that makes it a conversation rather than a list of unrelated costs")
        if not self.turns:
            raise EvidenceError("a conversation with no turns is not a conversation; it is the absence of a record "
                                "about one")
        units = {s.unit for s in self.turns}
        if len(units) != 1:
            raise EvidenceError(f"the turns are measured in {sorted(units)}; a total over them would be a number in no "
                                f"unit at all")
        splits = {s.cache_split for s in self.turns}
        if len(splits) != 1:
            raise EvidenceError(
                "some turns record which input leg they were billed on and some do not, so a total over them would put "
                "the unrecorded turns' whole input into the fresh leg. That is the direction that makes a cache effect "
                "look like a saving, and it is the reason the split is all-or-nothing on a single cost too")
        # The one invariant that is arithmetic rather than convention: there is nothing in a context before its first
        # turn, so the first turn cannot have been served from a cache belonging to it. A record that says otherwise is
        # either mis-ordered or is attributing another context's cache to this one, and both make the total wrong.
        if self.turns[0].served_from_cache:
            raise EvidenceError(
                f"the first turn of {self.context!r} reports {self.turns[0].cached_in} billed as a cache read, and "
                f"nothing was in this context before it. Either the turns are out of order, or a cache belonging to "
                f"another context is being charged to this one -- and in both cases the discount is credited to a turn "
                f"that did not earn it")

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def total(self) -> Spend:
        """The cost of the whole sequence. This is the quantity a comparison may use; a single turn's cost is not."""
        out = self.turns[0]
        for s in self.turns[1:]:
            out = out + s
        return out

    @property
    def paid_for_nothing(self) -> bool:
        """Whether this conversation populated a cache nobody read.

        A single turn that paid a cache write bought a discount for a turn that never came. Reported rather than
        refused, because it is a real thing that happens and the record should show it rather than reject it.
        """
        return self.turn_count == 1 and self.turns[0].cache_split and self.turns[0].cache_write > 0

    def __str__(self) -> str:
        tail = " (paid for a cache nobody read)" if self.paid_for_nothing else ""
        return f"{self.context}: {self.turn_count} turn(s), {self.total}{tail}"


def refuse_undefined_counterfactual(actual: Conversation, alternative: Conversation) -> None:
    """Refuse to state what an alternative would have cost when the partitioning of either side is unrecorded.

    **Not computable rather than unmeasured**, and the distinction matters because the two have different remedies. An
    unmeasured quantity can be measured later from the same record; an undefined one cannot, because the record does not
    contain the question. Whether a turn's input is billed fresh or cached depends on how many contexts there were and
    what was copied between them, so without that the alternative's input cost has no value at all -- not an uncertain
    one.

    This is the refusal the ledger's own note on the withdrawn saving asks for: if a published run's shape was never
    recorded there may be no defensible replacement figure, and leaving it withdrawn is the correct end state rather
    than a gap to be filled with an assumption.
    """
    for side, name in ((actual, "the run as it happened"), (alternative, "the alternative")):
        if side.partitioning is None:
            raise EvidenceError(
                f"cannot state what {name} would have cost: {side.context!r} does not record how the run was "
                f"partitioned. Whether a turn's input is billed fresh or cached depends on how many contexts there were "
                f"and what crossed between them, so the alternative's input cost is undefined rather than uncertain -- "
                f"and an undefined quantity cannot be recovered from this record by measuring harder")
    if alternative.partitioning.duplicates_prefix and not actual.partitioning.duplicates_prefix:
        raise EvidenceError(
            f"the alternative copies a whole transcript between contexts and the run as it happened did not, so the "
            f"alternative pays the entire prefix as fresh input in the second context. That is a cost of the "
            f"PARTITIONING and it would be reported as a cost of whatever the two arms were supposed to differ in")


def refuse_incomparable_shapes(a: Conversation, b: Conversation) -> None:
    """Refuse to compare two sequences of different length as though they were two prices for the same work.

    The measured reason: the cache discount attaches to the shape of a request, and identical content billed 0% as one
    long message billed 99.9% as a growing conversation. So a one-turn arm and a five-turn arm carrying the same words
    are not two prices for one thing -- most of the difference between them is the number of turns.

    This is the check the withdrawn saving needed. Routing breaks a cache prefix, so a decision that changes destination
    changes the shape of everything after it; comparing arms of different shape reports that as the decision's effect.
    """
    if a.turn_count != b.turn_count:
        raise EvidenceError(
            f"cannot compare {a.context!r} over {a.turn_count} turn(s) with {b.context!r} over {b.turn_count}: the "
            f"cache discount attaches to the shape of a request rather than to its text, and identical content measured "
            f"0% as one long message against 99.9% as a growing conversation. Most of the difference between arms of "
            f"different length is the length, and routing changes the shape of every turn after the one it moved")
