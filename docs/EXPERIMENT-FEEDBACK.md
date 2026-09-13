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
could not supply it.

> **See F32.** This paragraph is withdrawn as a claim about the population. 0.8934 is 436 of 488, whose
> one-sided upper 95% bound is 0.9156, so no cascade's ceiling here can be distinguished from 0.90. What
> stands is the empirical union on the observed items, and it is an oracle over outcomes known after the
> fact rather than an operational ceiling. With `claude-opus-5` the same floor is reachable. The floor and the target were chosen
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

> **See F32.** The crossing below is withdrawn. Each signal's threshold was chosen on the same items that
> scored it; chosen on a validation half instead, decision depth is worse than the entropy at both
> λ = 0.20 and λ = 0.40, with intervals spanning zero.

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

## F24 — No API arm exists for a single held-out item, so the economics have never left the fold

**Where it bit.** Checking, before a review could, how the 488 items carrying API outcomes were drawn from the
2,364. The difficulty is representative and that was the worry; the fold is not, and that is worse:

| | in the 488 | the other 1,876 |
|---|---|---|
| box accuracy | 0.6455 | 0.6189 |
| final entropy | 0.5031 | 0.5071 |
| answer margin | 3.6091 | 3.5870 |
| **calibration fold** | **488** | 447 |
| **test fold** | **0** | 1,429 |

Category shares agree within ±25%. So the ceilings in F19 are sound as measurements — they are counts of what
each system solved, and a subset matched on difficulty gives a representative one.

**But every economic conclusion lives entirely inside the calibration fold.** F20's shadow-price comparison split
the 488 in half and called one half held out; both halves are calibration items. F23's `U(λ)` table is on the
same 488. The signal work has always been calibration-fit and test-evaluated; the money work never has been,
because the API outcomes it needs do not exist outside the fold.

This does not make F20 or F23 wrong — F20's finding is an ordering that holds across a quota sweep and a scenario
set, and F23's crossing is between two signals measured the same way. It makes them unconfirmed in the sense the
rest of the study uses that word, and the distinction was not visible anywhere because the fold was not recorded
next to the number.

**What it cost.** Nothing yet, and that is the point of catching it here rather than after another round of
policy conclusions built on it.

**What would discharge it.** Two things:

- API outcomes for test-fold items. At roughly $0.0065 per item for `claude-opus-5`, the 1,429 test items cost
  about $9. That is routine measurement spend for this project and it converts every economic conclusion here
  from calibration-internal to out-of-fold, which no amount of re-analysis can do.
- A recorded outcome that names its fold, so a policy tuned and scored inside one fold cannot be reported as
  held-out. This is the same shape as F1 (the prompt condition), F16 (the ridge and the geometry) and F22 (the
  amplitude and the control): the number is fine, and the argument that fixes its meaning is not stored with it.
  Four instances now, which is enough to say the fix belongs in one place rather than four.

## F25 — 84% of the "competence direction" lies in the span of the answer-letter directions

**Where it bit.** A review's sharpest objection to F12: the direction may not be about competence at all, but
about which letter the model is on the point of emitting, since it is more confident on easy items. Measured
directly at L28, with the letter span built from ten one-vs-rest fits on the box's own answer:

| direction | inside the letter span | inside a SHUFFLED-letter span |
|---|---|---|
| fitted on correctness | **84.3%** | 76.1% |
| fitted on shuffled labels | 36.7% | 39.5% |
| isotropic random | 5.9% | 7.3% |
| data-shaped random | 34.8% | 44.7% |

An isotropic unit vector puts 7.0% of its norm in any ten-dimensional subspace, so 84.3% is not an accident. But
the shuffled-LETTER span captures 76.1%, so most of that overlap is structural — the subspace any fit on these
residuals lands in — and only about 8 points are attributable to letter information as such.

**What the letter component is worth.** Splitting the direction and scoring each part on held-out items:

| | dev AUC | share of the norm |
|---|---|---|
| the full direction | 0.7695 | 1.0000 |
| the letter component alone | 0.7437 | 0.8431 |
| the letter component removed | 0.6921 | 0.5378 |

So the letter component carries most of the predictive power, and what survives its removal is still well above
chance. The direction is not merely a letter detector.

**And the mechanism is a property of the box, cheaply available for free.** Accuracy by the letter the box itself
emits: `A` 0.3899 on 572 items, and every other letter between 0.5979 and 0.7522. The box answers `A` about a
quarter of the time and is wrong on three-fifths of those — it is the fallback. Which means **"the box answered
A" is a routing signal on its own, at AUC 0.6302, with no residual, no probe and no cost** — better than the
internal readout's 0.1762 skill in F23. Excluding `A` items the direction still reads 0.7294, and the free
entropy still beats it at every stratum (0.8424 overall, 0.8159 on non-`A`).

**What it cost.** F12's specificity claim narrows: what the intervention moves specifically is the verbaliser,
and the direction it moves along is substantially the direction of the letter it is about to emit. The matched
controls running on GPU test whether the verbaliser response survives the split; this entry is the geometry,
which did not need them.

**What would discharge it.** A direction reported with the fraction of it that lies in the span of directions
for the obvious confound, and a probe compared against the free observation of its own output. The second is the
cheaper habit and the one that would have caught this: the emitted letter was in every row of the capture from
the first run.

## F26 — The residual reads item difficulty, and the free signal already knows all of it

**Where it bit.** The one route left for the readout after F23: stop asking it about the box's own competence,
which it cannot report, and ask it about the ITEM, which is what the band demonstrably reads. Item difficulty
`b_i` from the 2PL is a property of the input and is defined across systems, so it is the natural target.

Registered before running, because four withdrawals in this study came from fixing the null after seeing the
effect. Criterion: held-out Spearman beating the best baseline AND exceeding the 95th percentile of a 200-draw
item-permutation null.

| features | held-out Spearman |
|---|---|
| free entropy | **0.5357** |
| residual L28 | 0.5353 |
| residual band L16/24/28/36 | 0.5173 |
| category one-hot | 0.3411 |
| category + length | 0.3182 |
| prompt length | 0.0516 |
| permutation null: median +0.0074, 95th percentile | +0.1258 |

**Verdict: FAIL, by 0.0004.** And the finding inside the failure is real: the residual predicts cross-system item
difficulty at 0.5353 against a null of 0.1258 and a topic baseline of 0.3411, so it is reading difficulty and not
merely the subject — which is what the band's verbalisability predicted. It is simply a dead tie with a signal
that costs nothing.

A second question was registered separately rather than allowed to rescue the first: does the residual carry
difficulty information the entropy lacks? Entropy alone 0.5357, entropy plus residual 0.5382, difference +0.0026
with a paired bootstrap interval of [−0.1027, +0.0696]. **FAIL.**

**What it cost.** It closes the routing axis for the internal readout, on the last and most favourable framing
available to it. Every version of the question has now been asked — self-competence (F23), answer movement (F22),
item difficulty (here) — and the free output signal wins or ties each time.

**What would discharge it.** Nothing in the mechanism. This is the entry that says the J-space work should not
reach tierbook as a signal, and F21's observation contract is the only shape in which it could arrive at all.
It is recorded as a requirement on the STUDY instead: a criterion fixed before the measurement, which is how
both halves of this entry came to be reportable as failures rather than as trends.

## F27 — A crashed capture reported success, and its own gate is what caught it

**Where it bit.** The normal-condition capture, whose whole purpose was to make the two prompt conditions
comparable. It failed twice over, and the two failures are different kinds of thing.

**It crashed and the platform said it succeeded.** The job ran three hours, wrote 1,400 of 2,364 rows, died on
`torch.OutOfMemoryError` inside `lm_head(hidden_states[:, slice_indices, :])` — full-vocabulary logits over every
position of a batch of eight, 5.72 GiB in one allocation — and the Job's status read `Complete 1/1`. The cause is
in the job's own command:

```
bash /opt/bench/entrypoint-jlens.sh "$@" 2>&1 | tee /results/jl-normal/run.log
```

A pipeline's exit status is the last command's, and `tee` always succeeds. Every capture job in this study was
written this way, so **any of them could have reported success on a partial file**, and the only reason this one
was caught is that the row count was checked against what was asked for.

**And the data it did write failed its pre-registered gate.** The gate was: the letter distribution must not be
degenerate, and accuracy must land near 0.74.

| | value |
|---|---|
| rows | 1,400 of 2,364 |
| rows with a parsed letter | 1,244 (88.9%) |
| accuracy, all rows | 0.4107 |
| accuracy, parsed rows only | 0.4622 |
| terse accuracy **on the same 1,400 items** | 0.6293 |
| top letter share / distinct letters | 0.139 / 11 |

The distribution is fine — this is not the collapse of F5. But the condition that is supposed to score 0.7597
scored below the terse condition on the same items, so the extraction is wrong, not merely lossy.

**The rule was the defect, and it was mine, not the harness's.** It took the last standalone capital A–J in the
last 400 characters. A model that explains mentions option labels while reasoning, so the last capital is often
one it was rejecting; and when the budget truncates the reasoning there is no conclusion to find at all. The
docstring said "the way the harness does" and the harness does no such thing — it grades a letter it is handed.

**What it cost.** Three hours of GPU and a round of the transfer test that cannot be run yet. What it did not
cost is a finding, because the gate refused the data. That is the first time in this study a criterion fixed in
advance stopped bad data before it became a conclusion, and it is the direct payoff of the discipline F26 adopted.

**What would discharge it.** Three things, and the first two are already done:

- The letter read from an explicit `Answer:` cue appended after the reasoning, where the next token has one job,
  with the regex reading kept alongside for comparison. Extraction stops being a guess about prose.
- The tail of the generated text and its length stored on every row. The previous failure could not be diagnosed
  from what was stored — the rows held a letter and no way to see where it came from. This is F5 in a sharper
  form: it is not enough for the extraction rule to be recorded, the input to the rule has to be too.
- `set -o pipefail` on any job whose real work is upstream of a `tee`, or the exit code is decoration. This is
  the class the taxonomy calls silent corruption: the failure became a plausible value, so the run completed
  wrong rather than stopping.

## F28 — 87% of the price term's value was leakage, and what survives is the tier's price, not the item's

**Where it bit.** F20's requirement, which was the only positive result this study has produced. A review pointed
out what should have been obvious: the per-item cost it reads is the REALISED bill for a call already made, and it
correlates +0.2313 with the box being wrong. No production system knows it before deciding. So the rule may have
been reading difficulty through a price-shaped hole.

Re-run with three cost models, one policy family, the same tuning protocol, and the bill always charged at the
realised rate — only what the RULE is allowed to see changes:

| | correlation with the box being wrong | nominal | price ×3 | demand ×3 | quota halved |
|---|---|---|---|---|---|
| realised bill (what F20 used) | **+0.2313** | +2.658 | +4.749 | +2.680 | +1.375 |
| tier mean, no per-item information | — | +0.000 | **+1.565** | +0.000 | +0.000 |
| ex ante, from the input length | **+0.0100** | +0.198 | +1.367 | +0.230 | +0.086 |

