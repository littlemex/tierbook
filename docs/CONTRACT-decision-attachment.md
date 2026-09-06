<!-- Last updated: 2026-09-06 -->

<!-- Applies to: tierbook main. Gateway side: stratoclave v1.4.0 (request filed and answered; section 8 is
     the agreed shape, section 8.1 is what blocks building it) -->

> **Scope, before anything else: [`SCOPE.md`](../SCOPE.md).** This is a routing mechanism that collects its
> own data and decides while its environment moves. The decision is a **function from observed state to an
> assignment** — volume, prices, availability, capacity, request shape, floors and SLOs are all inputs, and
> every threshold in it is **derived, never configured**. *"At this concurrency the next request belongs on
> the API"* is **one example of the output shape, not the mechanism.* It is **not** a tuning guide for one
> cluster, not a standing verdict about which tier wins, and not a benchmark: numbers about a particular
> GPU, engine flag or agent are **parameter readings**, not results.

# Contract: how a routing decision's detail is recorded, and what that record proves

A routing layer knows things a billing gateway must never learn. It knows which accuracy floor it was
holding, which equivalence predicate decided that two answers agreed, which frozen fold the matrix came
from. None of that belongs in a ledger, and a gateway that grew a field for each of them would become
tierbook-shaped — a shape the next routing layer could not use.

So the gateway carries **a pointer and a promise**, and nothing else. The detail lives in a store this
project owns, and the promise is a hash: whatever is at that pointer must match the digest the gateway
recorded, or the analysis says so out loud. **This document is the normative source for what that pointer
guarantees and what it does not.**

Design decided across four review rounds with two independent reviewers, adversarial first. Where a round
overturned an earlier draft the overturned version is named, because the reason is the useful part.

## 0. Vocabulary, and the patterns this is assembled from

**Attachment** — the external object holding a decision's detail. Not a ledger row, not a log line.

**Digest** — the sha256 of the attachment's stored bytes. Not of a canonicalised form; see section 3.

**Tierbook Accuracy Certificate** — this project's certificate: an accuracy lower bound plus the pins that
make it meaningful. **Always written in full.** The bare word *certificate* in the gateway's codebase means
its Savings Certificate (`record_type: savings_certificate`, schema `cert-v1`, partition `CERT#`), which is
a different object with different invariants — its honesty caveats include *quality-unmeasured*, which is
precisely what ours measures. Writing `certificate` unqualified in an issue invites four concrete
mis-implementations, so the long name is a contract term rather than a style preference.

Known patterns, named so none of this reads as invention: **Claim Check** (Enterprise Integration Patterns —
move the payload out, carry the reference), **content-addressed storage**, and **hash commitment** (the
commit half of commit-reveal). The composition is ordinary; what is specific here is which properties
survive the gateway's lossy write path, and section 1 is careful about that.

## 1. What this contract guarantees

**G1. Commitment.** If a gateway decision record exists for a span and carries `ext_digest`, then the
content of that attachment was fixed at the time the gateway wrote its own timestamp. Nothing written later
can satisfy the digest except the bytes that were already decided.

**G2. Pre-registration for intent, on the spans the gateway covered.** The gateway writes its decision
record at reserve — before the model runs — and it writes its own timestamp. An intent attachment's digest
riding in that record therefore inherits the property that made the gateway's decision log worth having:
the claim was on record before the outcome existed. This is what an earlier draft could not do. That draft
had the routing layer write its own records, which meant the routing layer attesting to its own
punctuality; a reviewer named it and the digest-in-the-reserve-record construction is the answer.

**G3. Tamper evidence, degrading gracefully.** With a content-addressed store the attachment is
tamper-*proof*: the key is derived from the digest, so a different body cannot occupy the same key. With a
store that permits overwrite it is tamper-*evident*: the mismatch is detected on read. **The degradation is
part of the contract, not a caveat** — a backend that cannot offer write-once is still usable, and says so.

