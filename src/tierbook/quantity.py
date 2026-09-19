"""A quantity a policy may condition on, with its price, its availability, where it came from and when it is valid.

**META MECHANISM RULE, and this module is where it was broken.** Logic is injected; it is never built in. This module
carried an `ESCALATION_SUBJECTS` list naming the two subjects a gate was allowed to read, and a predicate returning
`subject in ESCALATION_SUBJECTS`. That put a measurement inside the mechanism: a topic signal was refused **a
priori**, so a study measuring topic to predict competence had no way to say so, and the refusal was derived from one
corpus rather than from the record it was refusing. It is gone -- what replaced it reads the evidence the record
carries and asks the caller which target it cares about.

Vocabularies here name **what a thing is** (`SUBJECTS`, `VALUE_KINDS`, `AVAILABILITY`) and never **which things are
worth using**. The difference is the whole design: the first is description a caller has to supply, the second is a
decision the caller came here to make.

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

from tierbook.evidence import (SUBJECTS, Elicitation,  # noqa: F401
                              EvidenceError)
from tierbook.criterion import Null
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



#: How a claim that a probability is calibrated was established. Closed, and the distinction is the whole point: a
#: vendor saying "all answers are accompanied with calibrated probabilities" has made a claim, not supplied a
#: measurement, and the two are not interchangeable.
#:
#: `measured_here` means somebody binned this candidate's own outputs against outcomes on the buyer's items.
#: `vendor_asserted` means it was stated. `unmeasured` is the honest state of anything nobody has binned -- and it is
#: what a probability arriving from a new interface starts as.
CALIBRATION_EVIDENCE = ("measured_here", "vendor_asserted", "unmeasured")


@dataclass(frozen=True)
class Confidence:
    """A probability a candidate returns beside its answer, and what is known about whether it means anything.

    Some interfaces return a decision **and** a probability in one call. That is worth having: it is a
    `own_competence` signal at zero extra passes, which is the cheapest thing a gate can condition on. What it is not
    is calibrated because it was described as calibrated.

    **Two claims travel together in vendor copy and neither implies the other.** "The model never makes type errors"
    is a statement about FORM -- a decoder held to a grammar cannot emit a non-member -- and it is checkable and true.
    "Calibrated probabilities" is a statement about CONTENT, and a decoder can place 0.99 on the wrong member of an
    enum without violating its grammar once. This project measured that shape: 1,822 of 2,364 answers on one option,
    every one well formed. So `evidence` is required, `vendor_asserted` cannot support a decision that trusts the
    number, and `reliability` is the measurement that would change that.
    """

    evidence: str
    #: The measured gap between stated confidence and observed accuracy, when somebody measured it. Absent means
    #: nobody did, which is not the same as zero -- and treating it as zero is exactly what accepting the claim does.
    reliability_gap: float | None = None
    bins: int | None = None

    def __post_init__(self) -> None:
        if self.evidence not in CALIBRATION_EVIDENCE:
            raise Inadmissible(f"{self.evidence!r} is not one of {CALIBRATION_EVIDENCE}")
        if self.evidence == "measured_here" and (self.reliability_gap is None or self.bins is None):
            raise Inadmissible(
                "evidence='measured_here' claims somebody binned this candidate's outputs against outcomes, so the gap "
                "and the number of bins are what that measurement produced; without them the claim is 'vendor_asserted' "
                "wearing the stronger word")
        if self.evidence != "measured_here" and (self.reliability_gap is not None or self.bins is not None):
            raise Inadmissible(
                f"evidence={self.evidence!r} carries a reliability measurement, which only 'measured_here' can have: a "
                f"gap nobody measured here is a number from somewhere this project cannot check")
        if self.reliability_gap is not None and not 0.0 <= self.reliability_gap <= 1.0:
            raise Inadmissible(f"reliability_gap={self.reliability_gap!r} is not a gap between two probabilities")
        if self.bins is not None and self.bins < 2:
            raise Inadmissible(f"bins={self.bins} cannot show a reliability curve; one bin is a single average and says "
                               f"nothing about whether high confidence means anything different from low")

    def may_be_trusted(self, *, max_gap: float) -> bool:
        """Whether a decision may condition on the NUMBER rather than merely on its ordering.

        Refused for anything not measured here, because that is the state a claim leaves it in. An unmeasured
        probability is still usable as a **ranking** -- ordering items by it needs no calibration at all -- and this
        method is about the stronger use: reading 0.85 as 85%.
        """
        if self.evidence != "measured_here":
            raise Inadmissible(
                f"the calibration of this confidence is {self.evidence!r}, so reading its number as a probability is "
                f"reading a claim. Rank items by it -- that needs no calibration -- or bin it against outcomes on the "
                f"buyer's own items and record the gap")
        return self.reliability_gap <= max_gap

    def __str__(self) -> str:
        if self.evidence != "measured_here":
            return f"confidence, calibration {self.evidence}"
        return f"confidence, gap {self.reliability_gap:.4f} over {self.bins} bins"

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
    #: What it is about. No default: a quantity whose subject is unstated is one a router cannot tell apart from a
    #: quantity about something else, and the measured pair points in opposite directions.
    subject: str
    price: SignalPrice
    measured_on: WeightDigest
    elicitation: Elicitation
    validity: Validity
    readout_version: str
    #: The measured performance, when it has been measured. `None` means nobody has, which is not the same as a signal
    #: that performed badly -- and the distinction matters at the door: an unmeasured quantity is admissible on the
    #: axes this structure checks and says nothing about whether it is worth conditioning on.
    performance: Performance | None = None
    #: Set when this quantity IS a probability the candidate returned beside its answer. `None` means it is not that
    #: kind of quantity -- an entropy or a queue length has no calibration claim to check.
    confidence: Confidence | None = None

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
        if self.subject not in SUBJECTS:
            raise Inadmissible(
                f"{self.subject!r} is not one of {SUBJECTS}. A mechanism handed one score cannot tell which of them it "
                f"was handed, and the measured pair diverges rather than merely differing: the same readout named the "
                f"item's field at 0.7593 against a chance of 0.1429 and predicted its own error at 0.4227, below the "
                f"0.5 a coin gets")
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
        if self.confidence is not None and not isinstance(self.confidence, Confidence):
            raise Inadmissible(f"confidence={self.confidence!r} is not a Confidence; a bare flag would record that a "
                               f"probability was returned and not whether anybody checked what it means")
        if self.performance is not None and not isinstance(self.performance, Performance):
            raise Inadmissible(
                f"performance={self.performance!r} is not a Performance. A bare number here would be the stored scalar "
                f"this type exists to refuse: the ranking at one price is not the ranking at another")
        if not self.readout_version:
            raise Inadmissible(
                "readout_version is empty. The same model and the same prompt with a changed readout give a different "
                "number under one name, which is the substitution this structure exists to make visible")

    @property
    def is_free(self) -> bool:
        """Whether obtaining this costs nothing beyond what the request pays anyway."""
        return self.price.extra_passes == 0

    def shown_to_predict(self, target: str) -> bool:
        """Whether THIS RECORD shows the signal predicts `target` better than a declared baseline.

        **Read off the record rather than decided here, and that is the correction.** The previous version returned
        `self.subject in ESCALATION_SUBJECTS` -- a closed list naming the two subjects one corpus found useful. That put a
        measurement inside the mechanism: a topic signal was refused a priori, so a study measuring topic to predict
        competence had no way to say so, and the refusal was not derived from anything in the record it was refusing.

        What the mechanism can hold a caller to is the shape of the evidence: a performance curve, the target it was
        measured against, and a baseline it beat. What it must not do is decide which targets are worth predicting.

        An absent performance answers False for every target. That is "the record does not claim this", not "the signal
        is useless", and `why_not_shown_to_predict` says which of the two.
        """
        if self.performance is None or not self.performance.predicts:
            return False
        if self.performance.predicts != target:
            return False
        best = max((point[1] for point in self.performance.curve), default=None)
        if best is None:
            return False
        return any(best > baseline.value for baseline in self.performance.baselines)

    def why_not_shown_to_predict(self, target: str) -> str:
        """One sentence naming what is missing between this record and a claim that it predicts `target`."""
        if self.shown_to_predict(target):
            return f"{self.name} was measured against {target!r} and beat a declared baseline"
        if self.performance is None:
            return (f"{self.name} carries no measured performance, so nothing here says whether it predicts {target!r}. "
                    f"That is an absence of evidence rather than evidence of absence")
        if not self.performance.predicts:
            return (f"{self.name} carries a performance curve that does not say what it was measured to predict, so it "
                    f"cannot be read against {target!r} or against anything else")
        if self.performance.predicts != target:
            return (f"{self.name} was measured against {self.performance.predicts!r} and is being asked about "
                    f"{target!r}. A signal that predicts one thing is not evidence about another")
        return (f"{self.name} was measured against {target!r} and did not beat any of its declared baselines "
                f"{[b.kind for b in self.performance.baselines]}")

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
        return (f"{self.name}/{self.readout_version} (about {self.subject}, {self.kind}, {self.availability}, "
                f"{self.register}, "
                f"{'free' if self.is_free else f'{self.price.extra_passes} extra pass(es)'})")


#: What a signal's strength was compared against. Closed, because the whole defect this closes is a strength reported
#: against whichever baseline made it look best, and an open-ended name is how that happens.
#:
#: `constant_score` is the one that bit: an abstention rule was reported at 0.5000 as a structural result, and 0.5000 is
#: the AUC of a constant score by construction -- it says nothing about the signal. The real decision-time baseline,
#: measured, was a **category dictionary at 0.6583**. So "beats 0.5" was written where "loses to the category prior"
#: was the fact.
BASELINE_KINDS = ("constant_score", "category_prior", "free_surface_feature", "matched_norm_random", "declared")


@dataclass(frozen=True)
class Baseline:
    """One thing a signal's strength was compared against, and what that thing scored."""

    kind: str
    value: float
    note: str = ""

    def __post_init__(self) -> None:
        if self.kind not in BASELINE_KINDS:
            raise Inadmissible(
                f"{self.kind!r} is not one of {BASELINE_KINDS}. An open-ended name is how a strength gets reported "
                f"against whichever baseline made it look best, which is the defect this vocabulary closes")
        if self.kind == "declared" and not self.note:
            raise Inadmissible("a 'declared' baseline is one this vocabulary does not name, so it needs a note saying "
                               "what it is; without one the reader has a number and no idea what beat it")

    def __str__(self) -> str:
        return f"{self.kind}={self.value:.4f}" + (f" ({self.note})" if self.note else "")


