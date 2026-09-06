# Scope: what this project is, what it may not become, and what would prove it broken

**This is the governing document. Every other document in this repository is subordinate to it.** It is
normative: a requirement here is one a reviewer can hold an implementation to, and a sentence that cannot
be held to has no business being here.

## 1. What is being built

A routing layer over a **mixed fleet** — self-hosted fixed-cost serving plus several paid APIs, with new
models and new coding agents arriving over time. It discovers its own parameters in whatever environment it
is placed in, keeps re-estimating from live traffic, and decides where each request goes. **Every request is
assigned somewhere**, and each assignment says whether the evidence licensed it.

## 2. Definitions

These are used with exactly these meanings throughout. An implementation that leaves any of them to the
reader is not compliant.

**Task** — one unit of work a caller wants completed, which may span many model calls.

**Success** — the task's own oracle says so. Where the caller supplies a verifier (a reproduction test, a
schema, a checker) that verifier is the label. Where none exists, the family is **unlabelled** and no
accuracy floor can be held for it; the mechanism says so rather than substituting a judge. The label's
**source and maximum latency** are declared per family (section 5).

**Family** — a partition of requests within which evidence is pooled. The partition function and the
labeller are declared, versioned, and part of the decision record; "similar traffic" is not a family.

**Candidate** — what a decision selects:

```
(model, serving endpoint, decoding and tool policy)
```

conditioned on, but not selecting, the **agent / harness and version** that produced the request. See
section 4 for why the agent is a conditioning variable here and a selectable one only at task admission.

**Admissible** for a request means all three, jointly:

1. the candidate's corrected lower bound on success clears the family's floor (section 6),
2. the gateway authorises the spend (section 3), and
3. the SLO is feasible at current occupancy (section 5).

**Certified assignment** — an admissible candidate was chosen. The floor is claimed for this request.

**Uncertified assignment** — no candidate was admissible, so the request goes to the family's **declared
default candidate** and the record says the floor is **not** claimed for it.

**There is no "choose nothing".** An earlier draft of this document made refusal a runtime outcome, and
that was incoherent: the request is served either way, so declining to choose only means the default
chooses while the mechanism disclaims the consequence — worse than choosing, because the choice is then
unrecorded. What legitimately refuses is **certification**, which is a statement about a claim: the ledger
declines to say a tier beats another for a family when a held-out fold does not support it. That refusal is
older than this document and stays. It happens where claims are made, not where traffic is served.

## 3. The decision, and the objective

```
route(request, state) -> assign(candidate, evidence, certified: bool)
```

**The objective, stated as a formula because prose was ambiguous:** minimise the **expected total gateway
charge to complete one task under the declared retry policy**, subject to (a) a lower confidence bound on
task success clearing the family's floor, (b) the SLO expressed as a bound on `P(latency > L)`, and (c)
gateway authorisation. Not `E[charge | success]`, and not `E[charge] / P(success)` — those are different
quantities and two implementations optimising different ones would both have claimed compliance.

Every occasion in section 5 is that one objective re-evaluated on changed inputs.

### Authority boundaries

| concern | authority | this project's part |
|---|---|---|
| what a call cost, what remains authorised, cutting off anomalous spend | **the billing gateway** | reads its quotes and authorisation; **never reconstructs charge, never implements its own cutoff** |
| how a caller reaches a decision at all | **the vLLM semantic router contract**, community-owned and unchangeable here | expressible within it, invoked through a synthetic model name. An uncertified assignment uses the contract's own declared default, which `export_vsr.py` already configures; no new representation is needed |
| which candidate, and whether any is admissible | this project | all of it |

**The gateway quotes every candidate in the objective's unit, including the fixed-cost tier.** That is a
stated requirement on the gateway, not an internal cost model: two authorities for charge disagree over
retries, cache legs, credits and delayed usage, and then the router permits spend the gateway would refuse.
Anything this project computes about occupancy or option value is a **scheduling utility**, never financial
cost, and it may never override gateway authorisation.

## 4. Where the agent sits

The agent is the largest measured term and the hardest to place. With the model held constant, four coding
agents differed by **13.2×** in input tokens on identical tasks, and by **5.5×** in how many sessions fit in
one engine's KV cache. So it cannot be ignored. But by the time a model-routing decision is reached, the
agent has already built the prompt and the tool state: a downstream router cannot swap it and replay the
task faithfully.

Therefore, explicitly:

- **At routing time the agent is a conditioning variable.** Cost, accuracy evidence, request shape and
  capacity footprint are estimated per `(agent, candidate, family)`; aggregating them by model confounds
  the largest term with the smallest.
- **Selecting the agent is a task-admission decision**, upstream of the routing contract, and requires an
  orchestrator surface this project does not own. It is in scope as a stated interface and **out of scope
  for the first version's action space.** Claiming the agent as selectable while it is not reachable would
  be a promise the interface cannot keep.

## 5. Policy inputs and derived quantities

