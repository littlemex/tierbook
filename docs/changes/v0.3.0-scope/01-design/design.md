# Phase 1 — the design for v0.3.0, its assumptions, and the findings that go to triage

This is the phase-1 output: a design statement, the assumption table, and design-level findings. **It does not decide
the scope.** That is phase 2's job.

## 1. The design statement

### What this exists to do, and who operates it

v0.3.0 makes the mechanism able to **claim what SCOPE section 2 clause 1 says it claims**, and to **produce the labels
its own criteria need**. Those are the two things standing between v0.2.0 and a loop that closes, and they are not
independent: a bound that nothing can check and a label that nothing produces are the same gap seen from the two ends
of one arc.

v0.2.0 made the log survive its own evolution and put a randomiser above the deterministic policy. What it did not do
is give any component the authority to say whether a candidate's success rate clears a floor. `serve.route_once` takes
`bounds` from its caller; the compiled artifact carries the floor and not the bound; `no_false_certification` computes
admissibility from the caller's own number. So the falsifier that SCOPE section 12 calls decisive is a self-consistency
check, and a caller who asserts `0.99` for a tier the ledger measures at 70% passes it.

Operated by whoever runs the routing layer. Read by whoever later asks whether a certified assignment was entitled to
be certified — who is not the same person, and who has only the artifact and the log.

### The responsibilities, and which layer owns each

| Value | Owner | Why not elsewhere |
|---|---|---|
| A candidate's **absolute** lower bound on success for a family | the compiler | It is a function of the ledger's `solved`/`attempted` and a confidence level. A caller supplying it is asserting a measurement, which is what `load_config` already refuses through the config path and what `route_once` accepts through the call. |
| The **paired** lower bound against the reference | the compiler, unchanged | Already so. It answers non-inferiority, which is a different question from clause 1's, and conflating the two is what left clause 1 unimplemented. |
| Whether a bound is fresh enough to claim | `record.admissible`, unchanged | Already so, and C6 made it per-candidate. |
| **Which candidates exist at all for a family** | the compiler | Today `serve.candidate_set` derives this from the policy's rules, so a candidate with no rule is invisible to exploration. The set of candidates and the set of rules are different objects and only one of them is currently written down. |
| **What produces a label** | the operator's suite, NOT this mechanism | A7 settled it: `cli.py` states that running a benchmark is somebody's suite and anything writing a record in the documented shape is a valid producer. A component here that invoked a labeller would be this mechanism running that suite. |
| **Whether a label is late, absent or arrived** | `record.classify_label`, unchanged | Already so, and correct. What is missing is a documented way to hand it an outcome at all — see F4 as revised. |
| The exchange rate — accuracy given up per unit of charge saved | the compiler, and it already does | A6 falsified the assumption that it was absent: `report.frontier_for` marks the Pareto set and `compile --report` reaches it. It plots the **paired** bound, so it inherits F1 rather than being new work. |

### The contracts at each boundary, failure included

**compiler → routing.** Routing may assume every candidate the family has is named in the artifact with an absolute
bound, its confidence level, and the evidence it came from. It may **not** assume a bound it was handed by a caller
agrees with the artifact. On disagreement the mechanism refuses and names both, by amendment 2's rule for the floor.

**compiler → routing, on absence.** A candidate the ledger cannot bound — no `attempted`, or a cohort too small for
the declared confidence — is named with **no** bound rather than omitted. Omission is what makes a candidate invisible
to exploration today, and the fix is not to invent a bound for it but to say it has none.

**labeller → the log.** The log may assume a label arrives, or does not arrive, within the family's declared maximum
latency, and that `classify_label` decides which. The labeller may **not** decide the label state; it produces an
outcome or fails, and the classification stays where C4 put it. On labeller failure the outcome is recorded as a
failure to label, distinguishable from a label of failure — a distinction the record already has vocabulary for and
nothing currently produces.

