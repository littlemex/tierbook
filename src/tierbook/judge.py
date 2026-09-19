"""What a judge carries, and what a candidate must match for it to be admissible.

A judge is a decision rule somebody else may have built: it reads observations and says which candidate to use.
Three experiments produced the contract in this module, and each closed a defect that a plausible-looking design
admits.

**The key is a digest of the PUBLISHED weights.** Two models were served that agreed on architecture family,
`d_model`, depth, vocabulary size, the tied-embedding flag, dtype, attention period, weight file size and
`len(tokenizer)` -- 248,077 in both -- and whose residuals at the same layer, for the same prompt, had cosine 0.56
to 0.61 where two *different prompts* within one model reach 0.88 to 0.90. Their residual magnitudes differed by a
factor of 1.04, so no scale check would catch a judge running on the wrong one. Every weaker key is satisfied by
that pair, which is why `WeightDigest` refuses the weaker keys as *values* rather than merely preferring the digest.

**A digest of the LOADED tensors is not the same digest.** The first attempt hashed parameter bytes from the model
in memory and refused its own artefact on the very model it was built for: an inference engine fuses projections and
changes dtypes and shardings, so identical published weights give different tensor bytes. The refusal worked and
caught a real incompatibility, just not the intended one.

**Some constants cannot be declared, only measured.** Two models identical in architecture, dtype and depth
fraction had linear-probe amplitudes whose optimum differed by a factor of four, so a manifest cannot derive the
amplitude from anything it declares. A measured constant is therefore paired with the digest it was measured on,
and admission compares that digest rather than assuming a shape match licenses the number.

**And a third category is neither declared nor measured.** A readout convention -- "under a terse instruction the
next token is the answer" -- is an assumption about behaviour. It transfers no better than a Jacobian: on a model
matching its sibling in every declarable field it produced accuracy 0.0899 against a 0.10 random floor, and a
comparison run on those labels would have compared two orderings of noise. No manifest field can check it and no
digest can license it. What catches it is a base rate measured on the buyer's own items before the judge's output
is used at all, which is why `BaseRate` lives here and `admissible` reads it.

**The same comparison does double duty, and that is why binding lives here too.** Asking "may this judge run against
what is served" and asking "must a box be provisioned for it" are one question read at two points, so `bind` reuses the
digest the contract already carries rather than introducing a second notion of compatibility. The reason it matters is
not tidiness: a judge built by an ordinary user has to be able to point at the box an administrator already stands up
from a template, and if every judge provisions its own instead, a marketplace of judges does not work at any scale.
Which is why `blocked` and `provision` are different outcomes -- reporting the first as the second is exactly how a
shared box ends up idle beside a second copy of itself.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from tierbook.evidence import EvidenceError

from tierbook.reproduce import Rate

#: What a measured constant may be measured on. `published_weights` is the only honest answer this mechanism can
#: check: it is the artefact both the builder and the server can hash independently. `loaded_tensors` is named so
#: that the attempt is refused with its reason rather than silently accepted, because it is the mistake a careful
#: implementer makes first.
DIGEST_SUBJECTS = ("published_weights",)

#: Keys that were tried, are satisfied by two demonstrably different models, and are therefore refused as
#: compatibility keys rather than merely deprecated. Each is here because it was measured to be insufficient.
REFUSED_KEYS = ("shape", "d_model", "depth", "vocab_size", "tokenizer_length", "weight_statistics",
                "loaded_tensors", "model_name")

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


class Inadmissible(EvidenceError):
    """A judge was asked to run against a candidate its contract does not cover. Raised before the judge's output is
    read, because a mismatched judge still produces a working-looking gate -- one measured at 0.7176 against 0.7529
    for the matched one, a difference whose interval included zero -- so a mismatch is not detectable downstream.

    **Based on `EvidenceError` rather than `Exception`, and the reason is a defect this cost.** `quantity` defines an
    `Inadmissible` too, and the two were unrelated classes sharing a name: a door written as `except jd.Inadmissible`
    silently missed every refusal `quantity` raised, which is exactly what happened when `admit-fit` was added -- its
    refusal fell through to the outer handler and exited 1 where the door meant 2.

    Two exception classes with one name and no common base make every `except` a guess about which module raised. With
    this base, **`except EvidenceError` is always right**, and a caller that does not know which module refused does not
    need to."""


@dataclass(frozen=True)
class WeightDigest:
    """A digest of the published weights, and nothing weaker.

    `subject` exists so that a digest of the loaded tensors cannot be written as if it were this. That distinction
    is not pedantic: hashing loaded parameters made a correct artefact refuse its own model, because the engine's
    layout is not the publisher's.
    """

    hex: str
    subject: str = "published_weights"

    def __post_init__(self) -> None:
        if self.subject not in DIGEST_SUBJECTS:
            raise Inadmissible(
                f"{self.subject!r} is not one of {DIGEST_SUBJECTS}. A digest of the loaded tensors is a different "
                f"digest: an engine fuses projections and changes dtypes and shardings, so identical published "
                f"weights hash differently once served, and an artefact keyed that way refuses the very model it "
                f"was built on")
        if not _SHA256.fullmatch(self.hex):
            raise Inadmissible(
                f"{self.hex!r} is not a lowercase 64-character sha256. The point of a digest is that two models "
                f"agreeing on every declarable field -- {REFUSED_KEYS} were each checked and each satisfied by "
                f"such a pair -- still differ here, and a short or upper-case or non-hex value is not a value this "
                f"mechanism computed")

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.hex


def digest_published(snapshot: Path | str) -> WeightDigest:
    """Hash the published artefact: the config, then each weight file's name and size, in sorted order.

    Names and sizes rather than contents, deliberately. A content hash of tens of gigabytes is not something a
    server can afford at admission time, and the pair this contract exists to separate differs in file sizes as
    well as in weights -- so the cheap hash distinguishes them. Where it would not, `verify_contents` exists and is
    the caller's decision rather than this function's default.
    """
    d = Path(snapshot)
    h = hashlib.sha256()
    cfg = d / "config.json"
    if not cfg.exists():
        raise Inadmissible(f"{d} has no config.json, so there is nothing identifying which model this is; a digest "
                           f"over weight files alone would collide across two quantisations of one checkpoint")
    h.update(cfg.read_bytes())
    files = sorted(d.glob("*.safetensors"))
    if not files:
        raise Inadmissible(f"{d} contains no .safetensors, so the digest would be of a config alone -- which two "
                           f"different fine-tunes of one base model share")
    for f in files:
        h.update(f.name.encode())
        h.update(str(f.stat().st_size).encode())
    return WeightDigest(hex=h.hexdigest())


@dataclass(frozen=True)
class MeasuredConstant:
    """A number the judge measured, paired with the digest it was measured on.

    The pairing is the whole content. A judge's amplitude, its probe layer, the scaling of its fitted head: none is
    derivable from anything a manifest declares, and the amplitude's optimum was measured to differ by a factor of
    four between two models identical in architecture, dtype and depth fraction. So the number travels with the
    weights it is true of, and `admissible` compares that digest instead of accepting a shape match as a licence.
    """

    name: str
    value: float
    measured_on: WeightDigest

    def __post_init__(self) -> None:
        if not isinstance(self.measured_on, WeightDigest):
            raise Inadmissible(
                f"{self.name!r} was measured on {self.measured_on!r}, which is not a WeightDigest. A measured "
                f"constant with a weaker key is the defect this pairing exists to close: two models agreeing on "
                f"{REFUSED_KEYS} had optimal amplitudes a factor of four apart")
        if not self.name:
            raise Inadmissible("a measured constant with no name cannot be matched against the constant a judge "
                               "asks for, so it can only be checked by position, which is how the wrong number "
                               "gets used")


@dataclass(frozen=True)
class BaseRate:
    """A candidate's own accuracy on the buyer's items, measured before any judge is consulted.

    This is the only check that catches a broken *convention*. A judge whose readout assumes "the next token is the
    answer letter" ran on a model matching its sibling in every declarable field and produced 0.0899 against a 0.10
    random floor -- and the shape matched, the dtype matched, the tokenizer length matched, and a weight digest
    would have matched too, because it was the right model. What was wrong was an assumption about behaviour, and
    only a base rate sees it.

    `floor` is the buyer's, not the judge's: it is a property of the task -- one over the number of options, times
    some margin -- and a judge that could set it would be certifying itself.
    """

    correct: int
    total: int
    floor: float

    def __post_init__(self) -> None:
        if self.total <= 0:
            raise Inadmissible("a base rate over zero items is not a measurement; the check exists because a "
                               "convention failure looks exactly like a working judge until the rate is computed")
        if not 0 <= self.correct <= self.total:
            raise Inadmissible(f"{self.correct} correct of {self.total} is not a count")
        if not 0.0 < self.floor < 1.0:
            raise Inadmissible(f"floor={self.floor!r} must lie strictly between 0 and 1: a floor of 0 admits the "
                               f"noise this check exists to refuse, and a floor of 1 admits nothing")

    @property
    def rate(self) -> float:
        return self.correct / self.total

    @property
    def as_rate(self) -> Rate:
        """The same counts as a rate that cannot be read without its interval."""
        return Rate(successes=self.correct, n=self.total)

    @property
    def clears(self) -> bool:
        """Whether the whole interval sits above the floor -- not whether the centre does.

        DEFECT this closes: this compared the point estimate to the floor, so a base rate of 0.2137 over 234 items
        "cleared" a floor of 0.20 while its interval ran from 0.166 to 0.272. That is a sample which cannot tell which
        side of the floor it is on, admitted as evidence that the readout works. The measured form of the same error is
        a conclusion carried by 0.8934 that would not have survived 0.9156 printed beside it.
        """
        return self.as_rate.rules_out(self.floor, above=True)

    @property
    def cannot_decide(self) -> bool:
        """Whether the floor is inside the interval, which is a different answer from failing to clear it."""
        return self.as_rate.cannot_decide(self.floor)


@dataclass(frozen=True)
class JudgeContract:
    """Everything a judge must declare for admission to be decidable without running it.

    Split three ways because the three are checked differently, and collapsing them is how a manifest ends up
    looking complete while admitting a judge that cannot work:

    * `declared` -- compared against the served candidate. A mismatch is refused.
    * `measured` -- cannot be compared, only re-measured. The digest is what licenses each number.
    * `assumes` -- checkable by neither. Named so a reader knows what the base rate is guarding against.
    """

    judge_id: str
    weight_digest: WeightDigest
    declared: dict[str, str | int] = field(default_factory=dict)
    measured: tuple[MeasuredConstant, ...] = ()
    assumes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.judge_id:
            raise Inadmissible("a judge with no id cannot be named in a decision record, so its outcomes cannot be "
                               "attributed to it and its performance cannot be measured separately from the "
                               "policy that called it")
        bad = sorted(set(self.declared) & set(REFUSED_KEYS))
        if bad:
            raise Inadmissible(
                f"declared {bad} as if they identified the model. Each was measured to be insufficient: two models "
                f"agreed on all of {REFUSED_KEYS} and their residuals were further apart than two different "
                f"questions within one model. Declare them as description if useful, but the KEY is the digest, so "
                f"they may not appear here")
        wrong = [c.name for c in self.measured if c.measured_on != self.weight_digest]
        if wrong:
            raise Inadmissible(
                f"measured constants {wrong} were measured on a different digest than this judge declares. A "
                f"constant measured elsewhere is not a constant of this judge: supporting a second model is a "
                f"second measurement campaign, not a configuration change")

    def constant(self, name: str) -> float:
        for c in self.measured:
            if c.name == name:
                return c.value
        raise Inadmissible(f"{name!r} is not among this judge's measured constants "
                           f"{tuple(c.name for c in self.measured)}; a constant a judge needs and does not carry "
                           f"would be filled in by a default, which is a number nobody measured")


def admissible(contract: JudgeContract, *, served: WeightDigest, base_rate: BaseRate | None) -> None:
    """Refuse before the judge's output is read, or return.

    The ordering matters. The digest is checked first because it is decidable from the manifest alone and costs
    nothing; the base rate is checked second because it costs a pass over the buyer's items. Both are checked
    because they catch different things: the digest catches the wrong model, the base rate catches the right model
    behaving in a way the judge did not assume.
    """
    if not isinstance(served, WeightDigest):
        raise Inadmissible(f"the served model was identified by {served!r} rather than a WeightDigest; a weaker "
                           f"identifier admits a judge built for a different model, which still produces a "
                           f"working-looking gate")
    if contract.weight_digest != served:
        raise Inadmissible(
            f"judge {contract.judge_id!r} was built on {contract.weight_digest.hex[:16]} and the served model is "
            f"{served.hex[:16]}. A carried judge measurably still works -- 0.7176 against 0.7529 for the matched "
            f"one, an interval including zero -- so this cannot be caught downstream by the gate looking wrong")
    if base_rate is None:
        raise Inadmissible(
            f"judge {contract.judge_id!r} has no base rate for this candidate. A readout convention is neither "
            f"declared nor measurable from the weights, and a broken one produced 0.0899 against a 0.10 floor on a "
            f"model whose digest matched; the base rate is the only check that sees it")
    if base_rate.cannot_decide:
        raise Inadmissible(
            f"the candidate answers {base_rate.as_rate} on the buyer's items and the floor {base_rate.floor} lies "
            f"inside that interval, so this sample cannot tell which side of the floor the candidate is on. That is a "
            f"request for more items rather than a finding, and admitting it would let a rate indistinguishable from "
            f"the floor stand as evidence that the readout works")
    if not base_rate.clears:
        raise Inadmissible(
            f"the candidate answers {base_rate.as_rate} on the buyer's items, below the declared floor of "
            f"{base_rate.floor}. Whatever the judge then reports is an ordering of noise, and a comparison built on it "
            f"returns a number rather than an error")

#: Why a standing box could not be bound to. Closed, because the difference between these decides whether the answer
#: is "provision one" or "ask for access", and conflating them is how every judge ends up with its own box.
UNBINDABLE_REASONS = (
    "digest_mismatch",      # it serves a different model; no permission would help
    "not_shared",           # it serves the right model and its owner has not offered it
    "at_capacity",          # it serves the right model and would take a tenant, but not another one now
)

#: What a binding attempt concluded. `bound` names the box. `provision` means nothing serves this model at all, which
#: is the only honest reason to start a new one. `blocked` means something DOES serve it and would not take this
#: judge -- a permission or capacity problem wearing the shape of a provisioning one, and the distinction is the whole
#: point: answering `provision` here is how a shared box sits idle beside a second copy of itself.
BINDING_OUTCOMES = ("bound", "provision", "blocked")


@dataclass(frozen=True)
class StandingBox:
    """A serving box somebody already runs, and what it will and will not accept.

    The digest is a `WeightDigest` rather than a model name for the reason the rest of this module keys on one: two
    boxes serving models that agree on every declarable field are not interchangeable, and a judge bound to the wrong
    one produces a working-looking gate.

    `shared_with` is the marketplace requirement in one field. A judge built by an ordinary user has to be able to
    point at the box an administrator already stands up from a template, and the alternative -- every judge
    provisioning its own -- is the failure that makes a marketplace of judges impossible rather than merely wasteful.
    """

    box_id: str
    serves: WeightDigest
    owner: str
    shared_with: tuple[str, ...] = ()
    tenants: int = 0
    max_tenants: int = 1

    def __post_init__(self) -> None:
        if not self.box_id or not self.owner:
            raise Inadmissible("a standing box needs both an id and an owner: the id is what a judge binds to and the "
                               "owner is who a blocked judge has to ask, and a binding that cannot name either leaves "
                               "the caller with nothing to do next")
        if not isinstance(self.serves, WeightDigest):
            raise Inadmissible(
                f"box {self.box_id!r} says it serves {self.serves!r}, which is not a WeightDigest. Two boxes serving "
                f"models that agree on {REFUSED_KEYS} are not interchangeable, so a name here would let a judge bind "
                f"to the wrong one and still appear to work")
        if self.max_tenants < 1:
            raise Inadmissible(f"box {self.box_id!r} declares max_tenants={self.max_tenants}, so it can never be bound "
                               f"to; a box nothing may use is not a standing box, it is a box being decommissioned")
        if self.tenants < 0 or self.tenants > self.max_tenants:
            raise Inadmissible(f"box {self.box_id!r} reports {self.tenants} of {self.max_tenants} tenants, which is not "
                               f"an occupancy")

    def accepts(self, requester: str) -> bool:
        """Whether this box's owner has offered it to `requester`. Ownership is offered access, not a special case."""
        return requester == self.owner or requester in self.shared_with or "*" in self.shared_with

    @property
    def has_room(self) -> bool:
        return self.tenants < self.max_tenants


