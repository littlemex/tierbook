"""What would have happened under a different choice, computed exactly rather than estimated.

Causal questions about routing are usually hard because you observe one arm per unit. Here they are easy,
and it is worth being explicit about why: the outcome table holds **every candidate's answer on every
item**, so for any routing rule the potential outcome under that rule is observed, not inferred. There is
no missing counterfactual, no propensity to model, no overlap assumption to check. Comparing two policies is
arithmetic on a complete potential-outcomes table.

That completeness is exactly what the rest of this package has been under-using. `quorum` compares policies
by their marginal accuracy and cost, and two marginals whose intervals overlap look indistinguishable even
when one policy dominates the other item by item. A paired comparison on the same items is strictly
sharper, and on a complete table it is free.

## What this module adds that marginals cannot say

**Paired wins and losses.** Not "A is 91.4% and B is 90.4%" but "on 571 items A rescued 34 that B lost and
lost 28 that B rescued", with an exact test on the discordant pairs. Overlapping intervals frequently hide a
significant paired difference, and a significant paired difference frequently hides no cost advantage.

**Regret against the per-item oracle.** The oracle here is not "the best model overall" but, for each item,
**the cheapest candidate that solves it**. That is the true ceiling on routing: no rule can do better,
because doing better would require solving an item nobody solved. Regret splits into the accuracy a policy
gives up and the money it spends above the minimum, and the split matters -- a policy can have near-zero
accuracy regret and enormous cost regret, which is what "just call the dear model" looks like.

**Brackets for arms nobody measured.** A gate we have not built -- a prefill probe on the self-hosted box,
say -- has no observed counterfactual, because the probe scores do not exist. It can still be bounded:
evaluate the same policy with a **perfect** gate (escalate exactly when escalation would help) and with a
**worthless** gate (escalate a random subset of the same size). The first is what the probe could achieve at
best; the second is what it achieves if the signal is noise. If the perfect version already loses, no probe
can win and no GPU needs to be bought. This is the argument that retired the two-by-two intervention design,
and it generalises.

## What it refuses to do

**It will not compare policies on different item sets.** A policy evaluated on the items it happens to
cover is a policy scored on a subset it chose, and the comparison is meaningless. Every run here is over one
explicit item list and `compare` refuses runs whose lists differ.

**It will not report a paired difference without the discordant counts.** "A beats B by 1.0 points" over 571
items can be 34 against 28 or 200 against 194, and those are different facts. Both counts travel with every
comparison, and the p-value is the exact sign test rather than a normal approximation, because the counts
here are small enough for the approximation to manufacture significance.

**It will not call a bracket a measurement.** `bracket` returns two numbers with the gate named as
hypothetical. A reader who quotes the optimistic end as the policy's performance has been warned in the
field name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import comb
from typing import Callable, Sequence

from tierbook.evidence import UNOBSERVED, EvidenceError
from tierbook.outcomes import Cell, OutcomeTable
from tierbook.reproduce import wilson

#: A rule: given the table, an item, and the candidates it may use, return the tiers it calls in order.
#: Returning a tier twice is allowed and paid for twice, because a retry is a real cost.
Rule = Callable[[OutcomeTable, str], Sequence[str]]


def _cell(table: OutcomeTable, item: str, tier: str) -> Cell:
    return table.cells.get(item, {}).get(tier) or Cell(UNOBSERVED, None)


@dataclass
class Run:
    """One policy's exact behaviour on one item list."""

    label: str
    items: tuple[str, ...]
    solved: tuple[bool, ...]
    usd: tuple[float, ...]
    calls: tuple[tuple[str, ...], ...]

    @property
    def accuracy(self) -> float:
        return sum(self.solved) / len(self.solved) if self.solved else 0.0

    @property
    def usd_per_item(self) -> float:
        return sum(self.usd) / len(self.usd) if self.usd else 0.0

    @property
    def calls_per_item(self) -> float:
        return sum(len(c) for c in self.calls) / len(self.calls) if self.calls else 0.0

    def accuracy_interval(self) -> tuple[float, float]:
        return wilson(sum(self.solved), len(self.solved))

    def __str__(self) -> str:
        lo, hi = self.accuracy_interval()
        return (f"{self.label}: {self.accuracy:.1%} [{lo:.1%}, {hi:.1%}], "
                f"${self.usd_per_item:.5f}/item, {self.calls_per_item:.2f} calls/item")


