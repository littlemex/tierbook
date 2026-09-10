"""Tests for C5 -- a pooling rule, or a refusal to pool.

CONTRACT (docs/changes/v0.2.0-scope/CONTRACT.md, C5) says: when `accept.check_all`'s decisions carry more than one
`schema_version` and `pool_across_versions` is false, every criterion whose value depends on the mixture returns
`UNSUPPORTED`, with a detail naming the versions present and the count in each -- `floor_compliance`,
`default_is_not_a_hiding_place`, `exploration_cost`, `spend_regret`. `no_false_certification` does NOT refuse: it is
a per-decision universal claim, not a rate, so a mixture does not change what it means. With
`pool_across_versions=True` the criteria compute and every affected verdict's detail says the versions were pooled
on the caller's instruction.

Amendment 9 narrows this: the guard applies only where a criterion would otherwise PRODUCE a value. Compute first;
if the result is already `UNSUPPORTED` for the criterion's own reason, its detail is kept unchanged; only a `PASS`
or a `FAIL` is replaced by the mixture refusal. `spend_regret` is an unimplemented stub that always returns
`UNSUPPORTED` on its own account, so on a mixed log it must keep ITS OWN message, not the mixture one -- the
"refuse everything" implementation (correct before amendment 9, wrong after it) would send an operator to fix their
log when the real blocker is that no estimator exists at all.

THE CENTRE (Amendment 8, "C5's number, from the same journey pass"): eight v0.1.0 rows logged when no exploration
mechanism existed, plus two v0.2.0 rows that both explored, make `exploration_cost` report one pooled number, 20%,
which PASSES a 25% budget -- while the v0.2.0 mechanism's own rate over the decisions it was eligible to explore is
100%, four times over. Nothing in the unpooled report distinguishes the two mechanisms. `test_centre_...` below
builds exactly that log and asserts the verdict is no longer a pass.

Only C5 is in scope here. C1's reader, C3's draw and C6's freshness fix each have their own test files.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import accept as ac  # noqa: E402
from tierbook import record as rec  # noqa: E402


# ======================================================================================================
# fixture builders
# ======================================================================================================


def cand(cid="box", why="chosen", bound=0.90, cost=0.004):
    return {"id": cid, "excluded_because": why, "bound": bound, "bound_kind": "lcb95", "cost_usd": cost,
            "evidence_as_of": "2026-09-01"}


def v1_row(rid="r1", certified=True, chosen="box", candidates=None, exploration=False):
    """A row shaped exactly like something a v0.1.0 writer produced: no `schema_version` key, no
    `exploration_reason`/`eligible_set` keys -- those did not exist yet. This is how `record.from_row` decides a
    row is version 1: the key's ABSENCE, not a convention this file types in. Matches the shape of the real
    fixture at `docs/verify/v0.1.0-decisions.jsonl` field-for-field."""
    return {
        "family": "agentic-coding", "request_id": rid, "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": candidates or [cand(), cand("api", "below_floor", 0.70, 0.012)], "chosen": chosen,
        "selection_probability": 1.0, "exploration": exploration, "certified": certified,
        "policy_version": "p1", "mechanism_version": "0.1.0", "agent": "opencode", "model": "m",
        "endpoint": "http://e", "gateway_quote_usd": 0.004, "gateway_authorised": True, "decided_at": 1000.0,
        "gaps": [], "label_state": "pending", "label": None, "outcome": {},
    }


def v2_row(rid="r1", certified=True, chosen="box", candidates=None, exploration=False,
           exploration_reason="no_mechanism", eligible_set=None, selection_probability=1.0):
    """A row shaped like something a v0.2.0 writer produces: C1's full shape plus C3's two required fields,
    both present so a test exercising C5 does not also trip C1's own required-field refusals."""
    return {
        "family": "agentic-coding", "request_id": rid, "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": candidates or [cand(), cand("api", "below_floor", 0.70, 0.012)], "chosen": chosen,
        "selection_probability": selection_probability, "exploration": exploration, "certified": certified,
        "policy_version": "p1", "mechanism_version": "0.2.0", "agent": "opencode", "model": "m",
        "endpoint": "http://e", "gateway_quote_usd": 0.004, "gateway_authorised": True, "decided_at": 1000.0,
        "gaps": [], "label_state": "pending", "label": None, "outcome": {},
        "schema_version": 2, "exploration_reason": exploration_reason, "eligible_set": eligible_set or [],
    }


