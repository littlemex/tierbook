# CONTRACT: a run's own checkout is what its imports resolve to

## Out of scope, written first

| Not changing | Why |
|---|---|
| The permission system | It behaved correctly again. It refused the `cp` into another run's tree, which is the only reason a stale directory was not written to. |
| The model, the endpoint, the decode policy, the agent definition, its tool set | The candidate tuple must not move or the before/after is not a paired comparison of one change. |
| The item set, the oracle, the scorer | The scorer already applies the diff to a clean checkout in a separate testbed, so it never read through the pod's import path. It is not implicated and changing it would make the measurements incomparable. |
| The task prompt | The workspace-binding change owns the prompt. Two changes to the same measurement in one arm cannot be told apart. |
| Removing the editable-install artifacts | Moved into scope as D2 when a submodule measurement showed `PYTHONPATH` alone leaves the package resolving half from another run's tree, then **withdrawn** when the next measurement showed removal makes 11 of 24 items unimportable. The history is left here rather than tidied away, because the second reversal is the finding. |
| The interpreter a run verifies with | The real fix, and larger than this contract. See `01-design/interpreter-mismatch.md`. Moving it would make all three arms incomparable. |
| ~~Leaving the 142 leftover workspaces~~ | **Moved into scope as D3.** The original reasoning was that cleaning them would mask the defect. Two reviewers called that wrong and they are right: loud failure is the goal. A measurement settled it -- two leftover trees hold an earlier run's edit of the very file `astropy__astropy-14365` is asked to change. |
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

**D2 is withdrawn**, and the reason is worth more than the clause was. It said the driver should remove the
editable-install artifacts, on the ground that `PYTHONPATH` alone leaves `astropy.convolution._convolve` resolving
into another run's tree. That measurement stands. What the next measurement showed is that removing the artifacts
makes **11 of the 24 items unimportable in the agent pod at all**: each item's staged tree is its testbed image's
`/testbed`, compiled for that image's interpreter, and the tags across the 24 tars are `cpython-36`, `-39`, `-310` and
`-311` while the pod runs 3.11. astropy says so itself -- *"trying to import astropy from within a source checkout ...
without building the extension modules first"*. The artifacts were not a stray leftover; they are the only thing
making those items importable, because some earlier run took that advice and built for 3.11 in its own workspace.

So the clean fix removes a capability the measurement depends on, and the right answer is upstream of this contract:
run the agent with the interpreter its own item was built with. `01-design/interpreter-mismatch.md` holds that
measurement and both shapes of the proper fix. Neither is attempted here, because two changes are already being
measured against these baselines and a third that moves the interpreter would make all three incomparable.

Keeping the artifacts is wrong and is the least wrong option available without moving the interpreter. Stated as a
decision rather than left as an oversight.

**D3.** The driver removes a run's workspace when the run ends. Not primarily for the 8.9 GB, but because leftover
trees hold earlier runs' edits: 15 of 23 leftover astropy trees differ from the staged `qdp.py`, and two of them are
recorded workspaces for `astropy__astropy-14365` itself -- one from baseline 2, one from the arm running now. A later
run of that item can read an earlier run's edit of the file it was asked to change, which contaminates an outcome and
not merely a self-check.

**D4.** `PYTHONPATH` was chosen over `pip install -e .` per run because it was **measured** to win against both the
editable finders and `easy-install.pth`, and to survive a nested `sh -c`, a `bash -lc` login shell and a Python
`subprocess`. Only `env -i` escaped it. `pip install -e .` stays rejected: it rewrites the same process-global
artifact that caused this, so concurrent runs would fight over it.

**D5.** Nothing else changes. A review pointed out that calling the
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
   on a string prefix, and asserted for a **submodule** as well as the top-level package -- which is not prudence but
   the finding: a top-level-only assertion passes today while `astropy.convolution._convolve` still comes from
   another run. The replay must include a compiled submodule and require that it either resolves locally or **fails**,
   never that it resolves elsewhere. This runs in the test suite, so it does not need a measurement slot.
2. **The arm, which checks for damage rather than proving the fix.** Across all 24 items, zero runs reference
   another run's workspace. Import errors are **expected** rather than forbidden here, since D2 converts a silent
   foreign binary into a loud failure; what the arm checks is that no run fails for a reason unrelated to a missing
   compiled extension, and that the count of runs blocked by one is reported rather than absorbed.
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

**What this change is worth, said plainly.** Three things, in increasing order of how much they matter and
decreasing order of how visible they were. It removes a trap that fired in 2 runs of 48. It removes an
order-dependence present in every arm whether or not the trap fires. And it removes a path by which a run can read an
earlier run's edit of its own target file, which is the only one of the three that can move a solve rate -- in the
wrong direction. None of that should be sold as a solve-rate improvement; the honest claim is that three arms were
measured on a harness that was not isolating runs, and the next one will be.

**What is left undone, stated plainly.** With D2 withdrawn, a run on one of the 11 mismatched items still loads
compiled extensions from another run's workspace. D1 fixes the pure-Python half, which is where both observed failures
were, and D3 closes the channel by which a run reads another run's edit of its own target file. The other half waits
on the interpreter, and that is a real gap rather than a rounding error: on those items an agent is still testing a
hybrid of its own source and a foreign binary.

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
