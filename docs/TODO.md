# What is not done, and what each item is blocked on

**tierbook is a META mechanism. Logic is INJECTED into it and is never built into it.**

What that forbids, concretely: a closed vocabulary that encodes *which* signals are worth using, a threshold that
came out of one corpus, a refusal derived from a finding rather than from the record in front of it. If a study
measured that some signal does not help, that is a **measurement to be recorded** -- not a list the mechanism
refuses against, because the next corpus may measure the opposite and must be able to say so.

**What every experiment in this repository was for.** Not to produce the routing rules. To find out **what kinds of
thing a general mechanism has to be able to hold** -- which conditions have to be recordable, which refusals are
structural rather than empirical, which fields a claim needs before it can be checked. The findings are the input to
that question and never the answer shipped as code.

**The test.** For anything in `src/`, ask: could a different study, on a different corpus, with a different
conclusion, express its own answer through this? If the mechanism has already decided, it is wrong, however well
the decision is supported here.

**Applied to this list:** an item that reads "decide which signals a gate may use" is misphrased. The mechanism's
job is to make a signal's evidence recordable and to refuse a claim the record cannot support. Which signals a
particular study then uses is that study's.


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

**The split is now declared (F132): none.** All 53 `Hyper-tau-bench` tasks are one set. The interval on 53 items is
already [0.361, 0.621] and halving it leaves 26 a side, which supports nothing. The cost is stated rather than hidden:
with no held-out fold, a policy selected by searching this suite is a point estimate with the selection named, never a
guarantee.

**What it has to carry.** The suite and its manifest digest (`OutcomeTable` already keys on one). The split, declared
before the first run. The item count and the sampling rule, with a seed, so a second run draws the same items. And the
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

### T10 -- CLOSED (F132). Withdrawn permanently, and the reason on the record was wrong

The shape **is** determinable and it is single-call, so the cache-prefix argument does not apply to this
measurement at all. What disqualifies it was in the same paragraph all along: it is a saving over **90 shared
items** against this repository's own floor of **150** for reporting a comparison. Not a gap waiting to be
filled -- the items do not exist to fill it with.

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

**The tenth part is DONE (F133):** `tool_extension` and `tool_trace`, with the veto matching on the occasion
(tool, trace prefix, arguments, credentials class, attempt) and graded by what the tool's contract promised.
`tierbook admit-traces` is the caller.

### T14 -- SETTLED (F132). No cohort identifier in the record

Grouping is enumerated per analysis. Chosen because a name that stays fixed while the thing under it moves is a
failure recorded twice here already, and a pre-registered manifest can name a cohort that does not exist.
**Revisit if an external audit is ever in scope** -- pre-registration is the only mechanism that shows something
was changed afterwards, and that argument is why the other option had support.

### T15 -- DONE (F126). The collector now records whose absence each hole is

Closed by F126: `ABSENCE_REASONS` with a total `ABSENCE_BLAMES` classification, `COLLECTION_STATUS`, a
`Manifest` whose claim the record can contradict, and `tierbook collect-harness` as the production caller
`harness.py` did not previously have.

### T18 -- NOT DOING (F132)

`decide.GAP_REASONS` stays unblamed. `observe.py` documents that an absent variable declines to certify, so both
readings of `uncollected_variable` land on the same conservative outcome; 14 references, no wrong answer among
them. **A message that already fails safe is not worth fourteen edits.**

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

**Blocked on.** Not blocked, and now **priced (F132)**: `K=8` repeats of both arms over 699 items costs about
**$24 and 23 minutes of GPU** -- 6.5% of a single Hyper-tau-bench pass. Below a ceiling of 0.15 the conclusion is that
nobody can predict uplift and the effort belongs on the difficulty side instead.

**This is the next thing to run.** Every expensive item below (T9, T3) exists to refine conclusions that stop
mattering if the ceiling is low, so the ordering is settled by the price.

## Known and unblocked

### T6 -- A channel for returning an action, upstream

The engine-side gate has no supported way to return "I should not answer this". It is worked around with a sentinel
string in the output, which costs several decode steps to say one bit and needs both sides to agree on a magic value --
no single rare token existed in a 248,320-entry vocabulary. The code states the replacement it wants.

