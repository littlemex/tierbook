# Contract: make the derivation from measurements to a supported policy work on real data, and say what it rests on

Scope boundary: `/Users/akazawt/tierbook` — `src/tierbook/`, `harness/`, `docs/`, `SCOPE.md`, `tests/`.
Nothing outside that repository. No change to the billing gateway, to `distributed-ai`, or to the vLLM
semantic router.
Base: `194c167` on `main`.

Phase 1 was 22 review rounds against two models (independence verified after a first attempt failed it — see
the note under Amendments) plus a 24-instance measurement that closed the loop end to end for the first time.

## Stop condition

Done when **all four** hold, each counted by an id that survives rewording:

1. Every clause below marked `must` is implemented and has a test that fails without it. Counted as
   *unresolved clause ids*, not as a fraction of the text.
2. `tierbook validate` and `tierbook compile` run against a registry built by the framework itself from a
   measurement run it did not hand-write, and the compiled output states which policy is supported, whether
   it is degenerate, and why. Verified by re-running from a clean checkout.
3. For every family in that registry, the framework prints an answer to **"can the self-hosted candidate be
   used here, and if not, why"**. Counted as families with no such answer; the target is zero.
4. No clause is satisfied by deleting a measurement, widening a margin, or reclassifying an observed failure
   as unobserved. Verified by a test that asserts the *unobserved* states in an artifact are exactly those
   with a recorded reason, and by the margin being an input recorded in the compiled table's provenance.

Deleting a family, a candidate or an instance reduces the numerator and the denominator together, so it
cannot satisfy 2 or 3.

## Out of scope, and why

| # | Finding | Class | Why not here |
|---|---|---|---|
| O1 | Online learning / continuous re-estimation from live traffic | design | **Needs a decision the evidence has not licensed.** The supported policy on real data is degenerate (one candidate per family, nothing certified). A learner has nothing to choose between yet, and both reviewers independently found stable wrong fixed points in online updating under censored evidence. Revisit when a compile produces two candidates whose bounds overlap. |
| O2 | Exploration budget, propensity logging, shadow evaluation | design | Larger than the defect it addresses, while O1 holds. Exploration exists to keep a learner's estimates fresh; there is no learner. |
| O3 | Live occupancy, queue depth, seats and KV as decision inputs | design | **No certified policy conditions on them.** Buying execution and estimation machinery for policies that do not exist is the failure this project has made three times. Revisit when a family's supported policy differs by occupancy. |
| O4 | Multi-tenancy, fairness, per-tenant floors | design | Needs a decision this change cannot make (whose traffic yields), and there is one tenant. |
| O5 | Replacing or forking the vLLM semantic router | design | **Fixed by evidence instead**: on real data no arrangement is selected, so nothing supported is inexpressible in it. Both reviewers independently recommended keeping it as a leaf-dispatch adapter rather than replacing it. Revisit when a compile selects an arrangement. |
| O6 | An accuracy floor as the operator's control | design | Already falsified on this project: over 480 policies on 571 problems, certified lower bounds sat 6.7 points below point estimates and 9 of 10 recommended floors were unwarranted. Both reviewers independently said the primary output must be the cost–success frontier and that a floor is a decision rule applied afterwards. In scope as I7, not as a floor. |
| O7 | Selecting the agent / harness at routing time | design | **Unreachable through the interface.** By the time a model-routing decision is made the agent has built the prompt and the tool state. It is a conditioning variable here (I2) and a task-admission decision above this layer. |
| O8 | Latency as a term in the objective | design | Preference rather than defect. Performance largely follows from the choices the objective makes; an operator may add a constraint, and its treatment is recorded as unsettled rather than resolved by assertion. |
| O9 | Re-running the sweep on a second model to separate agent–model affinity from agent quality | measurement | Larger than this change and needs GPU time. **Recorded as a validity condition on the data instead** (I3), which is what makes the affinity visible rather than laundered. |
| O10 | A judge for families with no verifier | measurement | Unverifiable in this change and actively harmful: a judge would manufacture an accuracy number where no oracle exists. Such families are declared unlabelled (I4). |
| O12 | Adopting a prompt-optimisation framework in the **decision** slot | design | **Investigated and rejected on structure, not on preference.** It cannot produce the zero-LM-call form the slot needs, it has no place to carry a measurement-derived bound (its own evidence vocabulary is a scalar plus LM-written feedback), and its evaluator returns a point estimate with no interval or multiplicity correction — which is this project's known failure mode, unmitigated. Its weight-mutating optimisers also launch their own inference server and are not designed to attach to an externally managed engine behind a gateway. **Kept as a candidate for the harness-tuning axis instead** (see the note below this table). |
| O11 | Replaying a whole captured trajectory against a different candidate and reporting the result as a counterfactual | correctness | **Not deferred — refused.** The first response that differs changes every later input, so what comes out is a new measurement wearing a counterfactual's clothes. Single-turn re-asks are in scope (I12, I14); whole-trajectory replay is a fresh run and must be reported as one. |

