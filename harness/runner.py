"""Measure one tier on one fold of tau-bench, and account for it against the registry's price cards.

tau-bench's own cost column comes from litellm's price map, which does not know a gateway alias or a
self-hosted checkpoint, so it reads zero. Tokens are counted here from each response's usage block and
priced against the tier record instead -- the only accounting this project trusts.
"""
import argparse, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import shim  # noqa: F401  routes per model name and drops parameters a tier refuses

import litellm
from tau_bench.envs import get_env
from tau_bench.agents.tool_calling_agent import ToolCallingAgent

USAGE = {"agent": [0, 0, 0], "user": [0, 0, 0]}   # fresh_in, cached_in, out
_prev = litellm.completion


def _counting(*a, **kw):
    res = _prev(*a, **kw)
    who = "agent" if kw.get("tools") else "user"
    u = getattr(res, "usage", None)
    if u:
        cached = 0
        det = getattr(u, "prompt_tokens_details", None)
        if det is not None:
            cached = (getattr(det, "cached_tokens", 0) or 0)
        USAGE[who][0] += (u.prompt_tokens or 0) - cached
        USAGE[who][1] += cached
        USAGE[who][2] += (u.completion_tokens or 0)
    return res


litellm.completion = _counting
for mod in ("tau_bench.agents.tool_calling_agent", "tau_bench.envs.user"):
    __import__(mod)
    setattr(sys.modules[mod], "completion", _counting)


def price(card, fresh, cached, out):
    rate = card["cached_in"]
    if rate is None:
        fresh, cached, rate = fresh + cached, 0, 0.0
    return (fresh * card["fresh_in"] + cached * rate + out * card["output"]) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", required=True)
    ap.add_argument("--agent-model", required=True)
    ap.add_argument("--user-model", required=True)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=20)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--registry", default="/registry")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    card = json.loads(Path(f"{args.registry}/{args.tier}.json").read_text())["price_card"]
    rows = []
    for idx in range(args.start, args.end):
        for k in USAGE:
            USAGE[k][:] = [0, 0, 0]
        env = get_env("retail", user_strategy="llm", user_model=args.user_model,
                      user_provider="openai", task_split=args.split, task_index=idx)
        agent = ToolCallingAgent(tools_info=env.tools_info, wiki=env.wiki,
                                 model=args.agent_model, provider="openai", temperature=0.0)
        t0 = time.time()
        outcome, err = None, None
        try:
            res = agent.solve(env=env, task_index=idx, max_num_steps=args.max_steps)
            outcome = {"reward": res.reward, "turns": len(res.messages)}
        except Exception as e:  # a tier that cannot drive the tools is a measurement, not a crash
            err = f"{type(e).__name__}: {e}"[:300]
        wall = time.time() - t0
        a, u = USAGE["agent"], USAGE["user"]
        rows.append({
            "task": idx, "solved": bool(outcome and outcome["reward"] >= 1.0),
            "reward": (outcome or {}).get("reward"), "turns": (outcome or {}).get("turns"),
            "error": err, "wall_s": round(wall, 1),
            "agent_tokens": {"fresh_in": a[0], "cached_in": a[1], "out": a[2]},
            "user_tokens": {"fresh_in": u[0], "cached_in": u[1], "out": u[2]},
            # Only the agent's tokens are charged to the tier. The user simulator is the same model on every
            # arm, so its spend is a constant of the experiment rather than a property of the tier.
            "agent_usd": round(price(card, *a), 6),
        })
        print(json.dumps(rows[-1]), flush=True)
        Path(args.out).write_text(json.dumps({"tier": args.tier, "split": args.split, "rows": rows}, indent=1))
    n = len(rows); solved = sum(r["solved"] for r in rows)
    print(f"== {args.tier} {args.split}[{args.start}:{args.end}]: solved {solved}/{n}, "
          f"agent spend ${sum(r['agent_usd'] for r in rows):.4f}", flush=True)


if __name__ == "__main__":
    main()
