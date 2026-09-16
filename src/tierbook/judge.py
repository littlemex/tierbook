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
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

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


class Inadmissible(Exception):
    """A judge was asked to run against a candidate its contract does not cover. Raised before the judge's output is
    read, because a mismatched judge still produces a working-looking gate -- one measured at 0.7176 against 0.7529
    for the matched one, a difference whose interval included zero -- so a mismatch is not detectable downstream."""


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
    def clears(self) -> bool:
        return self.rate >= self.floor


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
    if not base_rate.clears:
        raise Inadmissible(
            f"the candidate answers {base_rate.correct}/{base_rate.total} = {base_rate.rate:.4f} on the buyer's "
            f"items, below the declared floor of {base_rate.floor}. Whatever the judge then reports is an ordering "
            f"of noise, and a comparison built on it returns a number rather than an error")
