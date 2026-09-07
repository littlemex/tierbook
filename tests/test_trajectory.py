"""Reading a stored run back, and the claims a re-ask does and does not license.

The requirement being served is that captured data can be asked a question afterwards. Each test here is a
way that path could look like it works while producing something nobody may quote.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import trajectory as tj  # noqa: E402


def store(tmp_path, sessions, messages, parts, *, with_wal=True):
    """A store shaped like the agent's own, so a schema change upstream breaks a test rather than a report."""
    p = tmp_path / "opencode.db"
    c = sqlite3.connect(p)
    c.execute("create table session (id text primary key, parent_id text)")
    c.execute("create table message (id text primary key, session_id text, time_created int, data text)")
    c.execute("create table part (id text primary key, message_id text, session_id text, time_created int,"
              " data text)")
    c.executemany("insert into session values (?,?)", sessions)
    c.executemany("insert into message values (?,?,?,?)",
                  [(i, s, t, json.dumps(d)) for i, s, t, d in messages])
    c.executemany("insert into part values (?,?,?,?,?)",
                  [(i, m, s, t, json.dumps(d)) for i, m, s, t, d in parts])
    c.commit()
    c.close()
    if with_wal:
        (tmp_path / "opencode.db-wal").write_bytes(b"")
    return p


def traces(tmp_path, pairs):
    """OTLP-shaped lines carrying `session.id`, which is the join from a run's shape to its content."""
    docs = []
    for trace, sid in pairs:
        docs.append({"resourceSpans": [{"scopeSpans": [{"spans": [
            {"traceId": trace, "name": "opencode.llm",
             "attributes": [{"key": "session.id", "value": {"stringValue": sid}}]}]}]}]})
    p = tmp_path / "traces.jsonl"
    p.write_text("".join(json.dumps(d) + "\n" for d in docs))
    return p


# --- the store is read completely, or it says what it did not read --------------------------------


def test_a_store_copied_without_its_wal_is_reported_not_trusted(tmp_path, capsys):
    """It fails silently: the file opens, the schema is intact, and the newest sessions are absent. One run of
    twenty-four had no content for exactly this reason."""
    p = store(tmp_path, [("s1", None)], [("m1", "s1", 1, {"role": "user"})], [], with_wal=False)
    tj.open_store(p)
    printed = capsys.readouterr().out
    assert "has no -wal beside it" in printed and "may be missing the most recent" in printed


def test_framing_parts_do_not_raise_a_warning_but_unknown_ones_do(tmp_path):
    """A warning that fires on every run is a warning nobody reads, and it would hide the one that matters."""
    p = store(tmp_path, [("s1", None)],
              [("m1", "s1", 1, {"role": "assistant"})],
              [("p1", "m1", "s1", 1, {"type": "step-start"}),
               ("p2", "m1", "s1", 2, {"type": "text", "text": "hi"})])
    traj = tj.read_turns(tj.open_store(p), "s1")
    assert "unread_part_types" not in traj

    q = tmp_path / "other"
    q.mkdir()
    p3 = store(q, [("s1", None)], [("m1", "s1", 1, {"role": "assistant"})],
               [("p1", "m1", "s1", 1, {"type": "something-new"})])
    traj3 = tj.read_turns(tj.open_store(p3), "s1")
    assert traj3["unread_part_types"] == {"something-new": 1}


def test_a_model_spelled_as_an_object_is_normalised_and_kept(tmp_path):
    p = store(tmp_path, [("s1", None)],
              [("m1", "s1", 1, {"role": "user", "model": {"providerID": "vllm", "modelID": "Q/35B"}})], [])
    m = tj.read_turns(tj.open_store(p), "s1")["messages"][0]
    assert m["model"] == "vllm/Q/35B" and m["model_raw"]["modelID"] == "Q/35B"


# --- subagents are structure, not an error -------------------------------------------------------


def test_a_delegating_run_resolves_to_its_root_and_names_the_children(tmp_path):
    """Several sessions on one trace is the ordinary case. Flattening them would attribute a delegate's
    tokens and replies to the thread that delegated."""
    p = store(tmp_path, [("root", None), ("kid", "root")], [], [])
    conn = tj.open_store(p)
    roots, children = tj.roots_and_children(conn, {"root", "kid"})
    assert roots == ["root"] and children == {"kid": "root"}


