"""This repository's own mistakes, as tests.

Each of these encodes a claim this project made and then measured to be wrong. If a future change makes one
of them pass differently, the change has undone a correction that cost real money to find.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tierbook import policy  # noqa: E402
from tierbook.table import Unvalidated, compile_to_file, lookup  # noqa: E402
from tierbook.validate import ASSIGNED, PROVISIONAL, REFUSED  # noqa: E402

REG = ROOT / "examples" / "ledger" / "tiers"
VAL = ROOT / "examples" / "ledger" / "validation"
FAM = "tool-agent-user-retail"
REF = "api-strong-a"
# A hypothetical, kept so that the margin gate below is still exercised on the tier whose bound fails.
# It is the figure a published number in this repository once used -- the observed per-task time times an
# ASSUMED sixteen requests in flight -- and the run recorded no timestamps, so it was never measured. It
# survives here as a way to reach a code path, never as a cost. `test_boundary.py` pins what happens without
# it, which is that the rule prefers the cheap API and the refused margins stop being reached at all.
TP = {FAM: 4364}


def compile_at(margin, tmp_path, validations=VAL):
    return compile_to_file(policy.load_registry(REG), {FAM: REF}, tmp_path / "t.json",
                           margin=margin, throughput_per_family=TP, today="2026-08-30",
                           validations=validations)


# --- the margin that failed out of fold ---------------------------------------------------------


@pytest.mark.parametrize("margin", [0.15, 0.20])
def test_a_margin_the_calibration_fold_liked_is_refused_by_the_held_out_fold(margin, tmp_path):
    """The calibration fold chose the self-hosted tier at these margins and the held-out fold does not.

    Measured: calibration bound -0.130 on 20 items, held-out bound -0.241 on 115. The saving was real and
    the quality claim was not. A compiler that returned `assigned` here would ship that mistake.
    """
    t = compile_at(margin, tmp_path)
    entry = t["families"][FAM]["cannot_reject"]
    assert entry["chosen"] == ["self-hosted-a"], "the calibration fold still picks it; that is the point"
    assert entry["status"] == REFUSED
    assert "OUTSIDE the margin" in entry["validation"]["reason"]
    assert entry["validation"]["holdout"]["lower_bound"] == pytest.approx(-0.2407, abs=5e-4)


def test_the_margin_that_did_hold_is_assigned(tmp_path):
    t = compile_at(0.25, tmp_path)
    entry = t["families"][FAM]["cannot_reject"]
    assert entry["status"] == ASSIGNED
    assert "inside the margin" in entry["validation"]["reason"]


def test_a_refused_entry_cannot_be_routed_without_the_awkward_flag(tmp_path):
    t = compile_at(0.15, tmp_path)
    with pytest.raises(Unvalidated):
        lookup(t, FAM, request_can_reject=False)
    arrangement, _ = lookup(t, FAM, request_can_reject=False, allow_unvalidated=True)
    assert arrangement.head == "self-hosted-a"


# --- the ranking that swapped between folds -----------------------------------------------------


def test_the_two_close_candidates_swapped_rank_between_folds(tmp_path):
    """At n=20 the order of two candidates within ten points of each other is not reliable.

    Calibration ranked them (self-hosted, cheap) at -0.130 and -0.210; the held-out fold ranked the same two
    (cheap, self-hosted) at -0.102 and -0.241. The compiler reports the instability rather than hiding it,
    because a reader deciding whether to trust the entry needs it more than they need the winner.
    """
    t = compile_at(0.25, tmp_path)
    rs = t["families"][FAM]["rank_stability"]
    assert rs["stable"] is False
    assert rs["calibration_order"] == ["self-hosted-a", "api-cheap-a"]
    assert rs["holdout_order"] == ["api-cheap-a", "self-hosted-a"]


# --- a calibration fold cannot validate itself ---------------------------------------------------


def test_without_a_held_out_fold_nothing_is_ever_assigned(tmp_path):
    t = compile_at(0.25, tmp_path, validations=None)
    for label in ("cannot_reject", "can_reject"):
        assert t["families"][FAM][label]["status"] == PROVISIONAL
        assert "no held-out fold" in t["families"][FAM][label]["validation"]["reason"]


def test_a_held_out_fold_that_reuses_the_calibration_items_validates_nothing(tmp_path):
    """The fold-collision gate, exercised through the items rather than through the label.

    This test used to fake the collision by copying the calibration record's cohort *string*, which worked
    only because the gate compared hand-written labels -- and that is the defect the content-addressed cohort
    closes. So the fake had to change with the fix: the held-out record now points at the calibration fold's
    own evidence artifact, which is a real collision rather than a naming one, and the gate must still catch
    it. A gate that only ever saw the label version was never tested against an attacker who renames.
    """
    val = json.loads((VAL / "tau-bench-retail-test.json").read_text())
    for tier_id, entry in val["tiers"].items():
        cal = json.loads((REG / f"{tier_id}.json").read_text())["families"][FAM].get("evidence")
        if cal:
            entry["evidence"] = cal          # the calibration fold's own items, under a held-out record
    val.pop("cohort", None)
    d = tmp_path / "val"
    d.mkdir()
    (d / "same.json").write_text(json.dumps(val))
    t = compile_at(0.25, tmp_path, validations=d)
    entry = t["families"][FAM]["cannot_reject"]
    assert entry["status"] == PROVISIONAL
    assert "shares its items with calibration" in entry["validation"]["reason"]


# --- nesting is never assumed --------------------------------------------------------------------


def test_the_evidence_block_reports_crossovers_so_nesting_is_not_taken_on_faith(tmp_path):
    """The held-out fold's crossovers, now derived rather than read out of a stored summary.

    The count is the same 6 and 9 it always was. What changed is where it comes from: this test used to read
    `paired_vs_reference` straight out of the validation JSON, so it would have kept passing against a stored
    number nobody could check. Deriving it from the artifact means the assertion now also proves the
    derivation agrees with the figure this project published.
    """
    from tierbook.evidence import load, paired

    t = compile_at(0.25, tmp_path)
    ev = t["families"][FAM]["evidence"]
    assert "crossovers" in ev and "nested" in ev

    val = json.loads((VAL / "tau-bench-retail-test.json").read_text())
    root = ROOT / "examples" / "ledger"
    ref = load(val["tiers"][REF]["evidence"]["path"], ledger_root=root)
    crossovers = {}
    for tier_id, entry in val["tiers"].items():
        if tier_id == REF:
            continue
        cand = load(entry["evidence"]["path"], ledger_root=root)
        crossovers[tier_id] = paired(cand, ref).candidate_only
    assert crossovers == {"self-hosted-a": 6, "api-cheap-a": 9}


# --- an unmeasured family is refused, never routed to the cheapest -------------------------------


def test_an_unmeasured_family_raises_rather_than_falling_through_to_the_cheapest(tmp_path):
    t = compile_at(0.25, tmp_path)
    with pytest.raises(KeyError) as e:
        lookup(t, "some-family-nobody-measured", request_can_reject=False)
    assert "Measure the family" in str(e.value)


# --- the transport failure that would have published a false claim ------------------------------


def test_a_tier_that_could_not_be_addressed_is_not_recorded_as_a_zero():
    """One tier scored 0 of 20 on its first arm because the endpoint refused the request shape.

    That is an invalid measurement, not a capability. The shipped record for that tier carries the
    restriction that caused it, so the next person to measure it knows to use the other wire first.
    """
    rec = json.loads((REG / "api-cheap-a.json").read_text())
    restrictions = " ".join(rec["adapter"]["restrictions"])
    assert "reasoning_effort" in restrictions and "responses wire" in restrictions
    assert rec["families"][FAM]["solved"] > 0, "the recorded outcome must be the one measured properly"
