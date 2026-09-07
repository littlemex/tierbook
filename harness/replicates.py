"""Whether a run reproduces, and what survives when it does not.

This project already has this rule for policies and for load probes -- a conclusion from one run is a reading, and
the capacity bound died when the probe was repeated. It did not have it for the thing the whole comparison rests
on: an arm's solve rate. So an arm ran once per condition and the honest caveat was a sentence rather than a
mechanism.

What a replicate measures that a binomial does not. The theoretical noise on 24 items at a 0.42 rate is about 2.4
tasks, which is a statement about item sampling. A second run of the SAME items on the SAME candidate measures
something else: decoding stochasticity, load-dependent timeouts, and whatever else moves between two afternoons.
Those add to item noise rather than replacing it, and only a replicate can see them.

The output is per item and then aggregate, in that order. "These three items flipped between runs" is actionable
-- they are the items a comparison must not lean on -- and a variance figure is not.

SCOPE (see ../SCOPE.md, which governs this file): an instrument. It reports; it decides nothing.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def solved_by_item(path: Path) -> tuple[dict, list]:
    doc = json.loads(path.read_text())
    solved, unobserved = {}, []
    for r in doc.get("rows", []):
        item = r.get("item_id")
        if not item:
            continue
        if r.get("state") == "unobserved":
            unobserved.append(item)
            continue
        solved[item] = r.get("state") == "solved"
    return solved, unobserved


def agreement(runs: list[dict]) -> dict:
    """Per-item stability across replicates of one candidate, then the aggregate.

    An item observed in only some runs is excluded and named: a rate over a shifting item set is not a rate, and
    the shifting is usually the interesting part.
    """
    everywhere = set(runs[0])
    for r in runs[1:]:
        everywhere &= set(r)
    partial = sorted(set().union(*[set(r) for r in runs]) - everywhere)

    flipped, stable_solved, stable_unsolved = [], [], []
    for item in sorted(everywhere):
        vals = [r[item] for r in runs]
        if all(vals):
            stable_solved.append(item)
        elif not any(vals):
            stable_unsolved.append(item)
        else:
            flipped.append({"item_id": item, "solved_in": sum(vals), "of": len(vals)})

    counts = [sum(1 for i in everywhere if r[i]) for r in runs]
    return {
        "replicates": len(runs),
        "items_in_every_run": len(everywhere),
        "excluded_partial": partial,
        "solved_per_run": counts,
        "spread": (max(counts) - min(counts)) if counts else 0,
        "stdev": (round(statistics.stdev(counts), 3) if len(counts) > 1 else None),
        "stable_solved": len(stable_solved),
        "stable_unsolved": len(stable_unsolved),
        "flipped": flipped,
        "reading": (
            f"{len(flipped)} of {len(everywhere)} items changed answer between runs of the same candidate, and "
            f"the count moved by {max(counts) - min(counts) if counts else 0}. "
            + ("Nothing flipped, so on this set the candidate is reproducible and a difference between arms of "
               "more than the item-sampling noise would mean something."
               if not flipped else
               "Those items cannot carry a comparison: a difference between arms that rests on them is a "
               "difference between two draws of one candidate.")),
        "not_a_substitute": ("this measures run-to-run movement on a FIXED item set. Item-sampling noise is "
                             "separate and larger at these sizes, and the two add"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--joined", action="append", required=True,
                    help="joined output for one replicate. Repeat it; at least two, since one run is the thing "
                         "this exists to stop being trusted")
    ap.add_argument("--out")
    a = ap.parse_args()
    if len(a.joined) < 2:
        raise SystemExit("[FAIL] give at least two --joined replicates; one run is a reading, not a rate")

    runs, unobs = [], []
    for path in a.joined:
        s, u = solved_by_item(Path(path))
        runs.append(s)
        unobs.append(u)
    res = agreement(runs)
    res["unobserved_per_run"] = unobs

    print(f"{res['replicates']} replicates, {res['items_in_every_run']} items in every run")
    print(f"  solved per run {res['solved_per_run']}   spread {res['spread']}   stdev {res['stdev']}")
    print(f"  stable solved {res['stable_solved']}   stable unsolved {res['stable_unsolved']}   "
          f"flipped {len(res['flipped'])}")
    for f in res["flipped"]:
        print(f"    {f['item_id']}: solved in {f['solved_in']} of {f['of']} runs")
    if res["excluded_partial"]:
        print(f"  excluded, not in every run: {res['excluded_partial']}")
    for i, u in enumerate(res["unobserved_per_run"], start=1):
        if u:
            print(f"  run {i} unobserved: {u}")
    print(f"  {res['reading']}")
    print(f"  {res['not_a_substitute']}")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
