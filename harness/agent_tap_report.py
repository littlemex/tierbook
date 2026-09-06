"""What the tap saw, per agent.

The report is deliberately narrow. It answers the three questions the tap exists for and nothing else:
which request fields each agent sets, how prefill-heavy it is, and how its prompt grows across a session.
Anything else invites reading a cost or a quality claim off a proxy log, and costing belongs to the ledger.

Usage:  python3 harness/agent_tap_report.py tap.jsonl [...] [--pods pods.json]

`--pods` takes the output of `kubectl get pods -o json` and maps the recorded peer address to a pod name.
Without it the report groups by address, which is correct but unreadable: on EKS a pod IP reverse-resolves
to an IP-derived host name and never to the pod, so the address is the identity and the name has to come
from the cluster. The mapping is done here rather than in the tap, which has no reason to hold cluster API
access, and a pod replaced mid-experiment changes address -- a fact the log should keep rather than hide.

SCOPE (see ../SCOPE.md, which governs this file): this is an INSTRUMENT that supplies parameters to a
routing mechanism, not the mechanism and not a conclusion. Every environment-specific number it prints --
a seat count, a KV capacity, a break-even concurrency, an agent's token appetite -- is a parameter reading
for one moment in one cluster. The mechanism's job is to re-read them live and decide from them; turning
any of them into advice about a particular deployment is the error this project has made three times.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

# The fields the billing gateway honours on one upstream wire and drops on the other. An agent that sets
# one of these is an agent whose behaviour changes with the resolved model for reasons that have nothing
# to do with the agent, so these are called out separately rather than buried in the field census.
WIRE_DEPENDENT = {
    "reasoning_effort", "seed", "logit_bias", "presence_penalty", "frequency_penalty",
    "parallel_tool_calls", "verbosity", "prediction", "modalities", "store", "user",
}


def load(paths: list[str]) -> list[dict]:
    rows = []
    for p in paths:
        with open(p, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    # A line truncated by a concurrent write is a lost observation, not a reason to
                    # refuse the other 99%.
                    continue
    return rows


POD_BY_IP: dict[str, str] = {}


def load_pod_map(path: str) -> None:
    """Address -> deployment-ish name, from `kubectl get pods -o json`."""
    with open(path) as fh:
        doc = json.load(fh)
    for item in doc.get("items", []):
        ip = (item.get("status") or {}).get("podIP")
        name = (item.get("metadata") or {}).get("name", "")
        if not ip or not name:
            continue
        parts = name.split("-")
        POD_BY_IP[ip] = "-".join(parts[:-2]) if len(parts) > 2 else name


def agent_of(row: dict) -> str:
    mapped = POD_BY_IP.get(row.get("peer_ip", ""))
    if mapped:
        return mapped
    label = row.get("agent") or "?"
    # A pod DNS name is `<pod>.<ns>.pod.cluster.local` and the pod name carries the deployment; the
    # replica hash is noise for a per-agent census.
    head = label.split(".")[0]
    parts = head.split("-")
    return "-".join(parts[:-2]) if len(parts) > 2 else head


def main() -> int:
    args = sys.argv[1:]
    if "--pods" in args:
        i = args.index("--pods")
        load_pod_map(args[i + 1])
        args = args[:i] + args[i + 2:]
    if not args:
        print(__doc__)
        return 2
    rows = [r for r in load(args) if r.get("request")]
    if not rows:
        print("no rows with a recorded request body")
        return 1

    by_agent: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_agent[agent_of(r)].append(r)

    print(f"# {len(rows)} calls, {len(by_agent)} agents\n")

    print("## Request fields set, per agent")
    print("A field an agent never sets cannot explain any difference in its results.\n")
    all_fields: set[str] = set()
    census: dict[str, Counter] = {}
    for agent, rs in by_agent.items():
        c = Counter()
        for r in rs:
            req = r["request"]
            if isinstance(req, dict):
                c.update(k for k in req if k not in ("messages", "model"))
        census[agent] = c
        all_fields |= set(c)

    agents = sorted(by_agent)
    width = max([len(f) for f in all_fields] + [22])
    print("| field | " + " | ".join(agents) + " |")
    print("|" + "---|" * (len(agents) + 1))
    for f in sorted(all_fields):
        marks = []
        for a in agents:
            n = census[a][f]
            share = 100 * n / len(by_agent[a])
            marks.append("-" if not n else ("always" if share > 99 else f"{share:.0f}%"))
        flag = " **[wire-dependent]**" if f in WIRE_DEPENDENT else ""
        print(f"| `{f}`{flag} | " + " | ".join(marks) + " |")

    print("\n## The confound, quantified")
    risky = {a: sorted(set(census[a]) & WIRE_DEPENDENT) for a in agents}
    if not any(risky.values()):
        print("No agent sets a field whose fate depends on the upstream wire. The agent-effect")
        print("comparison across model families is clean on this axis, and that is now a measurement")
        print("rather than an assumption.")
    else:
        print("These agents set fields the gateway honours on one wire and drops on the other, so a")
        print("cross-family comparison of them is confounded until the fields are equalised:\n")
        for a in agents:
            if risky[a]:
                print(f"- **{a}**: " + ", ".join(f"`{f}`" for f in risky[a]))
        print("\nThe fields are not equal in consequence: `parallel_tool_calls` and `reasoning_effort`")
        print("change what the model does, while `store` and `user` are inert hints.")

    print("\n## Prefill weight, per agent")
    print("Whether a self-hosted box can be cheaper is decided by this ratio, and it is a property of")
    print("the agent rather than of the task.\n")
    print("| agent | calls | median in | median out | in:out | streamed | median TTFB ms |")
    print("|---|---|---|---|---|---|---|")
    for a in agents:
        rs = by_agent[a]
        ins = sorted(r["usage"]["prompt_tokens"] for r in rs
                     if isinstance(r.get("usage"), dict) and r["usage"].get("prompt_tokens"))
        outs = sorted(r["usage"].get("completion_tokens", 0) for r in rs
                      if isinstance(r.get("usage"), dict))
        ttfb = sorted(r["ttfb_ms"] for r in rs if r.get("ttfb_ms") is not None)
        streamed = sum(1 for r in rs if r.get("streaming"))

        def med(xs):
            return xs[len(xs) // 2] if xs else None

        mi, mo, mt = med(ins), med(outs), med(ttfb)
        ratio = f"{mi / mo:.0f}:1" if mi and mo else "-"
        print(f"| {a} | {len(rs)} | {mi if mi else '-'} | {mo if mo else '-'} | {ratio} | "
              f"{100 * streamed // len(rs)}% | {mt if mt else '-'} |")

    print("\n## Prompt growth within a session")
    print("A prompt that grows every turn is what makes prefix reuse decide the cost. Reported as the")
    print("input tokens of the first and last call seen from each agent, in order.\n")
    for a in agents:
        rs = sorted(by_agent[a], key=lambda r: r.get("ts", 0))
        ins = [r["usage"]["prompt_tokens"] for r in rs
               if isinstance(r.get("usage"), dict) and r["usage"].get("prompt_tokens")]
        if len(ins) < 2:
            print(f"- {a}: fewer than two priced calls, no growth to report")
            continue
        print(f"- {a}: {ins[0]} -> {ins[-1]} over {len(ins)} calls, peak {max(ins)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
