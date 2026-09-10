# Phase 1 — the design for v0.2.0, its assumptions, and the findings that go to triage

This is the phase-1 output: a design statement, the assumption table, and a list of design-level findings. **It does
not decide the scope.** Deciding what will and will not change is phase 2's job, and the first draft of this document
conflated the two — it merged the review findings straight into a revised scope, which is convergence wearing
divergence's clothes. That draft is kept as `design-draft1.md`.

## 1. The design statement

### What this exists to do, and who operates it

v0.2.0 makes the mechanism able to learn from its own log. v0.1.0 produced one turn — observe, decide, record, check —
in a form that cannot answer the question SCOPE section 9 exists for: *would another choice have been better*. Two
things stand between the log and that question, and both are mechanism rather than analysis.

Operated by whoever runs the routing layer. Read by whoever later asks the log a counterfactual question, who is not the
same person and will not be able to ask the author what a field meant.

### The responsibilities, and which layer owns each

| Value | Owner | Why not elsewhere |
|---|---|---|
| The state a decision is made from | `observe` | Already so. The one collector that exists. |
| Which candidate is chosen deterministically | `decide` | Already so. |
| **Whether this request is explored, and into which arm** | a new randomiser, above `decide` | It must know what `decide` would have chosen, so it cannot live inside `decide`; and it must be the only place a draw happens, or two draws make the propensity unreconstructible. |
| **The propensity of the arm that was chosen** | the same randomiser | It is the only component that knows the eligible set and the draw. A caller computing it would be computing a second copy of the mechanism. |
| **What produces a label, and how long to wait for one** | the family's declaration in the ledger | SCOPE section 2: the label's source and maximum latency are declared *per family*. Not the caller's — a caller that decides when a label is late decides the success rate. |
| **Whether a label is late or absent** | the outcome join, reading that declaration | Today nothing decides it and the record's three-way label state is settled by whoever looks. |
| The identity of the evidence a bound came from | the compiler | It computed the bound. Routing cannot reconstruct which observations, exclusions or weighting produced one. |
| The record's schema version | the record's writer | The component that serialises knows what shape it wrote. A caller passing it in is a second copy of that knowledge. |

### The contracts at each boundary, failure included

**randomiser → `decide`.** The randomiser may assume `decide` is a pure function of state. It must not assume `decide`'s
choice is admissible. On a state where `decide` falls to the default, exploration still applies — the default is a
choice like any other, and excluding it from randomisation would fix the default's propensity at 1 forever.

**randomiser → record.** The record may assume the propensity is the conditional probability of the arm actually
chosen, under the draw actually performed, with the eligible set recorded beside it. On failure — an empty eligible set
— the randomiser does not draw and the decision is the deterministic one, recorded with `exploration: false` and
propensity 1. Silence here would look identical to a policy that chose not to explore.

**outcome join → the family declaration.** The join may assume a labeller and a maximum label latency are declared. On
their absence it must **refuse to classify** rather than choose a default: a label declared late by a rule nobody wrote
is a success rate nobody can defend.

**compiler → routing.** Routing may assume a bound cites an evidence artifact that exists and matches. On mismatch the
compiler refuses to certify. It may not assume the artifact is unchanged because its row count is unchanged.

## 2. The assumption table

| # | Assumption | Load-bearing | How it was checked | Result |
|---|---|---|---|---|
| A1 | The decision record is versioned, so a field added later is distinguishable from one whose value was absent | no — see F13 | read `Decision`'s fields; read what `schema.json` covers | **FALSE.** No `schema_version`. `schema.json` is titled *tier record* and constrains the ledger, not the decision log, which nothing validates |
| A2 | Bounds are recomputed as evidence accrues, so fixed-sample margins are *actively* anti-conservative | yes, for whether bounds belong in this release | looked for an accrual path; read `evidence.py` | **FALSE TODAY.** `trials_per_item` must be 1 and a cohort is fixed before any run. Latent, not active |
| A3 | Deferring exploration costs only the data collected in between | **yes** | ran `admissible` on a candidate whose evidence ages while it is never chosen | **FALSE.** A one-way door: `age 30d → True`, `age 91d → False (evidence_expired)` *regardless of a 0.95 bound*. Not chosen ⇒ not labelled ⇒ expired ⇒ cannot be chosen |
| A4 | Recording a field now, unused, preserves the ability to use it later | **yes**, for the stratum and consequence proposals | asked what would *produce* the value in this release | **FALSE.** Nothing produces a stratum here, so the field is present-and-absent: it distinguishes schema versions and loses the data anyway |
| A5 | A decide-time signal slot lets a later signal be compared against earlier decisions | yes, for the slot | asked when each intended occupant exists | **FALSE twice.** Old events lack the measurement whatever the slot; and an answer-token margin exists only *after* generation, so a decide-time field is the wrong home for it |
| A6 | The family declaration carries a labeller and a maximum label latency | **yes**, for the outcome join | read a family block and the schema's `required` | **FALSE.** Family requires only `solved`, `attempted`, `suite`. SCOPE section 2 requires the label's source and maximum latency per family; neither the record nor the schema carries them |
| A7 | A candidate whose evidence expired still has a bound that clears the floor, so exploration can reach it | **yes**, for opening the door | read `admissible`'s ordering: `no_bound → evidence_expired → below_floor → …` | **TRUE**, and the ordering matters: expiry is decided *before* the bound is compared, so a separate `clears_floor` predicate is needed rather than reusing `admissible` |

