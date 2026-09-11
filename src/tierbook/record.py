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

# Imported for its `evidence_age_days`, which `check_certification` reuses rather than recomputing
# `date.fromisoformat` / UTC midnight / `(now - then) / 86400` a third time (amendment 7, C6). Checked for a
# cycle before writing this: `observe` imports only `decide.STATE_VARS`, and neither `decide` nor `observe`
# imports `record`, so this edge does not close a loop.
from . import observe

#: The shape this module writes and reads by default. Verified: `accept._as_decision` used to splat every row key
#: into `Decision(**kw)`, so a record carrying a field the reader's Decision does not define raised
#: `TypeError: __init__() got an unexpected keyword argument` on every line -- outside `Log.read`'s corrupt-line
#: tolerance, which killed the whole acceptance run rather than being counted. A v0.1.0 log has no `schema_version`
#: key at all, so its absence is the fact that identifies it: it is read as version 1, not by a convention enforced
#: by nobody, but because `from_row` below checks for the key's absence in code.
#:
#: CONTRACT C2: 3, not 2. `policy_digest` is required starting at this version -- a version 1 or 2 row never had
#: it, because the mechanism that derives it did not exist for them, and `from_row` supplies `""` for exactly
#: those two versions rather than one (SEAMS.md S4, applied with its own cutoff: this field's mechanism shipped a
#: release after the one that introduced `exploration_reason`/`eligible_set`, so it reads correctly for one more
#: past version than they do).
SCHEMA_VERSION = 3

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
    # Amendment 7 (C6): distinct from `evidence_expired`, which asserts an age the record does not carry.
    # `Candidate.evidence_as_of` defaults to `""`, so an undated candidate is representable, and with a limit
    # declared there is no honest use of `evidence_expired` for it and no honest way to admit it either --
    # admitting it silently skips freshness, which is the v0.1.0 defect this entry exists to close.
    "no_evidence_date",
    "chosen",                   # it is the one that was selected; recorded so the set is complete
    # For a candidate whose admissibility was never evaluated. Added because the alternative was worse than "other":
    # `serve.candidate_set` used to assert `below_floor` for anything it could not otherwise classify, WITHOUT a floor
    # to compare against, and four of the reasons above were unreachable from that path. A closed vocabulary of
    # invented values aggregates confidently into nonsense, which is the failure the closed vocabulary was meant to
    # prevent.
    "not_evaluated",
    # CONTRACT C1: its `bound_provenance.corrected_over` names a term of BOUND_CORRECTIONS this release's mechanism
    # never applies. Before this reason existed, three records carrying a fabricated `bound` of 0.99 with
    # `bound_kind` of `lcb`, `point_estimate` and `asserted_by_operator` all certified identically, because
    # `admissible` compared only `bound < floor` and nothing anywhere read the kind. This is what makes an
    # overclaimed correction refused rather than merely unlabelled.
    "unearned_correction",
    # Amendment 4.1, and distinct from the line above: that one is a claim made and not earned, this one is no claim
    # at all. A row written before `bound_provenance` existed reads with an `unrecorded` estimator so the log stays
    # readable -- v0.2.0's C1's whole purpose -- and a bound whose provenance was never recorded cannot support a
    # NEW certification, because the mechanism has no record of what produced it. Both of those are C1's purposes
    # rather than a compromise between them.
    "unrecorded_provenance",
)

#: The three states a label can be in. `missing` and `pending` are different facts and collapsing them is how a
#: never-labelled task becomes a failure in a success rate.
LABEL_STATES = ("labelled", "missing", "pending")

