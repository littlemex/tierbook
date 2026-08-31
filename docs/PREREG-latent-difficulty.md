# Pre-registration: can the box's hesitation be read in its latent state rather than in its output token?

**Written 2026-09-01, before a single hidden state is captured.** The router that survived the gates reads one
number: the margin between the chosen option letter and the runner-up, at the first generated position. That
number is the final layer's softmax collapsed to a scalar, and it separates the box's own errors at an AUC of
0.797 to 0.838. The question here is whether the same judgement is better made from what the model was doing
*before* it committed — the layer-by-layer trajectory that in a person would look like "this one is obvious"
against "I need to think about this".

## What the literature already settles, and what it warns

**The quantity has a name.** Baldock, Maennel and Neyshabur define **prediction depth** — the layer at which a
prediction is effectively fixed — as a measure of an example's *computational* difficulty, and relate it to
uncertainty, accuracy and how quickly the example is learned (arXiv:2106.09647). That is the formal version of
"how much thinking did this need".

**The trajectory is readable.** The logit lens projects each layer's hidden state through the unembedding; the
tuned lens replaces it with a trained affine probe per block and is "more predictive, reliable and unbiased"
(Belrose et al., arXiv:2303.08112). Layer-wise probability trajectories have been used directly as an
uncertainty signal, comparing certain against uncertain predictions (arXiv:2507.06722).

**Internal state has beaten output probability at exactly this task.** `ProbeDirichlet` routes between models by
aggregating cross-layer hidden states, motivated by internal states carrying "model uncertainty before answer
generation" rather than output probabilities, and reports 16.7% and 18.9% relative improvements over its best
baselines (arXiv:2602.11877). Classifiers on hidden activations detect false statements at 71 to 83%
(Azaria and Mitchell, arXiv:2304.13734), while output-side self-knowledge is well calibrated in-domain and
loses calibration off-domain (Kadavath et al., arXiv:2207.05221).

**Two findings say it may fail here, and they are registered as the reasons it would.** `Pando` finds the logit
lens gives "no reliable benefit" for confidence detection (arXiv:2604.11061). And confidence has been observed
to form only in late layers, a two-phase structure (arXiv:2603.04464) — if this model decides late, prediction
depth is compressed into a few layers and carries little.

## The measurement

One forward pass per item, no generation, on the terse prompt the router actually sends — so the last prompt
position is exactly the state that produces the answer token whose margin is today's signal. 1,187 items, the
488-item calibration fold and the 699-item development fold, with the correctness labels already collected.

Captured per item: the hidden state at the last prompt position for every layer, plus the attention entropy at
that position.

Derived, and fixed here so the list cannot grow after seeing which one works:

1. **Per-layer letter distribution** via the logit lens, restricted to the option-letter tokens: margin and
   entropy at each layer.
2. **Decision depth** — the first layer after which the final answer stays top-1 among the letters.
3. **Flip count** — how many times the top letter changes across layers.
4. **Effort per layer** — the relative norm of each block's update to the residual stream.
5. **A linear probe** on the hidden state, fitted per layer and on a concatenation of layers, predicting "this
   answer will be wrong".

## What it is compared against, and what would make it worth building

The incumbent signal is the **served token-space margin**, whose AUC on the same folds is 0.797 (greedy) and
0.838 (sampled). A second token-space baseline is registered so that latent is not compared against a weakened
version of what we already have: **the entropy over the letter alternatives** at the answer position, from the
top-eight logprobs already recorded.

**Pass, on the development fold, requires both:**

1. the best latent signal's AUC beats the better token-space baseline by **at least 0.03** — larger than the
   run-to-run spread of the box, which moves its own solve count by ±1.6 points; and
2. substituting it into the router's threshold rule produces a point on the cost-quality frontier that
   **dominates** the token-space rule — at least as many solved and no dearer, on the same fold.

Both fitted on the calibration fold only, with the probe's regularisation chosen by cross-validation *within*
that fold. One evaluation.

**Fail is a real and likely outcome**, and it closes this line: the finding would be that on this model and this
family, the collapsed final-layer margin already carries what the trajectory has, which is what `Pando` reports
and what a late-deciding model would predict.

## Registered limitations

**The captured numerics are not the served numerics.** The capture runs in `transformers` at bf16; the router
runs on vLLM at FP8 with a different kernel and batch-dependent reductions. A probe that works on the capture
has not been shown to work on the deployment, and the honest next step in that case is a second capture from the
serving engine itself, which needs a patched engine rather than an API call. **No claim about the deployed router
will be made from the offline capture alone.**

**The labels come from runs that do not repeat.** The box's outcomes flip on 3.3% of items between two greedy
runs of the terse arm, so the target being predicted is itself noisy at that level. This is why the AUC bar is a
margin of 0.03 rather than any improvement.

**One family, one model, one prompt.** Multiple choice with a single-token answer is the easiest possible case
for reading a decision off one position, and the least like the agentic traffic this project cares about most.
A positive result here is a reason to test it elsewhere, not a general claim.

**No fine-tuning, no steering, no intervention.** The model is frozen and only read.
