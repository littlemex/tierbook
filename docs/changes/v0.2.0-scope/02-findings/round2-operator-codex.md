**Operator Verdict**

I would not upgrade this log in place or enable exploration. Phase 1 defines desired ownership, but not the compatibility, migration, reporting, control, or recovery contracts needed to operate v0.2.0.

**Q1 — Mixed Log and `accept`**

Step by step:

1. My existing lines have no `schema_version`.
2. The v0.2 reader must explicitly treat an absent version as v0.1. That rule is suggested by F13 but not yet accepted as scope.
3. Once v0.2 appends a new-shaped decision, the reader needs version dispatch and normalization. No such contract is specified.
4. `accept --log` must then decide whether to:
   - preserve v0.1 semantics for old lines;
   - normalize all lines to v0.2 semantics;
   - or calculate separate results by schema, policy and mechanism version.
5. None of those choices is specified. Therefore a result across both shapes has no defined meaning.

The same previously reported number can silently change through:

- **Floor input:** `accept --floor` can differ from the floor used for routing or exploration.
- **Missing-field defaults:** interpreting absent v0.2 fields as `false`, `1`, empty, or unknown changes inclusions and denominators.
- **Parser rejection:** if new fields make a line “corrupt,” dropping or tolerating those lines changes every denominator.
- **Wall-clock classification:** changing `pending` to `missing` based on the time of reading restates a report without a new log event.
- **Late labels:** adding a label after a report changes historical success, calibration and compliance results.
- **Policy pooling:** combining policy versions changes the arm mixture and makes propensities incomparable.
- **Unweighted exploration:** randomized traffic changes the observed population; raw averages no longer estimate the deterministic policy’s result.
- **Certification treatment:** excluding explored requests from `floor_compliance` raises the reported compliance rate artificially.
- **Default treatment:** exploration into or away from the default changes `default_is_not_a_hiding_place`.
- **Evidence interpretation:** new provenance or freshness handling can move records between admissible, expired and uncertified groups.

Every acceptance criterion is exposed:

- `floor_compliance`: denominator and explored-certification treatment.
- `bound_calibration`: label maturity, weighting and evidence identity.
- `no_false_certification`: whether explored choices remain certified.
- `default_is_not_a_hiding_place`: changed default propensity.
- `slo`: randomized arm mixture and missing outcomes.
- `spend_regret`: randomized mixture, propensity weighting and cost coverage.
- `exploration_cost`: no fixed baseline or aggregation contract is stated.
- `adaptation`: policy-version pooling and time-window semantics.
- `genericity_and_usefulness`: changed record completeness and population composition.

I need immutable report inputs: log cutoff, reader version, metric-definition version, floor, policy-version partitions, label cutoff and weighting rule. The design provides none of that. A mixed aggregate must be refused, not guessed.

**Q2 — Enabling Exploration**

Before enabling it, I need to be told:

- The exact exploration rate and where its authoritative value lives.
- Whether the rate is per request, family, policy, arm or time window.
- The exact arm distribution, including treatment of the deterministic and default arms.
- Which gates exploration may bypass. Expired evidence may be bypassed; floor, authorisation, availability, latency and pricing must not be ambiguous.
- Maximum traffic and spend exposure per arm.
- What happens on configuration, randomiser, logging or outcome-system failure.
- Whether exploration stops automatically when labels cannot be produced.
- How policy changes partition analysis.
- How quickly I can disable exploration and what deterministic behavior resumes.

The smallest operational control set is:

1. One versioned configuration containing the rate, arm distribution, floor and eligibility rules.
2. Hard per-arm traffic and spend caps, while retaining non-statistical safety gates.
3. An immediate kill switch with deterministic fallback.
4. A preflight interlock requiring a healthy outcome path and declared latency.
5. Audit fields for eligible set, chosen propensity, policy/config version and the single draw.
6. Monitoring for exposure, spend, SLO, missing labels and propensity integrity.

The design provides only part of item 5 and the empty-eligible-set fallback. It does not provide authoritative configuration, caps, a kill switch, health interlocks, or monitoring. “Only one component draws” is an architectural statement, not an enforceable control.

**Q3 — No Outcome Oracle**

The only conforming behavior stated is that the join refuses to classify when the family lacks a labeller or maximum latency. But the design does not say that this refusal prevents exploration.

The worst permitted sequence is therefore:

1. Exploration serves traffic.
2. Decisions are logged.
3. The join refuses every outcome.
4. No evidence is generated.
5. Candidates continue aging, while I pay exploration cost for an unusable log.

`pending` forever would also be wrong. With a valid maximum latency, a durable event must transition from `pending` to `missing` at a recorded time. That transition cannot depend merely on when I happen to run `accept`.

Late labels are unresolved. The current three states cannot represent both facts:

- the label missed its deadline; and
- a label later arrived.

If a late label replaces `missing` with `labelled`, my previously reported number is silently restated. If the reader treats that as a changed label and refuses, the log becomes unreadable. If it ignores the label, useful evidence is lost.

The record needs separate timeliness and value fields, plus `observed_at`, `deadline_at` and an as-of reporting cutoff. Published reports must remain reproducible.

**Q4 — Evidence-Identity Refusal**

The first three encounters look like this:

1. **I edit a cohort item after compilation.** The artifact no longer matches. I can restore the exact certified snapshot or recompute the bound.
2. **I make a semantically harmless edit.** If identity is byte-based, whitespace, ordering or filename changes may refuse. I need a documented canonical digest; otherwise I still restore or recompute.
3. **I legitimately replace, add or correct data.** That is new evidence. I must create a new immutable artifact, recompute the affected result and retain the old artifact for old decisions.

There is a non-recompute recovery only when I can retrieve the exact old artifact by digest from a snapshot, content-addressed store, version control or backup. Renaming the current directory is not recovery and must not satisfy the check.

If the old artifact is gone and only its bound or row count remains, I am correctly stuck: identity cannot be reconstructed. The only honest paths are recovering the artifact or recomputing. The design requires the refusal but does not provide canonicalization, snapshot creation, artifact storage, garbage collection, or a recovery command. That makes the refusal correct but operationally incomplete.

**Q5 — Rollback**

A mixed log may break v0.1 in several ways:

- New decision fields may be rejected by a strict v0.1 `Decision` constructor.
- Rejected v0.2 lines may be counted as corrupt or exceed whatever corruption tolerance exists.
- New outcome fields or transitions may be rejected.
- A v0.2 ledger containing labeller and latency fields may also fail v0.1 schema validation.
- Even if parsing succeeds, v0.1 acceptance calculations do not have the stated mixed-policy and exploration semantics.

The safe rollback is not “point v0.1 at the mixed file.” It is:

1. Stop all writers.
2. Preserve the mixed log byte-for-byte.
3. Produce a separate, auditable v0.1 projection containing only compatible fields and events.
4. Keep v0.2 policy, ledger and evidence snapshots.
5. Refuse mixed-version acceptance reports rather than presenting v0.1 aggregates as comparable.

The original append-only lines are recoverable if retained. What is not recoverable is the traffic already served, its spend or SLO impact, labels lost because no oracle ran, and the counterfactual behavior of the environment during that period.

v0.2.0 needs an explicit forward-reader matrix, rollback projection, report reproducibility contract and exploration interlock before this is an operable upgrade.
