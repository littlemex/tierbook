# An Ops loop driven from a coding agent

**This directory is the logic. `src/tierbook` is the mechanism.** That split is the point of the example, and the
easiest way to see it is that this example declares state variables tierbook has never heard of —
`price_per_mtok`, `hour_of_day`, `tenant_quota_left` — and the mechanism carries guards over them without changing.

Until recently it could not. `decide.STATE_VARS` was a module-level tuple of five names and a guard over anything else
was refused, so this example would have been impossible to write without editing the mechanism. That is exactly the
failure the mechanism is not allowed to have.

## What runs

```
observe  ->  decide  ->  call the agent  ->  record  ->  adapt  ->  observe ...
```

| step | who owns it | where |
|---|---|---|
| `observe` | the example — it decides which facts exist | `state.py` |
| `decide` | the **mechanism** evaluates guards; the example wrote them | `policy.py` + `tierbook.decide` |
| call | the example — a seam a real coding agent plugs into | `adapter.py` |
| `record` | the **mechanism** — spend on four legs, the harness, the decision | `tierbook.spend`, `tierbook.harness` |
| `adapt` | the example — every threshold is derived here, from what was recorded | `ops.py` |
| capacity | the **mechanism** sorts a measured goodput from a declared ceiling; the example states the rate it needs | `tierbook.throughput` |

## What the example decides, and what it refuses to decide for you

Its policy is one opinion among many: prefer the cheap candidate, escalate when the observed price of the cheap one
rises past what the dear one costs, and stop escalating when the tenant's quota is nearly gone. Those thresholds are
**derived from what the loop recorded**, never configured — that is this example's rule, and a different example may
choose differently.

It also has to get itself started, and it could not. Every threshold is derived from history, the price threshold
needs history on the dear candidate, and escalation needs the price threshold -- so the first version ran forever on
one arm and derived nothing. The loop therefore **explores**, through the mechanism's own randomiser so the propensity
is recorded rather than implied, at a rate the example chooses: high while either arm is unmeasured, low afterwards,
and never zero, because a loop that stops exploring cannot notice a price change.

What it does **not** do is decide on evidence the mechanism says cannot support the claim. A rate measured under a
closed loop cannot say whether the box holds the traffic, so the loop asks rather than assumes and `deliverable()`
answers `deliverable`, `refused` or `unknown`. The example's rule for those three, which is a choice it makes rather
than the only sensible one: **`refused` is a veto, `unknown` is not.** Vetoing on `unknown` would let a weak load
generator quietly shrink the pool. What `unknown` costs instead is the claim -- the loop may route there and may not
report that the candidate was shown to carry the traffic, and `shown_to_carry_the_traffic` keeps those apart.

## Running it

```bash
PYTHONPATH=src python -m pytest examples/opencode_ops/tests -q
```

The tests drive the whole loop with a fake agent, and one of them fails if the loop does not actually reduce spend —
an Ops loop that records beautifully and never changes anything is the failure mode this example exists to avoid.
