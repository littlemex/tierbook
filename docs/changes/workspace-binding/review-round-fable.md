# Q1. Claim-by-claim verdicts

**Claim 1 — partly true, partly false, and one part is undecidable.**

- *The five "mangled own id" cases:* The string evidence strongly supports **derivation from the run's own id** — four of five are clean character-drops (`9ef07f4[5]4b` → drop "54", `daf8d8a9[9]3` → drop a "9", `8c042ffb4[0]` → drop the "0", `0ae4d3229d` → its own 6-char suffix). The probability of a random other id sharing a 6–8 character prefix/suffix is negligible. **But note:** `415edc1dee → 415edc17` is *not* a character drop — there is no "7" anywhere in the source id. It shares a 7-char prefix and then confabulates. So the mechanism description ("dropping characters") is wrong for one of the five, and "from memory" (vs. mis-copied from context) is undecided — see Q2.
- *"A run copied its edit into another run's workspace" is **false** as stated.* The `cp` was **refused**. Nothing was copied. The correct statement is "attempted to copy." Moreover, the *direction* of the `cp` is not in evidence — the run may have been trying to copy *from* the stale astropy workspace (e.g., after finding its path embedded in some file), not depositing an edit into it. To settle: read the actual `cp` arguments in the telemetry.
- *How did the run know a real other-run path at all?* This is glossed over and matters. A 10-hex random id from a different sweep cannot be "remembered" — it was either read from somewhere (stale absolute paths baked into the checkout: `.egg-info`, `.pth` files, build artifacts, git config — plausible if checkouts are made by copying a previously-used tree) or it landed by a listing that shouldn't have been possible. Grep the run's transcript for `c4cd6ae898` before the `cp` call; grep the workspace files for it too. Until that's done, the sixth case is **undecided**, and it may indicate a checkout-contamination bug more serious than prompt wording.

**Claim 2 — false as stated (internally inconsistent).**
Under the rule as described — *length differs → mangled; well-formed but absent from manifests → undecided* — `c4cd6ae898` is **10 characters, the correct length**. The stated rule could never have labelled it "mangled"; it would have been "undecided." The mislabel is only possible under a different rule (absence-from-manifest → mangled, no length check), which means either the rule described is not the rule that ran, or the causal story about the manifest overwrite is wrong. Also, the overwrite bug means the manifest set has false negatives, so **"another run" classifications are unsound in general**, not just for this one case. Settle by reading the check's code history and by fixing manifests to be keyed by (sweep, item) and re-running classification.

**Claim 3 — overstated; undecidable on the arithmetic and weak on the causation.**

- Six runs out of **48** is 12.5% of runs. "A quarter of the cohort" is only defensible if the six runs fall on six *distinct items* (6/24). That's not in evidence — list the item ids for the six runs.
- The supporting statistic ("0 of 16 refusal-runs solved") is presented without the base rate. If the overall solve rate is low, zero solves among 16 runs is unremarkable. Compute solves among the 32 non-refusal runs and run a Fisher exact test. Also unverified: whether the two original zero-edit runs are even among the runs showing out-of-workspace paths.
- What *is* fairly supported: the failure mode (model addressing wrong absolute workspace paths) is real and not rare. That the *prompt change* is the right remedy remains a hypothesis.

**Claim 4 — the conclusion is undecidable and the supporting argument is partly false.**

- "*A ten-character random id must be reproduced from memory on every call*" — false. The proposed prompt change puts the absolute path **in context on every call**; the model copies, it doesn't recall. That materially weakens the "prompt fix is weaker" argument.
- The proposed "stronger" fix has a demonstrated hazard the claim ignores: the `c4cd6ae898` incident proves **stale workspaces persist across sweeps**. With deterministic item-named directories, baseline 2's astropy run would get the *same path* as baseline 1's leftover — and the permission system would *allow* everything, because the stale state is inside the "own" workspace. That converts a loud, refused failure into silent contamination. Item-name-plus-fresh-suffix with cleanup would be needed, which is not what's claimed.
- The scoping decision (hold the driver change out so prompt effect ≠ harness effect) is methodologically **sound**.

