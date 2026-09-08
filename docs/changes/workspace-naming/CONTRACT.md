# CONTRACT: a workspace name a model does not have to memorise

## Out of scope, written first

| Not changing | Why |
|---|---|
| The task prompt | It already states the absolute workspace. This change makes that string easy to reproduce; it does not change what is said about it. The prompt arm is measured and recorded. |
| The permission system | It behaved correctly in all three recorded arms, including every time it refused a mistranscribed path. |
| The model, the endpoint, the decode policy, the agent definition, the tools | The candidate tuple must not move. |
| The item set, the oracle, the scorer | A change to what counts as solved would make the arms incomparable. |
| The interpreter a run verifies with | The larger defect, recorded in `docs/changes/import-resolution/01-design/interpreter-mismatch.md`. Untouched here. |

## The premise, and it is an observation rather than an inference

`matplotlib__matplotlib-26208` wrote its own workspace id wrong in **all three recorded arms**:

    baseline 1   own 8c042ffb40   wrote 8c042ffb4    (dropped a character)   refused
    baseline 2   own 9ef07f454b   wrote 9ef07f4b     (dropped two)           refused, seven calls
    changed      own a932f30189   wrote a933f30189   (substituted one)       refused

The third of those had the absolute path written in its prompt. Six runs across the three arms did the same thing on
five distinct items. Every one was refused, and none of the affected runs solved except one whose mistranscription
happened to be in a shell string the permission system does not inspect.

Stating a ten-character random string does not make a model reproduce it. That is the finding phase 5 of the
workspace-binding change produced, and this change is what it argues for.

## What changes

**W1.** A run's workspace is named after its item: `/tmp/w/<instance-id>`. Every character is derivable from the task
the agent was given, so there is nothing to memorise.

**It is not shorter**, and an earlier draft of this clause said it was. Measured: `/tmp/w/psf__requests-1142` is 25
characters against the old scheme's 28, but `/tmp/w/matplotlib__matplotlib-26208` is 35 and
`/tmp/w/scikit-learn__scikit-learn-15100` is 39. So the claim is only about entropy, not length -- and length is
exactly what a competing explanation would point at, which is why the false version had to go rather than be
softened.

**W2.** The workspace is made **fresh**: removed if present, then created, before anything is staged into it. Without
this, a deterministic name is worse than a random one -- a leftover from an earlier run of the same item would be
inherited rather than avoided, and `tar x` over an existing tree leaves whatever the archive does not overwrite. This
is the clause that makes W1 safe.

**W3.** The removal is guarded. `rm -rf` on a path built from a template is the one genuinely dangerous line in this
harness, so a workspace is refused unless it is absolute, under a configured root, and has a non-empty final
component -- and the guard is a function with its own tests rather than a condition inline in a shell string.

**W4.** Nothing else changes. The trace id stays the join key; the session id stays as it was for telemetry.

## What this gives up, said before running it

The workspace no longer identifies a *run*, only an item. Two consequences, both accepted:

- Two concurrent runs of the same item would collide. Runs are sequential today, and the guard does not make them
  safe to parallelise. Whoever parallelises this must revisit W1.
- The recovery path in `workspace_audit.py` that reconstructs a workspace from the returned tar's name still works,
  because the tar is named after the session. But a workspace name no longer tells you which run made it. The
  manifests already carry that mapping and are keyed by run group, so nothing depends on the name for it.

## How it is verified

1. **The mechanism, and it is directly checkable.** Across 24 items, zero paths that are a near-miss of the run's own
   workspace. This is the sub-condition the previous arm failed, measured by `workspace_audit.py`, and the previous
   arm's number to beat is 1 with baselines at 1 and 4.
