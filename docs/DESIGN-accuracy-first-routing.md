# Predicting who can answer, and letting the pool's own measurements decide whether routing has content

**Written 2026-09-01**, after two reviews and two measurements taken the same day. This replaces a framing
error of mine: the earlier pages answered "what is optimal in today's pool at today's prices", and the question
is "what is the mechanism that keeps answering that as the pool changes". The pool will change — the
self-hosted tier's model and instance are not fixed, the APIs are not fixed, and a configuration with a
*better and dearer* box, or two boxes, or no box, is as likely as the current one. So no conclusion of the form
"box then the expensive API, done" is a deliverable.

The deliverable is three separable things, and only one of them is expensive.

## 1. The candidate matrix, measured once per family

Rows are items, columns are candidates, cells are verified outcomes. Everything else here is a function of this
matrix and of a price vector, which means **a price change or a candidate swap does not require re-measuring
it.** That is the whole reason to spend on it.

It needs a **noise floor** to be readable. The box flips 3.3% of its terse answers and 8.0% of its long ones
between two runs at temperature zero, so a violation rate below that floor is not evidence of anything. The
floor is measured by repeats on a stratified subsample, per candidate. **This is not yet done for the API
tiers, and every structural number below is therefore an upper bound on the structure.**

## 2. Does per-item routing have content? Three price-independent statistics

The verdict has to come out of the matrix rather than out of an assumption about who is better.

| statistic | what it says |
|---|---|
| **Loevinger's H** | 1 means a perfect ability ladder — the candidates are ordered and the order never depends on the item. Below about 0.5 means the ordering is item-dependent. |
| **share of variance in the first component** | how much of the matrix is that single ladder |
| **exclusive-win mass per pair** | for each pair, how often the weaker candidate solves what the stronger misses — and, weighted by price, how much that is worth |

Measured today on the two families this project has:

| | Loevinger H | first component | cheapest beats dearest | verdict |
|---|---|---|---|---|
| knowledge, 9 candidates × 1,187 items | **0.6375** | 48.6% | up to **3.2%** of items, at price ratios of 4x to 250x | the ordering is item-dependent; specialisation exists |
| agentic, 3 candidates × 20 instances | **1.0000** | 94.6% | **0 items** | a pure ladder |

The weakest pair on the knowledge corpus is `qwen3.8-27b` against `qwen3-next-80b` at H_ij 0.417 — 157 items
where the first beats the second against 269 expected under independence, so they are genuinely different
candidates rather than two rungs. `gpt-5.6-terra` against `claude-sonnet-5` is 0.506.

**A correction to my first attempt at this.** I used Guttman's raw coefficient of reproducibility first, and it
gave 0.75 for the knowledge pool and 0.77 for the agentic one — which would have called them equally
structured, while one has zero violations and 94.6% of its variance in one component. The raw coefficient was
moving with the marginals rather than the structure. H compares observed violations against what independence
would produce, which is the correction the question needs.

**And a correction to the conclusion I drew from the agentic pool.** H = 1 means per-item *specialisation*
routing has no content there — no item is a reason to prefer a weaker candidate. It does **not** mean routing
is pointless: routing on *difficulty* under a cost constraint still works on a pure ladder, because an easy item
can be finished by a cheaper rung. That is exactly what the knowledge-corpus router does, and it is why the
same mechanism gives a 4-cent prize on one family and a 10 to 30% saving on the other.

## 3. The gain is a function of the price vector, not a number

Given the matrix, the value of routing at any configuration is
`gain(prices) = cost(best fixed arrangement) − cost(oracle router)`, evaluated on the matrix. A new price table
or a swapped candidate is a re-evaluation, not a re-measurement. "Nested capability plus the cheapest tier first
gives a prize of four cents" is **one evaluation point of this function**, not a law about routing, and reading
it as a law was the error this document exists to correct.

## 4. The predictor: one item-side model, plus a few parameters per candidate

Both reviews arrived at the same form, and it is the multidimensional IRT model, which is the same object as a
low-rank logistic matrix factorisation:

    logit P(candidate m solves item i) = a_m · θ(x_i) + b_m

`θ(x_i)` is the item's latent description, regressed from **cheap probe features** `x_i`; `a_m, b_m` are the
candidate's discrimination vector and intercept. Three properties matter for a pool that changes:

- **Candidates are not exclusive.** A softmax over tiers is structurally wrong — 299 of 1,187 items are solved
  by all eight API tiers — and this form has no exclusivity in it.
- **The item side is the durable asset.** `θ` survives a candidate swap; a new candidate costs only `d+1`
  numbers, estimated by running it on a small **anchor set** of items whose θ is known. Full zero-shot
  onboarding of a new candidate is not possible even in principle, because its parameters are unidentified
  until it has answered something.
