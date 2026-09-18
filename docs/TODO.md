# What is not done, and what each item is blocked on

One place for work that is known and not started. An item here names what it is, why it matters, and **what would tell
us it is finished** -- an entry that cannot say the last of those is a wish rather than a task.

Ordered by whether something outside this repository has to happen first, because that decides what can be picked up
today.

## Registered by request

### T1 -- Choose the benchmark, and its sampling, from a configuration file

**What.** Which benchmark a run measures against, and how items are drawn from it, are currently decisions made in the
code and in scratch scripts. They should be a declaration a reviewer can read: the suite, the split, the number of
items, the sampling rule, and the seed.

**Why it matters, from this repository's own record.** Two comparisons in the ledger were invalidated by exactly this.
One compared 410 items against 90 and nearly produced a verdict; the fix was to intersect on question id and withhold
below 150 shared items. Another reported a saving of 7.9% that fell to **1.0%** once restricted to the same items --
the numbers were properties of the sample, not of the readout. A sampling rule in a file is checkable before a run; a
sampling rule in a script is discovered afterwards.

**What it has to carry.** The suite and its manifest digest (`OutcomeTable` already keys on one). The split, declared
before the first run -- `Hyper-tau-bench` has **no official split**, so for that suite the split is ours and has to be
written down. The item count and the sampling rule, with a seed, so a second run draws the same items. And the
intersection rule for a comparison, which is currently enforced in the harness rather than declared.

**Done when.** A run cannot start without one of these, two runs of the same file draw the same items, and a comparison
across two different files is refused rather than performed.

**Blocked on.** Nothing.

### T2 -- The infrastructure dependency on `distributed-ai`, and where the responsibility divides

**What.** GPU work in this project has gone through `distributed-ai` (cluster creation, image building, the EKS
manifests). What is actually depended on, and which side owns each piece, is not written down anywhere.

**Why it matters.** The line matters more than the list. This repository has a standing rule that it supplies mechanism
and the operator supplies application, and it has held that line against the router (endpoint discovery, queue scoring,
failover) and against the gateway (rates, reservations, the charge of record). The same line has never been drawn
against the infrastructure, so it is the one place where "we should also do X" has no answer.

**What the investigation has to produce.** An inventory of what is used, separated into: what this repository calls,
what it only reads, and what an operator does by hand. And for each, which side is expected to keep it working. The
questions that are actually open: does a tierbook measurement assume a cluster shape, does it assume an image, and can
somebody reproduce a recorded number without that repository at all.

**Done when.** A reader can tell, per item, which repository breaks if it changes -- and any measurement that cannot be
reproduced without `distributed-ai` says so in its own record rather than in somebody's memory.

**Blocked on.** Nothing.

### T10 -- Republish the routing saving as an interval, or leave it withdrawn

The 1.0% figure is withdrawn (F124). Replacing it needs both arms re-accounted at conversation scope on the
price card's four legs plus the observed cache hit rate. **If the run's shape was not recorded -- single calls
against multi-turn sequences -- there may be no defensible replacement**, and leaving it withdrawn is then the
correct end state rather than a gap.

**Done when.** Either an interval is published with the accounting scope stated, or the ledger says plainly
that the measurement cannot be reconstructed.

### T11 -- DONE (F129). The cost model expresses its own price card

`BILLED_LEGS` with `Spend.cached_in` / `Spend.cache_write` as an all-or-nothing pair, `fresh_in` derived, and
`refuse_mixed_cache` reaching `compare` through `Run.spend_per_item`. Not built: `cache_hit_rate_observed` and
`reusable_cache_tokens` as fields on a `Spend` -- they are properties of a tier's price card rather than of one
request's cost, and no experiment has needed them on the cost object.

### T12 -- DONE (F130) for the recordable half. The counterfactual half is T13

`spend.Conversation` with a total over the sequence, the arithmetic invariant that a context's first turn cannot
have been served from its own cache, `paid_for_nothing` reported rather than refused, and
`refuse_incomparable_shapes` so two sequences of different length are not compared as two prices for one thing.
Production caller `tierbook conversation-cost`.

**Still open and moved to T13:** the counterfactual needs to know how many contexts exist and what crosses
between them. The shape is now recordable; the alternative is not computable.

### T13 -- DONE (F131). `context_partitioning` is the ninth part, and it is priced

`HARNESS_PARTS` now has nine, with `Partitioning(contexts, crosses)` in `spend.py` and
`refuse_undefined_counterfactual`. Counting contexts is not enough: `briefs_and_results` keeps both caches warm
and `whole_history` re-bills the prefix as fresh input, and they differ in sign.

**Still open:** the tenth part. `tool_behaviour` is to be split into `tool_extension` (unobservable, as now) and
`tool_trace` (collected, never identifying, veto only), per
[DESIGN-surround-protocol.md](DESIGN-surround-protocol.md). The veto's restated form is designed and unbuilt.

### T14 -- Settle the one question the reviewers split on

Pre-registered signed cohort manifest, or no cohort digest in the record with grouping enumerated per
analysis. Both reviewers concede the full design only made tuning loud rather than impossible, so this is a
choice about where the loudness lives.