(net value against the confidence threshold, dollars over 2,000 requests.)

**The leak is confirmed and it was most of the effect.** The realised bill is barely predictable before the call —
held-out correlation with input length 0.1864, R² 0.0347 — so an honest ex-ante estimate carries almost none of
its per-item variation, and its correlation with the box being wrong drops from +0.2313 to +0.0100. **Only 12.8%
of the margin survives** (7.5%, 28.8%, 8.6%, 6.2% by scenario).

**The pre-registered criterion still passes, and the requirement changes anyway.** The ex-ante rule beats the
confidence threshold in 4 of 4 scenarios, so the finding is not withdrawn. But look at the tier-mean row: it is
exactly +0.000 in three scenarios — it collapses into the threshold, as a constant must — and **+1.565 when the
price triples.** So the value that matters under a moving environment comes from the tier's CURRENT PRICE, which
is a single scalar the provider publishes, and not from any per-item estimate.

That is a smaller requirement than F20's and a much better one. A price table cannot leak, needs no predictor, and
is the thing that actually changes when the environment moves. F20's framing — put the item's price in the rule —
would have had the mechanism carrying a cost model whose only measurable contribution here is 0.2 dollars per
2,000 requests, while the effect it was credited with came from a variable that does not exist at decision time.

**On the general shape.** What made the threshold fail under a price change is not that it lacked a signal: it is
that its decision statistic has the wrong units. A confidence threshold thresholds a belief about quality; the
right statistic is quality improvement per unit of the constrained resource, so a resource coupling items appears
twice and only twice — as consumption on the item side, and as one scalar multiplier on the mechanism side.
Anything else that varies with the environment is tuning, and tuning breaks when the environment moves. This is
also why F20's rejection of online shadow-price updating and this entry's conclusion agree: the multiplier is a
constant per epoch, and it is the PRICE TABLE that changes.

**What it cost.** The magnitude of the study's only positive result, reduced eightfold, before it reached the
mechanism. Caught by a review, not by me, and the shape is one this ledger has recorded four times: a number whose
meaning depends on when it becomes knowable, stored without that fact.

**What would discharge it.** A candidate's price as a current, tier-level quantity that the escalation rule reads,
and an `availability` field on it — F21's word — that makes "realised after the call" unusable as an input to a
decision made before it. The second half is the general fix: an observation whose availability is `after_the_call`
cannot be an argument to a policy that runs before it, and that is checkable rather than a matter of care.

## F29 — Store the curve, not the scalar

**Where it bit.** The same review, on F23's discharge. F23 reported oracle-normalised skill scores as well as the
`U(λ)` table, and the scalar is the part that will get quoted. But the crossing F23 measured is not only in the
cost term: at a high `λ` only the far tail of the distribution is being asked about, and the ranking in the tail
differs from the ranking overall. A signal's scalar summary averages exactly the thing that decides which signal
to use.

So the ranking of signals is part of the allocation function, not an input chosen once before it. Selecting on
area under the curve is the same error F23 already named, one level up: it potentiates the operating point away.

**What it cost.** Nothing yet. It is recorded because F23's skill-score column is the most quotable artifact this
study has produced and it is the one most likely to be misused.

**What would discharge it.** A signal's recorded performance being its `U(λ)` curve over the price range, with any
scalar derived from it at the point of use and never stored in its place. This is the same requirement as F21's
`validity` field carrying the price ratio, seen from the measurement side rather than the policy side.

## F30 — Where this study is at risk of killing a real effect, and the one test that was missing

**Where it bit.** A review audited the withdrawals rather than the findings, and made a distinction this ledger
had been eliding. `real ≤ control` does not mean "no effect"; it means specificity against THAT control is not
shown. A p-value of 0.17 to 0.39 is not evidence of equivalence without an equivalence margin and power. And
comparing a real quantity against the MAXIMUM of several controls puts a winner's curse on the control side.

Ranked by how much each withdrawal may have over-killed:

| withdrawal | over-kill risk | the defensible upper bound on what was shown |
|---|---|---|
| F23, the readout's incremental value | **highest** | worthless alone, at these prices, with static thresholds |
| F16, the variance share | medium | the LOW-variance reading is unsupported; not that no competence direction exists |
| F22, the answer movement | medium | the single-setting claim and the comparison to 59% fall; the logit monotonicity does not |
| F17, the adoption bar | none | arithmetic, at the same floor, box and escalator |
| F15's explanation | none | prose without provenance, not an effect |

**And the highest-risk one had a test missing.** F23 compared signals one at a time. It never asked whether
ADDING the readout to the best free policy helps — a signal can be worthless alone and still carry an increment.
So: both policies are F28's ex-ante-cost rule, differing only in what predicts the box being right, cross-fitted
over 5 folds, with a paired bootstrap over items. Registered before running.

| λ | baseline | nested | difference | 95% interval |
|---|---|---|---|---|
| 0.02 | 0.8570 | 0.8573 | **+0.0003** | [+0.0001, +0.0005] |
| 0.05 | 0.8270 | 0.8293 | +0.0022 | [−0.0068, +0.0111] |
| 0.10 | 0.7888 | 0.7851 | −0.0037 | [−0.0156, +0.0081] |
| 0.20 | 0.7164 | 0.7156 | −0.0008 | [−0.0099, +0.0081] |
| 0.40 | 0.6465 | 0.6453 | −0.0012 | [−0.0264, +0.0199] |

**Verdict: PASS**, by the letter of the criterion — the interval at λ = 0.02 excludes zero. And the win is
+0.0003 in accuracy-equivalent units, about three cents per two thousand requests, at the cheapest price only,
with three of the other four point estimates negative and the cross-fitted AUC slightly WORSE with the readout
than without it (0.7901 against 0.7913).

**The registration was the defect this time.** "Significant at one or more of five λ" is a sign test with no
magnitude floor and five chances, which is close to the shape it was written to prevent. It is reported as a PASS
because relabelling it after seeing the number is the move that produced four withdrawals, and the honest
correction is to the criterion, not to the verdict.

**What it cost.** Nothing to run. What it bought is the strongest available statement about the readout: not
"internal signals have no operational value", which the individual comparisons never licensed, but that adding
this readout to the best policy available moves net value by three cents per two thousand requests at one price
and not measurably anywhere else.

**What would discharge it.** A registered criterion carrying a magnitude floor and an equivalence margin, not
only a sign and an interval. A floor makes a negative result mean something — "the effect is smaller than X" —
where a bare interval that contains zero means only that the study was too small to tell, and this ledger has
several of those recorded as though they were refutations.

## F31 — The common cause of every withdrawal is that a claim carries no provenance

**Where it bit.** The process audit, asked to look at the withdrawals as a class rather than one at a time. Its
answer is sharper than "the null was fixed after the effect", which was this study's own diagnosis:

> The estimand, the representation space, the aggregation rule, the comparator, the operating condition and the
> numeric source were never fixed in an executable form, so a **silent substitution of the subject** between the
> result and the sentence about it could not be detected.

Every withdrawal is an instance. F16 substituted the RMSNorm-scaled space for the raw residual stream. F22
substituted a union over eight amplitudes for an effect at one. F17 substituted a percentile band for a floor.
F23 substituted a single operating point for a range. F28 substituted a realised bill for a price knowable at
decision time. In each case both quantities are real and the sentence names only one of them.

The audit's proposed gates, in the order they would have paid here:

1. **A typed claim contract** — every quantity fixed on one line as `sample / split / layer / representation /
   normalization / fit / statistic / aggregation / comparator / operating-range / unit`, with
   `aggregation=single_amplitude` and `aggregation=union_over_amplitudes` as DIFFERENT TYPES. A quantity whose
   fields are not all filled, or whose noun phrase in the prose does not match its contract, is not reported.
   This alone stops F16, F22 and F23.
2. **An arithmetic and reachability gate** — before measuring, assert `target ≤ the escalator's ceiling` and
   `k ≥ ceil(target × N) − correct_box`. F17 dies without the model ever being loaded.
3. **A nearest-control gate** — the single most confusing control named in advance, computed in the same loop and
   under the same aggregation. Failure to separate is reported as "specificity against this control not shown",
   never as "no effect".
4. **A one-axis perturbation gate** — at most three degrees of freedom that could move the conclusion, endpoints
   and centre, minutes not hours. A quantity whose sign or rank flips is reported as a curve, never as a scalar.
5. **A provenance and worst-row gate** — every numeric sentence carrying its command, artifact and denominator,
   and automatically displaying its least favourable row: the strongest control, the worst λ, the weakest
   amplitude. F22's "shuffled beats real" was in the data from the first run and nothing surfaced it.

**Corrections get their own rule**, because F15 introduced a new error while fixing one. A correction is a diff,
not an essay: old claim id, the invariant that failed, the verified replacement, the blast radius. **It adds no
new number and no new causal story** — a hypothesis about why the error happened is a separate document marked
unverified, and a correction needing a new number is a new claim that goes through the gates from the start.

**What it cost.** Nothing new; this is the accounting of costs already paid. It is recorded because it replaces
six separate ledger requirements — F1's prompt condition, F16's ridge and geometry, F19's fold, F22's amplitude
and control, F28's availability, F29's operating range — with one structure. Those six are the same defect, and
listing them separately made each look like an oversight rather than a missing mechanism.

**What would discharge it.** The claim contract as the thing a measurement emits, so that a quantity without its
arguments cannot be written down. Whether that belongs in tierbook or only in the study is an open question and
the honest answer today is the study: tierbook's own version of it is F21's observation contract, and the two
should be designed together if either is built.

## F32 — Two of the surviving conclusions were finite-sample artifacts, and the third design fix is null

**Where it bit.** An adversarial round applied to the conclusions that were left standing after the earlier
withdrawals, rather than to the withdrawn ones. Three checks, all registered with a magnitude floor this time, all
cheap. Two of them overturn a live conclusion.

**The cascade ceiling is not established below the floor.** F19 explained the unreachable floor by saying the
cascade's ceiling was 0.8934, under 0.90. That is 436 successes in 488:

| cascade | successes | rate | one-sided upper 95% |
|---|---|---|---|
| box + `claude-sonnet-4-6` | 436/488 | 0.8934 | **0.9156** |
| box + `claude-opus-5` | 444/488 | 0.9098 | 0.9303 |
| box + `claude-fable-5` | 447/488 | 0.9160 | 0.9357 |

**No cascade's ceiling can be distinguished from 0.90 at this sample size.** So F19's headline — the floor was
above the target's ceiling — is withdrawn as a claim about the population and narrows to: on the observed 488
items the empirical oracle union is 0.8934. F17's arithmetic is untouched, because 126 is below 167 regardless of
any ceiling; what falls is the causal story F19 attached to it. The empirical union is also an oracle over
outcomes known after the fact, so it was never an operational ceiling in the first place.