def labelled(rows: list, success: bool = True) -> dict:
    return {r["request_id"]: {"label_state": "labelled", "label": success} for r in rows}


def _norm_counts(d: dict) -> dict:
    """`version_counts` keys may legitimately be `int` or `str` -- nothing in the contract pins which -- so
    comparisons in this file go through this normaliser rather than assuming one."""
    return {str(k): v for k, v in d.items()}


# ======================================================================================================
# the centre: eight v0.1.0 rows (no mechanism) + two v0.2.0 rows (both explored) hide a 4x budget overrun
# ======================================================================================================


def test_centre_pooled_exploration_share_hides_the_v020_mechanisms_real_rate():
    """Catches C5 not being implemented at all, or implemented but not reaching `exploration_cost`: this is the
    exact reproduction Amendment 8 measures. Eight v0.1.0 decisions (no exploration mechanism existed for them,
    `exploration=False`) plus two v0.2.0 decisions that both explored (`exploration=True`) pool to a 20% share,
    which PASSES a 25% budget -- while the v0.2.0 mechanism's own rate, over the only decisions it was ever
    eligible to explore, is 100%, four times over. Nothing about the pooled number is wrong arithmetic; it is the
    wrong POPULATION, and C5 exists so `check_all` refuses to report it under `pool_across_versions=False`."""
    v1_rows = [v1_row(rid=f"v1-{i}", exploration=False) for i in range(8)]
    v2_rows = [v2_row(rid=f"v2-{i}", exploration=True, exploration_reason="explored",
                       eligible_set=["box", "alt"], selection_probability=0.05) for i in range(2)]
    decisions = v1_rows + v2_rows

    naive_share = sum(1 for r in decisions if r.get("exploration")) / len(decisions)
    assert naive_share == pytest.approx(0.20), "fixture sanity: the pooled share must be exactly the contract's 20%"
    v020_only_rate = sum(1 for r in v2_rows if r.get("exploration")) / len(v2_rows)
    assert v020_only_rate == pytest.approx(1.0), "fixture sanity: the v0.2.0 mechanism's own rate must be 100%"

    verdicts = ac.check_all(decisions, {}, floor=0.80, budgeted_exploration=0.25)
    ec = next(v for v in verdicts if v.criterion == "exploration_cost")
    assert ec.verdict != ac.PASS, (
        f"a 20% pooled share against a 25% budget is a naive PASS, but it is built from eight decisions with no "
        f"mechanism and two decisions running at 100% of their own eligible traffic -- the pooled PASS must not "
        f"survive `check_all` with `pool_across_versions` left at its default False, got {ec.verdict!r}"
    )


def test_explicit_schema_version_1_and_an_absent_key_produce_the_same_decision():
    """Requirement check, not a C5 assertion: the contract says a v0.1.0 row is one with NO `schema_version` key
    at all, which is how `record.from_row` decides version -- not a row with `schema_version: 1` typed in. This
    confirms the two are read identically by `from_row` before this file commits to building every v1 fixture
    with the key omitted, so a reader of this file does not have to take that equivalence on faith."""
    omitted = v1_row(rid="same")
    explicit = dict(omitted)
    explicit["schema_version"] = 1
    d_omitted, ignored_omitted = rec.from_row(omitted)
    d_explicit, ignored_ignored = rec.from_row(explicit)
    assert d_omitted.schema_version == d_explicit.schema_version == 1
    assert ignored_omitted == ignored_ignored == []
    assert d_omitted.as_dict() == d_explicit.as_dict()


