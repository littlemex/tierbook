# What the experiments have asked of the implementation

This file exists because of a policy change made on 2026-09-12, after v0.3.0 shipped: **the mechanism is no
longer built ahead of the research.** The optimisation study is the subject, and the implementation changes only
when an experiment has been held up by something the implementation does or does not record.

So every entry below carries the same two fields, and an entry without them is not a requirement:

- **Where it bit** — the experiment, and the moment it stopped or misled it.
- **What it cost** — what had to be re-run, re-derived, or thrown away.

Nothing here is scheduled. This is the ledger a future release's phase 1 reads from, not a backlog to work
through. An entry may sit here for several releases and then be discharged by one small change, or be deleted
because a later experiment showed the requirement was wrong.

---

## F1 — A tier's recorded outcome does not name the prompt condition it was measured under

**Where it bit.** The J-space routing study, reading the box's residual stream. The stored capture used a terse
instruction (`Answer with the option letter only. Do not explain.`) and the routing ledger's `self-hosted-a`
records an outcome measured with the model explaining before answering. Same box, same 1,187 items:

| | accuracy | per-item agreement |
|---|---|---|
| terse | 0.6243 | — |
| explaining | 0.7447 | **0.7346** |

**One in four items flips.** Every signal fitted under one condition is a signal about a different label under
the other, and neither record says which condition it is.

**What it cost.** Two rounds of conclusions had to be scoped down to "terse only" after the fact, and a GPU
re-run was needed to get the other condition at all. The re-run then produced a *third* number, because reading
an option letter off a position where the model is about to write prose put 1,822 of 2,364 items on `A`.

**What would discharge it.** A tier's outcome carrying the prompt condition as part of what was measured, so
that "the box's accuracy" is not a single number with a hidden argument. `serves` already records the model,
endpoint and deployment; the prompt is the same kind of fact and is currently absent.

---

## F2 — Nothing invalidates an artifact when the candidate it was derived from is replaced

**Where it bit.** Re-deriving the box-tuning pilot's target set. `docs/box-tuning-manifest.json` (created
2026-09-01) names `qwen3.8-27b`, the **dense** box. The shipped ledger serves `Qwen/Qwen3.6-35B-A3B-FP8`, the
**MoE** box. `docs/PREREG-box-cascade.md` states the discipline explicitly — "that makes it a **different
candidate**, so Gate 1 was recomputed rather than inherited" — and Gate 1 was recomputed. The tuning pilot's
frozen split was not.

**What it cost.** The pilot's target set is defined as "the box misses it, no cheap tier solves it, some dear
tier does", so it is a function of *which box*. Re-derived on the MoE: raw target 138 against 168, frozen pool
135 against 167, and **only 105 items in common — about four in ten changed.** The frozen 105 train / 62
hold-out split was a split for a candidate the ledger no longer serves.

**What would discharge it.** A derived artifact recording which candidates' outcomes it was derived from, so a
change to `serves.model` makes the derivation stale by construction rather than by someone noticing. The
mechanism for this already exists in spirit: `registry_version` content-hashes the ledger, and v0.3.0's
`policy_digest` hashes the compiled artifact. Neither reaches a hand-written manifest.

---

## F3 — The price basis behind a derived decision is not recorded with the decision

**Where it bit.** The same re-derivation. The target set's definition needs a cheap/dear split over the nine API
arms, and no static rate card exists in the repository — prices are read from the AWS Price List API at run
time. The split had to be reverse-engineered from prose in three documents and then validated by checking that
it reproduced the original 168 items exactly.

**What it cost.** A day's worth of the derivation was spent establishing an input that the original derivation
had used and not recorded. It was recoverable only because the original count was known; had it been off by one,
the definition could not have been confirmed.

**What would discharge it.** A decision derived from prices recording the price basis it used — not the prices
themselves, which go stale, but enough to re-derive them: the source, the date, and the resulting ordering.
v0.3.0's C2 did exactly this for the compiled policy's own parameters; the same argument applies here.

---