**The price crossing was selection on the test set.** F23 reported decision depth beating the free entropy at
λ = 0.40, and F29 was written on the strength of it. The threshold for each signal was chosen on the same 488
items that scored it. Choosing on a validation half and scoring on the other, over 400 splits:

| λ | free entropy | decision depth | depth − entropy | verdict |
|---|---|---|---|---|
| 0.20 | 0.7012 | 0.6826 | **−0.0187** [−0.0855, +0.0500] | FAIL |
| 0.40 | 0.6424 | 0.6387 | **−0.0037** [−0.0814, +0.1101] | FAIL |

Decision depth is WORSE at both prices once its threshold is chosen honestly, and both intervals span zero. The
crossing is withdrawn. The reviewer's first hypothesis — a boundary effect on a difference worth about four
correct answers in 488 — is what the data support.

**What that does to F29.** Its requirement stands and its evidence does not. Storing the curve rather than the
scalar is still right, because a scalar cannot express an operating point; but the demonstration that rankings
actually cross in this data is gone, and F29 should not be cited as showing that they do.

**And the design fix the reviewer proposed is null here.** Every readout in this study predicted whether the BOX
is right. The quantity that decides an escalation is the uplift `Y_api − Y_box`: detecting a failure the API also
fails is worth nothing, and the base rates differ (box wrong 0.3463, uplift positive 0.2561). Trained on the same
free features with the same protocol, targeting the uplift instead:

| λ | uplift minus box-wrong | verdict |
|---|---|---|
| 0.05 | −0.0003 [−0.0119, +0.0107] | FAIL |
| 0.10 | −0.0013 [−0.0138, +0.0083] | FAIL |
| 0.20 | −0.0003 [−0.0151, +0.0195] | FAIL |
| 0.40 | +0.0008 [−0.0257, +0.0324] | FAIL |

Right in principle, worth nothing at this sample size — recorded so it is not proposed again as an untried idea.

**What it cost.** Two live conclusions. Both were mine and both had the same shape as the earlier withdrawals: a
statistic computed on a sample and written down as a property of the world, with the selection step that produced
it left out of the sentence. This is the fifth and sixth instance of F31's provenance defect, and the first two
that were caught by a check rather than by a reviewer noticing a hole.

**What would discharge it.** Two mechanical rules, both of which the earlier entries can be re-run against:

- A rate reported with its sample size and interval, never as a bare number, whenever it is used to rule
  something out. F19's 0.8934 would never have carried its conclusion if 0.9156 had been printed beside it.
- A threshold or hyper-parameter chosen on the data it is scored on flagged automatically. This is the most
  common selection error in the study and it is detectable by inspection of the code path, not by judgement.

## F33 — The gates can express all eight withdrawals, which is less than catching them

**Where it bit.** F31 named the cause of the withdrawals and proposed five gates. A proposal is not a mechanism,
and this study has spent enough rounds on findings that turned out to be about the measurement to be suspicious
of one more claim about process. So the gates were written down as code and each withdrawn claim replayed as a
record through them — mutation testing applied to the reporting pipeline rather than to the model, with a canary
carrying a small real effect that must be ACCEPTED so that a gate set which rejects everything cannot score well.

| withdrawn claim, replayed | rejected by |
|---|---|
| F16, the geometry swapped | control (the null reaches 0.0133 against the claim's 0.00081); perturbation (moves tenfold along the ridge) |
| F17, a percentile band labelled a floor | reachability (budget 126 against an arithmetic minimum of 167) |
| F19, a ceiling asserted below the floor | reachability (upper bound 0.9156 does not exclude 0.90); interval (a rate ruling something out with no n) |
| F22, a union reported as one setting | control (aggregated differently from the claim) |
| F22b, the control beating the claim | control (shuffled 0.0723 against real 0.0630) |
| F23, a threshold selected on the scored set | selection |
| F28, realised cost used before the call | worst row (only 12.8% of the gain survives) |
| F30, a pass with no magnitude floor | magnitude floor |

**Eight of eight rejected, and the canary accepted.**

**And this is not an independent test, which is the point worth recording.** The mutations and the gates were
written by the same person in the same sitting, so what it demonstrates is that the eight failures are
EXPRESSIBLE as mechanical rules — not that a ninth, novel failure would be caught. The value is narrower and
real: each of the eight is now a regression test that a future round cannot reintroduce silently, and the canary
makes the type-II direction visible, which every previous version of this discipline in the ledger left
unmeasured.

**One limit is already visible from the matrix.** F16 was caught by the control and perturbation gates and NOT by
the contract gate, because its `representation` field was filled in honestly. A contract catches an omitted
argument; it cannot catch a misstated one. So the contract is a weaker instrument than F31 implied, and what
actually did the work here is the pair of gates that recompute something — the control and the perturbation —
rather than the pair that read what the author wrote.

**What it cost.** Minutes. It is recorded because it changes what F31 should ask for: not a form to fill in, but
the two or three gates that recompute a quantity a different way and compare. A field an author fills in is
worth about as much as the author's care, which is what the eight withdrawals already measured.

**What would discharge it.** The recomputing gates run as part of producing a number rather than as a check on it
afterwards — the same argument the change-pipeline makes for running a mechanism in the cheapest available
harness. The code is `gate/claim_gate.py` in the study's scratch tree, deliberately not in tierbook: it is a
discipline for the research, and nothing in the mechanism has asked for it.

## F34 — Six rounds measured a logit lens and called it a J-lens

**Where it bit.** Re-reading the paper (arXiv:2607.15495v1) after eight rounds of experiments built on it. Five
things in this study were not what the paper describes, and the first is not a detail:

| what this study did | what the paper defines |
|---|---|
| read `softmax(W_U · norm(h))` | `lens(h_l) = softmax(W_U · norm(J_l h_l))`, and a J-lens vector is a ROW of `W_U J_l` |
| never computed `J` at all | `J_l = E_{t, t'≥t, prompt}[∂h_final,t' / ∂h_l,t]`, averaged over 1,000 prompts |
| treated `J` as a same-position gradient | the expectation runs over **all subsequent positions** `t' ≥ t` |
| added `α·d` along a fitted discriminant | **swapped lens coordinates**: `h + V(σ(c) − c)` with `V = [v_s v_t]`, `c = V†h` — substituting one concept for another |
| intervened at L28, last position only | **all token positions**, across a **band** of intermediate layers |
| recorded the band as normalised L38–92 | the band is roughly **30–80% of depth** — L12–L32 in a 40-layer box |

So the readout in every round was a logit lens. `W_U` was extracted correctly and the wiring was verified, but
`J` was implicitly the identity, which is exactly the object the paper's construction exists to replace. And the
intervention was a different operation from the paper's in three ways at once: additive rather than
substitutional, one position rather than all, one layer rather than a band.

**What it cost.** It explains the shape of every negative result without excusing any of them. F22's withdrawn
comparison of 15% against the paper's 59% was not merely a difference of measure — it was a different
intervention. And the paper's reported numbers come from Claude Sonnet, Haiku and Opus 4.5/4.6, not from a 35B MoE,
so even a correct replication would be a cross-model comparison.

**What it does NOT explain, and this is the correction that matters most.** The paper states that next-token
prediction is not workspace content, and it was tempting to conclude that the negative results were predicted:
the readout was about the letter the box was on the point of emitting, and F25 measured 84.3% of the discriminant
inside the letter span. But **the quantity this study actually needs is not next-token confidence — it is how hard
the ITEM is**, meaning which tier can solve it. That is a property of the input and the paper's exclusion does not
reach it. The probe was contaminated; the target was never the wrong kind of thing.

**What would discharge it.** Computing `J`. It does not need backward passes, which is what made it look
impractical on an FP8 MoE: patching `h_l` with `εv` and reading the change in `h_final` at subsequent positions
gives `J_l v` from forward passes alone, so a few hundred random `v` over a few dozen prompts sketch a low-rank
`J_l`, at three layers in the band rather than all forty. That the box's thirty Gated DeltaNet layers carry
recurrent state does not obstruct it — the patch and the readout both act on the residual stream.

## F35 — Item difficulty IS in the residual, and the free signal already has all of it

**Where it bit.** The corrected target. Every previous round predicted whether the BOX is right; this one predicts
how hard the ITEM is, on two estimands, with the letter span projected out of the residual first.

| target | contaminated residual | letter span removed | category | free entropy | null 95th |
|---|---|---|---|---|---|
| tier depth (which rung first solves it) | 0.3242 | **0.2928** | 0.1382 | **0.4506** | 0.1670 |
| 2PL difficulty | 0.5252 | **0.3354** | 0.1631 | **0.5922** | 0.1630 |

**Difficulty survives the decontamination on both targets**, well clear of the permutation null — so the
representation is there, and the six rounds of negative results were not because the quantity is absent.
Removing the letter span costs a lot (0.5252 to 0.3354 on the 2PL target), which is F25 measured from the other
side.

**But the free entropy leads on both, and the residual adds nothing when capacity is matched.** Concatenating 2,048
residual dimensions onto three free features made held-out performance FALL, which is a capacity failure rather
than an information statement, so a separate test was registered in which the residual enters as its own
cross-fitted prediction — one column against one column:

| target | free entropy alone | plus the residual | difference |
|---|---|---|---|
| tier depth | 0.3276 | 0.3293 | +0.0017 [−0.0326, +0.0198] |
| 2PL difficulty | 0.5523 | 0.5496 | −0.0027 [−0.0403, +0.0188] |

Both fail a floor of 0.05. The residual alone reads 0.1887 and 0.3367 as a single column — real, and redundant.

**What it cost.** It closes the last framing the readout had, on the target that is actually the routing question,
with the contamination removed and the capacity matched. What died is the economics and not the existence, and
those are different claims that this ledger has previously run together.

**What would discharge it.** Nothing in the mechanism. Recorded because the next round should ask whether an
external cue can INSTALL difficulty in the workspace rather than whether it can be decoded from an unprompted
pass — the paper's directed modulation shows an instruction puts a concept into the workspace at positions that
have nothing to do with it, and a decoding failure says nothing about that.

## F36 — The fallback to A is not a verbalizable strategy either

**Where it bit.** A mechanistic question with a prediction on both sides. The box answers `A` on 24% of items and
is wrong on 61% of those. If that fallback is a STRATEGY — guess, skip, unsure — it is the kind of thing a model
would say on reflection, so it should be workspace content and its direction should lie mostly OUTSIDE the
answer-letter span. If it is noise in the choice of the next token, it should sit inside the span, as the
correctness discriminant did at 84.3%.

| | value |
|---|---|
| internal direction, held-out AUC separating escape-A from correct-A | 0.8285 |
| category-preserving permutation null, 95th percentile | **0.7928** |
| the free entropy on the same items | **0.8895** |
| fraction of the direction inside the letter span | **75.4%** |

**Criterion (i) passes and (ii) fails**, so the strategy reading is not supported: at 75.4% the escape direction is
nearly as letter-bound as the correctness discriminant, and it loses to the free entropy on its own question.

**And criterion (i)'s pass is thin for a reason worth recording.** The null sits at 0.7584 median because a
category-stratified permutation preserves each category's escape rate, and category alone predicts the fallback
well. Against that null the real direction gains 0.036. The threshold of 0.60 was set without reference to where
the null would land, which is the same defect as F30's missing magnitude floor — a criterion fixed in advance is
not enough if it is fixed in ignorance of the null.

**What it cost.** Nothing to run. It removes the most promising remaining reading of the study's one free signal:
"answered A" predicts errors, and the reason is not a strategy the model is holding.

**What would discharge it.** A criterion registered together with its null, computed on a fixture before the real
data is opened. The gate set in F33 has the pieces for this and did not have this rule; it is the ninth failure
and the first the gates could not have caught.

## F37 — The target was one coin flip per tier, and difficulty is not one-dimensional across tiers

**Where it bit.** A review's first correction to the corrected target. "Which rung first solves it" is built from
one Bernoulli observation per system, so it carries the full measurement error of a coin flip and discards the
items where a cheaper arm succeeds and a dearer one fails. A tier holding several arms gives several draws per
item, so the tier's success probability is estimable instead. Grouping the sixteen arms into three tiers and
shrinking each item's rate toward its tier's prior:

| tier | arms | pooled accuracy | mean cost per item |
|---|---|---|---|
| box | 5 | 0.6656 | $0.000065 |
| cheap | 2 | **0.5738** | $0.000307 |
| strong | 5 | 0.8504 | $0.005796 |

**Two things fall out that the ordinal target could not express.** The cheap tier is WORSE than the box, not
cheaper-and-better — so a ladder ordered by price is not ordered by capability. And the tiers are only weakly
aligned: box against strong correlates **+0.3805**, box against cheap +0.5144, cheap against strong +0.4830.
**44 of 488 items have the cheap tier beating the strong tier by more than 0.05, and 56 have the box beating it.**
Difficulty is not a single number that all tiers agree on, which is what both the ordinal ladder and the 2PL's
single `b_i` assume.

The allocation is also stable in the value of a correct answer, which answers an earlier adversarial objection
about that parameter deciding the result: from `V = $0.05` to `V = $1.00` the optimal split moves only from
303/40/145 to 299/36/153 across box/cheap/strong.

**What it cost.** Every difficulty measurement before this one used a target with avoidable noise and a
monotonicity assumption that about one item in ten violates.

**What would discharge it.** A recorded outcome that can hold several draws per candidate, which is F4 asked for
a second time and now with a use: without repeats there is no tier probability, only a coin flip, and the whole
decision-theoretic form below needs probabilities.

## F38 — The value of perfect difficulty knowledge is 100 to 1700 times what the observation costs

**Where it bit.** A review pointed out that eight rounds measured signals without ever computing the ceiling on
what a signal could be worth. The value of an observation is the improvement in DECISION value, and its upper
bound is the value of perfect information — if EVPI is already below what the observation costs, no signal is
worth measuring however good it is.

`EVPI = E[max_a U(a | perfect knowledge)] − max_a E[U(a)]`, the second term being the best single fixed tier,
since a router that knows nothing sends everything to one place:

| V | best fixed tier | EVPI per item | against a prefill readout | against a full generation |
|---|---|---|---|---|
| $0.02 | box | 0.00309 | **101.6×** | 1.1× |
| $0.05 | strong | 0.00637 | 209.2× | 2.2× |
| $0.20 | strong | 0.01358 | 445.7× | 4.7× |
| $1.00 | strong | 0.05215 | **1712.1×** | 17.9× |

> **Correction, same session, in the diff form this ledger requires.**
>
> - **Claim withdrawn:** F38's headline, that perfect difficulty knowledge is worth 100 to 1712 times a
>   prefill readout, and the conclusion "the economics are not the barrier".
> - **Invariant broken:** the maximum was taken over estimated tier probabilities, so
>   `E[max_a mu_hat] >= max_a E[mu_hat]` and the oracle selects whichever tier happened to be
>   over-estimated. The bias is asymmetric across tiers because the cheap tier has two arms where the
>   others have five.
> - **Verified replacement:** with each tier's arms split, the oracle built on one half and scored on the
>   other half's raw outcomes, the gap is **+0.00198 at V=$0.02 (49.5% of the plug-in figure, 65x a
>   prefill), +0.00011 at V=$0.05 (1.7%, interval spanning zero), and significantly NEGATIVE at
>   V=$0.20 (−0.00927, [−0.01581, −0.00288]) and V=$1.00 (−0.05927, [−0.09097, −0.02850])**. Item-level
>   routing built from finite data LOSES to the best fixed tier once a correct answer is worth
>   $0.10 or more, because there the best fixed action is "always strong" and the estimates are not good
>   enough to beat a constant.
> - **Blast radius:** F38's ratio table and its "not the barrier" conclusion. The decision-point half of
>   F38 is unaffected — it is an argument about when a signal becomes available, not a value estimate.
>   F39's honest-scoring failure is retro-explained by this. F40's ceiling and share figures are
>   correlations against a split-half bound and do not use the plug-in maximum, so they stand; what does
>   not stand is F40's sentence putting them "beside F38's EVPI".
>
> The quantity F38 computed should be called a plug-in upper-envelope gap. What survives is narrower and
> more useful: **there is one regime where item-level routing pays — where the strong tier is barely
> affordable — and outside it a constant policy is better than anything this sample can learn.**

