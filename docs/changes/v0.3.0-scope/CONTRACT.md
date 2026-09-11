# v0.3.0 — stop claiming more than the mechanism has, and open the door that lets it have more

Phase 2's output. The single source of scope. Phase 1 is `01-design/design.md`; the rounds that produced its findings
are indexed in `02-findings/README.md`.

## Out of scope, written first

Written first because it is the harder half, and because phase 1 proposed a centre this contract does not adopt.

| Not doing | Why not, and where it goes |
|---|---|
| **An anytime-valid bound** | SCOPE section 6 requires one and this release does not build it. R14 established a real tension rather than a detail: the authoritative general implementation is compiled C++ needing numerical optimisation, `pyproject.toml` declares `dependencies = []` with a stated reason, and the one elementary construction a round surfaced arrived through an automated fetch rather than a read — **a lead, not a citation**. Section 6 exists because a point estimate was trusted once; adopting a confidence sequence from a summary is the same mistake with more machinery. The smaller change that removes the harm is C1 below: stop asserting a correction the mechanism did not perform. Goes to v0.4.0's phase 1 with R14 as its input. |
| **A multiplicity correction over four terms** | Same reason, and one term does not exist to correct over. C3 makes the tenant term's cardinality **declared** rather than assumed, which is what makes a later correction honest; performing the correction is not in this release. |
| **Change-point detection** | R12 split it in two and both halves are blocked. The measured side needs a per-item time series the ledger does not have — `Evidence` is `path`, `header`, `verdicts` with one `produced_at` for a whole run — so it needs a ledger schema change. The serving side is derivable from the decision log today but needs labels, and C4 is the door to labels rather than the labels themselves. Deferring is not a choice about priority; the inputs are absent. |
| **Retirement of a candidate** | A9 found SCOPE section 6's "retired when it stops clearing" has no implementation at all — no state, no vocabulary, no path — and R11 found it requires extending `EXCLUSION_REASONS`, a closed enum whose every value describes *current* admissibility. That is a concept, not a fix, and it depends on change-point detection to know when clearing stopped. Named here so the omission is recorded rather than inherited a third time. |
| **Per-tenant floors** | R10 named it the requirement that would force a rewrite rather than an extension. C3 makes the ground ready by requiring the tenant scope be declared; nothing more. |
| **The compile cadence** | R13 found `deploy/base/compile-cronjob.yaml` runs daily and keeps the previous artifact on refusal, against section 6's "recomputed continuously". True, and it only bites once retirement exists, which is out. Recorded, not fixed. |
| **`explain` gaining a floor or bound column** | The persona round found it gives an operator nothing toward choosing a floor. Real, and it is a surface improvement rather than a claim being corrected. It waits until the absolute bound exists to show. |
| **`tierbook logs` accepting a decision log** | A naming collision that returns a plausible answer for the wrong file. A tangent found on the way past; fix it in a separate change and say so here so it is not lost. |
| **`requires-python` disagreeing with the tested minimum** | `pyproject.toml` declares `>=3.10`; the suite is green on 3.9.6 and has been through two releases. One of the two is wrong and deciding which is a packaging question with no bearing on this release's subject. A tangent. |
| **A second provenance scheme** | R15: `policy.registry_version` already content-hashes the ledger. C2 gives the compiled artifact the same treatment rather than inventing a scheme beside it. Rejected because inventing one is the defect C2 exists to fix. |

## What changes

The release is one thing said four ways: **every claim the mechanism makes is either true or labelled as weaker than it
looks, and the one door an operator needs is open.** Every entry below is a claim that currently outruns its evidence,
plus the door.

### C1 — a bound says which corrections produced it, and `certified` stops meaning two things

Two defects, one entry, because fixing either alone leaves the other's damage in an append-only log (R8).

**`bound_kind` becomes a checked, structured statement rather than a free string.** Today three records carrying a
fabricated `bound` of `0.99` with `bound_kind` of `lcb`, `point_estimate` and `asserted_by_operator` all certify
identically, because `admissible` compares only `bound < floor` and nothing reads the kind. It names, from a closed
vocabulary tied to its producers in the shape `tests/test_reason_vocabulary.py` established: the estimator, the
confidence level, and **which terms of section 6's multiplicity family were corrected over**. A bound that corrected
over none says so. Nothing in this release produces a bound claiming anytime-validity, and the vocabulary makes that
claim unrepresentable rather than merely absent.

**`certified` names one judgment.** `decide.py` sets `certified = entry.get("status") == "assigned"` — non-inferiority
validation against a reference — and `record.check_certification` computes section 2 admissibility. Both travel under
one word, and `tierbook route`'s JSON returns the first to an operator who declared a floor and reads it as the second.
The compile-time judgment is renamed to what it is; `certified` keeps section 2's meaning, which is the one SCOPE
defines and the falsifier tests.

This is the entry the ordering argument is about: R8 established the log is append-only, so a decision written before
this lands is permanently a bound of unknown provenance under an ambiguous word.

### C2 — a record can name the artifact it came from

`Decision`'s version-shaped fields are `feature_vector_version`, `policy_version`, `mechanism_version` and
`schema_version`. `policy_version` is a hand-typed CLI string defaulting to `"unversioned"`. So phase 1's own falsifier
contract — "the record carries which artifact" — was unimplementable as written, and I wrote it as though it held.