@dataclass(frozen=True)
class Binding:
    """What a binding attempt concluded, and for every box that was rejected, why.

    The rejections are carried rather than summarised for the same reason `Candidate.excluded_because` is: "provision
    one" and "ask box-1's owner for access" are different instructions to a caller, and a result that only said "no"
    would send them to provision a second copy of a box that already exists.
    """

    outcome: str
    box_id: str = ""
    rejected: tuple[tuple[str, str], ...] = ()   # (box_id, one of UNBINDABLE_REASONS)

    def __post_init__(self) -> None:
        if self.outcome not in BINDING_OUTCOMES:
            raise Inadmissible(f"{self.outcome!r} is not one of {BINDING_OUTCOMES}")
        if (self.outcome == "bound") != bool(self.box_id):
            raise Inadmissible(
                f"outcome={self.outcome!r} and box_id={self.box_id!r} disagree. A binding names a box exactly when it "
                f"succeeded: a named box with any other outcome reads as though it were usable, and an unnamed one "
                f"with outcome 'bound' cannot be acted on")
        bad = sorted({r for _, r in self.rejected} - set(UNBINDABLE_REASONS))
        if bad:
            raise Inadmissible(f"rejection reasons {bad} are not in {UNBINDABLE_REASONS}; an open-ended reason cannot "
                               f"be turned into an instruction for the caller")

    @property
    def instruction(self) -> str:
        """What the caller should actually do, which is the product of this whole comparison."""
        if self.outcome == "bound":
            return f"bind to {self.box_id}"
        if self.outcome == "provision":
            return ("provision a box serving this judge's digest: nothing standing serves it, so there is no shared "
                    "resource to point at")
        blocked = [b for b, r in self.rejected if r != "digest_mismatch"]
        return (f"ask the owner of {', '.join(blocked)} for access or capacity -- a box already serves this judge's "
                f"digest, so provisioning another would leave two copies of one model")


