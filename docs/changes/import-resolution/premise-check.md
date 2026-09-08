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

## `PYTHONPATH` alone is necessary and not sufficient: the package resolves half from each tree

A reviewer asked for the pass condition to assert on a **submodule** and not only the top-level package, because a
`__path__` extension can make one local while the other comes from elsewhere. That is exactly what happens, measured:

    PYTHONPATH=<own ws>, from /:
      astropy        -> <own ws>/astropy/__init__.py
      astropy.io.ascii.qdp  -> <own ws>/astropy/io/ascii/qdp.py
      astropy.convolution._convolve -> /tmp/run-opencode-acf4781c5e/astropy/convolution/
                                         _convolve.cpython-311-x86_64-linux-gnu.so     <-- ANOTHER RUN
      astropy.__path__ -> ['<own ws>/astropy']

The cause is the extension tag. The staged tar carries 17 `.so` files built for **cpython-39** and the pod runs
**3.11**, so `PathFinder` searching the run's own `__path__` cannot satisfy `_convolve`; the editable finder then
answers by name, and it names a tree where some run performed an editable install and compiled for 3.11. The
leftover the finder points at has both tags -- 17 cpython-39 and 17 cpython-311 -- while the run's own tree has only
the 39s.

So every arm recorded so far imported a **mixture**: pure-Python modules from the run's own checkout and compiled
extensions from another run's. No import failed, in either configuration, for any of `astropy`,
`astropy.io.ascii.qdp`, `astropy.convolution`, `astropy.units`, `astropy.table` or `astropy.io.fits`. The wrongness
is silent by construction.

That settles a second reviewer's question in the other direction too: the worry was that pointing `PYTHONPATH` at an
unbuilt checkout would turn silent wrongness into an `ImportError`. It does not, because the fallback quietly
supplies the missing binary. The absence of the error **is** the defect.

## Leftover trees hold earlier runs' edits of the same file

One reviewer argued the 142 leftover workspaces are not only an import hazard but a channel by which an agent can
read another run's answer to its own task. Checked against the staged tar for `astropy__astropy-14365`, comparing
`astropy/io/ascii/qdp.py`:

- 23 leftover trees contain that file; 15 differ from the staged version, 8 match.
- Two of the differing trees are recorded workspaces **for that same item**: `700cd74ee4` from baseline 2 and
  `99059ca0bd` from the arm currently running.

So a later run of `astropy__astropy-14365` can read an earlier run's edit of the exact file it has been asked to
change. That is contamination of an outcome, not of self-verification, and it is present in every arm.

The other 13 differences are not separated here between other items' base revisions and other runs' edits, and are
not claimed as either. Two is enough.

An earlier version of this check looked for `git diff` in the leftover trees and found nothing, which proved nothing:
no leftover workspace has a `.git` directory and `git` is not installed in the pod.

## The fix, and the tests that chose it

`PYTHONPATH` wins against the editable finder, and it survives the ways a run reaches an interpreter. Measured on the
pod rather than reasoned about:

    PYTHONPATH=<ws>, cd <ws>/astropy  ->  <ws>/astropy/__init__.py          (the failing case, fixed)
    nested `sh -c`                    ->  sees it
    `bash -lc` login shell            ->  sees it
    Python `subprocess`               ->  sees it
    `env -i`                          ->  does NOT see it (clears the environment on purpose)

Two entries are needed because layouts differ: `<ws>` for astropy, django and pylint, `<ws>/src` for flask -- and
`PYTHONPATH` beats the `easy-install.pth` route as well as the finders, which was worth measuring because that file
is documented to front-load its entries. It does not front-load ahead of `PYTHONPATH`: with the variable set,
`sys.path[0]` is its value.

Both entries always, rather than a per-repository table, and the shadowing risk that raises was checked rather than
dismissed: of the leftover workspaces on the pod, `src/` holds importable packages only for flask (`flask`) and
pytest (`pytest`, `_pytest`) -- each the repository's own package -- while matplotlib's `src/` holds C++ sources with
no importable top-level name. So on this subset the extra entry shadows nothing it should not.

**But `PYTHONPATH` is not the whole fix**, because of the mixed resolution above. Two more parts, both of which were
in the rejected column before the submodule was measured:

- **Remove the editable-install artifacts.** With them gone, a missing `cpython-311` extension raises instead of
  being supplied from another run's tree. Loud is what is wanted here: the run cannot silently exercise a foreign
  binary, and an `ImportError` naming the extension tells the agent what is actually wrong. The earlier argument
  against this -- "it fixes the pod until the next run installs one" -- is an argument for doing it per run, not for
  not doing it.
- **Remove the run's workspace when the run ends.** Not for disk, though 8.9 GB on a shared node matters, but
  because leftover trees hold earlier runs' edits of the same file. The earlier reasoning here was that cleaning
  would "mask the defect"; two reviewers called that wrong and they are right. Failing loudly is the goal, and a
  workspace that no longer exists cannot be imported from, read from, or written into.

`pip install -e .` per run stays rejected: it rewrites the same process-global artifact that caused this, so
concurrent runs would fight over it.

## What this does to the workspace-binding change

The `cp` into `c4cd6ae898` is **withdrawn** as evidence for that contract's premise: it was an agent working around
this defect, not one failing to stay in its workspace. The other five "wrote its own workspace id wrong" observations
are untouched -- they name directories that never existed, and no import path can produce them.

## Not implemented yet, deliberately

The changed-prompt arm is running. Each item spawns a fresh driver process, so editing the driver now would give
items 1..N one environment and N+1..24 another, and the arm could not be compared with either baseline.