@dataclass(frozen=True)
class Performance:
    """A signal's measured performance as a CURVE over the price range, with every baseline it was compared against.

    **The curve is what is stored and every scalar is derived.** A scalar is the part that gets quoted, and the crossing
    measured here is not only in the cost term: at a high price of accuracy only the far tail of the distribution is
    being asked about, and the ranking in the tail differs from the ranking overall. A stored scalar is that ranking
    frozen at one price and then read as the ranking.

    **Every baseline is carried, and no single one is the headline.** Two lessons pull in opposite directions and this
    is how they are both respected: quoting the weakest baseline is the defect that reported 0.5000 as structural when
    a category dictionary scored 0.6583, and taking the maximum over several controls puts a winner's curse on the
    control side. So `beats` requires the caller to name which baseline, and there is no method that answers "is it
    better" without one.
    """

    curve: tuple[tuple[float, float], ...]
    baselines: tuple[Baseline, ...]
    #: What this signal was measured to predict. **Free text, and deliberately not a closed vocabulary** -- deciding
    #: which targets are legitimate is the study's job and not this package's. An earlier version of this module had a
    #: closed `ESCALATION_SUBJECTS` and refused a topic signal outright on the strength of one corpus, which made a
    #: finding unrepresentable rather than recordable: a study where topic does predict competence could not say so.
    #:
    #: Empty means nobody said, and then `shown_to_predict` answers False for every target -- not because the signal is
    #: useless but because the record does not claim anything.
    predicts: str = ""

    def __post_init__(self) -> None:
        if len(self.curve) < 2:
            raise Inadmissible(
                f"a curve of {len(self.curve)} point(s) is a scalar wearing a curve's name. The reason to store a curve "
                f"is that the ranking at one price is not the ranking at another, and one point cannot show that")
        prices = [p for p, _ in self.curve]
        if prices != sorted(prices):
            raise Inadmissible(f"the curve's prices {prices} are not in order; reading a value between two points "
                               f"depends on the order, so an unsorted curve gives a different answer per storage order")
        if len(set(prices)) != len(prices):
            raise Inadmissible("the curve has two values at one price, so it is not a function of price and nothing "
                               "says which of them applies")
        if not self.baselines:
            raise Inadmissible(
                "no baseline recorded. A strength with nothing beside it is the state that let '0.5000, reported as "
                "structural' stand where the measured decision-time baseline was 0.6583: the number was right and the "
                "claim it supported was not")

    @property
    def price_range(self) -> tuple[float, float]:
        return (self.curve[0][0], self.curve[-1][0])

    def at(self, price: float) -> float:
        """The measured value at a price on the curve, refused outside the range it was measured over.

        Refused rather than extrapolated, and refused rather than interpolated between the two nearest points: the
        crossing this exists to preserve happens *between* measured prices, so a straight line through it would report
        a ranking that was never observed at exactly the prices where the ranking changes.
        """
        for p, u in self.curve:
            if p == price:
                return u
        lo, hi = self.price_range
        raise Inadmissible(
            f"price {price} was not measured; the curve holds {[p for p, _ in self.curve]} over [{lo}, {hi}]. "
            f"Interpolating would invent a value between two points, and between two points is exactly where the "
            f"ranking measured here changes")

    def beats(self, baseline_kind: str, *, price: float) -> bool:
        """Whether the signal beat one NAMED baseline at one price. There is deliberately no unqualified version.

        Naming it is the whole point: without a name a caller gets "better", which is the sentence that was written
        against a constant score while a category dictionary was winning.
        """
        matching = [b for b in self.baselines if b.kind == baseline_kind]
        if not matching:
            raise Inadmissible(
                f"{baseline_kind!r} is not among the baselines this performance was measured against "
                f"{tuple(b.kind for b in self.baselines)}; answering anyway would compare against a number nobody "
                f"measured here")
        return self.at(price) > matching[0].value

    def loses_to_any(self, *, price: float) -> tuple[str, ...]:
        """Which baselines the signal does NOT beat at this price, which is the fact `beats` alone can hide.

        Returned rather than raised, and returned as the whole list rather than the worst case: reporting only the
        strongest loss is the winner's curse from the other side, and reporting none of them is how "beats 0.5" got
        written.
        """
        value = self.at(price)
        return tuple(b.kind for b in self.baselines if value <= b.value)

    def __str__(self) -> str:
        lo, hi = self.price_range
        return (f"{len(self.curve)} points over [{lo:g}, {hi:g}] against "
                f"{', '.join(str(b) for b in self.baselines)}")


