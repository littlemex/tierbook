"""The held-out ladder: the k cheapest arms of the selection-half frontier, checked dearest first at the full alpha,
stopping at the first that does not clear (a fixed-sequence test). k = 1 is the cheapest arm that cleared selection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import certify  # noqa: E402
from tierbook import config as cfgmod  # noqa: E402
from tierbook.observation import Observation  # noqa: E402

SALT, T = "ladder-salt", "t"


def cfg(tmp_path, prices):
    c = {a: {"deployment": "self_hosted", "hourly_usd": 1.0, "endpoint": {"base_url": f"http://{a}/v1", "model": a}}
         for a in prices}
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"config_format": 2, "families": {}, "candidates": c}))
    return cfgmod.load_config(p)


def decl(prices, ladder, floor=0.85):
    return certify.load_declarations({
        "alpha": 0.05, "bound": "tierbook.bounds:wilson", "holdout_fraction": 0.5, "split_salt": SALT,
        "unobserved_as": "rejected", "max_observation_age_days": None, "held_out_correction": "none",
        "holdout_ladder": ladder, "task_types": {T: {"floor": floor}},
        "usd_per_attempt": {a: {"usd": u, "source": "test"} for a, u in prices.items()}})


def items(part, n):
    out, i = [], 0
    while len(out) < n:
        it = f"i{i}"
        if certify.partition_of(it, SALT, 0.5) == part:
            out.append(it)
        i += 1
    return out


SEL, HO = items("selection", 600), items("held_out", 600)


def arm(name, sel_rate, ho_rate):
    rows = []
    for its, rate in ((SEL, sel_rate), (HO, ho_rate)):
        k = round(rate * len(its))
        rows += [Observation(item=it, task_type=T, arm=name, outcome="accepted" if j < k else "rejected")
                 for j, it in enumerate(its)]
    return rows


# round 9's shape: a cheap arm that barely clears selection and fails held-out; a dearer one that holds; the dearest
PRICES = {"cheap": 1e-5, "mid": 2e-5, "dear": 5e-5}
ROWS = arm("cheap", 0.885, 0.85) + arm("mid", 0.91, 0.885) + arm("dear", 0.905, 0.89)


def test_ladder_of_one_is_todays_rule(tmp_path):
    e = certify.derive(ROWS, cfg(tmp_path, PRICES), decl(PRICES, 1))["task_types"][T]
    assert e["arm"] == "cheap" and e["status"] == "unconfirmed"
    assert [r["arm"] for r in e["ladder"]] == ["cheap"]


def test_a_longer_ladder_certifies_the_cheapest_confirmed_rung(tmp_path):
    e = certify.derive(ROWS, cfg(tmp_path, PRICES), decl(PRICES, "all"))["task_types"][T]
    assert e["status"] == "certified" and e["arm"] == "mid"
    assert [(r["arm"], r["verdict"]) for r in e["ladder"]] == [("mid", "certified"), ("cheap", "unconfirmed")]
    assert e["ladder_stopped_at"] == 2
    assert e["frontier_dropped"] == [{"arm": "dear", "dominated_by": "mid"}]
    assert "rung 1 of 2" in e["reason"] and "ladder stopped" in e["reason"]


def test_a_failing_top_rung_stops_the_ladder_and_cheaper_rungs_are_not_reached(tmp_path):
    rows = arm("cheap", 0.885, 0.88) + arm("mid", 0.91, 0.84)
    prices = {"cheap": 1e-5, "mid": 2e-5}
    e = certify.derive(rows, cfg(tmp_path, prices), decl(prices, 2))["task_types"][T]
    assert e["status"] == "unconfirmed" and e["arm"] == "mid"
    assert [(r["arm"], r["verdict"]) for r in e["ladder"]] == [("mid", "unconfirmed"), ("cheap", "not_reached")]
    assert "not reached" in e["reason"]
    assert e["ladder"][1]["held_out_lower"] is None and e["ladder"][1]["held_out_upper"] is None


def test_k_takes_the_cheapest_frontier_arms(tmp_path):
    rows = ROWS + arm("mid2", 0.895, 0.87)
    prices = dict(PRICES, mid2=1.5e-5)
    e = certify.derive(rows, cfg(tmp_path, prices), decl(prices, 2))["task_types"][T]
    assert [r["arm"] for r in e["ladder"]] == ["mid2", "cheap"]
    assert e["frontier_above_ladder"] == ["mid"]


def test_every_rung_is_tested_at_the_declared_alpha(tmp_path):
    e = certify.derive(ROWS, cfg(tmp_path, PRICES), decl(PRICES, "all"))["task_types"][T]
    lone = certify.derive(arm("mid", 0.91, 0.885), cfg(tmp_path, {"mid": 2e-5}), decl({"mid": 2e-5}, 1))
    assert e["held_out"]["lower"] == pytest.approx(lone["task_types"][T]["held_out"]["lower"])


@pytest.mark.parametrize("bad", [0, -1, True, "some", 1.5])
def test_holdout_ladder_is_declared_and_checked(bad):
    with pytest.raises(certify.DeclarationError, match="holdout_ladder"):
        decl(PRICES, bad)
    raw = {"alpha": 0.05, "bound": "tierbook.bounds:wilson", "holdout_fraction": 0.5, "split_salt": SALT,
           "unobserved_as": "rejected", "max_observation_age_days": None, "held_out_correction": "none",
           "task_types": {T: {"floor": 0.5}}}
    with pytest.raises(certify.DeclarationError, match="missing required key 'holdout_ladder'"):
        certify.load_declarations(raw)


def test_the_ladder_is_part_of_the_policy_and_the_guarantee(tmp_path):
    p = certify.derive(ROWS, cfg(tmp_path, PRICES), decl(PRICES, "all"))
    assert p["declarations"]["holdout_ladder"] == "all"
    assert "fixed-sequence" in p["guarantee"]
    one = certify.derive(ROWS, cfg(tmp_path, PRICES), decl(PRICES, 1))
    assert "fixed-sequence" not in one["guarantee"]


def test_a_failing_top_rung_is_described_as_not_confirmed(tmp_path):
    rows = arm("cheap", 0.885, 0.88) + arm("mid", 0.91, 0.84)
    prices = {"cheap": 1e-5, "mid": 2e-5}
    e = certify.derive(rows, cfg(tmp_path, prices), decl(prices, 2))["task_types"][T]
    assert e["reason"].startswith("dearest rung of a 2-rung held-out ladder, not confirmed")
    assert e["ladder"][1]["held_out_lower"] is None and e["ladder"][1]["selection_lower"] > 0.85


def test_a_contradicted_cheaper_rung_is_named_as_contradicted(tmp_path):
    rows = arm("cheap", 0.885, 0.70) + arm("mid", 0.91, 0.885)
    prices = {"cheap": 1e-5, "mid": 2e-5}
    e = certify.derive(rows, cfg(tmp_path, prices), decl(prices, 2))["task_types"][T]
    assert e["arm"] == "mid" and "checked next and contradicted" in e["reason"]


def test_equal_selection_bounds_keep_only_the_cheaper_arm(tmp_path):
    rows = arm("a", 0.91, 0.9) + arm("b", 0.91, 0.9)
    prices = {"a": 1e-5, "b": 2e-5}
    e = certify.derive(rows, cfg(tmp_path, prices), decl(prices, "all"))["task_types"][T]
    assert [r["arm"] for r in e["ladder"]] == ["a"] and e["frontier_dropped"] == [{"arm": "b", "dominated_by": "a"}]


def test_a_ladder_longer_than_the_frontier_checks_the_whole_frontier(tmp_path):
    e = certify.derive(ROWS, cfg(tmp_path, PRICES), decl(PRICES, 10))["task_types"][T]
    assert [r["arm"] for r in e["ladder"]] == ["mid", "cheap"] and e["frontier_above_ladder"] == []


def test_all_round_trips_through_the_policy(tmp_path):
    p = certify.derive(ROWS, cfg(tmp_path, PRICES), decl(PRICES, "all"))
    again = certify.load_declarations(p["declarations"])
    assert again.holdout_ladder is None and again.as_dict() == p["declarations"]
