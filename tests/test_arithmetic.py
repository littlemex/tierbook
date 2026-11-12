"""The arithmetic a certificate rests on, computed by tierbook from declared inputs rather than by hand.

Written against `bounds.clopper_pearson`, `bounds.false_pass_at_floor`, `bounds.items_for_power`, the computed form of
`usd_per_attempt`, `measured_on`, and `derive --ledger`. The reference numbers are the distillation record's: round
13's CPU price, round 14's x* = 528 and 778 and their false-pass chances 0.0204 and 0.0119.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from tierbook import certify  # noqa: E402
from tierbook.bounds import (binomial_tail, clopper_pearson, false_pass_at_floor, items_for_power,  # noqa: E402
                             pass_count, power_at, wilson_at)

from test_cascade_arms import T, candidates, declarations, obs  # noqa: E402


def test_round_14_false_pass_chances():
    assert pass_count(600, 0.85, 0.05, wilson_at) == 528
    assert false_pass_at_floor(600, 0.85, 0.05, wilson_at) == pytest.approx(0.0204, abs=5e-5)
    assert pass_count(887, 0.85, 0.025, wilson_at) == 778
    assert false_pass_at_floor(887, 0.85, 0.025, wilson_at) == pytest.approx(0.0119, abs=5e-5)


def test_clopper_pearson_is_exact_on_each_side():
    for n, k in ((50, 40), (600, 528), (887, 779)):
        lo, hi = clopper_pearson(k, n, 0.05)
        assert binomial_tail(k, n, lo) == pytest.approx(0.025, abs=1e-6)
        assert 1 - binomial_tail(k + 1, n, hi) == pytest.approx(0.025, abs=1e-6)
        wlo, whi = wilson_at(k, n, 0.05)
        assert lo <= wlo + 1e-4 and hi >= whi - 1e-4
    assert certify.resolve("tierbook.bounds:clopper_pearson") is clopper_pearson


def test_power_for_the_closing_run():
    n = items_for_power(0.85, 0.878, 0.05, 0.8, wilson_at, 5000)
    assert 1100 <= n <= 1250
    assert power_at(n, 0.85, 0.878, 0.05, wilson_at) >= 0.8
    assert all(power_at(m, 0.85, 0.878, 0.05, wilson_at) < 0.8 for m in range(1, n))


def test_power_counts_up_from_one_and_reaches_max_n():
    assert items_for_power(0.1, 0.99, 0.05, 0.8, wilson_at, 100) == 1
    n = items_for_power(0.85, 0.878, 0.05, 0.8, wilson_at, 5000)
    assert items_for_power(0.85, 0.878, 0.05, 0.8, wilson_at, n) == n
    assert items_for_power(0.85, 0.878, 0.05, 0.8, wilson_at, n - 1) is None


def test_round_13_price_from_its_inputs():
    d = declarations(usd_per_attempt={"student": {
        "usd_per_hour": 0.20012, "attempts_per_hour": 19612, "one_off_usd": 1.6464549, "horizon_attempts": 1_000_000,
        "measured_on": "student:abc", "source": "c8g.xlarge on-demand over measured items/h; labels and fine-tuning amortised"}})
    assert d.usd_per_attempt["student"]["usd"] == pytest.approx(0.0000119, abs=5e-8)


@pytest.mark.parametrize("bad", [
    {"usd_per_hour": 0.2, "attempts_per_hour": 100, "one_off_usd": 1, "source": "x", "measured_on": None},
    {"usd_per_hour": 0.2, "attempts_per_hour": 100, "source": "x"},
    {"usd": float("nan"), "source": "x"},
    {"usd": 0.1, "source": "x", "stands_in_for": True},
    {"usd": 0.1, "usd_per_hour": 0.2, "attempts_per_hour": 1, "one_off_usd": 0, "horizon_attempts": 1, "source": "x"},
    {"usd_per_hour": 0.2, "attempts_per_hour": 0, "one_off_usd": 0, "horizon_attempts": 1, "source": "x"},
    {"usd": 0.1},
])
def test_price_inputs_are_all_declared(bad):
    with pytest.raises(certify.DeclarationError):
        declarations(usd_per_attempt={"student": bad})


def rows(version):
    return [dataclasses.replace(obs(f"i{k}", "student", "accepted"), arm_version=version) for k in range(60)]


def test_a_price_measured_on_another_version_is_refused_unless_explained(tmp_path):
    cfg = candidates(tmp_path)
    price = {"usd": 0.001, "source": "x", "measured_on": "cpu-build"}
    with pytest.raises(certify.DeclarationError, match="measured on"):
        certify.derive(rows("gpu-build"), cfg, declarations(usd_per_attempt={"student": price}))
    other = {**price, "stands_in_for": {"version": "gpu-build-2", "why": "answers equal on 200 of 200 items"}}
    with pytest.raises(certify.DeclarationError, match="measured on"):
        certify.derive(rows("gpu-build"), cfg, declarations(usd_per_attempt={"student": other}))
    explained = {**price, "stands_in_for": {"version": "gpu-build", "why": "answers equal on 200 of 200 items"}}
    policy = certify.derive(rows("gpu-build"), cfg, declarations(usd_per_attempt={"student": explained}))
    assert policy["task_types"][T]["arms"]["student"]["price_check"]["check"] == "stands in"


def test_a_second_hourly_bill_that_disagrees_is_refused(tmp_path):
    price = {"usd_per_hour": 0.3, "attempts_per_hour": 100, "measured_on": None, "source": "x"}
    with pytest.raises(certify.DeclarationError, match="one bill"):
        certify.derive(rows("v1"), candidates(tmp_path), declarations(usd_per_attempt={"student": price}))


def test_every_held_out_cell_carries_its_exact_false_pass_chance(tmp_path):
    entry = certify.derive(rows("v1"), candidates(tmp_path), declarations())
    cell = entry["task_types"][T]["arms"]["student"]["held_out"]
    assert cell["false_pass_at_floor"] == pytest.approx(
        false_pass_at_floor(cell["items"], 0.1, 0.05, wilson_at))


def run(*args):
    return subprocess.run([sys.executable, "-m", "tierbook.cli", *args], capture_output=True, text=True,
                          env={"PYTHONPATH": str(ROOT / "src")})


def test_the_ledger_counts_every_look_at_one_held_out_set(tmp_path):
    from tierbook.observation import write
    cfg_path = tmp_path / "candidates.json"
    candidates(tmp_path)
    obs_path, ledger = tmp_path / "obs.jsonl", tmp_path / "looks.jsonl"
    write(rows("v1"), obs_path)
    looks = []
    for floor in (0.1, 0.2, 0.1):
        d = tmp_path / f"decl-{floor}.json"
        d.write_text(json.dumps({"alpha": 0.05, "bound": "tierbook.bounds:wilson", "holdout_fraction": 0.5,
                                 "split_salt": "cascade-salt", "unobserved_as": "rejected",
                                 "max_observation_age_days": None, "held_out_correction": "none",
                                 "holdout_ladder": 1, "task_types": {T: {"floor": floor}},
                                 "usd_per_attempt": {"student": {"usd": 0.001, "source": "x"}}}))
        out = tmp_path / "p.json"
        r = run("derive", "--observations", str(obs_path), "--candidates", str(cfg_path), "--declarations", str(d),
                "--out", str(out), "--ledger", str(ledger))
        assert r.returncode == 0, r.stderr
        looks.append(json.loads(out.read_text())["task_types"][T]["look"])
    assert looks == [1, 2, 3]
    assert json.loads(out.read_text())["task_types"][T]["items_seen_before"] > 0
    assert "held_out_items" not in json.loads(out.read_text())["task_types"][T]
    assert len(ledger.read_text().splitlines()) == 3
    r = run("derive", "--observations", str(obs_path), "--candidates", str(cfg_path), "--declarations", str(d),
            "--out", str(out))
    assert json.loads(out.read_text())["looks"].startswith("not recorded")


def test_power_cli_needs_every_input():
    r = run("power", "--floor", "0.85", "--assumed-rate", "0.878", "--alpha", "0.05", "--power", "0.8",
            "--bound", "tierbook.bounds:wilson", "--max-n", "5000")
    assert r.returncode == 0 and "held-out items" in r.stdout
    assert run("power", "--floor", "0.85").returncode != 0
