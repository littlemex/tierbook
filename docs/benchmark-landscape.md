# What can actually be measured, by task family

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

## What to run next, in order

1. **NTCIR-18 U4** -- the only Japanese, real-document, executable benchmark with an official three-way split.
   This is the gap in the current ledger.
2. **WMT24++ en→ja** with chrF -- a second family that can assign, deterministic, Apache-2.0.
3. **IFEval** -- cheap, fully executable, and per-item results for named models are already published in a form
   built for reuse.
4. **tau2-bench** -- extends the one non-nested family already measured here.
5. CUAD or ContractNLI -- a document-review family, for relative ranking only, with the contamination stated.

Summarisation and long-form writing enter the ledger as **diagnostic families**: measurable, reportable, and
structurally unable to assign a routing decision. That is a constraint to build around rather than argue with.
