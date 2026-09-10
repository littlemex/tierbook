The repository referenced by the scope is not present here; only `prompt.md` and empty response files exist. This is therefore a contract-level audit based on the supplied fields and stated behavior.

## Q1 — Responsibility Placement

Several fields are assigned to layers that cannot authoritatively supply them.

- **`schema_version`** belongs to the serializer/log writer and schema registry—not `serve.route_once` or its caller. The component emitting the event must select and validate the version atomically with serialization.
- **`bound_n` / `bound_attempted`** belong to the evidence compiler. Routing cannot reliably recover which observations, exclusions, corrections, or weighting produced a bound. `Candidate` may carry the provenance, but the compiler must supply it from an immutable evidence artifact.
- **`stratum`** belongs to a state collector plus a versioned classifier. A caller can supply raw facts, but letting arbitrary callers declare the derived stratum creates incomparable populations. At minimum log classifier version, inputs/provenance, and missing reason.
- **`consequence_class`** belongs to product/risk policy, not statistical routing. It may depend on tenant, intended use, failure mode, and candidate action. Treating it as a caller-provided request attribute invites understating risk.
- **`features`** belong to named feature extractors. Requiring the route caller to provide an untyped mapping merely moves collection responsibility outward; it does not establish trustworthy observation.

The missingness reason should also come from the component that failed to observe or derive the value. A caller cannot honestly distinguish “extractor unavailable,” “not applicable,” “redacted,” and “not yet computed” unless that provenance is propagated.

Most importantly, adding a `features` slot now does **not** let a future signal be compared with decisions made before that signal existed. Old events still lack the measurement. That claim is only true if `state_ref` preserves sufficient immutable raw state and future extractors can replay it.

## Q2 — Re-derived Scope

Starting only from “lower cost while giving up as little accuracy as possible, deciding from observed state in a moving environment,” I would scope v0.2.0 as follows:

1. **Create a validated, versioned decision envelope.**
   - Schema identifier/version, strict writer validation, per-version readers, and explicit normalization rules.
   - Record the complete feasible action set, not just the chosen candidate.

2. **Close the observation boundary.**
   - Implement or define the collector contract for decision-time state.
   - Record observation time, source, extractor/classifier versions, and typed missingness.
   - Preserve replayable raw-state references where permissible.

3. **Join decisions to outcomes reliably.**
   - Specify label eligibility, delay, censoring, deduplication, and request-to-outcome joins.
   - Exploration without dependable outcomes does not generate useful evidence.

4. **Introduce safety-constrained exploration.**
   - Randomize only among candidates satisfying the applicable floor, unless an explicit experimental-risk policy authorizes otherwise.
   - Log the chosen action’s actual conditional probability, eligible action set, experiment assignment, and mechanism parameters.
   - Report outcomes over all served traffic, including uncertified traffic.

5. **Make evidence immutable and reproducible.**
   - Bind every bound to a dataset/cohort digest, evidence revision, method, confidence level, exclusions, and computation version.
   - Freeze fixed-sample evidence epochs or refuse certification when the exact artifact no longer matches.

6. **Add environment-validity monitoring.**
   - At minimum monitor state/action/outcome drift and expire certification on explicit validity rules.
   - Full change-point detection can wait, but “moving environment” cannot be represented solely by evidence age.

### Divergences

- **S1 schema version stays**, but an integer field alone is insufficient. This divergence is justified because no validation currently exists.
- **The generic `features` mapping is replaced by typed observations or versioned feature schemas.** Justified: a bag of names is not a durable contract and does not recover historical signals.
- **The two bound counts are replaced by evidence-artifact provenance.** Justified: counts cannot identify the cohort or reproduce most bounds.
- **`consequence_class` must affect safety immediately or be explicitly marked observational.** Recording risk while knowingly ignoring it is difficult to defend once exploration can serve inferior candidates.
- **`stratum` should be delayed until its taxonomy and classifier ownership are defined, or logged with that provenance.** An unversioned caller label creates false comparability.
- **S3 moves alongside S1, not behind it.** The missing counterfactual outcomes are at least as irreversible as missing event fields.
- **S3 becomes safe exploration, not automatically uncertified exploration.** Certification and exploration are orthogonal.
- **The collector and outcome join enter scope.** Without them, “observed state” and learning from exploration remain assumptions rather than mechanisms.
- **S2 becomes exact artifact matching, not “has the cohort grown?”** Growth is only one mutation.
- **A minimal drift monitor enters scope.** Full change-point detection may remain out, but a moving environment requires more than age expiry.
- **Anytime-valid bounds can remain out.** Fixed, immutable evidence epochs are an honest alternative if enforced.

There is also a concrete defect in S3’s propensity example. With two total arms and 5% uniform exploration including the incumbent, probabilities are `0.975` and `0.025`. If exploration always chooses the alternative, they are `0.95` and `0.05`. The stated `0.95` and `0.025` only make sense with two non-default exploratory arms, for three arms total. The mechanism is under-specified before implementation begins.

