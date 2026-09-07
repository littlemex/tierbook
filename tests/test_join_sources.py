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


def span(trace, name, *, start, legs=None, provider="vllm-local", model="M", agent="a",
         all_billed_legs=True):
    """A span shaped like the producer's.

    Every billed leg is emitted by default, at zero where not given, because that is what a real producer
    does -- vLLM reports the cache legs explicitly rather than omitting them. A fixture that omitted them
    would be testing against a producer nobody runs, and it would make the unpriceable-row refusal fire
    everywhere. Pass `all_billed_legs=False` to test that refusal.
    """
    attrs = {"agent.name": agent, "llm.model_name": model, "llm.provider": provider,
             "llm.finish_reason": "stop", "duration_ms": 100}
    if all_billed_legs:
        for leg in js.BILLED_LEGS:
            attrs[js.LEGS[leg]] = 0
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
    # Only two legs are present on the span; the others are simply absent, which is how a producer
    # that renamed or stopped emitting one would look.
    p = write_traces(tmp_path, [
        span("t1", "opencode.llm", start=1, legs={"out": 5, "fresh_in": 10}, all_billed_legs=False)])
    res = js.join({"t1": {"trace_id": "t1", "state": "solved"}}, js.read_traces(p), {},
                  metered_providers=set())
    row = res["rows"][0]
    # Only BILLED legs count as a gap. `reasoning` is charged under output by every card here, so a span
    # without it is an ordinary non-reasoning turn rather than a hole in the billing record -- and a gap
    # reported on every row is a gap nobody reads.
    assert row["missing_legs"] == ["cache_write", "cached_in"]
    assert row["legs"] == {"fresh_in": 10, "out": 5, "cache_write": 0, "cached_in": 0, "reasoning": 0}, \
        "the sum still computes so a reader can see it, but the row is marked unpriceable beside it"
    assert row["priceable"] is False and "not a zero leg" in row["unpriceable_because"]
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
    argv = ["join_sources", "--outcomes", str(outcomes), "--traces", str(traces), "--out", str(out),
            "--no-metered-candidates"]
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
    # The output is still written, because naming what is unjoined is the point -- but it must not carry the
    # cost figures the refusal says it is withholding.
    doc = json.loads(out.read_text())
    assert doc["coverage"]["unjoined"][0]["missing"] == "telemetry"
    assert "refused" in doc
    assert all(r["cost"]["usd"] is None and "withheld_because" in r["cost"] for r in doc["rows"])


# --- the cross-check reports divergence and never averages it ------------------------------------


def test_crosscheck_flags_a_renamed_leg_as_one_side_zero(tmp_path):
    """The shape of a producer renaming an attribute: one source has the tokens, the other has zero.

    Reported as `one_side_zero` rather than as a ratio, because a ratio against zero is not a number and
    silently skipping the leg is how a rename becomes a missing measurement nobody noticed.
    """
    import crosscheck_telemetry as cc  # noqa: PLC0415

    tap = {"legs": {"fresh_in": 100, "cached_in": 900, "cache_write": 0, "out": 10}, "calls": 1}
    telem = {"legs": {"fresh_in": 100, "cached_in": 0, "cache_write": 0, "out": 10}, "calls": 1}
    res = cc.compare(tap, telem, tolerance=1.10)
    assert res["legs"]["cached_in"]["one_side_zero"] is True
    assert res["legs"]["cached_in"]["ratio"] is None
    assert res["within_tolerance"] is False
    # The legs that agree are still reported as agreeing, so a reader can see the disagreement is local.
    assert res["legs"]["fresh_in"]["ratio"] == 1.0


def test_crosscheck_passes_when_both_sources_agree(tmp_path):
    import crosscheck_telemetry as cc  # noqa: PLC0415

    same = {"legs": {"fresh_in": 5, "cached_in": 6, "cache_write": 7, "out": 8}, "calls": 2}
    res = cc.compare(same, dict(same), tolerance=1.10)
    assert res["within_tolerance"] and res["worst_ratio"] == 1.0


