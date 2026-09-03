"""Predict properties of the request, not a routing destination. The optimiser does the rest.

The distinction is the whole point of this module, and getting it wrong cost this project several rounds.

**What this does not do.** It does not predict "which candidate should serve this" or "will candidate A solve
this". Those couple the model to the pool: nine candidates means nine functions to learn from the same items,
and every new candidate needs its own labels before it can be routed to at all. Fitted that way on 366 items
here, per-candidate heads reached a within-candidate AUC of 0.58 and lost to a policy built on one categorical
feature at every budget tried.

**What it does.** It predicts a candidate-independent *description* of the request -- how hard it looks, and what
kind of thing it is. One function, learned from every item at once rather than divided nine ways. The ledger
already knows how each candidate performs as a function of that description, because that is a measurement
rather than a prediction. So:

    encoder    ->  description (difficulty, tag)          <- learned, candidate-independent
    ledger     ->  solve rate per candidate per bucket    <- measured, not predicted
    optimiser  ->  argmax over candidates of p - lam*cost <- the actual optimisation

Three properties follow, and the third is the one that matters operationally.

The description is one regression problem rather than N classification problems, so every item contributes to
the only function being learned. **Adding a candidate needs no retraining at all** -- it needs the candidate
measured on the calibration fold, which was always required, and its profile appears in the lookup. And a
description is legible: "this looks hard and it is about law" can be read, argued with and audited in a way that
a nine-dimensional probability vector cannot.

The catch, stated because it is real: the lookup assumes candidates differ *as a function of the description*.
Where a candidate's advantage is invisible in the description, this cannot see it -- and on this corpus the
items only one candidate solves are 27 of 1,187, so that blind spot is small but not empty.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from tierbook.evidence import EvidenceError
from tierbook.outcomes import OutcomeTable


def _np():
    try:
        import numpy as np
    except ImportError as e:  # pragma: no cover
        raise EvidenceError("describing requests needs numpy: pip install 'tierbook[predict]'") from e
    return np


@dataclass
class Description:
    """A request's predicted properties, and nothing about where it should go."""

    difficulty: float                 # predicted fraction of candidates that would solve it, in [0, 1]
    tag: str | None = None            # a declared category, if the caller has one
    extras: dict = field(default_factory=dict)


@dataclass
class Describer:
    """Predicts difficulty from frozen features. Candidate-independent by construction.

    `difficulty` is defined as the fraction of the measured candidate pool that solved the item, which makes it a
    property of the item rather than of any candidate. It is a regression rather than a classification because
    the quantity is ordered and the optimiser wants its value, not its bucket.
    """

    embed_id: str
    dim: int
    weights: object = None            # (dim + 1,)
    l2_chosen: float = 1.0
    cv_r2: float | None = None
    fitted_on_items: list[str] = field(default_factory=list)

    def difficulty_of(self, z) -> float:
        np = _np()
        raw = float(np.append(np.asarray(z, dtype=float), 1.0) @ self.weights)
        return min(1.0, max(0.0, raw))

    def describe(self, z, tag: str | None = None) -> Description:
        return Description(difficulty=self.difficulty_of(z), tag=tag)


def fit_describer(table: OutcomeTable, embeddings: dict, fit_items: list[str], *, embed_id: str,
                  may_train_on: bool | None = None, l2_grid: tuple[float, ...] = (0.1, 1.0, 10.0, 100.0),
                  folds: int = 5, candidates: list[str] | None = None, seed: int = 2) -> Describer:
    """Fit the difficulty regression, choosing the penalty inside the fitting slice.

    The target is the fraction of candidates that solved the item. Every item contributes one row, and every
    candidate's outcome contributes to that row -- which is the label-efficiency argument for describing the
    request instead of predicting the pool.
    """
    np = _np()
    if not may_train_on:
        raise EvidenceError(
            f"fitting a describer on this corpus is training on it, and `may_train_on` is {may_train_on!r}. "
            "Permission to evaluate is not permission to train, and the licence identifier does not say which."
        )
    cands = candidates or table.tiers
    rows = [i for i in fit_items if i in embeddings and table.cells.get(i)]
    if len(rows) < folds * 4:
        raise EvidenceError(f"{len(rows)} usable items is too few for {folds}-fold cross-validation")
    X = np.stack([np.append(np.asarray(embeddings[i], dtype=float), 1.0) for i in rows])
    y = np.array([
        sum(1 for c in cands if table.cells[i].get(c) and table.cells[i][c].solved)
        / max(1, sum(1 for c in cands if table.cells[i].get(c) and table.cells[i][c].attempted))
        for i in rows
    ])
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(rows))

    def solve(Xa, ya, l2):
        return np.linalg.solve(Xa.T @ Xa + l2 * np.eye(Xa.shape[1]), Xa.T @ ya)

    best_l2, best_r2 = l2_grid[0], None
    for l2 in l2_grid:
        scores = []
        for f in range(folds):
            te = order[f::folds]
            tr = np.setdiff1d(order, te)
            w = solve(X[tr], y[tr], l2)
            pred = X[te] @ w
            ss = float(((y[te] - pred) ** 2).sum())
            tot = float(((y[te] - y[tr].mean()) ** 2).sum())
            scores.append(1 - ss / tot if tot > 0 else 0.0)
        m = sum(scores) / len(scores)
        if best_r2 is None or m > best_r2:
            best_l2, best_r2 = l2, m
    return Describer(embed_id=embed_id, dim=X.shape[1] - 1, weights=solve(X, y, best_l2),
                     l2_chosen=best_l2, cv_r2=round(best_r2, 4), fitted_on_items=list(rows))


