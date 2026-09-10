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

## Interface

Written because phase 3 depends on two workers reading this the same way with no chance to ask. Failure paths are
stated for every entry: a review of the split found that most divergences between a test author and a code author sit
in "what does this return when it cannot do its job", so that is answered here rather than left to whoever gets there
first.

Names are binding. Behaviour not stated here is not contracted, and a worker who needs it stops and asks rather than
choosing.

### C1 — a reader that survives a field being added

**`record.SCHEMA_VERSION: int = 2`** — the version this writer stamps. v0.1.0 records carry no version and are read as
version 1.

**`record.Decision`** gains `schema_version: int`, defaulted to `SCHEMA_VERSION` by the writer. A caller **may not**
pass it: `Decision(schema_version=…)` raises `Incomplete` naming the writer as the owner.

**`record.from_row(row: dict) -> tuple[Decision, list[str]]`** — the only way a logged row becomes a `Decision`.
Returns the decision and the names of keys it ignored.

- A row with no `schema_version` is read as version 1.
- A key the dataclass does not define is **ignored and named** in the returned list. Not an error: this is the whole
  point of the entry.
- A row whose `schema_version` exceeds `SCHEMA_VERSION` raises `Incomplete`, naming both versions. A future shape read
  as if it were this one is the silent-corruption case.
- A row missing a field this version requires raises `Incomplete` naming the field. Absent is not defaulted.

**`accept._as_decision` is replaced by `from_row`.** Every caller goes through it.

**`accept.check_all`** gains a keyword `pool_across_versions: bool = False` — see C5.

**Failure surfaces.** `Log.read` continues to count unreadable *lines*; a row that parses as JSON but fails `from_row`
is a different failure and is counted separately as `__unreadable_rows__`, with the reason, because "the file was
truncated" and "the record is from a newer version" are different operator actions.

### C2 — the policy artifact records the parameters it was compiled under

**`decide.Policy`** gains `parameters: dict`, holding at least `floor: float` and `max_evidence_age_days: float | None`,
plus `staleness_limit_days: float | None` for C3. `as_dict` writes it; `from_dict` reads it.

**`decide.from_dict`** raises `ValueError` naming the absent key when an artifact carries rules but no `parameters`.
An artifact from v0.1.0 is exactly that case, and the message says to recompile — the same stance the prose-only guard
already takes.

**`decide.parameter(policy, name, supplied=None) -> float | None`** — the single reader.

- With `supplied is None`, returns the artifact's value.
- With a `supplied` value **equal** to the artifact's, returns it.
- With a `supplied` value **different** from the artifact's, raises `ValueError` naming both. It does not prefer either.
  A consumer that could prefer one is a second home for the number.
- When the artifact does not carry `name` and a value is supplied, raises `ValueError`: an artifact that did not record
  the parameter cannot confirm one.

**`cli`**: `assign --floor` and `accept --floor` become optional. When given, they are checked against the artifact
through `parameter`, and a mismatch exits **4** with the message on stderr. When absent, the artifact's value is used.
`accept` gains `--policy` so it has an artifact to read; without it, `--floor` is required and the output records that
the floor was operator-supplied and unchecked.

### C4 — the family declares its labeller, and no labeller means no exploration rate

**`schema.json`**, family object: `required` gains `label_source` and `max_label_latency_s`. `label_source` is one of
`executable_check`, `caller_supplied`, `none`. `max_label_latency_s` is a number, or `null` when `label_source` is
`none`.

**`validate`** fails a ledger whose family omits either, naming the family and the field.

**`exploration_rate`** may appear on a family only when `label_source != "none"`. A family with a rate and
`label_source: none` fails `validate` with a message naming both — the omission is a compile failure, not a runtime
discovery.

**`record.classify_label(decided_at, now, max_label_latency_s, label) -> str`** — returns a member of
`record.LABEL_STATES`.

Housed in `record` rather than in `outcomes`, and the correction is worth recording: `outcomes` is the potential-outcome
table — what every tier did on every item, so a policy can be chosen over it. A label's lifecycle is a different
subject, and the module that defines `LABEL_STATES` is the one that decides the transitions between them. Named in the
wrong module in a first draft of this section, and caught before any worker read it.

