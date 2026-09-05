# Requests from a routing layer: four opaque attachment fields, and the fixes we run as local patches

This file bundles **five requests (A–E)** and **three confirmation-only questions (Q1–Q3)**.

**Every section is self-contained and can be split into its own issue.** Splitting is welcome — the
letters are stable references and do not encode priority.

The requests are written against the repository's own `feature_request` / `bug_report` templates, so
each section carries a problem statement, the proposed change, alternatives considered, acceptance
criteria, and a breaking-change assessment.

## Summary

**What is requested**

| # | Request | Component | Independent? | Can we work around it? |
|---|---|---|---|---|
| **E** | Stop writing plaintext email addresses into audit log lines | backend | yes | yes, by carrying a patch — but this **violates C12.4, your own stated requirement** |
| **B** | Forward reasoning content and stream usage correctly; report cache legs as disjoint fields | backend | yes | yes, by carrying patches — but this is **a bug every OpenAI-compatible caller hits** |
| **D** | Build the backend image for the platform Fargate runs | iac | yes | yes (7 lines) |
| **C** | Warn when a reply was billed but carries no answer | backend | yes (its diff sits on top of B) | yes, by carrying patches |
| **A** | Four optional opaque attachment fields on the reserve record | backend | yes | yes — **degradable to an out-of-band ledger**, see A's last subsection |

**If only one of these is done, it should be B.** The `cached_tokens` semantics mismatch is not
specific to us: any caller applying OpenAI semantics to this gateway's usage block under-counts its
own cost silently. **E is smaller and is already a violation of a requirement you set yourselves**, so
it is the cheapest thing here to close; we rank B first only because it changes what callers are
billed for. A is the request we care most about as a design matter, but it is not urgent.

Sections are ordered A → B → C → D → E for stable lettering, which is **not** the priority order; the
table above is.

**What is not requested** — no extension of the reject-reason enum, no producer-specific field, no
dereferencing of `ext_uri`, no new table, no change to the money write path, and no verification that
`ext_uri` is free of sensitive content. Reasoning is in the closing section.

B, C, D and E are changes we already run in our deployment. Each section states the symptom, the cause,
the fix and how to verify it, at a granularity that can be re-implemented independently. **Focused
diffs and their tests are available on request.** Because two of our local commits each carry more
than one review concern — one of them holds both half of B and all of E — we would hand them over split
by the work packages below rather than as cherry-pickable commits. If an upstream implementation differs in shape from ours, we drop our patch
as soon as the symptom is gone.

---

## Request A: four opaque attachment fields on the reserve record

**Component:** backend (reserve request model, decision record)

### Problem statement

A routing layer decides which model to call, and later wants to answer "was that the right call?"
from records that were written before the outcome existed. The detail behind a decision — which
accuracy floor was held, which equivalence predicate decided that two answers agreed, which frozen
evaluation fold the estimate came from — is specific to one routing layer and does not belong in a
billing gateway. A gateway that grew a field per concept would take on the shape of whichever
routing layer asked first, and the next routing layer could not use it.

What the gateway is uniquely able to provide is **a timestamp that the routing layer did not write**.
The decision record is written at reserve, before the model runs. A digest of an external record
riding in that write inherits that property: the claim was fixed before the outcome existed. No
amount of care on our side reproduces this, because a routing layer attesting to its own punctuality
proves nothing.

So the request is for **a pointer and a promise, and nothing else**.

### Proposed solution

Four optional fields on the reserve request. All omittable; default absent.

| field | type | validation — the gateway's responsibility ends here |
|---|---|---|
| `ext_uri` | bounded string | ASCII, ≤512. **Not parsed as a URI. Never dereferenced** |
| `ext_digest` | sha256 hex | exactly 64 hex characters. We propose lower-case only, so one digest has one representation and P-A1 stays simple; follow your own convention if it differs |
| `ext_media_type` | bounded string | printable ASCII, ≤128. An opaque label. Not interpreted |
| `ext_producer` | safe key token | whatever your existing key-token grammar is. If there is none, we propose `[a-z0-9_-]{1,64}` |

Accepted values are stored as the bytes received — not normalised, truncated or re-encoded.