## F4 — `correct` is one Bernoulli draw and nothing records how stable it is

**Where it bit.** Every AUC in the J-space study. The label being predicted is "did this box answer this item
correctly", measured once. The previous release already recorded that this box's own answers move by ±1.6 points
between runs, and F1 shows a 26% flip between prompt conditions. A probe cannot exceed the label's own
stability, so the ceiling on every number in the study is unknown.

**What it cost.** No conclusion could be stated as "the signal is this strong" rather than "the signal is at
least this strong given a label of unknown noise". The adversarial review named this as a confound that caps
every AUC and it could not be quantified, because the repeat data needed is not in the outcome record.

**What would discharge it.** An outcome able to carry a repeat count and the agreement across repeats. The PVC
holds a `repeat-01` run, so the data exists outside the record; what is missing is the record's ability to
say it.

---

## F5 — How an answer was extracted is not part of the outcome

**Where it bit.** The GPU re-run for the explaining condition. The extraction convention — "the option letter is
the next token" — is true under the terse instruction and false when the model explains first. Applied anyway, it
put **1,822 of 2,364 items on `A`** and drove accuracy to 0.1599 against a 0.10 random floor.

**What it cost.** One full GPU run, and a set of numbers that were reported before the break was found. The
failure was loud enough to catch. The same failure at half the rate would have produced a plausible middle value
and been believed.

**What would discharge it.** An outcome recording the extraction rule that produced it, and a refusal when the
resulting answer distribution is degenerate. This is the same shape as v0.3.0's `bound_provenance`: a value
whose meaning depends on how it was produced, currently recorded without that.

---

## F6 — A claim about a signal does not record the baseline it beat

**Where it bit.** The J-space study's own first round, and this one is mine rather than the mechanism's. Issue #1
states "an abstention rule at decision time: AUC 0.5000", reported as structural. It is the tautological AUC of a
constant score. The real decision-time baseline, measured, is a category dictionary at **0.6583** — and that
dictionary is hollow, since within-category it reads 0.4790.

**What it cost.** A round of experiments aimed at the wrong bar, and a recommendation to close the issue that had
to be withdrawn.

**What would discharge it.** Whatever records a signal's strength recording what it was compared against, so
"beats 0.5" cannot be written where "loses to the category prior" is the fact. `accept`'s verdicts already carry
a `numbers` block and a provenance line for the floor they were checked against; a signal's baseline is the same
kind of fact.

---

## F7 — Only one position of the residual stream is ever stored

**Where it bit.** The whole verbalizable-readout question. The stored capture keeps the last prompt position, and
at that position the top token is `Answer` on every item whatever the question was. So "which words light up when
this question is put to the box" was unanswerable from stored data, and looked for a while like evidence that the
words carry nothing.

**What it cost.** A GPU re-run. The re-run then showed the words do track the question — for a law item the
readout moves through `Foreign` → `domestic / national / international / treaties / municipal` → `best / most /
option / correct` → `Answer, E, D` — which the single position had hidden entirely.

**What would discharge it.** Nothing in tierbook: this is a capture-side requirement, recorded here because the
next person to read a residual stream from this box will otherwise store one position for the same reason the
last one did. The note that matters is that a single-position capture is not a cheaper version of a
several-position capture; it answers a different question.

---

## F8 — The signal is weakest exactly where escalation is needed

**Where it bit.** C's first pass in the J-space study, splitting the corpus by the box's own decision depth --
the layer after which its leading option stops changing.

| | items | probe at L28 | probe at L40 | error rate |
|---|---|---|---|---|
| settles early (depth <= 36) | 1,827 | **0.7482** | 0.7762 | 0.278 |
| settles late (depth > 36) | 537 | **0.5350** | 0.6382 | **0.708** |

**On the items the box gets wrong seven times in ten, the workspace readout is a coin.** Where it reads well, the
box is already right three times in four and needs no help.

