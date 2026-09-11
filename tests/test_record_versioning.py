"""Tests for C1 -- a reader that survives a field being added.

Before this entry, `accept._as_decision` splatted every key of a logged row into `Decision(**kw)`. Verified in the
contract: a record carrying one new field made every reader raise `TypeError` on every line, outside `Log.read`'s
own corrupt-line tolerance, killing the whole acceptance run rather than being counted -- in both directions, a
v0.1.0 reader meeting v0.2.0 lines and an operator rolling back onto an old reader.

`record.from_row` is the fix, and every test below is one way the naive splat got a negative case wrong: an unknown
key, a missing version, a version from the future, a field this version requires but the row does not have.
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

V010_FIXTURE = ROOT / "docs" / "verify" / "v0.1.0-decisions.jsonl"


def cand(cid="box", why="chosen", bound=0.90, cost=0.004):
    """A row's candidate shape -- `bound_provenance` nested as a plain dict, the shape `from_row` reads (CONTRACT
    C1 point 3): a logged row carries it as a nested object, never as a `BoundProvenance` instance."""
    return {"id": cid, "excluded_because": why, "bound": bound,
            "bound_provenance": (None if bound is None else
                                 {"estimator": "clopper_pearson_fixed_sample", "confidence": 0.95,
                                  "corrected_over": ()}),
            "cost_usd": cost, "evidence_as_of": "2026-09-01"}


def row(**kw):
    """A row shaped like something `Log.append` would have written -- a plain dict, `from_row`'s whole input."""
    base = {
        "family": "agentic-coding", "request_id": "r1", "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": [cand(), cand("api", "below_floor", 0.70, 0.012)], "chosen": "box",
        "selection_probability": 1.0, "exploration": False, "certified": True,
        "policy_version": "p1", "mechanism_version": "0.1.0", "agent": "opencode", "model": "m",
        "endpoint": "http://e", "gateway_quote_usd": 0.004, "gateway_authorised": True, "decided_at": 1000.0,
        "exploration_reason": "no_mechanism", "eligible_set": [],
        "gaps": [], "label_state": "pending", "label": None, "outcome": {},
    }
    base.update(kw)
    return base


def _candidate_from_dict(c: dict) -> rec.Candidate:
    """`build_decision`'s bridge from the row shape (`cand()`, a plain dict) to the construction shape
    (`rec.Candidate`, a dataclass): `bound_provenance` is a nested dict in the former and a `BoundProvenance`
    instance in the latter (CONTRACT C1 point 3), and this is the one place in this file that crosses from one to
    the other."""
    c = dict(c)
    bp = c.pop("bound_provenance", None)
    if bp is not None:
        bp = rec.BoundProvenance(**bp)
    return rec.Candidate(bound_provenance=bp, **c)


def build_decision(**kw):
    """A `Decision` built the way a writer builds one -- from plain values, never from a logged row."""
    r = row()
    base = {k: v for k, v in r.items() if k != "candidates"}
    base["candidates"] = [_candidate_from_dict(c) for c in r["candidates"]]
    base.update(kw)
    return rec.Decision(**base)


def real_v010_row() -> dict:
    """A line actually written by v0.1.0, not a hand-written stand-in for one -- the contract asks for this by
    name rather than a fixture we typed ourselves."""
    for line in V010_FIXTURE.read_text().splitlines():
        parsed = json.loads(line)
        if "request_id" in parsed:
            return parsed
    raise AssertionError(f"{V010_FIXTURE} has no decision line")


# --- the version number itself -----------------------------------------------------------------------


def test_schema_version_is_2():
    """Catches C1 shipping with the wrong constant -- every other test in this file is keyed against it, so a wrong
    value here would make them all pass or fail for the wrong reason."""
    assert rec.SCHEMA_VERSION == 2


# --- stamped by the writer, refused from a caller -----------------------------------------------------


def test_a_written_decision_is_stamped_with_the_current_schema_version():
    """Catches the writer forgetting to stamp `schema_version`, which is the one fact `from_row` relies on to tell
    an old record from a current one -- an unstamped record has no version to compare against."""
    assert build_decision().schema_version == rec.SCHEMA_VERSION