# ======================================================================================================
# each of the four refusing criteria, tested separately -- and no_false_certification, which must not
# ======================================================================================================
#
# One shared mixed log: 20 v0.1.0 rows + 20 v0.2.0 rows, all certified, all admissible, all labelled successes,
# with a generous `uncertified_tolerance` and `budgeted_exploration` supplied so that WITHOUT the mixture,
# `floor_compliance`, `default_is_not_a_hiding_place` and `exploration_cost` would each compute a real PASS --
# not an unsupported-for-their-own-reason verdict, which is the only way this fixture can tell "the mixture
# guard fired" apart from "the criterion was unsupported anyway." `spend_regret` has no such state: it is a
# stub and is UNSUPPORTED regardless, which is exactly the case Amendment 9 exists for and is tested on its own
# below.


def _mixed_log(n_v1=20, n_v2=20):
    v1_rows = [v1_row(rid=f"v1-{i}", exploration=(i < 2)) for i in range(n_v1)]
    v2_rows = [v2_row(rid=f"v2-{i}", exploration=(i < 2), exploration_reason=("explored" if i < 2 else "rate_zero"))
               for i in range(n_v2)]
    decisions = v1_rows + v2_rows
    outcomes = {**labelled(v1_rows, True), **labelled(v2_rows, True)}
    return decisions, outcomes


def _verdict_for(name, decisions, outcomes, **kw):
    verdicts = ac.check_all(decisions, outcomes, floor=0.80, uncertified_tolerance=0.5,
                            budgeted_exploration=0.5, **kw)
    return next(v for v in verdicts if v.criterion == name)


def test_floor_compliance_refuses_on_a_mixed_log():
    """Catches `floor_compliance` staying silent about the mixture (reporting a pooled rate as if the log were
    homogeneous), and separately catches it refusing for the WRONG reason. Built so it would PASS cleanly without
    the mixture (40 labelled successes, well above an 80% floor with room in the confidence bound) -- so a verdict
    other than that clean PASS can only be the mixture guard, not a sample-size artifact."""
    decisions, outcomes = _mixed_log()
    v = _verdict_for("floor_compliance", decisions, outcomes)
    assert v.verdict == ac.UNSUPPORTED, (
        f"40 labelled successes clear an 80% floor cleanly when read as one population; a log spanning two "
        f"schema_version values must not report that pooled clearance as a verdict at all, got {v.verdict!r}"
    )


def test_default_is_not_a_hiding_place_refuses_on_a_mixed_log():
    """Same shape, for the second of the four. Every decision here is certified and admissible so the uncertified
    share is 0%, well within the declared 50% tolerance -- a clean PASS without the mixture -- so the mixture
    guard, not a missing-tolerance UNSUPPORTED, is the only thing that can explain anything else."""
    decisions, outcomes = _mixed_log()
    v = _verdict_for("default_is_not_a_hiding_place", decisions, outcomes)
    assert v.verdict == ac.UNSUPPORTED, (
        f"0% uncertified share against a declared 50% tolerance is a clean PASS read as one population; a mixed "
        f"log must not report it, got {v.verdict!r}"
    )


def test_exploration_cost_refuses_on_a_mixed_log():
    """Same shape, for the third: 4 of 40 decisions explored (10%), well within the declared 50% budget -- a
    clean PASS without the mixture."""
    decisions, outcomes = _mixed_log()
    v = _verdict_for("exploration_cost", decisions, outcomes)
    assert v.verdict == ac.UNSUPPORTED, (
        f"a 10% pooled exploration share against a 50% budget is a clean PASS read as one population; a mixed "
        f"log must not report it, got {v.verdict!r}"
    )


