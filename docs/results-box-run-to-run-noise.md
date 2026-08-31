# The self-hosted box is not reproducible, temperature zero does not fix it, and the noise scales with how much it generates

**Measured 2026-08-31** on the MoE box, six runs of the same 488 calibration items through the same deployment,
differing only in the decoding temperature, the client's concurrency, and whether the model was told to answer
tersely. This qualifies several numbers already reported here, which is why it is its own page.

## The measurement

| arm | reply length | run A | run B | outcomes that flipped | byte-identical answers |
|---|---|---|---|---|---|
| terse, greedy, 1 in flight | 59 tokens | 328 | 327 | **1.8%** | **96.3%** |
| terse, greedy, 16 in flight | 59 tokens | 329 | 321 | 3.3% | 92.0% |
| verbose, greedy, 16 in flight | 886 tokens | 362 | 359 | 8.0% | **12.1%** |
| verbose, sampled, 16 in flight | 895 tokens | 353 | 371 | 10.2% | 6.8% |

Three things follow, and the first is the one that surprised me.

**Temperature zero does not make it deterministic.** Greedy decoding on the verbose arm reproduced the previous
answer byte-for-byte on 12.1% of items. Sampling was not the source of the variation; it merely added to it.
What remains is the serving stack: under concurrency, a step's batch composition decides the order of the
reductions inside it, which moves the logits in the last bits, which flips a greedy argmax somewhere — and once
one token differs the rest of the generation follows a different path.

**The concurrency contributes, but it is not the whole cause.** Dropping the client from 16 in flight to 1
raised the terse arm's byte-identical share from 92.0% to 96.3% and halved the outcome flips. It did not reach
100%, so a run alone on the machine is still not a repeat of the previous one.

**Generation length is what dominates.** 59 tokens reproduces 92 to 96% of the time; 886 tokens reproduces 12%
of the time. The mechanism compounds per token, so a model that explains before answering is far less
reproducible than the same model told to answer directly — on the same weights, the same engine and the same
questions.

## What it does to the numbers already reported

Expressed as what one run can carry: **±1.6 points on 488 items for the terse arm and ±3.7 for the verbose
arm**, from the spread of the runs above.

| claim | arm it rests on | status |
|---|---|---|
| Gate 2c: −0.43 pt against the incumbent, interval [−1.14, +0.14] | terse | **unaffected** — it was reported as indistinguishable, and the run noise says the same thing more strongly |
| The terse arm loses 7.0 points to the verbose arm | both | **holds** — across runs the verbose arm sits at 353/362/371 and the terse at 319/321/329, so the gap is around 8 points and larger than either noise |
| Gate 1: the MoE ceiling is +4.43 pt over the incumbent, interval [+3.00, +6.15] | verbose | **weakened** — the point estimate is barely outside a ±3.7 point run-to-run spread, and the bootstrap interval measures sampling over items, not over runs. It needs repeats before it is quoted as a gain |
| The MoE solves 531 of 699 against the dense model's 456 | verbose, both | **holds in direction** — 75 items is far outside the noise, though the exact figure is one run of each |

The general form of the mistake this avoids: **a bootstrap interval over items is not an interval over runs.**
Every confidence interval in these documents resamples the 488 or 699 items of one run, which answers "how much
would this differ on other questions" and says nothing about "how much would this differ if I asked again". For
the verbose box arm the second is the larger of the two.

## What to do about it, and what not to

**The policy uses the terse arm, which is the reproducible one.** That is not a lucky accident to lean on: it is
reproducible *because* it is short, and it is short because that is what made its answer-position logprobs
readable in the first place. The construction that survived the gates is the one whose measurements are stable.

**Repeats are the fix, and they are cheap on the terse arm.** A terse pass over 488 items takes about two
minutes of a node that costs $15.2174 an hour, so three repeats cost about a quarter of a dollar. The verbose
arm costs ten minutes a pass and is the arm that needs them most.

**Not the fix: turning the concurrency down to buy determinism.** It buys 4 points of byte-identity and costs
most of the machine's throughput, and the throughput is what makes the box's amortised cost defensible at all.

**Not a defect to report upstream.** Batch-composition-dependent reductions are how a batching engine works, and
vLLM does not promise otherwise. The defect was in treating one run of it as a measurement.