**G4. Separability, per record only where the ledger row is.** "There was no attachment" and "the attachment
is gone" are distinguishable when a decision record exists, because the digest's presence in it answers the
first question without touching the store.

**Corrected 2026-09-06, on a finding from the gateway's owner against this document.** An earlier version
claimed G4 unconditionally, and it does not hold that way: the decision write is fire-and-forget, so a
dropped write leaves no record and the two states collapse into one. The coverage rate in N1 bounds this
*statistically* and cannot resolve a single request, which is what an audit needs.

There is a better signal and it was ours to find: **the ledger row is not fire-and-forget.** "A ledger row
exists for this span and a decision record does not" identifies a dropped write for one specific request.
That is per-record separability, restored, and it costs nothing extra to record — but it is unusable until
the read surface in section 8.1 exists, so G4 is **conditional on that** and section 7 carries the state.

## 2. What this contract does not guarantee

**N1. Not completeness.** The gateway's decision writes are fire-and-forget and lossy by design. G1 and G2
hold **on the spans a decision record covers**, and coverage is reported as a rate, never assumed. This is
the same partial-sum discipline the gateway already applies to its savings figures, and for the same reason:
a figure presented as complete when it is a partial sum is the failure mode both projects are avoiding.

**N2. Not readability.** The digest lives as long as the gateway record, which has no TTL. The *bytes* live
as long as the attachment store's retention, which is a configured number. **These are two lifetimes and
this contract refuses to conflate them.** After the store's retention passes, G1 still holds and the content
is unrecoverable — a state the analysis must name, not treat as absence.

**N3. Not confidentiality by construction.** URI syntax can be bounded and paths can be made meaningless
(section 4), but a producer determined to encode content into a bounded token can do so in fragments. What
is offered is a narrowed path, not a closed one. **Do not write "structurally prevented" anywhere.**

**N4. Not a gateway-side analytics surface.** The gateway does not dereference. Aggregations that need the
detail read the attachment store, which this project owns; see section 6.

**N5. Not an agreement with the gateway — but no longer only an intent.** This is a tierbook document. The
request in section 8 has now been **filed and answered**: the gateway declined the four-field form, agreed
the surface should be headers, and counter-proposed one field, which section 8 adopts. What is agreed is the
*shape*; what is not built is the shape, because both prerequisites in 8.1 are the gateway's work and are
scheduled as a separate change. Every statement here about gateway behaviour that is not marked verified in
section 10 remains a design intent.

## 3. The digest is over stored bytes, and is not canonicalised

`ext_digest = sha256(the exact bytes stored at ext_uri)`, lower-case hex, 64 characters.

Canonicalisation was considered and rejected. A canonical form requires the same normalisation implemented
on both the write and the verify side, and a divergent second copy of a rule is the failure the gateway's
own key-token helper exists to prevent — its module says in as many words that a local copy is the class of
bug it is there to stop. Verification must be three steps with no shared library: fetch, hash, compare.

The consequence is accepted: a semantically identical attachment serialised differently is a different
attachment. That is correct for an audit object.

## 4. Keys, and why there is no single one

An earlier reading borrowed a pattern from this project's own profiling platform, where one `alias` serves
as both the experiment name and the object-store prefix, so that the analysis scope and the cleanup unit
coincide. **That borrowing was rejected on review**, and the reason is worth keeping: in the profiling
platform the metadata and the trace are the same campaign's data, so one surviving without the other is an
operational accident. Here the asymmetry is *intended* (N2), so a single key would tie together two things
whose lifetimes deliberately differ.

Three keys, each with one job:

| purpose | key |
|---|---|
| joining a span to the gateway's record | `(run_id, span_id)` |
| identity of the attachment, and its URI | `ext_digest` |
| the cohort that shares one certified configuration | the Tierbook Accuracy Certificate's digest |

`ext_uri` is `{configured_prefix}/{sha256hex}` and nothing else. **No tenant, model, certificate, policy or
fold in the path** — those either leak (section N3) or invite navigation by path, which no reader needs
because every human entry point starts at the gateway record.