def test_crosscheck_reports_a_small_difference_without_flagging_it(tmp_path):
    """A retried attempt one side counted and the other abandoned is an expected small difference. The
    check reports it and does not declare a winner."""
    import crosscheck_telemetry as cc  # noqa: PLC0415

    res = cc.compare({"legs": {"fresh_in": 100, "cached_in": 0, "cache_write": 0, "out": 10}, "calls": 1},
                     {"legs": {"fresh_in": 105, "cached_in": 0, "cache_write": 0, "out": 10}, "calls": 1},
                     tolerance=1.10)
    assert res["within_tolerance"] is True
    assert res["legs"]["fresh_in"]["ratio"] == 1.05


# --- which runs are this cohort's, by two independent means ---------------------------------------


def run_cli(tmp_path, outcomes, traces, *extra):
    out = tmp_path / f"joined-{len(list(tmp_path.iterdir()))}.json"
    if not any(x.startswith("--metered-providers") or x == "--no-metered-candidates" for x in extra):
        extra = (*extra, "--no-metered-candidates")
    argv = ["join_sources", "--outcomes", str(outcomes), "--traces", str(traces),
            "--out", str(out), *extra]
    old = sys.argv
    sys.argv = argv
    try:
        code = js.main()
    finally:
        sys.argv = old
    return code, out


def test_another_groups_rows_are_excluded_and_named(tmp_path):
    """The guard's purpose: an orphaned driver from an aborted sweep must not pose as this cohort's."""
    traces = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1}),
                                     span("t2", "opencode.llm", start=1, legs={"out": 1})])
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [
        {"trace_id": "t1", "item_id": "i1", "state": "solved", "run_group": "mine"},
        {"trace_id": "t2", "item_id": "i1", "state": "solved", "run_group": "orphan"},
    ])
    code, out = run_cli(tmp_path, outcomes, traces, "--run-group", "mine")
    doc = json.loads(out.read_text())
    assert code == 0
    assert doc["selection"]["selected"] == 1
    assert doc["selection"]["other_groups_excluded"][0]["run_group"] == "orphan"
    assert doc["trials"]["trials_per_item"] == 1


def test_an_unstamped_row_is_excluded_by_default_and_named(tmp_path):
    """A row with no stamp is real data, so it is named rather than silently dropped -- but admitting it
    without being asked would defeat the guard it is missing."""
    traces = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1}),
                                     span("t2", "opencode.llm", start=1, legs={"out": 1})])
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [
        {"trace_id": "t1", "item_id": "i1", "state": "solved", "run_group": "mine"},
        {"trace_id": "t2", "item_id": "i2", "state": "solved"},
    ])
    code, out = run_cli(tmp_path, outcomes, traces, "--run-group", "mine")
    doc = json.loads(out.read_text())
    sel = doc["selection"]
    assert sel["selected"] == 1
    assert sel["unstamped"][0]["item_id"] == "i2" and sel["unstamped_admitted"] is False
    assert code == 0, "one selected row joined, so coverage is complete over what was selected"


def test_admitting_an_unstamped_row_records_that_it_was_an_assertion(tmp_path):
    """Because it is: the driver did not stamp it, the operator said it belonged. A reader of the output has
    to be able to tell those apart."""
    traces = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1}),
                                     span("t2", "opencode.llm", start=1, legs={"out": 1})])
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [
        {"trace_id": "t1", "item_id": "i1", "state": "solved", "run_group": "mine"},
        {"trace_id": "t2", "item_id": "i2", "state": "solved"},
    ])
    code, out = run_cli(tmp_path, outcomes, traces, "--run-group", "mine", "--admit-unstamped")
    sel = json.loads(out.read_text())["selection"]
    assert code == 0 and sel["selected"] == 2
    assert sel["unstamped_admitted"] is True
    assert "not on the driver's stamp" in sel["unstamped_note"]