## In scope

| # | Clause | Class | Why it must be fixed | Verified by |
|---|---|---|---|---|
| I1 | **must**: a candidate record is keyed by `(agent, model, endpoint, decode policy)`, and the ledger refuses a record that omits any of the four | correctness | One agent in the measured set is the served model's own CLI fork; keyed by model, its affinity is laundered into the model's score | a test that a record missing any of the four is refused, and that two records differing only in agent are distinct candidates |
| I2 | **must**: the agent appears in the record as a conditioning field and never as a routing action | boundary | Claiming it selectable promises what the interface cannot deliver | a test that the compiled table's actions name no agent |
| I3 | **must**: every record carries its validity conditions, and the compiler propagates them into the compiled table | correctness | Every figure was taken at concurrency 1, one repository per instance, one run per item, fixed agent order over an unflushable prefix cache. Quoted without those, they are wrong for the deployment | a test that a table compiled from records with validity conditions carries them, and that a record without them cannot be compiled |
| I4 | **must**: a family declares its label source, or declares itself unlabelled; an unlabelled family may carry cost but no accuracy claim | correctness | Otherwise the framework invents an accuracy number where no oracle exists | a test that an accuracy claim on an unlabelled family is refused |
| I5 | **must**: `unobserved` is never counted as `incorrect`, and every unobserved verdict carries a reason | correctness | Three of four agents silently edited nothing until an autonomy flag was found; folding that into a solve rate puts a configuration fact into a capability number | already enforced by `evidence.py`; add a test that a record whose artifact marks a timeout as `incorrect` is refused |
| I6 | **must**: the compiler states, per family, whether the supported policy is degenerate, an arrangement, or unsupported, and prints the reason | correctness | "The framework cannot say which policy is supported" is the failure mode; a degenerate answer is a correct answer and must be reported as one rather than inferred from silence | a test on the compiled table's own fields, and the real-data run in the verification plan |
| I7 | **must**: the compiler emits the cost–success frontier for the family, not only the selected point | correctness | An operator who cannot see the exchange rate cannot choose a floor, and a floor chosen blind is a guess wearing a policy's clothes | a test that the table carries every candidate's (cost, success bound) and marks which are on the frontier |
| I8 | **must**: for every family, the compiled table answers "can the self-hosted candidate be used here, and if not why" | requirement | A standing requirement of this project | a test that the field is present for every family, and that its reason is one of a closed set |
| I9 | **must**: an exporter refuses a policy it cannot execute, naming the policy and the reason, rather than exporting a reduced form | boundary | Exporting the head of an arrangement drops the safety net that justified it. `export_vsr.py` already refuses; the clause makes it a contract rather than a behaviour | a test that a table containing an arrangement fails `export-vsr` with the arrangement named |
| I10 | **must**: `SCOPE.md` states the purpose first — lower cost with as little accuracy loss as possible — and every environment-specific number in the repository is a parameter reading, not a conclusion | claim | The document currently reads as a mechanism specification with the purpose behind it, which is how it kept being turned into cluster tuning | `/claim-anchoring` over `SCOPE.md` and `README.md`, with every guarantee sentence anchored to a clause id here |
| I11 | **should**: `harness/sweep_to_ledger.py` becomes the supported path from a measurement run to records, with the four ledger refusals it had to satisfy recorded as tests | correctness | The ledger refused four drafts and every refusal was right; without tests the next producer rediscovers them | tests that reproduce each of the four refusals |
| I12 | **must**: every call is captured with enough to re-ask it — the request as sent, the four token legs, latency to first byte and to completion, and the candidate tuple that served it. **Charge comes from the billing gateway and from nowhere else**; any client-side cost figure is stored beside it as `cost_estimate_client`, labelled, and never used as the ledger's cost | requirement | Whether a different model or a changed prompt would have done better is answerable later **only if the inputs were kept**; the cost of keeping them is a log line. But charge has one authority: two of them disagree over retries, cache legs, credits and negotiated prices, and then a figure that reads as complete is not. This project already had a price disagreement produce a 36x error | a test that the ledger's cost field is populated only from a gateway-sourced charge, and that a record whose cost came from a client estimate is refused |
| I13 | **must**: trajectory capture is **delegated, not built**. The agent emits OTLP (`@devtheops/opencode-plugin-otel` v1.5.1 exports `opencode.token.usage` split into input/output/reasoning/cacheRead/cacheCreation, plus traces and log events); this project provides the **receiving endpoint** and the join, and nothing else | requirement | Storing and accumulating traces is solved outside this project, and building a second one makes it this project's maintenance burden for no gain. What is not solved outside is the join to the charge and the identity, which only the gateway holds | a test that a trajectory read from the OTLP receiver yields turn order and per-turn usage, and that no code in this repository writes a trajectory store |
| I15 | **must**: the join between a trace and its charge is measured, and a partial join is an error rather than a silent subset | correctness | The plugin injects W3C `traceparent` into the provider call for configured providers, which is how a trace reaches a gateway span without changing the gateway's schema. **A cost figure built on a partial join reads as complete**, which is the worst available failure | a test that the join reports a coverage rate, and that a coverage below a stated threshold refuses to produce a cost figure rather than producing one over the joined subset |
| I16 | **must**: a divergence between the gateway's charge and the client-side estimate is reported, never averaged and never silently preferred | correctness | Two authorities disagreeing is information: it is how a 36x price error was found here. Averaging destroys exactly the signal | a test that a divergence beyond a stated ratio is surfaced as an alarm and blocks compilation of that family |
| I21 | **must**: the decision is a **replaceable component** with a declared interface — `decide(request, state) -> candidate, evidence` — and the framework never assumes which implementation is in the slot. At least two forms exist and are interchangeable: a **compiled lookup** (no model call at all) and a **judge that runs on a candidate** (a prefill or hidden-state probe on the self-hosted engine). **The two forms are genuinely different implementations, not one parameterised**: a prompt-optimisation framework was investigated for this slot and cannot produce the zero-call form at all, so a design that assumes one mechanism covers both is wrong | design | Without the slot there is nowhere to substitute a decision function that later tuning produces, and the pattern the project started from — decide on the self-hosted engine first, then route — would be designed out. Whether the box is inside `decide` or `decide` is an optimised fixed function is deliberately not this contract's business | a test that a second implementation can be registered and selected without changing any caller, and that the compiled-lookup form and a probe form both satisfy the same interface |
| I24 | **must**: `decide`'s declared input is the set a decision function of either form can actually be fed — the request's family label and observable shape, the registered candidate set, the measurements in force with their validity conditions, and the state the execution contract can carry. **Signals that only one implementation can obtain are named as such**: token logprobs are reachable only outside a typed prompt-framework return value, and hidden states are unobtainable through any OpenAI-compatible layer and require the engine's native interface | boundary | An interface that promises a signal one implementation cannot get is a promise the slot cannot keep, and the investigation found exactly two such signals | a test that each registered implementation declares which of the named signals it consumes, and that registering one which consumes a signal the deployment cannot supply is refused at load |
| I25 | **must**: any candidate or decision implementation whose selection was searched carries **how many alternatives were compared**, and a bound rather than a point estimate | correctness | The searched-winner problem is this project's own hard-won result and it is not solved by any external framework: the one investigated returns a single point estimate from its evaluator, with no confidence interval, standard error or multiplicity correction anywhere, while its optimisers search 6 to 18 candidates and pick the best on a validation set. Adopting such a tool without adding this is adopting the failure | a test that a compiled table records the candidate count behind each selection, and that a selection reporting only a point estimate is refused |
| I22 | **must**: a decision function's own cost, latency and accuracy are measured and carried like any candidate's, and a policy that uses a probe is priced **including** the probe | correctness | A probe that runs on the engine consumes the capacity and the money serving needs. Unpriced, it looks free, and then a policy that pays for a probe on every request compares favourably against one that does not | a test that a policy whose `decide` calls a candidate carries that call's tokens and charge, and that the frontier places "with probe" and "without probe" as distinct points |
| I23 | **must**: the example demonstrates **both** decision forms end to end, and reports which one the measurements support | requirement | The self-hosted engine can expose hidden-state signals an API candidate cannot; that is an uncounted reason to hold one, and it only becomes counted if a decision form that uses it is actually run and priced. "The fixed table was enough" is an equally valid finding and must be reachable | the example's own output names the supported form and the margin over the other |
| I18 | **must**: the initial calibration and the continuous capture are **one mechanism**. A benchmark run is ordinary traffic: it goes through the agent, the agent's telemetry, the join and the ledger builder that production traffic goes through. The sweep's only remaining jobs are staging the task, driving it, and applying the oracle | correctness | Two producers of ledger records mean the same figure is computed two ways and they diverge; the divergence is then discovered as a contradiction in a report rather than as a build failure. It also doubles what must be kept correct for no gain | a test that no ledger record can be produced from a path the continuous capture does not use, and a run of the benchmark that produces records **without** the sweep computing any token or cost figure itself |
| I19 | **must**: the ledger builder joins three sources and names each — **outcomes** from the oracle, **telemetry** from OTLP, **charge** from the gateway — and refuses a record where any of the three is missing rather than filling a default | correctness | A record silently missing its charge, or carrying an outcome with no telemetry, is the shape that reads as complete. The three have different owners and different failure modes | a test that a record missing any of the three sources is refused, naming which |
| I20 | **should**: the recording pass-through is retained as an **independent cross-check** on the telemetry, not as a producer | correctness | It found two real defects the agent's own telemetry would not have shown: a fourth spelling of the cache-write leg from the engine, and two different conventions for the same quantity on one gateway. Two independent views of the same number is the same principle as I16 | a test that its figures are compared against the OTLP figures and a divergence beyond a stated ratio is surfaced |
| I17 | **must**: prompts are not exported to a third-party store by default. Repository contents and possibly customer data are in them; the capture stays useful without them because token counts, turn structure and outcomes do not require the text | correctness | The plugin can log prompts and the collector may be hosted. A default that ships prompts off-cluster is a privacy decision made by omission | a test that the shipped configuration disables prompt logging, and that enabling it requires an explicit setting whose name says what it does |
| I14 | **must**: the capture states what it licenses. A stored trajectory supports a **faithful re-ask of any single turn**; it does not support replaying a whole trajectory against a different candidate, because the first differing response changes every later input | correctness | Without this line someone will report "the same trajectory under a different model", which is a different experiment. Naming the limit is what makes the faithful half usable | the recorded artifact carries the limit as a field, and a test asserts a whole-trajectory replay is refused rather than silently performed |

