"""The translation a two-arm comparison depends on, and the ways it could lose part of a request.

This file exists because a metered arm was run through a different client library than the arm it was compared
with, and the loss was invisible in the outcomes: the arm's requests carried 3, 6, 6, 6, 3666, 3815, 7, 7 prompt
tokens with no accumulating history, against the other arm's cache reads climbing 6,336 to 23,232. Every test
here is a way the same loss could happen inside the translator instead of around it.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import oai_to_anthropic as shim  # noqa: E402


def test_a_full_conversation_survives_with_its_tool_pairing():
    """The failure this file answers. An assistant turn whose content is empty because it carried tool_calls must
    survive, and the tool messages after it must keep their ids, or the conversation the model receives is not the
    conversation the agent has."""
    req = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "you are a build agent"},
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "bash", "arguments": '{"cmd":"ls"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "a.py b.py"},
            {"role": "user", "content": "now edit it"},
        ],
        "tools": [{"type": "function", "function": {"name": "bash", "description": "run",
                                                   "parameters": {"type": "object"}}}],
        "max_tokens": 100,
    }
    body, notes = shim.to_anthropic(req)
    assert body["system"] == "you are a build agent"
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user"], "the tool result merged into the following user turn"
    call = body["messages"][1]["content"][0]
    assert call["type"] == "tool_use" and call["id"] == "c1" and call["input"] == {"cmd": "ls"}
    result = body["messages"][2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "c1"
    assert body["tools"][0]["name"] == "bash" and "input_schema" in body["tools"][0]


def test_history_is_not_shrunk():
    """The specific quantity that went wrong: what reaches the gateway must grow with the conversation."""
    def size(n):
        msgs = [{"role": "user", "content": "x" * 500}]
        for i in range(n):
            msgs.append({"role": "assistant", "content": f"turn {i}"})
            msgs.append({"role": "user", "content": "y" * 500})
        body, _ = shim.to_anthropic({"model": "m", "messages": msgs})
        return len(json.dumps(body))

    a, b, c = size(1), size(5), size(20)
    assert a < b < c
    assert c > 10 * a, "twenty turns must not translate to nearly the same bytes as one"


def test_only_fields_that_are_translated_are_accepted():
    """An earlier version of this set listed ten fields it accepted and never translated -- among them
    `parallel_tool_calls`, which changes agent behaviour -- so the file contradicted the fail-closed claim in its
    own docstring. Every one of them is now refused by name."""
    for field in ("some_new_knob", "response_format", "presence_penalty", "frequency_penalty", "user",
                  "parallel_tool_calls", "reasoning_effort", "logprobs", "n", "seed"):
        with pytest.raises(ValueError) as e:
            shim.to_anthropic({"model": "m", "messages": [], field: 1})
        assert field in str(e.value)
        assert "not translated here" in str(e.value) and "changes the candidate" in str(e.value)


def test_the_translated_set_is_exactly_what_the_code_handles():
    """The invariant that broke: a field in the accept list with no translation beside it."""
    assert shim.TRANSLATED == {"model", "messages", "tools", "tool_choice", "max_tokens",
                               "max_completion_tokens", "temperature", "top_p", "stream", "stream_options",
                               "stop"}


def test_an_unknown_message_role_is_refused_rather_than_becoming_a_user_turn():
    for role in ("developer", "function", "nonsense"):
        with pytest.raises(ValueError) as e:
            shim.to_anthropic({"model": "m", "messages": [{"role": role, "content": "x"}]})
        assert "is not translated here" in str(e.value) and "a different message" in str(e.value)


def test_a_content_block_that_is_not_text_is_refused_rather_than_vanishing():
    with pytest.raises(ValueError) as e:
        shim.to_anthropic({"model": "m", "messages": [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}]})
    assert "image_url" in str(e.value) and "dropped silently" in str(e.value)


def test_tool_choice_required_is_translated_and_an_unknown_one_is_refused():
    body, _ = shim.to_anthropic({"model": "m", "messages": [{"role": "user", "content": "x"}],
                                 "tool_choice": "required"})
    assert body["tool_choice"] == {"type": "any"}
    with pytest.raises(ValueError) as e:
        shim.to_anthropic({"model": "m", "messages": [{"role": "user", "content": "x"}],
                           "tool_choice": "something-new"})
    assert "would let the model choose differently than the caller asked" in str(e.value)


def test_a_tool_call_or_result_missing_its_id_is_refused():
    with pytest.raises(ValueError) as e:
        shim.to_anthropic({"model": "m", "messages": [
            {"role": "assistant", "content": None,
             "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": "{}"}}]}]})
    assert "cannot be paired with its result" in str(e.value)
    with pytest.raises(ValueError) as e2:
        shim.to_anthropic({"model": "m", "messages": [{"role": "tool", "content": "out"}]})
    assert "cannot be paired with its call" in str(e2.value)


def test_a_tool_with_no_name_or_an_untranslated_type_is_refused():
    with pytest.raises(ValueError):
        shim.to_anthropic({"model": "m", "messages": [{"role": "user", "content": "x"}],
                           "tools": [{"type": "function", "function": {"description": "no name"}}]})
    with pytest.raises(ValueError) as e:
        shim.to_anthropic({"model": "m", "messages": [{"role": "user", "content": "x"}],
                           "tools": [{"type": "web_search"}]})
    assert "tool type" in str(e.value)


def test_consecutive_same_role_turns_are_merged_not_dropped():
    body, notes = shim.to_anthropic({"model": "m", "messages": [
        {"role": "user", "content": "one"}, {"role": "user", "content": "two"}]})
    assert len(body["messages"]) == 1
    assert [c["text"] for c in body["messages"][0]["content"]] == ["one", "two"]
    assert any("merged" in n for n in notes)


def test_unparseable_tool_arguments_are_refused_not_rewritten():
    """Rewriting them into a placeholder produced a DIFFERENT tool invocation that looks valid to the model."""
    with pytest.raises(ValueError) as e:
        shim.to_anthropic({"model": "m", "messages": [
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c", "type": "function",
                             "function": {"name": "f", "arguments": "{not json"}}]}]})
    assert "unparseable arguments" in str(e.value)
    assert "a different invocation than the agent chose" in str(e.value)


def test_a_reply_keeps_its_tool_calls_and_the_gateways_usage():
    out, notes = shim.to_openai({
        "id": "msg_1", "model": "claude-haiku-4-5", "stop_reason": "tool_use",
        "content": [{"type": "text", "text": "running"},
                    {"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "ls"}}],
        "usage": {"input_tokens": 1234, "output_tokens": 56, "cache_read_input_tokens": 900},
    }, "m")
    choice = out["choices"][0]
    assert choice["finish_reason"] == "tool_calls" and notes == []
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "bash"
    assert choice["message"]["tool_calls"][0]["index"] == 0, "streaming reconstruction keys on it"
    assert json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"]) == {"cmd": "ls"}
    # Disjoint, as the Anthropic surface reports it -- and the gross total beside it, because a bare
    # prompt_tokens excluding cache legs is exactly the shape that made the broken arm look like it sent nothing.
    assert out["usage"]["prompt_tokens"] == 1234
    assert out["usage"]["cache_read_input_tokens"] == 900
    assert out["usage"]["billed_input_tokens"] == 2134
    assert "disjoint" in out["usage"]["convention"]


def test_a_truncated_reply_reports_length_not_stop():
    out, _ = shim.to_openai({"stop_reason": "max_tokens", "content": [{"type": "text", "text": "cut"}],
                             "usage": {"input_tokens": 1, "output_tokens": 2}}, "m")
    assert out["choices"][0]["finish_reason"] == "length"


def test_an_unmapped_stop_reason_is_named_rather_than_flattened_to_stop():
    """`stop` for an unknown reason is the one mapping that can turn a refusal into an apparently normal
    answer."""
    out, notes = shim.to_openai({"stop_reason": "refusal", "content": [{"type": "text", "text": "no"}],
                                 "usage": {}}, "m")
    assert out["choices"][0]["finish_reason"] == "stop"
    assert any("stop_reason 'refusal' is not a reason this maps" in n for n in notes)


def test_a_reply_block_with_no_representation_is_named_not_dropped_in_silence():
    """Thinking, redacted thinking, a server tool result or a citation used to vanish, so the caller saw a shorter
    answer and no reason for it."""
    out, notes = shim.to_openai({"stop_reason": "end_turn", "usage": {}, "content": [
        {"type": "thinking", "thinking": "..."}, {"type": "text", "text": "answer"}]}, "m")
    assert out["choices"][0]["message"]["content"] == "answer"
    assert any("type 'thinking' has no representation here" in n for n in notes)


def test_the_default_output_cap_is_not_silently_tiny():
    """An agent that omits max_tokens must not be given a cap that truncates every reply, which would look like
    incapability."""
    body, _ = shim.to_anthropic({"model": "m", "messages": [{"role": "user", "content": "x"}]})
    assert body["max_tokens"] >= 4096


def test_cache_marking_is_off_unless_asked_for(monkeypatch):
    """It changes what a request costs, so it changes what a comparison measures, and it is a per-deployment
    decision rather than a default."""
    monkeypatch.delenv(shim.CACHE_MARK_ENV, raising=False)
    body, notes = shim.to_anthropic({"model": "m", "messages": [{"role": "user", "content": "x"}],
                                     "tools": [{"type": "function", "function": {"name": "f"}}]})
    assert "cache_control" not in json.dumps(body)
    assert not any("cacheable" in n for n in notes)


def test_cache_marking_covers_the_schemas_the_system_and_the_previous_history(monkeypatch):
    """The absence of this distorted a comparison: the self-hosted arm read 91.4% of its input from a prefix cache
    and the metered arm read 0%, because nothing on that path asked for caching."""
    monkeypatch.setenv(shim.CACHE_MARK_ENV, "1")
    body, notes = shim.to_anthropic({
        "model": "m",
        "messages": [{"role": "system", "content": "you are an agent"},
                     {"role": "user", "content": "task"},
                     {"role": "assistant", "content": "working"},
                     {"role": "user", "content": "next"}],
        "tools": [{"type": "function", "function": {"name": "a"}},
                  {"type": "function", "function": {"name": "b"}}],
    })
    assert body["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in body["tools"][0], "one breakpoint at the end covers the whole block"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    marked = [i for i, m in enumerate(body["messages"])
              if any("cache_control" in b for b in m["content"])]
    assert marked == [len(body["messages"]) - 2], "the turn before the newest one"
    assert sum("cacheable" in n for n in notes) == 3


def test_cache_marking_does_not_rewrite_content(monkeypatch):
    monkeypatch.setenv(shim.CACHE_MARK_ENV, "1")
    body, _ = shim.to_anthropic({"model": "m", "messages": [
        {"role": "user", "content": "first"}, {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"}]})
    texts = [b["text"] for m in body["messages"] for b in m["content"] if b.get("type") == "text"]
    assert texts == ["first", "second", "third"]


def test_a_single_message_request_marks_no_history(monkeypatch):
    monkeypatch.setenv(shim.CACHE_MARK_ENV, "1")
    body, notes = shim.to_anthropic({"model": "m", "messages": [{"role": "user", "content": "only"}]})
    assert not any("history through" in n for n in notes)


def test_the_cache_marker_carries_the_warning_that_it_drops_content_on_this_gateway(monkeypatch):
    """Measured, not assumed: a four-message request carrying 4,333 input tokens unmarked came back reporting 25,
    cache legs zero, with the system prompt, tool schemas and history gone. The same silent shrinking that made an
    earlier arm worthless, reproduced by a change meant to fix a different distortion."""
    monkeypatch.setenv(shim.CACHE_MARK_ENV, "1")
    _, notes = shim.to_anthropic({"model": "m", "messages": [{"role": "user", "content": "x"},
                                                             {"role": "assistant", "content": "y"},
                                                             {"role": "user", "content": "z"}]})
    assert any("DROPPED rather than cached" in n for n in notes)


def test_the_shrink_floor_is_far_below_observed_traffic():
    """Its job is to catch a collapse, not to police a tokenizer. Real traffic on this path runs about 45 billed
    tokens per 100 bytes; both observed failures were two orders of magnitude below the floor."""
    assert shim.MIN_BILLED_PER_100_BYTES < 45 / 10
    # The two real failures: 25 tokens against a 4-message history, and 6 tokens against a full transcript.
    assert 25 * 100.0 / 20_000 < shim.MIN_BILLED_PER_100_BYTES
