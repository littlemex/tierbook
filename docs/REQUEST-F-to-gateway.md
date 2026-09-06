# Request F: a field's disposition is a function of the route *and the wire*, and one wire is unclassified

**Component:** backend — `_converse_types.FIELD_DISPOSITION`, `chat_completions.py` parameter
rejection sites, `test_request_field_disposition_is_executable.py`.

**One request, and it is the last one.** The four fixes we were carrying are upstream in v1.4.0 and
we carry none of them. This is not another instance of the class v1.4.0 closed; it is the observation
that the class was closed on one side of a boundary, and the request is to move the boundary rather
than to fix the fields that fell outside it. If this is done as specified there is nothing here for a
second round, because the thing being asked for is the total classification, not the members of it.

## Why this exists at all, stated plainly

Our previous filing listed defects we had personally tripped over. That was the wrong unit. v1.4.0
correctly generalised one of them into `FIELD_DISPOSITION` — a total classification a test can
falsify — and its own docstring scopes it to *"Every top-level **Anthropic Messages** request field
this gateway has an opinion about"*. `/v1/chat/completions` accepts the **OpenAI** request shape and
serves **two** upstream wires, so every OpenAI-shaped field is outside the set that test can falsify.

We then enumerated the whole matrix from your source rather than from what we had noticed: every
field a real caller sends on each inference route, crossed with each wire the route can resolve to,
classified by what the code does with it. That is the table in the next section, and it is what
convinced us to send one request instead of eleven.

## The finding: one field, two fates, no declaration

On `/v1/chat/completions`, `_build_openai_chat_payload` forwards the caller's body with
`body.model_dump(exclude_none=True)`, so **any** field the caller sent reaches the provider on the
`responses` wire. The Converse builder consumes named fields and an allowlist. The consequence is
that eleven fields are **honoured or silently dropped depending on which model was resolved**, with
nothing in the response saying which happened:

| field | `wire_protocol: messages` (Converse) | `wire_protocol: responses` (passthrough) |
|---|---|---|
| `reasoning_effort` | **dropped** | forwarded |
| `seed` | **dropped** | forwarded |
| `logit_bias` | **dropped** | forwarded |
| `presence_penalty` | **dropped** | forwarded |
| `frequency_penalty` | **dropped** | forwarded |
| `parallel_tool_calls` | **dropped** | forwarded |
| `verbosity` | **dropped** | forwarded |
| `prediction` | **dropped** | forwarded |
| `modalities` | **dropped** | forwarded |
| `store` | **dropped** | forwarded |
| `user` | **dropped** | forwarded |

This is the same defect shape v1.4.0 fixed for `thinking` — *"accepted by the request model, named as
forwarded, and never sent"* — and the same clause: **C13.1, a parameter this gateway cannot honour is
refused, not dropped.** The difference is only that these are OpenAI-shaped, so no table claims
anything about them and no test can be wrong.

### One of the eleven makes a README guarantee false

`README.md:233` says of this route:

> Unsupported parameters — `n > 1`, `logprobs`, `response_format`, `image_url` content parts, and
> **`parallel_tool_calls: false`** — are rejected with an explicit 400 rather than silently dropped, so
> incompatible requests fail loudly instead of degrading quietly.

`parallel_tool_calls` appears **zero times** in `backend/`, tests included:

```
$ grep -rn "parallel_tool_calls" backend/ --include='*.py' | wc -l
0
```

So it is accepted by `extra="allow"`, forwarded on the `responses` wire, and dropped on the Converse
wire — the precise behaviour the sentence promises does not happen. This is not a documentation nit:
the claim is *the invariant itself*, made in the place a caller reads to decide whether it can trust
the parameter, and it is the one field of the eleven where the drop changes control flow rather than
sampling. A caller setting `parallel_tool_calls: false` is telling the gateway its agent loop cannot
execute two tool calls from one turn; on the Converse wire it will receive exactly that and has been
told, in writing, that it would have received a `400` instead.

We flag it separately because it is the cheapest thing in this request to verify — one `grep` — and
because it suggests where else to look: the README sentence is a guarantee that no test holds, which
is the same gap `FIELD_DISPOSITION` was created to close, one layer up.

**Two of the eleven are not cosmetic, and we can say what they cost because we paid it.**