- A label present returns `labelled`.
- No label and `now - decided_at <= max_label_latency_s` returns `pending`.
- No label and beyond it returns `missing`.
- `max_label_latency_s is None` raises `ValueError`: with no declared latency the distinction is not the join's to make.

**`Log.read` does not reclassify.** A row at `schema_version < 2` keeps the label state it was written with, and
`classify_label` is never applied to it.

### C3 — exploration

**`explore.clears_floor(candidate, floor, *, staleness_limit_days=None, evidence_age_days=None) -> tuple[bool, str]`** —
separate from `admissible` because `admissible` decides expiry before comparing the bound.

- Returns `(False, "no_bound")` when the bound is absent.
- Returns `(False, "below_floor")` when the bound is under the floor.
- Returns `(False, "too_stale_to_explore")` when a limit is declared and the age exceeds it.
- Otherwise `(True, "eligible")`. **Expiry against `max_evidence_age_days` is not consulted**: that is the override.

**`explore.eligible(candidates, *, floor, authorised, latency_feasible, available, staleness_limit_days,
evidence_age_days) -> list[str]`** — candidate ids that may be explored into. A candidate excluded for
`not_authorised`, `latency_infeasible`, `unavailable`, `not_priced` or `no_bound` is **not** eligible. Only expiry is
overridden.

**`explore.draw(deterministic, eligible, rate, rng) -> tuple[str, float, str]`** — the chosen id, its propensity, and
the reason exploration did or did not happen.

- `rate` is 0, or `eligible` has no member other than `deterministic`: returns `(deterministic, 1.0, "no_eligible_arm")`
  or `("…", 1.0, "rate_zero")`. Distinguishable, because `exploration: false` had three causes and one bit.
- Otherwise the alternatives are drawn uniformly with total probability `rate`, so the deterministic arm's propensity is
  `1 - rate` and each of the `k` alternatives has `rate / k`. The returned propensity is **the chosen arm's**, and with
  `rate = 0.05` over one alternative that is `0.95` or `0.05`.
- `rate` outside `[0, 1)` raises `ValueError`. A rate of 1 would leave the deterministic arm propensity 0, which the
  record refuses.

**`record.Decision`** gains `exploration_reason: str` — one of `explored`, `no_eligible_arm`, `rate_zero`,
`no_mechanism`. Version 1 rows read as `no_mechanism`. And `eligible_set: list`, the ids the draw was over, so the
propensity can be checked rather than reconstructed.

**`accept.floor_compliance`** returns **two** rates, `certified` and `all_served`, each with its own bound and verdict.
Its `numbers` gains `served_labelled` and `served_rate`.

### C5 — a pooling rule, or a refusal

**`accept.check_all(..., pool_across_versions: bool = False)`**. When the decisions carry more than one
`schema_version` and `pool_across_versions` is false, **every criterion whose value depends on the mixture** returns
`UNSUPPORTED` with a detail naming the versions present and the count in each. Those criteria are
`floor_compliance`, `default_is_not_a_hiding_place`, `exploration_cost` and `spend_regret`.

`no_false_certification` does **not** refuse: it is a per-decision universal claim, not a rate, so a mixture does not
change what it means.

With `pool_across_versions=True` the criteria compute and every affected verdict's detail says the versions were pooled
on the caller's instruction.

### What no entry does

None of these reads a request's content, produces a stratum, or writes a feature vector. A worker who finds itself
needing any of those has left the contract.

## Amendment 1 — C1's reader stops one level above the field the design expects to grow

Raised by both C1 workers independently, from opposite sides. Each reported the same section as under-specified, and
integrating their work showed one of the three gaps is a defect rather than an ambiguity.

**A1.1 — the ignored-and-named contract applies to a candidate row too.** As implemented, `_candidate_from_row`
filters unknown keys out of a candidate dict **silently**, and its docstring justifies this on the grounds that "the
candidate set has never grown a field since this record existed." Phase 1 falsifies that claim in its own findings:
F12 proposes replacing `bound_n`/`bound_attempted` with an evidence reference, which is a **candidate-level** field.
So the reader that exists to survive the log's evolution does not survive it at the growth site the design already
names, and a candidate carrying an evidence reference would lose it with no counter, no reason and no error — the
silent-corruption class, which this contract admits without debate.

