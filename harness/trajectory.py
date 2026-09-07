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

*What would this turn have cost, or said, on a different candidate?* Answerable, but ONLY from the captured
wire request, and the difference between the two paths is not a detail.

Replaying the **captured request** (`--replay-from-tap`) varies the model and nothing else, because the whole
request is there: the system message, the tool schemas, the tool results, the parameters.

Reconstructing the context from the **session store** (`--turn` alone) varies much more than the model, and an
earlier version of this docstring claimed otherwise. The store keeps tool *calls* and not tool *results*, so a
reconstructed context is missing the tool output -- typically the bulk of the tokens in an agent run -- as well
as the tool schemas, which the agent builds at request time and stores nowhere. The first re-ask run here came
back at the token cap with 14,469 characters of prose where the observed run had answered with a `task` call,
at thirteen times the cost of the like-for-like replay. So the reconstructed path is for reading a run, and its
re-ask is labelled `reconstructed_context_only`: not comparable on either side, in cost or in answer.

Re-pricing needs no re-issue at all, and it has a boundary of its own: the legs are recorded, so a different
price is arithmetic on them **for the same model**. Across models it is not -- token counts are
tokenizer-dependent, and the cached leg describes one cache's warmth at one moment rather than a property of the
request -- so `reprice` returns those bounds beside the figure instead of a bare number.

*What would the whole run have done?* Not answerable by replay, and this module refuses to pretend. A
different model would take different actions from the point of divergence, so every tool result after that
point is a result of the *observed* run's actions and not of the counterfactual one's. Feeding the stored
results back produces a transcript in which the model appears to have taken actions it did not choose, and
its apparent success is then a property of the harness. `replay_whole_run` therefore raises, with that reason,
rather than returning something a caller could put in a table.

What the single-turn re-ask does establish is narrower and real: on this input, that candidate produced this
reply at this cost. Enough to price a turn, to compare two candidates on one context, and to see whether a
cheaper one would have answered the same -- which is the question a router asks. Two further claims are
available and are not the whole-run one: prefix replay to the first divergence, which is identified because the
tool calls matched exactly until then, and a per-turn agreement rate across many stored turns.

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
        "run's actions -- so the replay would credit the candidate for actions it did not choose. Three things "
        "ARE available and are not this: re-ask a single turn, which is answerable; replay the PREFIX up to "
        "the first divergence, which is identified because the tool calls matched exactly until then, and "
        "yields 'agreed for k turns, diverged at k+1'; or run the candidate on the task, which is a "
        "measurement rather than a counterfactual. The general correction -- randomised exploration with "
        "logged selection probabilities, so an off-policy estimator is identified -- is a gap in this project "
        "rather than a law of nature: nothing here logs a propensity yet.")


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


def request_from_tap(path: Path, first_user_text: str, *, want_depth: int | None = None) -> dict | None:
    """The captured request whose first user message is this text, matched on content.

    The strongest basis a re-ask can have, and the reason to prefer it over reconstructing one: this is the
    **exact request the agent sent** -- its tool schemas, its system message, its parameters -- so re-issuing
    it with only the model changed varies one thing. Reconstructing the context from the session store varies
    the tool schemas too, and that showed up as a plausible number rather than an error: a re-ask with no
    tools came back at the token cap with prose where the observed run had called a tool.

    Matched on content rather than on a clock or an address. The pass-through carries no trace id -- which is
    why the rest of this project joins on one -- and its caller field is a reverse-DNS name, so neither is a
    sound key. The message text is.

    `want_depth` is how many NON-SYSTEM messages the intended turn's context had, and system messages are
    excluded on both sides because only one side has them: the wire request carries a system message the session
    store never saw, so counting it made the closest match look one short on every turn and fired a warning on
    the normal case.

    Without a depth this RETURNS THE WRONG
    TURN for every turn but the first. The prompt appears in every later request of the same thread, carried in
    its history, so "fewest messages" always selects the request nearest the start. Asked for turn 7, the
    earlier version found and replayed turn 0 -- and then replaced the caller's context with it, so the output
    named turn 7 and measured turn 0. With a depth, the match closest to that depth is chosen and the distance
    is reported.
    """
    needle = _unwrap(first_user_text or "").strip()
    if not needle:
        return None
    # The cheap reject compares against the RAW line, so the needle has to be escaped the way it appears
    # inside a JSON string. Comparing decoded text to a raw line rejects every row -- a newline is one
    # character in the needle and the two characters `\n` on the line -- and the failure looks like "the
    # request was never captured" rather than like a bug here.
    # Two spellings, because a log may be written with `ensure_ascii` either way. Escaped-only rejects every
    # line of a UTF-8 log as soon as the needle has a non-ASCII character -- and the failure then looks exactly
    # like "the request was never captured", which is the reading this whole comment exists to prevent.
    raw_needle = needle[:120]
    escaped = json.dumps(raw_needle)[1:-1]
    matches = []
    for line in _lines(path):
        if escaped not in line and raw_needle not in line:
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
    def depth(q):
        return sum(1 for m in q.get("messages") or [] if m.get("role") != "system")

    if want_depth is None:
        chosen = min(pool, key=depth)
        rule = ("fewest messages among the matches that carry tool schemas. Correct only for the FIRST turn: "
                "history only grows, so this is the request nearest the start of the thread. Pass want_depth "
                "for any other turn")
        distance = None
    else:
        chosen = min(pool, key=lambda q: (abs(depth(q) - want_depth), depth(q)))
        distance = depth(chosen) - want_depth
        rule = (f"the match whose history is closest to the intended turn's depth of {want_depth} non-system "
                "messages, among those carrying tool schemas")
    chosen = dict(chosen)
    chosen["_selected_from"] = {"matched": len(matches), "with_tool_schemas": len(with_tools),
                                "messages": len(chosen.get("messages") or []),
                                "non_system_messages": depth(chosen),
                                "want_depth": want_depth, "depth_distance": distance, "rule": rule}
    return chosen


