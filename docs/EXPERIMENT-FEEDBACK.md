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

> **See F22.** The conclusion of this entry stands and its explanation does not. The flips are confined to items
> whose pre-intervention margin is small, the controls flip nearly as often as the real direction, and the 15% is
> a union over eight amplitudes rather than an effect at one. The comparison against the paper's 59% below is
> withdrawn there.

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

**The clean version of the control, which the adversarial round asked for, refutes it in every cell.** My first
control fitted the direction and measured its variance in the same sample; the correct form fits on train,
measures against the held-out covariance, and permutes labels WITHIN category so that a direction which merely
predicts the field earns no credit. 200 permutations:

| geometry, layer | real share | null median | one-sided p that real is unusually LOW |
|---|---|---|---|
| raw residual, L28 | 0.1311 | 0.1432 | 0.225 |
| raw residual, L36 | 0.0623 | 0.0310 | **1.000** — above all 200 nulls |
| RMSNorm-scaled, L28 | 0.0049 | 0.0133 | 0.170 |
| RMSNorm-scaled, L36 | 0.0115 | 0.0150 | 0.390 |

In three cells the real direction is indistinguishable from the null, and in the fourth it is significantly
HIGHER in variance. Nothing supports "the correctness direction is unusually low-variance." A second reading
falls out of the stratified null: at L28 in the raw stream the real direction is not distinguishable from a
direction that only knows the item's category.

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

## F20 — The escalation rule has to contain the per-item price, and that is the whole gain

**Where it bit.** Testing a proposal to price the scarce resource online — treat the API quota as expiring
inventory, carry a shadow price `λ`, update it by `λ ← [λ + η(used − pace)]₊`, and escalate when the expected
gain exceeds price plus `λ`. It was put forward as the framework for deriving an allocation from observed state
rather than from a threshold someone tuned, which is what this project says it is for.

**The first run appeared to confirm it** — the shadow price beat a confidence threshold in all four scenarios,
including against the threshold re-tuned for each scenario with hindsight. But it won with *less accuracy and
half the cost*, which is the signature of picking cheap items, not of pricing a scarce resource. So the shadow
rule was run again with `λ` frozen at the single constant that performs best on the nominal scenario. Whatever
separates the two is `λ`:

| quota | binding | confidence threshold | frozen `λ` | shadow price |
|---|---|---|---|---|
| 800 | yes | 78.55 / 0.8580 | **81.31** / 0.8555 | 75.54 / 0.7860 |
| 400 | no | 74.42 / 0.7940 | **77.08** / 0.7930 | 72.28 / 0.7400 |
| 250 | yes | 71.83 / 0.7445 | **75.00** / 0.7650 | 71.48 / 0.7265 |
| 150 | yes | 70.43 / 0.7195 | **72.79** / 0.7365 | 69.74 / 0.7050 |
| 80 | yes | 69.62 / 0.7065 | **71.00** / 0.7150 | 69.11 / 0.6960 |
| 40 | yes | 69.05 / 0.6955 | **69.64** / 0.6985 | 68.75 / 0.6905 |

(net value in dollars over 2,000 requests / accuracy.) With a demand spike the tuning never saw, at quotas 400,
150 and 80, the ordering is identical.

**The shadow price loses at every level of scarcity, binding or not.** The reason is structural rather than a
tuning failure: within the day the item stream is i.i.d., and for i.i.d. arrivals against a fixed quota the
optimal dual IS a constant. Updating it online only adds tracking error — it spends quota early while `λ` is
low and prices itself out later. `λ` could only pay if the *composition* of arrivals moved, which is the
scenario this simulation does not contain and the one the idea would need in order to get another hearing.

**What survived is one term.** The per-item API price belongs in the escalation rule, and a confidence threshold
cannot express it. The mechanism, measured on the same items:

- the per-item API cost spans **7.1×** between its 10th and 90th percentiles — it is a real billing figure that
  moves with output length, not a constant;
- and it correlates **+0.2313** with the box being wrong. The items most worth escalating are also the expensive
  ones, so a confidence-only rule spends most where it is least efficient.

The failure this fixes is visible without any scarcity at all: when the API price tripled mid-day, the confidence
threshold's spend went from $4.98 to $9.94 while it escalated the same 381 items, because the rule cannot see a
price. The cost-aware rule cut to 250 escalations and $1.79 on its own, with no re-tuning and no `λ`.

**What it cost.** Nothing — this ran on outcomes already on disk. It is recorded because it is the first result in
this study where the mechanism improved with no internal signal involved at all, and because it refutes the idea
it was built to test.

**What would discharge it.** An escalation decision that takes the candidate's price for THIS request rather than
a tier-level average, with the observation carrying its own acquisition cost. That is close to what the
observation contract in F21 asks for, and the two should be discharged together.

