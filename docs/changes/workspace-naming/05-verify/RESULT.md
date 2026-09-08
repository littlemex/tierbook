# Phase 5: what the item-named workspace did

Four arms of the same 24 items on the same candidate. The pass condition is not met, for the same over-broad clause the
previous arm failed. The solve count cannot be used at all, for the reason recorded in `LEAKAGE.md` before this arm's
numbers were read. And **the mechanism result is consistent with the change working and cannot establish it** -- an
earlier version of this line said "the mechanism went to zero" as a finding, which the table below refutes.

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

**The two baselines settle what this table can support.** They are identical in every respect and differ by 1 error
against 4. So the between-arm movement under no change at all is larger than the 1 to 0 being examined, and no reading
of the last two rows survives the first two. A review put it plainly and it is right: the honest finding is *consistent
with* the transcription hypothesis at a sample size that cannot distinguish it from no effect.

What the design argument still supports, stated as an argument rather than a measurement: a name with no
ten-character random span has nothing to mistranscribe. What the data supports: not a rate, and not a clean
attribution -- three changes moved together.

**Two things about the instrument, both of which cut.** All four arms were re-audited under the final classifier, so
the columns are one instrument's output rather than two; that was done after each change to it and is worth saying
because the alternative would make the comparison meaningless. But the classifier is *asymmetrically sensitive*: under
random hex, catching a corrupted span means fuzzy-matching a random string, so the baselines' 1 and 4 are plausibly
undercounts; under item naming, a near-miss lands near a known finite list of ids and the classifier was upgraded to
look for exactly that. So the item arm was measured by a more sensitive instrument and still found zero, which
strengthens the zero, while the baselines were measured by a less sensitive one, which weakens the 1 and the 4. Both
directions are stated because using only one would be picking.

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

So the version to ship is neither of the two named schemes but a third: the repository the prompt already names, and
nothing else. `/tmp/w/astropy` is shorter than either, has no ten-character random span, and names no upstream
artifact. `LEAKAGE.md` proposed it with a sequence number and what shipped has none -- see there for why the sequence
could not be made to work, and for the `.git` channel a review expected and the tars do not have.

A fifth arm on that scheme is the first whose solve count will be readable **on the channel this arm created**. The
channel that predates all five arms is still open: the problem statement is itself a search key, which is how
`pylint-7277` found its quoted issues in a baseline, and the network is reachable. Renaming a directory does not close
that, and the honest phrasing is that this removes the channel this arm created rather than that it makes the arm
clean.

## One thing this arm did not decide, said plainly

Whether any of this moves a solve rate. Four arms have now been read and not one of them supports that claim: two are
baselines, the third is confounded by nothing but its own sample size, and the fourth is confounded by answer
retrieval. What they do support is a chain of mechanism results, each with a denominator.
