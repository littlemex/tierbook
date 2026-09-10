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
from dataclasses import MISSING, asdict, dataclass, field, fields
from pathlib import Path

#: The shape this module writes and reads by default. Verified: `accept._as_decision` used to splat every row key
#: into `Decision(**kw)`, so a record carrying a field the reader's Decision does not define raised
#: `TypeError: __init__() got an unexpected keyword argument` on every line -- outside `Log.read`'s corrupt-line
#: tolerance, which killed the whole acceptance run rather than being counted. A v0.1.0 log has no `schema_version`
#: key at all, so its absence is the fact that identifies it: it is read as version 1, not by a convention enforced
#: by nobody, but because `from_row` below checks for the key's absence in code.
SCHEMA_VERSION = 2

#: The sentinel a fresh `Decision()` call actually receives for `schema_version`. Distinguishing "the writer's
#: default kicked in" from "a caller passed 2, which happens to equal the default" needs a value no caller would
#: plausibly supply; an int like 0 would not do, because a mixed-up caller could pass exactly that. Never seen
#: outside `Decision.__post_init__`, and `from_row` (the one place permitted to set a version other than the
#: default) does so by mutating the attribute after construction, not by passing it in.
_WRITER_STAMPS_SCHEMA_VERSION = object()

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
    # For a candidate whose admissibility was never evaluated. Added because the alternative was worse than "other":
    # `serve.candidate_set` used to assert `below_floor` for anything it could not otherwise classify, WITHOUT a floor
    # to compare against, and four of the reasons above were unreachable from that path. A closed vocabulary of
    # invented values aggregates confidently into nonsense, which is the failure the closed vocabulary was meant to
    # prevent.
    "not_evaluated",
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
    #: What KIND of number `bound` is -- a corrected lower bound, a point estimate, something else. Never inferred:
    #: an earlier version wrote "lcb" for whatever a caller passed, so a log of point estimates claimed to be a log of
    #: lower bounds and the falsifier passed against them.
    bound_kind: str = "unstated"
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
    #: Which shape this record was written in. Stamped by the writer, not supplied by a caller -- the component
    #: that serialises a Decision is the one that knows what shape it wrote, and a caller that could supply its own
    #: value would be a second, competing source for a fact `from_row` needs to trust unconditionally when it
    #: decides whether it can read a row at all.
    schema_version: int = field(default=_WRITER_STAMPS_SCHEMA_VERSION)

    def __post_init__(self) -> None:
        if self.schema_version is _WRITER_STAMPS_SCHEMA_VERSION:
            self.schema_version = SCHEMA_VERSION
        else:
            raise Incomplete(
                f"schema_version is stamped by the writer, not supplied by a caller. Passing "
                f"schema_version={self.schema_version!r} to Decision(...) would make the constructor a second place "
                f"that decides what shape a record is, competing with the one place -- from_row -- that is allowed "
                f"to say so")
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


def _candidate_from_row(row: dict) -> Candidate:
    """One candidate dict from a logged row, into the dataclass. Unknown keys inside a candidate are dropped
    silently rather than reported: `from_row`'s ignored-keys contract is about the top-level row, and the
    candidate set has never grown a field since this record existed."""
    return Candidate(**{k: v for k, v in row.items()
                        if k in {"id", "excluded_because", "bound", "bound_kind", "cost_usd", "evidence_as_of"}})


