"""Stop spending on an item nobody will get right, without ever calling a prediction a verdict.

On one corpus, 4.3% of items were solved by no candidate and carried **54.8%** of a cheapest-first
bill: the cascade walked the entire ladder on every one of them and paid the dearest tier last. That
is the single largest line on the page, so it looks like the obvious thing to detect.

It is not a detection problem, and the reason is measured. The cheap tier's own prefill uncertainty
predicts "every candidate solves this" at 0.83 AUC and "no candidate solves this" at **0.51** — a
coin. The asymmetry has a mechanism: "everyone can do it" is one common property, while "nobody can"
is a confluence of unrelated ones — an ambiguous specification, a missing dependency, a verifier that
cannot run, a search too long for the budget, a blind spot the whole panel shares — and it is a
logical AND over the candidate set, so it moves when the set moves. A candidate's self-doubt can say
"I do not know"; it carries no information about whether the others know.

## So the tail is separated first, and only the remainder is a routing problem

The 51 items nobody solved on that corpus were four different things:

| what it was | items | what removes it |
|---|---|---|
| the answer key is wrong | 22 | an audit, triggered by unanimous disagreement with the key |
| the same question appears twice | 10 redundant | deduplication on normalised text |
| the question has two correct answers | 1 | widening the key |
| genuinely unanswerable by this pool | 29 | an abstention rule |

Three of those four are repairs to the corpus, not policy. `broken_key_candidates` and
`duplicate_groups` here are the free detectors for the first two; they need no model and no extra
call, only the matrix.

## And the remainder stops on evidence, not on a prediction

`sequential_stop` walks the tiers a policy would walk and stops when the expected value of continuing
falls below the price of the next call. The evidence it updates on is **the failures that have already
happened**, which is why it needs no new signal: each tier that fails is an observation that the item
is harder than that tier, and `p_next` is supplied by the item model the mechanism already fits.

Two disciplines are load-bearing and both are enforced here rather than documented:

  * **it stops on a bound, not a point estimate.** `p_next` arrives with an upper confidence bound and
    the stop test uses the bound, so an uncertain "probably hopeless" keeps spending.
  * **it reports what stopping cost.** `lost` counts the items in the stopped set that some remaining
    tier would in fact have solved. A rule whose lost-success rate exceeds the cap the owner set is
    not shipped -- it runs in shadow mode, and `StopReport.within_cap` is what a caller checks before
    letting it gate anything.

Nothing here decides an answer is correct. The output is "stop paying and return unverified", which is
a spending decision; the verdict stays with the verifier.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from tierbook.evidence import UNOBSERVED
from tierbook.outcomes import Cell, OutcomeTable


def _cell(table: OutcomeTable, item: str, tier: str) -> Cell:
    return table.cells.get(item, {}).get(tier) or Cell(UNOBSERVED, None)


# --- free repairs to the corpus, before any policy runs -------------------------------------------

def broken_key_candidates(table: OutcomeTable, tiers: list[str], *,
                          items: list[str] | None = None) -> list[str]:
    """Items where every tier gave the same answer and the verifier rejected all of them.

    Measured: this fired on exactly 19 items over 1,187 and all 19 had a wrong answer key, with no
    false positives. Relaxing it to "all but one agreed" dropped the hit rate to 3 of 9, so the
    unanimity is doing the work -- one dissenter no longer distinguishes "the key is wrong" from "the
    question is hard".

    It does not treat a prediction as evidence of correctness. The output is a list of items for a
    human to read, and on the corpus above a human confirmed every one.

    Generalises past this corpus unchanged: unanimous agreement against a verifier's rejection is
    evidence about the **verifier**, so a routing mechanism that measures a candidate matrix emits a
    data-quality report as a byproduct.
    """
    out = []
    for item in (items if items is not None else table.items):
        answers = [_cell(table, item, t).answer for t in tiers]
        if any(a is None for a in answers):
            continue
        if len(set(answers)) != 1:
            continue
        if any(_cell(table, item, t).solved for t in tiers):
            continue
        out.append(item)
    return out


def _normalise(text: str) -> str:
    """Case, whitespace and unicode form folded away; nothing else.

    Deliberately not stemming or stopword removal: this is looking for the same question entered
    twice, not for questions about the same topic, and a looser normaliser merges items that are
    genuinely different and quietly shrinks the corpus.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", folded)).strip()


