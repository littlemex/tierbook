# The box's hesitation is real in its layers and already in its output token: the latent signal loses by 0.033

**Measured 2026-09-01** against [`PREREG-latent-difficulty.md`](PREREG-latent-difficulty.md). 2,364 questions
captured in one forward pass each on the deployed FP8 checkpoint, 935 calibration and 1,429 development items
graded by the same comparator the harness uses. Everything fitted on the calibration fold, one evaluation.

**It fails the registered bar**, and the way it fails is informative rather than empty.

## The measurement

Predicting "this answer is wrong", AUC:

| signal | where it lives | calibration (CV) | development |
|---|---|---|---|
| **entropy over the option letters** | token space | 0.8117 | **0.8424** |
| margin between the top two letters — today's router | token space | 0.8047 | 0.8295 |
| both together | token space | 0.8095 | 0.8386 |
| linear probe on the last layer's hidden state | latent | 0.7605 | **0.8095** |
| probe on seven layers concatenated | latent | 0.7436 | 0.8022 |
| five hand-built trajectory features | latent | 0.7680 | 0.7914 |
| **decision depth** — the layer after which the answer stops changing | latent | — | **0.6575** |
| total residual-stream movement ("effort") | latent | — | 0.6516 |
| how many times the leading letter changes | latent | — | 0.5363 |
| margin at layer 30, mid-network | latent | — | 0.4801 |
| token space **plus** the hidden-state probe | both | 0.8231 | 0.8461 |

The registered condition was that the best latent signal beat the better token-space baseline by at least 0.03.
It is **0.033 the other way**: 0.8095 against 0.8424. Adding the probe on top of the token-space pair buys
**+0.0037**, which is a tenth of the bar and inside the noise of a box whose own answers move by ±1.6 points
between runs.

## What the shape of the result says

**Your intuition is right about the phenomenon and wrong about where to read it.** Decision depth is a genuine
signal — 0.6575 is far from a coin — and it is exactly the human-shaped quantity: on easy questions the answer
is fixed early and stays; on hard ones the leading option is still changing near the top of the network. The
median question settles at block 36 of 40, the easiest at 28, the hardest not until 40. So the model does have
something like "I had to think about this one", and it is measurable.

But it is **weaker than simply asking how spread out the final answer distribution is.** The probe's AUC rises
monotonically with depth — 0.68 at layer 4, 0.73 at 16, 0.79 at 28, 0.81 at 40 — and peaks at the end. That is
the explanation and the disappointment in one line: by the time the difficulty is linearly decodable from the
hidden state, it has already been written into the output distribution, which anyone can read through an API for
free. `Pando` reported the same shape for the logit lens (arXiv:2604.11061), and the late-forming confidence
described in arXiv:2603.04464 is visible here as the dead mid-network layers — the margin at layer 30 is at
0.4801, which is no signal at all.

**Cross-layer aggregation did not rescue it.** `ProbeDirichlet` reports 16.7 to 18.9% relative gains from
aggregating layers (arXiv:2602.11877); here concatenating seven layers scored *below* the last layer alone on
both folds, which is what a 14,336-dimensional feature does against 935 training rows. That is a fair statement
about this corpus and this budget, not about their method.

## The byproduct is worth more than the experiment

**Entropy over the ten option letters beats the top-two margin the router uses today: 0.8424 against 0.8295.**
It costs nothing — the top-eight logprobs at the answer position are already recorded on every row, and the
router already reads them. That is a free +0.013 to the one signal the whole construction rests on, and it is the
only actionable finding here.

It also makes sense of the failure. The margin throws away everything except the gap between the first two
options; the entropy uses all ten. The latent state's advantage was supposed to be "more information than one
scalar", and most of that advantage was available in token space by not collapsing to one scalar in the first
place.

## Two methodological findings, both worth keeping

**Left padding silently changes this model's answers.** Thirty of its forty layers are Gated DeltaNet, which
carries a recurrent state along the sequence, and leading pad tokens enter that state whatever the attention mask
says. Batch-of-one agreed with the served engine on 8 of 8 items; left-padded batches of eight agreed on 77%.
Padding on the right and reading each row at its own index is correct instead, because causality keeps the
trailing pad out of the state. Anyone batching a hybrid-attention model for analysis will hit this.

**The offline capture and the served engine agree exactly where the router acts.** Over 1,187 items they agree on
77% of answers overall, but on **98.4% of the items whose margin clears the router's threshold**, and the
disagreements sit at a median margin of 0.12. The two engines differ only where the model is undecided. That is
reassuring for the deployment and awkward for this study, which is about the undecided region — so the capture
grades its own answers rather than borrowing the served run's labels.

## The dimension the probe was missing is the domain, and the incumbent router already had it

Added 2026-09-01, after the same capture was used to fit the mechanism's predictor rather than single signals.

Fitting `logit P(candidate m solves item i) = a_m · θ(x_i) + b_m` on the calibration items and scoring on the
development items, against each candidate's own solve rate as the baseline:

