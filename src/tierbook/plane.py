"""Why outcomes arrive on their own plane, and cannot reach the policy that is deciding.

An outcome -- whether the answer was right, what it cost, how long it took -- is knowable only after the decision it
judges. Something has to carry it back, and the obvious design is the one that destroys the log: let the callback
that receives an outcome update the thresholds the router is using. Then decision N behaves according to how many
outcomes happened to arrive before it, which is a function of network timing, so **replaying the log does not
reproduce the decisions**, and a policy that cannot be replayed cannot be audited or compared against another.

So this module separates three things that a single callback would collapse:

* **Observations append and do nothing else.** `register` refuses an observer that could reach a policy, by
  inspecting what it accepts -- because "the observer must not mutate the scorer" written in a docstring is a rule,
  and a rule is what gets broken by the next person who has a good reason.
* **A calibration snapshot is immutable, and its identity is derived from the observations that produced it.** An
  id somebody supplies is an id somebody can reuse after changing the contents, and then two different sets of
  numbers wear one name in the ledger.
* **A live policy names the snapshot it read.** One policy version may not span two snapshots. If the numbers
  change, the version changes -- otherwise two decisions credited to one policy were made with different constants
  and nothing downstream can separate them.

The cost of this separation is that the loop closes slowly: an outcome observed now changes behaviour only at the
next snapshot, and that is the price of a log that can be replayed. Nothing here makes the loop faster; it makes it
honest, and `staleness` reports the delay rather than hiding it.
"""
from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass, field

#: What an observation can say about how it ended. Closed, because the interesting analyses are all conditional on
#: this and an open string cannot be grouped over. `unobserved` is a first-class outcome: a request whose fate is
#: genuinely unknown must be representable, or it gets recorded as a failure and biases every rate computed from the
#: log.
TERMINAL_STATES = ("answered", "escalated", "aborted", "unobserved")

#: Names an observer may not accept. Each is a handle through which a callback could change what the router is
#: currently doing, which is the one thing this plane exists to prevent.
FORBIDDEN_HANDLES = ("policy", "scorer", "picker", "router", "gate", "threshold", "thresholds", "snapshot")


class Unreplayable(Exception):
    """Something was wired so that a replay of the log would not reproduce the decisions. Raised at registration or
    construction rather than at replay time, because by the time a replay disagrees the traffic is long gone and
    there is no way to tell which of the two runs was the real one."""


@dataclass(frozen=True)
class Outcome:
    """One outcome, arriving after the decision it judges, naming what it judges.

    All three identifiers are required. `request_id` joins it to the traffic, `decision_id` to the decision, and
    `policy_version` to the rule that made it -- and without the third an outcome gets credited to whatever policy
    is current when somebody reads the log, which silently attributes an old policy's results to a new one.
    """

    request_id: str
    decision_id: str
    policy_version: str
    terminal_state: str
    correct: bool | None = None
    cost_usd: float | None = None
    latency_s: float | None = None

    def __post_init__(self) -> None:
        for name in ("request_id", "decision_id", "policy_version"):
            if not getattr(self, name):
                raise Unreplayable(
                    f"{name} is empty, so this outcome cannot be joined to what produced it. An unattributable "
                    f"outcome is worse than a missing one: it still counts in every rate computed over the log")
        if self.terminal_state not in TERMINAL_STATES:
            raise Unreplayable(f"{self.terminal_state!r} is not one of {TERMINAL_STATES}; an open-ended state cannot "
                               f"be grouped over, and every rate this log exists to compute is conditional on it")
        if self.terminal_state == "unobserved" and self.correct is not None:
            raise Unreplayable(
                f"terminal_state is 'unobserved' but correct={self.correct!r}. Those contradict: if correctness is "
                f"known the request was observed, and recording both lets an unobserved request be counted as a "
                f"labelled one")


def register(observer) -> None:
    """Refuse an observer that could reach the thing it is observing.

    Checked by inspection rather than trusted, because the failure it prevents is invisible: an observer that
    adjusts a live threshold produces a system that works, performs plausibly, and cannot be replayed. There is no
    error and no log line -- the only symptom is that a re-run of the same traffic decides differently.
    """
    if not callable(observer):
        raise Unreplayable(f"{observer!r} is not callable, so nothing will deliver outcomes to it and the plane will "
                           f"be silently empty rather than wrong -- which is harder to notice")
    try:
        params = inspect.signature(observer).parameters
    except (TypeError, ValueError):  # a builtin or C callable exposes no signature
        raise Unreplayable(f"{observer!r} exposes no signature, so it cannot be checked for a handle to the policy; "
                           f"an unchecked observer is admitted on trust, and trust is what this refuses") from None
    reachable = sorted(n for n in params if n.lower() in FORBIDDEN_HANDLES)
    if reachable:
        raise Unreplayable(
            f"the observer accepts {reachable}, which is a handle to what the router is currently using. An observer "
            f"that can change a live threshold makes decision N depend on how many outcomes arrived before it -- a "
            f"function of network timing -- so replaying the log stops reproducing the decisions. Append to the "
            f"store and let a calibration job build the next snapshot")
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        raise Unreplayable(
            "the observer accepts **kwargs, so the check above cannot see what it will be handed. A signature that "
            "accepts anything is a signature that accepts a policy")