def from_row(row: dict) -> tuple[Decision, list[str]]:
    """The only way a logged row becomes a `Decision`. Returns the decision and the sorted names of row keys it
    ignored.

    Verified defect this replaces: `accept._as_decision` splatted every key of a logged row straight into
    `Decision(**kw)`, so a record carrying a field the reader's `Decision` did not define raised
    `TypeError: __init__() got an unexpected keyword argument`, on every line, outside `Log.read`'s corrupt-line
    tolerance -- adding any field to the record broke every older reader, in both directions: forward for a
    v0.1.0 reader meeting a v0.2.0 line, and backward for an operator rolling back. This makes the omission
    unrepresentable instead of adding a convention nobody enforces:

    - A row with no `schema_version` is missing the key entirely (a v0.1.0 record never had it), and is read as
      version 1 by this function's own check, not by an assumption a caller happens to share.
    - A key this Decision does not define is ignored and named in the returned list -- not an error, because a
      later field being unrecognised is exactly the case this function exists to survive.
    - A `schema_version` newer than `SCHEMA_VERSION` is refused by name for both versions: reading a future shape
      as if it were this one is the silent-corruption case, not a compatible one.
    - A field this version's `Decision` requires (no default) that is absent from the row raises `Incomplete`
      naming it. Absent is never defaulted -- a default invented here would be a value nothing measured.
    """
    version = row.get("schema_version", 1)
    if version > SCHEMA_VERSION:
        raise Incomplete(
            f"row carries schema_version {version}, newer than this reader's {SCHEMA_VERSION}. Reading a future "
            f"shape as if it were this one is the silent-corruption case this function exists to refuse")

    known = {f.name for f in fields(Decision)}
    ignored = sorted(k for k in row if k not in known)

    for f in fields(Decision):
        if f.name == "schema_version":
            continue
        if f.default is MISSING and f.default_factory is MISSING and f.name not in row:
            raise Incomplete(f"row is missing {f.name!r}, which this schema requires and does not default")

    kw = {k: v for k, v in row.items() if k in known and k not in ("schema_version", "candidates")}
    kw["candidates"] = [_candidate_from_row(c) for c in row["candidates"]]
    decision = Decision(**kw)
    # Bypasses the constructor guard by construction, not by exception: from_row is the one caller entitled to say
    # what version a row was written in, and it says so by mutating the attribute after __post_init__ has already
    # run, never by passing schema_version=... into Decision(...).
    decision.schema_version = version
    return decision, ignored


def admissible(candidate: Candidate, *, floor: float, authorised: bool,
               latency_feasible: bool | None, evidence_age_days: float | None = None,
               max_age_days: float | None = None) -> tuple[bool, str]:
    """SCOPE section 2's three-part definition, as code, so `certified` can be checked rather than trusted.

    The latency part is deliberately three-valued: where the operator set no latency constraint the condition is
    ABSENT rather than satisfied, and an implementation that read a missing constraint as a passed one would report a
    stronger admissibility than the definition grants.

    Freshness is checked too, and it was missing. Section 10 makes estimates stop being usable after a limit, and
    `evidence_expired` was in the exclusion vocabulary with nothing able to produce it -- so a candidate whose evidence
    had expired could be certified. Like latency it is three-valued: no declared limit means the condition is absent,
    not passed.
    """
    if candidate.bound is None:
        return False, "no_bound"
    if (max_age_days is not None and evidence_age_days is not None
            and evidence_age_days > max_age_days):
        return False, "evidence_expired"
    if candidate.bound < floor:
        return False, "below_floor"
    if not authorised:
        return False, "not_authorised"
    if latency_feasible is False:
        return False, "latency_infeasible"
    return True, "chosen"


