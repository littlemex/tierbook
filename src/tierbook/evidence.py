"""Per-item observations, checked on every read, so a paired comparison is drawn from something recoverable.

Before this module, a record carried only the 2x2 that a comparison produced -- `paired_vs_reference`,
hand-computed once and trusted forever. Two failure modes came from exactly that: a comparison that was
never run cannot be recovered from a summary (there is nothing underneath it to re-derive), and a summary
sitting in a JSON file merges like any other JSON file -- a JSONL artifact with per-line observations at
least makes a merge visible as new lines rather than a silently averaged number.

So the unit that ships is the artifact: one line per item, a header naming the suite it was measured against,
and a filename that carries the digest of its own bytes. `load()` re-verifies all of that on every call. A
cache keyed by path is how a mutated artifact keeps passing, so there is deliberately no cache here.

Three things this module refuses to blur, because blurring them is the specific defect this module exists to
close:

  * **a transport failure and a wrong answer are different cells.** `unobserved` (with a closed sub-reason)
    means nothing was learned about correctness; `incorrect` means an attempt completed and the outcome was
    negative. Only `solved` and `incorrect` are "attempted" -- the axis every derivation here uses.
  * **the suite manifest is checked before item ids are intersected.** A reused item id whose content changed
    is invisible to an id-only join, which is the whole reason a manifest digest exists in the first place.
    Checking it after intersecting reads the manifest through the very set it was supposed to gate.
  * **a duplicate item id is refused while the file is still a stream of lines**, not after it has already
    been folded into a dict. A dict silently keeps the last write for a repeated key, so a uniqueness check
    placed after the dict exists can never fire -- the condition it is supposed to catch is exactly the one
    that erased the evidence for it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

SOLVED = "solved"
INCORRECT = "incorrect"
UNOBSERVED = "unobserved"

KNOWN_STATES = frozenset({SOLVED, INCORRECT, UNOBSERVED})

#: The closed set of reasons an item may be unobserved. Closed on purpose: a fifth reason nobody has named
#: yet is a reason to extend this set deliberately, not a reason to accept an arbitrary string here.
UNOBSERVED_REASONS = frozenset({"policy_refusal", "unsupported", "execution_error", "not_selected"})

#: Provenance a header line must carry. Each is read by something downstream: `suite_manifest_digest` is
#: what `paired()` refuses to intersect across, `subject` and `family` identify what this artifact is
#: evidence for, and `trials_per_item` states the single-trial precondition rather than leaving it assumed.
_REQUIRED_HEADER_FIELDS = (
    "suite_manifest_digest", "run_id", "scorer_version", "subject", "family",
    "trials_per_item", "produced_at",
)


class EvidenceError(ValueError):
    """An artifact, or a comparison between two of them, that cannot be trusted as read.

    Named after `ConfigError` deliberately: the same policy applies -- refuse with the condition named in the
    message, rather than repair the input and proceed on a version nobody reviewed.
    """


def digest_of(path: str | Path) -> str:
    """The content digest of a file's exact bytes, as `"sha256:<64 hex>"`.

    Never of a parsed or re-serialised form. A digest of "what the JSON means" would still validate after
    whitespace, key order or a trailing newline changed underneath it, which defeats the point of a digest
    that is supposed to detect that anything changed at all.
    """
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return f"sha256:{h.hexdigest()}"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class Evidence:
    """One artifact, loaded and checked. Everything derived from it is a property, not stored state."""

    path: str
    header: dict
    verdicts: dict  # item_id -> (state, unobserved_reason | None)

    @property
    def suite_manifest_digest(self) -> str:
        return self.header["suite_manifest_digest"]

    @property
    def subject(self) -> str:
        return self.header["subject"]

    @property
    def family(self) -> str:
        return self.header["family"]

    @property
    def attempted(self) -> frozenset:
        """Item ids whose state is `solved` or `incorrect` -- the axis every 2x2 here is computed over."""
        return frozenset(i for i, (state, _) in self.verdicts.items() if state in (SOLVED, INCORRECT))

    @property
    def solved(self) -> frozenset:
        return frozenset(i for i, (state, _) in self.verdicts.items() if state == SOLVED)

    @property
    def cohort(self) -> str:
        """A stable name for the exact (manifest, item set) pair this artifact is evidence about.

        Covers the manifest digest as well as the item ids on purpose: two artifacts sharing every item id
        but disagreeing on the manifest are not the same cohort, because the manifest digest existing at all
        is there to catch a reused id whose content quietly changed. Hashing ids alone would let that
        difference wash out of the very value meant to detect a mismatch like it.
        """
        h = hashlib.sha256()
        h.update(self.suite_manifest_digest.encode())
        for item_id in sorted(self.verdicts):
            h.update(b"\0")
            h.update(item_id.encode())
        return f"evidence:{h.hexdigest()[:16]}"


def load(path: str | Path, *, ledger_root: str | Path) -> Evidence:
    """Read and fully verify one artifact. Every check below runs on every call; nothing here is cached.

    A cache keyed by path is exactly how a mutated artifact keeps passing: the whole value of re-checking on
    every read is that it catches a file that changed *after* it last loaded successfully, which a
    path-keyed cache would hide by construction.
    """
    root = Path(ledger_root)
    # A relative path is relative to the ledger, not to whatever directory the process happens to be in and
    # not to a repository root the ledger may not be inside. The boundary and the base are the same thing on
    # purpose: that is what makes containment mean something rather than being an accident of layout.
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    resolved, resolved_root = p.resolve(), root.resolve()

    if p.is_symlink():
        raise EvidenceError(f"{path}: the artifact is a symlink, which lets a name that carries a content "
                             "digest point at bytes nobody re-checked under that name")
    if not _inside(resolved, resolved_root):
        raise EvidenceError(f"{path}: resolves outside the ledger root {ledger_root}; an evidence path must "
                             "stay inside the ledger it was recorded into")
    if not resolved.is_file():
        raise EvidenceError(f"{path}: no such artifact file")

    digest = digest_of(resolved)
    short = digest.split(":", 1)[1][:16]
    if short not in resolved.name:
        raise EvidenceError(
            f"{path}: filename does not contain {short!r}, the first 16 hex characters of the digest of its "
            f"current bytes ({digest}). The name is supposed to be fixed once the bytes are; a file whose "
            "content changed without a matching rename is exactly what a JSONL merge produces, and this "
            "refuses it rather than trusting a digest that no longer describes what is on disk."
        )

    lines = resolved.read_text().splitlines()
    if not lines:
        raise EvidenceError(f"{path}: empty artifact; no header line")

    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError as e:
        raise EvidenceError(f"{path}: header line is not valid JSON -- {e}") from None
    if not isinstance(header, dict):
        raise EvidenceError(f"{path}: header line must be a JSON object")
    missing = [f for f in _REQUIRED_HEADER_FIELDS if f not in header]
    if missing:
        raise EvidenceError(f"{path}: header is missing {missing}")
    if header.get("trials_per_item") != 1:
        raise EvidenceError(
            f"{path}: trials_per_item is {header.get('trials_per_item')!r}, not 1. Single trial per item is "
            "the precondition every derivation here assumes; a record with repeats needs an aggregation rule "
            "this module does not define, so it refuses rather than guessing one."
        )

    verdicts: dict[str, tuple[str, str | None]] = {}
    for lineno, raw_line in enumerate(lines[1:], start=2):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError as e:
            raise EvidenceError(f"{path}:{lineno}: not valid JSON -- {e}") from None
        if not isinstance(obj, dict) or "item_id" not in obj or "state" not in obj:
            raise EvidenceError(f"{path}:{lineno}: a verdict line needs item_id and state")
        item_id = obj["item_id"]
        state = obj["state"]
        reason = obj.get("unobserved_reason")
        if state in (SOLVED, INCORRECT) and reason is not None:
            # An observed outcome carrying an unobserved_reason is a self-contradiction, and the derivation
            # would read `state` and ignore `unobserved_reason` -- so the file would assert two different
            # things and be counted as one of them silently. Refused rather than resolved, because there is
            # no correct way to pick which half the producer meant.
            raise EvidenceError(
                f"{path}:{lineno}: item_id {item_id!r} has state {state!r}, which is an observed outcome, "
                f"and also unobserved_reason {reason!r}. Those contradict: a sub-reason explains why nothing "
                "was observed, so it belongs only to an unobserved state. Drop one of them -- if the "
                "producer meant the item was not observed, say so in `state`, since that is the field the "
                "derivation reads."
            )
        if not isinstance(item_id, str):
            raise EvidenceError(f"{path}:{lineno}: item_id {item_id!r} is not a string; item_id is opaque "
                                f"but it is always a string, never a bare number a producer's own indexing "
                                "might collide on")

        # Uniqueness is checked HERE, against the set of ids seen so far while still reading lines -- never
        # after the lines have been folded into `verdicts`. A dict silently keeps the last write for a
        # repeated key, so a check placed after `verdicts` is built can never see the duplicate it exists to
        # catch: this is the same defect as a repeated trial with no aggregation rule, so the message says
        # both, because either framing is the same fact about this file.
        if item_id in verdicts:
            raise EvidenceError(
                f"{path}:{lineno}: item_id {item_id!r} appears more than once. This artifact declares "
                "trials_per_item=1 and defines no aggregation across repeats, so a second observation for an "
                "item already seen refuses rather than overwriting or averaging the first."
            )

        if state not in KNOWN_STATES:
            raise EvidenceError(f"{path}:{lineno}: item_id {item_id!r} has state {state!r}, not one of "
                                 f"{sorted(KNOWN_STATES)}")
        if state == UNOBSERVED and reason not in UNOBSERVED_REASONS:
            # Names the field, not just the value: whoever reads this refusal has to go and edit a line, and
            # `unobserved_reason` is what they are looking for.
            raise EvidenceError(f"{path}:{lineno}: item_id {item_id!r} is unobserved but its "
                                f"unobserved_reason is {reason!r}, not one of "
                                f"{sorted(UNOBSERVED_REASONS)}")

        verdicts[item_id] = (state, reason)

    return Evidence(path=str(path), header=header, verdicts=verdicts)


@dataclass(frozen=True)
class Paired:
    both: int
    candidate_only: int
    reference_only: int
    neither: int
    excluded: dict


def two_by_two(
    candidate_attempted: frozenset, candidate_solved: frozenset,
    reference_attempted: frozenset, reference_solved: frozenset,
) -> tuple[int, int, int, int, frozenset]:
    """The four raw counts over the intersection of two attempted sets, and the intersection itself.

    Exists as its own function because this arithmetic already existed once, in
    `tierbook.logs.disagreement_audit`, written directly into that function's return statement rather than
    shared. Two independent copies of "count agreements and disagreements between two attempted sets" drift
    from each other, so there is now exactly one.

    Deliberately opinion-free about what "attempted" or "solved" MEANS for either side -- that is entirely
    the caller's decision, made before calling this. In particular, `disagreement_audit` treats every item
    both sides agreed on as jointly correct without checking it, which is a documented assumption about
    *its* input data; that assumption is applied by building `reference_solved` to already include the
    agreed items, not by this function assuming anything about agreement at all. `paired` (above) makes no
    such assumption: its `solved` sets come from independently observed per-item states.
    """
    intersection = candidate_attempted & reference_attempted
    both = cand_only = ref_only = neither = 0
    for item_id in intersection:
        c, r = item_id in candidate_solved, item_id in reference_solved
        if c and r:
            both += 1
        elif c:
            cand_only += 1
        elif r:
            ref_only += 1
        else:
            neither += 1
    return both, cand_only, ref_only, neither, intersection


def paired(candidate: Evidence, reference: Evidence) -> Paired:
    """The 2x2 over the intersection of what both sides attempted, plus what that intersection left out.

    Order of checks is load-bearing, in this sequence:

      1. (both sides carrying evidence at all is the caller's job -- `Tier.paired` decides that before it
         ever has two `Evidence` objects to hand here.)
      2. the suite manifest digests agree, checked BEFORE any intersection.
      3. intersect the two attempted sets; an empty intersection refuses.
      4. build the 2x2, and report what the intersection excluded.

    Step 2 has to come before step 3 for a structural reason, not a stylistic one: if "the target set" is
    *defined* as the post-intersection key set, a manifest mismatch has nothing left to be a mismatch
    about -- the intersection has already thrown away every item that would have exposed it. So this function
    never asks "which ids are shared" before it has already asked "do these two artifacts even describe the
    same suite," and the manifest check below is written entirely in terms of the two headers, never in terms
    of `attempted` or any other post-intersection quantity.
    """
    for label, side in (("candidate", candidate), ("reference", side_ref := reference)):
        if side is None:
            raise EvidenceError(
                f"the {label} carries no evidence, so no 2x2 can be derived for it. A summary-only record "
                "can still be compared against its own family's reference using its stored 2x2, but it "
                "cannot take part in a derivation -- that is the honest degradation, not a failure."
            )
    del side_ref
    if candidate.family != reference.family:
        # Flagged by both implementers as missing. Two artifacts can share a suite and still be about
        # different traffic, and a 2x2 across families is a comparison of two different questions.
        raise EvidenceError(
            f"candidate evidence is for family {candidate.family!r} and reference evidence for "
            f"{reference.family!r}. A 2x2 across families compares two different questions."
        )
    if candidate.subject == reference.subject:
        raise EvidenceError(
            f"candidate and reference evidence name the same subject {candidate.subject!r}, so this would "
            "compare a tier against itself and report a perfect result by construction."
        )
    if candidate.suite_manifest_digest != reference.suite_manifest_digest:
        raise EvidenceError(
            f"candidate evidence carries suite_manifest_digest {candidate.suite_manifest_digest!r} and "
            f"reference evidence carries {reference.suite_manifest_digest!r}. These do not agree, so "
            "intersecting them by item id would silently compare two different suites under one name -- "
            "the exact failure a manifest digest exists to catch, re-entering through the derivation instead "
            "of through the loader."
        )

    cand_attempted = candidate.attempted
    ref_attempted = reference.attempted
    both, cand_only, ref_only, neither, intersection = two_by_two(
        cand_attempted, candidate.solved, ref_attempted, reference.solved
    )
    if not intersection:
        raise EvidenceError(
            "candidate and reference evidence share no attempted item id, so the intersection is empty and "
            "there is nothing to compute a paired 2x2 over"
        )

    # What the intersection left out. Universe is every id either artifact carries a verdict for; anything
    # in the universe but not in `intersection` was attempted by at most one side -- unobserved, or simply
    # absent, on the other. Reported rather than silently dropped, because intersecting two attempted sets
    # is itself a selection: the items that make it through are the ones both sides happened to attempt, and
    # that can differ systematically from the items either side skipped.
    universe = set(candidate.verdicts) | set(reference.verdicts)
    excluded_ids = universe - intersection
    by_pair: dict[str, int] = {}
    for item_id in excluded_ids:
        c_state = candidate.verdicts.get(item_id, (UNOBSERVED, "not_selected"))[0]
        r_state = reference.verdicts.get(item_id, (UNOBSERVED, "not_selected"))[0]
        key = f"candidate={c_state},reference={r_state}"
        by_pair[key] = by_pair.get(key, 0) + 1

    excluded = {
        "count": len(excluded_ids),
        "by_pair": by_pair,
        "reason": (
            "intersecting two attempted sets can introduce selection bias: an item excluded here was not "
            "attempted -- unobserved, or absent from this artifact -- on at least one side, so the 2x2 above "
            "is drawn from whichever items both sides happened to attempt, not from a fixed population "
            "measured on both."
        ),
    }
    return Paired(both=both, candidate_only=cand_only, reference_only=ref_only, neither=neither,
                  excluded=excluded)
