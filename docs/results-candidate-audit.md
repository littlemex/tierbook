# The box belonged in the comparison, and an averages filter was deleting the wrong tiers

**Measured 2026-08-31** on the knowledge multiple-choice corpus: 488 calibration and 699 held-out items with no
overlap, nine candidates including one self-hosted tier billed by the hour.

Two corrections to earlier work here, and they point the same way. A candidate's worth cannot be read off two
averages.

## The self-hosted tier had been excluded, and excluding it was wrong

It was left out of the earlier frontier analysis because it bills by the hour rather than per token, so a
token-price comparison could not include it. That reasoning was fine and the conclusion was not: leaving it out
removed the one tier whose economics differ in kind.

Put back, with its hourly bill amortised over measured per-item latency, it changes both axes.

| | items solved | notes |
|---|---|---|
| any of the eight API tiers | 667 / 699 | |
| **any of the nine, box included** | **671 / 699** | the box is the only solver of **4 items** |

The oracle's bill falls too: $1.2216 at concurrency 1, $1.1212 at 4, $0.8560 at 16.

**And its position on the frontier is decided entirely by a number nobody measured.** The run recorded per-item
latency but not the concurrency it ran at, so the amortised cost per request swings from worst-of-all to
cheapest-by-far:

| concurrency | tasks/hour | $/item | 699 items | against the cheapest API tier ($1.6489) |
|---|---|---|---|---|
| 1 | 1,814 | $0.00839 | $5.87 | dearer than everything |
| **3.6** | | | **$1.6489** | the crossover |
| 4 | 7,254 | $0.00210 | $1.47 | cheaper |
| 16 | 29,017 | $0.00052 | $0.37 | cheaper by 4.5x |

Its quality is 456/699 against the cheapest API tier's 582 -- eighteen points worse -- so it is a cheap-and-weak
frontier point *if* concurrency of about four is achievable, and dominated if it is not. That is the same
unmeasured quantity that once moved a published figure here by a factor of six, and the honest treatment is to
carry the assumption visibly rather than to pick a number.

## Stratifying by input length put three "dominated" tiers back on the frontier

On aggregate, five of eight API tiers are dominated on both average cost and solve count. Recomputed per
input-length bucket:

| bucket | items | frontier |
|---|---|---|
| short | 458 | **six tiers** |
| long | 214 | three tiers |
| aggregate | 699 | three tiers |

Three tiers dominated on aggregate are on the frontier for short inputs, and **the best tier on short inputs is
not the best tier overall**. Cost is a function of token count, so dominance is a relation between cost curves,
not between two scalars, and an average integrates over the boundary a tier is on the right side of.

## So admission is evidence, with three states

`audit()` decides per candidate and records what the decision was conditioned on -- price table, date, item set,
and whether the box's concurrency was measured or assumed. On this corpus:

| state | candidates |
|---|---|
| `active` | gpt-5.6-terra, grok-4.6, claude-sonnet-5, gpt-5.6-sol, claude-opus-5, qwen3.8-27b (the box) |
| `undecided` | claude-fable-5 -- solves 3 items uniquely, but the interval does not clear the stated practical difference |
| `suppressed` | nemotron-super-3-120b, qwen3-next-80b -- dominated in every stratum and unique solver of nothing |

Three properties of this that are deliberate.

**Suppression removes a candidate from routing, never from measurement.** Keeping every tier in the complete
panel costs about seventeen dollars per five thousand items, and that seventeen dollars is the budget that
notices when a price change un-suppresses a tier. A suppressed tier that stops being measured can never come
back.

**`undecided` is a real answer.** A candidate that solves something uniquely but not enough to clear the owner's
stated practical difference is neither routable nor written off. With enough items every candidate solves
*something* uniquely, so "non-zero" is not a threshold.

**Rank instability forces `undecided`, with a tolerance.** Exact-position matching declared eight of nine real
tiers unstable and the audit stopped saying anything; adjacent swaps between candidates separated by fractions of
a point are sampling noise. A move of two places or more is signal.

## How much room a learned router has, measured before building one

`headroom()` bounds what learning could win, and is meant to be run before a GPU is started.

| policy | solved / 699 | residual to oracle | 95% interval |
|---|---|---|---|
| cheapest fixed (the box) | 456 | +0.3076 | [+0.2718, +0.3419] |
| **category, one feature** | **596** | **+0.1073** | **[+0.0858, +0.1302]** |
| oracle cheapest solver | 671 | — | — |

The residual above the existing one-feature router is **10.7 points and its interval excludes zero**, so there is
something for a learned router to capture. The oracle also costs less than that router ($1.1212 against
$1.6523), so the room is in the direction of better *and* cheaper rather than a trade.

Of the 30.8 points between the cheapest fixed tier and the oracle, a single categorical feature already takes 20.
That is the number a learned encoder has to beat, and it is a much harder bar than the floor.

## What this does not support

**One family, one price table, one date.** Every suppression here is conditioned on those and goes stale when any
of them moves. A model update is a new candidate identity, not inherited evidence.

**The box's concurrency is still assumed.** Four is used above because it is the value at which the box becomes
cheaper than the cheapest API tier, which makes it the least favourable assumption that still admits the box.
Measuring it is the next thing worth spending money on.

**The residual is an upper bound on a learned router's win, not a forecast.** It is what a policy with perfect
foresight would take. How much of it is reachable from the prompt alone is a separate measurement, and it has not
been made.
