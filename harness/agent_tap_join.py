"""Attribute recorded calls to the runs that caused them.

The driver knows when each run started and ended; the tap knows every call and its caller's address.
Neither alone can say "this run cost that". The join is by address and time window, which asks nothing of
the agent -- and asking nothing of the agent is the constraint the whole design is built around, since an
agent modified to cooperate is no longer the agent being measured.

Two facts make the join sound rather than approximate, and both are enforced upstream rather than hoped
for. Runs are sequential per agent, so at most one run per address is open at any instant. And each run
gets a fresh session, so a call cannot belong to a session that spans two runs.

What it reports is deliberately per-run and not averaged: an agent's cost on a task is the sum over its
calls, and a mean over calls would hide that one agent takes four turns where another takes one.

Usage:  python3 harness/agent_tap_join.py runs.json tap.jsonl [--pods pods.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# A call can be recorded a moment after the driver saw its process exit, and the clocks are the same
# host's but not the same instant. One second either side; runs are seconds-to-minutes apart, so this
# cannot reach into a neighbouring run.
SLACK_S = 1.0


def pod_ips(pods_path: str | None) -> dict[str, str]:
    if not pods_path:
        return {}
    doc = json.loads(Path(pods_path).read_text())
    out = {}
    for item in doc.get("items", []):
        ip = (item.get("status") or {}).get("podIP")
        name = (item.get("metadata") or {}).get("name", "")
        if ip and name:
            parts = name.split("-")
            out[ip] = "-".join(parts[:-2]) if len(parts) > 2 else name
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    args = sys.argv[1:]
    pods = None
    if "--pods" in args:
        i = args.index("--pods")
        pods = args[i + 1]
        args = args[:i] + args[i + 2:]

    manifest = json.loads(Path(args[0]).read_text())
    ip_to_agent = pod_ips(pods)
    rows = []
    for line in Path(args[1]).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    claimed: set[str] = set()
    _by_run: dict[int, dict] = {}
    print(f"# {manifest['tag']}: {len(manifest['runs'])} runs\n")
    print("| run | agent | rc | wall s | calls | in tok | out tok | cache read | cache write | max ttfb ms |")
    print("|---|---|---|---|---|---|---|---|---|---|")

    per_agent: dict[str, list[dict]] = {}
    for n, run in enumerate(manifest["runs"]):
        lo, hi = run["started_wall"] - SLACK_S, run["ended_wall"] + SLACK_S
        mine = []
        for r in rows:
            ts = r.get("ts")
            if ts is None or not (lo <= ts <= hi):
                continue
            # The address must belong to this agent's pod when a pod map is available. Without one the
            # window alone is used, which is correct because runs are sequential -- but the map is what
            # makes a stray caller (a human probing the alias, say) attributable to nobody.
            if ip_to_agent and ip_to_agent.get(r.get("peer_ip", "")) != run["agent"]:
                continue
            if not r.get("request"):
                continue
            mine.append(r)
            claimed.add(r.get("id", ""))

        def leg(key: str) -> int:
            total = 0
            for r in mine:
                u = r.get("usage") or {}
                det = u.get("prompt_tokens_details") or {}
                total += int(u.get(key) or det.get(key) or 0)
            return total

        tin = leg("prompt_tokens")
        tout = leg("completion_tokens")
        cread = leg("cached_tokens") + leg("cache_read_input_tokens")
        cwrite = leg("created_cache_tokens") + leg("cache_creation_input_tokens")
        ttfb = max([r["ttfb_ms"] for r in mine if r.get("ttfb_ms") is not None], default=None)
        rc = "timeout" if run["timed_out"] else run["returncode"]
        print(f"| {n} | {run['agent']} | {rc} | {run['wall_s']} | {len(mine)} | {tin} | {tout} | "
              f"{cread} | {cwrite} | {ttfb if ttfb is not None else '-'} |")
        measured = {"calls": len(mine), "in": tin, "out": tout, "read": cread, "write": cwrite}
        per_agent.setdefault(run["agent"], []).append(measured)
        _by_run[n] = measured

    unclaimed = [r for r in rows if r.get("request") and r.get("id") not in claimed]
    print(f"\n**{len(unclaimed)} recorded calls belong to no run in this manifest.**")
    if unclaimed:
        print("Expected when the log spans earlier work or a human probed the alias. They are named")
        print("rather than dropped, because a call nobody claims is either traffic from outside the")
        print("experiment or a run whose window is wrong, and those need different fixes.")
        byip: dict[str, int] = {}
        for r in unclaimed:
            byip[r.get("peer_ip", "?")] = byip.get(r.get("peer_ip", "?"), 0) + 1
        for ip, n in sorted(byip.items(), key=lambda kv: -kv[1]):
            print(f"  - {ip} ({ip_to_agent.get(ip, 'not a pod in the map')}): {n}")

    if manifest.get("repeat", 1) > 1:
        print("\n## Warmth is a condition, not noise")
        print("The engine's prefix cache survives a run and there is no reset endpoint on it, so the")
        print("first iteration meets a colder cache than later ones. Reported per iteration rather than")
        print("averaged, because a warm cost and a cold cost are two different numbers and a deployment")
        print("that runs all day only ever pays the warm one.\n")
        print("| iteration | agent | position | in tok | cache read | cache write |")
        print("|---|---|---|---|---|---|")
        for n, run in enumerate(manifest["runs"]):
            m = _by_run.get(n, {})
            print(f"| {run.get('iteration')} | {run['agent']} | {run.get('position', '-')} | "
                  f"{m.get('in', '-')} | {m.get('read', '-')} | {m.get('write', '-')} |")

        print("\n## Run-to-run spread, per agent")
        print("The same agent on the same task. A difference between agents smaller than this is not a")
        print("difference between agents.\n")
        print("| agent | runs | calls | in tok (min-max) | out tok (min-max) |")
        print("|---|---|---|---|---|")
        for a, rs in sorted(per_agent.items()):
            ins = [r["in"] for r in rs]
            outs = [r["out"] for r in rs]
            calls = {r["calls"] for r in rs}
            print(f"| {a} | {len(rs)} | {sorted(calls)} | {min(ins)}-{max(ins)} | {min(outs)}-{max(outs)} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