The compiled policy carries a content hash, derived the way `policy.registry_version` already derives one over the
ledger, and the record carries it. A `policy_version` supplied by a caller that disagrees is refused naming both, by
`decide.parameter`'s established rule.

Fixes three things the design credited once (R6): the falsifier gets a premise, and auditing which multiplicity
assumption a historical bound used becomes possible at all, which is what makes C1's vocabulary readable later.

### C3 — the tenant term's cardinality is declared, not assumed

SCOPE section 6's multiplicity family is candidates × families × tenants × the selection process. No tenant field
exists anywhere in the record, the config or the artifact, and SCOPE section 7 is normative: pooling across tenants
while holding per-tenant floors is *"a declared policy input, not an emergency measure."* So the document requires a
declaration for which there is no field, and every bound ever computed assumed cardinality 1 without saying so.

`config.FamilyDeclaration` requires a tenant scope. Declaring a single tenant is legitimate and is the common case;
what is refused is silence. **A term with cardinality 1 by omission is not the same as a term with cardinality 1 by
declaration, and only the second can be corrected over later.**

### C4 — the door to a labelled log

`Log.attach_outcome` exists, `record.classify_label` exists, a family declares a labeller and a maximum label latency,
and there is no CLI verb and no mention in `README.md`, `SCOPE.md` or any `--help`. An operator working from the
documented surface cannot produce a labelled log without reading `src/`. Every criterion needing a realised rate is
therefore permanently `unsupported` for them, and the report attributes that to a missing measurement rather than to a
missing door.

A verb attaches an outcome. It does **not** invoke a labeller: A7 settled that decisively against phase 1's first
draft, because `cli.py`'s own first paragraph says running a benchmark is somebody's suite and anything that can write
a record in the documented shape is a valid producer of one. The verb is a door, not a runner.

### C5 — the ceiling is reported, and something reads it

A declared floor above `alpha ** (1/n)` can never be cleared, whatever the measurement says. The shipped ledger
declares `tool-agent-user-retail` at **0.92** on a **20-item** cohort whose ceiling is **0.8609**. Today an impossible
floor and no floor at all produce byte-identical `compile` and `route` output, `certified: true` either way, with no
warning (R7).

The compiler computes the ceiling and the cohort size the declared floor would need, and records both. It does **not**
refuse: R3 established that an unreachable floor is a true fact about the evidence budget rather than a malformed
declaration, and SCOPE sections 2, 8 and 12 all make serving the declared default uncertified the correct behaviour in
that state — section 12 makes it a *passing* criterion.

**And something reads it.** R16 found `"warning"` strings already written into artifacts in two places with **zero**
reads across `src/` and `tests/` — the same condition as `bound_kind`. Adopting only the surface would make this the
third value recorded and never read. A criterion reads the ceiling, so a floor that cannot be cleared is a stated
verdict rather than a comment in JSON.

### C6 — the candidate set comes from the ledger, not from the policy's rules

`serve.candidate_set` builds from `policy.rules`, so a candidate with no rule is absent from the set, invisible to
exploration, never labelled, and its evidence never refreshes (F3). A3 established the set is derivable without new
measurement: `assign_family`'s `ranked` already covers every candidate with an outcome for the family, for both shipped
families.

A candidate the ledger cannot bound is named **with no bound** rather than omitted. Omission is what makes it
invisible; the fix is to say it has none, which is also what C1's vocabulary now has a word for.

### What no entry does

Nothing here computes an anytime-valid bound, corrects over any multiplicity term, detects a change point, retires a
candidate, or invokes a labeller. Four of those are in the out-of-scope table with their reasons; the fifth is refused
on a boundary this project states in its own first paragraph.

## The stop condition

Two mutations, and neither is satisfiable by losing the thing it counts.

1. **A record whose bound claims a correction the release does not perform cannot be written.** Mutate `bound_kind` to
   accept a free string and a test fails; mutate a producer to emit a kind naming a correction nothing applied and a
   test fails. Counted as unresolved obligation ids, not as current text, so deleting the sentence that carries an
   obligation does not discharge it.
2. **An operator can produce a labelled log using only the documented surface, and the ceiling is a verdict rather
   than a string.** Mutate the ceiling out of the criterion and a test fails; delete the verb's documentation and the
   journey test that walks the documented surface fails.

## The obligation carried forward, as prose

Two things this release does not mechanise and a person has to hold.

The absolute bound the mechanism now labels honestly is still supplied by a caller. C1 stops it from claiming to be
something it is not; it does not make it a measurement. Whoever ships v0.4.0 owes the derivation, and until then a
certified assignment rests on a number an operator typed — correctly labelled, and still typed.

And section 6's sentence has two halves. This release touches admission and leaves retirement absent, so a candidate
that stops clearing keeps clearing until somebody recompiles and notices. Age stands where a change point belongs, and
SCOPE section 2 clause 4 currently describes the placeholder as the requirement — a document disagreeing with itself in
two sections, written that way by me in v0.2.0's amendment 6. Correcting the document is C1's neighbour and is not in
this release either; what is here is that the disagreement is now written down.

