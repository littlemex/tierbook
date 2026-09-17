"""A quantity a policy may condition on, with its price, its availability, where it came from and when it is valid.

Five rounds of internal-readout work ended with a review saying the mechanism should hold **no readout-specific feature
at all**, and instead make a measurable quantity a thing with properties, so an internal readout is admissible without
being privileged. Entropy, a hidden-state probe, a price and a queue length are then the same kind of thing, and the
mechanism never learns any of their names.

**This structure replaces six separate requirements**, each of which was a number stored without the argument that
gives it meaning: a number that does not carry the prompt condition it was measured under; a decision that does not
record the price basis it used; an outcome that does not record how its answer was extracted; a signal that does not
record what it is *about*; a fitted quantity that does not carry its hyper-parameters; and a floor that does not name
the escalation target it is claimed for. Each was the same defect seen from a different side.

**The register distinction is not tidiness, it is a factor of four.** Moving an internal direction moves the words a
model uses about its own competence, and moves only **15%** of its answers. A mechanism that could register "I can
move this readout" as a lever on output quality would be acting on a 15% effect as though it were the 59% a paper
reports for a different claim. So passive observation, active probe and control action are three registers, an
intervention belongs in the **middle** one -- priced by what it costs, like any other observation -- and a `Quantity`
may not claim the third at all.

Everything here is assembled from parts that already exist rather than restated: the price is a `spend.SignalPrice`,
the prompt condition is an `evidence.Elicitation`, and the model is a `judge.WeightDigest`. That is the point of having
built those first -- a sixth home for "which model" would be a sixth thing to get wrong.
"""
from __future__ import annotations

from dataclasses import dataclass

from tierbook.evidence import Elicitation, EvidenceError
from tierbook.judge import WeightDigest
from tierbook.spend import SignalPrice

#: What shape the value takes. Closed, because an aggregation that is correct for one is wrong for another: averaging a
#: category is meaningless and averaging a trajectory throws away the shape that made it worth reading.
VALUE_KINDS = ("scalar", "vector", "trajectory", "category")

#: When the quantity can be had, **in the order a request passes through**, and the order is load-bearing: everything
#: before `after_generation` is available to a decision about whether to generate, and `after_generation` is not.
#:
#: DEFECT the first version of this tuple had: it listed `during_compute` after `after_prefill`, and
#: `usable_before_generating` then excluded it -- which reported the one quantity this study is actually about, a
#: hidden-state readout taken during the prefill computation, as unusable by the gate it was built for. Reading a
#: hidden state mid-prefill happens before any token is generated; the order here is the request's, not the
#: implementer's guess at it.
#:
#: A layer number is deliberately NOT one of these. It is provider-specific detail below this axis, and a mechanism
#: that keyed on it would refuse a quantity from a model with a different depth for no reason that matters.
AVAILABILITY = ("before_prefill", "during_compute", "after_prefill", "after_generation")

#: The three registers, and the reason they are kept apart. `passive_observation` reads what the request produces
#: anyway. `active_probe` perturbs something and reads the effect, which costs at least one extra pass and is where an
#: intervention belongs. `control_action` is a lever on output quality -- and a `Quantity` may not claim it, because
#: registering a 15% effect there would have it acted on as though it were the 59% reported for a different claim.
REGISTERS = ("passive_observation", "active_probe", "control_action")


class Inadmissible(EvidenceError):
    """A quantity was declared in a way that would let it be read as something it is not.

    Raised at construction rather than at use, because every one of the six defects this structure replaces was a
    number that looked usable and was missing the argument that gave it meaning. By the time it is used, the argument
    is not recoverable.
    """


@dataclass(frozen=True)
class Validity:
    """The condition a quantity was calibrated under, and how long that calibration stands.

    Separate from the provenance because they answer different questions: provenance says what produced the number,
    validity says when it stops being true. A quantity fitted under one prompt condition does not transfer to another
    **by recalibration** -- it is about different items -- so the elicitation appears in both, and `calibrated_for`
    naming a different one than the quantity was measured under is a refusal rather than a note.
    """

    calibrated_for: Elicitation
    fresh_for_days: float
    missing_is_representable: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.calibrated_for, Elicitation):
            raise Inadmissible(
                f"calibrated_for={self.calibrated_for!r} is not an Elicitation. A label would be the key this package "
                f"refuses everywhere: two templates both called 'terse' are two templates, and a quantity calibrated "
                f"under one of them is not calibrated under the other")
        if self.fresh_for_days <= 0:
            raise Inadmissible(
                f"fresh_for_days={self.fresh_for_days!r} says the calibration was never valid, which cannot be what a "
                f"caller means; a quantity with no freshness window is one nothing may condition on, and that is "
                f"expressed by not declaring it rather than by declaring it stale")


