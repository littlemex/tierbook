# Surround: a protocol for what is around the model

> **Superseded, and kept as the record of how the design was reached.** The protocol shipped as **perigraph**
> (περί around + γραφή record) at `github.com/littlemex/perigraph`, and its `spec/vocabularies.json` is normative
> rather than anything here. The name `Surround` was dropped for the reason the reviewers gave for rejecting
> `harness.*`: it is a generic English word with an established meaning elsewhere. What this document is still good
> for is **why** each rule exists, and what was tried and refuted first.

**Status.** Design, revised once after review by two models. Nothing here is implemented. The name is provisional and
exists so the two sides of the boundary can be talked about without saying "the harness thing" -- not as a claim to a
standard.

**Name.** **Surround**, from `harness.py`'s own first sentence: *what surrounds the model*. The wire namespace is
**`surround.*`**. Not `harness.*`: both reviewers rejected that independently, and the reason is right -- `harness` is
a generic word, and putting it beside OTel's `gen_ai.*` implies ownership of a sibling namespace that nobody
registered. One name on the wire and on the page.

Surround does not invent a format. It is four borrowed pieces and two additions, established by surveying eight
specifications (F124):

| Role | Borrowed from |
|---|---|
| Attribute names, carriage, and zero-code injection | OTel GenAI (covers 6 of the 10 parts) |
| Naming a subject by a content digest | in-toto (`ResourceDescriptor`) |
| Separating "who said this" from "is this true" | SCITT (RFC 9943) |
| Saying what a record does **not** cover | C2PA 2.1 |
| **Addition 1**: a per-part content digest, labelled with the boundary it is over | Nothing surveyed carries one |
| **Addition 2**: a per-part sourcing mode | Nothing surveyed carries one |

## The rule this design turns on

The first version of this document said "collection never refuses; the judge refuses". Both reviewers rejected that
sentence, and they were right, because it conflates two refusals that have nothing to do with each other:

> **Execution never refuses because of collection. A record may still be refused as a record.**

The distinction matters because **the two refusals are about different objects**:

* Toward the **sender**, the collector is maximally permissive. Any part may be absent, in any combination, and the
  record is still valid. This is the flexibility the protocol exists to allow: a sender that supplies one part gets a
  usable record, not an error.
* About **itself**, the collector must be exact. A record must say whether it is complete, and a collector that
  failed must not be able to present its failure as the sender's silence.

**The defect that forced this.** A collector cannot record its own absence. If the shim is not injected, does not
recognise a renamed SDK field, or dies before export, there is no record saying `unrecorded` -- there is no record.
And a subtler form, which is the one that would actually have shipped: shim version N+1 loses the ability to read
`decoding`, writes the same absence reason it writes when the sender genuinely sent no decoding settings, and every
consumer then behaves exactly as designed while the regression stays invisible. A closed vocabulary constrains
spelling, not truth.

So four things are required, and they are the minimum that makes an absence checkable rather than merely spelled:

1. **An envelope created before any part is extracted**, carrying a terminal status: `complete`, `aborted`,
   `collector_failed`. A record whose status is not `complete` is inadmissible to the judge and still fully usable to
   the log.
2. **Absence reasons that say whose absence it is.** `not_provided` (the sender sent nothing), `not_reachable` (this
   shim, in this environment, cannot see it), `extraction_failed` (it was there and we failed), `redacted`,
   `not_observable` (structural -- nobody can see it). The first version had one undifferentiated hole, and the
   measurement failure and the sender's silence collapsed into it.
3. **A capability manifest**: the shim version and the part set it claims it can reach here. Then `not_reachable`
   becomes checkable, and a manifest that claims a part the record reports absent is a contradiction rather than a
   fact. This is SCITT's own separation -- who said this, against is this true -- applied to the collector instead of
   only to the sender, which the first version failed to do.
4. **A contradiction mark**, emitted at collection time when an observed fact and a `pushed_by_owner` claim disagree
   inside one record. The owner pushes `turn_budget: 5` and the transcript shows nine turns: both facts are in one
   hand at that moment, and deferring the join discards it for free.

The precedent for the permissive half is measured, not preferred. Strict pairing of `cost_usd` with `price_basis`
broke roughly 30 existing call sites; reverting to the existing `gaps` channel with one new reason cost zero churn
and lost no information. The gap is visible either way, and only one of the two ways lets the run finish.

## The question this design had to answer

*Must the information a log needs and the information routing needs be the same set?*

**No, and they cannot be, for a structural reason.** Routing decides *before* the call. A trajectory exists only
*after* it. No protocol moves a fact backwards through that.

The axis is already in the code and was built for this question -- `quantity.AVAILABILITY`:

```
("before_prefill", "during_compute", "after_prefill", "after_generation")
```

with `Quantity.usable_before_generating()` derived from the axis's order rather than from a list of the good values,
because the first version of that predicate excluded `during_compute` and thereby reported this study's own readout
as useless to its own gate.

