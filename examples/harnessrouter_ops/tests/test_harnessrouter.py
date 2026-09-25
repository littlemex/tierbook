"""The HarnessRouter adapter, and the opencode loop driven through it unchanged.

Two things are under test. The adapter maps the loop's request onto HarnessRouter's Responses API and maps the reply
back without turning "no answer" into "a wrong answer". And the loop itself -- written for the opencode example -- runs
through this adapter without a line of it changing and still moves traffic, which is what "the mechanism is
agent-agnostic" has to mean in practice.
"""
from __future__ import annotations

import random

from examples.harnessrouter_ops.adapter import harnessrouter_adapter, reply_from, text_of, to_responses_request
from examples.opencode_ops import policy as P
from examples.opencode_ops.adapter import request_body
from examples.opencode_ops.ops import Ops
from examples.opencode_ops.state import World


def completed(text: str, tokens_in: int = 10_000, tokens_out: int = 2_000) -> dict:
    return {
        "status": "completed",
        "output": [{"type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": tokens_in + tokens_out},
    }


class FakeHarnessRouter:
    """Answers like a HarnessRouter instance: a completed response whose text says whether the patch was right.

    Deterministic per model, for the same reason as the opencode example's fake: a test that averages over randomness
    cannot tell whether the loop moved traffic or the coin did.
    """

    def __init__(self, accepts: dict[str, float]):
        self.accepts = accepts
        self.requests: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, headers: dict, body: dict) -> tuple[int, dict]:
        self.requests.append((url, headers, body))
        model = body["model"]
        seen = sum(1 for _, _, b in self.requests[:-1] if b["model"] == model)
        rate = self.accepts[model]
        good = int((seen + 1) * rate) > int(seen * rate)
        return 200, completed("PATCH OK" if good else "PATCH WRONG")


def accept_ok(text: str, response: dict) -> bool:
    return text.startswith("PATCH OK")


def test_the_request_names_the_harness_and_the_model_and_carries_the_messages():
    body = request_body("fix the bug")
    req = to_responses_request(body, model="box", harness_id="opencode")
    assert req["metadata"] == {"harness_id": "opencode"} and req["model"] == "box" and req["stream"] is False
    assert [i["role"] for i in req["input"]] == ["system", "user"]
    assert "tools" not in req, "the harness owns its tools; the loop's tool schemas describe a set it will not use"


def test_the_reply_carries_text_and_tokens():
    reply = reply_from(200, completed("PATCH OK", 12_000, 3_000), accept=accept_ok)
    assert reply.accepted and reply.text == "PATCH OK"
    assert reply.input_mtok == 0.012 and reply.output_mtok == 0.003
    assert text_of({"output": [{"type": "reasoning"}, *completed("a")["output"]]}) == "a"


def test_no_answer_is_unobserved_not_wrong():
    refused = reply_from(404, {"error": {"message": "unknown harness"}}, accept=accept_ok)
    failed = reply_from(200, {**completed(""), "status": "failed"}, accept=accept_ok)
    broken = reply_from(502, {}, accept=accept_ok)
    assert refused.unobserved_because == "unsupported" and not refused.accepted
    assert failed.unobserved_because == "execution_error" and broken.unobserved_because == "execution_error"


def test_the_opencode_loop_runs_through_harnessrouter_unchanged_and_still_moves_traffic():
    fake = FakeHarnessRouter({P.CHEAP: 0.5, P.DEAR: 1.0})
    agent = harnessrouter_adapter("http://localhost:3000/api/harness", "opencode", api_key="test-key", post=fake,
                                  accept=accept_ok)
    world = World(price_per_mtok={P.CHEAP: 1.0, P.DEAR: 4.0}, tenant_quota_left=50.0, hour_of_day=14,
                  inflight={P.CHEAP: 2})
    ops = Ops(world=world, agent=agent, rng=random.Random(0))
    turns = [ops.turn(f"task {i}", now=1000.0 + i) for i in range(40)]
    assert all(r[0] == "http://localhost:3000/api/harness/v1/responses" for r in fake.requests)
    assert all(r[1]["Authorization"] == "Bearer test-key" for r in fake.requests)
    assert all(r[2]["metadata"]["harness_id"] == "opencode" for r in fake.requests)
    assert {t.candidate for t in turns} == {P.CHEAP, P.DEAR}, "both arms have to be measured before anything is derived"
    assert ops.preferred() is not None
