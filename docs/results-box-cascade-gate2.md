# Gate 2: the free judge fails, because the box is wrong in four tokens as often as in two thousand

**Measured 2026-08-31** against the addendum in [`PREREG-box-cascade.md`](PREREG-box-cascade.md), which fixed
the judge family and the fitting rule before the development fold was touched. One fitted judge, one evaluation,
as registered. It fails, and the way it fails is more useful than the failure.

## The registered result

The judge family was: escalate if the box's completion length reaches a threshold, or its finish reason is the
generation cap, or no answer could be parsed. The threshold was fitted on the 488-item calibration fold by
maximising solves subject to API spend staying inside the incumbent's.

**The fitting rule selected the degenerate member.** With a median completion length of 4 tokens, any threshold
at or below 4 escalates everything — which is the incumbent router with a GPU bill attached. That member
maximises calibration solves (413, identical to the incumbent) and spends exactly the incumbent's budget, so the
rule as written picked it.

Evaluated once on the development fold:

| | solved / 699 | API spend | quality gain |
|---|---|---|---|
| incumbent | 596 | $1.6523 | — |
| **Gate 2 judge, threshold 1** | **596** | **$1.6523** | **0.0, interval [0.0, 0.0]** |
| Gate 1 ceiling, for reference | 625 | $0.7899 | +4.15, [+2.72, +5.58] |

Escalated 699 of 699, of which 456 were items the box had already answered correctly. **Gate 2 fails**: the
registered pass condition was more than 596 solved with the interval excluding zero, and this is the incumbent
exactly.

## Why no member of the family could have passed

Measured on the calibration fold, which is the fold the judge was allowed to see:

- **Completion length has an AUC of 0.529 for "the box is wrong".** The median length is 4 tokens whether the
  box is right or wrong. There is nothing to threshold.
- **Truncation is precise and rare.** Of the 34 items cut off at the 2048-token cap, 31 were wrong — 91%
  against a base rate of 37%. That is a strong signal covering 7% of traffic.
- **So the reachable version of this judge escalates 34 items and gains 19 solves** (309 to 328 on the
  calibration fold), against the incumbent's 413. The remaining 145 box errors are **short, confident, wrong
  answers**, and every signal in this family is blind to them.

The whole family therefore sits between two useless corners: escalate everything and be the incumbent, or
escalate the runaways and keep 145 wrong answers. The sweep on the calibration fold shows no member in between,
because the feature separating the corners does not separate right from wrong.

## What this does and does not kill

**It kills the free judge, not the construction.** Gate 1's ceiling stands: escalating on the box's actual
correctness solves 29 more items than the incumbent while spending 52% less on APIs. The gap between that
ceiling and this floor is entirely the judge's, and the registered next question is whether a signal the run did
not record — token-level logprobs, entropy, the margin between the top two answer options — separates the short
confident errors that length cannot.

**It changes what the next spend is for.** The pre-registration ordered the capacity load test next, on the
grounds that capacity decides whether the owner saves money. That ordering is now wrong for a plain reason:
without a judge there is nothing to run at capacity. The next measurement is a re-run of the box on the
**calibration fold only** with logprobs recorded, which costs GPU time and no API money, followed by one refit.
Capacity comes after a judge exists that is worth running.

**A re-run has to be the same box.** The service behind the in-cluster endpoint is now `Qwen3.6-35B-A3B-FP8`,
not the `Qwen3.8-27B` that produced these outcomes. Logprobs collected from the current deployment would
describe a different candidate, and this repository treats a model change as a new candidate identity rather
than inherited evidence, so the re-run needs the measured box redeployed.

## What this does not support

**One iteration is the rule and it was taken.** A second threshold family on the same development fold would be
choosing a judge with the fold that reports the result, which is the failure mode the folds exist to prevent.
The sweep above is reported from the calibration fold on purpose.

**"Confident and wrong" is a description, not a measurement.** The claim here is only that completion length and
truncation do not separate the box's errors. Whether its logprobs do is unmeasured, and the honest prior is the
one already recorded on this corpus: an `e5` embedding of the prompt reached an AUC of 0.62 and could not be
turned into a policy that beat one categorical feature.

**Two escalations are unpriced.** The incumbent's chosen tier failed those calls and recorded no tokens; they
are counted, not charged as free, exactly as in the incumbent's own published figure.