def test_a_caller_supplying_schema_version_is_refused():
    """Catches a caller asserting its own version at construction time, which would let a component other than the
    serialiser claim what shape it wrote -- the exact ambiguity this entry exists to remove."""
    with pytest.raises(rec.Incomplete, match="writer"):
        build_decision(schema_version=1)


# --- from_row: the only door from a logged row to a Decision --------------------------------------------


def test_a_row_with_no_schema_version_reads_as_version_1():
    """Catches the reader defaulting an absent version to the CURRENT schema instead of the fixed, known v0.1.0
    shape -- reading a v0.1.0 row as version 2 is reading it optimistically, which is the failure mode C1 forbids
    by name for a row from the future and must not also commit for a row from the past."""
    d, ignored = rec.from_row(row())
    assert d.schema_version == 1
    assert ignored == []


def test_a_real_v010_line_reads_as_version_1():
    """Catches from_row working on a hand-written stand-in but not on an actual v0.1.0 log line -- the contract
    requires this be checked against a real record, and a reader tuned to a fixture's exact key order or spacing
    would pass the wrong test."""
    d, ignored = rec.from_row(real_v010_row())
    assert d.schema_version == 1
    assert d.request_id == "r1"
    # C1 replaced `bound_kind` with `bound_provenance`, so a real v0.1.0 line carries one field this reader no
    # longer models, and reporting it is C12's contracted behaviour rather than a regression. It is deliberately
    # NOT translated into a provenance: `bound_kind` was a free string, and the defect C1 closed was three rows
    # with the same fabricated bound and three different `bound_kind` values all certifying identically. Turning
    # such a string into a recorded estimator would launder an unchecked claim into an attributable one, which is
    # worse than reading the bound as `unrecorded` and saying so.
    assert ignored == ["candidates[0].bound_kind", "candidates[1].bound_kind"]


def test_a_fully_known_v020_row_ignores_nothing():
    """Catches from_row over-reporting ignored keys on an ordinary current row, which would turn the ignored list
    into noise an operator has to filter through instead of a signal that a field is actually unknown."""
    d, ignored = rec.from_row(row(schema_version=2))
    assert d.schema_version == 2
    assert ignored == []


def test_an_unknown_key_is_ignored_and_named_not_raised():
    """Catches the TypeError this whole entry exists to remove: the old `Decision(**kw)` splat raised on any field
    the dataclass did not define, which is exactly how adding a field to the record broke every older reader."""
    d, ignored = rec.from_row(row(schema_version=2, a_field_from_the_future="whatever"))
    assert ignored == ["a_field_from_the_future"]
    assert d.request_id == "r1"


def test_multiple_unknown_keys_are_all_named():
    """Catches a reader that reports only the first ignored key and drops the rest, which would undercount in the
    same way an earlier version of this codebase undercounted certification violations by breaking out of a loop
    early instead of scanning the whole row."""
    d, ignored = rec.from_row(row(schema_version=2, unknown_a=1, unknown_b=2))
    assert set(ignored) == {"unknown_a", "unknown_b"}


def test_a_row_newer_than_this_reader_knows_is_refused_by_name():
    """Catches the silent-corruption case the contract names explicitly: a row from a future schema parsed as if it
    were this one, instead of refused with both version numbers so an operator knows to upgrade the reader rather
    than being told nothing was wrong."""
    future = rec.SCHEMA_VERSION + 1
    with pytest.raises(rec.Incomplete) as exc:
        rec.from_row(row(schema_version=future))
    msg = str(exc.value)
    assert str(future) in msg and str(rec.SCHEMA_VERSION) in msg


def test_a_row_missing_a_required_field_is_refused_naming_it():
    """Catches a row that is short a field this version requires being read anyway with a gap nobody notices --
    the contract requires the raise name the specific field, not a generic parse failure."""
    bad = row(schema_version=2)
    del bad["family"]
    with pytest.raises(rec.Incomplete, match="family"):
        rec.from_row(bad)


def test_a_missing_required_field_is_not_silently_defaulted():
    """Catches a from_row implementation that papers over an absent field with `dict.get(key, default)`, which
    would make a record written short indistinguishable from one that is actually complete -- the contract says
    absent is never defaulted, in those words."""
    bad = row(schema_version=2)
    del bad["policy_version"]
    with pytest.raises(rec.Incomplete):
        rec.from_row(bad)