## Rejected alternatives, with reasons

| Rejected | Reason |
|---|---|
| Compute the absolute lower bound and make it the release's centre, as phase 1 proposed | R1: the bound available dependency-free is fixed-sample and single-test, which section 6 disqualifies **in those words**. Shipping it would relocate the defect rather than close it — a caller's honest guess becomes the compiler's miscalibrated assertion, which is worse because it carries the compiler's authority. |
| Refuse a floor above the cohort's ceiling at compile time (phase 1's F8) | R3: an unreachable floor is a true fact about the evidence budget, not a malformed declaration. SCOPE section 2 says there is no "choose nothing", section 8 serves the default uncertified on day one, and section 12 makes "everything to the default" a passing state. Refusing turns a purpose-correct degenerate state into an outage. |
| Build a component that invokes the family's declared labeller | A7: `cli.py`'s first paragraph. A component here that ran somebody's suite would cross the boundary this project states before anything else. |
| Add a third vocabulary-and-test scaffold for the new bound provenance | Q2 of the convention round: this project has already solved "a set that must not go stale" twice — a producer-tied vocabulary test, and a claim-with-probe pair. C1 uses the first because bound provenance is a per-record value. A third would be new machinery for a solved problem. |
| Invent a provenance scheme for the compiled artifact | R15: `registry_version` already content-hashes the ledger. C2 extends the existing shape. |
| Ship the ceiling as a `"warning"` string like the two that already exist | R16: neither existing warning key is read anywhere. Matching the surface without a reader would be the third value recorded and never read, which is the defect C1 is fixing in `bound_kind`. |
| Treat the three remaining `MISSING_FOR_A_CLOSED_LOOP` entries as one backlog | F6: anytime-valid bounds became load-bearing the moment exploration shipped, and the other two did not. Treating them as interchangeable hid that one is a prerequisite. |
| Resume C13 as new work under a new label | R17: v0.2.0's amendment 16 named it C13 and deferred it to this phase by name. Re-deriving it as F1/F2 was the duplicated-knowledge defect committed by the document complaining about it. C1 and C2 are C13, split by what each claims. |

## Every claim this contract makes about a file, checked

Run before the interface section was written, because a worker who inherits an unverified assertion builds on it four
times over. The commands are in `02-findings/README.md`'s neighbour; the results:

| claim | checked | result |
|---|---|---|
| the shipped ledger declares `tool-agent-user-retail` at a floor of 0.92 | read `examples/ledger/candidates.json` | 0.92 |
| the ceiling at n=20 is 0.8609 | `clopper_pearson_lower(20, 20, 0.05)` | 0.8609 |
| `admissible` never compares `bound_kind` | read the function body | not present |
| `registry_version` content-hashes the ledger | read it | sha256 over every tier record |
| `policy_version` defaults to `"unversioned"` | read `cli.py` | `default="unversioned"` |
| no CLI verb attaches an outcome | ran `--help` | no verb contains "attach" |
| `attach_outcome` is unmentioned in `README.md` and `SCOPE.md` | read both | absent from both |
| `candidate_set` builds from `policy.rules` | read `serve.py` | `for rule in policy.rules` |
| a `"warning"` key is written and never read | grepped writes and reads | 2 writes, **0** reads |

## Interface

Handed to `/split-impl` unchanged. Failure behaviour is part of every entry, because that is where two readers of one
sentence diverge.

### C1 — bound provenance, and one meaning for `certified`

**`record.BOUND_CORRECTIONS`** — a closed tuple naming what a bound may have been corrected over: `none`,
`candidates`, `families`, `tenants`, `selection_process`. Tied to its producers the way `EXCLUSION_REASONS` is: a test
drives every producer of a bound and asserts what comes back is in the tuple, and a producer growing a value the tuple
lacks fails at merge time.

**`record.BoundProvenance`** — `estimator: str`, `confidence: float`, `corrected_over: tuple[str, ...]`. `estimator` is
from a closed tuple whose only member this release ships is `clopper_pearson_fixed_sample`; adding
`anytime_valid_*` is a later release's act and the vocabulary makes its absence explicit rather than implied.
`corrected_over` is a subset of `BOUND_CORRECTIONS` and `()` is legal and is what this release produces.

**`Candidate.bound_kind` is replaced by `Candidate.bound_provenance: BoundProvenance | None`.** `None` means no bound,
which C6 requires to be representable. A free string is refused naming the field and the tuple — the old `bound_kind`
is not kept as an alias, because keeping it would leave a writer of an unchecked claim that the new check cannot see.

**`record.admissible` reads it**: a bound whose provenance claims a correction over a term the mechanism did not correct
over is not merely unlabelled, it is refused. That is the difference between the vocabulary being checked and being
recorded.

**`decide.Policy.certified` is renamed `validated`**, and `decide.as_dict` writes `validated`. It is the
non-inferiority status against the reference and nothing else. `route`'s JSON reports `validated`, and the word
`certified` appears in the online path only where section 2's judgment is meant. `from_dict` on an artifact carrying
`certified` refuses, naming both words and saying which judgment each is — an artifact from v0.2.0 is exactly that case
and must not be read optimistically, by C1's own rule for a version it does not know.

### C2 — the artifact's own hash, in the record

