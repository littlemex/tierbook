# Adversarial review

## Q1. The `rm -rf` lines, ranked

**1. (Highest) The freshness guarantee is unenforced in the only scenario where it fires — and the run exits 0.**
Parse the assembled command:

```
rm -rf WS && mkdir -p WS && export PYTHONPATH=...; tar xf ... -C WS && cd WS && { ...agent... }; give_back; rm -rf WS; exit ${exec_rc:-0}
```

The `export` produced by `python_path_export` ends in `"; "`. That semicolon **terminates the `&&` chain**. So if `rm -rf WS` fails, `mkdir` and `export` are skipped — but `tar xf` runs anyway. When does `rm -rf` on an existing tree fail? When a previous run left an unremovable tree (e.g. the agent `chmod`ed a directory unwritable, which agents do constantly when testing permission-related bugs). In exactly that case: WS still exists, `tar x` extracts **over the stale tree** (the precise contamination W2 exists to prevent), `cd` succeeds, the agent runs without `PYTHONPATH` set, produces a returned tar, and the run exits with the agent's status. Silent, scored, contaminated. The clause the contract calls "the clause that makes W1 safe" is a no-op in its only triggering condition. Corollary: if *staging* fails (tar error, WS missing), `exec_rc` is never set and the command **exits 0** — the docstring's claim that "the status the driver sees is the agent's own" is false on every failure path before the agent starts.

**2. The guard is lexical; the filesystem is not.** `guard_workspace` checks a string. It does not `lstat` anything. On a **shared, long-lived pod where every run executes arbitrary agent-chosen code as the same user**, a prior run can leave `/tmp/w` (or `/tmp/w/<item>`) as a **symlink** to `/work/returned` or anywhere else. `rm -rf` follows symlinks in *path components* (only the final component is safe, and only because the guard rstrips trailing slashes — good). The next run's `rm -rf /tmp/w/<item>` then deletes outside the root the guard swore to protect. Random names had this exposure too, but a deterministic, guessable name makes it targetable in advance. The guard needs an `O_NOFOLLOW`-style check on `/tmp/w` and the leaf, or the driver should create `/tmp/w` with known provenance.

