"""Replay the traffic windows in order and ask tierbook, at each one, what it would certify.

At window K the arms that exist are the ones that never change (the decision model, the generation arms) plus every
student fitted on experience up to K, and every confidence-routed arm built on those students. Observations of a
student that did not exist yet are left out, so each row is what an operator running `tierbook derive` at that
moment would have seen. Nothing here decides anything: it calls `certify.derive` once per window and prints it.

    python -I progress.py --observations obs.jsonl --candidates candidates.json --declarations declarations.json \
        --windows 9 --task-type finnews-sentiment --out progress.json
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone

from tierbook.certify import derive, load_declarations
from tierbook.config import load_config
from tierbook.observation import read

_WINDOWED = re.compile(r"^(?P<base>.+)-w(?P<k>\d+)$")


def window_of(arm: str) -> int | None:
    m = _WINDOWED.match(arm)
    return int(m.group("k")) if m else None


def replay(observations, cfg, decl, windows: int, task_type: str, as_of: datetime) -> list[dict]:
    rows = []
    for k in range(1, windows + 1):
        seen = [o for o in observations if (window_of(o.arm) or 0) <= k]
        pol = derive(seen, cfg, decl, as_of=as_of)
        e = pol["task_types"].get(task_type, {})
        arms = e.get("arms") or {}
        students = {a: s["held_out"] for a, s in arms.items() if window_of(a) == k}
        rows.append({
            "window": k, "status": e.get("status"), "arm": e.get("arm"),
            "spend_per_accepted_usd": (e.get("held_out") or {}).get("spend_per_accepted_usd"),
            "held_out_lower": (e.get("held_out") or {}).get("lower"),
            "this_window": {a: {"rate": h["rate"], "lower": h["lower"],
                                "spend_per_accepted_usd": h["spend_per_accepted_usd"]} for a, h in students.items()},
            "reason": e.get("reason"),
        })
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--observations", nargs="+", required=True)
    p.add_argument("--candidates", required=True)
    p.add_argument("--declarations", required=True)
    p.add_argument("--windows", type=int, required=True)
    p.add_argument("--task-type", required=True)
    p.add_argument("--as-of", default=None)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    as_of = datetime.fromisoformat(a.as_of.replace("Z", "+00:00")) if a.as_of else datetime.now(timezone.utc)
    rows = replay(read(a.observations), load_config(a.candidates), load_declarations(a.declarations), a.windows,
                  a.task_type, as_of)
    with open(a.out, "w") as f:
        json.dump(rows, f, indent=2)
    for r in rows:
        mine = "; ".join(f"{arm} rate {v['rate']:.3f} lower {v['lower']:.3f}" for arm, v in r["this_window"].items()
                         if v["rate"] is not None)
        cost = r["spend_per_accepted_usd"]
        print(f"W{r['window']}: {r['status']:<12} {r['arm'] or '-':<26} "
              f"{'' if cost is None else f'${cost:.8f}/accepted'}  | {mine}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