**`decide.policy_digest(policy) -> str`** — sha256 over the artifact's own serialisation, truncated the way
`registry_version` truncates, and written into the artifact by `compile_policy` as `policy_digest`.

**`Decision.policy_digest: str`**, no default, required at `schema_version` 3. `from_row` supplies `""` for a row at
version 1 or 2 and raises `Incomplete` naming the field at 3 or above — SEAMS S4's rule, applied to the third field
that needs it.

**`route_once` reads the digest from the policy** and refuses a caller-supplied `policy_version` that disagrees,
naming both, by `decide.parameter`'s rule. `--policy-version` loses its `"unversioned"` default: a value the mechanism
can derive is not a value a caller supplies.

### C3 — the tenant scope, declared

**`config.FamilyDeclaration.tenant_scope: str`** — required, refused when absent naming the family and the field. One
of `single`, `pooled`, `per_tenant`. `pooled` and `per_tenant` are declarations this release records and does not act
on; `load_config` refuses a family declaring `per_tenant` **together with** an `exploration_rate`, because R11 found
the rate and the selection-process term are coupled and this release corrects over neither.

The refusal message says that the scope is a multiplicity term SCOPE section 6 requires and section 7 calls a declared
policy input, and that declaring `single` is legitimate — what is refused is silence.

### C4 — the door

**`tierbook attach-outcome --log <path> --request-id <id> --label-state <state> [--label true|false] [--tokens N]
[--latency-s S]`**. Exit 0 on success. Exit 2 on a missing required argument. Exit 1 when the log refuses the outcome —
a label that changes, or a state that does not admit the label — with `record.Incomplete`'s own message on stderr,
unmodified, because it already says what the operator did and why the log refuses it.

It attaches. It does not read a family's `label_source`, does not invoke anything, and does not decide `label_state`:
`classify_label` owns that and the caller states what it observed. A `--label-state` outside `LABEL_STATES` is refused
naming the tuple.

**`README.md` gains the verb in the documented sequence**, between `assign` and `accept`, because a criterion that
needs a realised rate is unsupported until it runs.

### C5 — the ceiling, and a criterion that reads it

**`accept.floor_reachable(n, floor, alpha) -> tuple[bool, float, int]`** — whether the floor is reachable on a cohort
of `n`, the ceiling `alpha ** (1/n)`, and the smallest `n` at which the floor becomes reachable. `n <= 0` raises, by
C14's rule.

**`compile_policy` writes `floor_ceiling` into `Policy.parameters`**: the ceiling, the cohort size the evidence
actually has, and the smallest cohort the declared floor would need. Absent when the family has no evidence to count.

**`accept.CRITERIA` gains `floor_is_reachable`** — `FAIL` when the artifact's declared floor exceeds the ceiling its
own cohort imposes, naming both numbers and the cohort size required; `PASS` when it does not; `UNSUPPORTED` when the
artifact carries no `floor_ceiling`, which is a v0.2.0 artifact. It is a criterion and not a compile-time refusal, and
the reason is in the rejected-alternatives table.

This is the tenth criterion. SCOPE section 12 defines nine and C5 in v0.2.0 kept `floor_compliance` as one criterion
carrying two rates specifically to avoid a tenth. **That decision is reversed here deliberately and the reason is
different**: two rates over one population are one question asked twice, and floor reachability is a different question
about a different object — the declared floor against its cohort, not the traffic against the floor. SCOPE section 12's
list grows by one and the document is amended to say so, rather than the criterion being folded into a neighbour to
preserve a count.

### C6 — the candidate set from the ledger

**`policy.candidates_for(tiers, family) -> dict[str, float | None]`** — every candidate with an outcome for the family,
mapped to its bound or to `None`. Derived from what `assign_family`'s `ranked` already enumerates, which A3 verified
covers every measured candidate for both shipped families.

**`compile_policy` writes the set into the artifact** as `candidates`, and **`serve.candidate_set` reads it** rather
than deriving from `policy.rules`. A candidate present with `None` is in the set with no bound, excluded for
`no_bound`, and visible to `explore.eligible` as a candidate that exists and cannot be drawn into — which is the
distinction that made it invisible before.

A v0.2.0 artifact has no `candidates` key. `from_dict` refuses it rather than falling back to the rules, because
falling back is what made the omission silent.

## Amendment 1 — C3's out-of-enum refusal, which the interface implied and did not state

C3's test author reported it rather than pinning a message the contract had not committed to, which is the right call:
the interface says `tenant_scope` is "one of `single`, `pooled`, `per_tenant`", which implies an enum check, and
specifies the wording of only the omission and the coupling refusals.

The local idiom already answers it. `load_config`'s existing out-of-enum refusal for `label_source` reads:

```
family 'agentic-coding'.label_source is 'not_a_real_kind', which is not one of [...]
```

**`tenant_scope` follows that shape**: the family, the field, the value given, and the legal values. It does **not**
repeat the omission refusal's explanation that `single` is legitimate — an operator who typed a wrong value already
knows the field exists and needs the list, whereas an operator who omitted it needs to be told the easy answer is
allowed. Two refusals, two audiences, and conflating them would make the longer message the common case.

