"""Tests for the v0.5 certification plane (docs/DESIGN-v0.5-certification-plane.md).

Written against the interface in that document and in `tierbook.config` / `tierbook.export_vsr`, not against
`certify.py`, `observation.py` or `certify_cli.py`, which this file's author deliberately did not read. Every
fixture is built from `Observation` objects and plain dicts so a failure here points at a design promise, not
at a shared helper this file and the implementation might disagree about silently.

All item names are run through `certify.partition_of` with the declared salt and holdout fraction to land them
deliberately in the selection or held-out partition -- the same function `derive` uses -- rather than guessing
at the hash.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import certify  # noqa: E402
from tierbook import config as cfgmod  # noqa: E402
from tierbook.observation import Observation  # noqa: E402

SALT = "test-salt"
FRACTION = 0.5


# --- fixtures ---------------------------------------------------------------------------------------------------

def write_candidates(tmp_path: Path, candidates: dict, families: dict | None = None) -> Path:
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps({"config_format": 2, "candidates": candidates, "families": families or {}}))
    return p


def two_arm_candidates(tmp_path: Path, *, cheap_fresh=1.0, dear_fresh=5.0) -> Path:
    return write_candidates(tmp_path, {
        "api-cheap": {"deployment": "api",
                      "endpoint": {"base_url": "http://x/v1", "model": "cheap"},
                      "price_per_mtok": {"fresh_in": cheap_fresh, "cached_in": 0.0, "out": 0.0}},
        "api-dear": {"deployment": "api",
                     "endpoint": {"base_url": "http://x/v1", "model": "dear"},
                     "price_per_mtok": {"fresh_in": dear_fresh, "cached_in": 0.0, "out": 0.0}},
    })


def decl(**overrides) -> dict:
    base = dict(
        alpha=0.05,
        bound="tierbook.bounds:wilson",
        holdout_fraction=FRACTION,
        split_salt=SALT,
        unobserved_as="excluded",
        max_observation_age_days=None,
        held_out_correction="none", holdout_ladder=1,
        task_types={"law": {"floor": 0.5}},
        repeat_rule="all",
    )
    base.update(overrides)
    return base


def partition_items(partition: str, n: int, *, salt: str = SALT, fraction: float = FRACTION,
                    prefix: str = "item") -> list[str]:
    out, i = [], 0
    while len(out) < n:
        cand = f"{prefix}-{i}"
        if certify.partition_of(cand, salt, fraction) == partition:
            out.append(cand)
        i += 1
    return out


def row(item, task_type, arm, outcome, *, fresh_in=1_000_000, cached_in=0, out=0, run="r1",
        reason="", observed_at="2026-11-01T00:00:00Z") -> Observation:
    return Observation(item=item, task_type=task_type, arm=arm, outcome=outcome,
                       usage={"fresh_in": fresh_in, "cached_in": cached_in, "out": out},
                       run=run, reason=reason, observed_at=observed_at)


def accepted_block(items, task_type, arm, **kw) -> list[Observation]:
    return [row(i, task_type, arm, "accepted", **kw) for i in items]


def rejected_block(items, task_type, arm, **kw) -> list[Observation]:
    return [row(i, task_type, arm, "rejected", **kw) for i in items]


def find_task_type(policy: dict, name: str) -> dict:
    return policy["task_types"][name]


def arm_record(policy: dict, task_type: str, arm: str) -> dict:
    return find_task_type(policy, task_type)["arms"][arm]


# --- cost is spend over ALL attempts, including unobserved, divided by accepted items ------------------------------

def test_spend_per_accepted_counts_unobserved_spend_in_the_numerator_but_not_the_denominator(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path, cheap_fresh=1.0))
    sel = partition_items("selection", 4)
    held = partition_items("held_out", 20)
    obs = (accepted_block(sel[:3], "law", "api-cheap")
           + [row(sel[3], "law", "api-cheap", "unobserved", reason="timeout")]
           + accepted_block(held, "law", "api-cheap"))
    policy = certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.3}})))
    sel_rec = arm_record(policy, "law", "api-cheap")["selection"]
    # 4 attempts at $1.00 each (1,000,000 fresh_in tokens @ $1.0/Mtok) = $4.00 spend, 3 accepted items.
    assert sel_rec["spend_usd"] == pytest.approx(4.0)
    assert sel_rec["accepted"] == 3
    assert sel_rec["attempts"] == 4           # all 4 attempts, including the unobserved one
    assert sel_rec["items"] == 3              # the graded items the rate is over
    assert sel_rec["spend_per_accepted_usd"] == pytest.approx(4.0 / 3)


# --- unobserved_as changes the rate ------------------------------------------------------------------------------

def test_unobserved_as_rejected_lowers_the_rate_versus_excluded(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 3)
    held = partition_items("held_out", 20)
    obs = (accepted_block(sel[:2], "law", "api-cheap")
           + [row(sel[2], "law", "api-cheap", "unobserved", reason="ungraded")]
           + accepted_block(held, "law", "api-cheap"))

    excluded = certify.derive(obs, cfg, certify.load_declarations(
        decl(unobserved_as="excluded", task_types={"law": {"floor": 0.3}})))
    rejected = certify.derive(obs, cfg, certify.load_declarations(
        decl(unobserved_as="rejected", task_types={"law": {"floor": 0.3}})))

    assert arm_record(excluded, "law", "api-cheap")["selection"]["rate"] == pytest.approx(1.0)
    assert arm_record(rejected, "law", "api-cheap")["selection"]["rate"] == pytest.approx(2 / 3)


# --- the unit is the item: multiple runs need a declared repeat_rule, and are then counted once -------------------

def test_an_item_with_multiple_runs_refuses_without_a_declared_repeat_rule(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 1)
    held = partition_items("held_out", 20)
    obs = ([row(sel[0], "law", "api-cheap", "accepted", run="r1"),
            row(sel[0], "law", "api-cheap", "accepted", run="r2")]
           + accepted_block(held, "law", "api-cheap"))
    d = decl(task_types={"law": {"floor": 0.3}})
    del d["repeat_rule"]
    with pytest.raises(certify.DeclarationError, match="repeat_rule"):
        certify.derive(obs, cfg, certify.load_declarations(d))


def test_repeated_runs_of_one_item_are_counted_as_one_item_not_two_rows(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 2)
    held = partition_items("held_out", 20)
    obs = ([row(sel[0], "law", "api-cheap", "accepted", run="r1"),
            row(sel[0], "law", "api-cheap", "accepted", run="r2"),     # all agree: item accepted
            row(sel[1], "law", "api-cheap", "accepted", run="r1"),
            row(sel[1], "law", "api-cheap", "rejected", run="r2")]     # not unanimous: item rejected under "all"
           + accepted_block(held, "law", "api-cheap"))
    policy = certify.derive(obs, cfg, certify.load_declarations(
        decl(repeat_rule="all", task_types={"law": {"floor": 0.3}})))
    sel_rec = arm_record(policy, "law", "api-cheap")["selection"]
    assert sel_rec["items"] == 2          # not 4: four rows, two items
    assert sel_rec["accepted"] == 1       # only the unanimous item


# --- what ships is the held-out side, not the selection side --------------------------------------------------------

def test_the_shipped_rate_and_cost_are_the_held_out_ones_not_the_selection_ones(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path, cheap_fresh=2.0))
    sel = partition_items("selection", 20)
    held = partition_items("held_out", 20, prefix="heldout")
    obs = (accepted_block(sel, "law", "api-cheap")                      # selection: 20/20 = 1.0
           + accepted_block(held[:16], "law", "api-cheap")
           + rejected_block(held[16:], "law", "api-cheap"))              # held-out: 16/20 = 0.8
    policy = certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.5}})))
    t = find_task_type(policy, "law")
    assert t["status"] == "certified"
    sel_rate = arm_record(policy, "law", "api-cheap")["selection"]["rate"]
    held_rate = arm_record(policy, "law", "api-cheap")["held_out"]["rate"]
    assert sel_rate == pytest.approx(1.0)
    assert held_rate == pytest.approx(0.8)
    # The number the policy ships at top level for this task type is the held-out one, not the inflated
    # selection-side one.
    assert t["held_out"]["rate"] == pytest.approx(held_rate)
    assert t["held_out"]["rate"] != pytest.approx(sel_rate)


# --- held-out upper bound below the floor contradicts a selection winner -------------------------------------------

def test_a_held_out_upper_bound_below_the_floor_is_contradicted(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 20)
    held = partition_items("held_out", 20, prefix="heldout2")
    obs = (accepted_block(sel, "law", "api-cheap")                      # wins selection: 20/20
           + accepted_block(held[:2], "law", "api-cheap")
           + rejected_block(held[2:], "law", "api-cheap"))               # held-out: 2/20, upper bound << 0.5
    policy = certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.5}})))
    t = find_task_type(policy, "law")
    assert t["status"] == "contradicted"
    assert t["reason_code"] == "held_out_below"


# --- a task type with no declared floor cannot be assigned ----------------------------------------------------------

def test_a_task_type_with_no_declared_floor_is_unassignable(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 5)
    held = partition_items("held_out", 20)
    obs = accepted_block(sel, "undeclared-type", "api-cheap") + accepted_block(held, "undeclared-type", "api-cheap")
    policy = certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.5}})))
    t = find_task_type(policy, "undeclared-type")
    assert t["status"] == "unassignable"
    assert t["reason_code"] == "no_floor"


# --- a price change alone flips the assignment, with no re-measurement ---------------------------------------------

def test_a_price_change_alone_flips_the_assignment_with_the_same_observations(tmp_path):
    sel = partition_items("selection", 20, prefix="priceitem")
    held = partition_items("held_out", 20, prefix="priceheld")
    obs = (accepted_block(sel, "law", "api-cheap") + accepted_block(held, "law", "api-cheap")
           + accepted_block(sel, "law", "api-dear") + accepted_block(held, "law", "api-dear"))
    d = certify.load_declarations(decl(task_types={"law": {"floor": 0.5}}))

    cfg_a = cfgmod.load_config(two_arm_candidates(tmp_path, cheap_fresh=1.0, dear_fresh=5.0))
    policy_a = certify.derive(obs, cfg_a, d)
    assert find_task_type(policy_a, "law")["arm"] == "api-cheap"

    cfg_b = cfgmod.load_config(two_arm_candidates(tmp_path, cheap_fresh=10.0, dear_fresh=1.0))
    policy_b = certify.derive(obs, cfg_b, d)
    assert find_task_type(policy_b, "law")["arm"] == "api-dear"


# --- old observations cannot be chosen --------------------------------------------------------------------------

def test_observations_older_than_max_observation_age_days_cannot_be_chosen(tmp_path):
    from datetime import datetime, timezone

    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 20, prefix="ageitem")
    held = partition_items("held_out", 20, prefix="ageheld")
    stale_at = "2026-01-01T00:00:00Z"   # far older than 7 days before as_of
    obs = (accepted_block(sel, "law", "api-cheap", observed_at=stale_at)
           + accepted_block(held, "law", "api-cheap", observed_at=stale_at))
    as_of = datetime(2026, 11, 8, tzinfo=timezone.utc)

    no_limit = certify.derive(obs, cfg, certify.load_declarations(
        decl(max_observation_age_days=None, task_types={"law": {"floor": 0.5}})), as_of=as_of)
    assert find_task_type(no_limit, "law")["status"] == "certified"

    limited = certify.derive(obs, cfg, certify.load_declarations(
        decl(max_observation_age_days=7, task_types={"law": {"floor": 0.5}})), as_of=as_of)
    t = find_task_type(limited, "law")
    assert t["status"] == "unassignable"
    # Every arm's evidence exists but is too old to be chosen, so nothing fresh clears the floor -- distinct
    # from a task type with zero observations at all.
    assert t["reason_code"] == "nothing_clears_floor"
    assert "stale" in t["reason"]


# --- a token kind the price card has no price for makes the arm unpriced, and it never wins on cost -----------------

def test_an_arm_that_uses_an_unpriced_token_kind_never_wins_the_selection(tmp_path):
    cfg = cfgmod.load_config(write_candidates(tmp_path, {
        # fully priced, modest cost
        "priced": {"deployment": "api", "endpoint": {"base_url": "http://x/v1", "model": "priced"},
                   "price_per_mtok": {"fresh_in": 3.0, "cached_in": 3.0, "out": 3.0}},
        # price card is missing cached_in entirely, but observations below spend cached_in tokens on it --
        # if that spend were silently treated as free this arm would look cheapest.
        "half_priced": {"deployment": "api", "endpoint": {"base_url": "http://x/v1", "model": "half"},
                        "price_per_mtok": {"fresh_in": 0.01, "out": 0.01}},
    }))
    sel = partition_items("selection", 20, prefix="priceditem")
    held = partition_items("held_out", 20, prefix="pricedheld")
    half_sel = partition_items("selection", 20, prefix="halfsel")
    half_held = partition_items("held_out", 20, prefix="halfheld")
    obs = (accepted_block(sel, "law", "priced", fresh_in=1_000_000, cached_in=0, out=0)
           + accepted_block(held, "law", "priced", fresh_in=1_000_000, cached_in=0, out=0)
           + accepted_block(half_sel, "law", "half_priced", fresh_in=0, cached_in=1_000_000, out=0)
           + accepted_block(half_held, "law", "half_priced", fresh_in=0, cached_in=1_000_000, out=0))

    policy = certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.5}})))
    t = find_task_type(policy, "law")
    half_rec = arm_record(policy, "law", "half_priced")["selection"]
    assert half_rec["spend_per_accepted_usd"] is None
    assert t["arm"] == "priced"


# --- fallback is the single best arm by default, or the declared one -----------------------------------------------

def test_fallback_defaults_to_single_best(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 20, prefix="fbitem")
    held = partition_items("held_out", 20, prefix="fbheld")
    obs = accepted_block(sel, "law", "api-cheap") + accepted_block(held, "law", "api-cheap")
    policy = certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.5}})))
    assert policy["single_best"] is not None
    assert policy["fallback"]["arm"] == policy["single_best"]["arm"]


def test_a_declared_fallback_arm_overrides_single_best(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 20, prefix="fb2item")
    held = partition_items("held_out", 20, prefix="fb2held")
    obs = accepted_block(sel, "law", "api-cheap") + accepted_block(held, "law", "api-cheap")
    d = decl(task_types={"law": {"floor": 0.5}}, fallback_arm="api-dear")
    policy = certify.derive(obs, cfg, certify.load_declarations(d))
    assert policy["fallback"]["arm"] == "api-dear"
    assert policy["single_best"]["arm"] != "api-dear"


# --- contradicted and unassignable entries do not appear in the compiled table -------------------------------------

def test_as_table_omits_contradicted_and_unassignable_task_types(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel_ok = partition_items("selection", 20, prefix="okitem")
    held_ok = partition_items("held_out", 20, prefix="okheld")
    sel_bad = partition_items("selection", 20, prefix="baditem")
    held_bad = partition_items("held_out", 20, prefix="badheld")
    obs = (accepted_block(sel_ok, "law", "api-cheap") + accepted_block(held_ok, "law", "api-cheap")
           + accepted_block(sel_bad, "physics", "api-cheap")
           + accepted_block(held_bad[:2], "physics", "api-cheap") + rejected_block(held_bad[2:], "physics", "api-cheap")
           + accepted_block(partition_items("selection", 5, prefix="histitem"), "history", "api-cheap"))
    d = decl(task_types={"law": {"floor": 0.5}, "physics": {"floor": 0.5}})  # "history" is undeclared
    policy = certify.derive(obs, cfg, certify.load_declarations(d))
    assert find_task_type(policy, "law")["status"] == "certified"
    assert find_task_type(policy, "physics")["status"] == "contradicted"
    assert find_task_type(policy, "history")["status"] == "unassignable"

    table = certify.as_table(policy)
    assert "law" in table["families"]
    assert "physics" not in table["families"]
    assert "history" not in table["families"]


# --- a Bonferroni correction over task types widens the held-out interval ------------------------------------------

def test_bonferroni_correction_widens_the_held_out_interval_versus_none(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 20, prefix="bonfitem")
    held = partition_items("held_out", 20, prefix="bonfheld")
    obs = (accepted_block(sel, "law", "api-cheap") + accepted_block(held[:16], "law", "api-cheap")
           + rejected_block(held[16:], "law", "api-cheap")
           + accepted_block(partition_items("selection", 20, prefix="bonfitem2"), "physics", "api-cheap")
           + accepted_block(partition_items("held_out", 20, prefix="bonfheld2"), "physics", "api-cheap"))
    d_common = dict(task_types={"law": {"floor": 0.5}, "physics": {"floor": 0.5}})

    none_policy = certify.derive(obs, cfg, certify.load_declarations(decl(held_out_correction="none", holdout_ladder=1, **d_common)))
    bonf_policy = certify.derive(obs, cfg, certify.load_declarations(
        decl(held_out_correction="bonferroni_over_task_types", **d_common)))

    none_rec = arm_record(none_policy, "law", "api-cheap")["held_out"]
    bonf_rec = arm_record(bonf_policy, "law", "api-cheap")["held_out"]
    none_width = none_rec["upper"] - none_rec["lower"]
    bonf_width = bonf_rec["upper"] - bonf_rec["lower"]
    assert bonf_width > none_width


# --- drift: contradiction checks, undetermined, and the min_items guard --------------------------------------------

def _certified_policy(tmp_path, prefix="drift"):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 20, prefix=f"{prefix}sel")
    held = partition_items("held_out", 20, prefix=f"{prefix}held")
    obs = accepted_block(sel, "law", "api-cheap") + accepted_block(held, "law", "api-cheap")
    return cfg, certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.5}})))


def test_drift_without_a_declared_min_items_refuses_when_a_certified_assignment_exists(tmp_path):
    cfg, policy = _certified_policy(tmp_path)
    fresh = accepted_block(partition_items("selection", 5, prefix="freshitem"), "law", "api-cheap")
    d = certify.load_declarations(decl(task_types={"law": {"floor": 0.5}}))  # no min_items
    with pytest.raises(certify.DeclarationError, match="min_items"):
        certify.drift(policy, policy, fresh, d, cfg)


def test_drift_reports_undetermined_when_fresh_evidence_is_below_min_items(tmp_path):
    cfg, policy = _certified_policy(tmp_path)
    fresh = accepted_block(partition_items("selection", 3, prefix="undetermineditem"), "law", "api-cheap")
    d = certify.load_declarations(decl(task_types={"law": {"floor": 0.5}}, min_items=10))
    report = certify.drift(policy, policy, fresh, d, cfg)
    checks = [c for c in report["contradiction_checks"] if c["task_type"] == "law"]
    assert checks and checks[0]["verdict"] == "undetermined"
    assert checks[0]["items"] == 3


def test_drift_reports_contradicted_when_fresh_evidence_falls_below_the_floor(tmp_path):
    cfg, policy = _certified_policy(tmp_path, prefix="driftbad")
    bad = partition_items("selection", 20, prefix="contradictfresh")
    fresh = accepted_block(bad[:2], "law", "api-cheap") + rejected_block(bad[2:], "law", "api-cheap")
    d = certify.load_declarations(decl(task_types={"law": {"floor": 0.5}}, min_items=10))
    report = certify.drift(policy, policy, fresh, d, cfg)
    checks = [c for c in report["contradiction_checks"] if c["task_type"] == "law"]
    assert checks and checks[0]["verdict"] == "contradicted"


# --- export-policy vsr: certified entries only, default_model is the fallback, labels are mandatory ----------------

def cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "tierbook.cli", *args], cwd=str(cwd),
                          capture_output=True, text=True,
                          env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin:/usr/local/bin"})


def test_export_policy_vsr_emits_only_certified_decisions_with_fallback_as_default(tmp_path):
    cfg, policy = _certified_policy(tmp_path, prefix="exportok")
    candidates_path = two_arm_candidates(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy))
    out_path = tmp_path / "vsr.json"

    got = cli("export-policy", "--policy", str(policy_path), "--target", "vsr",
              "--candidates", str(candidates_path), "--out", str(out_path),
              "--signal", "law=LAW", cwd=tmp_path)
    assert got.returncode == 0, got.stdout + got.stderr
    config = json.loads(out_path.read_text())
    decided_models = {m["model"] for d in config["routing"]["decisions"] for m in d.get("modelRefs", [])}
    assert decided_models == {"api-cheap"}
    assert config["providers"]["defaults"]["model"] == policy["fallback"]["arm"]


def test_export_policy_vsr_refuses_a_certified_task_type_with_no_signal_mapping(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel_law = partition_items("selection", 20, prefix="exp2lawsel")
    held_law = partition_items("held_out", 20, prefix="exp2lawheld")
    sel_hist = partition_items("selection", 20, prefix="exp2histsel")
    held_hist = partition_items("held_out", 20, prefix="exp2histheld")
    obs = (accepted_block(sel_law, "law", "api-cheap") + accepted_block(held_law, "law", "api-cheap")
           + accepted_block(sel_hist, "history", "api-cheap") + accepted_block(held_hist, "history", "api-cheap"))
    d = certify.load_declarations(decl(task_types={"law": {"floor": 0.5}, "history": {"floor": 0.5}}))
    policy = certify.derive(obs, cfg, d)
    assert find_task_type(policy, "law")["status"] == "certified"
    assert find_task_type(policy, "history")["status"] == "certified"

    policy_path = tmp_path / "policy2.json"
    policy_path.write_text(json.dumps(policy))
    out_path = tmp_path / "vsr2.json"
    # Only "law" is mapped to a classifier label; "history" is certified but unmapped and must refuse the export.
    got = cli("export-policy", "--policy", str(policy_path), "--target", "vsr",
              "--candidates", str(two_arm_candidates(tmp_path)), "--out", str(out_path),
              "--signal", "law=LAW", cwd=tmp_path)
    assert got.returncode != 0


# =================================================================================================================
# Regression tests below, added against the interface fixed after review: `certify.drift` takes `cfg` as a
# required fifth argument; `certify.derive(..., as_of=...)`; `Observation.finish_reason`; `certify.dedupe`;
# `certify.assignments`; the CLI's exit codes (0 ok / 2 refused / 3 contradicted); and `ingest --append`. Each
# test is named for the defect it pins down, and is written the same way as the file above -- against the design
# document and this file's own helpers, not against certify.py/observation.py/certify_cli.py.
# =================================================================================================================

import dataclasses


def empty_usage_row(item, task_type, arm, outcome, *, run="r1", observed_at="2026-11-01T00:00:00Z") -> Observation:
    """Like `row()`, but `usage={}` -- DESIGN-v0.5 S2.1: "Empty usage means the source did not report it, which
    is unknown and not zero: an arm whose graded attempts carry no usage is unpriced.\""""
    return Observation(item=item, task_type=task_type, arm=arm, outcome=outcome, usage={},
                       run=run, reason="", observed_at=observed_at)


def majority_of_two_or_more(outcomes: list[str]) -> str:
    """A `repeat_rule` callable referenced by its dotted path from
    test_repeat_rule_accepts_a_module_colon_attribute_callable below. Deliberately not what `all`/`any`/`majority`
    would each say about the fixture there, so the test can tell whether this function ran at all rather than one
    of the built-ins."""
    return "accepted" if sum(1 for o in outcomes if o == "accepted") >= 2 else "rejected"


def write_observations_jsonl(path: Path, observations: list[Observation]) -> None:
    with open(path, "w") as f:
        for o in observations:
            f.write(json.dumps(dataclasses.asdict(o)) + "\n")


# --- 1. an arm whose only graded observations carry no usage at all is unpriced, and never wins on cost ---------

def test_an_arm_with_only_empty_usage_graded_observations_never_wins_on_cost(tmp_path):
    cfg = cfgmod.load_config(write_candidates(tmp_path, {
        "api-empty": {"deployment": "api", "endpoint": {"base_url": "http://x/v1", "model": "empty"},
                      "price_per_mtok": {"fresh_in": 1.0, "cached_in": 0.0, "out": 0.0}},
        "api-priced": {"deployment": "api", "endpoint": {"base_url": "http://x/v1", "model": "priced"},
                       "price_per_mtok": {"fresh_in": 2.0, "cached_in": 0.0, "out": 0.0}},
    }))
    empty_items = partition_items("selection", 20, prefix="emptysel") + partition_items(
        "held_out", 20, prefix="emptyheld")
    sel_p = partition_items("selection", 20, prefix="pricedsel")
    held_p = partition_items("held_out", 20, prefix="pricedheld")
    obs = ([empty_usage_row(i, "law", "api-empty", "accepted") for i in empty_items]
           + accepted_block(sel_p, "law", "api-priced") + accepted_block(held_p, "law", "api-priced"))
    policy = certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.3}})))
    t = find_task_type(policy, "law")
    # api-empty is accepted on every attempt and would look free and perfect if empty usage priced at $0; it
    # must lose to the arm that actually reports what it spent.
    assert t["arm"] == "api-priced"
    assert arm_record(policy, "law", "api-empty")["selection"]["spend_per_accepted_usd"] is None


# --- 2. drift lists a candidate arm that has never been observed, under "needs_measurement" ---------------------

def test_drift_reports_never_observed_for_a_candidate_arm_with_no_observations_at_all(tmp_path):
    cfg, policy = _certified_policy(tmp_path, prefix="nmobserved")  # only ever observes api-cheap
    fresh = accepted_block(partition_items("selection", 10, prefix="nmfresh"), "law", "api-cheap")
    d = certify.load_declarations(decl(task_types={"law": {"floor": 0.5}}, min_items=10))
    report = certify.drift(policy, policy, fresh, d, cfg)
    entries = [e for e in report["needs_measurement"] if e["task_type"] == "law" and e["arm"] == "api-dear"]
    assert entries, report["needs_measurement"]
    assert "never observed" in entries[0]["why"]


# --- 3. usd_per_attempt may only be declared for a candidate that IS fixed-cost and DOES exist -------------------

def test_usd_per_attempt_on_a_non_fixed_cost_or_unknown_arm_is_a_declaration_error(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 20, prefix="usdsel")
    held = partition_items("held_out", 20, prefix="usdheld")
    obs = accepted_block(sel, "law", "api-cheap") + accepted_block(held, "law", "api-cheap")

    # api-cheap is deployment "api" (per-token), not a fixed-cost ("self_hosted") candidate.
    not_fixed_cost = certify.load_declarations(decl(
        task_types={"law": {"floor": 0.3}}, usd_per_attempt={"api-cheap": {"usd": 0.1, "source": "test"}}))
    with pytest.raises(certify.DeclarationError, match="fixed-cost"):
        certify.derive(obs, cfg, not_fixed_cost)

    # "ghost-arm" is not a candidate at all.
    unknown_arm = certify.load_declarations(decl(
        task_types={"law": {"floor": 0.3}}, usd_per_attempt={"ghost-arm": {"usd": 0.1, "source": "test"}}))
    with pytest.raises(certify.DeclarationError, match="fixed-cost"):
        certify.derive(obs, cfg, unknown_arm)


# --- 4. CLI exit codes: 0 ok, 2 refused input or missing flag, 3 a contradicted drift -----------------------------

def test_cli_exit_codes_distinguish_refused_input_contradicted_drift_and_missing_flags(tmp_path):
    candidates_path = two_arm_candidates(tmp_path)
    declarations_path = tmp_path / "declarations.json"
    declarations_path.write_text(json.dumps(decl(task_types={"law": {"floor": 0.3}})))

    # a) derive on a broken observation line refuses with exit 2.
    broken_path = tmp_path / "broken.jsonl"
    broken_path.write_text('{"item": "x1", "task_type": "law", "arm": "api-cheap", "outcome": "accepted", '
                           '"run": "r1"}\nnot valid json at all {{{\n')
    policy_path = tmp_path / "policy.json"
    got = cli("derive", "--observations", str(broken_path), "--candidates", str(candidates_path),
              "--declarations", str(declarations_path), "--out", str(policy_path), cwd=tmp_path)
    assert got.returncode == 2, got.stdout + got.stderr

    # b) a real derive, then a drift whose fresh evidence contradicts the deployed assignment exits 3.
    sel = partition_items("selection", 20, prefix="cliexitsel")
    held = partition_items("held_out", 20, prefix="cliexitheld")
    good_path = tmp_path / "good.jsonl"
    write_observations_jsonl(good_path, accepted_block(sel, "law", "api-cheap") + accepted_block(
        held, "law", "api-cheap"))
    got = cli("derive", "--observations", str(good_path), "--candidates", str(candidates_path),
              "--declarations", str(declarations_path), "--out", str(policy_path), cwd=tmp_path)
    assert got.returncode == 0, got.stdout + got.stderr

    drift_declarations_path = tmp_path / "drift_declarations.json"
    drift_declarations_path.write_text(json.dumps(decl(task_types={"law": {"floor": 0.3}}, min_items=10)))
    bad = partition_items("selection", 20, prefix="cliexitcontra")
    fresh_path = tmp_path / "fresh.jsonl"
    write_observations_jsonl(fresh_path, accepted_block(bad[:1], "law", "api-cheap") + rejected_block(
        bad[1:], "law", "api-cheap"))
    drift_out_path = tmp_path / "drift.json"
    got = cli("drift", "--observations", str(good_path), "--candidates", str(candidates_path),
              "--declarations", str(drift_declarations_path), "--out", str(drift_out_path),
              "--deployed", str(policy_path), "--fresh", str(fresh_path), cwd=tmp_path)
    assert got.returncode == 3, got.stdout + got.stderr

    # c) export-policy --target vsr with no --candidates refuses with exit 2.
    vsr_out_path = tmp_path / "vsr.json"
    got = cli("export-policy", "--policy", str(policy_path), "--target", "vsr", "--out", str(vsr_out_path),
              "--signal", "law=LAW", cwd=tmp_path)
    assert got.returncode == 2, got.stdout + got.stderr

    # d) a malformed --signal (missing "=VALUE") refuses with exit 2.
    got = cli("export-policy", "--policy", str(policy_path), "--target", "vsr", "--candidates",
              str(candidates_path), "--out", str(vsr_out_path), "--signal", "law", cwd=tmp_path)
    assert got.returncode == 2, got.stdout + got.stderr


# --- 5. one attempt is one record: conflicting records refuse, identical duplicates count once, and ingest ------
# --- is idempotent by default -------------------------------------------------------------------------------------

def test_conflicting_attempt_records_refuse_and_identical_duplicates_count_once(tmp_path):
    conflicting = [Observation(item="x", task_type="law", arm="api-cheap", outcome="accepted",
                               usage={"fresh_in": 1, "cached_in": 0, "out": 0}, run="r1", reason="",
                               observed_at="2026-11-01T00:00:00Z"),
                  Observation(item="x", task_type="law", arm="api-cheap", outcome="rejected",
                               usage={"fresh_in": 1, "cached_in": 0, "out": 0}, run="r1", reason="",
                               observed_at="2026-11-01T00:00:00Z")]
    with pytest.raises(certify.EvidenceError, match="different records"):
        certify.dedupe(conflicting)

    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 3, prefix="dedupsel")
    held = partition_items("held_out", 20, prefix="dedupheld")
    identical = row(sel[0], "law", "api-cheap", "accepted")
    obs = ([identical, row(sel[0], "law", "api-cheap", "accepted"),   # byte-identical duplicate of `identical`
            row(sel[1], "law", "api-cheap", "accepted"), row(sel[2], "law", "api-cheap", "accepted")]
           + accepted_block(held, "law", "api-cheap"))
    policy = certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.3}})))
    sel_rec = arm_record(policy, "law", "api-cheap")["selection"]
    assert sel_rec["items"] == 3          # 3 distinct items, not 4 rows worth
    assert sel_rec["attempts"] == 3
    assert sel_rec["spend_usd"] == pytest.approx(3.0)   # not 4.0: the duplicate row is one attempt, not two


def test_rerunning_ingest_without_append_does_not_double_the_observation_count(tmp_path):
    calls_path = tmp_path / "calls.jsonl"
    calls_path.write_text(json.dumps({"item": "x1", "task_type": "law", "arm": "api-cheap", "run": "r1"}) + "\n")
    out_path = tmp_path / "observations.jsonl"

    got1 = cli("ingest", "--calls", str(calls_path), "--out", str(out_path), cwd=tmp_path)
    assert got1.returncode == 0, got1.stdout + got1.stderr
    first_line_count = sum(1 for _ in out_path.open())
    assert first_line_count == 1

    got2 = cli("ingest", "--calls", str(calls_path), "--out", str(out_path), cwd=tmp_path)
    assert got2.returncode == 0, got2.stdout + got2.stderr
    # re-running ingest WITHOUT --append replaces the output; the same call must not be counted twice.
    assert sum(1 for _ in out_path.open()) == 1

    got3 = cli("ingest", "--calls", str(calls_path), "--out", str(out_path), "--append", cwd=tmp_path)
    assert got3.returncode == 0, got3.stdout + got3.stderr
    # only --append is allowed to grow the file.
    assert sum(1 for _ in out_path.open()) == 2


# --- 6. freshness is judged per attempt: many stale accepted attempts plus one fresh one leave one item ----------

def test_freshness_is_judged_per_attempt_so_stale_attempts_do_not_inflate_the_item_count(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    held = partition_items("held_out", 20, prefix="freshheld")
    sel = partition_items("selection", 5, prefix="freshmix")
    stale_items, fresh_item = sel[:4], sel[4]
    stale_at = "2026-01-01T00:00:00Z"
    obs = (accepted_block(stale_items, "law", "api-cheap", observed_at=stale_at)
           + accepted_block([fresh_item], "law", "api-cheap", observed_at="2026-11-07T00:00:00Z")
           + accepted_block(held, "law", "api-cheap", observed_at="2026-11-07T00:00:00Z"))
    from datetime import datetime, timezone
    as_of = datetime(2026, 11, 8, tzinfo=timezone.utc)
    policy = certify.derive(obs, cfg, certify.load_declarations(
        decl(max_observation_age_days=7, task_types={"law": {"floor": 0.3}})), as_of=as_of)
    sel_rec = arm_record(policy, "law", "api-cheap")["selection"]
    # 4 stale items dropped entirely, not merged into or inflating the one fresh item's count.
    assert sel_rec["items"] == 1


# --- 7. unobserved_as does not retroactively reject an item that also has a graded run, and an all-unobserved ----
# --- fresh window is undetermined rather than "no change" ---------------------------------------------------------

def test_unobserved_as_rejected_leaves_an_item_with_an_accepted_run_accepted(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 1, prefix="mixeditem")
    held = partition_items("held_out", 20, prefix="mixedheld")
    # one accepted run and one unobserved run of the SAME item -- not a repeated-run case, since only one run
    # is graded, so this must not need a declared repeat_rule.
    obs = ([row(sel[0], "law", "api-cheap", "accepted", run="r1"),
            row(sel[0], "law", "api-cheap", "unobserved", run="r2", reason="timeout")]
           + accepted_block(held, "law", "api-cheap"))
    d = decl(task_types={"law": {"floor": 0.3}}, unobserved_as="rejected")
    del d["repeat_rule"]
    policy = certify.derive(obs, cfg, certify.load_declarations(d))
    sel_rec = arm_record(policy, "law", "api-cheap")["selection"]
    assert sel_rec["items"] == 1
    assert sel_rec["accepted"] == 1


def test_drift_is_undetermined_with_zero_graded_items_when_the_fresh_window_is_all_unobserved(tmp_path):
    cfg, policy = _certified_policy(tmp_path, prefix="allunobs")
    fresh_items = partition_items("selection", 5, prefix="allunobsfresh")
    fresh = [row(i, "law", "api-cheap", "unobserved", reason="ungraded") for i in fresh_items]
    d = certify.load_declarations(decl(task_types={"law": {"floor": 0.5}}, min_items=5))
    report = certify.drift(policy, policy, fresh, d, cfg)
    checks = [c for c in report["contradiction_checks"] if c["task_type"] == "law"]
    assert checks and checks[0]["verdict"] == "undetermined"
    assert checks[0]["graded_items"] == 0


# --- 8. export-policy --target table requires a fallback, and the table output carries it ------------------------

def test_export_policy_table_requires_a_fallback_and_the_table_output_carries_it(tmp_path):
    cfg, policy = _certified_policy(tmp_path, prefix="tablefb")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy))
    out_path = tmp_path / "table.json"
    got = cli("export-policy", "--policy", str(policy_path), "--target", "table", "--out", str(out_path),
              cwd=tmp_path)
    assert got.returncode == 0, got.stdout + got.stderr
    table = json.loads(out_path.read_text())
    assert table["fallback"]["arm"] == policy["fallback"]["arm"]

    no_fallback = dict(policy)
    no_fallback["fallback"] = None
    policy2_path = tmp_path / "policy_no_fallback.json"
    policy2_path.write_text(json.dumps(no_fallback))
    out2_path = tmp_path / "table2.json"
    got = cli("export-policy", "--policy", str(policy2_path), "--target", "table", "--out", str(out2_path),
              cwd=tmp_path)
    assert got.returncode == 2, got.stdout + got.stderr


# --- 9. an assignment's reason, and the as_table entry, both carry label_sources ----------------------------------

def test_assignment_reason_and_as_table_entry_both_carry_label_sources(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 20, prefix="lsel")
    held = partition_items("held_out", 20, prefix="lheld")
    obs = ([dataclasses.replace(row(i, "law", "api-cheap", "accepted"), label_source="dataset") for i in sel]
           + [dataclasses.replace(row(i, "law", "api-cheap", "accepted"), label_source="dataset") for i in held])
    policy = certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.5}})))

    asn = certify.assignments(policy)
    assert "dataset" in asn["law"]["why"]
    assert asn["law"]["label_sources"] == ["dataset"]

    table = certify.as_table(policy)
    entry = next(iter(table["families"]["law"].values()))
    assert entry["label_sources"] == ["dataset"]


# --- 10. an arm priced on selection but using a token kind the price card lacks on held-out is not eligible -------

def test_an_arm_unpriced_on_held_out_only_is_not_eligible_even_though_selection_priced_it(tmp_path):
    cfg = cfgmod.load_config(write_candidates(tmp_path, {
        "mixed": {"deployment": "api", "endpoint": {"base_url": "http://x/v1", "model": "m"},
                 "price_per_mtok": {"fresh_in": 1.0, "out": 1.0}},            # no cached_in price
        "other": {"deployment": "api", "endpoint": {"base_url": "http://x/v1", "model": "o"},
                 "price_per_mtok": {"fresh_in": 3.0, "cached_in": 3.0, "out": 3.0}},
    }))
    sel_m = partition_items("selection", 20, prefix="mixedsel")
    held_m = partition_items("held_out", 20, prefix="mixedheld")
    sel_o = partition_items("selection", 20, prefix="othersel2")
    held_o = partition_items("held_out", 20, prefix="otherheld2")
    obs = ([row(i, "law", "mixed", "accepted", fresh_in=1_000_000) for i in sel_m]            # priced on selection
           + [row(i, "law", "mixed", "accepted", fresh_in=0, cached_in=1_000_000) for i in held_m]  # NOT on held-out
           + accepted_block(sel_o, "law", "other") + accepted_block(held_o, "law", "other"))
    policy = certify.derive(obs, cfg, certify.load_declarations(decl(task_types={"law": {"floor": 0.3}})))
    t = find_task_type(policy, "law")
    assert t["arm"] == "other"
    assert arm_record(policy, "law", "mixed")["priced"] is False


# --- 11. the reference comparison is computed only over held-out items common to both arms, and names why ---------
# --- a task type without any is omitted ----------------------------------------------------------------------------

def test_comparison_uses_only_common_held_out_items_and_names_a_reason_for_what_it_omits(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel1 = partition_items("selection", 20, prefix="cmp1sel")
    held1 = partition_items("held_out", 20, prefix="cmp1held")
    sel2 = partition_items("selection", 20, prefix="cmp2sel")
    held2 = partition_items("held_out", 20, prefix="cmp2held")
    # "law" is served by api-cheap (the single best); "physics" is served ONLY by api-dear, with a held-out
    # item set that is entirely disjoint from api-cheap's -- there is no item both arms were observed on.
    obs = (accepted_block(sel1, "law", "api-cheap") + accepted_block(held1, "law", "api-cheap")
           + accepted_block(sel2, "physics", "api-dear") + accepted_block(held2, "physics", "api-dear"))
    d = certify.load_declarations(decl(task_types={"law": {"floor": 0.3}, "physics": {"floor": 0.3}}))
    policy = certify.derive(obs, cfg, d)
    comp = policy["comparison"]
    assert comp["task_types"] == ["law"]
    assert "physics" in comp["omitted"] and comp["omitted"]["physics"]


# --- 12. repeat_rule accepts a "module:attribute" callable over the graded outcomes -------------------------------

def test_repeat_rule_accepts_a_module_colon_attribute_callable(tmp_path):
    cfg = cfgmod.load_config(two_arm_candidates(tmp_path))
    sel = partition_items("selection", 1, prefix="modcallitem")
    held = partition_items("held_out", 20, prefix="modcallheld")
    # 2 accepted / 1 rejected: "all" would reject the item; the custom rule below (>= 2 accepted) accepts it,
    # so a passing assertion proves the dotted-path callable ran rather than a built-in rule.
    obs = ([row(sel[0], "law", "api-cheap", "accepted", run="r1"),
            row(sel[0], "law", "api-cheap", "accepted", run="r2"),
            row(sel[0], "law", "api-cheap", "rejected", run="r3")]
           + accepted_block(held, "law", "api-cheap"))
    d = certify.load_declarations(decl(
        task_types={"law": {"floor": 0.3}},
        repeat_rule="tests.test_certification_plane:majority_of_two_or_more"))
    policy = certify.derive(obs, cfg, d)
    sel_rec = arm_record(policy, "law", "api-cheap")["selection"]
    assert sel_rec["items"] == 1
    assert sel_rec["accepted"] == 1


# --- the meaning of cached tokens is the caller's declaration, per arm -------------------------------------------

def _body(usage):
    return {"choices": [{"message": {"content": "A"}, "finish_reason": "stop"}], "usage": usage}


def test_cached_tokens_are_read_inside_prompt_tokens_unless_the_arm_is_declared_additive():
    from tierbook.observation import from_chat_completion
    u = {"prompt_tokens": 100, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 60}}
    inside = from_chat_completion(_body(u), item="i", task_type="t", arm="gpt", outcome="accepted")
    beside = from_chat_completion(_body(u), item="i", task_type="t", arm="claude", outcome="accepted",
                                  cache_additive=True)
    assert inside.usage == {"fresh_in": 40, "cached_in": 60, "out": 5}
    assert beside.usage == {"fresh_in": 100, "cached_in": 60, "out": 5}


def test_reported_cache_writes_leave_usage_unknown_rather_than_priced_as_fresh_input():
    from tierbook.observation import from_chat_completion
    u = {"prompt_tokens": 10, "completion_tokens": 4, "prompt_tokens_details": {"cache_write_tokens": 3524}}
    o = from_chat_completion(_body(u), item="i", task_type="t", arm="claude", outcome="accepted", cache_additive=True)
    assert o.usage == {}


def test_ingest_applies_the_additive_meaning_only_to_the_named_arms():
    from tierbook.observation import ingest_chat_log
    u = {"prompt_tokens": 100, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 60}}
    calls = [{"item": "i", "task_type": "t", "arm": a, "response": _body(u)} for a in ("gpt", "claude")]
    grades = [{"item": "i", "arm": a, "outcome": "accepted"} for a in ("gpt", "claude")]
    got = {o.arm: o.usage["fresh_in"] for o in ingest_chat_log(calls, grades, cache_additive_arms=["claude"])}
    assert got == {"gpt": 40, "claude": 100}


def test_a_fixed_cost_arm_is_priced_per_attempt_even_when_its_answers_report_no_usage(tmp_path):
    """A decision model or a distilled student returns a label and no token counts; it is priced from its declared
    usd_per_attempt, so the absence of usage must not make it unpriced the way it does for a metered arm."""
    import json as _json
    from tierbook.config import load_config
    from tierbook.observation import Observation
    cf = tmp_path / "c.json"
    cf.write_text(_json.dumps({"config_format": 2, "families": {}, "candidates": {
        "student": {"deployment": "self_hosted", "endpoint": {"base_url": "http://s.invalid/v1", "model": "s"},
                    "hourly_usd": 0.1}}}))
    cfg = load_config(cf)
    d = certify.load_declarations({
        "alpha": 0.05, "bound": "tierbook.bounds:wilson", "holdout_fraction": 0.5, "split_salt": "s",
        "unobserved_as": "rejected", "max_observation_age_days": None, "held_out_correction": "none", "holdout_ladder": 1,
        "task_types": {"t": {"floor": 0.5}}, "usd_per_attempt": {"student": {"usd": 0.000001, "source": "test"}}})
    obs = [Observation(item=f"i{i}", task_type="t", arm="student", outcome="accepted") for i in range(200)]
    p = certify.derive(obs, cfg, d)
    assert p["task_types"]["t"]["status"] == "certified"
    assert p["task_types"]["t"]["held_out"]["spend_per_accepted_usd"] == pytest.approx(0.000001)


def _policy_file(tmp_path, status, arm):
    p = {"task_types": {"finnews": {"status": status, "arm": arm, "reason": "r"}},
         "observations_digest": "d", "guarantee": "g", "fallback": {"arm": "x"}}
    f = tmp_path / "policy.json"
    f.write_text(json.dumps(p))
    return f


def _learn_spec(tmp_path, router=None):
    e = {"task": "finnews-v1", "question": "q", "options": ["a", "b"], "kind": "choice"}
    if router:
        e["router"] = router
    f = tmp_path / "spec.json"
    f.write_text(json.dumps([e]))
    return f


def test_prismyra_learn_export_sets_the_router_of_the_certified_student(tmp_path):
    from tierbook import cli
    arms = tmp_path / "arms.json"
    arms.write_text(json.dumps({"student-w3": {"mode": "ab", "ratio": 10000, "student_path": "s.json"},
                                "prismyra": None}))
    out = tmp_path / "out.json"
    rc = cli.main(["export-policy", "--policy", str(_policy_file(tmp_path, "certified", "student-w3")),
                   "--target", "prismyra-learn", "--learn-spec", str(_learn_spec(tmp_path)), "--arm-router",
                   str(arms), "--signal", "finnews=finnews-v1", "--out", str(out), "--allow-unversioned"])
    assert rc == 0
    assert json.loads(out.read_text())[0]["router"] == {"mode": "ab", "ratio": 10000, "student_path": "s.json"}


def test_prismyra_learn_export_removes_the_router_when_nothing_is_certified(tmp_path):
    from tierbook import cli
    arms = tmp_path / "arms.json"
    arms.write_text(json.dumps({"student-w3": {"mode": "ab", "ratio": 10000, "student_path": "s.json"}}))
    out = tmp_path / "out.json"
    spec = _learn_spec(tmp_path, router={"mode": "ab", "ratio": 10000, "student_path": "old.json"})
    rc = cli.main(["export-policy", "--policy", str(_policy_file(tmp_path, "unconfirmed", "student-w3")),
                   "--target", "prismyra-learn", "--learn-spec", str(spec), "--arm-router", str(arms),
                   "--signal", "finnews=finnews-v1", "--out", str(out)])
    assert rc == 0
    assert "router" not in json.loads(out.read_text())[0]


def test_prismyra_learn_export_refuses_an_arm_prismyra_cannot_serve(tmp_path):
    from tierbook import cli
    arms = tmp_path / "arms.json"
    arms.write_text(json.dumps({"student-w3": {"mode": "ab", "ratio": 10000, "student_path": "s.json"}}))
    rc = cli.main(["export-policy", "--policy", str(_policy_file(tmp_path, "certified", "claude-haiku-4-5")),
                   "--target", "prismyra-learn", "--learn-spec", str(_learn_spec(tmp_path)), "--arm-router",
                   str(arms), "--signal", "finnews=finnews-v1", "--out", str(tmp_path / "o.json")])
    assert rc == 2


def _versioned_policy(tmp_path, entry):
    p = {"task_types": {"finnews": {"status": "certified", "reason": "r", **entry}},
         "observations_digest": "d", "guarantee": "g", "fallback": {"arm": "x"}}
    f = tmp_path / "policy.json"
    f.write_text(json.dumps(p))
    return f


#: Version strings as Prismyra's observation writer stamps them (an artifact, and the fallback's serving stack).
STUDENT_V = "student:0f3c9a1b2d4e5f60718293a4b5c6d7e8+package:0.5.1"
PRISMYRA_V = "backbone:littlemex/prismyra-decision|package:0.5.1|spec:5d41402abc4b"


def _export_learn(tmp_path, policy, spec=None, extra=()):
    from tierbook import cli
    arms = tmp_path / "arms.json"
    arms.write_text(json.dumps({"student": {"mode": "confidence", "tau": 0.9, "student_path": "s.json"},
                                "routed": {"mode": "confidence", "tau": 0.9, "student_path": "s.json"},
                                "prismyra": None}))
    out = tmp_path / "out.json"
    rc = cli.main(["export-policy", "--policy", str(policy), "--target", "prismyra-learn", "--learn-spec",
                   str(spec or _learn_spec(tmp_path)), "--arm-router", str(arms), "--signal", "finnews=finnews-v1",
                   "--out", str(out), *extra])
    return rc, out


def _record_of(tmp_path, out):
    return json.loads((tmp_path / json.loads(out.read_text())[0]["admission"]["record"]).read_text())


def test_prismyra_learn_export_writes_an_admission_record_bound_to_the_judged_version(tmp_path):
    import hashlib
    policy = _versioned_policy(tmp_path, {"arm": "student", "arm_version": STUDENT_V})
    rc, out = _export_learn(tmp_path, policy)
    assert rc == 0
    entry = json.loads(out.read_text())[0]
    assert entry["admission"] == {"mode": "external", "record": "out.json.admission/finnews-v1.json"}
    rec = _record_of(tmp_path, out)
    assert rec == {"format": 1, "tag": "finnews-v1", "version": STUDENT_V, "router": entry["router"],
                   "admitted_by": "tierbook export-policy",
                   "evidence": {"uri": str(policy.resolve()), "sha256": hashlib.sha256(policy.read_bytes()).hexdigest()}}


def test_a_cascade_record_binds_the_named_student_component(tmp_path):
    policy = _versioned_policy(tmp_path, {"arm": "routed", "arm_version": None,
                                          "component_versions": {"student": STUDENT_V, "prismyra": PRISMYRA_V}})
    assert _export_learn(tmp_path, policy)[0] == 2
    assert _export_learn(tmp_path, policy, extra=["--served-student", "routed=teacher"])[0] == 2
    rc, out = _export_learn(tmp_path, policy, extra=["--served-student", "routed=student"])
    assert rc == 0 and _record_of(tmp_path, out)["version"] == STUDENT_V


def test_an_unversioned_policy_is_refused_unless_allowed(tmp_path, capsys):
    spec = _learn_spec(tmp_path)
    raw = json.loads(spec.read_text())
    raw[0]["admission"] = {"mode": "external", "record": "old.json"}
    spec.write_text(json.dumps(raw))
    policy = _versioned_policy(tmp_path, {"arm": "student"})
    assert _export_learn(tmp_path, policy, spec=spec)[0] == 2
    rc, out = _export_learn(tmp_path, policy, spec=spec, extra=["--allow-unversioned"])
    assert rc == 0 and "admission" not in json.loads(out.read_text())[0]
    assert "no admission record (--allow-unversioned)" in capsys.readouterr().out
    assert json.loads((tmp_path / "out.json.provenance.json").read_text())["allow_unversioned"] is True


def test_an_operators_own_admission_is_not_replaced(tmp_path):
    spec = _learn_spec(tmp_path)
    raw = json.loads(spec.read_text())
    raw[0]["admission"] = {"mode": "confidence", "tau": 0.9}
    spec.write_text(json.dumps(raw))
    assert _export_learn(tmp_path, _versioned_policy(tmp_path, {"arm": "student", "arm_version": STUDENT_V}),
                         spec=spec)[0] == 2


def test_a_withdrawn_certificate_removes_the_external_admission_and_its_record(tmp_path):
    policy = _versioned_policy(tmp_path, {"arm": "student", "arm_version": STUDENT_V})
    rc, out = _export_learn(tmp_path, policy)
    rec = tmp_path / "out.json.admission" / "finnews-v1.json"
    assert rc == 0 and rec.exists()
    withdrawn = _versioned_policy(tmp_path, {"arm": "student", "arm_version": STUDENT_V, "status": "inconclusive"})
    rc, out = _export_learn(tmp_path, withdrawn, spec=out)
    e = json.loads(out.read_text())[0]
    assert rc == 0 and "router" not in e and "admission" not in e and not rec.exists()


def test_an_unconfirmed_entry_gets_a_record_only_when_allowed(tmp_path):
    policy = _versioned_policy(tmp_path, {"arm": "student", "arm_version": STUDENT_V, "status": "unconfirmed"})
    rc, out = _export_learn(tmp_path, policy)
    assert rc == 0 and "admission" not in json.loads(out.read_text())[0]
    rc, out = _export_learn(tmp_path, policy, extra=["--allow-unconfirmed"])
    assert rc == 0 and _record_of(tmp_path, out)["version"] == STUDENT_V


def test_a_tag_that_cannot_name_a_file_is_refused(tmp_path):
    from tierbook import cli
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([{"task": "../x", "question": "q", "options": ["a", "b"], "kind": "choice"}]))
    arms = tmp_path / "arms.json"
    arms.write_text(json.dumps({"student": {"mode": "ab", "ratio": 1, "student_path": "s.json"}}))
    rc = cli.main(["export-policy", "--policy", str(_versioned_policy(tmp_path, {"arm": "student",
                                                                                "arm_version": STUDENT_V})),
                   "--target", "prismyra-learn", "--learn-spec", str(spec), "--arm-router", str(arms),
                   "--signal", "finnews=../x", "--out", str(tmp_path / "o.json")])
    assert rc == 2 and not (tmp_path / "x.json").exists()
