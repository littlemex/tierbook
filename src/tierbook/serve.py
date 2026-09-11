"""One turn of the loop: observe, decide, record. The composition, so the three parts have somewhere to meet.

SCOPE section 3 states the mechanism as `route(request, state) -> assign(candidate, evidence, certified)`. `observe`
produces the state, `decide` produces the assignment, `record` writes what section 9 requires. This is the function
that calls them in that order, and it exists because a loop assembled by each caller is a loop each caller assembles
differently.

**Every request is assigned somewhere.** Section 2 is explicit that there is no "choose nothing": the request is served
either way, so declining to choose only means the declared default chooses while the mechanism disclaims the
consequence. When the state is incomplete or no rule fires, this returns the default with `certified: False` -- an
assignment, with the reason recorded.

**The propensity was 1 before C3, and the record said why that mattered.** A compiled policy here is deterministic,
so with no exploration mechanism the logged selection probability is 1 for the arm decide() chose and there is no
data at all for the others -- enough for section 9's record and not enough for section 9's off-policy claim, which
is why `accept.spend_regret` reported `unsupported` rather than a number.

**C3 makes the randomiser part of this composition, not a layer on top of it.** `route_once` calls `explore.draw`
exactly once per decision -- CONTRACT C3's "one draw" -- over the eligible set `explore.eligible` computes from
the same admissibility facts `candidate_set` already gathers. Exploration applies even when `decide` fell to the
declared default: the default is a choice like any other, and excluding it from the draw would fix its propensity
at 1 forever, which is the defect the paragraph above described and this module no longer has. The propensity and
the eligible set recorded on the `Decision` are exactly what the draw returned -- never recomputed by a caller,
because a caller re-deriving them from the policy afterwards could derive a different number than the one that was
actually drawn from.
"""
from __future__ import annotations

import random

from . import decide as dc
from . import explore as ex
from . import observe as ob
from .record import BoundProvenance, Candidate, Decision, Log, admissible

#: The propensity of an arm nothing was drawn for -- either because no rate was declared (or it was zero) or
#: because the eligible set held no alternative to draw. `explore.draw` returns this value itself, as a literal,
#: for exactly those two cases (its "rate_zero" and "no_eligible_arm" reasons); `route_once` below records
#: whatever `draw` returns rather than substituting this name for it, so an off-policy estimate never has to
#: guess which decisions in a log got a live draw and which got this constant. Kept, named, for a caller
#: elsewhere in this codebase that still wants "the propensity of a deterministic policy's chosen arm" as a
#: fact to compare against.
DETERMINISTIC_PROPENSITY = 1.0