No test is required for it by this amendment beyond what the enum check naturally gets: the reachability requirement in
C1's vocabulary test covers "every legal value is reachable", and the three-values test C3 already commissions covers
the positive side. Stating the wording is what was missing.

## Amendment 2 — four things C1's interface implied and did not state, all reported rather than guessed

C1's test author found each of these and deliberately left the corresponding case untested rather than pinning a
behaviour the contract had not committed to. Three of the four are defects I introduced in the interface.

**A2.1 — `"none"` is removed from `BOUND_CORRECTIONS`.** The interface listed it as a member and separately said
`corrected_over = ()` is legal and is what this release produces. That is two spellings for one meaning, which is the
duplication class this whole release is about, in the vocabulary the release adds. The tuple names **terms that can be
corrected over**, and "none" is not a term. `()` is the only spelling for no correction, and `("none",)` is refused as
an out-of-vocabulary value like any other string.

**A2.2 — the producer is named.** `EXCLUSION_REASONS`' vocabulary test drives named producers — `admissible`,
`clears_floor`, `_why_not`, `draw`. `BoundProvenance` had none: the interface named `record.admissible` as the consumer
that refuses a bad claim and no function that constructs one. The producer is **`serve.candidate_set`**, which is where
a `Candidate` acquires its bound today, and the vocabulary test drives it. Without a named producer the test can only
check the consumer, and a second construction site added later would be unwatched — which is C7's defect in the
vocabulary this entry adds.

**A2.3 — the refusal has a reason and it is in the exclusion vocabulary.** `admissible` returns a reason that lands in
`Candidate.excluded_because`, so a refusal with no named reason is unassignable. `EXCLUSION_REASONS` gains
**`unsupported_correction`**: the bound claims a correction over a term the mechanism did not perform. It is distinct
from `no_bound`, which says there is no bound at all, and from `below_floor`, which is about the number rather than the
claim.

**A2.4 — a bound and its provenance travel together, and the alternative is unrepresentable.** The interface defined
`bound_provenance = None` as "no bound" and said nothing about a numeric `bound` carrying no provenance. That
combination **is the pre-C1 state** — a number with no statement of what produced it — so leaving it constructible would
leave the defect representable while adding the vocabulary that was supposed to end it.

`Candidate.__post_init__` refuses a numeric `bound` with `bound_provenance=None`, and refuses a `bound_provenance` with
`bound=None`, each naming both fields. That is the move `/review-contract` calls making the omission unrepresentable
rather than watched: forgetting the provenance becomes a failure at construction instead of an absence nothing reads.

## Amendment 3 — C1 renamed the field and left the majority of records filling it from the other judgment

C1's code author reported this rather than leaving it, and it is the most consequential finding of the entry: **the
rename is done and the value flow is half done.**

`serve.route_once` has two branches and they fill `record.Decision.certified` from two different judgments. Verified by
reading both:

```python
        drawn = next(c for c in candidates if c.id == chosen)
        certified, _not_admissible_because = admissible(...)     # explored branch: SCOPE section 2
    else:
        certified = bool(got["validated"])                       # deterministic branch: non-inferiority
```

The deterministic branch is the majority of decisions. So a record saying `certified: true` on that path still means
"a held-out fold supported this against the reference", which is the judgment C1 renamed to `validated` three lines
above, and the falsifier compares that value against `admissible` — which is the `no_false_certification` failure the
live run in v0.2.0's phase 5 already observed.

**And the rename makes it harder to see, not easier.** Before, one word carried two meanings and a reader could suspect
it. Now two words exist and one of them is silently carrying the other's value, which reads as though the distinction
had been made.

The code author's reasoning was that changing the value flow is new logic outside "the smallest change", and that is
the right instinct applied to the wrong sentence. C1's interface says *"`certified` keeps section 2's meaning, which is
the one SCOPE defines and the falsifier tests."* A branch filling it from the validation status contradicts that
sentence, so fixing it is the entry's own content rather than an addition to it.

**Both branches call `admissible`.** The explored branch already does and its comment already says why — the two
predicates cannot disagree by construction. The deterministic branch does the same. Decisions that were `certified`
because the policy was validated become `certified` only when the candidate is admissible, which is the behaviour the
falsifier has been testing for all along.

**A3.2 — the online path includes the `route` verb's JSON, and the compile path does not.** The interface says the word
`certified` appears in the online path only where section 2's judgment is meant. `cli.py`'s `route` verb returns
`"certified": entry["certified"]` — the non-inferiority status, to an operator, in the JSON the persona round found them
trusting. That is the online path and it is in scope: the key is renamed `validated`, which is the same rename applied
to the same judgment.

The twelve other references in `policy.py`, `table.py`, `report.py`, `router.py` and `reproduce.py` are the **offline
compile path** and are **out of scope**. `policy.Candidate.certified` there is the calibration-fold judgment under its
own name in its own subsystem, and renaming it would be a second change of its own size. The line is the interface's
own word "online", not a count of references.

**A3.3 — the reason is `unearned_correction`, not amendment 2's `unsupported_correction`.** The code author chose the
first before amendment 2 was written. Theirs is better and is adopted: "unsupported" reads as "a correction this
software does not support", and the defect is that the claim was not earned by the work. Amendment 2's naming is
withdrawn on this point.

