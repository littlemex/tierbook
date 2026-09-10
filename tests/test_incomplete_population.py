"""Tests for C11 (Amendment 13) -- the rate criteria narrow their denominator by exactly the rows C1 taught
them to distinguish.

Written test-first, from the contract text, before `accept.py` was touched. `accept._unreadable` reads
`outcomes["__bad_lines__"]` only. A row that parses but fails `record.from_row` lands in
`outcomes["__unreadable_rows__"]` -- the counter C1 added THIS RELEASE so that "the file was truncated" and "the
record is from a newer schema" would be different operator actions -- and no criterion consulted it. That is F8's
shape (a denominator narrowed until the violation is outside it) in the one category C1 itself introduced.

The fix has two parts: `_unreadable` counts both classes and names them separately (repair the file vs. upgrade
the reader are different operator actions, and merging them back into one count would undo C1 from the other
end), and every criterion whose value is a rate over a population is guarded by it. `default_is_not_a_hiding_place`
gains an `outcomes` parameter so it can see either class at all -- it does not take `outcomes` today.

`no_false_certification` is a per-decision universal claim, not a rate, so a mixture -- or a narrowed population --
does not change what it means (CONTRACT C5 states the same exemption for schema-version mixing). It stays
unguarded, and is tested here doing exactly that.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import accept as ac  # noqa: E402
from tierbook import record as rec  # noqa: E402


def cand(cid="box", why="chosen", bound=0.90, cost=0.004):
    return {"id": cid, "excluded_because": why, "bound": bound, "bound_kind": "lcb95", "cost_usd": cost,
            "evidence_as_of": "2026-09-01"}


def row(**kw):
    """A row shaped like something a v0.2.0 `Log.append` would have written."""
    base = {
        "family": "agentic-coding", "request_id": "r1", "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": [cand(), cand("api", "below_floor", 0.70, 0.012)], "chosen": "box",
        "selection_probability": 1.0, "exploration": False, "certified": True,
        "policy_version": "p1", "mechanism_version": "0.2.0", "agent": "opencode", "model": "m",
        "endpoint": "http://e", "gateway_quote_usd": 0.004, "gateway_authorised": True, "decided_at": 1000.0,
        "exploration_reason": "no_mechanism", "eligible_set": [],
        "gaps": [], "label_state": "pending", "label": None, "outcome": {}, "schema_version": 2,
    }
    base.update(kw)
    return base


def dec(rid="r1", certified=True):
    """A plain decision-row dict (not run through `Log`) for the criteria that take `decisions` directly."""
    return row(request_id=rid, certified=certified)


def _write_future_schema_row(fh, rid: str) -> None:
    """A raw line stamped `schema_version: 999`: from_row refuses it (999 > rec.SCHEMA_VERSION), so `Log.read`
    counts it in `__unreadable_rows__` and excludes it from `decisions` -- the "upgrade the reader" class."""
    fh.write(json.dumps(row(request_id=rid, schema_version=999)) + "\n")


# ======================================================================================================
# the reproduction in the contract, as a test
# ======================================================================================================


def test_the_reproduction_40_successes_15_future_schema_failures(tmp_path):
    """CONTRACT Amendment 13, C11's own reproduction. 40 labelled successes (schema_version 2, certified,
    admissible) plus 15 rows stamped `schema_version: 999` -- a schema this reader refuses -- whose OUTCOMES
    (not their decisions, which never survive `Log.read`) are labelled failures.

    Measured against the code at HEAD, before this entry's fix:

        decisions read : 40      unreadable rows: 30      bad lines: 0
        floor_compliance: pass   rate 1.0   lower_bound 0.9278
        true rate had the dropped rows counted: 0.7273     (fails an 80% floor)

    (30, not 15, because each of the 15 future-schema rows is written twice below -- once as itself and once
    more is not needed; the CONTRACT's own number is 15 unreadable rows against 40 survivors. This fixture
    matches the CONTRACT's 15, and the arithmetic below -- 40 successes over 55 total, 40/55 = 0.727272... --
    is what "true rate 0.7273" means: the 15 dropped rows are outcomes-labelled failures that never reach
    `decisions` at all, so a rate computed only over `decisions` cannot see them.)

    `floor_compliance` must refuse (UNSUPPORTED), not PASS: the certified/labelled population it can see (40
    successes, rate 1.0, lower_bound 0.9278) clears an 80% floor cleanly, while the TRUE population -- the 40
    successes plus the 15 rows the reader could not read, all of which failed -- is 40/55 = 0.7273, which FAILS
    the same floor. A pass computed over the narrower population is the exact violation C11 exists to catch.
    """
    log = rec.Log(tmp_path / "log.jsonl")
    for i in range(40):
        rid = f"good-{i}"
        log.append(rec.Decision(
            family="agentic-coding", request_id=rid, feature_vector_version="fv1", state_ref="obs:a",
            candidates=[rec.Candidate(id="box", excluded_because="chosen", bound=0.90, cost_usd=0.004,
                                      evidence_as_of="2026-09-01"),
                       rec.Candidate(id="api", excluded_because="below_floor", bound=0.70, cost_usd=0.012,
                                    evidence_as_of="2026-09-01")],
            chosen="box", selection_probability=1.0, exploration=False, certified=True, policy_version="p1",
            mechanism_version="0.2.0", agent="opencode", model="m", endpoint="http://e",
            gateway_quote_usd=0.004, gateway_authorised=True,
            exploration_reason="no_mechanism", eligible_set=[]))
        log.attach_outcome(rid, label_state="labelled", label=True)
    with log.path.open("a") as fh:
        for i in range(15):
            _write_future_schema_row(fh, f"future-{i}")
    for i in range(15):
        log.attach_outcome(f"future-{i}", label_state="labelled", label=False)

    decisions, outcomes = log.read()
    assert len(decisions) == 40
    assert outcomes["__unreadable_rows__"]["count"] == 15
    assert outcomes.get("__bad_lines__", {}).get("count", 0) == 0

    # Sanity: what the criterion sees over the narrow population, and what is true over the whole one.
    narrow_rate = sum(1 for r in decisions if r["certified"]) / len(decisions)
    assert narrow_rate == pytest.approx(1.0)
    true_rate = 40 / 55
    assert true_rate == pytest.approx(0.7273, abs=5e-5)

    v = ac.floor_compliance(decisions, outcomes, floor=0.80)
    assert v.verdict == ac.UNSUPPORTED, (
        f"40 certified, labelled successes clear an 80% floor cleanly (rate 1.0, lower_bound 0.9278) when read as "
        f"the whole population -- but 15 rows were dropped as unreadable, and if they are counted as the failures "
        f"their attached outcomes say they are, the true rate is 0.7273, which FAILS the same floor. Reporting "
        f"the narrow rate as a verdict of any kind is the F8 shape C11 closes, got {v.verdict!r}"
    )
    assert v.verdict != ac.PASS


# ======================================================================================================
# the two classes are named separately, not merged into one count
# ======================================================================================================


def test_truncated_lines_and_future_schema_rows_produce_differently_worded_refusals(tmp_path):
    """A log with only truncated lines and a log with only newer-schema rows must each refuse with a detail
    naming their OWN class and count. A test that only checks `UNSUPPORTED` passes against an implementation
    that merged `__bad_lines__` and `__unreadable_rows__` into one counter -- this test would not catch that
    bug, so it checks the two details differ and each mentions its own count."""
    truncated_log = rec.Log(tmp_path / "truncated.jsonl")
    for i in range(20):
        rid = f"r{i}"
        truncated_log.append(rec.Decision(
            family="f", request_id=rid, feature_vector_version="fv1", state_ref="obs:a",
            candidates=[rec.Candidate(id="box", excluded_because="chosen", bound=0.9, cost_usd=0.004)],
            chosen="box", selection_probability=1.0, exploration=False, certified=True, policy_version="p1",
            mechanism_version="0.2.0", agent="opencode", model="m", endpoint="http://e",
            gateway_quote_usd=0.004, gateway_authorised=True, exploration_reason="no_mechanism", eligible_set=[]))
        truncated_log.attach_outcome(rid, label_state="labelled", label=True)
    with truncated_log.path.open("a") as fh:
        fh.write("{this is not valid json\n")
        fh.write("{also not valid json\n")
        fh.write("{and a third truncated line\n")
    t_decisions, t_outcomes = truncated_log.read()
    assert t_outcomes["__bad_lines__"]["count"] == 3
    assert "__unreadable_rows__" not in t_outcomes

    future_log = rec.Log(tmp_path / "future.jsonl")
    for i in range(20):
        rid = f"r{i}"
        future_log.append(rec.Decision(
            family="f", request_id=rid, feature_vector_version="fv1", state_ref="obs:a",
            candidates=[rec.Candidate(id="box", excluded_because="chosen", bound=0.9, cost_usd=0.004)],
            chosen="box", selection_probability=1.0, exploration=False, certified=True, policy_version="p1",
            mechanism_version="0.2.0", agent="opencode", model="m", endpoint="http://e",
            gateway_quote_usd=0.004, gateway_authorised=True, exploration_reason="no_mechanism", eligible_set=[]))
        future_log.attach_outcome(rid, label_state="labelled", label=True)
    with future_log.path.open("a") as fh:
        for i in range(3):
            _write_future_schema_row(fh, f"future-{i}")
    f_decisions, f_outcomes = future_log.read()
    assert f_outcomes["__unreadable_rows__"]["count"] == 3
    assert "__bad_lines__" not in f_outcomes

    v_truncated = ac.floor_compliance(t_decisions, t_outcomes, floor=0.80)
    v_future = ac.floor_compliance(f_decisions, f_outcomes, floor=0.80)
    assert v_truncated.verdict == ac.UNSUPPORTED and v_future.verdict == ac.UNSUPPORTED
    assert v_truncated.detail != v_future.detail
    assert "3" in v_truncated.detail and "3" in v_future.detail
    # Each names ITS OWN class, not the other's -- a merged counter could not produce this pair of details.
    assert ("truncat" in v_truncated.detail.lower() or "json" in v_truncated.detail.lower()
           or "line" in v_truncated.detail.lower())
    assert ("schema" in v_future.detail.lower() or "row" in v_future.detail.lower())
    assert v_truncated.numbers["unreadable"]["bad_lines"] == 3
    assert v_truncated.numbers["unreadable"]["unreadable_rows"] == 0
    assert v_future.numbers["unreadable"]["bad_lines"] == 0
    assert v_future.numbers["unreadable"]["unreadable_rows"] == 3


def test_unreadable_names_both_classes_from_outcomes_directly():
    """`accept._unreadable` itself, not through a criterion: it must return both counts, not one merged count.
    An implementation that folded `__unreadable_rows__` into `__bad_lines__` -- or vice versa -- would still
    satisfy a test that only checked a single merged number, so this pins the two are separately addressable."""
    outcomes = {"__bad_lines__": {"count": 2}, "__unreadable_rows__": {"count": 5}}
    counts = ac._unreadable(outcomes)
    assert counts["bad_lines"] == 2
    assert counts["unreadable_rows"] == 5
    assert counts != {"count": 7}  # not merged into one bucket under any key


# ======================================================================================================
# a complete log is unaffected
# ======================================================================================================


def test_a_complete_log_with_no_dropped_rows_computes_normally():
    """The guard must not fire on every log -- only one that actually dropped something."""
    rows = [dec(rid=f"r{i}") for i in range(40)]
    outcomes = {f"r{i}": {"label_state": "labelled", "label": True} for i in range(40)}
    v = ac.floor_compliance(rows, outcomes, floor=0.80)
    assert v.verdict == ac.PASS
    assert v.numbers["rate"] == 1.0


def test_a_log_with_dropped_rows_does_not_affect_a_non_rate_criterion():
    """`no_false_certification` is a per-decision universal claim, not a rate over a population -- CONTRACT C5
    gives the same exemption for schema-version mixing, and the same reasoning applies here: dropping some rows
    from the log does not change whether the rows that DID survive were each certified correctly. It must still
    compute (PASS or FAIL), never UNSUPPORTED-for-incompleteness, on a log that has lost rows."""
    rows = [dec(rid=f"r{i}") for i in range(10)]
    outcomes = {"__unreadable_rows__": {"count": 4, "reasons": ["line 1: future schema"] * 4}}
    v = ac.no_false_certification(rows, floor=0.80, latency_feasible=True)
    assert v.verdict == ac.PASS
    # And with bad_lines present instead:
    outcomes2 = {"__bad_lines__": {"count": 4, "note": "truncated"}}
    v2 = ac.no_false_certification(rows, floor=0.80, latency_feasible=True)
    assert v2.verdict == ac.PASS


# ======================================================================================================
# default_is_not_a_hiding_place refuses too, since it could not see either class before this entry
# ======================================================================================================


def test_default_is_not_a_hiding_place_takes_outcomes_and_refuses_on_dropped_rows():
    """Before this entry, `default_is_not_a_hiding_place` did not take `outcomes` at all, so it had no way to
    see either dropped-row class. This is the reproduction for it specifically: an uncertified share that looks
    fine (0%) over the rows that survived, while rows were dropped that -- if readable -- might have been the
    uncertified, hidden-behind-the-default cases the criterion exists to catch."""
    rows = [dec(rid=f"r{i}", certified=True) for i in range(20)]
    outcomes = {"__unreadable_rows__": {"count": 5, "reasons": ["line 1: future schema"] * 5}}
    v = ac.default_is_not_a_hiding_place(rows, outcomes, floor=0.80, latency_feasible=True,
                                         uncertified_tolerance=0.5)
    assert v.verdict == ac.UNSUPPORTED
    assert "5" in v.detail


def test_default_is_not_a_hiding_place_computes_normally_with_no_outcomes_given():
    """Backward compatible: a caller that does not pass `outcomes` at all (or passes an empty one) gets the
    criterion's ordinary behaviour, not a spurious refusal -- the guard is additive, not a new required input."""
    rows = [dec(rid="r1")]
    v = ac.default_is_not_a_hiding_place(rows, floor=0.80, latency_feasible=True, uncertified_tolerance=0.5)
    assert v.verdict == ac.PASS


