"""How an answer was pulled out of a reply, and a refusal when the result cannot be an answer distribution.

The convention "the option letter is the next token" is true under a terse instruction and false when the model
explains itself first. Applied anyway to one GPU run, it put **1,822 of 2,364 items on `A`** -- 77.1% of the corpus on
one option out of ten -- and drove accuracy to 0.1599 against a 0.10 random floor. One full run and a set of reported
numbers were lost.

**The reason this module exists is the sentence after that.** The break was loud enough to catch. *The same failure at
half the rate would have produced a plausible middle value and been believed.* So a check that only catches 77% is not
a check; `refuse_degenerate` is calibrated against half the measured break and `bound_from_options` refuses a bound
that would have let it through.

Two things are recorded, and they are the same shape as `record.BoundProvenance`: a value whose meaning depends on how
it was produced, currently written without that. The rule is one of a closed set, because "custom" in a log is a field
nobody can aggregate over. And the answers it produced are checked, because a rule can be named correctly and still be
wrong for the replies it was run on -- which is exactly what happened.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from tierbook.evidence import EvidenceError

#: How the answer was taken from the reply. Closed, and each entry names a convention that was actually used here.
#:
#: `next_token` is the one that broke: the token after the prompt, correct under a terse instruction only.
#: `answer_cue` appends an explicit cue and reads what follows it, which is what the repair used and what made the two
#: conditions comparable. `regex_in_reply` searches the whole reply, which cannot be told apart from the model
#: mentioning an option in passing. `parsed_structure` reads a declared field. `unrecorded` is what every outcome
#: written before this existed carries -- not a guess, but the true statement that nothing says.
EXTRACTION_RULES = ("next_token", "answer_cue", "regex_in_reply", "parsed_structure", "unrecorded")

#: The share of one option that was actually observed when the convention was wrong, and the number every bound here is
#: answerable to. Not a threshold: a record of what a real break looked like.
MEASURED_BREAK_MODAL_SHARE = 1822 / 2364

#: Half of it, because the ledger's own lesson is that the same failure at half the rate would have been believed.
MUST_CATCH_MODAL_SHARE = MEASURED_BREAK_MODAL_SHARE / 2

#: The same two numbers as multiples of uniform, which is the form the guard has to use.
#:
#: DEFECT the first version had: it compared a caller's absolute bound against `MUST_CATCH_MODAL_SHARE`, a share
#: measured on a **ten**-option task. On two options that refused every tolerance, because uniform is already 0.5 and
#: 0.3854 sits below it -- so a binary task could never obtain a bound at all, and the check would have been switched
#: off wherever it was most usable. Clustering has to be compared as a multiple of uniform or not at all.
MEASURED_BREAK_TOLERANCE = MEASURED_BREAK_MODAL_SHARE * 10
MUST_CATCH_TOLERANCE = MEASURED_BREAK_TOLERANCE / 2


class Degenerate(EvidenceError):
    """The extracted answers cannot be an answer distribution, whatever the accuracy says.

    Distinct from a low accuracy, and the distinction is why this check earns its place: accuracy 0.1599 against a 0.10
    floor is a *plausible* number, low but not obviously broken, and a reader shown only that would have gone looking
    for a weak model rather than a broken reader. The mass on one option is what says the reader is broken.
    """


def bound_from_options(options: int, *, tolerance: float = 3.0) -> float:
    """The largest modal share a working extraction may produce, derived from the number of options.

    `1 / options` is what a uniform reader gives, and real answers are not uniform -- a task has easy items whose
    correct answer happens to be `B` more often than chance. `tolerance` is how much clustering is allowed above
    uniform before the reader rather than the task is the likely cause, and it is a caller's declaration rather than a
    constant here because it depends on how skewed the answer key is.

    **What is not the caller's to declare** is a tolerance so loose it would have admitted the failure this exists to
    catch. The measured break was 7.71 times uniform and half of it is 3.85 times; a tolerance above that is refused
    with both numbers, because a check calibrated to catch only the loud version of a failure will not fire on the
    quiet one.

    The comparison is in multiples of uniform rather than in absolute share, and that is not a presentation choice: the
    break was measured on a ten-option task, and 0.385 of a **two**-option task is below uniform. Comparing the two as
    shares refused every tolerance a binary task could name.
    """
    if options < 2:
        raise EvidenceError(f"options={options} is not a choice; with one option every answer is the modal answer and "
                            f"no distribution over them can be degenerate or otherwise")
    if tolerance <= 1.0:
        raise EvidenceError(
            f"tolerance={tolerance} would put the bound at or below uniform, so a perfectly working reader on a task "
            f"whose answers are not exactly balanced would be refused; the check would then fire on every healthy run "
            f"and be switched off")
    if tolerance > MUST_CATCH_TOLERANCE:
        raise EvidenceError(
            f"tolerance={tolerance} is looser than {MUST_CATCH_TOLERANCE:.4f} times uniform, which is half the measured "
            f"break ({MEASURED_BREAK_TOLERANCE:.4f} times uniform, 1,822 of 2,364 on one option out of ten). A bound "
            f"that admits the quiet version of a failure is not a bound; lower the tolerance, or state the bound "
            f"directly and say why this task's answer key is that skewed")
    bound = tolerance / options
    if bound >= 1.0:
        # DEFECT this prevents: at the default tolerance a two-option task derives 1.5, clamped to 1.0, which admits
        # every possible answer set. The check would then be present, called, green, and incapable of refusing
        # anything -- coverage that is not coverage. Refusing sends the caller to state a bound and say why, which is
        # the only honest thing at two options: 95% on one of two is a broken reader or a badly skewed answer key, and
        # nothing derivable from the option count alone can tell those apart.
        raise EvidenceError(
            f"tolerance {tolerance} over {options} options derives a bound of {bound:.4f}, which admits every answer "
            f"set. A bound that refuses nothing reports as a check and is not one; state `modal_bound` directly, with "
            f"the reason this task's answers cluster that hard")
    return bound


@dataclass(frozen=True)
class Extraction:
    """The rule that produced an answer, travelling with it.

    `options` is here rather than left to the caller of the check because it is a property of the task the rule was run
    on, and the bound is meaningless without it: 40% on one option is a broken reader over ten options and ordinary
    over two.
    """

    rule: str
    options: int
    cue: str = ""

    def __post_init__(self) -> None:
        if self.rule not in EXTRACTION_RULES:
            raise EvidenceError(
                f"{self.rule!r} is not one of {EXTRACTION_RULES}. An open-ended rule cannot be aggregated over a log, "
                f"and the whole reason to record it is that two outcomes produced by different rules are not "
                f"comparable")
        if self.rule != "unrecorded" and self.options < 2:
            raise EvidenceError(f"rule {self.rule!r} declares {self.options} options; a rule that extracts one of a "
                                f"single choice extracts nothing")
        if self.rule == "answer_cue" and not self.cue:
            raise EvidenceError(
                "rule 'answer_cue' reads what follows a cue and no cue is recorded, so nothing says where the answer "
                "was read from. The cue is the whole content of this rule: appending it in one condition and not the "
                "other is what made two runs' endpoints different kinds of position")
        if self.rule != "answer_cue" and self.cue:
            raise EvidenceError(f"rule {self.rule!r} carries cue={self.cue!r} but does not read one, so the cue "
                                f"describes something that did not happen")

    def __str__(self) -> str:
        return f"{self.rule}" + (f"({self.cue!r})" if self.cue else "") + f" over {self.options} options"


def modal_share(answers: list[str | None]) -> float:
    """The share of the extracted answers that landed on whichever option got the most.

    `None` -- an unparsed reply -- is counted in the denominator and not as an option. A reader that fails to parse
    half the corpus and clusters the rest is two failures, and folding the unparsed into the mode would report one.
    """
    if not answers:
        return 0.0
    parsed = [a for a in answers if a is not None]
    if not parsed:
        return 0.0
    return Counter(parsed).most_common(1)[0][1] / len(answers)


def unparsed_share(answers: list[str | None]) -> float:
    """The share of replies the rule could not read at all, which is its own failure and not a low accuracy."""
    return 0.0 if not answers else sum(1 for a in answers if a is None) / len(answers)


def refuse_degenerate(answers: list[str | None], extraction: Extraction, *,
                      modal_bound: float | None = None, unparsed_bound: float = 0.5) -> None:
    """Refuse an answer set that cannot be a distribution over the options, before any accuracy is computed from it.

    Before rather than after, because an accuracy is a plausible number and this is not: the run that broke reported
    0.1599 against a 0.10 floor, which reads as a weak model. The 77.1% on one option reads as a broken reader, and
    only one of those two sends anybody to look at the extraction.

    `modal_bound` defaults to `bound_from_options(extraction.options)`, so a caller who has not thought about it gets a
    bound derived from the task rather than a number this module invented.
    """
    if extraction.rule == "unrecorded":
        raise EvidenceError(
            "the extraction rule is 'unrecorded', so there is nothing to check these answers against: the same set of "
            "letters is a working read under one convention and a broken one under another, and which it is depends "
            "on the rule this outcome does not carry")
    if not answers:
        raise EvidenceError("no answers to check; an extraction that produced nothing is not a passing extraction, and "
                            "returning silently here would report one as such")
    bound = bound_from_options(extraction.options) if modal_bound is None else modal_bound
    unparsed = unparsed_share(answers)
    if unparsed > unparsed_bound:
        raise Degenerate(
            f"{unparsed:.4f} of {len(answers)} replies could not be read by {extraction}. That is the rule failing, "
            f"not the model answering badly, and an accuracy computed over the remainder is an accuracy over the "
            f"items the rule happened to manage")
    share = modal_share(answers)
    if share > bound:
        raise Degenerate(
            f"{share:.4f} of {len(answers)} answers landed on one option out of {extraction.options}, above the bound "
            f"{bound:.4f}, under {extraction}. This is the shape of the measured break -- 1,822 of 2,364 on 'A', "
            f"accuracy 0.1599 against a 0.10 floor -- where the accuracy read as a weak model and the clustering was "
            f"what said the reader was broken")
