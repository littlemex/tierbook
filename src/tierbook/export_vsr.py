"""Emit a vLLM Semantic Router configuration whose decisions are the compiled table's decisions.

The division of labour, which is the only interesting thing in this module:

    the router          sees the request, classifies it into a family, and names a model
    Envoy               owns the connection and dials whichever upstream the router named
    the compiled table  says which tier that family goes to, and why
    this exporter       turns the table into the router's configuration, and refuses when it cannot

The router is not asked to decide anything. It has a multi-factor selector of its own -- weighted quality,
latency and cost -- and this exporter deliberately does not use it, because a selector fed by live
per-process statistics is choosing from evidence nobody committed to and nobody can review after an incident.
What it emits instead is a priority decision per family naming exactly one model: the one a held-out fold
supported. `quality_score` on each model card is therefore **not** a routing input here; it is recorded
because the schema carries it and a reader will want to see what the ledger measured, and the decisions
reference exactly one model each so nothing scores anything.

Four refusals, each of which would otherwise become a silent behaviour:

  * **a family with no compiled entry gets no decision.** Not a default, not the cheapest, not the reference.
    Unclassified traffic reaches the router's own default model, which the operator sets deliberately.
  * **a `provisional` entry is not exported** unless the caller passes the awkward flag, and then the emitted
    config carries the fact in its description where a reviewer reading the file will see it.
  * **a chain is not exported as a chain.** The compiled table can produce a two-stage arrangement whose
    escalation is conditional on failures the router does not observe. Exporting the head alone would quietly
    drop the safety net, so a chain is refused and named.
  * **a family whose classifier label is not declared is refused.** The label set belongs to whichever
    classifier the operator chose; guessing a mapping routes traffic using evidence about different traffic.

## Why the shapes here are not invented

Every key below matches a configuration this project has actually run: `v0.3`, with `providers.models[]`
carrying `backend_refs` rather than a bare address, `decisions[].rules.conditions` rather than a `signals`
block per decision, and `signals.domains[]` as objects rather than bare strings. An earlier version of this
exporter guessed those three and produced a file no router would load -- which is the exact failure mode this
module exists to prevent one layer up, so it is worth naming here rather than quietly fixing.
"""
from __future__ import annotations

import json
from pathlib import Path

from tierbook.config import Candidate, Config
from tierbook.validate import ASSIGNED

CONFIG_VERSION = "v0.3"

#: How a backend is reached, keyed by what tierbook already knows about the candidate. `openai` is the
#: OpenAI-compatible surface a vendor or gateway presents; `vllm` is a model server run in the operator's own
#: cluster. The distinction exists in the router because the two need different upstream handling, and it
#: happens to line up with the one distinction tierbook's cost model already makes.
_BACKEND_TYPE = {"api": "openai", "self_hosted": "vllm"}


class ExportError(RuntimeError):
    """The table and the requested router configuration cannot be reconciled; say which, do not guess."""


def _endpoint_of(cand: Candidate) -> tuple[str, str]:
    """`host:port` and the transport protocol, from the candidate's base URL.

    Envoy dials a host and a port; it does not take a URL. The path is deliberately dropped: Envoy forwards
    the client's own path to the upstream, and pinning one here would turn the backend into a fixed endpoint
    whose address then has to come from somewhere else.
    """
    from urllib.parse import urlparse

    u = urlparse(cand.endpoint.base_url)
    if not u.scheme or not u.hostname:
        raise ExportError(
            f"candidate {cand.id!r} has base_url {cand.endpoint.base_url!r}, which has no scheme and host to "
            "give Envoy. A router config needs a host and a port to dial, not a bare path."
        )
    port = u.port or (443 if u.scheme == "https" else 80)
    return f"{u.hostname}:{port}", u.scheme