*Can routing proceed on only part of the record?* **Yes, and it must be able to** -- because the cost of being wrong
is not the same for the four consumers:

| Consumer | Reads | When | Cost of being wrong | Therefore |
|---|---|---|---|---|
| **Route** | the parts present at decision time | `before_prefill` | one avoidable escalation -- bounded, priced, recoverable on the next call | proceeds on a partial record; falls back to a declared default |
| **Log / trajectory** | everything, in order, raw | all four stages | a hole found later | never refuses; records absence with a reason and a status |
| **Judge / compare** | identity, which needs digests, plus assignment provenance | after the fact | a published false claim -- unbounded, not recoverable | refuses, and names the parts it could not witness |
| **Replay** | payloads, not digests; runnable tool versions | after the fact | a reproduction that silently is not one | out of scope, named so the log is not quietly given its requirements |

**One strictness level for all four is wrong in both directions.** Strict enough for a verdict and routing stops
serving traffic whenever a part is missing -- which is most of the time, since four of the eight existing parts have
no collector (T8). Loose enough for routing and a verdict gets published on a partial record, which is the failure
F124 withdrew a number for.

The fourth consumer is a review finding: both reviewers named the replayer, and its bar is genuinely distinct -- it
needs bytes where the judge needs digests, and it refuses on missing payloads rather than on missing identity. Naming
it is the whole action for now. The mistake it prevents is folding its requirements into the log because the log
happens to be the component that stores things.

## The routing decision is not part of the surround, and the judge needs it anyway

**This was the fatal finding, and the reviewers split on the fix.** Both saw the leak; only one got the object right.

The leak: two runs identical on every identifying part, where run A's shim reached `context_partitioning` and run B's
did not. The router falls back for B and sends it somewhere else. The judge compares them as the same surround --
because nothing it keys identity on differs -- and publishes a delta that is an artefact of *missingness*,
systematically correlated with whichever side has the weaker shim.

One reviewer proposed making the routing decision a tenth harness part keyed into identity. **That is wrong, and the
other reviewer said why**: the routing decision is not something around the model, it is the *treatment assignment*.
Keying it into harness identity would make two runs of the same harness sent to different destinations count as
different harnesses, which destroys exactly the grouping the identifier exists to provide. And the confounding is not
removed by recording the fallback: missingness affected which model was tried, how many attempts ran, what context
accumulated, and what it cost. Adaptive escalation then loads the harder requests into the later tiers, so judging
only the final attempt hides the cheap model's failures while keeping some of their cost.

So it is a separate object with a separate name -- **assignment provenance** -- mandatory for the judge, invisible to
the router's own bar. Per attempt: the policy digest, the facts consulted **and their missingness**, the fallback
applied, the destination chosen, the attempt number and its parent, the termination reason, and the selection
probability when the choice was randomised.

The judge may then compare runs with equivalent assignment conditions, evaluate the policy as a whole including the
attempts that failed, and **refuse a model-against-model claim when assignment depended on state nobody recorded**.
The router's admission bar does not move at all.

## What is takeable: ten parts

The eight in `harness.HARNESS_PARTS`, plus the context-partitioning policy that Local Fusion's entire reported saving
lives in (T13), with `tool_behaviour` split in two. Ten, not nine -- the first version of this document said nine and
listed ten, which is the kind of error that makes a collector unable to enumerate its own absences.

| Part | Best sourcing | Route | Log | Identity |
|---|---|---|---|---|
| `instruction` | `in_the_request` | yes | yes | yes |
| `tool_schemas` | `in_the_request` | yes | yes | yes |
| `readout` | `in_the_request` | yes | yes | yes |
| `decoding` | `in_the_request` | yes | yes | yes |
| `loop` | `pushed_by_owner` | as a hint | yes | no |
| `turn_budget` | `pushed_by_owner` | as a hint | yes | no |
| `retry_policy` | `pushed_by_owner` | no | yes | no |
| `context_partitioning` (new, T13) | `pushed_by_owner` | as a hint | yes | no |
| `tool_extension` (was `tool_behaviour`) | `not_observable` | no | no | no |
| `tool_trace` (new) | `in_the_request`, after the fact | no | yes | no -- veto only |

A hint is not free: `loop` and `turn_budget` are pushed, so a sender can push values that buy cheaper routing.
Assignment provenance is what makes that auditable afterwards, since it records which facts the decision consulted.

### The correction: `tool_behaviour -> not_observable` was too strong

`harness.py` classifies `tool_behaviour` as `not_observable` on the grounds that a tool's schema is in the request
and its implementation is not. True of the tool as a *function*; false of the tool *restricted to the inputs actually
exercised*, and those are bytes the run itself produced -- the strongest mode in the vocabulary, held here, and
contemporaneous. Throwing them away is throwing away held evidence.

