"""Join what happened to what it cost, by trace id, and refuse to price a partial join.

Three sources have to meet, and they have three different owners:

    outcomes    the task's own oracle said solved / incorrect / unobserved   (this project)
    telemetry   four token legs, turn order, latency, candidate tuple        (the agent, via OTLP)
    charge      what was actually billed                                     (the billing gateway)

They meet on a **trace id issued before the run starts** and passed into the agent, not on a time window.
The window join was the first design and it breaks the moment two runs overlap, which is the normal case in
a deployment and was already the case in one sweep here.

**Cost has two kinds and they are never one number.** A metered candidate's charge is authored by the
gateway and known per request. A fixed-cost candidate has no per-request charge to look up: its figure is the
period's bill divided by the work that period carried, so it exists only after a window closes. Dividing an
hourly bill by one sequential experimenter's task rate and calling it a cost per task is a mistake this
project already published; the amortised kind therefore never enters this join at all. It is applied later,
against a stated window, by whoever computes the frontier.

**A partial join does not produce a partial cost figure; it produces no cost figure.** A cost summed over
the rows that happened to join reads as complete, and that is the failure this refuses. Coverage is reported
and a shortfall names the rows that are missing rather than the count.

SCOPE (see ../SCOPE.md, which governs this file): an instrument. It supplies parameters and states what it
cannot support; it decides nothing.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

#: How a cost may be described. The distinction is load-bearing, not descriptive: mixing them silently is
#: how a fixed bill becomes a per-request price.
METERED = "per_request_metered"
AMORTISED = "per_period_amortised"

#: Span attributes this join reads. Named so a change in the producer's vocabulary fails loudly here rather
#: than quietly producing zeros -- an absent leg read as 0 is the defect the ledger's own evidence rules
#: exist to prevent.
LEGS = {
    "fresh_in": "llm.token_count.prompt",
    "cached_in": "llm.token_count.prompt_details.cache_read",
    "cache_write": "llm.token_count.prompt_details.cache_write",
    "out": "llm.token_count.completion",
    "reasoning": "llm.token_count.completion_details.reasoning",
}
CANDIDATE_ATTRS = {"agent": "agent.name", "model": "llm.model_name", "provider": "llm.provider"}


def _attr(span: dict) -> dict:
    out = {}
    for a in span.get("attributes", []):
        v = a.get("value") or {}
        out[a["key"]] = next(iter(v.values()), None) if v else None
    return out


def read_traces(path: Path) -> dict[str, dict]:
    """Group spans by trace id, keeping turn order from the LLM spans' own sequence.

    Turn order comes from the spans, not from a sort on a timestamp we chose: the session span is the parent
    and the LLM spans are its children, so the structure is the producer's rather than our reconstruction.
    """
    by_trace: dict[str, dict] = defaultdict(lambda: {"turns": [], "session": None})
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        for rs in doc.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for sp in ss.get("spans", []):
                    tid = sp.get("traceId")
                    if not tid:
                        continue
                    attrs = _attr(sp)
                    rec = by_trace[tid]
                    name = sp.get("name", "")
                    if name.endswith(".session"):
                        rec["session"] = attrs
                    elif name.endswith(".llm"):
                        rec["turns"].append({
                            "span_id": sp.get("spanId"),
                            "start": sp.get("startTimeUnixNano"),
                            "legs": {k: int(attrs.get(v) or 0) for k, v in LEGS.items()},
                            "missing_legs": sorted(k for k, v in LEGS.items() if v not in attrs),
                            "candidate": {k: attrs.get(v) for k, v in CANDIDATE_ATTRS.items()},
                            "finish_reason": attrs.get("llm.finish_reason"),
                            "duration_ms": attrs.get("duration_ms"),
                        })
    for rec in by_trace.values():
        # Ordered by the producer's own start time, and the index is assigned here so a reader never has to
        # re-derive it. A turn with no start time sorts last rather than being dropped.
        rec["turns"].sort(key=lambda t: int(t["start"] or 0))
        for i, t in enumerate(rec["turns"]):
            t["index"] = i
    return dict(by_trace)


def read_outcomes(path: Path) -> dict[str, dict]:
    """Outcomes keyed by trace id. Written by whoever ran the task and applied its oracle."""
    out = {}
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("trace_id"):
            out[r["trace_id"]] = r
    return out


def read_charges(path: Path | None) -> dict[str, dict]:
    """Charges keyed by trace id, as the gateway reported them.

    Absent file means no metered candidate was involved, which is a legitimate state and not an error: a run
    entirely on a fixed-cost candidate has nothing here by construction.
    """
    if not path or not path.exists():
        return {}
    out = {}
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("trace_id"):
            out[r["trace_id"]] = r
    return out


def join(outcomes: dict, traces: dict, charges: dict, *, metered_providers: set[str]) -> dict:
    """One row per trace, plus the coverage figures that decide whether a cost may be stated at all."""
    rows, unjoined = [], []
    for tid, oc in sorted(outcomes.items()):
        tr = traces.get(tid)
        if tr is None:
            unjoined.append({"trace_id": tid, "missing": "telemetry", "item_id": oc.get("item_id")})
            continue
        providers = {t["candidate"].get("provider") for t in tr["turns"] if t["candidate"].get("provider")}
        metered = bool(providers & metered_providers)
        ch = charges.get(tid)
        if metered and ch is None:
            unjoined.append({"trace_id": tid, "missing": "charge", "item_id": oc.get("item_id"),
                             "providers": sorted(providers)})
            continue
        legs = {k: sum(t["legs"][k] for t in tr["turns"]) for k in LEGS}
        rows.append({
            "trace_id": tid,
            "item_id": oc.get("item_id"),
            "state": oc.get("state"),
            "unobserved_reason": oc.get("unobserved_reason"),
            "candidate": tr["turns"][0]["candidate"] if tr["turns"] else None,
            "turns": len(tr["turns"]),
            "legs": legs,
            # Wall time as the driver observed it. Carried because the ledger needs a latency figure and the
            # driver is the only thing that saw the process start and stop; it is not a token count, so this
            # is not a second producer of anything.
            "wall_s": oc.get("wall_s"),
            # Two kinds, never one number. The amortised kind is deliberately absent here: it does not exist
            # per request and is applied against a closed window elsewhere.
            "cost": ({"kind": METERED, "usd": ch.get("usd"), "source": "gateway",
                      "gateway_request_id": ch.get("request_id")} if ch else
                     {"kind": AMORTISED, "usd": None,
                      "note": "fixed-cost candidate: no per-request charge exists; apply a period bill "
                              "divided by that period's work, with the window stated"}),
            "missing_legs": sorted({m for t in tr["turns"] for m in t["missing_legs"]}),
        })

    n = len(outcomes)
    return {
        "rows": rows,
        "coverage": {
            "outcomes": n,
            "joined": len(rows),
            "rate": round(len(rows) / n, 4) if n else None,
            "unjoined": unjoined,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outcomes", required=True, help="JSONL, one row per run, with trace_id and state")
    ap.add_argument("--traces", required=True, help="the collector's traces.jsonl")
    ap.add_argument("--charges", help="JSONL from the gateway, with trace_id and usd. Absent is legitimate")
    ap.add_argument("--metered-providers", default="",
                    help="comma-separated provider names whose charge the gateway authors. A provider not "
                         "listed is treated as fixed-cost, so its absence of a charge is not a shortfall")
    ap.add_argument("--min-coverage", type=float, default=1.0,
                    help="below this, no cost figure is produced. Default 1.0 on purpose: a cost over the "
                         "rows that happened to join reads as complete")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    res = join(read_outcomes(Path(a.outcomes)), read_traces(Path(a.traces)),
               read_charges(Path(a.charges) if a.charges else None),
               metered_providers={p for p in a.metered_providers.split(",") if p})
    cov = res["coverage"]
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n")

    rate = "n/a" if cov["rate"] is None else f"{cov['rate']:.1%}"
    print(f"outcomes {cov['outcomes']}  joined {cov['joined']}  coverage {rate}")
    metered = [r for r in res["rows"] if r["cost"]["kind"] == METERED]
    fixed = [r for r in res["rows"] if r["cost"]["kind"] == AMORTISED]
    print(f"  metered rows {len(metered)}  fixed-cost rows {len(fixed)}")
    if cov["unjoined"]:
        print(f"  {len(cov['unjoined'])} unjoined, named in the output:")
        for u in cov["unjoined"][:8]:
            print(f"    {u['trace_id'][:16]}… missing {u['missing']} (item {u.get('item_id')})")
    missing_legs = sorted({m for r in res["rows"] for m in r["missing_legs"]})
    if missing_legs:
        print(f"  WARNING: token legs absent from some spans: {missing_legs}. Absent is not zero; the "
              "producer's vocabulary may have changed")
    if cov["rate"] is not None and cov["rate"] < a.min_coverage:
        print(f"\n[REFUSED] coverage {cov['rate']:.1%} is below --min-coverage {a.min_coverage:.1%}. No cost "
              "figure is produced: a cost summed over the joined subset reads as complete.")
        return 3
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