def simulate(table: OutcomeTable, rule: Rule, items: Sequence[str], *, label: str) -> Run:
    """Run a rule over a complete table and record exactly what it would have done.

    The rule is called once per item and returns the tiers it would call. The answer taken is the last
    call's answer, which is what every policy in this package does; a rule that wants different arbitration
    should encode it by returning a different final tier.
    """
    solved: list[bool] = []
    usd: list[float] = []
    calls: list[tuple[str, ...]] = []
    for item in items:
        seq = tuple(rule(table, item))
        if not seq:
            raise EvidenceError(f"the rule called nothing on item {item!r}; a policy must call something")
        spent = 0.0
        for tier in seq:
            c = _cell(table, item, tier)
            if c.state == UNOBSERVED:
                raise EvidenceError(
                    f"the rule called {tier!r} on item {item!r}, which is unobserved. A counterfactual "
                    f"is only exact where the cell exists; this one would have to be imputed.")
            if c.usd is None:
                raise EvidenceError(f"{tier!r} on {item!r} carries no cost, so this run cannot be priced")
            spent += c.usd
        final = _cell(table, item, seq[-1])
        solved.append(bool(final.solved))
        usd.append(spent)
        calls.append(seq)
    return Run(label, tuple(items), tuple(solved), tuple(usd), tuple(calls))


def oracle(table: OutcomeTable, candidates: Sequence[str], items: Sequence[str]) -> Run:
    """For each item, the cheapest candidate that solves it. The true ceiling on any routing rule.

    Where nobody solves an item the oracle still has to pay something, and it pays the cheapest candidate:
    an oracle that spends nothing on unsolvable items would be comparing against a rule that knows in
    advance which items to skip, which is a different and stronger oracle. `abandonment_oracle` is that one,
    kept separate so the two are never conflated.
    """
    def rule(t: OutcomeTable, item: str) -> Sequence[str]:
        priced = [(c, _cell(t, item, c)) for c in candidates]
        priced = [(c, x) for c, x in priced if x.state != UNOBSERVED and x.usd is not None]
        if not priced:
            raise EvidenceError(f"no priced candidate observed on item {item!r}")
        winners = [(x.usd, c) for c, x in priced if x.solved]
        if winners:
            return (min(winners)[1],)
        return (min((x.usd, c) for c, x in priced)[1],)

    return simulate(table, rule, items, label="oracle (cheapest solver per item)")


def abandonment_oracle(table: OutcomeTable, candidates: Sequence[str],
                       items: Sequence[str]) -> Run:
    """The oracle that also knows which items to skip: it pays nothing where nobody solves.

    Strictly stronger than `oracle` and worth reporting alongside it, because the difference between the two
    is the entire prize for predicting unsolvability -- the quantity separately measured at AUC 0.5000 from
    output-side signals.
    """
    def rule(t: OutcomeTable, item: str) -> Sequence[str]:
        priced = [(c, _cell(t, item, c)) for c in candidates]
        priced = [(c, x) for c, x in priced if x.state != UNOBSERVED and x.usd is not None]
        if not priced:
            raise EvidenceError(f"no priced candidate observed on item {item!r}")
        winners = [(x.usd, c) for c, x in priced if x.solved]
        if winners:
            return (min(winners)[1],)
        # Nothing solves it. The cheapest observation is the smallest price that can be paid to find out,
        # and a rule that pays zero would be assuming the item never arrived.
        return (min((x.usd, c) for c, x in priced)[1],)

    run = simulate(table, rule, items, label="oracle with abandonment")
    # Zero out the spend on items nobody solves: that is what abandonment buys.
    usd = list(run.usd)
    for j, item in enumerate(items):
        if not run.solved[j]:
            usd[j] = 0.0
    return Run(run.label, run.items, run.solved, tuple(usd), run.calls)


def _sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(max(wins, losses), n + 1))
    return min(1.0, 2 * tail / 2 ** n)


#: How a comparison relates to the knob whose setting it depends on. Closed, because the three are not degrees of
#: the same thing and the difference decides what the comparison may be read as.
#:
#: `fixed` -- true at one setting, which must be named. `integrated` -- reported over the whole curve, so no single
#: setting applies. `not_applicable` -- neither run has a tunable setting at all, which is an honest answer for two
#: fixed candidates and a dishonest default for anything with a gate in it.
OPERATING_POINT_KINDS = ("fixed", "integrated", "not_applicable")

#: Where the setting came from. This distinction is the one that was MEASURED to matter: choosing the coverage on the
#: items the comparison is then scored on gave seven candidate settings at every price of accuracy, and picking the
#: best of them inflated the reported interval directly. A comparison built that way is still worth recording -- it
#: says what the best case looked like -- but it cannot support a verdict, which is why `Unsupported` exists rather
#: than a refusal at construction.
CHOSEN_ON = ("calibration", "declared_in_advance", "scored_items")


class Unsupported(RuntimeError):
    """The comparison is readable and cannot support the verdict being asked of it. Distinct from an error: nothing
    about it is malformed, and the number it holds is the number that was computed. What is missing is the licence to
    read that number as a verdict, which is a property of how the setting was chosen rather than of the arithmetic."""


