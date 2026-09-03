# Agreement among cheap candidates is a better escalation signal than the box's own doubt, and it is the only part of the terse-decision idea that survived

**Written 2026-09-01**, after two reviews and five measurements taken the same day on the existing matrix at no
cost. It answers two questions that were asked together: how to strengthen the cheap tier as a measured
experiment, and whether the frontier model can be reserved for genuinely-high-intelligence decisions with terse
input and output while everything else is done by the box and mid-priced APIs.

The second question has a sharp answer and it is negative: a terse frontier *decision* is not worth buying, and
a terse frontier *answer* on fewer items is. The measurement that killed the first half is section 3, and it only
died on the frozen fold after looking significant on the first one.

## 1. Terse input and output is not where the saving is

The frontier tiers on this corpus spend most of their bill on *output*, but they do not emit much of it: the
median `claude-opus-5` answer is 297 prompt tokens and 63 completion tokens. **Asking for one letter does not
make the reply short**, because reasoning tokens are billed as output and the model spends them whether or not
the answer is one character: measured over 257 hard items, a decision prompt that invites the model to work the
answer out costs $0.01329 against $0.00870 for the same tier answering the same items normally — **53% more, not
less**. The benchmark's 63-token median came from an instruction that suppresses reasoning, and reproducing that
instruction brings the decision down to $0.01052, still dearer than answering.

Showing it only the candidates' letters and not the question would be cheap, but that is weighted voting, and
voting over all nine candidates reaches 89.1% against `claude-opus-5`'s own 89.6%. Counting is not deciding.

**The saving has to come from calling it less often, not from calling it more cheaply.** That reframes the
question as: what is a reliable, cheap certificate that the frontier model is not needed?

## 2. The certificate is agreement, and it beats the incumbent signal at equal cost

Measured over the 1,165 items left after removing the 22 items whose answer key is confirmed wrong
(see [`results-label-audit.md`](results-label-audit.md)):

| cheap pool that answers first | they agree on | accuracy when they agree | ceiling with a perfect arbiter | cost per item |
|---|---|---|---|---|
| `claude-opus-5` answering everything (reference) | — | — | 91.2% | $0.00617 |
| box + `nemotron-super-3-120b` + `qwen3-next-80b` | 47% | **89.7%** | **91.0%** | **$0.00165** |
| box + `grok-4.6` | 66% | 94.4% | 93.6% | $0.00406 |
| those three plus `claude-sonnet-5` | 42% | **97.2%** | 95.4% | $0.00462 |

**When three cheap candidates give the same answer, that answer is right 89.7% of the time — as often as the
frontier model is right on the whole corpus, at a quarter of the price.** Add `claude-sonnet-5` and unanimity
among four is right 97.2% of the time, which is well above anything a single candidate achieves.

The ceiling column is what a *perfect* arbiter would reach on the escalated remainder. It is quoted as a bound
only: section 3 measures a real arbiter and finds it worth nothing, so the operative policy escalates and lets the
dear tier answer.

And the comparison that matters, because the incumbent router rests entirely on the box's own prefill
uncertainty. Escalating to `claude-opus-5` when the box's answer-letter entropy is high, against escalating when
three cheap candidates disagree:

| policy | escalated | accuracy | cost per item |
|---|---|---|---|
| probe threshold at the median | 50% | 85.2% | $0.00454 |
| probe threshold at the 40th percentile | 60% | 87.3% | $0.00509 |
| **three cheap candidates disagree** | **53%** | **87.9%** | **$0.00488** |

**The quorum dominates the probe**: more accurate than the probe router that escalates 60% of items, and cheaper
than it. The box's own doubt says "I do not know"; it carries no information about whether anyone else knows,
which is exactly the mechanism reason a probe reads "everyone can do this" at 0.83 and "nobody can do this" at
0.51. Three independent opinions answer a different question, and it is the one the router needs.

**The three cheap candidates cost $0.00068 for all three.** Running them on every item is 14% of one
`claude-opus-5` call, so there is no cascade to design inside the quorum — buy all three opinions always.

## 3. Arbitration is dead: the calibration fold's effect did not survive the frozen fold

**The registered single evaluation, run on the frozen fold's 338 escalated items:** the arbiter scores 88.5%
against 88.2% for the same tier answering the same items — 9 wins, 8 losses, exact two-sided p = 1.0000. The
calibration fold's +3.5 points at p = 0.035 **did not replicate at all**, and the mid-priced arbiter's apparent
parity reversed in the same way.

