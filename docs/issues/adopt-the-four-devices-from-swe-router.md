# Adopt four devices from swe-router, and none of its mechanism

**Status: backlog.** Stage 1 needs no GPU and no new measurement -- it runs on arms already recorded.

Source: [`aarora79/agentic-coding-harness-benchmarks/vend/swe-router`](https://github.com/aarora79/agentic-coding-harness-benchmarks/tree/main/vend/swe-router).
18 models on 21 tasks from one repository, frozen into a generated `models.json` and a 446-line `route.py`.

## The distinction this issue rests on

That project's **mechanism** is the thing SCOPE forbids: a measurement frozen on a date, plus a lookup. Its
`provenance.measured_on` is a single day and its `source_commit` a single commit; the decision procedure reads the
table. Under a moving environment -- prices, quotas, availability, a model revision -- a lookup is a tuned box, and this
project has produced one three times and been told three times not to.

Its **epistemics** are better than ours in four specific places, and each is portable without the table. That is what
this issue is for. Nothing here copies a number from it; two of the four say explicitly that its number must be
replaced by one measured here.

## Device 1 -- the tie band must be a reading, and ours is a configured value

**This is the one worth doing first, and it can be done today.**

swe-router sets its tie band by measuring order stability: drop a single task from a tier and count how often two
models change places. It reports 82% of the time when they sit within 1 point, 53% within 2, 47% within 3, 5% past 5,
and never past 8 -- then treats anything under 3 points as a tie and takes the cheaper model. The threshold is a
reading, not a preference.

Ours is a preference. `tierbook.policy.assign_family` takes `margin: float` as a keyword argument, and
`tierbook/cli.py` requires `--margin` or reads it from a config, exiting when neither supplies one. Whatever value goes
in is an operator's judgement about how much accuracy to buy, and nothing in the repository says how large a gap has to
be before it survives dropping one item.

**What to build.** A jackknife over an already-recorded paired cohort: for each pair of candidates and each item, drop
that item, recompute both rates, and record whether the order reversed. Bucket by the gap and report the reversal rate
per bucket, which is the same table swe-router published and the number `--margin` should be read against.

**The data exists.** The box-versus-API paired comparison covers 21-22 items with both arms scored, and the box was run
twice on the same items. No GPU time and no new sweep: this is arithmetic over `joined-*.json` files already on disk.

**What it changes.** `--margin` stops being required-from-a-human and becomes a value the compiler can supply with a
provenance, and can refuse to supply when the cohort is too small to estimate it. The refusal is as much the point as
the number: a gap smaller than the measured reversal band is not a difference, and the compiler currently has no way to
say so.

## Device 2 -- consequence sets the floor, difficulty picks which measurement to read

swe-router keeps two questions apart. *What happens if this is wrong* sets a floor. *How hard is this* does not touch
the floor; it selects which measured score is compared against it. Collapsing them -- treating a big task as a
high-stakes one -- is how the top model ends up writing a docs page.

They support it with a measurement rather than an argument. Five tasks all classed `trivial`, every one a single-file
change, ranged from a 0.4-point gap between best and second-best to a 13.8-point gap. Three were mechanical; two turned
on knowing one exact thing. Same size, opposite answers -- so "hinges on one specific fact" gets +5 on the floor and
size gets nothing.

**What to build.** `assign_family` currently takes one `margin` and one aggregate quality bound per candidate. The
floor should arrive as a consequence class stated by the caller, and the quality bound should be read per difficulty
stratum rather than pooled. Both are changes to what the compiler reads, not to how it ranks.

**What has to be measured first, and it is not free.** A per-stratum bound needs enough items per stratum to bound
anything. The pilot subset is 24 items with one permanently unscoreable, which will not carry four strata. This device
is therefore blocked on cohort size, and the issue records it as blocked rather than as available.

**Do not adopt their difficulty input.** In swe-router the tier is assigned by the assistant itself at call time, so
the whole selection rests on a self-report that nothing checks. This project has already measured what that costs
elsewhere: 59% of a planning intervention's apparent gain was obtainable with no reasoning at all, and a leakage check
beat every self-assessment. A stratum has to come from something observable about the request, or the stratum is the
model's opinion of itself.

## Device 3 -- never average over a failure, and report the count beside the mean

swe-router excludes a failed task from the mean rather than averaging it in, and prints the completion count next to
every score, in bold where a model failed at least one task in that tier. So `qwen3.8` scoring 71.5 on `high` is its
average over the four hard tasks it finished, and the fifth is simply absent -- which no score can show.

We already do the equivalent on the measurement side: `staging_check.py` names a permanently unscoreable item and takes
it out of the denominator, and `read_arm.py` reports zero-edit runs beside the solve count. The gap is on the
**compile** side: a candidate's quality bound is one number, and a reader cannot see how many items it is over.

**What to build.** Carry the attempted-and-scored count with every bound the compiler reads, and print it beside the
bound in `report.py`. A bound over 4 items and a bound over 24 should not look the same in a report, and today they do.

## Device 4 -- a floor met by a mean is missed on the harder half by construction

The observation is theirs and it is correct: a tier score is a mean, so a candidate sitting near the floor falls below
it on the harder half of that tier by arithmetic. Their measured consequence: at a floor of 70 the router's pick
actually cleared the floor on 18 of 21 tasks, and asking for +5 of headroom moved that to 20 of 21 for $1.58 more per
task.

Their honest summary is the part worth copying: not "the same quality for less" but **86% of the bar for an eighth of
the price**, with the trade named rather than hidden.

**What to build.** Distinguish a bound that clears the floor from a bound that clears it *by more than the tie band from
device 1*, and say which in the report. This is the same distinction their `margin_is_meaningful` makes, and it is
cheap once device 1 has produced a band.

## What is deliberately not adopted

| Not taking | Why |
|---|---|
| `models.json` as a decision input | A measurement frozen on one date is the tuned box SCOPE forbids. Numbers may be read for orientation; nothing selects from them. |
| Any number from their tables | One repository, one LLM judge (`openai.gpt-5.6-sol`, repo-grounded, no control for a broken answer key), one run per model per task at 5-6 items per tier. Their own reversal statistics say orders under 3 points are coin flips, and the router selects on exactly those. |
| Their self-hosted cost basis | Hourly price divided by throughput at a stated concurrency. This project has twice produced a fake throughput peak by not saturating the generator or exhausting `max_num_seqs`, and once moved a per-task cost by 6x through one coefficient, changing the selection. A cost per task on that basis is a lower bound wearing a point estimate's clothes. |
| A single up-front pick | What was measured to work here is a cheapest-first cascade with a margin judge at AUC 0.838, quality held and cost down 10.7%. A method that recommends once and stops cannot express that. |
| `on_combined_frontier` | It mixes hosting bases. They say so themselves and mark it context rather than a selection key. |

## Order, and what ends each part

1. **Device 1**, on recorded data, no GPU. Ends if the cohort is too small to produce a stable reversal curve -- in which
   case the finding is that `--margin` cannot yet be derived here, which is worth knowing and is not what the
   repository currently implies.
2. **Devices 3 and 4**, once device 1 has a band. Both are report-side and small.
3. **Device 2**, blocked on cohort size. Not started until a stratum can be bounded.
