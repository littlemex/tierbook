# Contributing

## The one rule that decides whether a change belongs here at all

**tierbook is a META mechanism. Logic is INJECTED into it and is never built into it.**

Before anything else, ask of a proposed addition: **could a different study, on a different corpus, reaching the
opposite conclusion, express its own answer through this?** If the mechanism has already decided, the change is wrong
— however well the decision is supported by the measurements in this repository.

### What that forbids, concretely

| forbidden | allowed |
|---|---|
| a closed vocabulary naming **which** signals are worth using | a closed vocabulary naming **what a thing is** |
| a threshold carried in code because one corpus produced it | a threshold the caller supplies, and a refusal when they supply none |
| a refusal derived from a **finding** | a refusal derived from **the record in front of it** |
| a predicate that answers "is this signal good" | a predicate that answers "does this record show what is being claimed" |

A closed vocabulary is right when a value outside it is **meaningless**. It is wrong when a value outside it is merely
**unpromising in the data we happen to have**.

### The violation to learn from

`evidence.py` carried `ESCALATION_SUBJECTS = ("own_competence", "item_difficulty")`, and `quantity.py` had a predicate
returning `subject in ESCALATION_SUBJECTS`. Both were supported by a real measurement here — a topic signal reads at
five times chance and says nothing about competence on this corpus.

They were still wrong. A study measuring topic to predict competence **had no way to say so**, because the mechanism
had already refused the category. The replacement reads the evidence the record carries and asks the **caller** which
target it cares about.

Every violation so far has looked like good engineering. That is the point: the test is not whether the rule is true,
it is whether the mechanism is the place for it.

## What the experiments are for

`docs/EXPERIMENT-FEEDBACK.md` is a long list of measurements. **They are input to the question "what must a general
mechanism be able to hold", never an answer shipped as code.** A finding becomes one of exactly three things:

1. a **recordable field** — something a caller can now state;
2. a **shape a claim must have** — a refusal when a caller states less than the claim needs;
3. a **structural refusal** — something that cannot be true regardless of corpus, such as a first turn reading from a
   cache that did not exist yet.

If a finding became a fourth thing — a rule that decided for the caller — it was applied wrongly and should be
reverted.

## Working practice

- **Every invariant is tested by breaking it.** Add a rule, revert it locally, confirm a test fails. A test that
  passes against a deliberately broken implementation is not evidence.
- **A test has to sit where the two candidate behaviours differ.** Two separate cases in this repository passed while
  the invariant they were written for was inverted, because both sat on the same side of the boundary.
- **Measure a number immediately before writing it down.** A count taken before the last edit has shipped wrong twice.
- **`main` is closed.** Epic branch off `main`, feat branches into the epic, epic merged at the end.

## Scope

`SCOPE.md` is the governing document and opens with the standing order. Read it first; everything else here is
subordinate to it.
