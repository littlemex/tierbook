"""Confidence bounds on an acceptance rate, shared by the research layer and the certification plane.

A bound method is anything with the signature `(accepted, n, alpha) -> (lower, upper)`. The plane takes one by
dotted path from the caller's declarations (`tierbook.bounds:wilson` is the one shipped) and never chooses one
itself: which interval is appropriate depends on the sample sizes and on what the caller's guarantee has to
survive, and both are the caller's.
"""
from __future__ import annotations

import importlib
import math
from statistics import NormalDist
from typing import Callable

from tierbook.evidence import EvidenceError

Bound = Callable[[int, int, float], "tuple[float, float]"]


def wilson(successes: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """A Wilson score interval, which stays inside [0, 1] where the normal approximation does not.

    Used rather than the textbook interval because the rates here are small and the samples are in the
    low hundreds, which is exactly where the normal approximation puts a lower bound below zero and a
    reader stops trusting the number.

    **What the interval is over.** It treats the items as a sample and each item's flip as an independent
    binary draw, so it is uncertainty about the rate on the population the benchmark stands for. It is
    *not* uncertainty about the run: two collections give one difference, and no interval computed from
    them describes how much a third would move. A reader who wants the second thing has to collect a
    third run.
    """
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def wilson_at(accepted: int, n: int, alpha: float) -> tuple[float, float]:
    """`wilson` in the plane's bound signature: a two-sided interval at confidence `1 - alpha`."""
    if not 0.0 < alpha < 1.0:
        raise EvidenceError(f"alpha must be in (0, 1), not {alpha!r}")
    return wilson(accepted, n, z=NormalDist().inv_cdf(1 - alpha / 2))


def _log_pmf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * math.log(p) + (n - k) * math.log1p(-p))


def binomial_tail(x: int, n: int, p: float) -> float:
    """P(X >= x) for X ~ Binomial(n, p), summed exactly in log space."""
    if x <= 0:
        return 1.0
    if x > n:
        return 0.0
    logs = [_log_pmf(k, n, p) for k in range(x, n + 1)]
    m = max(logs)
    if m == -math.inf:
        return 0.0
    return min(1.0, math.exp(m) * sum(math.exp(v - m) for v in logs))


def _solve(f, lo: float = 0.0, hi: float = 1.0, iters: int = 80) -> float:
    """The root of an increasing f on [lo, hi] by bisection."""
    for _ in range(iters):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson(accepted: int, n: int, alpha: float) -> tuple[float, float]:
    """The exact (Clopper-Pearson) two-sided interval at confidence `1 - alpha`: each side misses with probability at
    most `alpha / 2` for every true rate, with no normal approximation. Wider than Wilson's, never narrower."""
    if not 0.0 < alpha < 1.0:
        raise EvidenceError(f"alpha must be in (0, 1), not {alpha!r}")
    if n == 0:
        return (0.0, 1.0)
    a = alpha / 2
    lo = 0.0 if accepted == 0 else _solve(lambda p: binomial_tail(accepted, n, p) - a)
    hi = 1.0 if accepted == n else _solve(lambda p: a - (1.0 - binomial_tail(accepted + 1, n, p)))
    return (lo, hi)


def pass_count(n: int, floor: float, alpha: float, bound: Bound) -> int | None:
    """The smallest accepted count whose lower bound reaches `floor` on `n` items, or None if none does."""
    lo, hi = 0, n
    if bound(n, n, alpha)[0] < floor:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if bound(mid, n, alpha)[0] >= floor:
            hi = mid
        else:
            lo = mid + 1
    return lo


def false_pass_at_floor(n: int, floor: float, alpha: float, bound: Bound) -> float | None:
    """The exact chance that an arm whose true rate is exactly `floor` passes on `n` items under `bound`. A below-floor
    arm passes with at most this, whatever the bound's own approximation, so it is the number a certificate's error
    claim rests on."""
    x = pass_count(n, floor, alpha, bound)
    return None if x is None else binomial_tail(x, n, floor)


def items_for_power(floor: float, assumed_rate: float, alpha: float, power: float, bound: Bound,
                    max_n: int = 100_000) -> int | None:
    """The smallest held-out size at which an arm with true rate `assumed_rate` passes `floor` with probability at
    least `power`. Every argument is the caller's; nothing is defaulted. None if not reached by `max_n`."""
    for n in _sizes(max_n):
        x = pass_count(n, floor, alpha, bound)
        if x is not None and binomial_tail(x, n, assumed_rate) >= power:
            return _refine(n, floor, assumed_rate, alpha, power, bound)
    return None


def _sizes(max_n: int):
    n = 10
    while n <= max_n:
        yield n
        n = int(n * 1.25) + 1


def _refine(n: int, floor, rate, alpha, power, bound) -> int:
    lo = max(1, int(n / 1.25) - 1)
    for m in range(lo, n + 1):
        x = pass_count(m, floor, alpha, bound)
        if x is not None and binomial_tail(x, m, rate) >= power:
            return m
    return n


def resolve(path: str) -> Bound:
    """A bound method from `module:attribute`. `tierbook.bounds:wilson` names `wilson_at`.

    The short name exists because `wilson` itself takes `z`, not `alpha`, and is used under that signature by the
    research layer; aliasing it here keeps one name for one interval in the declarations a reader writes.
    """
    if path in ("tierbook.bounds:wilson", "tierbook.bounds:wilson_at"):
        return wilson_at
    if path == "tierbook.bounds:clopper_pearson":
        return clopper_pearson
    mod, sep, attr = path.partition(":")
    if not sep or not mod or not attr:
        raise EvidenceError(f"bound {path!r} must be 'module:attribute'")
    try:
        fn = getattr(importlib.import_module(mod), attr)
    except (ImportError, AttributeError) as e:
        raise EvidenceError(f"bound {path!r} cannot be imported: {e}") from None
    if not callable(fn):
        raise EvidenceError(f"bound {path!r} is not callable")
    return fn