def test_two_root_sessions_on_one_trace_are_refused(tmp_path):
    """Two independent threads under one trace id cannot be read as one run, and picking either would be a
    silent choice about whose turns these are."""
    p = store(tmp_path, [("a", None), ("b", None)], [], [])
    roots, _ = tj.roots_and_children(tj.open_store(p), {"a", "b"})
    assert sorted(roots) == ["a", "b"], "the caller refuses on more than one root; this is the input to that"


# --- the context is what the candidate would be asked, and nothing after -------------------------


def test_the_context_stops_at_the_turn_and_excludes_the_reply(tmp_path):
    """A context that included the reply would ask the candidate to produce an answer it can already see."""
    p = store(tmp_path, [("s1", None)],
              [("m1", "s1", 1, {"role": "user"}), ("m2", "s1", 2, {"role": "assistant"})],
              [("p1", "m1", "s1", 1, {"type": "text", "text": "the task"}),
               ("p2", "m2", "s1", 2, {"type": "text", "text": "the answer"})])
    traj = tj.read_turns(tj.open_store(p), "s1")
    ctx = tj.turn_context(traj, 0)
    assert [c["content"] for c in ctx] == ["the task"]
    assert "the answer" not in json.dumps(ctx)


def test_a_turn_outside_the_stored_run_is_refused(tmp_path):
    p = store(tmp_path, [("s1", None)], [("m1", "s1", 1, {"role": "user"})],
              [("p1", "m1", "s1", 1, {"type": "text", "text": "x"})])
    traj = tj.read_turns(tj.open_store(p), "s1")
    with pytest.raises(SystemExit) as e:
        tj.turn_context(traj, 7)
    assert "outside the 1 messages" in str(e.value)


# --- what a re-ask licenses ----------------------------------------------------------------------


def test_replaying_a_whole_run_is_refused_with_the_reason():
    """A different candidate diverges at the first turn it handles differently, and every stored tool result
    after that belongs to the observed run's actions. The replay would credit the candidate for actions it
    did not choose."""
    with pytest.raises(NotImplementedError) as e:
        tj.replay_whole_run()
    msg = str(e.value)
    assert "did not choose" in msg and "single turn" in msg


def test_a_reply_cut_off_at_the_cap_is_cost_only(monkeypatch):
    """A truncated reply is a complete cost observation and an incomplete answer. Comparing it to the stored
    reply as an answer would be scoring the cap."""
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    import urllib.request
    payload = {"model": "M", "usage": {"prompt_tokens": 100, "completion_tokens": 8},
               "choices": [{"finish_reason": "length", "message": {"content": "cut"}}]}
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _fake(json.dumps(payload).encode()))
    r = tj.reask([{"role": "user", "content": "x"}], endpoint="http://x/v1", model="M", max_tokens=8,
                 timeout=5)
    assert r["comparable_as"] == "cost_only" and "scoring the cap" in r["comparable_note"]
    assert r["legs"]["out"] == 8


def test_a_complete_reply_is_comparable_as_both(monkeypatch):
    import urllib.request
    payload = {"model": "M", "usage": {"prompt_tokens": 100, "completion_tokens": 8},
               "choices": [{"finish_reason": "stop", "message": {"content": "done"}}]}
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _fake(json.dumps(payload).encode()))
    r = tj.reask([{"role": "user", "content": "x"}], endpoint="http://x/v1", model="M", max_tokens=99,
                 timeout=5)
    assert r["comparable_as"] == "cost_and_answer" and "comparable_note" not in r


def test_the_disjoint_cache_convention_is_not_subtracted_twice(monkeypatch):
    """Two conventions for one quantity, and this project has already fixed the subtraction once in the sweep
    path. A re-ask that got it wrong would report a cheaper turn than was billed."""
    import urllib.request
    payload = {"model": "M",
               "usage": {"prompt_tokens": 100, "completion_tokens": 5,
                         "cache_read_input_tokens": 900, "cache_creation_input_tokens": 50},
               "choices": [{"finish_reason": "stop", "message": {"content": "d"}}]}
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _fake(json.dumps(payload).encode()))
    r = tj.reask([{"role": "user", "content": "x"}], endpoint="http://x/v1", model="M", max_tokens=9,
                 timeout=5)
    assert r["legs"] == {"fresh_in": 100, "cached_in": 900, "cache_write": 50, "out": 5}