#: What kind of number a strength is. Closed, because the interval that is correct for one is wrong for another, and
#: that mistake does not announce itself: a Wilson interval is for a binomial proportion, and putting one around an
#: area under a curve produces a plausible-looking pair of bounds computed for a statistic nobody measured.
STATISTICS = ("proportion", "auc", "mean")

#: How the interval was obtained. `wilson_on_a_proportion` is refused for anything but a proportion, which is the
#: specific trap this vocabulary exists for -- the numbers this module was built from are areas under a curve, and the
#: nearest interval already in this package is Wilson's.
INTERVAL_METHODS = ("wilson_on_a_proportion", "bootstrap", "delong", "declared")

#: Whether a stratum's number came from a model fitted inside that stratum or carried in from the pooled fit. Measured
#: to matter: a probe fitted on the pooled fold read **0.5350** on the slow group and **0.5787** when refitted within
#: it -- a gap of 0.0437 -- so a carried figure cannot tell "no information here" from "a direction learned for the
#: other group".
FIT_SOURCES = ("refitted_in_stratum", "carried_from_pooled")


@dataclass(frozen=True)
class Strength:
    """One measured strength, with the sample it came from and an interval computed for the right statistic."""

    value: float
    n: int
    interval: tuple[float, float]
    statistic: str
    interval_method: str

    def __post_init__(self) -> None:
        if self.statistic not in STATISTICS:
            raise Inadmissible(f"{self.statistic!r} is not one of {STATISTICS}")
        if self.interval_method not in INTERVAL_METHODS:
            raise Inadmissible(f"{self.interval_method!r} is not one of {INTERVAL_METHODS}")
        if self.interval_method == "wilson_on_a_proportion" and self.statistic != "proportion":
            raise Inadmissible(
                f"a Wilson interval is for a binomial proportion and this is a {self.statistic!r}. It would return a "
                f"plausible-looking pair of bounds computed for a statistic nobody measured, and nothing downstream "
                f"could tell that from a correct one -- use a bootstrap or DeLong for an area under a curve")
        if self.n <= 0:
            raise Inadmissible("a strength over zero items is not a measurement")
        lo, hi = self.interval
        if not lo <= self.value <= hi:
            raise Inadmissible(f"the interval [{lo}, {hi}] does not contain {self.value}, so at least one of the three "
                               f"was computed over something else")

    def __str__(self) -> str:
        lo, hi = self.interval
        return f"{self.value:.4f} [{lo:.4f}, {hi:.4f}] over {self.n} ({self.statistic}, {self.interval_method})"


