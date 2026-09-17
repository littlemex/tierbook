# What can actually be measured, by task family

> **Scope, before anything else: [`SCOPE.md`](../SCOPE.md).** This is a routing mechanism that collects its
> own data and decides while its environment moves. The decision is a **function from observed state to an
> assignment** — volume, prices, availability, capacity, request shape, floors and SLOs are all inputs, and
> every threshold in it is **derived, never configured**. *"At this concurrency the next request belongs on
> the API"* is **one example of the output shape, not the mechanism.* It is **not** a tuning guide for one
> cluster, not a standing verdict about which tier wins, and not a benchmark: numbers about a particular
> GPU, engine flag or agent are **parameter readings**, not results.

Surveyed 2026-08-30. The question was not "which benchmarks exist" but "for which task families can I get **per-item
pass or fail for several models, offline, without a model judging another model's output**". That is the only
kind of evidence this project lets assign a routing decision, because a model's judgement of another model's
output was measured here at keep-precision 0.78 against a bar of 1.00, with every error in the dangerous
direction.

The answer is that the families split cleanly in two, and **the split is a property of the benchmark landscape
rather than of this project's fussiness**. Half of what an LLM is used for has no non-model scorer at all.

## Families that can assign

| family | best option | scorer | Japanese | the catch |
|---|---|---|---|---|
| knowledge MCQ | MMLU-Pro | `executable`, exact match | via translation only | already measured here: 699 test / 488 calib, disjoint |
| translation | **WMT24++** (Apache-2.0, 998 per pair) | `deterministic_metric`, chrF/BLEU | **`en-ja_JP` yes** | **ja→en was dropped in WMT24**; only en→ja is current |
| OCR / document parsing | **OmniDocBench v1.5** | `executable`, edit distance + TEDS + CDM | **no** | research use only, no commercial |
| OCR, Japanese | **NTCIR-18 U4** (`stockmark/u4-table-cell-qa`) | `executable`, exact match | **yes, real EDINET filings** | best Japanese option found: official 10,300 / 1,441 / 2,898 split, CC BY-4.0 |
| agentic tool use | SWE-bench Verified, tau-bench | `executable`, tests / database state | n/a | SWE-bench is code *fix*, not review |
| **agent construction** | **Hyper-tau-bench** (`sierra-research/hyper-tau-bench`, MIT, 53 tasks) | `executable`, exact match on final database state and on what was told to the customer | no | **its official metric subtracts a budget penalty from the pass rate**, so the headline number cannot be used here at all -- see the note below |
| document review (contracts) | CUAD, ContractNLI, MAUD, LegalBench (148 of 162 tasks) | `executable`, F1 / accuracy / AUPR | no | **contamination binds harder than the scorer**: all 2021-era SEC EDGAR |
| constrained writing | **IFEval** | `executable`, Python constraint checkers | no | measures constraint compliance, **not writing quality** |

## Families that cannot assign, and why

| family | why not | what remains |
|---|---|---|
| **summarisation (meaning)** | ROUGE is deterministic and measures surface overlap. Every faithfulness benchmark -- SummEval, SEAHORSE, FRANK, RealSumm, TofuEval -- ships `human_label` as its body, usable for correlating *existing* outputs and useless for scoring a new candidate summary. All English. | Japanese: XL-Sum ja via llm-jp-eval with RougeJa, 8,891 items with a split, **non-commercial**, 2021. Surface overlap only. |
| **document writing / long-form quality** | Of roughly ten benchmarks surveyed, **exactly one is fully executable** (IFEval), and it scores constraint compliance. The pattern is sharp: the moment a benchmark steps from countable or structural constraints to "is this good writing", it switches to an LLM judge. No exception found. | Japanese has no deterministic long-form option at all. ELYZA-tasks-100 is `human_label`; Nejumi and Shaberi are `model_judged`. |
| **code review quality** | No non-model option exists. CRScore depends on embedding models; CRScore++ regresses to RLAIF. CodeReviewer scores BLEU against a single reference, which penalises valid alternative phrasings. | Reference-similarity only, and it ranks worse than the executable families. |
| **live web research** | Almost all model-judged by default: BrowseComp, Deep Research Bench, WebVoyager, Online-Mind2Web, Mind2Web 2. | BrowseComp-Plus's *retrieval* side (Recall@k, nDCG) is `reference_metric` and offline. The judgement side is not. |
| **open-ended document review** | "Read this contract and flag the risks" has no deterministic gold. Better Call GPT is the type case: a senior lawyer re-grades every run. | `human_label` per run, or a model judge. |

## Is research a distinct family, or a subtype of agentic tool use?

The owner asked. **A subtype**, and the reason is how the benchmarks are built rather than how they are
described.

Their scoring falls into the same three classes as tool-use benchmarks, and GAIA and AssistantBench score only
the final answer -- the tool calls that produced it are not evaluated, which makes them a subset of a tool-use
benchmark rather than a different thing. BrowseComp-style suites claim "persistence of information gathering"
as a distinct axis and then implement it as repeated search calls scored with a QA grader template borrowed
from elsewhere. And the 2025-2026 generation settles it explicitly: GAIA2 places Search alongside Execution,
Ambiguity, Adaptability and Time as **one capability within a general agentic environment**, so the benchmark
designers treat research as a capability inside tool use.

So calibration should put research tasks on the same axis as long-horizon tool use, as the subset whose tools
are search and a browser. With one caveat that needs separate handling: research benchmarks are far more
model-judged than the rest of tool use, so their scoring reliability has to be tracked apart from their family.