def test_the_subset_convention_subtracts_so_the_legs_do_not_double_count(monkeypatch):
    import urllib.request
    payload = {"model": "M",
               "usage": {"prompt_tokens": 1000, "completion_tokens": 5,
                         "prompt_tokens_details": {"cached_tokens": 900, "created_cache_tokens": 50}},
               "choices": [{"finish_reason": "stop", "message": {"content": "d"}}]}
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _fake(json.dumps(payload).encode()))
    r = tj.reask([{"role": "user", "content": "x"}], endpoint="http://x/v1", model="M", max_tokens=9,
                 timeout=5)
    assert r["legs"] == {"fresh_in": 50, "cached_in": 900, "cache_write": 50, "out": 5}


# --- repricing needs no re-issue at all ----------------------------------------------------------


def test_repricing_recorded_legs_needs_no_call():
    """The cheapest counterfactual available, and the one most often wanted: the legs are already observed, so
    a different card is arithmetic on them."""
    legs = {"fresh_in": 1_000_000, "cached_in": 1_000_000, "cache_write": 0, "out": 100_000}
    card = {"fresh_in": 1.0, "cached_in": 0.1, "cache_write": 1.25, "output": 10.0}
    assert tj.reprice(legs, card) == pytest.approx(1.0 + 0.1 + 1.0)


def test_an_absent_rate_is_charged_as_fresh_rather_than_free():
    """Unmeasured is not free -- the same rule the rest of this project applies, held here so a card missing
    its cache line cannot make a cached turn look cheap."""
    legs = {"fresh_in": 0, "cached_in": 1_000_000, "cache_write": 1_000_000, "out": 0}
    card = {"fresh_in": 2.0, "cached_in": None, "cache_write": None, "output": 1.0}
    assert tj.reprice(legs, card) == pytest.approx(4.0)


class _fake:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def test_a_reask_with_no_tools_against_a_tool_answered_turn_is_input_side_only(monkeypatch, tmp_path):
    """The boundary that shows up as a plausible number rather than an error. The first re-ask run here came
    back at the token cap with 14,469 characters of prose where the stored run had answered with a `task`
    call: a model with no tools available explains instead of acting."""
    import urllib.request
    payload = {"model": "M", "usage": {"prompt_tokens": 861, "completion_tokens": 4096},
               "choices": [{"finish_reason": "length", "message": {"content": "prose " * 100}}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _fake(json.dumps(payload).encode()))
    r = tj.reask([{"role": "user", "content": "x"}], endpoint="http://x/v1", model="M", max_tokens=4096,
                 timeout=5, stored_reply_used_tools=True)
    assert r["comparable_as"] == "input_side_only"
    assert "not a comparison" in r["comparable_note"] and "tool schemas" in r["comparable_note"]


def test_whether_the_stored_reply_used_tools_is_read_from_the_store(tmp_path):
    p = store(tmp_path, [("s1", None)],
              [("m1", "s1", 1, {"role": "user"}), ("m2", "s1", 2, {"role": "assistant"})],
              [("p1", "m1", "s1", 1, {"type": "text", "text": "task"}),
               ("p2", "m2", "s1", 2, {"type": "tool", "tool": "bash"})])
    traj = tj.read_turns(tj.open_store(p), "s1")
    assert tj.stored_reply_used_tools(traj, 0) is True
    assert tj.stored_reply_used_tools(traj, 1) is False, "nothing answered the last message"


def test_offering_the_tool_schemas_makes_the_output_side_comparable(monkeypatch):
    import urllib.request
    payload = {"model": "M", "usage": {"prompt_tokens": 861, "completion_tokens": 40},
               "choices": [{"finish_reason": "tool_calls",
                            "message": {"content": None,
                                        "tool_calls": [{"function": {"name": "bash"}}]}}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _fake(json.dumps(payload).encode()))
    r = tj.reask([{"role": "user", "content": "x"}], endpoint="http://x/v1", model="M", max_tokens=4096,
                 timeout=5, tools=[{"type": "function", "function": {"name": "bash"}}],
                 stored_reply_used_tools=True)
    assert r["comparable_as"] == "cost_and_answer"
    assert r["tool_calls"] == ["bash"] and r["tools_offered"] is True


def test_tool_schemas_are_lifted_off_the_wire(tmp_path):
    """They exist nowhere else: the agent builds them at request time, and its session store keeps the calls
    rather than the definitions. The recording pass-through kept the request body, so it has them."""
    log = tmp_path / "tap.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in [
        {"agent": "other", "request": {"model": "M", "tools": [{"function": {"name": "wrong"}}]}},
        {"agent": "opencode", "request": {"model": "M"}},
        {"agent": "opencode", "request": {"model": "M", "tools": [{"function": {"name": "bash"}}]}},
    ]))
    got = tj.tools_from_tap(log, agent="opencode")
    assert [((t.get("function") or {}).get("name")) for t in got] == ["bash"]
    assert tj.tools_from_tap(log, agent="nobody") is None