@dataclass(frozen=True)
class Quantity:
    """One measurable thing a policy may condition on, and everything needed to know whether it may.

    Required and undefaulted throughout, because a default here is the defect: each of the six requirements this
    replaces was satisfied on paper by a field that existed and was empty.
    """

    name: str
    kind: str
    availability: str
    register: str
    price: SignalPrice
    measured_on: WeightDigest
    elicitation: Elicitation
    validity: Validity
    readout_version: str

    def __post_init__(self) -> None:
        if not self.name:
            raise Inadmissible("a quantity with no name cannot be referred to by a policy, so nothing can condition on "
                               "it and nothing can be said about which one a result was obtained from")
        if self.kind not in VALUE_KINDS:
            raise Inadmissible(
                f"{self.kind!r} is not one of {VALUE_KINDS}. The kind decides which aggregations are meaningful -- "
                f"averaging a category says nothing and averaging a trajectory throws away the shape that made it "
                f"worth reading -- so an open-ended kind is an open invitation to the wrong one")
        if self.availability not in AVAILABILITY:
            raise Inadmissible(
                f"{self.availability!r} is not one of {AVAILABILITY}. A layer number is not an availability: it is "
                f"provider-specific detail below this axis, and a mechanism keyed on it would refuse a quantity from a "
                f"model of different depth for no reason that matters")
        if self.register not in REGISTERS:
            raise Inadmissible(f"{self.register!r} is not one of {REGISTERS}")
        if self.register == "control_action":
            raise Inadmissible(
                "a quantity may not be registered as a control action. Moving an internal direction moves the words a "
                "model uses about its own competence and moves 15% of its answers, so registering it here would have a "
                "15% effect acted on as though it were the 59% reported for a different claim. An intervention is an "
                "'active_probe': priced by what it costs, like any other observation")
        if self.register == "passive_observation" and self.price.extra_passes > 0:
            raise Inadmissible(
                f"{self.name!r} is registered as a passive observation and costs {self.price.extra_passes} extra "
                f"pass(es). Reading what the request produces anyway costs no extra pass, so this is an active probe "
                f"wearing the cheaper register -- and the register is what a caller checks before deciding it is free")
        if self.register == "active_probe" and self.price.extra_passes == 0:
            raise Inadmissible(
                f"{self.name!r} is registered as an active probe and costs no extra pass. A probe perturbs something "
                f"and reads the effect, which requires running the perturbed pass; at no extra cost it is a passive "
                f"observation, and calling it a probe would have it declined on a budget it does not consume")
        if not isinstance(self.measured_on, WeightDigest):
            raise Inadmissible(
                f"measured_on={self.measured_on!r} is not a WeightDigest. Two models agreeing on every declarable "
                f"field had probe amplitudes a factor of four apart, so a shape or a name here licenses a constant "
                f"that is true of something else")
        if not isinstance(self.elicitation, Elicitation):
            raise Inadmissible(f"elicitation={self.elicitation!r} is not an Elicitation; the prompt condition is part "
                               f"of what was measured, not a note about it")
        if not isinstance(self.validity, Validity):
            raise Inadmissible(f"validity={self.validity!r} is not a Validity")
        if self.validity.calibrated_for != self.elicitation:
            raise Inadmissible(
                f"{self.name!r} was measured under {self.elicitation} and calibrated for "
                f"{self.validity.calibrated_for}. Those are different conditions, and a quantity fitted in one does "
                f"not transfer to the other by recalibration -- it is about different items, so the calibration does "
                f"not describe this quantity at all")
        if not self.readout_version:
            raise Inadmissible(
                "readout_version is empty. The same model and the same prompt with a changed readout give a different "
                "number under one name, which is the substitution this structure exists to make visible")

    @property
    def is_free(self) -> bool:
        """Whether obtaining this costs nothing beyond what the request pays anyway."""
        return self.price.extra_passes == 0

    def usable_before_generating(self) -> bool:
        """Whether a decision about *whether to generate* can condition on this.

        The one question the availability axis exists to answer, and the reason it is not a layer number: a quantity
        read after generation may be excellent and is useless to a gate, because by then the cost the gate exists to
        avoid has been paid.

        Derived from the axis's order rather than from a hand-written list of the good values, so adding a stage
        between the existing ones cannot leave this predicate silently wrong about it -- which is how the first version
        excluded `during_compute` and reported this study's own readout as useless to its own gate.
        """
        return AVAILABILITY.index(self.availability) < AVAILABILITY.index("after_generation")

    def __str__(self) -> str:
        return (f"{self.name}/{self.readout_version} ({self.kind}, {self.availability}, {self.register}, "
                f"{'free' if self.is_free else f'{self.price.extra_passes} extra pass(es)'})")


def admissible_for_a_gate(quantities: list[Quantity], *, elicitation: Elicitation,
                          served: WeightDigest) -> list[Quantity]:
    """Which of these a pre-generation gate may condition on, and nothing else.

    Three filters, and each rejects for a different reason a caller would otherwise have to check by hand: the model
    served is not the one it was measured on; the prompt condition differs, so the number is about different items; or
    it is not available until after the cost the gate exists to avoid has been paid.

    Returned as a list rather than raising, because "no quantity is admissible here" is an answer a caller acts on --
    it means the gate has nothing to decide with, which is a finding rather than an error.
    """
    return [q for q in quantities
            if q.measured_on == served
            and q.elicitation.template_digest == elicitation.template_digest
            and q.usable_before_generating()]