def test_a_duplicate_trial_is_refused_even_with_no_stamps_anywhere(tmp_path, capsys):
    """The invariant, independent of the stamp. The stamp is intent and a mid-flight edit can drop it; two
    rows for one (item, candidate) is visible in the data regardless, and it is the shape of the duplicate
    that reached a ledger once before."""
    traces = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1}),
                                     span("t2", "opencode.llm", start=1, legs={"out": 1}),
                                     span("t3", "opencode.llm", start=1, legs={"out": 1})])
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [
        {"trace_id": "t1", "item_id": "i1", "state": "solved"},
        {"trace_id": "t2", "item_id": "i1", "state": "incorrect"},
        {"trace_id": "t3", "item_id": "i2", "state": "solved"},
    ])
    code, out = run_cli(tmp_path, outcomes, traces)
    assert code == 4
    printed = capsys.readouterr().out
    assert "REFUSED" in printed and "not uniform" in printed and "i1" in printed
    tr = json.loads(out.read_text())["trials"]
    assert tr["uniform"] is False and tr["trials_per_item"] is None


def test_a_repeated_sweep_is_uniform_and_reports_its_own_number(tmp_path):
    """Two trials of every item is a legitimate sweep, and the number belongs in the record rather than a
    hardcoded 1 -- describing a repeated sweep as single-trial is the same error as the duplicate above,
    read from the other side."""
    spans, rows = [], []
    for i, (item, tid) in enumerate([("i1", "t1"), ("i1", "t2"), ("i2", "t3"), ("i2", "t4")]):
        spans.append(span(tid, "opencode.llm", start=1, legs={"out": 1}))
        rows.append({"trace_id": tid, "item_id": item, "state": "solved", "run_group": "mine"})
    traces = write_traces(tmp_path, spans)
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", rows)
    code, out = run_cli(tmp_path, outcomes, traces, "--run-group", "mine")
    assert code == 0
    assert json.loads(out.read_text())["trials"]["trials_per_item"] == 2


# --- the refusals actually refuse, and the unsafe state is not the default -------------------------


def test_forgetting_to_say_which_providers_are_metered_is_refused(tmp_path):
    """The unsafe state was the default: with no flag, every provider is fixed-cost, no charge is demanded of
    anything, and coverage comes out 100% on a cohort whose gateway figures were never consulted."""
    traces = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1})])
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [{"trace_id": "t1", "item_id": "i1",
                                                        "state": "solved"}])
    out = tmp_path / "j.json"
    old = sys.argv
    sys.argv = ["join_sources", "--outcomes", str(outcomes), "--traces", str(traces), "--out", str(out)]
    try:
        with pytest.raises(SystemExit) as e:
            js.main()
    finally:
        sys.argv = old
    assert "--no-metered-candidates" in str(e.value)


def test_a_row_missing_a_token_leg_is_refused_rather_than_summed_as_zero(tmp_path, capsys):
    """`read_traces` reads an absent attribute as 0, so a total over such turns is below what was billed --
    and reporting `missing_legs` beside that total left the total looking usable."""
    doc = {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": "t1", "name": "opencode.llm", "startTimeUnixNano": "1",
         "attributes": [{"key": "llm.token_count.prompt", "value": {"intValue": "10"}},
                        {"key": "llm.provider", "value": {"stringValue": "vllm-local"}}]}]}]}]}
    traces = tmp_path / "tr.jsonl"
    traces.write_text(json.dumps(doc) + "\n")
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [{"trace_id": "t1", "item_id": "i1",
                                                        "state": "solved"}])
    code, out = run_cli(tmp_path, outcomes, traces)
    assert code == 5
    printed = capsys.readouterr().out
    assert "absent leg is not a zero leg" in printed
    d = json.loads(out.read_text())
    assert d["rows"][0]["priceable"] is False and "refused" in d
    assert d["rows"][0]["cost"]["usd"] is None


def test_two_outcome_rows_under_one_trace_id_are_counted_not_overwritten(tmp_path, capsys):
    """The plausible artifact of a driver that retried while reusing the id it had issued. Collapsed to one
    row, the collision never reaches the trials invariant -- which is what makes the count look right."""
    traces = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1})])
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [
        {"trace_id": "t1", "item_id": "i1", "state": "solved"},
        {"trace_id": "t1", "item_id": "i1", "state": "incorrect"},
    ])
    code, out = run_cli(tmp_path, outcomes, traces)
    doc = json.loads(out.read_text())
    coll = doc["selection"]["trace_id_collisions"]
    assert len(coll) == 1 and coll[0]["kept_state"] == "solved" and coll[0]["dropped_state"] == "incorrect"
    # Refused, not merely counted: which run the surviving row describes is ambiguous, and everything downstream
    # keys on the trace id.
    assert code == 6
    assert "REFUSED" in capsys.readouterr().out
    assert doc["rows"][0]["cost"]["usd"] is None