**The policy-input list below is closed.** Adding a row requires amending this document with the "why
observation cannot supply it" column filled in. **A constant that observation could supply is a derived
quantity regardless of where it is written; putting it in a configuration file does not cure the defect.**
That sentence exists because the obvious way to satisfy this document is to hoist a tuned threshold — "if
concurrency > 7", "off-peak after 22:00" — into config and call it policy.

| policy input | why observation cannot supply it |
|---|---|
| accuracy floor, per family and per tenant | no measurement says whether 90% or 95% is acceptable |
| SLO: the latency L and the tail probability | a promise, not a fact |
| success label source and maximum label latency, per family | a choice about what counts as done |
| family partition function and version | a modelling choice about what may be pooled |
| confidence level, multiplicity family, and the significance `s` used to test coverage | risk tolerances |
| evidence window `W`, minimum effective samples `n` | how much staleness and how little data is tolerable |
| exploration budget: share of traffic and spend per day | how much money may be spent learning |
| **default candidate per family** | day one has no evidence, and an uncertified assignment has to go somewhere; deliberately not "the cheapest" |
| default evidence-transfer model across tenants | fairness and validity, not observation |
| reservation price of the fixed-cost tier | a contract; supplied to the gateway so it can quote it |
| deferability of a request class | a classification of caller intent |
| tenant shares, priority classes, exploration eligibility | fairness is a decision |
| acceptance tolerances: regret, SLO violation, adaptation window, off-policy error, maximum uncertified share | what counts as good enough |

**Derived continuously:** arrival rate and concurrency; seats, KV capacity and saturation throughput;
prefix-reuse rate per family; per-tuple request shape and context lifetime; per-tuple error and latency
distributions; live occupancy and degradation; accuracy bounds per tuple per family.

**The rule:** every operational threshold is computed from derived quantities plus stated policy inputs. A
number in code that is neither is a defect, and the mechanism must never present a policy choice as an
empirical estimate.

### The occasions, as one objective re-evaluated

| the input that moved | what the objective then says | derived from |
|---|---|---|
| concurrency, queue depth | the marginal request on the fixed tier costs delay, and delay is constrained | seats, KV, saturation throughput, live queue |
| arrival rate over the accounting horizon | the fixed cost amortises or does not | gateway quote for the fixed tier, realised tasks/h |
| a vendor price changes | the cheapest admissible candidate changes | gateway quotes |
| an API rate-limits, errors or slows | its SLO feasibility falls | observed per-tuple error and latency |
| a cheaper or stronger model appears | it enters on evidence, not on release notes | section 6's pipeline |
| the engine degrades: replica lost, KV pressure, hit rate falling | effective capacity is below configuration | live occupancy, not the flags |
| the request's shape: prefill- or decode-heavy, prefix reuse likely | which candidate is cheap *for this request* | per-family, per-tuple shape |
| a new agent or agent version | a different conditioning context, with its own estimates | per-tuple estimates |
| floor or SLO changes | the admissible set shrinks or grows, possibly to empty | policy inputs |
| the gateway's authorisation runs down | the admissible set shrinks to what it will authorise | the gateway |
| off-peak, fixed cost already sunk | deferable work may have a cheaper place, if capacity has no option value for imminent interactive work | clock, deferability, forecast occupancy |

"Fill the fixed tier while the SLO holds" and "batch belongs on the engine that is paid for anyway" are
**not** rules here. Both are wrong in reachable cases — capacity has option value when interactive work is
about to arrive, batch deadlines differ, and the fixed tier may not clear the floor at all.

## 6. The evidence contract

A candidate is admissible for a family only when a lower confidence bound on success — **anytime-valid**,
because bounds are recomputed continuously and admission happens at a data-dependent stopping time, so
fixed-sample intervals are anti-conservative here — clears the floor, computed over the declared
multiplicity family (candidates × families × tenants × the selection process itself) on at least `n`
effective samples whose validity assumptions still hold.

**A point estimate never gates admission.** Over 480 policies on 571 problems, certified lower bounds sat
6.7 points below point estimates and 9 of 10 recommended floors were unwarranted. That is why this section
exists.

A bound becomes unusable for admission when its **declared validity assumptions or its freshness contract
no longer hold** — not merely because it is old. Age alone invalidates nothing; a detected change point
does.

New candidates enter through a pipeline, never a config edit: shadow or ε-rate evaluation, bound recomputed
as samples arrive, admitted when it clears, retired when it stops clearing.

## 7. Multi-tenancy

The fixed tier is shared and scarce, and one agent measured at 13.2× another's tokens can occupy it alone.
Admission to it is subject to a fairness or priority policy (section 5).

Per-tenant evidence at `n` samples per tenant per family per tuple within `W` **cannot** be sustained by a
bounded exploration budget as the fleet grows. So the resolution is stated rather than improvised: when the
budget cannot sustain per-tenant evidence, **the declared default transfer model applies** — pooling across
tenants while holding per-tenant floors — and where even that does not license a bound, the admissible set
shrinks and the tenant's traffic becomes an uncertified assignment to its declared default. Pooling is a
declared policy input, not an emergency measure.

## 8. Exploration, and day one

Re-estimating a candidate you are not using means sending it traffic you believe is worse: real requests,
real money, real accuracy risk.

