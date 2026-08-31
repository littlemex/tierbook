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

## Addendum, 2026-08-31: the Gate 2 judge, fixed before the development fold is touched

Registered after Gate 1 passed and before any Gate 2 figure is computed, because Gate 1 revealed a cheaper
judge than the one this document assumed and the substitution has to be declared rather than discovered.

The recorded run carries no logprobs, so the entropy and logit-margin features listed above cannot be computed
without re-running the box on a GPU. What it does carry, per item, is what the box produced: **the number of
completion tokens, the finish reason, and whether an answer could be extracted from the text.** Those are
available after the box answers and before an escalation decision, which is exactly the information this
construction gets to use.

They are also more interesting than they look. The box's output length is bimodal — a median of 4 tokens
against a mean of 218.5, a 95th percentile of 2005 and a maximum of 2048, which is the generation cap. Most
answers are the letter and nothing else; a minority run away until they are cut off.

**Judge family, fixed now:** escalate if the box's completion length is at least a threshold, or its finish
reason is the length cap, or no answer could be extracted. The threshold is the only fitted parameter and it is
chosen **on the 488-item calibration fold** by maximising solves subject to the API spend staying within the
incumbent's, with ties broken towards the cheaper threshold.

**Evaluated once** on the 699-item development fold. Pass requires solving more than 596 with the lower bound
of the paired difference above zero, and API spend at most $1.6523. Fail, and the finding is that a judge built
from what the run already recorded is not enough, and the next question is whether logprobs are worth a GPU —
not a second threshold family on the same fold.

The order in the main document is unchanged in intent: this judge is free, and running it before the capacity
load test only reorders two measurements neither of which can affect the other's result. If Gate 2 fails there
is nothing for the capacity number to rescue.

## Addendum 2, 2026-08-31: a correction to Gate 1's cost column, and the generation cap as the registered Gate 2b

Written before any Gate 2b figure is computed. Two things forced this: Gate 2's judge failed, and the capacity
number Gate 1 said was unmeasured turns out to have been measured a week earlier, in
`serving/models/qwen3.8-27b/profiles.env`, on this box at the 262k window with 128-token replies.

**The correction.** Gate 1 quoted the box's amortised cost as $0.00839 per item at concurrency 1 falling to
$0.00052 at 16. That second figure came from dividing a per-item latency by a concurrency, which is the exact
arithmetic this project has already been burned by. Against the measured throughput table the box never gets
there:

| in flight | measured output tok/s | $/item, token-bound | $/item, request-bound |
|---|---|---|---|
| 16 | 306.7 | $0.003011 | $0.001764 |
| 48 — the measured knee | 395.7 | $0.002334 | $0.001367 |
| 96 | 423.4 | $0.002181 | $0.001278 |

Token-bound prices the box's own output at the measured rate and assumes the recorded mean of 218.5 output
tokens an item; request-bound assumes the box's cost is per request at the rate the measured 128-token replies
imply, which is the right model when replies are short and the prefill dominates. Break-even from Gate 1 is
**$0.001234 an item**. Under both accountings, at every measured concurrency, **the box's own bill exceeds the
API saving even with a perfect judge.** Gate 1's quality result stands; its cost column was too kind, and the
oracle construction as measured loses money.

**What is left, and it is not a better classifier.** The box's bill is dominated by a tail it does not need to
generate: the median reply is 4 tokens, the mean is 218.5, and the 95th percentile is 2005 against a 2048 cap.
Capping generation attacks the only term that can move, and the capped items are the ones Gate 2 already showed
are 91% wrong. So the registered Gate 2b is the owner's original question — how far to let the box generate —
with cost as the objective rather than accuracy:

**Policy family:** the box generates at most `k` tokens. If it produced an answer within `k`, that answer stands;
otherwise the item escalates to the incumbent's choice. This is computable from the recorded run without a GPU:
an item whose recorded completion was at most `k` is unaffected, and one that ran longer had no answer at `k`.

**Cost, reported under both accountings and never one:** API spend on escalated items, plus the box's bill from
`sum(min(completion_tokens, k))` at the measured token rate, and separately plus a flat per-request box cost at
the measured knee. A conclusion that holds under one and not the other is reported as undecided.

**`k` is fitted on the 488-item calibration fold** over `k` in {4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048},
choosing the point that maximises solves subject to total cost at or below the incumbent's, ties to the smaller
`k`. **Evaluated once on the 699-item development fold.**

**Pass** on either arm, both registered now so neither is chosen after the fact:

1. more than 596 solved with the paired interval excluding zero, and total cost at or below $1.6523; or
2. at least 596 solved with the paired lower bound no worse than −0.5 points, and total cost at or below
   **$1.2392**, which is three quarters of the incumbent's. Same quality materially cheaper is a win, and
   saying so in advance stops it from becoming a consolation prize discovered afterwards.

**The development fold has now been looked at three times.** Its numbers are no longer a claim about anything;
they select. The claim requires Gate 3 on the frozen fold, and if Gate 2b passes, the frozen fold is carved
before anything else is measured.

## Addendum 3, 2026-08-31: the box is now the MoE, and its verbosity is the only cost lever left

Written before the terse arm is run. The self-hosted lane moved from the dense `Qwen3.8-27B` to the MoE
`Qwen3.6-35B-A3B`, because every other self-hosted number in this project was measured on the MoE and it
measured better on every axis taken. That makes it a **different candidate**, so Gate 1 was recomputed rather
than inherited, on the same 699 item ids with the same eight API tiers.

It is better where it matters and worse where it costs. Box alone 531 against the dense model's 456; the
ceiling 627 against 625; escalation 24.0% against 34.8%, so the API bill falls to $0.6789. And its median reply
is **687 tokens against the dense model's 4** — it explains before answering, with thinking off, which is
where its extra accuracy comes from and also where its bill comes from.

Measured on this deployment at 877-token replies, the box's own price per output token bottoms out at
**$1.67/Mtok at 128 in flight**, which is the engine's admission cap; the $1.57 the sweep reports at 192 is
queueing outside the engine at a p95 of 101 seconds and is not an operating point. Break-even needs
**$1.59/Mtok**. So with a perfect judge the construction lands **3% dearer than the incumbent while solving 31
more items** — a wash on money, and any real judge's mistakes come out of that.

**The registered question, then: does telling it to answer with the letter alone keep the accuracy?** One
instruction prepended to the question, the question itself byte-identical, recorded on every row so the arm
says what it was told. Run on the **488-item calibration fold only**.

Two conditions, both fixed now, and the arm is only worth carrying if it meets both:

1. **Cost.** The box's own bill per item at the measured operating point must fall below the break-even
   $0.001393, which at 128 in flight means a mean reply under about 830 tokens — a bar the verbose arm misses
   by 6% and a terse arm should clear by an order of magnitude.
2. **Accuracy.** The terse arm must stay within **3 points** of the verbose arm's 353/488 on the same fold,
   so at least 69.3%. Below that, the verbosity *is* the accuracy, this lever is closed, and the honest finding
   is that the MoE box buys 31 items at cost parity and cannot be made cheaper without giving them back.

If the lever closes, the next question is not another prompt. It is whether 31 items at parity is worth a
machine, which is a question for the owner and not for a measurement.
