# v0.2.0: settle what cannot be retrofitted, then stop wasting the log

## What this exists to do

Decide the v0.2.0 scope by cost of deferral, not by value. Two costs are being distinguished and they were being
conflated:

- **Irreversible.** A field absent from a record today cannot be told apart later from a field whose value was absent.
  Every day of logging makes the retrofit less possible, and at some point it is simply not.
- **Recurring.** The mechanism works and the data it collects cannot answer a question it will be asked. Adding the
  capability later costs nothing structurally; what is lost is the data in between.

The instruction was "start with what is hard to change later", which is the first kind. An early draft of this
document put the record first and exploration third on the grounds that the record already has room for exploration.
That was wrong, and the assumption table below shows the check that reversed it.

## The assumptions, all checked before the scope was written

| assumption | load-bearing for | how it was checked | result |
|---|---|---|---|
| The decision record is versioned, so fields can be added without ambiguity | everything in S1 | read `Decision`'s fields; read what `schema.json` covers | **FALSE.** No `schema_version` on a decision. `schema.json` is titled *tier record* and constrains the measurement ledger, not the decision log, and nothing validates a decision record at all |
| A bound's sample size is available to be recorded beside it | S1's third item | read a family block in `examples/ledger/tiers` | **TRUE.** `solved: 16, attempted: 20` is already in the ledger. Recording it on `Candidate` is plumbing, not a new measurement |
| Bounds are recomputed as evidence accrues, which is what makes a fixed-sample margin actively anti-conservative | S2 | looked for an accrual path; read `evidence.py` | **FALSE TODAY.** `trials_per_item` must be 1 and a cohort is fixed before any run, so a bound is computed once per cohort. The defect is *latent* and becomes active on the first re-measure |
| Exploration requires a change to the record | the ORDER of S1 against S3 | read `Decision`'s fields | **FALSE.** `selection_probability` and `exploration` already exist. Exploration is not schema-expensive |
| Deferring exploration costs only the data collected in between | the whole S1-before-S3 argument | ran `admissible` against a candidate whose evidence ages while it is never chosen | **FALSE, and this reversed the ordering.** See below |

**The check that changed the answer.** Deterministic routing plus a freshness limit is a **one-way door**, and the door
was installed in v0.1.0:

    age  30d  bound 0.95 vs floor 0.80 -> admissible=True
    age  89d  bound 0.95 vs floor 0.80 -> admissible=True
    age  91d  bound 0.95 vs floor 0.80 -> admissible=False (evidence_expired)
    age 365d  bound 0.95 vs floor 0.80 -> admissible=False (evidence_expired)

A candidate the policy routes away from stops receiving labels. Its evidence ages. Past the limit it is inadmissible
**regardless of its bound** — so it cannot be chosen, so it cannot be refreshed. A candidate that loses once loses
permanently, and its 0.95 bound is irrelevant after ninety days.

The freshness check in `admissible` is mine, added in v0.1.0 in response to a review that correctly pointed out
`evidence_expired` sat in the vocabulary with nothing able to produce it. Adding it was right and it made the ratchet
real: before it, a stale bound still competed. So **v0.1.0 introduced a lock-in that only exploration opens**, and the
labels not collected for the unchosen arm during the deterministic period do not exist and cannot be back-filled.

That is irreversible in the same sense S1 is, and it is why the ordering below is not the one this document first
argued for.

## The scope

### S0 — exploration with logged propensities. Irreversible, and active since v0.1.0.

Promoted from third to first by the check above. It was described here as a recurring cost and it is a ratchet.

Three things are lost and only the first is recoverable:

- **The off-policy estimate.** Every decision at propensity 1 leaves the counterfactual arm with no data, so
  `accept.spend_regret` reports `unsupported` and will keep doing so. Recoverable in the sense that a later log with
  varying propensities answers the question for the period it covers.
- **The labels for the unchosen arm during the deterministic period.** Not recoverable. They were never produced.
- **The unchosen arm's admissibility, permanently, once its evidence expires.** Not recoverable without a re-measure
  outside the loop, which is precisely the thing the mechanism is supposed to make unnecessary.

Two design decisions it forces, stated here rather than discovered in implementation:

- **An explored assignment is uncertified by construction.** It goes to a candidate the policy would not have chosen,
  whose bound may not clear the floor, so the floor is not claimed for it. `accept.floor_compliance` already computes
  over certified decisions only, so exploration does not contaminate the floor — a property of the existing design
  rather than something being added.
- **The propensity is the probability of the arm that was chosen, under the randomisation actually used.** Not a
  nominal rate. Exploring 5% over two arms makes the chosen arm's propensity 0.95 or 0.025 depending on which it was,
  and recording 0.05 would make every estimate wrong by a factor.

**And a third that the ratchet forces, which a naive exploration design would miss.** Exploration has to be able to
reach a candidate whose evidence has **expired**, or it cannot open the door it exists to open. A design that explores
only among admissible candidates is a design that cannot rescue the arm it locked out. So the exploration arm is drawn
from the candidates the policy *names*, not from the ones currently admissible, and an assignment to an expired
candidate is uncertified and labelled as exploration — which is exactly what the record already distinguishes.

