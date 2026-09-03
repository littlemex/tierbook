"""A learned router: predict each candidate's success probability from the request, then let the optimiser choose.

This is the part that learns, and it is deliberately the only part. Everything it produces is a *proposal*: the
probabilities feed the constrained optimiser, and nothing here can promote an entry, accept an answer, or change
a table. A prediction is not evidence.

## Why this shape

**Per-candidate marginal probabilities, not a single "best tier" label.** Candidates are not mutually exclusive
-- on the corpus here 299 of 699 items were solved by all eight priced tiers -- so a softmax over tiers is
structurally wrong. A single label also throws away the cost information the optimiser needs and buries the
threshold inside the model, so a price change would require retraining.

**Candidate-conditioned, not a fixed bank of heads.** The score for candidate `a` is
`f([z, e_a, z * (W e_a)])` where `z` is the frozen request embedding and `e_a` is a learned embedding of the
candidate. Removing a candidate needs no retraining at all; adding one reuses the shared encoder and head and
needs only that candidate's own labels. A fixed eight-output head has to be rebuilt whenever the pool moves,
and the pool moved twice during this project.

**Plain BCE, and explicitly not focal loss or label smoothing.** Both improve classification accuracy and
distort the probability *values*, and the values are what a cost-constrained choice consumes. Calibration is
done afterwards, per candidate, by temperature scaling on a slice never used for fitting.

**Price is not a feature.** If price entered the success head, a price change would alter predicted success,
which is nonsense. Cost enters once, in the optimiser.

**Missing observations are masked, never imputed.** A candidate that was not run on an item contributes no
gradient for that item. Filling it with 0.5, or with the model's own guess, would promote a prediction to a
label -- the one thing this project refuses everywhere else.

## What is deliberately absent

No fine-tuning of the encoder. The embeddings come in frozen and cached, because on 1,187 distinct prompts a
560M-parameter encoder will memorise rather than generalise, and because the published encoder routers that
succeeded used ten thousand to a hundred thousand distinct prompts. Fine-tuning is a later decision with a
stated condition, not a starting point.

Numpy is an optional dependency, imported here and nowhere else. The online routing path stays a dictionary
lookup over a compiled table with no dependencies at all -- training is not the online path, and the package's
promise of an unbreakable serving surface should not be spent on a training convenience.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from tierbook.evidence import EvidenceError
from tierbook.outcomes import REFUSE, OutcomeTable


def _np():
    try:
        import numpy as np
    except ImportError as e:  # pragma: no cover - the message is the product
        raise EvidenceError(
            "training a predictor needs numpy, which is an optional extra: pip install 'tierbook[predict]'. "
            "It is optional on purpose -- the online routing path is a dictionary lookup over a compiled table "
            "and has no dependencies, and a training convenience should not be charged to the serving surface."
        ) from e
    return np


@dataclass
class Predictor:
    """A trained candidate-conditioned success-probability model, plus what it was fitted on.

    Carries its provenance because a probability with no attribution cannot be audited: which items it saw,
    which candidates it knows, which embedding produced `z`, and what the temperature per candidate is.
    """

    candidates: list[str]
    embed_id: str
    dim: int
    # parameters
    # The logit decomposes into three terms that answer different questions, and keeping them apart is what
    # makes the third measurable:
    #
    #     logit(i, a) = bias_cand[a] + g(z_i) + h(z_i, a)
    #
    # `bias_cand` is the candidate's base rate. `g` is shared difficulty -- it moves every candidate the same
    # way, so it says "this item is hard" and nothing about which candidate to send it to. `h` is
    # candidate-specific affinity, and it is the only term that can change the *ranking* between candidates on
    # a given item.
    #
    # Routing needs `h`. A model that learns `bias` and `g` perfectly still has nothing to route with, because
    # a threshold on a quantity that shifts all candidates together picks the same candidate every time. The
    # first version of this lumped `g` and `h` into one bilinear term, so there was no way to ask whether the
    # part that matters was earning its place. `ablate_affinity` asks that directly.
    bias_cand: object = None         # (n_candidates,)
    w_difficulty: object = None       # (dim,) -- g(z) = z . w_difficulty
    w_shared: object = None           # (dim, hidden) -- shared projection feeding h
    w_cand: object = None             # (n_candidates, hidden) -- per-candidate direction, h = (z W) . e_a
    use_affinity: bool = True         # False fits bias + g only, which is the ablation
    temperature: dict = field(default_factory=dict)
    fitted_on_items: list[str] = field(default_factory=list)
    calibrated_on_items: list[str] = field(default_factory=list)
    history: list = field(default_factory=list)

    # --- forward ----------------------------------------------------------------------------------

    def _difficulty(self, z) -> float:
        return float(z @ self.w_difficulty)

    def _affinity(self, z, ci: int) -> float:
        if not self.use_affinity:
            return 0.0
        return float((z @ self.w_shared) @ self.w_cand[ci])

    def _request_term(self, z, ci: int) -> float:
        """The part of the logit that depends on the request. Separated from the candidate bias on purpose.

        The first version of this put a per-candidate bias inside the same linear head as the request features.
        The head then explained each candidate's base rate with the bias, the gradient on the request weights
        went to nothing, and the fitted probabilities spanned 0.006 across 699 items -- flat enough that every
        cost threshold collapsed to a single candidate. The signal was in the features the whole time: the same
        embeddings scored AUC 0.58 to 0.66 per candidate under cross-validated ridge discriminants.

        So the bias is fitted first and held out of this term, and only the residual is left for the request to
        explain. A candidate's average is not something the request should have to predict.
        """
        return self._difficulty(z) + self._affinity(z, ci)

    def raw_logit(self, z, candidate: str) -> float:
        if candidate not in self.candidates:
            raise EvidenceError(
                f"{candidate!r} was not among the candidates this predictor was fitted on "
                f"({self.candidates}). A shared encoder will happily emit a number for an unseen candidate, "
                "and that number is not evidence about it -- measure the candidate and refit."
            )
        ci = self.candidates.index(candidate)
        return float(self.bias_cand[ci]) + self._request_term(z, ci)

    def probability(self, z, candidate: str) -> float:
        """Calibrated success probability. Temperature is applied per candidate.

        Per candidate rather than globally because the candidates differ in how confidently the head separates
        them, and a single temperature fitted across all of them is right on average and wrong for each.
        """
        t = self.temperature.get(candidate, 1.0)
        return 1.0 / (1.0 + math.exp(-self.raw_logit(z, candidate) / max(t, 1e-6)))

    # --- persistence ------------------------------------------------------------------------------

    def save(self, path: str | Path) -> Path:
        np = _np()
        p = Path(path)
        np.savez(p, w_shared=self.w_shared, w_cand=self.w_cand, bias_cand=self.bias_cand,
                 w_difficulty=self.w_difficulty)
        p.with_suffix(".meta.json").write_text(json.dumps({
            "candidates": self.candidates, "embed_id": self.embed_id, "dim": self.dim,
            "temperature": self.temperature, "fitted_on_items": len(self.fitted_on_items),
            "calibrated_on_items": len(self.calibrated_on_items),
            "note": ("A predictor is a proposal generator. Its output feeds the constrained optimiser and can "
                     "never promote an entry or accept an answer."),
        }, indent=2) + "\n")
        return p


def fit(
    table: OutcomeTable,
    embeddings: dict,
    fit_items: list[str],
    calib_items: list[str],
    *,
    embed_id: str,
    may_train_on: bool | None = None,
    hidden: int = 32,
    epochs: int = 400,
    lr: float = 0.05,
    l2: float = 1e-3,
    seed: int = 0,
    candidates: list[str] | None = None,
    use_affinity: bool = True,
) -> Predictor:
    """Fit the candidate-conditioned head on frozen embeddings, then calibrate on a disjoint slice.

    `fit_items` and `calib_items` must not overlap, and neither may touch the judge fold. The calibration slice
    exists because a temperature fitted on the same items as the weights is not a correction, it is more fitting.
    """
    np = _np()
    if not may_train_on:
        raise EvidenceError(
            "fitting a predictor on this corpus is training on it, and `may_train_on` is "
            f"{may_train_on!r}. Permission to evaluate is not permission to train, and the difference does not "
            "appear in a licence identifier: one corpus this project uses is CC BY-4.0 and its own card forbids "
            "training on it. `None` is treated as not permitted, because a licence question answered by "
            "omission is answered wrongly."
        )
    overlap = set(fit_items) & set(calib_items)
    if overlap:
        raise EvidenceError(
            f"{len(overlap)} items appear in both the fitting and calibration slices. A temperature fitted on "
            "the items that set the weights is not a calibration, it is more fitting."
        )
    cands = candidates or table.tiers
    missing = [i for i in list(fit_items) + list(calib_items) if i not in embeddings]
    if missing:
        raise EvidenceError(f"{len(missing)} items have no embedding (for example {missing[:3]})")
    dim = len(embeddings[fit_items[0]])

    rng = np.random.default_rng(seed)
    p = Predictor(candidates=list(cands), embed_id=embed_id, dim=dim,
                  bias_cand=np.zeros(len(cands)),
                  w_difficulty=np.zeros(dim),
                  w_shared=rng.normal(0, 1.0 / math.sqrt(dim), (dim, hidden)),
                  w_cand=rng.normal(0, 0.1, (len(cands), hidden)),
                  use_affinity=use_affinity)

    # Observed (item, candidate) pairs only. An unobserved pair is absent rather than imputed: there is no
    # placeholder row carrying a guessed label, which is the difference between masking and filling in.
    obs: list[tuple[str, int, float]] = []
    for i in fit_items:
        for ci, c in enumerate(cands):
            cell = table.cells.get(i, {}).get(c)
            if cell is None or not cell.attempted:
                continue
            obs.append((i, ci, 1.0 if cell.solved else 0.0))
    if not obs:
        raise EvidenceError("no observed (item, candidate) pairs in the fitting slice")

    Zm = np.stack([np.asarray(embeddings[i], dtype=float) for i, _, _ in obs])
    ci_arr = np.array([ci for _, ci, _ in obs])
    y = np.array([yy for _, _, yy in obs])

    # Item-normalised weights: average within an item, then across items. Without this an item every candidate
    # solves contributes as many easy positives as there are candidates and dominates the gradient, which is
    # this corpus's shape -- 299 of 699 items were solved by all eight priced tiers.
    per_item: dict[str, int] = {}
    for i, _, _ in obs:
        per_item[i] = per_item.get(i, 0) + 1
    w = np.array([1.0 / per_item[i] for i, _, _ in obs])
    w = w / w.sum()

    onehot = np.zeros((len(obs), len(cands)))
    onehot[np.arange(len(obs)), ci_arr] = 1.0

    for ep in range(epochs):
        g = Zm @ p.w_difficulty
        if p.use_affinity:
            H = Zm @ p.w_shared
            E = p.w_cand[ci_arr]
            h = np.sum(H * E, axis=1)
        else:
            H = E = None
            h = np.zeros(len(obs))
        logit = p.bias_cand[ci_arr] + g + h
        prob = 1.0 / (1.0 + np.exp(-np.clip(logit, -30, 30)))
        r = w * (prob - y)

        p.bias_cand -= lr * (onehot.T @ r + l2 * p.bias_cand)
        p.w_difficulty -= lr * (Zm.T @ r + l2 * p.w_difficulty)
        if p.use_affinity:
            p.w_shared -= lr * (Zm.T @ (r[:, None] * E) + l2 * p.w_shared)
            gw_cand = np.zeros_like(p.w_cand)
            np.add.at(gw_cand, ci_arr, r[:, None] * H)
            p.w_cand -= lr * (gw_cand + l2 * p.w_cand)

        if ep % 50 == 0 or ep == epochs - 1:
            eps = 1e-12
            loss = -float(np.sum(w * (y * np.log(prob + eps) + (1 - y) * np.log(1 - prob + eps))))
            p.history.append({"epoch": ep, "weighted_log_loss": round(loss, 6),
                              "difficulty_std": round(float(np.std(g)), 6),
                              "affinity_std": round(float(np.std(h)), 6)})

    p.fitted_on_items = list(fit_items)
    p.temperature = _fit_temperature(p, table, embeddings, calib_items, cands)
    p.calibrated_on_items = list(calib_items)
    return p


def _fit_temperature(p: Predictor, table: OutcomeTable, embeddings: dict, calib_items: list[str],
                     cands: list[str]) -> dict:
    """One temperature per candidate, by a coarse search on log loss over the calibration slice.

    A search rather than a gradient step because the objective is one-dimensional per candidate and a search
    cannot diverge. Candidates with fewer than twenty observations on the slice keep a temperature of 1.0 --
    fitting one from a handful of points is how a calibration makes probabilities worse.
    """
    np = _np()
    out = {}
    for c in cands:
        zs, ys = [], []
        for i in calib_items:
            cell = table.cells.get(i, {}).get(c)
            if cell is None or not cell.attempted or i not in embeddings:
                continue
            zs.append(p.raw_logit(np.asarray(embeddings[i], dtype=float), c))
            ys.append(1.0 if cell.solved else 0.0)
        if len(ys) < 20:
            out[c] = 1.0
            continue
        lg, yy = np.asarray(zs), np.asarray(ys)
        best, best_loss = 1.0, None
        for t in [0.25, 0.4, 0.6, 0.8, 1.0, 1.3, 1.7, 2.2, 3.0, 4.0, 6.0]:
            pr = 1.0 / (1.0 + np.exp(-np.clip(lg / t, -30, 30)))
            eps = 1e-12
            loss = -float(np.mean(yy * np.log(pr + eps) + (1 - yy) * np.log(1 - pr + eps)))
            if best_loss is None or loss < best_loss:
                best, best_loss = t, loss
        out[c] = best
    return out


@dataclass
class IndependentPredictor:
    """One regularised logistic head per candidate, fitted in closed form. The baseline that has to be beaten.

    Deliberately the dumbest thing that uses the features. It exists because a cleverer structure lost to it
    here: a candidate-conditioned bilinear head, fitted with gradient descent on the same embeddings, reached a
    within-candidate AUC of 0.580 while a plain cross-validated ridge discriminant on those embeddings reached
    0.62. A shared structure only pays if transfer between candidates is real, and that is a hypothesis rather
    than a starting point -- so the starting point is no sharing at all.

    Adding a candidate trains one more head and touches nothing else. Removing one deletes a head. That is the
    property a fixed bank of output logits does not have, and the candidate pool moved twice during this project.

    Closed form rather than iterative because the objective is ridge-penalised least squares on the +/-1 coded
    label, which has an exact solution and cannot be stopped early at the wrong place. Probabilities come from
    a per-candidate Platt scaling fitted on a disjoint slice -- two parameters rather than one, because the
    single-temperature version left predictions twenty points below the observed rate on this corpus and a
    one-parameter correction cannot move an offset.
    """

    candidates: list[str]
    embed_id: str
    dim: int
    weights: dict = field(default_factory=dict)      # candidate -> (dim + 1,)
    platt: dict = field(default_factory=dict)        # candidate -> (a, b) for sigmoid(a * s + b)
    l2_chosen: dict = field(default_factory=dict)
    fitted_on_items: list[str] = field(default_factory=list)
    calibrated_on_items: list[str] = field(default_factory=list)

    def score(self, z, candidate: str) -> float:
        np = _np()
        if candidate not in self.weights:
            raise EvidenceError(
                f"{candidate!r} has no head. A head is per candidate on purpose: measure the candidate and fit "
                "one, rather than borrowing another candidate's weights and calling the output evidence."
            )
        return float(np.append(np.asarray(z, dtype=float), 1.0) @ self.weights[candidate])

    def probability(self, z, candidate: str) -> float:
        a, b = self.platt.get(candidate, (1.0, 0.0))
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, a * self.score(z, candidate) + b))))


def fit_independent(table: OutcomeTable, embeddings: dict, fit_items: list[str], calib_items: list[str], *,
                    embed_id: str, may_train_on: bool | None = None,
                    l2_grid: tuple[float, ...] = (0.1, 1.0, 10.0, 100.0),
                    inner_folds: int = 5, candidates: list[str] | None = None,
                    seed: int = 1) -> IndependentPredictor:
    """Fit one ridge head per candidate, choosing the penalty by cross-validation inside the fitting slice.

    The penalty is chosen inside `fit_items` and never on `calib_items` or the judge fold, because a
    hyperparameter chosen on the slice that reports the result is a hyperparameter fitted to that slice.
    """
    np = _np()
    if not may_train_on:
        raise EvidenceError(
            "fitting a predictor on this corpus is training on it, and `may_train_on` is "
            f"{may_train_on!r}. Permission to evaluate is not permission to train, and the difference does not "
            "appear in a licence identifier."
        )
    if set(fit_items) & set(calib_items):
        raise EvidenceError("the fitting and calibration slices overlap, so the calibration is more fitting")
    cands = candidates or table.tiers
    dim = len(embeddings[fit_items[0]])
    out = IndependentPredictor(candidates=list(cands), embed_id=embed_id, dim=dim)
    rng = np.random.default_rng(seed)

    def solve(X, y, l2):
        A = X.T @ X + l2 * np.eye(X.shape[1])
        return np.linalg.solve(A, X.T @ y)

    def auc(s, y):
        pos, neg = s[y == 1], s[y == 0]
        if not len(pos) or not len(neg):
            return None
        return float((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())

    for c in cands:
        rows = [i for i in fit_items
                if i in embeddings and (table.cells.get(i, {}).get(c) and table.cells[i][c].attempted)]
        if len(rows) < inner_folds * 4:
            continue
        X = np.stack([np.append(np.asarray(embeddings[i], dtype=float), 1.0) for i in rows])
        y = np.array([1.0 if table.cells[i][c].solved else 0.0 for i in rows])
        order = rng.permutation(len(rows))
        best_l2, best_auc = l2_grid[0], None
        for l2 in l2_grid:
            aucs = []
            for f in range(inner_folds):
                te = order[f::inner_folds]
                tr = np.setdiff1d(order, te)
                if len(set(y[tr])) < 2 or len(set(y[te])) < 2:
                    continue
                w = solve(X[tr], y[tr] * 2 - 1, l2)
                a = auc(X[te] @ w, y[te])
                if a is not None:
                    aucs.append(a)
            if aucs:
                m = sum(aucs) / len(aucs)
                if best_auc is None or m > best_auc:
                    best_l2, best_auc = l2, m
        out.weights[c] = solve(X, y * 2 - 1, best_l2)
        out.l2_chosen[c] = best_l2

    out.platt = _fit_platt(out, table, embeddings, calib_items, cands)
    out.fitted_on_items = list(fit_items)
    out.calibrated_on_items = list(calib_items)
    return out


def _fit_platt(pred, table: OutcomeTable, embeddings: dict, calib_items: list[str],
               cands: list[str]) -> dict:
    """Two-parameter Platt scaling per candidate, by gradient descent on the calibration slice.

    Two parameters rather than one because a single temperature cannot move an offset, and on this corpus the
    single-temperature version left every candidate's predicted rate roughly twenty points below its observed
    rate. A scale alone cannot fix a bias.
    """
    np = _np()
    out = {}
    for c in cands:
        if c not in getattr(pred, "weights", {}):
            continue
        s, y = [], []
        for i in calib_items:
            cell = table.cells.get(i, {}).get(c)
            if cell is None or not cell.attempted or i not in embeddings:
                continue
            s.append(pred.score(embeddings[i], c))
            y.append(1.0 if cell.solved else 0.0)
        if len(y) < 20:
            out[c] = (1.0, 0.0)
            continue
        S, Y = np.asarray(s), np.asarray(y)
        a, b = 1.0, 0.0
        for _ in range(2000):
            pr = 1.0 / (1.0 + np.exp(-np.clip(a * S + b, -30, 30)))
            g = pr - Y
            a -= 0.5 * float(np.mean(g * S))
            b -= 0.5 * float(np.mean(g))
        out[c] = (a, b)
    return out

def signal_check(table: OutcomeTable, embeddings: dict, items: list[str], *,
                 candidates: list[str] | None = None, folds: int = 5, l2: float = 1.0,
                 seed: int = 1) -> dict:
    """Is there per-item signal in these features at all, measured before any policy is built?

    Run this first. It is cheap, it needs no held-out judge fold, and it separates the two failures that look
    identical from the outside:

      * **the features carry nothing.** Every candidate's AUC sits at 0.5, so the best any predictor can do is
        emit that candidate's base rate. Adding capacity will not help, and the honest output is a measurement
        rather than a bug report.
      * **the features carry something and the predictor threw it away.** AUC is comfortably above 0.5 while the
        fitted predictor's outputs are nearly constant across items. That is a training failure, not a feature
        failure, and the fix is in the head.

    This project needed the distinction. A candidate-conditioned head fitted on frozen `multilingual-e5-base`
    produced probabilities spanning 0.006 across 699 items -- flat enough that every margin collapsed to a single
    tier -- and the natural conclusion was that a retrieval embedding compresses away difficulty. This check said
    otherwise: all nine candidates scored above 0.5, seven of them above 0.6, from the same embeddings under
    cross-validated ridge discriminants. The features were fine and the head was not.

    Cross-validated on purpose, and on the fitting items only: an AUC computed in-sample on 768 dimensions and a
    few hundred items is near 1.0 whatever the truth is.
    """
    np = _np()
    cands = candidates or table.tiers
    usable = [i for i in items if i in embeddings]
    if len(usable) < folds * 4:
        raise EvidenceError(
            f"{len(usable)} items with embeddings is too few for {folds}-fold cross-validation. A signal check "
            "that cannot cross-validate reports in-sample separation, which on this many dimensions is near "
            "perfect regardless of whether any signal exists."
        )
    X = np.stack([np.asarray(embeddings[i], dtype=float) for i in usable])
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(usable))

    def cv_auc(y):
        aucs = []
        for f in range(folds):
            te = order[f::folds]
            tr = np.setdiff1d(order, te)
            if len(set(y[tr])) < 2 or len(set(y[te])) < 2:
                continue
            Xtr = np.hstack([X[tr], np.ones((len(tr), 1))])
            Xte = np.hstack([X[te], np.ones((len(te), 1))])
            A = Xtr.T @ Xtr + l2 * np.eye(Xtr.shape[1])
            w = np.linalg.solve(A, Xtr.T @ (y[tr] * 2 - 1))
            s = Xte @ w
            pos, neg = s[y[te] == 1], s[y[te] == 0]
            aucs.append(float((pos[:, None] > neg[None, :]).mean()
                              + 0.5 * (pos[:, None] == neg[None, :]).mean()))
        return (sum(aucs) / len(aucs)) if aucs else None

    per_candidate = {}
    for c in cands:
        y = np.array([1.0 if (table.cells.get(i, {}).get(c) and table.cells[i][c].solved) else 0.0
                      for i in usable])
        obs = np.array([1.0 if (table.cells.get(i, {}).get(c) and table.cells[i][c].attempted) else 0.0
                        for i in usable])
        if obs.sum() < folds * 4:
            per_candidate[c] = {"auc": None, "base_rate": None, "why": "too few observations"}
            continue
        per_candidate[c] = {"auc": cv_auc(y), "base_rate": round(float(y.mean()), 4)}

    aucs = [v["auc"] for v in per_candidate.values() if v["auc"] is not None]
    solvers = [sum(1 for c in cands if table.cells.get(i, {}).get(c) and table.cells[i][c].solved)
               for i in usable]
    return {
        "items": len(usable),
        "candidates": list(cands),
        "per_candidate": per_candidate,
        "auc_min": (min(aucs) if aucs else None),
        "auc_max": (max(aucs) if aucs else None),
        "candidates_above_half": sum(1 for a in aucs if a > 0.55),
        "single_solver_items": sum(1 for n in solvers if n == 1),
        "all_solver_items": sum(1 for n in solvers if n == len(cands)),
        "reading": (
            "AUC at 0.5 means the features say nothing beyond each candidate's base rate, and no amount of "
            "capacity recovers that. AUC comfortably above 0.5 while a fitted predictor's outputs are nearly "
            "constant is the other failure: the head threw away signal the features had. Check the spread of "
            "the fitted probabilities against these numbers before concluding anything about the features."
        ),
    }


def spread(predictor: Predictor, embeddings: dict, items: list[str],
           candidates: list[str] | None = None) -> dict:
    """How much a fitted predictor's output actually varies across items, per candidate.

    The other half of `signal_check`. A spread of a few thousandths means the predictor has learned each
    candidate's base rate and nothing else, so every cost threshold will collapse to one candidate and the
    policy is not routing at all -- which is exactly what happened here and was not noticed until a held-out
    judge produced numbers identical to a single tier's.
    """
    np = _np()
    cands = candidates or predictor.candidates
    out = {}
    for c in cands:
        ps = [predictor.probability(np.asarray(embeddings[i], dtype=float), c)
              for i in items if i in embeddings]
        if not ps:
            continue
        out[c] = {"min": round(min(ps), 4), "max": round(max(ps), 4),
                  "range": round(max(ps) - min(ps), 4),
                  "mean": round(sum(ps) / len(ps), 4)}
    ranges = [v["range"] for v in out.values()]
    return {
        "per_candidate": out,
        "widest_range": (max(ranges) if ranges else None),
        "collapsed": bool(ranges) and max(ranges) < 0.05,
        "reading": ("A widest range under about 0.05 means no cost threshold can separate the candidates per "
                    "item, so the resulting policy picks one candidate for everything. Compare against "
                    "`signal_check`: if the features scored above 0.5 and this is flat, the head is at fault."),
    }

def policy_from(predictor: Predictor, table: OutcomeTable, embeddings: dict, *,
                margin: float, cost_of: dict, min_probability: float | None = None,
                fallback: str) -> object:
    """Turn probabilities into an action: the cheapest candidate whose predicted success is within the margin.

    The margin is applied to the *predicted* best, not to a measured one, and that is the whole reason a
    predictor cannot promote anything on its own. What comes out is a policy to be judged on a held-out fold
    exactly like any hand-written one.

    `fallback` is used when no candidate clears the bar -- and it should be the reference tier rather than the
    cheapest, because an item the predictor is unsure about is one there is no evidence about.
    """
    np = _np()
    known = set(predictor.candidates)
    order = sorted((c for c in predictor.candidates if c in cost_of), key=lambda c: cost_of[c])

    def pick(item_id: str, features: dict):
        z = embeddings.get(item_id)
        if z is None:
            return fallback
        zz = np.asarray(z, dtype=float)
        probs = {c: predictor.probability(zz, c) for c in order}
        if not probs:
            return fallback
        top = max(probs.values())
        if min_probability is not None and top < min_probability:
            # Nothing is predicted to clear the owner's floor. Refusing is an action.
            return REFUSE
        for c in order:
            if probs[c] >= top - margin:
                return c
        return fallback

    return pick
