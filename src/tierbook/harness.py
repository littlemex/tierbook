"""What surrounds the model, identified so two runs can be told apart, and honest about what it cannot see.

**Why this matters more than the routing, on this project's own numbers.** Same box, same 1,187 items, and only the
instruction changed:

| condition | accuracy |
|---|---|
| terse (`Answer with the option letter only. Do not explain.`) | **0.6243** |
| explaining | **0.7447** |
| per-item agreement between them | **0.7346** -- one item in four flips |

**+12.04 points from one sentence.** Against that, the best cost saving routing between models produced here was 7.9%,
and it fell to **1.0%** once the comparison was restricted to the same items. So the thing around the model moved
accuracy by twelve points while the choice of model moved cost by one percent, and only one of the two had a name in
the record.

**What a harness is, concretely.** The instruction, the tools offered and their schemas, the loop that calls them, how
many turns it may take, what it retries, how the answer is finally read. Change any of those and the same model on the
same items is a different measurement.

## The part that needed careful thought: where each fact comes from

Three ways a fact about the harness can reach us, and they are **not interchangeable**:

* **in the request** -- we hold the bytes. It *is* what was sent: verifiable and contemporaneous. This is the only mode
  that may key an identity.
* **pulled by us** -- we fetched it. Verifiable and **not contemporaneous**: we read at one moment, the request ran at
  another, and whatever changed in between is invisible. A pulled fact therefore carries its lag, and a lag nobody
  bounded cannot support a per-request claim.
* **pushed by the owner** -- they told us. Not checkable here, and **a label they control can stay fixed while the thing
  underneath it changes** -- which is exactly the failure a prompt "version" invites.

And a fourth, which is the finding rather than an option: **not observable**. A tool's *schema* is in the request; its
*implementation* is not. Somebody can change what a tool does, leave its schema alone, and nothing in the request
differs. Recording that as unobservable is the only honest move -- the alternative is a record that looks complete and
silently groups two different harnesses under one identity.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from tierbook.evidence import (ABSENCE_REASONS, COLLECTION_STATUS, HARNESS_SOURCING, IDENTIFYING_SOURCING,
                              EvidenceError)

#: The parts of a harness this package can name. Closed, because a part nobody named is a part that changes without the
#: identity changing, and that is the whole defect.
HARNESS_PARTS = (
    "instruction",          # the system prompt / the instruction text
    "tool_schemas",         # what tools were offered, and their declared shapes
    "tool_behaviour",       # what those tools actually do
    "loop",                 # the scaffold: how calls are sequenced, what ends the run
    "turn_budget",          # how many turns it may take
    "retry_policy",         # what it retries and how often
    "readout",              # how the final answer is taken out of the reply
    "decoding",             # temperature, top-p, and whether output is grammar-constrained
)

#: For each part, the BEST mode that can reach it, as a total classification. Total on purpose: adding a part without
#: deciding how it is observed breaks a test rather than defaulting the new part to observable.
#:
#: `tool_behaviour` is the entry that forced this table to exist. Its schema is in the request and its behaviour is not,
#: so a change to what a tool does behind an unchanged schema is invisible from the request -- and a record that did not
#: say so would group two different harnesses under one identity.
BEST_AVAILABLE_SOURCING = {
    "instruction": "in_the_request",
    "tool_schemas": "in_the_request",
    "tool_behaviour": "not_observable",
    "loop": "pushed_by_owner",
    "turn_budget": "pushed_by_owner",
    "retry_policy": "pushed_by_owner",
    "readout": "in_the_request",
    "decoding": "in_the_request",
}


class Unidentified(EvidenceError):
    """A harness fact was recorded in a way that lets two different harnesses wear one identity.

    Raised at construction, because the whole point is to make the grouping wrong *before* anything is measured under
    it. By the time two runs have been compared, the fact that they were different harnesses is not recoverable from
    the numbers.
    """


@dataclass(frozen=True)
class Part:
    """One component of the harness, with how we know it and what that permits.

    `digest` is over bytes and is **required for anything identifying**. `label` is for the reader and is explicitly not
    the key: a version string the owner controls can stay `v3` while the text under it changes, which is the failure
    this separation exists to prevent -- and the same failure this project already recorded for a model name and for a
    prompt condition called "terse".
    """

    kind: str
    sourcing: str
    label: str = ""
    digest: str = ""
    #: How long before the request this fact was read, for a pulled fact. Required there and refused elsewhere: a fetched
    #: copy describes a different moment than the request, and a lag nobody wrote down is a lag nobody can bound.
    read_lag_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in HARNESS_PARTS:
            raise Unidentified(
                f"{self.kind!r} is not one of {HARNESS_PARTS}. A part nobody named is a part that can change without "
                f"the identity changing, which is the defect this vocabulary exists to close")
        if self.sourcing not in HARNESS_SOURCING:
            raise Unidentified(f"{self.sourcing!r} is not one of {HARNESS_SOURCING}")
        best = BEST_AVAILABLE_SOURCING[self.kind]
        if self.sourcing == "in_the_request" and best != "in_the_request":
            raise Unidentified(
                f"{self.kind!r} is claimed as being in the request, and the best any mode can do for it is {best!r}. "
                f"For `tool_behaviour` that is not a limitation of this implementation: a tool's schema is in the "
                f"request and its behaviour is not, so a change behind an unchanged schema is invisible from the bytes "
                f"we hold")
        if self.sourcing == "not_observable":
            if self.digest:
                raise Unidentified(
                    f"{self.kind!r} is recorded as not observable and carries a digest, so something was hashed. If "
                    f"bytes exist, name the mode that produced them; if they do not, the digest is of something else")
        elif not self.digest:
            raise Unidentified(
                f"{self.kind!r} has no digest. A part identified by a label alone is a part whose label can stay fixed "
                f"while its content moves -- this project has that failure recorded twice, for a model name and for a "
                f"prompt condition both called the same thing while differing underneath")
        if self.sourcing == "pulled_by_us" and self.read_lag_seconds is None:
            raise Unidentified(
                f"{self.kind!r} was pulled and carries no lag. We read at one moment and the request ran at another; a "
                f"lag nobody wrote down is a lag nobody can bound, and everything that changed inside it is invisible")
        if self.sourcing != "pulled_by_us" and self.read_lag_seconds is not None:
            raise Unidentified(
                f"{self.kind!r} is {self.sourcing!r} and carries a read lag, which only a pulled fact has: bytes in the "
                f"request have no lag by definition, and a pushed claim's timing is the owner's word rather than a "
                f"measurement")
        if self.read_lag_seconds is not None and self.read_lag_seconds < 0:
            raise Unidentified(f"read_lag_seconds={self.read_lag_seconds!r} would mean it was read after the request it "
                               f"describes")

    @property
    def identifying(self) -> bool:
        """Whether this part may contribute to the harness's identity."""
        return self.sourcing in IDENTIFYING_SOURCING

    def __str__(self) -> str:
        who = {"in_the_request": "in the request", "pulled_by_us": "pulled", "pushed_by_owner": "owner says",
               "not_observable": "NOT OBSERVABLE"}[self.sourcing]
        head = f"{self.kind} ({who}"
        if self.read_lag_seconds is not None:
            head += f", {self.read_lag_seconds:g}s before the request"
        head += ")"
        return head + (f" {self.label}" if self.label else "") + (f" {self.digest[:8]}" if self.digest else "")