## Amendment 4 — amendment 2.4 made every historical record unreadable, and two corrections to my own claims

**A4.1 — the pairing rule is about construction, not about reading, and I wrote it as both.** Amendment 2.4 said a
numeric `bound` with no `bound_provenance` is refused. Applied in `_candidate_from_row` as well as in the constructor,
that makes every row this project has ever written unreadable. Verified on the real artifact:

```
a real v0.1.0 row carries: ['bound', 'bound_kind', 'cost_usd', 'evidence_as_of', 'excluded_because', 'id']
REFUSED: Incomplete  bound=0.9 has no bound_provenance
```

That contradicts v0.2.0's C1 in its entirety — the entry whose purpose is that a log survives its own evolution, and
whose amendment 1 established that **the version decides**. I wrote a rule that refuses the past while adding a
vocabulary meant to describe the future.

**Reading is not certifying, and the two halves separate cleanly.** `BOUND_ESTIMATORS` gains `unrecorded`, and
`_candidate_from_row` supplies `BoundProvenance(estimator="unrecorded", confidence=None, corrected_over=())` for a row
below `schema_version` 3. The row reads. It says truthfully that the bound's provenance was never recorded, which is a
different statement from the record being unreadable.

And `admissible` **refuses** a candidate whose provenance is `unrecorded`, with its own reason
**`unrecorded_provenance`** — distinct from `unearned_correction`, which is a claim that was made and not earned, where
this is no claim at all. So a historical log stays readable and a historical bound stays unusable for a *new*
certification, which are both C1's purposes rather than a compromise between them. A historical record's own
`certified` field is untouched: it says what it said, and the falsifier reading it is a separate question from routing
on it today.

The constructor's pairing rule stands unchanged for **new** candidates: `serve.candidate_set` and `cli.cmd_assign` may
not build a bound with no provenance, which is where the defect actually lived.

**A4.2 — I attributed the phase-5 failure to the wrong criterion.** Amendment 3 said the live run flagged this as a
`no_false_certification` failure. The code author checked and reported that both `docs/verify/v0.1.0-accept.json` and
`docs/verify/v0.2.0-accept.json` show that criterion passing. Verified here: the v0.2.0 run's only failure is
**`default_is_not_a_hiding_place`**, and `no_false_certification` passes in both.

Amendment 3's argument does not depend on it — the two branches genuinely fill one field from two judgments, which is
readable in the code — but the citation was wrong and the author was right to leave it out of a comment rather than
assert it. Corrected here rather than quietly dropped, because a wrong citation in a contract is the class of defect
this release exists to fix.

**A4.3 — three tests encode the defect, which is the strongest evidence C1 is real.** All in `tests/test_serve.py`,
one shared root cause: the helper never supplies `floor` to `route_once`, so each assertion depended on `certified`
reflecting `policy.validated` regardless of any bound-against-floor check.

| test | asserted | under C1 |
|---|---|---|
| `test_a_free_seat_goes_to_the_reserved_candidate_and_is_recorded` | `certified is True` with **no floor given at all** | `False` |
| `test_a_certified_decision_whose_chosen_candidate_is_below_the_floor_is_caught_end_to_end` | its own docstring: "the policy says certified, the bound says otherwise, and the offline checker catches it" | nothing to catch — the online path no longer certifies it |
| `test_the_loop_writes_a_log_the_acceptance_checker_reads` | `unlabelled_certified == 2` | `0` |

The second is the sharpest: a test whose docstring describes the conflation as the *intended* behaviour, written when
that was the design. It changes deliberately as a wire change, and the falsifier it exercised is now catching nothing
because the defect it was built to catch cannot occur — which is the outcome, not a regression.

## Amendment 5 — amendment 4.1 made every historical certification report the mechanism as broken

Surfaced by the integrator's own fixture pass, not by either C1 author, and it is a defect in amendment 4.1 rather than
in anyone's code. Reproduced on the real artifact:

```
the historical decision recorded certified = True
check_certification says: ["certified but the chosen candidate 'box' was not admissible: unrecorded_provenance"]
no_false_certification: FAIL -- "the mechanism is broken rather than mistuned"
```

Amendment 4.1 fixed "a historical row is readable" and created "a historical row's certification is unauditable".
Every pre-C1 certified decision now fails the falsifier on replay — **not only the ones that were wrong** — and SCOPE
section 12 reads that criterion's failure as evidence the mechanism is broken. So a correct historical log now
accuses the mechanism.

**The distinction is the same one I have now drawn three times in this release and did not carry far enough.** Reading
is not certifying — amendment 4.1. Certifying a *new* decision is not auditing an *old* one — this amendment. For a
row whose bound's provenance was never recorded, the honest verdict is not "this was not admissible"; it is **"this
cannot be verified"**, and `accept` has had a third verdict for exactly that situation since v0.1.0.

**`record.check_certification` distinguishes not-admissible from not-checkable.** A candidate refused for
`unrecorded_provenance` yields an *unverifiable* finding rather than a violation, reported separately.

**`accept.no_false_certification` returns `UNSUPPORTED`** when every certified decision it holds is unverifiable, and
when the population is mixed it computes over the verifiable ones and its detail names how many it could not check —
which is C11's rule from the previous release, applied to a second way a population can be incomplete. It never
reports `FAIL` on a row it cannot check, because a falsifier whose silence is read as evidence must not speak from
absence.

