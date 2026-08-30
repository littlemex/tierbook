"""Route each model name to its own endpoint, leaving tau-bench unmodified.

tau-bench calls `litellm.completion(model=..., custom_llm_provider=...)` for both the agent and the user
simulator in one process, and litellm takes `api_base` from process-wide environment. That would force the
simulator onto whichever endpoint the agent under test is using, which makes an arm's difficulty depend on
the arm -- the one thing the pre-registration says must not happen.

So `completion` is wrapped once and `api_base`/`api_key` are chosen per model name from TIERBOOK_ENDPOINTS,
a JSON map of {model: {api_base, api_key_env}}. Nothing else about tau-bench changes: the agent loop, the
user simulator, the reward computation and the task data are the authors'.
"""
import json
import os

import litellm

_MAP = json.loads(os.environ.get("TIERBOOK_ENDPOINTS", "{}"))
_original = litellm.completion


def _routed(*args, **kwargs):
    model = kwargs.get("model")
    entry = _MAP.get(model)
    if entry:
        kwargs.setdefault("api_base", entry["api_base"])
        key_env = entry.get("api_key_env")
        kwargs.setdefault("api_key", os.environ.get(key_env, "unused") if key_env else "unused")
        # Parameters this tier refuses. The benchmark sends the same request to every arm, so a tier that
        # rejects a parameter the others accept has to have it dropped here rather than in the benchmark --
        # otherwise the arm fails for a reason that is not about the model. Each entry is a measured
        # restriction and is recorded on the tier's registry record, not hard-coded to a model name.
        for param in entry.get("drop_params", ()):
            kwargs.pop(param, None)
    # tau-bench reads res._hidden_params["response_cost"], which litellm only fills for models in its own
    # price map. These are gateway aliases and a self-hosted checkpoint, so that lookup fails and the
    # benchmark's own cost column is meaningless here. Cost is taken from the token counts against the
    # registry's measured price cards instead, which is the only accounting this project trusts.
    kwargs.setdefault("drop_params", True)
    return _original(*args, **kwargs)


litellm.completion = _routed
# The agent and user modules import the symbol directly, so patch where they hold it.
for mod in ("tau_bench.agents.tool_calling_agent", "tau_bench.envs.user"):
    try:
        __import__(mod)
        import sys
        setattr(sys.modules[mod], "completion", _routed)
    except Exception:
        pass


# --- the responses wire, for a tier that cannot have tools and reasoning on chat completions -------
#
# One tier refuses function tools together with any reasoning_effort other than "none" on chat completions.
# Forcing it to "none" makes it a materially different model -- measured elsewhere in this project as
# reasoning falling from 80% of output tokens to zero and the solve rate falling with it -- so the arm would
# be measuring the restriction rather than the tier. The adapter translates instead, which is exactly the
# per-tier work the design says belongs in an adapter and not in the benchmark.
import json as _json
import urllib.request as _url
from types import SimpleNamespace as _NS


def _to_responses_input(messages):
    """Chat messages to Responses items: an assistant tool call and its result become their own items."""
    items = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            if m.get("content"):
                items.append({"role": "assistant", "content": m["content"]})
            for c in m["tool_calls"]:
                fn = c.get("function") or {}
                items.append({"type": "function_call", "call_id": c.get("id") or "",
                              "name": fn.get("name") or "", "arguments": fn.get("arguments") or "{}"})
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": m.get("tool_call_id") or "",
                          "output": m.get("content") or ""})
        elif m.get("content") is not None:
            items.append({"role": role, "content": m["content"]})
    return items


def _responses_completion(entry, kwargs):
    tools = [{"type": "function", **(t.get("function") or {})} for t in (kwargs.get("tools") or [])]
    body = {"model": kwargs["model"], "input": _to_responses_input(kwargs.get("messages") or []),
            "max_output_tokens": entry.get("max_output_tokens", 4000)}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if entry.get("reasoning_effort"):
        body["reasoning"] = {"effort": entry["reasoning_effort"]}
    req = _url.Request(entry["responses_url"], data=_json.dumps(body).encode(),
                       headers={"Content-Type": "application/json",
                                "Authorization": "Bearer " + os.environ.get(entry.get("api_key_env") or "", "")})
    with _url.urlopen(req, timeout=entry.get("timeout", 600)) as r:
        d = _json.load(r)
    text, calls = "", []
    for item in d.get("output") or []:
        if item.get("type") == "function_call":
            calls.append(_NS(id=item.get("call_id") or item.get("id") or "", type="function",
                             function=_NS(name=item.get("name") or "",
                                          arguments=item.get("arguments") or "{}")))
        elif item.get("type") == "message":
            for part in item.get("content") or []:
                text += part.get("text") or ""
    u = d.get("usage") or {}
    det = u.get("input_tokens_details") or {}

    def _dump():
        out = {"role": "assistant", "content": text or None}
        if calls:
            out["tool_calls"] = [{"id": c.id, "type": "function",
                                  "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                 for c in calls]
        return out

    msg = _NS(role="assistant", content=text or None, tool_calls=calls or None, model_dump=_dump)
    usage = _NS(prompt_tokens=u.get("input_tokens") or 0, completion_tokens=u.get("output_tokens") or 0,
                prompt_tokens_details=_NS(cached_tokens=det.get("cached_tokens") or 0))
    return _NS(choices=[_NS(message=msg)], usage=usage, _hidden_params={"response_cost": 0.0})


_chat_routed = _routed


def _routed_any(*args, **kwargs):  # noqa: D401
    entry = _MAP.get(kwargs.get("model")) or {}
    # The responses wire is used only when the restriction requires it, which is when tools are declared.
    # The user simulator never declares tools, so it stays on chat completions in every arm -- which is what
    # keeps it a constant of the experiment rather than something that changes with the tier under test.
    if entry.get("responses_url") and kwargs.get("tools"):
        return _responses_completion(entry, kwargs)
    return _chat_routed(*args, **kwargs)


litellm.completion = _routed_any
for mod in ("tau_bench.agents.tool_calling_agent", "tau_bench.envs.user"):
    try:
        __import__(mod)
        import sys as _sys
        setattr(_sys.modules[mod], "completion", _routed_any)
    except Exception:
        pass
