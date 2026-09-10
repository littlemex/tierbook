# CONTRACT: v0.2.0 — make the log survive its own evolution, then explore safely into it

Phase 2 output. Two review rounds, two models each: adversarial-on-the-design, and the operator holding a v0.1.0 log.
Raw output in `02-findings/`. 26 findings deduplicated, triaged in three passes, and the ones not taken are below with
their reasons — because a rejection without a reason is a rejection that gets re-litigated.

## Out of scope, written first

| Not changing | Why |
|---|---|
| A `stratum` field on the decision | **F16, F4-assumption.** Nothing in this release produces one, so it would be present-and-absent for a year: it distinguishes the schema versions and loses the data anyway. An unversioned caller-supplied label is worse than absence because it creates false comparability. Returns when a versioned classifier exists to fill it. |
| A `consequence_class` field | **F8 makes it unnecessary here.** Genuinely caller knowledge, but recording a risk class while ignoring it is indefensible once exploration can serve inferior candidates — and C3 removes the need by constraining exploration to the floor instead of relying on a risk label. |
| A `features` mapping on the decision | **F15, F5-assumption, both refuted its justification.** It is a junk drawer that cannot express provenance, units, extractor identity or per-value missingness; it does not buy retro-comparability, because an old event lacks the measurement whether or not the slot existed; and one of its two intended occupants — an answer-token margin — exists only *after* generation, so a decide-time field is the wrong home. What would buy retro-comparability is a `state_ref` resolving to replayable raw state, which is larger than a field and is not this release. |
| `bound_n` / `bound_attempted` on a candidate | **F12.** They encode one binomial layout rather than a bound's provenance and cannot reproduce a bound computed with weights, clusters or stratification. They are also reconstructible from the ledger via `family` + `evidence_as_of`. Convenience, not rescue. |
| Evidence-identity refusal (digest-matched certification) | **F10 killed the cheap version and F26 killed the expensive one.** "Refuse if the cohort grew" is a proxy with a hole shaped like its purpose: a 24-item cohort can change completely and stay 24, and an operator hitting it freezes the evidence under a new name and recomputes — optional stopping laundered through a rename. The honest version needs canonicalisation, snapshot creation, artifact storage, garbage collection and a recovery command, or the refusal is correct and leaves the operator stuck. And A2 found the hazard is **latent**: nothing accrues evidence today. Deferred as a whole, with the obligation below. |
| Anytime-valid bounds | **F11.** A runtime guard that cannot fire in the release that adds it is first met by the author of the feature it blocks, who is the person most motivated to delete it. Carried as a prose obligation instead — see *The obligation carried forward*. |
| Change-point detection | Additive, and `model`, `endpoint` and `decided_at` already give a later detector something to work with. |
| A value for the reserved candidate's scarce capacity | A real cost leak and a different release's subject. Deferring it is a reason the leak persists, not a reason it does not matter. |
| The hidden-state measurement | `docs/issues/hidden-state-signal-from-the-box.md`. Needs GPU and may not survive an MoE. **Its `features`-slot home is withdrawn above**, so it will need its own record amendment when it lands. Said here so the issue is not read as already accommodated. |
| A crude stratum producer | **F14 argued for it and it is declined.** A heuristic classifier nobody has validated puts values in a field and makes them look like measurements, which is the failure the `stratum` rejection above is about. |
| Learning from the log — a bandit, a scheduler, any policy update | C3 makes the log *able* to support that later. Doing both at once means a release where nothing can be attributed, because the exploration and the learning move together. |

## What changes

### C1 — a reader that survives a field being added. **First, because everything else writes fields.**

`accept._as_decision` splats every key of a logged row into `Decision(**kw)`. Verified:

    a record carrying a NEW field -> TypeError: __init__() got an unexpected keyword argument 'schema_version'

So **adding any field to the record makes every older reader raise on every line**, and the raise happens outside
`Log.read`'s corrupt-line tolerance, so it kills the whole acceptance run rather than being counted. That is a launch
blocker for anyone with a log on disk, in both directions: forward for a v0.1.0 reader meeting v0.2.0 lines, and
backward for an operator rolling back.

