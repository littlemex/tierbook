# tierbook

> **Scope, before anything else: [`SCOPE.md`](SCOPE.md).** This is a routing mechanism that collects its
> own data and decides while its environment moves. The decision is a **function from observed state to an
> assignment** — volume, prices, availability, capacity, request shape, floors and SLOs are all inputs, and
> every threshold in it is **derived, never configured**. *"At this concurrency the next request belongs on
> the API"* is **one example of the output shape, not the mechanism.* It is **not** a tuning guide for one
> cluster, not a standing verdict about which tier wins, and not a benchmark: numbers about a particular
> GPU, engine flag or agent are **parameter readings**, not results.

**A ledger of what your tiers were measured to do, and a router that refuses to act beyond it.**

It does not route your traffic out of the box. It measures first, and until a held-out fold supports a choice
it will decline to make one. That is the feature.

Not on PyPI yet, so install from a checkout.

```console
pip install .
tierbook validate --registry examples/ledger/tiers
tierbook explain  --registry examples/ledger/tiers --family tool-agent-user-retail --reference api-strong-a
tierbook compile  --registry examples/ledger/tiers --validations examples/ledger/validation \
                  --family tool-agent-user-retail=api-strong-a --margin 0.15 --out table.json
```

That last command **refuses**, on the data shipped with it:

```
cannot_reject  status=refused   held out on evidence:721ca50377d2a589 at 115 items:
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

That cohort hash is content-addressed -- derived from the suite manifest and the exact item ids -- only for
a family whose outcome carries `evidence` (per-item observations, checked on every read). For a family that
still carries the older hand-written `paired_vs_reference` summary, the cohort is a hand-written label, and
renaming it, or reusing it on a different item set, defeats the gate above without either record being
individually invalid. Migrating a family to `evidence` is what closes that gap for it; nothing in this
codebase closes it retroactively for a summary-only record.

**The online path is a dictionary lookup and one rule**: escalate only on a failure that can be observed with
certainty — a transport error, an HTTP 200 whose stream carried no content, an unusable tool call, a budget
exhausted with no artifact, an artifact that fails its declared schema, or a check *you* supplied that
rejected it. An artifact that exists is shipped and never second-guessed.

**The slot for a semantic success detector is empty on purpose.** Three families of candidate were eliminated
against a pre-registered bar of keep-precision 1.00: signals inside an episode reached 0.77, self-consistency
cannot pay for itself at any k above 2.06, and a cheap-tier judge on the artifact reached 0.78 with every
error in the dangerous direction. One that clears the bar plugs in as another escalation trigger; it does not
become a redesign.

## Where this stops

Three responsibilities meet at this component and it holds exactly one of them.

| | owns | tierbook's relationship to it |
|---|---|---|
| **a gateway in front** | authentication, quota, audit, one URL over many vendors | optional. If you have one, point at it; this adds a decision, not a hop you must adopt |
| **whoever runs the cluster** | nodes, GPUs, model servers, storage, scaling | assumed to exist. `deploy/` puts three objects onto a cluster it does not create |
| **tierbook** | which tier a family goes to, and the evidence for it | this |

The boundaries are refusals rather than sentences. A candidate entry naming `image`, `launch`, `replicas` or
`weights` **fails to load**, with a message saying serving belongs to whoever runs the cluster. A candidate
entry setting any key that exists in the record schema also fails to load, because that file is where an
operator would otherwise hand-write the accuracy figure a routing decision then rests on.

Behind it, anything that speaks an OpenAI-compatible HTTP API: a vendor API, several through one gateway, or a
model server in the same namespace. The endpoint abstraction is a `base_url`, a model name and which of two
wire protocols the endpoint accepts. It cannot tell a rented API from a pod next door, and the one place that
distinction survives is the cost model, where a per-token bill and a per-hour bill are different arithmetic.

## Configuration: what may be measured, and what was observed

Two files, and keeping them apart is most of the design.

```
candidates.json    what MAY be measured. Endpoints, and the priced inputs no measurement can produce.
                   Every value in it is an unverified claim by whoever wrote it.
