# Gate 2b: the generation cap fails on quality, and in failing it makes the box's bill 55x smaller

**Measured 2026-08-31** against Addendum 2 of [`PREREG-box-cascade.md`](PREREG-box-cascade.md). One fitted
parameter, one evaluation on the development fold, both pass arms registered beforehand. It fails both, and the
byproduct changes what the construction's remaining question is.

## The registered result

The policy: the box generates at most `k` tokens; if it answered within `k` that answer stands, otherwise the
item escalates to the incumbent's choice. `k` was fitted on the 488-item calibration fold at **1024** — the
largest solve count inside the incumbent's budget under both cost accountings, at 327 against the incumbent's
413.

On the development fold, once:

| | solved / 699 | API spend | total, token-bound | total, request-bound |
|---|---|---|---|---|
| incumbent | 596 | $1.6523 | — | — |
| **cap at k = 1024** | **478** | $0.2885 | $1.4448 | $1.2440 |

Quality **−16.88 points, interval [−20.31, −13.45]**. Arm 1 required more than 596; arm 2 required at least 596
at three quarters the cost. **Both fail**, and not narrowly.

The reason is the one Gate 2 already found, in a different costume. A cap escalates an item only if the box's
generation ran long, and the box's errors are mostly short: of its 179 errors on the calibration fold, only 86
are long enough for any cap to catch, and the remaining 145 are short confident wrong answers that every member
of this family keeps.

## The byproduct is the useful part

The box's own token bill is almost entirely a tail it does not need to generate. Over the 699 development items:

| | box output tokens | box bill, token-bound |
|---|---|---|
| uncapped, as recorded | 152,749 | $1.6314 |
| **capped at 8 tokens** | **3,284** | **$0.0351** |
| capped at 4 tokens | 2,796 | $0.0299 |

**A 55x reduction**, because the median reply is 4 tokens and the mean of 218.5 is an artefact of the runaway
tail. Under the token-bound accounting the box stops being an expensive component at all.

Which puts the whole construction on one unmeasured number. Take Gate 1's oracle escalation and a 4-token cap
together:

| | solved / 699 | total, token-bound | total, request-bound |
|---|---|---|---|
| incumbent | 596 | $1.6523 | $1.6523 |
| **oracle escalation, box capped at 4** | **625** | **$0.8198** | **$1.7454** |

Token-bound, that is 29 more items solved at **half the cost**. Request-bound, it is 29 more items at **5.6%
more**. The two accountings disagree about whether the construction is worth building at all, which the
pre-registration declared makes it undecided, and the thing that decides them is measurable: **what the box's
request throughput is on this traffic shape** — a few hundred prompt tokens and a four-token reply — as against
the 128-token replies the existing throughput table was measured on. Token-bound is right if the box is limited
by tokens generated; request-bound is right if a short request costs about what a 128-token one costs.

## So there are exactly two open questions, and one GPU run answers both

1. **Request throughput at this traffic shape.** Replay the corpus's prompts at stepped concurrency with the
   generation cap in place, and record sustained requests a second with TPOT percentiles. This decides between
   the two rows above, and it is the measurement Gate 1 wrongly believed was missing and Addendum 2 corrected.
2. **Whether the box's logprobs separate its short confident errors.** Everything observable in the recorded
   run fails at this: completion length has an AUC of 0.529 and truncation covers 7% of traffic. The answer-token
   distribution — the margin between the top two options, the entropy at the answer position — has not been
   collected. It is the only remaining candidate for a judge, and without a judge the ceiling is unreachable.

Both come from one replay of 1,187 prompts against a redeployed `Qwen3.8-27B`, at no API cost. If the logprob
signal fails as well, the construction is finished on this corpus and the recorded finding is that a
self-hosted tier can be right where a frontier tier is wrong on 4% of items and **cannot be told when**.

## What this does not support

**The cap's cost saving is not a quality-neutral saving.** Capping at 4 tokens with no judge solves 326 on the
calibration fold against the incumbent's 413. The $0.0299 box bill is only interesting in combination with a
judge that escalates on something other than length.

**Both cost accountings rest on a table measured at a different traffic shape** (262k window, 128-token
replies, throughput tune). Neither is a measurement of this policy; they are the bounds the measurement will
fall between.

**The development fold has now selected three times.** Nothing in this page is a claim about held-out
performance, and the frozen fold stays untouched until there is something worth spending it on.