**On the harness-tuning axis, deliberately outside this contract.** A prompt-optimisation framework is a
plausible fit *there* rather than in the decision slot: its object of optimisation is the instructions and
demonstrations of a system that contains LLM prompts, and the published claim for its reflective optimiser is
that it beats an RL baseline by 6 to 20 percent using up to 35 times fewer rollouts on tasks involving
reasoning and tool interaction — which is the shape of this project's own largest measured lever, a system
prompt replacement that cut input tokens 2.1x on an identical task. Two things must travel with any such
adoption: the selection-validity layer of I25, because moving the tool to a different axis does not remove
the point-estimate problem, and the note that its cost lands on the gateway automatically when its client is
pointed at the gateway rather than at the engine. Two operational traps were found and are recorded so they
are not rediscovered: its disk cache key ignores the endpoint, so the same prompt against two engines
collides, and its weight-mutating path starts its own server.

## Alternatives considered and rejected

| Finding | Alternative | Why not |
|---|---|---|
| I6 | Emit only the selected policy, as today | A selected policy with no statement of its kind cannot be distinguished from a policy chosen by default, which is the failure mode |
| I7 | Report a single certified winner | Already falsified: quoting a search winner at its point estimate is what produced 9 of 10 unwarranted floors |
| I9 | Export the arrangement's head and warn | Reviewer-proposed and rejected: the second stage is the safety net, and a warning does not restore it |
| O5 | Fork the semantic router to add arrangements | No supported policy needs it yet; a fork is a permanent cost against a hypothetical benefit. If one is ever needed, contribute upstream — the capability is "a decision may name an arrangement and be re-entered on an observable failure" |
| O1 | Build the learner now and gate it behind a flag | A flag is not a decision. Unused machinery still has to be correct, and both reviewers found its failure modes are silent |
| I1 | Key records by model and record the agent as metadata | This is exactly the laundering the affinity case demonstrates |
| I21 | One parameterised decision mechanism covering both forms | The investigated prompt-optimisation framework has no zero-call compile target in any of its optimisers, so "one mechanism, two settings" is not available; assuming it would have produced an interface neither form fits |
| I25 | Trust the optimisation framework's own validation split | It auto-splits silently in one optimiser and warns-but-proceeds in another, and neither computes an interval. A split without a bound is not selection validity |