@dataclass(frozen=True)
class Harness:
    """Everything around the model for one run, and an identity derived from the parts we actually hold.

    `identity` is a property, not a field. A supplied identity is one somebody can keep across a change to the parts,
    and then two harnesses wear one name -- which is the same defect as a supplied snapshot id, a supplied total, or a
    prompt condition identified by the word "terse".

    Only the parts we hold bytes for enter the identity. A pushed loop description and an unobservable tool behaviour
    are recorded and **do not** change the name, because a name that moved when the owner edited a sentence about
    themselves would not group anything.
    """

    parts: tuple[Part, ...]

    def __post_init__(self) -> None:
        if not self.parts:
            raise Unidentified("a harness with no parts is not a harness; it is the absence of a record about one")
        kinds = [p.kind for p in self.parts]
        if len(set(kinds)) != len(kinds):
            raise Unidentified(f"two parts share a kind in {sorted(kinds)}, so nothing says which one applied")
        if not any(p.identifying for p in self.parts):
            raise Unidentified(
                "no part of this harness is identified by bytes we hold, so its identity would be constant across every "
                "possible harness. At minimum the instruction is in the request; a record without it is a record of "
                "somebody's description of a run rather than of the run")

    @property
    def identity(self) -> str:
        """Derived from the identifying parts, in a fixed order, so it cannot be kept across a change to them."""
        h = hashlib.sha256()
        for p in sorted((p for p in self.parts if p.identifying), key=lambda p: p.kind):
            h.update(f"{p.kind}={p.digest};".encode())
        return h.hexdigest()[:24]

    @property
    def unobserved(self) -> tuple[str, ...]:
        """Which parts nothing here can check. Reported, because a record that hid them would look complete."""
        return tuple(p.kind for p in self.parts if p.sourcing in ("pushed_by_owner", "not_observable"))

    @property
    def missing(self) -> tuple[str, ...]:
        """Which parts of a harness this record says nothing at all about."""
        return tuple(k for k in HARNESS_PARTS if k not in {p.kind for p in self.parts})

    def comparable_with(self, other: Harness) -> bool:
        """Whether two runs measured what is otherwise the same thing.

        Only the identifying parts decide it, and that is deliberate: a difference in what the owner *says* about their
        loop is not evidence that the loop differed, and treating it as such would refuse comparisons that are fine
        while still missing the ones that are not.
        """
        return self.identity == other.identity

    def __str__(self) -> str:
        return (f"harness {self.identity} from {len(self.parts)} part(s); "
                f"unobserved {list(self.unobserved) or 'none'}; unrecorded {list(self.missing) or 'none'}")