2. **Reported with a denominator, not as a bare zero.** A review pointed out that "zero near-misses" is also what a
   run that never wrote an absolute path produces, and those two are opposite results. So the audit now counts
   correct self-references too, and the reading is the pair: how many runs named their own workspace, and how many
   got it wrong. `matplotlib__matplotlib-26208`, which mistranscribed in all three arms, is the run to look at
   first -- but its individual behaviour is **not** a pass criterion, because one stochastic trajectory cannot gate
   acceptance. That was the same mistake the import-resolution contract made and had corrected.
3. **Freshness, checked rather than assumed.** A run whose workspace already exists with a stray file must not see
   that file. Checked as a test against the assembled shell command, and once on the pod.
4. **No regression, as a limitation not a guard.** Same sample-size limit as the previous two changes.

An increase in the solve count is **not** required. The honest expectation is that a refused call becomes a
successful one on a small number of runs, and that the solve rate does not move measurably at 24 items.

**What would falsify the premise.** Any run mistranscribes its own item-named workspace. If a model cannot reproduce
a name made entirely of words from its own prompt, the problem was never the entropy of the string -- and a review
named the most likely shape of that failure: a repository written once instead of twice, one underscore instead of
two, or a changed issue digit. `matplotlib__matplotlib-26208` contains its repository name twice and is the obvious
candidate.

An earlier draft of this section named `pydata__xarray-4695` here while clause 2 named
`matplotlib__matplotlib-26208`. A pass condition and its falsifier pointing at different items is an inconsistency a
review caught, and the resolution is that neither names an item: the condition is over all 24 runs and the named
items are where to look, not what decides.

**The cheapest observation, and why it could not be taken before the arm.** A review asked for the recorded
transcripts to be audited for occasions when the model emitted an instance id, before spending an arm. That was
measured and the answer is that there are none: across all three recorded arms the instance id appears in no tool-call
parameter, because nothing in those arms put it in a path. The recorded traces cannot test this premise, which makes
the arm the cheapest available observation rather than an extravagance. The first item of it referenced
`/tmp/w/astropy__astropy-14365` five times and got it right five times.

## Two confounds a review found, recorded before the arm's numbers are read

Recorded now, at item 12 of 24, with nothing computed from the arm yet. Writing a confound down after seeing the
result is worthless, so the timing is part of the record.

**The workspace name now puts a public benchmark id in every path the model sees.** `matplotlib__matplotlib-26208` is
a SWE-bench Verified instance id whose issue, pull request and gold patch are plausibly in training data. The three
recorded arms did not leak it: the staging path `/work/testbeds/<id>/staged.tar` appears only in the shell command
the parent ran, never in anything the agent reads, and the old workspace name was random. So a solve-rate difference
in this arm has a second available explanation that has nothing to do with transcription, and it points the same way
the change's author would like.

What follows from that, and it is a real cost of this change rather than a caveat: **this arm cannot support a
solve-rate claim at all**, not even the weak one the contract already declined to make. The mechanism metric --
whether a run mistranscribes its own workspace -- is unaffected, because recognising an id from training data does not
help a model copy it. That metric remains readable and it is the only thing this arm decides.

A cheaper design existed and was not taken because the arm was already running: name the workspace after a **hash of**
the item id, or after the repository and a short sequence number, which keeps low entropy and leaks nothing. If the
mechanism metric improves here, that is the version to ship, and the difference between them is worth one more arm.

**The audit's near-miss rule is calibrated for the naming scheme it replaced.** With random hex, any id within two
edits of the run's own was almost certainly a mistranscription. With item names it is often **another real item**:
`astropy__astropy-14365` and `astropy__astropy-14369` are one edit apart and both are in this 24-item set, and
`pydata__xarray-4695` and `pydata__xarray-4094` are two. So a run that reaches into a sibling item's workspace --
contamination, the more serious finding -- can be filed as its own id written wrong, which is the less serious one.
The membership check against the manifests catches it only for items that have already run, so mid-arm it is live.
Being fixed by giving the audit the item set, which it can read from the outcomes file: a tail that exactly equals a
known item id is another item's workspace, whatever its edit distance.
