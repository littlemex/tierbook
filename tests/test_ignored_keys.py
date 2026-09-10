"""The keys a read did not understand reach an operator, which is what C1's return value was for.

`from_row` returns `(Decision, ignored)`, and before C12 every production call site discarded the second value:
`Log.read` dropped the whole tuple, and `accept.py` bound it as `_ignored` at three sites. So a reader that
survived a field being added did so by NAMING what it did not understand, to nobody -- which is the same as
dropping it.

The asymmetry is the tell. C11 wired both READ FAILURE classes through to a criterion: a truncated line and a
row from a newer schema each make a rate refuse. The success-with-losses case reached nothing, and it is the one
that happens on the operator action C1's interface names first -- rolling a reader BACK. Every line reads fine,
every criterion computes, and the fields the newer mechanism recorded are absent from every decision the
criteria saw.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import cli  # noqa: E402
from tierbook import record as rec  # noqa: E402


def cand(cid="box", why="chosen", bound=0.90, cost=0.004):
    return {"id": cid, "excluded_because": why, "bound": bound, "bound_kind": "lcb95", "cost_usd": cost,
            "evidence_as_of": "2026-09-01"}


def row(**kw):
    base = {
        "family": "f", "request_id": "r1", "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": [cand(), cand("api", "below_floor", 0.70, 0.012)], "chosen": "box",
        "selection_probability": 1.0, "exploration": False, "certified": True, "policy_version": "p1",
        "mechanism_version": "0.2.0", "agent": "a", "model": "m", "endpoint": "http://e",
        "gateway_quote_usd": 0.004, "gateway_authorised": True, "decided_at": 1_780_000_000.0,
        "gaps": [], "label_state": "pending", "label": None, "outcome": {},
        "schema_version": rec.SCHEMA_VERSION, "exploration_reason": "no_mechanism", "eligible_set": [],
    }
    base.update(kw)
    return base


def write(path: Path, rows: list) -> Path:
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


def run_cli(argv: list) -> int:
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


# --- Log.read carries the names ----------------------------------------------------------------------


def test_log_read_names_the_keys_it_ignored(tmp_path):
    """Catches the list being computed and thrown away, which is what happened at every call site. The count
    alone is not enough and the next test says why, but a read that reports nothing at all is the defect."""
    log = rec.Log(write(tmp_path / "d.jsonl", [row(request_id="a", evidence_ref="x"),
                                               row(request_id="b", evidence_ref="y")]))
    _decisions, outcomes = log.read()
    assert "__ignored_keys__" in outcomes
    assert outcomes["__ignored_keys__"]["evidence_ref"] == 2


def test_the_names_are_carried_not_only_a_count(tmp_path):
    """Catches a counter without names. "This reader ignored 4,000 keys" and "this reader does not know
    evidence_ref" call for the same action and only the second says what to do -- upgrade the reader, or accept
    that this field is not in the population your criteria saw."""
    log = rec.Log(write(tmp_path / "d.jsonl", [row(request_id="a", evidence_ref="x", stratum="s"),
                                               row(request_id="b", stratum="s")]))
    _decisions, outcomes = log.read()
    assert outcomes["__ignored_keys__"] == {"evidence_ref": 1, "stratum": 2}


def test_a_log_with_nothing_ignored_carries_no_entry(tmp_path):
    """Catches an always-present key, which would make the signal noise: an operator scanning a report for it
    has to be able to read its absence as "this reader understood every field in every row"."""
    log = rec.Log(write(tmp_path / "d.jsonl", [row(request_id="a"), row(request_id="b")]))
    _decisions, outcomes = log.read()
    assert "__ignored_keys__" not in outcomes


def test_a_version_1_row_ignores_nothing_rather_than_reporting_its_absent_fields(tmp_path):
    """The direction that must NOT produce a report. A v0.1.0 row lacks the fields v0.2.0 added, and `from_row`
    SUPPLIES them per SEAMS S4 -- it did not fail to understand anything. Reporting them here would make every
    old log look like a reader problem, which is the opposite of the case this entry exists for."""
    v1 = {k: v for k, v in row().items()
          if k not in ("schema_version", "exploration_reason", "eligible_set")}
    log = rec.Log(write(tmp_path / "d.jsonl", [v1]))
    decisions, outcomes = log.read()
    assert len(decisions) == 1
    assert "__ignored_keys__" not in outcomes


# --- and it does not narrow any population ----------------------------------------------------------


def test_an_ignored_key_does_not_make_a_criterion_refuse(tmp_path):
    """The distinction C1's return value exists to express, and the reason this is not C11's guard. Nothing was
    lost from the population -- the rows are all there and all readable. Refusing here would make every
    reader-behind-its-log run unusable rather than annotated."""
    from tierbook import accept as ac

    rows = [row(request_id=f"r{i}", evidence_ref="x") for i in range(30)]
    log = rec.Log(write(tmp_path / "d.jsonl", rows))
    for i in range(30):
        log.attach_outcome(f"r{i}", label_state="labelled", label=True)
    decisions, outcomes = log.read()
    assert outcomes["__ignored_keys__"]["evidence_ref"] == 30
    v = [x for x in ac.check_all(decisions, outcomes, floor=0.80, latency_feasible=True)
        if x.criterion == "no_false_certification"][0]
    assert v.verdict != ac.UNSUPPORTED, "an ignored key is not an incomplete population"


# --- the report records it ---------------------------------------------------------------------------


def test_the_accept_report_records_the_ignored_keys(tmp_path):
    """Amendment 11's reason, in the value C12 surfaces: a criterion computed over rows whose new fields were
    dropped is not wrong, but a committed report that cannot say so is unreadable later."""
    log = rec.Log(write(tmp_path / "d.jsonl", [row(request_id="a", evidence_ref="x")]))
    out = tmp_path / "report.json"
    run_cli(["accept", "--log", str(log.path), "--floor", "0.80", "--out", str(out)])
    report = json.loads(out.read_text())
    assert report["ignored_keys"] == {"evidence_ref": 1}


def test_a_report_over_a_fully_understood_log_says_so_rather_than_omitting_the_key(tmp_path):
    """Catches the key being present only on the bad path, which would leave a reader unable to tell "this
    reader understood everything" from "this version of the tool did not look"."""
    log = rec.Log(write(tmp_path / "d.jsonl", [row(request_id="a")]))
    out = tmp_path / "report.json"
    run_cli(["accept", "--log", str(log.path), "--floor", "0.80", "--out", str(out)])
    report = json.loads(out.read_text())
    assert report["ignored_keys"] == {}