def _provider_model(cand: Candidate) -> dict:
    """One entry in `providers.models[]`, in the shape the router actually reads.

    `backend_refs` is the part an earlier version of this exporter omitted, and omitting it is not a cosmetic
    difference: without it the router has a model name and no way to reach anything.
    """
    endpoint, protocol = _endpoint_of(cand)
    backend_type = _BACKEND_TYPE[cand.deployment]
    ref: dict = {
        "name": f"{cand.id}-primary",
        "endpoint": endpoint,
        "protocol": protocol,
        "type": backend_type,
        "weight": 1,
    }
    if cand.endpoint.api_key_env:
        # The NAME of an environment variable, never a key. The router resolves it in its own process, which
        # is why a candidate file stays safe to commit.
        ref["api_key_env"] = cand.endpoint.api_key_env
    entry: dict = {
        "name": cand.id,
        "provider_model_id": cand.endpoint.model,
        "api_format": "openai",
        "backend_refs": [ref],
        # What actually goes on the wire to the backend. The router's own name for a tier is a tierbook id;
        # the upstream has never heard of it.
        "external_model_ids": {backend_type: cand.endpoint.model},
    }
    if cand.price_per_mtok:
        # Translated into the router's own key names so its accounting agrees with the ledger's. The ledger
        # calls a rate `fresh_in`; the router calls the same rate `prompt_per_1m`, and it logs an unknown-field
        # warning for every key it does not recognise -- a config that warns on every start teaches an
        # operator to ignore warnings, so the translation happens here rather than being left to them.
        pr = cand.price_per_mtok
        entry["pricing"] = {"currency": "USD"}
        for ledger_key, router_key in (("fresh_in", "prompt_per_1m"), ("out", "completion_per_1m"),
                                       ("output", "completion_per_1m"), ("cached_in", "cached_input_per_1m")):
            if pr.get(ledger_key) is not None:
                entry["pricing"][router_key] = float(pr[ledger_key])
    return entry


def _model_card(cand: Candidate, *, description: str, quality: float | None) -> dict:
    card: dict = {
        "name": cand.id,
        "description": description,
        "modality": "ar",
        "tags": [f"deployment:{cand.deployment}", f"wire:{cand.endpoint.wire}", "selector:unused"],
    }
    if quality is not None:
        # Recorded, not used. The decisions below name one model each, so nothing here is scored against
        # anything -- and a reader who sees a quality figure in a router config would reasonably assume the
        # router is choosing on it, which is why the tag above says it is not.
        card["quality_score"] = round(quality, 4)
    return card