@dataclass(frozen=True)
class OperatingPoint:
    """The setting a comparison was made at, and where that setting came from.

    Required on every `Comparison`, with no default, because a comparison reported without it reads as a general
    ranking and is not one. Signals cross: on the deferral curve measured for this study, three signals that separate
    cleanly at one floor all converge at the last tenth, so a ranking taken at one floor does not hold at another.
    """

    kind: str
    value: float | None = None
    chosen_on: str | None = None
    knob: str = ""

    def __post_init__(self) -> None:
        if self.kind not in OPERATING_POINT_KINDS:
            raise EvidenceError(f"{self.kind!r} is not one of {OPERATING_POINT_KINDS}; an open-ended kind cannot be "
                                f"aggregated over a set of comparisons, and the three differ in what may be read "
                                f"from them")
        if self.kind == "fixed":
            if self.value is None:
                raise EvidenceError(
                    "a fixed operating point with no value names nothing. The whole point of naming it is that a "
                    "ranking taken at one setting does not hold at another, so 'fixed' without the setting is the "
                    "unnamed comparison this field exists to stop")
            if self.chosen_on not in CHOSEN_ON:
                raise EvidenceError(
                    f"chosen_on={self.chosen_on!r} is not one of {CHOSEN_ON}. Where the setting came from decides "
                    f"whether the comparison supports a verdict: chosen on the scored items it does not, and that "
                    f"was measured rather than assumed")
            if not self.knob:
                raise EvidenceError(
                    "a fixed operating point with no knob named says a number without saying what it sets. A "
                    "coverage of 0.30 and a price of accuracy of 0.30 are different facts and would be read as the "
                    "same one")
        else:
            for name in ("value", "chosen_on"):
                if getattr(self, name) is not None:
                    raise EvidenceError(
                        f"kind={self.kind!r} carries {name}={getattr(self, name)!r}. Only a fixed point has a "
                        f"setting: an integrated comparison spans them all and a not_applicable one has no knob, so "
                        f"a value here would be read as the setting the comparison holds at")

    @property
    def supports_a_verdict(self) -> bool:
        return not (self.kind == "fixed" and self.chosen_on == "scored_items")

    def __str__(self) -> str:
        if self.kind == "fixed":
            return f"at {self.knob}={self.value:g} (chosen on {self.chosen_on})"
        return "over the whole curve" if self.kind == "integrated" else "no tunable setting"


@dataclass(frozen=True)
class Comparison:
    """A paired comparison of two runs on the same items."""

    a: str
    b: str
    items: int
    a_only: int                 # items a solved and b did not
    b_only: int                 # items b solved and a did not
    p_value: float              # exact sign test on the discordant pairs
    usd_delta: float            # a minus b, per item
    accuracy_delta: float       # a minus b
    #: No default. A comparison whose operating point is unstated reads as a general ranking, and F18's measurement
    #: is that it is not one -- three signals that separate at one floor converge at the last tenth. Defaulting this
    #: to anything would put the unnamed comparison back, wearing a field that claims it was named.
    operating_point: OperatingPoint

    def is_significant(self, *, allow_point_chosen_on_scored_items: bool = False) -> bool:
        """Whether the paired difference clears the level -- refused when the setting was chosen on these items.

        A method with an explicit escape rather than a property, on the same shape `table.lookup` uses for an
        unvalidated entry: the caller who wants the number anyway says so at the call site, where a reader of that
        line can see the claim being made.

        The refusal is not pedantry about a fold. Choosing the setting on the items then scored gave seven candidate
        settings at every price of accuracy, and taking the best of them inflated the reported interval directly --
        so the p-value below is not the p-value of the procedure that produced this number.
        """
        if not self.operating_point.supports_a_verdict and not allow_point_chosen_on_scored_items:
            raise Unsupported(
                f"{self.a} vs {self.b} was compared at {self.operating_point.knob}={self.operating_point.value:g}, "
                f"chosen on the items it is scored on. p = {self.p_value:.4f} is the p-value of a test that did not "
                f"include choosing the setting, so it is not the p-value of this result; pass "
                f"allow_point_chosen_on_scored_items=True to read it as the best case rather than as a verdict")
        return self.p_value < 0.05

    def __str__(self) -> str:
        try:
            verdict = ("a significant accuracy difference" if self.is_significant()
                       else "no significant accuracy difference")
        except Unsupported:
            # Said rather than swallowed: a comparison that cannot support a verdict prints what it is instead of
            # printing the verdict it cannot support, and prints it in the place a reader looks for the verdict.
            verdict = "no verdict: the setting was chosen on the scored items"
        return (f"{self.a} vs {self.b} on {self.items} items {self.operating_point}: "
                f"{self.a_only} / {self.b_only} discordant, p = {self.p_value:.4f} ({verdict}); "
                f"accuracy {self.accuracy_delta:+.1%}, cost {self.usd_delta:+.5f}/item")