- **`reasoning_effort`.** We ran a three-tier agentic comparison whose premise was that every tier
  reasoned. The premium tier sent `reasoning_effort: "high"` to a `messages`-wire model for weeks. It
  was accepted, dropped, and billed. Across 4,267 recorded responses every Claude model reports
  `reasoning_tokens: 0` while every OpenAI and xAI model reports 92–99% of output as reasoning —
  which is what the silence looks like from the outside once you know to look. Our figures survive
  because the direction happened to be safe, and that was luck, not design.
- **`seed`.** A caller that sets a seed and receives non-determinism does not conclude "the parameter
  was ignored", it concludes "this model is non-deterministic at temperature 0" and then reports a
  run-to-run noise figure. We have published such a figure. Converse has no seed, so dropping is the
  only *behaviour* available — which is exactly why C13.1 asks for a refusal instead.

## The second finding, which is the same principle applied inconsistently

`chat_completions.py` already has both rejection sites and already articulates when to use which:

- **route-wide, before the wire is known** (`:462`, *"Reject unsupported parameters explicitly (no
  silent drops)"*): `n > 1`, `logprobs`, `stream_options` without `stream`.
- **behind `if entry.wire_protocol == "messages"`** (`:534`): `top_logprobs`, `response_format`, with
  the reason given as *"the OpenAI-compatible endpoint serves both natively and rejecting them for
  every transport would deny structured output to the models that support it."*

That reason applies to `logprobs` and has not been applied to it. `logprobs` is rejected route-wide,
and OpenAI's Chat Completions API requires `logprobs: true` for `top_logprobs` to be legal. So on the
`responses` wire: send `top_logprobs` alone and the provider rejects it; send both and this gateway
rejects it. **The parameter the wire-conditional carve-out was written to preserve is unreachable in
every combination.**

Either the passthrough endpoint serves `logprobs` — in which case the route-wide rejection is in the
wrong place by your own stated reason — or it does not, in which case the `top_logprobs` carve-out is
wrong and the comment at `:536` is false. We cannot tell which from the source and are not guessing;
both readings are a defect and the measurement that settles it is yours to run.

We have an interest to declare here: an answer-token logprob margin is the only usable difficulty
signal we have found (AUROC 0.838, against 0.529 for output length and 0.62 for embeddings), and it
is unobtainable through this gateway on any model. We are not asking for a feature — we are asking
for the inconsistency to be resolved in whichever direction is true.

## What we are asking for

**Not** eleven fixes. One invariant, which makes the eleven a consequence.

1. **Re-key the classification by `(request shape, wire)`.** `FIELD_DISPOSITION` becomes a total
   function over the fields this gateway claims to handle *on each route*, valued in
   `forwarded` / `read_by_name` / `accepted_and_unused` / `refused`. A field whose value differs by
   wire is written as two entries, so "this field has two fates" becomes a fact the table states
   rather than an emergent property of which module happens to read it.
2. **Extend the executable test to the OpenAI-shaped request model and both wires.** It already
   builds the Converse payload and looks; the passthrough payload is built by one pure function
   (`_build_openai_chat_payload`) and can be looked at the same way. A field in no class fails, in
   both directions, on both wires.
3. **Refuse, on the wire where the field cannot be honoured**, using the site and shape that already
   exist at `:534`: `400`, `code: "unsupported_parameter"`, the parameter named. Not a warning — a
   warning is an operator-facing artefact and the party misled here is the caller.
4. **Resolve the `logprobs` / `top_logprobs` inconsistency** in whichever direction the passthrough
   endpoint's actual behaviour dictates, and record which it was.
5. **Bring `README.md:233` and `:816` back into agreement with the code, and put that sentence under
   the classification.** Either `parallel_tool_calls: false` is rejected as documented, or it comes
   out of the list. The durable form is that the README's list of rejected parameters is *generated
   from or checked against* the classification, so the two cannot drift again — the same move that
   made `test_documented_money_flag_defaults.py` compare documented defaults against the code that
   produces them.
6. **Document `reasoning_effort`.** It is the one parameter in this area with **zero** hits across
   `README.md` and `docs/`, and it is the one an OpenAI SDK user is most likely to set.

