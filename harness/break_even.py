"""The price at which two arms cost the same, for every reserved/metered pair in a registry.

Extracted from the comparison script so it is testable and so the assumptions travel with the number rather than
with a shell pipeline. See `tierbook.policy.break_even_price` for why the question is inverted at all: the gateway
in front of this deployment supplied no monetary settlement, and the cloud pricing API carries no entry for the
model the metered arm ran on, so choosing a price would put an invented figure at the centre of the answer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tierbook.policy import break_even_price, load_registry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--window-hours", type=float, required=True)
    ap.add_argument("--family-share", type=float, default=None,
                    help="the fraction of the reservation this family answers for. Required as soon as anything "
                         "else uses the box, or the whole bill is compared against one family's traffic")
    ap.add_argument("--out")
    a = ap.parse_args()

    tiers = load_registry(Path(a.registry))
    reserved = [t for t in tiers.values() if t.is_reserved]
    metered = [t for t in tiers.values() if not t.is_reserved]
    if not reserved or not metered:
        raise SystemExit(f"[FAIL] the registry holds {len(reserved)} reserved and {len(metered)} metered "
                        "candidate(s); a break-even needs one of each, and one arm is missing")

    rows = []
    for box in reserved:
        for alt in metered:
            for fam in sorted(box.record.get("families") or {}):
                if fam not in (alt.record.get("families") or {}):
                    rows.append({"reserved": box.id, "alternative": alt.id, "family": fam,
                                 "usd_per_mtok": None,
                                 "reason": f"{alt.id!r} was not measured on {fam!r}, so there is nothing to "
                                           "compare against on that family"})
                    continue
                v = break_even_price(box, alt, fam, window_hours=a.window_hours,
                                     family_share=a.family_share)
                rows.append({"reserved": box.id, "alternative": alt.id, "family": fam, **v})

    for r in rows:
        head = f"{r['reserved']} vs {r['alternative']} on {r['family']}"
        if r.get("usd_per_mtok") is None:
            print(f"{head}: no figure -- {r['reason']}")
            continue
        print(f"{head}: ${r['usd_per_mtok']:.4f} per million tokens, blended at this cohort's mix")
        print(f"  {r['reason']}")
        print(f"  legs {r['alternative_legs']}")
        print(f"  {r['price_equation']}")
        for x in r.get("assumes", []):
            print(f"    assumes: {x}")
    if a.out:
        Path(a.out).write_text(json.dumps({"window_hours": a.window_hours, "rows": rows}, indent=1) + "\n")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
