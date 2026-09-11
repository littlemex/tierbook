# Phase 1's review rounds for v0.3.0

Four rounds, one per distinct reader, each run as an independent pass with no sight of the others. The findings are
folded into `../01-design/design.md` sections 5 to 10; what is recorded here is which round produced what, so a later
amendment can cite a round the way v0.2.0's amendment 16 cites a specific measurement.

| round | reader | the finding that mattered most |
|---|---|---|
| 1 | re-derivation from purpose | The bound this design proposed is the one SCOPE section 6 disqualifies in those words: fixed-sample, single-test, no multiplicity term. Shipping it relocates the gap rather than closing it, because the compiler's authority makes a miscalibrated number worse than a caller's honest guess. Recorded as R1. |
| 2 | the operator | `certified` names two different judgments — non-inferiority validation in `route`'s JSON, section 2 admissibility in the falsifier — and nothing says which. And the record cannot name the artifact it came from, so this document's own falsifier contract was unimplementable as written. R5, R6. |
| 3 | adversarial on the design | The ordering claim survives and is understated: the log is append-only, so decisions written before `certified` and provenance are fixed are permanently ambiguous. And there is a third prerequisite nobody named — the tenant term of section 6's multiplicity family has cardinality 1 by omission rather than by declaration. R8, R9, R10. |
| 4 | convention fit | The no-dependency stance and section 6 are in real tension, and the round was explicit that its own upstream evidence was a lead rather than a citation. It also found that this document re-derived a finding the project had already named C13 — F2's defect committed by the document complaining about it. R14, R17. |

Two rounds contradicted each other on one point and both were right about different files: round 3 found the ledger's
evidence carries one timestamp for a whole run, while a check made here found the decision log does carry a
per-candidate time-ordered series. They answer different questions and R12 records the distinction, because "add
change-point detection" without saying which change point is how a placeholder gets replaced by another placeholder.

The raw output of each round is not reproduced here. What each round found that survived checking is in `design.md`
with the check beside it; what did not survive is not preserved, and the one place a round's own evidence was
explicitly weaker than a citation is stated as such in R14 rather than laundered into a recommendation.
