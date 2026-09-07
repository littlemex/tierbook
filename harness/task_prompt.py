"""The task text handed to an agent, as a function so it can be tested and so a change to it is visible.

It lived inside a heredoc in the sweep, which meant no test could see it and a change to it left no trace in a
diff anybody would read. That mattered once the recordings showed the prompt was the thing at fault.

**What the recordings said.** Two runs of twenty-four returned zero edits in 8 and 12 seconds with exit code 0.
Their first tool calls were `glob {"path":"/tmp"}` and `bash cd /tmp && git clone ...github.com/pytest-dev/pytest`,
both refused by the permission system, followed by a subagent instructed to "Search the xarray repository in /".
Neither run looked inside its own workspace. A run that solved, by contrast, addressed every one of its eighteen
tool calls to an absolute path under its own workspace. The prompt said "in the current directory", and the agents
that failed did not act as though a current directory existed.

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


def fill_workspace(text: str, workspace: str) -> str:
    """Replace the marker with the run's actual workspace.

    Refuses a text that still needs one and was given nothing, because a prompt containing the marker literally
    is worse than the wording it replaced -- and that failure would be invisible in an outcome.
    """
    if WORKSPACE_MARKER not in text:
        return text
    if not workspace:
        raise ValueError(f"the task text contains {WORKSPACE_MARKER} and no workspace was given to fill it")
    return text.replace(WORKSPACE_MARKER, workspace)


def build(repo: str, problem: str, *, workspace: str | None = None, variant: str = "baseline") -> str:
    """The task text for one instance.

    `workspace` is required by any variant that names it, and absent it this raises rather than formatting a
    placeholder into the prompt -- a prompt that says "at {workspace}" literally is worse than the wording it
    replaced.
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown prompt variant {variant!r}; one of {sorted(VARIANTS)}")
    template = VARIANTS[variant]
    if "{workspace}" in template and not workspace:
        raise ValueError(f"variant {variant!r} names the workspace, so it must be given one")
    if not problem.strip():
        raise ValueError("an empty problem statement would ask the agent to fix nothing")
    return template.format(repo=repo, problem=problem, workspace=workspace or "")
