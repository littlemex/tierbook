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


#: The signature every stop rule `evaluate` accepts must have: given the matrix, the member set and the items to
#: decide over, return a mapping from each item this rule decides to STOP on to the ANSWER it selects for that
#: item. An item absent from the returned mapping escalates. `agreement` below is the DEFAULT this project
#: measured, not the only shape the signature can hold.
#:
#: **Round 3 changed what this returns.** It used to be `(stopped, escalated)` -- two lists, membership only. That
#: was enough to bill a policy but not to SCORE one honestly: `evaluate` read a stopped item's correctness as "did
#: any member solve it", which is only a safe reading when the stoppers are unanimous, as `agreement`'s stop set
#: always is by construction. A rule that stops on some OTHER agreement notion (a majority, say) could report an
#: item as stopped without the members agreeing, and the old signature gave `evaluate` no way to know WHICH answer
#: the rule actually meant to return -- so it kept reading "any member correct", scoring "did the majority side
#: happen to include a correct member" where it meant to score "was the majority's own answer correct". Returning
#: the selected answer closes that gap: `evaluate` now scores the answer itself, and `agreement`'s own behaviour
#: (below) is unchanged by the wider signature -- unanimity means the "selected answer" IS the one answer all
#: members gave, so today's accuracy comes out identical.
#:
#: Named `ItemStopRule` rather than the bare `StopRule` an earlier version used, because `router.py` declares a
#: SECOND stop rule under that name with an incompatible signature -- one partitions a whole item set at once for
#: scoring, the other decides one streaming request's next action given partial answers -- and one name for two
#: shapes is how the wrong one gets imported. `StopRule` below is a deprecated alias for any importer who held
#: that name.
ItemStopRule = Callable[[OutcomeTable, tuple[str, ...], list[str]], dict[str, str]]
#: Deprecated alias, kept for any importer who held `quorum.StopRule` before round 2 renamed it to `ItemStopRule`
#: to stop colliding with `router.StopRule`'s (also renamed) incompatible signature.
StopRule = ItemStopRule


def agreement(table: OutcomeTable, members: tuple[str, ...], items: list[str]) -> dict[str, str]:
    """Map each item the members agree on to the answer they agree on; leave the rest out (they escalate).

    Agreement requires every member to have produced an answer AND all answers to be identical. See
    the module docstring for why an absent answer escalates rather than being filled in.

    **The default `evaluate` runs, not the only rule the signature can hold.** The module docstring traces this shape
    to a fold-derived finding ("Escalation does not branch") and `router.Certificate.rules_are_fold_derived=True`
    disclosed it without making it injectable -- disclosure and injectability are different things, and TB-034 named
    the gap. `evaluate`'s `stop_rule` parameter is where a different study's stop rule (escalate on a signal instead
    of on disagreement, stop on a majority rather than on unanimity) can be expressed without editing this function.
    """
    out: dict[str, str] = {}
    for item in items:
        answers = [_cell(table, item, m).answer for m in members]
        if all(a is not None for a in answers) and len(set(answers)) == 1:
            out[item] = answers[0]
    return out


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


def _identity_of(rule: Callable) -> str:
    """A name for an injected rule to put in a refusal message. Not a proof of anything about the rule -- see
    `router.Rule` for why this project no longer treats a shared name as evidence that two callables behave
    alike. This is display only."""
    return getattr(rule, "__qualname__", repr(rule))


def _check_stopped_answers(stopped_answers: dict[str, str], subject: list[str], stop_rule: Callable) -> None:
    """Refuse an injected rule whose output cannot be scored honestly.

    Trusting the rule's output unchecked is how a rule inventing an id nobody asked about, or "stopping" on an
    empty answer, would corrupt `evaluate`'s bill, its accuracy, and `enumerate_policies`'s `min_stopped` logic
    silently. The check is purely structural: it says nothing about whether the PARTITION or the ANSWERS are good,
    only that every key is one of the items asked for and every value is an answer the rule is actually selecting.
    """
    invalid_keys = sorted(set(stopped_answers) - set(subject))
    if invalid_keys:
        raise EvidenceError(
            f"stop_rule {_identity_of(stop_rule)!r} returned {invalid_keys} as stopped, which were not among the "
            f"{len(subject)} items asked for")
    empty = sorted(k for k, v in stopped_answers.items() if not v)
    if empty:
        raise EvidenceError(
            f"stop_rule {_identity_of(stop_rule)!r} returned {empty} as stopped with no answer (falsy). Stopping "
            f"on an item means committing to an answer for it; a rule with nothing to commit should leave that "
            f"item out of the mapping so it escalates instead")


def evaluate(table: OutcomeTable, members: tuple[str, ...], escalate_to: str, *,
             prices: dict[str, float] | None = None, items: list[str] | None = None,
             stop_rule: ItemStopRule = agreement) -> QuorumPolicy:
    """Price and score one policy on the matrix.

    `prices` is a per-item cost per tier, overriding the matrix's own recorded cost. That override is
    the whole point of the separation: re-pricing a policy must not require re-running it, so a new
    rate card is an argument here and not a new measurement.

    `stop_rule` maps each item it stops on to the answer it selects; an item it leaves out escalates. Defaults to
    `agreement` -- unanimity among `members` -- which is the shape this module's own docstring traces to one
    fold's measurement (TB-034). **Declared here rather than fixed in the function**, so a study whose stop rule
    is not unanimity (a majority, a signal-gated escalation) can be scored on the same frontier without editing
    this function, and scored HONESTLY: a stopped item's correctness is read off the SELECTED ANSWER (below), not
    off "did any member happen to solve it" -- the two coincide exactly when the rule is unanimous, which is why
    `agreement`'s own numbers do not move, and diverge for a rule that is not, which is the gap round 2 left open.
    """
    subject = list(items if items is not None else table.items)
    # The caller's own `items` can carry a duplicate; that is not the injected rule's doing, so it gets its own
    # message rather than being blamed on `stop_rule` when the duplicate resurfaces in its output.
    if len(subject) != len(set(subject)):
        dupes = sorted({i for i in subject if subject.count(i) > 1})
        raise EvidenceError(f"items contains duplicate id(s) {dupes}, so scoring it would count that item more "
                           f"than once regardless of what any stop_rule returns")
    stopped_answers = stop_rule(table, members, subject)
    _check_stopped_answers(stopped_answers, subject, stop_rule)
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
        """
        return any(_cell(table, item, m).answer == answer and _cell(table, item, m).solved for m in members)

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
