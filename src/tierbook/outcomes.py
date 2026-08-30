"""The potential outcome table: what every tier did on every item, so a policy can be chosen over it.

A tier record answers "how did this tier do on this family". That is enough to pick one tier per family and
not enough for anything else. This module is the join across tiers -- for each item, what each tier would have
returned and what it would have cost -- which is the object a policy is chosen over.

The name is borrowed deliberately. In causal inference a potential outcome is what *would* have happened under
an action not taken, and that is exactly what a benchmark run gives you for free: every tier was run on every
item, so for each item the counterfactual "what if this had gone to the cheap tier" is observed rather than
estimated. A production log does not have this property, which is why calibration runs are worth their cost
and why replaying a logged request through every tier is the thing that turns a log into training data.

What this makes computable, none of which a per-family summary can support:

  * **the oracle**, meaning the cheapest tier that actually solved each item. On the corpus in this repository
    that is +27 correct AND 67% cheaper than always sending everything to the strongest tier -- so on that
    family routing is not a quality-for-money trade at all, and the belief that it can only lower cost was
    wrong. A reachable policy got part of the way there: +2.00 points of solve rate over the *cheapest* tier at
    two tenths of one percent more money, out of fold.
  * **the floor**, meaning items no tier solved. No router reaches them, and reporting progress against the
    oracle without subtracting the floor overstates what is left to win.
  * **the shape of the win.** On the same corpus 299 of 699 items were solved by all eight priced tiers, 13 by
    exactly one, and 32 by none. Those three numbers say the money is in the easy items, the quality headroom is
    thin and concentrated, and 4.6 points of it is unreachable -- which decides what a predictor has to be good
    at and what it can never fix.
  * **a frontier**, so the owner picks the quality floor and the cost ceiling instead of a weighting nobody
    can check.

Two refusals live here, both for reasons measured in this repository:

  * **a tier with no price is not free.** Excluding a tier whose cost cannot be computed is honest; treating
    its cost as zero makes it win every comparison. That happened here once, and it produced a 3.0x saving
    that rested on treating a model as costless.
  * **items are joined on a suite manifest, not on an id.** A reused item id whose content changed is
    invisible to an id-only join, which is the same defect the evidence loader already refuses.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from tierbook.evidence import INCORRECT, SOLVED, UNOBSERVED, Evidence, EvidenceError

#: What a policy may do with a request. `REFUSE` is a first-class action rather than the absence of one: if no
#: arrangement satisfies the constraints its owner stated, refusing is the correct answer, and making it an
#: action means the optimiser can return it instead of the caller having to notice that nothing qualified.
SEND = "send"
REFUSE = "refuse"


@dataclass(frozen=True)
class Cell:
    """One tier's observed outcome on one item, and what it cost to get it."""

    state: str
    usd: float | None                     # None means unpriced, which is NOT zero
    seconds: float | None = None

    @property
    def solved(self) -> bool:
        return self.state == SOLVED

    @property
    def attempted(self) -> bool:
        return self.state in (SOLVED, INCORRECT)


