# Tuning the cheap tier is a separate responsibility, and the interface that makes it separable is not one-directional

**Written 2026-09-01.** The question was whether "make the box stronger" belongs to routing. It does not — but
the separation is bought with an interface, and the interface costs more than "the prompt, the output, a label
and a run id". Two reviews agreed on that and each found a failure mode the owner's framing misses.

Alongside it, two parameters of the mechanism were measured today on the existing matrix, at no cost.

## The separation holds, on three conditions

**A tuned box is a new candidate.** That is what makes the split work at all: the mechanism already treats a
model change as a new candidate identity, so a tuned box enters as an addition to the candidate set and costs
`d+1` parameters on an anchor set rather than a re-measurement of the matrix. Routing's internal state does not
change. **Versioning has to include the serving configuration, not just the weights** — this project has already
measured a 7-point accuracy swing from one chat-template flag and an 8% outcome flip rate from batching, so
"same weights" is not "same candidate".

**Routing has to pay for exploration it does not need.** A log that only contains the route the policy chose has
no outcomes for the routes it did not choose, and no amount of later cleverness recovers them. So a fixed small
fraction of decisions must be randomised — escalations that the score said were unnecessary, and continuations
of runs the abstention detector wanted to stop. That cost is charged to routing and spent on training. Refusing
it makes the separation nominal.

**And the interface runs both ways.** If the training side tunes on items that sit in the anchor set or a
hold-out, the tuned candidate's parameters are overestimated and every gain figure downstream is wrong. So the
training side owes routing a **contamination manifest** — the item ids it trained on. This is the part "just use
the logs later" misses: it is not a one-directional feed.

**One more, which follows from the mechanism rather than from the reviews.** The item-side model regresses θ from
*the box's own* probe features. If the probe is the serving box, tuning the box shifts the probe's distribution
and the θ regression degrades silently. **The probe must therefore be a pinned, frozen artifact whose only job is
measurement**, versioned separately from whatever the pool is serving. Otherwise improving the fleet breaks the
instrument that measures it.

## The logging contract, and what each field prevents

| field | what goes wrong without it |
|---|---|
| run id, item id | nothing joins; repeats cannot be distinguished from distinct items |
| **the effective input, rendered and pinned** | the prompt that was actually sent is not recoverable from the template plus the item, because templates and system prompts move |
| the output, verbatim | there is no distillation target |
| **candidate identity + version, probe version, policy version** | outcomes from two different candidates are pooled under one name; this is the 7-point flag and the 8% flip rate |
| **the eligible action set** | a route that was never available looks like a route that was rejected |
| **the action probability (propensity)** | no counterfactual estimate is possible; inverse-probability weighting and doubly robust estimators need the denominator, and it cannot be reconstructed afterwards |
| **the exploration flag** | the unbiased slice cannot be separated from the policy-selected one, which is the selective-labels problem in its exact form |
| **usage in tokens, not dollars** | a price change invalidates the log; prices belong in the evaluation, not the record |
| the independent verified outcome | the label is the candidate's own opinion, which this project does not accept |
| latency and step count | the cost that is not money is invisible |

Two boundaries worth stating in the contract itself. **Provider terms may forbid training on an API's output**,
so the record must carry which candidate produced each completion and the training side must filter on it — this
project already has one corpus whose licence permits evaluation and forbids training. And **retention**: verbatim
prompts are the most sensitive thing here, so the contract needs a stated horizon rather than an implicit one.

## What the training side can actually take, cheapest first

1. **A distillation corpus that costs nothing to produce.** Every escalation is a pair: an item the cheap tier
   failed and a stronger tier solved. This is the highest-value byproduct and it is free.
2. **A difficulty predictor that improves itself.** Every routed item adds a row of probe features with a
   verified outcome, which is exactly the training data for θ.
3. **An abstention detector**, but only from the randomised-continuation slice, because that is the only part
   with outcomes for the runs the detector wanted to stop.