@dataclass
class Profiles:
    """Measured solve rate per candidate as a function of the description. Measured, never predicted.

    This is the piece that makes adding a candidate free of retraining: a new candidate needs a row here, and a
    row here is a measurement on the calibration fold, which was always required of it.
    """

    edges: tuple[float, ...]
    rate: dict = field(default_factory=dict)          # candidate -> [rate per bucket]
    support: dict = field(default_factory=dict)       # candidate -> [n per bucket]
    fallback: dict = field(default_factory=dict)      # candidate -> overall rate
    min_support: int = 15

    def bucket_of(self, difficulty: float) -> int:
        for k, e in enumerate(self.edges):
            if difficulty < e:
                return k
        return len(self.edges)

    def probability(self, candidate: str, description: Description) -> float:
        """The measured rate for this candidate in this difficulty bucket, or its overall rate.

        Falls back on thin support rather than trusting a bucket with four observations in it, because a rate
        estimated from four items is noise and the optimiser consumes the value rather than the ordering.
        """
        b = self.bucket_of(description.difficulty)
        rates = self.rate.get(candidate)
        if rates is None:
            raise EvidenceError(
                f"{candidate!r} has no measured profile. A candidate with no measurement cannot be routed to, "
                "and a shared model's guess about it is not a measurement."
            )
        if self.support.get(candidate, [])[b] < self.min_support:
            return self.fallback[candidate]
        return rates[b]


def fit_profiles(table: OutcomeTable, describer: Describer, embeddings: dict, items: list[str], *,
                 buckets: int = 5, candidates: list[str] | None = None,
                 min_support: int = 15) -> Profiles:
    """Measure each candidate's solve rate against predicted difficulty, on the calibration fold.

    Bucketed by quantile of *predicted* difficulty rather than of the true fraction, because the online path
    only ever sees the prediction. Bucketing on truth would flatter every profile by giving it a cleaner axis
    than production has.
    """
    np = _np()
    cands = candidates or table.tiers
    usable = [i for i in items if i in embeddings and table.cells.get(i)]
    d = np.array([describer.difficulty_of(embeddings[i]) for i in usable])
    qs = [float(np.quantile(d, k / buckets)) for k in range(1, buckets)]
    p = Profiles(edges=tuple(qs), min_support=min_support)
    for c in cands:
        rates, support = [], []
        for b in range(buckets):
            sel = [i for i, dv in zip(usable, d)
                   if p.bucket_of(dv) == b and table.cells[i].get(c) and table.cells[i][c].attempted]
            n = len(sel)
            support.append(n)
            rates.append(sum(1 for i in sel if table.cells[i][c].solved) / n if n else 0.0)
        obs = [i for i in usable if table.cells[i].get(c) and table.cells[i][c].attempted]
        p.rate[c] = rates
        p.support[c] = support
        p.fallback[c] = (sum(1 for i in obs if table.cells[i][c].solved) / len(obs)) if obs else 0.0
    return p


def probabilities_from(describer: Describer, profiles: Profiles, embeddings: dict,
                       tag_feature: str | None = None):
    """A `probabilities(item_id, features)` callable for the optimiser, built from prediction plus measurement.

    The prediction is one number. Everything candidate-specific comes from the measured profile, so this is the
    seam that keeps the encoder independent of the pool.
    """
    def probabilities(item_id: str, features: dict) -> dict:
        z = embeddings.get(item_id)
        if z is None:
            return {}
        desc = describer.describe(z, tag=(features or {}).get(tag_feature) if tag_feature else None)
        return {c: profiles.probability(c, desc) for c in profiles.rate}
    return probabilities
