#!/usr/bin/env bash
# Two arms, one comparison, and every refusal left in place.
#
# Runs the whole path for a pair of measured cohorts: join each arm, build its ledger record, cross-check the
# gateway's aggregate against the sum of its own per-call replies, compile, and print what the evidence supports.
# Nothing here suppresses a refusal -- the join refuses a partial cohort, the compiler refuses a bound from a
# single probe, and the point of running it as one script is that those refusals arrive in one place.
#
# It deliberately does NOT print a winner. At 24 items with one run per arm, binomial noise is worth two or three
# tasks, so the honest output is both counts, both token totals, and the price at which the two arms cost the
# same -- which needs no price card, because the gateway supplied none.
set -euo pipefail

BOX_OUTCOMES=${BOX_OUTCOMES:?}
BOX_TRACES=${BOX_TRACES:?}
API_OUTCOMES=${API_OUTCOMES:?}
API_TRACES=${API_TRACES:?}
API_RUN_GROUP=${API_RUN_GROUP:?}
SHIM_REQUESTS=${SHIM_REQUESTS:?}
LEDGER_BEFORE=${LEDGER_BEFORE:?}
LEDGER_AFTER=${LEDGER_AFTER:?}
HOURLY_USD=${HOURLY_USD:?}
WINDOW_HOURS=${WINDOW_HOURS:?}
OUT=${OUT:-/tmp/compare}

HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"

echo "=== 1. the gateway's two views of its own usage ==="
python3 "$HERE/crosscheck_ledger.py" --before "$LEDGER_BEFORE" --after "$LEDGER_AFTER" \
  --requests "$SHIM_REQUESTS" --out "$OUT/ledger-crosscheck.json" || true

echo
echo "=== 2. join each arm ==="
python3 "$HERE/join_sources.py" --outcomes "$BOX_OUTCOMES" --traces "$BOX_TRACES" \
  --no-metered-candidates --out "$OUT/joined-box.json"
python3 "$HERE/join_sources.py" --outcomes "$API_OUTCOMES" --traces "$API_TRACES" \
  --run-group "$API_RUN_GROUP" --no-metered-candidates --out "$OUT/joined-api.json"

echo
echo "=== 3. one registry holding both arms ==="
rm -rf "$OUT/ledger"
python3 "$HERE/sweep_to_ledger.py" --joined "$OUT/joined-box.json" --out "$OUT/ledger" \
  --hourly-fixed-usd "$HOURLY_USD"
python3 "$HERE/sweep_to_ledger.py" --joined "$OUT/joined-api.json" --out "$OUT/ledger"

echo
echo "=== 4. what the evidence supports ==="
PYTHONPATH="$HERE/../src" python3 -m tierbook.cli compile \
  --registry "$OUT/ledger/tiers" --family "agentic-coding=$(ls "$OUT/ledger/tiers" | head -1 | sed 's/\.json$//')" \
  --margin 5 --window-hours "$WINDOW_HOURS" --min-items 20 \
  --out "$OUT/policy.json" --report "$OUT/policy.md" || true

echo
echo "=== 5. the price at which the two arms cost the same ==="
PYTHONPATH="$HERE/../src" python3 - "$OUT/ledger/tiers" "$WINDOW_HOURS" <<'PY'
import json, sys
from pathlib import Path
from tierbook.policy import break_even_price, load_registry

tiers = load_registry(Path(sys.argv[1]))
window = float(sys.argv[2])
reserved = [t for t in tiers.values() if t.is_reserved]
metered = [t for t in tiers.values() if not t.is_reserved]
if not reserved or not metered:
    print("one arm is missing from the registry, so there is nothing to break even against")
    raise SystemExit(0)
for box in reserved:
    for alt in metered:
        for fam in box.record.get("families", {}):
            v = break_even_price(box, alt, fam, window_hours=window)
            print(f"{box.id} vs {alt.id} on {fam}:")
            print(f"  {v.get('usd_per_mtok') and format(v['usd_per_mtok'], '.4f') or '-'} USD per million tokens")
            print(f"  {v['reason']}")
            for a in v.get("assumes", []):
                print(f"    assumes: {a}")
PY
