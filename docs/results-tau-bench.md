# The router on a family it had never seen: 35× cheaper, and the claim partly refuted

**Measured 2026-08-30 on real hardware.** Every tier in this repository had been measured on one traffic
family — agentic coding — and the assignment was compiled from it. This is the mechanism put to a family it
has never seen: τ-bench retail, a tool-using agent talking to a simulated user, judged on the resulting
database state. Procedure and readings were fixed in `PREREG-tau-bench.md` before any task ran.

## The headline, both halves of it

**At a margin of 0.25 the compiled assignment costs $0.0133 a request against the reference tier's $0.4699
— 35× less — at a solve rate whose held-out lower bound stays inside the margin.** That is the claim, and
at that margin it holds out of fold.

**At margins of 0.15 and 0.20 it does not.** The same calibration fold compiled the same tier, and out of
fold its quality bound was −0.241, outside both margins. The router was overconfident by about eleven points
of solve rate, which is the first pre-registered refutation condition and it fired.

So the mechanism transfers and the *sample it was calibrated on* does not carry the confidence the rule
attributed to it. Both statements are the result.

## The three tiers on the held-out 115

| tier | solved | spend | $/request | wall p50 | turns p50 |
|---|---|---|---|---|---|
| self-hosted | 76/115 (66%) | $1.13 | **$0.0098** | **17 s** | 30 |
| cheap API | 91/115 (79%) | $3.87 | $0.0337 | 25 s | 26 |
| reference (expensive API) | **95/115 (83%)** | $54.04 | $0.4699 | 68 s | 26 |

The self-hosted tier is 48× cheaper per request than the reference and four times faster, at 17 points less
solve rate. Nothing about that ordering was predictable from the coding family, where the same tier needed
31 steps against the reference's 13 and was slower than the remote APIs.

## Reading 3: what each margin compiled, and how it held up

The margin is an input nobody has priced, so the pre-registration fixed a grid rather than a value.

| margin | compiled | $/request | out-of-fold quality bound | verdict |
|---|---|---|---|---|
| 0.10 | the reference | $0.4699 | — | nothing certified; **no saving, correctly** |
| 0.15 | self-hosted | $0.0133 | −0.241 | 35× cheaper but **quality fails out of fold** |
| 0.20 | self-hosted | $0.0133 | −0.241 | 35× cheaper but **quality fails out of fold** |
| 0.25 | self-hosted | $0.0133 | −0.241 | **35× cheaper and quality holds** |

At 0.10 the rule declined to route and said so — `not certified`, distinguished in the decision record from
the reference winning. That is the mechanism behaving correctly at the cost of buying nothing.

## Why the calibration fold misled, and by how much

Twenty items said one thing and 115 said another, in a way no amount of care in the *rule* could have fixed:

| tier | bound on 20 (calibration) | bound on 115 (held-out) | solve rate 20 → 115 |
|---|---|---|---|
| self-hosted | **−0.130** | **−0.241** | 0.95 → 0.66 |
| cheap API | **−0.210** | **−0.102** | 0.90 → 0.79 |

**The two cheap tiers swapped rank between folds.** On the calibration fold the self-hosted tier had the
tighter bound and was chosen; on the held-out fold the cheap API is the one within 0.10 of the reference and
the self-hosted tier is not. The compiled choice was the worse of the two on the axis it was chosen for.

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

Against the reference alone, on 115 unseen tasks: **97.2% of the bill removed** ($54.04 → $1.13 for the
self-hosted assignment, or $3.87 for the cheap API), **4× lower median latency**, and 17 points of solve
rate given up. Whether that trade is worth taking is the defect-cost question nobody has priced — at $1 a
defect it plainly is, at $100 it plainly is not, and the router cannot decide that for its owner.

Against the *cheapest tier alone*, which is the harder bar the pre-registration set: the compiled assignment
**is** the cheapest tier at margins 0.15 and above, so the router did not beat cheapest-alone — it selected
it. A router that selects the cheapest tier when the cheapest tier is certifiable is doing its job, but it
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
self-hosted tier look *more expensive per request than the cheap API* ($0.0317 against $0.0293), and its own
family's figure makes it three times cheaper. The schema now carries latency per family for that reason.