def export(
    table: dict,
    cfg: Config,
    *,
    signal_for_family: dict[str, str],
    default_model: str,
    listener_port: int = 8801,
    entrypoint: str = "tierbook/routed",
    request_can_reject: bool = False,
    allow_provisional: bool = False,
    signal_kind: str = "domain",
    signal_categories: dict[str, list[str]] | None = None,
) -> tuple[dict, dict]:
    """Build the router config, and the provenance that travels beside it. `signal_for_family` maps a tierbook family to a classifier label.

    Supplied by the caller rather than inferred: the classifier's label set is a property of the classifier
    the operator chose, and a family this project measured has no reason to share a name with one of its
    labels. A family with no label is refused rather than mapped to something plausible.

    `signal_categories` carries whatever the chosen classifier keys each label on -- for the MMLU domain
    classifier that is a list of categories. Left empty, a label is declared by name alone, which is correct
    for a classifier that needs no further configuration and wrong for one that does. This exporter cannot
    tell which, so it passes the caller's answer through instead of inventing one.
    """
    families = table.get("families") or {}
    if not families:
        raise ExportError("the compiled table has no families, so there is nothing to configure")
    if entrypoint in RESERVED_ENTRYPOINTS:
        raise ExportError(
            f"entrypoint {entrypoint!r} is a name the router reserves for its own auto-model alias, so it "
            "refuses to start with it. An entrypoint is the virtual model name a client asks for; pick a new "
            "one such as 'tierbook/routed'."
        )

    decisions: list[dict] = []
    used: dict[str, str] = {}        # candidate id -> why it is in this config
    skipped: list[str] = []
    for family, entry in families.items():
        d = entry["can_reject" if request_can_reject else "cannot_reject"]
        status = d.get("status")
        if status != ASSIGNED and not allow_provisional:
            skipped.append(f"{family} ({status}: {(d.get('validation') or {}).get('reason', '')[:120]})")
            continue
        if d["kind"] == "chain":
            raise ExportError(
                f"the entry for {family!r} is a chain {d['chosen']}, whose second stage fires only on "
                "failures the router does not observe (an empty stream, an unusable action stream, a check "
                "that rejected the artifact). Exporting the head alone would drop the safety net that "
                "justified the arrangement. Either give the router those signals or compile with "
                "request_can_reject=False for this family."
            )
        signal = signal_for_family.get(family)
        if not signal:
            raise ExportError(
                f"family {family!r} has a compiled entry but no classifier label in signal_for_family "
                f"(given: {sorted(signal_for_family)}). Map it to a label the classifier actually emits, or "
                "remove the family -- guessing the mapping would route this traffic on evidence about other "
                "traffic."
            )
        chosen = d["chosen"][0]
        if chosen not in cfg.candidates:
            raise ExportError(
                f"the table assigns {family!r} to {chosen!r}, which is not in the candidate configuration "
                f"({cfg.source}). The table was compiled against a different candidate set; reconcile them "
                "rather than exporting a name the router cannot reach."
            )
        used[chosen] = (f"assigned for {family} by tierbook: {d['why'][:200]}"
                        + ("" if status == ASSIGNED else f" [{status.upper()}: no held-out fold supports this]"))
        decisions.append({
            "name": f"tierbook_{family.replace('-', '_').replace(' ', '_')}",
            "description": (f"{family}: compiled at margin {table.get('margin')} from registry "
                            f"{table.get('registry_version')}, status {status}. One model, no scoring."),
            "priority": 100,
            # `rules`, not a per-decision `signals` block. An earlier version of this exporter used the
            # latter and the router did not read it.
            "rules": {"operator": "AND", "conditions": [{"type": signal_kind, "name": signal}]},
            "modelRefs": [{"model": chosen, "use_reasoning": False}],
        })

    if not decisions:
        raise ExportError(
            "no family produced an exportable decision. Skipped: " + "; ".join(skipped) +
            ". Every entry is provisional, which means no held-out fold supports it; measure a second cohort "
            "or pass allow_provisional=True and accept that the config records it."
        )
    if default_model not in cfg.candidates:
        raise ExportError(f"default_model {default_model!r} is not a configured candidate")
    used.setdefault(default_model, (
        "the default for traffic no decision matched. Deliberately not the cheapest tier: an unclassified "
        "request is one tierbook has no evidence about, and the tier with the best measured quality is the "
        "only defensible answer in the absence of evidence."))

    quality = _quality_scores(table)
    members = [cfg.candidates[cid] for cid in sorted(used)]
    cards = [_model_card(c, description=used[c.id], quality=quality.get(c.id)) for c in members]
    labels = sorted(set(signal_for_family.values()))
    cats = signal_categories or {}
    signals = {"domains": [
        {"name": label, "description": f"tierbook traffic family label {label!r}.",
         **({"mmlu_categories": cats[label]} if label in cats else {})}
        for label in labels
    ]}
    routing = {"strategy": "priority", "modelCards": cards, "signals": signals, "decisions": decisions}
    # The model catalog is shared across recipes, so a recipe may carry the strategy, the signals and the
    # decisions but NOT the cards. The router refuses to start otherwise, naming that exact reason -- so this
    # is not a cosmetic difference and the two dicts must stay distinct.
    recipe_routing = {"strategy": "priority", "signals": signals, "decisions": decisions}
    recipe = "tierbook"
    provenance = {
            "compiled_from_registry": table.get("registry_version"),
            "table_compiled_at": table.get("compiled_at"),
            "margin": table.get("margin"),
            "objective": table.get("objective", "cost"),
            "request_can_reject": request_can_reject,
            "families_skipped": skipped,
            "note": ("Decisions here are lookups, not a live selector: each names exactly one model. "
                     "Recompile the table and re-export when the ledger changes; the registry hash above is "
                     "how a reviewer checks that this file still matches the evidence."),
    }
    config = {
        "version": CONFIG_VERSION,
        "listeners": [{"name": f"http-{listener_port}", "address": "0.0.0.0", "port": listener_port,
                       "timeout": "1200s"}],
        "providers": {"defaults": {"default_model": default_model},
                      "models": [_provider_model(c) for c in members]},
        "routing": routing,
        "entrypoints": [{"model_names": [entrypoint], "recipe": recipe}],
        "recipes": [{"name": recipe,
                     # The registry hash lives in a field the schema accepts, so a reader of the config alone
                     # can still check that it matches the ledger it was compiled from.
                     "description": (f"one decision per measured traffic family, each naming the tier a "
                                     f"held-out fold supported at margin {table.get('margin')}. Compiled "
                                     f"from registry {table.get('registry_version')} on "
                                     f"{table.get('compiled_at')}."),
                     "routing": recipe_routing}],
        "global": {"router": {"config_source": "file", "strategy": "priority"},
                   # The classification API answers "which decision would this request take" without calling
                   # a model, which is how an operator checks the routing without spending anything. It binds
                   # to loopback by default; acknowledging that it is container-local is what lets it start.
                   "services": {"management_api": {"bind_address": "127.0.0.1"}}},
    }
    return config, provenance