**Two caveats.** This is a resampling simulation over 244 held-out items with a per-request value fixed at $0.05,
not real traffic; the ordering above is stable across the quota sweep but the magnitudes are not a forecast. And
the escalation target is `claude-opus-5`, chosen because F19 showed `claude-sonnet-4-6`'s cascade ceiling sits
below the floor this study had been using.

## F21 — An observation is not a feature; it has a cost, an availability and a condition

**Where it bit.** Asking what, if anything, five rounds of J-space work should put into the mechanism. The answer
from the review is that it should put in **no J-space-specific feature at all**, and instead make an observation
a thing with properties, so that an internal readout is admissible without being privileged:

- `value` — scalar, vector, trajectory or category. Entropy, an internal readout, a price and a load are the
  same kind of thing.
- `availability` — before prefill, during compute, after prefill, after generation. A layer number is
  provider-specific detail below this.
- `acquisition_cost` — money, GPU time, added latency, memory, a synchronisation stall.
- `provenance` — model, version, **prompt condition**, readout version.
- `validity` — the condition it was calibrated under, its freshness, whether it is missing.

Two consequences that this study's own results force, and which are the reason this is not merely tidy:

- **The intervention must not be registered as a control action.** F12 showed that moving the direction moves
  the words about competence; F14 showed it moves only 15% of the answers. A mechanism that could register "I
  can move this readout" as a lever on output quality would be acting on a 15% effect as though it were the 59%
  the paper reports. Passive observation, active probe and control action are three different registers and the
  middle one is where this belongs — priced by its acquisition cost, like any other observation.
- **`provenance` has to carry the prompt condition**, which is F1, and `validity` has to carry the condition it
  was calibrated under, which is F19 — because a signal fitted in one condition does not transfer to the other
  by recalibration, it is about different items.

**What it cost.** Nothing directly. It is the shape the previous nineteen entries were circling: F1, F3, F5, F9,
F16 and F19 are each a case of a number stored without the argument that gives it meaning.

**What would discharge it.** One structure, replacing six separate requirements. It is also the only entry here
that would let the J-space work reach the mechanism at all — as an optional observation with a price, which is
what the measurements support, rather than a signal the mechanism knows the name of.

## F22 — The answer movement was not caused by the direction, and 15% was a union over a sweep

**Where it bit.** A review named the cheapest rival explanation for "the direction moves the words but only 15% of
the answers": the answer logits may move on nearly every item, with the argmax turning over only where the
pre-intervention margin was smaller than the movement. That predicts flips concentrate at low margin. It is
checkable without another GPU run, because the intervention outcomes and the pre-intervention margins are both on
disk for the same 2,364 items. Both halves of the prediction hold, and a third thing falls out that is worse.

**Flips exist only where the margin is small.** Flip rate at the strongest amplitude, by margin quintile:

| margin quintile | n | margin range | real | shuffled labels | random |
|---|---|---|---|---|---|
| 1 | 440 | 0.00–0.75 | **0.1932** | 0.2182 | 0.1750 |
| 2 | 503 | 0.88–2.12 | 0.1093 | 0.1133 | 0.0736 |
| 3 | 475 | 2.25–4.12 | 0.0189 | 0.0337 | 0.0105 |
| 4 | 448 | 4.25–6.00 | **0.0000** | 0.0045 | 0.0022 |
| 5 | 498 | 6.12–12.38 | **0.0000** | 0.0000 | 0.0000 |

Above the median margin, **nothing flips at any amplitude in any direction.** So the quantity measured is how many
items were sitting near a decision boundary, not whether the direction reaches the decision.

**The controls flip nearly as often, so the flipping is not specific to the direction.** At the strongest
amplitude the shuffled-label direction flips MORE than the real one (0.0723 against 0.0630), with random at
0.0508. Taking the union over all eight amplitudes — which is where the 15% came from — real is 0.1531, shuffled
0.1299, random 0.0990. The specificity that F12 established is about the KNOWN/UNKNOWN verbaliser logits, and it
does not extend to the answer: **the answer movement is what any perturbation of that size does to items near a
boundary.**

**And 15% was a union over a sweep quoted as an effect.** At the strongest single amplitude the real direction
flips 6.30%. The 15.31% is the fraction flipped by at least one of eight amplitudes across two signs. Those are
different quantities and F14 compared the union against the paper's single-setting 59%.

**What this does to F14.** F14's claim that the direction moves the words but barely moves the answer survives,
and its reason changes completely. It is not a dissociation between a report pathway and a decision pathway that
this measurement can see. The answer barely moves because the answer is mostly not close, and what movement there
is is not attributable to the direction. The comparison against the paper's 59% is withdrawn: a free-generation
change rate and a ten-way argmax turnover are not the same measurement, and the latter is capped by the margin
distribution of the benchmark.