def refuse_incomparable(a: Harness, b: Harness) -> None:
    """Refuse a comparison across two harnesses, naming what differs.

    The same shape as the refusal already in place for a prompt condition, one level up: the instruction is one part of
    a harness, and the measured 12-point swing came from changing it. A comparison across harnesses attributes to the
    arms a difference that is partly the difference between what surrounded them.
    """
    if a.comparable_with(b):
        return
    ka = {p.kind: p.digest for p in a.parts if p.identifying}
    kb = {p.kind: p.digest for p in b.parts if p.identifying}
    differ = sorted(k for k in set(ka) | set(kb) if ka.get(k) != kb.get(k))
    raise Unidentified(
        f"these runs used different harnesses ({a.identity} against {b.identity}); the identifying parts that differ "
        f"are {differ}. Changing the instruction alone moved accuracy from 0.6243 to 0.7447 on the same box and the same "
        f"1,187 items, with one item in four flipping, so a difference between the arms cannot be separated from a "
        f"difference between what surrounded them")


#: Who each absence is about, as a total classification. Total on purpose: an absence reason added without deciding
#: whose it is breaks a test rather than defaulting to the harmless answer.
#:
#: The split that matters is `sender` against `collector`. An absence blamed on the sender is a fact about the run; one
#: blamed on the collector is a **measurement failure**, and the two were the same string until a shim losing the ability
#: to read a part was found to be indistinguishable from a sender that sent nothing.
ABSENCE_BLAMES = {
    "not_provided": "sender",
    "not_reachable": "collector",
    "extraction_failed": "collector",
    "redacted": "sender",
    "not_observable": "nobody",
}