def candidate_set(policy: dc.Policy, chosen: str, *, bounds: dict | None = None,
                  costs: dict | None = None, evidence_as_of: str = "",
                  bound_provenance: BoundProvenance | None = None,
                  floor: float | None = None, authorised: bool = False,
                  latency_feasible: bool | None = None, available: dict | None = None,
                  evidence_age_days: float | None = None, max_age_days: float | None = None) -> list:
    """The candidate set for the record, including the chosen one and why each other was not.

    Every candidate the LEDGER can name is included, because section 9 asks for the set with the reason each
    was excluded, and a set containing only the winner cannot support an exclusion analysis.

    **CONTRACT v0.3.0 C6: membership comes from `policy.candidates`, not from `policy.rules`.** A candidate
    with no rule used to be absent from this set entirely -- invisible to exploration, never labelled, its
    evidence never refreshed -- because `policy.rules` only ever names the arm a compile actually chose (and
    its tail), never every candidate the ledger has an outcome for. `policy.candidates` (`policy.candidates_for`,
    written into the artifact by `compile_policy`) is that wider set: a candidate the ledger cannot bound is a
    key mapped to `None` rather than a missing key, which is what makes it a candidate that EXISTS with no
    bound -- excluded for `no_bound` below -- rather than a candidate nobody considered. Each member's own
    `Candidate.bound` on the record is still whatever `bounds` supplies for it (this function's own,
    longer-standing contract, unchanged here); `policy.candidates`'s values are consulted only for which ids
    belong in the set, never substituted in as a second source for the bound itself. `policy.candidates_for`'s
    own numbers say what the ledger itself could bound at compile time, which is not the same claim as a
    per-request bound, and v0.3.0 does not wire the second into the first -- see CONTRACT C6's own "obligation
    carried forward": the absolute bound is still typed by an operator.

    **The reason is derived, not asserted.** An earlier version wrote `below_floor` for any candidate it could not
    otherwise classify, without a floor to compare against -- and four of the eight reasons were unreachable from this
    path, so the log showed a clean distribution over three reasons no matter what happened. A review put it exactly
    right: a closed vocabulary of invented values aggregates confidently into nonsense, and the membership check that
    guarantees the enum is what made the fabrication invisible. Where no floor is supplied the reason is
    `not_evaluated`, which is the true statement.

    `bound_provenance` is passed rather than inferred. An earlier version labelled every supplied bound `lcb`
    (`bound_kind`, CONTRACT C1), so a caller handing over point estimates produced a log claiming they were
    corrected lower bounds -- and the falsifier passed against them. `bound_provenance` is structured now
    (`record.BoundProvenance`), and `record.admissible` refuses one that claims a correction this mechanism did
    not perform, rather than merely recording an unchecked label.
    """
    bounds = bounds or {}
    costs = costs or {}
    available = available or {}
    # CONTRACT v0.3.0 C6: the ledger's own candidate set, not `policy.rules` -- see this function's own
    # docstring for why deriving from the rules left a ruleless candidate invisible.
    named = list(policy.candidates)
    seen, out = set(), []
    for cid in named:
        if cid in seen:
            continue
        seen.add(cid)
        cand = Candidate(id=cid, excluded_because="chosen" if cid == chosen else "not_evaluated",
                         bound=bounds.get(cid),
                         bound_provenance=bound_provenance if cid in bounds else None,
                         cost_usd=costs.get(cid), evidence_as_of=evidence_as_of)
        if cid != chosen:
            cand.excluded_because = _why_not(cand, cid, costs=costs, floor=floor, authorised=authorised,
                                             latency_feasible=latency_feasible, available=available,
                                             evidence_age_days=evidence_age_days, max_age_days=max_age_days)
        out.append(cand)
    if chosen not in seen:  # noqa: SIM102 - see the comment below
        # The policy chose something it does not name -- CONTRACT v0.3.0 C6 makes this the ordinary shape of a
        # candidate the ledger has never recorded an outcome for (SCOPE section 6: a new candidate enters
        # through shadow or epsilon-rate evaluation before it has one), not only the pre-C6 escape hatch this
        # branch was written for. Recorded rather than raised: the record's own invariant will refuse it, and
        # refusing here would lose the evidence of how it happened.
        out.append(Candidate(id=chosen, excluded_because="chosen", bound=bounds.get(chosen),
                             # Mirrors the main loop above: a bound with no provenance is unrepresentable
                             # (CONTRACT amendment 3, C1), and this branch supplying one without the other used
                             # to raise `Incomplete` for exactly the caller this docstring says is legitimate.
                             bound_provenance=bound_provenance if chosen in bounds else None,
                             cost_usd=costs.get(chosen), evidence_as_of=evidence_as_of))
    return out


def _why_not(cand: Candidate, cid: str, *, costs: dict, floor: float | None, authorised: bool,
             latency_feasible: bool | None, available: dict, evidence_age_days: float | None,
             max_age_days: float | None) -> str:
    """Why one candidate was not chosen, derived from what is known and honest about what is not.

    The order matters: the cheapest facts first, so a candidate that is not serving is reported as `unavailable`
    rather than as whatever its bound would have said.
    """
    if available.get(cid) is False:
        return "unavailable"
    if cand.bound is None:
        return "no_bound"
    if cid not in costs:
        return "not_priced"
    if floor is None:
        # The true statement. Asserting `below_floor` here is what the earlier version did, and it was a claim about
        # a comparison nobody made.
        return "not_evaluated"
    ok, why = admissible(cand, floor=floor, authorised=authorised, latency_feasible=latency_feasible,
                         evidence_age_days=evidence_age_days, max_age_days=max_age_days)
    return "not_evaluated" if ok else why


def _confirmed_policy_version(policy: dc.Policy, supplied: str | None) -> str:
    """`policy_version` on the record, confirmed against the policy's own digest by `decide.parameter`'s rule
    (CONTRACT C2): `supplied=None` reads the digest and returns it; a `supplied` value that agrees is handed
    back; one that disagrees is refused, naming both, because a caller that could prefer its own label over the
    artifact's own hash is a second, competing home for the fact this digest exists to answer -- the same
    defect `parameter` already refuses for `floor` and the other compiled numbers.
    """
    digest = policy.policy_digest
    if supplied is None:
        return digest
    # `parameter` distinguishes two refusals and so does this: an artifact that recorded NOTHING cannot confirm a
    # supplied value, and an artifact that recorded a DIFFERENT value contradicts it. Collapsing both into "does
    # not match ''" reports an absence as a competing value, which is the shape of claim this release is closing.
    if not digest:
        raise ValueError(f"policy_version was supplied as {supplied!r}, but this policy carries no digest: an "
                         f"artifact that did not record one cannot confirm a supplied version. A policy from "
                         f"compile_policy carries its own; one built by hand has nothing to check against")
    if supplied != digest:
        raise ValueError(f"policy_version supplied as {supplied!r} does not match {digest!r}, this policy's "
                         f"own digest. Refusing rather than preferring either")
    return supplied