def test_spend_regret_is_unsupported_on_a_mixed_log_same_as_always():
    """The fourth named criterion, and the one Amendment 9 is about: `spend_regret` is an unimplemented stub and
    is `UNSUPPORTED` on every log, mixed or not -- this alone does not prove the mixture guard ran at all, which
    is exactly why the next test pins the DETAIL rather than the verdict."""
    decisions, outcomes = _mixed_log()
    v = _verdict_for("spend_regret", decisions, outcomes)
    assert v.verdict == ac.UNSUPPORTED


def test_no_false_certification_does_not_refuse_on_a_mixed_log():
    """The fifth criterion, and the one that must NOT join the other four: it is a per-decision universal claim
    ("every certified assignment's candidate was admissible"), not a rate, so a mixture of schema versions does
    not change what it means. Catches an implementation that refuses every criterion in `CRITERIA` uniformly
    when it sees more than one `schema_version` -- the "refuse everything" implementation the contract calls out
    as the easier and wrong one."""
    decisions, outcomes = _mixed_log()
    v = _verdict_for("no_false_certification", decisions, outcomes)
    assert v.verdict == ac.PASS, (
        f"every candidate in this log is genuinely admissible; no_false_certification must compute its real "
        f"verdict regardless of the version mixture, got {v.verdict!r} ({v.detail!r})"
    )
    assert "schema_version" not in v.detail and "pool" not in v.detail.lower()


# ======================================================================================================
# Amendment 9: compute first -- a criterion already UNSUPPORTED for its own reason keeps its own message
# ======================================================================================================


def test_spend_regret_keeps_its_own_message_on_a_mixed_log_not_the_mixture_one():
    """The test that distinguishes "compute first, override only PASS/FAIL" from "refuse without computing" --
    the second was correct before Amendment 9 and passes every other test in this file, including the four
    above, because `spend_regret` is UNSUPPORTED under both rules. Only the DETAIL tells them apart: a stub with
    no implementation must say so (its own message, naming the estimator and the propensity-1 problem), not that
    the log spans two schema versions -- an operator told the latter goes to fix a log that was never the
    blocker."""
    decisions, outcomes = _mixed_log()
    v = _verdict_for("spend_regret", decisions, outcomes)
    assert v.verdict == ac.UNSUPPORTED
    assert "schema_version" not in v.detail, (
        f"spend_regret has no implementation regardless of the log's version mixture -- its detail must be its "
        f"own stub message, not the mixture refusal, got {v.detail!r}"
    )


def test_all_four_and_no_false_certification_distinguished_in_one_call():
    """The single call that pins Amendment 9 end to end: in ONE `check_all` invocation over the mixed log, three
    criteria carry the mixture-refusal detail, `spend_regret` carries its own unrelated detail, and
    `no_false_certification` computes a real PASS. An implementation that refuses every criterion uniformly
    (correct pre-Amendment-9, wrong after it) would make `spend_regret`'s detail indistinguishable from
    `floor_compliance`'s here; this is the test that would catch that regression even if the four separate tests
    above were each individually satisfied by a different, inconsistent implementation."""
    decisions, outcomes = _mixed_log()
    verdicts = {v.criterion: v for v in ac.check_all(decisions, outcomes, floor=0.80, uncertified_tolerance=0.5,
                                                     budgeted_exploration=0.5)}
    mixture_bearing = ("floor_compliance", "default_is_not_a_hiding_place", "exploration_cost")
    for name in mixture_bearing:
        assert verdicts[name].verdict == ac.UNSUPPORTED, name
    spend_regret_detail = verdicts["spend_regret"].detail
    assert verdicts["spend_regret"].verdict == ac.UNSUPPORTED
    for name in mixture_bearing:
        assert verdicts[name].detail != spend_regret_detail, (
            f"{name}'s mixture-refusal detail must not read the same as spend_regret's unrelated stub detail -- "
            f"if it does, the guard is not distinguishing 'would have produced a value' from 'never could'"
        )
    assert verdicts["no_false_certification"].verdict == ac.PASS