Granularity rules, one borrowed and the rest not:

- **Borrowed:** an iteration must not become a cohort identity. What changes per iteration is
  `(run_id, span_id)` and the attachment digest, never the cohort key.
- **Not borrowed:** "one question, one key". An investigation is a *query* the evaluator defines, not the
  identity of an audit object. A certificate digest is the exact cohort of runs that shared nine pinned
  properties; spanning several revisions is something the evaluator states explicitly by listing digests,
  never something an implicit alias does for it.
- Differences in *conditions* are expressed inside the attachment. Differences in *configuration* are
  expressed as certificate pins.

## 5. Invariants

**I1. Digest before body.** The digest is computed and handed to the gateway before, or in the same step
as, the attachment upload. An upload that lands later still satisfies G1; one that lands *first* is
permitted but buys nothing.

**I2. Bytes-faithful round trip.** The store must return exactly the bytes written. A backend that
transforms, re-encodes or recompresses on read cannot host attachments.

**I3. Never raise, never block.** Attachment writing follows the gateway's discipline: failure to produce
or upload an attachment must not fail the request and must not delay it. A dropped attachment is a coverage
statistic.

**I4. Closed world for verdicts.** Where an attachment records an adjudication, the adopted member must be
one the corresponding intent attachment enumerated. A verdict naming something outside that set is
detectable and is excluded from audited statistics.

**I5. No detail on the gateway.** The one header of section 8 is the entire gateway-side footprint. A future
field carrying producer-specific meaning is a contract violation regardless of how convenient it is — and
the one-field form is what makes this an invariant rather than a vigilance: an opaque commitment leaves no
place for a vocabulary to accumulate, so the gateway cannot take a tierbook shape by accident.

**I6. One writer per digest.** Two producers must not write different bytes claiming one digest; with
content addressing this is automatic, and without it, it is I2's problem to detect.

## 6. Who reads what

Two owners, because one of them cannot do the other's job.

**Attachment Resolver — platform-owned.** Joins gateway records to the store, dereferences, verifies
sha256, and classifies each span as `verified` / `detail-unavailable` / `digest-mismatch` / `orphan`.
Reports counts and drop rates by producer and media type. Owns the store's IAM, network reachability and
retention. **Knows nothing about what an attachment means.**

**Tierbook Offline Evaluator — this project's.** Interprets the producer-specific schema, computes the
things only it can (agreement rates, escalation rates by floor, predicate match rates), and aggregates by
certificate digest. Every derived report carries the evaluator's version, the window, and the covered and
missing counts.

The split borrows one thing from the profiling platform — **read the data where it lives, and let the
permissions live there too** — and refuses to borrow the rest: domain semantics do not move to the platform.
It also means an analysis result is **not** the same evidence as the attachment it came from; a summary is
derived, and the audit object is the bytes.

## 7. Degraded behaviour, as a table the analysis must implement

| state | how it is detected | what analysis may claim |
|---|---|---|
| `verified` | digest matches fetched bytes | everything |
| `detail-unavailable` | record has a digest, fetch fails or object gone | commitment held (G1); content unknown. **Not** "no attachment" |
| `digest-mismatch` | fetch succeeds, hash differs | tampering or a broken store. Excluded from audit, alerted |
| `orphan` | attachment exists, no gateway record | usable for tuning, **never for audit** — it has no pre-registration attestation |
| `absent` | record exists, no digest field | the producer wrote none |
| `record-dropped` | **ledger row exists for the span, no decision record** | nothing about the attachment. Distinguishes a lost write from `absent`, which the digest's presence alone cannot — see the G4 correction. Requires the read surface of 8.1 |
| `record-never-attempted` | ledger row exists, no decision record, **and the request was a hard pin** | nothing about the attachment, and nothing is wrong. The gateway does not emit a record on a path with no multi-candidate decision facts, so this is the expected state for our own access pattern and must not be counted as a drop |

