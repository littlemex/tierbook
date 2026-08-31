# The box's capacity, measured on the traffic it would actually serve: the economics clear, and only the judge is left

**Measured 2026-08-31** on the redeployed `Qwen3.8-27B` (131k window, throughput tune, TP=2 across two replicas
on one `g6e.12xlarge` at $15.2174/hour), driven from inside the cluster so the load generator is not the thing
being measured. This settles the question Addendum 2 of [`PREREG-box-cascade.md`](PREREG-box-cascade.md) declared
undecided, and it settles it in the construction's favour.

## Two sweeps, because the reply length is the whole question

Every request carried a 190-word prompt, near the corpus's mean of 258 prompt tokens, and asked for a fixed
number of output tokens so a throughput figure is not partly a measurement of how talkative the model felt.

| in flight | 4-token replies, req/s | p50 | p95 | 128-token replies, req/s | p50 | p95 |
|---|---|---|---|---|---|---|
| 1 | 5.16 | 0.2 s | 0.2 s | 0.28 | 3.6 s | 3.6 s |
| 16 | 16.21 | 1.0 s | 1.0 s | 3.16 | 5.0 s | 5.1 s |
| 48 | 17.32 | 2.1 s | 3.3 s | 5.50 | 8.4 s | 9.0 s |
| 96 | 17.41 | 5.1 s | 5.7 s | **7.30** | 12.8 s | 13.3 s |
| 128 | **17.60** | 5.9 s | 10.0 s | 7.03 | 13.6 s | 26.8 s |

**A four-token reply is 2.4x the requests a second of a 128-token one, not 32x** — the prefill and the
per-request overhead dominate at that length, which is exactly why the two accountings had to be measured rather
than reasoned about. And request throughput is flat from 16 in flight onwards while latency grows, so 16 is
where a policy should sit: 16.2 requests a second at a p50 of one second.

At the peak, **$0.000240 an item** for a four-token reply and **$0.000579** for a 128-token one.

## What that does to Gate 1

Break-even from Gate 1 was $0.001234 an item. The measured cost of a capped box is **five times under it**.
Recomputing the oracle ceiling with the cap in place and the measured price:

| policy | solved / 699 | API | box | total | against the incumbent |
|---|---|---|---|---|---|
| incumbent, `category` | 596 | $1.6523 | — | $1.6523 | — |
| **oracle judge, box capped at 8 tokens** | **620** | $0.9913 | $0.1679 | **$1.1591** | **+24 solved, 1.43x cheaper** |
| oracle judge, uncapped | 625 | $0.7899 | ≥ $0.4048 | ≥ $1.1947 | +29 solved, ≤ 1.38x cheaper |

The uncapped row is a **lower bound on its cost**: the box's uncapped mean reply is 218.5 tokens, longer than
the 128 the price came from, so the true figure is worse. The capped row is the honest best case, and the cap
costs 5 of the 29 items while saving the runaway generation.

Two corrections this forces on earlier pages, both in the same direction — the box is cheaper than either
estimate, and both estimates were arithmetic rather than measurement:

- Gate 1 said $0.00052 an item at concurrency 16, from a per-item latency divided by a concurrency. Measured at
  this reply length: $0.000240. The method was wrong and the number was pessimistic.
- Addendum 2 corrected it to a request-bound $0.001367, from the earlier table's 128-token replies at 3.3
  requests a second. Measured at four tokens: 17.6. That correction was also wrong, and also pessimistic, for
  the opposite reason — it transferred a measurement across a traffic shape.

The lesson holds in both directions: a number taken from a table measured on other traffic is not a
measurement of this one.

## So the construction now rests on exactly one thing

Cost is settled: at a generation cap the box is a fifth of break-even and the whole construction is 1.43x
cheaper than the incumbent while solving 24 more items — **if the escalation is decided correctly.** Everything
about that "if" is unproven. Gate 2 showed nothing observable in the box's finished answer identifies its errors
(completion length AUC 0.529, truncation covering 7% of traffic), and Gate 2b showed a cap alone gives up 118
items.

The remaining measurement is whether the box's own answer-token distribution separates its short confident
errors. It is now collectable: the redeployed engine returns per-position alternatives, verified on this
deployment — on a four-option question the chosen letter came back at a logprob of −0.023 with the nearest
other letter at −10.90, so a per-item margin exists to threshold. Whether it separates *errors* is the open
question, and it is the last one before Gate 3.

## What this does not support

**These are peak sustained figures at a fixed reply length, not a service level.** At 128 in flight the p95 of a
four-token reply is 10 seconds against a p50 of 5.9, so the queue is deep; the operating point that matters is
16 in flight, and that is the one to quote.

**Prefix caching is off and stays off.** The same prompt sent twice cost the same both times (+2% and +0% in the
two sweeps), as expected for a model with 48 of 64 layers in linear attention. No multi-turn discount exists on
this box, and none is assumed anywhere here.

**The quality figures it recomputes are one run each.** The box's outcomes are not reproducible between runs
even at temperature zero — ±3.7 points on 488 items for the verbose arm — so the +24 and +31 item figures here
are a single run of a noisy arm. See [`results-box-run-to-run-noise.md`](results-box-run-to-run-noise.md). The
cost figures are unaffected: they come from throughput sweeps, not from outcomes.

**One node, one model, one window.** Every figure is conditioned on that configuration, and the earlier table
measured at a 262k window on the same hardware differs by more than a factor of two, which is the size of the
error available from changing a setting.
