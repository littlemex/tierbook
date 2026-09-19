"""What this example decides to observe, which is not the mechanism's business.

The vocabulary here is the point. `price_per_mtok`, `hour_of_day` and `tenant_quota_left` are facts **tierbook has
never heard of**, and the guards in `policy.py` read them without the mechanism changing. Until the state vocabulary
moved onto the policy, a guard over any of the three was refused outright and this example could not have been
written.

`inflight` is in the mechanism's default set too, and it is here for a different reason: to show that a caller may
mix its own facts with the defaults freely, rather than choosing between the two.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Import path: the example lives beside the package rather than inside it, so it imports the public surface the same
# way any other consumer would.
from tierbook import observe as ob
from tierbook import throughput as th


@dataclass
class World:
    """The facts this example's loop reads, and a clock it does not own.

    A plain dataclass rather than a scrape, because what this example demonstrates is the shape of the loop. A real
    deployment replaces `snapshot` with a metrics read and a price-card fetch; nothing else here changes, which is the
    property worth demonstrating.
    """

    price_per_mtok: dict[str, float]
    tenant_quota_left: float
    hour_of_day: int
    inflight: dict[str, int] = field(default_factory=dict)
    #: What is known about how fast each candidate can be served, as whichever kind of evidence actually exists: a
    #: `throughput.Throughput` when somebody ran the box, a `throughput.Ceiling` when somebody only declared a limit.
    #: They are separate types on purpose and this example keeps them separate, because a declared limit can refuse a
    #: requirement and can never show one is met. A candidate absent from this mapping has no capacity evidence at all,
    #: which is a third state and not the same as a zero.
    capacity: dict[str, object] = field(default_factory=dict)

    def snapshot(self, candidate: str, *, now: float) -> ob.Observation:
        """One observation, keyed the way the mechanism's guards read it.

        A per-candidate fact is qualified with the candidate's name and a global one is not. The example decides which
        of its facts are per candidate; `policy.py` declares the same split to the mechanism, and a disagreement between
        the two shows up as an unobserved variable rather than as a silently wrong comparison.
        """
        o = ob.Observation(candidate=candidate)

        def put(key: str, value) -> None:
            o.state[key] = value
            o.readings[key] = ob.Reading(value=value, as_of=now, source="example world")

        put(f"price_per_mtok:{candidate}", self.price_per_mtok[candidate])
        put(f"inflight:{candidate}", self.inflight.get(candidate, 0))
        put("tenant_quota_left", self.tenant_quota_left)
        put("hour_of_day", self.hour_of_day)
        return o

    def can_deliver(self, candidate: str, required_per_hour: float) -> tuple[str, str]:
        """Whether this candidate can carry the rate the loop needs, and one sentence of why.

        The example does not answer this itself. It hands whatever evidence it has to the mechanism, which sorts a
        measured goodput from a declared ceiling and returns `deliverable`, `refused` or `unknown` -- the third being the
        answer that keeps the other two honest, because a shortfall against a lower bound may be the load generator
        rather than the box.
        """
        evidence = self.capacity.get(candidate)
        if isinstance(evidence, th.Throughput):
            return th.deliverable(required_per_hour, measured=evidence)
        if isinstance(evidence, th.Ceiling):
            return th.deliverable(required_per_hour, ceiling=evidence)
        return th.deliverable(required_per_hour)

    def charge(self, candidate: str, mtok: float) -> None:
        """Spend the tenant's quota. The loop's behaviour has to change as this runs down, or it is not a loop."""
        self.tenant_quota_left = max(0.0, self.tenant_quota_left - self.price_per_mtok[candidate] * mtok)