The last two are the states an earlier version of this table did not have, and their absence is what made
G4 look unconditional. Note that they are told apart by **the request shape, not by the record**: an audit
that cannot see whether the span was a hard pin cannot separate them, which is why 8.1 lists emitting the
record on a pinned path as a prerequisite rather than a nicety.

## 8. What the gateway is asked for (one header, and no vocabulary)

The request is deliberately small, and it has been made smaller twice. The first version asked for a
namespaced reason registry so this project's reasons could live beside the gateway's five. **The owner
rejected it**: adding namespaces to a billing gateway is the wrong shape, and the gateway's posture toward
routing layers is that they should not need it to change. Externalising the detail removed the request
entirely — there is no place for producer-specific vocabulary, so the gateway cannot acquire a tierbook
shape even by accident.

The second version asked for four fields. **The gateway declined it and counter-proposed one, and the
counter-proposal is better**; this section is now that shape.

```
x-sc-ext-commitment: sha256:<64 lower-case hex>
```

Algorithm-qualified, validated for syntax only, never interpreted, never dereferenced, attached to a
reserve-time record whose timestamp the gateway writes.

| what changed | why the one-field form wins |
|---|---|
| `ext_digest` → the header's value | the only one of the four that is already a digest, so the only one that does not collide with the gateway's own stated policy on caller-supplied text |
| `ext_uri`, `ext_media_type`, `ext_producer` → dropped | recoverable from the object this project owns. Our store is indexed by digest, so a hash lookup returns the pointer, the type and the producer. Asking the gateway to hold them is asking it to keep a second, verbatim, TTL-less copy of our index to save us one lookup |
| body fields → **HTTP headers** | settled in our favour, and for a reason rather than a preference: the request body is forwarded to the provider, so body fields either fail its validation or force field-stripping on the way out, which is a second place that knows the wire shape. Verified on the deployed gateway — 715 bytes of `x-sc-ext-*` traverse CloudFront and the load balancer, and a malformed correlation header alongside them returns `400` before any money is written |
| `sha256:` prefix added | `ext_digest` as we specified it pinned sha256 and lower-case hex without naming either, so a producer using a different digest would have been silently locked out of a field that looked generic |

**The cost of the one-field form, stated rather than buried:** after our retention passes the commitment
survives and the description of *what kind of thing* was committed does not, unless we keep it ourselves.
Section 2's N2 already separates the digest's lifetime from the bytes', so this is the same trade one field
earlier.

**Two corrections we accepted against our own filing.** `P-A1` asked for byte-identity on read and export;
transparency has to be defined over the **validated parsed value**, because the gateway's correlation-header
validator strips surrounding whitespace and intermediaries may normalise optional whitespace before
application code sees it. And a raw `ext_uri` would have contradicted a policy the gateway's decision store
states about itself — it already hashes caller-chosen session identifiers, on the reasoning that a tenant
may embed meaningful text in them and the log is a durable audit store. That sentence was about our case.

**Not requested:** any extension to the reject-reason enum, any per-producer field, any dereferencing, any
new table, any change to the money write path, any gateway-side attempt to verify that caller-supplied text
carries no secret. **Semantic no-leak stays on this side** — the gateway cannot check it; that is I5 and N3
here.

### 8.1 Why this is not yet buildable, and what blocks it

The gateway named two prerequisites and they are real, so this section is a contract and not a scheduled
change.

1. **There is no way to read the record back.** No read route, no export subcommand; the record's partition
   key appears in one module and its own unit test. All of A's value is realised at verification time, when
   someone fetches the gateway's record and compares its digest and timestamp against ours. Shipping the
   write path first is not a partial delivery, it is the defect.
2. **The record is not written on our own access pattern.** The decision record is emitted only when the
   gateway's routing produced candidate facts or a policy override acted. A caller that decides externally
   and pins a concrete model — which is exactly what a routing layer in front of it does — takes a path
   whose own comment says a hard pin normally has no multi-candidate decision facts. We would receive a
   `200` and no record. **This is a third collapse state that section 7's table does not model**, and it is
   not a dropped write a coverage rate would catch; it is a write never attempted.

