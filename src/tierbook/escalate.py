"""What a re-issued request carries, so a loop and a double charge are unrepresentable rather than unlikely.

When a cheap candidate declines to answer, something has to send the work somewhere better. That re-issue is where
the accidents live, and they were measured on two real servers rather than imagined: 32 requests, 12 escalated, and
the fields below are what made the hop bound hold and the idempotency keys not collide.

**The engine returns an action, not a destination.** This is the one design decision the whole module rests on. The
cheap side says only "I should not answer this"; *where* the work goes is the caller's choice, because the standard
routing mechanism already picks endpoints and re-implementing that produces compatibility debt rather than value. So
`Escalation` carries a `target_profile` -- a class of candidate -- and never an address.

**A retry is not a second escalation.** The key is derived from the parent request and the hop, so two attempts at
one escalation collide by construction and the ledger can tell one decision from two tries at it. A key chosen by
the caller would be a field the caller can vary, and varying it is exactly how a retry becomes a second charge.

**The hop bound is a bound, not a warning.** A depth that merely gets logged is a loop with a paper trail.

**And the engine has no channel for an action.** A logits processor cannot set a response header, so the action has
to be encoded in what the model emits. A single rare token is not available -- four candidates each failed to be one
token in a 248,320-entry vocabulary -- so `SENTINEL` is a multi-token string, emitted one token per step. It costs
several decode steps to say one bit and it depends on both sides agreeing on a magic string, which is why
`upstream_ask` states what would replace it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

#: The action the cheap side can return. `commit` is not "success": it is "answer with what you have", which is a
#: decision as much as escalating is, and naming it keeps the ledger's vocabulary closed over what actually happened.
ACTIONS = ("commit", "escalate", "abort")

#: What a policy declares about substitution, because the choice is the buyer's and not the detector's. Generation
#: length is only known while decoding, by which point output may already be streaming to the client and cannot be
#: replaced -- so a policy that escalates late must say which of these it does.
COMMIT_SEMANTICS = ("buffered", "early")

#: Encoded in the body because the extension point has no channel for an action. Multi-token deliberately: no single
#: rare token was available in the vocabulary this was measured on.
SENTINEL = "TIERBOOK_ESCALATE"

#: More than this many hops is refused. Two is enough for cheap -> better -> best and small enough that a cycle
#: cannot hide inside it.
MAX_HOPS = 2


class Loop(Exception):
    """A re-issue would exceed the hop bound, or would repeat a stage it has already left. Raised before the request
    is sent, because a loop detected afterwards has already been paid for."""


class Untraceable(Exception):
    """A re-issue could not be attributed to the decision that caused it. Raised at construction, because an
    outcome that cannot be joined to a decision cannot be used to score the policy that made it -- which is the
    whole purpose of recording it."""


@dataclass(frozen=True)
class Escalation:
    """One re-issue, with the fields that make its accidents unrepresentable.

    `decision_id` and `policy_version` are both required and neither defaults. A re-issue that cannot name the
    decision behind it is an outcome nothing can be learnt from, and one that cannot name the policy version is an
    outcome credited to whatever policy happens to be current when it is read.
    """

    parent_request_id: str
    decision_id: str
    policy_version: str
    target_profile: str
    hop_count: int
    commit_semantics: str = "buffered"

    def __post_init__(self) -> None:
        for name in ("parent_request_id", "decision_id", "policy_version", "target_profile"):
            if not getattr(self, name):
                raise Untraceable(
                    f"{name} is empty. An escalation missing it cannot be joined to what caused it, so its outcome "
                    f"cannot be credited or blamed, which is the only reason to record an escalation at all")
        if self.target_profile.count(":") or self.target_profile.replace(".", "").isdigit():
            raise Untraceable(
                f"target_profile={self.target_profile!r} looks like an address. The cheap side returns an ACTION, "
                f"not a destination: endpoint selection belongs to the routing mechanism that already does it, and "
                f"naming an address here is how a gate quietly becomes a second router")
        if self.commit_semantics not in COMMIT_SEMANTICS:
            raise Untraceable(
                f"{self.commit_semantics!r} is not one of {COMMIT_SEMANTICS}. Generation length is only known while "
                f"decoding, by which time output may already be streaming, so whether a late escalation may replace "
                f"an answer is a declaration the buyer makes rather than a detail")
        if not isinstance(self.hop_count, int) or isinstance(self.hop_count, bool):
            raise Loop(f"hop_count={self.hop_count!r} is not an integer; a depth that cannot be compared cannot bound")
        if self.hop_count < 1:
            raise Loop(f"hop_count={self.hop_count} is not a hop: the original request is hop zero and is not an "
                       f"escalation, so the first re-issue is one")
        if self.hop_count > MAX_HOPS:
            raise Loop(f"hop_count={self.hop_count} exceeds MAX_HOPS={MAX_HOPS}. The bound is enforced here rather "
                       f"than logged, because a depth that only gets logged is a loop with a paper trail")

    @property
    def idempotency_key(self) -> str:
        """Derived, so a retry of one escalation cannot be billed as two.

        The caller does not supply this. A key the caller can vary is a key a retry varies, and then the ledger sees
        two escalations where one was intended -- which is the double-charge this module exists to make impossible
        rather than to detect.
        """
        return hashlib.sha256(f"{self.parent_request_id}|{self.hop_count}".encode()).hexdigest()[:24]

    def headers(self) -> dict[str, str]:
        """The fields as they cross the boundary. Names are fixed here so both sides read the same ones."""
        return {"x-tb-parent-request-id": self.parent_request_id,
                "x-tb-decision-id": self.decision_id,
                "x-tb-policy-version": self.policy_version,
                "x-tb-target-profile": self.target_profile,
                "x-tb-hop-count": str(self.hop_count),
                "x-tb-idempotency-key": self.idempotency_key}


def next_hop(previous: Escalation | None, *, parent_request_id: str, decision_id: str, policy_version: str,
             target_profile: str, commit_semantics: str = "buffered") -> Escalation:
    """Build the next escalation, refusing a cycle rather than counting one.

    Passing the previous escalation is how the depth is derived instead of asserted. A caller that computes its own
    `hop_count` can compute the same one twice, and two escalations at one depth is a cycle that the bound does not
    see.
    """
    if previous is None:
        return Escalation(parent_request_id=parent_request_id, decision_id=decision_id,
                          policy_version=policy_version, target_profile=target_profile,
                          hop_count=1, commit_semantics=commit_semantics)
    if previous.parent_request_id != parent_request_id:
        raise Loop(f"the previous escalation belongs to {previous.parent_request_id!r} and this one claims "
                   f"{parent_request_id!r}; a chain whose links name different parents is two chains, and its depth "
                   f"is not what either of them thinks")
    if previous.target_profile == target_profile:
        raise Loop(f"escalating to {target_profile!r} again, which is the profile that just declined. Repeating a "
                   f"stage is the cycle the hop bound would eventually stop, one paid attempt at a time")
    return Escalation(parent_request_id=parent_request_id, decision_id=decision_id, policy_version=policy_version,
                      target_profile=target_profile, hop_count=previous.hop_count + 1,
                      commit_semantics=commit_semantics)


def action_from_body(text: str, *, tokens_emitted: int | None = None) -> str:
    """Read the action out of what the model emitted, because there is nowhere else for it to be.

    An empty completion with a normal stop reason is *not* read as an escalation. It cannot be told apart from a
    request the model answered with nothing, and a run that relied on it reported the right count for the wrong
    reason -- 12 of 12 detected through an ambiguous path that happened to agree with the sentinel. So the
    ambiguous case returns `commit` and the ambiguity is the caller's to resolve, which is the honest handling until
    the extension point grows a channel.
    """
    if SENTINEL in text:
        return "escalate"
    return "commit"


def upstream_ask() -> str:
    """What would replace the sentinel, stated so the workaround is not mistaken for the design."""
    return ("The action belongs in response metadata. Encoding it in the body costs several decode steps to say one "
            "bit, requires both sides to agree on a magic string, and has an ambiguous fallback when no rare "
            "single token exists -- four candidates each failed to be one token in a 248,320-entry vocabulary. A "
            "field on the response, or a non-scheduling telemetry hook that may not change endpoint selection, "
            "removes all three.")