`from_row` therefore reports candidate-level unknown keys in the same `ignored` list, qualified by position
(`candidates[1].evidence_ref`), and a candidate row missing a field the shape requires raises `Incomplete` naming it
rather than a raw `TypeError`.

**A1.2 — `__unreadable_rows__` has a shape.** `{"count": int, "reasons": list[str]}`, one string per row, and a
version refusal's string names **both** the row's version and the reader's. The contract said "with the reason" and
left the shape to two blind readers, which is the interface defect `/split-impl` exists to surface. It reconciled only
because the test author bound loosely on purpose.

**A1.3 — order and fate, stated so they are not each reader's choice.** `from_row` checks the version **before**
validating fields, because a row written to a shape this reader does not know cannot be meaningfully validated against
the shape it does know. A row that fails `from_row` is **excluded** from the returned `decisions`, matching how a
corrupt line is already handled; it exists in `__unreadable_rows__` and nowhere else.

**Not amended: the forward reference to C5.** `pool_across_versions` is named in C1's interface and specified in C5's.
That is deliberate — C1 must add the keyword so C5 does not change a signature every earlier reader depends on — and
the C1 worker is right that it invites a partial implementation. The mitigation is the instruction, not the contract:
C1 accepts the keyword and does nothing with it.

## Amendment 2 — the floor has no declared home, and a global flag cannot be its home

C2's instruction said to find where the floor enters the compile path and carry it through, and not to invent a new
source. The worker searched the whole path — `cli.cmd_compile`, `table.compile_to_file`, `policy.assign_family`,
`config.Objective` — and found that **the floor does not enter it anywhere**. The instruction was unsatisfiable as
written. Checked again here: `grep floor` over `src/tierbook/config.py` and `src/tierbook/schema.json` returns nothing,
and the example ledger's `objective.constraints` carries only `non_inferiority.margin`, which is a relative margin
against a reference and not an absolute floor.

So the finding is larger than the entry. The floor is not a number the compile path lost; it is a number **nothing in
this repository has ever declared**. Every one of its three supply points is a live argument, which is why C2's audit
found zero recorded copies: there was no first copy to record.

**A2.1 — the floor is supplied, not derived, and SCOPE says so.** Section 5's table of things no measurement settles
lists "accuracy floor, per family and per tenant — no measurement says whether 90% or 95% is acceptable," and section 12
names floors among the "genuinely environment-owned rows" of a policy file. A future round proposing to derive the floor
is answered here: the mechanism cannot derive how much accuracy its operator requires, and a derived floor would be the
mechanism grading its own homework. This is not a threshold in the sense the project forbids configuring; it is the
requirement the thresholds are derived *against*.

**A2.2 — the floor is per family, so a global flag is wrong on its face.** Sections 2, 5 and 12 all say "the family's
floor," in those words. `compile --floor` as the worker added it is one number for every family in a ledger, so two
families with different accuracy requirements would silently share whichever was typed. That is a correctness defect,
not a matter of taste, and it is worse than the defect C2 set out to fix: today a mismatch is at least a second typed
number an operator can compare, whereas one flag for two families is a wrong answer with nothing to compare it to.

**A2.3 — the home is the family's declaration in the ledger.** `families` currently maps a family name to a reference
candidate id, a bare string. It becomes an object with `reference` and `floor`, the ledger's `config_format` goes to 2,
and a bare string is refused naming what to change. The reasons, in order of weight: SCOPE already calls floors rows in
a *file*, so a flag was never the contracted shape; the ledger is reviewable and under version control where a shell
history is not; and the floor is per family, which is exactly what the `families` mapping is keyed by.

`compile --floor` is withdrawn. `compile` reads each family's floor from the ledger and `compile_policy` writes it into
`parameters` as before — the rest of C2, which is the part that closes the three-copies defect, is unchanged and stays.

**A2.4 — the seam with C4, recorded rather than discovered at integration.** C4 adds a labeller and a maximum label
latency **per family**, which needs the same `families`-becomes-an-object change. C2 owns the shape change because it
needs it first; C4 appends to the shape C2 creates and does not re-bump `config_format`. Recorded in `SEAMS.md`.