A3 is the release's centre. One review sharpened what is lost, and the sharpening is the point: it is not log lines at a
constant rate but **the counterfactual arm's behaviour in the interim environment, and that environment will not exist
later.** Under the mechanism's own premise that environments move, "would the alternative have been better last quarter"
is permanently unidentified for every quarter before exploration ships.

The freshness check that creates the door is mine, added in v0.1.0 because a review correctly noted `evidence_expired`
sat in the vocabulary with nothing able to produce it. Adding it was right; it made the ratchet real.

## 3. Design-level findings, for phase 2 to triage

Numbered so the contract can accept or reject each by name. **None is decided here.**

### Class D — ordering and load-bearing position

**F1. A rule appended to a policy changes what every earlier propensity meant.** `decide` returns the first matching
rule and exploration draws from the eligible set that policy defines. Append a rule and the eligible set changes, so a
propensity recorded under the old policy is not comparable with one recorded under the new. `policy_version` is already
recorded, which makes the condition *available*; nothing states the pooling rule that uses it.

**F2. Two random draws would make the propensity unreconstructible.** If exploration draws and a retry policy also
draws, the recorded propensity is one factor of the true one. Nothing today forbids a second draw.

### Class G — duplicated knowledge

**F3. The floor is supplied twice and nothing compares the copies.** `assign_family` takes it, `accept --floor` takes it
from a human, and exploration eligibility needs it. A criterion computed against a floor different from the one the
policy used is a silent wrong answer, and today that is one CLI flag away.

**F4. `max_age_days` exists in two places** — the compiler's default and `admissible`'s argument — and the ratchet in A3
is exactly what that number controls.

**F5. The exploration rate must have one home.** The policy artifact, the CLI and the record are three candidates; the
record's realised propensity is a *different quantity* and must not be mistaken for a copy of the rate.

### Class H — capability claimed but not declared

**F6. The ledger declares a capability SCOPE requires and the schema does not carry** (A6). An outcome join cannot decide
`pending` versus `missing` without a declared maximum label latency, and that is the distinction the record's three-way
label state exists for.

**F7. `attach_outcome` exists and nothing calls it.** The mechanism advertises a labelled log and supplies no producer of
labels. Exploration on top of this yields randomised assignments nobody can learn from.

### From the review rounds, on the first draft's proposals

**F8. "Explored assignments are uncertified by construction" preserves the metric, not the floor.** Certification says
whether an action clears the floor; exploration says why it was selected. Conflating them permits serving below the floor
and then removing that traffic from `floor_compliance`'s denominator.

**F9. The first draft's propensity example was arithmetically wrong.** Two arms with 5% exploration spread over both
gives 0.975 and 0.025; exploration always taking the alternative gives 0.95 and 0.05. The draft said 0.95 and 0.025,
which needs three arms. The error is the argument for specifying the randomisation before implementing it.

**F10. "Refuse if the cohort grew" is a proxy with a hole shaped like its purpose.** A 24-item cohort can change
completely and stay 24; and an operator hitting the refusal can freeze the evidence under a new cohort name and
recompute — optional stopping laundered through a rename.

**F11. A guard that cannot fire in the release that adds it will first be met by the author of the feature it blocks**,
who is the person most motivated to delete it. A dependency stated in the accrual feature's scope is enforceable where a
runtime refusal is not.

**F12. `bound_n`/`bound_attempted` encode one binomial layout rather than a bound's provenance**, and cannot reproduce a
bound computed with weights, clusters or stratification. They are also reconstructible from the ledger via `family` +
`evidence_as_of`, so they are convenience rather than rescue.

**F13. `schema_version` is cheap insurance, not rescue.** An absent version is readable as v0.1.0, whose shape is fixed.
What the field prevents is a *second* unversioned shape.

**F14. The purpose's central clause stays deferred.** After v0.2.0 nothing produces a per-request signal about the work.
One review held that a crude versioned stratum producer was within reach and that not building it is unjustified.

**F15. `features` as a mapping is a junk drawer** that will accumulate incompatible meanings and missingness conventions,
and cannot express provenance, units, extractor identity, observation time or per-value missingness.

**F16. The stratum needs a versioned classifier, not a caller label.** An unversioned caller-supplied stratum creates
false comparability, which is worse than absence.

**F17. Exploration without a dependable outcome join does not generate evidence**, so R-ordering that puts exploration
before the join produces a log of randomised assignments nobody can learn from.

## 4. Refusing to proceed on one point

A6 cannot be worked around by the outcome join. Either the family declaration gains a labeller and a maximum label
latency — a schema change to the ledger — or the join must refuse to classify and v0.2.0 ships an outcome path that
cannot say whether a label is late. Phase 2 has to choose, and choosing the second **silently** is the failure mode.
