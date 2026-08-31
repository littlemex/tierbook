# Gate 1: the box-first construction clears the incumbent on quality and halves the API bill, and its own bill decides everything

**Measured 2026-08-31** on the 699-item development fold of the knowledge multiple-choice corpus, against the
pre-registration in [`PREREG-box-cascade.md`](PREREG-box-cascade.md), which was committed before any figure
here was computed. Nothing was spent to produce it: the gate reuses outcomes already recorded.

The construction: the self-hosted tier answers every item, and an item escalates to the incumbent router's own
choice when the box is wrong. Gate 1 makes that escalation decision with the recorded outcome, so what follows
is the **ceiling** of the construction and not a policy.

## The registered gate passes

| | solved / 699 | API spend |
|---|---|---|
| box alone | 456 | none, it bills by the hour |
| incumbent — `category`, one feature | 596 | $1.6523 |
| **the ceiling of this construction** | **625** | **$0.7899** |

Quality gain over the incumbent **+4.15 points, 95% interval [+2.72, +5.58]**, and the API bill falls **52.2%**
because only the 34.8% of items the box gets wrong are ever sent to an API tier. Both registered conditions
were "above 596 with the interval excluding zero" and "at most $1.6523", and both hold with room.

## The whole gain is the 29 items where the cheap tier beats the dear one

Against the incumbent, item by item:

| | count |
|---|---|
| both correct | 427 |
| **box correct, incumbent wrong** | **29** |
| incumbent correct, box wrong | 169 |
| neither | 74 |

The ceiling cannot lose an item the incumbent solved — if the box is right it keeps the answer, and if the box
is wrong the item goes to the incumbent's own choice — so the entire +29 is the middle row. That fixes what a
real judge is for, and it is not what the phrase "escalation judge" suggests. The judge does not have to spot
hard items; it has to **keep the 29 items where a 27B self-hosted model is right and a frontier API tier is
wrong**, while escalating the 243 where the box is wrong. A judge tuned to escalate whenever it is unsure gives
up the quality gain first and keeps only the cost saving.

The 74 items nothing solves are the floor, and the 169 the box misses are what the API budget is actually
buying at $0.00325 an item.

## The unmeasured concurrency decides whether the owner saves anything

The API saving is $0.8624 over 699 items, which is **$0.001234 per item**. That is the exact amortised price at
which the box's own bill cancels the saving. At $15.2174/hour and the recorded per-item latency, the box's
amortised cost is $0.00839 per item at concurrency 1, so the break-even concurrency is **6.80**.

| box concurrency | box $/item | total, API + box | against the incumbent's $1.6523 |
|---|---|---|---|
| **2 — what the deployment is configured for** | $0.00419 | **$3.7222** | 2.25x dearer |
| 4 | $0.00210 | $2.2560 | 1.37x dearer |
| **6.8** | $0.00123 | $1.6523 | the crossover |
| 8 | $0.00105 | $1.5230 | cheaper |
| 16 | $0.00052 | $1.1564 | cheaper by 1.43x |

The running deployment is started with `--max-num-seqs=2`, recorded in `vsr/pool.yaml` as a serving argument
rather than as a measured ceiling. **At that configuration this construction costs more than twice the
incumbent** even with a perfect judge, and the extra $2.07 buys 29 items. Raising the flag is one line; what
it does to TPOT and to queueing at this model size is not known, and this project has already moved a published
figure by a factor of six by assuming a throughput instead of measuring one.

So Gate 1's verdict is: **the construction is worth continuing, and the next thing to measure is capacity, not
a classifier.** The pre-registration ordered the capacity load test ahead of the judge, and this result is the
reason that ordering matters rather than a formality — a judge fitted before capacity is known could be perfect
and still lose the owner money.

## Reproducing it

`escalation_ceiling()` in `audit.py` computes the table above from an outcome table, a default tier and a
fallback policy. It reports `total_usd` as `None` unless an amortised per-item price for the default tier is
passed in, so the hourly tier is never silently charged as free, and it returns `break_even_usd_per_item` so the
measurement that decides the construction is a number rather than a judgement.

The incumbent was refitted from the calibration fold before this was computed and reproduced its published
figures exactly — 596 solved and $1.652295 — which is what licenses comparing against them.

## What this does not support

**The escalation oracle knows the answer, and a judge will not.** Every false escalation spends API money the
saving is made of, and every missed escalation loses an item the incumbent would have solved. The $0.7899 is a
floor on the API bill for this escalation rate, not a forecast.

**One item's escalation is unpriced.** The incumbent's chosen tier failed the call on it and recorded no
tokens, so it is counted and not charged; the same item is unpriced in the incumbent's published figure.

**These 699 items are development data.** They have now chosen between seven constructions. The decision
belongs on a fold that has never been used, as registered, with the operating point fixed beforehand.

**The 29 items are 4.15 points on one corpus in one family.** Whether a cheap self-hosted model beats frontier
tiers on some items in other families is a separate measurement, and the one place it was checked before — the
agentic coding corpus — the box's successes were a strict subset of the API tiers' and this row was empty.
