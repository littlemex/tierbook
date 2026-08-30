"""What may be considered, kept mechanically separate from what was observed.

Two files, and the boundary between them is the whole point:

    candidates.json   what MAY be measured -- reachable endpoints, and the priced inputs no measurement
                      can produce. Every value in it is an unverified claim by whoever wrote it.
    <ledger>/tiers/   what WAS observed. Only this can route.

The separation is enforced rather than described. A key that exists in the record schema is **illegal in a
candidate entry**, so a hand-written "accuracy": 0.9 or "solved": 18 cannot be smuggled into the thing the
compiler trusts by editing the easier file. This is mechanical on purpose: a rule that lives in prose is a
rule that a busy operator edits around at two in the morning.

Two refusals sit here rather than in a document:

  * **a candidate that describes how to START a model is rejected.** `image`, `weights`, `launch`, `command`,
    `replicas`, `gpu` and their kin belong to whoever owns the cluster. This component decides where a
    request goes; it does not own a lifecycle, and the way to mean that is for the file to fail to load.
  * **a candidate is not a measurement.** A candidate with no records is visible as unmeasured, and routing
    to it raises. Removing a candidate de-lists it and never deletes its records: the ledger is append-only,
    because a decision made last week must stay explicable after the candidate is gone.

Discovery from a gateway is a stationery printer, not a runtime feature. `tierbook discover` prints a draft
candidate file for a human to edit and commit. Reading a live model list at compile or route time would make
a routing decision depend on a gateway's publication state that nobody committed to, which is the one thing
this project exists to refuse.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FORMAT = 1

# Keys that describe how to bring a model into existence rather than how to reach one. Rejected with the
# name of the boundary they cross, because the person who wrote them is usually doing something reasonable
# in the wrong file.
LIFECYCLE_KEYS = (
    "image", "images", "weights", "model_path", "checkpoint", "launch", "command", "args", "entrypoint",
    "replicas", "gpu", "gpus", "accelerator", "resources", "node_selector", "nodeSelector", "tolerations",
    "helm", "chart", "manifest", "kustomize", "docker", "compose", "systemd", "engine_args", "serve",
)

# Keys that only a measurement may set. Derived from the record schema at load time so the two cannot drift,
# with a small identity allowlist: a candidate must be able to say which tier it is, or the join has no key.
JOIN_KEYS = frozenset({"id", "schema_version"})


class ConfigError(ValueError):
    """A candidate file that cannot be loaded, with the boundary it crossed named in the message."""


@dataclass(frozen=True)
class Endpoint:
    """How to reach a candidate. Generic by construction: anything that speaks an OpenAI-compatible wire.

    `base_url` is a URL and nothing more. A gateway in front, a vendor API, a model server on the cluster
    next door, something behind a corporate proxy -- this module cannot tell them apart and deliberately does
    not try. `deployment` distinguishes them only where the *cost model* must differ: a per-token bill and an
    hourly bill are arithmetic, not architecture.

    `gateway_version` pins whatever sits in front. This matters for the same reason `revision` does and is
    more tractable: a provider will not tell you which checkpoint is behind an alias, but a gateway you or
    your organisation runs can be asked which version it is. A gateway changes what a measurement means --
    it decides the wire, the parameters it forwards, the prices it charges against, and what it reports as
    success -- so a record taken against one version does not describe another. Pinned here, recorded in the
    measurement, and checked before routing.
    """

    base_url: str
    model: str
    wire: str = "chat"                  # "chat" | "responses"; declared, then pre-flighted before measuring
    api_key_env: str | None = None      # the NAME of an environment variable, never a key
    revision: str | None = None         # pinned identity, checked against the record at route time
    gateway_version: str | None = None  # the pinned version of whatever sits in front, if anything does
    refuses_params: tuple[str, ...] = ()  # parameters this endpoint rejects, discovered by pre-flight
    headers: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 600.0


@dataclass(frozen=True)
class Candidate:
    """One thing that may be measured, and the priced inputs measurement cannot produce.

    Prices live here because they are quoted, not observed -- but the record that consumes them cites them,
    so a price change invalidates the record rather than silently repricing an old decision.
    """

    id: str
    endpoint: Endpoint
    deployment: str                       # "api" (per token) | "self_hosted" (per hour)
    price_per_mtok: dict[str, float] | None = None   # api: fresh_in / cached_in / out
    hourly_usd: float | None = None                  # self_hosted: the bill while it is up
    note: str = ""

    @property
    def is_fixed_cost(self) -> bool:
        return self.deployment == "self_hosted"


@dataclass(frozen=True)
class Objective:
    """One objective and the constraints that cannot be switched off.

    There are no axis switches. Three checkboxes labelled accuracy, performance and cost would misdescribe
    the problem in a way that leaks into every later decision:

      * **accuracy is a constraint, not a preference.** There is no syntax for removing `margin`, because a
        router that may trade quality for money without a stated bound is choosing an unstated exchange rate
        on its owner's behalf.
      * **reliability cannot be deselected because it is the denominator.** Both objectives are computed to
        *acceptance*, not per attempt: a failure means paying the attempt again, in dollars if the objective
        is cost and in seconds if it is latency. Measured here once: retries reordered the arrangements.
      * **latency is not automatically a constraint.** For a fixed-capacity tier it is an input to the cost
        model, via throughput. Turning that into an SLO would invent a requirement nobody stated. If an SLO
        is genuinely wanted it is written down, separately and optionally.

    Weights are refused rather than defaulted. Once quality is a weighted term, "cheapest" stops denoting
    anything a reader can check.
    """

    objective: str = "cost"               # "cost" | "latency", each expected-to-acceptance
    margin: float = 0.15                  # mandatory: no key removes it
    alpha: float = 0.05
    latency_slo_p95_ms: float | None = None
    min_completion_probability: float | None = None
    max_age_days: int = 90

    def __post_init__(self) -> None:
        if self.objective not in ("cost", "latency"):
            raise ConfigError(f"objective must be 'cost' or 'latency', not {self.objective!r}")
        if not 0.0 < self.margin < 1.0:
            raise ConfigError(f"margin must be a solve-rate difference in (0, 1), not {self.margin!r}")


@dataclass(frozen=True)
class Config:
    candidates: dict[str, Candidate]
    families: dict[str, str]              # family -> reference candidate id
    objective: Objective
    throughput_per_family: dict[str, float] = field(default_factory=dict)
    source: str = ""

    def reference_for(self, family: str) -> str:
        try:
            return self.families[family]
        except KeyError:
            raise ConfigError(
                f"no reference candidate configured for family {family!r}; the configured families are "
                f"{sorted(self.families)}"
            ) from None


def _record_schema_keys(schema_path: str | Path | None = None) -> frozenset[str]:
    """Every key a record may set, so a candidate entry can be refused for setting one.

    Read from the schema rather than listed here: a hand-maintained copy of this set would fall behind the
    schema, and the first field it missed would be the one someone hand-edited.

    Defaults to the schema packaged with the code, and raises rather than returning an empty set when it is
    missing. An earlier version fell back to "no forbidden keys" when it could not find a schema file, which
    silently disabled this refusal in exactly the case that matters -- a candidate file deployed on its own,
    nowhere near a ledger.
    """
    from tierbook import SCHEMA_PATH

    p = Path(schema_path) if schema_path is not None else SCHEMA_PATH
    if not p.exists():
        raise ConfigError(
            f"the record schema is missing at {p}. It is what decides which keys a candidate file may not "
            "contain, so loading configuration without it would drop that check rather than apply it."
        )
    schema = json.loads(p.read_text())
    keys: set[str] = set(schema.get("properties") or {})
    fam = ((schema.get("properties") or {}).get("families") or {})
    for holder in ("additionalProperties", "patternProperties"):
        node = fam.get(holder)
        if isinstance(node, dict):
            for sub in ([node] if "properties" in node else node.values()):
                if isinstance(sub, dict):
                    keys |= set(sub.get("properties") or {})
    return frozenset(keys - JOIN_KEYS)


def _reject_illegal(cid: str, raw: dict, observed: frozenset[str]) -> None:
    lifecycle = sorted(k for k in raw if k in LIFECYCLE_KEYS)
    if lifecycle:
        raise ConfigError(
            f"candidate {cid!r} sets {lifecycle}, which describes how to START a model rather than how to "
            "reach one. Serving is the cluster owner's responsibility; tierbook connects to what is already "
            "running. Give it a base_url instead."
        )
    measured = sorted(k for k in raw if k in observed)
    if measured:
        raise ConfigError(
            f"candidate {cid!r} sets {measured}, which only a measurement may set -- those keys exist in the "
            "record schema. Configuration says what may be measured; the ledger says what was observed, and "
            "only the ledger can route. Measure it and write a record."
        )


def load_config(path: str | Path, *, schema: str | Path | None = None) -> Config:
    """Read a candidate file, refusing the two things it must not contain."""
    p = Path(path)
    raw = json.loads(p.read_text())
    if raw.get("config_format") != CONFIG_FORMAT:
        raise ConfigError(f"{p}: config_format must be {CONFIG_FORMAT}, found {raw.get('config_format')!r}")
    observed = _record_schema_keys(schema)

    candidates: dict[str, Candidate] = {}
    for cid, entry in (raw.get("candidates") or {}).items():
        if not isinstance(entry, dict):
            raise ConfigError(f"candidate {cid!r} must be an object")
        _reject_illegal(cid, entry, observed)
        ep = entry.get("endpoint") or {}
        _reject_illegal(f"{cid}.endpoint", ep, observed)
        if not ep.get("base_url") or not ep.get("model"):
            raise ConfigError(
                f"candidate {cid!r} needs endpoint.base_url and endpoint.model: the only thing tierbook "
                "needs to know about a backend is how to reach it and what to ask it for."
            )
        deployment = entry.get("deployment")
        if deployment not in ("api", "self_hosted"):
            raise ConfigError(f"candidate {cid!r}: deployment must be 'api' or 'self_hosted', not {deployment!r}")
        if deployment == "self_hosted" and entry.get("hourly_usd") is None:
            raise ConfigError(
                f"candidate {cid!r} is self_hosted with no hourly_usd. A machine bills while it is idle, so "
                "without its hourly bill its cost per request cannot be computed at all -- and an idle "
                "fixed-cost tier is infinitely expensive per request, which is the honest answer."
            )
        if deployment == "api" and not entry.get("price_per_mtok"):
            raise ConfigError(f"candidate {cid!r} is an api with no price_per_mtok; a token has to cost something")
        candidates[cid] = Candidate(
            id=cid,
            endpoint=Endpoint(
                base_url=ep["base_url"], model=ep["model"], wire=ep.get("wire", "chat"),
                api_key_env=ep.get("api_key_env"), revision=ep.get("revision"),
                gateway_version=ep.get("gateway_version"),
                refuses_params=tuple(ep.get("refuses_params") or ()),
                headers=dict(ep.get("headers") or {}), timeout_s=float(ep.get("timeout_s", 600.0)),
            ),
            deployment=deployment,
            price_per_mtok=entry.get("price_per_mtok"),
            hourly_usd=entry.get("hourly_usd"),
            note=entry.get("note", ""),
        )

    obj_raw = dict(raw.get("objective") or {})
    if "weights" in obj_raw:
        raise ConfigError(
            "objective.weights is refused. Quality is a constraint here, not a term in a weighted sum: "
            "once it is weighted, 'cheapest' no longer denotes anything a reader can check. Set a margin."
        )
    cons = dict(obj_raw.pop("constraints", None) or {})
    objective = Objective(
        objective=obj_raw.get("objective", "cost"),
        margin=float((cons.get("non_inferiority") or {}).get("margin", 0.15)),
        alpha=float((cons.get("non_inferiority") or {}).get("alpha", 0.05)),
        latency_slo_p95_ms=(cons.get("latency_slo") or {}).get("p95_ms"),
        min_completion_probability=(cons.get("reliability") or {}).get("min_completion_probability"),
        max_age_days=int(obj_raw.get("max_age_days", 90)),
    )
    families = dict(raw.get("families") or {})
    unknown = {f: r for f, r in families.items() if r not in candidates}
    if unknown:
        raise ConfigError(f"families name references that are not candidates: {unknown}")
    return Config(
        candidates=candidates, families=families, objective=objective,
        throughput_per_family={k: float(v) for k, v in (raw.get("throughput_per_family") or {}).items()},
        source=str(p),
    )


def draft_from_model_list(models: list[dict], *, base_url: str, api_key_env: str,
                          wire_by_id: dict[str, str] | None = None) -> dict:
    """Turn a gateway's model list into a draft candidate file for a human to edit and commit.

    Deliberately incomplete. Every draft entry carries `price_per_mtok: null` and a `note` saying so, which
    means the draft **does not load** until someone fills in what a token costs. A gateway advertises names;
    it does not tell you what it charges you, what it can do, or whether it is any good. A discovery feature
    that produced a loadable file would be inviting exactly the unrecorded premise this design refuses.
    """
    wire_by_id = wire_by_id or {}
    out = {
        "config_format": CONFIG_FORMAT,
        "_draft": ("Printed from a live model list. Nothing here is measured. Fill in price_per_mtok or "
                   "hourly_usd, delete what you will not measure, then commit it -- the file will not load "
                   "until you do, which is intentional."),
        "_draft_is_not_an_inventory": (
            "A model list is not the set of models a gateway can serve. On the gateway this project uses, "
            "the list was generated from a hand-maintained table rather than from the registry the request "
            "path dispatches on, and five servable models appeared in no list at all. So treat this draft as "
            "a starting point that may be missing entries, never as a complete inventory -- if a model you "
            "know exists is absent, add it by hand rather than concluding it is unavailable."),
        "candidates": {},
        "families": {},
        "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.15}}},
    }
    for m in models:
        mid = m.get("id") or m.get("model") or ""
        if not mid:
            continue
        out["candidates"][mid.replace("/", "-")] = {
            "deployment": "api",
            "endpoint": {"base_url": base_url, "model": mid, "wire": wire_by_id.get(mid, "chat"),
                         "api_key_env": api_key_env,
                         # `revision` or nothing. A model list's `created_at` is not a revision -- on the
                         # gateway this project uses it is generated at request time -- so falling back to it
                         # would write a timestamp into a field whose whole purpose is to pin a checkpoint.
                         "revision": m.get("revision") or None},
            "price_per_mtok": None,
            "note": "drafted from a model list; price and wire are unverified claims until someone checks them",
        }
    return out
