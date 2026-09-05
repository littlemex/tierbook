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

USAGE = {"agent": [0, 0, 0, 0], "user": [0, 0, 0, 0]}   # fresh_in, cached_in, out, cache_write
_prev = litellm.completion


def _legs(u):
    """The four billed input/output legs of one usage block, in whichever convention it used.

    Two conventions reach this runner through one gateway. Nested in `prompt_tokens_details`, a cache read is
    OpenAI's subset of `prompt_tokens` and is subtracted out to leave the fresh leg. At the top level, under
    the gateway's own `cache_read_input_tokens`/`cache_creation_input_tokens`, the legs are disjoint from
    `prompt_tokens` and are added -- there `prompt_tokens` is the uncached input only and `total_tokens`
    excludes the cache legs entirely, so subtracting would delete the fresh leg on exactly the warm threads
    where it is the largest charge. litellm carries unknown keys through on the usage object, so both shapes
    arrive here.
    """
    extra = getattr(u, "model_extra", None) or {}
    def _get(name):
        value = getattr(u, name, None)
        return extra.get(name) if value is None else value

    prompt = u.prompt_tokens or 0
    read_disjoint = _get("cache_read_input_tokens")
    write_disjoint = _get("cache_creation_input_tokens")
    if read_disjoint is not None or write_disjoint is not None:
        return prompt, int(read_disjoint or 0), (u.completion_tokens or 0), int(write_disjoint or 0)

    det = getattr(u, "prompt_tokens_details", None)
    cached = (getattr(det, "cached_tokens", 0) or 0) if det is not None else 0
    return max(0, prompt - cached), cached, (u.completion_tokens or 0), 0


def _counting(*a, **kw):
    res = _prev(*a, **kw)
    who = "agent" if kw.get("tools") else "user"
    u = getattr(res, "usage", None)
    if u:
        for i, value in enumerate(_legs(u)):
            USAGE[who][i] += value
    return res


litellm.completion = _counting
for mod in ("tau_bench.agents.tool_calling_agent", "tau_bench.envs.user"):
    __import__(mod)
    setattr(sys.modules[mod], "completion", _counting)


def price(card, fresh, cached, out, cache_write=0):
    """The four legs at this card's rates, matching `tierbook.policy.Tier.token_cost`.

    A null `cache_write` on the card is charged at the fresh rate, not at zero: a write the provider bills at
    a premium and this card cannot express is a lower bound, which is smaller than the truth and never free.
    """
    rate = card["cached_in"]
    if rate is None:
        fresh, cached, rate = fresh + cached, 0, 0.0
    write_rate = card.get("cache_write")
    if write_rate is None:
        write_rate = card["fresh_in"]
    return (
        fresh * card["fresh_in"] + cached * rate + cache_write * write_rate + out * card["output"]
    ) / 1e6


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
            USAGE[k][:] = [0, 0, 0, 0]
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
            "agent_tokens": {"fresh_in": a[0], "cached_in": a[1], "out": a[2], "cache_write": a[3]},
            "user_tokens": {"fresh_in": u[0], "cached_in": u[1], "out": u[2], "cache_write": u[3]},
            # Only the agent's tokens are charged to the tier. The user simulator is the same model on every
            # arm, so its spend is a constant of the experiment rather than a property of the tier.
            "agent_usd": round(price(card, *a), 6),
            # A write leg priced off a card with no write rate is a floor, so a row that has one says so
            # rather than leaving a reader to find out from the card.
            "agent_usd_is_a_floor": bool(a[3]) and card.get("cache_write") is None,
        })
        print(json.dumps(rows[-1]), flush=True)
        Path(args.out).write_text(json.dumps({"tier": args.tier, "split": args.split, "rows": rows}, indent=1))
    n = len(rows); solved = sum(r["solved"] for r in rows)
    print(f"== {args.tier} {args.split}[{args.start}:{args.end}]: solved {solved}/{n}, "
          f"agent spend ${sum(r['agent_usd'] for r in rows):.4f}", flush=True)


if __name__ == "__main__":
    main()
