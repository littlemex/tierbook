# CONTRACT: a run's own checkout is what its imports resolve to

## Out of scope, written first

| Not changing | Why |
|---|---|
| The permission system | It behaved correctly again. It refused the `cp` into another run's tree, which is the only reason a stale directory was not written to. |
| The model, the endpoint, the decode policy, the agent definition, its tool set | The candidate tuple must not move or the before/after is not a paired comparison of one change. |
| The item set, the oracle, the scorer | The scorer already applies the diff to a clean checkout in a separate testbed, so it never read through the pod's import path. It is not implicated and changing it would make the measurements incomparable. |
| The task prompt | The workspace-binding change owns the prompt. Two changes to the same measurement in one arm cannot be told apart. |
| Removing the editable-install artifacts from the image | It fixes the pod until the next run performs an editable install, which is the same defect with a longer fuse. Recorded as rejected rather than left unconsidered. |
| Making the agent pod single-use per run | It would remove this and several neighbouring problems, and it costs a pod start per run on a shared node. Worth doing and not here; this change must be measurable against the recorded baselines, which used a long-lived pod. |

## The premise, checked before the change

`01-design/premise-check.md` holds the measurement. In short, and every line of it observed rather than reasoned:

- In the agent pod, `import astropy` resolves to `/tmp/run-opencode-c4cd6ae898/astropy` -- a leftover workspace from
  an earlier sweep. `django`, `flask` and `pylint` resolve into three other leftover workspaces.
- The route is editable-install artifacts in `/usr/local/lib/python3.11/dist-packages`: three
  `__editable___*_finder.py` meta-path finders and one `easy-install.pth`. 142 run workspaces and 8.9 GB survive in
  `/tmp`, so those directories are still readable and nothing errors.
- Those four packages cover **10 of the 24 items** in the pilot subset.
- One recorded run acted on it: `astropy__astropy-14365` edited the file in its own workspace, ran
  `python -c "from astropy.io.ascii.qdp import _line_type"`, got the unedited behaviour, compared both trees with
  `ls`, and tried to `cp` its fix into the tree Python was importing. Refused. Scored `incorrect`.

**What is not established.** That this costs solves. One run is observed acting on it; the other nine items' runs may
never have imported anything. The size of the effect is what the change measures, and the premise claims only that
the harness returns another run's behaviour to an agent testing its own edit.

## What changes

**D1.** The driver sets `PYTHONPATH` for each run to that run's own workspace, and to `<workspace>/src` as well,
because repository layouts differ -- `<ws>/astropy` and `<ws>/django` against `<ws>/src/flask`. Both entries, always,
rather than a per-repository table: an entry naming a directory that does not exist costs nothing, and a table is a
second thing to keep in step with the item set.

**D2.** `PYTHONPATH` is chosen over the alternatives because it was **measured** to win against the editable finder
on the pod, not assumed to. The check is in the premise document and is repeated as a test.

**D3.** Nothing the candidate can observe changes except that environment variable. Same tools, same model, same
oracle, same items, same prompt variant.

**Deliberately not fixed here: the 142 leftover workspaces.** They are what make a stale pointer resolvable instead
of failing loudly, so cleaning them would also mask the defect rather than fix it, and it would change disk state
under a measurement in a way no arm could be compared across. Cleanup belongs to whoever owns the pod's lifecycle.

## How it is verified

Against the two recorded baselines, paired, on all 24 items.

**Pass condition, stated before the run.**

1. **Mechanism, and it is the whole point.** In the changed arm, `python -c "import <pkg>"` inside a run resolves to
   that run's own workspace for every one of the four affected packages. Checked directly by running the import in a
   run's environment, not inferred from an outcome. Zero runs may reference another run's workspace at all.
2. **The item that acted on it.** `astropy__astropy-14365` no longer compares two trees or attempts a `cp` into
   another workspace. That is a statement about its tool calls, not about whether it solves.
3. **No regression, stated as a limitation rather than a guard.** With 24 items and run-to-run movement estimated
   from a single replicate pair, a regression of one to three items sits inside the noise and this design cannot
   detect it. The same limit as the workspace-binding change and for the same reason.

An increase in the solve count is **not** required. If it happens on the 10 affected items and not on the other 14,
that is worth reporting as a pattern and still not worth a causal claim at this sample size.

**What would falsify the premise.** The imports already resolve to the run's own workspace when checked in a live
run -- meaning the pod-level check was measuring a state no run is actually in, for instance because the driver
already sets something that shadows the finder.

## What this does to the workspace-binding result

Stated here because the two changes overlap on one observation and the reader will ask.

The `cp` into `c4cd6ae898` is withdrawn as evidence for the workspace-binding premise: it was an agent working around
this defect, not one failing to stay in its workspace. The other five "wrote its own workspace id wrong"
observations are untouched, because they name directories that never existed and no import path can produce them.

And the coupling is worse than "non-stationary across arms", which is how that contract's limitation first recorded
it. Two probes minutes apart during the changed-prompt sweep showed the astropy pointer move from the first
baseline's leftover to `acf4781c5e` -- the changed arm's own item 2. A run that installs fixes itself; the damage
falls on runs that do not, so item 1 imported a leftover from a previous arm and item 3 imported item 2's tree. The
three astropy items in one arm are therefore **order-dependent, not independent trials**, and the same holds for
django, pylint and flask. That is uncontrolled in every arm recorded so far and it is the reason this change comes
before any further arm is measured.