def compare(a: Run, b: Run, *, operating_point: OperatingPoint) -> Comparison:
    """Pair two runs item by item. Refuses runs over different item lists, and requires the setting be named.

    `operating_point` is keyword-only and has no default for the reason the field does not: a signature that let it
    be omitted would make the unnamed comparison the easy one to write.
    """
    if a.items != b.items:
        raise EvidenceError(
            f"cannot pair {a.label!r} over {len(a.items)} items with {b.label!r} over {len(b.items)}: "
            f"a policy scored on the items it happens to cover is scored on a subset it chose")
    a_only = sum(1 for x, y in zip(a.solved, b.solved) if x and not y)
    b_only = sum(1 for x, y in zip(a.solved, b.solved) if y and not x)
    return Comparison(a.label, b.label, len(a.items), a_only, b_only,
                      _sign_test(a_only, b_only),
                      a.usd_per_item - b.usd_per_item, a.accuracy - b.accuracy,
                      operating_point)


@dataclass
class Regret:
    """How far a run sits from the per-item ceiling, split into the two currencies."""

    label: str
    accuracy_regret: float      # oracle accuracy minus this run's
    usd_regret: float           # this run's cost minus the oracle's, per item
    usd_ratio: float            # this run's cost divided by the oracle's
    items_lost: int             # items the oracle solved and this run did not

    def __str__(self) -> str:
        return (f"{self.label}: gives up {self.accuracy_regret:.1%} accuracy "
                f"({self.items_lost} items) and spends {self.usd_ratio:.2f}x the oracle "
                f"({self.usd_regret:+.5f}/item)")


def regret(run: Run, ceiling: Run) -> Regret:
    if run.items != ceiling.items:
        raise EvidenceError("regret needs the run and the ceiling over the same items")
    lost = sum(1 for x, y in zip(ceiling.solved, run.solved) if x and not y)
    base = ceiling.usd_per_item
    return Regret(run.label, ceiling.accuracy - run.accuracy,
                  run.usd_per_item - base,
                  run.usd_per_item / base if base else float("inf"), lost)


# --------------------------------------------------------------- hypothetical gates


@dataclass
class Bracket:
    """Best and worst case for a policy whose gate has not been measured.

    `optimistic` uses a gate that fires exactly when escalation would help; `pessimistic` uses a gate that
    fires on a random subset of the same size. A real signal lands between them. **Neither is a measurement
    of anything that exists** -- the field names say so on purpose, because quoting the optimistic end as a
    result is the failure mode this class is built to prevent.
    """

    label: str
    optimistic: Run
    pessimistic: Run
    gate_rate: float
    #: Set when even the optimistic end fails whatever bar was applied. Then no signal quality can rescue
    #: the design and no measurement needs to be bought.
    optimistic_already_fails: str | None = None

    def __str__(self) -> str:
        s = (f"{self.label} (gate fires on {self.gate_rate:.1%} of items, HYPOTHETICAL):\n"
             f"    perfect gate:   {self.optimistic}\n"
             f"    worthless gate: {self.pessimistic}")
        if self.optimistic_already_fails:
            s += f"\n    -> {self.optimistic_already_fails}"
        return s


def bracket_gated_escalation(table: OutcomeTable, items: Sequence[str], *, first: str,
                             escalate_to: str, seed: int = 0) -> Bracket:
    """Bound a policy of the form "call `first`; a gate decides whether to escalate".

    The gate's size is fixed to the rate a perfect gate would fire at -- the share of items `first` gets
    wrong -- so the two ends differ only in *which* items are escalated, never how many. Holding the call
    budget fixed is what makes the pessimistic end a fair floor rather than a cheaper policy in disguise.
    """
    import random

    need = [item for item in items if not _cell(table, item, first).solved]
    rate = len(need) / len(items) if items else 0.0
    need_set = set(need)

    def perfect(t: OutcomeTable, item: str) -> Sequence[str]:
        return (first, escalate_to) if item in need_set else (first,)

    rng = random.Random(seed)
    chosen = set(rng.sample(list(items), len(need))) if need else set()

    def worthless(t: OutcomeTable, item: str) -> Sequence[str]:
        return (first, escalate_to) if item in chosen else (first,)

    return Bracket(
        label=f"{first} -> {escalate_to}, gated",
        optimistic=simulate(table, perfect, items, label=f"{first}->{escalate_to} (perfect gate)"),
        pessimistic=simulate(table, worthless, items, label=f"{first}->{escalate_to} (random gate)"),
        gate_rate=rate,
    )
