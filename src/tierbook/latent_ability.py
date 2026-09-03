"""One latent difficulty per item, so a failure tells you something about the next tier.

This is the piece `abstain.sequential_stop` needs and did not have. Driven by a failure count alone the
stopping rule never cleared a 5% lost-success cap on the measured corpus, and the reason is that "four
cheap tiers failed" is overwhelmingly evidence for *escalate* rather than for *stop*: 51 items were
solved by nobody where 143 merely needed a dearer tier. A count cannot separate those. A shared latent
does, because each candidate's failure is informative in proportion to how strong that candidate is.

The model is the one-dimensional item-response model, which is the same object as a rank-one logistic
factorisation:

    P(candidate m solves item i) = sigmoid(b_m - a_m * theta_i)

`theta_i` is the item's **difficulty** and `a_m, b_m` are the candidate's discrimination and its
intercept, which is its skill. The minus sign is what makes the name true: a higher `theta` lowers
every candidate's chance, so the axis reads as difficulty rather than as its opposite. Writing it as
`a * theta + b` fits equally well and silently inverts the axis, which is worth stating because that
is the version this module had first and a test caught it.

Fitted by alternating maximum likelihood on a grid over `theta`. The grid is deliberate rather than
incidental: it is what makes the **posterior** available in closed form, and the posterior is the whole
point of the module.

## Why a posterior rather than a point estimate

`p_next` has to be an upper bound, because a stopping rule reading a point estimate abandons items the
model is merely uncertain about. With a grid over `theta` the update after observing failures is exact
and costs nothing:

    p(theta | failures) proportional to prior(theta) * product over failed m of (1 - sigmoid(b_m - a_m theta))

and the bound is a high quantile of `sigmoid(b_next - a_next theta)` under that posterior. So an item
whose failures are consistent with a wide range of difficulties keeps spending, and only one whose
posterior has collapsed onto the hard end is abandoned.

## What it is not

**It is not a verdict.** The output is a probability that feeds a spending decision. Nothing here can
mark an answer correct.

**It is not a substitute for features.** Fitted from outcomes alone, `theta` is known only for items
the candidates have already answered, which is enough for the sequential rule -- that rule runs
*during* a cascade, so the failures it conditions on are observations of the very item in hand. Routing
an unseen item needs `theta` regressed from cheap features, which is `predict.fit`'s job, and the two
compose: this module supplies the shape and the conditional, that one supplies the prior.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from tierbook.evidence import UNOBSERVED
from tierbook.outcomes import Cell, OutcomeTable


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _cell(table: OutcomeTable, item: str, tier: str) -> Cell:
    return table.cells.get(item, {}).get(tier) or Cell(UNOBSERVED, None)


@dataclass
class AbilityModel:
    """Fitted candidate parameters and the grid the posterior is computed on."""

    tiers: dict[str, tuple[float, float]]          # tier -> (discrimination a, intercept b)
    grid: tuple[float, ...]                        # the theta values the posterior lives on
    prior: tuple[float, ...]                       # prior mass on each grid point, summing to 1
    theta: dict[str, float]                        # posterior-mean theta per fitted item

    def p_solve(self, tier: str, theta: float) -> float:
        a, b = self.tiers[tier]
        return _sigmoid(b - a * theta)

    def posterior(self, failures: tuple[str, ...], solves: tuple[str, ...] = ()) -> list[float]:
        """`p(theta | observations)` on the grid, from the prior and the tiers already seen.

        Failures push mass towards the hard end and successes towards the easy end, each in proportion
        to the candidate's discrimination -- which is what makes a strong candidate's failure more
        informative than a weak one's, the distinction a failure count cannot draw.
        """
        w = list(self.prior)
        for idx, theta in enumerate(self.grid):
            for tier in failures:
                if tier in self.tiers:
                    w[idx] *= (1.0 - self.p_solve(tier, theta))
            for tier in solves:
                if tier in self.tiers:
                    w[idx] *= self.p_solve(tier, theta)
        total = sum(w)
        if total <= 0.0:
            # Every grid point was ruled out, which means the observations contradict the model rather
            # than identifying a difficulty. Falling back to the prior keeps the rule spending, which
            # is the conservative direction; silently returning a confident answer here would abandon
            # exactly the items the model understands least.
            return list(self.prior)
        return [x / total for x in w]

    def p_next_bound(self, tier: str, failures: tuple[str, ...], *, quantile: float = 0.95,
                     solves: tuple[str, ...] = ()) -> float:
        """An upper confidence bound on `P(tier solves | observations)`.

        The quantile is taken over the posterior of `theta`, so the bound widens exactly when the
        observations leave the difficulty unresolved.
        """
        post = self.posterior(failures, solves)
        # Order grid points by the success probability they imply, then walk to the quantile.
        pairs = sorted(((self.p_solve(tier, th), w) for th, w in zip(self.grid, post)))
        cumulative = 0.0
        for p, w in pairs:
            cumulative += w
            if cumulative >= quantile:
                return p
        return pairs[-1][0] if pairs else 1.0

    def p_next_mean(self, tier: str, failures: tuple[str, ...],
                    solves: tuple[str, ...] = ()) -> float:
        post = self.posterior(failures, solves)
        return sum(w * self.p_solve(tier, th) for th, w in zip(self.grid, post))


def fit(table: OutcomeTable, tiers: list[str], *, items: list[str] | None = None,
        grid_points: int = 41, theta_range: float = 4.0, rounds: int = 60,
        step: float = 0.25) -> AbilityModel:
    """Alternating fit of `(a_m, b_m)` against the items' posterior-mean difficulty.

    Two choices worth naming. The grid is coarse on purpose -- 41 points over four standard deviations
    -- because the posterior is read as a quantile and not as a density, and a finer grid buys accuracy
    the stopping rule cannot use. And unobserved cells contribute nothing: a candidate that never ran
    on an item gives no gradient for it, rather than being imputed at the model's own guess, which is
    the one substitution this project refuses everywhere.
    """
    subject = list(items if items is not None else table.items)
    grid = tuple(-theta_range + 2 * theta_range * k / (grid_points - 1) for k in range(grid_points))
    # A standard normal prior over difficulty, which fixes the scale the model is otherwise free to
    # rescale, and is the same prior the posterior update starts from at request time.
    prior_raw = [math.exp(-0.5 * th * th) for th in grid]
    prior = tuple(x / sum(prior_raw) for x in prior_raw)

    params = {t: (1.0, 0.0) for t in tiers}
    theta = {i: 0.0 for i in subject}

    for _ in range(rounds):
        # E-ish step: each item's posterior mean under the current parameters.
        model = AbilityModel(tiers=params, grid=grid, prior=prior, theta=theta)
        for item in subject:
            observed = [(t, _cell(table, item, t)) for t in tiers]
            fails = tuple(t for t, c in observed if c.state != UNOBSERVED and not c.solved)
            wins = tuple(t for t, c in observed if c.solved)
            post = model.posterior(fails, wins)
            theta[item] = sum(w * th for th, w in zip(grid, post))

        # M-ish step: one gradient step per candidate on the log likelihood.
        for tier in tiers:
            a, b = params[tier]
            ga = gb = 0.0
            for item in subject:
                cell = _cell(table, item, tier)
                if cell.state == UNOBSERVED:
                    continue
                y = 1.0 if cell.solved else 0.0
                p = _sigmoid(b - a * theta[item])
                # d/da of the log likelihood carries the minus from `b - a*theta`.
                ga += (y - p) * (-theta[item])
                gb += (y - p)
            n = max(1, len(subject))
            # Discrimination is held positive: a negative `a` would mean a candidate that does better
            # on harder items, which is a sign flip in the latent rather than a fact about the world,
            # and letting it happen makes the fitted axis mean two things at once.
            params[tier] = (max(0.05, a + step * ga / n), b + step * gb / n)

    return AbilityModel(tiers=params, grid=grid, prior=prior, theta=theta)
