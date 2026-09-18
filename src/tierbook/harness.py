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

from tierbook.evidence import HARNESS_SOURCING, IDENTIFYING_SOURCING, EvidenceError

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


def digest_bytes(payload: str) -> str:
    """Hash a part's content. Over the bytes, because that is the only thing a label cannot drift away from."""
    if not payload.strip():
        raise Unidentified("an empty payload has no content to identify; a part that is genuinely empty is a part that "
                           "was not applied, and that is a different record")
    return hashlib.sha256(payload.encode()).hexdigest()