def _lines(path: Path):
    """Stream a log line by line. The pass-through log runs to gigabytes, so it is never read whole."""
    with path.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield line


def reask(context: list[dict], *, endpoint: str, model: str, max_tokens: int, timeout: int,
          tools: list | None = None, stored_reply_used_tools: bool = False,
          from_wire: bool = False, sampling: dict | None = None) -> dict:
    """Issue one stored turn against a stated candidate and report what came back, with its billed legs.

    Deliberately not a scorer. It answers "on this input, what did that candidate say and what did it cost",
    and the reply is returned for a human or an oracle to judge. Anything more -- calling the reply right, or
    extrapolating it to the run -- would be the claim `replay_whole_run` refuses.

    `tools` is the agent's tool schemas, and passing them is what makes the output side comparable. Without
    them a candidate that would have called a tool writes prose instead, so its output leg measures a
    different question; `stored_reply_used_tools` lets this say so instead of leaving the two totals looking
    like a comparison.

    `from_wire` says the context came from a captured request rather than from the session store. Only the
    former is comparable: a reconstructed context has lost the tool results.

    `sampling` carries the observed request's own decoding parameters. A candidate in this project is
    `(model, endpoint, decoding and tool policy)`, so hardcoding a temperature silently changes the candidate
    and then reports the result as that candidate's. Absent, the defaults used are named in the result.
    """
    import urllib.error
    import urllib.request

    # Every field of a message is carried, not just role and content. Dropping an assistant message whose
    # content is empty because it carried `tool_calls` orphans the tool results that follow it, and losing
    # `tool_call_id` breaks the pairing -- so the replayed request is structurally different from the wire one
    # and a server may reject it or silently reinterpret it. "Varies one thing" was false while that held.
    messages = []
    for c in context:
        if c.get("content") in (None, "") and not c.get("tool_calls"):
            continue
        m = {k: v for k, v in c.items()
             if k in ("role", "content", "name", "tool_calls", "tool_call_id") and v is not None}
        if m.get("role"):
            messages.append(m)
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    # The observed request's own sampling, when it is known. Only defaulted when it is not, and then said so.
    defaulted = {}
    for key, default in (("temperature", 0), ("top_p", None), ("tool_choice", None)):
        if sampling and sampling.get(key) is not None:
            payload[key] = sampling[key]
        elif default is not None:
            payload[key] = default
            defaulted[key] = default
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
           "tools_offered": bool(tools), "context_from": "wire" if from_wire else "session_store"}
    if defaulted:
        # A candidate is (model, endpoint, decoding and tool policy). Defaulting part of the decoding changes
        # the candidate, so what was defaulted is named rather than left to look like the observed setting.
        out["decoding_defaulted"] = defaulted
    if not from_wire:
        out["comparable_as"] = "reconstructed_context_only"
        out["comparable_note"] = (
            "the context was rebuilt from the session store, which keeps tool CALLS and not tool RESULTS. The "
            "observed request carried those results -- usually most of its tokens -- so neither the input leg "
            "nor the output leg is comparable. Replay the captured wire request instead")
        return out
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