**routing → the falsifier.** The falsifier may assume the bound in the record came from the artifact, because the
record carries which artifact. On a record whose bound has no artifact reference, it refuses to certify rather than
verifying the number against itself.

## 2. The assumption table

Every load-bearing assumption checked in this phase, not phase 5.

| # | Assumption | Load-bearing | How it was checked | Result |
|---|---|---|---|---|
| A1 | The ledger carries enough to compute an absolute lower bound per candidate per family | **yes** — the whole design rests on it | computed `clopper_pearson_lower(attempted, solved, 0.05)` for every candidate and family in the shipped ledger | **TRUE.** Every candidate with an outcome has both counts |
| A2 | Doing so changes the shipped example's answer | yes | computed the bounds against each family's declared floor | **TRUE, and harder than expected.** At `agentic-coding`'s floor 0.80 only the reference clears (0.8609 against 0.5990 and 0.4922). At `tool-agent-user-retail`'s floor 0.92 **nothing clears, including a 20-of-20 reference** |
| A3 | `assign_family`'s `ranked` already enumerates every candidate, so the set is derivable without new measurement | **yes** | compared `ranked`'s single-tier members against the tiers with an outcome, per family | **TRUE.** `ranked` covers every measured candidate for both families |
| A4 | An exact 95% lower bound on a 20-item cohort is wide enough that few candidates clear a 0.80 floor | yes | computed the ceiling `alpha ** (1/n)` for a perfect score at several cohort sizes | **TRUE, and it yields a stronger fact than the assumption asked for** — see F8. n=20 ceiling 0.8609; n=50 0.9418; n=100 0.9705; n=1000 0.9970 |
| A5 | `Candidate` can carry an evidence reference without breaking C1's reader | yes | added `evidence_ref` to a real v0.1.0 candidate row and read it through `from_row` | **TRUE.** Returned as `ignored == ['candidates[0].evidence_ref']`, version 1, no refusal — which is what amendment 1 built |
| A6 | Nothing in the repo already computes an exchange rate under another name | no | grepped for a frontier and read what it produces | **FALSE.** `report.frontier_for` marks the Pareto set over `quality_lcb` and `cost_per_request`, and `compile --report` reaches it. F5 is revised: the rate is computed and it is computed over the **paired** bound, so it inherits F1's problem rather than being absent |
| A7 | A labeller can be invoked from here without the mechanism holding a socket, which SCOPE forbids | **yes** — if false the labeller cannot live here at all | read `cli.py`'s own statement of the boundary | **FALSE, decisively.** *"There is no `measure` either... running a benchmark is somebody's suite, and anything that can write a record in the documented shape is a valid producer of one."* A component that invokes a labeller is this mechanism running somebody's suite. F4 is revised below |

## 3. Design-level findings, for phase 2 to triage

**F1 (class H, undeclared capability).** SCOPE section 2 clause 1 names a quantity the mechanism has never computed.
The mechanism has been shipping decisions whose certification rests on a number supplied from outside, and the
document says the number is the candidate's corrected lower bound on success. This is the release's centre.

**F2 (class G, duplicated knowledge).** The bound has two homes and one of them is a function argument. The floor was
in the same state before amendment 2 and the fix is the same rule; what is new is that the bound is a *measurement*
rather than a requirement, so its home is the artifact rather than a declaration.

**F3 (class D, ordering).** `serve.candidate_set` derives the candidate set from the policy's **rules**. A candidate
with no rule is absent from the set, so exploration cannot reach it, so it is never labelled, so its evidence never
refreshes. That is assumption A3's ratchet from v0.2.0 in a second form, and the door C3 opened does not reach it.

**F4 (class H), revised by A7.** The gap is not that nothing invokes a labeller — a component that did would cross the
boundary `cli.py` states in its own first paragraph. The gap is that **`Log.attach_outcome` has no CLI verb.** Eleven
verbs exist and none attaches an outcome, so an operator following the documented path cannot produce a labelled log at
all without importing the library. Every criterion that needs a realised rate is therefore permanently `unsupported`
for anyone using the documented surface, which is most of section 12 — and the mechanism reports that as a missing
measurement rather than as a missing verb, so the report blames the operator's data for the absence of a door.