registry/tiers/    what WAS observed. Only this can route.
```

A candidate with no records is visible as **unmeasured**, and routing to it raises. Removing a candidate
de-lists it and never deletes its records, because a decision made last week must stay explicable after the
candidate is gone.

`tierbook discover --base-url ...` prints a **draft** candidate file from a gateway's model list, for a human
to edit and commit. The draft does not load: every price comes out `null`. That friction is the feature. A
gateway advertises names -- asked live, the one this project uses returns identifiers and display names and
nothing else -- so a candidate discovered at compile time would make a routing decision depend on a
publication state nobody committed to.

## Choosing what to optimise

There are no axis switches, and three checkboxes labelled accuracy, performance and cost would misdescribe the
problem in a way that leaks into every later decision.

```json
{
  "objective": "cost",
  "constraints": {
    "non_inferiority": {"margin": 0.15},
    "latency_slo": {"p95_ms": 30000},
    "reliability": {"min_completion_probability": 0.99}
  }
}
```

- **quality is a constraint, and there is no syntax for removing it.** A router permitted to trade quality for
  money without a stated bound has chosen an unstated exchange rate on its owner's behalf. `weights` is
  refused rather than defaulted, because the moment quality is a weighted term, "cheapest" stops denoting
  anything a reader can check.
- **reliability cannot be deselected because it is the denominator.** Both objectives are computed *to
  acceptance*, not per attempt: a failed attempt is paid for again, in dollars when the objective is cost and
  in seconds when it is latency. Measured here once -- retries reordered the arrangements. It is separately
  available as a hard constraint, which removes candidates rather than repricing them.
- **latency is not automatically a constraint.** For a fixed-cost tier it is an *input to the cost model*, via
  throughput; turning that into an SLO would invent a requirement nobody stated. Write one down if you want
  one.
- **the compiler refuses to price a fixed-cost tier from another family's throughput.** The same tier here ran
  94 seconds a task on one family and 17 on another, which moved its cost per request by a factor of three.

## Your own traffic as the benchmark

`tierbook logs <file.jsonl>` reports what your traffic can support before anyone builds a benchmark out of it.
The tasks are the valuable part and ship unconditionally -- a task distribution from your real workload is
exactly what a public benchmark cannot give you.

What does **not** ship is the obvious version: send each logged request to the best model available, keep its
answer as the correct one, score everything else against it. That is refused, and the reason is measurement
rather than principle. A model's judgement of another model's output was measured here at keep-precision 0.78
against a bar of 1.00. And on one family the strongest tier solved 95 of 115 items while cheaper tiers solved
101, each solving six to nine the strongest one failed -- so agreement with the strongest would have marked
them **down** exactly where they were right. That does not add noise around a true ranking; it inverts the
ranking where the ranking decides something. An older strong model is not a fix either: it removes the
tautology and installs a frozen ceiling.

So three things exist instead, and they cannot be confused because the schema distinguishes them:

| facility | evidence class | may assign |
|---|---|---|
| tasks whose outcome something other than a model decided -- an exit status, a schema validation, a test suite that came with the request | `executable_check` | yes, on the property it checks |
| `agreement@ref=<model:version:date>` | `model_reference` | **no**, and it cannot be anyone's validation fold either |
| an audit of the items where candidate and reference disagreed | `human_label` | yes -- the only promotion path |

The audit is minimal for a structural reason: where the two agree, the study contains no information about
which is right, so labelling agreements buys nothing. `coverage()` reports what fraction of the log was
admissible, because a measurement over the 12% of traffic that arrived with a test suite is a measurement of
that 12%. If nothing is admissible, tierbook says **"not measurable for correctness from these logs"**, which
is a real result: it names what you would have to start recording.

## On a cluster you already have

`deploy/` is three objects and no cluster. See `deploy/README.md`.

| object | when | may write |
|---|---|---|
| `measure` (Job) | when you ask | one record into the ledger |
| `compile` (CronJob) | on a schedule | the compiled table, into one named ConfigMap |
| `router` (Deployment) | always | nothing; it reads the table |

Separate because their failure modes must not be shared: a compile that refuses -- and it will, whenever no
held-out fold supports an entry -- exits non-zero and leaves the router serving what it was already serving,
rather than falling back to something nobody chose.

`tierbook export-vsr` turns a compiled table into a vLLM Semantic Router configuration **and the Envoy config
beside it**, because a router config alone routes nothing: the ExtProc names a model in a header and something
has to dial the upstream that name refers to. One priority decision per family, naming exactly one tier. The
router's own multi-factor selector is deliberately unused, because a selector fed by live per-process
statistics chooses from evidence nobody committed to and nobody can review after an incident.

The export refuses: a family with no classifier label, a `provisional` entry without an explicit flag, a chain
whose second stage fires on failures the router does not observe, an entrypoint name the router reserves, and a
data-plane port the router itself binds.

**This path was verified on a cluster**, and doing so corrected eleven things -- six of them fatal or
eviction-level. The router's own log names the decision it took, so the claim is checkable:

```
{"msg":"routing_decision","decision":"tierbook_tool_agent_user_retail","selected_model":"api-cheap-a"}
{"msg":"No decision matched"}
{"msg":"routing_decision","decision":"","selected_model":"api-strong-a"}
```

See `docs/results-router-on-a-cluster.md`.

## What a stranger does on day one

Not routing. **Producing a record for a tier you own**, then asking the compiler what it can and cannot
conclude from it. `harness/` holds the instrument this project used, and `examples/ledger/` is a worked ledger
whose shape you can copy. The contract is `src/tierbook/schema.json`, which ships inside the package; any harness emitting records that conform
works. The rule the instrument must follow: **a call that died on the wire produces `null` and a transport
report, never a zero.** One tier here scored 0 of 20 on an endpoint restriction rather than on the task, and a
harness that had reported that number would have published a false claim about a model.

## One turn of the loop: observe, decide, record, check

v0.1.0 is where the four parts meet. Before it, `decide` was handed a state by whoever called it and nothing wrote a
record, so the mechanism could be described and not run.

**It is one turn, and the loop still does not close.** Nothing here feeds anything back: no arc runs from `record` or
`accept` to `decide`, and a pipeline that cannot update anything from its own log is a pipeline.

What changed is which part is missing. A family that declares an `exploration_rate` now draws randomly among the
candidates whose bound clears its floor, and the log records the realised propensity of the arm actually chosen
alongside the set it was drawn from — so the log can support an off-policy estimate, and what is absent is the
estimator rather than the data. Labels are still not attached automatically: a family declares what produces one and
how long to wait, and nothing calls the labeller.

```console
# what a policy would decide from, and what could not be read
tierbook observe --candidate box --metrics-url http://vllm:8000/metrics \
    --model-name Qwen/Qwen3.6-35B-A3B --authorised true --measured-on 2026-09-08 --out obs.json

