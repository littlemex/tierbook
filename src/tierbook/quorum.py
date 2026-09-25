"""Stop when cheap candidates agree, and let the price vector choose which ones.

A cheap candidate's own uncertainty answers "do I know this". A routing policy needs "does anyone
cheaper than the dear tier know this", and those are different questions: measured on a
nine-candidate corpus, the box's prefill entropy predicts "every candidate solves it" at 0.83 AUC and
"no candidate solves it" at 0.51, because self-doubt carries no information about what the others
know. Three independent answers do carry it. Where three cheap candidates agree, the agreed answer was
right 89.7% of the time -- as often as the frontier tier is right on the whole corpus, at a quarter of
the price -- and where they disagree the item is escalated.

**This module deliberately does not decide which candidates form the quorum.** That is a function of
the price vector, and the price vector changes: the answer on one pool at one set of prices was
"the self-hosted box plus two cheap APIs, escalating to the frontier tier", and quoting that as the
design is the error this module exists to prevent. `frontier()` enumerates the policies, prices each
one, and returns the ones nothing else dominates; `cheapest_meeting()` picks from that under a quality
floor. A price change is a re-evaluation over the same matrix, never a re-measurement.

## What the rule is, exactly

A policy is a set of **members** and one **escalation tier**. For each item:

  * every member answers;
  * if they all produced an answer and the answers are identical, the policy stops and returns it;
  * otherwise the escalation tier answers, and its answer is the policy's.

**An absent answer breaks the quorum.** A member that abstained, or whose reply did not parse into an
answer, cannot be shown to agree with anything, so the item escalates. This is not a convenience: on
the corpus that motivated the module, 200 of 10,485 cells were malformed, and the 63 from which an
answer could be recovered were graded incorrect in every single case -- so "recovering" them moves
wrong answers into the set the policy stops on. Refusing to guess costs a few extra escalations and
buys a stop set that is 1.1 points more accurate.

**A one-member policy stops on everything**, because there is nothing for one candidate to disagree
with. That is a real policy -- "the cheap tier answers, nobody checks" -- and it is the cheap end of
the frontier rather than a degenerate case to exclude.

## What it refuses to do

**It will not price a policy it cannot price.** If any cell a policy needs carries no cost, the
policy's cost is `None` and it is excluded from the frontier rather than being treated as free. An
unpriced tier that appears free is how a self-hosted candidate wins every comparison it should lose.

**It reports the denominator.** A three-member policy that agrees on eleven items can show a very
high accuracy on agreement, and that number means nothing. `stopped` travels with every point so a
reader can see what the conditional accuracy was computed over, and `min_stopped` refuses the ones
too thin to read.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from typing import Callable

from tierbook.evidence import DEFAULT_SUBJECTS, UNOBSERVED, EvidenceError
from tierbook.outcomes import Cell, OutcomeTable


@dataclass(frozen=True)
class QuorumPolicy:
    """One policy, priced on one matrix. Everything here is observed or arithmetic on the observed."""

    members: tuple[str, ...]
    escalate_to: str
    items: int
    stopped: int                          # items the members agreed on, so no escalation happened
    solved: int                           # items the policy got right, over `items`
    solved_when_stopped: int              # of `stopped`, how many the agreed answer got right
    usd_per_item: float | None            # None when any needed cell is unpriced
    #: The best single member's accuracy over ALL items, which is what the quorum has to beat to be
    #: worth building. On the stopped set every member gave the same answer, so every member is right or
    #: wrong together there and a comparison inside it is vacuous -- the honest baseline is what one
    #: member would have given you on the whole corpus.
    best_member_accuracy: float = 0.0
    #: The largest, over member pairs, of P(both wrong | at least one wrong). High values mean agreement
    #: is a weak certificate: measured over 120 pairs, this correlates -0.791 with the accuracy of the
    #: agreed answer while the stop rate RISES with it, so a correlated quorum stops more often and
    #: worse. `None` for a one-member policy, which has no pair.
    worst_joint_failure: float | None = None
    # Set on a signal-threshold policy, `None` on a quorum. Both shapes live in one dataclass so one
    # frontier can rank them against each other; the field is what tells a reader which mechanism a
    # frontier point came from.
    signal_threshold: float | None = None

    @property
    def mechanism(self) -> str:
        if self.signal_threshold is not None:
            return "signal"
        return "single" if len(self.members) == 1 else "quorum"

    @property
    def stop_rate(self) -> float:
        return self.stopped / self.items if self.items else 0.0

    @property
    def accuracy(self) -> float:
        return self.solved / self.items if self.items else 0.0

    @property
    def accuracy_when_stopped(self) -> float:
        """How often the agreed answer was right. Read it against `stopped`, not on its own."""
        return self.solved_when_stopped / self.stopped if self.stopped else 0.0

    @property
    def wrong_stop_rate(self) -> float:
        """The share of ALL items where the policy stopped and the agreed answer was wrong.

        `stop_rate x (1 - accuracy_when_stopped)`, and it is the number an operator actually feels:
        how often the policy returns a confident wrong answer instead of escalating. A stop rate of 67%
        at 87.8% accuracy-when-stopped is 8.2% of every request answered wrongly with no second look,
        and neither of the two figures it is built from says that on its own.
        """
        return (self.stopped - self.solved_when_stopped) / self.items if self.items else 0.0

    @property
    def agreement_lift(self) -> float:
        """How much better the agreed answer is than the best member would have been anyway.

        This is the number that says whether the quorum does anything. Measured over 120 pairs it runs
        from +17.3% down to +0.8%, and the bottom of that range is a pair of near-duplicate serving
        configurations that stop on 97% of items and add nothing -- **one model wearing two hats**. A
        stop rate cannot tell those apart from a real quorum; this can.
        """
        return self.accuracy_when_stopped - self.best_member_accuracy

    @property
    def priced(self) -> bool:
        return self.usd_per_item is not None


def _cell(table: OutcomeTable, item: str, tier: str) -> Cell:
    return table.cells.get(item, {}).get(tier) or Cell(UNOBSERVED, None)


#: The signature every per-item stop rule accepts: given ONE item's per-member answers (`None` for a member
#: that abstained or produced nothing parseable), decide whether to stop and, if so, which answer to select.
#: Returns the SELECTED ANSWER to stop, or `None` to escalate. `agreement` below is the DEFAULT this project
#: measured, not the only shape the signature can hold.
#:
#: **Round 5 narrowed this contract, closing the gap round 4 left.** Round 4's `decide_from_score` still let a
#: rule read the WHOLE matrix (`table, members, items`), and two reviewers showed that a rule reading anything
#: beyond this one item's member answers sees DIFFERENT input at fit time (the real table: real item ids, real
#: cell status/cost, the escalation tier's own cell, every other item) than at runtime (a synthetic one-item
#: table built from nothing but the answers heard so far). A rule that reads cell status, an item id, a
#: batch-wide quantile, or the escalation tier's cell can therefore certify one accuracy and execute a different
#: policy -- not because either call site has a bug, but because the CONTRACT let a rule depend on something
#: the two call sites could not agree to supply identically.
#:
#: Narrowing the signature to exactly `Mapping[member, answer] -> answer | None` removes THAT specific
#: divergence -- there is no batch, no item id, no escalation cell, no OTHER item in the argument for a rule to
#: read even if it wanted to, so `evaluate`'s call and `router.decide_from_score`'s call for the same member
#: answers are the identical call on the identical shape of input.
#:
#: **What this narrowing does and does not guarantee (round 6, after a reviewer showed the difference matters).**
#: It bounds what a rule's ARGUMENT can contain; it cannot bound what the rule's BODY reads. Python cannot stop
#: a closure from reading a global counter, `random.random()`, or module state that changes between calls, and
#: a rule that does will legitimately score one way during `evaluate`'s search (called many times per item) and
#: decide another way at runtime (called once per live request) -- the earlier wording here ("structurally
#: impossible", "provably the same computation") overstated what the type signature alone can promise. The
#: actual guarantee is narrower and is a contract on the RULE, not a property the signature enforces on its
#: own: **for any per-item stop rule that is a pure, deterministic function of its `Mapping[member, answer]`
#: argument, `evaluate`'s batch scoring and `router.decide_from_score`'s runtime decision compute the same
#: result for the same member answers.** Writing a rule that is pure and deterministic is the caller's promise
#: to keep, the same way `evidence.py`'s closed vocabularies are a promise about what a value MEANS rather than
#: something Python enforces. `Router.fit` adds one cheap, best-effort check for this (see its docstring): it
#: cannot catch a rule that changes ITS OWN behaviour after `fit` returns (a global flipped later, an external
#: clock), only a rule whose stopped-items-and-answers already disagree with itself within `fit`.
#:
#: **What this deliberately leaves out.** A rule that genuinely needs the whole batch -- a quantile over the
#: corpus, a signal keyed by item id, anything that is a property of the CORPUS rather than of one question --
#: is out of scope for this injection point. That is a real and different kind of policy, and this project
#: already has a place for it: `evaluate_signal`/`enumerate_signal_policies`, which take a `signal: dict[item,
#: float]` computed once over the whole corpus ahead of time and read it per item. A caller whose rule needs
#: batch context builds that signal separately and uses THAT mechanism; it does not belong behind
#: `ItemStopRule`, which promises a per-item determinism this project can check for, at best, by comparing two
#: calls -- never guarantee for an arbitrary Python callable.
#:
#: Named `ItemStopRule` rather than the bare `StopRule` an earlier version used, because `router.py` used to
#: declare a SECOND stop rule under that name with an incompatible signature; `router.py`'s runtime derivation
#: now shares this exact signature instead of a separate one, so there is only one shape left in the whole
#: project. `StopRule` below is a deprecated alias for any importer who held the pre-round-2 bare name.
ItemStopRule = Callable[[Mapping[str, "str | None"]], "str | None"]
#: Deprecated alias, kept for any importer who held `quorum.StopRule` before round 2 renamed it to `ItemStopRule`.
StopRule = ItemStopRule


def agreement(answers: Mapping[str, str | None]) -> str | None:
    """Select the answer every member gave, when they all gave one and it is the same one; otherwise escalate.

    Agreement requires every member to have produced an answer AND all answers to be identical. See
    the module docstring for why an absent answer escalates rather than being filled in.

    **The default this project measured, not the only rule the signature can hold.** The module docstring traces
    this shape to a fold-derived finding ("Escalation does not branch") and
    `router.Certificate.rules_are_fold_derived=True` discloses that it was chosen by reading this project's own
    fold. `evaluate`'s `stop_rule` parameter (and `router.decide_from_score`, which calls the SAME function) is
    where a different study's per-item rule -- a majority, a tie-breaking preference -- can be expressed
    without editing this function.
    """
    values = list(answers.values())
    if all(v is not None for v in values) and len(set(values)) == 1:
        return values[0]
    return None


def joint_failure(table: OutcomeTable, a: str, b: str, items: list[str]) -> float | None:
    """`P(both wrong | at least one wrong)` for a pair, which is what makes agreement worth having.

    Measured over 120 pairs on one corpus, this correlates **-0.791** with the accuracy of the answer a
    quorum stops on, while the stop rate *rises* with it -- so a correlated pair stops more often and
    worse, and a stop rate quoted on its own hides that entirely.

    It is deliberately measured rather than inferred from whether the candidates share weights. On the
    same corpus, pairs sharing weights disagreed on 2.7% to 35.7% of answers and pairs from different
    model families on 9.4% to 46.3%, with **identical medians** (31.9% and 31.8%) -- two frontier models
    of one family agreed more closely than two serving configurations of one open-weights model. "Shares
    weights" predicts nothing; the matrix says what the correlation actually is.

    `None` when no item is wrong for either, which is not a low correlation but an absent measurement.
    """
    both = sum(1 for i in items
               if not _cell(table, i, a).solved and not _cell(table, i, b).solved)
    either = sum(1 for i in items
                 if not _cell(table, i, a).solved or not _cell(table, i, b).solved)
    return both / either if either else None


def rule_identity(rule: Callable) -> str:
    """A name for an injected rule to put in a refusal message or a report. **Display only, and deprecated for
    anything else**: round 2 used a shared name as PROOF that two independently-declared callables behaved
    alike, and a reviewer found that a name is self-declared and proves nothing -- round 3 removed the
    cross-check this fed. Kept under its old name only because deleting it outright breaks any importer who
    held it; do not reintroduce a check that compares two of these strings and treats equality as equivalence.
    """
    return getattr(rule, "__qualname__", repr(rule))


def check_selected_answer(selected: object, stop_rule: Callable, member_answers: Mapping[str, "str | None"],
                          *, item: str = "") -> None:
    """Refuse a per-item stop rule's return value that is not a genuine commitment to stop.

    Two things are checked, and both apply at the ONE place both `evaluate` and `router.decide_from_score` call
    the rule, so there is one check rather than two drifting copies:

    * the value itself must be `None` (escalate) or a non-empty answer string (stop, and select this one).
      Trusting it unchecked is how a rule returning the OLD `(stopped, escalated)` two-list shape, or one
      "stopping" on an empty string, would corrupt `evaluate`'s bill and its accuracy silently.
    * a SELECTED answer must be one a member actually gave. A round-6 review showed `decide_from_score` would
      otherwise accept an answer no member produced (a rule inventing `"C"` for member answers it had not seen
      while fitting, say) at runtime, while `evaluate`'s own scoring only ever caught that indirectly, later,
      through `_answer_is_correct`'s "no member's cell recorded" refusal -- a rule could clear `fit` on a
      fitting table that never happened to trigger that later check, then invent an answer at runtime that
      would have failed it. Checking membership HERE, at the point the rule's answer is first read, makes
      `evaluate` and `decide_from_score` refuse identically rather than one of them refusing later or not at
      all.
    """
    if selected is None:
        return
    if not isinstance(selected, str) or not selected:
        where = f" for item {item!r}" if item else ""
        raise EvidenceError(
            f"stop_rule {rule_identity(stop_rule)!r} returned {selected!r}{where}, which is neither None "
            f"(escalate) nor a non-empty answer string (stop, and select this one)")
    attested = {v for v in member_answers.values() if v is not None}
    if selected not in attested:
        where = f" for item {item!r}" if item else ""
        raise EvidenceError(
            f"stop_rule {rule_identity(stop_rule)!r} selected {selected!r}{where}, which is not one of the "
            f"members' own answers {sorted(attested)}. A rule may only select an answer a member actually "
            f"gave -- inventing one is not a stop")


def stopped_answers_for(table: OutcomeTable, members: tuple[str, ...], subject: list[str],
                        stop_rule: ItemStopRule) -> dict[str, str]:
    """Apply `stop_rule` to each item in `subject`, one at a time, returning `{item: selected_answer}` for the
    ones it stops on -- the ONE per-item loop `evaluate` scores from and `Router.fit` re-runs once, at the end,
    as a cheap check for a non-deterministic or stateful rule (see `Router.fit`'s docstring). Public, and kept
    as the single place this loop is written, so the search and the check that follows it can never drift into
    two different readings of "what did this rule do here".
    """
    stopped_answers: dict[str, str] = {}
    for item in subject:
        answers = {m: _cell(table, item, m).answer for m in members}
        selected = stop_rule(answers)
        check_selected_answer(selected, stop_rule, answers, item=item)
        if selected is not None:
            stopped_answers[item] = selected
    return stopped_answers


def evaluate(table: OutcomeTable, members: tuple[str, ...], escalate_to: str, *,
             prices: dict[str, float] | None = None, items: list[str] | None = None,
             stop_rule: ItemStopRule = agreement) -> QuorumPolicy:
    """Price and score one policy on the matrix.

    `prices` is a per-item cost per tier, overriding the matrix's own recorded cost. That override is
    the whole point of the separation: re-pricing a policy must not require re-running it, so a new
    rate card is an argument here and not a new measurement.

    `stop_rule` decides ONE item at a time (`quorum.ItemStopRule`: `{member: answer} -> answer | None`).
    `evaluate` calls it once per item, applying it to exactly this policy's members' answers for that item --
    the same call, on the same shape of input, that `router.decide_from_score` makes at runtime. For a rule
    that is a PURE, DETERMINISTIC function of that input, this makes the two sides compute the same result; see
    `ItemStopRule`'s docstring for what that promise does and does not cover, and why the signature stops there.
    Defaults to `agreement` -- unanimity among `members` -- which is the shape this module's own docstring
    traces to one fold's measurement (TB-034). A stopped item's correctness is read off the SELECTED ANSWER
    (below), not off "did any member happen to solve it" -- the two coincide exactly when the rule is
    unanimous, which is why `agreement`'s own numbers do not move, and diverge for a rule that is not, which is
    the gap round 2 left open.
    """
    subject = list(items if items is not None else table.items)
    # The caller's own `items` can carry a duplicate; that is not the injected rule's doing, so it gets its own
    # message rather than being blamed on `stop_rule` when the duplicate resurfaces in its output.
    if len(subject) != len(set(subject)):
        dupes = sorted({i for i in subject if subject.count(i) > 1})
        raise EvidenceError(f"items contains duplicate id(s) {dupes}, so scoring it would count that item more "
                           f"than once regardless of what any stop_rule returns")
    stopped_answers = stopped_answers_for(table, members, subject, stop_rule)
    stopped = list(stopped_answers)
    escalated = [i for i in subject if i not in stopped_answers]

    def cost_of(item: str, tier: str) -> float | None:
        if prices is not None:
            return prices.get(tier)
        return _cell(table, item, tier).usd

    total = 0.0
    unpriced = False
    for item in subject:
        for tier in members:
            usd = cost_of(item, tier)
            if usd is None:
                unpriced = True
            else:
                total += usd
    for item in escalated:
        usd = cost_of(item, escalate_to)
        if usd is None:
            unpriced = True
        else:
            total += usd

    def _answer_is_correct(item: str, answer: str) -> bool:
        """Whether the rule's SELECTED answer for `item` is the correct one.

        Read off whichever member's cell carries that exact answer and was itself marked solved -- correctness is
        a property of the answer matching the item's own ground truth, not of which member said it, so any member
        recording that string as solved settles it for every other member who gave the same string. This is what
        makes the check correct for `agreement` (every stopper gave the identical answer, so this is exactly "any
        member solved it", unchanged from round 2) and for a rule that is NOT unanimous (a majority's answer is
        scored by whether THAT answer was right, not by whether some other, dissenting member happened to be).

        **One remaining ambiguity is refused rather than guessed at:** if two members recorded the identical
        answer string with DIFFERENT `solved` verdicts, the table itself contradicts itself about whether that
        string is correct, and picking one verdict via `any` would silently prefer whichever member happened to
        be listed (or graded) as solved. The OTHER ambiguity this used to refuse here -- a selected answer no
        member's cell recorded at all -- is now caught earlier, at `check_selected_answer` (round 6): that check
        runs on every selection before it can ever reach `stopped_answers`, so by the time this function runs,
        `answer` is already known to be one of the members' own non-`None` answers for this item.
        """
        verdicts = {_cell(table, item, m).solved for m in members if _cell(table, item, m).answer == answer}
        if len(verdicts) > 1:
            raise EvidenceError(
                f"item {item!r} has members recording {answer!r} with different solved verdicts ({verdicts}), so "
                f"whether {answer!r} is correct depends on which member is asked. That is a contradiction in the "
                f"table, not something scoring can resolve by picking one member's verdict over another's")
        return verdicts.pop()

    right_stopped = sum(1 for i in stopped if _answer_is_correct(i, stopped_answers[i]))
    right_escalated = sum(1 for i in escalated if _cell(table, i, escalate_to).solved)

    best_member = max((sum(1 for i in subject if _cell(table, i, m).solved) for m in members),
                      default=0) / len(subject) if subject else 0.0
    pair_jf = [j for a, b in combinations(members, 2)
               if (j := joint_failure(table, a, b, subject)) is not None]

    return QuorumPolicy(
        members=tuple(members),
        escalate_to=escalate_to,
        items=len(subject),
        stopped=len(stopped),
        solved=right_stopped + right_escalated,
        solved_when_stopped=right_stopped,
        usd_per_item=None if unpriced or not subject else total / len(subject),
        best_member_accuracy=best_member,
        worst_joint_failure=max(pair_jf) if pair_jf else None,
    )


def enumerate_policies(table: OutcomeTable, *, candidates: list[str], escalate_to: list[str],
                       max_members: int = 4, prices: dict[str, float] | None = None,
                       items: list[str] | None = None, min_stopped: int = 30,
                       stop_rule: ItemStopRule = agreement) -> list[QuorumPolicy]:
    """Every policy worth pricing, with the unreadable ones dropped.

    A member is never also the escalation tier: escalating to a candidate that already answered and
    was overruled by the disagreement is not a policy, it is a no-op that would score as one.

    `min_stopped` drops policies whose stop set is too small for `accuracy_when_stopped` to mean
    anything. A one-member policy stops on everything so it is never dropped by this, which is
    correct -- its conditional accuracy is just its accuracy.

    `stop_rule` is passed through to `evaluate` unchanged; see its docstring.
    """
    out: list[QuorumPolicy] = []
    for size in range(1, max_members + 1):
        for members in combinations(candidates, size):
            for tier in escalate_to:
                if tier in members:
                    continue
                policy = evaluate(table, members, tier, prices=prices, items=items, stop_rule=stop_rule)
                if policy.stopped < min_stopped and policy.stopped != policy.items:
                    continue
                out.append(policy)
    return out


def evaluate_signal(table: OutcomeTable, member: str, escalate_to: str, *,
                    signal: dict[str, float], about: str, threshold: float,
                    probe_usd: float = 0.0,
                    prices: dict[str, float] | None = None,
                    items: list[str] | None = None,
                    subjects: tuple[str, ...] = ()) -> QuorumPolicy:
    """One candidate answers; a per-item confidence signal decides whether to escalate.

    This is the third mechanism, and it exists here rather than in its own module so that all three
    end up on **one** frontier. Leaving it out is how a comparison error survives: a quorum was once
    reported as the recommended policy after being measured only against a probe threshold and against
    the frontier tier answering everything, while a single mid-priced candidate answering everything
    dominated it on both axes and was never enumerated. A frontier that cannot express a mechanism
    cannot rule it out either.

    **`about` is required and is checked, not recorded.** DEFECT this closes: this took a bare `dict[str, float]` with
    nothing saying what the numbers were about, so a topic classifier and a confidence readout arrived here identically
    and produced policies described identically. They are not interchangeable, and the measurement is brutal: at one
    layer the same readout named the item's field at 0.7593 against a chance of 0.1429 and predicted its own error at
    0.4227, *below* the 0.5 a coin gets.

    Named `about` rather than `subject` because "subject" already means a candidate in this package, and this function's
    own body used it for a list of item ids -- that local is renamed to `item_ids` here, which is what it holds. Three
    meanings of one word in one file is how the wrong one gets read.

    A signal policy is strictly more expressive than a one-member quorum: a lone candidate always
    "agrees" with itself and so can never escalate, whereas a threshold escalates exactly the items
    the signal flags. `threshold` escalates when `signal[item] >= threshold`, so the signal is an
    uncertainty (higher means less sure); `probe_usd` is what reading it costs per item, which is not
    zero when the signal comes from an extra call.

    `subjects` is the vocabulary `about` is checked against. **Declared here rather than fixed in the module**, so a
    study whose signal is about something `evidence.DEFAULT_SUBJECTS` does not name can still build a policy. Empty
    falls back to `DEFAULT_SUBJECTS`, which keeps every existing caller working while making the default visibly a
    default (the same move F141 made for `decide.STATE_VARS`, applied to the one closed vocabulary this module still
    checked membership against after F140).
    """
    vocabulary = subjects or DEFAULT_SUBJECTS
    if about not in vocabulary:
        raise EvidenceError(
            f"about={about!r} is not one of {vocabulary}. The signal has to say what it is about, because a policy "
            f"built on one thing and reported as built on another is the failure this argument exists to prevent. "
            f"What it is NOT is a judgement about which of them is worth escalating on: this function used to refuse "
            f"everything except competence and difficulty, on the strength of one corpus, which made a study "
            f"measuring topic to predict competence unable to say so. Whether the signal earns its place is decided "
            f"by what is measured about it, not by which name it carries. Widen `subjects` if this signal is about "
            f"something {vocabulary} does not name")
    item_ids = list(items if items is not None else table.items)

    def cost_of(item: str, tier: str) -> float | None:
        if prices is not None:
            return prices.get(tier)
        return _cell(table, item, tier).usd

    kept, escalated = [], []
    for item in item_ids:
        value = signal.get(item)
        # An item with no signal reading escalates, for the same reason an absent answer breaks a
        # quorum: an unread signal is not a confident one, and defaulting it to "sure" would send the
        # unmeasured items to the cheap tier, which is the direction that flatters the policy.
        if value is None or value >= threshold:
            escalated.append(item)
        else:
            kept.append(item)

    total, unpriced = 0.0, False
    for item in item_ids:
        usd = cost_of(item, member)
        if usd is None:
            unpriced = True
        else:
            total += usd + probe_usd
    for item in escalated:
        usd = cost_of(item, escalate_to)
        if usd is None:
            unpriced = True
        else:
            total += usd

    right_kept = sum(1 for i in kept if _cell(table, i, member).solved)
    right_escalated = sum(1 for i in escalated if _cell(table, i, escalate_to).solved)
    return QuorumPolicy(
        members=(member,),
        escalate_to=escalate_to,
        items=len(item_ids),
        stopped=len(kept),
        solved=right_kept + right_escalated,
        solved_when_stopped=right_kept,
        usd_per_item=None if unpriced or not item_ids else total / len(item_ids),
        signal_threshold=threshold,
    )


def enumerate_signal_policies(table: OutcomeTable, *, candidates: list[str], escalate_to: list[str],
                              signal: dict[str, float], about: str,
                              quantiles: tuple[float, ...] = (
                                  0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
                              probe_usd: float = 0.0, prices: dict[str, float] | None = None,
                              items: list[str] | None = None,
                              subjects: tuple[str, ...] = ()) -> list[QuorumPolicy]:
    """Threshold policies at quantiles of the signal, so the sweep does not depend on its units.

    Quantiles rather than raw values because a signal's scale is arbitrary -- an entropy, a margin and
    a predicted probability have no common range -- and a sweep in raw units silently spends most of
    its points in a region no item occupies.
    """
    subject = list(items if items is not None else table.items)
    values = sorted(v for v in (signal.get(i) for i in subject) if v is not None)
    if not values:
        return []
    out = []
    for q in quantiles:
        idx = min(len(values) - 1, int(q * len(values)))
        thr = values[idx] if q < 1.0 else values[-1] + 1.0
        for member in candidates:
            for tier in escalate_to:
                if tier == member:
                    continue
                out.append(evaluate_signal(table, member, tier, signal=signal, about=about, threshold=thr,
                                           probe_usd=probe_usd, prices=prices, items=items, subjects=subjects))
    return out


def canonical(policies: list[QuorumPolicy]) -> list[QuorumPolicy]:
    """Collapse policies that differ only in a choice that never took effect.

    A policy that never escalates has an escalation tier in name only: with eight candidates that is
    eight rows on a frontier, identical in accuracy and cost, differing in a field no request ever
    read. Left in, they crowd out the rows that represent a real choice and inflate any count of "how
    many frontier points use mechanism X", which is a statistic this module reports.

    Two policies are the same decision when their members, accuracy and cost agree and neither ever
    escalated. The one kept is the first by escalation-tier name, so the choice is deterministic and a
    reader is not invited to read meaning into which survived.
    """
    seen: dict[tuple, QuorumPolicy] = {}
    out: list[QuorumPolicy] = []
    for p in sorted(policies, key=lambda q: (q.members, q.escalate_to)):
        if p.stopped != p.items:
            out.append(p)
            continue
        key = (p.members, p.signal_threshold, p.solved, p.usd_per_item)
        if key not in seen:
            seen[key] = p
            out.append(p)
    return out


def frontier(policies: list[QuorumPolicy]) -> list[QuorumPolicy]:
    """The policies nothing else beats on both accuracy and cost.

    Unpriced policies are excluded rather than ranked, because a policy whose cost is unknown cannot
    be said to be dominated or dominating. Policies whose escalation tier never fired are collapsed
    first, so one real decision appears once.
    """
    priced = [p for p in canonical(policies) if p.priced]
    keep: list[QuorumPolicy] = []
    for p in priced:
        if any(q is not p and q.accuracy >= p.accuracy and q.usd_per_item <= p.usd_per_item
               and (q.accuracy > p.accuracy or q.usd_per_item < p.usd_per_item)
               for q in priced):
            continue
        keep.append(p)
    return sorted(keep, key=lambda p: p.usd_per_item)


def cheapest_meeting(policies: list[QuorumPolicy], *, accuracy_floor: float) -> QuorumPolicy | None:
    """The cheapest policy that clears a quality floor, or `None` if none does.

    This is the operator-facing shape of the question. A floor is a sentence an owner can say -- "I
    will not go below this accuracy" -- where a weight on cost against quality is not.
    """
    # Canonicalised for the same reason `frontier` is: two never-escalating policies that differ only
    # in an escalation tier no request reached are one decision, and returning either at random makes
    # two runs of the same data look like they disagree. That false difference showed up in a
    # reproducibility check before this line existed.
    eligible = [p for p in canonical(policies) if p.priced and p.accuracy >= accuracy_floor]
    return min(eligible, key=lambda p: (p.usd_per_item, p.members, p.escalate_to)) if eligible else None