| features for θ | d | log loss | Brier | AUC |
|---|---|---|---|---|
| none — the candidate's solve rate | — | 0.4763 | 0.1530 | 0.6893 |
| probe only | 1 | 0.4531 | 0.1440 | 0.7418 |
| probe only | 2 | 0.4535 | 0.1440 | 0.7403 |
| category only | 1 | 0.4700 | 0.1504 | 0.7131 |
| **probe + category** | 1 | 0.4466 | 0.1415 | 0.7558 |
| **probe + category** | **2** | **0.4414** | **0.1397** | **0.7653** |

**A second dimension buys nothing on probe features and pays as soon as the category is added.** That resolves
what looked like a contradiction: the matrix is not one-dimensional — Loevinger's H is 0.6375 — but the probe
reads only its first axis, and "d = 2 is useless" was a statement about the feature set rather than the matrix.

Removing the first component from the correctness matrix and looking at what is left says what the second axis
is: **it is the domain.** Its item scores average +0.2115 on mathematics and −0.1839 on health, with engineering
and law positive and economics and philosophy negative. It correlates weakly with the probe (margin −0.283,
entropy +0.273) and not at all with prompt length (+0.048).

So the incumbent router — a map from category to tier, the thing every learned router in this project has failed
to beat — was capturing the second dimension all along, while the probe captures the first. **They were never
competitors.** The predictor that uses both is better than either: log loss 0.4414 against 0.4531 for the probe
alone and 0.4700 for the category alone, and 7.3% below the no-item-information baseline.

One correction to the numbers above this section: the first fit of the probe-only model reported 0.4646, and that
run was under-trained at 60 iterations. At 300 it is 0.4531. The ordering of the findings is unchanged.

## Is "needs specialised knowledge" a third axis? It is the second axis, measured worse

Asked 2026-09-01: would classifying items by how much specialised terminology they carry add anything?
Three estimators of that were built and measured, and the answer is precise.

**The axis is real, and it is the second dimension rather than a third.** At the category level the
rare-word rate correlates with the second dimension at **r = −0.766** over seven categories: it runs from
symbol-heavy general vocabulary at one end — mathematics, mean inverse document frequency 1.289, rare-word
rate 0.077, the highest digit and symbol density — to specialised terminology at the other, health at 2.352
and 0.218. "Knowledge required" is a fair name for what the second dimension is.

**But every per-item estimator of it is too noisy to use.** Correlations with the second dimension, per item:

| estimator | how it is computed | r with the second dimension |
|---|---|---|
| digit rate | from the text | +0.206 |
| **prompt surprisal**, mean NLL | the box's own prefill, `prompt_logprobs` | +0.106 |
| rate of tokens with NLL > 8 | same | +0.113 |
| rare-word rate | corpus document frequency | −0.072 |
| mean inverse document frequency | same | −0.088 |

And in the predictor, on the same folds, adding them **costs** accuracy:

| features for θ | d | log loss | AUC |
|---|---|---|---|
| **probe + category** | **2** | **0.4414** | **0.7653** |
| probe + lexical knowledge features | 2 | 0.4562 | 0.7412 |
| probe + category + lexical | 2 | 0.4475 | 0.7593 |
| probe + prompt surprisal | 2 | 0.4555 | 0.7460 |
| probe + category + surprisal | 2 | 0.4539 | 0.7567 |
| surprisal alone | 2 | 0.4777 | 0.7003 |

**The reason is sample size, not the idea.** A single question is one or two hundred words, which is far too
little text to estimate its vocabulary's specialisation; the category label is the *same quantity pooled over
about a hundred and seventy items*, so it has a fraction of the variance. The model-based measure is a better
per-item estimator than word counting — surprisal reaches +0.106 where rare-word rate manages −0.072 — and it
is still nowhere near enough.

**Which means the fix is coarser pooling, not finer.** Learned clusterings of the item text were tried against
the seven human categories, fitted on the calibration items only:

| partition | buckets | log loss at d = 2 | AUC |
|---|---|---|---|
| **human category** | 7 | **0.4414** | **0.7653** |
| tf-idf clusters | 7 | 0.4555 | 0.7391 |
| tf-idf clusters | 15 | 0.4516 | 0.7554 |
| tf-idf clusters | 30 | 0.4691 | 0.7360 |
| tf-idf clusters | 60 | 0.4745 | 0.7306 |
| category and 30 clusters together | 37 | 0.4573 | 0.7525 |

Every learned partition loses to the seven human categories, and they get **monotonically worse as they get
finer** — 488 calibration items over 7 buckets is seventy items each, over 30 buckets it is sixteen, and
sixteen is where the estimate of the axis stops being worth having. So the productive version of this idea is
a taxonomy with *more* items behind each bucket, not a more discriminating one.

## What this does not support

**It does not say latent difficulty is useless in general.** It says that on a single-token multiple-choice
answer, where the whole decision is one position and the output distribution is fully observable, the output
distribution already carries it. The case that would differ is the one this project cares about most: long
agentic work, where there is no single answer position, no clean distribution to read, and the interesting
hesitation is spread over hundreds of steps. Nothing here tests that.

**No claim is made about the deployed router from this capture.** It ran in `transformers` on the same FP8
checkpoint but different kernels and no tensor parallelism, and the answers diverge in the low-margin region.

**The line is closed as registered.** The next router change is the entropy substitution, in token space, with
its own registration — not a hidden-state probe.
