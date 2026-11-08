# v0.5 design: tierbook as the certification plane beside a request-path router

**Status:** adopted for v0.5. Supersedes the positioning in `docs/DESIGN.md` where the two disagree; it does not
retract any measurement in `docs/results-*.md`.

## 1. What changed outside, and what it does to this project

Three things moved between the first design (2026-08) and now (2026-11). The survey behind this section is summarised
in `docs/prior-art-2026-11.md`.

**Per-request routing became a commodity.** vLLM Semantic Router (v0.4.0, 2026-09-27) ships a declarative
signal → decision → algorithm pipeline with a dozen selection algorithms, a cost/quality/latency `multi_factor`
selector, OpenTelemetry tracing, a replay audit log and a versioned config contract with a migration command.
LiteLLM, Kong, Cloudflare, OpenRouter, Requesty, Azure Model Router and Bedrock Intelligent Prompt Routing all route
per request with some notion of cost. Writing another request-path selector would duplicate all of that and lose.

**Nobody turns outcomes into a certified assignment.** Every surveyed router prices models from a hand-written card
and scores quality from a public index or an opaque classifier. Where a learning loop exists it is process-local
(vllm-sr's `routing_sampling` experience is not shared across replicas), manual (vllm-sr's `recipe-learning` writes
proposals a human applies; NVIDIA's retraining is manual), or closed (OpenRouter, NotDiamond, Azure). The one design
that states the missing object precisely is vllm-sr's own **`success_constrained` proposal (2026-09-04, status
Proposal, unimplemented)**: choose, among candidates whose calibrated `P(success | request, candidate)` meets a
target, the one with the lowest lifecycle cost.

