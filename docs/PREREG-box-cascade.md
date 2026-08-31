# Pre-registration: the box as the default path, with escalation bought out of an API budget

**Written 2026-08-31, before the first figure of this construction is computed.** Six learned routers have
now lost to a router built on one categorical feature, so this one is registered before it is measured and it
is registered with a gate that can kill it in an afternoon.

## What changed, and why this is not a seventh variation of the same idea

The six that lost all treated the self-hosted tier as one candidate among nine and priced it per token. That
pricing is wrong in kind. The box is a `g6e.12xlarge` billed by the hour, so **inside a fixed deployment
window its marginal cost is zero and what is scarce is its capacity**, not its money. Two independent reviews
converged on the same reformulation, and on the same correction to my first attempt at it:

- every item goes through the box, because that is where the escalation signal comes from, so the only
  decision variable is escalation;
- maximise expected solves subject to two constraints, an API budget and the box's service capacity;
- the box's capacity price is zero while capacity is spare and only becomes a real term at saturation, and in
  *this* construction escalation **shortens** box occupancy rather than lengthening it, because the box stops
  generating.

That makes the objective a knapsack on the *gain* of escalating, `p_api(i) - p_box(i)`, bought with
`c_api(i)`. The Lagrangian sweep from the losing attempts reappears, but the point it compares against is no
longer "another candidate" — it is "the answer the box already has".

## The numbers this has to beat, stated before looking

All are already published in `results-candidate-audit.md` and `results-routing-raises-quality.md`, measured on
the 699-item held-out fold of the knowledge multiple-choice corpus.

| | solved / 699 | API spend |
|---|---|---|
| box alone (`qwen3.8-27b`, self-hosted) | 456 | none, it is hourly |
| **`category`, one feature — the incumbent** | **596** | **$1.6523** |
| oracle over all nine candidates | 671 | $1.1212 at concurrency 4 |

The box's own bill is $15.2174/hour and **its concurrency has never been measured**, so its amortised per-item
cost is an assumption carried visibly: $0.00839 at concurrency 1, $0.00210 at 4, $0.00052 at 16. Every total
cost figure below is reported twice, once as API spend alone and once with the box's amortised bill added at
all three concurrencies, because the second is the number an owner pays and the first is the number the policy
controls.

## Gate 1 — the oracle, on the development fold, costing nothing to run

Escalate exactly when the box is wrong, using the recorded outcome as the oracle, and send those items to the
incumbent router's own choice. This is the ceiling of the whole construction: no judge can escalate better than
knowing the answer.

- **solved** = (box correct) + (box wrong and the incumbent's chosen tier correct)
- **API spend** = the incumbent's cost on the escalated items only
- **escalation rate** = the box's error rate, which is both the API bill's driver and the capacity relief

**Pass** requires both:

1. solved is above 596 with the lower bound of the paired difference above zero, and
2. API spend is at most $1.6523.

**Fail on either, and the construction stops here** — no judge is built, no GPU is started, and the finding is
recorded as the seventh loss. This is the same death the cost-prefix level-label attempt died of, and it died
at the oracle stage for $0, which is the cheap end of this mistake.

One arithmetic caution, registered because it is the way this gate could be read too favourably: items the box
gets wrong are the harder items, so the API tiers' solo accuracy must **not** be applied as a rate to them. The
gate is computed from the item-level outcome table only.

## Gate 2 — a realisable policy, on the development fold

Only if Gate 1 passes. The oracle is replaced by an escalation judge fitted on the calibration fold (488
items), and the policy must still exceed 596 at no more than $1.6523. **One iteration.** If a fitted judge does
not clear the incumbent on the first attempt, the construction stops; a seventh loss should not be dragged out
by tuning.

The judge's features are drawn from the box's own generation — logit margin on the answer tokens, entropy,
cumulative surprisal, confidence change between checkpoints, whether an answer format was reached, mechanical
self-contradiction markers — plus category and input length. Generation-length checkpoints are fixed now at
**0, 8, 32, 64, 128 and full**, recovered from one trace per item rather than one generation per checkpoint.

Two lines that do not move for this experiment:

- **The box's confidence is a feature, never a label.** Labels come from the recorded external correctness of
  the box. The moment a candidate's own confidence counts as evidence that its answer is right, this project's
  central rule is broken, and the rule is what makes any of these numbers worth reading.
- **The learner proposes, the optimiser decides, and neither promotes anything.** A predicted probability is
  not evidence and cannot admit a tier or accept an answer.

## Gate 3 — the decision, on a fold that has never been used

The 699 items are **development data from now on**. They have been used to choose between seven constructions
and can no longer support a claim. Gate 3 needs a fold carved from the unused remainder of the corpus, frozen
before it is looked at, with the operating point — including the escalation threshold and the generation
checkpoint — fixed on the development fold and not touched afterwards. Pass requires solving at least as many
as the incumbent at no more than the incumbent's cost, on that fold, on the first and only run.

## What is deliberately not being built

- **KV or logit hand-off between tiers.** Different tokenisers and different model families; impossible, not
  merely hard.
- **A hidden-state probe on the prefill.** Frozen until a load test shows the box saturating. If the box can
  generate a full answer and still have spare capacity, the strongest signal is the finished answer, and the
  probe is a fallback rather than a plan. An `e5` embedding of the prompt reached an AUC of 0.62 on this corpus
  and could not be turned into a policy that beat one categorical feature, which is the prior this probe would
  have to overcome.
- **Self-consistency across samples.** It spends the scarce thing, box capacity, to buy signal.
- **Any TTFT optimisation.** The owner has accepted TTFT regression explicitly; TPOT and throughput are the
  constraints that matter.
- **Retraining or blending the six losing routers.** They stay as recorded negative results, and the incumbent
  stays as the comparison.

## Order of work, fixed

Gate 1 first, because it is free. Then, only if it passes: the box capacity load test — arrival rate stepped up
while TPOT percentiles and queue depth are recorded, with capacity defined as the arrival rate at which TPOT
degrades past its stated limit. **No throughput number is estimated.** A throughput figure assumed rather than
measured moved a published result in this project by a factor of six, and that is why the capacity constraint
is not allowed to enter any optimisation until it has been observed.
