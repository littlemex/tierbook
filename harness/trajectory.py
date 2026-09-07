"""Read a stored run back, and ask one turn of it again under a different choice.

This exists because of a requirement that is not negotiable and does not need defending: the data has to be
captured such that afterwards one can ask what a **different model, or a changed prompt**, would have done.
Capturing token counts, the cost at the time, the turn sequence and the latency is worth doing on its own; the
part that needs building is the path from a captured run back to a question.

**Where the content lives, and why it is not in the telemetry.** The collector deletes the prompt attributes
by name, on purpose: an OTLP pipeline is a place prompts leak from, and stripping them there is cheap. So the
telemetry carries the *shape* of a run -- four billed legs per turn, order, latency, the candidate tuple --
and the agent's own store carries the content. They are joined on `session.id`, which appears on every span
the agent emits, and the join is exact rather than a time window. That division is the design, not a
shortfall: the telemetry is the part that must be safe to keep and ship, and the content stays where the
agent already keeps it.

**Two questions, one answerable and one not.**

*What would this turn have cost, or said, on a different candidate?* Answerable, with one boundary that has to
be stated because it is easy to miss. The turn's **content** is stored and can be re-issued, but the request
the agent actually sent also carried its tool schemas, and those are built at request time and are not in the
store. So a re-ask that offers no tools is asking a different question: the first one run here came back at
the token cap with 14,469 characters of prose where the stored run had answered with a `task` call, because a
model with no tools available explains instead of acting. The input side is like-for-like; the output side is
not, unless the caller supplies the tool schemas. This module reports which of those it got.

Re-pricing needs no re-issue at all and has no such boundary: the legs are already recorded, so a different
price card is arithmetic on them.

*What would the whole run have done?* Not answerable by replay, and this module refuses to pretend. A
different model would take different actions from the point of divergence, so every tool result after that
point is a result of the *observed* run's actions and not of the counterfactual one's. Feeding the stored
results back produces a transcript in which the model appears to have taken actions it did not choose, and
its apparent success is then a property of the harness. `replay_whole_run` therefore raises, with that reason,
rather than returning something a caller could put in a table.

What the single-turn re-ask does establish is narrower and real: on this exact input, that candidate produced
this reply at this cost. Enough to price a turn, to compare two candidates on the same context, and to see
whether a cheaper one would have answered the same -- which is the question a router asks.

SCOPE (see ../SCOPE.md, which governs this file): an instrument. It reads what was captured and states what a
re-ask does and does not license; it decides nothing.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

#: The part types that carry a turn's content. A part type absent from here is not dropped silently -- it is
#: reported, because a store that grew a new part type is a store this no longer reads completely.
TEXT_PARTS = ("text",)
TOOL_PARTS = ("tool", "tool-invocation", "tool_use")
#: Framing the store writes around each step. Not content, and listed so the "part types this does not read"
#: warning stays about types nobody has looked at -- a warning that fires on every run is a warning nobody
#: reads, and it would hide the one that matters.
FRAMING_PARTS = ("step-start", "step-finish")


def open_store(path: Path) -> sqlite3.Connection:
    """Open the agent's store read-only.

    A SQLite database copied without its `-wal` sidecar is missing whatever has not been checkpointed, and it
    fails *silently*: the file opens, the schema is intact, and the most recent sessions are simply absent.
    That happened here -- a run finished ten minutes before the copy and its session was not in it -- so this
    says so rather than leaving a caller to notice that one row of twenty-four had no content.
    """
    if not path.exists():
        raise SystemExit(f"[FAIL] no store at {path}")
    wal = path.with_name(path.name + "-wal")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    if not wal.exists():
        n = conn.execute("select count(*) from session").fetchone()[0]
        print(f"[WARN] {path.name} has no -wal beside it. It holds {n} sessions and may be missing the most "
              f"recent ones: an uncheckpointed write lives in the sidecar, and a copy without it opens "
              f"cleanly with those sessions absent. Copy {wal.name} too.")
    return conn


def sessions_for_trace(traces: Path) -> dict[str, set[str]]:
    """Session ids per trace id, read from the spans' own `session.id`.

    Every span the agent emits carries it, so this is the join from the shape of a run to its content.
    """
    out: dict[str, set[str]] = {}
    for line in traces.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        for rs in doc.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for sp in ss.get("spans", []):
                    tid = sp.get("traceId")
                    if not tid:
                        continue
                    for a in sp.get("attributes", []):
                        if a["key"] == "session.id":
                            v = next(iter((a.get("value") or {}).values()), None)
                            if v:
                                out.setdefault(tid, set()).add(v)
    return out


def roots_and_children(conn: sqlite3.Connection, session_ids: set[str]) -> tuple[list[str], dict[str, str]]:
    """Split a trace's sessions into roots and the subagent sessions beneath them.

    A run with several sessions is the ordinary case, not an error: an agent that delegates opens a session
    per subagent, and the store records the parent. So the structure is read rather than refused -- but a
    subagent's turns are not the main thread's, and flattening them would attribute a delegate's tokens and
    replies to the thread that delegated.
    """
    parents = {}
    for sid in sorted(session_ids):
        row = conn.execute("select parent_id from session where id = ?", (sid,)).fetchone()
        if row is not None:
            parents[sid] = row["parent_id"]
    roots = [s for s, par in parents.items() if not par]
    children = {s: par for s, par in parents.items() if par}
    return roots, children


def _unwrap(text: str) -> str:
    """Decode a text part that was stored as a JSON string literal.

    The store keeps some prompts double-encoded -- the part's `text` is `"You are working in..."`, quotes and
    escaped newlines included -- because the driver handed the prompt to the agent as a quoted argument. Left
    as-is it breaks every comparison against the wire, where the same prompt appears decoded: the leading
    quote and the two-character `\n` mean a substring match on the real text finds nothing. Only a value that
    is *entirely* a JSON string literal is decoded, so ordinary prose that happens to start with a quote is
    untouched.
    """
    t = text.strip()
    if len(t) > 1 and t[0] == '"' and t[-1] == '"':
        try:
            v = json.loads(t)
        except json.JSONDecodeError:
            return text
        if isinstance(v, str):
            return v
    return text


def read_turns(conn: sqlite3.Connection, session_id: str) -> dict:
    """The stored trajectory of one session: messages in order, each with its parts.

    Ordered by the store's own `time_created`, not by anything reconstructed here. Unknown part types are
    counted and named rather than skipped: a store that grew a part type this does not read is a store this
    reads incompletely, and silence would make that look like a short trajectory.
    """
    rows = list(conn.execute(
        "select id, data, time_created from message where session_id = ? order by time_created, id",
        (session_id,)))
    if not rows:
        return {"session_id": session_id, "messages": [], "absent": True}
    messages, unknown = [], {}
    for r in rows:
        d = json.loads(r["data"])
        parts = []
        for p in conn.execute("select data from part where message_id = ? order by time_created, id",
                              (r["id"],)):
            pd = json.loads(p["data"])
            kind = pd.get("type")
            if kind in TEXT_PARTS:
                parts.append({"type": "text", "text": _unwrap(pd.get("text") or "")})
            elif kind in TOOL_PARTS:
                parts.append({"type": "tool", "tool": pd.get("tool") or pd.get("toolName"),
                              "state": (pd.get("state") or {}).get("status")})
            elif kind not in FRAMING_PARTS:
                unknown[kind] = unknown.get(kind, 0) + 1
        # The store spells a model as an object (`{providerID, modelID}`) on some messages and omits it on
        # others. Normalised to one readable string here so a caller never has to know which, and kept in
        # `model_raw` so nothing is lost.
        raw = d.get("model")
        if isinstance(raw, dict):
            model = "/".join(str(raw[k]) for k in ("providerID", "modelID") if raw.get(k)) or None
        else:
            model = raw
        messages.append({"id": r["id"], "role": d.get("role"), "model": model,
                         **({"model_raw": raw} if isinstance(raw, dict) else {}),
                         "agent": d.get("agent"), "parts": parts})
    return {"session_id": session_id, "messages": messages, "absent": False,
            **({"unread_part_types": unknown} if unknown else {})}


def stored_reply_used_tools(traj: dict, index: int) -> bool:
    """Whether the message that answered turn `index` in the observed run called a tool.

    Read from the store rather than assumed, because it decides whether a re-ask without tool schemas is a
    comparison or a different question.
    """
    nxt = traj["messages"][index + 1] if index + 1 < len(traj["messages"]) else None
    return bool(nxt and any(p["type"] == "tool" for p in nxt["parts"]))


def turn_context(traj: dict, index: int) -> list[dict]:
    """The message list as it stood when turn `index` was issued.

    Everything up to and including the user message that prompted it, and nothing after: a context that
    included the reply would be asking the candidate to produce an answer it can already see.
    """
    msgs = traj["messages"]
    if not 0 <= index < len(msgs):
        raise SystemExit(f"[FAIL] turn {index} is outside the {len(msgs)} messages stored for "
                         f"{traj['session_id']}")
    ctx = []
    for m in msgs[:index + 1]:
        text = "\n".join(p["text"] for p in m["parts"] if p["type"] == "text")
        tools = [p["tool"] for p in m["parts"] if p["type"] == "tool" and p.get("tool")]
        if not text and not tools:
            continue
        ctx.append({"role": m["role"] or "user", "content": text,
                    **({"tools_called": tools} if tools else {})})
    return ctx


def replay_whole_run(*_args, **_kwargs):
    """Refused, and the reason is the point.

    A different candidate diverges from the observed run at the first turn it would have handled differently,
    and every tool result after that point is a result of the *observed* run's actions. Feeding those stored
    results back produces a transcript in which the candidate appears to have taken actions it did not choose,
    and its apparent success then measures the harness rather than the candidate. There is no correction for
    this: the counterfactual's tool results were never observed, because the actions that would have produced
    them were never taken.
    """
    raise NotImplementedError(
        "a whole trajectory cannot be replayed against a different candidate. It would diverge at the first "
        "turn it handled differently, and every stored tool result after that point belongs to the observed "
        "run's actions -- so the replay would credit the candidate for actions it did not choose. Re-ask a "
        "single turn, which is answerable, or run the candidate on the task, which is a measurement.")


def tools_from_tap(path: Path, *, agent: str | None = None, model: str | None = None) -> list | None:
    """Lift tool schemas off the wire, from the recording pass-through's captured requests.

    The schemas are a property of the **harness**, not of a turn: an agent sends the same tool set on every
    request until its configuration changes. And the wire is the only place they were captured -- the agent
    builds them at request time, and its session store keeps the *calls*, not the definitions.

    `agent` filters on the pass-through's own `agent` field, and that field is a **reverse-DNS name of the
    caller**, not an agent name: in this cluster it came back as node hostnames for pods behind SNAT and as a
    service name only for one deployment. So it identifies a source host at best. Prefer
    `request_from_tap`, which matches on content and needs no attribution at all.
    """
    for line in _lines(path):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        req = r.get("request")
        if not isinstance(req, dict) or not req.get("tools"):
            continue
        if agent and r.get("agent") != agent:
            continue
        if model and req.get("model") != model:
            continue
        return req["tools"]
    return None


def request_from_tap(path: Path, first_user_text: str) -> dict | None:
    """The captured request whose first user message is this text, matched on content.

    The strongest basis a re-ask can have, and the reason to prefer it over reconstructing one: this is the
    **exact request the agent sent** -- its tool schemas, its system message, its parameters -- so re-issuing
    it with only the model changed varies one thing. Reconstructing the context from the session store varies
    the tool schemas too, and that showed up as a plausible number rather than an error: a re-ask with no
    tools came back at the token cap with prose where the observed run had called a tool.

    Matched on content rather than on a clock or an address. The pass-through carries no trace id -- which is
    why the rest of this project joins on one -- and its caller field is a reverse-DNS name, so neither is a
    sound key. The message text is.
    """
    needle = _unwrap(first_user_text or "").strip()
    if not needle:
        return None
    # The cheap reject compares against the RAW line, so the needle has to be escaped the way it appears
    # inside a JSON string. Comparing decoded text to a raw line rejects every row -- a newline is one
    # character in the needle and the two characters `\n` on the line -- and the failure looks like "the
    # request was never captured" rather than like a bug here.
    escaped = json.dumps(needle[:120])[1:-1]
    matches = []
    for line in _lines(path):
        if escaped not in line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        req = r.get("request")
        if not isinstance(req, dict):
            continue
        msgs = req.get("messages") or []
        for m in msgs:
            c = m.get("content")
            text = c if isinstance(c, str) else " ".join(
                part.get("text", "") for part in (c or []) if isinstance(part, dict))
            if m.get("role") == "user" and needle in (text or ""):
                matches.append(req)
                break
    if not matches:
        return None
    # Many captured requests quote a prompt -- every later turn of the same thread carries it in its history,
    # and a summarisation call carries it again with no tools at all. Taking the first match got one of those:
    # three messages, zero tool schemas, and a re-ask that measured a different question while looking like a
    # replay. So the rule is stated rather than incidental: among the matches, the turn being replayed is the
    # one that carries the harness's tool schemas and has the FEWEST messages, because history only grows.
    with_tools = [q for q in matches if q.get("tools")]
    pool = with_tools or matches
    chosen = min(pool, key=lambda q: len(q.get("messages") or []))
    chosen = dict(chosen)
    chosen["_selected_from"] = {"matched": len(matches), "with_tool_schemas": len(with_tools),
                               "messages": len(chosen.get("messages") or []),
                               "rule": "fewest messages among the matches that carry tool schemas; history "
                                       "only grows, so that is the turn nearest the start of the thread"}
    return chosen


def _lines(path: Path):
    """Stream a log line by line. The pass-through log runs to gigabytes, so it is never read whole."""
    with path.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield line


def reask(context: list[dict], *, endpoint: str, model: str, max_tokens: int, timeout: int,
          tools: list | None = None, stored_reply_used_tools: bool = False) -> dict:
    """Issue one stored turn against a stated candidate and report what came back, with its billed legs.

    Deliberately not a scorer. It answers "on this input, what did that candidate say and what did it cost",
    and the reply is returned for a human or an oracle to judge. Anything more -- calling the reply right, or
    extrapolating it to the run -- would be the claim `replay_whole_run` refuses.

    `tools` is the agent's tool schemas, and passing them is what makes the output side comparable. Without
    them a candidate that would have called a tool writes prose instead, so its output leg measures a
    different question; `stored_reply_used_tools` lets this say so instead of leaving the two totals looking
    like a comparison.
    """
    import urllib.error
    import urllib.request

    payload = {
        "model": model,
        "messages": [{"role": c["role"], "content": c["content"]} for c in context if c.get("content")],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    if tools:
        payload["tools"] = tools
    body = json.dumps(payload).encode()
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions", data=body,
                                headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            doc = json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[FAIL] the endpoint refused the re-ask: {e.code} {e.read()[:400]!r}")
    u = doc.get("usage") or {}
    det = u.get("prompt_tokens_details") or {}
    # The same four legs, read under whichever convention arrived -- the disjoint spelling if the top-level
    # keys are present, the subset spelling otherwise. Getting this wrong is how a cached read gets counted
    # twice, which this project has already fixed once in the sweep path.
    dr, dw = u.get("cache_read_input_tokens"), u.get("cache_creation_input_tokens")
    if dr is not None or dw is not None:
        legs = {"fresh_in": int(u.get("prompt_tokens") or 0), "cached_in": int(dr or 0),
                "cache_write": int(dw or 0)}
    else:
        read = int(det.get("cached_tokens") or 0)
        write = int(det.get("created_cache_tokens") or 0)
        legs = {"fresh_in": max(0, int(u.get("prompt_tokens") or 0) - read - write),
                "cached_in": read, "cache_write": write}
    legs["out"] = int(u.get("completion_tokens") or 0)
    choice = (doc.get("choices") or [{}])[0]
    finish = choice.get("finish_reason")
    msg = choice.get("message") or {}
    out = {"model": doc.get("model") or model, "legs": legs, "finish_reason": finish,
           "reply": msg.get("content") or "",
           "tool_calls": [((t.get("function") or {}).get("name")) for t in (msg.get("tool_calls") or [])],
           "tools_offered": bool(tools)}
    if stored_reply_used_tools and not tools:
        # The boundary that matters most and shows up as a plausible number rather than an error: the stored
        # turn was answered with a tool call, this re-ask offered no tools, so the candidate explained instead
        # of acting. The input side is still like-for-like; the output side is answering a different question.
        out["comparable_as"] = "input_side_only"
        out["comparable_note"] = (
            "the stored turn was answered with a tool call and this re-ask offered no tool schemas, so the "
            "candidate wrote prose instead of acting. The input leg is like-for-like; the output leg is not, "
            "and the totals are not a comparison. Pass the agent's tool schemas to make them one")
        return out
    if finish == "length":
        # A reply cut off at the cap is a complete cost observation and an incomplete answer. Comparing it to
        # the stored reply as an answer would score the cap, so the two claims are separated here rather than
        # left to whoever reads the JSON.
        out["comparable_as"] = "cost_only"
        out["comparable_note"] = (f"the reply stopped at the {max_tokens} token cap, so it is a complete "
                                  "observation of what this turn costs and an incomplete answer. Comparing "
                                  "it to the stored reply as an answer would be scoring the cap")
    else:
        out["comparable_as"] = "cost_and_answer"
    return out


def reprice(legs: dict, card: dict) -> float:
    """What the recorded legs would cost on a different price card. No re-issue needed.

    The cheapest counterfactual available and the one most often wanted: the legs are already observed, so a
    different card is arithmetic on them. A leg absent from the card is charged at the fresh rate rather than
    at zero, on the same principle the rest of this project applies -- unmeasured is not free.
    """
    fresh = card["fresh_in"]
    read = card.get("cached_in")
    write = card.get("cache_write")
    return (int(legs.get("fresh_in") or 0) * fresh
            + int(legs.get("cached_in") or 0) * (fresh if read is None else read)
            + int(legs.get("cache_write") or 0) * (fresh if write is None else write)
            + int(legs.get("out") or 0) * card["output"]) / 1e6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="the agent's own store, copied WITH its -wal sidecar")
    ap.add_argument("--traces", help="collector traces, to resolve a trace id to a session id")
    ap.add_argument("--trace-id", help="the run to read, by the id the driver issued before it started")
    ap.add_argument("--session-id", help="or the agent's session id directly")
    ap.add_argument("--turn", type=int, help="print the context as it stood when this turn was issued")
    ap.add_argument("--out", help="write the trajectory as JSON")
    ap.add_argument("--reask-endpoint", help="an OpenAI-compatible base URL to re-issue --turn against")
    ap.add_argument("--reask-model", help="the model to name in that request")
    ap.add_argument("--reask-tools", help="JSON array of the agent's tool schemas. Without it a candidate "
                                        "that would have called a tool writes prose instead, and the output "
                                        "leg then measures a different question")
    ap.add_argument("--tools-from-tap", help="lift those schemas off the wire instead, from a recording "
                                           "pass-through log. They are a property of the harness rather than "
                                           "of a turn, and this is the only place they were captured")
    ap.add_argument("--tap-agent", help="restrict --tools-from-tap by the pass-through's caller field, which "
                                      "is a reverse-DNS host name rather than an agent name")
    ap.add_argument("--replay-from-tap", help="find the captured request for this turn by matching its text, "
                                            "and re-issue THAT with only the model changed. The strongest "
                                            "basis available: it varies one thing")
    ap.add_argument("--reask-max-tokens", type=int, default=1024)
    ap.add_argument("--reask-timeout", type=int, default=600)
    ap.add_argument("--price-card", help="JSON price card, to price the re-asked turn and the stored one on "
                                        "the same rates")
    a = ap.parse_args()

    conn = open_store(Path(a.store))
    sid = a.session_id
    if not sid:
        if not (a.traces and a.trace_id):
            raise SystemExit("[FAIL] give --session-id, or --traces with --trace-id")
        found = sessions_for_trace(Path(a.traces)).get(a.trace_id) or set()
        if not found:
            raise SystemExit(f"[FAIL] no span in {a.traces} carries a session id for trace {a.trace_id}")
        roots, children = roots_and_children(conn, found)
        unknown = sorted(found - set(roots) - set(children))
        if unknown:
            print(f"[WARN] {len(unknown)} session id(s) on this trace are absent from the store: {unknown}. "
                  "A recently finished run whose copy is missing its -wal looks exactly like this")
        if not roots:
            raise SystemExit(f"[FAIL] trace {a.trace_id} has {len(found)} sessions and none of them is a root: "
                             f"{sorted(found)}. Every one has a parent, so the thread they belong to was not "
                             "captured.")
        if len(roots) > 1:
            # Several *roots* is genuinely ambiguous -- two independent threads on one trace id -- unlike
            # several sessions, which is just delegation.
            raise SystemExit(f"[FAIL] trace {a.trace_id} carries {len(roots)} root sessions: {sorted(roots)}. "
                             "Name one with --session-id; two independent threads under one trace id cannot "
                             "be read as one run.")
        sid = roots[0]
        mine = sorted(c for c, par in children.items() if par == sid)
        if mine:
            print(f"root session {sid} delegated to {len(mine)} subagent session(s): {mine}")
            print("Their turns are theirs. Read one with --session-id; flattening them into the root would "
                  "attribute a delegate's tokens and replies to the thread that delegated.")

    traj = read_turns(conn, sid)
    if traj["absent"]:
        raise SystemExit(f"[FAIL] session {sid} has no messages in this store. If the run finished recently, "
                         "the copy is probably missing its -wal sidecar")
    print(f"session {sid}: {len(traj['messages'])} messages")
    for i, m in enumerate(traj["messages"]):
        text = next((p["text"] for p in m["parts"] if p["type"] == "text"), "")
        tools = [p["tool"] for p in m["parts"] if p["type"] == "tool" and p.get("tool")]
        print(f"  [{i:2d}] {(m['role'] or '?'):9s} {m.get('model') or '-':28s} "
              f"{len(text):6d} chars  tools={tools[:4]}")
    if traj.get("unread_part_types"):
        print(f"\n[WARN] part types this does not read: {traj['unread_part_types']}. Absent from the printout "
              "is not absent from the run")

    if a.turn is not None:
        ctx = turn_context(traj, a.turn)
        print(f"\ncontext as it stood at turn {a.turn}: {len(ctx)} messages, "
              f"{sum(len(c['content']) for c in ctx)} chars")
        print("This is what a different candidate would be asked. It licenses one claim -- what that "
              "candidate produced on this exact input -- and not a claim about the whole run.")
        result = None
        if a.reask_endpoint:
            if not a.reask_model:
                raise SystemExit("[FAIL] --reask-endpoint needs --reask-model: the candidate is part of the "
                                 "question, and a server's default is not a candidate anybody chose")
            tools = json.loads(Path(a.reask_tools).read_text()) if a.reask_tools else None
            if tools is None and a.replay_from_tap:
                first = next((c["content"] for c in ctx if c.get("content")), "")
                req = request_from_tap(Path(a.replay_from_tap), first)
                if req is None:
                    raise SystemExit(f"[FAIL] no captured request in {a.replay_from_tap} contains this turn's "
                                     "text. Without it there is nothing to replay, and reconstructing one "
                                     "would vary the tool schemas as well as the model.")
                tools = req.get("tools")
                # The exact wire context, so the only thing that changes is the model.
                ctx = [{"role": m.get("role"), "content": m.get("content")
                        if isinstance(m.get("content"), str) else json.dumps(m.get("content"))}
                       for m in req.get("messages") or []]
                sel = req.get("_selected_from") or {}
                print(f"replaying the captured request: {len(ctx)} messages, {len(tools or [])} tool schemas, "
                      f"originally sent to {req.get('model')}")
                print(f"  selected from {sel.get('matched')} captured requests containing this text "
                      f"({sel.get('with_tool_schemas')} of them carry tool schemas): {sel.get('rule')}")
            if tools is None and a.tools_from_tap:
                tools = tools_from_tap(Path(a.tools_from_tap), agent=a.tap_agent)
                if tools is None:
                    raise SystemExit(f"[FAIL] no captured request in {a.tools_from_tap} carries tool schemas"
                                     + (f" for agent {a.tap_agent!r}" if a.tap_agent else "")
                                     + ". Without them the output side of a re-ask is not comparable, and "
                                     "guessing a tool set would make it look as if it were.")
                print(f"lifted {len(tools)} tool schema(s) off the wire: "
                      f"{[((t.get('function') or {}).get('name')) for t in tools][:8]}")
            result = reask(ctx, endpoint=a.reask_endpoint, model=a.reask_model,
                           max_tokens=a.reask_max_tokens, timeout=a.reask_timeout, tools=tools,
                           stored_reply_used_tools=stored_reply_used_tools(traj, a.turn))
            print(f"\nre-asked on {result['model']}: legs {result['legs']}, "
                  f"finish {result['finish_reason']}, {len(result['reply'])} chars back")
            if result.get("comparable_note"):
                print(f"  [WARN] {result['comparable_note']}")
            if a.price_card:
                card = json.loads(Path(a.price_card).read_text())
                card = card.get("self_hosted", {}).get("rate", card)
                card = {"fresh_in": card.get("fresh_in"), "cached_in": card.get("cache_read",
                        card.get("cached_in")), "cache_write": card.get("cache_write"),
                        "output": card.get("out", card.get("output"))}
                print(f"  this turn on that card: ${reprice(result['legs'], card):.6f}")
            print(f"  comparable as: {result['comparable_as']}")
            print("  What this licenses: on this input, that candidate said this, at this cost. Not that the "
                  "run would have gone this way -- see replay_whole_run.")
        if a.out:
            Path(a.out).write_text(json.dumps({"session_id": sid, "turn": a.turn, "context": ctx,
                                               **({"reask": result} if result else {})}, indent=1) + "\n")
            print(f"wrote {a.out}")
    elif a.out:
        Path(a.out).write_text(json.dumps(traj, indent=1) + "\n")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
