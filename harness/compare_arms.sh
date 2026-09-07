#!/usr/bin/env bash
# Two arms, one comparison, and every refusal actually left in place.
#
# Runs the whole path for a pair of measured cohorts: join each arm, reconcile the gateway's aggregate against the
# sum of its own per-call replies, build one registry, compile, run the paired comparison, and print the price at
# which the two arms cost the same.
#
# It does NOT print a winner. At 24 items with one run per arm the paired discordance is what carries any claim,
# and two independent binomials would be the wrong statistic on tasks both arms attempted.
#
# An earlier version of this file ended two of its steps with `|| true`, which neutralised exactly the refusals it
# claimed to preserve -- a review caught it. Now every step fails the script, and artifacts land in a staging
# directory promoted only when all of them pass. Otherwise a stale policy from a previous run survives beside a
# failed one and reads as current.
set -euo pipefail

BOX_OUTCOMES=${BOX_OUTCOMES:?}
BOX_TRACES=${BOX_TRACES:?}
API_OUTCOMES=${API_OUTCOMES:?}
API_TRACES=${API_TRACES:?}
API_RUN_GROUP=${API_RUN_GROUP:?}
REFERENCE_TIER=${REFERENCE_TIER:?}     # named, not guessed: filename order could pick the metered arm
SHIM_REQUESTS=${SHIM_REQUESTS:?}
LEDGER_BEFORE=${LEDGER_BEFORE:?}
LEDGER_AFTER=${LEDGER_AFTER:?}
HOURLY_USD=${HOURLY_USD:?}
WINDOW_HOURS=${WINDOW_HOURS:?}
OUT=${OUT:-/tmp/compare}

HERE=$(cd "$(dirname "$0")" && pwd)
STAGE=$(mktemp -d "${OUT%/}.staging.XXXXXX")
trap 'echo "REFUSED: a step failed. Nothing was promoted; $STAGE holds what was produced" >&2' ERR

echo "=== 1. join each arm ==="
# First, so the reconciliation below can be restricted to the cohort that actually joined rather than to every
# record the translator happened to write.
python3 "$HERE/join_sources.py" --outcomes "$BOX_OUTCOMES" --traces "$BOX_TRACES" \
  --no-metered-candidates --out "$STAGE/joined-box.json"
python3 "$HERE/join_sources.py" --outcomes "$API_OUTCOMES" --traces "$API_TRACES" \
  --run-group "$API_RUN_GROUP" --no-metered-candidates --out "$STAGE/joined-api.json"

echo
echo "=== 2. the gateway's aggregate against the sum of its own replies ==="
echo "    (a reconciliation within one authority, not an independent check)"
python3 "$HERE/crosscheck_ledger.py" --before "$LEDGER_BEFORE" --after "$LEDGER_AFTER" \
  --requests "$SHIM_REQUESTS" --out "$STAGE/ledger-reconciliation.json"

echo
echo "=== 3. one registry holding both arms ==="
python3 "$HERE/sweep_to_ledger.py" --joined "$STAGE/joined-box.json" --out "$STAGE/ledger" \
  --hourly-fixed-usd "$HOURLY_USD"
python3 "$HERE/sweep_to_ledger.py" --joined "$STAGE/joined-api.json" --out "$STAGE/ledger"

echo
echo "=== 4. what the evidence supports ==="
PYTHONPATH="$HERE/../src" python3 -m tierbook.cli compile \
  --registry "$STAGE/ledger/tiers" --family "agentic-coding=$REFERENCE_TIER" \
  --margin 5 --window-hours "$WINDOW_HOURS" --min-items 20 \
  --out "$STAGE/policy.json" --report "$STAGE/policy.md"

echo
echo "=== 5. the paired comparison, which is the only one these tasks support ==="
python3 "$HERE/paired_arms.py" --a "$STAGE/joined-box.json" --b "$STAGE/joined-api.json" \
  --out "$STAGE/paired.json"

echo
echo "=== 6. the price at which the two arms cost the same ==="
PYTHONPATH="$HERE/../src" python3 "$HERE/break_even.py" --registry "$STAGE/ledger/tiers" \
  --window-hours "$WINDOW_HOURS" --out "$STAGE/break-even.json"

trap - ERR
rm -rf "$OUT"
mv "$STAGE" "$OUT"
echo
echo "every step passed; promoted to $OUT"