def _quality_scores(table: dict) -> dict[str, float]:
    """Each tier's measured solve rate on whichever family it appears in, for the record only.

    Read out of the table's own evidence block rather than recomputed, so this cannot disagree with what the
    compiler saw. Not a routing input: see `_model_card`.
    """
    out: dict[str, float] = {}
    for entry in (table.get("families") or {}).values():
        for row in ((entry.get("evidence") or {}).get("tiers") or []):
            n, solved = row.get("attempted"), row.get("solved")
            if n and solved is not None:
                out.setdefault(row["tier"], solved / n)
    return out


#: Virtual model names the router reserves for itself. Asking for one as an entrypoint is refused at start-up
#: with a stack trace, so it is refused here instead, where the name is chosen.
RESERVED_ENTRYPOINTS = frozenset({"auto"})

#: Ports the router itself binds inside the container. The ExtProc and the data plane share a network
#: namespace on purpose -- the ExtProc call is on the request path for every request, so crossing a node
#: boundary would add network variance to every latency the router reports -- which means a data-plane
#: listener on one of these does not produce a configuration error. It produces one process failing to bind,
#: discovered as a crash loop rather than as a refusal.
ROUTER_RESERVED_PORTS = {50051: "the ExtProc gRPC listener", 8080: "the router's classification API",
                         9190: "the router's metrics endpoint"}