**Not amended: `policy.assign_family`'s argument.** The C2 worker read the entry's reference to "`assign_family`'s
argument" as shorthand for the CLI `assign` verb's `--floor`, on the grounds that `policy.assign_family`'s argument is
named `margin` and is a different quantity. That reading is correct and the original entry's wording was loose. The
three supply points are the CLI `assign`, `serve.route_once`, and `accept`.

## Amendment 3 — two exit codes, and two tests that were green against the defect

**A3.1 — `accept` given neither `--policy` nor `--floor` exits 2.** The mismatch code 4 was in the contract; this
case was not, and it was answered to C2's test author and not to its code author, so one expected 2 and the other
shipped 1. 2 is argparse's own code for an argument that had to be supplied and was not, and that is the operator
action here: supply something. 4 stays reserved for two present numbers that disagree, which is a different action —
one of the two sources is wrong and has to be found. Collapsing them would send an operator looking for a conflict
that does not exist. Recorded as a contract defect rather than a worker error: an interface question answered to one
side of a deliberately blind pair is the coordinator's failure, and answering it once in the contract is the fix.

**A3.2 — a refusal that another refusal already covers is not pinned by a test of its effect.** Two of C2's
tests passed against mutations that removed the behaviour they name.

Disabling the bare-string migration refusal changed nothing observable to the test: a generic shape check downstream
refuses a bare string too, and its message names `reference` and `floor`. So the test's assertions all held against a
loader that had lost the *only* message telling an operator their file was valid yesterday and why it no longer is.
Accepting `config_format: 1` outright was invisible for the mirror reason — the fixture paired format 1 with the old
families shape, which trips both refusals, and the bare-string one names `config_format` in its migration text.

Both are the same shape and it is worth stating as a general obligation rather than two fixes: **when a value is
refused in two places, a test written against the refusal's effect cannot tell which one fired.** Pin the message
that only one of them produces, and build the fixture so that exactly one refusal can apply. Found by mutating each
refusal in turn, which is the check `/split-impl` requires before a phase is called finished and which no amount of
reading would have produced — both tests looked correct, and were, about the wrong thing.

## Amendment 4 — C4 was aimed at the measurement schema, and would have invented a second vocabulary for a concept the schema already has

Found before C4's workers were launched, which is the only cheap moment: an assertion in an interface section is built
on by every worker who reads it. Three checks, each a single file read.

**A4.1 — `schema.json` is the wrong file.** Its title is `tier record` and its `families` block holds `solved`,
`attempted`, `suite` and the evidence pair: *what one tier was measured to do on that family*. `label_source` and
`max_label_latency_s` are policy inputs describing how a **future** request's label will be produced and how long to
wait for one. Putting them there would make an operator's rule a property of a past measurement, let two tiers measured
on the same family declare different labellers with nothing reconciling them, and cross the boundary this repository
already enforces in both directions — `tests/test_boundary.py` refuses a candidate that hand-writes a measurement, and
refuses configuration presented as evidence.

They move to the per-family declaration in `candidates.json` — the object C2 created for the floor. `SEAMS.md` S1
already said C4 appends to that object, and it was right for a reason the interface section had lost.

**A4.2 — `validate` is therefore the wrong verb.** `cmd_validate` reads the tier registry and never opens the config.
The refusal belongs in `load_config`, beside C2's, and reaches an operator through whichever command loads the config.

**A4.3 — the enum already exists, in a stronger form.** The tier record's `oracle.kind` names what decided an outcome
with seven values ordered from strongest to weakest, from `executable_acceptance` to `model_judge`. C4's proposed
`executable_check | caller_supplied | none` is a third, coarser vocabulary for the same concept, sitting beside it with
no mapping between them. The declaration takes `oracle.kind`'s enum, extended by exactly one value — `none`, meaning no
labeller for online traffic, which is a state a measurement record has no reason to express.

