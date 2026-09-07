# CONTRACT: bind the agent to its workspace in the task prompt

## Out of scope, written first

| Not changing | Why |
|---|---|
| The permission system that rejected the out-of-workspace calls | It behaved correctly. The agent asked to read `/tmp` and `/` and to clone from the internet; refusing is the point of a sandboxed measurement, and loosening it would make the measurement about a machine nobody would run. |
| The model, the endpoint, the decode policy | The candidate tuple must not move, or the before/after is not a paired comparison of one change. |
| The agent definition (`build`) and its tool set | Same reason. |
| The item set, the oracle, the scorer | A change to what counts as solved would make the two measurements incomparable. |
| The `Do not write any tests` and `When you are done, stop` instructions | Both are load-bearing for the oracle: the test patch is applied after the diff is taken, and a run that never stops is a timeout rather than an answer. |
| The three-control scorer battery | Already passing on four instances across four repositories; nothing here touches it. |
| Retrying the two failed items alone | A change measured only on the items that motivated it cannot be distinguished from those items being easy the second time. The whole set is re-run. |

## The premise, checked before the change (phase 1)

_Superseded by `01-design/premise-check.md`, which measured all 24 runs instead of reading two. The summary below
is kept because the contract's scope was decided from it and an amendment should show what it was decided from._


**Claim.** The prompt does not bind the agent to its workspace, so some runs search outside it, hit the
permission wall, and stop having edited nothing.

**Checked against the recording, not reasoned about.** Two of 24 runs on the self-hosted arm returned
`unobserved/unsupported` -- zero files touched -- after 8 and 12 seconds, with exit code 0. The telemetry's tool
spans say what happened:

- `pydata__xarray-4695`: first call `glob {"pattern":"**/xarray/**/*.py","path":"/tmp"}` -> **rejected by the
  permission system**. Then `bash find /tmp`, then a subagent told to *"Search the xarray repository in /"*, then
  `grep {"path":"/"}` -> rejected. It never looked inside its own workspace.
- `pytest-dev__pytest-8399`: first `glob` (workspace-relative) succeeded; then
  `bash cd /tmp && git clone --depth 1 https://github.com/pytest-dev/pytest.git` -> **rejected**. It stopped.

For contrast, `astropy__astropy-14369`, which solved: every one of its 18 tool calls used an absolute path under
its own workspace, `/tmp/run-opencode-c4cd6ae898/...`.

So the failure is neither incapability nor a broken harness. The prompt says "in the current directory" and the
agents that fail do not act as though a current directory exists.

## What changes

**C1.** The task prompt states the workspace as an absolute path, and states that it is the complete checkout.
The driver already knows the path -- it stages the tree there -- so this is passing a fact the harness has rather
than adding a policy. The evidence that this is the right lever is the truncation: an agent reconstructed its own
workspace path and lost a character off the end, which is what happens to a path nobody stated.

**C2.** The prompt states that the environment is offline and that fetching the repository is neither possible
nor necessary. One failure was an attempted `git clone`.

**C3.** Nothing outside the prompt text changes. Same tools, same model, same oracle, same items.

**Attribution is deliberately given up.** C1 and C2 are two hypotheses matched to two different failures, and
running them together means a pass cannot say which sentence did the work. At 24 items, splitting them costs two
more runs to buy an attribution that the interval could not support anyway. Stated rather than implied.

**What C3 excludes, and why that is now a decision rather than an assumption.** Two harness-side levers were
weighed and left out. The permission system's *rejection message* could name the workspace, which would bind the
agent through the tool rather than through text it can ignore -- a plausibly better fix, excluded because it
changes the harness under the measurement and cannot then be told from the prompt. And the `todowrite` schema
mismatch found in phase 1 is a real defect that this change does not touch; folding it in would put two unrelated
fixes behind one result.

## How it is verified (phase 5)

Paired, on the whole item set, against a baseline that is itself a replicate:

1. Two runs of the current prompt (baseline and its replicate) establish run-to-run movement, so an improvement
   can be told from a draw. One of those runs is already recorded; the second is in flight.
2. One run of the changed prompt on the same 24 items.
3. `harness/paired_arms.py` for the discordance table and its interval; `harness/replicates.py` for whether the
   baseline reproduced itself at all.

**Pass condition, stated before the run.** A review pointed out that the first version could pass by flakiness or
by activity, so it has three parts and the mechanism one is not optional:

1. **Mechanism, across all 24 items, not just the failures.** Zero tool calls naming a path outside the run's own
   workspace, and zero permission rejections attributable to a path. This is the thing the change is supposed to
   do, and it is checkable from the telemetry independently of any outcome.
2. **The motivating failures.** Both items attempted, where attempted means a non-empty diff *under the repository
   tree* -- not merely non-zero files touched, which a scratch file would satisfy. And they must have failed in
   **both** baseline runs: if the replicate already attempts them, the failure is stochastic and this change
   cannot be credited with fixing it.
3. **No regression beyond what step 1 measured.** Stated as a limitation rather than a guard: with a paired
   interval spanning roughly fourteen points either side and run-to-run movement estimated from a single
   replicate pair, a regression of one to three items would sit inside the noise and this design cannot detect it.

An increase in the solve count is **not** required and would not be believable at this sample size.

**What would falsify the premise:** paths outside the workspace still appear in the telemetry after the change.
Note what does *not* falsify it -- a run that stays inside its workspace and still returns zero edits. That is the
failure mode having moved rather than the premise being wrong, and it needs its own diagnosis rather than a
verdict.

## Amendments

**2026-09-08, after the phase-2 review.** The premise was restated from all 24 runs rather than two: 6 of 24 runs
had a refused tool call and 0 of the 10 that solved did. Two competing hypotheses were refuted by measurement
rather than by argument -- the driver's cwd is correct, and the permission system never rejected a real workspace
path. The pass condition gained the mechanism check and the requirement that the motivating failures reproduce in
both baseline runs, because as first written it could pass by flakiness or by a scratch file. The regression clause
was demoted from a guard to a stated limitation. And two excluded levers -- the rejection message, and the
`todowrite` schema defect -- are now named as decisions rather than left out silently.