**The literature now says which parts of that object matter.** Routing gains concentrate in a static per-task-type
assignment (arXiv:2608.23023: 21 of the 29 recoverable items are taken by one model per task type; 2606.07587:
21 learned routers plateau together). The evaluation unit that survives price changes is cost per solved task
(arXiv:2504.13359 cost-of-pass; 2510.11977 HAL). Picking the best of many policies on the same data overstates it
(winner's curse: 2510.18161, 2607.18545; selection-valid bounds: 2608.08265), which this project measured itself as a
6.7-point gap (`docs/results-selection-cost.md`). Prices and models move, so the price must be separable from the
measurement (2604.00136 ParetoBandit, 2506.17254 StageRoute).

**Consequence.** tierbook stops being a router. It is the plane that answers, from your own outcomes, *which arm each
task type should go to, at what cost per accepted task, with what guarantee* -- and hands that answer to whatever
router is on the request path, then re-answers when prices, models or outcomes move. vllm-sr's `success_constrained`
names the object; tierbook computes it offline, certifies it, and exports it as configuration the router already
understands.

## 2. The pipeline

```
source log ──┐
outcomes ────┴─> ingest ─> observations.jsonl ─┐
candidates.json ───────────────────────────────┼─> tally ─> derive ─> policy.json ─> export ─> router
declarations.json ─────────────────────────────┘                          ▲                     │
                                                                          └── drift <── routed traffic
```

Each step is a pure function from files to a file, and each owns one sentence. A change that makes a step do more
than its sentence is stopped in review.

| step | owns exactly |
|---|---|
| `ingest` | mapping a source log's fields, and joining it to the caller's outcomes by `(item, arm, run)` |
| `tally` | per (task type, arm, item) results over fresh attempts, and the partition each item falls in |
| `derive` | bounds, the comparison, the status of each assignment, the fallback |
| `export` | translating a policy into a router's configuration, or refusing |
| `drift` | the diff between a deployed policy and a re-derived one, and whether fresh evidence contradicts it |

There is no `loop` verb. The loop is the composition `ingest -> derive -> drift -> export`, run by whoever operates
it; `examples/certification_loop/` is one such composition, and the verb is fixed only once running it shows what
must be fixed.

**What the loop needs from outside, stated as a premise rather than hoped for.** Routed traffic yields outcomes only
for the arm it was routed to, and only where a grader runs. So the loop closes for an arm that is serving, and an arm
that is not serving is re-measured by whoever operates the loop (a drive on a sample of traffic). `drift` names the
cells that need it; nothing is re-assigned on evidence that does not exist.

### 2.1 Observation: the only record

One line per attempt of one item by one arm in one run:

```json
{"item": "mmlu-pro:1234", "task_type": "law", "arm": "api-cheap-a", "run": "r1",
 "outcome": "accepted", "usage": {"fresh_in": 812, "cached_in": 0, "out": 3},
 "latency_s": 0.84, "observed_at": "2026-11-08T09:12:00Z", "label_source": "dataset", "source": "drive"}
```

* `outcome` is `accepted`, `rejected` or `unobserved` (with a `reason`). The grader is the caller's; ingest joins
  the grader's file to the source log and marks every attempt it cannot join `unobserved: ungraded`. A grade for a
  call that returned no answer is refused, not overridden: the two inputs disagree and choosing is not a mapping.
* `finish_reason` is carried from the completion. An answer cut off at the output budget is still the grader's to
  judge; the count of cut-off attempts per cell is what lets a reader see that the budget, not the arm, decided it.
* **One record per attempt.** An identical line read twice is one attempt; two different records for the same
  `(task type, arm, item, run)` are refused. `ingest` replaces its output unless `--append` is given.
* `usage` is tokens. **Cost is always recomputed from the current candidate file**, so a price change re-derives the
  policy with nothing re-measured. Empty `usage` means the source did not report it, which is unknown and not zero:
  an arm whose graded attempts carry no usage is unpriced. A source that knows the billed amount records `billed_usd`; it is reported beside
  the computed cost for reconciliation and is never what a choice is made on, because it is yesterday's price.
* `task_type` is the label the assignment is keyed on, and `label_source` says who produced it. The assignment is
  exported against the router's own label, so an assignment derived from a label the router did not produce says so
  in its status reason: the guarantee is conditional on the label in the record, not on the router's classifier.

### 2.2 Tally

Attempts older than `max_observation_age_days` (judged per attempt against `--as-of`, default now and recorded) are
dropped first and counted as stale, so one new attempt cannot carry a cell of old ones. Then per (task type, arm,
item): the item's verdict, its graded runs, and what all its fresh attempts consumed. The partition is `selection` or `held_out`, from a hash of `(split_salt, item)`; the salt is
declared, so a re-derivation under changed conditions can draw a fresh split rather than re-spend the same held-out
set. Checking the same held-out items again after adding evidence is a second look at them, and the nominal
`1 - alpha` is then optimistic; a new salt is the way to avoid that, at the cost of re-splitting what was measured.

**The unit is the item, not the attempt.** Repeated runs of one item are correlated, and counting them separately
narrows every interval by the repetition factor. When any item has more than one graded run, the declaration must
say how runs combine into one item outcome (`repeat_rule`: `all`, `any`, `majority`, or a `module:attribute`
callable over the graded outcomes); without it the tally refuses rather than guess. `unobserved_as` decides only what
an item with no graded run counts as: a timed-out retry beside an accepted answer neither rejects the answer nor makes
the item look repeated.

### 2.3 Derive

Everything that decides what is certified is declared; nothing has a default, because a default here would be a
policy the operator did not choose:

| declaration | meaning |
|---|---|
| `floor` per task type | the acceptance rate an assignment must be shown to clear |
| `alpha` | one minus the confidence of each bound |
| `bound` | dotted path to `(accepted, n, alpha) -> (lower, upper)`; `tierbook.bounds:wilson` is provided |
| `holdout_fraction`, `split_salt` | the split |
| `unobserved_as` | `rejected` or `excluded`: whether an attempt with no gradable answer counts against the rate |
| `max_observation_age_days` | evidence older than this cannot be chosen (`null` is an explicit "no limit") |
| `held_out_correction` | `none` (each task type holds at `1 - alpha`) or `bonferroni_over_task_types` (the policy holds as a whole) |
| `fallback_arm` | optional; where traffic with no certified assignment goes |

Per task type:

1. **Cost.** Every attempt's tokens times the arm's current per-kind price, summed over all attempts including
   unobserved ones, divided by accepted items: spend per accepted task. A token kind the arm used with no price for
   it makes the arm `unpriced`, and an arm must be priced on both partitions to be eligible, because the shipped
   cost is the held-out one. A fixed-cost arm is priced only through a declared `usd_per_attempt` (derived elsewhere,
   e.g. hourly rate over a measured throughput), never invented here; declaring one for an arm that is not a
   fixed-cost candidate is refused.
2. **Selection** (selection partition only): among priced, fresh arms whose lower bound clears the floor, the minimum
   spend per accepted task; ties go to the higher lower bound.
3. **Check** (held-out partition only): the chosen arm's held-out bound. Status:
   * `certified` -- held-out lower bound clears the floor;
   * `unconfirmed` -- the floor lies inside the held-out interval;
   * `contradicted` -- held-out upper bound is below the floor;
   * `unassignable` -- no arm cleared the floor on selection, or the declaration is missing; the nearest miss is
     named.
   The shipped cost and rate are the held-out ones; the selection-side figures are kept in the record only.
4. **References.** The single best arm, chosen on the selection partition by pooled lower bound over the certifiable
   task types (with the task types it covers named), and what the policy costs relative to it on the **same** held-out
   items -- only items both arms were observed on count, and a task type with none is listed as omitted. "Send
   everything to one arm" is a legitimate answer.
5. **Fallback.** `fallback_arm` if declared, otherwise the single best arm. It is part of the policy, so that traffic
   with no certified assignment goes somewhere the policy chose and a reader can audit, rather than to whatever the
   router defaults to.

The objective is fixed at spend per accepted task. It is the definition this plane certifies, not a preference
among arms, and an objective that is not a ratio of spend to accepted work needs a different derivation, not a
parameter.

### 2.4 Export

`tierbook export-policy --target vsr` writes one vllm-sr decision per `certified` task type, through the exporter
verified against a live router in v0.4.0, with the policy's fallback as the router's default model. A task type
whose label has no entry in the caller's signal map is refused. `unconfirmed` entries need `--allow-unconfirmed`;
`contradicted` and `unassignable` are never exported. `--target table` writes the same assignment as plain JSON.

### 2.5 Drift

Given the deployed policy, fresh observations and the current candidates, separate reports:

* **re-derivation** -- the diff between the deployed policy and the policy derived from all evidence under today's
  prices: which task types changed arm or status, and why, with whether the declarations or the candidate file differ
  from the ones the deployed policy was derived under. A price change shows up here and nowhere else;
* **contradiction** -- per deployed certified assignment, the fresh-window bound for the assigned arm. Upper bound
  below the floor is `contradicted`; fewer graded items than the declared `min_items` is `undetermined`, which is
  reported as such and never as "no change". The guarantee is per window at `alpha`; an operator who runs it daily
  should expect `alpha` of unchanged arms to be flagged over time and size `alpha` for that.
* **needs measurement** -- every (task type, arm) in candidates × observed task types that was never observed or has
  only stale evidence. This is the work order for the part of the loop that routed traffic cannot do.

* **unattributed attempts** -- fresh attempts whose arm is not a candidate (a router that failed before naming the arm
  it chose records none). They count for no assignment, so they are reported beside the checks: a window of failures
  must not read as an `undetermined` window that was merely quiet.

`drift` exits 3 when a deployed assignment is contradicted and 2 when it refused its input, so a scheduler can tell
"the world moved" from "the run did not happen".

**The policy's labels and the router's labels.** A routed observation carries the arm the router reports it chose
(`x-vsr-selected-model`) and the item's own `task_type`; an item the router classified into another task type, or
into no decision, is observed on whatever arm it actually reached. The contradiction check for a task type therefore
reads exactly the traffic that reached its assigned arm with that label, and misclassification shows up as traffic on
the fallback, not as a change in the assigned arm's rate.

## 3. What stays, what goes

* **Stays as the research layer**, unchanged and still tested: the ledger/compile/validate/route path of v0.1-v0.4,
  `OutcomeTable` and its analyses, the `admit-*` claim checks. They are where the findings in `docs/results-*.md` came
  from. The new pipeline reuses `tierbook.bounds:wilson` (re-exported by `reproduce`), `config.load_config` and
  `export_vsr.export` rather than re-implementing them.
* **Removed**: `predict.py` and `describe.py` -- no importer, no test, no entry point and no reference outside
  their own docstrings; `predict`'s documented install extra does not exist; and the learned router `predict`
  implements is what three independent studies and this project's own measurement found not to beat a static
  per-type assignment. `upstreams.py` also has no caller, but it is the checker for the patch series in
  `infra/patches/`, which this release adds to; it stays and gets one.
* **Shared**: the Wilson interval moves to `tierbook/bounds.py`, which both layers import, so the research layer
  can change without moving the plane's bounds.
* **Not built**: a request-path selector, a learned router, a semantic success detector, an online bandit. Each is
  either a commodity (§1) or contradicted by a measurement here and by the literature. An online bandit is the natural
  next consumer of `observations.jsonl`, and the record is designed so one can read it, but no experiment here has yet
  needed one.

## 4. What would prove this design wrong

* A router on the request path that computes a held-out-checked, cost-per-accepted assignment from its own replay log
  -- if vllm-sr ships `success_constrained` with a selection-valid guarantee, this plane's derive step is redundant and
  should shrink to a data source for it.
* A deployment where the task-type label the router can see does not carry the assignment (the static per-type
  assignment is no better than single-best). The derivation then outputs single-best, which is correct but makes the
  plane a cost report rather than a router input.
* A drift report that fires on noise: if a fresh-window upper bound falls below the floor on an unchanged arm at the
  rate its confidence level predicts, the window is too small and the default must be revisited.