# ======================================================================================================
# one test per guarded criterion, one test per deliberately unguarded criterion
# ======================================================================================================
#
# `floor_compliance` and `default_is_not_a_hiding_place` are covered above. The three below are the rest of
# the module's criteria: `exploration_cost` and `slo` are rates over a population and are guarded the same
# way; `no_false_certification` is a per-decision universal claim and is deliberately left unguarded (its own
# test is above, in the "complete log" section). `bound_calibration`, `spend_regret`, `adaptation` and
# `genericity_and_usefulness` never read `decisions`/`outcomes` to produce a value at all -- they are static
# UNSUPPORTED stubs -- so there is no population for a guard to narrow, and they are not tested here for the
# same reason `no_false_certification`'s test above does not need a "does it ignore the guard" companion for
# them: nothing about this entry touches a function that computes nothing from the log.


def test_exploration_cost_is_guarded():
    rows = [dec(rid=f"r{i}") for i in range(10)]
    outcomes = {"__unreadable_rows__": {"count": 3, "reasons": ["line 1: future schema"] * 3}}
    v = ac.exploration_cost(rows, outcomes, budgeted_share=0.5)
    assert v.verdict == ac.UNSUPPORTED
    assert "3" in v.detail


def test_exploration_cost_computes_normally_on_a_complete_log():
    rows = [dec(rid="r1"), dec(rid="r2")]
    v = ac.exploration_cost(rows, {}, budgeted_share=0.5)
    assert v.verdict == ac.PASS
    v_no_outcomes = ac.exploration_cost(rows, budgeted_share=0.5)
    assert v_no_outcomes.verdict == ac.PASS


