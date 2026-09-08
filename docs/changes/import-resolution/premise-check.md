# An agent verifying its own edit can import a different run's code

Found while checking a reviewer's question about a single tool call. It is a harness defect and it is invisible in
every outcome the harness produces. **A first version of this document said it affects 10 of the 24 items; a review
refuted that and the measurement below replaces it. It bit 2 runs of 48.**

## The route, measured on the pod

Four packages resolve into leftover workspaces from *previous sweeps*:

    astropy   -> /tmp/run-opencode-acf4781c5e/astropy      (was c4cd6ae898 an hour earlier -- see below)
    django    -> /tmp/run-opencode-4f22569e96/django
    flask     -> /tmp/run-opencode-d9cb5ac510/src/flask
    pylint    -> /tmp/run-opencode-f330e33f0e/pylint

through editable-install artifacts in `/usr/local/lib/python3.11/dist-packages`: three `__editable___*_finder.py`
meta-path finders and one `easy-install.pth`. 142 run workspaces and 8.9 GB survive in `/tmp`, so the directories
those artifacts name are still readable and nothing errors.

Those four packages cover 10 of the 24 items in the pilot subset. That is the number **exposed**, and it is not the
number affected.

## What decides whether a run is actually affected: its cwd

The correction. `sys.path[0]` is the invoking directory and is consulted before the editable finder, so a run that
invokes Python from its workspace root already imports its own code with nothing set:

    cd <ws>            && python3 -c "import astropy"  ->  <ws>/astropy/__init__.py            (correct)
    cd <ws>/astropy    && python3 -c "import astropy"  ->  /tmp/run-opencode-acf4781c5e/...    (another run)
    cd /               && python3 -c "import astropy"  ->  /tmp/run-opencode-acf4781c5e/...    (another run)

The driver execs the agent with cwd at the workspace root, so the default case is safe. The defect bites only when a
run moves somewhere else first -- and `cd <ws>/<package>` is the natural mistake, because that is where the source
being edited lives.

**Measured over the two recorded baselines**, counting every `bash` call containing `python` inside the 10 exposed
items and taking each call's effective cwd from its own `cd` or `workdir`:

| | exposed items | python calls in them | calls from a cwd other than the workspace root | runs affected |
|---|---|---|---|---|
| baseline 1 | 10 | 53 | 0 | none |
| baseline 2 | 10 | 47 | 5 | 2 |

So the incidence is **2 runs of 48**, both in the replicate, both scored `incorrect`.

## The two runs, and what they did about it

Both are the same shape -- `cd <ws>/<package> && python3 -c "import <package>..."` -- and in both the agent noticed
that something was wrong and worked around it rather than trusting the answer.

`astropy__astropy-14365` edited `astropy/io/ascii/qdp.py` in its own workspace, then ran
`cd <ws>/astropy && python -c "from astropy.io.ascii.qdp import _line_type; ..."` and got the **unedited** behaviour.
It then ran

    ls /tmp/run-opencode-c4cd6ae898/astropy/io/ascii/qdp.py /tmp/run-opencode-700cd74ee4/astropy/io/ascii/qdp.py

comparing the two trees, and finally tried

    cp /tmp/run-opencode-700cd74ee4/.../qdp.py /tmp/run-opencode-c4cd6ae898/.../qdp.py

which the permission system refused.

`pylint-dev__pylint-4551` did the same thing and then bypassed the import system entirely. Its third attempt reads

    cd /tmp && python3 -c "
    import astroid
    # Direct import to avoid any caching
    import importlib.util
    spec = importlib.util.spec_from_file_location('writ...

so it had concluded the import was giving it the wrong file and loaded the file by path instead. It scored
`incorrect`.

Both agents diagnosed their situation correctly. The harness was lying to them.

**What is not established.** That this cost either solve. Both runs scored `incorrect` and both were working around
false feedback, but a run can produce a bad patch on its own, and 2 observations decide nothing about a rate.

## Why no outcome shows it

The scorer applies the diff to a clean checkout in a separate testbed, so scoring never reads through the pod's
import path. The damage is confined to the agent's ability to test its own work.

## The pointer moves, and within one arm

Two probes of the same interpreter and the same site directory, minutes apart during the changed-prompt sweep:

    first probe:   import astropy -> /tmp/run-opencode-c4cd6ae898   (a leftover from the FIRST baseline)
    second probe:  import astropy -> /tmp/run-opencode-acf4781c5e

`acf4781c5e` is that same sweep's `astropy__astropy-14369` workspace -- its item 2. A run that performs an editable
install repoints the package to its own tree, which fixes that run and hands the pointer to whoever comes next. Item
1 imported a leftover from a previous arm; item 3, running next, imported item 2's tree.

So for the exposed repositories the items in one arm are **order-dependent rather than independent trials**, whether
or not any given run trips over it. That is uncontrolled in all three arms recorded so far, and it is a better reason
to fix this than the 2-in-48 incidence is.

## The fix, and the tests that chose it

`PYTHONPATH` wins against the editable finder, and it survives the ways a run reaches an interpreter. Measured on the
pod rather than reasoned about:

    PYTHONPATH=<ws>, cd <ws>/astropy  ->  <ws>/astropy/__init__.py          (the failing case, fixed)
    nested `sh -c`                    ->  sees it
    `bash -lc` login shell            ->  sees it
    Python `subprocess`               ->  sees it
    `env -i`                          ->  does NOT see it (clears the environment on purpose)

Two entries are needed because layouts differ: `<ws>` for astropy, django and pylint, `<ws>/src` for flask. Both
always, rather than a per-repository table, and the shadowing risk that raises was checked rather than dismissed: of
the leftover workspaces on the pod, `src/` holds importable packages only for flask (`flask`) and pytest (`pytest`,
`_pytest`) -- each the repository's own package -- while matplotlib's `src/` holds C++ sources with no importable
top-level name. So on this subset the extra entry shadows nothing it should not.

Rejected: `pip install -e .` per run, which costs a build per run and rewrites the same process-global artifact that
caused this, so concurrent runs would fight over it. Also rejected: deleting the editable artifacts once, which fixes
the pod until the next run installs one.

## What this does to the workspace-binding change

The `cp` into `c4cd6ae898` is **withdrawn** as evidence for that contract's premise: it was an agent working around
this defect, not one failing to stay in its workspace. The other five "wrote its own workspace id wrong" observations
are untouched -- they name directories that never existed, and no import path can produce them.

## Not implemented yet, deliberately

The changed-prompt arm is running. Each item spawns a fresh driver process, so editing the driver now would give
items 1..N one environment and N+1..24 another, and the arm could not be compared with either baseline.
