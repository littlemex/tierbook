# Step 0 kills the prefill routing line for agentic work: a perfect predictor is worth four cents an instance

**Computed 2026-09-01 from existing logs only, at no cost**, as the first step of the plan two independent
reviews agreed on. It fails, and it fails on economics rather than on signal, which means none of the steps
after it need to be run.

## What was asked

The plan was to find a cheap prefill-only signal that predicts whether the self-hosted box will solve a
SWE-bench instance, so that box attempts destined to fail could be skipped. Step 0 was to measure, for free,
how much such a predictor could possibly be worth. Two quantities, both from 20 instances that have all three
tiers measured and comparable:

- the **oracle against the incumbent** arrangement (cheap API, then premium), which was the registered kill;
- the **oracle against the box-first cascade** — box, then cheap, then premium — which is what a predictor
  actually has to beat, because that arrangement needs no predictor at all.

## The measurement

| | development fold (12) | held-out fold (8) | pooled (20) |
|---|---|---|---|
| incumbent, cheap → premium | $6.7003 | $0.9634 | $7.6637 |
| box first, no predictor | $5.1428 (−23.2%) | $0.3283 (−65.9%) | $5.4710 (−28.6%) |
| oracle, perfect foresight | $4.3529 (−35.0%) | $0.3283 (−65.9%) | $4.6811 (−38.9%) |
| oracle vs incumbent, 95% interval | **[6.6%, 70.7%]** | [47.2%, 76.2%] | [12.1%, 71.1%] |
| **the predictor's prize: oracle vs box-first** | **+15.4%** [9.6%, 25.3%] | **+0.0%** [0.0%, 0.0%] | **+14.4%** [8.8%, 23.0%] |
| per instance | $0.0658 of $0.4286 | $0.0000 of $0.0410 | **$0.0395 of $0.2736** |

**The registered kill fires.** The condition was a 95% lower bound of at least 10% on the oracle's saving
against the incumbent; on the development fold it is **6.6%**. The pooled set passes at 12.1%, and the
disagreement between the folds is not noise — the held-out eight are a set where **all three tiers solve all
eight**, so the oracle there is simply "always use the box" and a predictor has nothing to decide.

**And the number that decides it is the prize, not the kill.** A predictor's whole job is to beat the
arrangement that needs no predictor. That is worth **four cents an instance on a twenty-seven cent bill**, and
**exactly zero** on the easier fold.

## Why it is that small, and why that was predictable

Capability is nested here — every instance the box solves is also solved by both API tiers — and the box is the
cheapest tier. So "try the box, then the cheap API, then the premium one" already lands on the cheapest solving
tier for every instance where the box succeeds. **The only thing a predictor can add is not paying for box
attempts that were going to fail**, and a failed box attempt costs three to five cents.

Nothing about the signal was the problem. A perfect signal, free of charge, wins four cents.

## A contamination found in step 0 itself, worth keeping

The other half of step 0 was to measure run-to-run agreement, with a kill at more than 40% of instances giving
mixed results. The first pass reported 20% for the box and 27% for the cheap tier, and **both figures were
wrong**: the runs are not repeats of each other.

| run | what actually differs |
|---|---|
| `pass2` | the text protocol, before native tool calling |
| `passfc` | function calling, cheap tier at effort **none** |
| `passfcr` | function calling, cheap tier at effort **high** |
| `passfct` | function calling, box's **thinking on** |
| `passc80` | 80 steps and 2.4M tokens instead of 40 and 1.2M |

So `cheap-always` scoring 5 of 15 in `passfc` against 9 of 15 in `passfcr` is the **effort dial**, already
recorded here as turning that tier into a different model, not a seed. **There are no true repeats in this
corpus at a fixed configuration**, which means run-to-run agreement for the agentic arms has never been
measured and cannot be measured from what exists. It would be cheap to buy for the box — fifteen instances,
twice — but there is now no reason to.

## What survives

**The single-turn router stands.** On the knowledge corpus, a prefill probe with a margin threshold matches the
incumbent's quality at 89% of the cost, and the frontier reaches 70% for one item out of 413. That is a
different traffic family with a different economics, and it is unaffected by this.

**The entropy substitution is still worth doing** — letter entropy beats the top-two margin by 0.013 AUC at no
cost, in token space, on the family where the router actually runs.

**And the highest-value work is still not routing.** The premium tier lost four of twenty-four episodes to
empty completions from the gateway, at $17.6850 of dead money against $14.5899 of successful spend. Against a
predictor's four cents an instance, fixing that is worth roughly two orders of magnitude more, which is what
both reviews said before any of this was computed.

## What this does not support

**It is twenty instances and the intervals are wide.** The development fold's oracle interval spans 6.6% to
70.7%. What the pooled figure rules out is not "a predictor could ever help" but "a predictor is the next thing
worth building here".

**Only cost was measured.** A predictor also saves wall clock — the box spends 27 steps where the API spends 5
to 8 — and latency was measured separately: the box-less two-stage cascade was fastest at every percentile. So
the latency argument points the same way rather than rescuing the line.

**Nested capability is a property of these three tiers on this corpus**, conditioned on one price table and one
date. A pool where the cheap tier solved something the premium tier did not would change the shape of this
entirely, and the one place that was checked — the knowledge corpus — did contain such items.