def test_a_charge_with_no_outcome_row_is_money_attributed_to_nothing(tmp_path, capsys):
    """The loop iterates outcomes, so it never visits a charge it has no outcome for. For a framework whose
    purpose is cost, that is the worst silent loss available."""
    traces = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1},
                                          provider="api-x")])
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [{"trace_id": "t1", "item_id": "i1",
                                                        "state": "solved"}])
    charges = write_jsonl(tmp_path, "charges.jsonl", [
        {"trace_id": "t1", "usd": 0.10, "request_id": "r1"},
        {"trace_id": "ghost", "usd": 0.25, "request_id": "r2"},
    ])
    code, out = run_cli(tmp_path, outcomes, traces, "--charges", str(charges),
                        "--metered-providers", "api-x")
    doc = json.loads(out.read_text())
    cov = doc["coverage"]
    assert cov["charges_with_no_outcome_usd"] == 0.25
    assert cov["charges_with_no_outcome"][0]["gateway_request_id"] == "r2"
    # Refused. A cost figure that excludes unattributed spend is not this cohort's cost; it is the cost of the
    # part that joined.
    assert code == 7 and "REFUSED" in capsys.readouterr().out
    assert doc["rows"][0]["cost"]["usd"] is None


def test_trials_are_keyed_by_the_whole_candidate_not_the_agent(tmp_path):
    """Keyed on the agent alone, a three-model sweep counts three trials per item, and a duplicate of one
    model alongside a gap in another still sums to three and passes as uniform."""
    spans, rows = [], []
    for tid, item, model in [("t1", "i1", "A"), ("t2", "i1", "A"), ("t3", "i1", "B")]:
        spans.append(span(tid, "opencode.llm", start=1, legs={"out": 1}, model=model))
        rows.append({"trace_id": tid, "item_id": item, "state": "solved"})
    traces = write_traces(tmp_path, spans)
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", rows)
    code, out = run_cli(tmp_path, outcomes, traces)
    tr = json.loads(out.read_text())["trials"]
    assert code == 4, "two trials of (i1, A) and one of (i1, B) is not uniform"
    assert tr["candidates_seen"] == 2
    assert any(u["model"] == "A" and u["trials"] == 2 for u in tr["uneven"])


def test_an_admitted_unstamped_row_is_marked_on_the_row(tmp_path):
    """Recorded only in the summary, the row is indistinguishable from a stamped one -- and every consumer
    reads rows, so the assertion-versus-observation distinction is lost exactly where it matters."""
    traces = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1}),
                                     span("t2", "opencode.llm", start=1, legs={"out": 1})])
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [
        {"trace_id": "t1", "item_id": "i1", "state": "solved", "run_group": "mine"},
        {"trace_id": "t2", "item_id": "i2", "state": "solved"},
    ])
    code, out = run_cli(tmp_path, outcomes, traces, "--run-group", "mine", "--admit-unstamped")
    rows = {r["item_id"]: r for r in json.loads(out.read_text())["rows"]}
    assert "cohort_membership" not in rows["i1"]
    assert rows["i2"]["cohort_membership"] == "asserted_by_operator_no_driver_stamp"


def test_a_run_whose_turns_used_different_candidates_is_not_attributed_to_one(tmp_path):
    """The provider set was already computed to decide metering, so the information to notice this was there.
    Stamping the row with the first turn's model misattributes the rest."""
    traces = write_traces(tmp_path, [span("t1", "opencode.llm", start=1, legs={"out": 1}, model="A"),
                                     span("t1", "opencode.llm", start=2, legs={"out": 1}, model="B")])
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", [{"trace_id": "t1", "item_id": "i1",
                                                        "state": "solved"}])
    code, out = run_cli(tmp_path, outcomes, traces)
    row = json.loads(out.read_text())["rows"][0]
    assert row["candidate"] is None
    assert [c["model"] for c in row["candidates_mixed"]] == ["A", "B"]