#: The space a fitted direction's variance share was measured in. Closed, and closed because the SAME direction is
#: high-variance in one of these and low-variance in the other: the final norm's weights rescale every coordinate, so
#: they change which directions are large.
#:
#: This is the entry that cost the study its opening claim. A figure read as "this box confirms the paper's under-10%"
#: was measured **after** the norm weights were applied; in the raw stream the same direction is **2nd** by variance.
GEOMETRIES = ("raw_residual", "norm_scaled")

#: What the variance share was measured against. Closed, because the wrong one is not a weaker measurement, it is a
#: different quantity: a direction fitted and measured in one sample is being scored on the covariance it was chosen to
#: exploit.
VARIANCE_REFERENCES = ("fitting_sample", "held_out_covariance")

#: How the null was built, when one was. Unrestricted permutation lets a direction that merely predicts the ITEM'S
#: CATEGORY earn credit, and the stratified form is what removed it -- at one layer the real direction turned out
#: indistinguishable from a direction that only knows the category.
PERMUTATION_SCHEMES = ("none", "unrestricted", "within_category")


@dataclass(frozen=True)
class Fit:
    """A fitted direction's variance share, carrying the knob and the space it was computed in.

    **The measurement this type exists for.** Same data, same labels, same layer, and only the ridge changing:

    | ridge | raw: share / rank | norm-scaled: share / rank |
    |---|---|---|
    | 0.5 | 0.2424 / 2 | 0.2351 / 2 |
    | 20 | 0.1438 / 2 | 0.0042 / 28 |
    | 100 | 0.0556 / 4 | 0.0014 / **75** |

    **Rank 2 to rank 75 by turning one knob**, while held-out AUC barely moved. So the variance share of a fitted
    direction is a property of the fit and **not of the model**, and a figure quoted without its ridge and its geometry
    is a figure about nothing in particular. `share` is therefore never exposed as a bare number: it is reachable only
    through `about_this_fit()`, and `about_the_model()` does not exist.

    The two smallest ridges in that sweep diverged numerically and read AUC 0.5549. Those rows are **void, not
    evidence**, which is why `void_because` exists and why a void fit refuses to report a share at all.
    """

    share: float
    rank: int
    geometry: str
    ridge: float
    measured_against: str
    layer: int
    permutation: str = "none"
    #: The null as a DISTRIBUTION with the quantile a verdict may use, not a median. Reusing `criterion.Null` rather than
    #: carrying a float, because the same defect was already found and closed one module over: "beats the null" with only
    #: a middle recorded can mean either the middle or the tail, and **being above the median is a coin flip**. The first
    #: version of this field WAS a bare median, and it called the study's own raw-L28 row -- share 0.1311 against a null
    #: median of 0.1432, one-sided p 0.225 -- a result, on the wrong side of that coin.
    null: Null | None = None
    #: Why this row carries no evidence, when it does not. A numerically diverged solve produces a share and a rank like
    #: any other, and nothing about the numbers says they came from a fit that did not converge -- so the only way a void
    #: row stops being quoted is if asking for its share raises.
    void_because: str = ""

    def __post_init__(self) -> None:
        if self.geometry not in GEOMETRIES:
            raise Inadmissible(
                f"{self.geometry!r} is not one of {GEOMETRIES}. The same direction is 2nd by variance in the raw stream "
                f"and 75th after the norm weights are applied, so a share without its space is a number about nothing "
                f"in particular")
        if self.measured_against not in VARIANCE_REFERENCES:
            raise Inadmissible(f"{self.measured_against!r} is not one of {VARIANCE_REFERENCES}")
        if self.permutation not in PERMUTATION_SCHEMES:
            raise Inadmissible(f"{self.permutation!r} is not one of {PERMUTATION_SCHEMES}")
        if not 0.0 <= self.share <= 1.0:
            raise Inadmissible(f"share={self.share!r} is not a fraction of the variance")
        if self.rank < 1:
            raise Inadmissible(f"rank={self.rank} is not a rank; the largest direction is 1st")
        if self.ridge <= 0:
            raise Inadmissible(
                f"ridge={self.ridge!r} is not a regularisation. An unregularised fit is a different estimator rather "
                f"than the zero end of this one, and the sweep this type records has its two smallest ridges void for "
                f"numerical divergence")
        if self.layer < 0:
            raise Inadmissible(f"layer={self.layer} is not a layer")
        if (self.null is None) != (self.permutation == "none"):
            raise Inadmissible(
                f"permutation={self.permutation!r} and null={self.null!r}: a null was built and not recorded, or one was "
                f"recorded for a scheme that says nothing was permuted. What was held fixed is the whole difference "
                f"between a null that rules out the item's category and one that does not, and the real share is only "
                f"readable against it -- 0.0623 sits above every one of 200 nulls at one layer and indistinguishable "
                f"from them at another")
        if self.null is not None and not isinstance(self.null, Null):
            raise Inadmissible(
                f"null={self.null!r} is not a Null. A bare median here is the defect closed one module over: it cannot "
                f"say which quantile a verdict is against, and above-the-median is a coin flip")

    @property
    def is_void(self) -> bool:
        return bool(self.void_because)

    def about_this_fit(self) -> float:
        """The share, and the name says everything this number is about.

        There is deliberately no `about_the_model()`. The ridge moved this figure from rank 2 to rank 75 on identical
        data, so no accessor here can honestly answer a question about where the model keeps its information.
        """
        if self.is_void:
            raise Inadmissible(
                f"this fit is void ({self.void_because}) and has no share to report. A diverged solve produces a share "
                f"and a rank like any other, and nothing in the numbers says so -- reporting it is how a void row gets "
                f"quoted as evidence")
        return self.share

    def rules_out_the_null(self) -> bool:
        """Whether the share is distinguishable from a direction with no signal in it.

        Refused rather than answered when the share was measured in the fitting sample: a direction chosen to exploit a
        covariance and then scored against that same covariance is not being tested. This was the FIRST control run here
        and it is the one the adversarial round replaced.
        """
        if self.null is None:
            raise Inadmissible(
                "no null was built for this fit, so there is nothing for the share to be distinguishable from. Landing "
                "in the low-variance tail is the solver's default, which is why a low-variance finding was never "
                "evidence on its own")
        if self.measured_against == "fitting_sample":
            raise Inadmissible(
                "this share was measured in the sample the direction was fitted on, so the direction is being scored "
                "against the covariance it was chosen to exploit. Fit on train and measure against the held-out "
                "covariance, which is the form that refuted the original claim in every cell")
        if self.is_void:
            raise Inadmissible(f"this fit is void ({self.void_because})")
        return self.share > self.null.at_quantile

    def __str__(self) -> str:
        head = (f"share {self.share:.4f} (rank {self.rank}) at layer {self.layer} in {self.geometry}, ridge "
                f"{self.ridge:g}, against {self.measured_against}")
        if self.is_void:
            return head + f" -- VOID: {self.void_because}"
        if self.null is not None:
            head += (f", {self.null.draws} {self.permutation} permutations (median {self.null.median:.4f}, "
                     f"{self.null.quantile:.2f} quantile {self.null.at_quantile:.4f})")
        return head


