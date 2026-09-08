# An agent verifying its own edit imports a different run's code

Found while checking a reviewer's question about a single tool call. It is a harness defect, it is invisible in every
outcome the harness produces, and it affects 10 of the 24 items in the pilot subset.

## What is true, measured on the pod

In the agent pod, four packages resolve into leftover workspaces from *previous sweeps*:

    astropy   -> /tmp/run-opencode-c4cd6ae898/astropy
    django    -> /tmp/run-opencode-4f22569e96/django
    flask     -> /tmp/run-opencode-d9cb5ac510/src/flask
    pylint    -> /tmp/run-opencode-f330e33f0e/pylint

They resolve there through editable-install artifacts left in `/usr/local/lib/python3.11/dist-packages`: three
`__editable___*_finder.py` meta-path finders and one `easy-install.pth`. 142 run workspaces and 8.9 GB survive in
`/tmp`, so the directories those artifacts name are still present and readable, which is why nothing errors.

Of the 24 items in the subset, astropy has 3, django 3, pylint 3 and pallets/flask 1: **10 items** where
`python -c "import <pkg>"` inside a run reads code from a different run.

## How it was found, and what it explains

A reviewer asked how a run could have named `c4cd6ae898` -- a well-formed 10-character id belonging to another
sweep -- when a random id cannot be guessed. Reading that run's calls in order answers it. Calls 0 through 12 of
`astropy__astropy-14365` are all inside its own workspace `700cd74ee4`: it read `astropy/io/ascii/qdp.py`, edited it,
and then at calls 9 and 11 ran `cd <own workspace>/astropy && python -c "from astropy.io.ascii.qdp import
_line_type; ..."` to check the edit. That import resolved to `c4cd6ae898`, so it exercised **unedited** code and
reported the old behaviour. At call 13 the agent ran

    ls /tmp/run-opencode-c4cd6ae898/astropy/io/ascii/qdp.py /tmp/run-opencode-700cd74ee4/astropy/io/ascii/qdp.py

comparing the two, and at call 31

    cp /tmp/run-opencode-700cd74ee4/.../qdp.py /tmp/run-opencode-c4cd6ae898/.../qdp.py

which the permission system refused. The run was recorded `incorrect`.

So the agent diagnosed the situation correctly and acted rationally on it. The `cp` was not an agent wandering out of
its workspace; it was an agent trying to make its own edit take effect in the tree Python was actually importing.
The workspace-binding change's premise reads that behaviour as the prompt failing to bind the agent, and for this
item that reading is wrong.

## Why no outcome shows it

The scorer runs in a separate testbed and applies the diff to a clean checkout, so the score is not computed through
the pod's import path. The damage is entirely to the agent's ability to test its own work: every `import` check on
those 10 items returns another run's behaviour. An agent that trusts it concludes a correct fix did not work.

## The pointer moved while the next arm was running, which makes this worse than stated above

Measured live rather than argued. Two probes of the same interpreter and the same site directory, minutes apart
during the changed-prompt sweep:

    first probe:   import astropy -> /tmp/run-opencode-c4cd6ae898/astropy   (a leftover from the FIRST baseline)
    second probe:  import astropy -> /tmp/run-opencode-acf4781c5e/astropy

`acf4781c5e` is the changed arm's own `astropy__astropy-14369` workspace -- item 2 of that sweep. So during item 2 a
run performed an editable install and repointed the package to its own tree.

Two consequences, and the second is the one that matters.

A run that installs fixes itself. The damage falls on runs that do not: item 1 (`astropy-14365`) imported the first
baseline's leftover, and item 3 (`astropy-14995`), which ran next, imported **item 2's** tree.

So the three astropy items in one arm are not independent trials. Whichever astropy run installs last determines what
every later astropy run imports, which makes the result order-dependent within a single arm -- not merely
non-stationary across arms, which is how the workspace-binding contract's limitation first recorded it. The same
holds for the three django items, the three pylint items and flask.

## The fix, and the test that chose it

`PYTHONPATH` beats the editable finder, verified on the pod rather than reasoned about:

    no PYTHONPATH:    import astropy -> /tmp/run-opencode-c4cd6ae898/astropy/__init__.py
    PYTHONPATH=<ws>:  import astropy -> <ws>/astropy/__init__.py

It also survives every way a run reaches an interpreter, measured on the pod rather than assumed: a nested `sh -c`,
a `bash -lc` login shell, and a `subprocess` spawned from Python all see it. The only probe that escaped was
`env -i`, which clears the environment on purpose.

So one environment variable per run fixes it, and it needs two entries because repository layouts differ: `<ws>` for
astropy and django, `<ws>/src` for flask. Two alternatives were rejected. Running `pip install -e .` per run is what
a SWE-bench harness normally does but costs a build per run and repoints a process-wide artifact, so concurrent runs
would fight over it. Deleting the editable artifacts once fixes the pod until the next run installs one, which is the
same defect with a longer fuse.

Cleaning `/tmp` is separate and also wanted: 142 leftover workspaces are what make the stale pointers resolvable
instead of failing loudly.

## Not implemented yet, deliberately

The changed-prompt arm is running. Each item spawns a fresh driver process, so editing the driver now would give
items 1..N one environment and N+1..24 another, and the arm could not be compared with either baseline. The fix lands
after that arm finishes, as its own change with its own contract and its own before/after -- on which those 10 items
are the interesting ones.

## What this does to the workspace-binding change in flight

It does not invalidate it, and it narrows what it can claim.

- The stale pointer was present in both baselines and is present in the changed arm, so the comparison is between
  arms that share the defect.
- It is worse than not stationary. As the section above measures, the pointer moved during the changed arm to that
  arm's own item 2, so within one arm the astropy items are **order-dependent**: whichever installs last decides what
  every later astropy run imports. That is uncontrolled in all three recorded arms and belongs in the limitations
  rather than being discovered later.
- One of the six "wrote its own workspace id wrong" observations is now explained by something else entirely, and it
  is the only one of the six involving a real other-run directory. The other five remain unexplained by this and
  still name directories that never existed.