**A4.4 — and the coarse enum silently drops a gate the offline path has.** `oracle.independent_of_candidate` exists
because "a standard produced by a model that is also a candidate scores that candidate perfectly by construction," in
the schema's own words. A three-value `label_source` cannot express that, so the online path would be able to declare a
judge that is also a candidate in the family — and exploration exists to generate evidence, which a candidate grading
itself is not. The declaration carries `independent_of_candidate`, and a family whose labeller is not independent of one
of its own candidates cannot have an exploration rate. That is the same mechanical refusal C4 already specifies for a
missing labeller, applied to the second way the label can fail to mean anything, rather than a new mechanism.

### C4's interface, replacing the section above

**`config.FamilyDeclaration`** gains `label_source: str`, `max_label_latency_s: float | None`, and
`label_independent_of_candidate: bool`. `load_config` refuses a family that omits any of them, naming the family and
the field. This is `config_format` 2's shape, set by C2 and appended to here without a second bump — S1.

`label_source` is one of `oracle.kind`'s seven values or `none`. The reader takes the enum **from the schema file** so
the two cannot drift; a hardcoded copy is the duplication this amendment exists to remove.

`max_label_latency_s` is a number, or `null` exactly when `label_source` is `none`. A number with `none`, or `null`
with anything else, is refused naming both.

`label_independent_of_candidate` is a boolean and has no default. `false` is a legitimate declaration — an operator may
be running a judge that is also a candidate and should be able to say so — and it costs the family its exploration rate.

**`exploration_rate`** may appear on a family only when `label_source != "none"` **and**
`label_independent_of_candidate` is true. Otherwise `load_config` refuses, naming both the rate and the reason. The
artifact cannot represent the combination, so the omission is a load failure and not a runtime discovery.

**`record.classify_label(decided_at, now, max_label_latency_s, label) -> str`** — unchanged from the section above,
including the `ValueError` on `max_label_latency_s is None` and `Log.read` not reclassifying a row below
`schema_version` 2.

## Amendment 5 — the staleness limit repeats the floor's mistake, and C3's two new record fields collide with C1's reader

Both found before C3's workers were launched, by re-deriving the numbers the entry carries rather than trusting the
entry's prose. The first is amendment 2's defect in a second value; the second is a seam between two entries that are
each individually correct.

**A5.1 — `staleness_limit_days` has no declared source, exactly as the floor had none.** C2 carries it in
`Policy.parameters` and `compile_policy` takes it as an argument, and `decide.py`'s own comment says it "has no source
yet -- C3's". So a C3 worker told the limit is "declared per family and recorded in the artifact under C2" would go
looking for the declaration, not find one, and invent a supply point — which is precisely what C2's worker did with
`compile --floor`, and why amendment 2 exists. Saying it once here is cheaper than the same amendment twice.

The limit is per family for the same reason the floor is: it is how stale a bound an operator will accept for *this*
family's traffic, which no measurement settles. So it is a fourth append to the object C2 created and C4 extended —
`SEAMS.md` S1 — and `compile` threads it into `parameters` the way it already threads the floor.

**`config.FamilyDeclaration`** gains `staleness_limit_days: float | None`. Refused when absent, like C4's three;
`null` is a legitimate declaration meaning no limit, and it is refused **in combination with an `exploration_rate`**,
because the door C3 opens exists to reach a candidate whose evidence expired, so an unbounded staleness there is a
bound from any past environment at all. A family may decline to state a limit or may explore, not both.

**A5.2 — `exploration_reason` cannot be a required field, and must not be an optional one either.** C1's `from_row`
raises `Incomplete` naming any field the row lacks that the dataclass declares without a default. `Decision` has
sixteen such fields today. So `exploration_reason` added without a default refuses **every v0.1.0 row**, which is the
exact failure C1 was built to remove — reintroduced by the next entry, one release later, in the same object.

Given a default of `no_mechanism` it reads correctly for a version 1 row and **wrongly** for a version 2 row that
omits it: a v0.2.0 writer that forgot to stamp the reason would be read as a mechanism that was never installed, and
the count of decisions with no exploration mechanism is a number this release reports.

**Resolved by making the version decide, not the default:** `from_row` supplies `no_mechanism` for
`schema_version == 1` and raises `Incomplete` naming the field for `schema_version >= 2`. Recorded as `SEAMS.md` S4,
because it is a rule about the boundary between C1's reader and C3's writer and belongs to neither alone. The same
treatment applies to `eligible_set`, whose version 1 value is the empty list.