`admissible` is unchanged: refusing `unrecorded_provenance` is correct for a **new** routing decision, where a bound
with no recorded provenance cannot support a claim about this request. What changes is only what an audit of an old
record concludes from the same refusal.

**Two tests are reclassified by this.** The fixture pass filed
`test_record_versioning.py::test_accept_reads_a_v010_row_without_a_schema_version_key` and
`journeys::test_p2_old_decisions_log_gets_a_full_accept_report_not_a_crash` as obsolete-bordering-on-encodes-the-defect,
and was right to hesitate: they are neither. They assert the correct behaviour and amendment 4.1 broke it. They stay
as they are and this amendment makes them pass again.

## Amendment 6 (C1): certification is a conjunction, and amendment 5 mis-stated its own consequence

Two corrections, both found at integration, both to amendments I wrote earlier in this release.

### 6.1 `certified` needs the rules to be validated AND the candidate to be admissible

Amendment 3 replaced `certified = bool(got["validated"])` with `certified = admissible(drawn, ...)`, and **that traded
one one-sided reading for another.** `policy.validated` records whether this policy's rules ever cleared
non-inferiority on a held-out fold. Admissibility is a property of the **candidate**; validation is a property of the
**rules that reached it**. A decision taken by rules that never cleared non-inferiority cannot claim the floor however
good the candidate's own bound looks, and a decision by validated rules cannot claim it for a candidate under the
floor. Certification needs both, so `route_once` computes the conjunction.

Caught by `test_serve.py::test_an_uncertified_policy_never_certifies_however_the_state_looks` — a test that had been
passing for the wrong reason and started failing for the right one the moment the fixture declared a floor. It is the
phase-3 case where a test fails and the contract, not either worker, is what was wrong.

### 6.2 Amendment 5's closing claim about two tests was false

Amendment 5 says those two tests "stay as they are and this amendment makes them pass again." They do not. Their
assertion was `verdict == PASS`, and the verdict amendment 5 produces over a log with no recorded provenance is
`UNSUPPORTED` — which is amendment 5's entire point. **Both are changed deliberately, as wire changes**, and the
reason is written beside each assertion: a `pass` there would be the criterion claiming a check it did not perform.

I wrote the amendment from the mechanism's intent and did not run it against the two tests it named. That is the
same defect class as a comment describing behaviour the code does not have, one level up.

### 6.3 The route fixture never declared a floor

`test_serve.py`'s shared `route()` helper omitted `floor`, so every test in that file exercised the `floor is None`
path without saying so, and three of them asserted `certified is True` against a certification nothing had a basis
to grant. `floor=0.80` is added to the helper — a fixture adaptation, not a changed assertion.

The consequence is worth stating: with the floor declared, **`route_once` can no longer produce a falsely-certified
record at all**, because the decision and the falsifier now share one predicate. So
`test_a_certified_decision_whose_chosen_candidate_is_below_the_floor_is_caught_end_to_end` was split in two — one
test asserting the loop refuses to write the record, one asserting the falsifier still catches such a row from any
other writer. The second is not redundant: `Decision` accepts the combination on purpose, because refusing it at
construction would move the check into the writer and leave nothing able to audit a log written by an older
mechanism version or a second implementation.

## Amendment 7 (C1): a v0.1.0 `bound_kind` is reported, never translated

