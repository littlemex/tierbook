# What this project is, and the mistake it keeps being turned into

**This is the scope statement. Every other document in this repository is subordinate to it.** It exists
because the same error has been made three times and each time it produced work that was useful and beside
the point.

## What is being built

A **routing mechanism** that operates while its environment moves. Request volume moves, API prices and
availability move, a self-hosted engine's capacity and occupancy move, agents come and go, checkpoints are
replaced. The mechanism **collects its own initial data** in whatever environment it is dropped into, keeps
re-estimating from live traffic, and decides where each request goes.

The output it owes its caller is a decision of this shape:

> at this concurrency, against these prices, with this SLO and this accuracy floor, the next request
> belongs on the API rather than on the self-hosted engine

**and the threshold in that sentence is derived, never configured.**

## What is NOT being built

**Not a tuning guide for one cluster.** "This deployment needs seven concurrent sessions to amortise its
GPU", "this engine seats 128 requests", "this agent fits 272 sessions in KV" — every one of those is a
*parameter reading*, not a result. Writing them into a conclusion is how this project gets turned into
consultancy about somebody's current hardware, which is the failure mode named at the top.

**Not a fixed verdict about which tier is better.** A self-hosted engine's marginal cost is near zero until
it saturates and becomes *latency* afterwards. So there is no standing answer, only an admission policy:
fill the fixed-cost tier while the SLO holds, overflow the remainder to the cheapest tier that clears the
accuracy floor. Which tier is "cheaper" is an output, not an input.

**Not a benchmark.** Measurements exist to populate parameters. A measurement presented as the deliverable
is the deliverable missing.

## The parameters, and where each comes from

None of these may be hardcoded. Every one is either measured by the calibration routine or read from a
feed, and every one is expected to change under the mechanism's feet.

| parameter | source | changes when |
|---|---|---|
| arrival rate, concurrency | observed, continuously | users arrive |
| seats, KV capacity, saturation throughput | calibration against the live engine | engine flags, model, hardware |
| prefix-reuse rate | observed per traffic family | the agent or the workload changes |
| fixed cost per hour | configuration (a reservation price, stated) | the contract you bought |
| API unit prices, availability | price feed, never hand-entered | the vendor |
| request shape: input, expected output | observed per family | the agent |
| SLO, accuracy floor | the operator's requirement | policy |

## Calibration is part of the deliverable

A mechanism dropped into a new environment does not know that environment's capacity, throughput or hit
rate. It runs a calibration to find out, and then keeps correcting from real traffic. "Measure it by hand
first and put the numbers in a config file" does not satisfy this: the environment moves, and a number
entered once is wrong from the second hour onwards.

## How today's measurement tools relate to this

`harness/agent_tap.py`, `harness/agent_drive.py`, `harness/testbed.py`, `harness/sweep_agents.py` and
`harness/agent_frontier.py` are **instruments that supply parameters**. They are not the router and their
outputs are not conclusions about which agent or tier to use. When one of them produces a striking number,
the correct next question is which parameter it estimates and how the mechanism should read it live.

## The test a statement here has to pass

Before writing a recommendation, check that it survives a change of environment. If the sentence stops
being true when the GPU, the price list, the agent or the user count changes, it belongs in a measurement
record and not in a conclusion — and the conclusion that *does* belong is the rule that generated it.
