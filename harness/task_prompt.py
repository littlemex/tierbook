"""The task text handed to an agent, as a function so it can be tested and so a change to it is visible.

It lived inside a heredoc in the sweep, which meant no test could see it and a change to it left no trace in a
diff anybody would read. That mattered once the recordings made the prompt a plausible cause.

**What the recordings said**, and what they did not. Two runs of twenty-four returned zero edits in 8 and 12
seconds with exit code 0. One, on `pydata__xarray-4695`, opened with `glob {"path":"/tmp"}`, was refused, and went
on to instruct a subagent to "Search the xarray repository in /": that run never addressed its own workspace. The
other, on `pytest-dev__pytest-8399`, did -- its first `glob` was workspace-relative and succeeded -- and then ran
`cd /tmp && git clone ...github.com/pytest-dev/pytest` and stopped when that was refused. Those are two different
failures, and an earlier version of this paragraph said neither run looked inside its workspace, which the
recording contradicts. `pytest-dev__pytest-8399` later solved on a replicate of the same prompt, so it is
stochastic and is not evidence for anything here.

**What is much stronger evidence, found later by the mechanism check.** Six runs across two baselines addressed a
path that was their own workspace with characters missing -- `0ae4d3229d` written as `d3229d`, `415edc1dee` as
`415edc17`, `9ef07f454b` as `9ef07f4b`, `daf8d8a993` as `daf8d8a93`, `8c042ffb40` as `8c042ffb4`. Every one was
refused and none of those runs solved. A quarter of the cohort could not reproduce a ten-character random
directory name it was never told. That is what this prompt addresses by stating it.

It also shows what would address it better: a workspace named after the item, so there is nothing to reproduce.
That is a driver change, held out of this one so that a prompt effect could be told from a harness effect.

So the workspace is stated as an absolute path, and the checkout is stated to be complete at the revision in
question, so there is nothing to fetch.

**Two sentences that were drafted and cut**, both because they claimed more than was true or licensed. One said
"there is no network access". A phase-4 review asked whether that was so, and it is not: a run that solved fetched
5,010 bytes from `raw.githubusercontent.com` successfully. The `git clone` in the other failure was stopped by the
permission system, not by the absence of a network, and telling a model something it can disprove in one call
invites it to discount the rest. The other said paths outside the workspace "are refused" -- a statement about
enforcement, which is the text-channel twin of the harness lever this change deliberately excluded so that the
prompt could be told apart from it.

**What deliberately did not change**, because both are load-bearing for the oracle rather than for the agent: the
instruction not to write tests, since the instance's own test patch is applied after the diff is taken; and the
instruction to stop when done, since a run that does not stop is a timeout rather than an answer.
"""
from __future__ import annotations

#: The wording before the recordings were read. Kept so the change is legible and so a baseline can be reproduced
#: exactly rather than approximately.
BASELINE = """You are working in a checkout of the {repo} repository in the current directory.
Fix the issue described below by editing the source files. Do not write any tests.
When you are done, stop.

--- issue ---
{problem}"""

WORKSPACE_BOUND = """You are working in a checkout of the {repo} repository at {workspace}.
That directory is a complete checkout at the revision this task is about: everything you need to read and change
is already there, and there is no need to fetch or clone anything.
Fix the issue described below by editing the source files. Do not write any tests.
When you are done, stop.

--- issue ---
{problem}"""

VARIANTS = {"baseline": BASELINE, "workspace-bound": WORKSPACE_BOUND}

#: What a caller writes when the workspace is not known yet. The sweep builds the task text before a run exists,
#: and the workspace is a per-session directory the driver creates, so the driver substitutes this at run time.
#: A marker rather than a format field, because the text passes through a file and a stray brace in a problem
#: statement would otherwise be read as one.
WORKSPACE_MARKER = "<<WORKSPACE>>"


def _require_absolute(workspace: str) -> None:
    """C1 says an absolute path, and `.` or `../repo` would satisfy every other check here while telling the agent
    exactly the thing the change exists to stop telling it."""
    if not workspace.startswith("/"):
        raise ValueError(f"the workspace must be an absolute path, and {workspace!r} is not; a relative one is "
                         f"the wording this change replaces")


def fill_workspace(text: str, workspace: str) -> str:
    """Replace the marker with the run's actual workspace.

    Refuses a text that still needs one and was given nothing, because a prompt containing the marker literally
    is worse than the wording it replaced -- and that failure would be invisible in an outcome.
    """
    if WORKSPACE_MARKER not in text:
        return text
    if not workspace:
        raise ValueError(f"the task text contains {WORKSPACE_MARKER} and no workspace was given to fill it")
    _require_absolute(workspace)
    return text.replace(WORKSPACE_MARKER, workspace)


def check_deliverable(text: str) -> str:
    """The last thing between a prompt and an agent. Called by the driver rather than trusted to have happened.

    A text that still contains the marker means the substitution was skipped somewhere upstream, and the run would
    proceed, produce an outcome, and count in a comparison -- with the one sentence the change is about reading
    `at <<WORKSPACE>>`. Nothing downstream distinguishes that from the change working.
    """
    if WORKSPACE_MARKER in text:
        raise ValueError(f"the prompt still contains {WORKSPACE_MARKER}; fill_workspace() did not run, and shipping "
                         f"this would measure a prompt naming a directory that does not exist")
    return text


def build(repo: str, problem: str, *, workspace: str | None = None, variant: str = "baseline") -> str:
    """The task text for one instance.

    `workspace` is required by any variant that names it, and absent it this raises rather than formatting a
    placeholder into the prompt -- a prompt that says "at {workspace}" literally is worse than the wording it
    replaced.
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown prompt variant {variant!r}; one of {sorted(VARIANTS)}")
    template = VARIANTS[variant]
    if "{workspace}" in template:
        if not workspace:
            raise ValueError(f"variant {variant!r} names the workspace, so it must be given one")
        if workspace != WORKSPACE_MARKER:
            _require_absolute(workspace)
    if not problem.strip():
        raise ValueError("an empty problem statement would ask the agent to fix nothing")
    return template.format(repo=repo, problem=problem, workspace=workspace or "")
