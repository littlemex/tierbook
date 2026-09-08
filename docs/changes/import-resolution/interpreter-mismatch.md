# The agent pod has one Python; the items were built with four

The root cause underneath the import-resolution defect, found by following that defect's own error message rather than
by reasoning about it. It is larger than the two changes in flight and it is stated separately so neither of them
absorbs it.

## The measurement

The agent pod runs a single interpreter, `python3` = **3.11.2**. Each SWE-bench testbed image pins its own, and the
staged tar the driver hands a run is that image's `/testbed` tree, compiled extensions included. Reading the extension
tags out of all 24 staged tars:

| tag in the staged tar | items | can the pod's 3.11 load them |
|---|---|---|
| `cpython-311` | 3 (django-17084, matplotlib-26208, matplotlib-26342) | yes |
| no compiled extensions at all | 10 (seaborn, flask, requests-2931, xarray-6992, 3 pylint, 3 pytest) | not applicable |
| `cpython-310` | 3 (xarray-3993, xarray-4094, xarray-4695) | **no** |
| `cpython-39` | 5 (3 astropy, django-15128, requests-1142) | **no** |
| `cpython-36` | 3 (django-11880, sklearn-14496, sklearn-15100) | **no** |

So for **11 of the 24 items** the tree a run is asked to edit cannot be imported by the interpreter that run has.

## What astropy says about it, in its own words

With `PYTHONPATH` pointed at the run's own workspace and the editable-install artifacts removed from the picture,
`import astropy.io.ascii.qdp` raises:

    ImportError: You appear to be trying to import astropy from within a source checkout or from an editable
    installation without building the extension modules first. Either run:
      pip install -e .
    or
      python setup.py build_ext --inplace
    to make sure the extension modules are built

That is the correct diagnosis, delivered by the package itself. The run's own tree has 17 `.so` files, all tagged
`cpython-39`, and none of them is loadable by 3.11.

## Which explains the editable installs, and the whole chain

Some run, at some point, followed that advice and ran `pip install -e .` in its own workspace. That compiled the
extensions for 3.11 **and** wrote a finder into the pod's shared `dist-packages` naming that workspace. From then on
every later run importing `astropy` got:

- pure-Python modules from wherever `sys.path` led, which is its own tree when invoked from the workspace root
- compiled extensions from **that** run's workspace, because its own tree has none 3.11 can load

which is the mixed resolution measured in `premise-check.md`, and the reason nothing ever errored. The editable
artifacts were not a stray leftover; they were the only thing making 11 items importable at all.

## What this does to the two changes in flight

**It does not change the workspace-binding measurement**, which is about prompt text and is already recorded with its
limitations. It does weaken one reading of its premise: an agent that cannot import the tree it is editing has a
reason to look elsewhere that has nothing to do with the prompt not naming a directory.

**It changes the import-resolution contract's D2.** Removing the editable artifacts gives clean isolation and makes
11 of 24 items unimportable in the agent pod. That is honest rather than good: the runs stop exercising a foreign
binary and also stop being able to test their work at all. Recorded as a consequence to accept deliberately or to fix
properly, not as a detail.

## The proper fix, and why it is not in either contract

A run should verify with **the interpreter its own item was built with**. Two shapes, both larger than a driver flag:

- Run the agent inside the item's testbed image, which already has the right conda environment -- the same image the
  scorer uses, whose `/testbed` matplotlib imports correctly under its own 3.11.11 env.
- Or build the staged tree for the pod's interpreter once per item, offline, so `pip install -e .` never has to happen
  inside a run and never writes to a shared directory.

Both remove the entire chain rather than its last link. Neither is attempted here: two changes are already being
measured against these baselines, and a third that moves the interpreter would make all three incomparable.

## What to do in the meantime, stated so it is a decision and not an oversight

Keep the editable artifacts, add `PYTHONPATH` (D1), and add per-run workspace cleanup (D3) -- but **not** artifact
removal (D2). D1 gets the pure-Python modules right, which is where the two observed failures were. Cleanup closes
the channel by which a run reads another run's edit of its own target file. Leaving the artifacts keeps 11 items
importable through a foreign binary, which is wrong and is the least wrong option available without moving the
interpreter.

That last sentence is the honest summary of this document: the fix that removes the defect also removes a capability
the measurement depends on, and the right answer is upstream of both.