**F5, revised by A6.** The exchange rate is computed. `report.frontier_for` marks the Pareto set over `quality_lcb`
and `cost_per_request` and `compile --report` reaches it. But `quality_lcb` is the **paired** bound against a reference,
not the absolute one clause 1 names, so the frontier an operator reads to choose a floor is plotted on a different axis
from the one the floor is compared against. That is worse than absence in one specific way: it looks like the right
picture.

**F6.** The three remaining entries in `MISSING_FOR_A_CLOSED_LOOP` are not equal. Anytime-valid bounds become
**load-bearing the moment exploration feeds evidence back**, because the cohort then grows under a data-dependent
stopping rule. Change-point detection and the reserved candidate's capacity value do not block the loop. Treating the
three as one backlog hides that one of them is a prerequisite for the arc this release would close.

**F7.** A bound derived at a declared confidence makes the confidence level a value with two possible homes — the
compiler's default and the family's declaration — which is amendment 2's defect waiting to happen a third time. It
should be settled before it is written, not after.

**F8, from A4 and stronger than the assumption asked.** A declared floor above `alpha ** (1/n)` **can never be
cleared**, whatever the measurement says, because that is the lower bound a perfect score yields on a cohort of that
size. The shipped ledger declares `tool-agent-user-retail` at a floor of **0.92** on a **20-item** cohort whose ceiling
is **0.8609**. The floor and the cohort size are in contradiction, and today nothing notices because the bound the
floor is compared against comes from the caller.

This is checkable at compile time and it is the cheapest thing in this release: the mechanism cannot derive what
accuracy an operator requires, but it can refuse a requirement that no measurement of the size available could ever
support. It also gives the operator the number they actually need, which is how many items the cohort must have for
their floor to be reachable at all.

| cohort | ceiling at 95% |
|---|---|
| 20 | 0.8609 |
| 50 | 0.9418 |
| 100 | 0.9705 |
| 200 | 0.9851 |
| 1000 | 0.9970 |

**F9.** F1's fix makes the shipped example refuse for one family entirely — no candidate clears 0.92, including the
reference at 20 of 20. Whether the example ledger is then still a usable example, or has to grow a cohort or lower a
floor, is a scope question phase 2 must answer rather than discover. The README's quickstart is verified end to end by
the journey layer, and it would change.

## 4. Refusing to proceed on one point

A7 falsified the design's own responsibility table before the rounds ran, and the revision is not cosmetic: F4's fix
moves from "build a component" to "add a verb", which is a different size of change and a different risk. Phase 2
should treat the label path as a **surface** question rather than a mechanism one, and any proposal that reintroduces a
labeller-invoking component has to answer `cli.py`'s first paragraph.

## 5. Revisions after the first review round, and one of them moves the release's centre

### R1 — the bound this design proposed is the one SCOPE section 6 disqualifies, in those words

Section 6, quoted in full because the wording is the finding:

> A candidate is admissible for a family only when a lower confidence bound on success — **anytime-valid**, because
> bounds are recomputed continuously and admission happens at a data-dependent stopping time, so fixed-sample
> intervals are anti-conservative here — clears the floor, computed over the declared multiplicity family
> (candidates × families × tenants × the selection process itself) on at least `n` effective samples whose validity
> assumptions still hold.

Every number in this document's assumption table and in F8's ceiling table was computed with
`accept.clopper_pearson_lower(attempted, solved, 0.05)`: fixed-sample, single-test, flat α, no multiplicity term.
That is precisely what section 6 rules out for this use, and `decide.MISSING_FOR_A_CLOSED_LOOP` already says so about
this project's own margins. v0.2.0 shipped exploration, so the data-dependent stopping time section 6 warns about has
already arrived — every compile after a label lands is that case.

