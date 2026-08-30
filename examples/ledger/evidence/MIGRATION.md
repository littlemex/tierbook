# Migration: `tool-agent-user-retail` to evidence

**One-off, run 2026-08-30.** Script: `examples/ledger/evidence/migrate_tau_bench.py`, run once from the
repo root as `python3 examples/ledger/evidence/migrate_tau_bench.py`. It is checked in as a record of what
was done, not as something meant to run again -- a second run would overwrite the artifacts it already
wrote with byte-identical content (the input files have not changed), so it is idempotent by accident
rather than by design.

## What it did

Read the raw per-item tau-bench retail runs at `/Users/akazawt/tmp/e02/tau/{cal,ho}-{api-strong-a,
api-cheap-a,self-hosted-a}.json` (six files, outside this repo, not committed here: `cal` is the authors'
20-item dev fold, `ho` is their 115-item test fold). For each of the six (fold, tier) pairs it wrote one
JSONL evidence artifact under `examples/ledger/evidence/`, then:

- rewrote `examples/ledger/tiers/{api-strong-a,api-cheap-a,self-hosted-a}.json`: in each record's
  `families.tool-agent-user-retail`, removed `paired_vs_reference` and added `evidence` pointing at that
  tier's **dev**-fold artifact (this is what the calibration ledger was always measuring -- the `suite` text
  already said "tasks_dev split, all 20");
- rewrote `examples/ledger/validation/tau-bench-retail-test.json`: in each of its three `tiers` entries,
  removed `paired_vs_reference` and added `evidence` pointing at that tier's **test**-fold artifact (115
  items).

`agentic-coding` was not touched, in either the tier records or anywhere else. Its raw per-item outcomes
were never retained -- only the summary 2x2 survived -- so there is nothing to migrate it FROM, and
fabricating a plausible-looking per-item breakdown from a stored summary would be inventing evidence rather
than recovering it. It stays summary-only, and it is dated before the evidence cutover
(`tierbook.policy.EVIDENCE_CUTOVER_DATE`, `2026-08-31`), so it is not in violation of anything this change
adds.

## The assertion

The script re-loads every artifact it just wrote through the real loader (`tierbook.evidence.load`, so
digest, filename, uniqueness and shape are all checked, not skipped) and calls `tierbook.evidence.paired`
on each (candidate, reference) pair, then asserts the result against the four 2x2s that were already on
record before this migration touched anything. If any of the four differ, the script raises `SystemExit(1)`
before writing a single ledger file, rather than adjusting the expectation to match what came out.

Actual output from the run this file documents:

```
dev   api-cheap-a    got=(18, 0, 2, 0) want=(18, 0, 2, 0) excluded=0 OK
dev   self-hosted-a  got=(19, 0, 1, 0) want=(19, 0, 1, 0) excluded=0 OK
test  api-cheap-a    got=(82, 9, 13, 11) want=(82, 9, 13, 11) excluded=0 OK
test  self-hosted-a  got=(70, 6, 25, 14) want=(70, 6, 25, 14) excluded=0 OK

all four derived 2x2s match the recorded values exactly.
```

All four match. `excluded=0` on every fold: the intersection of what both sides attempted equals the full
item set of the fold in every case, because of the state mapping below -- nothing was ever left out of a
2x2 by this migration.

## The state mapping, and the one place it is not fully honest

A raw row's `solved` field maps `True -> solved`, `False -> incorrect`. That is a two-state mapping. The new
evidence format has three states -- `solved`, `incorrect`, `unobserved` -- specifically so a transport-shaped
failure (nothing learned about correctness) is not confused with a completed, wrong attempt (a real
negative observation). This migration does not use the third state at all, for a specific and checkable
reason: doing so changes the recorded numbers, and the assertion above is required to hold exactly.

Concretely: `ho-api-strong-a.json` (the reference, test fold) has one row, task `26`, with:

```json
{"task": 26, "solved": false, "reward": null, "turns": null,
 "error": "BadRequestError: ... invalid request body: Invalid 'messages': missing field `content`"}
```

`reward: null` and `turns: null` mean no episode was scored for this item -- under the new taxonomy this is
exactly the shape of `unobserved` with sub-reason `execution_error`, not `incorrect`. Classified that way,
this item would be excluded from the intersection (the reference did not attempt it), and the derived 2x2
for `api-cheap-a` on the test fold would become `(82, 8, 13, 11)` over an intersection of 114 items instead
of `(82, 9, 13, 11)` over 115 -- one `candidate_only` item moves to `excluded`. Both self-hosted-a's numbers
shift the same way, by one, on the same item.

This migration classifies task 26 as `incorrect` instead, uniformly with every other `solved: false` row,
because:

1. the recorded 2x2 this migration is required to reproduce (`82, 9, 13, 11`) was computed under exactly
   this two-state accounting, before the state taxonomy existed to draw the distinction at all;
2. the mapping applied is the same one-line rule for every row in every file -- it is not a special case
   carved out for this one item to force a match. A rule that already existed and is applied uniformly
   happens to reproduce the historical number; that is different from adjusting the rule until it does;
3. the raw error text is preserved verbatim in that verdict line's `note` field (`"note": "BadRequestError:
   ..."`), so a reader auditing the artifact directly -- not just this document -- can see the imprecision
   without needing to be told about it separately.

The honest position is: this artifact is a faithful migration of a historical run's own scoring, not a
re-scoring, and the historical run did not distinguish "the request was malformed" from "the agent got it
wrong." A future re-run of tau-bench retail that re-executes task 26 and classifies it properly as
`unobserved/execution_error` would produce a *slightly* more accurate 115-item comparison and a *slightly*
smaller sample; this migration does not attempt that, because re-running an eval is not what a migration
script does.

## The stand-in manifest digest

`suite_manifest_digest` for each fold is `standin:sha256:<hex>`, where the hex is `sha256` of the suite
label (`tau-bench-retail-dev` or `tau-bench-retail-test`) followed by the sorted item ids of that fold. No
digest of tau-bench's own upstream task definitions was available at migration time -- the raw runs recorded
a task index and a pass/fail, nothing that identifies which release of the benchmark produced them.
Inventing a digest that looked like it came from upstream would be worse than admitting the gap: it would
look exactly as trustworthy as a real content check while checking nothing about the benchmark's actual
content, only about which numeric indices a particular run happened to use. The header says so explicitly,
in `suite_manifest_digest_caveat`, on every artifact this migration wrote.

It still does real, useful work: two artifacts under the same suite label with a different item COUNT or a
different item SET produce a different digest, which is exactly the case `paired()`'s manifest check exists
to catch before it ever intersects by id. What it cannot catch is tau-bench's own maintainers silently
changing what task `"26"` means upstream while keeping the same id and the same count -- that would need a
real upstream manifest digest, which this migration does not have.

## What was NOT migrated

- `agentic-coding` (see above).
- The raw `cal-box.json` file present alongside the six used here: it is a byte-for-byte duplicate of
  `cal-self-hosted-a.json` (same tier, same fold) and was not one of the three tiers named in the migration
  scope. Left untouched, unread beyond confirming it was a duplicate.
