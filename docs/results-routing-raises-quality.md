# Routing raised quality at the same price, and the yardstick decides whether that is the point

**Measured 2026-08-30**, out of fold: fitted on 488 calibration items, judged on 699 held-out items with zero
overlap. Eight tiers, all reached through one gateway, priced from that gateway's own rate table.

This page exists because an earlier conclusion in this repository was wrong. That conclusion was that routing
can only lower cost and never raise quality, generalised from strict nesting observed on two coding corpora.
On this corpus it is false, and the refutation is not subtle.

## The result

| policy | solved / 699 | spend | vs. this baseline |
|---|---|---|---|
| cheapest single tier (`gpt-5.6-terra`) | 582 | $1.6489 | — |
| **category-bucket routing, margin 0.10** | **596** | **$1.6523** | **+2.00 pt quality, +0.2% cost** |
| middle single tier (`grok-4.6`) | 612 | $2.3200 | +4.3 pt, +40.7% |
| strongest single tier (`claude-opus-5`) | 635 | $3.7455 | +7.6 pt, +127% |
| oracle cheapest solver (unreachable) | 662 | $1.2150 | +11.5 pt, −26% |

Against the cheapest tier the paired difference is **+0.0200 with a 95% interval of [+0.0072, +0.0329]**. The
interval excludes zero, so on this corpus routing bought quality rather than trading it away, at a cost
difference of two tenths of one percent.

## The comparison decides the answer, so the comparison is the finding

The same policy, the same held-out items, three different baselines:

| baseline | margin | verdict | quality difference | cost |
|---|---|---|---|---|
| `gpt-5.6-terra` (cheapest) | 0.10 | passes | **+0.0200** [+0.0072, +0.0329] | +0.2% |
| `grok-4.6` (middle) | 0.05 | passes | −0.0029 [−0.0117, +0.0059] | +12.1% |
| `claude-opus-5` (strongest) | 0.10 | passes | −0.0558 [−0.0741, −0.0374] | **−55.9%** |
| `claude-opus-5` (strongest) | 0.05 | **undetermined** | −0.0358 [−0.0534, −0.0181] | −30.6% |

**Reporting only the last row would have been the flattering choice and the misleading one.** "55.9% cheaper"
is true and it is measured against the most expensive thing on offer. Switching from the strongest tier to
`grok-4.6` — no routing at all, one line of configuration — already gets 38% of that saving for 23 fewer
correct. A router has to be compared with the best *single* option on the frontier, not with the strongest one,
or it is being credited with a saving that any operator could have had for free.

So the baseline is now taken from the calibration fold's own frontier rather than chosen by quality alone.

## The three-valued verdict earned its keep immediately

The `claude-opus-5` row at margin 0.05 is `undetermined`: the interval [−0.0534, −0.0181] straddles the target
of −0.05, so this sample does not decide it either way. A two-valued verdict would have called that a failure.

That distinction is not academic here. The error it prevents is the one this project made: one twenty-item arm
lost, the result was read as a defeat, and a whole class of approach was removed from scope on the strength of
it. An inconclusive sample lowers the priority of an experiment. It does not change a product goal.

## What the labels look like, and why that decides what to build

The outcome table makes the shape of the problem visible in a way a per-family average cannot.

| tiers that solved the item | items |
|---|---|
| 8 of 8 | **299** |
| 7 | 160 |
| 6 | 106 |
| 5 | 37 |
| 4 | 18 |
| 3 | 21 |
| 2 | 13 |
| 1 | 13 |
| **0** | **32** |

Three readings, each of which changes what is worth building.

**299 items are solved by every tier.** These need the cheapest tier and no prediction at all. This is where the
money is, and a predictor is not required to find it — a price list is.

**13 items are solved by exactly one tier.** Picking that one out of eight from the prompt alone is where a
prompt-only predictor is weakest, and it is only 1.9% of the corpus. The quality headroom is thin and
concentrated.

**32 items are solved by nobody.** No router reaches them. Any progress claimed against the oracle without
subtracting this floor is overstated by 4.6 points.

## Where this sits in the published results, and why the yardstick differs