def envoy_config(cfg: Config, used: list[str], *, listen_port: int = 8801,
                 extproc_host: str = "127.0.0.1", extproc_port: int = 50051) -> dict:
    """The data plane. Envoy owns the connection; the router only names a model.

    Emitted here because a router config alone routes nothing: the ExtProc names a model in a header and
    something has to dial the upstream it refers to. One cluster per distinct address and one route per
    model name, so adding a tier to the ledger never needs an Envoy edit by hand.
    """
    if listen_port in ROUTER_RESERVED_PORTS:
        raise ExportError(
            f"the data plane cannot listen on {listen_port}: that is {ROUTER_RESERVED_PORTS[listen_port]}, "
            "and the two share a network namespace because the ExtProc call must stay on loopback. A "
            f"collision here does not fail as a config error -- it fails as one process not binding. Pick "
            f"another port; {8801} is the conventional one."
        )
    clusters: list[dict] = []
    routes: list[dict] = []
    by_endpoint: dict[str, str] = {}
    for cid in used:
        cand = cfg.candidates[cid]
        endpoint, protocol = _endpoint_of(cand)
        host, _, port = endpoint.partition(":")
        cluster_name = by_endpoint.get(endpoint)
        if not cluster_name:
            cluster_name = f"{cid.replace('.', '-').replace('/', '-')}_cluster"
            by_endpoint[endpoint] = cluster_name
            clusters.append(_cluster(cluster_name, host, int(port), tls=(protocol == "https")))
        routes.append({
            "match": {"prefix": "/", "headers": [{"name": "x-selected-model",
                                                  "string_match": {"exact": cid}}]},
            "route": {"cluster": cluster_name, "timeout": "1200s",
                      **({"host_rewrite_literal": host} if protocol == "https" else {})},
        })
    # A request that arrives with no usable decision must not be answered by whichever cluster happens to be
    # first. 503 with a body saying so is the honest outcome: the router refused, and the caller should see
    # that rather than a silently pinned tier.
    routes.append({"match": {"prefix": "/"},
                   "direct_response": {"status": 503, "body": {"inline_string":
                       "tierbook: no decision named a model for this request, so nothing was dialled\n"}}})
    return {
        "admin": {"address": {"socket_address": {"address": "127.0.0.1", "port_value": 9901}}},
        "static_resources": {
            "listeners": [{
                "name": "ingress",
                "address": {"socket_address": {"address": "0.0.0.0", "port_value": listen_port}},
                "filter_chains": [{"filters": [{
                    "name": "envoy.filters.network.http_connection_manager",
                    "typed_config": {
                        "@type": ("type.googleapis.com/envoy.extensions.filters.network."
                                  "http_connection_manager.v3.HttpConnectionManager"),
                        "stat_prefix": "tierbook",
                        "route_config": {"name": "local", "virtual_hosts": [
                            {"name": "all", "domains": ["*"], "routes": routes}]},
                        "http_filters": [
                            {"name": "envoy.filters.http.ext_proc", "typed_config": {
                                "@type": ("type.googleapis.com/envoy.extensions.filters.http."
                                          "ext_proc.v3.ExternalProcessor"),
                                "grpc_service": {"envoy_grpc": {"cluster_name": "extproc"}},
                                "processing_mode": {"request_header_mode": "SEND",
                                                    "request_body_mode": "BUFFERED",
                                                    "response_header_mode": "SKIP",
                                                    "response_body_mode": "NONE"},
                                "message_timeout": "60s"}},
                            {"name": "envoy.filters.http.router", "typed_config": {
                                "@type": ("type.googleapis.com/envoy.extensions.filters.http."
                                          "router.v3.Router")}},
                        ],
                    }}]}],
            }],
            "clusters": clusters + [_extproc_cluster(extproc_host, extproc_port)],
        },
    }


def _cluster(name: str, host: str, port: int, *, tls: bool) -> dict:
    c: dict = {
        "name": name, "type": "STRICT_DNS", "connect_timeout": "10s",
        "load_assignment": {"cluster_name": name, "endpoints": [{"lb_endpoints": [
            {"endpoint": {"address": {"socket_address": {"address": host, "port_value": port}}}}]}]},
    }
    if tls:
        c["transport_socket"] = {"name": "envoy.transport_sockets.tls", "typed_config": {
            "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
            "sni": host}}
    return c


def _extproc_cluster(host: str, port: int) -> dict:
    return {
        "name": "extproc", "type": "STATIC", "connect_timeout": "5s",
        # HTTP/2 because ExtProc is gRPC. Over loopback deliberately: the ExtProc call is on the request path
        # for every request, so crossing a node boundary would add network variance to every latency the
        # router reports.
        "typed_extension_protocol_options": {
            "envoy.extensions.upstreams.http.v3.HttpProtocolOptions": {
                "@type": ("type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions"),
                "explicit_http_config": {"http2_protocol_options": {}}}},
        "load_assignment": {"cluster_name": "extproc", "endpoints": [{"lb_endpoints": [
            {"endpoint": {"address": {"socket_address": {"address": host, "port_value": port}}}}]}]},
    }


def models_used(config: dict) -> list[str]:
    return [m["name"] for m in config["providers"]["models"]]


def write(config: dict, out: str | Path) -> Path:
    p = Path(out)
    p.write_text(json.dumps(config, indent=2) + "\n")
    return p
