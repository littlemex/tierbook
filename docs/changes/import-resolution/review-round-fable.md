# Adversarial review

## Q1. Is the premise sound?

The core observation — four packages resolve into leftover workspaces via editable-install artifacts — is directly measured and I have no basis to dispute it. But several load-bearing steps are inference, not observation:

**1. "10 of 24 items where `import <pkg>` *inside a run* reads code from a different run."** The measurement was taken on the pod, not inside run environments. The contract's own falsification clause admits this ("the driver already sets something that shadows the finder"), but the headline claim asserts the in-run fact anyway. Only one run (`astropy-14365`) is observed to have actually hit it. The other nine items may never import, or may import through a path that self-corrects (see below). Observation that settles it: dump `sys.path`, `sys.meta_path`, and `<pkg>.__file__` from within a live run's tool-execution path for each of the four packages.

**2. The mechanism as described does not fully explain the observed failure.** The failing calls were `cd <own workspace>/astropy && python -c "from astropy.io.ascii.qdp import ..."`. With `python -c`, cwd is `sys.path[0]`, and setuptools' editable finder is *appended* to `sys.meta_path` — after `PathFinder`. So the run's own checkout, sitting in cwd, should have won. For the import to resolve to `c4cd6ae898`, something extra must be in play: `PYTHONSAFEPATH` set in the image, a finder that prepends rather than appends, or an invocation wrapper. The premise document doesn't name it. This matters because the same unknown could interact with the fix. Observation: `python -c "import sys; print(sys.flags.safe_path); print(sys.meta_path); print(sys.path)"` from inside a run.

**3. How the agent obtained the id `c4cd6ae898`.** The narrative answers the reviewer's question ("how could a run name another run's id?") by asserting the agent read it off the import resolution. But nowhere is it shown that any tool output before call 13 *contained* that path — e.g., a printed `__file__` or a traceback naming the foreign tree. If calls 9 and 11 produced only behavioral output (old return value, no path), the id's provenance is unexplained again. Observation: grep the transcripts of calls 0–12 for the string `c4cd6ae898`.