**What it cost.** Nothing yet -- this is the first measurement to look. But it reframes every AUC reported in the
study: a pooled AUC of 0.75 is an average over a population where the signal is strong on the easy half and absent
on the half that matters, and the pooled number hides that completely.

**What would discharge it.** A criterion able to report a signal's strength CONDITIONAL on the population it will
be used on, rather than pooled over traffic. `accept` already refuses to pool a rate across schema versions for
exactly this class of reason (C5 in the previous release, and C11's incomplete-population rule). The same argument
applies to a routing signal: pooling across a population whose difficulty varies makes the reported strength a
property of the mix rather than of the signal.

## F9 — The workspace names the subject and not its own competence, and a router needs the second

**Where it bit.** B in the J-space study. A cue placed after the question — `Field (math, law, health, ...):` —
lets the readout be scored against a truth that is known for every item, which separates "does the band hold
readable content" from "does it hold self-knowledge".

| layer | names the field (top-1) | chance | predicts its own error (AUC) |
|---|---|---|---|
| 24 | 0.2432 | 0.1429 | **0.3316** |
| 28 | **0.3071** | 0.1429 | 0.3470 |
| 32 | **0.3794** | 0.1429 | 0.3388 |
| 40 | **0.7593** | 0.1429 | 0.4227 |

**The band reads. It reads the subject at two to three times chance, and it says nothing about competence** — the
error AUC is below 0.5 at every layer, so the relation runs backwards. A supervised probe still extracts error
from the same band at 0.74, on a direction occupying 0.081% of the variance, which no vocabulary projection
surfaces.

**What it cost.** Nothing was thrown away; this is the measurement that turned "the readout is empty" into "the
readout is full of the wrong thing". Two earlier rounds had treated a null result on error prediction as a null
result on verbalizability, which it was not.

**What would discharge it.** A router that consumes a signal recording WHAT the signal is about. "The model can
name the topic" and "the model knows whether it can answer" are different facts with different uses — the first
routes by subject, the second by difficulty — and a mechanism that takes one score cannot tell which it was
handed. v0.3.0's `bound_provenance` made the same distinction for a bound; a signal needs it too.

## F10 — A signal read at one depth is not the signal; the trajectory is

**Where it bit.** D in the J-space study, after F8 recorded that the probe collapses to 0.5350 on the 537 items
the box settles late on. That reading was of ONE layer. Taking all 41 layers' margin, entropy and effort as a
trajectory instead:

| population | trajectory | single layer (L28) | error rate |
|---|---|---|---|
| settles late | **0.6148** | 0.5350 | 0.708 |
| settles early | **0.8000** | 0.7482 | 0.278 |
| everything | **0.8321** | 0.7606 | 0.376 |

**The information on the hard group was not absent, it was spread across depth.** And pooled, the trajectory
reaches 0.8321 against the free token-space entropy's 0.8424 — a gap of 0.010, where every single-layer readout
had been losing by 0.05.

Two further readings from the same run: the box's own settling depth is predictable from **layer 8** at 0.6834,
and error itself from layer 8 at 0.7016 — within 0.06 of layer 28. Twenty per cent of the network decides most of
what the whole network will say about its own difficulty.

**What it cost.** F8 was written as "the signal disappears where escalation is needed". That is wrong as stated
and is corrected here: the single-layer signal disappears, the trajectory does not. Two rounds of conclusions
about the workspace band were reading one slice of a quantity that lives along depth.

**What would discharge it.** Nothing in tierbook directly. What this asks of the mechanism is narrower: a signal
recorded for routing should carry **at what depth it was read**, because "0.75 at layer 28" and "0.83 over layers
0-40" cost different amounts to obtain and are not interchangeable. The early-exit consequence is the reason this
matters commercially — a signal available at layer 8 lets the remaining 80% of the forward pass be skipped, and
the box's median output is 687 tokens.

## F11 — Conditioning on a post-hoc quantity mixes distribution shift with absence of information

**Where it bit.** E in the J-space study, after a reviewer named the confound in F8/F10's own numbers. My 0.5350
on the slow group came from a probe **fitted on the pooled calibration fold** and applied to that group. That
cannot distinguish "no information here" from "a direction learned for the other group". Refitting within the
group, plus four other observations, separated them:

| observation | slow (537) | fast (1,827) |
|---|---|---|
| free output-layer entropy | **0.6872** | 0.8027 |
| probe refitted WITHIN the group, L20 | **0.6098** | 0.7350 |
| probe refitted WITHIN the group, L28 | 0.5787 (was 0.5350 pooled) | 0.7779 |
| non-linear (MLP) at L28 | 0.5607 — no gain over linear 0.5601 | — |
| item difficulty from the other nine arms | **0.6144** | 0.8216 |

So: information is **not absent** (entropy reads 0.687 there), the readout is **not non-linear** (the MLP adds
nothing), and part of the collapse **was** distribution shift (0.5350 → 0.5787, and 0.6098 at L20). What remains
is mechanical: this group's answer does not settle until layer 36 or later, so **the band has no self-assessment
to hold yet** — an assessment of a decision cannot precede the decision. That is also why every verbalisation cue
failed in the band.

And a new fact with routing value: **the slow group's errors are not explained by item difficulty.** The other
nine arms average 0.712 on those items while the box manages 0.292. These are items other models solve and this
box alone stalls on — a box-specific weakness, which is exactly the population where sending the request
elsewhere is worth most.

**What it cost.** F8 and F10 both reported a number produced by this confound. Neither conclusion was reversed,
but both were less certain than they read.

**What would discharge it.** Any conditional report of a signal's strength stating whether the model was refitted
within the stratum or carried in from the pooled fit, because those are different quantities and the difference
here was 0.045. Conditioning on a quantity known only after generation (settling depth) also cannot be reproduced
in production; the report has to condition on something available at decision time.

## F12 — The direction is causal, and moving it connects competence to words that reading it could not

**Where it bit.** The injection experiment, which is the first round in this study to MOVE the residual rather
than read it. The error-discriminant direction at L28 was fitted on calibration, frozen, and added to the residual
at doses measured in units of the mean residual norm. Two controls, both required: a random direction of the same
norm, and a direction fitted to shuffled labels.

| direction | dose | `KNOWN - UNKNOWN` logit gap | `guess` stem logit |
|---|---|---|---|
| **real** | 0 | −0.114 | 8.115 |
| **real** | **+2** | **−0.958** | **7.557** |
| **real** | **−2** | **+1.062** | **8.876** |
| shuffled labels | +2 / −2 | −0.804 / +0.146 | 8.945 / 7.763 |
| random | +2 / −2 | −0.284 / +0.047 | 8.827 / 7.727 |

**Only the real direction is monotone and symmetric under sign reversal.** Push toward "correct" and the model
calls itself KNOWN and pulls `guess` down; push the other way and it calls itself UNKNOWN and pushes `guess` up.
The random direction moves the gap by less than a quarter as much AND moves it the same way in both directions —
the signature of a large perturbation rather than a meaningful one. The shuffled-label direction is asymmetric
too.

So a direction that occupies **0.081% of the variance** and never surfaced in any vocabulary readout is
nonetheless **causally connected to the words for competence**. Reading it failed; steering it works. This is the
same shape of evidence the paper rests on, reproduced here.

**What it cost.** Nothing — but it reverses the reading of five earlier rounds. Every one of them concluded
"competence is not verbalizable in this box" from read-only evidence. The correct statement is narrower:
**competence is not verbalized spontaneously, and is verbalizable on intervention.**

**What would discharge it.** A signal a router consumes being able to say whether it was obtained by observation
or by intervention, because the two cost different amounts per request — an observation is one forward pass, an
intervention is at least two — and they are not interchangeable evidence. The minimum perturbation radius at
which the answer flips is itself an uncertainty measure and is only available under intervention.

## F13 — Generation costs 95 times the prefill, so the gate's depth barely matters

**Where it bit.** The timing run, measured on the deployment rather than assumed. The routing judge had put the
value of skipping generation at $0.0024-$0.0127 per item on assumed throughput — a range straddling the entire
$0.00820 of API-selection headroom, so the decision rested on a number nobody had measured.

Measured, 96 items at batch 8 on one L40S:

| | per item |
|---|---|
| prefill to layer 20 | **56.2 ms** |
| prefill through all 40 layers | **109.4 ms** |
| generation to the box's own median of 687 tokens | **10.42 s** |
| **saved by aborting before generation** | **10.36 s** |

At $1 / $2 / $4 per GPU-hour that is **$0.00288 / $0.00576 / $0.01151** per abort. The deployment's own rate
(g6e.12xlarge, four GPUs, about $2.62 per GPU-hour) puts it near **$0.0075** — the same order as the whole
API-selection headroom.

**And the gate's depth is almost irrelevant.** Reading at layer 20 rather than at layer 40 saves 53 ms, which is
0.5% of what skipping generation saves. Every earlier round treated "readable at layer 8 or 20" as the
commercially interesting property. It is not: **the interesting property is being readable before generation at
all**, and the strongest such signal is the full-prefill one.

**What it cost.** F10 named early exit as the reason the layer-8 result mattered, and the cascade simulation
compared an L20 probe against a full-forward entropy as if the L20 one were cheaper in a way that mattered. It is
cheaper by 1% of the relevant cost. The comparison should have been between signals available before generation,
all of which cost about the same.

**What would discharge it.** A cost model that separates prefill from generation. Everything in this project so
far prices a request by its token counts, which mixes a 0.109-second prefill with a 10.4-second generation at the
same rate per token. A router that decides whether to generate needs those two priced apart, and no record here
does that.

## F14 — The direction moves the words about competence but barely moves the answer

**Where it bit.** The full injection run, 2,364 items at five doses in both directions with two controls. F12 had
established the causal link to vocabulary on 60 items; this scores it as a routing signal on all of them.

The perturbation radius at which the answer flips, over the whole corpus:

| smallest dose that flips the answer | items |
|---|---|
| 0.25 | 93 |
| 0.5 | 59 |
| 1.0 | 72 |
| 2.0 | 138 |
| **never, up to 2.0** | **2,002 (85%)** |

**Fifteen per cent of answers move at all.** The paper reports 59% for swapping a J-space component; this
direction, which is the error discriminant rather than a concept component, reaches 15%. So the direction is
causally wired to the *words* for competence (F12) and only weakly to the *answer*.

As abstention scores, against the free full-prefill entropy at 0.8321:

| score | dev AUC |
|---|---|
| flip radius | 0.5876 |
| all four intervention features | 0.6239 |
| baseline KNOWN−UNKNOWN gap | 0.5827 |
| dose-response slope | 0.5332 |

At the budgets that decide adoption, escalating to the strong arm: at 141/1,187 the free entropy rescues 58 and
breaks 1; **intervention features added to it rescue 60 and break 0**. At 42/1,187, 21 against 20. The gain is
small and the elimination of breakage is the more interesting half.

**What it cost.** 83 minutes of GPU. The finding stands as representation research — the direction is real,
causal, and verbalizable on intervention — and as a routing signal it is additive at the margin rather than
competitive on its own.

**What would discharge it.** A cost model that can price a signal requiring **two forward passes**. Every
intervention feature here costs at least a second prefill, and F13 measured a prefill at 0.109 s against a
generation at 10.42 s — so a second prefill is 1% of what the gate saves, which makes even a small additive gain
worth buying. Nothing in the mechanism records how many passes a signal cost, so that trade cannot be stated.

## F15 — The adoption bar and the measurement were on different prompt conditions the whole time

**Where it bit.** Asking the adoption question the right way round. Every simulation so far fixed an escalation
budget and counted rescues. The bar is the reverse — "hold the floor with at most 126 escalations per 1,187" — so
the quantity is the budget each signal REQUIRES:

| signal | floor 0.75 | floor 0.80 | floor 0.85 | floor 0.90 |
|---|---|---|---|---|
| free full-prefill entropy | 268 | 377 | 496 | **859** |
| flip radius | 382 | 557 | 954 | 1,162 |
| KNOWN−UNKNOWN gap | 498 | 744 | 907 | 1,153 |
| **oracle**, best gain first | 170 | 229 | 289 | **348** |

**The bar of 126 is unreachable even by the oracle**, which needs 348. That is not a statement about any signal.

**The cause is a condition mismatch I carried for several rounds.** The residual data is the TERSE condition,
where the box scores 0.608 on dev. The floor of 0.90 and the budget of 126 were stated for the NORMAL condition,
where the box scores 0.7597.

> **Correction, same day.** The sentence that stood here said lifting 0.608 to 0.90 needs at least 205 net
> rescues and lifting 0.7597 to 0.90 needs 141, "which is where the original number came from." Both figures
> are wrong and the derivation is invented. Over 1,187 items the arithmetic minimum is `ceil(0.90 × 1187) −
> p_box × 1187`: **347 from 0.608, and 167 from 0.7597.** The bar allowed 141, and 126 after its own 10%
> reduction, so it was below the arithmetic minimum in BOTH conditions — see F17, which supersedes this
> paragraph's account of the cause. The condition mismatch is real; it is not what made the bar unreachable.

So "the adoption condition is unmet" was reported repeatedly by comparing a requirement computed on one condition
against a measurement taken on another. This is F1 again, one level up: the prompt condition is not recorded with
the number, so two numbers that cannot be compared look comparable.

**What it cost.** Several rounds of "not yet adopted" that were not measurements of the signal at all. The correct
comparison needs the normal condition's residuals, which is the extraction that once collapsed 1,822 items onto
`A` (F5) and has since been fixed to take its label from generation — and has not yet been run.

**What would discharge it.** The same thing F1 asks for, enforced rather than documented: a number carrying the
condition it was measured under, so that a comparison between two conditions is refused instead of performed. Every
economic threshold in this project is conditioned on a box accuracy, and none of them says which box.

## F16 — A figure quoted as a property of the model was a property of the ridge

**Where it bit.** The claim that opened this whole study and was carried through five rounds: the correctness
direction occupies 0.081% of the activation variance and sits 120th by variance, which was read as this box
confirming the paper's "J space is under 10% of activation variance."

An adversarial round asked the obvious control I had never run — fit the same solver on PERMUTED labels and see
where a direction with no signal in it lands. Two things came out, and both destroy the claim.

**The geometry was not the one the claim is about.** The 0.081% was measured after applying the final RMSNorm
weights, which rescale every coordinate and therefore change which directions are high-variance. In the raw
residual stream — the activations the paper's claim is about — the correctness direction is among the TOP few:

| layer | real share | rank | permuted share (median) | permuted rank (median) |
|---|---|---|---|---|
| L24 | 0.1926 | **2** | 0.0392 | 4 |
| L28 | 0.1438 | **2** | 0.0245 | 5 |
| L36 | 0.0618 | 4 | 0.0080 | 21 |
| L40 | 0.0032 | 38 | 0.0095 | 19 |

The permuted-label directions are LOWER in variance than the real one. Landing in the low-variance tail is the
solver's default, so a low-variance finding was never evidence for anything; and the real direction does not land
there.

**The number moves with the regularisation alone.** Same data, same labels, same layer, only the ridge changing:

| L28, ridge | raw: share / rank / dev AUC | RMSNorm-scaled: share / rank / dev AUC |
|---|---|---|
| 0.5 | 0.2424 / 2 / 0.7320 | 0.2351 / 2 / 0.3328 |
| 20 | 0.1438 / 2 / 0.7695 | 0.0042 / 28 / 0.7419 |
| 100 | 0.0556 / 4 / 0.7960 | 0.0014 / **75** / 0.5480 |

Rank 2 to rank 75 by turning one knob, while dev AUC barely moves. **The variance share of a fitted direction is
a property of the fit, not of the model,** and cannot be quoted as a measurement of where a model keeps its
information. (The two smallest ridges diverge numerically — AUC 0.5549 — and those rows are void, not evidence.)

**What it cost.** The first of the seven "settled" measurements, withdrawn. It was also the finding that made the
paper look confirmed in this box, which is what gave the following four rounds their premise.

**What would discharge it.** A quantity derived from a fitted model carrying the fitting hyper-parameters and the
geometry it was computed in, the same way F1 asks a number to carry its prompt condition. This is the same defect
class in a third place: a number whose meaning depends on an argument that is not stored beside it.

## F17 — The adoption bar was never derived from the floor, and was infeasible in every condition

**Where it bit.** Auditing F15's own arithmetic, at an adversarial round's insistence. F15 diagnosed a condition
mismatch and then explained the bar's origin — and that explanation does not survive checking.

The bar was "hold floor 0.90 with at most 126 escalations per 1,187," where 126 is a 10% reduction on 141. The
arithmetic minimum of net rescues to reach a floor is `ceil(floor × N) − p_box × N`:

| condition | floor 0.80 | floor 0.90 |
|---|---|---|
| terse, 0.608 | 228 | 347 |
| normal, 0.7597 | 48 | **167** |

**141 is below 167, so the bar was unsatisfiable in the normal condition too** — by any signal, by the oracle, by
anything. It was unsatisfiable on the day it was written.

Where 42 and 141 actually came from: they are the percentile bands 3.54% and 11.88% of 1,187, named in an earlier
review round, with the labels "floor 0.80" and "floor 0.90" attached to them there. No derivation was ever given
and I never asked for one; I inherited the numbers and their labels together and treated the labels as their
provenance.

The same audit shows the oracle column carried no information either. The oracle's 348 at floor 0.90 equals the
arithmetic minimum of 347 — it is `(floor − p_box) × N` restated, not a measurement of how good an oracle can be.
Two of the five rows in F15's table were identities.

**What it cost.** The adoption criterion for the entire study, void. Every "not yet adopted" conclusion, including
F15's own correction, was measured against a bar no policy could clear.

**What would discharge it.** Two things, and the second is the one that generalises:

- A floor expressed as headroom rather than as an absolute: `γ = (F − p_box) / (p_ceiling − p_box)`, with
  `p_ceiling = p_box + (1 − p_box) · q_API`. In terse the floor of 0.90 was `γ > 1` — not merely hard but outside
  what escalating every single item could reach. Stated in γ, the two conditions' bars are comparable and an
  impossible one is visible on sight.
- **Feasibility checked before a policy is scored.** When the oracle cannot reach the floor in the same condition,
  the verdict belongs on the CONSTRAINT — infeasible — and not on the policy. This is a property of any evaluator
  that carries a floor and a budget, so it is the one clause here that is about tierbook's mechanism rather than
  about the study's bookkeeping.

## F18 — What the escalation table was actually measuring, once the identities are removed

**Where it bit.** F15's table survives F17 if it is read as the ratio each signal achieves against the arithmetic
bound rather than as a pass/fail against a bar. `η(F) = N_oracle(F) / N_signal(F)`:

| floor | free entropy | flip radius | KNOWN−UNKNOWN gap |
|---|---|---|---|
| 0.75 | 0.63 | 0.45 | 0.34 |
| 0.80 | 0.61 | 0.41 | 0.31 |
| 0.85 | 0.58 | 0.30 | 0.32 |
| 0.90 | **0.41** | 0.30 | 0.30 |

The free entropy runs at about 0.6 of the bound over most of the range and **falls to 0.41 at the top**. That is
the finding the yes/no bar was hiding: the entropy ranks the middle of the difficulty distribution well and is bad
at the last tenth, which is exactly the region a high floor is made of. It is also where an internal signal would
have to earn its place, and where all three signals converge to 0.30.

**What it cost.** Nothing yet — this is recovered from measurements already taken. It is recorded because it is the
first statement in this study about WHERE a signal fails rather than whether it passes.

**What would discharge it.** A comparison reported over the whole deferral curve rather than at one operating
point. Signals cross: a ranking taken at one floor does not hold at another, and this table is an instance. The
mechanism-level form is that a policy comparison must name its operating point or integrate over it.

## F19 — Three things decide whether a floor is reachable, and the study checked none of them

**Where it bit.** Taking F17's fix seriously — express a floor as headroom, and check feasibility before
scoring a policy — and finding that "headroom" needs three inputs, not one. Fitting a two-parameter item
response model to the response matrix already on disk (488 items × 16 systems: 7 API arms, 9 box arms across
two prompt conditions) puts every arm and every condition on one scale and makes all three checkable.

**First: the escalation target's own ceiling.** No cascade can exceed the fraction of items that the box or its
escalation target solves. Measured:

| cascade | ceiling |
|---|---|
| box + `claude-sonnet-4-6` | **0.8934** |
| box + `claude-opus-5` | 0.9098 |
| box + `claude-fable-5` | 0.9160 |
| box + every API arm, best per item | 0.9590 |
| every one of the 16 systems, best per item | 0.9672 |

The simulations escalated to `claude-sonnet-4-6`. **Floor 0.90 is above that cascade's ceiling**, so it was
unreachable for a reason that has nothing to do with the condition and nothing to do with a signal: the target
could not supply it. With `claude-opus-5` the same floor is reachable. The floor and the target were chosen
independently and never checked against each other.

**Second: accuracy is not a sufficient statistic, so it misranks arms.** `qwen3-next-80b` scores 0.6230 and
`qwen3.6@terse` scores 0.6537, yet the fitted abilities put them the other way round (θ = −0.588 against
−0.961): the terse arm's successes sit on easier items. Ranking candidates by accuracy picks a different winner
from ranking them by ability on the same items.

**Third: a prompt condition is not a shift in ability — it changes which items are solved.** The model assumes
responses are independent given item difficulty and system ability, so two arms sharing a model and a prompt
should agree MORE than it predicts, and they do. The comparison that matters is where a prompt change falls:

| pair | excess disagreement (observed − predicted) |
|---|---|
| two terse arms of the same box | **−0.1189** |
| two normal arms of the same box | −0.0365 |
| a normal arm against a terse arm | **+0.0147** |
| the box against a different model entirely | +0.0877 |

On that scale the prompt change sits **65% of the way from a re-run to a different model**. So F1 understates
the problem: a signal fitted in one condition is not a mis-scaled version of the same signal in the other, and
no amount of recalibration transfers it. The condition has to be part of the identity of the measurement, not a
scale factor applied to it.

**What it cost.** Nothing new was run — the response matrix was already on disk from the economics work, and the
fit takes seconds. The cost was earlier: five rounds of signal comparison inside a cascade whose ceiling was
below its own floor.

**What would discharge it.** A floor accepted only alongside the escalation target it is claimed for, with the
cascade's ceiling computed from recorded per-item outcomes and the floor refused when it exceeds it. This is the
one clause in F17's discharge that has teeth, and F19 is why: the infeasibility was in the pairing of a floor
with a target, which is exactly the kind of fact a policy artifact can hold and check.

Two caveats on the fit itself. The weak prior shrinks the box's predicted accuracy to 0.6200 against a measured
0.6537, so predicted escalation counts run conservative; and the discriminations hit both clip bounds, so
individual item parameters are not to be quoted. The three comparisons above are ordinal and survive that.

## Not requirements, deliberately

Kept here so they are not re-proposed as work.

- **A general residual-capture component in tierbook.** The capture is research code and belongs to the study,
  not the mechanism. Building it into tierbook is the over-engineering the policy change exists to stop.
- **A J-lens implementation in tierbook.** Whether the readout is worth anything is unsettled. Nothing goes into
  the mechanism until an experiment asks for it, and no experiment has.
- **Acting on `tenant_scope`.** v0.3.0 records it and says in its own interface that nothing acts on it. No
  experiment has needed it acted on.
