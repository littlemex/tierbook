**Verdict**

Do not accept W3 or the verification argument as written. The default instance IDs may currently be benign, but `guard_workspace()` is not a deletion-safety boundary. W1 is plausible as an experiment, not established by the evidence.

I could inspect only the supplied packet; the implementation repository, tests, manifests, and `workspace_audit.py` are absent.

**Q1 — `rm -rf` Risks**

Ranked by severity:

1. **Critical — shell injection and glob expansion.**  
   `guard_workspace()` accepts whitespace, `;`, newlines, quotes, `$()`, backticks, `*`, `?`, and brackets, while `build_inner()` inserts the path unquoted at every use (`prompt.md:145`, `prompt.md:149`). For example, `/tmp/w/x; rm -rf /work/returned; #` passes the guard. `/tmp/w/*` can delete every workspace. The same defect affects `mkdir`, `cd`, and both `tar -C` arguments. This makes the claim that the guard protects `rm -rf` false.

2. **Critical — lexical containment is not filesystem containment.**  
   The prefix test at `prompt.md:110` does not inspect the filesystem. If `/tmp/w` is a symlink or bind mount, `/tmp/w/item` can resolve anywhere. A nested template path can similarly traverse an intermediate symlink. A mount inside the workspace can also be recursively erased because `rm` lacks a filesystem-boundary restriction.  
   Important distinction: GNU `rm -rf /tmp/w/item` normally removes a final-component symlink itself rather than traversing it. Intermediate symlinks and mounted directories are the dangerous cases.

3. **Critical — timeouts can defeat the “sequential” premise.**  
   A client or `kubectl exec` timeout does not guarantee that the remote shell and its children have terminated. A timed-out run can continue while the driver starts the next run. With the same deterministic item path, either run can remove, archive, or recreate the other’s workspace.

4. **High — explicit concurrency destroys both runs.**  
   Two same-item runs collide exactly as acknowledged, but the damage is broader than “collision”: one initial or final `rm` can unlink the other run’s live tree; one `tar` can archive the other run’s state; absolute-path operations can silently switch from one generation to another. Open file descriptors and current working directories may continue referring to an unlinked old tree.

5. **High — initialization failures become apparent success.**  
   If initial `rm`, `mkdir`, export, staging, or `cd` fails, the `&&` chain stops before `exec_rc` is assigned. The following semicolon still runs hand-back and cleanup, then `exit ${exec_rc:-0}` returns zero (`prompt.md:149`). A failed removal can therefore archive stale content, delete some of it, and report success without running the agent.

6. **High — hand-back failure is discarded, then evidence is deleted.**  
   If returned-archive creation fails or produces a partial archive, cleanup still runs and the final exit status remains the agent’s status. This can destroy the only complete copy while reporting a successful run. Disk-full, permission, disconnect, and concurrent-writer cases all trigger this class.

7. **High — predictable-path replacement attacks the archive.**  
   An agent or surviving child can rename/delete its pathname and replace `/tmp/w/item` before hand-back. `tar -C` follows a replacement symlink, so it can archive unrelated pod data. Final `rm` will generally remove only that symlink, but the confidentiality and measurement failure has already occurred. A replacement bind mount can also turn cleanup into external deletion.

8. **Medium — signals leave dirty or partial state.**  
   A signal before cleanup leaves the workspace. A signal during `tar` can leave a partial returned archive plus a live workspace. The next same-item run’s initial removal then destroys the recovery copy. Random per-run workspaces preserved such crash evidence.

9. **Medium — background children race with `tar` and cleanup.**  
   The agent command returning does not imply all descendants stopped. They can modify files during archiving, retain deleted inodes, or recreate the deterministic path after cleanup. `tar` can consequently capture an internally inconsistent checkout.

10. **Medium — ordinary filesystem failures are hidden.**  
    Permissions, immutable attributes, read-only mounts, transient I/O errors, or a busy mount can make removal partial or unsuccessful. The initial failure follows the false-success path above; final cleanup failures are ignored because `exit` explicitly returns `exec_rc`.

11. **Low/conditional — staged archive escape.**  
    Absolute names, `..` members, symlink chains, hardlinks, devices, and mounted content need explicit testing against the exact `tar` implementation and archive trust boundary. Modern GNU tar rejects many obvious escapes, but `--no-same-owner` is not a containment option. This risk predates W1 but now interacts with a reusable path.