**The economics are not the barrier.** A prefill readout costs about $0.000030 of L40S time and perfect
difficulty knowledge is worth between $0.003 and $0.052 an item. Every signal this study has measured had room to
pay, and none of them captured enough of the ceiling to do it. That is a statement about the signals, and it is
the first time this study can say so rather than suspecting it.

> **Second correction, same session.** The paragraph below is a HYPOTHESIS, not a measurement, and it was
> written as though it were measured.
>
> - **Claim narrowed:** "the internal readout adds nothing at the decision point where the free signal is
>   also free, and at the decision point where the free signal costs a generation it has never been
>   measured."
> - **Invariant broken:** the broad form implies there is no free signal at prefill in the explaining
>   condition. There is — the first generated token's distribution, the prefill residual, and the logits
>   of a forced answer suffix all exist before generation. What is unavailable is specifically the ANSWER
>   distribution's entropy.
> - **Verified replacement:** in the terse condition the answer IS the first generated token, so the two
>   decision points COINCIDE and this capture cannot separate them. Every comparison in this study is of
>   that kind. Whether the first-token distribution carries comparable information in the explaining
>   condition is unmeasured.
> - **Blast radius:** the paragraph below and the "97 times cheaper" figure, which compares against a
>   generation the router may not need. The claim survives only if, in the explaining capture, the
>   at-prefill entropy is materially worse than the after-generation entropy — registered at 0.05 in
>   held-out Spearman. If it is as good, a router uses it and the timing argument is void.

**And it exposes a decision point this study never measured at.** The free entropy that beat every internal
readout is the entropy of the answer distribution. In the terse condition the answer is the next token, so that
entropy is a prefill quantity and the residual has no cost advantage over it — which is the comparison every
round has run. **In the explaining condition it is not**: the answer distribution does not exist until the box
has written its reasoning, so obtaining the free signal costs a full generation. At `V = $0.02` a generation
costs nine tenths of the entire EVPI, and the prefill residual is about 97 times cheaper.

So the honest form of the study's central negative result is narrower than it has been stated: **the internal
readout adds nothing at the decision point where the free signal is also free.** At the decision point where
the free signal costs a generation, it has never been measured — and that is the condition the box would
actually be deployed in, since it is where it scores 0.7597 rather than 0.6244.

**What it cost.** Nothing to compute; it is arithmetic over the tier target. What it changes is which measurement
matters next, and the answer is the one that has failed twice on GPU: the explaining condition's residuals.

**What would discharge it.** An observation carrying the availability F21 already asks for, used for the purpose
this entry found: a policy compared against a baseline whose own signal is unavailable at the policy's decision
point is not a fair comparison, and nothing in the record currently says when a signal becomes available.

## F39 — The residual reads difficulty and not uplift, and uplift is what decides

**Where it bit.** Asking the routing question on the quantity that actually chooses the action. Every round so far
predicted something adjacent to the decision — whether the box is right, how hard the item is, which rung solves
it. What decides an escalation is the UPLIFT: how much more likely the stronger tier is to be right. With tier
probabilities estimated from several draws per item (F37) the uplift is a difference of probabilities rather than
a difference of coin flips, so it can be predicted.

| target | clean residual alone | free signals | free + residual | permutation null, 95th |
|---|---|---|---|---|
| uplift, strong minus box | **0.0741** | 0.1996 | 0.1725 | **0.0778** |
| uplift, cheap minus box | **0.0740** | 0.2217 | 0.2238 | **0.0702** |

**The residual does not see the uplift at all.** It is indistinguishable from a permutation null on both, where the
same residual reads item difficulty at 0.2928 to 0.3354 (F35). So the internal state knows "this item is hard" and
does not know "a stronger model would fix it", and those are different facts. **This explains six rounds of
negative results mechanically** rather than by exhaustion: a signal that detects a failure the dearer tier also
fails is worth nothing, and difficulty is largely that kind of signal.

**And the economics show a first significant gain, at one operating point.** Choosing a tier by expected utility
from cross-fitted tier probabilities, with the registered floor of `0.005 × V` and a paired bootstrap:

| V | oracle | all box | free | free + residual | difference | verdict | share of EVPI captured |
|---|---|---|---|---|---|---|---|
| $0.05 | 0.0431 | 0.0332 | 0.0368 | 0.0377 | **+0.00093** [+0.00015, +0.00173] | **PASS** | 36% → **45%** |
| $0.20 | 0.1779 | 0.1331 | 0.1640 | 0.1650 | +0.00101 [−0.00049, +0.00246] | FAIL | 69% → 71% |
| $1.00 | 0.8968 | 0.6655 | 0.8411 | 0.8442 | +0.00313 [−0.00327, +0.00973] | FAIL | 76% → 77% |

> **Correction, same session, in the diff form this ledger requires.**
>
> - **Claim withdrawn:** F39's economic pass at `V = $0.05` (+0.00093, interval above zero).
> - **Invariant broken:** the policy chose a tier from estimated tier probabilities and was then scored
>   with those same probabilities, so an estimate that happened to be optimistic about a tier both
>   selected it and rewarded it.
> - **Verified replacement:** each tier's arms were split into a fitting half and a scoring half fixed in
>   advance; the predictor sees only the fitting arms and the reward comes from arms it never saw. Under
>   that scoring the difference is FAIL at every one of six values of V, with every interval spanning
>   zero: +0.00045, −0.00035, +0.00038, +0.00119, +0.00162, +0.00311 at V of 0.02, 0.05, 0.10, 0.20,
>   0.50, 1.00 against floors of 0.005·V.
> - **Blast radius:** the economic table below and the EVPI-capture column derived from it. The free
>   signals' own gain over sending everything to the box survives and is large (0.8569 against 0.6639 at
>   `V = $1.00`); what is withdrawn is the residual's increment on top of them. F40 is unaffected — it
>   measures correlations against a split-half ceiling and never scores a policy.

