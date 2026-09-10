# Operator review, v0.1.0 → v0.2.0, with a live log

Preliminary complaint that colors everything below: this is a phase-1 document, and for four of my five questions the honest answer is "phase 2 hasn't decided." I'll answer against what's written, and every place the design punts, I'll say what the punt costs me.

---

## Q1. The upgrade walk

**Step 1: the reader hits the mixed log.** My v0.1.0 lines have no `schema_version` (A1). F13 says absent-version is *readable as* v0.1.0 — but that's a convention, and the design's own A1 result says **nothing validates the decision log**. So "readable as v0.1.0" is enforced by nobody. If the v0.2.0 reader treats an unversioned line as v0.1.0, fine. If it treats it as malformed, `read()` tolerates *one* corrupt line — my second pre-upgrade decision kills the read. The design does not say which. That's not a triage item, that's a launch blocker for anyone with a log on disk.

**Step 2: `accept --log`.** Three problems fire in order:

- **F3 fires first.** `accept --floor` takes the floor from me at the CLI; the policy took it from `assign_family`; exploration eligibility needs it a third time. Nothing compares the copies. Post-upgrade, if the randomiser's `clears_floor` uses a floor one keystroke different from the one I pass to `accept`, `floor_compliance` is computed against a floor the traffic was never served under. Silent, and one flag away.
- **The join reads a declaration that doesn't exist** (A6). My families declare `solved`/`attempted`/`suite` only. The contract says refuse-to-classify. Does that make `accept` fail per family, or skip label-dependent criteria silently? Unstated. If it skips silently, that is exactly the failure section 4 names — and section 4 admits phase 2 might choose it.
- **Old `label_state` was "settled by whoever looks."** The v0.2.0 join, if it runs at all, reclassifies pending/missing under a latency rule my old outcomes were never governed by. Retroactive relabeling of pre-upgrade records is a silent restatement of every success rate I've reported.

**Step 3: criteria across both shapes.** Here is the full list of numbers that silently change:

1. **`exploration_cost`** — pre-upgrade traffic contributes zero exploration; computed over the whole log the rate is diluted by an amount that depends on log length, not behavior. No pooling rule stated (F1 makes it available, nothing uses it).
2. **`default_is_not_a_hiding_place`** — the contract explicitly explores away from the default, so the default's propensity drops below 1 at the upgrade boundary. Any default-share statistic pooled across the boundary compares two different mechanisms and reports one number.
3. **`spend_regret`** — explored decisions are deliberately non-optimal. Computed naively, regret rises at the upgrade and looks like degradation. Nothing in the design says exploration traffic is credited or annotated for this criterion.
4. **`floor_compliance`** — F8 is flagged, not decided. If phase 2 ships "explored = uncertified," my denominator shrinks by exactly the traffic most likely to breach the floor.
5. **Any counterfactual estimate** — old records read as propensity-1 deterministic decisions. Pool them with propensities under weighting and they contribute infinite-weight certainty. F1 says the pooling rule is unstated. Unstated means someone will compute it wrong and the number will look fine.
6. **`exploration: false` changes meaning.** In v0.1.0 it meant no mechanism existed. In v0.2.0 it also means "randomiser ran and the eligible set was empty." Same bit, three causes, no discriminating field. The design itself says silence here would be indistinguishable from policy — and then records the failure mode *as* silence with `exploration: false`, propensity 1. That contradicts its own stated concern. I need a distinct recorded reason, not a shared false.

---

## Q2. Before I turn exploration on

What I have to be told and am not:

1. **The exact eligible set.** A7 tells me expiry (`evidence_expired`) is decided before the bound, so exploration bypasses expiry via a separate `clears_floor`. Fine — but what about `not_authorised`, `latency_infeasible`, `not_priced`? Does the randomiser draw from candidates the gateway never authorized? The design enumerates one exclusion it overrides and is silent on the other seven. I will not route paid traffic through a randomiser whose eligible set I cannot enumerate.
2. **What bound `clears_floor` uses.** The whole point of the door is reaching a candidate whose evidence expired — meaning the bound that "clears the floor" is by construction stale. How stale is acceptable? 91 days? 400? Nowhere.
3. **Where the rate lives and what zero means.** F5 says one home, doesn't pick it. And rate-zero must be recorded distinguishably from randomiser failure and from pre-upgrade absence (see Q1 item 6). Kill switch semantics are not designed.
4. **The F17 gate.** Exploration before the outcome join works is randomized traffic nobody learns from — the design says so and then leaves it as a triage item. The minimal control is a refusal: *no exploration in a family without a declared labeller.* That couples F6 to the exploration switch mechanically. Not provided.
5. **F2's second draw.** Nothing forbids a retry policy drawing again. If my gateway retries, my recorded propensities are one factor of the truth from day one and I find out at analysis time.