The safe shape is not “validate then interpolate.” Pass the workspace as a positional shell argument and quote every use as `"$workspace"`, constrain instance IDs to a narrow grammar, verify `/tmp/w` itself is a real owned directory, reject symlinked ancestors, and propagate initialization, archive, and cleanup failures separately.

**Q2 — Unnoticed Breakage**

- **Predictability replaces isolation.** Earlier agents and surviving processes can know future paths and watch, pre-create, or mutate them. Initial cleanup handles static leftovers, not active adversaries or background daemons.
- **External state can now persist by path.** Compiler caches, language servers, test daemons, permission caches, telemetry aggregation, and home-directory caches may key state by absolute checkout path even when the workspace itself is fresh.
- **Nominally sequential runs can overlap.** Timeouts and orphaned children invalidate the stated concurrency assumption without anyone intentionally parallelizing.
- **Downstream identity assumptions remain unproved.** Saying trace ID is the official join key does not show that logs, audit scripts, dashboards, cache keys, permission decisions, or recovery tooling never group by `cwd`.
- **Templates defeat W1.** `template.format(tag=tag)` may omit `{tag}`, normalize several tags to one path, introduce nested paths, or inject shell syntax (`prompt.md:93`). The function does not enforce item-derived uniqueness.
- **Filesystem aliases defeat uniqueness.** Tags containing `/`, `.`, repeated slashes, or equivalent normalized paths can map distinct strings to the same directory. Only `..` is rejected.
- **The path is not generally shorter.** `/tmp/w/matplotlib__matplotlib-26208` is longer than `/tmp/run-opencode-a932f30189`. The categorical claim at `prompt.md:31` is false.
- **Guessability changes agent behavior.** An agent may synthesize a plausible path from the item name instead of copying the authoritative path. That invites dropped repository prefixes, one versus two underscores, altered issue numbers, and project-name normalization.

**Q3 — Premise**

The evidence shows random suffixes were mistranscribed. It does not show entropy caused the errors.

The strongest contrary reason is that the observed defect may be an attention/copying defect. Item IDs are often longer, tokenized into more pieces, punctuation-heavy, and repetitive. The known failing item contains `matplotlib` twice; omission or repetition errors are plausible. “Derivable” is not “reliably emitted.”

The cheapest useful observation is to audit existing transcripts for every occasion where the model emitted the exact instance ID:

- count exact copies;
- count altered issue numbers, separators, and repository names;
- condition on genuine opportunities to emit it;
- inspect the five items that previously mistyped random IDs.

If those traces lack enough opportunities, run several inexpensive preflight calls with the unchanged candidate tuple on the known failing items and require absolute-path tool calls. One stochastic canary is weak; repeated trials are still far cheaper than a scored arm.

**Q4 — Verification**

It is operationally falsifiable but can pass spuriously.

- Zero near misses can mean zero absolute-path attempts, early termination, relative-path use, or errors hidden inside shell strings the auditor does not inspect.
- It measures a raw count without an opportunity denominator. Report exact references, near misses, other wrong paths, and runs with no reference.
- “Near miss” can exclude a materially wrong but edit-distant path.
- One successful `matplotlib` run cannot confirm a stochastic premise; one failure is informative but does not isolate entropy as the cause.
- Clause 2 and the stated falsifier disagree: one names `matplotlib`, the other names `pydata__xarray-4695` (`prompt.md:59`, `prompt.md:69`).
- A textual command-order test does not establish freshness under the actual pod user, filesystem, timeouts, mounts, and surviving processes.
- The plan can pass while archive failures, false-zero exit statuses, timeouts, or solve regressions increase, because none is an acceptance guard.

At minimum, add archive-validity rate, stage/agent/hand-back/cleanup statuses, exact-reference opportunities, refused-call rate, orphan-process checks, and repeated trials for the named item.

**Q5 — Most Likely Regression**

The new “memorable” path is longer and linguistically repetitive for important items, so the model still copies it incorrectly—now by dropping a repository name, underscore, or issue digit rather than a hex character. That directly worsens the intended metric and is more likely than an exotic deletion exploit.

The most dangerous operational regression, separately, is a timed-out or background process contaminating a later same-item run through the now-predictable reused path.