## Interface

**`Record`** — one candidate's measurements. `id`, `serves: {model, endpoint}`, `adapter: {agent, decode_policy, wire, compliance}`, `claim: {kind, metric}`, `oracle: {kind, independent_of_candidate, existed_before_candidate_output}`, `measurement_target`, `price_card`, `latency`, `reliability: {..., failure_classes}`, `provenance: {..., validity_conditions: [str]}`, `families: {<f>: {solved, attempted, suite, runs_per_item, evidence: {path, digest}}}`. Refused when: any of the four candidate keys is absent (I1); `validity_conditions` is absent (I3); an accuracy claim is made on a family the record declares unlabelled (I4).

**Evidence artifact** — JSONL. Line 1 is a header carrying `suite_manifest_digest, run_id, scorer_version, subject, family, trials_per_item=1, produced_at`. Each later line is `{item_id, state}` with `state ∈ {solved, incorrect, unobserved}` and `unobserved_reason ∈ {policy_refusal, unsupported, execution_error, not_selected}` required exactly when `state == unobserved` and forbidden otherwise (I5). The filename contains the first 16 hex of the file's own digest. A path is resolved against the ledger root, which is the registry directory's parent.

**Compiled table**, per family, adds: `policy_kind ∈ {degenerate, arrangement, unsupported}` with `policy_kind_reason` (I6); `frontier: [{candidate, cost, success_lower_bound, on_frontier: bool}]` (I7); `self_hosted: {usable: bool, reason}` where `reason ∈ {selected, not_certified, no_capacity_evidence, cannot_be_reached, dearer_at_realised_load, no_record}` (I8); and `validity_conditions` unioned from the records it read (I3).