### S1 — version and complete the decision record. Irreversible if deferred.

Four additions, each of which cannot be reconstructed from a log written without it.

**`schema_version` on every decision.** Without it, a v0.1.0 record that lacks `stratum` is indistinguishable from a
v0.2.0 record whose stratum was unknown. With it, the first is a different schema and the second is a gap. This is the
whole reason the rest of S1 depends on it: a one-line field whose absence makes every other addition ambiguous
forever.

**The bound's sample size, on `Candidate`.** A bound over 4 items and a bound over 24 are the same number today, and a
reader cannot tell them apart. swe-router's discipline, and the ledger already carries `solved`/`attempted`, so this is
plumbing. Recorded as `bound_n` and `bound_attempted` rather than a rate, because the pair is what a later reader needs
and a rate discards it.

**A stratum and a consequence class.** swe-router's second device: what happens if this is wrong sets the floor, and how
hard the work is selects which measured bound to compare against it. Neither can be recovered from a log that did not
record them — a request's difficulty is not in its outcome. Recorded here **without** being used to decide anything,
because the per-stratum bounds do not exist yet: the pilot subset is 24 items with one permanently unscoreable and will
not carry four strata. So this release records the field and the decision ignores it.

That split is deliberate and worth stating plainly: **a field recorded and unused is cheap; a field wanted and
unrecorded is impossible.** The alternative — waiting until the strata can be bounded — throws away every log line
written in between.

**A signal slot: the versioned feature vector section 9 asks for.** Today `feature_vector_version` versions a vector
nobody records. That is the slot a per-request signal lands in, and the two candidates named in `docs/issues/` are
exactly that shape: a hidden-state probe, and an answer-token margin. Recording `features` as a named mapping with its
version means a signal introduced later can be compared against decisions made before it existed, which a log without
the slot cannot support.

`accept` gains nothing from S1 by itself. That is expected: S1 buys the ability to ask questions later, and a release
whose value is entirely in the future has to say so rather than dress it up.

### S2 — refuse the claim a latent defect would make wrong. Cheap now, prevents a wrong claim later.

The margins are fixed-sample. Recomputing a bound as evidence accrues and admitting at a data-dependent stopping time
makes them anti-conservative, which is one of the six gaps. The check above found that nothing accrues today, so the
defect is latent.

The fix is not anytime-valid bounds. It is a **refusal**: the compiler declines to certify against a cohort that has
grown since the bound it is reading was computed, and names anytime-valid bounds as what would lift the refusal.

That keeps the ordering honest. Implementing anytime-valid bounds is a real piece of statistics and does not belong in a
release whose theme is "record what cannot be retrofitted". Refusing the claim costs a comparison and means no
certification made in the interim is anti-conservative.

## Out of scope, with the reason

| Not in v0.2.0 | Why |
|---|---|
| Anytime-valid bounds | S2 makes waiting safe. Doing the statistics belongs in a release about bounds. |
| Change-point detection | A policy expires by age today. Additive later, and nothing about it is foreclosed by a log that lacks it. |
| A value for the reserved candidate's scarce capacity | It changes the objective, and the objective is not what this release touches. |
| The hidden-state measurement itself | `docs/issues/hidden-state-signal-from-the-box.md`. Needs GPU and a J-lens that may not survive an MoE. **The slot it would use is S1.** |
| Deriving the tie band | `docs/issues/adopt-the-four-devices-from-swe-router.md`. A computation over recorded cohorts, not a schema change. **Its provenance field is S1.** |
| Using the stratum to decide | The per-stratum bounds do not exist. Recording it is S1; deciding from it needs a cohort that can carry four strata. |
| A bandit, a scheduler, or any policy that learns from the log | S0 makes the log *able* to support that later. Doing both at once would mean a release where nothing can be attributed, since the exploration and the learning would move together. |

## The contracts this changes

**`record.Decision` → its readers.** A record gains a version and four fields. `accept` must read a record whose
version it does not know and say so rather than computing over it — a criterion evaluated across two schema versions is
a criterion over a mixture nobody described.

**`serve.route_once` → its caller.** The caller supplies the stratum, the consequence class and the features, or they
are absent with a reason. Same rule as the collector: absent with a reason, never defaulted. A fabricated stratum is
worse than none because it aggregates.

**The compiler → the ledger.** S2 adds a precondition: the cohort a bound was computed over must not have grown. On
failure the compiler refuses to certify rather than emitting a bound it cannot stand behind.

## What would prove this scope wrong

If `schema_version` turns out not to be enough — if a reader needs to distinguish more than "which shape is this" —
then S1 is under-built and the retrofit problem returns. The check: write a v0.1.0 record and a v0.2.0 record, hand both
to `accept`, and see whether it can say something true about each without treating them as one population.