So F1 as designed does not close the gap the design statement opens with. It **relocates** it: a caller's
unverifiable assertion becomes the compiler's own miscalibrated one, which is worse in the specific way that matters,
because it carries the compiler's authority. **The release's centre is therefore not "compute the absolute bound" but
"compute a bound that is corrected in section 6's sense"**, and the anytime-valid term stops being a backlog item and
becomes F1's precondition. F6 said this and this document did not obey it.

### R2 — and section 6 contradicts a clause v0.2.0 shipped and I wrote into SCOPE section 2

Section 6, two paragraphs later:

> A bound becomes unusable for admission when its **declared validity assumptions or its freshness contract no longer
> hold** — not merely because it is old. Age alone invalidates nothing; a detected change point does.

v0.2.0's C6 made freshness part of admissibility keyed on `max_evidence_age_days`, and amendment 6 added a fourth
clause to SCOPE section 2 saying the evidence must be "no older than the family's declared limit." **Age alone is
exactly what that clause tests, and section 6 says age alone invalidates nothing.** So v0.2.0 substituted an age
threshold for the change-point detection section 6 names, and then I wrote the substitution into the governing
document as though it were the requirement.

This is not a small correction. It means change-point detection is not one of three interchangeable backlog entries:
it is **the thing that is supposed to invalidate a bound**, and the age limit is a placeholder standing where it
belongs. It also means C3's staleness override, and the one-way door assumption A3 that justified it, are reasoning
about a proxy rather than about the condition. Phase 2 has to decide whether v0.3.0 replaces the proxy or states
plainly that it is one — and stating it plainly requires amending SCOPE section 2 clause 4 rather than leaving two
sections of one document disagreeing.

### R3 — F8's refusal is wrong, and the reason is in the purpose

Section 2: *"There is no 'choose nothing' ... the request is served either way."* Section 8's day-one case serves the
declared default uncertified while evidence accrues. Section 12 makes "generic by sending everything to the default" a
**passing** state unless the acceptance oracle can name a feasible admissible candidate — which for an unreachable
floor it structurally never can. And the project's own statement of purpose says a degenerate output is a correct
output when that is what the measurements support.

An unreachable floor is not a malformed declaration. It is a true fact about the evidence budget, the same in kind as
having no evidence yet. F8's diagnostic — the ceiling, and the cohort size the floor would need — is right and worth
keeping; wiring it to a compile-time abort turns a purpose-correct degenerate state into an outage for that family.
F9's worry that the shipped example would "refuse entirely" was the tell, and I read it as a problem with the example
rather than as a problem with the refusal.

**Revised:** the ceiling is computed, recorded on the artifact, and reported loudly — including how many items the
cohort needs for the declared floor to be reachable — and the family runs through its declared default, uncertified,
by the machinery section 8 and `record.admissible` already provide.

### R4 — F5 is co-equal with F1, not behind it

Section 3 calls the exchange rate part of the deliverable and says a floor chosen without seeing it is a guess wearing
a policy's clothes. The floor is now a per-family declaration an operator must supply. Shipping a gate keyed to the
absolute bound while the frontier they read to choose that gate's threshold is plotted on the paired bound leaves them
guessing with a plausible-looking chart. Both ends of the same quantity, and only one was called the centre.

## 6. The second round: what a person is told, and seven things this design did not contain

The persona round asked what an operator is told rather than what the code does. Two of its findings are larger than
anything in section 3, and both were verified here directly rather than taken on report.

### R5 — `certified` names two different judgments, in the JSON a person trusts in production

`decide.py:454` sets `certified = entry.get("status") == "assigned"`, which is the **non-inferiority validation
status**: a held-out fold supported the choice against the reference. `record.check_certification` computes something
else under the same word: whether the chosen candidate was **admissible under SCOPE section 2**, which is the bound
clearing the floor plus authorisation, latency and freshness.