**4. "The astropy artifact is dated 20260907 and names the *first* baseline's workspace."** Two inferences here: that the file timestamp is trustworthy (a pod with a wrong clock breaks the "dated after the first baseline" ordering), and that the workspace id maps to that sweep (the mapping evidence isn't shown). Observation: the sweep manifest that assigns `c4cd6ae898` to a sweep, plus a clock sanity check.

**5. "The agent diagnosed the situation correctly and acted rationally."** Consistent with the tool calls shown, and I'd accept it — but note it is a reading of intent, and the withdrawal of this observation from the workspace-binding premise rests entirely on that reading plus point 3 above.

## Q2. Is PYTHONPATH the right fix, and where does the measurement fail to generalise?

The demonstrated measurement is **one package, one invocation style, in the pod's default environment**. Ways it fails to carry over:

1. **The agent's tool-execution path may not inherit it.** If the bash tool spawns login shells whose profiles reset `PYTHONPATH`, or the agent harness constructs subprocess environments explicitly, the driver's env var never reaches the interpreter the agent actually runs. This is the single most dangerous case, because clause 1's check could be run through the driver's environment and pass while every agent-invoked Python still uses the finder. *Would produce a spurious pass* if "a run's environment" is reconstructed rather than exercised through the real tool path.

2. **`python -E` / `-I`.** These drop `PYTHONPATH` but *keep* system site-packages processing, so the editable finder still installs and still wins. Any tool that invokes `sys.executable -E` (pip's isolated builds do) reverts to the wrong tree. *Spurious pass:* yes, if the mechanism check uses a plain `python -c`.

3. **Test suites that spawn subprocesses with sanitized environments.** astropy's and django's suites contain subprocess-spawning tests, often with explicit `env=` dicts. Parent-level import resolves correctly; the child resolves via the finder. *Spurious pass:* yes — clause 1 checks top-level imports only.

4. **tox/nox/pre-commit.** tox filters `PYTHONPATH` by default. In a fresh venv the dist-packages finder is also absent, so this fails loudly rather than silently importing the wrong tree — less bad, but the agent still can't test its edit, and the fix didn't help.

5. **`easy-install.pth` may not lose to `PYTHONPATH` at all.** The classic easy-install.pth footer uses the `sys.__egginsert` trick to move its entries to the *front* of `sys.path` — ahead of `PYTHONPATH`. The demonstrated win is against a *finder* (astropy). Flask, the one easy-install.pth package, was not shown measured. If clause 1 genuinely checks all four packages in a live run this gets caught; if the flask check was skipped or done pod-level, it slips through.

6. **`conftest.py` / pytest path manipulation.** pytest's default prepend mode inserts the rootdir at `sys.path[0]` — which means agents that verify via `pytest` from their own repo root were probably importing the *right* tree all along. This cuts both ways: it doesn't break the fix, but it undermines the "10 items affected" incidence claim (Q1, point 1).

7. **A second-order effect the contract doesn't mention:** `PYTHONPATH=<ws>` points at an *unbuilt* source checkout. astropy has C extensions; importing an unbuilt tree raises rather than silently working. Agents on three astropy items may go from "silently wrong behaviour" to "import error," respond by running `pip install -e .` themselves — which repoints the shared process-wide artifact, the exact concurrency fight the contract rejected `pip install -e` to avoid. The measured `PYTHONPATH` win on the pod implies *some* workspace imported successfully — but which one, and was it built? Not shown.

Cases producing a pass with wrong imports persisting: **1, 2, 3**, and **5** if flask isn't checked in-run.

## Q3. Is the pass condition falsifiable, and can it pass spuriously?

Clause 1 is falsifiable and is the right check — *if* "running the import in a run's environment" means through the agent's actual tool path, not through the driver's env. That ambiguity is the spurious-pass hole (Q2 case 1). It also only checks top-level imports, missing cases 2 and 3.

Clause 2 is close to evidence-free. It asserts the *absence* of two behaviours (`ls` comparison, `cp`) in a single stochastic re-run of one item. The unfixed harness would also frequently produce a run that never compares trees — the agent has to notice the discrepancy, sample the right investigation, and find the foreign path. Absence of the behaviour is compatible with fix-working, fix-broken-agent-didn't-notice, and fix-broken-agent-noticed-differently. It can also *false-fail*: 142 workspaces remain in `/tmp`, so an agent can wander into another run's tree for unrelated reasons. Clause 2 should be demoted to "interesting anecdote if it reproduces," not a pass condition.

Clause 3 honestly declines to be a guard. Fine — but then the entire pass/fail weight rests on clause 1, which makes the ambiguity in clause 1's execution path the whole ballgame.

Also: "zero runs may reference another run's workspace at all" is stricter than the mechanism claim. Agents can `ls /tmp` and reference other workspaces without any import being wrong. As written, the clause can fail for reasons the fix doesn't govern.

## Q4. Is refusing to clean `/tmp` correct?

The "cleaning would mask the defect" argument is wrong on its own terms, and the document contradicts itself. It states the leftovers "are what make the stale pointers resolvable **instead of failing loudly**." Failing loudly is the desired behaviour. Deleting the leftovers converts silent wrong-code into an immediate ImportError — that's *surfacing* the defect, not masking it. The legitimate part of the refusal is narrower: don't change disk state under the in-flight arm, and cleaning alone doesn't fix the artifact mechanism (a future editable install re-creates the problem pointing at a *live* tree). Both true; neither justifies "not in scope" without a named owner and date.

Strongest argument against the position: the 142 workspaces are not just an import hazard. They are **prior sweeps' attempts at the same 24 items**, readable by every agent. An agent that explores `/tmp` — and this one demonstrably did — can find another run's completed diff for its own task. That's a contamination channel that affects *solve outcomes*, not just self-verification, and it exists in every arm including the one currently running. Second: 8.9 GB on a shared node is a disk-exhaustion risk that would end an arm mid-flight far more disruptively than a cleanup would. "Belongs to whoever owns the pod's lifecycle," with no owner named, is how it's still there next quarter.

## Q5. Most likely way this wastes a measurement slot

Two candidates; I rank them:

**Most likely:** the defect's real incidence is ~1 run. Agents that verify via `pytest` from the repo root were self-correcting via path prepending (Q2.6); agents that don't import at all were never exposed; the one observed run is the whole effect. The arm then produces "mechanism check passes, outcomes indistinguishable from noise" — which the contract already predicts and already declines to require anything of. In that case the fix is correct hygiene that needed only the mechanism verification, and burning a full 24-item arm on it purchased nothing the pod-level check couldn't. The contract's own honesty ("an increase in the solve count is not required") is close to an admission that the arm may be informationally empty.

**Most dangerous:** clause 1 is verified through the driver's environment rather than the agent's tool-execution chain, `PYTHONPATH` doesn't survive that chain (login-shell profile, explicit subprocess env, `-E`), the arm passes its stated condition, and the wrong-tree imports continue — discovered later by another reviewer reading another tool call, at the cost of the arm *and* the credibility of the pass condition.

The one-line insurance against both: before the arm starts, have a scripted probe run as an *item* — through the real agent tool path — that prints `sys.flags.safe_path`, `sys.path`, `sys.meta_path`, and `__file__` for all four packages, parent and in a spawned subprocess. That settles Q1 points 1–2, Q2 cases 1–3 and 5, and Q3's ambiguity, for the price of one item slot instead of twenty-four.