**3. Unquoted interpolation of a value the guard does not charset-check.** `workspace_for(tag)` accepts any non-empty tag; `"/tmp/w/foo; rm -rf /work"` passes every guard condition (absolute, under root, non-empty tail, no `..`) and is then interpolated **unquoted** into the shell string — command injection. Same for spaces (`rm -rf /tmp/w/foo bar` deletes `bar` in the pod's CWD) and globs. SWE-bench ids are tame, so this is latent, but the guard's entire justification is "a function with its own tests rather than a condition in a shell string" — and it fails to model the shell context it feeds. Either quote `ws` at interpolation or restrict tag to `[A-Za-z0-9._-]+`.

**4. Deterministic names + orphaned processes = de facto concurrency.** "Runs are sequential" is true of the driver, not the pod. A timed-out `kubectl exec` does not reliably kill the remote process tree. An orphaned agent from a previous run of the *same item* can still be running when the next run's `rm -rf` yanks its workspace away — or keep writing into the freshly staged tree *after* the freshness point. Random names made orphans harmless; item names make them a contamination channel. The contract only discusses collisions under future parallelisation; retries and timeouts create them today.

**5. The sweep destroys evidence unconditionally.** `give_back` and the sweep are joined by `;`. If `tar cf` to `/work/returned` fails or truncates, `rm -rf WS` still runs, the exit code is the agent's (likely 0), and the only copy of the run's output is gone. The scorer then records a failure attributable to the model that was actually infra.

**6. Fails-to-delete accumulation.** If `sh` is killed, no sweep runs. With item naming this is self-healing *only for items that are re-run*; a partial arm leaves up to 24 trees on a shared pod's `/tmp` indefinitely. Low severity, but the old scheme at least made leftovers identifiable per run.

## Q2. What W1 breaks that the contract has not noticed

**The workspace name now leaks the benchmark instance id into every tool call, `ls`, traceback, and `pwd`.** Look at the staging path in the real command: `/work/testbeds/x/staged.tar`. Someone anonymised the testbed directory to `x` — plausibly deliberately, to avoid telling the model which public benchmark item it is solving. W1 undoes that: `matplotlib__matplotlib-26208` is a public SWE-bench id whose issue, PR, and gold patch are plausibly in training data. Stamping it on every path is a memorisation/contamination channel that can move solve rates for reasons that have nothing to do with refused permission calls — and the "no regression" comparison against three arms that did *not* leak the id becomes confounded in the direction the change's author would like.

**The audit's near-miss detector is calibrated for the wrong distribution.** With random hex, any string edit-close to the workspace name was almost surely a mistranscription. With item names, the id appears legitimately hundreds of times per transcript (repo paths, git output, the prompt echo, error messages), and edit-close strings are now *other real strings* (issue numbers of sibling items, repo-internal paths). `workspace_audit.py` will have a different false-positive and false-negative profile per naming scheme, so "0 vs 1-and-4" is not one metric measured twice. The contract does not mention recalibrating the audit.

**A mistranscription now points somewhere real.** `pydata__xarray-4695` mistyped as `-4965` was, under random naming, a path to nothing. Under item naming it is another item's workspace, possibly with a leftover tree (see Q1.6), and the contract itself notes shell strings bypass the permission system. Frequency of the error may drop; severity per error rises from "refused" to "silently read/wrote another item's tree."

**The agent can act on the path before being told it.** A model that has seen SWE-bench harnesses may guess `/tmp/w/<id>` or `/testbed` conventions and touch the workspace tree, or sibling item trees, from priors rather than from the prompt — behaviour no recorded arm could exhibit.

**The claimed-safe recovery path deserves suspicion.** The contract asserts `workspace_audit.py` reconstructs a workspace from the returned tar's name and "still works." The tar name carries the session id; the workspace now carries the item id; the mapping between them lives only in manifests. "Still works" is asserted, not demonstrated, and it is exactly the kind of implicit workspace-identifies-run assumption the question is about.

## Q3. Is the premise sound?

Partially. The mechanism claim — natural tokens copy better than 10 hex chars — is plausible: item ids tokenize into familiar subwords, appear repeatedly in context, and can be *reconstructed* rather than copied.

**The strongest reason it will not work:** the fragile part of `matplotlib__matplotlib-26208` is `26208` — an arbitrary digit string with exactly the memoryless, per-character fragility of the hex it replaces. All six recorded errors were character drops/substitutions inside an arbitrary string; the change shortens that arbitrary core from 10 hex chars to ~5 digits, it does not eliminate it. If the failure is decode-level corruption of high-entropy spans (rather than "the string was too long"), the error moves into the digits at a reduced but nonzero rate — and now `-26028` may be a real sibling path (Q2).

**Cheap observation, no arm needed:** the three recorded arms already contain thousands of reproductions of item-derived digit strings — issue numbers in file paths, test names, git output. Grep the existing transcripts and count mangled digit sequences of length 4–5 versus mangled hex spans, in the same runs by the same runs. If digits are mangled at a comparable per-character rate, the premise is wrong and it cost one grep. Cheaper still than an arm: sample a few dozen completions offline with the new prompt and count reproductions of `/tmp/w/<id>`.

## Q4. The verification plan

Falsifiable in form, weak in power, and passable spuriously:

- **Clause 1** compares 0 against baselines of ~1, 4, 1 events per arm. Under a Poisson rate of ~2/arm, an unchanged system produces zero events roughly one arm in seven. A single passing arm is suggestive, not conclusive — and it is measured by an audit tool whose detection profile the naming change itself altered (Q2). The clause can pass because the detector went blind, not because transcription improved.
- **Clause 2** is an n=1 Bernoulli observation on a stochastic item. Three-for-three prior failures make one clean run meaningful-ish, but the item may simply make fewer tool calls this time (it has failed *differently* each arm), and "did not mistranscribe" on a short trajectory is nearly vacuous. It also cannot fail informatively: one mistranscription on a stochastic item refutes nothing about the rate.
- **Clause 3** tests the wrong branch. Planting a stray file exercises the case where `rm -rf` *succeeds*. The freshness hazard is the case where `rm -rf` *fails* (Q1.1), and in that case the assembled command demonstrably proceeds contaminated and exits 0. The test as specified passes while the guarantee is broken.
- **The falsification criterion at the bottom is good** — it is the one genuinely crisp prediction — but note it, too, is a per-run event on stochastic trajectories; absence in one arm is weak evidence of the premise, presence is strong evidence against. The asymmetry should be stated.

## Q5. The single most likely way this makes the measurement worse

**The headline metric becomes incomparable across arms while looking better.** The change swaps the naming scheme *and* keeps the same audit tool, whose near-miss detection was implicitly calibrated to random hex, where any edit-close string was damning. Under item naming, the id saturates every transcript legitimately, mistranscriptions can collide with real sibling strings, and residual errors concentrate in the digit suffix where a detector tuned to hex-shaped anomalies is weakest. The most probable outcome is an arm that reports "zero near-misses" — clause 1 passes, the change ships — where some fraction of that zero is detector blindness, and the one number the whole contract turns on ("1, with baselines 1 and 4, versus 0") was never the same measurement twice.

Runner-up, because it is live right now: the `"; "` in `python_path_export` means the fourth arm currently running can execute runs on stale or unstaged trees and exit 0 (Q1.1). Any solve-rate movement in that arm is uninterpretable until the assembled commands of every run are checked for a failed leading `rm`/`tar`. That check should happen before the arm's numbers are read, not after.