def test_uniform_trials_do_not_rule_out_a_cohort_collected_twice(tmp_path):
    """Two runs of everything are uniform at two. The caveat says so rather than letting the invariant look
    stronger than it is."""
    spans, rows = [], []
    for tid, item in [("t1", "i1"), ("t2", "i1"), ("t3", "i2"), ("t4", "i2")]:
        spans.append(span(tid, "opencode.llm", start=1, legs={"out": 1}))
        rows.append({"trace_id": tid, "item_id": item, "state": "solved"})
    traces = write_traces(tmp_path, spans)
    outcomes = write_jsonl(tmp_path, "outcomes.jsonl", rows)
    code, out = run_cli(tmp_path, outcomes, traces)
    tr = json.loads(out.read_text())["trials"]
    assert code == 0 and tr["trials_per_item"] == 2
    assert "collected twice" in tr["uniformity_caveat"]


# --- the gateway's charge reaches the record, or its absence is explained -------------------------


def test_a_metered_cohorts_charge_reaches_the_family_record(tmp_path):
    """It was accumulated and discarded, so a metered cohort produced a record with no charge and came out
    unrankable on cost -- a silent hole exactly where the framework's purpose is."""
    import subprocess
    joined = tmp_path / "joined.json"
    joined.write_text(json.dumps({
        "rows": [
            {"trace_id": "t1", "item_id": "i1", "state": "solved", "wall_s": 10.0, "turns": 2,
             "candidate": {"agent": "a", "model": "M", "provider": "api-x"},
             "legs": {"fresh_in": 100, "cached_in": 0, "cache_write": 0, "out": 10},
             "cost": {"kind": "per_request_metered", "usd": 0.10}},
            {"trace_id": "t2", "item_id": "i2", "state": "incorrect", "wall_s": 12.0, "turns": 3,
             "candidate": {"agent": "a", "model": "M", "provider": "api-x"},
             "legs": {"fresh_in": 200, "cached_in": 0, "cache_write": 0, "out": 20},
             "cost": {"kind": "per_request_metered", "usd": 0.25}},
        ],
        "coverage": {"outcomes": 2, "joined": 2, "rate": 1.0, "unjoined": []},
        "trials": {"uniform": True, "trials_per_item": 1, "observed": [1]},
    }))
    out = tmp_path / "led"
    r = subprocess.run([sys.executable, str(ROOT / "harness" / "sweep_to_ledger.py"),
                        "--joined", str(joined), "--out", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    rec = json.loads((out / "tiers" / "agent-a.json").read_text())
    assert rec["families"]["agentic-coding"]["bill_usd"] == pytest.approx(0.35)


def test_a_mixed_cohort_does_not_present_the_metered_subsets_bill_as_the_whole(tmp_path):
    """Summed over the metered subset it would read as the cohort's bill, which is the same class of error as a
    cost over the rows that happened to join."""
    import subprocess
    joined = tmp_path / "joined.json"
    joined.write_text(json.dumps({
        "rows": [
            {"trace_id": "t1", "item_id": "i1", "state": "solved", "wall_s": 10.0, "turns": 2,
             "candidate": {"agent": "a", "model": "M", "provider": "api-x"},
             "legs": {"fresh_in": 100, "cached_in": 0, "cache_write": 0, "out": 10},
             "cost": {"kind": "per_request_metered", "usd": 0.10}},
            {"trace_id": "t2", "item_id": "i2", "state": "solved", "wall_s": 11.0, "turns": 2,
             "candidate": {"agent": "a", "model": "M", "provider": "api-x"},
             "legs": {"fresh_in": 100, "cached_in": 0, "cache_write": 0, "out": 10},
             "cost": {"kind": "per_period_amortised", "usd": None}},
        ],
        "coverage": {"outcomes": 2, "joined": 2, "rate": 1.0, "unjoined": []},
        "trials": {"uniform": True, "trials_per_item": 1, "observed": [1]},
    }))
    out = tmp_path / "led"
    r = subprocess.run([sys.executable, str(ROOT / "harness" / "sweep_to_ledger.py"),
                        "--joined", str(joined), "--out", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    fam = json.loads((out / "tiers" / "agent-a.json").read_text())["families"]["agentic-coding"]
    assert "bill_usd" not in fam
    assert "every row carried one" in fam["bill_usd_absent_because"]
