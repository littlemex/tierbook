# Phase 1: the premise, checked on the recordings

The first version of this document asserted a premise from two runs and declared the harness sound without
checking the one harness fact the premise rested on. A review said so. Redone.

## What was measured

All 24 runs of the self-hosted baseline, from the telemetry's tool spans.

| | |
|---|---|
| runs with at least one refused tool call | **6 of 24** |
| of those, states | 4 incorrect, 2 unobserved (zero edits) |
| runs that solved and had a refusal | **0 of 10** |
| runs naming a path outside their workspace | 4 |

So refusal is not a curiosity of two failures: no run that solved ever had one.

## Three hypotheses, two refuted by measurement

**The driver launches the agent in the wrong directory.** Refused. `agent_drive.py` builds one shell command --
`mkdir -p {ws} && ... cd {ws} && exec "$@"` -- because `kubectl exec` has no working-directory option. The cwd is
the workspace.

**The permission system rejects the workspace itself.** Refused, and this one looked true for a while.
`matplotlib__matplotlib-26208` had `glob {"pattern":"**/*.py","path":"/tmp/run-opencode-8c042ffb4"}` rejected, and
that reads as its own workspace. It is not: the run returned `opencode-8c042ffb40.tar`, so its workspace was
`/tmp/run-opencode-8c042ffb40` -- **the agent truncated its own path by one character**. Of five glob calls with an
explicit path that were allowed, four named a workspace root; the five rejected named `/`, `/tmp`, or that typo.
The permission system was right every time.

**The agent does not reliably know its own workspace path.** Supported, and the truncation is the sharpest
evidence for it: an agent that had been *told* the path would not lose a character off the end of it. The others
are of a piece -- `glob path:"/"`, `grep path:"/"`, `read filePath:"/"`, a subagent told to "Search the xarray
repository in /", `grep path:"/src/matplotlib"` (a directory that does not exist here), and
`bash cd /tmp && git clone https://github.com/pytest-dev/pytest.git`.

## One cause that is not about paths at all

`pylint-dev__pylint-4551`: `todowrite` was called without the `priority` key its schema requires, and the tool
refused with a schema error. That is a tool-contract mismatch, not a workspace question, and nothing in this
change addresses it. Recorded here so it is not silently folded into a result about prompts.

## A defect found on the way, unrelated to the premise

The driver writes its manifest to `runs-{instance}.json`, so a second sweep over the same instances overwrites the
first. The workspace-to-trace mapping for the baseline was gone by the time this analysis wanted it, and the
workspace had to be recovered from the returned tar's filename. The manifest path needs the run group in it.