This is the shape `/review-contract` calls making the omission unrepresentable rather than watched: a v2 writer that
forgets the field fails at read time, loudly, instead of the forgotten value being indistinguishable from a real one.

## Amendment 6 — exploration through the expiry override does not claim the floor, and SCOPE was one clause short

Found by C3's code author, reported rather than worked around, and reproduced here before deciding anything:

```
clears_floor (explore): (True, 'eligible')
admissible (record)   : (False, 'evidence_expired')
check_certification   : ["certified but the chosen candidate 'box' was not admissible: evidence_expired"]
```

The falsifier fires on the exact case C3 exists to create. SCOPE section 12 calls that signal *the mechanism is
broken, not mistuned*, so this is the most consequential finding in the release and it is not a bug in either worker's
code.

**A6.1 — the root cause is in the governing document, not the contract.** SCOPE section 2 listed admissibility as
three conditions. `record.admissible` has enforced four since v0.1.0, freshness among them, added because
`evidence_expired` sat in the exclusion vocabulary with nothing able to produce it. So the document said three and the
code did four, and a worker told an explored assignment "is certified when the rest of admissibility holds" read *the
rest* as everything except freshness — reasonably, because section 2 is what admissibility means. SCOPE section 2 now
carries the fourth clause, and says that it was implemented before it was written and what the omission cost.

**A6.2 — an arm reached through the override is served uncertified.** Its bound clears the floor and the evidence
behind that bound is past the family's limit, so the bound describes a past environment and cannot support a claim
about this request. `serve.route_once` decides `certified` from full admissibility, freshness included — never from
`explore.eligible`'s verdict, which answers a different question: who may be drawn, not whether the floor is claimed.

This does not reopen F8. F8's objection to "uncertified by construction" was that it removes traffic from
`floor_compliance`'s denominator, and C3 already answers that by reporting **two** rates. The traffic appears in
`all_served`. What F8 forbids is certification following from *why* an arm was selected; what this requires is
certification following from whether the arm was admissible, which is the same rule applied to every assignment.

And the door still does its work: the request is served by the arm, the label comes back, the evidence refreshes, and
the arm becomes admissible again. That was the point of opening it — assumption A3's ratchet was that an arm never
chosen is never labelled. Serving it uncertified breaks the ratchet. Certifying it was never necessary.

**A6.3 — `check_certification` needs the two limits kept apart.** It compares evidence age against
`max_evidence_age_days` and must keep doing so; nothing about it changes. What changes is that `route_once` stops
recording `certified=True` for the case it would flag. The falsifier was right and is left alone — a falsifier
adjusted to stop reporting a real inconsistency is a falsifier that has been switched off.

**A6.4 — the two ambiguities C3's workers each reported independently, settled.**

`rate_zero` takes precedence over `no_eligible_arm` when both hold. With a rate of zero the eligible set is never
consulted, so reporting `no_eligible_arm` would report on a code path that did not run. Both workers chose this
independently; it is recorded so the next reader does not have to.

`floor_compliance` stays **one** verdict, not two. SCOPE section 12 defines nine criteria and splitting one into two
would put `accept.CRITERIA` at ten, diverging from the governing document over a presentation choice. The two rates,
their two bounds and their two sub-verdicts live in `numbers`, and the criterion's own verdict is the worse of the two:
a criterion that passed while its all-served half failed would be the defeat F8 describes, reintroduced through the
report instead of through the definition.

## Amendment 7 — C6, because the falsifier can miss the violation it exists to catch

Found by C3's code author as a third interaction, reported rather than worked around, and the reproduction turned out
larger than the report. This is admitted without debate under pass 1: the artifact's reason for existing is defeated.

`accept.py` contains no `evidence_age_days` and no `max_age_days` anywhere. So
`accept.default_is_not_a_hiding_place` and `accept.no_false_certification` have called `record.check_certification`
with freshness absent since v0.1.0, in which release `record.admissible` gained freshness as its fourth condition.
The criterion has been blind to it ever since.