def comparable_fits(a: Fit, b: Fit) -> None:
    """Refuse to read two fits against each other unless the knob and the space were held.

    The defect in its exact shape: rank 2 and rank 75 are the same data at two ridges, and quoting them side by side
    reads as the model moving. A comparison across geometries is the same error one level up, since the norm weights
    decide which directions are large before any fit happens.
    """
    # Voidness is checked FIRST, and the order is the point: a void row carries no evidence at any ridge, so refusing it
    # for the ridge tells a caller how to fix a comparison that can never be made.
    for fit in (a, b):
        if fit.is_void:
            raise Inadmissible(f"one of these fits is void ({fit.void_because}) and carries no evidence to compare")
    if a.geometry != b.geometry:
        raise Inadmissible(
            f"these fits were computed in {a.geometry!r} and {b.geometry!r}. The norm weights rescale every coordinate "
            f"and therefore change which directions are high-variance, so the difference between these shares is partly "
            f"the difference between the spaces")
    if a.ridge != b.ridge:
        raise Inadmissible(
            f"these fits used ridge {a.ridge:g} and {b.ridge:g}. On identical data one knob moved this figure from rank "
            f"2 to rank 75 while held-out AUC barely moved, so the difference between them is the knob")
    if a.layer != b.layer:
        raise Inadmissible(f"these fits are at layers {a.layer} and {b.layer}; the comparison is across depth, which is "
                           f"a different question and needs saying so")