Smallest sufficient control set: (a) one rate, per-family, zero-off with a recorded state; (b) enumerated exclusion-override list, expiry only; (c) `clears_floor` with a stated staleness bound; (d) labeller-declared-or-refuse gate; (e) single-draw enforcement. The design provides half of (b) and half of (c). That's it.

---

## Q3. The join with no oracle

With nothing declared, the join refuses to classify — for every family, forever, because A6 says the schema can't even carry the declaration yet. So: `attach_outcome` still has no caller (F7), `label_state` stays wherever the writer put it, `missing` can **never** be produced (producing it requires the latency window that doesn't exist), and every explored assignment is F17's unlabellable log line. Practically, v0.2.0 gives me v0.1.0's outcome situation plus randomized traffic. That's strictly worse until the ledger schema changes ship — which section 4 correctly refuses to hand-wave, but phase 1 also doesn't order them.

**The late label is the sharp edge.** `read()` refuses when a label CHANGES. Two cases, neither designed:

- If `pending → labelled` counts as a change, the first late label makes my entire log unreadable. Hard stop, no verb to recover with, append-only log.
- If it doesn't count, then the number I reported yesterday was computed on pending-excluded data and today's read gives a different number *from the same command with no marker*. There is no as-of semantics in `read()`. A reported number is unreproducible and nothing says so.

Either the reader gains as-of-timestamp reads, or every report I produce needs an out-of-band snapshot. The design addresses neither.

---

## Q4. Evidence-identity refusal, hand-edited cohort

**Hit 1:** I fix a typo in one item's expected answer. Compile refuses. I recompute the bound. Annoying but correct — except nothing tells me the new bound isn't poolable with the old one, and nothing on the record distinguishes recomputed-after-edit from continuous.

**Hit 2:** I add an item. Refusal again. Now I've learned the workaround the design itself documents: **rename the cohort and recompute** (F10). Optional stopping laundered through a rename, in the design's own words — noted as a finding, not closed. A refusal whose documented bypass is a rename doesn't protect anything; it selects for operators who rename.

**Hit 3:** I reformat the directory — key order, whitespace, no semantic change. Does it refuse? I can't tell, because *the design never defines "matches."* Byte hash? Canonicalized content? Row identity? "Exists and matches" is the entire contract text. For a hand-edited directory this is the whole question.

**The stuck state exists:** v0.1.0 never told me to retain evidence artifacts. If a bound cites an artifact I deleted, the compiler refuses to certify, the candidate goes `no_bound`, A3's ratchet does the rest, and the only exit is rerunning trials — against an endpoint or model that may no longer exist. Then the candidate is **permanently uncertifiable**, retroactively, because v0.2.0 imposed a retention requirement v0.1.0 never stated. The upgrade notes must say "archive every evidence artifact before upgrading" and the design doesn't know it needs to.

---

## Q5. Rollback with a mixed log

**Mechanical reads probably succeed, and that's the problem.** v0.1.0's line kinds match; v0.2.0 lines carry extra fields. If the v0.1.0 reader ignores extras, every explored decision — propensity 0.05, deliberately suboptimal — reads back as an ordinary policy choice. `spend_regret`, `floor_compliance`, `default_is_not_a_hiding_place` all silently include randomized traffic as if the policy chose it. Rollback that *lies* is worse than rollback that breaks. If instead the reader treats new-shaped lines as corrupt: one-line tolerance, second line kills the read, log unreadable under v0.1.0.

**Outcome lines from the v0.2.0 join** that reclassified anything trip v0.1.0's label-change refusal, making the mixed log unreadable by the version I rolled back to — and there is no verb to split or filter an append-only log. Recovery is hand surgery on the evidence record, which is the exact thing append-only exists to forbid.

**Unrecoverable, full stop:** the exploration window's traffic was really served — rollback doesn't unserve it — and by the design's own A3 argument, the counterfactual data from the *interim* environment is gone permanently. The one saving grace is that `mechanism_version` is already on every record, so the regime boundary is at least locatable. That field, plus F13's `schema_version`, is the entire rollback story, and only one of the two exists today.

**Bottom line for phase 2:** reader behavior on unversioned and future-versioned lines, `read()` semantics for late labels, the definition of evidence "matches," and the recorded distinction between rate-zero / empty-eligible / pre-upgrade are not triage items to weigh — they are the upgrade path. Ship exploration without them and my log stops being evidence in both directions: forward and back.