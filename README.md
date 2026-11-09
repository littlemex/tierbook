# tierbook

**Certified model assignments for the router you already run.** tierbook reads the graded outcomes of your own traffic
and tells your router which model each task type should go to: the cheapest per accepted task that clears the quality
floor you declare, checked on items the choice was not made on, priced at today's rates — and it re-decides when prices,
models or outcomes move.

![tierbook sits beside the request path](docs/images/architecture.png)

**You bring** a log of calls (task type, model, tokens), a grade per attempt from your own grader, a price per model,
and a minimum acceptance rate — a *floor* — per task type. **You get** `policy.json`: per task type, which model (an
*arm*) to use, whether that choice is *certified* (its confidence bound on items it was not chosen on clears your floor),
what it costs per accepted task, and a configuration for your router.

Routers such as [vLLM Semantic Router](https://github.com/vllm-project/semantic-router) and LiteLLM pick a model per
request. tierbook does a different job: it derives the per-task-type choice from your graded outcomes, attaches a
held-out confidence bound to it, and writes it into their configuration. It never sits in the request path. The survey
of what routers do today is in [`docs/prior-art-2026-11.md`](docs/prior-art-2026-11.md).

## Why

| | measured, in this repository |
|---|---|
| A policy that splits task types across models costs less than the best single model on the same items | **0.84 ×** the single-best cost per accepted task (five arms, 489 common held-out items); when only one arm was worth using, the policy said so (**1.00 ×**) ([record](docs/verify/v0.5.0-certification-loop.md)) |
| A price change re-derives the policy with nothing re-measured | a probe that tripled one arm's rate moved three of four task types and brought the policy to **0.79 ×** the single-best cost (508 items); the live router followed |
| A small CPU model taught by a decision model can take over routine traffic — at a floor you allow | a LightGBM student (sentence-embedding features) certified at a declared floor of 0.75 at **$0.00000069** per accepted task, with the teacher's labelling cost amortised over a declared 1,000,000 requests: about **1/68** of [Prismyra](https://github.com/littlemex/Prismyra), the decision model that certifies at 0.85. At 0.80 and 0.85 the student was not certified ([record](docs/verify/v0.5.0-distillation-loop.md)) |
| A choice reported on the data it was made on looks better than it is | 6.7 points between the point estimate and the guaranteed bound on this project's own search ([results](docs/results-selection-cost.md)); every assignment here is checked on a held-out half |

## How it works

![the loop](docs/images/ops-loop.png)

Four verbs, each a pure function from files to a file. The loop is their composition; run it as often as anything moves.

| verb | reads | writes |
|---|---|---|
| `tierbook ingest` | a call log and your grades | `observations.jsonl`, one line per attempt: tokens, latency, outcome |
| `tierbook derive` | observations, `candidates.json` (arms, prices), `declarations.json` (floors, alpha, split) | `policy.json`: per task type an arm, a status and why |
| `tierbook export-policy` | a policy | a vLLM Semantic Router config, a Prismyra learn spec, or a plain table |
| `tierbook drift` | the deployed policy, fresh observations, today's prices | what a re-derivation changes, which assignments fresh traffic contradicts, what needs measuring |

tierbook never grades. Acceptance is yours — a test suite, an answer key, a human label. How an attempt with no gradable
answer counts is declared too (`unobserved_as`); the examples count it as rejected rather than dropping it. The three
input files and one example line of each are in the design document,
[§2](docs/DESIGN-v0.5-certification-plane.md#2-the-pipeline).

## Quickstart

Offline, on measurements this repository ships: the three arms of the recorded run that policy v1 chose between
(MMLU-Pro biology, history, math, law; 1,000 items; arm names are the gateway's model aliases).

```bash
git clone https://github.com/littlemex/tierbook.git
cd tierbook
python3 -m venv .venv && .venv/bin/pip install -q .
S=examples/certification_loop/sample
.venv/bin/tierbook derive --observations $S/observations.jsonl --candidates $S/candidates.json --declarations $S/declarations.json --out policy.json
```

Each line is a task type, its status, the arm, the held-out cost per accepted task, and the reason (cut short here):

```
biology    certified  claude-sonnet-5   $0.001342/accepted  cheapest per accepted task among 1 that cleared selection; ...
history    certified  qwen3-next-80b    $0.000069/accepted  cheapest per accepted task among 2 that cleared selection; ...
law        certified  claude-sonnet-5   $0.001916/accepted  cheapest per accepted task among 1 that cleared selection; ...
math       certified  claude-sonnet-5   $0.001875/accepted  cheapest per accepted task among 1 that cleared selection; ...
policy $0.001371/accepted vs single best claude-sonnet-5 $0.001628/accepted on 489 common held-out items of 4 certified task type(s)
```

The assignment as plain data, for any router:

```bash
.venv/bin/tierbook export-policy --policy policy.json --target table --out table.json
```

Now suppose one vendor raises its price fiftyfold (a probe in a shipped candidate file, not a quoted price). Nothing is
re-measured, and with no `--fresh` traffic only the re-derivation is reported:

```bash
.venv/bin/tierbook drift --observations $S/observations.jsonl --deployed policy.json --candidates $S/candidates-qwen-x50.json --declarations $S/declarations.json --out drift.json
```

```
inputs   declarations changed: False, candidates changed: True
changed  history: {'status': 'certified', 'arm': 'qwen3-next-80b'} -> certified claude-sonnet-5
```

Hand the policy to a router with `export-policy --target vsr` (vLLM Semantic Router) or `--target prismyra-learn`
(Prismyra's own router). The full loop against live endpoints is in
[`examples/certification_loop/`](examples/certification_loop/README.md).

## What a certificate means

![how one task type gets an assignment](docs/images/certificate.png)

| status | meaning | exported? |
|---|---|---|
| `certified` | the held-out lower bound clears the floor | yes |
| `unconfirmed` | the floor lies inside the held-out interval | only with `--allow-unconfirmed` |
| `contradicted` | the held-out upper bound is below the floor | never |
| `unassignable` | nothing cleared the floor on selection, or a declaration is missing | never; the policy's fallback answers |

Everything that decides what is certified is declared by you, with no defaults: the floor per task type, alpha, the
bound method (`tierbook.bounds:wilson` ships; any `module:attribute` works), the split, how unobserved attempts count,
how long evidence stays fresh, and whether the guarantee holds per task type or for the policy as a whole. The
guarantee is printed in words in every policy, including what it is conditional on.

A certificate covers the task type as your labels define it. Once a router classifies requests, it says nothing about
the ones the classifier puts elsewhere — in the recorded run, 18-21 % of routed requests did not reach their own task
type's decision. Looking at the same held-out half again after adding evidence makes the nominal confidence optimistic;
declare a fresh `split_salt` to avoid it (the recorded runs did not, and say so).

## Where it plugs in

![what tierbook reads and writes](docs/images/interfaces.png)

| neighbour | tierbook reads | tierbook writes |
|---|---|---|
| a gateway ([stratoclave](https://github.com/littlemex/stratoclave), at or after the commit `infra/tierbook-up` pins) | `GET /api/mvp/me/rates` for prices (the gateway's own endpoint name); usage-history `cost_microusd` to reconcile against the bill | — |
| vLLM Semantic Router | `x-vsr-selected-model` on routed responses | a config that its own `vllm-sr config validate` accepts (0.4.0 and the 0.5.0 development builds) |
| Prismyra | `/v1/decide` answers and its experience log | the `router` block of a tag in its learn spec |
| your side | grades, floors, arms and prices | — |

Anything that speaks an OpenAI-compatible API can be an arm: a vendor API, a gateway in front of several, a model
server on your own GPUs, or a decision model and its CPU student. An arm without a token price (a self-hosted or
fixed-cost one) is priced from a declared cost per attempt with its source, typically an hourly price over a measured
throughput.

## Teach on a GPU, serve on a CPU

![the distillation lane](docs/images/distillation.png)

For a routine closed-label task — sentiment, intent, a yes/no check — the cheapest arm that clears the floor can be a
small model trained on the traffic itself. [Prismyra](https://github.com/littlemex/Prismyra) answers in the background
and logs what it answered; its learn pipeline refits a LightGBM student on that log every window, with text embeddings
registered as features; tierbook certifies, per window, whether the student, the student routed by confidence, or
Prismyra itself is the cheapest at your floor, and exports the decision as the router block of Prismyra's learn spec.
Serving through Prismyra's router, with its confidence-mode admission, is still being verified. The run behind the
numbers is in [`docs/verify/v0.5.0-distillation-loop.md`](docs/verify/v0.5.0-distillation-loop.md) and the pieces in
[`examples/distillation_loop/`](examples/distillation_loop/README.md).

## A live run

![three deployments](docs/images/live-run.png)

Five, then seven arms behind a billing gateway, routed by vLLM Semantic Router 0.4.0 across three deployments. The
first exposed a gateway defect: Claude responses carried non-canonical usage keys, which the router rejects. The second,
with the unreachable Claude arms left out of the candidate file, assigned every task type to one arm. The third followed
a price probe. Each move came with a reason in the drift report. Claude arms were later routed end to end on a fixed
gateway with a vllm-sr 0.5.0 development build ([record](docs/verify/v0.5.0-certification-loop.md)).

## Install

Python 3.10 or newer, from source (there is no PyPI release):

```bash
pip install .
pip install '.[dev]'
```

The second line adds what the test suite needs. The router, Prismyra and the gateway are separate projects; tierbook
needs none of them installed to derive a policy.

## Command reference

| command | what it does |
|---|---|
| `ingest --calls C --outcomes O --out obs.jsonl [--cache-additive-arm ARM]` | join a chat-completions log to grades; `--append` to add to an existing file |
| `derive --observations ... --candidates C --declarations D --out policy.json [--as-of T]` | certify per task type |
| `drift --observations ... --deployed P --fresh F ... --out drift.json` | diff, contradiction checks, cells to measure; exit 3 on a contradiction |
| `export-policy --policy P --target vsr\|prismyra-learn\|table --out ...` | translate a policy for a router; refuses what the target cannot express |
| `validate`, `explain`, `compile`, `route`, `export-vsr`, `assign`, `accept`, `admit-*` | the ledger workflow, still supported: [`docs/ledger-path.md`](docs/ledger-path.md) |

Exit codes: `0` done, `2` refused (bad input, a missing declaration, an export the target cannot express), `3` a
deployed assignment was contradicted by fresh evidence.

## Design

* **A mechanism, not a policy.** No list of good models, signals or task types lives in the code, and no threshold comes
  from one corpus; a study that reached the opposite conclusion must be able to express it through the same files
  ([`SCOPE.md`](SCOPE.md)).
* **Price is separate from measurement.** Observations carry tokens; cost is recomputed from today's candidate file.
* **The unit is the item.** Repeated runs of one item combine by a declared rule rather than counting as independent
  evidence.
* **Refusals come from the record.** A missing floor, an unpriced arm, stale evidence or an unservable export is a
  named refusal, never a silent default.

The full design and why it is shaped this way: [`docs/DESIGN-v0.5-certification-plane.md`](docs/DESIGN-v0.5-certification-plane.md),
from the survey in [`docs/prior-art-2026-11.md`](docs/prior-art-2026-11.md).

## Repository layout

| path | what |
|---|---|
| `src/tierbook/` | the package; `certify.py`, `observation.py`, `bounds.py` and `certify_cli.py` are the certification plane |
| `examples/certification_loop/` | measure → grade → derive → route → drift against live endpoints, plus the offline sample |
| `examples/distillation_loop/` | Prismyra as teacher, its LightGBM student, tierbook's certificate |
| `docs/verify/` | the real-machine records behind every number on this page |
| `docs/diagrams/`, `docs/images/` | the figures' draw.io sources and their rendered PNGs (`python docs/diagrams/gen.py` regenerates both) |
| `infra/` | bringing a gateway (and optionally a cluster) up from scratch for verification |

## Status

v0.5.0. The certification loop runs end to end on billed traffic through vLLM Semantic Router. The distillation lane is
shown up to the certificate: Prismyra labels, its LightGBM student is refitted per window, tierbook certifies per window;
serving through Prismyra's router is still being verified.

Known limits: vLLM Semantic Router 0.4.0 rejects Claude responses that carry reasoning (`unknown field
"reasoning_details"`), so routing those needs its `main` or a 0.5.0 build. Not yet shown: more than one router replica,
and a self-hosted arm priced from a measured throughput inside tierbook rather than declared.

## License

Apache-2.0 ([`LICENSE`](LICENSE)).