| policy over the 687 clean frozen-fold items | accuracy | cost per item | against the frontier tier |
|---|---|---|---|
| `claude-opus-5` answers everything | 92.4% | $0.00593 | — |
| **quorum, then `claude-opus-5` answers the 49% it escalates** | **89.2%** | **$0.00441** | **−26%** |
| quorum, then `claude-opus-5` arbitrates | 89.4% | $0.00657 | +11% |
| quorum, then `claude-sonnet-5` arbitrates | 85.9% – 86.6% | $0.00295 | −50% |

**So the answer to "reserve the expensive model for a terse high-intelligence decision" is no, on this pool.**
Showing the frontier tier three candidate answers changes nothing it does — two points and a tenth on 338 items,
at 57% more money because thinking tokens are billed as output. What pays is not asking it at all: the quorum
stops on half the items and the tier that does get asked simply answers.

**Two effects that looked real on one fold both vanished on the next**, and they vanished in opposite directions:
the frontier arbiter's gain evaporated, the mid-priced arbiter's parity became a 3-point loss. The reason is
visible in the noise floor measured earlier — these tiers flip 3.6% and 5.1% of their answers between identical
runs, which is the same size as the effects being chased. **A single fold cannot see a 3-point effect here, and
the pre-registration is the only reason this was caught rather than shipped.**

What survives is section 2's stopping rule, and it survives well: **89.2% at 74% of the frontier tier's cost.**

The rest of this section is what the calibration fold showed and how it failed, kept because the failure is the
finding.

### What the calibration fold showed

**Experiment A, run.** On the 257 escalated items of the calibration fold, the arbiter saw the question and the
cheap candidates' letters — unlabelled, order-randomised, free to pick a letter nobody offered — and emitted one
answer. The registered bar was to beat the same tier simply answering those items, which scores 82.9%.

| arbiter | accuracy on the escalated items | wins / losses against answering | cost per escalated item |
|---|---|---|---|
| `claude-opus-5`, invited to reason | **86.4%** | 12 / 3, exact p = 0.035 | $0.01329 |
| `claude-opus-5`, terse instruction | 85.2% | 8 / 2, p = 0.11 | $0.01052 |
| the same tier answering, no proposals | 82.9% | — | $0.00870 |
| a perfect chooser among the proposals | 74.7% | — | — |
| a perfect chooser allowed its own answer too | 90.7% | — | — |

**The anchoring risk did not materialise.** Seeing three answers, mostly wrong, made the frontier tier *better*
than answering unaided, by 3.5 points with a paired p of 0.035. It stayed inside the proposals on 82% of items,
and the 74.7% ceiling for choosing only among proposals confirms that the gain comes from being allowed to
override all three.

**None of that replicated.** It is recorded because the shape of the mistake is instructive: a paired test at
p = 0.035 on 257 items, with a mechanism story that fit ("it is allowed to override all three"), and it was
noise. On the frozen fold the same wording, same tier, same quorum gives 9 wins and 8 losses.

**And the whole policy was already unfavourable even taking the calibration numbers at face value:**

| policy over the 478 clean calibration items | accuracy | cost per item | against the frontier tier |
|---|---|---|---|
| `claude-opus-5` answers everything | 89.5% | $0.00652 | — |
| quorum, then `claude-opus-5` answers the 54% it escalates | 86.0% | $0.00540 | −17% |
| quorum, then `claude-opus-5` arbitrates, terse | 87.2% | $0.00638 | −2% |
| quorum, then `claude-opus-5` arbitrates, reasoning | 87.9% | $0.00787 | **+21%** |
| **quorum, then `claude-sonnet-5` arbitrates, reasoning** | **85.1% – 86.8%** | **$0.00232** | **−64%** |

**So the answer to "use the expensive model only for the genuinely hard decision" is yes, and the decider should
not be the expensive model.** A mid-priced arbiter reaches the same accuracy as escalating to the frontier tier
and letting it answer, for a third of that policy's cost and just over a third of the frontier tier's. The
frontier tier's role on this pool at these prices collapses to nothing: it buys 2.7 to 4.4 accuracy points for
2.8 times the money.

The `claude-sonnet-5` figure is a range because 8 of its 257 replies came back as an **empty stream** — content
of zero length with no finish reason — which is the same gateway defect this design ranks as the first piece of
work. The range's floor scores those 8 as wrong and its ceiling as right.

**Two gateway defects were found by running this**, both recorded because they distort measurement rather than
merely annoy:

- A reply truncated at the token limit returns **empty content and is billed in full**. Before this was noticed,
  36% of one arm's replies were empty and the arm appeared to score 60.7%. An experiment that does not record
  `finish_reason` cannot see this.