**The structure is the finding, not the pass.** Where a correct answer is worth little the strong tier is barely
affordable, the free signals capture only 36% of the available value, and the residual adds nine points of that
capture — about ninety-three cents per thousand items, significant under a criterion fixed in advance. Where a
correct answer is worth a lot the free signals already capture 76% and there is almost nothing left to add. So
the internal readout's value is not zero and not general: it is concentrated in the regime where escalation is
marginal, which is exactly the regime a single reported number would average away.

**What it cost.** Nothing new to run. It is the first economically significant result the internal readout has
produced in nine rounds, and it arrived only after the target was changed from box correctness to tier uplift and
the estimand was given several draws per item.

**What would discharge it.** Two things, and the first is a warning rather than a request:

- **This is one operating point out of three and it is small.** F29's rule applies to it as much as to anything
  else: it is a point on a curve, and quoting "+$0.93 per thousand" without `V = $0.05` beside it would repeat
  the defect this ledger has recorded six times.
- A policy able to hold a per-candidate success probability rather than a single quality estimate, since the
  action here is chosen by comparing `p_tier × V − cost` across tiers and that needs a probability per candidate.
  This is the concrete form of what F37 asks for, and the two would be discharged together.

## F40 — The uplift is reliably measurable and almost nobody predicts it

**Where it bit.** F39 found the residual indistinguishable from a permutation null on the uplift, and that has two
explanations: the residual cannot see it, or the target is too noisy for anything to see it. The free signals
reaching 0.1996 on the same target argues for the first, but an argument is not a measurement. Splitting each
tier's arms in half and correlating the two halves' uplifts bounds what any predictor could reach:

| quantity | split-half | Spearman-Brown | ceiling on any signal |
|---|---|---|---|
| box success | 0.9107 | 0.9532 | 0.9763 |
| strong success | 0.6383 | 0.7792 | 0.8827 |
| **uplift, strong minus box** | **0.7593** | **0.8632** | **0.9291** |
| uplift, cheap minus box | 0.4513 | 0.6219 | 0.7886 |

**The target is not the limit.** The uplift is reliable enough that a predictor could reach 0.93. Dividing the
observed correlations by that ceiling:

| signal | correlation with the TRUE uplift | share of the ceiling |
|---|---|---|
| the free signals | 0.2148 | **21.5%** |
| the letter-cleaned residual | 0.0798 | **8.0%** |

So the residual is about a third as good as free, and **the free signals themselves capture only a fifth of what
is there.** Seventy-eight per cent of a reliably defined quantity is unpredicted by anything measured here.

**This is the strongest statement the study can make, and it is not about the readout.** Put beside F38's EVPI —
perfect difficulty knowledge is worth 100 to 1700 times a prefill readout — the shape is: **a quantity that is
reliably defined, economically valuable, and essentially unpredicted.** Nine rounds of negative results about one
signal are a small part of that; the open problem is the size of the unclaimed remainder.

**What it cost.** Nothing to run. It converts the study's central negative result from "this signal failed" into a
measured bound on how much room exists, which is a different and more useful claim.

**What would discharge it.** Nothing in the mechanism, and this is the entry that says what the research should do
next rather than what tierbook should hold. Two candidates the numbers point at, in order:

- The uplift needs a signal from the STRONGER tier's side, not the box's. Every signal here is computed from the
  box, and the box has no way to know what a different model would do with the item — which is the mechanism
  behind F39. A cheap probe of the escalation target, rather than of the box, is the untried direction.
- The reliability of the cheap-minus-box uplift is much lower (0.6219 against 0.8632), which is a measurement
  problem rather than a modelling one: the cheap tier has two arms and the strong tier five. More arms per tier
  would raise the ceiling before any signal work is worth doing.

## F41 — Difficulty transfers between tiers, more to a near neighbour than a distant one

**Where it bit.** A review objected that correlations of 0.38 to 0.51 between tiers describe the data without
rejecting one-dimensionality, and that the test is a held-out model comparison. Two versions were run and the
first one's failure was informative about the estimator rather than the structure.

**The latent-index version failed, and its own estimator is why.** Fitting one difficulty per item and letting
each tier respond to it monotonically, then estimating a held-out item's difficulty from the box's five
Bernoulli draws and predicting the other tiers, is WORSE than using the tier means: −1.099 nats per draw against
−0.477, and worse still with two indices. A maximum-likelihood difficulty from five draws saturates at 0/5 and
5/5, so extrapolating it amplifies noise. Registered criterion: FAIL, reported as such.

**With the estimate shrunk, the transfer is there.** Same question without the latent machinery: shrink the box's
success rate by an empirical-Bayes prior fitted on train items, and predict each other tier's draws.

| predicting | tier mean alone | the box's shrunk rate | gain | permuted null |
|---|---|---|---|---|
| the cheap tier | −0.68174 | −0.60708 | **+0.07466** | +0.00015 |
| the strong tier | −0.41837 | −0.38793 | **+0.03044** | +0.00003 |

Both clear the registered floor of 0.005 nats per draw; the null does not move. Adding the free entropy takes
cheap to +0.10439 and strong to +0.03622, and adding category as well takes strong to +0.04410.

**The magnitudes are the finding.** Transfer to the cheap tier is **2.5 times** transfer to the strong tier. So
what the box knows about an item's difficulty is informative about a model of similar capability and much less
informative about a much stronger one — and the uplift is a DIFFERENCE, which subtracts the shared component and
leaves precisely the part the box knows least about.

**That makes F39's null mechanistically expected rather than merely observed**, and it is the third independent
route to the same place: the residual reads difficulty and not uplift (F39); the free signals reach only 21.5% of
a 0.93 ceiling on the uplift (F40); and the box's own accuracy transfers to a near neighbour 2.5 times better
than to a distant one (here). None of the three involves the residual's coordinate system, so none depends on the
readout being a J-lens.

**What it cost.** Nothing to run. It replaces a description of correlations with a held-out model comparison,
which is what the objection asked for, and it corrects a failure of my own estimator rather than letting the
first FAIL stand as a statement about the data.

**What would discharge it.** Nothing in the mechanism directly, but it sharpens what F40 asked for: a signal for
the uplift has to come from the escalation target's side, and this says why in a quantity rather than an argument
— the shared component is what a box-side signal can see, and the uplift is what remains after it is removed.

## F42 — On the items where escalation is the question, the residual knows nothing about the other model

**Where it bit.** The decomposition a review named as the only route to a mechanistic claim. The uplift is, near
enough, `P(strong right | box wrong) x P(box wrong)`, and the second factor IS difficulty, which the residual
reads. So a null on the product cannot distinguish "the residual knows nothing about the strong tier" from "the
product is hard to predict". Conditioning on the box being wrong removes the factor the residual already has.

| subset | target | residual | free signals | null, 95th | residual − null |
|---|---|---|---|---|---|
| **the box was wrong, n=173** | P(strong right) | **+0.1620** | **+0.3478** | +0.1767 | **−0.0146** |
| the box was right, n=315 | P(strong right) | +0.3135 | +0.2774 | +0.0966 | +0.2169 |
| all items, n=488 | P(strong right) | +0.3407 | +0.2739 | +0.0668 | +0.2739 |

**Two things, and together they are the sharpest result this study has.**

**On the items where escalation is the question, the residual is at the null and the free signals are far above
it.** Where the box has already failed — the only items an escalation decision is about — the residual carries
nothing about whether a stronger model will succeed, and the free signals carry a substantial amount, 0.3478
against a null of 0.1767. That is the positive control a review demanded: the target is predictable, and the
residual is not what predicts it.

**And the residual's apparent knowledge of the strong tier is entirely the shared difficulty component.** Over all
items it reads 0.3407; conditioned on the box being wrong, which is exactly where the shared component is removed,
it drops to the null. So "the internal state knows something about the other model" was reading the item's
difficulty twice, once through each tier.

**The asymmetry criterion also failed, and that one is a measurement limit rather than a finding.** Inside the
box-wrong subset there is little variation in `P(box wrong)` left to predict — the subset is conditioned to have
it high — so the residual reads it at 0.1264 against a null of 0.1288. The comparison that would establish "knows
its own failure, not the other's competence" needs a target that survives the conditioning, and this one does not.
Registered criterion: FAIL, reported as such and not reinterpreted.

**What it cost.** Nothing to run. It converts the study's central claim from a correlation on a product to a
conditional statement with a positive control, which is the form a reviewer asked for and the form that can be
defended.

**What would discharge it.** Nothing in the mechanism. It is the entry that says what the routing signal has to
be: the free output signals already carry 0.3478 about the stronger model's success on exactly the items that
matter, and no internal readout of the box has been shown to add to that. Any further work on box-side internal
signals for escalation now has to beat this number, on this subset, before it is worth measuring at all.

## F43 — Two of the tier claims survive, the non-monotonic counts do not, and the capture condition is the odd one out

**Where it bit.** A review rated three of F37's claims high-risk on the grounds that the tiers have 5, 2 and 5
arms, so shrinkage pulls them by different amounts, and that counting non-monotonic items by comparing point
estimates counts noise. Each was re-run with equal arm counts, raw rates and no shrinkage at all, over 200 random
two-arm subsets.

**Survives.** The cheap tier is weaker than the box in **200 of 200** subsets, and the correlations barely move:
box-strong +0.3428 [+0.2946, +0.3828], box-cheap +0.5051, cheap-strong +0.4426, against the shrunk figures of
0.3805, 0.5144 and 0.4830.

**Does not survive.** Counting non-monotonic items from a beta-binomial posterior rather than from point estimates:

| | point estimates | confident at 95% |
|---|---|---|
| the cheap tier beats the strong tier by >0.05 | 44 | **1** |
| the box beats the strong tier by >0.05 | 56 | **20** |

**So F37's 44 and 56 were mostly noise**, as the review predicted. The honest figures are 1 and 20 of 488. The
qualitative point — the price ladder is not a capability ladder — rests on the accuracy comparison and the
correlations, which do survive; the per-item counts were overstated by a factor of forty and three.

**And the arm-level correlation matrix, which contains no grouping decision at all, shows something the tier
summary hid:**

| | mean correlation |
|---|---|
| among the box's five prompt variants | **+0.8720** |
| among the five frontier arms | **+0.5710** |
| between groups | +0.3281 |

**One model under five different prompts agrees on items more than five different frontier models agree with each
other.** Prompt variation within a model is a smaller perturbation of item-level outcomes than model identity
among strong models — which is a fact about what "the same capability" means and is worth stating on its own.