@dataclass(frozen=True)
class Absence:
    """One part that is not in the record, and whose absence it is.

    A part is present or absent and never both: the same kind appearing in a harness's parts and in its absences is a
    record that answers "was this collected" two ways, and a consumer reading one of them is reading whichever it
    happened to check first.
    """

    kind: str
    reason: str
    #: What the collector was doing when it failed, for a `collector` absence. Required there, because a measurement
    #: failure nobody described is one nobody can fix, and refused elsewhere: the sender's silence has no detail we hold.
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in HARNESS_PARTS:
            raise Unidentified(
                f"{self.kind!r} is not one of {HARNESS_PARTS}. An absence of something the vocabulary does not name is "
                f"not a hole in the record; it is a hole in the vocabulary, and counting it as the first would report a "
                f"record as complete about a part nobody can ask for")
        if self.reason not in ABSENCE_REASONS:
            raise Unidentified(f"{self.reason!r} is not one of {ABSENCE_REASONS}")
        best = BEST_AVAILABLE_SOURCING[self.kind]
        if self.reason == "not_observable" and best != "not_observable":
            raise Unidentified(
                f"{self.kind!r} is absent as {self.reason!r} and the best any mode can do for it is {best!r}, so "
                f"something reachable is being recorded as structurally invisible. That is the direction that matters: "
                f"it makes a collector's failure look like a fact about the world, and nothing downstream can tell them "
                f"apart afterwards")
        if self.reason != "not_observable" and best == "not_observable":
            raise Unidentified(
                f"{self.kind!r} is structurally unobservable and is absent as {self.reason!r}, which claims somebody "
                f"could have had it. A tool's implementation behind an unchanged schema is invisible from the bytes we "
                f"hold, and blaming that on a sender or on a collector invites work that cannot succeed")
        if self.blames == "collector" and not self.detail:
            raise Unidentified(
                f"{self.kind!r} is absent because of us ({self.reason!r}) and carries no detail. This is the entry that "
                f"exists to be actionable -- a measurement failure nobody described is one nobody can fix, and it will "
                f"read as the sender's silence at every later glance")
        if self.blames != "collector" and self.detail:
            raise Unidentified(
                f"{self.kind!r} is absent as {self.reason!r}, which is not our failure, and carries detail "
                f"{self.detail!r}. Detail here describes what we were doing when we failed; there is no such moment")

    @property
    def blames(self) -> str:
        return ABSENCE_BLAMES[self.reason]

    def __str__(self) -> str:
        head = f"{self.kind} absent ({self.reason}, blames {self.blames})"
        return head + (f": {self.detail}" if self.detail else "")


@dataclass(frozen=True)
class Manifest:
    """What the collector claims it can reach here, so that `not_reachable` becomes checkable rather than merely spelled.

    This is the separation borrowed from SCITT -- who said this against is this true -- applied to the collector instead
    of only to the harness owner, which the first version of this design borrowed and then failed to use on itself.

    `reaches` is a claim, not an observation, and that is why it is worth having: a claim contradicts a record, and a
    contradiction is louder than a hole.
    """

    collector: str
    version: str
    reaches: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.collector or not self.version:
            raise Unidentified(
                "a manifest without a collector and a version cannot be compared against another run's, so a part that "
                "stopped being readable between two versions is a change nobody can attribute")
        unknown = sorted(set(self.reaches) - set(HARNESS_PARTS))
        if unknown:
            raise Unidentified(f"the manifest claims to reach {unknown}, which are not parts in {HARNESS_PARTS}")
        if len(set(self.reaches)) != len(self.reaches):
            raise Unidentified(f"the manifest lists a part twice in {sorted(self.reaches)}")
        impossible = sorted(k for k in self.reaches if BEST_AVAILABLE_SOURCING[k] == "not_observable")
        if impossible:
            raise Unidentified(
                f"the manifest claims to reach {impossible}, which no mode reaches. A collector that claims an "
                f"impossible part will report a contradiction on every run it ever produces, which trains a reader to "
                f"ignore the one signal this structure exists to raise")

    def __str__(self) -> str:
        return f"{self.collector}/{self.version} reaches {list(self.reaches)}"