def duplicate_groups(texts: dict[str, str]) -> list[list[str]]:
    """Groups of item ids whose text is the same after normalisation, largest group first.

    A duplicate inflates two things at once: the count of items in whatever bucket it lands in, and
    the share of the bill attributed to that bucket. On the corpus above one eminent-domain question
    appeared three times, was unsolved in every copy, and so contributed three items and three items'
    worth of spend to the "nobody solves it" tail on the strength of one bad answer key.
    """
    by_text: dict[str, list[str]] = defaultdict(list)
    for item, text in texts.items():
        by_text[_normalise(text)].append(item)
    groups = [sorted(ids) for ids in by_text.values() if len(ids) > 1]
    return sorted(groups, key=lambda g: (-len(g), g))


# --- the remainder: stop when continuing stops paying ---------------------------------------------

@dataclass
class StopReport:
    """What a stopping rule did, and what it cost to do it."""

    stopped: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    calls_saved: int = 0
    usd_saved: float = 0.0
    lost: list[str] = field(default_factory=list)   # stopped, but a remaining tier would have solved it

    @property
    def lost_rate(self) -> float:
        """Of the items stopped, the share that were in fact solvable by a tier not called."""
        return len(self.lost) / len(self.stopped) if self.stopped else 0.0

    def within_cap(self, cap: float) -> bool:
        """Whether the rule may gate real traffic, against a cap the owner set in advance.

        A rule outside its cap is not "nearly ready": it is a rule that abandons work someone paid for
        more often than the owner agreed to, and it belongs in shadow mode until the bound moves.
        """
        return self.lost_rate <= cap


def sequential_stop(table: OutcomeTable, order: list[str], *, p_next, value_of_success: float,
                    prices: dict[str, float] | None = None,
                    items: list[str] | None = None) -> StopReport:
    """Walk `order`, stopping when the bound on continuing no longer pays for the next call.

    `p_next(item, tier, failures)` returns an **upper** confidence bound on the probability that
    `tier` solves `item`, given the tiers that have already failed. The bound rather than the point
    estimate is what makes the rule conservative in the right direction: an item the model is unsure
    about keeps spending, and only a confidently hopeless one is abandoned.

    `value_of_success` puts the two sides of the comparison in the same units. Without it there is no
    stopping rule at all, only a probability nobody can act on -- the sentence an owner can say is
    "one more correct answer is worth this much to me", and that is exactly this argument.
    """
    report = StopReport()
    subject = list(items if items is not None else table.items)

    def price(item: str, tier: str) -> float:
        if prices is not None and tier in prices:
            return prices[tier]
        usd = _cell(table, item, tier).usd
        # An unpriced tier is treated as free ONLY here, and it is the conservative direction: a call
        # that looks free is never skipped, so the rule cannot abandon an item on the strength of a
        # cost it does not know.
        return 0.0 if usd is None else usd

    for item in subject:
        failures: list[str] = []
        solved = False
        stopped_at = None
        for idx, tier in enumerate(order):
            bound = p_next(item, tier, tuple(failures))
            if bound * value_of_success < price(item, tier):
                stopped_at = idx
                break
            if _cell(table, item, tier).solved:
                solved = True
                break
            failures.append(tier)

        if stopped_at is None:
            report.completed.append(item)
            continue

        report.stopped.append(item)
        # What stopping saved is what the cascade WOULD have spent, which is the remaining tiers up to
        # and including the first that solves -- not all of them. Counting all of them credits the rule
        # with calls the cascade was never going to make, and on the corpus here that inflated the
        # reported saving past 100% of the entire bill, which is how the error announced itself.
        remaining = order[stopped_at:]
        would_call: list[str] = []
        for tier in remaining:
            would_call.append(tier)
            if _cell(table, item, tier).solved:
                break
        report.calls_saved += len(would_call)
        report.usd_saved += sum(price(item, t) for t in would_call)
        if not solved and any(_cell(table, item, t).solved for t in remaining):
            report.lost.append(item)
    return report
