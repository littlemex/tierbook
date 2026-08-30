"""Emit a vLLM Semantic Router configuration whose decisions are the compiled table's decisions.

The division of labour, which is the only interesting thing in this module:

    the router          sees the request, classifies it into a family, owns the connection, retries
    the compiled table  says which tier that family goes to, and why
    this exporter       turns the second into the first's configuration file, and refuses when it cannot

The router is not asked to decide anything. It has a latency-and-cost selector of its own and this exporter
does not use it, because a selector fed by live per-process statistics is choosing from evidence nobody
committed to and nobody can review after an incident. What it emits instead is a priority decision per
family naming exactly one model: the one a held-out fold supported.

Three refusals, each of which would otherwise become a silent behaviour:

  * **a family with no compiled entry gets no decision.** Not a default, not the cheapest, not the reference.
    Unclassified traffic must reach the router's own default model, which the operator sets deliberately.
  * **a `provisional` entry is not exported** unless the caller passes the awkward flag, and then the emitted
    config carries the fact in its description where a reviewer reading the file will see it.
  * **a chain is not exported as a chain.** The compiled table can produce a two-stage arrangement, and its
    escalation is conditional on failures the router does not observe. Exporting the head alone would quietly
    drop the safety net, so a chain is refused and named.
"""
from __future__ import annotations

import json
from pathlib import Path

from tierbook.config import Config
from tierbook.validate import ASSIGNED


class ExportError(RuntimeError):
    """The table and the requested router configuration cannot be reconciled; say which, do not guess."""


def _member(cid: str, cfg: Config) -> dict:
    c = cfg.candidates[cid]
    ep = c.endpoint
    entry: dict = {"name": cid, "model": ep.model, "address": ep.base_url}
    if ep.api_key_env:
        entry["api_key_env"] = ep.api_key_env
    if c.price_per_mtok:
        # Passed through so the router's own accounting agrees with the ledger's. Not used for selection.
        entry["pricing"] = {k: float(v) for k, v in c.price_per_mtok.items()}
    return entry


def export(
    table: dict,
    cfg: Config,
    *,
    signal_for_family: dict[str, str],
    default_model: str,
    listener_port: int = 8801,
    entrypoint: str = "auto",
    request_can_reject: bool = False,
    allow_provisional: bool = False,
) -> dict:
    """Build the router config. `signal_for_family` maps a tierbook family to a classifier label.

    Supplied by the caller rather than inferred: the classifier's label set is a property of the classifier
    the operator chose, and a family this project measured has no reason to share a name with one of its
    labels. A family with no label is refused rather than mapped to something plausible -- a wrong mapping
    routes traffic using evidence about different traffic, which is the failure the whole ledger exists to
    prevent.
    """
    families = table.get("families") or {}
    if not families:
        raise ExportError("the compiled table has no families, so there is nothing to configure")

    decisions: list[dict] = []
    cards: dict[str, dict] = {}
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
        cards[chosen] = {
            "model": chosen,
            "description": (
                f"assigned for {family} by tierbook: {d['why'][:200]}"
                + ("" if status == ASSIGNED else f" [{status.upper()}: no held-out fold supports this]")
            ),
        }
        decisions.append({
            "name": f"tierbook-{family}",
            "description": (f"{family}: compiled at margin {table.get('margin')} from registry "
                            f"{table.get('registry_version')}, status {status}"),
            "priority": 100,
            "signals": {"all": [{"type": "domain", "name": signal}]},
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
    cards.setdefault(default_model, {
        "model": default_model,
        "description": ("the default for traffic no decision matched. Deliberately not the cheapest tier: an "
                        "unclassified request is one tierbook has no evidence about, and the tier with the "
                        "best measured quality is the only defensible answer in the absence of evidence."),
    })

    members = [_member(cid, cfg) for cid in sorted(cards)]
    recipe = "tierbook"
    routing = {
        "strategy": "priority",
        "modelCards": [cards[c] for c in sorted(cards)],
        "signals": {"domains": sorted({v for v in signal_for_family.values()})},
        "decisions": decisions,
    }
    return {
        "version": "v0.3",
        "_tierbook": {
            "compiled_from_registry": table.get("registry_version"),
            "table_compiled_at": table.get("compiled_at"),
            "margin": table.get("margin"),
            "objective": table.get("objective", "cost"),
            "request_can_reject": request_can_reject,
            "families_skipped": skipped,
            "note": ("Decisions here are lookups, not a live selector. Recompile the table and re-export "
                     "when the ledger changes; the registry hash above is how a reviewer checks that this "
                     "file still matches the evidence."),
        },
        "listeners": [{"name": f"http-{listener_port}", "address": "0.0.0.0", "port": listener_port,
                       "timeout": "1200s"}],
        "providers": {"defaults": {"default_model": default_model}, "models": members},
        "routing": routing,
        "entrypoints": [{"model_names": [entrypoint], "recipe": recipe}],
        "recipes": [{"name": recipe,
                     "description": ("one decision per measured traffic family, each naming the tier a "
                                     "held-out fold supported at the compiled margin"),
                     "routing": routing}],
        "global": {"router": {"config_source": "file", "strategy": "priority"}},
    }


def write(config: dict, out: str | Path) -> Path:
    p = Path(out)
    p.write_text(json.dumps(config, indent=2) + "\n")
    return p
