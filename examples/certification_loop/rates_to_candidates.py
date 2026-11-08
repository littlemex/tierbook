"""Write the candidate file from the gateway's own billing rates, rather than from a hand-copied price list.

Reads `GET /api/mvp/me/rates` (stratoclave), which lists, per pricing key, the models the caller may invoke and the
per-MTok rates in micro-USD it is billed at. Each requested arm becomes a candidate whose `price_per_mtok` is that
rate. An arm the gateway does not price for this caller is refused rather than written with a guessed price.

    python -I rates_to_candidates.py --gateway "$GATEWAY_URL" --arms qwen3-next-80b,claude-sonnet-5 --out candidates.json
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone


def candidates_from_rates(rates: dict, arms: list[str], *, base_url: str, api_key_env: str) -> dict:
    by_model = {}
    for row in rates.get("rates") or []:
        for m in row.get("models") or []:
            by_model[m] = row
    missing = [a for a in arms if a not in by_model]
    if missing:
        raise SystemExit(f"the gateway prices no model named {missing} for this caller; "
                         f"it prices {sorted(by_model)}")
    out = {"config_format": 2,
           "_comment": (f"Generated from GET /api/mvp/me/rates (version {rates.get('version')}, as of "
                        f"{rates.get('as_of')}); regenerate rather than edit."),
           "candidates": {}, "families": {}}
    for a in arms:
        r = by_model[a]
        out["candidates"][a] = {
            "deployment": "api",
            "endpoint": {"base_url": base_url, "model": a, "wire": "chat", "api_key_env": api_key_env},
            "price_per_mtok": {"fresh_in": r["input_per_mtok_microusd"] / 1e6,
                               "cached_in": r["cache_read_per_mtok_microusd"] / 1e6,
                               "out": r["output_per_mtok_microusd"] / 1e6},
            "note": f"gateway pricing key {r['pricing_key']!r}",
        }
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--gateway", required=True, help="the gateway's OpenAI base URL, ending in /v1")
    p.add_argument("--arms", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--api-key-env", default="TIERBOOK_API_KEY")
    a = p.parse_args(argv)
    root = a.gateway.rstrip("/").removesuffix("/v1")
    req = urllib.request.Request(root + "/api/mvp/me/rates")
    req.add_header("authorization", f"Bearer {os.environ[a.api_key_env]}")
    with urllib.request.urlopen(req, timeout=30) as r:
        rates = json.loads(r.read())
    c = candidates_from_rates(rates, [x for x in a.arms.split(",") if x], base_url=a.gateway.rstrip("/"),
                              api_key_env=a.api_key_env)
    with open(a.out, "w") as f:
        json.dump(c, f, indent=2)
        f.write("\n")
    print(f"wrote {a.out}: {len(c['candidates'])} candidate(s) priced from the gateway at "
          f"{rates.get('as_of') or datetime.now(timezone.utc).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
