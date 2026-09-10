"""The decision record, and a refusal to write one that cannot support the claims made from it.

SCOPE section 9 lists what each decision appends. This writes exactly that list and refuses a record missing a field
some later claim needs, because the alternative is a log that looks complete and turns out not to identify the
estimate somebody wants from it. That has a precedent in this repository: data collected without selection
probabilities cannot support an off-policy estimate later, however much of it there is.

**Three fields carry the whole weight, and each is required for a different reason.**

`selection_probability` is what makes any "another choice would have been better" claim identified. Section 9 says a
claim like that must come from randomised exploration with logged propensities, inverse-propensity or doubly-robust
estimation, or a declared design -- and every one of those needs the propensity at the time of the decision. It cannot
be reconstructed afterwards from a deterministic policy, because a deterministic policy's propensity is 1 for what it
chose and the counterfactual arm has no data at all. That is the definition of unidentified.

`certified` is checked against the three-part admissibility definition rather than copied from the decision. Section 12's
falsifier is a certified assignment whose candidate was not admissible, so a record that merely echoed the decision's
own claim could never expose it.

`label` is written as a three-way value -- a label, or an explicit missing, or not-yet-arrived. Section 9 requires
label-missingness recorded explicitly, and the reason is that a missing label silently read as a failure moves a
realised success rate in the direction that flatters the floor.

What this does not do: decide, observe, or judge. It is the append-only surface the acceptance criteria are computed
from, and its refusals are about completeness, never about whether an assignment was a good one.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Why a candidate was not selected. Closed, because "other" in a log is a field nobody can aggregate.
EXCLUSION_REASONS = (
    "below_floor",              # its corrected lower bound did not clear the family's floor
    "not_authorised",           # the gateway would not authorise the spend
    "latency_infeasible",       # an operator's latency constraint is not feasible at current occupancy
    "unavailable",              # it is not serving
    "not_priced",               # no cost figure, so it cannot be compared on the objective
    "no_bound",                 # no comparable bound, so admissibility cannot be evaluated
    "evidence_expired",         # its estimate is past its freshness limit
    "chosen",                   # it is the one that was selected; recorded so the set is complete
)

#: The three states a label can be in. `missing` and `pending` are different facts and collapsing them is how a
#: never-labelled task becomes a failure in a success rate.
LABEL_STATES = ("labelled", "missing", "pending")


class Incomplete(Exception):
    """A record was missing a field a later claim needs. Raised at write time, because the alternative is finding out
    when the claim is attempted and the data is already collected."""


@dataclass
class Candidate:
    """One member of the candidate set, and why it was or was not chosen."""

    id: str
    excluded_because: str
    bound: float | None = None
    bound_kind: str = ""
    cost_usd: float | None = None
    evidence_as_of: str = ""

    def __post_init__(self) -> None:
        if self.excluded_because not in EXCLUSION_REASONS:
            raise Incomplete(f"{self.excluded_because!r} is not one of {EXCLUSION_REASONS}; an open-ended reason "
                             f"cannot be aggregated over a log")


@dataclass
class Decision:
    """One decision, with everything section 9 requires.

    Every field is required and none defaults to something plausible. A default here would be a value a reader takes
    for an observation.
    """

    family: str
    request_id: str
    feature_vector_version: str
    state_ref: str                  # a reference to immutable state, not a snapshot: section 9 forbids the snapshot
    candidates: list                # of Candidate, the whole set including the chosen one
    chosen: str
    selection_probability: float
    exploration: bool
    certified: bool
    policy_version: str
    mechanism_version: str
    agent: str
    model: str
    endpoint: str
    gateway_quote_usd: float | None
    gateway_authorised: bool
    decided_at: float = field(default_factory=time.time)
    gaps: list = field(default_factory=list)
    label_state: str = "pending"
    label: bool | None = None
    outcome: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 < self.selection_probability <= 1.0:
            raise Incomplete(
                f"selection_probability {self.selection_probability!r} is not in (0, 1]. A zero propensity for an "
                f"arm that was chosen is a contradiction, and a missing one leaves every off-policy estimate from "
                f"this log unidentified")
        if self.label_state not in LABEL_STATES:
            raise Incomplete(f"label_state {self.label_state!r} is not one of {LABEL_STATES}")
        if self.label_state == "labelled" and self.label is None:
            raise Incomplete("label_state says labelled and no label was given")
        if self.label_state != "labelled" and self.label is not None:
            raise Incomplete(f"a label was given with label_state {self.label_state!r}, which is how a label nobody "
                             f"produced ends up in a success rate")
        ids = [c.id for c in self.candidates]
        if self.chosen not in ids:
            raise Incomplete(f"the chosen candidate {self.chosen!r} is not in the candidate set {ids}")
        chosen_rows = [c for c in self.candidates if c.excluded_because == "chosen"]
        if [c.id for c in chosen_rows] != [self.chosen]:
            raise Incomplete("exactly one candidate must be marked 'chosen', and it must be the chosen one; the "
                             "candidate set is what an exclusion analysis reads and a set with two winners has no "
                             "meaning")

    def as_dict(self) -> dict:
        d = asdict(self)
        d["candidates"] = [asdict(c) if not isinstance(c, dict) else c for c in self.candidates]
        return d


def admissible(candidate: Candidate, *, floor: float, authorised: bool,
               latency_feasible: bool | None) -> tuple[bool, str]:
    """SCOPE section 2's three-part definition, as code, so `certified` can be checked rather than trusted.

    The third part is deliberately three-valued: where the operator set no latency constraint the condition is
    ABSENT rather than satisfied, and an implementation that read a missing constraint as a passed one would report a
    stronger admissibility than the definition grants.
    """
    if candidate.bound is None:
        return False, "no_bound"
    if candidate.bound < floor:
        return False, "below_floor"
    if not authorised:
        return False, "not_authorised"
    if latency_feasible is False:
        return False, "latency_infeasible"
    return True, "chosen"


def check_certification(decision: Decision, *, floor: float, latency_feasible: bool | None) -> list:
    """Section 12's falsifier, computed rather than asserted.

    Returns the violations found. Two are possible and they are opposite errors: an assignment marked certified whose
    candidate was not admissible, and an uncertified assignment made while an admissible candidate existed -- the
    second is section 12's "default is not a hiding place".
    """
    out = []
    chosen = next(c for c in decision.candidates if c.id == decision.chosen)
    ok, why = admissible(chosen, floor=floor, authorised=decision.gateway_authorised,
                         latency_feasible=latency_feasible)
    if decision.certified and not ok:
        out.append(f"certified but the chosen candidate {chosen.id!r} was not admissible: {why}")
    if not decision.certified:
        for c in decision.candidates:
            if c.id == decision.chosen:
                continue
            was, _ = admissible(c, floor=floor, authorised=decision.gateway_authorised,
                                latency_feasible=latency_feasible)
            if was:
                out.append(f"uncertified while {c.id!r} was admissible, so the default was a hiding place")
                break
    return out


class Log:
    """Append-only JSONL. One line per decision, and the outcome attached later by request id.

    Append-only because an acceptance criterion computed over a log that can be rewritten is a criterion computed
    over whatever survived the rewrite.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, decision: Decision) -> None:
        with self.path.open("a") as fh:
            fh.write(json.dumps(decision.as_dict(), sort_keys=True) + "\n")

    def attach_outcome(self, request_id: str, *, label_state: str, label: bool | None = None,
                       **outcome) -> None:
        """The outcome arrives later, so it is appended as its own line rather than editing the decision.

        Editing would break append-only, and a log whose earlier lines can change cannot support a criterion computed
        over it. The reader joins by `request_id` and takes the last outcome line.
        """
        if label_state not in LABEL_STATES:
            raise Incomplete(f"label_state {label_state!r} is not one of {LABEL_STATES}")
        if (label is None) == (label_state == "labelled"):
            raise Incomplete(f"label_state {label_state!r} and label {label!r} disagree")
        with self.path.open("a") as fh:
            fh.write(json.dumps({"outcome_for": request_id, "label_state": label_state, "label": label,
                                 "at": time.time(), **outcome}, sort_keys=True) + "\n")

    def read(self) -> tuple[list, dict]:
        """Every decision, and the outcomes keyed by request id. Returns both rather than a merged view, because a
        decision with no outcome is a fact the caller needs to see."""
        decisions, outcomes = [], {}
        if not self.path.exists():
            return decisions, outcomes
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if "outcome_for" in row:
                outcomes[row["outcome_for"]] = row
            else:
                decisions.append(row)
        return decisions, outcomes
