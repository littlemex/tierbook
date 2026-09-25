"""The seam HarnessRouter plugs into: the same `Agent` the opencode example drives, reached over HarnessRouter's
OpenAI Responses-compatible API instead of an agent's own model call.

**Why the loop is not rewritten.** HarnessRouter runs a coding agent (Codex, Claude Code, opencode and others -- a
*harness*: the scaffold, tools and turn loop around a model) behind one API, and the caller names both the harness and
the model on every request (`metadata.harness_id` and `model`). That is exactly the surface `opencode_ops` asks of an
agent -- one call that takes a request and returns a reply -- so this example supplies only the adapter and reuses the
loop, the policy and the state unchanged. If the loop had to change to talk to a different agent backend, the
mechanism would not be agent-agnostic, and that is the claim the two examples together test.

**The harness is a conditioning variable, not a candidate.** tierbook routes a request among candidates *given* the
harness it arrived through; choosing the harness is a task-admission decision upstream of it (SCOPE section 4). So an
adapter is built for one `harness_id`, and comparing harnesses means running one loop per harness and comparing what
they recorded, not putting harnesses into the candidate set.

Nothing here imports an HTTP library: the transport is a parameter, so the tests can drive the whole loop with a fake
and a real run passes `urllib_post`.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from examples.opencode_ops.adapter import Agent, Reply

#: A transport: (url, headers, JSON body) -> (HTTP status, parsed JSON reply). Injected so nothing here opens a socket
#: in a test.
Post = Callable[[str, dict, dict], tuple[int, dict]]


def urllib_post(url: str, headers: dict, body: dict, *, timeout: float = 600.0) -> tuple[int, dict]:
    """The standard-library transport. An error status is returned, not raised: the adapter decides what it means."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def to_responses_request(body: dict, *, model: str, harness_id: str) -> dict:
    """The loop's chat-shaped request as a Responses request.

    Messages map onto input items one for one. `tools` and sampler settings are **not** forwarded: in HarnessRouter the
    harness owns its tools and its loop, so sending the loop's tool schemas would describe a tool set the harness will
    not use. They stay in the loop's body, where `tierbook.harness` reads them, so what the loop recorded as its harness
    parts is still what it sent; the harness that actually ran is identified by `harness_id`.
    """
    return {
        "model": model,
        "input": [{"role": m["role"], "content": m["content"]} for m in body.get("messages", [])],
        "metadata": {"harness_id": harness_id},
        "stream": False,
    }


def text_of(response: dict) -> str:
    """Every `output_text` part of every assistant message, in order."""
    return "".join(
        part.get("text", "")
        for item in response.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


def reply_from(status: int, response: dict, *, accept: Callable[[str, dict], bool]) -> Reply:
    """What the loop needs back, including the case the opencode example learned the hard way: **no answer at all is
    not a wrong answer.** A request HarnessRouter refused (unknown harness or model, bad request) never reached a model,
    and a task that failed inside the harness never produced one; both are recorded as unobserved, with the reason in
    the mechanism's own vocabulary, rather than as `accepted=False`."""
    if status >= 400:
        reason = "unsupported" if status in (400, 404, 422) else "execution_error"
        return Reply(text="", accepted=False, input_mtok=0.0, output_mtok=0.0, unobserved_because=reason)
    usage = response.get("usage") or {}
    tokens_in = float(usage.get("input_tokens", 0)) / 1e6
    tokens_out = float(usage.get("output_tokens", 0)) / 1e6
    if response.get("status") != "completed":
        return Reply(text="", accepted=False, input_mtok=tokens_in, output_mtok=tokens_out,
                     unobserved_because="execution_error")
    text = text_of(response)
    return Reply(text=text, accepted=bool(accept(text, response)), input_mtok=tokens_in, output_mtok=tokens_out)


def harnessrouter_adapter(base_url: str, harness_id: str, *, api_key: str, post: Post = urllib_post,
                          accept: Callable[[str, dict], bool] | None = None) -> Agent:
    """An `Agent` that sends each call through HarnessRouter, on one harness.

    `base_url` is the instance's harness API root (the README's `HARNESSROUTER_BASE_URL`, e.g. `.../api/harness`).
    `accept` is this deployment's quality signal and the one thing a caller must think about: the default -- the task
    completed with a non-empty answer -- is as crude as the opencode example's, and a real run replaces it with what it
    can actually observe, such as a test suite passing on the patch.
    """
    judge = accept or (lambda text, response: bool(text.strip()))
    url = base_url.rstrip("/") + "/v1/responses"
    headers = {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}

    def agent(body: dict, *, candidate: str) -> Reply:
        status, response = post(url, headers, to_responses_request(body, model=candidate, harness_id=harness_id))
        return reply_from(status, response, accept=judge)

    return agent
