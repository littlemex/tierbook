# Read the box's hidden state, and find out whether it breaks the abstention limit

**Status: backlog.** Not scheduled. Filed because the cheapest step is small and the thing it would settle is the one
structural blocker in this project's routing results.

## Why this is worth a slot

Four measured results in this repository point at the same gap.

| what was measured | value | where |
|---|---|---|
| output-length signal for "will this be wrong" | AUC 0.529 | box-cascade gates |
| embedding similarity signal | AUC 0.62 | box-cascade gates |
| answer-token logprob margin | **AUC 0.838** | the first usable signal, and it needs the answer generated first |
| an abstention rule at decision time | **AUC 0.5000** | reported as *structural*: at the decision point the conditioning set is a constant |

The 0.5000 is the important one. It was not a weak feature set; it was that nothing available at decision time varied
with the input. Every signal we found either arrives too late (the margin, which requires generating the answer) or
does not discriminate (length, embeddings).

Prior art says the missing axis is inside the model. "Is this wrong" and "can this be answered" are different
questions, output-side signals are blind to the second, and scale does not fix it; hidden-state probes reach AUROC
0.69–0.77 (arXiv:2607.08456). A hidden state is not a constant at decision time, so it is the one candidate for
breaking the 0.5000 for the reason the 0.5000 exists.

And this is the only capability the self-hosted box has that a metered API does not. That has been carried as unpriced
value; this issue is how it stops being unpriced.

## Where the value is, and where it is not

**Not** in the agentic-coding cascade. A perfect prefill predictor there was worth $0.0395 per item against the
box-first cascade, and 0.0% held out, because the box is already the cheapest thing and "box, then cheap, then
expensive" already lands cheapest. A better signal does not revive a dead economic case.

**Yes** in the escalation decision under a residency or quota constraint. The certified floors there are 78.2% at
$0.00382 staying domestic against 81.6% at $0.01202 with the API unlocked. What is at stake is 3.4 accuracy points and
a 3.1x price difference, decided per input, before generation. That is the decision a pre-generation "can the box
answer this" signal is for.

## The three objects, in increasing cost

Stage 1 is where the measurable value is. Stages 2 and 3 are only worth reaching if stage 1 clears the bar.

### Stage 1 — the residual stream, read out. No Jacobian at all.

Enough for a probe, which is what the 0.69–0.77 figure was measured on. What is needed is the activation at a mid-depth
layer for the prompt, before any token is generated.

vLLM 0.27.1 as deployed here does not return it: `SamplingParams` carries no hidden-state field, and the server is
running a generation task, not a pooling one. So this is plumbing work in the serving path, not a modelling problem.
Two routes to compare rather than pick blind:

- a second, pooling-mode load of the same weights, which costs GPU memory and keeps the generation path untouched
- a forward hook in the running engine, which costs a patched engine and touches the path everything else measures

Whichever is cheaper, the deliverable is: prompt in, one activation vector out, with the layer as a parameter.

### Stage 2 — J-lens, which needs `J_ℓ h` and not `J_ℓ`

The published method (Gurnee, Sofroniew, Lindsey et al., *Verbalizable Representations Form a Global Workspace in
Language Models*, 2026-07-06) reads a mid-layer activation through `lens(h) = softmax(W_U norm(J_ℓ h))`, where
`J_ℓ = E[∂h_final/∂h_ℓ]` averaged over about 1000 prompts. The reported findings: swapping a concept's J-space
component changes the model's report 59% of the time against 5% for the other 93% of the variance; the space is under
10% of activation variance at every layer; deleting it leaves fluency intact and drops multi-step reasoning to near
zero.

**The read-out needs a Jacobian-vector product, not the matrix.** `J_ℓ h` for one specific `h` is a directional
derivative, and a directional derivative is one perturbed forward pass:

    J h  ~=  ( f(h + eps*h) - f(h) ) / eps        where f maps the layer-l residual to the final residual

So the read-out is forward-only and vLLM can do it, once stage 1's plumbing can both **read** the residual at layer
`l` and **inject** a modified one and resume from there. Backward is not required. This is the part of the earlier
assessment that was wrong: "vLLM cannot do this in principle" was too strong, and the reason it is wrong is that we
never need the matrix.

**But the forward-only route gives a different object, and that has to be said.** The published `J_ℓ` is averaged over
1000 prompts precisely to remove context dependence; a per-input JVP is the context-dependent version the paper threw
away. For routing that may be the more useful of the two -- we want *this* input's state -- but it is not J-lens as
published, and the paper's selectivity and broadcast findings do not transfer to it without being re-established.

Building the published context-averaged `J_ℓ` is the expensive path: either a separate `transformers` load with
autograd, or `d` forward probes per prompt for a `d x d` matrix, which is not viable at this width.

### Stage 3 — the MoE question the paper does not answer

The paper works on dense Claude models. The box is `Qwen/Qwen3.6-35B-A3B-FP8`, a mixture of experts. Averaging a
Jacobian over prompts that route to different experts averages over different functions, so the context-averaged
object may not exist in the form the method assumes. Nothing here says it fails; nothing says it holds either. If
stage 1 clears the bar and stage 2 is wanted, this is the assumption to check before building on it.

## What would make this worth doing, and what would end it

**Stage 1 passes** if a probe on the mid-layer activation separates "the box answers this correctly" from "it does not"
at AUC materially above 0.5000 on held-out items, measured on the same cohort the 0.5000 came from so the comparison is
against the number it is meant to beat.

**It ends** if the probe also sits at 0.5000. That is a result worth having: it would say the limit is not about where
the signal is read from, and the abstention route closes for good rather than staying open as a suspicion.

**The bar it has to clear is not 0.5000 alone.** Learned routers in the literature do not beat static task-type
assignment or the single best model -- 21 methods across 5 benchmarks converge to that, and oracle-gap recovery lands
at 7.5-14.4%. Anything built here is measured against static assignment and against always-using-one-model, not
against a strawman.

## Scope

In: reading and injecting a residual stream from the served box, a probe trained on it, and the AUC comparison above.

Out: the router itself, any policy change, and any claim about consciousness or interpretability. This issue buys one
signal and finds out whether it discriminates. What a signal is worth is decided by the mechanism that consumes it,
after it exists.
