"""This example's routing opinion, and every threshold in it derived rather than configured.

**One opinion among many.** A different example may prefer availability over price, or refuse to move traffic at all
outside business hours. The mechanism carries whichever guards it is given and has no view on which are sensible --
that is the property being demonstrated, and the reason this file is here rather than in `src/`.

The guards read three facts the mechanism has never heard of. It evaluates them because the policy **declares** its own
vocabulary; the mechanism's contribution is to refuse a guard over a variable the policy did not declare, so a fact
nobody supplies cannot be read at request time.
"""
from __future__ import annotations

from tierbook import decide as dc

#: The facts this example's guards read. Two are its own invention, one is per candidate, and `inflight` overlaps with
#: the mechanism's defaults deliberately -- a caller mixes freely rather than choosing.
STATE_VARS = ("price_per_mtok", "inflight", "tenant_quota_left", "hour_of_day")
PER_CANDIDATE = ("price_per_mtok", "inflight")

#: What this example calls the two places a request can go. Names, not tiers: the mechanism gets them from the policy.
CHEAP = "box"
DEAR = "api"


def thresholds_from_history(history: list[dict]) -> dict[str, float]:
    """Derive this policy's numbers from what the loop recorded. **Nothing here is configured.**

    Two numbers come out, and both are the example's choice of what to derive:

    * `price_cross` -- the price per Mtok above which the cheap candidate stops being cheap. Derived as the dear
      candidate's **observed** price rather than its list price, because the loop has been paying it and the paid figure
      is the one a decision should turn on.
    * `quota_floor` -- the quota below which escalation stops. Derived as the cost of the most expensive request the loop
      has actually seen, so the last decision cannot be one the tenant cannot pay for. A configured floor would be a
      number that is wrong the first time the request mix changes.

    With no history there is nothing to derive, and this returns an empty mapping rather than a default. A caller with no
    history has to decide what to do about that, and hiding it behind a plausible constant is how a configured threshold
    gets reintroduced.
    """
    if not history:
        return {}
    dear_prices = [row["price"] for row in history if row["candidate"] == DEAR]
    worst_spend = max((row["spend"] for row in history), default=0.0)
    out: dict[str, float] = {"quota_floor": worst_spend}
    if dear_prices:
        out["price_cross"] = sum(dear_prices) / len(dear_prices)
    return out


def build(thresholds: dict[str, float], *, family: str = "coding") -> dc.Policy:
    """This example's policy, given numbers derived from its own history.

    The rules read in order and the first that fires decides, which is the mechanism's semantics rather than this
    example's. What is this example's: which facts to look at, in which order, and what each threshold means.
    """
    rules: list[dc.Rule] = []

    # Quota first, because it is the constraint that cannot be traded against anything. Below the floor the loop stops
    # escalating whatever the prices say: a cheap answer the tenant can pay for beats a better one they cannot. A rule is
    # a conjunction of guards and the first rule that fires decides, so ordering is how this example expresses priority.
    if "quota_floor" in thresholds:
        rules.append(dc.Rule(
            (dc.Guard("tenant_quota_left", "<", thresholds["quota_floor"],
                      derived_from="the most expensive request this loop has recorded"),),
            (CHEAP,), "the tenant cannot pay for an escalation, so stop escalating"))

    # Then price. The cheap candidate stops being cheap somewhere, and where is measured rather than assumed.
    if "price_cross" in thresholds:
        rules.append(dc.Rule(
            (dc.Guard(f"price_per_mtok:{CHEAP}", ">=", thresholds["price_cross"],
                      derived_from="the mean price this loop has actually paid on the dear candidate"),),
            (DEAR,), "the cheap candidate is no longer cheaper than the dear one"))

    # And a load guard on the cheap side, which is the one fact the mechanism's defaults already knew about.
    rules.append(dc.Rule(
        (dc.Guard(f"inflight:{CHEAP}", ">=", 8.0,
                  derived_from="the seat count the engine reported at startup"),),
        (DEAR,), "the cheap candidate is at its seat count"))

    return dc.Policy(family, tuple(rules), (CHEAP,),
                     state_vars=STATE_VARS, per_candidate=PER_CANDIDATE,
                     note="example policy: quota, then price, then load. Every number derived from recorded history.")


def choose(policy: dc.Policy, observation, *, thresholds: dict[str, float]) -> str:
    """Which candidate this example sends the next request to.

    The mechanism evaluates the guards and reports what fired and what it could not read. **This function is where the
    example turns that into a destination**, which is deliberately not something the mechanism does: it reports, and a
    caller decides what a report means.
    """
    got = dc.decide(policy, observation.state)
    fired = got.get("rule")
    if fired is None:
        # Nothing fired, so the policy's declared default stands. Reading it off the policy rather than naming CHEAP
        # again means the two cannot disagree about what "no rule matched" means.
        return policy.default[0]
    return policy.rules[fired].assign[0]
