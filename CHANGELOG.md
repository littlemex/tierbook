# Changelog

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