def test_the_captured_request_is_found_by_its_text_not_by_a_clock_or_an_address(tmp_path):
    """The pass-through carries no trace id -- which is why the rest of this project joins on one -- and its
    caller field is a reverse-DNS host name. The message text is the only sound key."""
    log = tmp_path / "tap.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in [
        {"agent": "ip-10-0-5-211.internal",
         "request": {"model": "M", "messages": [{"role": "user", "content": "solve issue 41 in astropy"}],
                     "tools": [{"function": {"name": "bash"}}]}},
        {"agent": "ip-10-0-5-211.internal",
         "request": {"model": "M", "messages": [{"role": "user", "content": "something else entirely"}],
                     "tools": [{"function": {"name": "read"}}]}},
    ]))
    req = tj.request_from_tap(log, "solve issue 41 in astropy")
    assert req and [((t.get("function") or {}).get("name")) for t in req["tools"]] == ["bash"]
    assert tj.request_from_tap(log, "a turn nobody sent") is None
    assert tj.request_from_tap(log, "") is None, "an empty needle would match the first row of any log"


def test_a_double_encoded_prompt_is_decoded_so_it_matches_the_wire():
    """The store keeps some prompts as JSON string literals, because the driver handed them over as a quoted
    argument. Left encoded, every comparison against the wire finds nothing -- a newline is one character in
    the text and two on the line -- and that reads as "never captured" rather than as a bug."""
    assert tj._unwrap('"You are working\\nin a checkout"') == "You are working\nin a checkout"
    assert tj._unwrap("plain text") == "plain text"
    assert tj._unwrap('"unterminated') == '"unterminated', "not a literal, so not decoded"
    assert tj._unwrap('"a" and "b"') == '"a" and "b"', "quoted at both ends but not one literal"


def test_the_cheap_reject_escapes_the_needle_before_scanning_raw_lines(tmp_path):
    """The bug this guards: comparing decoded text against a raw JSON line rejects every row."""
    log = tmp_path / "tap.jsonl"
    log.write_text(json.dumps({"request": {"model": "M", "tools": [{"function": {"name": "bash"}}],
                                           "messages": [{"role": "user",
                                                         "content": "line one\nline two"}]}}) + "\n")
    assert tj.request_from_tap(log, '"line one\\nline two"') is not None
    assert tj.request_from_tap(log, "line one\nline two") is not None


def test_the_replayed_request_is_the_one_with_tools_and_the_shortest_history(tmp_path):
    """Many captured requests quote a prompt: every later turn carries it in its history, and a summarisation
    call carries it again with no tools at all. Taking the first match got one of those -- three messages,
    zero tool schemas -- and the re-ask measured a different question while looking like a replay."""
    log = tmp_path / "tap.jsonl"
    prompt = "solve the astropy issue"
    log.write_text("".join(json.dumps(r) + "\n" for r in [
        {"request": {"model": "M", "messages": [{"role": "user", "content": prompt},
                                                {"role": "assistant", "content": "..."},
                                                {"role": "user", "content": "summarise"}]}},
        {"request": {"model": "M", "tools": [{"function": {"name": "bash"}}],
                     "messages": [{"role": "user", "content": prompt},
                                  {"role": "assistant", "content": "x"}]}},
        {"request": {"model": "M", "tools": [{"function": {"name": "bash"}}],
                     "messages": [{"role": "user", "content": prompt}]}},
    ]))
    req = tj.request_from_tap(log, prompt)
    assert len(req["messages"]) == 1 and req["tools"]
    assert req["_selected_from"] == {"matched": 3, "with_tool_schemas": 2, "messages": 1,
                                     "rule": req["_selected_from"]["rule"]}
    assert "history only grows" in req["_selected_from"]["rule"]


def test_when_no_match_carries_tool_schemas_the_shortest_is_taken_and_counted(tmp_path):
    """Still a real captured request, and the counts say it had no tools -- which the re-ask then reports as
    input-side-only rather than as a comparison."""
    log = tmp_path / "tap.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in [
        {"request": {"model": "M", "messages": [{"role": "user", "content": "p"},
                                                {"role": "user", "content": "again"}]}},
        {"request": {"model": "M", "messages": [{"role": "user", "content": "p"}]}},
    ]))
    req = tj.request_from_tap(log, "p")
    assert req["_selected_from"]["with_tool_schemas"] == 0 and len(req["messages"]) == 1