- Exploration has a **spend and capacity budget** (policy input) and is authorised through the gateway.
- Floor-critical traffic is not *silently* routed to an unadmitted candidate: it may be assigned there, but
  only as an uncertified assignment that says so. Shadow evaluation is the alternative where the class
  cannot tolerate that.
- **Every decision records whether it was exploration and with what probability.** Without logged
  propensities no later counterfactual is identified.
- **Day one:** before any candidate is admitted for a family, traffic goes to that family's declared default
  candidate as an **uncertified assignment**, while evidence accrues through shadow evaluation funded by the
  exploration budget. Nothing is blocked and no floor is claimed. An earlier draft made day one impossible by
  requiring refusal instead; with a declared default the contradiction does not arise.
- **Staleness is tracked per estimate and reported.** Routing away from a candidate starves its evidence, so
  a minimum measurement rate is maintained or the estimate is declared expired.

## 9. The decision record

Each decision appends: a **versioned feature vector** and references to immutable state (not a literal
snapshot of everything, which would be unbounded and would carry tenant content); the candidate set with the
reason each was excluded; per-candidate estimates with bounds and freshness; the chosen candidate and its
selection probability; whether it was exploration; policy and mechanism versions; agent, model and endpoint
versions; the gateway's quote and authorisation state; and, when it arrives, the outcome — tokens, latency,
failure, and the success label, with **label-missingness recorded explicitly**.

Any claim that another choice would have been better must come from an identified method — randomised
exploration with logged propensities, inverse-propensity or doubly-robust estimation, or a declared design.
Comparing the chosen arm against a guess is not one.

## 10. Behaviour when estimates are wrong

Decisions are uncertainty-aware rather than point-driven. Estimates carry freshness limits after which they
stop being usable. Drift raises an alarm. The conservative response is the declared default as an uncertified
assignment, never a certified claim built on a guess. Updates are rate-limited and reversible.

## 11. What this may not become

**Not a tuning guide for one cluster.** "This deployment needs seven concurrent sessions", "this engine
seats 128", "this agent fits 272 sessions in KV" are **parameter readings**, not results.

Two acceptance conditions, because prose alone did not hold:

1. **A deliverable is accepted only if it contains executable derivation code that, given another
   environment's observations, produces different numbers without being edited.** Parameter readings appear
   only as that code's test fixtures.
2. **The calibration routine takes no environment-specific arguments beyond endpoints, credentials and the
   versioned policy file of section 5** — with probing load limits a row in that file. It must be
   demonstrated on two environments that differ in hardware or fleet composition, not two namespaces of one
   cluster.

**Calibration is a deliverable; any particular calibration result is a test fixture.** That distinction is
the acceptance condition, not a matter of reading.

**Not a benchmark.** Measurements populate parameters. The instruments in `harness/` must each name the
parameter row in section 5 that they feed; **an instrument whose output no row consumes is out of scope**,
or the loop of measure, ask which parameter it estimates, measure again runs forever and `route()` is never
written.

## 12. Acceptance criteria, and what would prove this broken

Pre-registered, reported rather than asserted, and computed only from what section 9 requires to be logged.

| criterion | measured how | fails if |
|---|---|---|
| floor compliance | realised success rate on routed traffic, per family, against that family's floor | it falls below the floor beyond sampling error at significance `s` |
| bound calibration | the confidence procedure on pre-registered resampling or simulation where the estimand is known | a pre-declared test rejects the claimed coverage at significance `s` |
| no false certification | over the log, against section 2's three-part definition | any decision marked certified whose candidate was not admissible |
| default is not a hiding place | over the log | an uncertified assignment was made while an admissible candidate existed, or the uncertified share exceeds its stated tolerance |
| SLO | realised `P(latency > L)` per traffic class | it exceeds the stated tolerance |
| spend regret | **estimated** by section 9's declared off-policy method, with an interval | the interval's lower edge exceeds the stated tolerance |
| exploration cost | from the log | it exceeds the budgeted share |
| adaptation | inject a price change, a model release, an agent swap, a capacity loss | the new candidate does not enter shadow evaluation within the adaptation window, or is not admitted once its bound clears, **or either requires a code change** |
| genericity, and usefulness | a held-out environment and a candidate introduced after implementation freeze; the held-out run reuses the incumbent policy file except genuinely environment-owned rows (floors, SLOs, prices, budgets, default candidates) | routing logic must be edited; **or any other policy value must be changed**; **or the certified share falls below its stated minimum while the acceptance oracle identifies a feasible admissible candidate** |

That last row's second half exists because "generic by sending everything to the default" would otherwise
pass every other criterion.

**The falsifier:** the mechanism is broken — not mistuned — if it marks an assignment certified when the
candidate was not admissible under section 2, or if its confidence procedure fails the calibration test.

## 13. The test a sentence in this repository has to pass

Before writing a recommendation, check that it survives a change of environment, price list, agent and user
count. If it does not, it is a parameter reading and belongs in a measurement record. What belongs in the
conclusion is **the code that produces it, with the reading as that code's test fixture.**