# one turn: observe, decide, append the record
tierbook assign --policy policy.json --request-id r1 --candidate box \
    --metrics-url http://vllm:8000/metrics --model-name Qwen/Qwen3.6-35B-A3B \
    --authorised true --previous obs.json --bounds '{"box":0.90,"api":0.70}' \
    --costs '{"box":0.004,"api":0.012}' --log decisions.jsonl

# SCOPE section 12's criteria over that log
tierbook accept --policy policy.json --log decisions.jsonl --uncertified-tolerance 0.10
```

`accept` takes the same policy the assignment was made under, and reads the accuracy floor and the evidence-age limit
out of it. Both are available as flags, and using them is weaker: a number typed at a shell prompt is one the artifact
never wrote down, so the criteria would be computed against a value nothing can confirm. The report says which it used
in `floor_provenance` and `max_age_days_provenance`, so a committed report is readable later without knowing how it was
invoked.

**Four properties are worth knowing before using it.**

**Nothing is defaulted.** A state variable that could not be read is *absent*, with a reason, and `decide` reports it
as `uncollected_variable` and declines to certify. A fabricated zero for `inflight` reads as an idle engine and sends
the next request to the reserved candidate, so the one value a collector must not guess is the one a naive
implementation defaults. `observe` exits non-zero when the state is incomplete, so a deploy script cannot proceed on a
state nobody looked at.

**An arrival rate needs two samples.** It is a derivative of a counter, so the first `observe` refuses it and says how
to obtain one. Reporting a total as a rate is the kind of error that looks like a working collector.

**Every request is assigned somewhere.** SCOPE section 2 is explicit that there is no "choose nothing": the request is
served either way, so `assign` returns the declared default with `certified: false` rather than declining, and the
record says why.

**A criterion passes only when it was shown, not when it failed to be refuted.** Floor compliance fails on a one-sided
binomial tail and passes only when an exact lower confidence bound clears the floor; between the two it is
`unsupported`, with the rate and the bound printed. There is no chosen sample size in it -- an earlier version had one
and it was the wrong shape of answer.

**Most acceptance criteria come back `unsupported`, and that is the honest output.** How many of section 12's nine are
evaluable is a property of the log rather than of the release, so the report says which and why instead of the README
naming a number that goes stale. Each criterion states its own requirement: certification checks need only decisions,
the realised-rate checks need attached labels, the latency check needs recorded latencies, and spend regret needs an
off-policy estimator that does not exist yet. A checker with only pass and fail would have to choose between reporting
a pass it did not earn and a failure it cannot substantiate; `unsupported` names the missing measurement instead.

Two of those requirements moved in this release. Exploration now produces logged propensities that vary, so spend
regret's blocker is the estimator rather than the data — for a family that declares a rate. A family that declares none
still has propensity 1 for every decision, under which the counterfactual arm has no data at all, which is the older
problem and not a lesser one.

`decide.MISSING_FOR_A_CLOSED_LOOP` names **three** gaps — anytime-valid bounds, change-point detection, and a value
for the reserved candidate's scarce capacity — and it is shipped inside every compiled policy artifact, so an item
that stopped being true would be a false statement in a machine-readable file. Three items were removed: a state
collector, in v0.1.0, and logged selection probabilities and exploration, in this one. The first stayed in the list for
a whole release after it shipped, and a test asserted the artifact still claimed it, so the guard over the list
required the artifact to be wrong. Each remaining claim now names the symbol whose existence would falsify it, and a
test fails if any claim and its probe disagree.

## What is deliberately not here

- **No circuit breaker, no retry infrastructure, no server.** Those are your operator's, and shipping them
  would invite running this as production middleware before the evidence supports it.
- **No shared or central registry.** Other people's cohort hashes are unverifiable. The ledger is yours; the
  repository ships an empty one and a worked example.
- **No learned routing, no online adaptation.** Measured, and it lost.
- **No provider zoo.** One generic OpenAI-compatible adapter. Every gateway is its own landmine, and
  collecting them is someone else's project.
- **No serving.** Not qwen, not vLLM, not a model server, not a GPU. A candidate file that describes how to
  start a model fails to load.
- **No `measure` verb.** Running a benchmark is your suite's job; anything emitting records in the documented
  shape is a valid producer. What is here is the part that must not be reinvented per suite: the pre-flight
  that stops a transport failure being recorded as a score, and the coverage report that stops a measurement
  of 12% of your traffic being read as a measurement of your traffic.

## The examples are examples

`examples/ledger/` holds three real tiers measured on two real families, and they are **worked examples of the
schema, not truths about vendors**. Every record carries `measured_at` and a pin of exactly what was measured.
They will go stale; that is what the pin is for.

## Status

**v0.2.0.** One turn runs end to end and the log can now be learned from. A state is observed from a live engine, a
compiled policy decides from it, a family that declares an exploration rate draws randomly among the candidates whose
bound clears its floor, the decision is recorded in the shape SCOPE section 9 requires with the realised propensity and
the set it was drawn over, and the acceptance criteria are computed from that log.

**The loop still does not close.** Nothing feeds an outcome or a verdict back into the policy. What changed is which
part is missing: the propensities vary now, so an off-policy estimate is unidentified for want of an **estimator**
rather than for want of data, and a family declares what produces its labels and how long to wait without anything
calling the labeller.

What v0.2.0 does **not** do: hold an anytime-valid bound, detect a change-point, or price the reserved candidate's
scarce capacity. Those three are named in `decide.MISSING_FOR_A_CLOSED_LOOP`, which ships inside every compiled policy,
and each now names the symbol whose existence would falsify it — because three items were removed this release after
one of them had been false for a whole release while a test required the artifact to keep claiming it.

Two backlog items are written up in `docs/issues/`: reading the box's hidden state to find out whether it breaks an
abstention limit that measured `AUC 0.5000` for a structural reason, and deriving the tie band from a jackknife
instead of taking `--margin` from a human.

Still alpha in the sense that matters: two parameters must come from outside before any of this has a unique answer rather than a Pareto
frontier: **the value of a second** for a family, and **the cost of an escaped defect**. At $1 a defect a
cheap tier ships; at $100 the required keep-precision is 0.993; at $10,000 it is 0.99993 and no affordable
sample can certify it. The router cannot decide that for you and does not pretend to.

`docs/` carries the design, the pre-registrations written before each measurement, and the results — including
the two pre-registrations whose predictions failed.