@dataclass(frozen=True)
class Collection:
    """One run's record of what surrounded the model: the parts held, the parts not held, and how the collector itself did.

    Two refusals live here and they are about different objects, which is the correction the first version of this design
    needed. **Toward the sender this is maximally permissive**: any combination of parts may be absent and the record is
    still valid, because a collector that refuses a partial record produces no record, and a run that emitted nothing is
    indistinguishable from a run that emitted a perfect record of nothing. **About itself it is exact**: the status says
    whether the collector finished, and a collector that failed cannot present its failure as the sender's silence.

    `harness` is optional, and that is the permissive half made concrete: a run where nothing identifying was reachable
    still produces a record. It is simply not admissible to anything that publishes a claim.
    """

    manifest: Manifest
    status: str = "complete"
    harness: Harness | None = None
    absences: tuple[Absence, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in COLLECTION_STATUS:
            raise Unidentified(f"{self.status!r} is not one of {COLLECTION_STATUS}")
        if self.harness is not None and not isinstance(self.harness, Harness):
            raise Unidentified(f"harness={self.harness!r} is not a Harness")
        kinds = [a.kind for a in self.absences]
        if len(set(kinds)) != len(kinds):
            raise Unidentified(f"two absences share a kind in {sorted(kinds)}, so nothing says why the part is missing")
        held = {p.kind for p in self.harness.parts} if self.harness else set()
        both = sorted(held & set(kinds))
        if both:
            raise Unidentified(
                f"{both} are recorded as held and as absent at once, so this record answers 'was this collected' two "
                f"ways and a consumer reads whichever it happened to check first")

    @property
    def unaccounted(self) -> tuple[str, ...]:
        """Parts this record says nothing about at all -- neither held nor explained.

        Distinct from an absence, and the distinction is the point: an absence is a statement, and this is the silence
        an absence was invented to replace. A record with an empty `absences` and eight unaccounted parts looks like a
        record of a bare harness and is a record of a collector nobody finished.
        """
        named = ({p.kind for p in self.harness.parts} if self.harness else set()) | {a.kind for a in self.absences}
        return tuple(k for k in HARNESS_PARTS if k not in named)

    @property
    def contradictions(self) -> tuple[str, ...]:
        """Parts the collector claims it can reach and did not deliver.

        The one alarm this structure exists to raise. A hole that the manifest says should not be there is not a
        property of the run -- it is the collector regressing, and it is invisible in every other reading because the
        absence is spelled exactly the way a legitimate one is.
        """
        held = {p.kind for p in self.harness.parts} if self.harness else set()
        return tuple(k for k in self.manifest.reaches if k not in held)

    @property
    def our_failures(self) -> tuple[str, ...]:
        """Absences that are our fault rather than the sender's. Separated because only these are ours to fix."""
        return tuple(a.kind for a in self.absences if a.blames == "collector")

    def admissible_to_a_verdict(self) -> bool:
        """Whether anything may publish a claim from this record.

        Three conditions, and each is a different failure. An incomplete status means the record does not describe the
        run it appears to. A contradiction means the collector is lying about its own reach, so no absence in the record
        can be read at face value. And no identifying part means the identity would be constant across every possible
        harness, so a comparison against it groups things that have nothing in common.
        """
        return self.status == "complete" and not self.contradictions and self.harness is not None

    def why_not(self) -> str:
        """One sentence naming everything standing between this record and a published claim."""
        if self.admissible_to_a_verdict():
            return (f"admissible: {self.status}, no contradiction, identity "
                    f"{self.harness.identity}")
        parts = []
        if self.status != "complete":
            parts.append(f"the collector reports {self.status!r}, so the record does not describe the run it looks like")
        if self.contradictions:
            parts.append(f"the manifest claims to reach {list(self.contradictions)} and did not deliver them, so no "
                         f"absence here can be read at face value")
        if self.harness is None:
            parts.append("no part was identified by bytes we hold, so the identity would be the same for every "
                         "possible harness")
        return "not admissible to a verdict -- " + "; and ".join(parts)

    def __str__(self) -> str:
        who = self.harness.identity if self.harness else "no identity"
        return (f"collection {who} ({self.status}); held "
                f"{len(self.harness.parts) if self.harness else 0}; absent {len(self.absences)}; "
                f"unaccounted {list(self.unaccounted) or 'none'}; contradictions {list(self.contradictions) or 'none'}")


def digest_bytes(payload: str) -> str:
    """Hash a part's content. Over the bytes, because that is the only thing a label cannot drift away from."""
    if not payload.strip():
        raise Unidentified("an empty payload has no content to identify; a part that is genuinely empty is a part that "
                           "was not applied, and that is a different record")
    return hashlib.sha256(payload.encode()).hexdigest()
