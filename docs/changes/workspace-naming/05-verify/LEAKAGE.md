# The item-named workspace handed an agent the answer

The confound recorded in `CONTRACT.md` before this arm's numbers were read fired, in exactly the predicted way, and it
is worse than the recorded version: not recall from training data but **retrieval of the gold patch over the network**.

## What happened

`astropy__astropy-14369`, run under `/tmp/w/astropy__astropy-14369`:

    webfetch  https://api.github.com/repos/astropy/astropy/issues/14369      success,  8,585 bytes
    webfetch  https://github.com/astropy/astropy/pull/14369.diff             success, 14,013 bytes
    bash      curl -s https://raw.githubusercontent.com/astropy/astropy/678be259.../cds.py     success

The agent read `14369` off its own workspace path, inferred that it names an upstream astropy pull request, and
downloaded the merged diff. Its own comments say so: *"The PR was merged on 2023-02-10 into v5.0.6 milestone"*, and
then `curl .../pulls/14369/commits` to find the parent commit.

**That run solved.**

## It happened only where the id was in the path

Every run of all four arms, searched for a fetch of an upstream pull request, issue or commit:

| arm | runs | runs fetching an upstream pull/issue/commit | which |
|---|---|---|---|
| baseline 1 | 24 | 1 | `pylint-7277`: `/issues/3636`, `/issues/4161` |
| baseline 2 | 24 | 0 | -- |
| changed prompt | 24 | 0 | -- |
| **item-named** | 19 so far | 2 | `pylint-7277` as above, **and `astropy-14369`: `/issues/14369`, `/pull/14369`** |

The `pylint-7277` fetches are not this: 3636 and 4161 are issue numbers **quoted in its own problem statement**, so
following them is ordinary research and it happened in a baseline too. `astropy-14369` fetching `14369` is the only
run in four arms that looked up **its own instance id**, and it could only do that because the id was in its path.

## What this costs

**The naming arm cannot support a solve number.** The contract already said that, for the weaker reason that a model
might recognise a public id from training data. The actual mechanism is stronger and the conclusion is the same, now
with an observation instead of an argument.

**The naming scheme is unsafe for measurement, not merely confounded.** Any item whose upstream fix is reachable can be
retrieved rather than solved, and the network is reachable -- a run in an earlier arm fetched 5,010 bytes from
raw.githubusercontent.com, which is how the prompt's claim to be offline was found to be false. This is not a caveat
to carry; it is a reason to change the name.

**What it does not cost.** The mechanism metric -- whether a run mistranscribes its own workspace -- is untouched.
Knowing what an id refers to does not help a model copy it, and that metric is the only thing this arm was ever going
to decide.

## The replacement

Low entropy and **not identifying**: `/tmp/w/<repo>-<n>`, where `<repo>` is the repository the task already names and
`<n>` is a small sequence number. `/tmp/w/astropy-2` is shorter than either scheme it replaces, has no ten-character
random span to transcribe, and names no upstream artifact.

It does not make retrieval impossible -- an agent can still search for the issue text, which is what `pylint-7277` did
in a baseline -- and it removes the direct handoff, which is the part this arm created.

## What to do with this arm

Read its mechanism columns and discard its solve count. The one run that retrieved its answer is named, so a reader can
see exactly which number is not a measurement.
