"""What each inference route does with each request field, per upstream wire.

Written because the last round of requests filed symptoms instead of a class. The gateway closed
the class for one wire -- `FIELD_DISPOSITION` is scoped to "Anthropic Messages request fields" --
and the remaining holes sit just outside that boundary. So this enumerates the whole matrix from
the source rather than from what anyone happened to trip over.

For each (route, field) it reports:
  read      - the code reads it by name and does something with it
  rejected  - the code raises a 400 naming it, route-wide
  rejected@messages / rejected@responses - rejected only on that wire
  forwarded - reaches the provider inside a passthrough payload or additionalModelRequestFields
  DROPPED   - accepted by the request model or by extra="allow", and never referenced

Every DROPPED is a candidate violation of the gateway's own C13.1 ("a parameter this gateway
cannot honour is refused, not dropped").
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/Users/akazawt/stratoclave")
MVP = ROOT / "backend" / "mvp"

ROUTES = {
    "/v1/chat/completions": ("chat_completions.py", "ChatCompletionsRequest"),
    "/v1/messages": ("anthropic.py", "AnthropicMessagesRequest"),
    "/openai/v1/responses": ("openai_responses.py", None),
}

# Fields real callers send. Not "every field the vendor will ever ship" -- the set a client
# library or a plain curl actually puts on the wire today, which is the set a silent drop can
# cost someone money on.
ECOSYSTEM = {
    "/v1/chat/completions": [
        # OpenAI Chat Completions
        "model", "messages", "max_tokens", "max_completion_tokens", "temperature", "top_p",
        "n", "stream", "stream_options", "stop", "presence_penalty", "frequency_penalty",
        "logit_bias", "logprobs", "top_logprobs", "response_format", "seed", "tools",
        "tool_choice", "parallel_tool_calls", "user", "service_tier", "metadata", "store",
        "reasoning_effort", "prediction", "modalities", "verbosity",
        # Anthropic-shaped extras a caller may add for a Claude model behind this route
        "thinking", "top_k", "anthropic_beta",
    ],
    "/v1/messages": [
        "model", "messages", "system", "max_tokens", "temperature", "top_p", "top_k",
        "stop_sequences", "stream", "tools", "tool_choice", "metadata", "service_tier",
        "thinking", "anthropic_beta", "container", "mcp_servers",
    ],
}


def declared_fields(path: Path, cls: str) -> dict[str, str]:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            out = {}
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    out[stmt.target.id] = ast.unparse(stmt.annotation)
            return out
    return {}


def _const_tuple(path: Path, name: str) -> set[str]:
    """A module-level tuple/frozenset/dict of string literals, read from the source."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == name:
            return set(re.findall(r'''["']([a-z_]+)["']''', ast.unparse(node.value)))
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return set(re.findall(r'''["']([a-z_]+)["']''', ast.unparse(node.value)))
    return set()


CT = MVP / "_converse_types.py"
FORWARDED = _const_tuple(CT, "ADDITIONAL_MODEL_REQUEST_FIELD_KEYS")
RENDERED_ONLY = _const_tuple(CT, "RENDERED_ONLY_FIELD_KEYS")
DISPOSITION = _const_tuple(CT, "FIELD_DISPOSITION")
# `FIELD_DISPOSITION` maps name -> class, so the literal scrape above catches both. Pull the
# accepted-and-unused ones out by reading the dict properly.
_tree = ast.parse(CT.read_text())
ACCEPTED_UNUSED = set()
for _n in ast.walk(_tree):
    if isinstance(_n, ast.AnnAssign) and isinstance(_n.target, ast.Name) \
            and _n.target.id == "FIELD_DISPOSITION" and isinstance(_n.value, ast.Dict):
        for _k, _v in zip(_n.value.keys, _n.value.values):
            if isinstance(_k, ast.Constant) and isinstance(_v, ast.Constant) \
                    and _v.value == "accepted_and_unused":
                ACCEPTED_UNUSED.add(_k.value)


def classify(module: Path, route: str, field: str, declared: bool) -> str:
    """Both wires, because on this gateway one field can have two fates.

    The whole point of redoing this: `FIELD_DISPOSITION` is scoped to the Anthropic Messages
    request shape, so a field that only exists on the OpenAI shape is outside the set its test
    can falsify. That is where the last two findings were, so the classifier has to be told
    about both wires explicitly rather than reading one module.
    """
    src = module.read_text()
    lines = src.splitlines()
    converse_only = route == "/v1/messages"

    # Rejections, and whether they are route-wide or behind the wire branch.
    rejects = set()
    for i, ln in enumerate(lines):
        if not re.search(rf'\bbody\.{re.escape(field)}\b', ln):
            continue
        window = "\n".join(lines[i:i + 4])
        if "HTTPException" in window and "400" in window:
            near = "\n".join(lines[max(0, i - 22):i])
            rejects.add("messages" if 'wire_protocol == "messages"' in near else "both")

    reads = any(re.search(rf'\bbody\.{re.escape(field)}\b', ln) for ln in lines) and not rejects
    if not reads:
        reads = bool(re.search(rf'getattr\(body,\s*["\']{re.escape(field)}["\']', src))

    def verdict_for(wire: str) -> str:
        if "both" in rejects or wire in rejects:
            return "rejected(400)"
        if field in FORWARDED:
            if wire == "messages":
                if field in RENDERED_ONLY and converse_only:
                    return "withheld-by-design(unrenderable)"
                return "forwarded"
            # A responses-wire model never reaches the Converse builder.
            return "forwarded(verbatim body)"
        if reads:
            return "read"
        if field in ACCEPTED_UNUSED:
            return "accepted_and_unused(declared)"
        if wire == "responses":
            return "forwarded(verbatim body)" if "model_dump(" in src else "DROPPED"
        return "DROPPED"

    if converse_only:
        return verdict_for("messages")
    return f"{verdict_for('messages')} | {verdict_for('responses')}"


print(f"{'route':22s} {'field':22s} {'decl':6s} {'converse wire':34s} | responses wire")
print("-" * 96)
findings = []
for route, (fname, cls) in ROUTES.items():
    if route not in ECOSYSTEM:
        continue
    module = MVP / fname
    decl = declared_fields(module, cls) if cls else {}
    for field in ECOSYSTEM[route]:
        d = "declared" if field in decl else "extra"
        verdict = classify(module, route, field, field in decl)
        print(f"{route:22s} {field:22s} {d:6s} {verdict}")
        if "DROPPED" in verdict:
            findings.append((route, field, d, verdict))

print()
print(f"candidate silent drops: {len(findings)}")
for route, field, d, verdict in findings:
    print(f"  {route}  {field}  ({d})  {verdict}")