### T15 -- DONE (F126). The collector now records whose absence each hole is

Closed by F126: `ABSENCE_REASONS` with a total `ABSENCE_BLAMES` classification, `COLLECTION_STATUS`, a
`Manifest` whose claim the record can contradict, and `tierbook collect-harness` as the production caller
`harness.py` did not previously have.

### T18 -- Blame the four gap reasons the same way

`decide.GAP_REASONS` has four entries and none says whose absence it is, and `uncollected_variable` carries
the identical ambiguity F126 closed: "the state did not carry it" against "we failed to collect it".

**Not urgent, and the reason is on the record.** `observe.py` documents that an absent variable becomes
`uncollected_variable` and the decision declines to certify, so both readings produce the same conservative
outcome. Fourteen references, no wrong answer among them.

**Done when.** Either each gap reason is blamed, or this entry says plainly that a message which already
fails safe is not worth fourteen edits.

### T16 -- DONE (F127). A comparison whose arms were missing different facts is refused

Closed much smaller than designed: `record.Decision` and `escalate.Escalation` already carried almost every
field the design listed, and missingness already travelled through the existing `gaps` channel. **What was
missing was the refusal**, now `counterfactual.refuse_differential_missingness`, called from `compare()` and
exposed as `tierbook admit-comparison`.

### T17 -- DONE (F128). A digest says which of three things it is over

`DIGEST_BOUNDARIES` with `Part.boundary`, defaulting to `model_visible` because that is the true statement
about every existing caller. The remaining half -- a canonical digest that may narrow a candidate set while
being unable to authorise a comparison -- is **not built**, because no experiment has needed to group by one
yet. It is the index half of F125's design and stays out until something asks for it.

## Blocked on something outside this repository

### T3 -- Cost in GPU-seconds rather than tokens

Tokens are a weak proxy. A policy ahead in tokens can lose in GPU-seconds, because a token count does not see KV-cache
occupancy or what a long trace does to every other request sharing the batch. `spend.py` can already represent
`gpu_seconds` and refuses to convert into it, which is the honest state; nothing has measured one.

**Blocked on.** Load. This needs concurrent traffic against a real engine, and it cannot be obtained by running more
items serially.

### T4 -- Measure Jev rather than only representing it

The interface is implemented: a schema-constrained readout whose unparsed share is zero by construction, and a
`Confidence` that refuses to be read as a probability until somebody bins it here.

**Blocked on.** Early access. The API is behind a waitlist, so no number about it can enter the ledger.

### T5 -- The uplift signal

Routing turns on `P(strong correct) - P(box correct)`. The second term is measurable from the box's own state; **nothing
predicts the first**, and a confidence the box returns is another estimator of the second. This is the one gap that
would change what routing is worth.

**Blocked on.** Not blocked, but the ledger's own next step is to measure the **reliability ceiling** of an uplift label
first (`K=8` re-runs, split-half, `r_max = sqrt(rho)`): below 0.15 the conclusion is that nobody can predict uplift and
the effort belongs on the difficulty side instead. Measuring the ceiling is cheaper than another predictor.

## Known and unblocked

### T6 -- A channel for returning an action, upstream

The engine-side gate has no supported way to return "I should not answer this". It is worked around with a sentinel
string in the output, which costs several decode steps to say one bit and needs both sides to agree on a magic value --
no single rare token existed in a 248,320-entry vocabulary. The code states the replacement it wants.

**Done when.** The request is filed upstream with the three asks already named: an outcome observer, per-step scheduled
token counts, and a field on the response for an action.

### T7 -- The remaining shape the ledger names three times

`F16` asks a fitted quantity to carry its hyper-parameters and the geometry it was computed in. `F22` asks a recorded
effect to say whether it is one setting or a sweep, with the control's value beside it. The second is largely
discharged by `OperatingPoint` (`fixed` against `integrated`) and `Baseline`; the first is not built.

### T8 -- Harness parts that are declared and not yet collected

`harness.py` names eight parts and classifies how each can be reached. Four of them -- `turn_budget`, `retry_policy`,
`readout`, `decoding` -- have no collector, so a real record reports them as unrecorded. The vocabulary exists so that
absence is visible; closing it means writing the collectors.

### T9 -- Repeats, which the ledger says bound everything

Several conclusions rest on `n=1`. The ledger records that repeats are what bound a gate's cost and that a single run
leaves it unmeasurable. `Hyper-tau-bench` makes this concrete and expensive: roughly **15 hours and $370** per pass, so
a repeat there is a decision rather than a formality.

## Deliberately not doing

Recorded here so they are not rediscovered as gaps.

| Not doing | Why |
|---|---|
| Endpoint discovery, queue scoring, failover, model lifecycle | The routing layer already has them; re-implementing produces compatibility debt rather than value |
| Rates, reservations, the charge of record | The gateway owns money. If this repository held it, every "cannot decide" would stop a charge |
| Measuring quality for the operator | Mechanism here, application theirs. The gateway's own documents say the same and call the caveat correct design |
| A conversion between cost units | `tokens` to `usd` needs a price card and `tokens` to `gpu_seconds` needs load. An assumed coefficient once moved a published figure by a factor of six and changed which candidate was selected |
