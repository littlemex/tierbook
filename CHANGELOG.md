# Changelog

## 0.1.0

The loop closes. Before this release the mechanism could be described and not run: `decide` was handed a state by
whoever called it, and nothing wrote a record, so SCOPE section 12's acceptance criteria were prose.

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
- Floor compliance is over **certified and labelled** decisions only, tested against the exact binomial tail, and
  reports `unsupported` below 30 labels with the rate printed so it is not mistaken for a pass.
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

### Known gaps, named rather than implied

`decide.MISSING_FOR_A_CLOSED_LOOP` lists six. This release closes the first — a collector. The other five stand:
logged selection probabilities that vary, exploration or shadow allocation, anytime-valid bounds, change-point
detection, and a value for the reserved candidate's scarce capacity. They are why six of nine acceptance criteria
report `unsupported`, and the report says so per criterion instead of in a footnote.

Two backlog items are written up in `docs/issues/`: reading the box's hidden state, to find out whether it breaks an
abstention limit that measured `AUC 0.5000` for a structural reason; and deriving the tie band from a jackknife over
recorded cohorts, so `--margin` stops being a value a human supplies.
