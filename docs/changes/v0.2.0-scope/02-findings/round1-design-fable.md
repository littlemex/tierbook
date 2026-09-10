# Audit

## Q1. Responsibility placement

Two of S1's four additions are correctly placed. Two ask a layer for something it cannot know, and the document's own escape hatch ("absent with a reason, never defaulted") converts that misplacement into a year of empty fields — which quietly defeats the irreversibility argument that justified S1 in the first place.

**Correctly placed:**

- `schema_version` — stamped by the record constructor. The writer knows what shape it is writing. Fine.
- `bound_n` / `bound_attempted` — but note the document's contract list is incomplete here. `serve` writes the `Candidate`; `serve` reads a compiled artifact; therefore the *compiler's output* must gain these fields, and the "contracts this changes" section names the compiler→ledger precondition but not the compiler→serve artifact enrichment. The plumbing is real; the contract for it is unwritten.

**Misplaced:**

- **`stratum`.** The design assigns it to `serve.route_once`'s caller. But stratum is *how hard the work is* — a measurement, not caller metadata. The mechanism's own gap #1 says the collector does not exist: "`decide` is given a state, it does not observe one." Nothing in v0.2.0 builds a producer for stratum, so the caller will supply `absent: no collector` on every request. The field's claimed benefit — retrofit-proofing — only materializes if *values* land in it. A field that is present-but-absent for a year distinguishes the schema versions and loses the data anyway. The document proves stratum can't be recovered from outcomes, then hands it to a layer that also can't produce it, and calls the problem solved.
- **`features`, partially.** The two named intended occupants are a hidden-state probe and an answer-token margin. The probe comes from inside the box (explicitly out of scope, needs GPU). The answer-token margin is computable only *after generation* — after the decision. A decide-time slot on `Decision` is temporally the wrong home for one of the two signals it was designed for. Either the record needs an amendment path (post-hoc feature attachment, with its own versioning), or half the slot's motivation is void. The document doesn't notice this.

Consequence class is the one caller-supplied field that genuinely is caller knowledge (the caller knows what it will do with the answer). It's fine.

## Q2. Re-derivation from purpose

Derive from "lower cost, minimal accuracy loss, **deciding from observed state**, in a **moving environment**":