C1 makes the omission unrepresentable rather than adding a convention:

- The reader **ignores keys it does not know**, and counts them, so a later field cannot break it.
- A row with **no `schema_version` reads as v0.1.0**, whose shape is fixed and known. Not by convention enforced by
  nobody — by the reader's own code, with a test that feeds it a real v0.1.0 line.
- `schema_version` is **stamped by the writer**, not passed in by a caller: the component that serialises knows what
  shape it wrote.
- A row whose version is **newer than the reader knows** is refused by name rather than parsed optimistically. Reading
  a future shape as if it were this one is the silent-corruption case.

This reframes F13. `schema_version` was called cheap insurance; the field is, and **the tolerance is the prerequisite**.

### C2 — the policy artifact records the parameters it was compiled under.

Verified: the compiled policy carries `certified: true` and **does not carry the floor**. The floor has three supply
points — `assign_family`'s argument, `serve.route_once --floor`, `accept --floor` — and zero recorded copies. So no
criterion computed over a v0.1.0 log can be known to have used the policy's floor, and the
`no_false_certification: pass` published in `docs/verify/v0.1.0-accept.json` is conditional on a number typed at a shell
prompt matching one the artifact never wrote down. `max_evidence_age_days` has the same shape, and it is the number the
one-way door in A3 turns on.

The artifact records the floor and the evidence-age limit it was compiled under; every consumer reads them from there;
and a consumer given a conflicting value **refuses rather than preferring one**. One home, and disagreement becomes a
failure instead of a preference.

### C3 — exploration, specified before it is implemented.

The eligible set, the draw and the recorded propensity, each pinned because a review found each one under-specified.

**Eligibility is enumerated, and expiry is the only override.** Exploration draws from candidates whose **bound clears
the floor**, where `clears_floor` is a predicate separate from `admissible` — necessary because `admissible` decides
expiry *before* comparing the bound (A7), so reusing it could not reach the arm the ratchet locked out. The other
exclusions are **not** overridden: a candidate that is `not_authorised`, `latency_infeasible`, `unavailable`,
`not_priced` or `no_bound` is not explored into. A review declined to route paid traffic through a randomiser whose
eligible set it could not enumerate, and that is the right refusal.

**An expired candidate's bound has a stated staleness limit.** The door exists to reach a candidate whose evidence
expired, so the bound that clears the floor is by construction stale. An unbounded staleness is a bound from any past
environment; the limit is declared per family and recorded in the artifact under C2.

**One draw.** Exploration is the only place a random draw happens for a decision. A retry policy that drew again would
make the recorded propensity one factor of the true one, and the error would surface only at analysis time.

**The propensity is the conditional probability of the arm chosen, under the draw performed.** The first draft's own
example was wrong: two arms with 5% exploration spread over both gives 0.975 and 0.025; exploration always taking the
alternative gives 0.95 and 0.05; the draft said 0.95 and 0.025, which needs three arms. The randomisation is therefore
specified in the contract rather than in the implementation, and the eligible set is recorded beside the propensity so
it can be checked rather than reconstructed.

**Not "uncertified by construction".** Certification says whether an action clears the floor; exploration says why it
was selected. Conflating them permits serving below the floor and then removing that traffic from
`floor_compliance`'s denominator — which preserves the metric, not the floor. Since eligibility already requires the
bound to clear the floor, an explored assignment is certified when the rest of admissibility holds, and
`floor_compliance` reports **two** numbers: over certified traffic and over all served traffic.

**`exploration: false` gets a reason.** The design's own contract said silence would be indistinguishable from a policy
that chose not to explore, and then recorded the failure *as* that silence. Three causes share the bit today — no
mechanism, an empty eligible set, a zero rate — so the record carries which one.

**One home for the rate**, the family's declaration in the artifact, with zero recorded distinguishably from absent.

### C4 — the outcome join, and exploration that cannot be expressed without a labeller.

