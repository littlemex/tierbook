# Gate 2c: the first realisable policy that holds the incumbent's quality, at 10.7% less money — and it fails the gate it was registered against

**Measured 2026-08-31** against Addendum 4 of [`PREREG-box-cascade.md`](PREREG-box-cascade.md). One fitted
parameter on the calibration fold, one evaluation on the development fold, both pass arms fixed before either
was computed. Both fail. The result is still the best this construction has produced, and both halves of that
sentence are the finding.

## The registered result

The policy: the terse arm of the MoE box answers every item; its answer is accepted when the logprob margin
between the chosen option letter and the best other letter clears θ, and escalated to the incumbent router's
choice otherwise. θ was fitted at **6.0** on the calibration fold by the registered rule — maximise solves
subject to total cost inside the incumbent's.

| | solved / 699 | cost | quality against the incumbent |
|---|---|---|---|
| incumbent, `category` | 596 | $1.6523 | — |
| terse box alone | 434 | $0.0443 | — |
| **Gate 2c policy, θ = 6.0** | **593** | **$1.4753** | **−0.43 pt, interval [−1.14, +0.14]** |
| this arm's ceiling, for reference | 627 | $0.8266 + box | +4.4 pt |

**Quality is indistinguishable from the incumbent** — the interval covers zero — at **89.3% of the cost**, of
which the box's own bill is $0.0443 and the API escalations are $1.4310.

Arm 1 required more than 596 solved: **fail**, it solved 593. Arm 2 required at least 596 at three quarters of
the cost: **fail** on both counts. The arms were set before the frontier below was known, and they are not
being moved now.

## Why the fitted point is the conservative end

The judge escalated 502 of 699 items. Of those, **251 were items the box had answered correctly** and 14 were
wrong answers it kept. That asymmetry is the fitting rule showing through: "maximise solves subject to a budget"
pushes θ up until almost everything escalates, because every escalation recovers a possible item and the budget
was generous enough to allow it. A rule written for cost would have chosen differently, and the frontier it
would have chosen from was already visible on the calibration fold:

| θ | escalated / 488 | solved | total cost | against the incumbent's $1.2659 |
|---|---|---|---|---|
| −∞ (never escalate) | 18 | 321 | $0.1268 | 10% of it, 92 items worse |
| 0.5 | 116 | 368 | $0.5210 | 41%, 45 worse |
| 2.0 | 204 | 402 | $0.7971 | **63%, 11 worse** |
| 4.0 | 293 | 410 | $1.0515 | 83%, 3 worse |
| **6.0 (fitted)** | 352 | **413** | $1.1853 | **94%, equal** |
| +∞ (always escalate) | 488 | 413 | $1.3141 | 104%, equal — the incumbent plus a box bill |

The shape is the useful part: **quality rises with θ and saturates exactly at the incumbent's**, while cost
rises monotonically. So this construction cannot beat the incumbent on quality — it can only reach it more
cheaply, and how much more cheaply is a choice along that curve. θ = 2.0 on the calibration fold is 63% of the
cost for 11 fewer items out of 488. What that point does on the development fold is **not measured and will not
be**: choosing it after seeing this table would be fitting the operating point to the fold that reports it.

## What the four gates add up to

| | quality | cost | why it stops here |
|---|---|---|---|
| Gate 1 ceiling, dense box | 625 | API $0.7899 | needs a perfect judge; box's own bill exceeded the saving |
| Gate 1 ceiling, MoE box | 627 | API $0.6789 | same, and the box is 3% dearer than the incumbent at its admission cap |
| Gate 2, length judge | 596 | $1.6523 | AUC 0.529 — the judge degenerated into "escalate everything" |
| Gate 2b, generation cap | 478 | $1.4448 | a cap escalates what ran long, and the errors are short |
| **Gate 2c, margin judge** | **593** | **$1.4753** | **the first non-degenerate judge; quality-neutral at −10.7%** |

The lever that moved was **the signal, not the model, the price, or the capacity**. Completion length gave 0.529
and an embedding of the prompt gave 0.62; the margin at the answer position gives 0.838, and that is the whole
difference between a policy that is the incumbent with a GPU bill and one that is the incumbent for a tenth less.

## What this does not support

**The box's $0.0443 assumes the machine is busy.** It is 699 items' worth of a $15.2174/hour node at the
measured 17.6 requests a second for terse replies — about forty seconds of machine time. Idle time is not priced
here, and at this reply length keeping the node paid for needs roughly 63,000 items an hour. The 10.7% is a
saving on a fully utilised box, not on a box that exists.

**The judge's 251 needless escalations are the headroom, not a defect to be tuned away here.** They are what
separates $1.4753 from the ceiling's $0.8266, and the fitting rule that produced them was registered. Whether a
cost-oriented rule reaches the ceiling is a question for the frozen fold with its own registration.

**A three-stage cascade is still unbuilt and still the obvious next shape.** The verbose arm solves 83 items the
terse arm misses, at 15 times the tokens; escalating from terse to verbose before reaching an API tier needs a
signal at the verbose arm's answer position, around token 680, which the eight-position record does not keep.

**Every number here is one corpus, one price table, one day.** The development fold has now been looked at four
times and selects rather than claims. The frozen fold has not been touched.