@dataclass(frozen=True)
class Calibration:
    """An immutable set of constants, and the observations that produced them.

    `snapshot_id` is a property rather than a field: an id somebody supplies is an id somebody can keep after
    changing the contents, and then the ledger holds two different sets of numbers under one name and every
    comparison across them is meaningless.

    `built_from` is a closed range on purpose. A snapshot built from "everything up to now" is not reproducible --
    "now" moves -- so it cannot be rebuilt to check a claim made from it.
    """

    constants: dict[str, float]
    built_from: tuple[str, str]
    observation_count: int

    def __post_init__(self) -> None:
        if not self.constants:
            raise Unreplayable("a snapshot with no constants is not a snapshot; a policy reading it would fall back "
                               "to defaults, which are numbers nobody measured wearing the name of ones that were")
        lo, hi = self.built_from
        if not lo or not hi:
            raise Unreplayable(
                f"built_from={self.built_from!r} is not closed at both ends. A snapshot built from 'everything up to "
                f"now' cannot be rebuilt, because 'now' has moved, so no claim made from it can be rechecked")
        if lo > hi:
            raise Unreplayable(f"built_from={self.built_from!r} runs backwards")
        if self.observation_count <= 0:
            raise Unreplayable("a snapshot over zero observations has constants that came from somewhere other than "
                               "the observations it names")

    @property
    def snapshot_id(self) -> str:
        """Derived from the contents, so it cannot be kept across a change to them."""
        h = hashlib.sha256()
        for k in sorted(self.constants):
            h.update(f"{k}={self.constants[k]!r};".encode())
        h.update(f"{self.built_from[0]}..{self.built_from[1]}#{self.observation_count}".encode())
        return h.hexdigest()[:24]

    def constant(self, name: str) -> float:
        try:
            return self.constants[name]
        except KeyError:
            raise Unreplayable(f"{name!r} is not in this snapshot {sorted(self.constants)}; a policy that filled it "
                               f"in from a default would be running on a number this snapshot cannot account "
                               f"for") from None


@dataclass(frozen=True)
class Reading:
    """A policy version paired with the snapshot it read. What makes the pair auditable is that it cannot change."""

    policy_version: str
    snapshot_id: str

    def __post_init__(self) -> None:
        if not self.policy_version or not self.snapshot_id:
            raise Unreplayable("a reading needs both a policy version and a snapshot id; either alone says which "
                               "half of the pair produced a decision and leaves the other unknowable")


def mixtures(readings: list[Reading]) -> dict[str, list[str]]:
    """Which policy versions name more than one set of constants, and which.

    The FACT, separated from what to do about it, because two callers need the same fact and must act on it
    differently: a caller about to decide must not proceed at all, and a log reader must still return the rows it
    holds. Written once, so the two policies cannot drift apart -- which is what happened when the reader grew its
    own copy of this grouping and the two implementations were one edit away from disagreeing about what a mixture
    is.

    There is no branch here for a reading with no snapshot: `Reading` refuses one, so a row that predates the
    mechanism naming its snapshot cannot become a reading at all and is filtered where it is read. That is the
    earlier and better place for it -- an unknown snapshot is not a *different* snapshot, and counting it as
    different would report every history spanning the change as a mixture.
    """
    per_version: dict[str, set] = {}
    for r in readings:
        per_version.setdefault(r.policy_version, set()).add(r.snapshot_id)
    return {v: sorted(s) for v, s in per_version.items() if len(s) > 1}


def refuse_drift(readings: list[Reading]) -> None:
    """Refuse one policy version that read two different snapshots.

    This is the check the whole module builds towards. A version spanning two snapshots means two decisions credited
    to one policy were made with different constants, and no analysis over the log can separate them -- the log looks
    complete and the comparison it supports is between two things that were never one policy. If the numbers change,
    the version changes.
    """
    mixed = mixtures(readings)
    if mixed:
        version, ids = sorted(mixed.items())[0]
        raise Unreplayable(
            f"policy version {version!r} read snapshot {ids[0]} and also {ids[1]}. Two decisions credited to one "
            f"policy were made with different constants, so any rate computed over that version is over a mixture; "
            f"bump the version when the snapshot changes")


@dataclass
class Store:
    """Append-only. The only mutation this plane permits, and it touches nothing a decision reads."""

    observations: list[Outcome] = field(default_factory=list)

    def append(self, obs: Outcome) -> None:
        if not isinstance(obs, Outcome):
            raise Unreplayable(f"{obs!r} is not an Outcome; a loose dict here means the required identifiers were "
                               f"never checked, and the check exists because an unattributable outcome still counts")
        self.observations.append(obs)

    def staleness(self, *, live_snapshot: Calibration) -> int:
        """How many observations have arrived that the live policy's snapshot does not include.

        Reported rather than hidden. The separation this module enforces has a real cost -- an outcome observed now
        changes nothing until the next snapshot -- and a number naming that lag is what lets somebody decide the
        rebuild cadence instead of assuming the loop is closed.
        """
        return max(0, len(self.observations) - live_snapshot.observation_count)