## 9. Preconditions before this is turned on

- **The store exists and is not provisioned by this project.** The bucket, its IAM and its retention belong
  to the platform chart. tierbook code receives an endpoint and a prefix and knows neither the account nor
  the bucket name.
- **`enabled: true` with no backend configured must fail to start.** A missing setting and a deliberate
  `enabled: false` must not look alike, or every attachment disappears silently.
- **Backend chosen explicitly, not sniffed from the URI scheme.** Scheme dispatch is for readers. A writer
  that infers its destination from a string is a writer that quietly writes somewhere else when the string
  changes.
- **Write-once verified, or the degradation declared.** If the configured backend cannot refuse an
  overwrite, G3 drops to tamper-evident and the deployment records that it did.
- **The gateway's writer sizing re-checked.** A quorum multiplies decision writes; the gateway's writer runs
  two workers behind a bounded semaphore and drops on overflow. Drop rate is observable, so this is
  tunable after the fact — but it should be looked at before, not discovered from a coverage graph.
- **A measurement of the mechanism's own cost.** Borrowed from the profiling platform, which places one run
  with profiling disabled in the same index so the difference *is* the measured overhead. The analogue here
  is a mode that decides and records the pointer but writes no attachment. **It must not be applied to
  audited production spans** — measuring overhead by disabling the audit trail defeats the purpose.

## 10. Where the evidence stops

**Verified by reading the gateway's source:** the decision record is written at reserve and the outcome at
settle; the reject-reason enum has five members of which the pipeline emits two, the other three being
filtered before the record is built; `selection_reason` and `fallback_reason` exist in the schema and are
passed `None` at every call site; the correlation headers `x-sc-workflow-run-id` and `x-sc-group-id` are
client-suppliable while `span_id` is never trusted from a client; decision writes ride the routing-signals
table under distinct sort-key namespaces and carry no TTL.

**Verified by reading this project's source:** the equivalence predicate is fully specified in code
(`Answer:\s*\[?([A-Ja-j])\]?`, then a bare single letter, else none; agreement requires every member
parseable and identical) and is therefore pinnable. It is **defined only for multiple choice**.

**Not verified, and stated as unverified:** object-lock behaviour on the chosen backend; whether the
gateway's writer sizing survives quorum-multiplied writes; whether an alternative backend satisfies I2;
the drop-rate curve under load. None of these are guesses dressed as facts — they are the list of things to
measure before section 9 can be signed off.

**Answered by the gateway's owner, 2026-09-06.** The request was filed as
`/Users/akazawt/tmp/e02/sclv-issues/ISSUES.md` and answered in full. Three things it settled that this
document now rests on:

- **Q2 — there is no public schema for the ledger or its export.** No export route, no export subcommand, no
  `additionalProperties` declaration anywhere in the gateway repository. So no third-party consumer can hold
  a strict schema against these records, and the one compatibility risk this document left open **does not
  exist**. Its absence is load-bearing, which is why it is recorded here rather than left as a question.
- **Q3 — the `reasoningContent` leg set is open, so the unknown-member warning is not dead code.** Two
  members arrived unannounced while the answer was being written, one of them a usage key that was present on
  one call and absent from the next in the same script run. The check is a set difference against a declared
  known set, not an inference from "we emitted nothing".
- **Q1 — a client-side timeout or disconnect bounds neither the provider's work nor the charge**, and the
  gateway issues no cancellation on any transport. But the exposure *is* bounded, by the reservation rather
  than by our timeout: admission is priced from a byte-count bound over the payload, the provider cannot
  exceed the output cap in it, and an unobservable outcome keeps its reservation instead of being refunded.

**Nothing in section 8 has been run.** The one field is not implemented on either side, and 8.1 says what
blocks it. Of the four local patches the same file carried, **all four are now upstream** in the gateway's
v1.3.0 and v1.4.0 and this project carries none of them; they were never part of this contract.