**The part that matters for this study is narrower and uncomfortable.** `qwen3.6@terse` correlates 0.75 to 0.77
with its own four prompt variants, while those four correlate 0.93 to 0.96 among themselves. **The condition the
residuals were captured under is the outlier of the box's own family.** Every internal-signal result rests on it,
and the arm that carries the residuals is the least representative arm available.

**What it cost.** One overstated count, corrected by a factor of forty. What it bought is the arm-level matrix as
the primary object, which is what the review asked for and which needed no grouping judgement.

**What would discharge it.** A recorded outcome carrying the arm rather than a tier label, so a correlation
between arms is computable without a grouping decision, and a grouping declared as an analysis choice rather than
baked into what is stored. F37's request for several draws per candidate and this are the same requirement seen
from two sides: the draws have to remain distinguishable after they are stored.

## F44 — What the free signals know is the subject, and even that does not change the allocation

**Where it bit.** F42's positive control needed opening up. The free signals predict the stronger tier's success
at 0.3543 on the 173 items the box got wrong, and a router needs to know which component carries it.

| component | alone | the set without it | what the set loses |
|---|---|---|---|
| **category** | **+0.3522** | **+0.0817** | **+0.2726** |
| answer entropy | +0.1277 | +0.3362 | +0.0181 |
| answer margin | +0.1150 | +0.3040 | +0.0503 |
| answered A | −0.0295 | +0.2917 | +0.0626 |
| prompt length | −0.1553 | +0.3100 | +0.0443 |
| decision depth | +0.1464 | +0.3265 | +0.0278 |

The whole set reaches +0.3543 against a permutation null of +0.1610. **Category alone reaches +0.3522, and
removing it drops the set to +0.0817 — below the null.** So on the items where escalation is the question, what
predicts whether a stronger model will succeed is the SUBJECT, and no per-item quantity contributes.

**And the prescription that follows from that fails too.** If the only real signal is the subject, the right
router chooses one tier per category and nothing per item. Scored honestly — the choice made from one half of each
tier's arms on train items, the reward taken from the other half on held-out items:

| V | one global fixed tier | one tier per category | per item, free signals | per-category minus global |
|---|---|---|---|---|
| $0.02 | 0.01301 | 0.01360 | 0.01426 | +0.00059 [−0.00027, +0.00149] |
| $0.05 | 0.03962 | 0.03948 | 0.03954 | −0.00015 [−0.00101, +0.00055] |
| $0.20 | 0.17065 | 0.16869 | 0.17149 | −0.00195 [−0.00550, +0.00101] |
| $1.00 | 0.86944 | 0.86944 | 0.86944 | +0.00000 |

Every V fails the registered floor, and above $0.50 the policies are identical because everything goes to the
strong tier. At `V = $0.05` the per-category policy sends only `health` to the box and the other six subjects to
the strong tier, and that single deviation is worth nothing.

**A signal that correlates with the target need not change the allocation, and here it does not.** The decision is
dominated by the cost-benefit comparison at the tier level, and per-category variation in success does not move
any item across a boundary. This is the point a review made in general form — a gain in Spearman or AUC that does
not change a route has zero value of information — and it is now measured rather than asserted.

**So the honest conclusion for this benchmark, these tiers and these prices is that the best policy this sample
supports is a single fixed tier.** Per-item routing loses to it above `V = $0.10`, per-category routing does not
beat it at any V, and the residual adds nothing to either. That is a complete negative result about routing on
this setup rather than a negative result about one signal, and it is worth more than the nine rounds that produced
it because it says where the remaining value is not.

**What it cost.** Nothing to run. It closes the prescription the previous three entries were converging on, which
is better than leaving it as an untested recommendation.

**What would discharge it.** Nothing. This entry is why the ledger's requirements should not be built yet: the
mechanism this study was going to inform has, on the data available, no allocation to make. F40's remainder is
where the value is — 78% of a reliably defined uplift is unpredicted — and until something predicts it there is
nothing for a policy to act on.

## F45 — The Jacobian the J-lens needs is not defined on this box, and the reason is the router

**Where it bit.** Building `J_l` for real, which F34 identified as the thing eight rounds of this study had
skipped. It does not need backward passes: patching `h_l` with `eps*v` and reading the change in the final block's
output gives `J_l v` from forward passes alone. A pre-registered linearity gate ran first — with `r(a)` the
central-difference response at amplitude `a`, 90% of (direction, prompt) pairs had to satisfy
`cos(r(a), r(a/2)) >= 0.995` and a norm ratio in [0.90, 1.10].

**It failed 0 of 96 at every amplitude.** Three controls then settled why, and it was not what I assumed:

| control | result | what it rules out |
|---|---|---|
| a zero perturbation | output moves by **0.000e+00** | the patch machinery is correct |
| the same perturbation twice | output moves by **0.000e+00** | the forward is fully deterministic; there is no stochastic noise floor |
| expert sets under the patch | **16.28% of tokens change, up to 50.72% in one layer** | this is the cause |

> **Correction, in the diff form this ledger requires.**
>
> - **Claim withdrawn:** the third control's figure — 16.28% of tokens changing their expert set, up to
>   50.72% — and the reading that routing flips make the function piecewise linear.
> - **Invariant broken:** the module hooked was `mlp.gate`, which in this family is not the top-k router.
>   Substituting its output on 40 of 40 calls left the final hidden state **bit-identical**
>   (`max |clamped − free| = 0.000000e+00`, against `max |free − clean| = 4.30`), and a forward hook's
>   return value does replace the output the caller sees. A tensor whose substitution changes nothing is
>   not the routing tensor, so the flip fraction was the top-8 of the wrong quantity.
> - **Verified replacement:** none yet. The flip fraction is unmeasured, and the router-clamp comparison
>   that appeared to exonerate routing measured nothing either.
> - **Blast radius:** the third control's row, the sentence below it, and this entry's diagnosis. What
>   still stands is controls 1 and 2 (the patch machinery is correct; the forward is exactly
>   deterministic), the amplitude sweep, and the gate's FAIL — none of those involve the gate module.
>
> So the cause of the linearity failure is now **unknown**, not routing. The candidates that remain are
> the Gated DeltaNet recurrence carrying a perturbation through thirty of forty layers, the RMSNorm
> non-linearity, and the curvature of a forty-layer network. The next step is identifying the real
> router by what its output looks like rather than by its name.

**And the amplitude sweep runs the opposite way to the usual one:**

| alpha | cos median | norm ratio | ‖r‖ median |
|---|---|---|---|
| 0.001 | **−0.0026** | 0.4696 | 1.229e-01 |
| 0.005 | 0.0521 | 0.5065 | 2.798e-02 |
| 0.020 | 0.4184 | 0.6573 | 9.767e-03 |
| 0.050 | 0.8170 | 0.8802 | 8.736e-03 |
| 0.200 | **0.9765** | 0.9714 | 8.051e-03 |
| 1.000 | 0.9593 | 0.9820 | 7.547e-03 |

**Small amplitudes are pure noise, not precision.** At 0.001 the two responses are uncorrelated and the response
norm divided by epsilon BLOWS UP — the signature of a quantisation floor, since FP8 activations round a
small perturbation into the same bucket and the difference is a rounding artefact. The cosine peaks at 0.9765
around alpha 0.2 and falls again by 1.0, so there is a best amplitude and it does not reach the registered 0.995.

**Registered gate: FAIL, and it is not a matter of choosing epsilon better.** Below the quantisation floor there
is no signal; above it the routing has already moved. The derivative the J-lens is built from is not defined on
this box at any amplitude that clears the numerics, and that is an obstruction specific to a fine-grained MoE
rather than a tuning problem.

**What it cost.** The J construction, in its literal form. It is also the answer to a question this study has been
carrying since F34 — whether measuring on a MoE with linear-attention layers is a contribution or a confound. It
is neither: it is an obstruction to the method, and that is a more useful thing to have found than either.

**What would discharge it.** A different object, well defined, stated as different: the Jacobian of the network
with the **routing held fixed** to the unperturbed pass. Freezing every expert assignment makes the remaining map
smooth, and it is what the paper's construction computes on a dense model. That test is written and registered
with the same two-amplitude criterion plus a control that the expert-flip fraction is exactly 0 once clamped, and
the unclamped numbers reported beside it at the same amplitudes. If it passes, this study gets a `J` and can say
precisely which `J` it is; if it fails, the J-lens is not computable here by any route available to me.

## F46 — The Jacobian is computable at the deep end of the band and not at the shallow end

**Where it bit.** F45 concluded that the derivative the J-lens is built from is not defined on this box at any
amplitude clearing the numerics. That was measured with the four probe layers pooled into one pass fraction, and
pooling was the error: `J_l` is a separate object per layer, so the criterion belongs to each layer. Applied per
layer, with the router clamped by its input and the flip fraction verified at exactly 0.0000:

| layer | depth | α=0.2 pass | cos median | α=0.5 pass | cos median | cos min |
|---|---|---|---|---|---|---|
| L12 | 30% | **0.050** | 0.9689 | 0.150 | 0.9744 | 0.9467 |
| L22 | 55% | 1.000 | 0.9924 | 1.000 | 0.9919 | 0.9865 |
| L32 | 80% | 1.000 | 0.9981 | 1.000 | **0.9965** | **0.9942** |
| L39 | 98% | 1.000 | 0.9999 | 1.000 | **0.9990** | **0.9977** |

**Monotone in depth, and the pooled failure was entirely L12.** At L39, one block from the readout, the response
is linear to four decimal places — exactly what the architecture forces, which is the canary working. At L32 and
L39 the **original** 0.995 criterion is met (minimum cosines 0.9942 and 0.9977). At L22 it is not (0.9865) but 0.98
is. At L12 neither.

> **Correction to F45, in the diff form this ledger requires.**
>
> - **Claim withdrawn:** "the derivative the J-lens is built from is not defined on this box at any amplitude
>   that clears the numerics", and with it the framing that this is an obstruction to the method as such.
> - **Invariant broken:** the pass fraction pooled four layers, so one failing layer sank three passing ones.
>   A criterion has to be applied at the granularity of the object it judges.
> - **Verified replacement:** with the router clamped, the original criterion is met at L32 and L39 and failed
>   at L12; L22 sits between. Linearity degrades monotonically with distance from the output.
> - **Blast radius:** F45's headline and its conclusion about MoE architectures. What stands from F45: the FP8
>   quantisation floor at small amplitudes, the determinism controls, the amplitude sweep at L22, and the fact
>   that routing is part of the limit.

**What this says about the paper's construction on this box.** The band the paper reports as the workspace is
30–80% of depth, which here is L12 to L32. **The Jacobian is usable at the deep end of that band and not at the
shallow end** — so a J-lens built at L32 rests on a linear response, and one built at L12 does not. That is a
statement about where the method applies rather than whether it applies, and it is the opposite of what F45 said.

**What it cost.** One over-broad conclusion, withdrawn within the day. It is the fourth time in this study that a
claim of mine was too general for its evidence, and the third that a granularity choice was the cause.