- The streaming path **emits no usage block** even when `stream_options.include_usage` is set, so a streamed call
  cannot be costed from its own response. The rows affected here are priced at the arm's median instead.

## 4. Abstention: the tail is four different things and only one of them is routing

The 51 items nobody solves carry 54.8% of the cascade bill. Both reviews independently said not to build a
detector for them, and the audit says why: the tail is a confluence of mechanisms, not a class.

| what it is | items | what removes it |
|---|---|---|
| the answer key is wrong | 22 confirmed | a hand audit, triggered by unanimous disagreement with the key |
| the same question appears twice | 10 redundant | deduplication on normalised question text |
| the question has two correct answers | 1 confirmed | widening the key |
| genuinely unanswerable by this pool | 29 | an abstention rule — **this** is the routing problem |

**The detector for the first row already exists and is free.** Every candidate agreeing while the verifier says
they are all wrong fired on exactly 19 items over the whole corpus and all 19 were bad keys, with no false
positives. In a tenant this generalises without change: unanimity against a verifier's rejection is evidence
about the verifier. It does not treat a prediction as evidence of correctness — its output is "a human should
look at these".

For the 29 that remain, neither review recommends a classifier, and both propose the same shape:

- **Deterministic pre-flight first.** Input completeness, dependency and environment availability, whether the
  verifier can even execute, contradictions in the specification. Anything decided here is an immediate
  abstention and needs no model at all. Crucially this separates *unverifiable* from *candidates failed*, and
  conflating those two is what makes the 0.51 figure unfixable.
- **Then sequential evidence, not a new signal.** Each failed tier updates the item's difficulty posterior
  upward, and `P(the next tier succeeds | the failures so far)` falls out of the shared item model the mechanism
  already fits. Stop when the expected value of a success falls below the next call's price.
- **Stop on the lower bound, not the point estimate.** The decision rule is a one-sided confidence bound on "no
  remaining candidate will succeed", with an **ex-ante cap on the lost-success rate inside the stopped set**. The
  learned part runs in shadow mode until that cap is demonstrably met; only the deterministic pre-flight gates
  real traffic before then.

## 5. The box-tuning experiment

**The ceiling is known and it is modest.** All-API costs $2.6289 over these items; today's box saves 11.3%; a box
at frontier ability would save 25.9%, because escalations already land on cheap APIs, so the box's value is
bounded by the gap to the *cheapest adequate* API rather than to the dearest one. The most valuable target is the
95 items the box misses that currently need a dear tier: capturing all of them is −20.0% of the bill, and such an
item is worth 4.0 times more than an average one ($0.00554 against $0.00137).

**95 items is a pilot, not a study.** Both reviews said so and gave the same reasons: memorising surface patterns
of dear-tier-dependent items, forgetting the easy centre, leakage through near-duplicates, and a threshold that
becomes self-fulfilling because it was fitted before the improvement. The duplicate groups found in the audit are
a concrete instance of the leakage risk.

The experiment, with everything that has to be fixed before it starts:

- **Freeze a new hold-out first**, collected by the same rule as the target, before any training. Group
  near-duplicates by normalised text and semantic cluster so that no group straddles the split. Use the 95 items
  for pilot training only.
- **Three arms, three seeds each.** Untuned box; the box tuned on the 95 target items; and a control tuned on the
  same number of items drawn from routing byproducts that are *not* dear-tier-dependent. Without that control a
  gain cannot be attributed to the targeting.
- **Four evaluation faces.** The target hold-out; the easy centre the cheap tier already handles; the
  nobody-solves distribution; and a time-ordered hold-out of the tenant's own traffic. Two runs per cell, a third
  on any cell that flips.
- **Promotion needs all three of:** a reproducible verified gain on the target hold-out; degradation on the easy
  centre below a cap set in advance; and a one-sided lower bound on the expected cost saving that is positive.
- **The policy and the thresholds are frozen during the comparison.** Moving the threshold after tuning makes the
  target set grow by construction.
- **A tuned box is a new candidate.** It is placed on the anchor set of 100 to 200 items, which is necessary but
  **not sufficient** — anchors position it against the others and say nothing about whether the tuning was worth
  it. The anchor set must include repeat cells so the tuned box's own flip rate is re-estimated; this project has
  already measured a 7-point accuracy swing from one chat-template flag and an 8% outcome flip rate from
  batching, so "same weights" is not "same candidate".