`tierbook route` returns `"certified": true` from the first. An operator who declared a floor of 0.92 reads that and
has every reason to believe their quality bar was met. It was not checked in that path at all. Two structurally
different claims share one field name, and nothing in the output says which one is being made.

This is worse than F1 and F5 and it subsumes part of them. F1 says the mechanism never computes the absolute bound;
this says that where it does make a certification claim online, the claim is about a different quantity and is not
labelled as such. Fixing F1 without renaming or splitting this field would produce two correct judgments and no way to
tell them apart — and the field is in the artifact and the record, so both readers inherit the ambiguity.

### R6 — the record cannot name the artifact it came from, so the falsifier's premise is false

The design's contract section asserts that the falsifier may assume the bound came from the artifact "because the
record carries which artifact." It does not. `Decision`'s version-shaped fields are `feature_vector_version`,
`policy_version`, `mechanism_version` and `schema_version`. `policy_version` is a **hand-typed CLI string defaulting
to `"unversioned"`** (`cli.py:772`). There is no hash of the compiled table, no registry version, nothing derived from
the artifact's content.

So the contract this design wrote down is not merely unimplemented — it is unimplementable against the current schema,
and I wrote it as though it held. Whoever inherits a log six months later cannot identify which compiled table
governed a decision, let alone re-verify a bound inside it.

And `bound_kind` — the field that looks like it exists for exactly this — is decorative. Three records with the same
fabricated `bound` of 0.99 and `bound_kind` of `lcb`, `point_estimate` and `asserted_by_operator` all certify
identically, because `admissible` compares only `bound < floor`. The vocabulary is recorded and never read, which is
C7's defect class in a field nobody scanned.

### R7 — an impossible floor and no floor are operator-indistinguishable

F8 said the contradiction goes unnoticed. It is stronger than that: compiling the shipped ledger with the unreachable
floor of 0.92 and compiling it with **no floor declared at all** produce the same `route` response, `certified: true`,
for the same candidate, with no warning either way. There is currently no differential signal between "the floor
cannot be enforced" and "there is no floor."

### The remaining findings from that round, for phase 2 rather than for revision here

- `explain` — the verb whose stated job is what the ledger says about a family — has no floor and no absolute-bound
  concept. It is an operator's first natural step for sanity-checking a floor and gives them nothing toward it.
- `Log.attach_outcome` is absent from `README.md`, `SCOPE.md` and every `--help`. It appears only under
  `docs/changes/`, `docs/releases/` and `docs/reviews/`, which a reader of the documented surface has no reason to
  open. F4 said there is no verb; there is also no mention.
- `tierbook logs` silently accepts a **decision** log — the wrong shape for it — and returns a plausible,
  self-consistent report. It exists to turn raw traffic into a ledger record. An operator looking for the door to
  attach a label types the nearest-sounding verb and gets an answer that is not one.
- `pyproject.toml` declares `requires-python = ">=3.10"` while the suite has been verified green on 3.9.6 throughout
  this and the previous release. The declared minimum and the tested minimum disagree; one of them is wrong.

## 7. What the two rounds together change about the release

Before the rounds this document said the centre was computing the absolute bound. After them:

1. **The bound must be corrected in section 6's sense** — anytime-valid, over a declared multiplicity family — or the
   compiler's authority makes a miscalibrated number worse than a caller's honest guess. R1.
2. **`certified` must mean one thing**, or fixing the bound produces two correct judgments a reader cannot separate.
   R5. This is a naming and contract decision that has to precede the arithmetic.
3. **A record must be able to name its artifact**, or the falsifier has no premise and this document's own contract
   section is fiction. R6.
4. Age is a placeholder standing where a change point belongs, and SCOPE says so in one section while section 2 says
   otherwise because I wrote the placeholder in as the requirement. R2.
5. The ceiling is reported, not refused. R3.
6. The frontier and the gate are two ends of one quantity. R4.