4. **Preference learning** from cases where two candidates both answered and one was verified — rarer, since the
   policy usually stops at the first success.

And the danger, named by both reviews: **training the box only on what the router escalated teaches it the hard
tail and lets it forget the easy centre**, while the router's own threshold becomes self-fulfilling — a box that
improves on escalated items alone still gets escalated, because the threshold was fitted before the improvement.
The minimum discipline is three disjoint regions split by semantic cluster (train, anchor and calibration, final
hold-out), a permanent trickle of randomised escalation and continuation across all score bands, replay of the
original production distribution mixed into training, candidates and policy frozen for a generation at a time,
and promotion decided by a concurrent control that checks stratified forgetting rather than the average.

Prior art, with the distinction that matters: `FrugalGPT`, `AutoMix` and `RouteLLM` are cost-under-quality
cascades and none of them publishes a logging contract for feeding the student. `Learning to Defer`,
`Predict Responsibly` and `SelectiveNet` are the routing-aware training lineage, quality- and coverage-first,
with price added as a loss term rather than measured. Knowledge distillation, `Distilling Step-by-Step` and
`Orca` are the quality side of using a strong teacher, and none of them addresses the router's selection bias.
The bias itself is `The Selective Labels Problem`, with the remedies in the counterfactual-evaluation line —
contextual-bandit offline evaluation, counterfactual risk minimisation, doubly robust policy evaluation. Those
correct bias where the exploration probability is positive; they do not conjure support where there is none.

## Two parameters of the mechanism, measured today

**How many dimensions the probe can see: one.** Fitting `logit P(m solves i) = a_m · θ(x_i) + b_m` on the
calibration items and scoring on the development items, with each candidate's own solve rate as the baseline:

| model | log loss | Brier | AUC |
|---|---|---|---|
| baseline: the candidate's solve rate, no item information | 0.4763 | 0.1530 | 0.6893 |
| **d = 1** | **0.4646** | **0.1471** | **0.7367** |
| d = 2 | 0.4648 | 0.1472 | 0.7360 |
| d = 3 | 0.4642 | 0.1470 | 0.7368 |

**A second dimension buys nothing.** That is worth stating precisely against the earlier structural finding: the
matrix itself is *not* one-dimensional — Loevinger's H is 0.6375 and a cheaper candidate beats a dearer one on up
to 3.2% of items — but **the cheap probe reads only the first dimension.** The specialisation is real and
invisible to this instrument. Exploiting it needs either a second probe of a different lineage or per-candidate
features, and that is the next thing worth trying rather than a deeper model on the same features.

**What onboarding a new candidate costs: about a hundred items, comfortably two hundred.** Leaving one candidate
out, fitting the item side on the other eight, then estimating the held-out candidate's two parameters from N
anchor items:

| anchors | verdict |
|---|---|
| 20 | **worse than using the candidate's own solve rate** — two parameters on twenty binary outcomes overfits |
| 50 | roughly break-even for the weak candidates, still worse for the strong ones |
| 100 | beats the no-information baseline for seven of nine |
| 200 to 488 | beats it for all nine |

The gain is largest exactly where the probe has dynamic range: `nemotron-super-3-120b` 0.6880 → 0.6047,
`qwen3.8-27b` 0.6468 → 0.5841, against `claude-fable-5` 0.3219 → 0.3161. So a new candidate at the weak end is
cheap to place and a new frontier candidate is nearly free to place badly — its parameters barely matter because
the probe cannot discriminate at that end anyway.

## What this does not claim

**No tuning has been done.** This specifies the interface and measures the mechanism's parameters; the training
side does not exist yet.

**The anchor figure is for this family and this probe.** A hundred items is the cost of placing a candidate on a
single-token multiple-choice family where one probe call is $0.00024. On the agentic family an anchor item is a
whole episode, and the equivalent number has not been measured.

**The contamination manifest is a requirement, not a mechanism.** Nothing enforces it yet, and an interface whose
correctness depends on the other side's goodwill is a design that will fail quietly.