def check_certification(decision: Decision, *, floor: float, latency_feasible: bool | None,
                        evidence_age_days: float | None = None, max_age_days: float | None = None) -> list:
    """Section 12's falsifier, computed rather than asserted.

    Returns the violations found. Two are possible and they are opposite errors: an assignment marked certified whose
    candidate was not admissible, and an uncertified assignment made while an admissible candidate existed -- the
    second is section 12's "default is not a hiding place".
    """
    out = []
    kw = dict(floor=floor, authorised=decision.gateway_authorised, latency_feasible=latency_feasible,
              evidence_age_days=evidence_age_days, max_age_days=max_age_days)
    chosen = next(c for c in decision.candidates if c.id == decision.chosen)
    ok, why = admissible(chosen, **kw)
    if decision.certified and not ok:
        out.append(f"certified but the chosen candidate {chosen.id!r} was not admissible: {why}")
    if not decision.certified:
        # The chosen candidate is IN this scan. An uncertified decision whose own chosen candidate was admissible is
        # the purest hiding place -- the mechanism declined to certify an assignment it could have -- and an earlier
        # version skipped it, which made exactly that case undetectable. Every violation is reported rather than the
        # first: an earlier version broke out of the loop and undercounted.
        for c in decision.candidates:
            was, _ = admissible(c, **kw)
            if was:
                out.append(f"uncertified while {c.id!r} was admissible, so the default was a hiding place")
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

    def append_observation(self, ref: str, observation: dict) -> None:
        """The state a decision was made from, so its `state_ref` resolves.

        Its own line rather than a field on the decision, because section 9 forbids embedding the snapshot -- it would
        be unbounded and would carry tenant content. What is stored here is the collector's own summary: the values it
        read, their sources and what it could not read, which is bounded and contains no request content.
        """
        with self.path.open("a") as fh:
            fh.write(json.dumps({"observation_ref": ref, "observation": observation}, sort_keys=True) + "\n")

    def read(self, *, strict: bool = False) -> tuple[list, dict]:
        """Every decision, and the outcomes keyed by request id.

        Both rather than a merged view, because a decision with no outcome is a fact the caller needs to see.

        **A label that changes is a refusal, not a later value winning.** An earlier version kept the last outcome per
        request, which made the log append-only in bytes and mutable in meaning: appending `labelled/True` after
        `labelled/False` silently replaced the label, and the argument for trusting a criterion computed over an
        append-only log did not hold. A `pending` or `missing` outcome may be superseded by a real label, because that
        is the label arriving rather than changing.

        **A corrupt line does not destroy the log.** A crash mid-append leaves a truncated line, and an earlier version
        raised on it -- losing every intact record before it. The count is carried in `bad_lines` on the returned
        outcomes dict rather than swallowed, and `strict=True` raises for a caller that wants that.

        **A line that parses but fails `from_row` is a different failure from a corrupt line, and is counted
        separately.** "The file was truncated" and "the record is from a newer version this reader refuses" are
        different operator actions -- the first is repaired or truncated, the second means the log needs the newer
        reader, and folding the two counts together would hide which one applies. Counted as `__unreadable_rows__`,
        with the reason, and `strict=True` raises for a caller that wants that.
        """
        decisions, outcomes, observations, bad, unreadable = [], {}, {}, 0, []
        if not self.path.exists():
            return decisions, outcomes
        for n, line in enumerate(self.path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                if strict:
                    raise Incomplete(f"line {n} of {self.path} is not readable: {exc}") from exc
                bad += 1
                continue
            if "observation_ref" in row:
                observations[row["observation_ref"]] = row["observation"]
            elif "outcome_for" in row:
                rid = row["outcome_for"]
                prev = outcomes.get(rid)
                if prev is not None and prev.get("label_state") == "labelled":
                    if prev.get("label") != row.get("label") or row.get("label_state") != "labelled":
                        raise Incomplete(
                            f"{rid} already carries the label {prev.get('label')!r} and a later line says "
                            f"{row.get('label')!r} ({row.get('label_state')}). A label that changes makes every "
                            f"criterion computed over this log a criterion over the rewrite")
                outcomes[rid] = row
            else:
                try:
                    from_row(row)
                except Incomplete as exc:
                    if strict:
                        raise Incomplete(f"line {n} of {self.path} parsed as JSON but its record could not be "
                                         f"read: {exc}") from exc
                    unreadable.append(f"line {n}: {exc}")
                    continue
                decisions.append(row)
        # Attached to the outcomes mapping so a caller that only reads decisions cannot lose it.
        if observations:
            outcomes["__observations__"] = observations
        if bad:
            outcomes["__bad_lines__"] = {"count": bad, "note": "unreadable lines, most likely a crash mid-append; "
                                                               "the intact records before and after them are kept"}
        if unreadable:
            outcomes["__unreadable_rows__"] = {"count": len(unreadable), "reasons": unreadable}
        return decisions, outcomes