Ordering matters and phase 2 has to decide it: 2 and 3 are prerequisites for 1 in the sense that shipping 1 first
makes the ambiguity and the missing provenance harder to fix, not easier. That is class D, and it is the reason this
belongs in phase 1 rather than being discovered during implementation.

## 8. Three facts checked while the remaining rounds ran

**A8 — the multiplicity family section 6 requires includes a dimension the mechanism does not have.** Section 6 says
the bound is "computed over the declared multiplicity family (candidates × families × tenants × the selection process
itself)". `grep -rn tenant src/tierbook/*.py` returns four hits and every one is prose in a comment; there is no tenant
field in the record, the config or the artifact, and SCOPE section 7 is the multi-tenancy section that describes what
does not exist yet. So a bound corrected over three of the four named dimensions is available and the fourth is not.
Whether that is honest or is the same defect as the fixed-sample one — a number that looks corrected and is not —
is a phase-2 decision, and it has to be made explicitly rather than by shipping three quarters of a correction.

**A9 — nothing retires a candidate.** Section 6's sentence is "admitted when it clears, retired when it stops
clearing", and only the first half exists. `grep -rniE "retire|withdraw|demote"` over `src/tierbook/` returns three
hits, all unrelated prose. Admission has a compile path, a policy artifact and a falsifier; retirement has nothing —
no state, no vocabulary, no path. This design's section 1 talks about admission throughout and never once about
retirement, which means it inherited the omission rather than noticing it.

**A10 — the log could feed a change-point detector today.** R2 said age is a placeholder where a change point belongs,
and the obvious objection is that the placeholder cannot be replaced because the data is not there. It is:
`record.Decision` carries `family`, `chosen`, `decided_at`, `label_state` and `label`, so a per-candidate
time-ordered sequence of labelled outcomes is derivable from a log the mechanism already writes. Nothing computes it,
and nothing being able to is a different situation from nothing doing it. The placeholder is replaceable; what it
needs is the labels C4 declared and F4 found no door for.

That last one links three findings that looked separate: **the label path (F4), the change point (R2) and retirement
(A9) are one arc.** A candidate stops clearing because its outcomes moved; the outcomes are labels; the labels have no
documented door; so nothing can detect the move, so nothing can retire the candidate, so age stands in for the
detection. Phase 2 should treat them as one entry or state deliberately why it is splitting them.

## 9. The third round: the ordering claim holds, is understated, and is missing a term

### R8 — the ordering is not merely harder to reverse, it is partly irreversible

Section 7 argued R5 and R6 come before R1 because shipping R1 first makes them harder. The log is **append-only** —
`Log.append` writes immutable JSONL and `Decision` has no update path, which is the property C1's whole reader exists
to preserve. So every decision written between "R1 ships" and "R5/R6 ship" is a permanent record of a correct bound
under an ambiguous `certified` and with no artifact reference. Not friction: debt with no bankruptcy option. The
ordering claim is right and it was undersold.

### R9 — there is a third prerequisite and this document never named it: the tenant term

Section 6's multiplicity family is candidates × families × tenants × the selection process. A8 established that no
tenant field exists anywhere. What A8 did not establish, and this round did, is that **SCOPE section 7 is normative
rather than speculative**: it states that the declared default transfer model applies, pooling across tenants while
holding per-tenant floors, and that *"pooling is a declared policy input, not an emergency measure."* So the document
requires a declaration for which there is no field.

The failure mode is R5's, one level down. If v0.3.0 starts writing a `bound_kind` that asserts "multiplicity
corrected", a reader has every reason to read that as corrected over all four named terms. It would be three, under a
single-tenant assumption nobody wrote down — and `bound_kind` is already decorative, so nothing would catch the
substitution. **A term with cardinality 1 by omission is not the same as a term with cardinality 1 by declaration**,
and only the second is honest.

This makes the prerequisite list three items, not two. Change-point detection is *not* a fourth: R2's remedy —
disclose the age proxy honestly — works without touching R1's arithmetic, whereas tenancy changes the arithmetic the
moment it is added.