## Q3 — Brittle Parts

### Likely Rewrite Points

- **S1’s `features` mapping** fails when features become typed, repeated, large, sensitive, asynchronous, or candidate-specific. A mapping cannot reliably express provenance, units, extractor identity, observation time, redaction, or per-value missingness.
- **S1’s bound counts** fail when the bound uses weights, clustered observations, multiple trials, exclusions, stratification, effective sample size, or a non-binomial method. Even `solved`/`attempted` does not reproduce the bound.
- **S1’s `consequence_class`** fails if consequence is action-specific or multi-dimensional. A request does not necessarily have one consequence independent of which candidate fails and how.
- **S2’s growth comparison** fails on cohort correction, relabeling, deletion, replacement, changed exclusions, or recomputation with a different method while the row count stays constant.
- **S3’s chosen propensity alone** becomes operationally unauditable when eligibility constraints, contextual exploration rates, multiple arms, fallback routing, retries, or hierarchical randomization are introduced. The scalar may be statistically sufficient for some IPS estimators, but only if the action set and probability-producing mechanism can be reconstructed.

### The Two That Must Change Together

**S2 and S3 must be designed together.** Exploration creates adaptively collected evidence. The moment that evidence feeds subsequent bounds, the supposedly latent fixed-sample problem becomes active. They need a shared rule for:

- evidence epochs,
- when exploratory observations enter a cohort,
- cohort freezing,
- policy-dependent sampling,
- repeated certification tests,
- and confidence-budget handling.

S1 and S3 must also deploy atomically at the event boundary, but that is a rollout dependency. S2/S3 is the deeper statistical dependency.

### Wrong-Shaped Field

The worst is **`features: mapping`**. It is a junk drawer likely to accumulate incompatible meanings and missingness conventions.

The second is **`bound_n` / `bound_attempted`**. It encodes a current binomial ledger layout rather than the provenance of a bound. Prefer an `evidence_ref` pointing to an immutable artifact containing:

- cohort digest and revision,
- sufficient statistics,
- bound method and parameters,
- confidence level and multiplicity treatment,
- observation and computation times,
- exclusions and weighting.

A projected `solved`/`attempted` pair may still be included for convenience, but it should not be the contract.

## Q4 — Irreversible vs. Recurring

The distinction is not sound.

Every deterministic decision made without support for another action permanently lacks that action’s outcome. Later exploration cannot repair those historical counterfactuals. That is irreversible data loss in exactly the sense used to justify S1—and arguably stronger, because adding a schema version cannot restore either missing field values or missing outcomes.

A propensity-1 log remains useful for:

- evaluating the policy actually run,
- factual outcome and cost reporting,
- calibration on selected traffic,
- deterministic policy replay,
- supervised outcome modeling where natural overlap exists,
- and some comparisons across historical policies under additional assumptions.

It cannot, without overlap and strong modeling assumptions, identify:

- the outcome of an action never taken in that state region,
- the value of a policy choosing that action there,
- causal differences between routed-away candidates,
- or unbiased off-policy estimates outside observed support.

Calling S3 “recurring” understates the loss. The implementation can be added later without a schema migration, but the missing counterfactual evidence from the intervening period is permanently gone. “Structural deferral cost” and “data irrecoverability” are different axes; the document uses the first for ordering while calling it the second.

Likewise, not every S1 value is necessarily irreversible: some may be reconstructed from immutable request payloads, classifier versions, evidence snapshots, or policy configuration. Irrecoverability should be assessed field by field, not inferred from absence in the decision event.

## Q5 — S2’s Refusal

A refusal is honest engineering if it establishes a real invariant rather than hiding a TODO. That requires:

- certification bound to an immutable evidence artifact;
- comparison of artifact identity or digest, not merely row count;
- refusal on relabeling, changed membership, changed exclusions, changed method, or changed confidence parameters;
- tests proving every certification path enforces the check;
- a visible reason code and operational metric for refusals;
- documented ways forward: frozen evidence epochs, fresh preregistered cohorts, or anytime-valid inference;
- an owner and trigger for revisiting the statistical method.

It becomes deferral behind a permanent guard if:

- the mutable ledger remains the only evidence store;
- normal remeasurement immediately makes all certification impossible;
- operators can bypass the refusal by copying or renaming a cohort;
- exploration is shipped but no evidence-ingestion design is agreed;
- refusal rates are not monitored;
- the system silently falls back to stale certification;
- or “anytime-valid later” has no concrete criterion, owner, or planned use case.

The proposed “has the cohort grown?” condition is too weak. A cohort of 24 can change completely and remain size 24. S2 is honest only after changing the invariant to “the exact evidence snapshot and bound procedure are the ones certified.”

Finally, “explored assignments are uncertified by construction” is not a safe resolution. Certification should describe whether an action clears the floor; exploration describes why it was selected. Conflating them permits unsafe service and then removes that traffic from `floor_compliance`’s denominator. That preserves the metric, not the floor.