**Withdrawn from this request, because we checked and were wrong.** An earlier draft asked you to
document the `thinking` asymmetry on `/v1/messages`. It is already documented, in more places and
better than we would have asked for: `README.md:224–226` and the route table at `:815` both state it
with the reason, `docs/ARCHITECTURE.md:843–852` covers the reasoning legs and says multi-turn thinking
with tool use is unsupported, and clause **C13.4** carries an explicit boundary paragraph naming this
exact drop as a stated deferral rather than a case the clause covers. We are recording the withdrawal
rather than deleting it, so the same request is not made a third time by someone reading only the
code.

### Acceptance criteria

- **P-F1.** For every field in the classification, on every `(route, wire)` pair, the test asserts
  the claimed disposition by constructing the payload that will actually be sent and inspecting it.
- **P-F2.** A field present in the ecosystem list for a route and absent from the classification
  fails the test. Adding a field to the classification without implementing its disposition also
  fails.
- **P-F3.** A request carrying a field classified `refused` on the resolved wire returns `400` naming
  the parameter, **before any reservation is opened**, and is not billed.
- **P-F4.** A field classified `forwarded` on one wire and `refused` on the other is exercised on
  both, in one test, so the asymmetry cannot regress on one side silently.
- **P-F5.** `top_logprobs` is reachable on the wire whose endpoint supports it, or it is refused on
  both and the carve-out and its comment are removed.
- **P-F6.** The README's list of rejected parameters is checked against the classification by a test,
  so a parameter named there and unhandled in code fails a build rather than a caller.

### Alternatives considered

**Translating `reasoning_effort` into `thinking` for Converse-backed models.** Rejected as a request:
the mapping from three effort levels to a token budget is a policy judgement, it would make the same
parameter mean different things per provider, and a gateway inventing a budget the caller did not ask
for is a gateway spending the caller's money on its own opinion. Refusing is honest and costs nothing.

**Forwarding every unrecognised extra into `additionalModelRequestFields`.** Rejected for the reason
already written at `_converse_types.py:60` — it converts this gateway's forward-compatible
`extra="allow"` into an upstream `ValidationException` the caller cannot act on. The allowlist is
right; the request is that what is *outside* the allowlist be refused rather than dropped.

**Us maintaining the matrix on our side.** This is what we are doing in the interim, and it is the
wrong home: the classification is a property of the gateway's conversion code, and a copy of it in a
routing layer is stale from the moment either side changes. Our copy also cannot refuse a request
before it is billed, which is the part that matters.

### Breaking change assessment

**This is a behaviour change and callers will notice.** A request that today succeeds while quietly
ignoring `seed` or `reasoning_effort` will begin returning `400`. That is the point, and it is the
same trade v1.3.0 already made for `stream_options` with `stream=false`. Two notes on scope:

- The change is confined to fields in the classification. `extra="allow"` still accepts a field
  nobody has classified, so a new vendor field does not `422` — the forward-compatibility that
  `_converse_types.py:66` protects is untouched.
- `user`, `store` and `metadata`-like fields are inert observability hints rather than behaviour
  controls, and refusing them may be more disruptive than it is worth. We have listed them for
  completeness and have no objection to their being classified `accepted_and_unused` **explicitly**,
  which is a declaration rather than an accident and satisfies the invariant either way.

### Out of scope, deliberately

`container` and `mcp_servers` on `/v1/messages` are unclassified, and we are **not** filing them:
your own docstring states that the table cannot enumerate every field Anthropic will ever ship, and
we agree. The request above is about the fields this gateway *claims* to handle and the wire-dependent
fates it does not currently state — not about upstream's roadmap.

## One correction back to you, since you asked for them

Your answer to request B says our build put a disjoint count in
`prompt_tokens_details.cached_tokens`, and that our diagnosis was of the wrong artifact. The patch
emitted the top-level `cache_read_input_tokens` / `cache_creation_input_tokens` keys and carried a
test asserting `"prompt_tokens_details" not in usage` — the same shape v1.3.0 shipped. Your shipped
`CHANGELOG` and code comments are correct; only the reply is not, so nothing needs changing in the
repository. The misreading was invited by our own filing, which wrote a *rationale* for the field
naming in the position where the template asks for a *symptom*, and our breaking-change note then
described a caller reading a field that on `main` did not exist.

Two of your findings we are adopting wholesale, with thanks: our recursive-walk fix for E would have
leaked through a dict key and through a leaf coerced by `default=str` after the walk, and our
condition for C would have fired on every tool-use turn. Both are recorded on our side with the
reasoning, because in each case the corrected version is not the one we would have arrived at.
