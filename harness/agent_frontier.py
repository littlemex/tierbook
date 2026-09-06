"""Cost per solved task, per coding agent, with the model held constant.

The headline this produces is the one a frontier plot needs and does not usually have: the quality axis is
the instance's own tests, not a judge. `FAIL_TO_PASS` must pass and `PASS_TO_PASS` must still pass, which
is an oracle that exists at inference time because the requester brings it. Nothing here scores prose.

Three things it refuses to do, each because the alternative produces a number that reads as authoritative:

**It does not average an unresolved run together with a run that did nothing.** Three of the four agents
in this cluster silently edited no files until an autonomy flag was found, and each looked exactly like a
capability failure. So a failure with an empty diff is reported on its own line and never folded into a
solve rate, because it is a fact about configuration and the solve rate is supposed to be about capability.

**It does not report a cost per solved task for an agent that solved nothing.** The quantity is undefined,
not infinite, and printing a large number invites a comparison.

**It does not hide that this is one run per instance.** The same agent on the same task was measured
varying by a factor of 1.9 in input tokens, so a gap between two agents smaller than that is not evidence
about the agents. With one run per instance there is no within-instance spread to quote, and the report
says so rather than presenting a difference as if it were resolved.

Usage:
    python3 harness/agent_frontier.py --state ~/tmp/e02/tap/sweep.json --tap tap.jsonl --pods pods.json

SCOPE (see ../SCOPE.md, which governs this file): this is an INSTRUMENT that supplies parameters to a
routing mechanism, not the mechanism and not a conclusion. Every environment-specific number it prints --
a seat count, a KV capacity, a break-even concurrency, an agent's token appetite -- is a parameter reading
for one moment in one cluster. The mechanism's job is to re-read them live and decide from them; turning
any of them into advice about a particular deployment is the error this project has made three times.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_rate(path: Path) -> dict:
    """The self-hosted tier's measured rates, from the tier file rather than from a constant here.

    A price written into a report is a price that disagrees with the ledger eventually.
    """
    d = json.loads(path.read_text())
    return d["self_hosted"]["rate"]


def cost_usd(rate: dict, fresh: int, read: int, write: int, out: int) -> float:
    return (fresh * rate["fresh_in"] + read * rate["cache_read"]
            + write * rate["cache_write"] + out * rate["out"]) / 1e6


def pod_map(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    out = {}
    for item in json.loads(Path(path).read_text()).get("items", []):
        ip = (item.get("status") or {}).get("podIP")
        name = (item.get("metadata") or {}).get("name", "")
        if ip and name:
            parts = name.split("-")
            out[ip] = "-".join(parts[:-2]) if len(parts) > 2 else name
    return out


def tap_rows(path: str | None) -> list[dict]:
    if not path:
        return []
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("request"):
            rows.append(r)
    return rows


def legs_of(rows: list[dict]) -> tuple[int, int, int, int]:
    """The four billed legs across a set of calls, in whichever spelling each arrived under.

    `created_cache_tokens` is the self-hosted engine's name for the write leg and belongs to the subset
    convention, so it is subtracted out of `prompt_tokens` to leave the fresh remainder. Getting this
    wrong charges the same tokens twice, on the tier where the write rate equals the fresh rate.
    """
    fresh = read = write = out = 0
    for r in rows:
        u = r.get("usage") or {}
        det = u.get("prompt_tokens_details") or {}
        prompt = int(u.get("prompt_tokens") or 0)
        out += int(u.get("completion_tokens") or 0)
        disjoint_read = u.get("cache_read_input_tokens")
        disjoint_write = u.get("cache_creation_input_tokens")
        if disjoint_read is not None or disjoint_write is not None:
            fresh += prompt
            read += int(disjoint_read or 0)
            write += int(disjoint_write or 0)
            continue
        r_leg = int(det.get("cached_tokens") or 0)
        w_leg = int(det.get("created_cache_tokens") or 0)
        read += r_leg
        write += w_leg
        fresh += max(0, prompt - r_leg - w_leg)
    return fresh, read, write, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=str(Path.home() / "tmp/e02/tap/sweep.json"))
    ap.add_argument("--tap", help="the tap log, for token and latency figures")
    ap.add_argument("--pods", help="kubectl get pods -o json, to name the callers")
    ap.add_argument("--workdir", default=str(Path.home() / "tmp/e02/tap"))
    ap.add_argument("--tiers", default=str(HERE / "tiers.function-calling.json"))
    a = ap.parse_args()

    state = json.loads(Path(a.state).read_text())
    rate = load_rate(Path(a.tiers))
    ips = pod_map(a.pods)
    rows = tap_rows(a.tap)

    done = {k: v for k, v in state["instances"].items() if v.get("outcome") == "done"}
    print(f"# {len(done)} of {len(state['instances'])} recorded instances scored\n")
    if not done:
        return 1

    per: dict[str, dict] = defaultdict(lambda: {
        "attempted": 0, "resolved": 0, "empty_diff": 0, "timed_out": 0,
        "wall": 0.0, "calls": 0, "legs": [0, 0, 0, 0], "solved": [], "lost": [],
    })

    for inst, rec in sorted(done.items()):
        for key, run in rec.get("runs", {}).items():
            agent = key.split("#")[0]
            p = per[agent]
            p["attempted"] += 1
            p["wall"] += run.get("wall_s") or 0.0
            if run.get("timed_out"):
                p["timed_out"] += 1
            if run.get("resolved"):
                p["resolved"] += 1
                p["solved"].append(inst)
            else:
                if run.get("files_touched") == 0:
                    p["empty_diff"] += 1
                p["lost"].append(inst)

            # Tokens, from the tap, matched by this run's own window and address.
            manifest = Path(a.workdir) / f"runs-{inst}.json"
            if not rows or not manifest.exists():
                continue
            for r in json.loads(manifest.read_text())["runs"]:
                if f"{r['agent']}#{r['iteration']}" != key:
                    continue
                lo, hi = r["started_wall"] - 1.0, r["ended_wall"] + 1.0
                mine = [x for x in rows
                        if lo <= (x.get("ts") or 0) <= hi
                        and (not ips or ips.get(x.get("peer_ip", "")) == agent)]
                p["calls"] += len(mine)
                for i, v in enumerate(legs_of(mine)):
                    p["legs"][i] += v

    print("## Solved, and what a solve cost")
    print("Scored by the instances' own tests. No judge is involved on this axis.\n")
    print("| agent | solved / attempted | timed out | empty diff | tokens in | tokens out | "
          "spend USD | USD / solved |")
    print("|---|---|---|---|---|---|---|---|")
    for agent in sorted(per):
        p = per[agent]
        fresh, read, write, out = p["legs"]
        spend = cost_usd(rate, fresh, read, write, out)
        per_solved = f"${spend / p['resolved']:.4f}" if p["resolved"] else "undefined"
        print(f"| {agent} | {p['resolved']} / {p['attempted']} | {p['timed_out']} | {p['empty_diff']} | "
              f"{fresh + read + write:,} | {out:,} | ${spend:.4f} | {per_solved} |")

    print("\n## Where the input tokens went")
    print("Three legs at three prices. A cache read is 8% of a fresh token on this tier, so the split is")
    print("most of the difference between two agents that send similar totals.\n")
    print("| agent | fresh | cache read | cache write | read share | calls | wall s |")
    print("|---|---|---|---|---|---|---|")
    for agent in sorted(per):
        p = per[agent]
        fresh, read, write, out = p["legs"]
        total = fresh + read + write
        share = f"{100 * read / total:.1f}%" if total else "-"
        print(f"| {agent} | {fresh:,} | {read:,} | {write:,} | {share} | {p['calls']} | "
              f"{int(p['wall']):,} |")

    print("\n## Which instances, per agent")
    for agent in sorted(per):
        p = per[agent]
        print(f"- **{agent}** solved {len(p['solved'])}: {', '.join(p['solved']) or '(none)'}")

    solved_sets = {a: set(p["solved"]) for a, p in per.items()}
    if len(solved_sets) > 1:
        print("\n## Is one agent's solve set inside another's")
        print("A strict subset means the cheaper agent adds nothing an escalation would not have")
        print("caught anyway. An overlap that is not nesting means the choice of agent is a real")
        print("decision rather than a budget one.\n")
        names = sorted(solved_sets)
        for i, x in enumerate(names):
            for y in names[i + 1:]:
                sx, sy = solved_sets[x], solved_sets[y]
                if sx == sy:
                    rel = "identical"
                elif sx < sy:
                    rel = f"{x} ⊂ {y}"
                elif sy < sx:
                    rel = f"{y} ⊂ {x}"
                elif not (sx & sy):
                    rel = "disjoint"
                else:
                    rel = (f"overlapping: {len(sx & sy)} shared, "
                           f"{len(sx - sy)} only {x}, {len(sy - sx)} only {y}")
                print(f"- {x} vs {y}: {rel}")

    print("\n## What these numbers do not settle")
    print("- **One run per instance.** The same agent on the same task varied by 1.9x in input tokens")
    print("  when it was measured twice, so a gap smaller than that is not evidence about the agents.")
    print("- **A fixed agent order within each instance.** The engine's prefix cache survives a run and")
    print("  cannot be flushed, so a later agent meets a warmer cache. The effect is bounded here")
    print("  because each agent's prefix is its own system prompt and tool schemas, which the others do")
    print("  not share -- but it is not zero and it was not counterbalanced.")
    print("- **An empty diff is not a capability result.** Every such run is a configuration question")
    print("  until its agent has been shown to edit files on some instance.")
    print("- **Cost is the self-hosted tier's measured rate card**, which amortises a GPU hour over")
    print("  measured throughput. It is not a quote and it moves with the reservation price.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