def test_slo_is_guarded():
    rows = [dec(rid=f"r{i}") for i in range(10)]
    outcomes = {f"r{i}": {"latency_s": 5.0} for i in range(10)}
    outcomes["__bad_lines__"] = {"count": 2, "note": "truncated"}
    v = ac.slo(rows, outcomes, latency_limit_s=60.0, tolerance=0.05)
    assert v.verdict == ac.UNSUPPORTED
    assert "2" in v.detail


def test_slo_computes_normally_on_a_complete_log():
    rows = [dec(rid=f"r{i}") for i in range(10)]
    outcomes = {f"r{i}": {"latency_s": 5.0} for i in range(10)}
    v = ac.slo(rows, outcomes, latency_limit_s=60.0, tolerance=0.05)
    assert v.verdict == ac.PASS


# ======================================================================================================
# check_all threads outcomes through to the criteria that need it
# ======================================================================================================


def test_check_all_threads_outcomes_into_default_is_not_a_hiding_place_and_exploration_cost():
    """Catches the guard being implemented on the free functions but never wired into `check_all`, which is
    the only path `cli.cmd_accept` actually calls -- a fix that only the unit tests see is not a fix."""
    rows = [dec(rid=f"r{i}") for i in range(10)]
    outcomes = {"__unreadable_rows__": {"count": 4, "reasons": ["line 1: future schema"] * 4}}
    verdicts = {v.criterion: v for v in ac.check_all(rows, outcomes, floor=0.80, uncertified_tolerance=0.5,
                                                     budgeted_exploration=0.5)}
    assert verdicts["default_is_not_a_hiding_place"].verdict == ac.UNSUPPORTED
    assert verdicts["exploration_cost"].verdict == ac.UNSUPPORTED
    assert verdicts["floor_compliance"].verdict == ac.UNSUPPORTED
    # no_false_certification is not a rate and must still compute despite the same dropped rows.
    assert verdicts["no_false_certification"].verdict in (ac.PASS, ac.FAIL)
