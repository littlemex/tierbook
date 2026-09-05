<!-- Last updated: 2026-09-06 -->
<!-- Applies to: tierbook main. Gateway side: stratoclave main (requests not yet filed) -->

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

**G4. Separability.** "There was no attachment" and "the attachment is gone" are distinguishable, because
the digest's presence in the gateway record answers the first question without touching the store.

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

**N5. Not an agreement with the gateway.** This is a tierbook document. The gateway's side is a request
(section 8) and is **not yet filed**; until it is, every gateway-side statement here is a design intent.

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

**I5. No detail on the gateway.** The four fields of section 8 are the entire gateway-side footprint. A
future field carrying producer-specific meaning is a contract violation regardless of how convenient it is.

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

## 8. What the gateway is asked for (four fields, and no vocabulary)

The request is deliberately small, and the earlier version of this section was much larger. That version
asked for a namespaced reason registry so this project's reasons could live beside the gateway's five.
**The owner rejected it**: adding namespaces to a billing gateway is the wrong shape, and the gateway's
posture toward routing layers is that they should not need it to change. Externalising the detail removes
the request entirely — there is no place for producer-specific vocabulary, so the gateway cannot acquire a
tierbook shape even by accident.

| field | type | why every routing layer can fill it |
|---|---|---|
| `ext_uri` | bounded string, ASCII, ≤512 | any layer with somewhere to put detail can name it. The gateway never dereferences |
| `ext_digest` | sha256 hex, exactly 64 | a hash exists for any byte string, independent of meaning |
| `ext_media_type` | bounded string, ≤128 | an opaque label; the gateway does not interpret it |
| `ext_producer` | safe key token | every layer knows who it is |

**Not requested:** any extension to the reject-reason enum, any per-producer field, any dereferencing, any
new table, any change to the money write path. Syntax validation of `ext_uri` (length, character class) is
in scope for the gateway; **semantic no-leak is not**, because the gateway cannot check it — that is I5 and
N3 on this side.

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

**Nothing here has been run.** This contract is a design; the four fields are not implemented on either
side. The request in section 8 is **drafted but not sent** — its text is
`/Users/akazawt/tmp/e02/sclv-issues/ISSUES.md`, request A, where the four fields appear with numbered
acceptance properties and the compatibility question this document leaves open (whether a public export
schema exists) is raised as Q2. The same file carries four unrelated fixes this project runs as local
patches against the gateway; those are not part of this contract.
