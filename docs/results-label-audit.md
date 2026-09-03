# Unanimous disagreement with the answer key is a free, exact detector of a broken answer key

**Measured 2026-09-01**, prompted by a review note on the finding that a small set of items nobody solves
carries about half the bill. The note said: audit those items by hand before designing anything to detect them,
because a broken answer key and an unanswerable question look identical in a correctness matrix. That was right,
and the audit changed the shape of the problem.

Nothing here cost anything. It is a re-reading of the matrix already measured.

## The measurement

Over the 1,187 items with a complete row across nine candidates, 51 are solved by nobody. Counting how many
candidates gave the *same* answer on those:

| candidates agreeing on one answer | items | inspected by hand | confirmed broken key |
|---|---|---|---|
| **all nine** | **19** | 19 | **19** |
| exactly eight | 9 | 9 | 3, plus one question with two correct answers |

**Unanimity is exact and near-unanimity is not.** All nineteen items where every candidate agreed were cases
where the agreed answer is right and the dataset's recorded answer is wrong. Relaxing the condition by one
candidate drops the hit rate from 19 of 19 to 3 of 9, because a single dissenter no longer distinguishes "the
key is wrong" from "the question is hard".

Over the whole corpus the condition fires on exactly those 19 items: 471 items have unanimous agreement, 452 of
them are graded correct, and the 19 graded incorrect are the 19 above. **No false positives at all.**

Examples, with the dataset's own answer in brackets: the largest asymptotically is `O(2^n)` [`O(n^2)`]; the
option that is *not* a classic security property is correctness [availability]; with prices rising and output
constant, nominal GDP rises and real GDP is unchanged [nominal rises, real falls]; critics of 1980s speech codes
invoked freedom of speech [freedom of the press]; `samyak jnana` is right knowledge [right intuition]. Halving a
conductor's diameter and doubling its length gives 8R [4R].

## It is the labels, not our rendering

Checked before concluding anything, because a letter mis-mapped during prompt rendering would produce the same
symptom and would be our bug rather than the corpus's:

- The options in the rendered prompt are in the same order as the dataset's `options` array for all 19 items.
- The dataset's `answer` letter and its `answer_index` agree on all 12,032 rows, so there is no ambiguity about
  which option the label names.
- The harness passes both straight through — the loader takes `options` and `answer` from the row with no
  shuffling.

So the text the label points at really is a wrong answer. This is documented label noise in this corpus, not a
defect in the measurement.

## What it does to the numbers

**Accuracy, corrected for the 19 unanimous items only** — a uniform +1.6 points for every candidate, because by
construction every candidate got all nineteen "wrong":

| candidate | measured | corrected |
|---|---|---|
| `claude-opus-5` | 89.6% | 91.2% |
| `claude-fable-5` | 89.3% | 90.9% |
| `grok-4.6` | 87.3% | 88.9% |
| `gpt-5.6-sol` | 85.6% | 87.2% |
| `claude-sonnet-5` | 83.7% | 85.3% |
| `gpt-5.6-terra` | 82.4% | 84.0% |
| `qwen3-next-80b` | 64.8% | 66.4% |
| `qwen3.8-27b` | 64.4% | 66.0% |
| `nemotron-super-3-120b` | 54.8% | 56.4% |

The ordering is unchanged and no gap between candidates moves, which is why the routing conclusions drawn from
this matrix stand. What moves is the **ceiling**: the pool's best member is at 91%, not 90%, and the headroom a
tuning programme is aiming at is correspondingly smaller than it looked.

**The bill.** Running the pool cheapest-first and stopping at the first correct answer costs $4.9809 over the
1,187 items, at the gateway's own registry rates.

| | items | share of the bill |
|---|---|---|
| nobody solves it | 51 | **54.8%** |
| — of which a confirmed broken key | 22 | **7.0%** |
| — genuinely unanswerable by this pool | 29 | **47.8%** |

**So the audit reduces the big number without removing it.** Half the bill really is spent on items the pool
cannot answer, and only a seventh of that half is the corpus's fault. The label errors are cheap items — short
questions that every candidate answers in four tokens — while the genuinely unanswerable ones are long
questions where the dear tiers spend output tokens. That asymmetry is why 22 of 51 items are only 7.0 of 54.8
points.

**A note on an earlier figure.** A previous page reported 57 items at 50.4% of the bill. That count is over the
eight API tiers with the self-hosted box excluded; 51 is the same quantity with the box included. Both are
correct and they answer different questions. The 4.8% / 4.3% / 4.0% series for eight, nine and ten candidates is
the expected shape.

**Duplicates, found on the way.** Ten groups of items share an identical question text, ten items redundant. One
group — `1692` and `1693`, an eminent-domain question — is unsolved in every copy, so one bad key is being
counted twice. A third near-copy, `995`, differs by one clause and is keyed the same way, and all three are in
the 19.

## Why this belongs in the mechanism rather than in a footnote

**The detector is free, exact here, and general.** "Every candidate agreed and the verifier says they are all
wrong" needs no probe, no model and no extra call — only the matrix the mechanism already measures. And the
reasoning does not depend on this corpus: in a tenant's own traffic, unanimous agreement against a verifier's
rejection is evidence about the *verifier*, not about the candidates. A routing mechanism that measures a
candidate matrix therefore emits a **data-quality report** as a byproduct, and that is worth having on its own.

It does not cross the line this project keeps about never treating a prediction as evidence of correctness. The
output is not "this answer is right"; it is "these items are worth a human's attention", and a human decided all
19.

**And it changes what to build for the expensive tail.** The tail is not one phenomenon. It is broken labels,
which an audit removes; duplicates, which deduplication removes; questions with two correct answers, which need
the key widened; and genuinely unanswerable items, which need an abstention rule. Only the last of those is a
routing problem, and it is 29 items rather than 51.

## What is deliberately not claimed

**The true label-error rate is higher than 1.6% and unmeasured.** This detector only fires where every candidate
agrees, so it cannot see a mislabelled item that the pool disagrees about. The published audits of this corpus
family report error rates several times this figure, so 1.6% is a floor on the corpus's noise and the corrected
accuracies above are still under-estimates.

**The nine items at eight-of-nine agreement were judged by one reader.** Three are unambiguous; the five left
undecided are contested law and medicine questions where the dataset's answer is defensible. They are recorded as
undecided rather than resolved.

**No item was removed from any fold.** Every number in the other documents stands as measured. Correcting them
would require a decision about the unmeasured remainder of the label noise, and that decision has not been made.