#: Why `exploration: false` on a decision, or why it is true. Closed for the same reason EXCLUSION_REASONS is:
#: four causes shared one bit before this existed -- no mechanism installed at all, an eligible set with no
#: alternative to the deterministic arm, a rate of zero, and (C10 / amendment 13) the randomiser running and the
#: incumbent winning anyway -- and a silent False could not be attributed to any of them. `no_mechanism` is also
#: the value a version 1 row reads as (SEAMS.md S4): it never had this field, so "no mechanism" is the true
#: statement about it, not a guess.
#:
#: `not_diverted` (C10) is NOT the same fact as `no_eligible_arm` or `rate_zero`: those two mean the draw was
#: never performed at all (`explore.draw` returns before touching `rng`), while `not_diverted` means the draw WAS
#: performed -- `rng.random()` was called, a real alternative existed -- and it landed on the deterministic arm.
#: Before this value existed, `explore.draw` had nowhere to put that outcome except `explored`, which is why
#: `exploration_reason == "explored"` was true for BOTH outcomes of an active draw and could not be used to
#: measure diverted traffic (CONTRACT amendment 13, C10).
EXPLORATION_REASONS = ("explored", "no_eligible_arm", "rate_zero", "no_mechanism", "not_diverted")

#: SCOPE section 6's multiplicity family (candidates x families x tenants x the selection process). Closed and
#: tied to its producers the way EXCLUSION_REASONS is: a test drives every producer of a bound and asserts what
#: comes back is a subset of this tuple, so a producer growing a value the tuple lacks fails at merge time rather
#: than shipping an unrepresentable claim. There is no `none` member: the tuple names terms that CAN be corrected
#: over, "none" is not a term, and `()` is the one spelling of "corrected over nothing" -- CONTRACT amendment 3
#: (v0.3.0) removed the second spelling rather than let the release that closes one duplication class open
#: another in the vocabulary it adds. `corrected_over=()` is what every producer this release ships returns,
#: since CORRECTIONS_PERFORMED below is empty.
BOUND_CORRECTIONS = ("candidates", "families", "tenants", "selection_process")

#: The estimators a bound may be produced by. Closed for the same reason BOUND_CORRECTIONS is: this release ships
#: exactly one, and adding `anytime_valid_*` is a later release's act (SCOPE section 6, out of scope in this
#: contract) -- the vocabulary makes its absence explicit here rather than leaving `estimator` a free string that
#: could name one nothing here implements.
#:
#: `unrecorded` is the one member no CALLER may write: `_candidate_from_row` supplies it for a row below
#: schema_version 3, whose bound genuinely has no recorded provenance. Amendment 4.1 exists because the pairing
#: rule below, applied to reading as well as to construction, made every row this project has ever written
#: unreadable -- which contradicts v0.2.0's C1 entirely, the entry whose purpose is that a log survives its own
#: evolution. Reading is not certifying, and `admissible` refuses this estimator separately.
BOUND_ESTIMATORS = ("clopper_pearson_fixed_sample", "unrecorded")

#: Which of BOUND_CORRECTIONS this release's mechanism actually performs. Empty, honestly: nothing here corrects a
#: bound over any multiplicity term (SCOPE section 6's anytime-valid bound and its multiplicity correction are both
#: out of scope, per CONTRACT's out-of-scope table). `admissible` refuses a `bound_provenance` that claims a term
#: outside this set, which is what turns the claim into something checked rather than merely recorded.
CORRECTIONS_PERFORMED: tuple[str, ...] = ()


class Incomplete(Exception):
    """A record was missing a field a later claim needs. Raised at write time, because the alternative is finding out
    when the claim is attempted and the data is already collected."""


