"""One turn of the loop: observe, decide, record. The composition, so the three parts have somewhere to meet.

SCOPE section 3 states the mechanism as `route(request, state) -> assign(candidate, evidence, certified)`. `observe`
produces the state, `decide` produces the assignment, `record` writes what section 9 requires. This is the function
that calls them in that order, and it exists because a loop assembled by each caller is a loop each caller assembles
differently.

**Every request is assigned somewhere.** Section 2 is explicit that there is no "choose nothing": the request is served
either way, so declining to choose only means the declared default chooses while the mechanism disclaims the
consequence. When the state is incomplete or no rule fires, this returns the default with `certified: False` -- an
assignment, with the reason recorded.

**The propensity is 1 and the record says why that matters.** A compiled policy here is deterministic, so the logged
selection probability is 1 for the arm it chose and there is no data at all for the others. That is enough for section
9's record and **not** enough for section 9's off-policy claim, which is why `accept.spend_regret` reports
`unsupported` rather than a number. Writing 1.0 without saying so would leave a reader to discover that later.
"""
from __future__ import annotations

from . import decide as dc
from . import observe as ob
from .record import Candidate, Decision, Log

#: The propensity of a deterministic policy's chosen arm. Named rather than written as a literal at the call site,
#: because the name is where the consequence is recorded: an off-policy estimate over a log of these is unidentified.
DETERMINISTIC_PROPENSITY = 1.0


def candidate_set(policy: dc.Policy, chosen: str, *, bounds: dict | None = None,
                  costs: dict | None = None, evidence_as_of: str = "") -> list:
    """The candidate set for the record, including the chosen one and why each other was not.

    Every candidate the policy can name is included, because section 9 asks for the set with the reason each was
    excluded, and a set containing only the winner cannot support an exclusion analysis. A candidate the policy
    mentions but for which no bound was supplied is recorded as `no_bound` rather than omitted -- omitting it would
    make a candidate nobody could evaluate look like a candidate nobody considered.
    """
    bounds = bounds or {}
    costs = costs or {}
    named = []
    for rule in policy.rules:
        named.extend(rule.assign)
    named.extend(policy.default)
    seen, out = set(), []
    for cid in named:
        if cid in seen:
            continue
        seen.add(cid)
        if cid == chosen:
            why = "chosen"
        elif cid not in bounds:
            why = "no_bound"
        elif cid not in costs:
            why = "not_priced"
        else:
            why = "below_floor"
        out.append(Candidate(id=cid, excluded_because=why, bound=bounds.get(cid),
                             bound_kind="lcb" if cid in bounds else "", cost_usd=costs.get(cid),
                             evidence_as_of=evidence_as_of))
    if chosen not in seen:
        # The policy chose something it does not name. Recorded rather than raised: the record's own invariant will
        # refuse it, and refusing here would lose the evidence of how it happened.
        out.append(Candidate(id=chosen, excluded_because="chosen", bound=bounds.get(chosen),
                             cost_usd=costs.get(chosen), evidence_as_of=evidence_as_of))
    return out


def route_once(*, policy: dc.Policy, observation: ob.Observation, request_id: str,
               feature_vector_version: str, policy_version: str, mechanism_version: str,
               agent: str, model: str, endpoint: str, gateway_quote_usd: float | None,
               bounds: dict | None = None, costs: dict | None = None, evidence_as_of: str = "",
               log: Log | None = None) -> tuple[dict, Decision]:
    """Observe -> decide -> record, once.

    Returns the raw decision from `decide` and the record that was written, because the two say different things: the
    first carries the gaps, the second carries what a later claim will be computed from.
    """
    got = dc.decide(policy, observation.state)
    chosen = got["assign"][0]
    authorised = bool(observation.state.get("metered_authorised", False))

    decision = Decision(
        family=policy.family,
        request_id=request_id,
        feature_vector_version=feature_vector_version,
        # A reference, not a snapshot: section 9 forbids the snapshot because it would be unbounded and would carry
        # tenant content. The observation is logged separately by whoever collected it.
        state_ref=state_ref(observation),
        candidates=candidate_set(policy, chosen, bounds=bounds, costs=costs, evidence_as_of=evidence_as_of),
        chosen=chosen,
        selection_probability=DETERMINISTIC_PROPENSITY,
        exploration=False,
        certified=bool(got["certified"]),
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