The digest is over **the stored bytes of the external object, not a canonical form of it**. We
considered canonicalisation and rejected it: a canonical form needs the same normalisation
implemented on both the writing and the verifying side, and a divergent second copy of a rule is
exactly the class of bug the gateway's own key-token helper exists to prevent. Verification must be
three steps with no shared library — fetch, hash, compare.

### Acceptance criteria

- **P-A1 Transparency.** The four values accepted at reserve are byte-identical on read and export.
- **P-A2 Fail-closed atomicity.** A reserve carrying an attachment that fails syntax validation is
  **rejected as a whole request**, with no money write and no partial record. Silently dropping only
  the attachment is not acceptable — it breaks the producer's assumption that the commitment landed.
- **P-A3 Equivalence when absent.** For a request carrying none of the four fields, the response and
  the resulting record are indistinguishable from the current implementation.
- **P-A4 Accounting independence.** Presence or content of an attachment changes no accounting value:
  no token leg, no amount.
- **P-A5 Non-interpretation.** An `ext_uri` that is ≤512 ASCII characters but **not** a valid URI is
  also accepted. (This is "the gateway does not interpret it", written as something testable.)
- **P-A6 Non-dereference.** Acceptance is a pure function of length and character class. That no
  network I/O originates from `ext_uri` is a code-review item rather than a property test.

### Alternatives considered

- **A namespaced reason registry**, so a routing layer's reject reasons could live beside the
  gateway's own. Rejected: adding namespaces to a billing gateway is the wrong shape, and this
  request would then need updating every time a routing layer invented a word. Externalising the
  detail removes the request entirely — with no place for producer-specific vocabulary, the gateway
  cannot acquire a routing layer's shape even by accident.
- **A free-form tag bag.** Rejected: keys that appear at runtime disperse — the same reason ends up
  spelled three ways and the records stop being aggregable, which defeats the purpose of keeping them.
- **A single key doubling as both the analysis scope and the storage prefix.** Rejected: that pattern
  works where the metadata and the payload are one campaign's data and losing one without the other
  is an accident. Here the asymmetry is intended (the digest outlives the bytes), so one key would
  bind together two deliberately different lifetimes.
- **Bedrock invocation logging** instead of gateway-side fields. Rejected as the record location for
  this: there is no mechanism to attach a decision rationale, no way to join to a run or span, and it
  is an account-wide setting, so enabling it means opening a log sink that includes other teams'
  request bodies. Its value as independent evidence for provider charges is real, but that is an
  account-operations matter this design does not depend on.

### Breaking change assessment

- **Request path: no break.** Existing clients send none of the new fields.
- **The one place something can break:** a third-party consumer reading the ledger or an export with
  a strict schema (`additionalProperties: false` or equivalent) meeting an attachment-bearing record.
  Attachments are producer opt-in, so records without them stay identical by P-A3. Whether a public
  export schema exists is **unverified on our side** — that is Q2.
- Existing property tests that enumerate fields exhaustively will need updating. We consider that
  expected work rather than a compatibility break, and we call it out so it is not a surprise.
- **Size:** at most roughly +800 bytes per record with all four fields at their limits. Whether
  records or log lines have a size ceiling is **unverified**; if there is one, we would like to know.
- We ask for **no new table**, but whether your storage format needs a column added is **your call and
  unverified by us**.

### What the gateway is not asked to guarantee, and what we do not claim either

- **Not completeness.** Decision writes are fire-and-forget and lossy by design. Coverage is reported
  as a rate on our side, never assumed — the same partial-sum discipline the savings figures already
  apply.
- **Not readability.** The digest lives as long as the record, which has no TTL. The bytes live as
  long as the store's retention. These are two lifetimes and we do not conflate them; after retention
  passes, the commitment still holds and the content is unrecoverable, which our analysis names as a
  distinct state rather than treating as absence.
- **Not confidentiality by construction.** A producer determined to encode content into a bounded
  token can do so in fragments. Syntax validation narrows the path; it does not close it. We do not
  ask the gateway to check this and we do not describe it as structurally prevented.
- **Not an analytics surface.** Aggregations that need the detail read the external store, which the
  routing layer's platform owns.

