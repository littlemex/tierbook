# tierbook

**A ledger of what each inference tier was measured to do, and a router that only reads it.**

A tier here is not a model name. It is a versioned record of measurements — what its adapter actually
complies with, what it costs per request shape, how long it takes at the percentile you care about, how
often it fails and how much it had already billed when it did, what it solved on each traffic family, and
how its cache behaves when other traffic is interleaved. The router is deliberately thin: it reads the
ledger, and it does not guess.

## What this is not

**It is not a gateway.** [`stratoclave`](https://github.com/littlemex/stratoclave) enforces budgets and
keeps an auditable ledger of calls, and its own subtitle says model routing stays external. This is that
external thing. It consumes the gateway's ledger events, capability declarations and price snapshots; it
never asks the gateway to decide anything.

**It is not infrastructure or an experiment record.**
[`distributed-ai`](https://github.com/littlemex/distributed-ai) holds the clusters that serve a
self-hosted tier and the dated, append-only records of the experiments that produced the numbers here.
Those records stay there and are cited, not copied.

**It is not a difficulty predictor.** No classifier chooses a tier. That is a measured decision, not a
stylistic one — see below.

## Two numbers this repository publishes about itself

**No non-inferiority margin anyone would pre-register admits the self-hosted tier.** It solved 14 of 20
against the reference tier's 20 of 20, and because the comparison is paired, all six discordant items favour
the reference: the one-sided lower bound on the difference is **−0.47**, not the −0.30 the point estimate
suggests. An earlier version of this work published −0.30 as the margin required, which understated it.

**A sample of twenty with one run per item cannot certify non-inferiority at a margin anyone wants.** The
rule is built so that this shows up as `not certified` rather than as a winner, and so that the decision
record says which of the two happened.

## The rule

> Offline, per traffic family: assign the cheapest tier whose measured outcome on that family's frozen
> benchmark set is non-inferior to the family's reference tier, at a margin fixed in advance, scored out of
> fold. Online, per request: map it to a family, send it to the assigned tier, and escalate **only on
> observable failure**. Never escalate on a judgement about quality.

Three timescales, and only the first makes a decision:

| when | what happens |
|---|---|
| offline, per family | measure, then assign the cheapest sufficient tier |
| per hour | recompute a fixed-cost tier's effective rate from realised throughput; refresh per-tier failure rates |
| per request | classify into a family, send, and react only to failures that can be observed with certainty |

The online path has no cleverness in it on purpose.

## Why there is no learned router

Not caution — three measurements, all from the record in `distributed-ai`:

- A learned multi-factor router **lost 3.6 accuracy points and added 12.8 s** while saving 63% of cost.
- Its selector **named one member for 96% of requests**, which is a family assignment made expensively.
- An offline per-domain assignment **overfit and lost 2.5 points out of fold**.

Against that, what actually paid was unglamorous: driving each tier through its own native tool-calling
interface **doubled one tier's solve rate for free**; request *shape* moves input cost by 12× on a tier
that caches; putting retries into the cost function **reversed which arrangement was cheapest**; and
picking the right single tier per family beat every router that was implemented.

A small model is admitted for two narrow jobs only — identifying which family a request belongs to when
metadata cannot, and an abstaining estimate of whether a cheaper tier is safe for a family — and both are
gated on leave-one-family-out validation, an untouched holdout, and a lower confidence bound on *routed
outcome*. Classifier accuracy is not the metric. Failing the gate means zero routing authority.

## Escalation fires only on things that cannot be wrong about failure

- a transport error, or an HTTP 200 whose stream ended with no content;
- an unusable action stream (the adapter could not read a call);
- budget exhausted — steps, tokens or wall clock — **with no artifact produced**;
- any check that can *reject* with certainty: a patch that does not apply, output that fails its declared
  schema, a required field absent.

All of these err in the safe direction: a spurious escalation costs one attempt. **The slot for a semantic
success detector exists and is empty.** Three families of candidate were eliminated against a
pre-registered bar of keep-precision 1.00 — signals inside an episode reached 0.77, self-consistency cannot
pay for itself at any k above 2.06, and a cheap-tier judge on the artifact reached 0.78 with every error in
the dangerous direction. If one ever clears the bar on a held-out fold it plugs in as one more trigger; it
does not become a redesign.

**The one thing that would reopen the cheap-first cascade:** a request that arrives carrying its own
executable acceptance check. The reason in-repository tests were uninformative on the benchmark is that its
judging tests are `fail_to_pass` tests absent from the checkout by construction — and a requester-supplied
failing reproduction test *is* such a test, present at inference time. Where one exists, the oracle the
arithmetic assumed actually exists. Measuring what fraction of real traffic carries one is the first thing
to do and needs no model work.

## Layout

```
registry/        the ledger: schema for a tier record, and the measured instances
routing/         the rule: family table, admission, the objective, the cascade executor
harness/         the episode harness that produces per-family outcomes for agentic traffic
docs/            the design, and what it deliberately does not claim
```

## Status

Alpha, one consumer, and honest about it. The measurements it ships with are from a public benchmark; the
project's own rule is that no traffic is admitted to a cheaper tier until the work actually being routed is
measured. Two parameters have to come from outside before there is a unique answer rather than a Pareto
frontier: **the value of a second** for a family, and **the cost of an escaped defect**. At $1 per defect a
cheap tier ships; at $100 the required keep-precision is 0.993; at $10,000 it is 0.99993 and no affordable
sample can certify it.