def route_once(*, policy: dc.Policy, observation: ob.Observation, request_id: str,
               feature_vector_version: str, policy_version: str | None = None, mechanism_version: str,
               agent: str, model: str, endpoint: str, gateway_quote_usd: float | None,
               bounds: dict | None = None, costs: dict | None = None, evidence_as_of: str = "",
               bound_provenance: BoundProvenance | None = None, floor: float | None = None,
               latency_feasible: bool | None = None, max_age_days: float | None = None,
               exploration_rate: float | None = None, staleness_limit_days: float | None = None,
               rng: random.Random | None = None,
               log: Log | None = None) -> tuple[dict, Decision]:
    """Observe -> decide -> record, once -- and now explore -> record, because CONTRACT C3 makes the randomiser
    part of this composition. `decide` still produces ONE assignment; what changed is that this function no
    longer writes that assignment down uncontested.

    Returns the raw decision from `decide` and the record that was written, because the two say different things: the
    first carries the gaps, the second carries what a later claim will be computed from.

    CONTRACT C2: `policy_version` is left `None` by a caller with nothing to add, and this reads `policy.policy_digest`
    for it -- the compiled artifact's own content hash, the fact `Decision.policy_digest` also carries. A caller that
    DOES supply a value is checked against the digest through `_confirmed_policy_version` rather than trusted outright,
    by `decide.parameter`'s rule: a value that disagrees is refused, naming both, because a value the mechanism can
    derive is not a value a caller supplies.

    `rng` is a parameter rather than a module-level generator (CONTRACT constraint), so a caller can seed one run
    and get a reproducible draw. Left absent, a fresh `random.Random()` is used -- harmless even then, because
    `explore.draw` never touches it when `exploration_rate` is `None` or `0`: the "rate_zero" branch returns
    before any random number is drawn.
    """
    # CONTRACT C2: resolved before anything else runs, so a mismatched `policy_version` is refused before this
    # function does any work a caller would have to notice was wasted.
    resolved_policy_version = _confirmed_policy_version(policy, policy_version)
    got = dc.decide(policy, observation.state)
    deterministic = got["assign"][0]
    authorised = bool(observation.state.get("metered_authorised", False))
    available = {c: observation.state.get(f"available:{c}") for c in (bounds or {})}
    evidence_age_days = observation.state.get("evidence_age_days")

    # Built around decide()'s own choice first, because that is the candidate set `explore.eligible` reads to
    # find who else clears the floor -- the same admissibility facts this function already gathers for the
    # record, not a second, separately-computed set.
    candidates = candidate_set(
        policy, deterministic, bounds=bounds, costs=costs, evidence_as_of=evidence_as_of,
        bound_provenance=bound_provenance,
        floor=floor, authorised=authorised, latency_feasible=latency_feasible, available=available,
        evidence_age_days=evidence_age_days, max_age_days=max_age_days)

    # `explore.eligible` requires a real floor -- it compares a candidate's bound against it, and `None` would
    # make that comparison a `TypeError` rather than a refusal. Without one there is no basis to say what clears
    # it, so nothing is eligible, matching how `_why_not` above already answers "not_evaluated" rather than
    # asserting a comparison nobody made.
    eligible_ids = ([] if floor is None else
                    ex.eligible(candidates, floor=floor, authorised=authorised, latency_feasible=latency_feasible,
                               available=available, staleness_limit_days=staleness_limit_days,
                               evidence_age_days=evidence_age_days))
    chosen, propensity, exploration_reason = ex.draw(
        deterministic, eligible_ids, exploration_rate or 0.0, rng if rng is not None else random.Random())

    if chosen != deterministic:
        # ONE DRAW chose an arm decide() did not. `candidate_set` is rebuilt around the arm actually served, so
        # `excluded_because == "chosen"` names the one that was, not the one decide() proposed -- the invariant
        # `Decision.__post_init__` already enforces.
        candidates = candidate_set(
            policy, chosen, bounds=bounds, costs=costs, evidence_as_of=evidence_as_of,
            bound_provenance=bound_provenance,
            floor=floor, authorised=authorised, latency_feasible=latency_feasible, available=available,
            evidence_age_days=evidence_age_days, max_age_days=max_age_days)
    # CONTRACT C1 (amendment 3): both branches call `admissible` on the candidate actually served, not only the
    # explored one. `record.Decision.certified` is SCOPE section 2's judgment and nothing else -- before this,
    # the deterministic branch (the MAJORITY of decisions) set it from `got["validated"]`
    # (`policy.validated`, the non-inferiority status), which is the same conflation this entry renames the WORD
    # to stop, still present in the VALUE: the rename alone would have left two words with one of them silently
    # carrying the other's meaning, reading as though the distinction had been made when it had not.
    #
    # DEFECT this line prevents (amendment 6, generalised by amendment 3): `explore.eligible`'s verdict answers
    # "who may be drawn INTO", and it deliberately does not consult `max_evidence_age_days` -- that override is
    # the whole reason the door exists, so it can reach an arm the freshness ratchet locked out. But "may be
    # drawn into" is not "the floor may be claimed for it", and neither is "the compiled rule fired": SCOPE
    # section 2's admissibility has a bound-vs-floor clause and a freshness clause that a compiled rule's guards
    # do not re-derive per request from the caller's own `bounds`. `admissible` is called here rather than
    # re-derived, so this decision and `check_certification` (the falsifier that tests exactly this predicate)
    # use the SAME predicate and cannot disagree by construction, on the deterministic path as well as the
    # explored one.
    #
    # `floor is None` is guarded the same way `eligible_ids` above already is: `admissible` compares
    # `candidate.bound < floor` unconditionally, and `None` would make that comparison a `TypeError` rather
    # than a refusal. With no floor declared there is no basis to say the bound cleared it, so nothing can be
    # certified -- the same "not_evaluated" honesty `_why_not` already gives the non-chosen candidates above.
    # Amendment 6: a CONJUNCTION, not a replacement. Amendment 3 read `certified` from `admissible` alone, which
    # traded one one-sided reading for another: `policy.validated` is whether this policy's rules ever cleared
    # non-inferiority on a held-out fold, and a decision taken by rules that never did cannot claim the floor
    # however good the candidate's own bound looks. Admissibility is a property of the CANDIDATE; validation is a
    # property of the RULES that reached it; certification needs both, and dropping either is the same defect
    # from a different side.
    drawn = next(c for c in candidates if c.id == chosen)
    certified = (False if floor is None else
                bool(got["validated"]) and
                admissible(drawn, floor=floor, authorised=authorised, latency_feasible=latency_feasible,
                          evidence_age_days=evidence_age_days, max_age_days=max_age_days)[0])

    decision = Decision(
        family=policy.family,
        request_id=request_id,
        feature_vector_version=feature_vector_version,
        # A reference, not a snapshot: section 9 forbids the snapshot because it would be unbounded and would carry
        # tenant content. The observation is logged separately by whoever collected it.
        state_ref=state_ref(observation),
        candidates=candidates,
        chosen=chosen,
        # Whatever `explore.draw` actually returned -- never DETERMINISTIC_PROPENSITY substituted back in, and
        # never recomputed from the policy after the fact: a caller re-deriving the propensity from the eligible
        # set could derive a different number than the one the draw used, which is a second home for a value
        # section 9 needs identified to exactly one.
        selection_probability=propensity,
        # CONTRACT amendment 13 / C10: `exploration` must mean "traffic was diverted", not "the randomiser ran".
        # `exploration_reason == "explored"` used to conflate the two -- returned for both an alternative winning
        # AND the incumbent winning anyway -- which made this field read true for ~100% of active draws at a rate
        # where only ~5% actually diverted. `chosen != deterministic` is the correct signal, and it is already
        # computed three lines above to decide whether to re-derive `certified`; reusing it here rather than
        # deriving a second time from the reason string is what keeps the two derivations from disagreeing.
        exploration=(chosen != deterministic),
        exploration_reason=exploration_reason,
        eligible_set=eligible_ids,
        certified=certified,
        policy_version=resolved_policy_version,
        # CONTRACT C2: the policy's own digest, read once above and never recomputed here -- the same value
        # `resolved_policy_version` was just confirmed against, so the two fields cannot disagree by construction.
        policy_digest=policy.policy_digest,
        mechanism_version=mechanism_version,
        agent=agent,
        model=model,
        endpoint=endpoint,
        gateway_quote_usd=gateway_quote_usd,
        gateway_authorised=authorised,
        # Both kinds of gap travel: the policy's own, and the collector's. A caller that saw only one would think the
        # other had been checked.
        gaps=list(got["gaps"]) + [f"uncollected_variable: {k} -- {v}"
                                  for k, v in sorted(observation.not_observed.items())],
    )
    if log is not None:
        # The observation is persisted BEFORE the decision, so `state_ref` resolves to something. A review found it was
        # a dangling pointer: the record hashed an observation that nothing stored, so it looked like it identified the
        # decision's state and did not.
        log.append_observation(state_ref(observation), observation.as_dict())
        log.append(decision)
    return got, decision


def state_ref(observation: ob.Observation) -> str:
    """A stable reference to one observation, so the record can point at it without embedding it.

    Content-addressed over the readings, because two observations with the same values taken at different times are
    different states and a reference that collided on them would let a reader join a decision to the wrong one.
    """
    import hashlib
    import json

    blob = json.dumps(observation.as_dict(), sort_keys=True).encode()
    return "obs:" + hashlib.sha256(blob).hexdigest()[:16]