**What would discharge it.** Nothing in the mechanism. The build is now running for L22, L32 and L39 with α=0.5,
and its usability is decided by internal checks registered before it finished: split-half agreement, the identity
ordering with depth, the leakage outside the activation subspace, and the paper's variance-share claim computed
with the logit lens as a control.

## F47 — J exists, it is a stable estimate, and the paper's variance claim is true and uninformative

**Where it bit.** The thing this study skipped for eight rounds. `J_22` is now built from forward passes with the
router clamped by its input, and the checks registered before it existed have been run on it.

| check | result | criterion |
|---|---|---|
| split-half entry correlation | **0.9612** | ≥ 0.70 — **PASS** |
| split-half relative Frobenius | **0.3355** | ≤ 0.60 — **PASS** |
| diagonal mass share | 0.108134 | a random matrix gives 1/2048 = 0.00049, so **220×** that |
| leakage outside the activation subspace | 0.8282 | reported, not gated |

**So the estimate is stable**: two disjoint halves of the probe prompts agree at 0.9612, which is the first time
this study has had a verified `J` rather than an assumption about one. The diagonal carries 220 times the mass a
random matrix would, which is the structure a Jacobian of a residual network should have.

**And the paper's headline claim, measured with its nulls for the first time:**

| k | J-lens | logit lens | random k-subspace | top-k PCA |
|---|---|---|---|---|
| 16 | **1.75%** | 1.34% | **0.78%** | 67.88% |
| 25 | 2.47% | 1.93% | 1.22% | 72.99% |
| 64 | 5.68% | 4.35% | 3.12% | 82.08% |

**"Under 10% of activation variance" is true, and it is true of the null as well.** A random k-dimensional
subspace holds 0.78% to 3.12%; the leading principal directions hold 68% to 82%. The J-lens subspace holds about
2.2 times the random subspace and a twelfth of the PCA subspace. So the claim as stated is satisfied by
essentially any subspace not aligned with the leading principal directions, and on its own it is not evidence
about where a model keeps information.

**The ordering is the informative part, and it runs the other way.** `J-lens > logit lens > random` at every k.
Applying `J` moves the readout subspace AWAY from random and TOWARD holding more variance — the opposite
direction from "the information sits in a low-variance subspace, which is why it is special". This is measured on
the right object, unlike F16's withdrawn 0.081%, which was the variance share of a fitted discriminant and a
property of the ridge.

**What it cost.** Nothing that was not already spent. What it produced is the first quantitative statement this
study can make about the paper rather than about its own probes, and the shape of it is that a number can be
reproduced and still carry no evidence — which is the same lesson as F16 arriving from the opposite side.

**Two caveats, stated rather than buried.** The activations are the terse condition's residuals at one position
per item, not a general corpus, so the variance shares are shares of THAT distribution. And what is estimated is
`J P_V`, the Jacobian restricted to the probe basis; the leakage ratio of 0.8282 says the part of `J`'s row space
outside where activations live responds at 83% of the strength of the part inside it, so the restriction is not a
formality.

**What is still pending.** L32 and L39 are still building, so the depth-ordering check — the one that would show
the plumbing is right by reproducing what the architecture forces — has only one layer to work with so far.

## F48 — The J-lens readout beats its null and not the logit lens, and it changes what the readout is about

**Where it bit.** The question the whole study was set up to answer, asked for the first time on a real `J`. One
design consequence had to be settled first: a linear probe on `norm(J h)` is a linear function of `h`, so by linear
closure it cannot beat a linear probe on `h`, and every negative result already recorded covers it. What is not
covered is a readout passing through the VOCABULARY and the SOFTMAX, which is what the paper's lens is. So the
features are non-linear functions of `softmax(W_U norm(J h))`, registered before running, with two controls.

| readout | entropy | max probability | verbaliser log-odds | answer-letter rank | four combined |
|---|---|---|---|---|---|
| **J-lens** | 0.6364 | 0.5976 | **0.6870** | 0.5788 | **0.7439** |
| logit lens | **0.6838** | **0.6645** | 0.5743 | 0.5631 | 0.7002 |
| random J, matched norm | 0.5004 | 0.5161 | 0.6097 | 0.5720 | 0.6257 |

**Against the null: +0.1182, PASS.** The J-lens readout carries real information — a random matrix of the same
Frobenius norm gets 0.6257 where `J` gets 0.7439. This is the first controlled positive result for the J-lens in
this study, and it required building `J` to obtain.

**Against the logit lens: +0.0436, FAIL** on the registered floor of 0.05. Reported as a failure; the criterion
is not moved.

**The per-feature structure is the finding, and it is the paper's own distinction appearing in this box.** The two
readouts are not better and worse at the same thing:

- the logit lens wins on the next-token-shaped features — entropy 0.6838 against 0.6364, maximum probability
  0.6645 against 0.5976 — which is what it is, the next-token distribution;
- the J-lens wins decisively on the verbaliser question, whether the model is poised to say something uncertain:
  **0.6870 against 0.5743, a gap of +0.1127**, and +0.0773 over the null on that feature alone.

So applying `J` does not sharpen a readout, it **moves it from the next token to what the model would say** —
which is precisely the property the paper's construction exists to isolate, and it shows up here as a reversal in
which feature each lens is good at rather than as a uniform improvement.

**What it cost.** Nothing that was not already spent building `J`. What it settles is the question the user's
instruction named: the J-lens readout can predict, above a null, and it does not beat the free next-token readout
at the combined task on this data.

**What would discharge it.** Nothing in the mechanism. What the RESEARCH should do next follows from the
per-feature split: the verbaliser gap is where `J` earns its keep, so the next measurement is the intervention —
swapping lens coordinates across all positions and the whole band, with the router clamped — since that is the
operation the paper uses to establish the same point causally, and the one this study has never performed
correctly.

**Two caveats.** This is L22, the shallowest layer whose Jacobian passed even the relaxed criterion; L32 and L39
are still building and the deep layers are where linearity is best. And the four features were chosen before
seeing any of these numbers but they are four of many possible ones — the combined figure is not a ceiling on what
a J-lens readout could do.

## F49 — At L32 the J-lens readout beats both controls, and the mechanism is a clean reversal

**Where it bit.** F48 measured the J-lens readout at L22 and it beat the null but fell 0.0064 short of the floor
against the logit lens. L32 is the layer at the deep end of the paper's band whose Jacobian passes even the
original 0.995 linearity criterion, so it is where the estimate should be best. Same four features, same two
controls, same registered floor of 0.05, nothing changed but the layer.

| readout | entropy | max probability | verbaliser log-odds | answer-letter rank | four combined |
|---|---|---|---|---|---|
| **J-lens** | 0.5741 | 0.5779 | **0.7629** | 0.5119 | **0.7626** |
| logit lens | **0.6721** | **0.6220** | 0.5011 | 0.5974 | 0.6729 |
| random J, matched norm | 0.6102 | 0.6213 | 0.5277 | **0.6406** | 0.6797 |

**Both criteria PASS: +0.0897 over the logit lens and +0.0829 over the null.** So the J-lens readout predicts, and
it predicts better than the readout that needs no Jacobian — which is the question this study was set up to answer
and had never asked on a real `J`.

**And the mechanism is a complete reversal, sharper at L32 than at L22.** On the verbaliser question — whether the
model is poised to say something uncertain — the J-lens reads **0.7629** and the logit lens reads **0.5011**, which
is chance. On entropy and maximum probability the logit lens wins, 0.6721 and 0.6220 against 0.5741 and 0.5779.
The two lenses are not better and worse at one thing; they are about different things, and applying `J` moves the
readout **off the next token and onto what the model would say**. That is the property the paper's construction
exists to isolate, and at L32 the separation is near-total: one lens is at chance exactly where the other is
strongest.

**Depth strengthens it, consistently with the linearity measurements.** From L22 to L32: the combined margin over
the logit lens goes +0.0436 → +0.0897, the verbaliser gap goes +0.1127 → +0.2618, the split-half correlation of
`J_hat` goes 0.9612 → 0.9824, and the J-lens share of activation variance rises 1.75% → 2.33% while the logit
lens's FALLS 1.34% → 1.07%. Four independent quantities move the same way with depth.

**What it cost.** The eight rounds that measured a logit lens while calling it a J-lens, and the four hours of GPU
to build `J` properly. What it produced is the study's first result that is about the paper's object rather than
about a probe of my own.

**Two caveats, and one of them limits the claim.** The random-`J` control beats the logit lens on the
answer-letter rank (0.6406 against 0.5974) and nearly matches it overall (0.6797 against 0.6729), so at L32 a
random dense mixing is as good as the identity for this feature set — the null is not weak here, which makes the
J-lens margin over it the meaningful number rather than the margin over the logit lens alone. And the four
features were fixed before any of these numbers were seen, but they are four of many; the combined figure is not
a ceiling.

**What would discharge it.** Nothing in the mechanism. The research step it points at is the intervention: the
paper establishes the same separation causally by swapping lens coordinates across all positions and the whole
band, and that operation — with the router clamped, which F46 showed is necessary — has still never been run here.

## F49 — At L32 the J-lens readout beats both controls, and the mechanism is a clean reversal

**Where it bit.** F48 measured the J-lens readout at L22 and it beat the null but fell 0.0064 short of the floor
against the logit lens. L32 is the layer at the deep end of the paper's band whose Jacobian passes even the
original 0.995 linearity criterion, so it is where the estimate should be best. Same four features, same two
controls, same registered floor of 0.05, nothing changed but the layer.

| readout | entropy | max probability | verbaliser log-odds | answer-letter rank | four combined |
|---|---|---|---|---|---|
| **J-lens** | 0.5741 | 0.5779 | **0.7629** | 0.5119 | **0.7626** |
| logit lens | **0.6721** | **0.6220** | 0.5011 | 0.5974 | 0.6729 |
| random J, matched norm | 0.6102 | 0.6213 | 0.5277 | **0.6406** | 0.6797 |

**Both criteria PASS: +0.0897 over the logit lens and +0.0829 over the null.** The J-lens readout predicts, and
better than the readout that needs no Jacobian — the question this study was set up to answer, asked for the first
time on a real `J`.

**The mechanism is a near-total separation, sharper at L32 than at L22.** On whether the model is poised to say
something uncertain the J-lens reads **0.7629** and the logit lens reads **0.5011**, which is chance. On entropy
and maximum probability the logit lens wins. Applying `J` moves the readout **off the next token and onto what the
model would say**, which is the property the paper's construction exists to isolate.

**Depth strengthens it, consistently with the linearity measurements.** From L22 to L32 the combined margin over
the logit lens goes +0.0436 → +0.0897, the verbaliser gap +0.1127 → +0.2618, `J_hat`'s split-half correlation
0.9612 → 0.9824, and the J-lens variance share 1.75% → 2.33% while the logit lens's FALLS 1.34% → 1.07%.