**Done when.** The request is filed upstream with the three asks already named: an outcome observer, per-step scheduled
token counts, and a field on the response for an action.

### T7 -- DONE (F137). A fitted quantity carries its knob and its geometry

`quantity.Fit` with `GEOMETRIES`, `VARIANCE_REFERENCES`, `PERMUTATION_SCHEMES`, a `criterion.Null` rather than a bare
median, `void_because`, and `comparable_fits` refusing a difference in ridge, geometry or layer. There is no accessor
that makes the share a property of the model. Caller: `tierbook admit-fit`.

### T8 -- DONE (F134), and the premise was wrong

It said four parts had no collector, implying the rest did. **None did.** `collect_from_request` is the first one,
with `tierbook read-harness` as its caller. It found three defects in code already shipped, and the finding worth
carrying forward is that **a harness read from a request is identified by its instruction and nothing else** --
everything else in a body is a protocol value whose rendering into the prompt we do not hold.

**Not collected, and correctly so:** `loop`, `turn_budget`, `retry_policy` and `context_partitioning` are pushed by
the owner, and a request body has no place to put them. Their absence is the sender's, which the record now says.

### T9 -- Repeats, which the ledger says bound everything

Several conclusions rest on `n=1`. The ledger records that repeats are what bound a gate's cost and that a single run
leaves it unmeasurable. `Hyper-tau-bench` makes this concrete and expensive: roughly **15 hours and $370** per pass, so
a repeat there is a decision rather than a formality.

### T19 -- Telemetry conventions moved; decide what the observation reader should accept

**What.** The reason perigraph exists -- no shared shape for the records around a model call, so each collector's data
has to be translated by hand -- is still only half solved. Surveyed on 2026-11-12 (Japan time) against the repositories
themselves:

| convention | state | what it now carries | what it still does not |
|---|---|---|---|
| OpenTelemetry GenAI ([semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai) at `e6658f1`, 2026-11-06) | every attribute, span and event is `stability: development`; moved out of the core repository in semconv v1.42.0 | `gen_ai.evaluation.result` (name, score value, score label, explanation) | cost; a routing decision; a per-part content digest; a per-part sourcing mode |
| OpenInference ([Arize-ai/openinference](https://github.com/Arize-ai/openinference) at `715e299`, 2026-11-11) | no stability marking | a `DECISION` span kind (`spec/decision_spans.md`, naming Jev, OpenAI's Decisions API and vLLM Semantic Router Decision 1.0); `llm.cost.*` in USD; `evaluation.*` with `annotator_kind` | a per-part content digest; a per-part sourcing mode |
| OpenLLMetry ([traceloop/openllmetry](https://github.com/traceloop/openllmetry) at `e3d651a`, 2026-11-05) | follows OTel for the operation names | `traceloop.prompt.version_hash`, one digest for a whole prompt version | per-part digests; evaluation results; cost |

The two things perigraph adds (a digest per part, labelled with the boundary it is over, and a sourcing mode per part)
are in none of the three. Decision calls, cost and evaluation results now have a shape in OpenInference, but the three
name the same facts differently (`gen_ai.*`, `llm.*` / `evaluation.*`, `traceloop.*`), so a record from one is still
not a record from another.

**Why it matters.** tierbook defines its own observation format and refuses what does not fit it at the door, so none
of this breaks it. What it costs is reach: a deployment already exporting OpenInference `DECISION` spans and
`evaluation.*` results has to be converted by hand before tierbook can certify anything from it.

**What would tell us it is finished.** Either (a) an adapter that reads OpenInference `DECISION` spans with their
`evaluation.*` results into observations, refusing a span that lacks what an observation needs and saying which field,
with a test on a recorded span from each of the three decision APIs the spec names; or (b) a recorded decision not to,
with the reason. Re-survey the three conventions before starting; they moved within the last two months.

**Decision (2026-11-12, Japan time): (b) for now, with a trigger.** No experiment so far had spans; every one had a call
log or an observation writer, and the integration with Prismyra writes observations directly. Start (a) at the first
deployment that has `DECISION` spans and no call log. The adapter would only write observations: `check-observations`
is already the validator it has to pass.

### T20 -- Two writers on one looks ledger

**What.** `derive --ledger` appends one row per judgement and counts earlier looks by reading the file first. Two
`derive` runs against one ledger at the same moment can each count the other's look as absent. The documentation says
one writer at a time; nothing enforces it.

**What would tell us it is finished.** A lock (or an atomic append that re-reads under the lock), with a test that two
concurrent runs report looks 1 and 2, never 1 and 1. Not started because every run so far had one operator.

### T21 -- `drift` does not appear in the ledger

**What.** A `drift` re-derivation looks at fresh items, not the held-out half, so it is not a look at the certified
set. But a drift run whose fresh rows overlap a held-out set does look at it, and the ledger does not see that.

**What would tell us it is finished.** `drift --ledger` records the fresh items it judged and counts overlap with
earlier looks the same way `derive` does. Start when a deployment reuses certification items as drift traffic.

### T22 -- Which content digest a manifest uses is not declared

**What.** Overlap by content works when the observation id is `sha256:<content>` and the manifest's `content_sha256`
was computed the same way. Prismyra's writer digests `[context, question]` as compact JSON; another writer may digest
something else, and two digests of one item under two schemes never match, so an overlap goes unseen rather than being
refused.

**What would tell us it is finished.** A manifest and an observation file each name their content scheme as an opaque
string, and `derive` reports (never guesses) when a candidate's sets and its observations use different schemes, so
the check is listed as unchecked. Start at the second writer.

### T23 -- A feature builder's own version

**What.** Prismyra's artifact version names the feature module but not a version of it, so changing the builder's code
without renaming it keeps the version. The admission record and the certificate then cover a student whose features
changed.

**What would tell us it is finished.** Prismyra's side: the builder reports an opaque version and Prismyra folds it
into the artifact version. Nothing changes in tierbook, which compares the string. Start when a builder changes
in place, which a hidden-state builder that reads a backbone would.

### T24 -- Drift re-derives over the certified held-out half

**What.** `drift` re-derives from `--observations` plus the fresh rows, so it reads the held-out half again; the
ledger (T21) does not count that, and a re-derivation that changes the choice is reported as a change, not as a
second look. Seen in the phase-6 run, where drift was run over the certification observations.

**What would tell us it is finished.** Either drift judges fresh rows only against the deployed policy (no
re-derivation over held-out items), or the re-derivation is recorded in the ledger as a look. Decide with T21.

### T25 -- A policy whose certified arms only partly run on one Prismyra server

**What.** `export-policy --target prismyra-learn` now refuses any exported task type that `--signal` does not map to a
tag. A policy with one task type certified on a Prismyra student and another certified on an arm Prismyra cannot serve
(a metered API) therefore has no invocation that succeeds: leaving the second out is refused, mapping it is refused.

**Why it matters.** Before, the operator could leave the second task type out, and the export skipped it silently --
the same silence that lost a real certificate in the dbpedia_14 run. The refusal is the safer default; the gap is the
mixed policy. No run so far has had one.

**What would tell us it is finished.** A caller declaration with no default (for example
`--not-on-this-server TASK_TYPE`), listed in the export's `decisions` with its reason and refused when the same task
type is also in `--signal`, added when the first mixed policy appears. The vsr target's own signal check and this one
could then share one helper.

## Deliberately not doing

Recorded here so they are not rediscovered as gaps.

| Not doing | Why |
|---|---|
| Endpoint discovery, queue scoring, failover, model lifecycle | The routing layer already has them; re-implementing produces compatibility debt rather than value |
| Rates, reservations, the charge of record | The gateway owns money. If this repository held it, every "cannot decide" would stop a charge |
| Measuring quality for the operator | Mechanism here, application theirs. The gateway's own documents say the same and call the caveat correct design |
| A conversion between cost units | `tokens` to `usd` needs a price card and `tokens` to `gpu_seconds` needs load. An assumed coefficient once moved a published figure by a factor of six and changed which candidate was selected |
