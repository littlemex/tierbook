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
the agent was given, so there is nothing to memorise. It is also shorter than what it replaces.

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
2. **The item that has failed three times.** `matplotlib__matplotlib-26208` does not mistranscribe its workspace.
   That is a statement about its tool calls, not about whether it solves -- it has scored `incorrect` in all three
   arms and may well again.
3. **Freshness, checked rather than assumed.** A run whose workspace already exists with a stray file must not see
   that file. Checked as a test against the assembled shell command, and once on the pod.
4. **No regression, as a limitation not a guard.** Same sample-size limit as the previous two changes.

An increase in the solve count is **not** required. The honest expectation is that a refused call becomes a
successful one on a small number of runs, and that the solve rate does not move measurably at 24 items.

**What would falsify the premise.** A run mistranscribes `/tmp/w/pydata__xarray-4695`. If a model cannot reproduce a
name made entirely of words from its own prompt, the problem was never the entropy of the string.