### If this is not implemented

We keep the digest-to-request mapping in an out-of-band ledger of our own. What degrades: the
commitment that a digest was fixed at the gateway's timestamp is lost, tamper detection then rests on
trusting our own ledger, and "there was never an attachment" becomes indistinguishable from "the
attachment is gone" without the gateway's record. **Operation continues under that degradation. That
is why this request is not urgent.**

---

## Request B: forward reasoning content and usage correctly (two commits, inseparable)

**Component:** backend — `_converse_core.py`, `chat_completions.py`, plus streaming and normalisation
tests. Local commits `4898fbf` and `86e99f6` (the latter also carries request E, which splits out).

**These two must be treated as one change.** The second is the fix for three defects found while
reviewing the first. Merging only the first would land those three defects upstream.

### Symptoms

1. The Converse path drops reasoning blocks and never emits a usage chunk on a stream. When both
   occur together, a reply that spent its entire output budget on thinking arrives as **an empty
   success that is billed in full**, and a streaming caller cannot compute its own cost at all.
2. `prompt_tokens_details.cached_tokens` is a **subset** of `prompt_tokens` under OpenAI semantics,
   but Bedrock's `inputTokens` excludes the cache legs and this gateway bills four mutually disjoint
   legs. **A caller that subtracts `cached_tokens` under OpenAI semantics under-counts its cost.**

### Proposed solution — the shape our patch takes; re-implementation is fine

- `normalized_events` mirrors `delta.reasoningContent` as three legs: text, signature, and redacted.
  The signature leg is required for multi-turn thinking round-trips that also use tools.
- The chat adapter forwards reasoning as `reasoning_content`, kept separate from the answer text, on
  both the streaming and non-streaming paths.
- `stream_options` is declared on the request model; with `include_usage`, a terminal usage-only chunk
  is emitted, and non-terminal chunks carry an explicit `"usage": null`.
- Cache legs move to `cache_read_input_tokens` / `cache_creation_input_tokens` — the names the
  compatible ecosystem already uses for disjoint counting. They are reported on the non-streaming
  path too, so the usage schema does not depend on the streaming flag.
- The unknown-reasoning-leg check becomes **an explicit set difference against the known legs**
  instead of an inference from "nothing was emitted", so a known leg co-occurring with an unknown one
  cannot hide it. The warning fires once per stream rather than once per delta.

### Acceptance criteria

- **P-B1.** A Converse stream with `include_usage` emits exactly one usage chunk, terminally, and
  non-terminal chunks carry `"usage": null`.
- **P-B2.** All three reasoning legs survive, and the signature round-trips through a multi-turn
  tool call.
- **P-B3.** Both cache legs are reported on the streaming and non-streaming paths; all reported legs
  are mutually disjoint and their sum equals the sum of the billed legs.
- **P-B4.** A known leg and an unknown leg in the same delta still produce the unknown-leg warning,
  once per stream.

### Alternatives considered

Reporting `cached_tokens` under OpenAI's subset semantics by folding the cache legs into
`prompt_tokens`. Rejected: it makes the gateway's own usage block disagree with the legs it bills, so
the ledger and the API response would tell different stories about the same request.

### Breaking change assessment

A caller that already reads `prompt_tokens_details.cached_tokens` from this gateway and knowingly
compensates for the disjoint counting would need to stop compensating. We think that caller does not
exist, precisely because the field's current value is not usable for cost arithmetic — but this is the
one behavioural change in the request rather than a pure addition.

---

## Request C: make "billed but answered nothing" visible on both transports

**Component:** backend (both transports) and iac. Local commit `2b2c563`. Its diff sits on top of
B's, but the warning itself ports independently.

### Symptom, including the diagnosis that turned out to be wrong

The first diagnosis of empty completions was the dropped reasoning block of request B. **Real traffic
refuted that.** Called through a deployed SDK, Bedrock can return a `reasoningContent` whose
`reasoningText.text` is empty — carrying only an opaque signature — while billing the full output
token count. The gateway cannot forward text the provider did not send, and `content: null` with
`finish_reason: length` is the standard signal for an exhausted output budget. **The wire was already
correct; the operator was the blind party.**

