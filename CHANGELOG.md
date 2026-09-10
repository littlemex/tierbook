# Changelog

## 0.2.0

**The log survives its own evolution, and exploration is specified and drawn from.** A reader can now add a field
without breaking every older line that lacks it, and a family that declares an exploration rate draws randomly among
the candidates whose bound clears its floor rather than always taking the deterministic arm.

The loop still does not close. No arc runs from `record` or `accept`'s report back to `decide` -- nothing here learns.
What changed is which part is missing: exploration now produces logged propensities that vary, so `spend_regret`'s
blocker is the estimator rather than the data, not the absence of a randomised design to estimate from. A family
declares a labeller and a maximum label latency, and `Log.attach_outcome` still exists and nothing calls it -- labels
are declared, not collected.

### Breaking changes

**`config_format` 1 -> 2.** `families` stops being a bare string mapping a family to its reference candidate and
becomes an object carrying `reference` and `floor`, because the floor and (later) the labeller are per-family
declarations with nowhere else to live. A holder of a format-1 file gets one refusal, at the first load, naming every
problem across every family at once rather than the first of several -- `load_config` used to raise on the first
family it met and stop, which measured as five sequential failures on this project's own shipped v0.1.0 file, one
problem discovered per load. Migrating that file now takes **two** loads: the operator reads one message naming
everything wrong, fixes all of it, and loads again.

**The decision record's `schema_version` 1 -> 2.** A line with no `schema_version` is read as version 1, silently and
without error -- `record.from_row` reads this project's own `v0.1.0` decision log with nothing raised and nothing
ignored. A v0.1.0 decision log takes no migration at all. The two breaking changes read oppositely on purpose: the
config format is validated in full because both shapes are known and the difference between them is exactly what an
operator needs told; a decision log's older rows are read as what they always were, because nothing about a past
decision needs to change to be read by a newer tool.

### Added