def reprice(legs: dict, card: dict, *, same_model: bool = True, cold_cache: bool = False) -> dict:
    """What the recorded legs would cost on a different price card, and what that figure may be used for.

    The cheapest counterfactual available: the legs are already observed, so a different card is arithmetic on
    them. Valid **for the same model at a different price**, which is a real question -- a price change, a
    committed-use discount, a different region.

    Across models it is not arithmetic, and the requirement it seems to serve invites exactly that misuse.
    Token counts are tokenizer-dependent, and 10-30% differences between vocabularies are ordinary; and
    `cached_in` describes the warmth of one serving cache at one moment, not a property of the request, so a
    different provider starts cold. `same_model=False` therefore returns the figure with a bound on how it may
    be read rather than a clean number, and `cold_cache=True` charges the cached leg as fresh, which is what a
    provider that has never seen the prefix does.

    A leg absent from the CARD is charged at the fresh rate, and the direction of that substitution is stated
    rather than called conservative: a cache write is usually charged ABOVE fresh -- 1.25x is common -- so
    substituting fresh UNDER-charges it. That is the opposite of the safe direction, and the returned figure
    says so instead of implying a floor it does not provide.
    """
    fresh = card["fresh_in"]
    read = card.get("cached_in")
    write = card.get("cache_write")
    cached = int(legs.get("cached_in") or 0)
    written = int(legs.get("cache_write") or 0)
    usd = (int(legs.get("fresh_in") or 0) * fresh
           + cached * (fresh if (read is None or cold_cache) else read)
           + written * (fresh if write is None else write)
           + int(legs.get("out") or 0) * card["output"]) / 1e6
    caveats = []
    if not same_model:
        caveats.append("a different model counts tokens with a different tokenizer, so these legs are not that "
                       "model's legs. Differences of 10-30% between vocabularies are ordinary, and this figure "
                       "cannot be compared with one measured on that model")
    if cold_cache:
        caveats.append("the cached leg is charged as fresh, because a provider that has never served this "
                       "prefix has nothing cached")
    elif cached and read is None:
        caveats.append("the card states no cached rate, so the cached leg is charged as fresh")
    if written and write is None:
        caveats.append("the card states no cache-write rate, so that leg is charged at fresh -- which "
                       "UNDER-charges it wherever a write costs more than fresh, as it commonly does. This "
                       "figure is not a floor")
    return {"usd": usd, "same_model": same_model, "cold_cache": cold_cache, "caveats": caveats}


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
    ap.add_argument("--reprice-cross-model", action="store_true",
                    help="say that the card belongs to a DIFFERENT model. The figure then carries the bound "
                         "that these legs are not that model's legs, because a different tokenizer counts "
                         "differently")
    ap.add_argument("--reprice-cold-cache", action="store_true",
                    help="charge the cached leg as fresh, which is what a provider that has never served this "
                         "prefix does")
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
        if not a.replay_from_tap:
            print("Rebuilt from the session store, which keeps tool CALLS and not tool RESULTS. It is a "
                  "reading of the run, not a request that can be compared: use --replay-from-tap for that.")
        result = None
        if a.reask_endpoint:
            if not a.reask_model:
                raise SystemExit("[FAIL] --reask-endpoint needs --reask-model: the candidate is part of the "
                                 "question, and a server's default is not a candidate anybody chose")
            tools = json.loads(Path(a.reask_tools).read_text()) if a.reask_tools else None
            sampling = None
            if tools is None and a.replay_from_tap:
                first = next((c["content"] for c in ctx if c.get("content")), "")
                req = request_from_tap(Path(a.replay_from_tap), first, want_depth=len(ctx))
                if req is None:
                    raise SystemExit(f"[FAIL] no captured request in {a.replay_from_tap} contains this turn's "
                                     "text. Without it there is nothing to replay, and reconstructing one "
                                     "would vary the tool schemas as well as the model.")
                tools = req.get("tools")
                sel = req.get("_selected_from") or {}
                sampling = {k: req.get(k) for k in ("temperature", "top_p", "tool_choice")
                            if req.get(k) is not None}
                wire_ctx = [dict(m) for m in req.get("messages") or []]
                print(f"replaying the captured request: {len(wire_ctx)} messages, {len(tools or [])} tool "
                      f"schemas, originally sent to {req.get('model')}")
                print(f"  selected from {sel.get('matched')} captured requests containing this text "
                      f"({sel.get('with_tool_schemas')} of them carry tool schemas): {sel.get('rule')}")
                if sel.get("depth_distance"):
                    print(f"  [WARN] the closest match sits {sel['depth_distance']:+d} messages from the "
                          f"intended turn's depth of {sel.get('want_depth')}. It is not that turn's request")
                ctx = wire_ctx
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
                           stored_reply_used_tools=stored_reply_used_tools(traj, a.turn),
                           from_wire=bool(a.replay_from_tap), sampling=sampling)
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
                priced = reprice(result["legs"], card, same_model=not a.reprice_cross_model,
                                 cold_cache=a.reprice_cold_cache)
                print(f"  this turn on that card: ${priced['usd']:.6f}")
                for c in priced["caveats"]:
                    print(f"    [caveat] {c}")
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