We include the refuted diagnosis because the remaining defect is an observability one, and knowing
which explanation was eliminated is what keeps the next occurrence from being misdiagnosed the same
way.

### Proposed solution

Both transports warn on a reply that was billed while answering nothing. The warning carries the
resolved model id, the request id, the stop reason, the output token count, whether thinking text was
present, and which block types were actually seen. **The condition is deliberately a catch-all, and
our code comment says so** — reading every instance as the signature case above is how the next cause
gets misdiagnosed.

One unrelated fix rides in the same commit: `iac/scripts/build-and-push.sh` pushed the mutable
`latest` tag before the immutable build tag, so on a repository with tag immutability the failing
`latest` PUT took the whole build down under `set -e`. The order is now immutable-tag-first.

### Acceptance criteria

- **P-C1.** A reply with billed `outputTokens > 0` and empty answer text produces exactly one warning,
  on either transport, carrying the fields above.
- **P-C2.** The immutable build tag is pushed before `latest`, and a `latest` push failure does not
  fail the build.

### Breaking change assessment

None. Log output only, plus a push ordering change in a script.

---

## Request D: build the backend image for the platform Fargate runs

**Component:** iac — `scripts/build-and-push.sh` (+7). Local commit `72a92f9`.

### Symptom

An arm64 build from an Apple Silicon host pushes and deploys cleanly, then fails at runtime with
`exec /app/entrypoint.sh: exec format error`. From the ECS side this appears only as a task exiting
255 with no container reason. **We believe an existing image tag named `v1.1.0-amd64` is the trace of
this happening before and being worked around by hand.**

### Proposed solution

Default the build to `linux/amd64`, overridable through a `PLATFORM` environment variable.

### Acceptance criteria

The produced image manifest's platform is `linux/amd64` by default, and the value of `PLATFORM` when
it is set.

### Breaking change assessment

None for anyone building on x86. A maintainer who deliberately built arm64 images for an arm64
runtime now passes `PLATFORM` explicitly.

---

## Request E: the audit writer records email addresses in plaintext

**Component:** backend — `mvp/authz.py`. Part of local commit `86e99f6`; separable from request B and
should be filed on its own if the bundle is split.

This one is a bug report against a requirement the project already states, not a feature request.

### Expected behaviour

C12.4: no structured log writes an email address in plaintext.

### Actual behaviour

`log_audit_event` does. `core/logging.mask_sensitive_data` masks an `actor_email` **key**, and this
writer has no key to mask — it serialises its whole payload into the log record's **message**, so the
processor chain never sees a field and the address rides straight through it.

An address reaches this writer by four routes that real call sites use, not just the named field:

| route | call site |
|---|---|
| the named `actor_email` field | `admin_tenants` |
| a value inside `details` | `admin_users` |
| a human-readable `reason` sentence | `sso_exchange` |
| `target_id` itself — an SSO invite is keyed by the address it invites | `admin_sso_invites` |

Masking the named field alone would leave the other three.

### Proposed solution

Scrub the **whole payload at the single writer**, not at each call site — the same reasoning that keeps
`BILLABLE_LEGS` one declaration instead of a rule every caller repeats.

- `actor_email` becomes `actor_email_hash`.
- A recursive scrub walks dicts and lists and rewrites addresses **in place inside a sentence** rather
  than dropping the sentence, so a reason like "<address> already has a password-based account" keeps
  its meaning and loses only the address.
- The marker is `dynamo.usage_logs.hash_user_email`'s digest, not the 8-character marker
  `core/logging` uses for ephemeral app logs, because an audit row and a usage row are both persisted
  and matching an actor across the two is the only reason to keep any form of the address.
- `actor_id` stays as the identity a reader resolves against the Users table.

The address pattern is deliberately loose on the local part and anchored on a dotted domain: matching
one string that was not an address costs a marker in a log line, and missing one costs a plaintext
address in a durable record.

### Acceptance criteria

- **P-E1.** An audit event carrying an address by each of the four routes above emits a line
  containing no substring matching an email address.