**A family declares its own floor, labeller, label latency, labeller independence and staleness limit -- all five per
family, none of them global.** The floor was never declared anywhere in this repository before this release, and a
`compile --floor` flag was built and withdrawn before shipping once the audit noticed it would be one number shared by
every family in a ledger: two families with different accuracy requirements would silently share whichever number was
typed, which is worse than the defect the flag existed to fix. All five now live in the same per-family object
`config_format: 2` created for the floor: `label_source` (one of `oracle.kind`'s seven values, or `none`), taken from
the schema file rather than copied so the two enums cannot drift; `max_label_latency_s`; `label_independent_of_candidate`,
because a judge that is also a candidate in its own family scores that candidate perfectly by construction; and
`staleness_limit_days`, for the same reason the floor is per family -- how stale a bound an operator will accept for
*this* family's traffic is not something any measurement settles. `exploration_rate` may appear on a family only when
`label_source != "none"` **and** `label_independent_of_candidate` is true; otherwise `load_config` refuses, naming
both the rate and the reason, because a family whose label cannot mean anything cannot be given a mechanism that learns
from one. The refusal is a load failure, not a runtime discovery.

**The policy artifact records the parameters it was compiled under.** `decide.Policy` gains `parameters`: `floor`,
`max_evidence_age_days`, `staleness_limit_days`. Before this, the compiled artifact carried `certified: true` and not
the floor it was certified against -- three supply points (`assign`, `route_once`, `accept`) and zero recorded copies,
so no criterion computed over a log could be known to have used the policy's own floor. `decide.parameter(policy,
name, supplied=None)` is the single reader: with nothing supplied it returns the artifact's value; with a supplied
value equal to the artifact's it returns it; with a different one it raises, naming both, rather than preferring
either. `assign --floor` and `accept --floor` are now optional -- given, they are checked against the artifact and a
mismatch exits **4**; absent, the artifact's value is used; `accept` gains `--policy`, and given neither `--policy` nor
`--floor` it exits **2**, argparse's own code for an argument that had to be supplied and was not.

**Exploration: the eligible set, the draw and the recorded propensity, each pinned before being implemented.** A
candidate is eligible for exploration when its bound clears the floor even if its evidence has expired -- the door
exists to reach a candidate the freshness ratchet would otherwise lock out forever, since an arm never chosen is never
labelled -- but every other exclusion (`not_authorised`, `latency_infeasible`, `unavailable`, `not_priced`, `no_bound`)
still applies; a review declined to route paid traffic through a randomiser whose eligible set it could not enumerate.
One draw happens per decision. The recorded propensity is the chosen arm's conditional probability under the draw
actually performed -- `rate` spread uniformly over the alternatives, so the deterministic arm's propensity is
`1 - rate` and each of `k` alternatives gets `rate / k`. `Decision` gains `exploration_reason` (why exploration did or
did not happen) and `eligible_set` (so the propensity can be checked, not reconstructed). `floor_compliance` now
reports **two** rates, `certified` and `all_served`, because an explored assignment is certified when the rest of
admissibility holds and not by virtue of why it was selected -- certifying by construction would let served-below-floor
traffic quietly leave the denominator, which preserves the metric and not the floor.

**A reader that survives a field being added.** `record.from_row(row)` replaces `accept._as_decision`'s
`Decision(**kw)` splat, which raised `TypeError` on every line the instant any field was added, outside `Log.read`'s
own corrupt-line tolerance -- so adding a field to the record killed a whole acceptance run rather than being counted,
in both directions: forward for an old reader meeting a new line, backward for an operator rolling back. A row's
unknown key is now ignored and *named*, not dropped; a row whose version exceeds what the reader knows is refused by
name rather than parsed optimistically; a row missing a field its own version requires raises, naming it. The same
treatment reaches a candidate row's unknown keys, by position, once the audit noted `bound_n`/`bound_attempted` are a
candidate-level field a future entry may replace and the original design only ever named the decision row.

**A pooling rule, or a refusal to pool.** `accept.check_all` gains `pool_across_versions: bool = False`. Six numbers
change silently at a schema-version boundary -- the exploration share is diluted by log length rather than behaviour,
a default's propensity-1 rows contribute infinite-weight certainty to any weighted estimate, and more -- so
`floor_compliance`, `default_is_not_a_hiding_place`, `exploration_cost` and `spend_regret` return `UNSUPPORTED` naming
the versions present and the count in each when a log mixes them and pooling was not asked for. `no_false_certification`
is exempt: it is a per-decision universal claim, not a rate, so a mixture does not change what it means.

### Fixed before release, from two review rounds and the journey layer

- **An arm reached through the expiry override was certified, and the falsifier caught it.** `explore.clears_floor`
  answers who may be drawn, not whether the floor is claimed; `serve.route_once` was deriving `certified` from that
  answer instead of from full admissibility, freshness included. The reproduction was exactly the case the door exists
  to create: `clears_floor` returns `(True, "eligible")` on stale evidence, `admissible` returns `(False,
  "evidence_expired")` on the same candidate, and the record said `certified`. Fixed by deriving `certified` from full
  admissibility on every assignment, explored or not; the arm is still served -- the label still comes back and the
  evidence still refreshes -- just not certified while stale.
- **The falsifier applied one evidence age to every candidate in a decision, and no scalar was right.** `accept.py`
  never threaded an age into `record.check_certification` at all, so freshness has been unchecked by the falsifier
  since v0.1.0 gained it as a fourth admissibility condition. Threading a single scalar through would not have fixed
  it either: measured on a real decision holding a 617-day-old candidate and a 9-day-old one, a 400-day scalar age
  reported **nothing** where the 9-day candidate was a genuine hiding place, and a 5-day scalar reported **both**
  candidates where only the 9-day one was true -- no scalar is correct for a set of candidates that differ in age by
  608 days. `check_certification` now derives each candidate's own age from its own `evidence_as_of` against
  `decision.decided_at`, via `observe.evidence_age_days` rather than a third copy of the same date arithmetic.
  `EXCLUSION_REASONS` gains `no_evidence_date` for a candidate with no recorded date and a limit declared, since
  treating it as unaged would silently skip freshness -- the original v0.1.0 defect, restored. `accept`'s report now
  also records `max_age_days` and its provenance, alongside the floor's own two fields, because a run made with no
  `--policy` checked three conditions and not four, and the report was not honest about which it had done.
- **A closed vocabulary was checked against itself and against nothing that produces it.** `EXCLUSION_REASONS` has
  nine values guarded by a membership check, and deleting each in turn and running the whole suite found four with
  zero test coverage: `not_authorised`, `latency_infeasible`, `unavailable` and `no_bound` could each be removed with
  the suite green, while `record.admissible` and `serve._why_not` still return exactly those strings on paths no test
  exercised. Fixed by testing the producers (`admissible`, `clears_floor`, `_why_not`) against the vocabulary rather
  than testing the vocabulary against a second list of itself. All nine values are kept; the four are the ones that
  exist for the case that has not happened yet.
- **`exploration` recorded that the randomiser ran, not that traffic was diverted.** `explore.draw` returned
  `"explored"` for both outcomes of an active draw -- the alternative winning, and the incumbent winning anyway --
  and `exploration_cost` computed its share straight off that field. Measured over 5,000 seeds at a rate of 0.05:
  `reason == "explored"` on 100.0% of draws, while only 5.5% actually diverted. `exploration_cost` therefore reported
  ~100% against a budget the mechanism was 5.5% inside -- a failure for a mechanism operating well within its own
  budget, which pressures an operator to shrink or disable the exploration that the freshness-ratchet fix above
  depends on for recovery. `exploration_reason` gains a fifth value, `not_diverted`; `exploration` is now derived as
  `chosen != deterministic`, the same signal `route_once` already computed three lines away. The propensity is
  unchanged -- an incumbent winning under an active draw still has propensity `1 - rate`, not 1, because the two
  fields answer different questions.
- **The rate criteria narrowed their denominator by exactly the rows C1 taught them to distinguish.** `accept._unreadable`
  read `outcomes["__bad_lines__"]` only, never the `__unreadable_rows__` counter this release's own reader added for
  rows that parse but fail `from_row`. Reproduced with 40 labelled successes and 15 rows stamped an unreadable schema
  version, all labelled failures: `floor_compliance` reported `pass`, rate 1.0, lower bound 0.9278, while the true rate
  counting the dropped rows is 0.7273 -- which fails an 80% floor. Both classes are now counted and named separately
  in every rate criterion's population (`floor_compliance`, `exploration_cost`, `slo`), and
  `default_is_not_a_hiding_place` gains an `outcomes` parameter it did not take at all before, which is why it had no
  guard against either class.
- **The mixture guard was overwriting a criterion's own, more specific reason.** Applying the schema-version pooling
  refusal ahead of a criterion's own logic replaced `spend_regret`'s "this has no implementation" with "your log spans
  two schema versions" -- sending an operator to fix the wrong thing. Fixed by computing first: the mixture guard now
  only overwrites a `PASS` or a `FAIL`, never a criterion's own `UNSUPPORTED`.
- **`from_row`'s list of ignored keys reached nobody.** `record.from_row` returns `(Decision, ignored)`, and every
  production call site -- `Log.read`, `accept`'s three call sites -- discarded the second value. An operator rolling a
  reader *back* onto a log a newer mechanism wrote gets every line reading fine and every criterion computing, while
  the fields the newer mechanism recorded (a propensity, an eligible set) are silently absent from what the criteria
  saw, with no signal that the reader is behind its own log. `Log.read` now carries `__ignored_keys__` -- names, not
  only a count -- and `accept`'s report records it. It does not make a criterion `UNSUPPORTED`: nothing was lost from
  the population, only understood less of, which calls for annotation rather than refusal.
- **Four tests passed on 3.9 and failed on 3.11, off the same commit, on the same machine.** They seeded a stall timer
  with a literal `0.0` and compared it against `time.perf_counter()`, whose reference epoch the language leaves
  undefined -- on this machine it is process start on 3.9 and boot time on 3.11, an 803,137-second difference that
  tripped a 2400-second stall ceiling before a single line was parsed. The production code was already correct: it
  takes and compares both readings from `perf_counter()` itself. Only the test supplied a value from no clock at all.

### What this release found about its own claims

Two of this release's most serious findings were in prose, not code, and both were caught by a worker's report rather
than by anyone re-reading the sentence.

`decide.as_dict` writes `decide.MISSING_FOR_A_CLOSED_LOOP` into **every compiled policy artifact**, as
`missing_for_a_closed_loop` -- a list of what the mechanism still lacks, "so their absence is not mistaken for
presence." Three of its six items were false at this release's own `HEAD`: a state collector, false for a whole
release (it shipped in v0.1.0 as `observe.py`, and the v0.1.0 release text itself said the tuple "closes the first" and
then never removed the entry); and logged selection probabilities and exploration itself, both false in this release,
both shipped by the exploration mechanism above. `tests/test_decide.py` asserted that the artifact claims exploration
and varying selection probabilities are missing, so a test *required* the shipped artifact to carry a false statement,
and it passed through eight prior entries because none of their diffs touched this tuple. The three false items are
removed, and every remaining claim is now tied to a probe -- a callable naming the symbol whose existence would
falsify it -- with a test asserting every claim and its probe agree.

Separately, `spend_regret`'s own refusal message said exploration was the prerequisite the mechanism lacked. Once the
exploration mechanism above shipped, that sentence was false in its central clause: a family declaring a rate now
produces exactly the varying propensities the message said were missing. The message now names the estimator as the
actual blocker, and says exploration is available and is what makes the estimate identifiable once a family declares
a rate -- found not by reviewing the message, but by a worker reporting a guard three layers away.

### Known gaps, named rather than implied

`decide.MISSING_FOR_A_CLOSED_LOOP` now lists **three**, down from six: anytime-valid bounds, change-point detection,
and a value for the reserved candidate's scarce capacity. This release closed two more -- logged selection
probabilities and exploration -- on top of the state collector v0.1.0 closed, and each remaining claim now has a probe
so the list cannot go stale silently again.

The loop still does not close: no arc runs from `record` or `accept`'s report back to `decide`. `Log.attach_outcome`
exists, as it did in v0.1.0, and nothing calls it -- a family now declares a labeller and a maximum label latency, but
declaring one is not calling one, and exploration on top of an unlabelled log produces randomised assignments nobody
can learn from. Spend regret's blocker is now the estimator, not the data, for a family that declares a rate; a family
that declares none still has propensity 1 for every decision, which is the older problem and not a lesser one.

The full suite passes at **1072 passed, 3 skipped** in `tests/` and **302 passed** in `harness/tests`, identically on
Python 3.9.6 and 3.11.15 -- checked directly on both interpreters. The count was 1065 while C12 was still being
written, and this entry carried that number for an hour: a changelog written alongside the work it describes is a
measurement like any other, and it goes stale the same way. That equality is asserted rather than assumed because it was false earlier in this release for exactly
the reason above: four tests compared against an interpreter clock epoch the language does not define, and passed on
one minor version while failing on the other from the same commit.

## 0.1.0

**One turn of the loop runs end to end.** Before this release the mechanism could be described and not run: `decide` was
handed a state by whoever called it, and nothing wrote a record, so SCOPE section 12's acceptance criteria were prose.

The loop does **not** close, and an earlier draft of this entry said it did. Nothing feeds back: outcomes are
attachable and nothing attaches them, exploration is off with a constant propensity so the log cannot support an
off-policy estimate, and no arc runs from the record or the verdicts to the policy.

### Added

**`observe` — the state a policy decides from.** Reads occupancy and availability from a vLLM `/metrics` endpoint and
carries the family's authorisation and evidence age. Verified against a running engine, not a fixture: the metric names
and the label set are the ones the engine exports.

- **Nothing is defaulted.** A variable that could not be read is absent with a reason, and `decide` reports it as
  `uncollected_variable` and declines to certify. A fabricated zero for `inflight` reads as an idle engine and sends the
  next request to the reserved candidate.
- `inflight` counts `running` **plus** `waiting`, because `waiting` above zero means the seats are already full and
  counting only `running` reports a saturated engine as having room.
- A model's series is read by `model_name`, so another candidate's occupancy is never summed into this one's — and a
  candidate with a `running` series but no `waiting` one is refused rather than half-read.
- `NaN` is dropped rather than parsed. It compares false against every threshold, so one broken series would make a
  saturated engine read as having room.
- An arrival rate refuses a single sample, a zero interval, and a counter that went backwards — the last is a restart,
  not a negative rate.
- Whether the gateway authorises spend is **passed in, never probed**: it is a question about a budget and a tenant,
  and inferring it from a reachable endpoint answers a different one.
- State keys are qualified by candidate where the quantity is a candidate's (`inflight:box`), which is how `decide`'s
  guards read them. An earlier version emitted bare keys, producing a state no guard matched — every request would have
  taken the default while the metrics endpoint answered perfectly. Caught by a test that wires the two modules
  together; neither module read wrong on its own.

**`record` — the decision record SCOPE section 9 requires**, with three refusals at write time rather than at claim
time.

- A `selection_probability` outside `(0, 1]` is refused. It cannot be reconstructed afterwards: a deterministic
  policy's propensity is 1 for what it chose and the counterfactual arm has no data at all, which is the definition of
  unidentified.
- `label_state` is three-valued — `labelled`, `missing`, `pending` — and a label given with a state that does not admit
  one is refused. A missing label silently read as a failure moves a realised success rate in the direction that
  flatters the floor.
- The candidate set must contain exactly one candidate marked `chosen`, and the exclusion reasons are a closed set:
  "other" in a log is a field nobody can aggregate.
- The log is append-only. An outcome arrives as its own line joined by request id, because a criterion computed over a
  rewritable log is a criterion computed over the rewrite.

**`accept` — SCOPE section 12's criteria, computed, with a third verdict.**

- `pass`, `fail`, and **`unsupported`**: the log does not contain what the criterion needs, so nothing was evaluated. A
  checker with two verdicts must choose between reporting a pass it did not earn and a failure it cannot substantiate.
- Three criteria are evaluable from a small log — no false certification (section 12's falsifier), default-is-not-a-
  hiding-place, and exploration cost. Six are not, and each says what it needs in its own words rather than sharing a
  message.
- Floor compliance is over **certified and labelled** decisions only and asks two questions that are not each other's
  negation: it FAILS on the exact one-sided binomial tail, and PASSES only when an exact lower confidence bound clears
  the floor. An earlier version passed when the failure test did not reject, which is accepting a null, and gated the
  middle case on `n < 30` -- a constant nobody derived. The bound replaced it, so a sample of 29 with every label a
  success now passes on its own evidence while 36 of 40 against a floor of 80% is `unsupported`, its 95% lower bound
  being 78.6%.
- A tolerance that was not declared is `unsupported` rather than compared against a number chosen here. Inventing it
  would be grading our own work.
- `summarise` deliberately does not reduce to `accepted`: over a set where most criteria were never evaluated, that
  word is the claim this module exists to refuse.

**`serve.route_once` — observe, decide, record, once.** Returns both the raw decision and the record, because the first
carries the gaps and the second carries what a later claim is computed from. Both kinds of gap travel into the record —
the policy's own and the collector's — since a caller that saw one would think the other had been checked.

**CLI: `observe`, `assign`, `accept`.** `observe` exits non-zero on an incomplete state so a deploy script cannot
proceed on a state nobody looked at. `accept` exits non-zero only on a failure, since an unsupported criterion is a
measurement nobody made rather than a defect.

**`decide.from_dict`.** A compiled policy on disk is a policy again. `as_dict` wrote guards only as prose, which made
the artifact one-way and forced the deployable path to rebuild the object it had just serialised; it now writes both
the prose a reader needs and the fields a loader needs, and an artifact from the older shape refuses to load rather
than having its English parsed.

### Fixed before release, from one adversarial review round

Seven defects, all real, and the review is in `docs/reviews/`.

- **`candidate_set` fabricated its exclusion reasons.** It wrote `below_floor` for anything it could not otherwise
  classify, **without a floor to compare against**, and four of the eight reasons were unreachable from that path -- so
  the log showed a clean, aggregable distribution over three reasons no matter what happened. A closed vocabulary of
  invented values aggregates confidently into nonsense, and the membership check that guaranteed the enum is what made
  it invisible. The reason now comes from the same `admissible` function the falsifier uses, and where no floor was
  supplied it is `not_evaluated` -- the true statement.
- **`bound_kind` was asserted as `lcb` for any supplied bound**, so a caller passing point estimates produced a log
  claiming they were corrected lower bounds, and the falsifier passed against them. It is passed, never inferred, and
  defaults to `unstated`.
- **`state_ref` was a dangling pointer.** The record hashed an observation that nothing persisted. The observation is
  now written to the log before the decision that references it.
- **The hiding-place scan skipped the chosen candidate**, which made the purest case undetectable: an uncertified
  decision whose own chosen candidate was admissible is a mechanism declining to certify an assignment it could have.
  It also stopped at the first violation and undercounted.
- **`admissible` ignored freshness** although `evidence_expired` was in the exclusion vocabulary with nothing able to
  produce it, so a candidate whose evidence had expired could be certified. Freshness is now three-valued like the
  latency condition: an undeclared limit is absent, not passed.
- **The log was append-only in bytes and mutable in meaning.** `read` kept the last outcome per request, so appending
  `labelled/True` after `labelled/False` silently replaced a label -- and the argument for trusting a criterion computed
  over an append-only log did not hold. A changed label is now refused; a label arriving after `pending` is not a
  change. One corrupt line no longer destroys every intact record around it, and the count travels rather than being
  swallowed.
- **`observe` summed across models when given no `model_name`**, which its own docstring called out as reporting
  another candidate's occupancy as this one's. It refuses when several `model_name` series are present and no filter was
  given. A non-finite or unreadable sample also refuses now instead of being dropped, because dropping one of three
  series produces a **partial sum** -- exactly the "saturated engine reads as having room" failure the module claims to
  preclude -- and `+Inf` could not even be matched by the old pattern.

Also corrected: `observe`'s claim that each reading carried its own timestamp was false, since one was computed before
the fetch and stamped on everything. It is true now, and `spread_s` is documented for what it actually buys -- a state
merged from several calls -- rather than for a spread that is zero within one call by construction.

### Known gaps, named rather than implied

`decide.MISSING_FOR_A_CLOSED_LOOP` lists six. This release closes the first — a collector. The other five stand:
logged selection probabilities that vary, exploration or shadow allocation, anytime-valid bounds, change-point
detection, and a value for the reserved candidate's scarce capacity. They are why six of nine acceptance criteria
report `unsupported`, and the report says so per criterion instead of in a footnote.

Two backlog items are written up in `docs/issues/`: reading the box's hidden state, to find out whether it breaks an
abstention limit that measured `AUC 0.5000` for a structural reason; and deriving the tie band from a jackknife over
recorded cohorts, so `--margin` stops being a value a human supplies.