# ======================================================================================================
# the detail names the versions present AND the count in each, not just that a mixture exists
# ======================================================================================================


def test_detail_names_both_versions_and_their_distinct_counts():
    """"A message saying 'mixed versions' tells an operator nothing about which half of their log is which
    size." Built with deliberately UNEQUAL and mutually-distinguishable counts (8 vs 3) so a check for the
    substring '2' cannot be satisfied by the count alone, and a check for the substring '1' cannot be satisfied
    by the version number alone -- every one of the four digits asserted below can only come from the fact it is
    tied to."""
    v1_rows = [v1_row(rid=f"v1-{i}") for i in range(8)]
    v2_rows = [v2_row(rid=f"v2-{i}") for i in range(3)]
    decisions = v1_rows + v2_rows
    outcomes = {**labelled(v1_rows, True), **labelled(v2_rows, True)}
    v = _verdict_for("exploration_cost", decisions, outcomes)
    assert v.verdict == ac.UNSUPPORTED
    assert "1" in v.detail and "8" in v.detail, v.detail
    assert "2" in v.detail and "3" in v.detail, v.detail


def test_numbers_carries_version_counts_keyed_by_schema_version():
    """The same fixture, checked structurally rather than by scanning prose: `numbers["version_counts"]` must
    map each schema_version present to how many decisions carried it, so a caller can read the split
    programmatically instead of parsing the detail string. Keys may legitimately be `int` or `str` -- nothing in
    the contract pins which -- so this normalises before comparing."""
    v1_rows = [v1_row(rid=f"v1-{i}") for i in range(8)]
    v2_rows = [v2_row(rid=f"v2-{i}") for i in range(3)]
    decisions = v1_rows + v2_rows
    outcomes = {**labelled(v1_rows, True), **labelled(v2_rows, True)}
    v = _verdict_for("exploration_cost", decisions, outcomes)
    assert "version_counts" in v.numbers, v.numbers
    assert _norm_counts(v.numbers["version_counts"]) == {"1": 8, "2": 3}


# ======================================================================================================
# pool_across_versions=True: the criteria compute, and say pooling was on the caller's instruction
# ======================================================================================================


def test_pool_across_versions_true_computes_a_real_verdict_not_unsupported():
    """The positive half of C5's other branch: with the flag set, the criteria that refused above must actually
    compute -- not just avoid the mixture-refusal detail while still landing on some other UNSUPPORTED. Built
    from the same mixed log used for the four-refusals tests, where each criterion's real, pooled verdict is a
    clean PASS -- so a non-PASS here (of any kind) means the flag did not reach the criterion."""
    decisions, outcomes = _mixed_log()
    verdicts = {v.criterion: v for v in ac.check_all(decisions, outcomes, floor=0.80, uncertified_tolerance=0.5,
                                                     budgeted_exploration=0.5, pool_across_versions=True)}
    for name in ("floor_compliance", "default_is_not_a_hiding_place", "exploration_cost"):
        assert verdicts[name].verdict == ac.PASS, (
            f"{name} must compute its real pooled verdict once the caller sets pool_across_versions=True, got "
            f"{verdicts[name].verdict!r} ({verdicts[name].detail!r})"
        )


def test_pool_across_versions_true_records_the_pooling_was_on_the_callers_instruction():
    """The half a silently-pooling implementation would fail: "every affected verdict's detail says the versions
    were pooled on the caller's instruction." An implementation that computes the pooled number correctly but
    says nothing about WHY it pooled would pass the test above and silently reintroduce the defect C5 exists to
    close -- pooling that looks identical to a homogeneous log's own, unremarkable PASS, indistinguishable from
    the operator's point of view. Checked on all three criteria that actually compute a value under pooling."""
    decisions, outcomes = _mixed_log()
    verdicts = {v.criterion: v for v in ac.check_all(decisions, outcomes, floor=0.80, uncertified_tolerance=0.5,
                                                     budgeted_exploration=0.5, pool_across_versions=True)}
    for name in ("floor_compliance", "default_is_not_a_hiding_place", "exploration_cost"):
        detail = verdicts[name].detail.lower()
        assert "instruction" in detail or "caller" in detail, (
            f"{name}'s detail under pool_across_versions=True must say the pooling was on the caller's "
            f"instruction, not merely report a number as if the log were homogeneous -- got {detail!r}"
        )


