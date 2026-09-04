"""Where a candidate's weights came from, kept separate from how it behaves.

Two candidates sharing weights are **not** thereby correlated. Measured on one corpus, pairs sharing
weights disagreed on 2.7% to 35.7% of answers and pairs from different model families on 9.4% to 46.3%,
with medians of 31.9% and 31.8% -- identical. Two frontier models of one family agreed more closely
than two serving configurations of one open-weights model. So provenance predicts nothing about
behaviour, and `quorum.joint_failure` measures behaviour from the matrix instead.

This module exists for the three things a measurement cannot give, all of which are facts about
provenance rather than about outcomes:

**A version bump invalidates every pair statistic the candidate is in.** Change the weights and the
joint statistics measured against every other candidate are stale at once, which is the asymmetry that
matters: with candidates from different families one breaks at a time. `stale_pairs` names them so they
can be dropped rather than silently reused.

**An unmeasured pair can still be flagged.** "These two share weights and their disagreement has never
been measured" is worth saying, and it is the only thing available before any measurement exists. It is
a flag and never an estimate: filling the disagreement in from the label would be inventing a number.

**Some risks never appear in a disagreement rate at all.** A blind spot in the weights, a contaminated
training set, a simultaneous update, a shared serving cluster, an adversarial input the whole family is
weak to -- a corpus of a few hundred questions shows none of these, and no amount of measuring changes
that. The honest handling is a note attached to the policy rather than a number folded into its score.

It is called lineage rather than correlation deliberately: "correlation group" reads as a promise about
statistics that the measurements above refuse.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateId:
    """A candidate's identity, structured enough to answer "did this change?".

    `weights` is the model artefact, `weights_version` the revision of it, and `serving` everything
    about how it was run that can move the answer distribution -- decoding parameters, the prompt
    template, an output cap, tools, post-processing. Two candidates differing only in `serving` are the
    same weights behaving differently, which is a case this project measured at up to 35.7% answer
    disagreement, so it is a distinction the identity has to carry rather than flatten.
    """

    weights: str
    weights_version: str
    serving: str

    def __str__(self) -> str:
        """The flat name the rest of the code uses as a dictionary key."""
        return f"{self.weights}@{self.weights_version}/{self.serving}"

    @property
    def lineage(self) -> str:
        """What a version bump changes together. Deliberately excludes `weights_version`."""
        return self.weights


def shares_lineage(a: CandidateId, b: CandidateId) -> bool:
    return a.lineage == b.lineage


def stale_pairs(candidates: list[CandidateId], *, changed: str,
                new_version: str) -> list[tuple[str, str]]:
    """Every pair whose measured joint statistics a weight change invalidates.

    Returns the flat names, so a caller can drop exactly those entries from a cache of pair statistics.
    A candidate on the changed lineage invalidates its pairs with **everything**, including its own
    other serving configurations, because the outcomes those statistics were measured from no longer
    exist.
    """
    affected = [c for c in candidates if c.lineage == changed and c.weights_version != new_version]
    out = []
    for c in affected:
        for other in candidates:
            if other is c or str(other) == str(c):
                continue
            out.append(tuple(sorted((str(c), str(other)))))
    return sorted(set(out))


def single_lineage(members: list[CandidateId]) -> bool:
    """Whether a quorum's members all come from one set of weights.

    A note for a reader, not an input to a score. The measured joint statistics already carry whatever
    correlation is observable; this carries the part that is not -- a common blind spot, a simultaneous
    update, a shared cluster. On the corpus here the *best* policy at one accuracy floor was a
    single-lineage quorum, so this must not be used to exclude anything.
    """
    return len({m.lineage for m in members}) == 1