### R10 — per-tenant floors is the requirement that would force a rewrite, and the reason is the append-only log again

Of the three futures worth testing, two are extensions. An asynchronous labeller landing days later is already handled:
`classify_label` is three-valued and `max_label_latency_s` is declared per family precisely for it. A ledger a hundred
times bigger is what an anytime-valid bound is *for*.

Per-tenant floors is different. The magnitude of a multiplicity correction is a function of the cardinality of each
term. Today the tenant term's cardinality is implicitly 1 everywhere a bound has ever been computed. The day it is
T > 1, every bound already written was corrected against the wrong value of its own input — not missing a check, wrong
by construction, in an append-only log. That is a rewrite of R1's core computation rather than an addition to it.

### R11 — two pairs that must change together, beyond the ones already named

**`EXCLUSION_REASONS` and retirement.** The vocabulary is closed and every value describes *current* admissibility.
There is no way to say a candidate was retired, only that it currently fails a test that resembles retirement. A9
found retirement absent; this round finds that adding it means extending a closed enum the design treats as
load-bearing, which is the one-way door F3 already hit once.

**`exploration_rate` and the selection-process term.** SCOPE section 5 already lists "tenant shares, priority classes,
exploration eligibility" as a fairness decision. The moment exploration becomes tenant-scoped, the randomiser stops
being one draw per family and becomes tenant-conditioned — which is literally the selection process the correction must
cover. The rate's home and the correction's derivation are coupled twice, and neither the config schema nor R1
anticipates the second coupling.

### R12 — the change point is deeper than R2 said, and A10 and this round are both right about different files

A10 established that the **decision log** carries a per-candidate time-ordered series: `family`, `chosen`,
`decided_at`, `label_state`, `label`. That stands.

This round establishes that the **ledger's evidence** does not. `Evidence` is `path`, `header`, `verdicts`, and the
header carries one `produced_at` for the whole file — confirmed by reading a real evidence file from the shipped
ledger, whose header keys are `family`, `produced_at`, `run_id`, `scorer_version`, `subject`,
`suite_manifest_digest`, `suite_manifest_digest_caveat`, `trials_per_item`. There is no per-item time anywhere.

Both are true and they answer different questions. A change point in the **serving** environment shows up in the
decision log and is detectable from what the mechanism already writes. A change point in the **measured** cohort —
which is what would invalidate a bound computed from the ledger — would need a series the ledger does not have and
cannot be retrofitted with one without changing its schema. So R2's remedy is honest for one and understated for the
other, and phase 2 must say which change point it means. Saying "change-point detection" without that distinction is
how a placeholder gets replaced by a different placeholder.

### R13 — the shipped cadence contradicts section 6's "recomputed continuously"

`deploy/base/compile-cronjob.yaml` runs `0 3 * * *` and keeps the previous artifact on refusal. Section 6 says bounds
are recomputed continuously and that a candidate is retired when it stops clearing; retirement therefore cannot happen
faster than daily, and a refusal freezes it further with the previous artifact still serving. That is a gap between a
stated cadence and a shipped one, and the manifest's own comment says the schedule "is not the interesting part" —
which was true when nothing depended on the cadence and stops being true if retirement does.

## 10. The fourth round: this document commits the defect it complains about

### R14 — the no-dependency stance and section 6 are in real tension, and phase 2 has to choose

`pyproject.toml` declares `dependencies = []` with the reason stated in a comment: *"a component that decides where
money goes should not be able to break because something it did not need moved."* That is load-bearing, not
incidental, and this codebase already has its answer to "we need an exact statistical inversion and cannot import
SciPy": `clopper_pearson_lower` bisects the binomial tail by hand because the inverse is monotone.