def test_the_stop_condition_adding_a_field_to_a_real_v010_line_does_not_raise():
    """This is the contract's own stop condition for C1, run directly against the real fixture: add a field to an
    actual v0.1.0 line and confirm the reader survives it instead of raising, which is the regression this whole
    entry exists to prevent."""
    mutated = dict(real_v010_row())
    mutated["a_brand_new_field"] = "anything"
    d, ignored = rec.from_row(mutated)
    # The new field and the two v0.1.0-only candidate fields together: the reader survives an unknown key and
    # names every field it did not model, which is what makes "survives" checkable rather than asserted.
    assert ignored == ["a_brand_new_field", "candidates[0].bound_kind", "candidates[1].bound_kind"]
    assert d.schema_version == 1


def test_a_v010_row_and_a_v020_row_keep_distinct_schema_versions():
    """Catches the two versions being merged into one during read, which is the second half of the contract's
    stop condition: a v0.1.0 row and a v0.2.0 row must each produce a decision carrying the version it was actually
    written with, not a version the reader assigns them both."""
    old, _ = rec.from_row(real_v010_row())
    new, _ = rec.from_row(row(schema_version=2, request_id="r2"))
    assert old.schema_version == 1
    assert new.schema_version == 2


# --- every caller of _as_decision now goes through from_row ------------------------------------------


def test_accept_does_not_raise_on_a_row_carrying_an_unknown_key():
    """Catches accept.py still calling something that splats row keys straight into `Decision(**kw)`: with a real
    unknown key present, the old `_as_decision` raised `TypeError` and no criterion in the whole run could be
    computed, which is the launch blocker C1 exists to remove."""
    rows = [row(schema_version=2, a_future_field="x")]
    v = ac.no_false_certification(rows, floor=0.80, latency_feasible=True)
    assert v.verdict == ac.PASS


def test_accept_reads_a_v010_row_without_a_schema_version_key():
    """Catches accept breaking on the exact input the contract protects: a logged v0.1.0 row with no
    `schema_version` key at all, reaching a criterion computed over the whole log rather than raising before the
    criterion is evaluated."""
    rows = [real_v010_row()]
    v = ac.no_false_certification(rows, floor=0.80, latency_feasible=True)
    # Amendment 5, deliberately changed: this asserted PASS. A pass is what the criterion cannot earn over a log
    # whose bounds carry no recorded provenance -- and this row is a real v0.1.0 line, so its bound has none.
    # UNSUPPORTED names the missing measurement instead, which is the verdict this checker has had since v0.1.0
    # for exactly the case where it cannot check. The synthetic rows above still read PASS, because `cand()`
    # records a provenance the way a v0.2.0 writer does.
    assert v.verdict == ac.UNSUPPORTED
    assert "provenance" in v.detail


def test_default_is_not_a_hiding_place_also_survives_an_unknown_key():
    """Catches only one of accept's two `_as_decision` call sites being migrated to `from_row`, leaving the other
    to raise on the same new field -- a partial migration is a bug that only shows up on whichever criterion runs
    second."""
    rows = [row(schema_version=2, a_future_field="x", certified=False, chosen="fallback",
                candidates=[cand("fallback", "chosen", 0.50), cand("box", "not_priced", 0.95)])]
    v = ac.default_is_not_a_hiding_place(rows, floor=0.80, latency_feasible=True)
    assert v.verdict == ac.FAIL and "hiding place" in v.detail


# --- Log.read: two different failures, counted separately ---------------------------------------------


def test_log_read_separates_unreadable_lines_from_unreadable_rows(tmp_path):
    """Catches the two operator actions being collapsed into one counter. 'The file was truncated' calls for
    repairing disk; 'the record is from a newer schema version' calls for upgrading the reader. A single bucket for
    both loses the distinction the contract requires be kept, and an operator acts on the wrong half of the log."""
    log = rec.Log(tmp_path / "log.jsonl")
    future = rec.SCHEMA_VERSION + 1
    with log.path.open("a") as fh:
        fh.write(json.dumps(row(schema_version=2, request_id="good")) + "\n")
        fh.write("{not json at all\n")
        fh.write(json.dumps(row(schema_version=future, request_id="from_the_future")) + "\n")
    decisions, outcomes = log.read()
    assert len(decisions) == 1
    assert outcomes["__bad_lines__"]["count"] == 1
    assert outcomes["__unreadable_rows__"]["count"] == 1
    # A1.2: the shape is {"count": int, "reasons": list[str]}, one string per row, naming both versions.
    reasons = outcomes["__unreadable_rows__"]["reasons"]
    assert len(reasons) == 1
    assert str(future) in reasons[0] and str(rec.SCHEMA_VERSION) in reasons[0]


