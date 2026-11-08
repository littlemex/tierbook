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


def resolve(path: str) -> Bound:
    """A bound method from `module:attribute`. `tierbook.bounds:wilson` names `wilson_at`.

    The short name exists because `wilson` itself takes `z`, not `alpha`, and is used under that signature by the
    research layer; aliasing it here keeps one name for one interval in the declarations a reader writes.
    """
    if path in ("tierbook.bounds:wilson", "tierbook.bounds:wilson_at"):
        return wilson_at
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