@dataclass(frozen=True)
class BoundProvenance:
    """What produced `Candidate.bound`, structured rather than a free string.

    DEFECT this replaces: `bound_kind` was a free string, so three records carrying the same fabricated `bound` of
    0.99 with `bound_kind` of `lcb`, `point_estimate` and `asserted_by_operator` all certified identically, because
    `admissible` compared only `bound < floor` and nothing anywhere read the kind. `estimator` and `corrected_over`
    are each closed vocabularies (BOUND_ESTIMATORS, BOUND_CORRECTIONS) precisely so a value nothing here produces
    cannot be written, and `admissible` below reads `corrected_over` rather than merely recording it.
    """

    estimator: str
    confidence: float | None
    corrected_over: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.estimator == "unrecorded" and self.corrected_over:
            raise Incomplete("an unrecorded provenance cannot also claim a correction: there is no record of what "
                             "produced the bound, so there is no record of what it was corrected over either")
        if self.estimator not in BOUND_ESTIMATORS:
            raise Incomplete(f"{self.estimator!r} is not one of {BOUND_ESTIMATORS}; an open-ended estimator name "
                             f"cannot be checked against what this mechanism actually ships")
        unknown = sorted(set(self.corrected_over) - set(BOUND_CORRECTIONS))
        if unknown:
            raise Incomplete(f"corrected_over {self.corrected_over!r} names {unknown}, not in {BOUND_CORRECTIONS}; "
                             f"an open-ended correction cannot be checked against what this mechanism actually "
                             f"performs")


@dataclass
class Candidate:
    """One member of the candidate set, and why it was or was not chosen."""

    id: str
    excluded_because: str
    bound: float | None = None
    #: What produced `bound` -- the estimator, its confidence, and which of BOUND_CORRECTIONS it was corrected
    #: over. `None` means no bound, the same fact `bound is None` already states; a candidate with a bound and no
    #: provenance is not representable, because a bound nobody can attribute is exactly the "decorative field"
    #: defect this replaces `bound_kind` to close.
    bound_provenance: BoundProvenance | None = None
    cost_usd: float | None = None
    evidence_as_of: str = ""

    def __post_init__(self) -> None:
        if self.excluded_because not in EXCLUSION_REASONS:
            raise Incomplete(f"{self.excluded_because!r} is not one of {EXCLUSION_REASONS}; an open-ended reason "
                             f"cannot be aggregated over a log")
        if self.bound_provenance is not None and not isinstance(self.bound_provenance, BoundProvenance):
            raise Incomplete(f"bound_provenance must be a BoundProvenance or None, not {self.bound_provenance!r}; "
                             f"a free string cannot state which of {BOUND_CORRECTIONS} the bound was corrected "
                             f"over, which is the vocabulary bound_kind left decorative")
        # CONTRACT amendment 3 (v0.3.0): `bound` and `bound_provenance` are refused apart, each naming both
        # fields. A numeric bound with no provenance is exactly the pre-C1 state -- a number with nothing saying
        # what produced it -- so leaving that combination constructible would leave the defect representable
        # beside the vocabulary meant to end it. The reverse (a provenance with no bound) is refused for the
        # same reason C6 needs `None` to mean "no bound" unambiguously: a provenance describing a bound that is
        # not there is a second, competing signal for the same fact.
        if self.bound is not None and self.bound_provenance is None:
            raise Incomplete(f"bound={self.bound!r} has no bound_provenance; a number with nothing saying what "
                             f"produced it is the state this vocabulary exists to make unrepresentable")
        if self.bound is None and self.bound_provenance is not None:
            raise Incomplete(f"bound_provenance={self.bound_provenance!r} is set but bound is None; a provenance "
                             f"cannot describe a bound that is not there")


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
    #: CONTRACT C2: a content hash of the compiled policy artifact `route_once` decided from
    #: (`decide.policy_digest`), so a record can name the artifact rather than a hand-typed label. No dataclass
    #: default, for the same reason `exploration_reason` below has none: a plausible-looking default here would
    #: be a value nothing measured. SEAMS.md S4 governs its absence from a row, in `from_row` -- a version 1 or
    #: 2 row never had this field, because the mechanism that derives it did not exist for them, and reads as
    #: `""`; a version 3-or-later row omitting it is `Incomplete`, naming the field, because for that row the
    #: omission means a writer forgot to stamp a fact the mechanism did produce.
    policy_digest: str
    mechanism_version: str
    agent: str
    model: str
    endpoint: str
    gateway_quote_usd: float | None
    gateway_authorised: bool
    #: Why exploration did or did not happen, one of EXPLORATION_REASONS. No dataclass default (SEAMS.md S4):
    #: `no_mechanism` reads correctly for a version 1 row, which never had this field, and wrongly for a version
    #: 2 row that omits it -- a writer that forgot to stamp the reason would be indistinguishable from a
    #: mechanism that was never installed, and that count is a number this release reports. `from_row` supplies
    #: the version 1 value; it is the only caller entitled to.
    exploration_reason: str
    #: The candidate ids the draw in `explore.draw` was performed over, so the returned propensity can be
    #: CHECKED against the set it was drawn from rather than reconstructed from the policy afterwards. Same
    #: no-default treatment as `exploration_reason`, for the same reason: version 1 rows read this as `[]`
    #: because no draw was ever performed for them.
    eligible_set: list
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
        if self.exploration_reason not in EXPLORATION_REASONS:
            raise Incomplete(f"exploration_reason {self.exploration_reason!r} is not one of "
                             f"{EXPLORATION_REASONS}; an open-ended reason cannot be aggregated over a log")
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