* `tool_extension` -- the function. Stays `not_observable`, stays non-identifying.
* `tool_trace` -- the ordered call records. **May never key an identity**: a per-run outcome is unique per run, and
  keying on it would make every pair of runs incomparable, which is the defect the identifier split was introduced to
  fix. It is also **not always collectable** -- a client-side shim cannot see tools a server-side agent, a browser or
  a provider-managed runner executed -- so it takes the same absence model as every other part.

### The veto, restated, because the first version was unsound

The first version said: equal arguments and unequal response digests prove two runs used different tools. Both
reviewers refuted it, and between them listed more than a dozen ways the condition holds with the tool unchanged. The
three that decide the design:

1. **It could fire against a single run.** Write key `k`, then read `k`: equal arguments, unequal responses, one run,
   one tool. The rule said "some call has equal arguments" and never used the ordering it had already collected.
2. **It fires on essentially every networked tool.** Response bodies carry request ids, timestamps and trace
   headers, and the design refuses canonicalisation, so any two runs touching such a tool veto each other. An
   always-firing veto means the judge can never publish for any harness with a real tool -- the pathway destroys
   itself.
3. **The conclusion was false even when firing is right.** A live search, a clock, a moved index: the environments
   diverged and blocking the comparison is correct, but "different tools, proven" is not what was observed.

So:

> **Equal effective invocation context and an unequal stable projection of the response establish a divergence in
> recorded execution** -- for that invocation, and for nothing else.

`effective invocation context` is the trace prefix up to that call, the arguments, the credentials class, and the
attempt number. The projection is over the response **as rendered to the model**, which is consistent with the
canonicalisation rule for the same reason: those are the bytes that mattered.

And the strength is graded rather than absolute:

* **Automatic veto** only where the tool's contract declares determinism over the recorded context.
* **Widen to unknown** for a mutable or stochastic tool -- the comparison is not authorised and not refused.
* **No veto** for a known-volatile response field or a capture-layer difference.

One-sidedness is still right, and one of the review's own cases proves it: two serialisations of the same logical
arguments make the arguments compare unequal, so the veto misses a genuine difference. That miss is safe **only**
because the rule can refuse and can never authorise. Agreement on the exercised inputs says nothing about the inputs
neither run touched.

## Three boundaries, so a digest says what it is a digest of

The reviewers agreed the canonicalisation refusal is correct and that it is not sufficient, because three different
things were being called "the bytes":

| Boundary | Digest supports |
|---|---|
| `transport` | what an SDK put on the wire |
| `parsed` | the protocol value after decoding |
| `model_visible` | the exact text the model read |

**Only a `model_visible` digest may support a claim that two runs had the same input.** A canonical digest is
permitted as an *index* -- it may narrow candidates and may never authorise a comparison, the same one-sided shape as
the veto. Two SDK versions can serialise differently and decode to an identical model-visible string; two strings
that canonicalise to one JSON value can behave differently when embedded verbatim in a prompt. Both directions are
wrong if the boundary is not labelled.

## What the collector deliberately does not do

| Not doing | Why |
|---|---|
| Canonicalise bytes the model reads | The model reads a string, not a meaning. Canonicalisation gives two behaviourally different strings one digest, reintroducing the failure in the unsafe direction. |
| Hash the payload after transmission | That hashes something other than what was sent. |
| Commit the record to a cohort identifier | Open: T14. The reviewers split and this design does not pretend they agreed. |
| Promise a comparison policy cannot be loosened | What is reachable is *undeniable* loosening, which converts a false guarantee into an auditable admission. Worth having, not worth calling a guarantee. |
| Distributional testing of stochastic tools | Named by review, not earned yet: no experiment here has been blocked by it. Recorded so it is not rediscovered as a gap. |

## Injection, concretely

Zero code change on either side decides whether this is usable at all, and it is the one property already solved by
something else: OTel auto-instrumentation. The sender sets an environment variable; the shim wraps the client.

What the shim adds over stock GenAI instrumentation is only the additions: it digests each part it can reach, labels
the boundary that digest is over, stamps each part with its sourcing mode, and emits its own capability manifest and
terminal status. All of it lands as attributes on a span that would have been emitted anyway.

## Done when

* A run that can reach only `instruction` produces a record, routes, and reports the other nine parts absent with a
  reason that distinguishes the sender's silence from this shim's blindness.
* A verdict over that same record refuses, and names the parts it could not witness.
* A record whose envelope says `collector_failed` is admissible to the log and refused by the judge.
* A manifest claiming a part that the record reports `not_reachable` is a contradiction, not a fact.
* Two runs whose traces diverge at the same prefix with the same arguments cannot be compared, without anybody
  declaring a version -- and two runs of a stochastic tool are neither compared nor refused, but marked unknown.
* A model-against-model claim is refused when the assignment depended on state nobody recorded.
* A sender emits a surround record without editing its own source.