- **P-E2.** The named field is `actor_email_hash` and `"actor_email":` does not appear.
- **P-E3.** The same actor yields the same marker in an audit line and in a usage row.

### Alternatives considered

Extending `mask_sensitive_data` to cover this writer. Rejected: the processor chain operates on fields,
and this writer's payload is a message; making the chain parse messages would make every log line's
cost depend on a regex over its full text, for one writer's benefit.

### Breaking change assessment

Anyone parsing audit lines for `actor_email` sees `actor_email_hash` instead, and cannot recover the
address. That is the point of the change. Retrospective correlation is preserved through the shared
digest, and identity resolution through `actor_id`.

### Note on scope

We are reporting the defect and the shape of our fix. **We have not audited whether other writers that
serialise payloads into messages have the same gap** — we found this one because it sat next to work we
were already doing. The pattern to look for is a writer that logs `json.dumps(payload)` rather than
structured fields.

---

## Confirmation-only questions

These are specification questions. **No implementation is requested in any of them.**

### Q1. What is the intended provider-side behaviour after a gateway timeout or a client disconnect?

Once the provider request has been submitted, for each of the Converse and OpenAI-compatible
transports: does the gateway actively cancel provider generation, does it only stop consuming the
response, or is cancellation best-effort and transport-dependent? And how is the hold or the billing
classified for generation that may continue after the caller has stopped receiving output?

**What we measured, so this is not a hypothetical.** In our environment a generation abandoned by the
client on a read timeout **ran to completion on the provider side and was billed** — 8,958 output
tokens on the call we instrumented. Existing comments and the retention accounting acknowledge that an
abandoned provider call may continue to be billed, but we could not find one explicit cross-transport
statement of whether server-side generation is interrupted.

We are asking for the current guarantee — **or the explicit absence of one** — to be documented, so
callers do not infer that a client-side timeout bounds provider work or cost. A pointer to where it
is already written would fully answer this.

### Q2. Is there a public schema for the ledger or its export?

Specifically, how `additionalProperties` is treated. We need this to finish request A's compatibility
assessment; we could not determine it from the outside.

### Q3. Is the set of `reasoningContent` legs closed or open, as upstream sees it?

We designed request B's unknown-leg warning assuming the set can grow. If upstream treats it as a
closed enum, the warning is dead code and we would rather not add it.

---

## What we currently carry as local patches

We keep these until equivalent upstream changes exist, and we absorb the rebase cost.

| local commit | what it does | request |
|---|---|---|
| `4898fbf` | Normalise and forward Converse reasoning; honour requested stream usage | B |
| `86e99f6` | Disjoint cache legs; preserve unknown usage; detect co-occurring unknown reasoning legs | B |
| `86e99f6` | Scrub email addresses from audit lines by all four routes | **E** |
| `2b2c563` | Warn on answer-less billed replies; push immutable build tags before `latest` | C |
| `72a92f9` | Build for the Fargate platform rather than inheriting the host architecture | D |

All of these are running in our environment. **Note that `86e99f6` appears twice**: it carries both
half of B and all of E, which is why we would hand over diffs split by request rather than by commit.
If an upstream fix takes a different shape, we drop the corresponding patch once the symptom is gone.

---

## Considered and deliberately not requested

- **Extending the reject-reason enum.** A producer's own classification is not universal. It belongs
  in the content behind the attachment.
- **Any producer-specific field.** Same reason. The request closes at four fields.
- **Dereferencing `ext_uri`.** It would add a failure surface and an analysis surface to the gateway.
  Being able to point is enough.
- **A new table, or any change to the money write path.** We do not want to touch the accounting
  invariants; optional additive fields are sufficient. How they are stored is your call.
- **Verifying that `ext_uri` leaks nothing.** The gateway cannot check this. We hold it as an
  invariant on the producer side and have written it as such in our own contract.
- **Any gateway-side guarantee of an attachment's completeness or readability.** The design assumes
  the writes are lossy, and coverage is reported by the producer.

## Status of our side

The routing layer's contract for all of this is written and reviewed; **nothing in request A has been
implemented on either side.** B, C, D and E are running as the patches listed above. We are not blocked
on any of these — each section states what we do if the answer is no.
