# The router on a family it had never seen: 16x cheaper, and an assumed cost figure caught

**Measured 2026-08-30 on real hardware.** Every tier in this repository had been measured on one traffic
family — agentic coding — and the assignment was compiled from it. This is the mechanism put to a family it
has never seen: τ-bench retail, a tool-using agent talking to a simulated user, judged on the resulting
database state. Procedure and readings were fixed in `PREREG-tau-bench.md` before any task ran.

> **Corrected 2026-08-30.** The figures below originally read $0.0133 a request and 35x, from the self-hosted
> tier. That number divided its hourly bill by a throughput obtained by multiplying the observed per-task
> time by an **assumed** sixteen requests in flight. The run recorded no per-task timestamps, so its realised
> throughput was never measured and the assumption was carrying the headline. Corrected below to the
> conservative throughput the run does support. The correction also changes which tier the rule selects, and
> it selects the one the held-out fold preferred -- so the mechanism comes out better and the number smaller.

## The headline, both halves of it

**At a margin of 0.25 the compiled assignment costs $0.0293 a request against the reference tier's $0.4699 --
16x less -- at a solve rate whose held-out lower bound stays inside the margin.** The assignment is the cheap
API, whose cost is fully measured: it bills per token, so there is no amortisation in it to assume.

The self-hosted tier's cost per request is **not determined by this run**. Its token spend is $0.0098, and its
share of a $15.22 hourly bill depends on a throughput nobody measured. Bounding it by what the run does
support -- one sequential shard at 16.5 s a task on average, so at least 218 tasks an hour -- puts it at
$0.0768, which
is more expensive per request than the cheap API. Sixteen in flight would make it $0.0133. Both are arithmetic
on the same measurement and the run cannot say which is right, so the rule now refuses to prefer it.

**At margins of 0.15 and 0.20 it does not.** The same calibration fold compiled the same tier, and out of
fold its quality bound was −0.241, outside both margins. The router was overconfident by about eleven points
of solve rate, which is the first pre-registered refutation condition and it fired.

So the mechanism transfers and the *sample it was calibrated on* does not carry the confidence the rule
attributed to it. Both statements are the result.

## The three tiers on the held-out 115

| tier | solved | spend | $/request, tokens only | $/request, all-in | wall p50 | turns p50 |
|---|---|---|---|---|---|---|
| self-hosted | 76/115 (66%) | $1.13 | **$0.0098** | **$0.0768, not determined** | **17 s** | 30 |
| cheap API | 91/115 (79%) | $3.87 | $0.0337 | $0.0337 | 25 s | 26 |
| reference (expensive API) | **95/115 (83%)** | $54.04 | $0.4699 | $0.4699 | 68 s | 26 |

The two cost columns differ only for the self-hosted tier, and that gap is the whole correction. A rented
machine bills while it is idle, so its cost per request is its token spend plus its hourly bill divided by how
many tasks an hour it actually completes -- and this run did not measure that. The all-in figure shown is the
conservative bound: what the run demonstrably sustained. Quoting the tokens-only column as a cost per request
would price a machine as though it were free when nothing is on it.

The self-hosted tier is 48x cheaper per request *in token spend* than the reference and four times faster, at
17 points less solve rate. Nothing about that ordering was predictable from the coding family, where the same tier needed
31 steps against the reference's 13 and was slower than the remote APIs.

## Reading 3: what each margin compiled, and how it held up

The margin is an input nobody has priced, so the pre-registration fixed a grid rather than a value.

| margin | compiled | $/request | out-of-fold quality bound | verdict |
|---|---|---|---|---|
| 0.10 | the reference | $0.4699 | — | nothing certified; **no saving, correctly** |
| 0.15 | cheap API | $0.0293 | −0.102 | 16x cheaper, **quality holds** out of fold |
| 0.20 | cheap API | $0.0293 | −0.102 | 16x cheaper, **quality holds** out of fold |
| 0.25 | cheap API | $0.0293 | −0.102 | 16x cheaper, **quality holds** out of fold |

The row that used to be here said `self-hosted` at $0.0133 for the three lower margins, failing out of fold
at 0.15 and 0.20 with a bound of −0.241. That selection was produced by the assumed throughput. With the
conservative one the self-hosted tier is no longer cheapest, the rule selects the cheap API instead, and the
cheap API's bound holds at every margin it is offered at. **The pre-registered refutation condition therefore
no longer fires** -- and the reason is not that the rule got better at statistics. It is that an unmeasured
input was removed, and the input had been pushing the rule towards the candidate the held-out fold liked
less. Which is the more useful finding: the rank instability recorded below was the symptom, and an assumed
cost figure was the cause.

At 0.10 the rule declined to route and said so — `not certified`, distinguished in the decision record from
the reference winning. That is the mechanism behaving correctly at the cost of buying nothing.

## Why the calibration fold misled, and by how much

Twenty items said one thing and 115 said another, in a way no amount of care in the *rule* could have fixed:

| tier | bound on 20 (calibration) | bound on 115 (held-out) | solve rate 20 → 115 |
|---|---|---|---|
| self-hosted | **−0.130** | **−0.241** | 0.95 → 0.66 |
| cheap API | **−0.210** | **−0.102** | 0.90 → 0.79 |

**The two cheap tiers swapped rank between folds.** On the calibration fold the self-hosted tier had the
tighter bound; on the held-out fold the cheap API is the one within 0.10 of the reference and the self-hosted
tier is not. With the corrected cost the rule does not choose the self-hosted tier at all, so the swap no
longer decides the outcome here -- but it decided it in the original run, and at n = 20 it will decide the
next one, so it stays on the record.

This is not a defect in the rule — the rule reported a bound from the data it had, and the bound was honest
about *that* data. It is a statement about how much twenty paired items can support, which the
pre-registration said in advance and which this measures: **at n = 20 the ranking of two candidates within
10 points of each other is not reliable.**

## Reading 4: nesting breaks here, for the first time in this project

| tier | solves items the reference does not |
|---|---|
| self-hosted | **6** of 115 |
| cheap API | **9** of 115 |

Both cheap tiers solve tasks the reference fails. Counted together:

| arrangement | solved |
|---|---|
| reference alone | 95/115 |
| either cheap tier | **101/115** |
| any of the three | **105/115** |
| none of the three | 10/115 |

**So on this family the reference is not the ceiling, and routing could raise quality rather than only lower
cost.** Every earlier conclusion in this project rested on strict nesting observed twice on other corpora,
and this is the counterexample. The narrowing already applied — that nesting is a per-family, per-pair
property re-certified at admission rather than a law — is what made the rule able to notice: the
counterexample count is recorded and gates chain construction, so the rule refuses to build a cascade for
this family instead of assuming one is safe.

What it should do *instead* for a non-nested family is not implemented and is named rather than guessed:
estimate the full joint outcome and choose among tiers as non-nested experts, which needs a measurement of
the arrangement rather than of the tiers.

## What the router actually bought, stated plainly

Against the reference alone, on 115 unseen tasks: **92.8% of the bill removed** ($54.04 -> $3.87 for the
cheap API, which is what the rule now assigns), **2.7x lower median latency**, and four points of solve rate
given up. The 97.2% that used to be quoted here was the self-hosted tier's token spend and excluded its
hourly bill. Whether that trade is worth taking is the defect-cost question nobody has priced — at $1 a
defect it plainly is, at $100 it plainly is not, and the router cannot decide that for its owner.

Against the *cheapest tier alone*, which is the harder bar the pre-registration set: the compiled assignment
**is** the cheapest tier at margins 0.15 and above, so the router did not beat cheapest-alone -- it selected
it. Note that "cheapest" changed meaning under the correction: by token spend the self-hosted tier is
cheapest, and all-in it is not. A router that selects the cheapest tier when the cheapest tier is certifiable is doing its job, but it
means nothing here was bought by the routing logic beyond the certification itself, which is exactly what
the earlier knowledge-question round found.

## What this run does not support

**Not a τ-bench score.** One trial per task, a fixed user simulator chosen for comparability, and a tool
adapter that had to translate one tier onto a different wire. Comparable across arms; not comparable to
published τ-bench numbers.

**Not transfer.** Two families is two families, and they disagreed about which tier is closest to the
reference. If anything this run argues that per-family measurement cannot be skipped, which is the opposite
of transfer.

**Nothing about production traffic.** Still a public benchmark.

## Two things the run found that were not being looked for

**One tier could not run this benchmark at all through the obvious path.** The cheap API refuses function
tools together with any reasoning setting other than none on chat completions, which is what τ-bench uses
through litellm — so its first arm scored **0 of 20** on a gateway restriction rather than on the task.
Measuring it properly needed an adapter onto the other wire. A benchmark harness that had simply reported
that number would have published a false result about a model.

**Latency is a property of the tier and the family together, not of the tier.** The same self-hosted tier
takes 94 seconds a task on coding and 17 on this family. That matters beyond reporting: the fixed-cost
amortisation divides an hourly bill by realised throughput, so using the coding family's figure made the
self-hosted tier look *more expensive per request than the cheap API* ($0.0317 against $0.0293). The schema
carries latency per family for that reason, and the compiler now refuses to compute a fixed-cost tier's cost
from another family's figure rather than substituting one.

**A per-task latency is not a throughput, and the difference was hiding in a multiplication.** This is the
correction at the top of the page, and it is worth stating as a finding rather than an erratum: the same
observation, times an assumed concurrency, produced a cost per request that differed by a factor of six and
changed which tier the rule chose. Nothing in the original run was measured wrongly. What was missing was the
one number nobody had recorded -- how many tasks an hour the deployment actually completed -- and the analysis
filled the gap with a plausible constant instead of refusing. `throughput_for` now refuses, and the record
carries the concurrency its latency was observed at so that the substitution cannot be made silently.