1. Something that *observes* — at least one real signal produced and recorded per request (gap #1).
2. Exploration with propensities, because a moving environment plus no exploration means the incumbent's superiority is an artifact of construction (gaps #2, #3). = S3.
3. Some answer to environment movement beyond expiry-by-age (gap #5).
4. Record hygiene to make 1–3 legible later. = S1's versioning.

**Divergences:**

- **The purpose's central clause is untouched, and the document under-admits it.** v0.2.0 records *slots* for observed state and observes nothing. After this release, `decide` is still given a state it does not observe. The document is admirably blunt that "`accept` gains nothing from S1" but never states the larger version: *the purpose statement's key phrase is deferred in its entirety.* Partially justified (the probe needs hardware), but a crude stratum producer — even a heuristic one, versioned and named as such — was in reach and would have made S1's stratum field collect something. Not justified as scoped.
- **Change-point detection deferred.** Justified — it is genuinely additive, and `model`/`endpoint`/`decided_at` already give a later detector something to work with.
- **Scarce-capacity value deferred.** Defensible, though note the tension: the purpose is *cost*, and gap #6 is a direct cost leak. "It changes the objective" is a real reason but it's a reason the leak persists, not a reason it doesn't matter.
- **S2 does not derive from the purpose at all.** It derives from honesty about a latent statistical defect. That's fine — but it means S2 is in the release on a different warrant than S1/S3, and its guard needs to be judged on its own terms (see Q5).
- Ordering S1 before S3 despite S3 carrying the value: justified, *provided both actually ship in the same release*. If S3 slips to v0.3.0, the ordering argument becomes the mechanism by which the largest recurring loss was extended — watch for that.

## Q3. Adversarial on the design

**What breaks under a slight shift: S2.** The refusal predicate is "the cohort has *grown*." The actual hazard is *evidence changed after the bound was read, with admission at a data-dependent time*. Growth is a proxy. The moment `trials_per_item > 1` ships — re-measuring the *same* items — evidence changes with zero growth and the guard passes silently. Same for relabeling (the pilot has one "permanently unscoreable" item; the day it becomes scoreable, evidence changed, cohort didn't grow). The predicate must be evidence-*identity* (a hash of the evidence set the bound was computed over), not cardinality. As specified, S2 is a rewrite waiting for the first accrual feature.

**What must change together: S1 and S2.** S2's refusal needs the bound's cohort identity; S1 records only counts (`bound_n`, `bound_attempted`) plus the pre-existing `evidence_as_of`. Counts cannot back an identity check. If S1 ships counts and S2 ships a growth check, both are individually plausible and jointly weak. S1 should record a cohort/evidence fingerprint; then S2's predicate is a comparison against it, and the record can also *audit* past refusals. (Secondarily, S1 and S3 are coupled through `accept`: `floor_compliance` over certified-only across two schema versions with an exploration flag is one reader with three simultaneous new rules.)

**The wrong-shaped field: `stratum` as a bare value.** The document already contains its own indictment: "a fabricated stratum is worse than none because it aggregates." A stratum recorded without a **stratification-scheme version and assigner identity** will aggregate across drifting definitions. Strata definitions *will* drift — the pilot can't even carry four strata yet, so the scheme that eventually gets used will be designed later, and early strata (from whatever ad-hoc scheme callers use in the meantime) will be incomparable with late ones while looking identical. That is precisely a field recorded for a year and then found unusable — worse, found *usable-looking*. The `features` mapping has a milder version of the same disease: one version number for a mapping of signals with independent lifecycles (probe v2 + margin v1 cannot be expressed). Version per feature, or the vector version means nothing.

Honorable mention: `(bound_n, bound_attempted)` as a flat pair discards item-level structure. The day re-measurement arrives (which S2 explicitly anticipates), a clustered bound cannot be reconstructed or audited from the pair. Reconstructible via ledger join, so tolerable — but the document's "the pair is what a later reader needs" is true only under `trials_per_item = 1`, an assumption the same document treats as temporary.

## Q4. Irreversible vs. recurring

The distinction is sound as a *taxonomy* and wrong as *applied* — in both directions.

**S3 contains an irreversible core.** "Recurring" implies the loss is replaceable in kind: ship exploration later, collect the same data then. That assumes stationarity — and the mechanism's own premise (gap #5, "the environment stopped resembling the one it was measured in") denies it. What a propensity-1 log costs is not generic data volume; it is *the counterfactual arm's behavior in the interim environment*, and the interim environment will not exist later. "Would the alternative have been better during Q1" is permanently unidentified for any Q1 before exploration ships. Worse, gap #3 compounds it: the routed-away-from arm's evidence expires by age while it collects no labels, at which point it is `evidence_expired`, excluded, and — if exploration randomizes only among live arms — dead in a way that requires a deliberate re-measurement campaign to reverse. Deferring S3 doesn't just lose log lines at a constant rate; it can kill an arm. That is a foreclosure, not a recurring cost.

**Meanwhile, half of S1 is not irreversible.** `schema_version` is retrofittable by convention: a reader that treats version-absent as v0.1.0 loses nothing, because v0.1.0's shape is known and fixed. (It becomes irreversible only once *two* unversioned shapes coexist — which is exactly what shipping it now prevents, so it stays in scope, but the honest label is "cheap insurance," not "irreversible.") `bound_n`/`bound_attempted` are reconstructible from the ledger via `family` + `evidence_as_of`, assuming the ledger is append-only — so that item is convenience plumbing, not rescue from oblivion.

**What survives scrutiny:** the genuinely irreversible items are stratum-at-request-time, consequence class, decide-time features, and *the act of randomisation itself*. Note that last one is in S3, not S1. The document's headline claim — S1 irreversible, S3 merely recurring — has the most irreversible single thing in the release filed under "recurring."

## Q5. Is S2's refusal honest?

The *shape* is honest — declining to make a claim you cannot stand behind, and naming the lift condition, is right. As specified, three things push it toward theater:

1. **The guard never fires in v0.2.0.** Nothing accrues today; the document says so. A refusal that cannot trigger is untested code protecting against a hazard that arrives with a future feature — and it will be the author of *that* feature, whose work the guard blocks, who first encounters it. A guard whose only ever encounter is by the person incentivized to delete it is a deferral, not a defense. The honest version makes the coupling hard: the accrual feature *cannot ship* without anytime-valid bounds, stated as a dependency in the accrual feature's scope, not as a runtime refusal to be discovered.

2. **The predicate is a proxy** (Q3). If "cohort has grown" is the check, an operator hitting the refusal has an obvious remediation: freeze the current evidence under a new cohort name and recompute a fixed-sample bound. That is *optional stopping laundered through a rename* — peeking at accrued evidence, then choosing the freeze point — and it is exactly the anti-conservative behavior the guard exists to prevent. Unless S2 also refuses bounds computed over cohorts whose freeze point was chosen after observing accrual, the guard has a hole shaped like its whole purpose.

3. **"Names anytime-valid bounds as what would lift the refusal" is a pointer, not a plan.** Honest deferral has an owner, a trigger, and a consequence for the trigger firing. This has a citation.

**What would make it the latter, concretely:** the refusal fires for the first time in v0.4.0; the operator renames the cohort and recomputes; certification proceeds; nobody notices the stopping time was data-dependent. Every element of that path is permitted by S2 as written. Fix the predicate to evidence identity, close the re-freeze loophole explicitly, and make anytime-valid bounds a stated blocker on the accrual feature rather than a lift condition on a guard — then it's honest engineering. As drafted, it's a well-worded IOU.

---

**Summary of demanded changes:** give `stratum` a scheme version and assigner or accept that it will be empty for a year and say so; version features individually and decide the post-hoc attachment question now; replace S2's growth predicate with evidence identity and record that identity in S1 (the coupled pair); close the re-freeze loophole; relabel the S1/S3 cost taxonomy — the randomisation gap is the most irreversible thing in this release, and the scope should carry that as the argument for why S3 must not slip.