def test_a_row_that_fails_from_row_does_not_also_count_as_a_bad_line(tmp_path):
    """Catches a row that parses as valid JSON but fails from_row being double-counted as an unreadable LINE too,
    which would make the two counters overlap instead of partitioning the log's failures."""
    log = rec.Log(tmp_path / "log.jsonl")
    with log.path.open("a") as fh:
        fh.write(json.dumps(row(schema_version=rec.SCHEMA_VERSION + 1)) + "\n")
    _, outcomes = log.read()
    assert outcomes.get("__bad_lines__", {}).get("count", 0) == 0
    assert outcomes["__unreadable_rows__"]["count"] == 1
    assert len(outcomes["__unreadable_rows__"]["reasons"]) == 1


# --- amendment 1: the candidate row, __unreadable_rows__'s shape, and version-before-fields -----------


def test_a_candidate_carrying_an_unknown_key_is_ignored_and_named_by_position():
    """A1.1: catches a candidate-level unknown key being silently dropped instead of reported. F12 proposes
    replacing bound_n/bound_attempted with an evidence reference -- a candidate-level field -- so a reader that
    exists to survive the log's evolution must survive it at that growth site too, not only on the decision's own
    fields. Named with an index, not always index 0, because a position qualifier that is always candidates[0] is
    the defect this clause is most likely to ship with."""
    candidates = [cand(), cand("api", "below_floor", 0.70, 0.012)]
    candidates[1]["evidence_ref"] = "ev:abc123"
    d, ignored = rec.from_row(row(schema_version=2, candidates=candidates))
    assert "candidates[1].evidence_ref" in ignored
    assert d.request_id == "r1"


def test_a_candidate_missing_a_required_field_raises_incomplete_naming_it_not_typeerror():
    """A1.1's negative case: catches a candidate row short a required field reaching the old raw `_as_candidate`
    splat and raising `KeyError`/`TypeError` instead of the same named `Incomplete` a decision-level omission gets."""
    candidates = [cand(), cand("api", "below_floor", 0.70, 0.012)]
    del candidates[1]["excluded_because"]
    with pytest.raises(rec.Incomplete, match="excluded_because"):
        rec.from_row(row(schema_version=2, candidates=candidates))


def test_the_version_check_happens_before_field_validation():
    """A1.3: catches from_row validating fields before checking the version. A row from a future schema cannot be
    meaningfully checked against a shape it was not written to, so a row that is both from the future AND missing a
    field this reader requires must refuse with the version message, not a spurious 'missing field' one."""
    bad = row(schema_version=rec.SCHEMA_VERSION + 1)
    del bad["family"]
    with pytest.raises(rec.Incomplete) as exc:
        rec.from_row(bad)
    msg = str(exc.value)
    assert str(rec.SCHEMA_VERSION + 1) in msg and str(rec.SCHEMA_VERSION) in msg
    assert "family" not in msg


def test_a_row_that_fails_from_row_is_absent_from_decisions_not_kept_for_audit(tmp_path):
    """A1.3: catches a row that fails from_row being appended to `decisions` anyway -- e.g. 'for audit' -- when the
    amendment settles that it exists in __unreadable_rows__ and nowhere else. Checked by request id, not by
    length, so a partial or raw row slipped in under a different index would still be caught."""
    log = rec.Log(tmp_path / "log.jsonl")
    with log.path.open("a") as fh:
        fh.write(json.dumps(row(schema_version=2, request_id="good")) + "\n")
        fh.write(json.dumps(row(schema_version=rec.SCHEMA_VERSION + 1, request_id="from_the_future")) + "\n")
    decisions, outcomes = log.read()
    ids = {d["request_id"] if isinstance(d, dict) else d.request_id for d in decisions}
    assert ids == {"good"}