**Claim 5 — true as a factual account, but with two unresolved problems.**
The false-positive mechanism is plausible (though a naive regex on `((J/m)/s)/kpc2` should also have matched `/m` — worth checking what the regex actually is), and keeping the signal reported while removing it from the verdict is defensible. But: (a) the verdict is now blind to non-workspace-shaped absolute paths in bash strings (`/repo`, `/workspace`, a mangled path missing the prefix); (b) there's an unexplained inconsistency in the setup itself — five of the six findings were in **named path arguments** (`filePath`, grep, glob), which are the *strong* signals, yet the weak regex is credited with the discovery. Either the strong-signal check has a bug (e.g., it only inspects *successful* calls and skipped the refused ones), or the credit is wrong. That must be resolved *before* trusting the new verdict logic, because the same bug would affect the workspace-shaped check.

# Q2. Strongest alternative to "mis-remembered its own id"

**The shortened string was present verbatim in the model's context, and the model copied it faithfully.** Candidate sources: a truncated or line-wrapped path in earlier tool output (permission-refusal error messages that echo paths, `pwd`/git output, a pager or column-limited display eliding characters), or a path embedded in a file in the checkout. In that case the corruption happened *upstream* of the model, and the prompt change would not fix it — fixing the display/echo would.

**Distinguishing observation:** search the full transcript (all tool outputs and prompts) *prior to* each offending call for (i) the exact shortened string and (ii) the full correct id.
- Shortened string appears earlier in *tool output* → copied-from-corrupted-source; not mis-remembering.
- Full id appears in context, shortened string does not → generation-time mangling (mis-copy/mis-recall) — claim 1's story.
- **Neither appears** → the model never saw its absolute path at all, "memory" is impossible, and the ids are pure confabulation seeded by the visible `/tmp/run-opencode-` naming convention (which it could have learned from refusal error text). The `415edc17` case, with its invented "7," already smells like this third bucket.

# Q3. Is the changed-prompt run still worth running?

**Yes.** The experiment's premise no longer rests on the motivating items at all — the mechanism finding (repeated wrong-absolute-path tool calls, all refused) is independent evidence that the model lacks a reliable handle on its workspace path. But be precise about what it can conclude:

- With **one** motivating item and demonstrated run-to-run stochasticity (pytest-8399 flipped between baselines), a single sweep **cannot attribute any solve-count movement to the prompt**. Outcome conclusions need repeated runs or a pre-registered margin larger than observed baseline variance.
- The **mechanism condition is the real test**: does stating the absolute path drive out-of-workspace calls to zero?

**If mechanism passes but solves don't move:** you have learned something specific and valuable — the path-confusion failure mode is real, prompt-fixable, and **was not the binding constraint on solving**. The 0-of-16 refusal/solve correlation was correlation (refusals mark struggling runs) rather than cause (refusals blocking otherwise-good runs). Consequence: stop justifying either the prompt or the driver fix on solve-rate grounds; keep the prompt fix as hygiene; go look at why the runs fail *after* they can address their files.

# Q4. Is the prompt experiment a waste if the driver fix is better?

**Case for "waste":** if item-named directories remove the failure at the source, every unit of compute spent testing the inferior intervention is compute not spent shipping the superior one. Run the driver fix, confirm zero out-of-workspace calls, done.

**Case against:** (1) Claim 4's superiority is *unproven* and its argument is flawed — the prompt fix also puts the path in context, and deterministic naming has a demonstrated hazard (stale workspaces from prior sweeps would silently alias into the "own" workspace, turning refused failures into permitted contamination). (2) The prompt experiment is the *controlled* test: it changes one variable and answers the causal question — does eliminating path confusion move solves? — which the driver fix, bundled with environment changes, cannot cleanly answer. (3) It also validates the rebuilt mechanism check on live data before anything else depends on it. (4) If the prompt alone achieves zero out-of-workspace calls, the driver change becomes unnecessary risk.

**Commit: not a waste.** The prompt run is the cheaper, cleaner causal probe, and the "driver fix is better" claim is currently an untested assertion whose strongest concrete evidence in this very dataset — a stale directory surviving on disk — is an argument *against* deterministic naming as specified. Run the prompt experiment; decide on the driver change (with cleanup semantics added) based on whether the mechanism condition fails.