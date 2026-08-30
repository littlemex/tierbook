# tierbook

**A ledger of what your tiers were measured to do, and a router that refuses to act beyond it.**

It does not route your traffic out of the box. It measures first, and until a held-out fold supports a choice
it will decline to make one. That is the feature.

```console
pip install tierbook
tierbook validate --registry examples/ledger/tiers
tierbook explain  --registry examples/ledger/tiers --family tool-agent-user-retail --reference api-strong-a
tierbook compile  --registry examples/ledger/tiers --validations examples/ledger/validation \
                  --family tool-agent-user-retail=api-strong-a --margin 0.15 --out table.json
```

That last command **refuses**, on the data shipped with it:

```
cannot_reject  status=refused   held out on tau-bench-retail-test:115 at 115 items:
                                bound -0.2407 is OUTSIDE the margin of -0.15.
                                The calibration fold chose this tier and the held-out fold does not support it.
RANK UNSTABLE across folds: calibration ['self-hosted-a', 'api-cheap-a']
                            vs held-out ['api-cheap-a', 'self-hosted-a']
```

Run the same command at `--margin 0.25` and it assigns. The refusal is not a demo: it is what this project's
compiler did to this project's own conclusion, and the shipped example reproduces it on day one.

## Why a router should refuse things

Three measurements, all in `docs/`, all of which cost money to find.

**A calibration fold will lie to you about which tier is closest.** On a 20-item fold the self-hosted tier's
paired bound was −0.130 and the cheap API's −0.210, so the compiler chose the self-hosted tier. On a 115-item
held-out fold the same two were −0.241 and −0.102 — **they swapped rank**. No minimum sample size predicts
that: the bound was computed correctly and was simply about the wrong twenty items. The only gate that works
is empirical — a held-out fold, on a different cohort, that the claim survives.

**A learned router lost to picking one model per family.** −3.6 accuracy points, +12.8 s of latency, and a
selector that named one member for 96% of requests, which is a family assignment made expensively. An
offline per-domain assignment overfit and lost 2.5 points out of fold. There is no classifier in here, and
that is a result rather than a taste.

**The expensive tier is not always the ceiling.** On one family the two cheaper tiers each solved tasks the
reference failed — 6 and 9 of 115 — so routing could have raised quality rather than only lowered cost. A
router that hardcodes "escalate to the strongest" would have been worse than one that reads the ledger.
Nesting is a per-family, per-pair measurement here, never an assumption.

## The mechanism

```
measure  ->  tier record  ->  compile (draft)  ->  validate on a different cohort  ->  route
```

**A tier is a record of measurements with no model name in anything the router branches on**: adapter
compliance, a price card per request shape, a latency distribution *per family*, a failure rate with the
distribution of spend sunk before death, per-family outcomes with a paired 2×2 and the hash of the item set
they were measured on, and hard eligibility. **A field that was not measured is `null`** — never zero, never
a published figure. This deployment has seen an engine advertise 7–14× more reusable cache than it had, and a
rate card price a model 17× wrong.

**Compiling produces a draft.** An entry becomes `assigned` only when a held-out record on a *different*
cohort hash still supports the claim. Otherwise it is `provisional`, and `tierbook route` refuses it unless
you pass `--allow-unvalidated`, which is deliberately ugly so that its presence in a deploy script is the
audit trail.

**The online path is a dictionary lookup and one rule**: escalate only on a failure that can be observed with
certainty — a transport error, an HTTP 200 whose stream carried no content, an unusable tool call, a budget
exhausted with no artifact, an artifact that fails its declared schema, or a check *you* supplied that
rejected it. An artifact that exists is shipped and never second-guessed.

**The slot for a semantic success detector is empty on purpose.** Three families of candidate were eliminated
against a pre-registered bar of keep-precision 1.00: signals inside an episode reached 0.77, self-consistency
cannot pay for itself at any k above 2.06, and a cheap-tier judge on the artifact reached 0.78 with every
error in the dangerous direction. One that clears the bar plugs in as another escalation trigger; it does not
become a redesign.

## What a stranger does on day one

Not routing. **Producing a record for a tier you own**, then asking the compiler what it can and cannot
conclude from it. `harness/` holds the instrument this project used, and `examples/ledger/` is a worked ledger
whose shape you can copy. The contract is `registry/schema.json`; any harness emitting records that conform
works. The rule the instrument must follow: **a call that died on the wire produces `null` and a transport
report, never a zero.** One tier here scored 0 of 20 on an endpoint restriction rather than on the task, and a
harness that had reported that number would have published a false claim about a model.

## What is deliberately not here

- **No circuit breaker, no retry infrastructure, no server.** Those are your operator's, and shipping them
  would invite running this as production middleware before the evidence supports it.
- **No shared or central registry.** Other people's cohort hashes are unverifiable. The ledger is yours; the
  repository ships an empty one and a worked example.
- **No learned routing, no online adaptation.** Measured, and it lost.
- **No provider zoo.** One reference adapter. Every gateway is its own landmine, and collecting them is
  someone else's project.

## The examples are examples

`examples/ledger/` holds three real tiers measured on two real families, and they are **worked examples of the
schema, not truths about vendors**. Every record carries `measured_at` and a pin of exactly what was measured.
They will go stale; that is what the pin is for.

## Status

Alpha. Two parameters must come from outside before any of this has a unique answer rather than a Pareto
frontier: **the value of a second** for a family, and **the cost of an escaped defect**. At $1 a defect a
cheap tier ships; at $100 the required keep-precision is 0.993; at $10,000 it is 0.99993 and no affordable
sample can certify it. The router cannot decide that for you and does not pretend to.

`docs/` carries the design, the pre-registrations written before each measurement, and the results — including
the two pre-registrations whose predictions failed.
