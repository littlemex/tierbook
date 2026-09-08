**Overall Verdict**

The defect is plausible and the astropy incident is strong evidence that it occurred once. The broader premise—“10 affected items,” `PYTHONPATH` fully fixes run imports, and the proposed arm measures its consequence—is not established.

I could not review the referenced `01-design/premise-check.md`, driver, transcripts, or pod state because this workspace contains only `prompt.md`. Those claims therefore remain unverified assertions.

**Q1 — Premise**

The following steps do not follow from the observations presented:

- **Pod state → run state.** A bare import in the pod does not establish resolution inside the driver’s actual tool process. The contract itself acknowledges this at `prompt.md:154`. Settle it by recording `env`, `cwd`, `sys.executable`, `sys.path`, `sys.meta_path`, and `importlib.util.find_spec(pkg).origin` from an actual agent tool call before the change.
- **Four vulnerable repositories → ten affected runs.** Repository membership only establishes ten opportunities. It does not show those runs used Python, used the affected interpreter, imported the top-level package, or did so from a vulnerable working directory. “Potentially affected” is justified; “affects 10 items” is not.
- **One command shape → every import check.** The astropy command ran after `cd <workspace>/astropy`. That directory is the package directory, not its parent, so normal `sys.path[0]` lookup cannot find `<workspace>/astropy` as package `astropy`. A command from `<workspace>` may already resolve locally without `PYTHONPATH`. The claim at `prompt.md:47` that *every* import check on all ten items returns another run’s behavior is unsupported.
- **Astropy test → four-package fix.** Only an astropy before/after is shown at `prompt.md:52`. There is no presented `PYTHONPATH` test for Django, Flask, or pylint, especially their test runners and console entry points.
- **Wrong origin → unedited behavior.** Importing from another tree proves the origin is wrong, not that its relevant file differs or explains the observed result. Settle this with `module.__file__`, hashes/diffs of the relevant source in both trees, and a direct demonstration that the two versions produce different results.
- **Old behavior → wrong import.** Old behavior alone could arise from an incomplete fix, cached bytecode, another module, or an incorrect test. The exact transcript must show the imported module’s origin during calls 9 and 11.
- **`ls` and `cp` → diagnosed correctly and acted rationally.** That interpretation is likely, but intention is inferred. The exact preceding tool output or agent text must show how it learned `c4cd6ae898` and why it copied there.
- **Defect occurred → defect caused the incorrect score.** The scorer’s clean result means the pod import did not directly determine scoring. The agent may still have produced a bad patch independently. A counterfactual replay or patch assessment is needed to show that correct local feedback would likely change the submitted diff.
- **142 workspaces → imports do not error.** Only existence and readability of the four referenced targets matter. The total count and disk size are operational concerns, not causal evidence for these imports.
- **Artifacts are the route.** File presence is insufficient. Settle this with `find_spec`, `sys.path`, `sys.meta_path`, the finder mapping, and a removal/disable experiment for each artifact.
- **Artifacts are from “previous sweeps.”** Paths and timestamps can support this, but no run ledger is supplied. A workspace-to-sweep manifest would settle it.
- **Stale pointer existed in both baselines and the changed arm.** Present pod state cannot reconstruct prior process state. More seriously, `prompt.md:79` says the astropy artifact is dated after the first baseline. That does not establish what finder/path won during that baseline. Historical environment snapshots or call-time origins are required.
- **Which tree wins changes whenever an editable install occurs.** Not necessarily. It depends on installer behavior, artifact cleanup, finder order, project name, interpreter, and whether the install writes global or virtual-environment state.
- **Scorer is unimplicated.** Plausible, but unverified here. Settle it with scorer execution records showing a separate filesystem/interpreter and the applied diff’s clean checkout.
- **Permission refusal was the only reason the stale tree was not written.** It was one reason. Filesystem ownership, mount options, command failure, or later cleanup could also prevent or undo it.
- **Only the environment variable is observable.** False literally. `PYTHONPATH` changes `sys.path`, import origins, plugin discovery, test collection, console-command behavior, tracebacks, and potentially dependencies imported from `<workspace>/src`. Those are precisely observable effects.

Thus the narrow premise is sound: **at least one recorded astropy run appears to have tested another run’s code**. The population-level and causal claims are not yet sound.

**Q2 — `PYTHONPATH`**

`PYTHONPATH=<workspace>/src:<workspace>` is a reasonable low-cost mitigation, but it is not an import-isolation invariant.

Ways the bare probe may not generalize:

- The driver sets the variable but fails to `export` it or does not pass it in the tool subprocess environment.
- A subprocess supplies a replacement `env` and drops `PYTHONPATH`.
- `env -i`, `sudo`, `su`, SSH, container execution, or shell startup files clear or replace it.
- `python -E` ignores `PYTHON*`; `python -I` uses isolated mode and ignores `PYTHONPATH`.
- The agent invokes a different Python version or executable.
- A virtualenv, tox, nox, Hatch, Poetry, uv, or build-isolation environment sanitizes variables or has its own stale installation.
- Console scripts use a shebang pointing to another interpreter.
- `pytest`, a plugin, or `conftest.py` rewrites `sys.path`, imports plugins before inserting the repository, or changes the working directory.
- `sitecustomize`, `usercustomize`, `.pth` executable code, or a higher-priority meta-path finder rewrites resolution after startup.
- A long-lived interpreter imported the package before `PYTHONPATH` was set; `sys.modules` then wins. Changing `os.environ` does not update that process’s `sys.path`.
- The repository itself alters `sys.path` or package `__path__`.
- Namespace packages, `pkgutil.extend_path`, or package-specific path extension produce a mixed package: top-level `pkg.__file__` is local while submodules come from another tree.
- Native extensions or generated/build-tree modules still resolve from a stale installation.
- `<workspace>/src` may contain unrelated top-level names, unintentionally shadowing dependencies. “A nonexistent entry costs nothing” does not cover repositories where `src` exists for another purpose.
- The workspace path may be a symlink or bind mount; a textual prefix test could say “own workspace” while `realpath` points elsewhere.
- The agent can explicitly modify `PYTHONPATH`, use `PYTHONHOME`, invoke a package-specific development command, or run from another checkout.
- A run can perform another editable install after the mechanism probe, changing hooks or interpreter state.

Most of these allow clause 1 to pass while real work remains wrong, because clause 1 tests only one bare `python -c` pathway. In particular: sanitized subprocesses, isolated mode, alternate interpreters, virtualenv/tox environments, long-lived processes, pytest/conftest manipulation, early plugin imports, namespace-package mixing, and later environment mutation all produce a spurious pass.

The mechanism test should exercise at least:

1. The exact agent shell/tool execution path.
2. `python`, `python3`, and relevant console/test entry points.
3. A subprocess spawned from that path.
4. The repository’s normal test command.
5. Relevant submodules, checking both `find_spec(...).origin` and `realpath`.
6. The environment immediately before and after the run, not only at initialization.

**Q3 — Pass Condition**

Clause 1 is potentially falsifiable, but underspecified:

- “Inside a run” needs an exact command, interpreter, cwd, lifecycle point, and inherited environment.
- “Resolves to the workspace” needs a realpath-based rule.
- Checking only the top-level package does not exclude mixed submodule resolution.
- “Zero runs may reference another workspace at all” is ambiguous: import origins, command text, tracebacks, or any textual reference?

Clause 2 is not a valid pass criterion. It can pass spuriously because the stochastic agent may:

- Never test the edit.
- Use a different test.
- Solve immediately.
- Fail earlier.
- Reach the same incorrect result without discovering the stale path.

Its absence therefore does not show the fix prevented the behavior. Conversely, clause 2 can fail despite a correct fix if the agent mentions or compares the old path for historical or diagnostic reasons.

At most, clause 2 is a descriptive secondary observation. A defensible test would replay the recorded commands deterministically under old and new environments and assert that the old command imports the stale file while the new command imports the edited file. Organic tool-call behavior should not gate acceptance.

Clause 3 is not a pass condition at all. Consequently the contract can “pass” despite lower solve count, new import shadowing, or other regressions.

**Q4 — Leftover Workspaces**

For a narrowly controlled mechanism experiment, retaining the stale targets temporarily is defensible: it ensures the proposed change is tested against the actual dangerous condition rather than against a conveniently broken pointer.

As an operational policy, however, the reasoning is too convenient. Cleanup does not merely “mask” an import defect. The defect has two causal components:

- Process-global stale import metadata.
- Cross-run workspaces remaining readable.

Removing either prevents silent cross-run execution. Per-run cleanup also reduces cross-run data exposure, accidental writes, disk exhaustion, and non-stationarity. A loud import failure is safer and more diagnosable than silently running another candidate’s code.

The strongest argument against the contract is: **measurement comparability does not justify knowingly retaining a cross-run integrity and isolation violation.** Validate `PYTHONPATH` against a controlled stale fixture, then remove global artifacts and clean each workspace after its run. Better still, isolate imports with per-run virtual environments or single-use execution environments. Defense in depth is appropriate because `PYTHONPATH` is bypassable.

**Q5 — Most Likely Waste**

The most likely waste is that the arm reconfirms the already-known bare-import mechanism but produces no interpretable outcome effect: most of the ten runs either never exercise the vulnerable import path or naturally run from a directory where local imports already win, while the one observed astropy behavior does not recur because its trajectory is stochastic.

With 24 items, no required solve improvement, and clause 2 depending on one stochastic trace, the measurement can easily consume a slot while answering nothing beyond what a deterministic harness test should have answered.