Two things need separating here, and an earlier draft of this page ran them together.

**What the literature actually says, quoted rather than paraphrased.** LLMRouterBench (arXiv:2601.07206, 400k+
instances, 21 datasets, 33 models) reports that "several recent approaches, including commercial routers, fail
to reliably outperform a simple baseline", and that "a substantial gap remains to the Oracle, driven primarily
by persistent model-recall failures". RouterBench (arXiv:2403.12031, 405k outcomes) frames itself as addressing
"balancing performance with cost". An earlier draft of this page asserted that both conclude no router beats
the *best single model*; that specific wording could not be confirmed from the primary sources and has been
withdrawn in favour of the quoted text.

**Cost is not what distinguishes this project from that work.** It would be convenient to say the published
routers optimise quality alone, and it is not true: RouterBench is explicitly about balancing performance with
cost, LLMRouterBench provides metrics for "performance-cost trade-off routing", and FrugalGPT, RouteLLM, Hybrid
LLM and PILOT are all cost-aware by construction.

What differs is the shape of the objective.

  * **Three axes, not two.** Latency enters, and for a fixed-cost tier it enters through throughput, so the same
    tier's cost per request moved by a factor of three between two families here. A two-axis frontier cannot
    express that.
  * **Constraints the owner states, not a scalarised score.** Quality is a floor with a margin, reliability is
    its own constraint, and there is no weight vector -- because the exchange rate between a defect and a dollar
    cannot be set from inside.
  * **Non-dominated options, not a recommendation.** `frontier()` returns every policy nothing else dominates
    and marks the rest. The owner picks.
  * **Refusal is an action.** If nothing satisfies the stated constraints, the answer is to refuse.

On that objective, "did the router beat the best single model" is not the question asked. Both of these are
frontier points and neither is a defeat: 2.0 points above the cheapest tier at the same money, and 5.6 points
below the strongest at 56% less. The frontier code already treats them that way; it was this page's prose that
borrowed a single-axis yardstick.

**One point of direct agreement with the literature.** LLMRouterBench attributes the remaining gap to the oracle
to "persistent model-recall failures" -- the router failing to recall which model can solve an item. That is
exactly the shape of the histogram above: 13 items are solved by exactly one of eight tiers, and finding that
one from the prompt is the hard part. The agreement is worth more than the disagreement would have been,
because it says the bottleneck found here is the one the field has found at scale.

**And the policy really is a single dictionary lookup**, since a reviewer asked whether the gain was a cascade in
disguise. `bucket_policy` maps one feature value to one tier and calls it once: no cascade, no second attempt,
no ensemble, no escalation.

## What this does not support

**One family.** Knowledge multiple-choice. The two coding corpora in this repository nested strictly, and
`tau-bench` did not — so whether routing raises quality is a per-family property, and this page is one family's
answer.

**One feature.** The bucket is the benchmark's own category label, which a production router does not get for
free: it has to be predicted, and a classifier's label is not the benchmark's label. The +2.00 pt figure is
therefore an upper bound on what the same policy achieves behind a real classifier.

**Label volume is one to two orders of magnitude below the published encoder routers, by the measure that
matters.** By training examples the gap is smaller than it looks: 1,187 items x 8 tiers is 9,496 (item, tier)
pairs, which is the same order as Hybrid LLM's 10,000. By **distinct prompts** it is 1,187 against 10,000 to
120,000, and for a text encoder distinct prompts is the binding constraint -- the eight heads see the same
1,187 inputs. The bucket policy here sidesteps that because it consumes a categorical label rather than text; a
learned encoder will not.

**No prompt-only ceiling yet.** The three bounds the design calls for — full-information oracle, empirical
ceiling from prompt features alone, and irreducible ambiguity — only the first is computed here (0.9542 on the
cost-complete subset). Until the second exists, the gap between this policy and the oracle cannot be
attributed between missing information, finite sample and a weak model.

**Six items have no cost.** One tier lost its token counts on 6 of 699 rows. Those items are excluded from the
cost figures and counted, rather than the tier being dropped or the missing cost being read as zero — the
latter once produced a 3.0x headline here that rested on treating a model as free.
