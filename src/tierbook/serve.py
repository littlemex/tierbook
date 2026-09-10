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
from .record import Candidate, Decision, Log, admissible

#: The propensity of an arm nothing was drawn for -- either because no rate was declared (or it was zero) or
#: because the eligible set held no alternative to draw. `explore.draw` returns this value itself, as a literal,
#: for exactly those two cases (its "rate_zero" and "no_eligible_arm" reasons); `route_once` below records
#: whatever `draw` returns rather than substituting this name for it, so an off-policy estimate never has to
#: guess which decisions in a log got a live draw and which got this constant. Kept, named, for a caller
#: elsewhere in this codebase that still wants "the propensity of a deterministic policy's chosen arm" as a
#: fact to compare against.
DETERMINISTIC_PROPENSITY = 1.0


def candidate_set(policy: dc.Policy, chosen: str, *, bounds: dict | None = None,
                  costs: dict | None = None, evidence_as_of: str = "", bound_kind: str = "unstated",
                  floor: float | None = None, authorised: bool = False,
                  latency_feasible: bool | None = None, available: dict | None = None,
                  evidence_age_days: float | None = None, max_age_days: float | None = None) -> list:
    """The candidate set for the record, including the chosen one and why each other was not.

    Every candidate the policy can name is included, because section 9 asks for the set with the reason each was
    excluded, and a set containing only the winner cannot support an exclusion analysis.

    **The reason is derived, not asserted.** An earlier version wrote `below_floor` for any candidate it could not
    otherwise classify, without a floor to compare against -- and four of the eight reasons were unreachable from this
    path, so the log showed a clean distribution over three reasons no matter what happened. A review put it exactly
    right: a closed vocabulary of invented values aggregates confidently into nonsense, and the membership check that
    guarantees the enum is what made the fabrication invisible. Where no floor is supplied the reason is
    `not_evaluated`, which is the true statement.

    `bound_kind` is passed rather than inferred. An earlier version labelled every supplied bound `lcb`, so a caller
    handing over point estimates produced a log claiming they were corrected lower bounds -- and the falsifier passed
    against them.
    """
    bounds = bounds or {}
    costs = costs or {}
    available = available or {}
    named = []
    for rule in policy.rules:
        named.extend(rule.assign)
    named.extend(policy.default)
    seen, out = set(), []
    for cid in named:
        if cid in seen:
            continue
        seen.add(cid)
        cand = Candidate(id=cid, excluded_because="chosen" if cid == chosen else "not_evaluated",
                         bound=bounds.get(cid), bound_kind=bound_kind if cid in bounds else "unstated",
                         cost_usd=costs.get(cid), evidence_as_of=evidence_as_of)
        if cid != chosen:
            cand.excluded_because = _why_not(cand, cid, costs=costs, floor=floor, authorised=authorised,
                                             latency_feasible=latency_feasible, available=available,
                                             evidence_age_days=evidence_age_days, max_age_days=max_age_days)
        out.append(cand)
    if chosen not in seen:  # noqa: SIM102 - see the comment below
        # The policy chose something it does not name. Recorded rather than raised: the record's own invariant will
        # refuse it, and refusing here would lose the evidence of how it happened.
        out.append(Candidate(id=chosen, excluded_because="chosen", bound=bounds.get(chosen),
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


def route_once(*, policy: dc.Policy, observation: ob.Observation, request_id: str,
               feature_vector_version: str, policy_version: str, mechanism_version: str,
               agent: str, model: str, endpoint: str, gateway_quote_usd: float | None,
               bounds: dict | None = None, costs: dict | None = None, evidence_as_of: str = "",
               bound_kind: str = "unstated", floor: float | None = None,
               latency_feasible: bool | None = None, max_age_days: float | None = None,
               exploration_rate: float | None = None, staleness_limit_days: float | None = None,
               rng: random.Random | None = None,
               log: Log | None = None) -> tuple[dict, Decision]:
    """Observe -> decide -> record, once -- and now explore -> record, because CONTRACT C3 makes the randomiser
    part of this composition. `decide` still produces ONE assignment; what changed is that this function no
    longer writes that assignment down uncontested.

    Returns the raw decision from `decide` and the record that was written, because the two say different things: the
    first carries the gaps, the second carries what a later claim will be computed from.

    `rng` is a parameter rather than a module-level generator (CONTRACT constraint), so a caller can seed one run
    and get a reproducible draw. Left absent, a fresh `random.Random()` is used -- harmless even then, because
    `explore.draw` never touches it when `exploration_rate` is `None` or `0`: the "rate_zero" branch returns
    before any random number is drawn.
    """
    got = dc.decide(policy, observation.state)
    deterministic = got["assign"][0]
    authorised = bool(observation.state.get("metered_authorised", False))
    available = {c: observation.state.get(f"available:{c}") for c in (bounds or {})}
    evidence_age_days = observation.state.get("evidence_age_days")

    # Built around decide()'s own choice first, because that is the candidate set `explore.eligible` reads to
    # find who else clears the floor -- the same admissibility facts this function already gathers for the
    # record, not a second, separately-computed set.
    candidates = candidate_set(
        policy, deterministic, bounds=bounds, costs=costs, evidence_as_of=evidence_as_of, bound_kind=bound_kind,
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
        # `Decision.__post_init__` already enforces. And CONTRACT C3 ("not uncertified by construction"): the
        # drawn arm came from `eligible_ids`, which already required its bound to clear the floor and the rest
        # of admissibility except the expiry `clears_floor` deliberately overrides -- so it is certified here,
        # not left to inherit whatever `decide` said about a rule it did not fire.
        candidates = candidate_set(
            policy, chosen, bounds=bounds, costs=costs, evidence_as_of=evidence_as_of, bound_kind=bound_kind,
            floor=floor, authorised=authorised, latency_feasible=latency_feasible, available=available,
            evidence_age_days=evidence_age_days, max_age_days=max_age_days)
        certified = True
    else:
        certified = bool(got["certified"])

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
        exploration=(exploration_reason == "explored"),
        exploration_reason=exploration_reason,
        eligible_set=eligible_ids,
        certified=certified,
        policy_version=policy_version,
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