## Three constraints that outrank the scorer

**Contamination binds harder than scoring for the legal and document-review family.** CUAD, ContractNLI, MAUD
and most of LegalBench are executable with official splits and CC BY-4.0 -- and all of them are 2021-era SEC
EDGAR or public web documents. Use them for relative ranking between tiers, not for absolute claims.

**A deterministic scorer existing is not the same as the published numbers using it.** JDocQA has one, and its
official leaderboard runs GPT-4.1 as a judge. GAIA's dev166 is contaminated and only the private test300 is
usable, through leaderboard submission. `llm-jp/jawildtext` (2026) is executable and ships **only a `train`
split with no held-out test** -- verified directly -- so it contaminates by design.

**Permission to evaluate is not permission to train, and the licence identifier does not say which.**
`OmniDocBench-JASyn` is CC BY-4.0 and its own card states that using it for model training or distillation is
prohibited, because it was generated with `claude-sonnet-4-6`. This project has used it for calibration, which
is fine, and a router predictor fitted on it would not be. `fit_bucket_policy` now refuses without an explicit
`may_train_on`, and treats `None` as not permitted: a licence question answered by omission is answered
wrongly, and the omission is silent whereas the refusal is not.

## A note on metrics that are models

The survey produced a distinction this project's schema was missing. chrF and BLEU have no learned parameters.
COMET, BLEURT and MetricX have frozen ones -- **reproducible bit for bit, and still models that can be
systematically wrong**. Those two properties are usually conflated, and this project has the reason not to
conflate them: a calibrated synthetic proxy reversed sign against the official metric here, so reproducible is
not correct.

`oracle.kind` now separates `deterministic_metric` from `fixed_weight_model_metric`. The latter may assign --
refusing COMET outright would leave translation with surface overlap only -- but the record carries the fact.
One licence trap while we are here: **COMET-Kiwi is CC-BY-NC-SA and cannot be used commercially.**

## Hyper-tau-bench: admissible, and not through its own metric

Added on the strength of its scorer, which is the class this ledger can use: **one point per conversation if the final
database state and the content conveyed to the customer match the specification exactly**, zero otherwise. Deterministic,
no judge model, 53 tasks over four domains, MIT licence -- confirmed from the repository's own `LICENSE`, because the
write-up that prompted this does not state one.

**What it measures is a different unit from everything above it in the table, and the mapping has to be stated or it
will be assumed wrong.** Every other row scores a *candidate answering an item*. Here the unit is a **developer building
an agent**: a task hands over an evidence corpus (377 files for airline, about 1,700 for banking), a simulated client, a
REST API that may be defective, and a token budget; the thing scored is the agent that gets built. It maps onto this
ledger only as **candidate = the developer model, item = the task**, and it is a real mapping -- binary outcome per
(model, task) is exactly the outcome table's shape. What it is not is a routing benchmark for serving a request.

**Its official metric is unusable here, and that is the sharpest catch.** The reported score is

    S = max(0, pass_rate - p),   p = max(0, mean_credits / budget - 1)

which **subtracts a cost term from an accuracy term inside one number**. This project's cost apparatus exists to keep
those apart: the exchange rate between accuracy and spend is the buyer's declaration, not the benchmark's, and a figure
with the trade already applied cannot be re-decided by anybody downstream. Usable only by taking the **raw pass/fail per
task and the credits separately** -- both are reported in the paper's discussion -- and discarding `S`.

**No official split is documented**, which binds harder than it looks: a threshold chosen on these 53 tasks and then
scored on them is the state that cannot support a verdict, so a split has to be declared before the first run and it will
be this project's split rather than the benchmark's.

**The task counts limit what can be concluded, computed rather than asserted.** Using this project's own interval and
sign-test arithmetic:

| population | n | a 50% pass rate reads | smallest attainable two-sided p |
|---|---|---|---|
| all tasks | 53 | [0.361, 0.621] | 2.2e-16 |
| banking | 35 | [0.330, 0.644] | 5.8e-11 |
| airline, retail, telecom | 6 each | [0.188, 0.812] | **0.031** |

So a **pooled** comparison has room to say something, a banking-only one does too, and a **per-domain** claim on the
other three has an interval 0.625 wide -- wider than the gap between any two models anybody would compare. And 35 of the
53 tasks are banking, so an unstratified pooled figure is largely a banking figure.

**Cost makes repeats the binding constraint.** The write-up measures 34-46 minutes per task and estimates roughly **15
hours and $370** for one full pass at three-way parallelism. This ledger already records that repeats are what bound a
gate's cost and that a single run leaves it unmeasurable; at this price a repeat is a decision rather than a formality.

## What to run next, in order

1. **NTCIR-18 U4** -- the only Japanese, real-document, executable benchmark with an official three-way split.
   This is the gap in the current ledger.
2. **WMT24++ en→ja** with chrF -- a second family that can assign, deterministic, Apache-2.0.
3. **IFEval** -- cheap, fully executable, and per-item results for named models are already published in a form
   built for reuse.
4. **tau2-bench** -- extends the one non-nested family already measured here.
5. **Hyper-tau-bench**, on the raw pass/fail only, and only after a split is declared. Priced last on purpose: $370 and 15 hours a pass makes it the one entry here where a second run has to be argued for.
6. CUAD or ContractNLI -- a document-review family, for relative ranking only, with the contamination stated.

Summarisation and long-form writing enter the ledger as **diagnostic families**: measurable, reportable, and
structurally unable to assign a routing decision. That is a constraint to build around rather than argue with.