@dataclass
class OutcomeTable:
    """Items x tiers, with the features an online router can actually see at request time.

    `features` holds only what is available before a tier is called -- a category, an estimated input length, a
    classifier label. Deliberately not the outcome, the output length, or anything else known only afterwards:
    a table that mixes the two trains a predictor on information it will not have, and the resulting number is
    an upper bound masquerading as a result.
    """

    suite: str
    manifest_digest: str
    cells: dict[str, dict[str, Cell]] = field(default_factory=dict)   # item_id -> tier -> Cell
    features: dict[str, dict] = field(default_factory=dict)          # item_id -> feature dict

    # --- construction -----------------------------------------------------------------------------

    @classmethod
    def from_evidence(cls, evidence: list[Evidence], *, cost_per_item: dict[str, dict[str, float]] | None = None,
                      features: dict[str, dict] | None = None) -> OutcomeTable:
        """Join evidence artifacts into one table, refusing to join across suites.

        The manifest check is the same one `paired()` makes and for the same reason: joining on item ids alone
        cannot see a reused id whose content changed, so it is checked before any ids are compared.
        """
        if not evidence:
            raise EvidenceError("no evidence to join, so there is no table")
        digests = {e.suite_manifest_digest for e in evidence}
        if len(digests) > 1:
            raise EvidenceError(
                f"the evidence carries {len(digests)} different suite manifest digests {sorted(digests)}. "
                "Joining them by item id would compare different suites under one name, which is the failure "
                "a manifest digest exists to catch."
            )
        subjects = [e.subject for e in evidence]
        if len(set(subjects)) != len(subjects):
            raise EvidenceError(f"two artifacts claim the same subject: {sorted(subjects)}")
        table = cls(suite=evidence[0].family, manifest_digest=evidence[0].suite_manifest_digest)
        costs = cost_per_item or {}
        for e in evidence:
            for item_id, (state, _reason) in e.verdicts.items():
                usd = (costs.get(e.subject) or {}).get(item_id)
                table.cells.setdefault(item_id, {})[e.subject] = Cell(state=state, usd=usd)
        table.features = dict(features or {})
        return table

    # --- shape ------------------------------------------------------------------------------------

    @property
    def tiers(self) -> list[str]:
        return sorted({t for row in self.cells.values() for t in row})

    @property
    def items(self) -> list[str]:
        return sorted(self.cells)

    def complete_items(self, items: list[str] | None = None) -> list[str]:
        """Items every tier attempted. A policy comparison outside this set is not paired.

        Kept separate from `items` rather than filtering on construction, because the count of incomplete items
        is itself worth reporting: a table that is 40% incomplete is describing a different population from the
        one its owner thinks it is.
        """
        ts = set(self.tiers)
        return [i for i in (items or self.items) if set(self.cells[i]) == ts
                and all(self.cells[i][t].attempted for t in ts)]

    def priced_tiers(self) -> tuple[list[str], list[str]]:
        """Which tiers have a cost on at least one item, and which have none at all.

        A tier with no price anywhere cannot take part in a cost comparison and is named rather than charged as
        zero -- doing the latter once produced a headline saving here that rested on treating a model as free.

        A tier missing a price on *some* items is a different case and is handled by `priced_items`, not by
        exclusion. Dropping a whole tier because six of six hundred and ninety-nine rows lost their token
        counts would throw away a good tier to punish a gap in the instrument, and the real corpus has exactly
        that shape.
        """
        priced, unpriced = [], []
        for t in self.tiers:
            vals = [self.cells[i][t].usd for i in self.items if t in self.cells[i]]
            (priced if any(v is not None for v in vals) else unpriced).append(t)
        return priced, unpriced

    def priced_items(self, tiers: list[str] | None = None,
                     items: list[str] | None = None) -> tuple[list[str], list[str]]:
        """Items where every tier under comparison has a cost, and the ones excluded because one does not.

        Complete cases, for the same reason a paired comparison uses them: a total summed over a different set
        of items per tier is not a comparison. The excluded list is returned rather than logged so a caller can
        report how much of the population the cost figure covers -- on the real corpus this is 6 items of 699,
        all on one tier, and hiding that would make the figure look like it covered everything.
        """
        ts = tiers or self.tiers
        keep, drop = [], []
        for i in (items or self.items):
            row = self.cells[i]
            (keep if all(t in row and row[t].usd is not None for t in ts) else drop).append(i)
        return keep, drop

    # --- what the table says ----------------------------------------------------------------------

    def solved_by(self, tier: str, items: list[str] | None = None) -> int:
        return sum(1 for i in (items or self.items) if (self.cells[i].get(tier) or Cell(UNOBSERVED, None)).solved)

    def spend_of(self, tier: str, items: list[str] | None = None) -> float | None:
        total = 0.0
        for i in (items or self.items):
            c = self.cells[i].get(tier)
            if c is None or c.usd is None:
                return None
            total += c.usd
        return total

    def any_correct(self, items: list[str] | None = None, tiers: list[str] | None = None) -> int:
        ts = tiers or self.tiers
        return sum(1 for i in (items or self.items) if any((self.cells[i].get(t) or Cell(UNOBSERVED, None)).solved
                                                           for t in ts))

    def floor(self, items: list[str] | None = None, tiers: list[str] | None = None) -> list[str]:
        """Items no tier solved. Nothing routes around these, so they are subtracted before claiming headroom."""
        ts = tiers or self.tiers
        return [i for i in (items or self.items)
                if not any((self.cells[i].get(t) or Cell(UNOBSERVED, None)).solved for t in ts)]

    def solver_count_histogram(self, items: list[str] | None = None,
                               tiers: list[str] | None = None) -> dict[int, int]:
        """How many tiers solved each item, bucketed. This is the difficulty axis the labels actually have.

        Reported because it decides what a predictor has to be good at, in a way an average cannot show. An
        item every tier solves needs no prediction, only the cheapest tier; an item one tier solves needs the
        predictor to pick that one out of many, and is where a prompt-only predictor is weakest.
        """
        ts = tiers or self.tiers
        out: dict[int, int] = {}
        for i in (items or self.items):
            n = sum(1 for t in ts if (self.cells[i].get(t) or Cell(UNOBSERVED, None)).solved)
            out[n] = out.get(n, 0) + 1
        return out

    def oracle_cheapest(self, items: list[str] | None = None,
                        tiers: list[str] | None = None) -> tuple[int, float, dict[str, str]]:
        """The unreachable upper bound: for each item, the cheapest tier that actually solved it.

        Unreachable on purpose, and reported as a diagnostic rather than used as an objective. Using it as the
        thing to maximise would smuggle in the assumption that which tier solves an item is knowable in
        advance, which is the whole question a predictor exists to answer badly.
        """
        ts = tiers or self.tiers
        chosen: dict[str, str] = {}
        solved = 0
        spend = 0.0
        for i in (items or self.items):
            solvers = [(self.cells[i][t].usd, t) for t in ts
                       if t in self.cells[i] and self.cells[i][t].solved and self.cells[i][t].usd is not None]
            if solvers:
                usd, t = min(solvers)
                chosen[i] = t
                solved += 1
                spend += usd
            else:
                # Nobody solved it, so nothing is saved by sending it anywhere clever. Charged at the cheapest
                # attempt, because the request still costs something even when it cannot succeed.
                priced = [(self.cells[i][t].usd, t) for t in ts
                          if t in self.cells[i] and self.cells[i][t].usd is not None]
                if priced:
                    usd, t = min(priced)
                    chosen[i] = t
                    spend += usd
        return solved, spend, chosen

    # --- evaluating a policy ----------------------------------------------------------------------

    def evaluate(self, pick, items: list[str] | None = None) -> dict:
        """Run a policy over the table. `pick(item_id, features) -> tier | REFUSE`.

        Returns solve count, spend, refusal count and the population, because a policy that refuses half the
        traffic and scores well on the rest has not been compared with one that answered everything.
        """
        items = items or self.items
        solved = refused = 0
        spend = 0.0
        unpriced = 0
        for i in items:
            choice = pick(i, self.features.get(i, {}))
            if choice == REFUSE or choice is None:
                refused += 1
                continue
            c = self.cells[i].get(choice)
            if c is None:
                raise EvidenceError(f"policy chose {choice!r} for {i!r}, which has no observed outcome there")
            if c.solved:
                solved += 1
            if c.usd is None:
                unpriced += 1
            else:
                spend += c.usd
        answered = len(items) - refused
        return {
            "items": len(items), "answered": answered, "refused": refused,
            "solved": solved, "spend_usd": round(spend, 6),
            "solve_rate": (solved / answered) if answered else None,
            "usd_per_answered": (spend / answered) if answered else None,
            "unpriced_choices": unpriced,
        }

    def frontier(self, policies: dict[str, object], items: list[str] | None = None) -> list[dict]:
        """Evaluate several policies and mark the ones nothing else dominates.

        A frontier rather than a score, because collapsing quality and cost into one number chooses an exchange
        rate between a defect and a dollar on the owner's behalf. Nobody outside can state that rate -- at $1 a
        defect a cheap tier ships and at $10,000 no affordable sample can certify one -- so the honest output
        is the set of options that are not strictly worse than another, and the owner picks.
        """
        rows = []
        for name, pick in policies.items():
            r = self.evaluate(pick, items)
            r["policy"] = name
            rows.append(r)
        for r in rows:
            r["dominated_by"] = [
                o["policy"] for o in rows
                if o is not r and (o["solved"] >= r["solved"]) and (o["spend_usd"] <= r["spend_usd"])
                and (o["solved"] > r["solved"] or o["spend_usd"] < r["spend_usd"])
            ]
            r["on_frontier"] = not r["dominated_by"]
        return sorted(rows, key=lambda r: (r["spend_usd"], -r["solved"]))

    def report(self, items: list[str] | None = None, tiers: list[str] | None = None) -> dict:
        """Everything the table says about itself, for a reader deciding whether to trust a policy built on it."""
        items = items or self.items
        ts = tiers or self.tiers
        priced, unpriced = self.priced_tiers()
        cost_tiers = [t for t in ts if t in priced]
        # Complete cases for cost: a spend total summed over a different set of items per tier is not a
        # comparison. The excluded count travels in the report so the figure cannot look like it covered
        # everything -- on the real corpus it is 6 items of 699, all on one tier.
        cost_items, cost_excluded = self.priced_items(cost_tiers, items)
        best = max(ts, key=lambda t: self.solved_by(t, items)) if ts else None
        oracle_solved, oracle_spend, _ = self.oracle_cheapest(cost_items, cost_tiers)
        return {
            "suite": self.suite,
            "manifest_digest": self.manifest_digest,
            "items": len(items),
            "complete_items": len(self.complete_items(items)),
            "tiers": ts,
            "priced_tiers": priced,
            "unpriced_tiers": unpriced,
            "floor_items": len(self.floor(items, ts)),
            "solver_count_histogram": self.solver_count_histogram(items, ts),
            "cost_items": len(cost_items),
            "cost_items_excluded": len(cost_excluded),
            "best_single": {"tier": best, "solved": self.solved_by(best, items) if best else None,
                            "spend_usd": self.spend_of(best, cost_items) if best else None},
            "oracle_cheapest": {"solved": oracle_solved, "spend_usd": round(oracle_spend, 6)},
            "headroom_over_best_single": (
                None if best is None else round((oracle_solved - self.solved_by(best, items)) / len(items), 4)),
            "reading": (
                "The floor is items no tier solved, so headroom is measured after subtracting it. The "
                "histogram is the difficulty axis: items every tier solves need the cheapest tier and no "
                "prediction, and items one tier solves need a predictor to find that one -- so a table whose "
                "mass is at the top is a cost problem, and one whose mass is in the middle is a routing "
                "problem. A tier with no price anywhere is excluded and listed, never charged as zero; items "
                "where one tier lost its token counts are excluded from the cost figures only, and counted in "
                "`cost_items_excluded`, so a spend total is never summed over a different set per tier."
            ),
        }