- **It gives the conditional probabilities a cascade needs.** `P(B solves | A failed)` falls out of the shared
  θ; independent per-candidate classifiers throw exactly that away.

The dimension `d` is not fixed in advance: start at 1 and add while held-out log loss improves. **`d` is itself
one of the verdict statistics from section 2.** Model selection is on log loss, Brier score and calibration,
**not AUC** — a router that consumes probabilities needs them to be calibrated, not merely ordered.

## 5. Does one cheap probe carry the whole row? Measured today

If the box's own prefill uncertainty is a measurement of item difficulty, then to the extent the matrix is
one-dimensional it should predict *every* candidate's correctness after a monotone recalibration. That is
testable on the existing matrix at no cost, and the decay pattern is itself evidence about dimensionality.

Predicting "this candidate is wrong" from the box's 4-token prefill probe, 1,187 items:

| target | its solve rate | AUC from margin | AUC from letter entropy |
|---|---|---|---|
| the probe's own error | 62.4% | 0.8241 | 0.8281 |
| `nemotron-super-3-120b` | 54.8% | **0.7512** | **0.7605** |
| `qwen3.8-27b` | 64.4% | 0.7368 | 0.7440 |
| `qwen3-next-80b` | 64.8% | 0.6985 | 0.7015 |
| `gpt-5.6-sol` | 85.6% | 0.6691 | 0.6671 |
| `gpt-5.6-terra` | 82.4% | 0.6597 | 0.6494 |
| `claude-sonnet-5` | 83.7% | 0.6434 | 0.6569 |
| `grok-4.6` | 87.3% | 0.6426 | 0.6366 |
| `claude-opus-5` | 89.6% | 0.6337 | 0.6368 |
| `claude-fable-5` | 89.3% | 0.6267 | 0.6232 |
| **every candidate solves it** (38.1% of items) | — | **0.8076** | **0.8284** |
| no candidate solves it (4.3% of items) | — | 0.5082 | 0.5262 |

Three findings, and the third is the most useful.

**One probe does carry information about every candidate**, at 0.62 to 0.76. So a single $0.00024 call gives a
usable prior on the whole row, which is what makes the optimisation step cheap.

**It decays monotonically with the candidate's strength**, exactly as predicted before it was measured: a strong
candidate's failures are a thin tail at the hard end, where the box is uniformly uncertain and has no dynamic
range left. The prediction and the measurement agreeing is evidence that the shared-difficulty model is the
right one.

**The single most predictable thing is "everyone can do this", at 0.83.** That is the decision worth the most
in any cost-minimising pool — 38.1% of items here — and it is the one the probe reads best. Its opposite,
"nobody can do this", is unreadable at 0.51: the pool's floor cannot be detected in advance.

## 6. The agentic case, where there is no single answer position

Both reviews converged on the same replacement, and it is not a prefill probe. **Model the time to a verified
success, not a fixed label:**

    P(verified success by budget B | pre-start features x, candidate m, history through step k)

as a discrete-time hazard or landmark survival model, with competing risks separating the outcomes that are
actually different: verified success, recoverable stall, unrecoverable damage, an empty completion from the
gateway, and budget exhaustion.

- **`k` is not a constant.** Whether to look one more step or switch now is an optimal-stopping decision, and it
  is item-dependent: an easy instance should settle in two steps and only a hard one deserves a long look. The
  quantity to plot is the information value curve — held-out AUC and calibration at step `t` against cumulative
  cost at step `t` — and `k` is where the marginal gain stops paying for itself.
- **Trajectory features before embeddings.** Cheap counters that every candidate's logs already carry: state
  revisits and n-gram repetition (loops), the decay of newly-touched files, edit churn and reverts, no-ops,
  repeated identical errors, tool failures, tokens per step, context consumed, transitions in the test signal.
- **Randomised continuation is mandatory.** If a candidate is only ever abandoned when the detector fires, the
  data has no outcomes for abandoned trajectories and the detector cannot be calibrated. A fixed fraction of
  triggers must be ignored and the run continued, and the evaluation uses inverse-probability weighting or a
  doubly robust estimator, with a concurrent control before anything is promoted.
- **The objective is not stall-detection AUC.** It is verified success rate at a fixed total budget.

## What is deliberately not claimed

**The structural numbers are uncorrected for run noise.** The box's own flip rate is measured; the API tiers'
are not. Until they are, H = 0.6375 is an upper bound on the knowledge pool's structure, and part of the 157
violations on the weakest pair could be flips.

**The agentic verdict rests on 20 instances and 3 candidates**, and one of them solved all 20, which makes H
degenerate rather than informative. It says "this pool, measured this way, is a ladder", not "agentic pools are
ladders".

**No predictor has been fitted yet.** Section 5 measures raw signals, not the model of section 4, and the
anchor-set mechanism of section 4 has not been built.
