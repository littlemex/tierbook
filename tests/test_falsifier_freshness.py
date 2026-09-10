"""Tests for C6 (amendment 7) -- the falsifier reads the age it already holds.

`accept.py` contained no `evidence_age_days` and no `max_age_days` anywhere, so `accept.no_false_certification`
and `accept.default_is_not_a_hiding_place` had called `record.check_certification` with freshness absent since
v0.1.0, in which release `record.admissible` gained freshness as its fourth condition. Threading a scalar
through would not have fixed it either: `check_certification` used to build ONE `kw` dict and apply ONE
`evidence_age_days` to EVERY candidate in the decision, while each candidate carries its own `evidence_as_of` --
and tiers are measured at different times, so differing dates are the normal case, not an edge one. Amendment 7's
own measurement, on one decision holding a 617-day-old candidate and a 9-day-old one, both with bounds above the
floor, uncertified:

    scalar age supplied   what the OLD falsifier reported        what is true
    400 days               nothing                                the 9-day candidate was admissible and the
                                                                    default hid behind it
    5 days                 both candidates                         only the 9-day one; the 617-day one was expired

No scalar gives the right answer. C6 removes `evidence_age_days` from `record.check_certification`'s signature
and derives each candidate's age from its own `evidence_as_of` against `decision.decided_at` -- never the clock at
check time -- via `observe.evidence_age_days`, which already existed and already did this arithmetic.
`record.EXCLUSION_REASONS` gains `no_evidence_date` for a candidate with no date at all, and
`accept.no_false_certification`/`default_is_not_a_hiding_place`/`check_all` gain `max_age_days`, threaded by
`cli.cmd_accept` through `decide.parameter(policy, "max_evidence_age_days", None)` -- no new CLI flag, since a
second typed number is the defect amendment 2 exists to close.

Only C6 is in scope here. Nothing about `schema_version`, the policy artifact's other parameters, exploration's
draw, or pooling across versions is tested in this file. Three tests in `test_exploration.py` are
`@pytest.mark.xfail(strict=True)` against the signature this entry removes; they are the integrator's to unmark
when C6 lands and are not touched here.

**Why every fixture date is computed, never typed as a literal ISO string:** a literal like `"2025-01-01"` used to
compute an age is a fixture that is exactly-right on one calendar day and silently wrong on every other one --
it would pass while this suite is written and fail (or, worse, pass for the wrong reason) whenever it is next
read. Every `evidence_as_of` below is derived from the `decided_at` it is being measured against, using
`evidence_as_of_before`, so the intended age (617 days, 9 days, ...) holds regardless of when `pytest` runs.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import accept as ac  # noqa: E402
from tierbook import cli  # noqa: E402
from tierbook import observe as obs  # noqa: E402
from tierbook import record as rec  # noqa: E402

#: Computed once, at import, from `datetime.now()` -- not a literal calendar date. This is still "the present
#: moment", but recorded as a fixed value for the whole file so every test in it agrees on what "now" was, and it
#: is used only as a seed for `decided_at_ts`: nothing below ever compares it back against a fresh `time.time()`.
_ANCHOR = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def decided_at_ts(offset_days: float = 0.0) -> float:
    """A `decided_at` timestamp, `offset_days` from this file's anchor. Never a hardcoded epoch value: the anchor
    is derived from `datetime.now()` at import time so the fixture is never "correct today, wrong next year"."""
    return (_ANCHOR + dt.timedelta(days=offset_days)).timestamp()


def evidence_as_of_before(decided_at: float, age_days: float) -> str:
    """The ISO date `age_days` before `decided_at`, derived from `decided_at` itself rather than from wall-clock
    "now". This is the piece that keeps every age below exact and calendar-independent: two calls with the same
    `decided_at` and `age_days` always produce a candidate whose age (measured against that `decided_at`) is
    exactly `age_days`, on any day this suite happens to run.
    """
    as_of = dt.datetime.fromtimestamp(decided_at, tz=dt.timezone.utc) - dt.timedelta(days=age_days)
    return as_of.date().isoformat()


def cand(cid="box", why="chosen", bound=0.90, cost=0.004, evidence_as_of=""):
    return rec.Candidate(id=cid, excluded_because=why, bound=bound, bound_kind="lcb95", cost_usd=cost,
                         evidence_as_of=evidence_as_of)


def decision(**kw):
    """A `Decision` built the way a writer builds one. `decided_at` defaults to this file's anchor rather than
    `time.time()`, so a caller who does not override it still gets a value derived the same calendar-independent
    way as everything else here."""
    base = dict(
        family="agentic-coding", request_id="r1", feature_vector_version="fv1", state_ref="obs:abc",
        candidates=[cand()], chosen="box",
        selection_probability=1.0, exploration=False, certified=True, policy_version="p1",
        mechanism_version="0.1.0", agent="opencode", model="Qwen/Qwen3.6-35B-A3B",
        endpoint="http://vllm:8000", gateway_quote_usd=0.004, gateway_authorised=True,
        decided_at=decided_at_ts(0.0),
        exploration_reason="no_mechanism", eligible_set=[])
    base.update(kw)
    return rec.Decision(**base)


def run_cli(argv: list[str]) -> int:
    """Invoke the CLI through its documented entry point, normalising `SystemExit` the way
    `test_policy_parameters.py` already does: `cli.main` sometimes returns a status and sometimes raises
    `SystemExit` (argparse's own errors do), and a CLI test should assert on the exit status, not on which
    mechanism produced it."""
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


def minimal_policy_dict(*, floor=0.80, max_evidence_age_days=None) -> dict:
    """The smallest artifact `decide.from_dict` will load: no rules, so nothing about compilation is under test
    here, only whether `cmd_accept` reads `max_evidence_age_days` out of `parameters` and threads it through."""
    return {
        "family": "agentic-coding", "default": ["api"], "certified": False, "note": "",
        "domain": {}, "provenance": {}, "rules": [],
        "parameters": {"floor": floor, "max_evidence_age_days": max_evidence_age_days},
    }


# --- the date helper itself, because a bug here would make every other test below meaningless ------------------


def test_the_date_helper_derives_the_intended_ages_from_decided_at():
    """Guards the fixture technique, not the contract: if `evidence_as_of_before` had an off-by-one or a timezone
    bug, every age-dependent test below would be silently testing the wrong ages while still looking reasonable.
    Checked against the actual production arithmetic (`observe.evidence_age_days`), not reimplemented here."""
    decided_at = decided_at_ts(0.0)
    assert obs.evidence_age_days(evidence_as_of_before(decided_at, 617), now=decided_at) == 617.0
    assert obs.evidence_age_days(evidence_as_of_before(decided_at, 9), now=decided_at) == 9.0
    assert obs.evidence_age_days(evidence_as_of_before(decided_at, 0), now=decided_at) == 0.0


# --- the signature itself: evidence_age_days is gone, not merely unused -----------------------------------------


def test_check_certification_no_longer_accepts_a_scalar_evidence_age_days():
    """Catches an implementation that kept the retired parameter around (accepted and ignored, or accepted and
    still applied to every candidate). Amendment 7 says `evidence_age_days` is GONE from the signature, not
    deprecated: a single scalar cannot be correct for a candidate set whose members carry different
    `evidence_as_of` dates, so a version that still accepts it has not actually adopted the fix."""
    with pytest.raises(TypeError):
        rec.check_certification(decision(), floor=0.80, latency_feasible=True, evidence_age_days=30.0)


# --- the centre: one decision, two candidates, two true ages, no scalar gets it right ---------------------------


def test_two_candidates_at_different_ages_the_scalar_falsifier_could_not_get_right():
    """The exact reproduction amendment 7 measures. One decision holds a 617-day-old candidate ('old') and a
    9-day-old one ('fresh'), both bounds above the floor, uncertified, `max_age_days=90`. The pre-C6 falsifier
    could not get this right with any single scalar it was handed: supplied 400, it reported NOTHING (the fresh
    candidate's own hiding place went unseen because 400 > 90 marked BOTH candidates stale); supplied 5, it
    reported BOTH candidates (5 < 90 marked both fresh, including the one that was genuinely 617 days expired).
    The true answer needs both ages at once: 'old' is expired and cannot hide anything; 'fresh' is not expired,
    clears the floor, and was not chosen -- exactly one violation, and it must name 'fresh', not 'old'."""
    decided_at = decided_at_ts(0.0)
    old = cand("old", "chosen", bound=0.90, evidence_as_of=evidence_as_of_before(decided_at, 617))
    fresh = cand("fresh", "not_evaluated", bound=0.85, evidence_as_of=evidence_as_of_before(decided_at, 9))
    d = decision(decided_at=decided_at, chosen="old", certified=False, candidates=[old, fresh])

    violations = rec.check_certification(d, floor=0.80, latency_feasible=True, max_age_days=90.0)

    assert len(violations) == 1, violations
    assert "fresh" in violations[0]
    assert "old" not in violations[0]
    assert "hiding place" in violations[0]


# --- decided_at is the reference, not the clock at check time --------------------------------------------------


def test_two_decisions_differing_only_in_decided_at_get_different_verdicts():
    """The candidate's `evidence_as_of` is held fixed; only `decided_at` moves. A reader keyed to `decided_at`
    (as the contract requires) must see the same evidence as fresh from one decision and expired from the
    other, for the identical string on the identical candidate -- which is only possible if the reference really
    is `decided_at` and not some property of the candidate alone."""
    decided_at_a = decided_at_ts(0.0)
    evidence_as_of = evidence_as_of_before(decided_at_a, 5.0)   # 5 days old, measured against decision A
    decided_at_b = decided_at_ts(300.0)                          # decision B happens 300 days later

    candidate = cand("box", "chosen", bound=0.90, evidence_as_of=evidence_as_of)
    decision_a = decision(decided_at=decided_at_a, candidates=[candidate], chosen="box", certified=True)
    decision_b = decision(decided_at=decided_at_b, candidates=[candidate], chosen="box", certified=True)

    violations_a = rec.check_certification(decision_a, floor=0.80, latency_feasible=True, max_age_days=90.0)
    violations_b = rec.check_certification(decision_b, floor=0.80, latency_feasible=True, max_age_days=90.0)

    assert violations_a == [], "5 days old against a 90-day limit must be admissible"
    assert violations_b and "evidence_expired" in violations_b[0], (
        "the SAME evidence_as_of, judged against a decided_at 300 days later, is 305 days old and must expire")


def test_check_certification_does_not_reach_for_the_wall_clock(monkeypatch):
    """Rules out an implementation that computes age against `time.time()` instead of `decision.decided_at`.
    `decided_at` and `evidence_as_of` are both fixed, well within `max_age_days`; `time.time()` is monkeypatched
    to two very different fake values (one equal to `decided_at`, one 200 days past it) in both `record` and
    `observe` -- the two modules that could plausibly call it. A correct implementation never asks the clock, so
    the verdict must be identical either way. An implementation using the clock would report the evidence as
    fresh under the first fake time and expired under the second, since 200 days crosses the 90-day limit."""
    decided_at = decided_at_ts(-500.0)   # arbitrarily long ago; only its relationship to evidence_as_of matters
    evidence_as_of = evidence_as_of_before(decided_at, 10.0)
    d = decision(decided_at=decided_at, candidates=[cand("box", "chosen", bound=0.90,
                                                         evidence_as_of=evidence_as_of)],
                chosen="box", certified=True)

    def check():
        return rec.check_certification(d, floor=0.80, latency_feasible=True, max_age_days=90.0)

    monkeypatch.setattr(time, "time", lambda: decided_at)
    result_at_decided_at = check()
    monkeypatch.setattr(time, "time", lambda: decided_at + 200 * 86400.0)
    result_much_later = check()

    assert result_at_decided_at == result_much_later == [], (
        "the verdict changed when only the wall clock moved, so something is reading time.time() instead of "
        "decision.decided_at")


# --- no_evidence_date: a third exclusion reason, distinct from evidence_expired --------------------------------


def test_no_evidence_date_is_in_the_closed_vocabulary():
    assert "no_evidence_date" in rec.EXCLUSION_REASONS


def test_an_undated_candidate_with_a_declared_limit_is_refused_as_no_evidence_date_not_evidence_expired():
    """An undated bound cannot be certified against a declared limit -- there is no age to compare -- and the two
    wrong alternatives are both worse than refusing: `evidence_expired` would assert an age the record does not
    carry, and silently admitting it would restore the v0.1.0 defect this whole entry exists to remove. A test
    that only checked "it was refused" would pass against either wrong alternative; this pins the specific one."""
    d = decision(candidates=[cand("box", "chosen", bound=0.90, evidence_as_of="")], chosen="box", certified=True)
    violations = rec.check_certification(d, floor=0.80, latency_feasible=True, max_age_days=90.0)
    assert violations, "an undated candidate under a declared limit must not be certified"
    assert "no_evidence_date" in violations[0]
    assert "evidence_expired" not in violations[0]


def test_an_undated_candidate_with_no_declared_limit_is_not_refused_for_freshness_at_all():
    """The mirror case, same shape as the latency constraint: with no `max_age_days` declared, the freshness
    condition is absent, not satisfied -- and absent means an undated candidate is not penalised for a condition
    that was never asked of it, exactly as an operator who set no latency constraint is not penalised either."""
    d = decision(candidates=[cand("box", "chosen", bound=0.90, evidence_as_of="")], chosen="box", certified=True)
    assert rec.check_certification(d, floor=0.80, latency_feasible=True, max_age_days=None) == []


# --- max_age_days absent means the condition is absent, not satisfied ------------------------------------------


def test_max_age_days_absent_is_absent_not_satisfied_for_a_dated_but_ancient_candidate():
    """The record-level analogue of `test_an_undeclared_freshness_limit_is_absent_rather_than_passed` in
    `test_record.py`, one layer up: a 617-day-old, DATED candidate must not be silently treated as fresh when no
    limit was declared (that would be inventing a pass), and must be flagged once a limit is declared (the same
    candidate, unchanged, only the policy input changes)."""
    decided_at = decided_at_ts(0.0)
    stale = evidence_as_of_before(decided_at, 617.0)
    d = decision(decided_at=decided_at, chosen="box", certified=True,
                candidates=[cand("box", "chosen", bound=0.90, evidence_as_of=stale)])

    assert rec.check_certification(d, floor=0.80, latency_feasible=True, max_age_days=None) == []

    violations = rec.check_certification(d, floor=0.80, latency_feasible=True, max_age_days=90.0)
    assert violations and "evidence_expired" in violations[0]


# --- accept threading: the keyword must change the verdict, not merely be accepted ------------------------------


def test_no_false_certification_verdict_changes_with_max_age_days():
    """A function that accepts `max_age_days` as a keyword and never passes it to `check_certification` would
    still pass a test that only checks the keyword does not raise -- that is exactly the pre-C6 behaviour,
    reproduced through new plumbing instead of old. This asserts the VERDICT differs, not merely that the call
    succeeds."""
    decided_at = decided_at_ts(0.0)
    stale = evidence_as_of_before(decided_at, 617.0)
    row = decision(decided_at=decided_at, chosen="box", certified=True,
                  candidates=[cand("box", "chosen", bound=0.90, evidence_as_of=stale)]).as_dict()

    without_limit = ac.no_false_certification([row], floor=0.80, latency_feasible=True, max_age_days=None)
    with_limit = ac.no_false_certification([row], floor=0.80, latency_feasible=True, max_age_days=90.0)

    assert without_limit.verdict == ac.PASS
    assert with_limit.verdict == ac.FAIL


def test_default_is_not_a_hiding_place_verdict_changes_with_max_age_days():
    """Same principle as above, for the mirror criterion. Without a limit, a 617-day-old candidate that clears
    the floor looks admissible (freshness absent), so the uncertified decision that left it unchosen is a hiding
    place. Once a limit is declared, that candidate expires and stops being one -- the criterion's verdict must
    move from the mixture-detecting FAIL to UNSUPPORTED (no hiding place found, and no uncertified tolerance was
    declared to compare the remaining share against)."""
    decided_at = decided_at_ts(0.0)
    stale = evidence_as_of_before(decided_at, 617.0)
    fresh_fallback = evidence_as_of_before(decided_at, 1.0)
    row = decision(decided_at=decided_at, chosen="fallback", certified=False,
                  candidates=[cand("fallback", "chosen", bound=0.50, evidence_as_of=fresh_fallback),
                              cand("stale_box", "not_evaluated", bound=0.90, evidence_as_of=stale)]).as_dict()

    without_limit = ac.default_is_not_a_hiding_place([row], floor=0.80, latency_feasible=True, max_age_days=None)
    with_limit = ac.default_is_not_a_hiding_place([row], floor=0.80, latency_feasible=True, max_age_days=90.0)

    assert without_limit.verdict == ac.FAIL
    assert "hiding place" in without_limit.detail
    assert with_limit.verdict == ac.UNSUPPORTED


def test_check_all_threads_max_age_days_into_the_freshness_sensitive_criteria():
    """The keyword has to reach `check_all`'s own callers, not stop at `no_false_certification` and
    `default_is_not_a_hiding_place` being individually correct -- `cmd_accept` calls `check_all`, not either of
    them directly, so this is the level a wiring mistake would actually surface at."""
    decided_at = decided_at_ts(0.0)
    stale = evidence_as_of_before(decided_at, 617.0)
    row = decision(decided_at=decided_at, chosen="box", certified=True,
                  candidates=[cand("box", "chosen", bound=0.90, evidence_as_of=stale)]).as_dict()

    def verdict_for(name, max_age_days):
        verdicts = ac.check_all([row], {}, floor=0.80, latency_feasible=True, max_age_days=max_age_days)
        return next(v for v in verdicts if v.criterion == name).verdict

    assert verdict_for("no_false_certification", None) == ac.PASS
    assert verdict_for("no_false_certification", 90.0) == ac.FAIL


# --- cli: cmd_accept reads the limit from the artifact, and there is no --max-age-days flag ---------------------


def test_accept_cli_has_no_max_age_days_flag(tmp_path, capsys):
    """No new CLI flag: the contract is explicit that a second typed number for the same fact is the defect
    amendment 2 exists to close, reopened in a second value if `accept` grew one here. Exit code 2 is argparse's
    own code for an argument it does not recognise -- distinct from the 4 the contract reserves for two present,
    disagreeing numbers, which this is not: there is nowhere for this flag to disagree with, because it must not
    exist at all."""
    log_path = tmp_path / "decisions.jsonl"
    rc = run_cli(["accept", "--log", str(log_path), "--max-age-days", "90"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unrecognized" in err.lower()


def test_cmd_accept_reads_max_age_days_from_the_policy_artifact_through_parameter(tmp_path):
    """The end-to-end proof that `cmd_accept` actually reads `max_evidence_age_days` via
    `decide.parameter(policy, "max_evidence_age_days", None)`, per the contract's own wording -- the same rule
    amendment 2 established for the floor. A log with one certified decision whose only candidate is 617 days
    stale: run through a policy that declares a 90-day limit, `accept` must FAIL (no_false_certification); run
    through an otherwise-identical policy that declares no limit, it must not. An implementation that wired
    `--policy`/`--floor` correctly but forgot this one line would pass every test in `test_policy_parameters.py`
    and still reproduce C6's whole defect through a brand-new code path instead of the retired one."""
    decided_at = decided_at_ts(0.0)
    stale = evidence_as_of_before(decided_at, 617.0)
    d = decision(decided_at=decided_at, chosen="box", certified=True,
                candidates=[cand("box", "chosen", bound=0.90, evidence_as_of=stale)])
    log_path = tmp_path / "decisions.jsonl"
    rec.Log(log_path).append(d)

    strict_policy = tmp_path / "strict.json"
    strict_policy.write_text(json.dumps(minimal_policy_dict(floor=0.80, max_evidence_age_days=90.0)))
    rc_strict = run_cli(["accept", "--log", str(log_path), "--policy", str(strict_policy)])
    assert rc_strict == 1, "a 617-day-old candidate must fail no_false_certification under a 90-day limit"

    lenient_policy = tmp_path / "lenient.json"
    lenient_policy.write_text(json.dumps(minimal_policy_dict(floor=0.80, max_evidence_age_days=None)))
    rc_lenient = run_cli(["accept", "--log", str(log_path), "--policy", str(lenient_policy)])
    assert rc_lenient == 0, "with no limit declared in the artifact, the same candidate must not fail on freshness"


# --- amendment 11: the report records which limit it used, and whether it used one ----------------------


def test_the_report_records_the_freshness_limit_it_read_from_the_artifact(tmp_path):
    """Catches the value reaching the computation with no copy reaching the record -- which is the defect C2 closed
    for the floor, in the value C6 added. Before this, two runs differing in whether freshness was checked at all
    produced reports that were identical about freshness."""
    log_path = tmp_path / "decisions.jsonl"
    rec.Log(log_path).append(decision(decided_at=decided_at_ts(0.0)))
    policy = tmp_path / "p.json"
    policy.write_text(json.dumps(minimal_policy_dict(floor=0.80, max_evidence_age_days=90.0)))
    out = tmp_path / "report.json"
    run_cli(["accept", "--log", str(log_path), "--policy", str(policy), "--out", str(out)])
    report = json.loads(out.read_text())
    assert report["max_age_days"] == 90.0
    assert str(policy) in report["max_age_days_provenance"]


def test_a_report_with_no_policy_says_freshness_was_not_checked(tmp_path):
    """The distinction this exists for: `null` already means "the operator declared no limit, so the condition is
    absent", a legitimate declaration. Without the provenance line the same `null` also means "there was no artifact
    to read", and those are different facts -- freshness considered and found unbounded, versus never considered."""
    log_path = tmp_path / "decisions.jsonl"
    rec.Log(log_path).append(decision(decided_at=decided_at_ts(0.0)))
    out = tmp_path / "report.json"
    run_cli(["accept", "--log", str(log_path), "--floor", "0.80", "--out", str(out)])
    report = json.loads(out.read_text())
    assert report["max_age_days"] is None
    assert "not checked" in report["max_age_days_provenance"]


def test_a_declared_absence_of_a_limit_is_distinguishable_from_no_artifact(tmp_path):
    """The two `null`s must not read the same. An artifact declaring `max_evidence_age_days: null` says freshness was
    considered and left unbounded; no artifact at all says nobody looked. A single `null` with no provenance collapses
    them, and the collapse is invisible in a committed report."""
    log_path = tmp_path / "decisions.jsonl"
    rec.Log(log_path).append(decision(decided_at=decided_at_ts(0.0)))
    policy = tmp_path / "p.json"
    policy.write_text(json.dumps(minimal_policy_dict(floor=0.80, max_evidence_age_days=None)))
    out_declared = tmp_path / "declared.json"
    run_cli(["accept", "--log", str(log_path), "--policy", str(policy), "--out", str(out_declared)])
    out_absent = tmp_path / "absent.json"
    run_cli(["accept", "--log", str(log_path), "--floor", "0.80", "--out", str(out_absent)])
    declared = json.loads(out_declared.read_text())
    absent = json.loads(out_absent.read_text())
    assert declared["max_age_days"] is None and absent["max_age_days"] is None
    assert declared["max_age_days_provenance"] != absent["max_age_days_provenance"]
