# Phase 5: what the item-named workspace did

Four arms of the same 24 items on the same candidate. **The mechanism the change targets went to zero.** The pass
condition is still not met, for the same over-broad clause the previous arm failed. And the solve count cannot be
used at all, for the reason recorded in `LEAKAGE.md` before this arm's numbers were read.

## The mechanism, with its denominator

| arm | workspace name | runs that named their own workspace | references | wrote it wrong | per reference |
|---|---|---|---|---|---|
| baseline 1 | `/tmp/run-opencode-<10 hex>` | 19/24 | 377 | 1 | 0.27% |
| baseline 2 | same | 18/24 | 323 | 4 | 1.24% |
| prompt states the path | same | 24/24 | 786 | 1 | 0.13% |
| **item-named** | `/tmp/w/<instance-id>` | **24/24** | **778** | **0** | **0%** |

**Same usage -- 24 of 24 runs, 778 references against 786 -- and the errors went from 1 to 0.** Also zero paths naming
another item's workspace, which is the reading the audit had to be taught to distinguish before this arm could be read
at all: under item naming a sibling item is often within two edits of the run's own name.

**Attribution to the name alone is given up, and an earlier draft of this section claimed it.** It said the last two
rows "hold the prompt constant and differ only in the name". They do not. The timestamps:

    arm 3 first run          09:35
    D1 (PYTHONPATH) and D3 (per-run workspace cleanup) merged   11:02
    item naming merged                                          11:07
    arm 4 first run          11:16

So arm 4 carries three changes relative to arm 3, not one. No mechanism connects either of the other two to
transcription -- setting `PYTHONPATH` and removing a workspace afterwards do not help a model copy a string -- but
"no mechanism I can think of" is an argument, and the arms cannot separate them. The same applies to the fifth arm,
which differs from the fourth by the repo-only name **and** four driver guards.

What one error becoming zero supports: the six mistranscriptions across the earlier arms were about the string, not
about the model's care. What it does not support: a rate, or a clean attribution. One event against 778 opportunities
and zero against 778 are not distinguishable at this sample size, and three changes moved together.

## The pass condition: still not met, and for the same clause

Clause 1 requires zero tool calls naming a path outside the run's own workspace. Four remain, and none is a
mistranscription:

- `astropy-14365` ran `ls /tmp` and was refused.
- `astropy-14369` ran `ls /tmp/w` -- it found the workspace root.
- `pylint-4551` wrote scratch files under `/tmp/test_pyreverse` and was refused.
- `pytest-7432` wrote `/tmp/test_skip_location.py`.

These are agents using `/tmp` as scratch space, which the clause counts and which has nothing to do with binding. It
is the same defect in the clause that the previous arm's result recorded, and it is **still not being relaxed**,
because a pass condition rewritten after seeing a result is not a pass condition. The sub-clause that does bear on
this change -- a path that is a near-miss of the run's own workspace -- is zero.

## The solve count: unusable, and that was written down first

`solved 16/23`, against 10, 9 and 13 for the earlier arms. **This number is discarded.** One run fetched the merged
upstream diff for its own task -- 14,013 bytes, successfully -- after reading its instance id off its own workspace
path, and it solved. `LEAKAGE.md` has the full account and the search across all four arms showing it happened only
where the id was in the path.

The confound was recorded at item 12 of 24, with nothing computed, precisely so that this paragraph would not be an
excuse invented afterwards.

## What the change is, after all four arms

The prompt change is worth keeping: it took absolute-path usage from 19 and 18 of 24 runs to 24 of 24, and it removed
every zero-edit run. The naming change removes the transcription failure the prompt change could not, and it is
**unsafe as measured**: the name it uses hands an agent a search key for its own answer.

So the version to ship is neither of the two named schemes but the third, recorded in `LEAKAGE.md` and now
implemented: the repository the prompt already names, and nothing else. `/tmp/w/astropy` is shorter than either, has
no ten-character random span, and names no upstream artifact. A fifth arm on that scheme is the first one whose solve
count will be readable.

## One thing this arm did not decide, said plainly

Whether any of this moves a solve rate. Four arms have now been read and not one of them supports that claim: two are
baselines, the third is confounded by nothing but its own sample size, and the fourth is confounded by answer
retrieval. What they do support is a chain of mechanism results, each with a denominator.