def _candidate_from_row(row: dict, index: int) -> tuple[Candidate, list[str]]:
    """One candidate dict from a logged row, into the dataclass, at `index` in `candidates`.

    Ignored-and-named applies here too, not only at the top level. F12 (phase 1 findings) proposes replacing
    `bound_n`/`bound_attempted` with an evidence reference resolving to the ledger, and that field belongs on the
    CANDIDATE, not the decision -- so a candidate is exactly where this record is next expected to grow, and a
    reader that ignored-and-named at the top level while dropping an unrecognised candidate key silently would be
    the same unrepresentable-omission defect one level down, at the field the design already names. The name
    carries the position (`candidates[1].evidence_ref`) because a reader debugging a fifty-candidate row needs to
    know which one grew the field, not just that one did.
    """
    known = {"id", "excluded_because", "bound", "bound_provenance", "cost_usd", "evidence_as_of"}
    ignored = [f"candidates[{index}].{k}" for k in sorted(row) if k not in known]
    for f in fields(Candidate):
        if f.default is MISSING and f.default_factory is MISSING and f.name not in row:
            raise Incomplete(f"candidates[{index}].{f.name} is required and missing from the row")
    kw = {k: v for k, v in row.items() if k in known}
    if isinstance(kw.get("bound_provenance"), dict):
        # A logged row carries `bound_provenance` as a plain object (json.dumps flattened the dataclass), not the
        # BoundProvenance instance `Candidate.__post_init__` requires -- so it is rebuilt here rather than splatted,
        # the same "required field absent -> named Incomplete" rule `Candidate`'s own fields get, applied one level
        # down at the position (`candidates[N].bound_provenance.<field>`) a reader debugging it needs.
        bp = kw["bound_provenance"]
        for f in fields(BoundProvenance):
            if f.default is MISSING and f.default_factory is MISSING and f.name not in bp:
                raise Incomplete(f"candidates[{index}].bound_provenance.{f.name} is required and missing "
                                 f"from the row")
        kw["bound_provenance"] = BoundProvenance(estimator=bp["estimator"], confidence=bp["confidence"],
                                                 corrected_over=tuple(bp.get("corrected_over", ())))
    elif kw.get("bound") is not None:
        # Amendment 4.1. A row written before this field existed carries a bound and no provenance, and the
        # constructor's pairing rule refuses that -- correctly, for a NEW candidate, and catastrophically for a
        # read: applied here it made every row this project has ever written unreadable, which is the opposite of
        # what v0.2.0's C1 exists for. So the row reads, saying truthfully that the provenance was never recorded,
        # and `admissible` refuses the estimator separately. Reading is not certifying.
        kw["bound_provenance"] = BoundProvenance(estimator="unrecorded", confidence=None)
    return Candidate(**kw), ignored


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
      later field being unrecognised is exactly the case this function exists to survive. A candidate carries the
      same treatment, named by position (`candidates[1].evidence_ref`), because the candidate set is itself a
      growth site the design already names (F12's proposed evidence reference is a per-candidate field).
    - A `schema_version` newer than `SCHEMA_VERSION` is refused by name for both versions: reading a future shape
      as if it were this one is the silent-corruption case, not a compatible one.
    - A field this version's `Decision` requires (no default) that is absent from the row raises `Incomplete`
      naming it. Absent is never defaulted -- a default invented here would be a value nothing measured. A
      candidate missing a field it requires raises the same way, named by position.
    - `exploration_reason` and `eligible_set` (C3) are the one exception to "absent is never defaulted", and the
      exception is by version rather than by field (SEAMS.md S4): a version 1 row supplies `no_mechanism` and
      `[]` because C3's mechanism did not exist when it was written, and a version 2-or-later row missing either
      raises `Incomplete` naming it, because for that row the omission means a writer forgot to stamp a fact
      the mechanism did produce.
    - `policy_digest` (C2) is the same exception, with a cutoff one version later: a version 1 OR 2 row supplies
      `""`, because the mechanism that derives a digest did not exist until this release, and only a version 3
      row missing it raises `Incomplete` naming it.
    """
    # Version first, before any field is validated against this reader's shape: a row written to a shape this
    # reader does not know cannot be meaningfully checked against the shape it does know -- the fields it thinks
    # are "missing" might just be renamed or restructured in the version ahead of it, and reporting that as a
    # missing-field Incomplete would misname the actual problem.
    version = row.get("schema_version", 1)
    if version > SCHEMA_VERSION:
        raise Incomplete(
            f"row carries schema_version {version}, newer than this reader's {SCHEMA_VERSION}. Reading a future "
            f"shape as if it were this one is the silent-corruption case this function exists to refuse")

    known = {f.name for f in fields(Decision)}
    ignored = [k for k in row if k not in known]

    # SEAMS.md S4: `exploration_reason` and `eligible_set` have no dataclass default -- a default of
    # `no_mechanism` would read correctly for a version 1 row and WRONGLY for a version 2 row that omits the
    # field, making a writer that forgot to stamp it indistinguishable from a mechanism never installed. So the
    # version decides here, in the one place entitled to say what version a row was written in, rather than the
    # dataclass deciding for every version at once.
    S4_VERSION_1_VALUES = {"exploration_reason": "no_mechanism", "eligible_set": []}
    s4_kw = {}
    for name in S4_VERSION_1_VALUES:
        if name in row:
            continue
        if version == 1:
            # A v1 row never had this field, and the C3 mechanism did not exist for it: `no_mechanism` and `[]`
            # are the true statements about it, not a guess. Fresh literal per call -- `eligible_set` is a list
            # and every Decision must own its own, never a reference shared across rows.
            s4_kw[name] = "no_mechanism" if name == "exploration_reason" else []
        else:
            raise Incomplete(f"row is missing {name!r}, which schema_version {version} requires and does not "
                             f"default: only a version 1 row (written before C3's mechanism existed) reads its "
                             f"absence as no_mechanism/[]")

    # CONTRACT C2, SEAMS.md S4 again, with its own cutoff: `policy_digest` is one release younger than
    # `exploration_reason`/`eligible_set` above, so a row written under C3 but before C2 (schema_version 2) is
    # exactly as silent about it as a version 1 row is -- the mechanism that derives a digest did not exist for
    # either. Only a version 3-or-later row omitting it is a writer that forgot to stamp a fact the mechanism
    # did produce.
    S4_VERSION_1_OR_2_VALUES = {"policy_digest": ""}
    for name in S4_VERSION_1_OR_2_VALUES:
        if name in row:
            continue
        if version <= 2:
            s4_kw[name] = S4_VERSION_1_OR_2_VALUES[name]
        else:
            raise Incomplete(f"row is missing {name!r}, which schema_version {version} requires and does not "
                             f"default: only a version 1 or 2 row (written before C2's mechanism existed) reads "
                             f"its absence as \"\"")

    for f in fields(Decision):
        if f.name == "schema_version" or f.name in S4_VERSION_1_VALUES or f.name in S4_VERSION_1_OR_2_VALUES:
            continue
        if f.default is MISSING and f.default_factory is MISSING and f.name not in row:
            raise Incomplete(f"row is missing {f.name!r}, which this schema requires and does not default")

    candidates = []
    for index, c in enumerate(row["candidates"]):
        candidate, candidate_ignored = _candidate_from_row(c, index)
        candidates.append(candidate)
        ignored.extend(candidate_ignored)
    ignored.sort()

    kw = {k: v for k, v in row.items() if k in known and k not in ("schema_version", "candidates")}
    kw["candidates"] = candidates
    kw.update(s4_kw)
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

    CONTRACT C1: `bound_provenance` is read here too, checked before floor, freshness or anything else derived from
    the bound's own value -- a claim about how the bound was produced is a property of the bound itself. A
    provenance naming a correction outside CORRECTIONS_PERFORMED is refused as `unearned_correction` rather than
    merely unlabelled, which is what makes the vocabulary checked instead of decorative: the earlier `bound_kind`
    let three records with the identical fabricated `bound` of 0.99 and `bound_kind` of `lcb`, `point_estimate` and
    `asserted_by_operator` all certify identically, because nothing here read it. `candidate.bound_provenance` is
    read directly, not guarded by a second `is not None` check: `Candidate.__post_init__` already refuses a
    non-`None` `bound` paired with a `None` `bound_provenance`, so having passed the `no_bound` return above, the
    provenance is guaranteed present.
    """
    if candidate.bound is None:
        return False, "no_bound"
    if candidate.bound_provenance.estimator == "unrecorded":
        return False, "unrecorded_provenance"
    if set(candidate.bound_provenance.corrected_over) - set(CORRECTIONS_PERFORMED):
        return False, "unearned_correction"
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


def _admissible_at_decision(candidate: Candidate, *, floor: float, authorised: bool,
                            latency_feasible: bool | None, max_age_days: float | None,
                            decided_at: float) -> tuple[bool, str]:
    """`admissible`, with the age it needs derived here rather than supplied by the caller (amendment 7, C6).

    DEFECT this replaces: `check_certification` used to take one `evidence_age_days` and apply it to every
    candidate in the decision, while each candidate carries its own `evidence_as_of` and tiers are measured at
    different times -- differing dates are the normal case, not an edge one. Measured on one decision holding a
    617-day-old candidate and a 9-day-old one: a 400-day scalar reported NOTHING where the 9-day candidate's
    certification was a real hiding place, and a 5-day scalar reported BOTH where only the 617-day one had
    actually expired. No scalar is right for a set whose members differ by 608 days, so the age is computed per
    candidate instead of threaded through as a fourth copy of the same number.

    The reference is `decided_at` -- when the decision was made -- not the clock at the moment this runs.
    Re-evaluating against accept-time would make a verdict drift as the file ages, which is the defect
    `classify_label` already refuses for label states: a criterion whose answer changes because the file got
    older is not a criterion.

    An empty `evidence_as_of` is never passed to `observe.evidence_age_days`: with `max_age_days` declared there
    is no honest reading of an undated candidate -- `evidence_expired` would assert an age the record does not
    carry, and treating the age as absent would silently skip freshness for it, which is the v0.1.0 defect
    amendment 7 exists to close. `no_evidence_date` names which of the two applies, checked after `no_bound` so
    it keeps `admissible`'s own priority (a candidate with no bound is `no_bound` regardless of its date). With
    no `max_age_days` declared the condition is simply absent, exactly as for every dated candidate.
    """
    if candidate.bound is not None and max_age_days is not None and not candidate.evidence_as_of:
        return False, "no_evidence_date"
    age = (observe.evidence_age_days(candidate.evidence_as_of, now=decided_at)
          if candidate.evidence_as_of else None)
    return admissible(candidate, floor=floor, authorised=authorised, latency_feasible=latency_feasible,
                      evidence_age_days=age, max_age_days=max_age_days)


#: How an unverifiable finding is marked in `check_certification`'s list, so `accept` can separate the two without
#: a second return value and without parsing prose. Amendment 5: a finding that cannot be checked is not a
#: violation, and a falsifier whose silence is read as evidence must not speak from absence.
_UNVERIFIABLE_PREFIX = "UNVERIFIABLE: "


def check_certification(decision: Decision, *, floor: float, latency_feasible: bool | None,
                        max_age_days: float | None = None) -> list:
    """Section 12's falsifier, computed rather than asserted.

    Returns the violations found. Two are possible and they are opposite errors: an assignment marked certified whose
    candidate was not admissible, and an uncertified assignment made while an admissible candidate existed -- the
    second is section 12's "default is not a hiding place".

    `evidence_age_days` is gone from this signature (amendment 7, C6): each candidate's age is derived from its
    own `evidence_as_of` against `decision.decided_at` by `_admissible_at_decision`, which is what a scalar
    covering every candidate could never be right about. See that function for the measured defect this closes.
    """
    out: list[str] = []
    unverifiable: list[str] = []
    kw = dict(floor=floor, authorised=decision.gateway_authorised, latency_feasible=latency_feasible,
              max_age_days=max_age_days, decided_at=decision.decided_at)
    chosen = next(c for c in decision.candidates if c.id == decision.chosen)
    ok, why = _admissible_at_decision(chosen, **kw)
    if decision.certified and not ok:
        if why == "unrecorded_provenance":
            # Amendment 5. A row whose bound's provenance was never recorded cannot be AUDITED, and that is not
            # the same statement as "this was not admissible". Reporting it as a violation made every pre-C1
            # certified decision fail the falsifier on replay -- not only the wrong ones -- and SCOPE section 12
            # reads that failure as the mechanism being broken, so a correct historical log accused the mechanism.
            # `admissible` still refuses the same candidate for a NEW decision, where a bound with no recorded
            # provenance cannot support a claim; only what an audit concludes from that refusal changes here.
            unverifiable.append(f"certified and unverifiable: the bound of {chosen.id!r} carries no recorded "
                                f"provenance, so whether it cleared the floor cannot be established from this "
                                f"record")
        else:
            out.append(f"certified but the chosen candidate {chosen.id!r} was not admissible: {why}")
    if not decision.certified:
        # The chosen candidate is IN this scan. An uncertified decision whose own chosen candidate was admissible is
        # the purest hiding place -- the mechanism declined to certify an assignment it could have -- and an earlier
        # version skipped it, which made exactly that case undetectable. Every violation is reported rather than the
        # first: an earlier version broke out of the loop and undercounted.
        for c in decision.candidates:
            was, _ = _admissible_at_decision(c, **kw)
            if was:
                out.append(f"uncertified while {c.id!r} was admissible, so the default was a hiding place")
    return out + [_UNVERIFIABLE_PREFIX + u for u in unverifiable]


def classify_label(decided_at: float, now: float, max_label_latency_s: float | None, label: bool | None) -> str:
    """A label's lifecycle, so `pending` and `missing` are computed rather than guessed at read time.

    Housed here rather than in `outcomes` (amendment 4, C4): `outcomes` is the potential-outcome table -- what
    every tier did on every item, so a policy can be chosen over it -- and a label's lifecycle is a different
    subject. This module already owns `LABEL_STATES`, and the module that defines the three states is the one
    that decides the transitions between them.

    Three-valued for the same reason `admissible` is: collapsing `missing` into `pending`, or either into
    `labelled`, is how a task nobody ever labelled becomes a silent success or a silent failure in a rate
    somebody reports.

    `max_label_latency_s is None` raises rather than picking a state. A family with `label_source: none`
    (config.FamilyDeclaration) has no declared latency, and with none declared there is no line between "still
    waiting" and "gave up waiting" for this function to draw on the caller's behalf -- so a caller with no
    latency to give has no join to perform, not a call that returns some default.

    Never called from `Log.read` on a row's own recorded `label_state`, and that omission is deliberate:
    `Log.read` returns each row's `label_state` exactly as it was written, at whatever `schema_version` wrote
    it. Passing a row's `decided_at` through this function at read time would reclassify `pending` against a
    latency rule declared AFTER that row was logged -- silently restating every success rate already computed
    from it, for every row at `schema_version < 2` and not only the ones that changed. A caller that wants a
    fresh classification calls this function itself, with the label state it already has as a fact, not as an
    invitation to overwrite.
    """
    if max_label_latency_s is None:
        raise ValueError(
            "max_label_latency_s is None: with no declared latency, the distinction between 'pending' and "
            "'missing' is not classify_label's to make -- the caller has no join to perform here, not a "
            "default to fall back on."
        )
    if label is not None:
        return "labelled"
    if now - decided_at <= max_label_latency_s:
        return "pending"
    return "missing"


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
        ignored_keys: dict = {}
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
                    _decision, row_ignored = from_row(row)
                    # CONTRACT C12. `from_row` names the keys it did not understand and every caller discarded
                    # the list, so a reader that survived a field being added named it to nobody -- the same
                    # outcome as dropping it. Counted per key name rather than in total: an operator who reads
                    # "4,000 keys ignored" and one who reads "this reader does not know evidence_ref" take the
                    # same action, and only the second is told what it is.
                    for key in row_ignored:
                        ignored_keys[key] = ignored_keys.get(key, 0) + 1
                except Incomplete as exc:
                    if strict:
                        raise Incomplete(f"line {n} of {self.path} parsed as JSON but its record could not be "
                                         f"read: {exc}") from exc
                    # Excluded from `decisions`, not appended-and-flagged: a row this reader could not turn into a
                    # Decision has no fields a criterion can trust, so it exists in `__unreadable_rows__` and
                    # nowhere else -- the same fate a corrupt line gets from `bad`, for the same reason.
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
        # Absent rather than empty when nothing was ignored, so its absence reads as "this reader understood
        # every field in every row" rather than as one more key a caller has to interpret.
        if ignored_keys:
            outcomes["__ignored_keys__"] = ignored_keys
        # CONTRACT amendment 12 (C4). An outcome naming a request_id no decision in this log carries is a label
        # that landed on nothing. REPORTED rather than refused, and the difference is what the fact is: a
        # rewritten label makes every criterion over this log a criterion over the rewrite, which is why the
        # branch above raises; an orphan makes a label silently ABSENT, which is a gap in the population rather
        # than a corruption of it -- C11's shape, and C12's above.
        #
        # `attach-outcome` refuses this at the door with a message the operator can act on. This is the backstop
        # for every other writer: a library caller, an older version, a hand edit. Without it, `accept` reports
        # "no decisions are labelled, so no realised rate exists" over a log holding twenty labels aimed at ids
        # that do not exist -- blaming a missing measurement for a typo, which is the failure C4 exists to end.
        known = {row["request_id"] for row in decisions}
        orphans = sorted(rid for rid in outcomes if not rid.startswith("__") and rid not in known)
        if orphans:
            outcomes["__orphan_outcomes__"] = {"count": len(orphans), "request_ids": orphans}
        return decisions, outcomes