@dataclass(frozen=True)
class StratifiedPerformance:
    """A strength reported per stratum rather than pooled, and what makes the report usable in production.

    **Pooling makes the number a property of the mix.** Split by the box's own settling depth, one probe read 0.7482 on
    the 1,827 items that settle early and **0.5350** on the 537 that settle late -- and the late group is where the box
    is wrong seven times in ten. A pooled 0.75 is an average over a population where the signal is strong on the easy
    half and **absent on the half that matters**, and the pooled number hides that completely.

    **And the stratifier has to be available when the decision is made.** Settling depth is known only after
    generation, so a report conditioned on it cannot be reproduced in production however true it is. That is not a
    reason to refuse recording it -- the analysis that found the collapse is worth keeping -- so this is constructible
    and `reproducible_in_production` is False, with `production_strength` refusing rather than the constructor.
    """

    stratum_of: Quantity
    per_stratum: dict
    fit_source: str
    pooled: Strength | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stratum_of, Quantity):
            raise Inadmissible(f"stratum_of={self.stratum_of!r} is not a Quantity. A bare name would not say when the "
                               f"stratifier is available, which is what decides whether this report can be used at all")
        if self.fit_source not in FIT_SOURCES:
            raise Inadmissible(
                f"{self.fit_source!r} is not one of {FIT_SOURCES}. A probe fitted on the pooled fold read 0.5350 on the "
                f"slow group and 0.5787 refitted within it, so which of the two produced a number is part of the number")
        if len(self.per_stratum) < 2:
            raise Inadmissible(
                f"{len(self.per_stratum)} stratum/strata is a pooled report wearing a conditional name. The whole point "
                f"is the comparison between them: one number over one group says nothing about the mix it came from")
        bad = [k for k, v in self.per_stratum.items() if not isinstance(v, Strength)]
        if bad:
            raise Inadmissible(f"strata {sorted(bad)} carry bare numbers rather than a Strength; a strength used to "
                               f"rule something out needs its sample size and its interval beside it")

    @property
    def reproducible_in_production(self) -> bool:
        """Whether the stratifier can be read when the decision is made."""
        return self.stratum_of.usable_before_generating()

    @property
    def weakest(self) -> tuple[str, Strength]:
        """The stratum the signal is worst on, which is the one a pooled figure hides."""
        return min(self.per_stratum.items(), key=lambda kv: kv[1].value)

    def pooling_hides(self) -> float:
        """How far the pooled figure sits above the worst stratum, or 0.0 when no pooled figure was recorded.

        The number F8 is about: 0.75 pooled against 0.5350 on the group that matters is a gap of 0.215, and the pooled
        figure is the one that gets quoted.
        """
        if self.pooled is None:
            return 0.0
        return max(0.0, self.pooled.value - self.weakest[1].value)

    def production_strength(self, stratum: str, *, allow_carried_fit: bool = False) -> Strength:
        """The number a production policy may use for this stratum, or a refusal naming why it may not.

        Two refusals, and they are different problems. A stratifier read after generation cannot be evaluated at
        decision time at all, so no amount of statistics rescues the report. A figure carried from the pooled fit
        cannot tell "no information here" from "a direction learned for the other group" -- measured at 0.0437 -- so it
        is readable as an upper or lower bound on the stratum and not as the stratum's strength.
        """
        if stratum not in self.per_stratum:
            raise Inadmissible(f"{stratum!r} is not one of {sorted(self.per_stratum)}")
        if not self.reproducible_in_production:
            raise Inadmissible(
                f"the strata are defined by {self.stratum_of.name!r}, available {self.stratum_of.availability}, so which "
                f"stratum a request falls in is not knowable when the decision is made. This report describes a split "
                f"that cannot be performed in production, however true it is of the corpus")
        if self.fit_source == "carried_from_pooled" and not allow_carried_fit:
            raise Inadmissible(
                f"the figure for {stratum!r} was carried from the pooled fit, which cannot distinguish an absence of "
                f"information in this stratum from a direction learned for another one; refitting within the group "
                f"moved the measured case from 0.5350 to 0.5787. Pass allow_carried_fit=True to read it as a bound "
                f"rather than as this stratum's strength")
        return self.per_stratum[stratum]


