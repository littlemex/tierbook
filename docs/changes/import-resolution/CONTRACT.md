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

- In the agent pod, `astropy`, `django`, `flask` and `pylint` resolve into four leftover workspaces from earlier
  sweeps, through editable-install artifacts in `/usr/local/lib/python3.11/dist-packages`. 142 run workspaces and
  8.9 GB survive in `/tmp`, so those directories are readable and nothing errors.
- Those four packages cover 10 of the 24 items. That is the number **exposed**.
- A run is only **affected** when it invokes Python from somewhere other than its workspace root, because
  `sys.path[0]` is consulted before the editable finder. The driver execs at the workspace root, so the default case
  is already correct, and `cd <ws>/<package>` is the natural way to leave it.
- Measured over both baselines: 100 `python` calls inside the exposed items, of which **5 ran from a cwd other than
  the workspace root, in 2 runs of 48** -- both in the replicate, both scored `incorrect`.
- Both of those agents noticed. `astropy__astropy-14365` compared the two trees with `ls` and tried to `cp` its fix
  into the one Python was importing (refused). `pylint-dev__pylint-4551` bypassed the import system with
  `importlib.util.spec_from_file_location`, having written `# Direct import to avoid any caching`.

**A first version of this contract claimed the defect affects 10 items.** A review refuted it and the measurement
above replaces it: 10 exposed, 2 observed affected.

**What is not established.** That this cost either solve. Both affected runs scored `incorrect` while working around
false feedback, and 2 observations decide nothing about a rate.

**The stronger reason to fix it is not the incidence.** A run that performs an editable install repoints the package
to its own tree and hands the pointer to whoever runs next, so for the exposed repositories the items within one arm
are order-dependent rather than independent trials -- measured live, see the premise document.

## What changes

**D1.** The driver sets `PYTHONPATH` for each run to that run's own workspace, and to `<workspace>/src` as well,
because repository layouts differ -- `<ws>/astropy` and `<ws>/django` against `<ws>/src/flask`. Both entries, always,
rather than a per-repository table: an entry naming a directory that does not exist costs nothing, and a table is a
second thing to keep in step with the item set.

**D2.** `PYTHONPATH` is chosen over the alternatives because it was **measured** to win against the editable finder
on the pod, and to survive a nested `sh -c`, a `bash -lc` login shell and a Python `subprocess`. Only `env -i`
escaped it. The checks are in the premise document and are repeated as tests.

**D3.** Nothing changes except that environment variable and its consequences. A review pointed out that calling the
variable the only observable change is false: `PYTHONPATH` alters `sys.path`, import origins, plugin discovery, test
collection and traceback paths, and `<ws>/src` can shadow a top-level name. Those are the intended effects plus one
risk, and the risk was checked rather than dismissed -- on this subset `src/` holds importable packages only for
flask and pytest, each the repository's own, while matplotlib's holds C++ sources. What does not change: the model,
the endpoint, the decode policy, the agent definition, the tools, the items, the oracle and the prompt variant.

**Deliberately not fixed here: the 142 leftover workspaces.** They are what make a stale pointer resolvable instead
of failing loudly, so cleaning them would also mask the defect rather than fix it, and it would change disk state
under a measurement in a way no arm could be compared across. Cleanup belongs to whoever owns the pod's lifecycle.

## How it is verified

Against the two recorded baselines, paired, on all 24 items.

**Pass condition, stated before the run.** A review's central point about the first version is taken: a clause that
names one stochastic trajectory cannot gate acceptance, because the agent may simply not test its edit that time.
The gate is a deterministic replay; the arm is a check for damage, not the evidence.

1. **A deterministic replay, which is the gate.** Take the recorded commands from the two affected runs verbatim --
   `cd <ws>/astropy && python -c "from astropy.io.ascii.qdp import _line_type; ..."` and the pylint equivalent --
   and run each in a staged workspace under both environments. The old environment must import the stale file and
   the new one must import the edited file. Asserted on `importlib.util.find_spec(...).origin` after `realpath`, not
   on a string prefix, and asserted for a **submodule** as well as the top-level package, because a namespace or
   `__path__` extension can make the top level local while submodules come from elsewhere. This runs in the test
   suite, so it does not need a measurement slot at all.
2. **The arm, which checks for damage rather than proving the fix.** Across all 24 items, zero runs reference
   another run's workspace, and no run shows an import error or a collection failure that the baselines did not.
   Neither affected run repeating its workaround is worth reporting and is **not** a pass criterion: it can pass
   spuriously (the agent never tests its edit) and fail spuriously (the agent mentions the old path while
   diagnosing something else).
3. **No regression, stated as a limitation rather than a guard.** With 24 items and run-to-run movement estimated
   from a single replicate pair, a regression of one to three items sits inside the noise and this design cannot
   detect it. The same limit as the workspace-binding change and for the same reason.

An increase in the solve count is **not** required and would not be believable: 2 runs of 48 were affected, so there
is almost nothing for a solve rate to show.

**What would falsify the premise.** Half of it already was: the pod-level probe measured a state most runs are not
in, because the driver's cwd already shadows the finder. What remains falsifiable is the replay -- if the recorded
command imports the run's own file under the old environment too, then something else produced the unedited
behaviour those two agents saw, and this change addresses nothing.

**What this change is worth, said plainly.** It removes a trap that fired twice in forty-eight runs and an
order-dependence that is present in every arm whether or not it fires. It is a cheap fix with a deterministic test
and it should not be sold as a solve-rate improvement.

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