**`tierbook export-vsr`** — exit non-zero, naming the family and the arrangement, when the table contains a policy the target cannot execute (I9). Unchanged otherwise.

**`harness/sweep_to_ledger.py --state --tap --pods --out --family --commit`** — writes `<out>/tiers/*.json` and `<out>/evidence/*.jsonl` (I11).

**Captured call row** (I12) — what the tap records today, plus `candidate: {agent_definition, model, endpoint, decode_policy}`, `charge: {usd, source: "gateway", gateway_request_id}` and `cost_estimate_client: {usd, source}` kept apart. A row whose `charge.source` is not the gateway may not be compiled.

**Trajectory** (I13) — read from the OTLP receiver, not written by this repository: `{trace_id, run_id, candidate, family, item_id, turns: [{index, span_id, usage, finish_reason, tool_calls, ttfb_ms, total_ms}], totals, licence}`. `licence` states the I14 limit in the artifact itself.

**Join** (I15) — `join(trace, ledger) -> {rows, coverage, unjoined: [...]}`. Coverage below the stated threshold refuses a cost figure and names the unjoined rows.

## Verification plan

Phase 5 builds a registry **from scratch**, on the real cluster, and observes a policy come out of it.

1. From a clean checkout at the contract's head, re-run `harness/sweep_to_ledger.py` against the recorded sweep state and tap log. Evidence: `tierbook validate` accepts every record with no notes.
2. `tierbook compile` with each of the four candidates as reference in turn. Evidence: every family reports `policy_kind`, a frontier with at least two candidates placed, and a `self_hosted` answer. The degenerate result is the expected one and must be *stated*, not inferred.
3. `tierbook export-vsr` against that table. Evidence: it succeeds while the policy is degenerate, and fails naming the family when an arrangement is injected into the table by hand.
4. **A second measurement run through the live path**, not a replay: drive the agents on two instances that were not in the sweep, produce records, compile, and confirm the answer changes only in ways the new evidence explains. Evidence: the two runs' artifacts, their digests, and the two compiled tables.
5. **A single-turn re-ask from a captured trajectory** (I12, I14): take one turn from a stored trajectory, re-issue it byte-identically to a different candidate, and record both outcomes. Evidence: the two responses, the two costs computed from the rows alone, and a refusal when a whole-trajectory replay is attempted.
6. The trusted objects this change creates are watched: `<out>/tiers/*.json`, `<out>/evidence/*.jsonl`, the compiled table and the trajectory artifacts are all inputs a later claim rests on, so step 1 re-derives them rather than reading a stored copy.

Environment: `distai-eks` / namespace `qwen-trial`, the engine and agents already deployed; the registry directory is created fresh and not reused.

## Amendments

- **2026-09-07, independence of phase 1.** The first pass of the review rounds was run with the reviewing
  model's working directory inside the artifacts tree, and `sandbox_mode=read-only` grants read access to the
  whole filesystem. That model read the other's answers — 556 references in one round. All 22 rounds were
  re-run with the other model's output relocated outside the tree and the working directory neutral, and
  independence was re-checked (0 references). Any statement that the two models "independently converged"
  refers only to the re-run.
- **2026-09-07, the runtime refusal is withdrawn.** An earlier draft of `SCOPE.md` made refusal a runtime
  outcome. It is incoherent: the request is served either way, so declining to choose only means the declared
  default chooses while the mechanism disclaims the consequence. What refuses is certification. The
  bootstrap-candidate machinery added to escape the resulting cold-start contradiction is withdrawn with it.