The flipped items are also the ones the box was failing anyway — median margin 0.688 and accuracy 0.2983, against
median margin 4.000 and accuracy 0.6713 for the rest — so nothing here is a candidate for improving answers.

**What it cost.** Nothing to run; the join was already possible. The cost was carrying "15% against the paper's
59%" as a finding through two rounds, and building a mechanistic story on a number that was a union over a sweep
and not specific to its own treatment.

**What would discharge it.** A recorded effect saying whether it is the effect at one setting or the union over a
sweep, and carrying the control's value beside it. Both are the same defect as F1 and F16 in a third place: a
number stored without the argument that fixes its meaning, next to which a control is not stored at all.

## F23 — Signals cross, so a ranking without an operating point is not a ranking

**Where it bit.** F18's own discharge, done: report over the whole deferral curve instead of at one point. Two
summaries, both over all 2,364 items where they can be.

**The oracle-normalised skill score** (E-AURC rescaled — Geifman & El-Yaniv, NeurIPS 2017) over every coverage:

| signal | AURC | skill against the oracle |
|---|---|---|
| free entropy | 0.1636 | **0.7197** |
| answer margin, negated | 0.1704 | 0.6967 |
| decision depth | 0.2764 | 0.3342 |
| **UNKNOWN − KNOWN gap** | 0.3227 | **0.1762** |
| layer flips | 0.3494 | 0.0847 |
| random ranking | 0.3742 | 0.0000 |
| oracle | 0.0816 | 1.0000 |

**And the economic form**, `U(λ) = accuracy − λ · escalation rate` at the best threshold for each λ, on the 488
items that carry an API arm, escalating to `claude-opus-5`:

| λ | all box | all API | free entropy | answer margin | decision depth | UNKNOWN − KNOWN | oracle |
|---|---|---|---|---|---|---|---|
| 0.02 | 0.6537 | 0.8570 | **0.8601** | 0.8600 | 0.8574 | 0.8573 | 0.9047 |
| 0.05 | 0.6537 | 0.8270 | **0.8377** | 0.8355 | 0.8281 | 0.8276 | 0.8970 |
| 0.10 | 0.6537 | 0.7770 | **0.8066** | 0.8045 | 0.7832 | 0.7781 | 0.8842 |
| 0.20 | 0.6537 | 0.6770 | **0.7500** | 0.7496 | 0.7262 | 0.6791 | 0.8586 |
| 0.40 | 0.6537 | 0.4770 | 0.6676 | 0.6689 | **0.6758** | 0.6537 | 0.8074 |

**The crossing is real and it is in the table.** At every λ up to 0.20 the free entropy wins. At λ = 0.40 the
decision depth wins, and the entropy is third. A signal that is worse over the whole curve (skill 0.3342 against
0.7197) is the better choice in the regime where the API is barely worth using at all. So "the free entropy is
the best free signal" is a statement about a price range, not about the signal, and every ranking in this study
that omitted its operating point was underdetermined.

**The internal readout has no economic value at any price.** The `UNKNOWN − KNOWN` gap scores 0.1762 in skill,
and at λ = 0.40 its best policy is to escalate nothing — its `U` equals the all-box value to four decimals. It is
not that it is beaten narrowly; across the price range there is no threshold on it that is worth setting.

**On F18's numbers.** They are not withdrawn but they measure something narrower than they appeared to. The
0.6-falling-to-0.41 figures are the oracle's escalation COUNT divided by the signal's at fixed floors — a
high-escalation quantity. The skill score of 0.7197 integrates the whole curve, and the kept-set error at 5%
escalated is 0.3491 against the oracle's 0.3428, nearly identical. Both are true: the entropy tracks the oracle
closely when little is escalated and falls away as more is, which is why a high floor reads worse than the curve
as a whole.

**What it cost.** Nothing to run. It is recorded because it retires a class of claim rather than a claim: eight
rounds of "signal A beats signal B" were stated without the price or budget that decides it.

**What would discharge it.** A signal comparison that either names its operating point or reports the curve, and
a policy artifact that stores the price ratio it was chosen under — which is the `validity` field F21 asks for,
used for the one purpose that has already changed an answer.

## Not requirements, deliberately

Kept here so they are not re-proposed as work.

- **A general residual-capture component in tierbook.** The capture is research code and belongs to the study,
  not the mechanism. Building it into tierbook is the over-engineering the policy change exists to stop.
- **A J-lens implementation in tierbook.** Whether the readout is worth anything is unsettled. Nothing goes into
  the mechanism until an experiment asks for it, and no experiment has.
- **Acting on `tenant_scope`.** v0.3.0 records it and says in its own interface that nothing acts on it. No
  experiment has needed it acted on.
