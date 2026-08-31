# Gate 3 met both registered conditions and is reported as void, because one of the incumbent's two tiers returned nothing on 60% of calls

**Measured 2026-08-31** against Addendum 5 of [`PREREG-box-cascade.md`](PREREG-box-cascade.md), on the frozen
fold: the `validation` split at `--samples 400`, 436 items, on which no model had ever answered. One run, one
evaluation, θ = 3.0 fixed on the calibration fold beforehand.

## What the arithmetic said

| | solved / 436 | cost |
|---|---|---|
| incumbent, `category` | 291 (66.7%) | $0.7665 |
| probe alone | 275 (63.1%) | $0.0138 |
| **policy, θ = 3.0** | **317 (72.7%)** | **$0.5143** |

Paired difference **+5.96 points, interval [+3.21, +8.72]**; cost ratio **0.671**. Condition 1 wanted a lower
bound at or above −2 points: met. Condition 2 wanted cost at or below 85%: met. **By the registered rule this
is a pass, and it is not being reported as one.**

## Why it is void

The incumbent scored 66.7% here against 85.3% on the development fold. That is not the fold being harder. Split
by tier:

| tier | frozen fold | development fold |
|---|---|---|
| `gpt-5.6-terra` | 365 / 436 = **83.7%** | 582 / 699 = 83.3% |
| `grok-4.6` | 129 / 436 = **29.6%** | 612 / 699 = 87.6% |

`gpt-5.6-terra` is stable to within half a point. `grok-4.6` lost 58 points, and not by answering wrongly:

- **260 of 436 calls returned an empty completion** — `finish_reason: "stop"`, zero completion tokens, empty
  text, and no first token ever observed. A median of **1.2 seconds**, so these are fast failures rather than
  timeouts.
- **31 more failed with `ClientPayloadError: Response payload is not completed`**, the body cut mid-stream.
- Of the 145 that did answer, the slowest took **59.9 seconds** and the median 30.4 — pinned under a
  sixty-second ceiling, which is what cut the 31.

So 291 of 436 is a measurement of one tier's availability on one afternoon, and the policy's +5.96 points is
mostly the incumbent being unable to answer for the two categories that route to `grok-4.6` — law and
engineering. Reporting that as a quality win would be measuring an outage and calling it a router.

Concurrency contributes and does not explain it: re-run at 6 in flight instead of 12, the empty rate fell from
60% to **44%** over the first 64 items. Called directly outside the harness the same model answers 200 with
content, so it is neither dead nor unauthorised.

## The defect this exposes, for the third time

**A failed upstream is being presented as a successful empty answer.** `finish_reason: "stop"` with zero tokens
is indistinguishable, to every client and to this harness, from a model that chose to say nothing — and it is
recorded as a wrong answer rather than as an unavailable tier. This project has now been damaged by it three
times: four of twenty-four agentic episodes, one of them after $9.2452 had been spent; the four gateway failures
that forced an arm down to twelve comparable items; and now 60% of a tier on a frozen fold that cost thirty
minutes and $0.77 to collect.

The gateway's own log carries a matching warning on this model — `cascade_model_unresolvable` with
`selected_model=grok-4.6` — so the information exists on the server and is not reaching the response.

## What is and is not spent

**The fold's items are not consumed by this.** Nothing was fitted on them: θ came from the calibration fold and
was fixed in the registration before the fold existed. What is now known is the policy's own score on it, which
means a re-run can repair the comparison arm but cannot be presented as a first look. That is stated here rather
than glossed.

**The probe arm's collection stands** — 436 items, one run, no failures, $0.0138 of machine time.

**Two honest ways forward, and they answer different questions.** Repair the transport and re-collect the
incumbent's tiers, which asks "is the policy better than a working incumbent". Or keep the failures and treat
availability as part of the product, which asks "is the policy better than the incumbent as it actually
behaves" — this project has already decided that availability is part of the product, but a 44 to 60% failure
rate on one tier is an incident rather than a rate, and baking an incident into a baseline flatters the thing
being tested.

**Not done: dropping `grok-4.6` from the incumbent and refitting.** That would be choosing the baseline after
seeing which baseline loses, on the fold that reports the result.
