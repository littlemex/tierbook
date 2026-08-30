"""Reaching a backend, generically, and the two checks that keep a score attached to what produced it.

The only thing this module assumes about a backend is that it speaks an OpenAI-compatible HTTP API. That
covers a gateway sitting in front of several vendors, a vendor API directly, and a model server someone
started on a cluster -- and it deliberately cannot tell them apart, because the difference is somebody
else's responsibility. What tierbook needs from a backend is a URL, a model name, and which of the two wires
it speaks. Nothing here starts, scales, or watches anything.

Two checks live here because each closes a failure this project actually shipped:

  * **a protocol pre-flight before measuring.** One tier scored 0 of 20 on a benchmark because the endpoint
    refuses function tools together with any reasoning setting, on that wire. A harness that reported that
    number would have published a false result about a model. So a mismatch is discovered before the run and
    classified as an endpoint incompatibility, never as a task outcome, and the wire actually used is
    recorded inside the record -- a score belongs to the transport it was measured over.

    Probing is the only way to know, and that is now established rather than assumed: the operators of the
    gateway this project measured confirmed the refusal originates **upstream**, not in the gateway, which
    forwards the request shape unchanged. So no gateway can declare the combination in advance without
    publishing a claim about someone else's behaviour that it neither controls nor is notified about. A
    declaration would be inherited by every score built on it; a probe is cheap and belongs to whoever ran it.
  * **an identity check at route time.** A gateway name can be repointed at a new checkpoint without telling
    anyone. If the identity the backend reports no longer matches the identity in the record, the record does
    not describe what is behind the name and the caller is told so.

Standard library only, as with the rest of the package. A component that decides where money goes should not
acquire a new failure mode because an HTTP library moved.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from tierbook.config import Endpoint

CHAT = "chat"
RESPONSES = "responses"

#: Failures of the transport rather than of the task. Kept distinct from a low score because a mismatched
#: wire produces a zero that looks exactly like incapability and is not.
INCOMPATIBLE = "endpoint_incompatible"
UNREACHABLE = "endpoint_unreachable"
OK = "ok"


@dataclass
class Probe:
    """What a pre-flight found, in a form a record can cite."""

    status: str
    wire: str
    detail: str = ""
    refused_params: tuple[str, ...] = ()
    supports_tools: bool | None = None
    reported_identity: str | None = None

    @property
    def may_measure(self) -> bool:
        return self.status == OK


def _post(ep: Endpoint, path: str, body: dict) -> tuple[int, dict | str]:
    url = ep.base_url.rstrip("/") + path
    data = json.dumps(body).encode()
    headers = {"content-type": "application/json", **ep.headers}
    if ep.api_key_env:
        key = os.environ.get(ep.api_key_env)
        if not key:
            raise RuntimeError(
                f"{ep.api_key_env} is not set. tierbook reads the NAME of an environment variable from "
                "configuration and never the key itself, so that a candidate file is safe to commit."
            )
        headers["authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=ep.timeout_s) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _get(ep: Endpoint, path: str) -> tuple[int, dict | str]:
    url = ep.base_url.rstrip("/") + path
    headers = dict(ep.headers)
    if ep.api_key_env and os.environ.get(ep.api_key_env):
        headers["authorization"] = f"Bearer {os.environ[ep.api_key_env]}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=min(ep.timeout_s, 30.0)) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # noqa: BLE001 - unreachable is a legitimate answer here
        return 0, str(e)


def _wire_path(wire: str) -> str:
    return "/chat/completions" if wire == CHAT else "/responses"


def _minimal_body(ep: Endpoint, *, with_tools: bool, extra: dict | None = None) -> dict:
    """The smallest request that exercises the features a measurement needs."""
    tool = {
        "type": "function",
        "function": {"name": "ping", "description": "a probe",
                     "parameters": {"type": "object", "properties": {"x": {"type": "string"}},
                                    "required": ["x"]}},
    }
    if ep.wire == CHAT:
        body: dict = {"model": ep.model, "max_tokens": 16,
                      "messages": [{"role": "user", "content": "reply with the single word ok"}]}
        if with_tools:
            body["tools"] = [tool]
    else:
        body = {"model": ep.model, "max_output_tokens": 16,
                "input": [{"role": "user", "content": [{"type": "input_text",
                                                        "text": "reply with the single word ok"}]}]}
        if with_tools:
            body["tools"] = [{"type": "function", "name": "ping", "description": "a probe",
                              "parameters": tool["function"]["parameters"]}]
    for k in ep.refuses_params:
        body.pop(k, None)
    body.update(extra or {})
    return body


def preflight(ep: Endpoint, *, needs_tools: bool = True, extra: dict | None = None) -> Probe:
    """Ask the backend the smallest version of the question the measurement will ask.

    Returns rather than raises, and distinguishes the three answers a caller must treat differently:
    reachable and capable of what the run needs; reachable but refusing this combination of features, which
    is an endpoint fact and not a model fact; and not reachable at all.
    """
    code, body = _post(ep, _wire_path(ep.wire), _minimal_body(ep, with_tools=needs_tools, extra=extra))
    if code == 0:
        return Probe(UNREACHABLE, ep.wire, detail=str(body))
    if code >= 400:
        msg = body.get("error", {}).get("message", "") if isinstance(body, dict) else str(body)
        detail = f"HTTP {code}: {msg[:300]}"
        if needs_tools:
            # Distinguish "this endpoint will not do tools plus whatever else was asked" from "this endpoint
            # is broken", by asking again without tools. The answer changes what a caller should do: the
            # first needs the other wire or a different parameter set, the second needs the operator.
            again = _post(ep, _wire_path(ep.wire), _minimal_body(ep, with_tools=False, extra=extra))
            if again[0] < 400:
                return Probe(INCOMPATIBLE, ep.wire, supports_tools=False,
                             detail=(f"{detail}. The same request without tools succeeds, so this is an "
                                     "endpoint restriction on tools rather than a model limitation. Measure "
                                     "it over the other wire, or record it as unmeasurable here -- do not "
                                     "record the resulting zero as a score."))
        return Probe(INCOMPATIBLE, ep.wire, detail=detail)
    ident = None
    if isinstance(body, dict):
        ident = body.get("model") or (body.get("response") or {}).get("model")
    return Probe(OK, ep.wire, supports_tools=needs_tools or None, reported_identity=ident,
                 refused_params=ep.refuses_params)


def negotiate(ep: Endpoint, *, needs_tools: bool = True) -> tuple[Endpoint, Probe]:
    """Find a wire this backend will accept for the run, and say which one it was.

    Tries the declared wire first, because a declaration is worth something even though it is not evidence.
    Falls back to the other wire only when the first refuses the feature combination, which is how the
    0-of-20 arm was eventually measured properly.
    """
    probe = preflight(ep, needs_tools=needs_tools)
    if probe.may_measure or probe.status == UNREACHABLE:
        return ep, probe
    other = RESPONSES if ep.wire == CHAT else CHAT
    alt = Endpoint(**{**ep.__dict__, "wire": other})
    alt_probe = preflight(alt, needs_tools=needs_tools)
    if alt_probe.may_measure:
        alt_probe.detail = (f"the declared wire {ep.wire!r} refused this feature combination and {other!r} "
                            f"accepts it; the record must say {other!r}, since a score belongs to the "
                            "transport it was measured over")
        return alt, alt_probe
    return ep, probe


def gateway_fingerprint(ep: Endpoint) -> str | None:
    """A content address for the gateway's observable surface, or None when it cannot be read.

    A version string is a pin the operator writes down, and a pin nobody can check is worth little. So this
    is computed instead of declared: the sorted model identifiers the gateway advertises, each with whatever
    wire it declares for them. Two reasons that is the right surface to hash.

    It is what a measurement actually depended on. Which models exist, and which wire each one speaks, decides
    what was measurable and how it was measured -- a tier scored 0 of 20 here purely because of the wire it
    was reached over.

    And it changes when the substrate changes even if nobody bumps a version. That is not hypothetical: the
    operators of the gateway this project uses found that their model list was generated from a
    hand-maintained table rather than from the registry the request path dispatches on, and that five servable
    models appeared in no list at all. A surface that can be wrong that way can also change quietly, and a
    fingerprint notices while a version string does not.

    Deliberately **not** an error when it cannot be read. An unreachable gateway is a different problem from a
    changed one, and conflating them would make this refuse during an outage.
    """
    code, body = _get(ep, "/models")
    if code != 200 or not isinstance(body, dict):
        return None
    entries = body.get("data") or body.get("models") or []
    parts = []
    for m in sorted(entries, key=lambda m: str(m.get("id") or "")):
        mid = m.get("id")
        if not mid:
            continue
        parts.append(f"{mid}\x1f{m.get('wire_protocol') or ''}")
    if not parts:
        return None
    return "surface:" + hashlib.sha256("\x1e".join(parts).encode()).hexdigest()[:16]


def substrate_matches(ep: Endpoint, record: dict) -> str | None:
    """Whether the thing in front still is the thing a record was measured against.

    Returns None when it matches or cannot be checked, and a description when it does not. Two checks, in
    order of how much they are worth:

      1. **the pinned version.** If configuration pins one and the record was measured against one and they
         disagree, the record is about a different gateway. This is the check the operator controls.
      2. **the observable surface.** Computed rather than declared, so it catches a substrate that moved
         without anyone bumping a version.

    Neither is an error when absent. A record measured before either existed is a record about a moving
    target, which is worth saying rather than refusing over.
    """
    target = record.get("measurement_target") or {}
    pinned, measured = ep.gateway_version, target.get("gateway_version")
    if pinned and measured and str(pinned) != str(measured):
        return (f"configuration pins gateway version {pinned!r} and this record was measured against "
                f"{measured!r}. A gateway decides the wire, the parameters it forwards, the prices it charges "
                "against and what it calls success, so a record taken against one version does not describe "
                "another.")
    was = target.get("gateway_surface")
    if was:
        now = gateway_fingerprint(ep)
        if now and now != was:
            return (f"the gateway's observable surface is {now} and this record was measured against {was}. "
                    "The set of models it advertises, or the wire it declares for one of them, has changed. "
                    "That may be benign, but it is not the substrate the measurement was taken on.")
    # Silence is only correct when a comparison actually happened. If either side is missing, nothing was
    # compared, and saying nothing would let "unpinned" read exactly like "checked and fine" -- which is the
    # shape of the defect this whole module exists to avoid one layer down.
    if not (pinned and measured) and not was:
        missing = []
        if not pinned:
            missing.append("configuration does not pin `endpoint.gateway_version`")
        if not measured:
            missing.append("this record has no `measurement_target.gateway_version`")
        return (f"{' and '.join(missing)}, so nothing here can detect the thing in front being replaced. "
                "Record the gateway version and its surface fingerprint when you measure, or treat this "
                "record as describing a moving substrate.")
    return None


def identity_matches(ep: Endpoint, record: dict) -> str | None:
    """Whether the backend still serves what the record was measured against.

    Returns None when it does, and a description when it does not. Deliberately cheap: it protects the one
    promise the ledger makes, which is that a claim traces to evidence about the thing behind the name. A
    name silently repointed at a new checkpoint breaks that promise without breaking anything visible.
    """
    target = (record.get("measurement_target") or {})
    want = target.get("revision") or ep.revision
    if not want:
        return ("neither the record nor the configuration pins a revision, so nothing here can detect the "
                "backend being repointed at a different checkpoint; treat the record as describing a moving "
                "target")
    code, body = _get(ep, "/models")
    if code != 200 or not isinstance(body, dict):
        return None      # cannot check is not the same as does not match; say nothing rather than guess
    for m in (body.get("data") or []):
        if m.get("id") != ep.model:
            continue
        # `revision` only. NOT `created_at`, which this project previously fell back to: the gateway team
        # measured that their `/v1/models` generates `created_at` at request time, so it is neither a
        # registration date nor a model revision. Comparing it against a stored value would report a mismatch
        # on every single call -- a refusal that always fires, which is worse than one that never does,
        # because it teaches an operator to ignore the one warning that protects the ledger's core promise.
        got = m.get("revision")
        if got is None:
            return (f"the backend does not report a revision for {ep.model!r}, so nothing here can detect it "
                    "being repointed at a different checkpoint. The gateway does not guarantee identifying "
                    "the checkpoint behind a provider-managed alias, so treat this record as describing a "
                    "moving target rather than assuming stability.")
        if got and str(got) != str(want):
            return (f"the backend reports {ep.model!r} at revision {got!r} and the record was measured at "
                    f"{want!r}; the record does not describe what is behind this name any more")
        return None
    return (f"the backend no longer advertises {ep.model!r}; the record cannot be checked against what is "
            "actually serving")


@dataclass
class Backend:
    """A configured endpoint plus what pre-flight learned about it, which is what a measurement should use."""

    endpoint: Endpoint
    probe: Probe | None = None
    dropped: tuple[str, ...] = field(default_factory=tuple)

    def prepared(self, body: dict) -> dict:
        """Strip the parameters this endpoint refuses, and record that it happened.

        A silently dropped parameter is how two arms end up measured under different conditions without
        anybody noticing. Twice in this project a comparator was accidentally weakened that way -- once with
        reasoning off on one side only -- so what was dropped belongs in the record next to the score.
        """
        out = dict(body)
        dropped = []
        for k in self.endpoint.refuses_params:
            if k in out:
                out.pop(k)
                dropped.append(k)
        self.dropped = tuple(dropped)
        return out

    def note_for_record(self) -> dict:
        p = self.probe
        return {
            "base_url": self.endpoint.base_url,
            "model": self.endpoint.model,
            "wire_used": (p.wire if p else self.endpoint.wire),
            "revision": self.endpoint.revision,
            "parameters_dropped": list(self.dropped),
            "preflight": (None if not p else {"status": p.status, "detail": p.detail}),
        }
