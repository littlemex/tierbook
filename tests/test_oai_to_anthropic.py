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


def test_an_unknown_field_is_refused_rather_than_dropped():
    """A parameter dropped in translation changes the candidate, which is the defect this exists to prevent."""
    with pytest.raises(ValueError) as e:
        shim.to_anthropic({"model": "m", "messages": [], "some_new_knob": 1})
    assert "refusing rather than dropping" in str(e.value)


def test_a_field_that_cannot_be_honoured_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        shim.to_anthropic({"model": "m", "messages": [], "response_format": {"type": "json_object"}})
    assert "response_format" in str(e.value) and "change the candidate" in str(e.value)


def test_consecutive_same_role_turns_are_merged_not_dropped():
    body, notes = shim.to_anthropic({"model": "m", "messages": [
        {"role": "user", "content": "one"}, {"role": "user", "content": "two"}]})
    assert len(body["messages"]) == 1
    assert [c["text"] for c in body["messages"][0]["content"]] == ["one", "two"]
    assert any("merged" in n for n in notes)


def test_unparseable_tool_arguments_are_carried_not_silently_emptied():
    body, _ = shim.to_anthropic({"model": "m", "messages": [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c", "type": "function", "function": {"name": "f", "arguments": "{not json"}}]}]})
    assert body["messages"][0]["content"][0]["input"] == {"_unparsed_arguments": "{not json"}


def test_a_reply_keeps_its_tool_calls_and_the_gateways_usage():
    out = shim.to_openai({
        "id": "msg_1", "model": "claude-haiku-4-5", "stop_reason": "tool_use",
        "content": [{"type": "text", "text": "running"},
                    {"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "ls"}}],
        "usage": {"input_tokens": 1234, "output_tokens": 56, "cache_read_input_tokens": 900},
    }, "m")
    choice = out["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "bash"
    assert json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"]) == {"cmd": "ls"}
    # The gateway's own counts, under the disjoint cache convention the Anthropic surface uses -- the same
    # convention the ledger reads, so the legs are not double-subtracted downstream.
    assert out["usage"] == {"prompt_tokens": 1234, "completion_tokens": 56, "total_tokens": 1290,
                            "cache_read_input_tokens": 900}


def test_a_truncated_reply_reports_length_not_stop():
    out = shim.to_openai({"stop_reason": "max_tokens", "content": [{"type": "text", "text": "cut"}],
                          "usage": {"input_tokens": 1, "output_tokens": 2}}, "m")
    assert out["choices"][0]["finish_reason"] == "length"


def test_the_default_output_cap_is_not_silently_tiny():
    """An agent that omits max_tokens must not be given a cap that truncates every reply, which would look like
    incapability."""
    body, _ = shim.to_anthropic({"model": "m", "messages": [{"role": "user", "content": "x"}]})
    assert body["max_tokens"] >= 4096
