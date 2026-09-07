"""Compare the agent's own telemetry against an independent recording of the same calls.

There is one producer of token figures and that is deliberate. This is not a second producer — it is a
**check**, and it exists because two independent views of the same number is how this project found two real
defects that a single view would have shown as plausible: a fourth spelling of the engine's cache-write leg,
and two different conventions for the same quantity on one gateway.

The rule the check enforces is the same one the ledger applies to money: **a divergence is information and is
never averaged away.** Two sources that disagree about how many tokens a call used are telling you that one
of them changed, and the useful response is to say which rows and by how much, not to split the difference.

What it cannot do, said plainly so nobody reads more into it: the pass-through sees the wire and the agent
sees its own accounting, so a small difference is expected where one counts a retried attempt the other
abandoned. The check reports the distribution and flags rows beyond a stated ratio; it does not declare a
winner.

SCOPE (see ../SCOPE.md, which governs this file): an instrument. It reports; it decides nothing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

#: The tap's spelling for each leg, and the telemetry's. Both are read from their own vocabulary rather than
#: normalised into a third one: a normaliser is a place where a rename becomes a silent zero.
TAP_LEGS = ("fresh_in", "cached_in", "cache_write", "out")
SPAN_LEGS = {
    "fresh_in": "llm.token_count.prompt",
    "cached_in": "llm.token_count.prompt_details.cache_read",
    "cache_write": "llm.token_count.prompt_details.cache_write",
    "out": "llm.token_count.completion",
}


def tap_totals(path: Path, lo: float, hi: float, peer_ips: set[str] | None) -> dict:
    """Sum the tap's legs over a time window. The tap has no trace id, which is the whole reason the join
    moved to one — so a window is all this check has, and it is used here only for a comparison, never for
    attribution."""
    legs = dict.fromkeys(TAP_LEGS, 0)
    calls = 0
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not r.get("request") or not (lo <= (r.get("ts") or 0) <= hi):
            continue
        if peer_ips and r.get("peer_ip") not in peer_ips:
            continue
        u = r.get("usage") or {}
        det = u.get("prompt_tokens_details") or {}
        prompt = int(u.get("prompt_tokens") or 0)
        dr, dw = u.get("cache_read_input_tokens"), u.get("cache_creation_input_tokens")
        if dr is not None or dw is not None:
            legs["fresh_in"] += prompt
            legs["cached_in"] += int(dr or 0)
            legs["cache_write"] += int(dw or 0)
        else:
            r_leg = int(det.get("cached_tokens") or 0)
            w_leg = int(det.get("created_cache_tokens") or 0)
            legs["cached_in"] += r_leg
            legs["cache_write"] += w_leg
            legs["fresh_in"] += max(0, prompt - r_leg - w_leg)
        legs["out"] += int(u.get("completion_tokens") or 0)
        calls += 1
    return {"legs": legs, "calls": calls}


def span_totals(path: Path, trace_id: str) -> dict:
    legs = dict.fromkeys(TAP_LEGS, 0)
    calls = 0
    missing = set()
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
                    if sp.get("traceId") != trace_id or not sp.get("name", "").endswith(".llm"):
                        continue
                    attrs = {a["key"]: next(iter((a.get("value") or {}).values()), None)
                             for a in sp.get("attributes", [])}
                    for leg, key in SPAN_LEGS.items():
                        if key in attrs:
                            legs[leg] += int(attrs[key] or 0)
                        else:
                            missing.add(leg)
                    calls += 1
    return {"legs": legs, "calls": calls, "missing_legs": sorted(missing)}


def compare(a: dict, b: dict, *, tolerance: float) -> dict:
    """Per-leg ratio, and whether any leg is outside the tolerance.

    A zero on one side and a non-zero on the other is reported as an infinite ratio rather than skipped: that
    is the shape of a renamed attribute, which is exactly what this check is for.
    """
    out = {}
    worst = 0.0
    for leg in TAP_LEGS:
        x, y = a["legs"][leg], b["legs"][leg]
        if x == y:
            ratio = 1.0
        elif min(x, y) == 0:
            ratio = float("inf")
        else:
            ratio = max(x, y) / min(x, y)
        out[leg] = {"tap": x, "telemetry": y, "ratio": None if ratio == float("inf") else round(ratio, 4),
                    "one_side_zero": min(x, y) == 0 and max(x, y) > 0}
        worst = max(worst, 1e9 if ratio == float("inf") else ratio)
    return {"legs": out, "worst_ratio": None if worst >= 1e9 else round(worst, 4),
            "within_tolerance": worst <= tolerance,
            "calls": {"tap": a["calls"], "telemetry": b["calls"]}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outcomes", required=True, help="rows carrying trace_id and the run's wall window")
    ap.add_argument("--runs", required=True, help="the driver's manifest, for each run's start and end")
    ap.add_argument("--tap", required=True)
    ap.add_argument("--traces", required=True)
    ap.add_argument("--pods", help="kubectl get pods -o json, to restrict the tap window to one agent's pod")
    ap.add_argument("--agent", help="only check this agent's runs")
    ap.add_argument("--tolerance", type=float, default=1.10,
                    help="a leg differing by more than this ratio is flagged. Not a pass mark: the "
                         "difference is reported either way")
    ap.add_argument("--out")
    a = ap.parse_args()

    outcomes = {}
    for line in Path(a.outcomes).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("trace_id"):
                outcomes[r["trace_id"]] = r

    windows = {}
    manifest = json.loads(Path(a.runs).read_text())
    for r in manifest.get("runs", []):
        if r.get("trace_id"):
            windows[r["trace_id"]] = (r["started_wall"] - 1.0, r["ended_wall"] + 1.0, r.get("agent"))

    ips = None
    if a.pods:
        ips = set()
        for item in json.loads(Path(a.pods).read_text()).get("items", []):
            ip = (item.get("status") or {}).get("podIP")
            name = (item.get("metadata") or {}).get("name", "")
            if ip and a.agent and name.startswith(a.agent):
                ips.add(ip)

    rows, flagged = [], []
    for tid, oc in sorted(outcomes.items()):
        if tid not in windows:
            continue
        lo, hi, agent = windows[tid]
        if a.agent and agent != a.agent:
            continue
        cmp = compare(tap_totals(Path(a.tap), lo, hi, ips), span_totals(Path(a.traces), tid),
                      tolerance=a.tolerance)
        cmp.update({"trace_id": tid, "item_id": oc.get("item_id"), "agent": agent})
        rows.append(cmp)
        if not cmp["within_tolerance"]:
            flagged.append(cmp)

    print(f"{len(rows)} runs cross-checked, {len(flagged)} outside tolerance {a.tolerance}")
    print("\n| item | leg | tap | telemetry | ratio |")
    print("|---|---|---|---|---|")
    for r in rows[:12]:
        for leg, d in r["legs"].items():
            if d["ratio"] != 1.0:
                print(f"| {str(r['item_id'])[:28]} | {leg} | {d['tap']} | {d['telemetry']} | "
                      f"{'one side 0' if d['one_side_zero'] else d['ratio']} |")
    if flagged:
        print("\nDIVERGENCE. Not averaged: one of the two sources changed, and which rows is the finding.")
        for r in flagged[:6]:
            bad = [f"{k} tap={v['tap']} telemetry={v['telemetry']}"
                   for k, v in r["legs"].items() if v["ratio"] != 1.0]
            print(f"  {r['item_id']}: " + "; ".join(bad))
    missing = sorted({m for r in rows for m in span_totals(Path(a.traces), r["trace_id"])["missing_legs"]})
    if missing:
        print(f"\nWARNING: legs absent from some spans: {missing}. Absent is not zero.")
    if a.out:
        Path(a.out).write_text(json.dumps({"rows": rows, "tolerance": a.tolerance}, indent=1) + "\n")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