`Log.attach_outcome` exists and nothing calls it. Exploration on top of that produces randomised assignments nobody can
learn from, so the join is a prerequisite rather than a companion.

SCOPE section 2 requires the label's **source and maximum latency** declared per family. A6 found the family block
requires only `solved`, `attempted`, `suite`, and the schema does not carry either field. **Phase 1 refused to proceed
on this point and the contract chooses the first branch:** the family declaration gains a labeller and a maximum label
latency, and the schema requires them.

And the coupling is mechanical rather than a runtime guard: **a family without a declared labeller cannot have an
exploration rate.** Not "exploration refuses at runtime" — the artifact cannot represent one, so the omission is a
compile failure rather than a discovery. That is what terminates F6, F7, F17 and F24 together instead of adding a
watcher that the next round finds unwatched.

**The join does not relabel a pre-upgrade record.** Reclassifying `pending` versus `missing` under a latency rule the
old outcomes were never governed by is a silent restatement of every success rate already reported. Records below the
C1 version boundary keep the label state they were written with.

### C5 — a pooling rule, or a refusal to pool.

Six numbers change silently at the upgrade boundary: the exploration share is diluted by log length rather than
behaviour; the default's propensity drops below 1 so any default-share statistic compares two mechanisms; spend regret
rises because explored decisions are deliberately non-optimal and looks like degradation; `floor_compliance`'s
denominator moves; and old records read as propensity-1 contribute infinite-weight certainty to any weighted estimate.

`policy_version` is recorded, which makes conditioning *available*; nothing uses it. So each criterion either states its
pooling rule or **refuses to pool across a policy version boundary** and says so — the same third verdict `accept`
already has, applied to a mixture rather than to a missing measurement.

## The stop condition

Not a count of fields or findings. Both of these, demonstrated:

1. **A v0.1.0 log and a v0.2.0 log, read by the v0.2.0 reader, each produce a true statement and are not pooled into
   one.** The mutation that tests it: add a field, feed a real v0.1.0 line, and see that nothing raises and nothing is
   silently merged.
2. **A family with no declared labeller cannot be given an exploration rate**, and the failure is at compile time. The
   mutation: delete the labeller from a family that has a rate and watch the compile fail.

Neither is satisfiable by the loss of the thing it counts: the first fails if the reader gets more permissive by
dropping the version check, and the second fails if the rate is made optional.

## The obligation carried forward, as prose

Evidence must not accrue into a cohort while bounds are fixed-sample. Nothing accrues today, and the moment something
does — a re-measure that appends, exploration feeding labels back into a cohort — the margins become anti-conservative
and every certification computed after that point is wrong in a known direction. **Whoever builds accrual owns
anytime-valid bounds as part of that work, not as a follow-up.** This is written as prose rather than as a clause
because a clause implies a test, and a test that cannot fire in this release is the mechanism the next round finds
unwatched.

## Rejected alternatives, with reasons

| Alternative | Rejected because |
|---|---|
| Record the stratum now, use it later | Nothing produces it, so the field collects nothing while making the schema look richer. **F16.** |
| A `features` mapping as the signal slot | Does not buy retro-comparability; wrong shape; wrong time for half its motivation. **F15.** |
| "Refuse if the cohort grew" | A proxy with a hole shaped like its purpose — a rename launders optional stopping. **F10.** |
| Explored assignments are uncertified by construction | Preserves the metric, not the floor. **F8.** |
| A runtime guard for the accrual hazard | First met by the author of the feature it blocks. **F11.** |
| A convention that absent-version means v0.1.0 | Enforced by nobody, and the reader raises before the convention applies. **F18.** Replaced by making the reader tolerant in code. |
| Exploration among admissible candidates only | Cannot reach the arm the ratchet locked out, which is the door's whole purpose. **A7.** |
| Exploration overriding every exclusion | Routes paid traffic through a randomiser whose eligible set nobody can enumerate. **F22.** |
| Adding a watcher for the labeller declaration | A watcher buys the next round the same finding one level up. Replaced by making the omission unrepresentable in the artifact. **F24.** |