A real v0.1.0 candidate carries `bound_kind`, which C1 replaces with `bound_provenance`. The reader reports it in
`ignored` (C12's contracted behaviour from the previous release) and **deliberately does not translate it into a
provenance.**

Translating `bound_kind: "lcb"` into `estimator: "clopper_pearson_fixed_sample"` looks like preserving information
and is the opposite. The defect C1 exists to close is that `bound_kind` was a free string: three records with the
identical fabricated `bound` of 0.99 and `bound_kind` of `lcb`, `point_estimate` and `asserted_by_operator` all
certified identically, because nothing read it. Turning such a string into a recorded estimator would launder an
unchecked claim into an attributable one — strictly worse than reading the bound as `unrecorded` and saying so, which
is what amendments 4.1 and 5 already make safe.

Three tests asserting `ignored == []` against the real fixture are updated to name the two keys. Their subject was
never that nothing is ignored; it was that the reader survives a field it does not model and says which one.

## Amendment 8 (C6): the set comes from the ledger's outcomes, not from whatever `ranked` contains

C6 says the candidate set comes from the ledger rather than the policy's rules, and A3 justified it by observing that
`assign_family`'s `ranked` already covers every candidate with an outcome for both shipped families. Re-derived before
writing code, that observation holds — and the way it can stop holding is now known and was not stated.

`assign_family` builds `arrangements` inside a loop that can `continue` past a tier into an `excluded` map, on a
declared `latency_slo_p95_ms` above the tier's recorded p95 and on `min_completion_probability`. A tier excluded there
reaches neither `arrangements` nor `ranked`. A set derived from `ranked` would therefore omit it — which is exactly the
invisibility C6 exists to end, reintroduced through a different door.

It is unreachable with the shipped evidence, and that is the reason to state it rather than to rely on it: the retail
records carry `p50` and `mean` and no `p95`, so `slo` is `None` and the guard never fires. Measured at
`latency_slo_p95_ms` of `None`, 20000 and 15000, `excluded` was empty every time. An omission that cannot happen today
because of a missing field in the evidence is an omission waiting for someone to record that field.

**So the set is derived from every candidate the ledger records an outcome for**, and a candidate `assign_family`
excluded is named with the reason it was excluded and no bound — the same treatment C6 already gives a candidate the
ledger cannot bound. Deriving from `ranked` and adding a check that the two agree was rejected: it is a watcher over
the omission rather than a construction in which the omission cannot occur.

## Amendment 9 (C2): an artifact that recorded no digest is not an artifact that recorded a different one

C2's interface says a caller-supplied `policy_version` that disagrees with the artifact's digest is refused naming
both, "by `decide.parameter`'s established rule". Read against the code, that rule has **two** refusals and the
interface named one.

`parameter` refuses a supplied value for a name the artifact never recorded with a *different* message — "an artifact
that did not record the parameter cannot confirm one" — precisely because an absence is not a competing value. The
first implementation of `_confirmed_policy_version` collapsed both cases into `does not match ''`, which reports the
absence of a digest as a rival claim to the caller's. That is the same shape of over-statement C1 spent five
amendments removing from `certified`, one layer out.

So `_confirmed_policy_version` refuses an absent digest on its own terms, and says where a digest comes from: a policy
from `compile_policy` carries one, a policy built by hand has nothing to check against. Both refusals stay refusals —
the fix is what the message claims, not whether it fires.

**This is what makes the 21 broken `route_once` tests a wire change rather than breakage.** They hand-build
`decide.Policy(...)`, which carries no digest, and pass `policy_version="p1"` — a fabricated label standing where the
mechanism now derives a value. C2's whole sentence is that a value the mechanism can derive is not a value a caller
supplies, so the adaptation is to stamp the fixture's policy with its own real digest and stop supplying the label.
A fixture that keeps supplying one is asserting the state this entry removes.

## Amendment 10 (C6): the set carries ids and no number, because R1 rejected the number

C6's interface says `candidates_for(tiers, family) -> dict[str, float | None]`, "every candidate with an outcome for
the family, mapped to its bound or to `None`". Implemented literally, that bound is
`clopper_pearson_lower(attempted, solved, 0.05)` — **the fixed-sample single-test absolute bound this contract's own
rejected-alternatives table turns down under R1**, in R1's own words: SCOPE section 6 disqualifies it, and shipping it
"would relocate the defect rather than close it — a caller's honest guess becomes the compiler's miscalibrated
assertion, which is worse because it carries the compiler's authority."

So the interface asked for the alternative the table rejected, and the code author implemented what the interface said.
That is the contract's defect, not the implementation's, and it is the reason the table records reasons: without R1's
reason written down, the number would have shipped with the compiler's authority behind it.

**Two measurements decided it rather than taste.**

| | |
|---|---|
| At 20 of 20, the bound is **0.8609** | which is exactly `0.05 ** (1/20)`, C5's own **ceiling**. At the top of the range the number is a property of how many items were run, not of the candidate it is filed under. |
| For `tool-agent-user-retail` (floor 0.92), **no** candidate clears | 0.7174, 0.8609, 0.7839 against a floor above the ceiling. C5's fact arriving through C6's door, as a number the artifact asserts. |

And nothing read it. `serve.candidate_set` takes the per-request bound from the caller's `bounds`, so the artifact's
value was consulted only for which ids belong in the set — making it **the fourth value this codebase records and
never reads**, beside `bound_kind` and the two `"warning"` strings this same release removes. R16 rejected shipping the
ceiling as a third one. Shipping a fourth through a different entry is the same defect with a different label.

**`candidates_for` returns `tuple[str, ...]`**: the ids, sorted. `compile_policy` writes them as a list;
`Policy.candidates` is a tuple defaulting to empty; `from_dict` still refuses an artifact with no `candidates` key.
Membership is the whole claim, and it is what `serve.candidate_set` needed — `no_bound` is derived at decision time
from the caller's `bounds`, exactly as before.

**Amendment 8's fold-back disappears with it.** `candidates_for` reads each tier's own recorded outcome and never
calls `assign_family`, so a tier `assign_family` excluded is in the set for the same reason every other measured tier
is. There is no second pass putting back what a first pass dropped, which is what amendment 8 asked for and did not
get in a form that terminated: the fold-back was a watcher over the omission, and this is a construction the omission
cannot occur in.

### And the refusal is not gated on the artifact carrying rules

`from_dict`'s first implementation refused only an artifact that carried `rules` and no `candidates` key, to spare
fixtures focused on other entries. A **rules-less** artifact is the sharper case, not the exempt one: it is precisely
what the shipped ledger produced in the incident C6 exists to close — the compiler certified nothing on a 20-item
cohort, `rules` was empty, the set collapsed to one member, and 400 consecutive draws returned `no_eligible_arm`.
Exempting that shape reads the incident's own artifact happily with an empty candidate set, which is the defect
wearing the fix's clothes. The refusal is unconditional, and the nine fixtures it broke carry the key a real artifact
carries.