**One caveat that limits the claim.** The random-`J` control beats the logit lens on the answer-letter rank and
nearly matches it overall (0.6797 against 0.6729), so a random dense mixing is as good as the identity for this
feature set. The J-lens margin over the NULL is therefore the meaningful number, not the margin over the logit
lens alone.

## F50 — Read as a cascade rather than a competitor, the readout works, and my comparison was the error

**Where it bit.** I reported F49 to the user as "no, this cannot be used for routing", on two grounds. Both were
wrong, and the user identified the error before any further measurement.

- **I counted the prefill as a cost.** If the box is going to answer, the prefill is paid regardless, so a gate
  reading the residual at L32 costs **nothing extra**. I had been comparing the J-lens (0.7626) against the answer
  entropy (0.8424) as though they competed for one slot; they are two stages, and the first is free.
- **I demanded uplift of the first gate.** F39 and F42 established that box-side signals do not read whether a
  stronger model would fix an item, and I applied that to the wrong decision. The first gate only decides whether
  to BUY MORE OBSERVATION; the uplift question arises at the final escalation, where the generation already exists
  and the stronger signal is available.

**Measured as a cascade, on held-out items, with the box scoring 0.6221 overall:**

| let through | accuracy on what passed | left for stage 2 | accuracy there | ceiling: the post-generation gate |
|---|---|---|---|---|
| **50%** | **0.8070** | 50.0% | 0.4370 | 0.8755 |
| 60% | 0.7760 | 40.0% | 0.3916 | 0.8355 |
| 70% | 0.7330 | 30.0% | 0.3636 | 0.7810 |
| 80% | 0.6964 | 20.0% | 0.3252 | 0.7253 |
| 90% | 0.6672 | 10.0% | 0.2168 | 0.6796 |

**Half the corpus can be passed straight to decoding at 0.8070**, eighteen and a half points above the box's own
average, for no additional compute. The half that is held back sits at 0.4370, which is the population worth
spending a generation on. And the post-generation signal reaches 0.8755 on the same 50% — so **the free gate
captures most of a ceiling that costs a full generation to reach.**

The right comparison is therefore "0.8070 for nothing against 0.8755 for a generation", not "0.7626 against
0.8424". Same numbers, different question, opposite conclusion.

**What it cost.** A wrong recommendation, corrected within the conversation. The defect is one this ledger has
recorded from the other side in F38: a signal's value depends on when it becomes available, and I had the
principle written down and still compared two signals from different decision points as competitors.

**What would discharge it.** The second stage has not been measured. Reading the J-lens again AFTER generation —
which is where the uplift question actually lives — needs residuals from the explaining condition, and the capture
that passed its gate (888 rows, accuracy 0.7928) stored readouts and labels but **not the residual vectors**. That
capture has to be re-run with the hidden states kept.

## F51 — The gate works in the condition it would be deployed in, and J transfers across conditions

**Where it bit.** F50 measured the free prefill gate on the terse condition, where the answer is the next token so
the "post-generation" signal is not really post-generation. The explaining condition is the one the design exists
for: there the answer distribution does not exist until the box has written its reasoning, so the readout at L32 is
the only signal available at the moment the decision is made. The explaining capture's residuals turned out to have
been stored all along — my earlier statement that it held "readouts and labels but not the residual vectors" was
wrong, from reading a truncated directory listing — so no re-run was needed.

| let through | J-lens, using the TERSE-estimated J | logit lens | random J, matched norm |
|---|---|---|---|
| 40% | **0.8592** | 0.7606 | 0.8028 |
| **50%** | **0.8571** | 0.7744 | 0.8008 |
| 60% | 0.8558 | 0.7900 | 0.8088 |
| 70% | 0.8333 | 0.7903 | 0.8038 |

The box scores 0.7853 on the 531 held-out items. **At 50% passed the gate reaches 0.8571, beating the logit lens by
+0.0827 and the null by +0.0564** — both clear the registered floor of 0.03.

**And `J_32` was estimated on terse prompts and works on the explaining condition unchanged.** That is a different
fact from F19's finding that a prompt condition reorders items: the OUTCOMES move between conditions, and the
matrix does not. `J` is a property of the weights, estimated by averaging over prompts, so it should transfer —
and it does, which is the first cross-condition transfer anything in this study has achieved after F19 showed
signals fitted in one condition do not carry to the other.

**What it cost.** Nothing; the data existed. What it settles is that the cascade design holds in the deployment
condition rather than only in the condition the residuals happened to be captured in, which was the caveat hanging
over every internal-signal result since F43 found the terse arm to be the outlier of the box's own family.

**What would discharge it.** The second stage, which remains unmeasured: reading the J-lens again after generation,
where the uplift question lives. The residuals for that exist now at both stored positions, so it is an analysis
rather than another capture.

## F52 — Stage 2 works, and the free thing beats it

**Where it bit.** The half of the cascade that had never been measured. Stage 1 is a free prefill gate; stage 2
decides, among the items stage 1 held back, whether to escalate — and that is the uplift question every earlier
attempt found the null on. Two things are different here: the readout goes through `J` and the vocabulary, and the
capture stored TWO positions, the later of which sits inside the model's own reasoning rather than before it.

On the 265 held-out items stage 1 held back, where the box scores 0.7698:

| stage-2 signal | AUC |
|---|---|
| the J-lens at the EARLIER position, the one stage 1 used | **0.4703** |
| the J-lens at the LATER position, inside the reasoning | **0.6293** |
| both positions | 0.6301 |
| generation length, free once the generation exists | **0.6978** |

**Re-reading the residual after generation carries genuinely new information: +0.1590 over the position stage 1
already used, PASS.** The earlier position is at chance on this subset, which is what it should be — stage 1 spent
that information, and what is left is what it could not separate. So the design's premise holds: there is a second
look worth taking.

**And the second look is beaten by the cheapest thing in the room.** Generation length alone reaches 0.6978. Once
the generation has been paid for, its length is free, and it is better than the J-lens readout at the same
decision. So stage 2's first choice is the token count, and the J-lens is a candidate for adding to it rather than
for replacing it.

**What it cost.** Nothing; the residuals existed at both positions. What it settles is the shape of the cascade:
the J-lens earns stage 1, where nothing else is available, and has to compete at stage 2 against quantities that
generation hands over for free.

**What would discharge it.** Whether the J-lens adds to generation length rather than losing to it, which is an
increment test with a floor and is not yet run.

## F53 — All three Jacobians verify, and the paper's variance claim breaks outside the band

**Where it bit.** The full three-layer verification, with the depth-ordering check finally having enough layers to
be a test rather than a table.

| layer | ‖J−P_V‖/‖P_V‖ | diagonal mass | split-half correlation | leakage ratio |
|---|---|---|---|---|
| 22 | 0.9956 | 0.108134 | 0.9612 | 0.8282 |
| 32 | 0.9927 | 0.153264 | 0.9824 | 0.9444 |
| 39 | **0.9924** | **0.206121** | — | 0.9933 |

**Both orderings PASS**: distance to the projected identity falls with depth and the diagonal carries monotonically
more mass, 0.108 → 0.153 → 0.206. These are what the architecture forces, so reproducing them is what shows the
estimate is of the thing it claims to be rather than of an artefact.

**And at L39 the paper's headline number fails:**

| layer | k=64 J-lens | logit lens | random | top-k PCA |
|---|---|---|---|---|
| 22 | 5.68% | 4.35% | 3.12% | 82.08% |
| 32 | 7.59% | 4.08% | 3.09% | 80.34% |
| **39** | **11.40%** | 5.84% | 3.18% | 73.41% |

At sixty-four directions the J-lens subspace holds **11.40%** of activation variance, above the paper's "never more
than 10%". **L39 is outside the band the paper reports** — depth 98% against its 30–80% — so this is a measurement
beyond the claim's stated scope rather than a contradiction of it. What it shows is that the claim is not a general
property of the construction: it holds inside the band and stops holding just outside it, which is consistent with
the band being where the workspace is and is a sharper statement than reproducing the number inside.

The ratio to the null also rises with depth at every k — 2.2×, 3.0×, 3.6× at k=16 — so `J`'s effect on the readout
subspace strengthens monotonically toward the output, matching the linearity, the split-half stability, and the
prediction margin. Five independent quantities now move the same way with depth.

**What it cost.** Nothing beyond the four and a half hours of build. It is the first time this study has said
something about the paper's claim that the paper does not already say.

## F54 — At stage 2 the Jacobian is not the reason, and the null says so

**Where it bit.** F52 left one question: the later-position J-lens loses to generation length, but losing to a free
quantity does not settle whether it ADDS to it, and that is what decides whether stage 2 should read the residual
at all. Registered before running, with the random-`J` null that F49 established is necessary.

On the 265 held-out items stage 1 held back:

| model | AUC | against length alone |
|---|---|---|
| generation length alone | 0.6978 | — |
| length + **J-lens** at the later position | 0.7356 | +0.0378 [−0.0030, +0.0754] |
| length + **random J**, matched norm | **0.7521** | +0.0542 [−0.0004, +0.1044] |

**The J-lens clears the increment floor and the null clears it by more.** +0.0378 passes 0.03; the random matrix
reaches +0.0542, so the J-lens is −0.0165 against its own null and FAILS. What helps at stage 2 is passing the
residual through a dense mixing and into the vocabulary at all — the Jacobian specifically is not the reason. And
both intervals span zero, so at 265 items even the increment over length is not established.

**So the two stages want different things, and this is the sharpest practical result of the study:**

| stage | is `J` needed? | evidence |
|---|---|---|
| **1**, at prefill, free | **yes** | +0.0827 over the logit lens and +0.0564 over the null, both passing |
| 2, after generation | **no** | the null beats it; generation length is the first choice |

The asymmetry has a reading. At prefill the only thing available is the residual, and `J` is what turns it from a
next-token readout into a what-would-be-said readout — the distinction F49 measured as a near-total reversal. After
generation the model has already said things, so the quantity `J` was recovering is observable directly, and a
random mixing suffices to extract whatever is left.

**What it cost.** Nothing; it is the same data. It stops a wrong recommendation: reading `J` at stage 2 would have
been justified by an increment that its own null exceeds.

**What would discharge it.** Nothing in the mechanism. For the research, stage 2's signal set should be built from
what generation hands over — length first — and any residual-based addition has to clear a matched-norm random
mixing, not merely the free baseline.

## Not requirements, deliberately

Kept here so they are not re-proposed as work.

- **A general residual-capture component in tierbook.** The capture is research code and belongs to the study,
  not the mechanism. Building it into tierbook is the over-engineering the policy change exists to stop.
- **A J-lens implementation in tierbook.** Whether the readout is worth anything is unsettled. Nothing goes into
  the mechanism until an experiment asks for it, and no experiment has.
- **Acting on `tenant_scope`.** v0.3.0 records it and says in its own interface that nothing acts on it. No
  experiment has needed it acted on.
