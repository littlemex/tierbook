"""Ask the same question twice, and report which of the answers survived.

Three conclusions in this project came from one run of a matrix and reversed when the matrix was
collected again: an arbitration gain significant at p = 0.035 became 9 wins to 8 losses at p = 1.0; a
single mid-priced candidate that dominated a quorum became dominated by one; and the cheapest policy
meeting an accuracy floor changed at two of the four floors tested. None of those reversals was caught
by review -- three adversarial rounds read the same numbers and agreed with them -- and all three would
have been caught by running the comparison twice.

So this module exists to make that comparison a routine rather than a heroic act. Its output is
deliberately not a score. It is a list of claims with a `survived` flag, because the useful artefact is
"this specific recommendation did not hold", not a number summarising how reproducible a table was.

## What it refuses to do

**It will not compare a subset that differs between the runs, and it will not hide how much was lost.**
Only items complete in both tables are used. A collection whose second run lost a contiguous block of
items -- a token expiring mid-run does exactly that when work is dispatched in order -- leaves a subset
that is biased rather than merely smaller, and averaging over it produces a confident wrong answer. That
happened here, so `dropped`, the drop-out rate and a **contiguity statistic** travel with the result:
lost items clustered in the id ordering are the signature of an expiry, and scattered ones are the
signature of per-item pathology.

**And it checks that restricting to the shared items did not itself change the answer.** This is the
subtlest thing the module does, and it exists because the module would otherwise be dishonest. The
claims are labelled "what run 1 said", but run 1 is re-evaluated **on the shared subset**, not on the
items it was originally read over. If the subset alone moves run 1's conclusion, the module is checking
the survival of a claim nobody ever made. So `subset_changed_first` is computed before anything else and
reported first; when it fails, every claim after it is about a reconstruction rather than a
recollection.

**It will not accept a candidate that is missing from one side.** Silently dropping it would change the
pool between the runs, which changes every quorum and every frontier, so the comparison would be of two
different questions.

**It will not report a flip rate without an interval.** An earlier measurement put one candidate's rate
at 22.3% with a 95% interval of [15.2%, 29.5%] on 137 items; a bare 22.3% invites arithmetic the
interval forbids.

**It will not make an ordering claim that was never significant.** "A beats B" at 90.4% against 91.1%
over 571 items is two intervals crossing, not a fact, and with eight candidates there are 28 such pairs
-- so most of them would be flags planted in noise, and their "reversal" would be noise reversing. An
ordering claim is only made when run 1's own margin clears an exact paired test, and the p-value travels
with it.

**And it reports how many failures chance alone would produce.** Checking dozens of claims at once means
some fail without anything being wrong. The count is not a correction -- the module deliberately does not
adjust its threshold, because a warning system should err towards warning -- but a reader comparing "5
failed" against "about 1.6 expected by chance" reads it differently from "5 failed" alone.

**And it will not call anything reproducible.** Two runs give a difference, not a variance. A claim that
survives one repeat is a claim that has not yet failed, and `Reproduction` says so in those terms.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from math import comb

from tierbook.evidence import EvidenceError, UNOBSERVED
from tierbook.outcomes import Cell, OutcomeTable
from tierbook.quorum import (
    QuorumPolicy,
    cheapest_meeting,
    enumerate_policies,
    frontier,
)


def wilson(successes: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """A Wilson score interval, which stays inside [0, 1] where the normal approximation does not.

    Used rather than the textbook interval because the rates here are small and the samples are in the
    low hundreds, which is exactly where the normal approximation puts a lower bound below zero and a
    reader stops trusting the number.
    """
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True)
class Claim:
    """One statement a single run supported, and whether the second run still supports it."""

    kind: str                  # "subset_integrity", "cheapest_at_floor", "frontier_membership", "ordering"
    subject: str               # what the claim is about, in words
    first: str                 # what run 1 said
    second: str                # what run 2 said
    survived: bool
    #: For a claim with a null hypothesis, the size of run 1's own test. `None` where there is none.
    p_value: float | None = None

    def __str__(self) -> str:
        mark = "held" if self.survived else "FAILED"
        p = "" if self.p_value is None else f" (run 1 p={self.p_value:.1e})"
        return (f"[{mark}] {self.kind}: {self.subject}{p}"
                f"\n    run 1: {self.first}\n    run 2: {self.second}")


@dataclass
class Reproduction:
    """The comparison of two collections of the same matrix."""

    items: int
    candidates: tuple[str, ...]
    first_items: int = 0                   # items run 1 was originally read over
    dropped: tuple[str, ...] = ()           # items run 1 had that the comparison could not use
    limiting_candidate: str | None = None   # the candidate whose gaps cost the most items
    flips: dict[str, int] = field(default_factory=dict)
    accuracy: dict[str, tuple[float, float]] = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)

    @property
    def dropout(self) -> float:
        return len(self.dropped) / self.first_items if self.first_items else 0.0

    @property
    def dropped_are_clustered(self) -> float:
        """How concentrated the lost items are in the id ordering, from 0 (spread) to 1 (one block).

        Work dispatched in id order and interrupted -- a bearer token expiring is the case that happened
        -- loses a contiguous block, and the resulting subset is biased rather than merely smaller. Items
        lost to per-item pathology are scattered instead. The two need different responses, so the shape
        is measured rather than assumed: the score is the largest run of consecutive lost positions
        divided by the number lost.
        """
        if len(self.dropped) < 2:
            return 0.0
        order = {item: n for n, item in enumerate(sorted(self._all_first, key=_as_int))}
        lost = sorted(order[i] for i in self.dropped if i in order)
        longest = run = 1
        for a, b in zip(lost, lost[1:]):
            run = run + 1 if b == a + 1 else 1
            longest = max(longest, run)
        return longest / len(lost)

    #: Every item run 1 held, kept so `dropped_are_clustered` can place the losses in order.
    _all_first: tuple[str, ...] = ()

    @property
    def expected_failures_by_chance(self) -> float:
        """Roughly how many of these claims would fail with nothing wrong.

        Not a correction -- no threshold is adjusted, because a warning system should err towards
        warning -- but "5 failed" reads differently against "1.6 expected" than it does alone. Each
        ordering claim is counted at its own test size; the floor and frontier claims have no null to
        speak of and are counted at zero.
        """
        return sum(c.p_value for c in self.claims if c.p_value is not None)

    def flip_rate(self, candidate: str) -> tuple[float, float, float]:
        """`(rate, low, high)` for one candidate, the interval at 95%."""
        n = self.items
        k = self.flips[candidate]
        low, high = wilson(k, n)
        return (k / n if n else 0.0, low, high)

    @property
    def pooled_flip_rate(self) -> tuple[float, float, float]:
        k = sum(self.flips.values())
        n = self.items * len(self.candidates)
        low, high = wilson(k, n)
        return (k / n if n else 0.0, low, high)

    @property
    def failed(self) -> list[Claim]:
        return [c for c in self.claims if not c.survived]

    @property
    def held(self) -> list[Claim]:
        return [c for c in self.claims if c.survived]

    def summary(self) -> str:
        """Deliberately phrased as 'has not yet failed', because one repeat is not a variance."""
        rate, low, high = self.pooled_flip_rate
        lines = [
            f"{self.items} items complete in both runs, {len(self.candidates)} candidates.",
            f"run 1 held {self.first_items}; {len(self.dropped)} dropped ({self.dropout:.1%}), "
            f"clustering {self.dropped_are_clustered:.2f}"
            + (f", limited by {self.limiting_candidate}" if self.limiting_candidate else ""),
            f"pooled flip rate {rate:.1%} [{low:.1%}, {high:.1%}].",
            f"{len(self.held)} claims have not yet failed; {len(self.failed)} failed "
            f"({self.expected_failures_by_chance:.1f} expected by chance).",
        ]
        lines += [str(c) for c in self.failed]
        return "\n".join(lines)


def _as_int(item: str) -> int:
    """Item ids sort numerically where they can, so `i10` follows `i9` rather than `i1`."""
    digits = "".join(ch for ch in item if ch.isdigit())
    return int(digits) if digits else 0


def _sign_test(wins: int, losses: int) -> float:
    """Exact two-sided sign test on the discordant pairs, which is McNemar without the approximation.

    Used rather than a chi-square because the discordant counts here are single digits, where the
    approximation is exactly wrong in the direction that manufactures significance.
    """
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(max(wins, losses), n + 1))
    return min(1.0, 2 * tail / 2 ** n)


def _shared_items(first: OutcomeTable, second: OutcomeTable, candidates: list[str]) -> list[str]:
    def complete(t: OutcomeTable, item: str) -> bool:
        row = t.cells.get(item) or {}
        return all((row.get(c) or Cell(UNOBSERVED, None)).state != UNOBSERVED for c in candidates)

    return sorted(i for i in first.cells if i in second.cells
                  and complete(first, i) and complete(second, i))


def compare(first: OutcomeTable, second: OutcomeTable, *, candidates: list[str],
            escalate_to: list[str] | None = None, floors: tuple[float, ...] = (0.85, 0.90, 0.95),
            max_members: int = 3, min_stopped: int = 30, min_coverage: float = 0.5,
            ordering_alpha: float = 0.05,
            prices: dict[str, float] | None = None) -> Reproduction:
    """Compare two collections of the same matrix and return the claims that failed.

    `first` is the run a conclusion was drawn from and `second` is the repeat, which is why the claim
    strings are asymmetric: the point is to check statements already made, not to average two runs.
    """
    def observed(table: OutcomeTable, cand: str) -> int:
        return sum(1 for i in table.cells
                   if (table.cells[i].get(cand) or Cell(UNOBSERVED, None)).state != UNOBSERVED)

    for name, table in (("first", first), ("second", second)):
        # A threshold rather than "at least one observation": a candidate seen on three items passes a
        # presence check and then silently collapses the comparison to three items, and the error shows
        # up as an unexplained item count instead of as the missing coverage it is.
        thin = {c: observed(table, c) for c in candidates
                if observed(table, c) < min_coverage * len(table.cells)}
        if thin:
            raise EvidenceError(
                f"the {name} table covers {thin} of {len(table.cells)} items, under the "
                f"{min_coverage:.0%} floor. Comparing anyway would change the pool between the runs, "
                "and a different pool is a different question."
            )

    items = _shared_items(first, second, candidates)
    if not items:
        raise EvidenceError("no item is complete in both runs, so there is nothing to compare")

    shared = set(items)
    dropped = tuple(sorted((i for i in first.cells if i not in shared), key=_as_int))
    # Which candidate's gaps cost the most items, so a shrunken comparison names its cause.
    limiting = None
    if dropped:
        blame = {c: sum(1 for i in dropped
                        if (second.cells.get(i, {}).get(c) or Cell(UNOBSERVED, None)).state == UNOBSERVED)
                 for c in candidates}
        if any(blame.values()):
            limiting = max(blame, key=lambda c: blame[c])

    rep = Reproduction(items=len(items), candidates=tuple(candidates),
                       first_items=len(first.cells), dropped=dropped,
                       limiting_candidate=limiting, _all_first=tuple(first.cells))

    def solved(t: OutcomeTable, item: str, cand: str) -> bool:
        return (t.cells.get(item, {}).get(cand) or Cell(UNOBSERVED, None)).solved

    for cand in candidates:
        rep.flips[cand] = sum(1 for i in items if solved(first, i, cand) != solved(second, i, cand))
        rep.accuracy[cand] = (
            sum(1 for i in items if solved(first, i, cand)) / len(items),
            sum(1 for i in items if solved(second, i, cand)) / len(items),
        )

    tiers = escalate_to if escalate_to is not None else candidates
    policies = {}
    for label, table in (("first", first), ("second", second)):
        policies[label] = enumerate_policies(
            table, candidates=candidates, escalate_to=tiers, max_members=max_members,
            min_stopped=min_stopped, prices=prices, items=items,
        )

    # Claim 0, computed and reported before everything else: did restricting to the shared items move
    # run 1's own conclusion? Every later claim labels its first column "what run 1 said", but run 1 is
    # re-evaluated on the subset -- so if the subset alone changes that answer, the module is checking
    # the survival of a claim nobody ever made, and a reader has to know that before reading the rest.
    if dropped:
        full_first = enumerate_policies(
            first, candidates=candidates, escalate_to=tiers, max_members=max_members,
            min_stopped=min_stopped, prices=prices,
            items=sorted(first.cells, key=_as_int),
        )
        moved = []
        for floor in floors:
            whole = cheapest_meeting(full_first, accuracy_floor=floor)
            part = cheapest_meeting(policies["first"], accuracy_floor=floor)
            ident = lambda p: None if p is None else (p.members, p.escalate_to)
            if ident(whole) != ident(part):
                moved.append(f"{floor:.0%}")
        rep.claims.append(Claim(
            kind="subset_integrity",
            subject=("run 1's own conclusion is unchanged by restricting to the items the comparison "
                     "can use"),
            first=f"read over all {len(first.cells)} items",
            second=(f"read over the {len(items)} shared items: "
                    + ("unchanged" if not moved
                       else f"the answer moves at the {', '.join(moved)} floor(s)")),
            survived=not moved,
        ))

    # Claim 1: the cheapest policy meeting each floor. This is the claim an owner acts on, so it is
    # checked first and by identity -- the members and the escalation tier -- rather than by cost,
    # because two policies at the same price are still two different things to operate.
    for floor in floors:
        a = cheapest_meeting(policies["first"], accuracy_floor=floor)
        b = cheapest_meeting(policies["second"], accuracy_floor=floor)

        def describe(p: QuorumPolicy | None) -> str:
            if p is None:
                return "no policy reaches this floor"
            return (f"{'+'.join(p.members)} -> {p.escalate_to} "
                    f"({p.accuracy:.1%}, ${p.usd_per_item:.5f})")

        same = (a is not None and b is not None
                and a.members == b.members and a.escalate_to == b.escalate_to)
        rep.claims.append(Claim(
            kind="cheapest_at_floor",
            subject=f"the cheapest policy meeting a {floor:.0%} accuracy floor",
            first=describe(a), second=describe(b), survived=same,
        ))

    # Claim 2: which policies are on the frontier at all. A point that appears in one run and not the
    # other is not a policy anyone should quote, whatever its numbers looked like.
    ids = {label: {(p.members, p.escalate_to) for p in frontier(ps)}
           for label, ps in policies.items()}
    both = ids["first"] & ids["second"]
    only_first = ids["first"] - ids["second"]
    rep.claims.append(Claim(
        kind="frontier_membership",
        subject="the set of policies on the frontier",
        first=f"{len(ids['first'])} points",
        second=f"{len(ids['second'])} points, {len(both)} of them shared, "
               f"{len(only_first)} present only in the first run",
        survived=not only_first,
    ))

    # Claim 3: each single candidate's accuracy ordering against every other. A swap here is what moved
    # the frontier in practice, because a candidate crossing an accuracy floor changes what is cheapest.
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            fa, fb = rep.accuracy[a][0], rep.accuracy[b][0]
            sa, sb = rep.accuracy[a][1], rep.accuracy[b][1]
            # Run 1's own margin has to clear a paired test before "A beats B" is a claim at all.
            # 90.4% against 91.1% over 571 items is two intervals crossing, and with eight candidates
            # there are 28 such pairs -- so without this gate most ordering claims would be flags
            # planted in noise, and their later "reversal" would be noise reversing.
            aw = sum(1 for it in items if solved(first, it, a) and not solved(first, it, b))
            bw = sum(1 for it in items if solved(first, it, b) and not solved(first, it, a))
            p = _sign_test(aw, bw)
            if p > ordering_alpha or fa == fb or sa == sb:
                continue
            rep.claims.append(Claim(
                kind="ordering",
                subject=f"{a} against {b}",
                first=f"{a} {fa:.1%} vs {b} {fb:.1%} ({aw} / {bw} discordant)",
                second=f"{a} {sa:.1%} vs {b} {sb:.1%}",
                survived=(fa > fb) == (sa > sb),
                p_value=p,
            ))

    return rep
