# Phase 5: what the changed prompt did

Three arms of the same 24 items on the same candidate: two runs of the current prompt and one of the changed one.
**The contract's pass condition is not met**, because clause 1 requires zero and the changed arm has one. Clause 2 is
met more than it asked for. The full picture matters more than the verdict, so it is all here.

## Clause 1, mechanism: NOT MET

Re-audited after the classifier was corrected, so the three columns are comparable:

| | clean | out-of-workspace | own id written wrong | shell fs-arg | refused |
|---|---|---|---|---|---|
| baseline 1 | 15 | 4 | 1 | 4 | 6 |
| baseline 2 (replicate) | 12 | 7 | 4 | 5 | 10 |
| **changed prompt** | **18** | **1** | **1** | **3** | **3** |

The condition was "zero tool calls naming a path outside the run's own workspace, and zero permission rejections
attributable to a path". The changed arm has 1 and 2. What they are:

- `matplotlib__matplotlib-26208` asked for `glob path=/tmp/run-opencode-a933f30189` and was refused. Its own
  workspace was `/tmp/run-opencode-a932f30189`. **One character, same length.** That item wrote its own workspace id
  wrong in all three arms -- `8c042ffb40` as `8c042ffb4`, `9ef07f454b` as `9ef07f4b`, and now `a932f30189` as
  `a933f30189` -- with the absolute path stated in the prompt the third time.
- Three `bash` calls naming `/tmp/test_mrt.txt`, `/tmp/patch_writer.py` and `/tmp/test_skip_location.py`: agents
  writing scratch files. Outside the workspace, counted by the condition as written, and nothing to do with binding.

The condition was too broad. That is said here and **not fixed**, because relaxing a pass condition after seeing the
result is how a measurement stops meaning anything. What can be said without relaxing it is that the sub-condition
the change targets -- a path that is a near-miss of the run's own workspace -- went 1, 4, 1, and the two baselines
differ from each other by more than either differs from the changed arm. On that metric the change is **not
separable from run-to-run movement**.

## Clause 2, the motivating failure: MET, and by more than it asked

`pydata__xarray-4695` produced a **zero-byte diff in both baselines** -- 0 files touched, twice -- and under the
changed prompt produced 2,052 bytes across 2 files and scored `resolved: true`.

The clause asked only that it be attempted.

## Clause 3, regression: none observed

Solve counts 10, 9, **13**. No item that solved in *both* baselines failed under the changed prompt. The one item
that went the other way, `astropy__astropy-14369`, solved in baseline 1 and failed in baseline 2, so it is inside
baseline movement.

**The denominator is 23, not 24, in every arm.** `pylint-dev__pylint-4551` cannot be scored in this environment at
all: the scorer reports that this checkout does not contain the instance's `FAIL_TO_PASS` ids, so the item is recorded
`incorrect` no matter what the agent does. It was found by `harness/staging_check.py`, which exists to say whether an
arm can be read before its numbers are quoted, and it is constant across all three arms so it cannot flatter one. What
it does change is every rate: 10, 9 and 13 of **23** scoreable items.

The same item is also one of the two runs the import-resolution defect affected, so its agent was working around a
lying import path on a task that could not have been scored either way.

## The denominator changed the reading, and it took a reviewer to ask for it

A review pointed out that "zero near-misses" and "never wrote an absolute path" produce the same number, so the audit
now counts correct self-references too. With that beside the errors:

| | runs that named their own workspace | references | wrong | wrong per reference |
|---|---|---|---|---|
| baseline 1 | 19/24 | 377 | 1 | 0.27% |
| baseline 2 | 18/24 | 323 | 4 | 1.24% |
| **changed prompt** | **24/24** | **786** | 1 | **0.13%** |

That is a direct behavioural effect of the prompt and it was invisible in the bare counts. Stating the absolute path
made every run use absolute paths -- 24 of 24 against 19 and 18 -- and roughly doubled how often they did so. The
earlier reading in this document, that the change is "not separable from run-to-run movement", was drawn from the
error count alone; against a denominator that more than doubled, the same single error is the lowest rate of the three
arms rather than a tie with baseline 1.

Both readings are kept. The error count is 1, 4, 1 and does not separate the arms; the rate is 0.27%, 1.24%, 0.13% and
the usage is 19, 18, 24 of 24. What none of it supports is a claim about solving.

## The metric that reads most cleanly, and it was not in the contract

Runs producing **no edit at all** -- the failure the change was written from:

| | zero-edit runs | which |
|---|---|---|
| baseline 1 | 2 | xarray-4695, pytest-8399 |
| baseline 2 | 2 | xarray-4695, seaborn-3187 |
| changed prompt | **0** | -- |

Three distinct items produced zero edits at least once across the baselines, and **all three solved** under the
changed prompt. This is the strongest signal in the measurement and it is stated with its weakness: three items is
three items, and an item with a solve probability near 0.4 fails twice and then solves 14% of the time by itself.
Two of the three, `pytest-8399` and `seaborn-3187`, are already known to move between baselines. `xarray-4695` is
the one that failed the same distinctive way twice and then solved.

## What the paired instrument cannot see, which is worth more than either p-value

Both paired comparisons excluded `pydata__xarray-4695`, because `paired_arms.py` drops an item one arm never
attempted rather than scoring it as a failure -- correctly, since an unattempted item is not evidence about
capability. But the effect this change was designed to produce **is** an item going from unattempted to attempted, so
the discordance table is structurally blind to it.

    changed vs baseline 2:  22 compared, 11 vs 9, discordant 2-0, p = 0.5000, excluded: xarray-4695, seaborn-3187
    changed vs baseline 1:  22 compared, 11 vs 10, discordant 2-1, excluded: xarray-4695, pytest-8399

Reporting only those two lines would hide the result. The zero-edit table above is where the effect lives, and it is
a count of exclusions rather than a count of solves.

## The conclusion, and the change it argues for

The prompt change is worth keeping: 18 clean runs against 15 and 12, 3 refusals against 6 and 10, zero zero-edit runs
against two and two, and the item it was written for solved. None of that is a solve-rate claim at this sample size.

It does **not** fix what it was aimed at. `matplotlib-26208` mistranscribed its own ten-character workspace id with
that id written in its prompt. Stating a random string does not make a model reproduce it. The fix recorded as out of
scope -- naming the workspace after the item, so there is nothing to transcribe -- is what this arm argues for, and it
now has an observation behind it rather than an inference.

## One uncontrolled variable, recorded in the contract before this arm ran

The pod's `import astropy` pointer moved during this arm, from a leftover of baseline 1 to this arm's own item 2. For
the eleven items whose staged trees are built for a Python the pod does not run, a run's compiled extensions come
from whichever earlier run last performed an editable install. That is present in all three arms and is uncontrolled
in all three. `docs/changes/import-resolution/` holds the measurement and the fix.