Threading the value through would not fix it. `check_certification` builds one `kw` dict and applies **one**
`evidence_age_days` to **every** candidate in the decision, while each candidate carries its own `evidence_as_of` — and
tiers are measured at different times, so differing dates are the normal case, not an edge one. Measured on one
decision holding a 617-day-old candidate and a 9-day-old one:

| scalar age supplied | what the falsifier reports | what is true |
|---|---|---|
| 400 days | **nothing** | the 9-day candidate was admissible and the default hid behind it |
| 5 days | **both** candidates | only the 9-day one; the 617-day one was expired |

Both directions are wrong and no scalar produces the right answer, because the two ages differ by 608 days. A
falsifier that can report **nothing** where a real hiding place exists is worse than an absent one, since SCOPE
section 12 reads its silence as evidence.

### C6 — the falsifier reads the age it already holds

**`record.check_certification`** loses `evidence_age_days`. Each candidate's age is derived from its own
`evidence_as_of` against the decision's `decided_at`, both already in the record. This removes a parameter rather than
threading one through four signatures, and it fixes the one-age-for-many defect at the same time — a scalar cannot be
correct for a set whose members differ.

**The reference is `decided_at`, not the time the check runs.** The question is whether the evidence was fresh *when
the decision was made*. Re-evaluating against the clock at accept time would make a verdict drift as the file ages,
which is the defect C4 already refuses for label states: a criterion whose answer changes because the file got older
is not a criterion.

**`EXCLUSION_REASONS`** gains `no_evidence_date`. `Candidate.evidence_as_of` defaults to the empty string, so an
undated candidate is representable, and with a limit declared there are only wrong alternatives: `evidence_expired`
asserts an age the record does not carry, and admitting it silently skips freshness — the v0.1.0 defect, restored.
An undated bound cannot be certified against a declared limit, and the reason says which of the two it is.

**`accept.no_false_certification`, `accept.default_is_not_a_hiding_place` and `accept.check_all`** gain
`max_age_days: float | None = None`. Unlike the age, the limit is not in the record: it is the family's declared
policy input, so it comes from outside — and from exactly one place. **`cmd_accept` reads it from the policy artifact
through `decide.parameter`**, the same rule amendment 2 established for the floor. No new CLI flag: a second typed
number is the defect amendment 2 exists to close, and adding one here would reopen it in a second value.

**With `max_age_days` absent the condition is absent, not satisfied** — as with the latency constraint, and as SCOPE
section 2's clause 4 now says. A criterion run without a policy is honest about having checked three conditions rather
than claiming four.

### C6's interface, and the copy it must not become

**`observe.evidence_age_days(measured_on, now=None) -> float` already exists** and already does this arithmetic:
`date.fromisoformat`, UTC midnight, `(now - then) / 86400`, and a refusal naming the bad value when the string is not
an ISO date. `check_certification` calls it rather than repeating it. A third copy of the same three lines is the
duplicated-knowledge class every other entry in this release closed, and the drift it invites is a criterion and a
collector disagreeing about how old the same evidence is.

**`record.check_certification(decision, *, floor, latency_feasible, max_age_days=None)`** — `evidence_age_days` is
gone from the signature. Per candidate: `observe.evidence_age_days(candidate.evidence_as_of, now=decision.decided_at)`.
An empty `evidence_as_of` is not passed to it; that candidate is `no_evidence_date` when a limit is declared, and the
condition is absent when none is.

The import direction is worth a check before writing: `record` importing `observe` must not create a cycle. If it
does, the shared arithmetic moves to whichever module both can import, and the move is reported — not resolved by
copying the three lines.

**`accept.no_false_certification`, `accept.default_is_not_a_hiding_place`, `accept.check_all`** gain
`max_age_days: float | None = None` and pass it down. **`cli.cmd_accept`** reads it through
`decide.parameter(policy, "max_evidence_age_days", None)` — the artifact's own value, no flag, no second copy.

**`record.EXCLUSION_REASONS`** gains `no_evidence_date`. C1's `from_row` reads a version 1 row whose candidate carries
an exclusion reason from the old, shorter vocabulary, so the tuple only ever grows: removing a value would make a
v0.1.0 log unreadable, which is the failure C1 exists to prevent.