- **The probe must be a pinned, frozen artifact.** The item model regresses difficulty from the box's own probe
  features. If the probe is the serving box, tuning it shifts the probe's distribution and the regression decays
  silently — improving the fleet would break the instrument that measures it.
- **Cut condition.** No consistent hold-out gain across three seeds, or one breach of the centre-regression cap,
  and the line stops. Because the theoretical ceiling is −20.0% of the bill, the cumulative cost of collection,
  training and maintenance is capped at a conservative fraction of that.

## 6. The agentic re-measurement

**The existing agentic evidence is withdrawn from the evidence base.** Twenty instances, three candidates, one
run each, with one candidate solving all twenty: that supports no statement about ability ordering, about
Loevinger's H, or about the value of a predictor. It stays on file as an exploratory note.

The minimum that would replace it, from the stricter of the two reviews: **200 independently verified instances,
six candidates spanning cheap, middle and frontier, two runs per cell** — 2,400 runs — with a third run on every
cell whose two runs disagree. If the budget does not reach that, the conclusions are restricted to protocol
calibration and **no routing claim is made at all**. Before committing to 200, run an 80-instance calibration at
the same shape to fix the flip rate, the degenerate-instance rate and the cost variance.

- **Stratify** by the current three candidates' pattern (all pass, mixed, all fail), repository and language,
  change size, testability, tool and network dependence, runtime, and a static difficulty proxy. Sample mixed
  strata heavily and keep all-pass and all-fail as small quotas.
- **Do not delete the eight instances every candidate solved.** They exist in the production distribution, so
  they carry weight in cost and quality aggregates; they are reweighted by sampling probability rather than
  dropped. They simply contribute nothing to ordering or prediction, so they are not over-sampled.
- **The noise floor is estimated per candidate and per stratum** and enters the correctness matrix's error model,
  so H is reported as an interval rather than a point.
- **The bill-concentration analysis comes first**, and it is kept as `P(verified success)` per instance together
  with measured tokens, tool calls and wall-clock per candidate, so the deliverable is a cost curve per quality
  floor rather than one table at today's prices.

## 7. Order of work, and why

1. **Fix the gateway's empty completions.** An upstream zero-token completion is relayed as a success and
   charged: $17.69 discarded against $14.59 of successful spend on the affected arm. It is recovered directly
   with no quality trade-off, and until it is fixed it keeps poisoning the labels every other measurement uses.
2. **Deduplicate and audit the labels.** Free, done for the unanimous case, and it shrinks the biggest number on
   the page from 54.8% to 47.8% of the bill.
3. **Experiment A, the arbiter — done and killed, $10.20 across both folds.** Arbitration adds nothing the
   frontier tier does not already do by answering. The quorum stopping rule that came out of it is the keeper.
4. **The quorum optimiser (experiment B).** No new measurement; this is the code that makes the answer survive a
   price change.
5. **Abstention, deterministic pre-flight only at first**, with the sequential rule in shadow mode behind a
   lost-success cap.
6. **The box-tuning pilot**, under the gates in section 5.
7. **The agentic re-measurement**, starting with the 80-instance calibration.

The two reviews disagreed on nothing material here. They ordered tuning against the agentic re-measurement
differently, and the tie-break is stated: the agentic work moves ahead of tuning only if agentic spend comes to
dominate the bill and a product decision on agentic routing is imminent.

## What this does not claim

**About 7% of the mid-priced arm's cost is imputed, not measured.** The gateway's Converse transport
accepts `stream_options.include_usage` and emits no usage chunk, so the rows that had to be collected
over the streaming path — 24 of 338 on the frozen fold, 17 of 257 on the calibration fold — carry a
crude local token estimate rather than the provider's count. The measurement client tags those rows so
imputed spend is separable, and the `$0.00295` figure should be read as measured to within that
fraction. The accuracy figures are unaffected; only the cost column is.

**No arm has been repeated.** The frozen-fold figures are single runs, and the tiers involved flip 3.6% and 5.1%
of their answers between identical runs. That is smaller than the 3.2-point accuracy gap the quorum policy gives
up, so the ranking is safe, but it is the same size as the arbitration effect that failed to replicate — which is
the reason to distrust any single-fold difference of that size here.

**Every accuracy figure here is on a corpus with known residual label noise.** The 22 confirmed bad keys are
removed; the unmeasured remainder is larger and biases all of these figures downward by an unknown amount.

**The quorum table is one price vector.** The three-candidate quorum is not the answer; the optimiser is. At a
different price vector the best quorum is a different subset, and possibly a single candidate.

**No tuning has been done and no arbiter has been run.** Sections 3, 5 and 6 are registrations.
