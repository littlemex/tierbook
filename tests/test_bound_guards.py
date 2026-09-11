"""The lower bound refuses inputs that cannot describe a measurement.

`clopper_pearson_lower` computes the number the entire floor comparison rests on, and its boundary case
`if k >= n: return alpha ** (1.0 / n)` was correct for `k == n` and applied to `k > n` as well. More successes
than trials is not a boundary, it is a contradiction, and the value it returned was HIGH -- so a transposed
pair of arguments produced a bound that flattered the candidate rather than a refusal.

Measured while investigating something else: `cp(n=16, k=20)` returned 0.8293, which read as `self-hosted-a`
clearing a 0.80 floor. Its true bound on that cohort is 0.4922.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.accept import clopper_pearson_lower as cp  # noqa: E402


def test_more_successes_than_trials_is_refused_naming_both():
    """Catches the exact input that produced a confident wrong answer. The message names both numbers because a
    transposition is the way this arises and seeing them in order is what reveals it."""
    with pytest.raises(ValueError) as excinfo:
        cp(16, 20, 0.05)
    msg = str(excinfo.value)
    assert "16" in msg and "20" in msg


def test_the_refused_value_is_the_one_that_used_to_be_returned():
    """Pins the direction of the old error, which is why this matters rather than being tidiness: the value was
    0.8293 against a true bound of 0.4922 on the same cohort, so the mistake made a candidate look admissible."""
    assert cp(20, 14, 0.05) == pytest.approx(0.4922, abs=5e-4)
    assert cp(20, 16, 0.05) == pytest.approx(0.5990, abs=5e-4)


def test_zero_or_negative_trials_is_refused_rather_than_dividing_by_zero():
    """`alpha ** (1.0 / n)` with n == 0 raised ZeroDivisionError -- a better failure than a wrong answer, but not
    a stated one, so a reader could not tell it was intended."""
    for bad in (0, -1):
        with pytest.raises(ValueError):
            cp(bad, 1, 0.05)


def test_the_equal_case_still_takes_the_closed_form():
    """The boundary this guard must not break. k == n has an exact closed form and is the common case for a
    small perfect cohort -- 20 of 20 is in the shipped example ledger."""
    assert cp(20, 20, 0.05) == pytest.approx(0.05 ** (1.0 / 20))


def test_no_successes_has_no_positive_lower_bound():
    assert cp(20, 0, 0.05) == 0.0