Section 6 asks for a bound that is anytime-valid **and** corrected over a four-term multiplicity family. The round
checked upstream rather than asserting from memory and reported that the authoritative general implementation of the
confidence-sequence toolkit (Howard, Ramdas, McAuliffe, Sekhon, arXiv:1810.08240; the authors' `confseq`) is a
header-only C++ library whose mixture-boundary methods need numerical optimisation and special functions. It also
reported a plausible elementary corner — the predictable plug-in empirical-Bernstein variant of Waudby-Smith and
Ramdas, arXiv:2010.09686 — whose bound reduces to running sums and a Bernstein penalty inverted with arithmetic and a
log.

**And it flagged the limit of its own evidence**, which is the part worth keeping: that formula came from an automated
fetch over a rendered copy of the paper, not from reading the paper or the reference implementation. So it is a lead,
not a citation. This project's section 6 exists because a point estimate was trusted once, and adopting a bound from a
summary would be the same mistake with more machinery.

So the tension is real and phase 2 chooses between (a) staying inside the elementary corner, accepting its slack, and
verifying both the confidence sequence and a separate multiplicity-spending rule line by line against a reference
before shipping — the `clopper_pearson_lower` precedent; or (b) crossing the dependency line that `pyproject.toml` and
SCOPE both currently treat as load-bearing. There is no verified closed form for the *composition* of a per-candidate
confidence sequence with a four-axis correction; that is two literatures, and gluing them wrong is how section 6 came
to be written.

### R15 — R6's fix already exists in this codebase under another name

`policy.registry_version` is a sha256 over every tier record, and its docstring says *"a hash of everything the
decision was taken from, so a decision can be replayed."* The ledger already has content-addressed provenance. What
lacks it is the **compiled policy**: `policy_version` is a hand-typed CLI string defaulting to `"unversioned"`. So R6
is not a new provenance scheme to design, it is giving the artifact the treatment the ledger already gets. Naming that
matters, because inventing a second scheme beside `registry_version` would be F2's defect in the provenance layer.

### R16 — "report loudly" has a shape here, and adopting it as-is would repeat a defect three times

The round found that `"warning"` strings are already written into compiled artifacts in two places and that **nothing
reads them**: zero reads of the key across `src/` and `tests/`, confirmed here. That is exactly `bound_kind`'s
condition, which R6 called decorative, and exactly what C7 built a producer-tied test for in a third vocabulary.

So R3's revision — report the ceiling loudly rather than refusing — has an established surface to use, and using only
the surface would make this the **third** value recorded and never read. The ceiling has to ship with something that
reads it, or it is a comment in JSON.

### R17 — and this document re-derived a finding the project had already named, which is F2's defect at the meta level

v0.2.0's `CONTRACT.md` amendment 16 named this exact finding **C13**, established that the artifact does not carry the
quantity SCOPE clause 1 needs, and closed with: *"C13 goes to the next release's phase 1 with the observation above as
its input."* Verified at line 1042 of that file.

This document does not mention C13 or amendment 16 anywhere. It re-derived the same finding from scratch as F1 and F2
via A1 and A6. The house style is to name a finding once and carry the name across documents — `C4`, `C6`, `C7`,
"amendment 2's rule" — and not doing it for the one prior finding that is this release's actual origin is the
duplicated-knowledge class F2 complains about, committed by the document complaining.

**Corrected here rather than in phase 2: F1 and F2 are C13, resumed.** The new material is what A1, A2, A4 and A6
measured about it, and R1's finding that the bound C13 asked for has to be corrected in section 6's sense rather than
merely moved into the artifact — which is what makes this a design phase rather than an implementation of a deferred
patch.

### R18 — the artifact layout does not match what the last change used

v0.2.0's phase 1 lives in the repository at `docs/changes/v0.2.0-scope/01-design/design.md` with per-round raw output
under `02-findings/`, one file per round per model. This document is at a tmp path and folds four rounds into inline
prose. Before phase 2 it moves to `docs/changes/v0.3.0-scope/` and the rounds split into `02-findings/`, so the
eventual `CONTRACT.md` can cite a specific round the way amendment 16 cites a specific measurement.
