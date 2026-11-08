# stratoclave patches for tierbook

Patches against [littlemex/stratoclave](https://github.com/littlemex/stratoclave) that tierbook needs and upstream
does not have yet. `infra/tierbook-up` applies them to its pinned checkout of the gateway (`GATEWAY_REF`, the commit
they were made against) before deploying, and `./infra/tierbook-up patches` reports whether each still applies or has
landed upstream. Both are proposed upstream as the branch `feat/me-rates-and-canonical-chat-usage` of
littlemex/stratoclave; delete them here once it is merged and `GATEWAY_REF` moves past it.

## What is in this patch

`0001-feat-mvp-let-a-caller-read-its-own-billing-rates-and.patch` adds two
read-only pieces of self-service data to the gateway's existing `/api/mvp/me`
surface, gated on the `usage:read-self` scope every end user already holds:

- `GET /api/mvp/me/rates` — the caller's current per-model billing rates
  (`input` / `output` / `cache_read` / `cache_write`, in micro-USD per
  million tokens), the active `pricing_key`, the active override version
  (or `null` for built-in defaults), and an `as_of` timestamp. Scoped to only
  the models the caller is actually eligible to invoke right now.
- `GET /api/mvp/me/usage-history` entries gain two fields: `cost_microusd`
  (the settled charge for that row, already stored server-side but not
  returned before) and `request_id` (the gateway's own correlation id for
  that request, echoed at the time on the `x-sc-span-id` response header).

## Why tierbook needs it

tierbook's v0.5 cost model prices every observed call as `current rate x
token count`, recomputed at report time rather than cached at observation
time, so that a price-list change alone makes a past report correct again —
`GET /api/mvp/me/rates` is where that current rate comes from, read straight
off the gateway that actually bills it, instead of a second price list
tierbook would otherwise have to maintain by hand and keep in sync.
tierbook also needs to check its own derived cost against what the gateway
itself charged for the exact same request — the new `cost_microusd` and
`request_id` fields on `/me/usage-history` are what let it join its own
record of a call to the gateway's billed amount for that same call.

## How to apply

```bash
cd stratoclave   # a clone of littlemex/stratoclave, on a branch off main
git am /path/to/this/directory/0001-feat-mvp-let-a-caller-read-its-own-billing-rates-and.patch
```

`git am` preserves the original commit message, author (`littlemex
<littlemex@users.noreply.github.com>`), and the fact that it is a single
commit. No `Co-authored-by` trailer is present.

## Base commit

Built against `littlemex/stratoclave@main` at commit `34768dca17a429e04a7368a34d71e8fe4561edb0`, which is also
`GATEWAY_REF` in `infra/tierbook-up`.

If `main` has moved on by the time this is applied and `git am` conflicts,
rebase the patch onto current `main` before applying — the change is
additive (a new endpoint, two new optional response fields, one write-side
attribute) and does not depend on anything specific to commit `34768dc`
beyond files it already touches (`backend/mvp/me.py`,
`backend/dynamo/usage_logs.py`).

## When this patch can be deleted

Delete this directory once littlemex/stratoclave's own `main` contains an
equivalent of both endpoints' behavior (whether merged as this exact patch,
rewritten, or superseded by a different design that still gives tierbook a
read of its live per-model rates and a per-request cost/id it can join
against) — i.e. once tierbook's own stratoclave clone can be a plain,
unpatched checkout of upstream `main` again.

## 0002: stop leaking Anthropic-shaped cache keys into chat/completions usage

`0002-fix-mvp-stop-leaking-Anthropic-shaped-cache-keys-int.patch` is a second
commit on the same branch (`tierbook/rates-and-request-cost`), on top of
0001 — apply both, in order, with `git am` as above.

**What it fixes.** On `/v1/chat/completions`, a Claude-family (Converse-backed)
response's `usage` block put its two prompt-cache legs at the top level,
spelled the Anthropic way (`cache_read_input_tokens` /
`cache_creation_input_tokens`) — keys the OpenAI Chat Completions `usage`
schema does not define. A GPT-family response on the same endpoint already
used the correct nesting (`usage.prompt_tokens_details.cached_tokens` /
`.cache_write_tokens`).

**Why tierbook needs it.** tierbook routes some of its traffic through this
gateway's `/v1/chat/completions` via vLLM Semantic Router, which decodes an
upstream response strictly and 502s on an unknown field — confirmed on real
traffic as `field "usage": unknown field "cache_read_input_tokens"`. Every
Claude-family call tierbook sent through that path failed outright; its
qwen/nemotron traffic over the same path did not, only because neither model
reports a cache leg for the unknown field to appear in. Without this fix,
tierbook cannot route any Claude-family model through vLLM Semantic Router at
all.

**What it keeps.** `prompt_tokens` keeps this endpoint's pinned meaning (C8.4: uncached input, with the cache legs
reported beside it and `total_tokens` excluding them), so on this endpoint a Claude response's cached tokens are
additive to `prompt_tokens` while a GPT response's are inside it. tierbook reads the difference from a declaration,
`tierbook ingest --cache-additive-arm <claude arm>`, rather than guessing it.

**Base commit.** The same `34768dca17a429e04a7368a34d71e8fe4561edb0` 0001 is
based on — 0002 is the very next commit on top of 0001, not an independent
patch against `main`.

**Delete this patch once it is upstream:** when a Converse-backed
`/v1/chat/completions` response reports its cache legs nested under
`usage.prompt_tokens_details` instead of the top-level
`cache_read_input_tokens` / `cache_creation_input_tokens` keys, on the pinned
commit.