def bind(contract: JudgeContract, boxes: list[StandingBox], *, requester: str) -> Binding:
    """Which standing box this judge may use, or what to do because none will.

    **Requirement and provisioning are two readings of one comparison**, which is why this reuses the digest the
    contract already carries rather than introducing a second notion of compatibility. Asking "does any standing box
    serve what this judge needs" and asking "must I start one" are the same question answered at different points.

    The three outcomes are kept apart because they are different instructions, and collapsing the last two is the
    specific failure this exists to prevent: if `blocked` were reported as `provision`, every judge whose access
    request was pending would start its own copy of a box that is already running, and a marketplace where each
    judge silos its own hardware does not work at any scale.
    """
    rejected: list[tuple[str, str]] = []
    for box in boxes:
        if box.serves != contract.weight_digest:
            rejected.append((box.box_id, "digest_mismatch"))
        elif not box.accepts(requester):
            rejected.append((box.box_id, "not_shared"))
        elif not box.has_room:
            rejected.append((box.box_id, "at_capacity"))
        else:
            return Binding(outcome="bound", box_id=box.box_id, rejected=tuple(rejected))
    serves_it = [r for r in rejected if r[1] != "digest_mismatch"]
    return Binding(outcome="blocked" if serves_it else "provision", rejected=tuple(rejected))