def test_pool_across_versions_true_does_not_change_spend_regrets_own_message():
    """The mirror of Amendment 9's rule under the OTHER flag value: `spend_regret` never computes anything
    regardless of `pool_across_versions`, so there is nothing for it to pool and its detail must stay its own
    stub message -- not gain a pooling note that describes an operation that did not happen for it."""
    decisions, outcomes = _mixed_log()
    unpooled = _verdict_for("spend_regret", decisions, outcomes)
    pooled = _verdict_for("spend_regret", decisions, outcomes, pool_across_versions=True)
    assert pooled.verdict == ac.UNSUPPORTED
    assert pooled.detail == unpooled.detail, (
        "spend_regret has no value to pool either way; its message must not differ between the two flag values"
    )


# ======================================================================================================
# a single-version log is unaffected, in both directions of the flag
# ======================================================================================================
#
# The sharpest way to catch an implementation that refuses whenever `pool_across_versions` is False -- rather
# than whenever versions are actually MIXED -- is a log with only one version present: the flag must not matter
# at all, in either direction, because there is nothing to pool or refuse pooling.


def _single_version_log(row_builder, n=20):
    rows = [row_builder(rid=f"r{i}", exploration=(i < 3)) for i in range(n)]
    return rows, labelled(rows, True)


def test_a_pure_v010_log_is_identical_under_both_flag_values():
    """Catches the "refuse whenever the flag is False" bug directly: a homogeneous v0.1.0 log's verdicts must be
    byte-for-byte the same whether `pool_across_versions` is False (the default) or True, because there is only
    one version present and nothing for the flag to act on."""
    decisions, outcomes = _single_version_log(v1_row)
    kw = dict(floor=0.80, uncertified_tolerance=0.5, budgeted_exploration=0.5)
    without_flag = ac.check_all(decisions, outcomes, **kw, pool_across_versions=False)
    with_flag = ac.check_all(decisions, outcomes, **kw, pool_across_versions=True)
    assert without_flag == with_flag
    ec = next(v for v in without_flag if v.criterion == "exploration_cost")
    assert ec.verdict == ac.PASS, (
        f"a pure v0.1.0 log with a 15% exploration share against a 50% budget must PASS outright -- if it is "
        f"UNSUPPORTED instead, the implementation is refusing on the flag's default value rather than on an "
        f"actual mixture, got {ec.verdict!r}"
    )


def test_a_pure_v020_log_is_identical_under_both_flag_values():
    """The mirror case: a homogeneous v0.2.0 log must be equally unaffected by the flag. Needed on its own,
    separately from the v0.1.0 case above, because an implementation could special-case "only version 1 present"
    as the trigger for skipping the guard and still wrongly refuse a pure, single v0.2.0 log."""
    decisions, outcomes = _single_version_log(v2_row)
    kw = dict(floor=0.80, uncertified_tolerance=0.5, budgeted_exploration=0.5)
    without_flag = ac.check_all(decisions, outcomes, **kw, pool_across_versions=False)
    with_flag = ac.check_all(decisions, outcomes, **kw, pool_across_versions=True)
    assert without_flag == with_flag
    ec = next(v for v in without_flag if v.criterion == "exploration_cost")
    assert ec.verdict == ac.PASS, (
        f"a pure v0.2.0 log with a 15% exploration share against a 50% budget must PASS outright, got "
        f"{ec.verdict!r}"
    )
