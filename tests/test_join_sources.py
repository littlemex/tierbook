"""The join's failure modes, each of which would otherwise produce a number that reads as complete.

The join exists because three sources with three owners have to meet: the oracle's outcome, the agent's
telemetry, and the gateway's charge. Every test here is a way that meeting can go wrong quietly.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import join_sources as js  # noqa: E402


def span(trace, name, *, start, legs=None, provider="vllm-local", model="M", agent="a"):
    attrs = {"agent.name": agent, "llm.model_name": model, "llm.provider": provider,
             "llm.finish_reason": "stop", "duration_ms": 100}
    for key, value in (legs or {}).items():
        attrs[js.LEGS[key]] = value
    return {"traceId": trace, "spanId": f"s{start}", "name": name,
            "startTimeUnixNano": str(start),
            "attributes": [{"key": k, "value": {"intValue" if isinstance(v, int) else "stringValue": v}}
                           for k, v in attrs.items()]}


def write_traces(tmp, spans):
    p = tmp / "traces.jsonl"
    p.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}) + "\n")
    return p


def write_jsonl(tmp, name, rows):
    p = tmp / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


# --- turn order comes from the producer, not from our reconstruction ------------------------------


def test_turn_order_and_index_come_from_the_spans(tmp_path):
    """Written out of order on purpose: a time-window join loses order the moment runs overlap, and this
    is the property that replaces it."""
    p = write_traces(tmp_path, [
        span("t1", "opencode.llm", start=300, legs={"out": 3}),
        span("t1", "opencode.session", start=1),
        span("t1", "opencode.llm", start=100, legs={"out": 1}),
        span("t1", "opencode.llm", start=200, legs={"out": 2}),
    ])
    turns = js.read_traces(p)["t1"]["turns"]
    assert [t["index"] for t in turns] == [0, 1, 2]
    assert [t["legs"]["out"] for t in turns] == [1, 2, 3]


def test_two_overlapping_runs_stay_separate(tmp_path):
    """The whole reason for a trace id. Interleaved by start time, so a window join would mix them."""
    p = write_traces(tmp_path, [
        span("A", "opencode.llm", start=100, legs={"out": 10}),
        span("B", "opencode.llm", start=110, legs={"out": 20}),
        span("A", "opencode.llm", start=120, legs={"out": 11}),
        span("B", "opencode.llm", start=130, legs={"out": 21}),
    ])
    tr = js.read_traces(p)
    assert [t["legs"]["out"] for t in tr["A"]["turns"]] == [10, 11]
    assert [t["legs"]["out"] for t in tr["B"]["turns"]] == [20, 21]


# --- a partial join produces no cost figure ------------------------------------------------------


def test_missing_telemetry_is_named_not_dropped(tmp_path):
    p = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1})])
    outcomes = {"t1": {"trace_id": "t1", "item_id": "i1", "state": "solved"},
                "t2": {"trace_id": "t2", "item_id": "i2", "state": "solved"}}
    res = js.join(outcomes, js.read_traces(p), {}, metered_providers=set())
    assert res["coverage"]["joined"] == 1
    assert res["coverage"]["rate"] == 0.5
    assert res["coverage"]["unjoined"] == [{"trace_id": "t2", "missing": "telemetry", "item_id": "i2"}]


def test_a_metered_run_with_no_charge_does_not_join(tmp_path):
    """The dangerous case: telemetry and an outcome exist, so the row looks complete, but the charge that
    makes its cost real is absent. Joining it would put a priceless row into a priced total."""
    p = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1}, provider="bedrock")])
    outcomes = {"t1": {"trace_id": "t1", "item_id": "i1", "state": "solved"}}
    res = js.join(outcomes, js.read_traces(p), {}, metered_providers={"bedrock"})
    assert res["rows"] == []
    assert res["coverage"]["unjoined"][0]["missing"] == "charge"


def test_a_fixed_cost_run_with_no_charge_joins_fine(tmp_path):
    """The mirror case, and the one the earlier design got wrong: a fixed-cost candidate has no
    per-request charge to be missing, so its absence is not a shortfall."""
    p = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1}, provider="vllm-local")])
    outcomes = {"t1": {"trace_id": "t1", "item_id": "i1", "state": "solved"}}
    res = js.join(outcomes, js.read_traces(p), {}, metered_providers={"bedrock"})
    assert res["coverage"]["rate"] == 1.0
    assert res["rows"][0]["cost"]["kind"] == js.AMORTISED
    assert res["rows"][0]["cost"]["usd"] is None


# --- the two cost kinds are never one number -----------------------------------------------------


def test_a_metered_row_carries_the_gateway_as_its_source(tmp_path):
    p = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1}, provider="bedrock")])
    outcomes = {"t1": {"trace_id": "t1", "item_id": "i1", "state": "solved"}}
    charges = {"t1": {"trace_id": "t1", "usd": 0.0123, "request_id": "req-9"}}
    res = js.join(outcomes, js.read_traces(p), charges, metered_providers={"bedrock"})
    cost = res["rows"][0]["cost"]
    assert cost == {"kind": js.METERED, "usd": 0.0123, "source": "gateway", "gateway_request_id": "req-9"}


def test_the_amortised_kind_never_carries_a_per_request_number(tmp_path):
    """Dividing an hourly bill by one experimenter's task rate and calling it a cost per task is a mistake
    this project already published. The kind exists so that number cannot be put here."""
    p = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1}, provider="vllm-local")])
    res = js.join({"t1": {"trace_id": "t1", "state": "solved"}}, js.read_traces(p), {},
                  metered_providers={"bedrock"})
    cost = res["rows"][0]["cost"]
    assert cost["usd"] is None
    assert "window" in cost["note"]


# --- an absent leg is not a zero -----------------------------------------------------------------


def test_an_absent_token_leg_is_reported_rather_than_read_as_zero(tmp_path):
    """The producer's vocabulary can change. A leg silently read as 0 is the same class of defect as an
    unreadable usage block settling as a measured zero, which the ledger already refuses."""
    # Only two legs are present on the span; the other three are simply absent, which is how a producer
    # that renamed or stopped emitting one would look.
    p = write_traces(tmp_path, [
        span("t1", "opencode.llm", start=1, legs={"out": 5, "fresh_in": 10})])
    res = js.join({"t1": {"trace_id": "t1", "state": "solved"}}, js.read_traces(p), {},
                  metered_providers=set())
    row = res["rows"][0]
    assert row["missing_legs"] == ["cache_write", "cached_in", "reasoning"]
    assert row["legs"] == {"fresh_in": 10, "out": 5, "cache_write": 0, "cached_in": 0, "reasoning": 0}, \
        "the sum still computes so a reader is not blocked, but every gap is declared beside it"
    # The two legs that WERE present must not appear as missing: that is the difference between
    # "not emitted" and "emitted as zero", and conflating them is the defect this guards.
    assert "out" not in row["missing_legs"] and "fresh_in" not in row["missing_legs"]


def test_unobserved_carries_its_reason_through_the_join(tmp_path):
    p = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 0})])
    outcomes = {"t1": {"trace_id": "t1", "item_id": "i1", "state": "unobserved",
                       "unobserved_reason": "unsupported"}}
    res = js.join(outcomes, js.read_traces(p), {}, metered_providers=set())
    assert res["rows"][0]["state"] == "unobserved"
    assert res["rows"][0]["unobserved_reason"] == "unsupported"


# --- the CLI refuses rather than producing a subset total ----------------------------------------


def test_the_cli_refuses_below_the_coverage_threshold(tmp_path, capsys):
    traces = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1})])
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [
        {"trace_id": "t1", "item_id": "i1", "state": "solved"},
        {"trace_id": "t2", "item_id": "i2", "state": "solved"},
    ])
    out = tmp_path / "joined.json"
    argv = ["join_sources", "--outcomes", str(outcomes), "--traces", str(traces), "--out", str(out)]
    old = sys.argv
    sys.argv = argv
    try:
        with pytest.raises(SystemExit) as caught:
            js.main() if False else (_ for _ in ()).throw(SystemExit(js.main()))
    finally:
        sys.argv = old
    assert caught.value.code == 3
    printed = capsys.readouterr().out
    assert "REFUSED" in printed and "reads as complete" in printed
    # The output is still written, because naming what is unjoined is the point.
    assert json.loads(out.read_text())["coverage"]["unjoined"][0]["missing"] == "telemetry"