def admissible_for_a_gate(quantities: list[Quantity], *, elicitation: Elicitation,
                          served: WeightDigest) -> list[Quantity]:
    """Which of these a pre-generation gate CAN condition on, as a matter of what the records are about.

    **Three filters, and all three hold whatever anybody is studying.** The model served is not the one it was measured
    on, so the number is about a different object. The prompt condition differs, so it is about different items. It is
    not available until after the cost the gate exists to avoid has been paid, so a gate cannot read it at all.

    **What this function deliberately does NOT filter on is whether the signal is any good.** Two earlier versions did.
    The first knew which subjects were permitted, from a list naming the two this corpus found useful, so a topic signal
    was refused a priori and a study measuring topic to predict competence could not express it. The second asked for
    measured evidence against a target -- better, and still wrong, because **exploring an unmeasured signal is a
    legitimate thing to do** and this package has a module for it.

    So the caller decides. `Quantity.shown_to_predict(target)` reports what a record shows and
    `why_not_shown_to_predict` says what is missing; requiring it is a policy, and a policy belongs to whoever is
    running the study.

    Returned as a list rather than raising, because "no quantity is admissible here" is an answer a caller acts on --
    it means the gate has nothing to read, which is a finding rather than an error.
    """
    return [q for q in quantities
            if q.measured_on == served
            and q.elicitation.template_digest == elicitation.template_digest
            and q.usable_before_generating()]
