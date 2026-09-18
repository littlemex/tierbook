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

## What the whole thing amounts to, in two sentences

The user's own phrasing, which is clearer than anything in the entries below and is retained verbatim:

> **j score は生成せずに間違えそうかどうかを知ることができるので、簡単なタスクはそのまま箱に回答させることができる。thinking の有無は精度とコストからトークン費用で自動判定できる。**

Both are supported by measurement.

**The first**: a readout taken while the prompt is being read — before a single token is generated, so the reading is
free because the prefill is paid regardless — separates items the cheap path will get wrong from items it will get
right. Passing the easier half straight through gives **0.8571 on that half against the box's own 0.7853** (F51), and
the J-lens readout beats a plain next-token readout by 0.0897 and a random Jacobian by 0.0829 on the same target (F48).

**The second**: whether to spend a reasoning budget is settled by one number, and the number comes from measurement
rather than from an opinion. With cost per query written as `tokens + λ · (1 − accuracy)`, where λ is what one avoided
error is worth in tokens, the winning policy is **answer immediately below λ ≈ 1,850 and think below λ ≈ 9,253**
(F86). At a dollar per million output tokens that boundary is **$0.0019 per avoided error**. It is a property of the
model and the workload, so a different deployment re-measures it.

**The boundary the phrasing above correctly respects.** The readout says the cheap path *will be wrong*. It does not
say the expensive path *will be right* — those are different quantities and the second is the one escalation needs
(F67, F68). So "let the easy ones through" follows from the measurement and its converse, "send the hard ones up",
does not. Every failed entry below is some version of assuming it did.

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

## F55 — The deepest Jacobian is the worst gate, and the band is where J earns its keep

**Where it bit.** My own prediction, and it was wrong. Five quantities strengthen monotonically with depth —
linearity, split-half stability, diagonal mass, the variance-share ratio to the null, and the prediction margin —
so I expected `J_39` to make the best stage-1 gate. Same measurement as F51, same condition, same controls, one
layer deeper:

| at 50% passed | L32 | L39 |
|---|---|---|
| **J-lens** | **0.8571** | 0.7932 |
| logit lens | 0.7744 | **0.8271** |
| random J, matched norm | 0.8008 | 0.8120 |
| verdict | both PASS | **both FAIL** (−0.0338, −0.0188) |

**At L39 the J-lens is the worst of the three and the logit lens is the best.** The gate does not improve with
depth; it peaks inside the band and degrades outside it.

**The explanation is the one the architecture gives.** L39 is one block from the readout, so its residual is
already nearly the output — which is exactly why its Jacobian is linear to four decimal places (cos 0.9999) and
close to the identity. Applying `J` there has nothing to add, and reading the residual directly through `W_U` is
the right thing. **`J` earns its keep only where the residual is not yet the output.**

So the paper's band, depth 30–80%, is confirmed as the place the construction applies — and confirmed by my
prediction failing rather than by reproducing a number inside it. L32 sits at the deep end of the band and is the
best gate; L39 is outside it and the plain readout wins. This is the second thing this study can say about the
paper that the paper does not say itself, the first being F53's finding that the variance claim breaks just outside
the band.

**What it cost.** A wrong prediction, stated as wrong. Five monotone quantities do not license a sixth: they are
all properties of the ESTIMATE getting better with depth, and the gate depends on what there is to estimate, which
gets smaller. Extrapolating a trend across a change of subject is the same defect as the granularity errors this
ledger has recorded, in a new form.

**What would discharge it.** Nothing in the mechanism. For the research it fixes the operating point: stage 1 reads
L32, and the deeper layers are for verifying that the construction behaves as the architecture forces rather than
for deployment.

## F56 — A shape check catches half a cross-model judge's errors, and the silent half is the dangerous one

**Where it bit.** The interface work needs a compatibility contract that refuses a judge built for one model when
it is pointed at another. Before designing it, the cheap thing is to find out what happens WITHOUT one. Two real
models make the test sharp: `ornith-ai/Ornith-1.5-9B` is the same architecture family as the box (`qwen3_5`) and
shares its 248,320-token vocabulary exactly, and `google/gemma-4-12B-it` differs in every axis.

| | box: Qwen3.6-35B-A3B | Ornith-1.5-9B | gemma-4-12B-it |
|---|---|---|---|
| d_model | 2048 | **4096** | **3840** |
| depth | 40 | **32** | **48** |
| vocabulary | 248320 | **248320** | 262144 |
| tied embeddings | no | no | **yes** |
| dtype | **FP8** | bf16 | bf16 |

Enumerating every artefact the stage-1 judge carries and pointing it at each target:

| artefact | at Ornith | at gemma-4 |
|---|---|---|
| `J` applied to a residual | fails loudly | fails loudly |
| the layer index 32 | fails loudly, only 32 layers exist | **silently wrong**, exists but is 67% of depth not 80% |
| verbaliser token ids | **silently wrong** | loudly or silently |
| `W_U` | shape mismatch | **silently wrong**, tied so the readout is a different map |
| the fitted logistic on 4 features | **silently wrong** | **silently wrong** |
| the amplitude α | **silently wrong** | **silently wrong** |
| | 2 loud, **3 silent** | 2 loud, **4 silent** |

**A contract keyed on shapes lets the judge run and quietly produce a worse gate than no gate.** Two of the silent
failures are worth naming because I would not have predicted either:

- **Equal vocabulary size is not safety.** Ornith shares the box's family and its vocabulary size exactly, and
  that establishes nothing about whether token id 12345 means the same string. A **tokenizer hash** is required
  where I would have written "vocab_size".
- **Reduction destroys type safety.** The fitted head takes four scalars, so nothing checks their provenance —
  four numbers from any model's residual are accepted. The further a pipeline reduces, the less a type system can
  protect, which is the opposite of the intuition that narrow interfaces are safer.

**The minimum contract that makes every row above fail loudly**, derived from the enumeration rather than guessed:
a model identity hash, `d_model`, depth, a **tokenizer hash** rather than a vocabulary size, the tied-embedding
flag, and **the dtype the amplitude was calibrated against**.

**What it cost.** Nothing; it is arithmetic over three published configs. It replaces a guessed contract with one
derived from what actually fails, and it found two failure modes that a shape-based design would have shipped.

**What would discharge it.** The contract as the thing a judge's manifest carries, checked at admission. It is also
the same matching that lets a judge BIND to an already-standing shared box rather than provisioning its own —
requirement and provisioning are two readings of one comparison, so the contract does double duty.

**One prediction now testable.** The FP8 quantisation floor that dominated the amplitude sweep — cosine −0.0026 at
α = 0.001 with the response norm blowing up — should be a property of this box's weights rather than of the method.
Ornith is bf16 in the same family, so if the reading is right its linear window extends much further down. That run
is in flight.

## F57 — Two models agreed on every declarable field, and their representations were further apart than two different questions

**Where it bit.** F56 derived a compatibility contract by enumerating what breaks, and named a tokenizer hash as
the fix for the fact that equal vocabulary size proves nothing. Running it found the contract still too weak, and
found it in the direction that matters.

Two models loaded into one process: `ornith-ai/Ornith-1.5-9B` and `empero-ai/Qwen3.8-9B-Distill`. They agree on
`model_type`, `d_model` (4096), depth (32), `vocab_size` (248320), the tied-embedding flag, dtype (bf16), the
attention period, the weight file size — **and on `len(tokenizer)`, at 248077 exactly.** The only fields that
differ are the name and the weights themselves, whose first-layer statistics differ in the fifth decimal
(mean 5e-06 against 6e-06, std 0.015346 against 0.015420). So a statistical fingerprint is fragile too.

**The number that decides it.** Residuals at the same layer index, same prompts:

| comparison | cosine |
|---|---|
| **same prompt, different model** | **0.5995, 0.6102, 0.5711, 0.5625** |
| different prompt, same model | 0.8983, 0.8995, 0.8750 |

**The between-model distance exceeds the between-question distance.** A judge carried across would read in a space
further from where it was fitted than two unrelated questions are from each other. And the residual rms is 0.4511
against 0.4694 — a ratio of 1.04 — so **no scale or sanity check on magnitudes would catch it.** The distill likely
shares lineage with its sibling, which makes 0.57 an upper bound on similarity and the conclusion conservative.

**What co-hosting does NOT break.** The two models' blocks are distinct Python objects and a hook registered on one
fires zero times during a forward through the other (1 against 0). **Hooks belong to the module tree, not to the
engine.** One engine holding several models does not mix observations, so the entity that owns a hook is the model
instance — which is what the four-level entity model needs in order to say who a resident `J` belongs to.

**Two other measured facts from the same pair.** Ornith is **dense**: `found 0 MoE gate modules`, so the input-side
router clamp that was indispensable on the box has nothing to clamp. A judge declaring "requires a clampable router"
is declaring a property some models in the same family do not have. And the amplitude at which the Jacobian is
linear is **not portable**: on Ornith the cosine peaks at α = 0.05 (0.9913) and has already fallen to 0.9084 by
α = 0.5, which is the box's operating point and where the box is at its best (0.9965 at L32). F56 argued the
amplitude was a silent-failure row; this measures it.

**A withdrawal.** F56 predicted the small-amplitude floor was a property of the box's FP8 weights and would not
appear in bf16. It does: α = 0.001 gives cosine −0.0531 on Ornith against −0.0026 on the box, and two identical
patched passes differ by 0.000e+00, so it is deterministic rounding of a small perturbation rather than run-to-run
noise. The floor is a small-signal property of the arithmetic, not of the quantisation format.

**What would discharge it.** The contract keys on a **weight digest**, not on shapes, not on vocabulary size, not on
`len(tokenizer)`, and not on weight statistics. Everything weaker than a digest is satisfied by two models whose
representations are further apart than two different questions.

## F58 — Some of a judge's constants cannot be declared, only measured, and the manifest has to say which

**Where it bit.** F56 and F57 built toward a compatibility contract of declared fields, checked at admission. If
every constant a judge carries were derivable from a declaration, that contract would close. This tests one
constant that looked derivable and finds it is not.

The amplitude α at which the forward-difference Jacobian stays linear, swept at the same depth fraction:

| α | box, Qwen3.6-35B-A3B FP8, L32 = 80% | Ornith-1.5-9B bf16, L18 = 56% | Qwen3.8-9B-Distill bf16, L18 = 56% |
|---|---|---|---|
| 0.001 | −0.0026 | −0.0531 | 0.0557 |
| 0.005 | — | 0.6398 | 0.7253 |
| 0.02 | — | 0.9351 | 0.9741 |
| **0.05** | — | **0.9913 (peak)** | 0.9950 |
| **0.2** | — | 0.9848 | **0.9986 (peak)** |
| 0.5 | **0.9965 (peak)** | 0.9084 | 0.9850 |

**The last two columns hold structure, dtype and depth fraction identical** — both are `qwen3_5`, d_model 4096,
32 layers, bf16, read at 18/32 — and the peak still differs by a factor of four. So α is a property of the
**weights**, not of the architecture, and no declaration can derive it.

**What this does to the contract.** F56 and F57 converged on "admission is a comparison of declared fields against
a resident implementation." That is necessary and **not sufficient**: a judge also carries constants that were
*measured* on the model it was built for, and a measured constant has no derivation to check. The manifest therefore
needs two kinds of entry, and the distinction is not cosmetic:

| kind | example | how admission checks it | what a mismatch costs |
|---|---|---|---|
| **declared** | d_model, depth, tokenizer digest, tied flag | compare to the resident model | refusal, loudly |
| **measured** | the linear amplitude, the calibrated layer, the fitted head's scaling | **cannot be compared** — only re-measured | silent degradation |

**The consequence for the marketplace.** A seller shipping a judge for model X ships measured constants that are
valid for X's weights. The buyer's admission check can confirm the weights are X's, and that is exactly what makes
the measured constants trustworthy — **the weight digest is what licenses the measured half of the manifest.** With
a weaker key (shapes, vocabulary size, `len(tokenizer)`, all of which F57 showed two different models share) the
declared half passes and the measured half is quietly wrong, which is the worst combination: it looks admitted.

**The corollary for building a judge for a new model.** It is not a port. Every measured constant has to be
re-established on the new weights, so "this judge supports models of shape S" is not a claim anyone can make. The
unit a seller can honestly sell is **a judge for a specific weight digest**, and supporting a second model is a
second measurement campaign, not a configuration change.

**What would discharge it.** The manifest carries `measured_on: <weight digest>` beside every measured constant, and
admission refuses when the digest does not match rather than assuming a shape match licenses the constant.

## F59 — The two failures that appeared only on running it, and neither is in any contract

**Where it bit.** F56, F57 and F58 derived a compatibility contract from configuration files and from residual
geometry. Actually running the J construction on a second and third model produced two failures that no field in
that contract mentions, and they have opposite characters.

**One fails loudly, in code that had worked for weeks.** The construction adds `epsilon * v` to the residual leaving
a block. On the FP8 box the activations arrive dequantised to float32 and a float32 perturbation adds cleanly; on a
bf16 model the residual is bf16 and the next matmul refuses the mixed pair — `expected mat1 and mat2 to have the
same dtype, but got: float != c10::BFloat16`. The method is unaffected; the *implementation* carried an assumption
about the box's numeric representation that nothing declared and no reviewer had reason to look for.

**One fails quietly enough to have produced a published number.** The letter is read from the next token at the last
prompt position, which is correct for a model that complies with "answer with the option letter only". On
`empero-ai/Qwen3.8-9B-Distill` — matching its sibling on `model_type`, `d_model`, depth, vocabulary,
`len(tokenizer)`, tied flag, dtype and attention period — it gave **accuracy 0.0899 against a 0.10 random floor.**
The labels were noise. A gate comparison run on them would have compared two orderings of noise and reported a
number, and nothing in the compatibility contract of F56–F58 has a field that would have refused it: the model is
the right shape, the right dtype, the right tokenizer length, and the weight digest would have matched the model
the judge was being built FOR.

**What this adds to the contract.** A third category beside declared and measured (F58): **conventions**. The
readout convention is not a field of the model and not a constant measured on its weights — it is an assumption
about how the model behaves under an instruction, and it transfers no better than the Jacobian does. A manifest
cannot check it and a digest cannot license it. What catches it is a **base-rate floor measured on the buyer's own
items before the judge's output is used at all**, which is a measurement the runtime must perform, not a declaration
the seller can make.

That floor is now pre-registered in the harness at 0.20 for a ten-option task, and the run refuses rather than
reporting. It is the same shape as the sanity gate that caught the 1,822-of-2,364 collapse earlier, which is the
second time the same class of defect has been caught by measuring the base rate and no other way.

**What would discharge it.** The measurement block computes a base rate per candidate before any judge is consulted,
and a judge's output is inadmissible until the base rate is above a declared floor. This is a **block tierbook owns**,
not a manifest field, which is the useful conclusion: some of what makes a bought judge safe cannot be sold with it.

## F60 — A judge carried to the wrong model still beat no judge, and that withdraws F57's conclusion

**Where it bit.** F57 measured that two models agreeing on every declarable field have residuals whose cosine for
the same prompt (0.56–0.61) is *lower* than two different prompts within one model (0.88–0.90), and concluded that a
judge carried across would be reading in the wrong space, so the contract must key on a weight digest. That is an
argument from geometry to behaviour, and the behaviour was not measured. It is now.

Both models in one process, same 712 items, `J` built on each at L18 with α = 0.2 and 256 directions, the four
J-lens features computed on **B's** residuals under each `J`, and the logistic head fitted on **B's** outcomes in both
arms. Held-out half, gate at 50% pass:

| gate | AUC | accuracy on the passed half |
|---|---|---|
| **native** — `J` built on B, gating B | 0.6206 | **0.7529** |
| **foreign** — `J` built on A, gating B | 0.5740 | **0.7176** |
| none — every item passes | — | 0.6667 |

**native − foreign = +0.0353, 95% CI [−0.0294, +0.0824] → FAIL** against the pre-registered floor of 0.03 with the
interval above zero.

**The foreign judge still works.** It adds **+0.0509** over no gate. The point estimate favours the native judge and
meets the magnitude floor, but at n = 356 held-out items the interval crosses zero, so the claim that a carried judge
is worse cannot be made. The geometry is confirmed — the flattened `J_A`·`J_B` cosine is **0.5744**, matching the
residual cosine — and it does not reach the behaviour.

**Why it survives, and it is the same fact as an earlier finding.** The foreign arm carries A's Jacobian and **B's
refitted head**. F56 observed that the fitted head takes four scalars, so nothing checks their provenance, and called
that a hole in type safety. It is the same property that absorbs the mismatch here: four numbers is a narrow enough
channel that refitting downstream recovers most of what the wrong Jacobian cost. **The reduction that destroys type
safety is what makes the mismatch survivable** — one fact, two consequences, and I had written up only the one that
sounded like a warning.

**What this does to the design.** Refusing loudly on a digest mismatch is now the *strict* option rather than the
obviously correct one, and the evidence does not support it as the only admission rule. A second rule is defensible
and better matched to what was measured: **admit with the mismatch declared, and require re-measurement of the base
rate and the gate's own increment on the buyer's items before the judge's output is trusted.** F59 already argues the
runtime must measure a base rate that no manifest can declare; this extends it — the runtime must also measure the
*increment*, because that is the quantity a digest mismatch actually moves, and it moves it by an amount too small
for a declaration to predict.

**What I got wrong, plainly.** F57's headline sentence — that a judge carried across reads in a space further away
than two unrelated questions, therefore the contract must key on a weight digest — used a true measurement to reach
a conclusion about behaviour that the behaviour does not support. The digest is still the right key for the *measured*
constants of F58, where a mismatch has no downstream refit to absorb it. It is not established as a ground for refusal
of the judge as a whole.

## F61 — The intervention passes: moving the J-lens coordinates moves what the model would say, 4.7x more than moving the rest

**Where it bit.** Every round until now READ the workspace. The paper's own strongest evidence is causal — exchanging
a concept's J-space coordinates changed the output 88% of the time for a pure swap, 59% for the J-component alone,
5% for the rest of the variance — and it had never been run here. What was run earlier was an ADDITION of one fitted
direction, at ONE position, in ONE layer, with the router free, which is a different operation whose negative result
says nothing about this one.

The operation as defined: `V = [v_s v_t]` two rows of `W_U J`, `c = V⁺h`, `h ← h + V(σ(c) − c)` with σ swapping the
coordinates, applied at **every token position**, at L22 and L32 (both inside the paper's 30–80% band, both passing
the linearity criterion), with the router clamped on its **input** — 40 gates recorded on an unperturbed pass and
substituted on the perturbed one, so routing is held and the measured change is the swap alone.

| arm | change in the KNOWN−UNKNOWN gap | answer changed |
|---|---|---|
| **real** — the KNOWN/UNKNOWN pair | **1.1988** | 0.0471 |
| `rand_vocab` — two random vocabulary rows of the same `W_U J` | 0.6844 | 0.0388 |
| `rand_plane` — a covariance-matched random 2-plane | 0.2332 | 0.0471 |
| `nonJ` — the same two vectors with their J-component removed | **0.2550** | 0.0388 |

**real − strongest control = +0.5144 nats, 95% CI [+0.4430, +0.5849] → PASS** against the pre-registered floor of
0.30 with the interval above zero.

**real : nonJ is 4.7 : 1**, which is the paper's qualitative structure. F48 showed the J-lens readout PREDICTS
difficulty better than the logit lens; this is the causal complement — moving those coordinates moves what the model
would say about its own answerability, and moving the part of the same vectors that lies outside J's column space
barely does.

**Three limitations, none of which the headline should hide.**

- **`rand_vocab` reaches 0.6844, more than half of real.** A random vocabulary pair is far above a random plane
  (0.6844 against 0.2332), so **being a vocabulary direction of `W_U J` carries as much of the effect as being the
  right one.** The concept pair wins significantly, and most of the effect is the general property.
- **The answer changes 4% of the time in every arm, not 88%.** The swap was applied at two layers, not across the
  whole 20-layer band, so this is a much weaker operation than the paper's. For a routing gate that is the *desirable*
  direction — the readout moves while the answer does not, and the answer is the thing being gated — but it means the
  paper's headline number is not reproduced and this run does not claim it.
- **`J` here has effective rank 448**, equal to the number of probe directions, so it is a rank-limited estimate of the
  paper's expectation. The "non-J component" is therefore confounded with "the part of the space that was never
  probed", and the 4.7 ratio is an upper bound on the true contrast. Notably the non-J share falls from 0.813 at L22
  to 0.667 at L32, so the deeper Jacobian captures more of the verbaliser direction — consistent with the earlier
  finding that linearity and predictive quality both improve with depth inside the band.

**What it settles for routing.** The J-lens coordinates are not an epiphenomenon of the readout: they are causally
upstream of the verbaliser, by a margin that survives three controls chosen to kill it. Combined with F48 (predicts)
and F50–F53 (gates in the deployment condition), the mechanism is established well enough that the remaining
questions are about magnitude and cost, not about whether the quantity is real.

## F62 — An intervention moves the readout but adds no information, and the difficulty signal is not in the verbaliser plane

**Where it bit.** F61 established the swap works: exchanging two J-lens coordinates moves the KNOWN−UNKNOWN gap 4.7x
more than moving the same vectors' non-J part. That is a fact about the mechanism, and it does not answer the question
routing needs — **can an intervention make the readout MORE informative about whether the item is hard?** A swap moves
the readout by construction; a gate needs the *ordering over items* to sharpen. An intervention that moves every item
by the same amount improves nothing.

So a gain rather than a swap: `h ← h + (g−1)·V(V⁺h)` at every position, at L22 and L32, router clamped, same
machinery. The gain was chosen on the calibration fold and scored on the test fold, because choosing on the scoring
fold is the failure this project has recorded twice.

| basis | gain | calib AUC | **test AUC** | accuracy at 50% passed |
|---|---|---|---|---|
| lens | 0.0 — the coordinate removed entirely | **0.7767 (best on calib)** | **0.7938** | 0.8214 |
| lens | 0.5 | 0.7626 | 0.8128 | 0.8214 |
| **lens** | **1.0 — untouched** | 0.7664 | **0.8054** | 0.8304 |
| lens | 2.0 | 0.7515 | 0.8243 | 0.8482 |
| lens | 4.0 | 0.7193 | 0.8098 | 0.8571 |
| lens | 8.0 | 0.6024 | 0.7203 | 0.7679 |
| rand | 0.0 | 0.7557 | **0.8227** | 0.8214 |
| rand | 2.0 | 0.7700 | **0.8220** | 0.8393 |

**FAIL** against the pre-registered floor. Calibration chose g = 0.0, which is 0.0116 AUC *worse* than untouched on
test. The gains that look good on test (2.0, 4.0) are matched by the covariance-matched random plane at 0.8220 and
0.8227, so what improves there is perturbation magnitude, not the lens coordinate.

**What this settles, and it is a real answer rather than a null.** The question was whether an external intervention
can CREATE the routing signal in J-space. It can move the readout — F61 measured that at 4.7x over the non-J control
— and moving it adds no information about difficulty. **The information was already there; perturbing does not add
any.** For a gate, that means the design space is reading, not steering, and the effort belongs in what to read and
when rather than in how to intervene.

**A second finding from the g = 0.0 row.** Removing the KNOWN/UNKNOWN 2-plane from the residual *entirely* costs only
0.0116 AUC (0.8054 → 0.7938). **The difficulty signal is not concentrated in the verbaliser plane.** That is not in
tension with the earlier result that the verbaliser log-odds is the feature which made the J-lens readout beat the
logit lens (0.7629 against 0.5011): the readout runs the residual through the whole of `J` and the whole of `W_U`, so
the verbaliser *log-odds* can carry the signal while the two-dimensional span of two `W_U J` rows does not. Reading a
wide readout and steering a narrow plane are not inverse operations, and this run is the measurement that separates
them.

**What would discharge it.** Nothing further on interventions for the gate. The remaining questions on the mechanism
are about where and when to read, which the deployment-condition results already address, and the intervention line is
closed with a negative that has a control behind it.

## F63 — The industry already externalises the routing decision, and it does so upstream of the observation we need

**Where it bit.** Every design round so far assumed tierbook would define its own interface for externalising a
routing decision. It does not need to: Envoy's External Processing filter plus the Gateway API Inference Extension
(GIE) already standardise exactly that, `llm-d` implements it, and vLLM's semantic-router uses the same mechanism.
Reading the implementation rather than the marketing settles what is available and what is not.

**The decision's actual input and output**, from `kubernetes-sigs/gateway-api-inference-extension`:

```go
type Request struct { RequestId, TargetModel, Prompt string; Headers map[string]string }
type Endpoint struct { State EndpointState }        // per-endpoint, per scheduling cycle
type Filter interface { Filter(ctx, *Request, *CycleState, []*Endpoint) []*Endpoint }
type Scorer interface { Score(ctx, *Request, *CycleState, []*Endpoint) []*ScoredEndpoint }  // [0,1]; weights in config
type Picker interface { Pick(ctx, *CycleState, []*ScoredEndpoint) []*ScoredEndpoint }
type PickResult struct { Endpoint string; Fallbacks []string; MutatedBody []byte; ExtraHeaders map[string]string }
```

Called at the `RequestHeaders` / `RequestBody` phases. Existing scorers — queue depth, KV-cache utilisation,
prefix-cache hit, adapter affinity — all read **per-endpoint** state.

**The mismatch that decides the architecture.** The EndpointPicker runs **before any engine has processed the
request**, so the layer-32 residual the stage-1 gate reads does not exist at decision time. What the existing scorers
consume is per-endpoint state; what the gate needs is **per-request internal state that comes into existence only
after that request has begun running on an endpoint.** No amount of interface design removes this: it is a
consequence of where the decision point sits.

**The resolution, chosen from four candidates on latency, cost, feasibility and standards fit:**

| approach | latency | cost | feasibility | fit |
|---|---|---|---|---|
| two requests, prefill-only then resubmit | poor, three serial hops | poor, prefill twice on a cache miss | low–medium | shape only; abuses inference as a probe API |
| decide inside the engine, engine picks the endpoint | good | minimal | medium | **bypasses the standard** |
| **speculative dispatch** | **good on the common path** | pays cheap prefill, saves cheap decode on escalation | medium–high | **the standard picks endpoints; only the internal judgement is in the engine** |
| redefine the gate to use gateway-visible data only | best | minimal | high | most standard, but discards the measured gate |

**Speculative dispatch wins, and the reason it fits is that the engine returns an action rather than a
destination** — `ContinueLocal` / `Escalate(target_profile, reason, receipt)` / `Abort`. Endpoint selection after an
escalation goes back to the standard picker, so nothing is bypassed. On the common path `ContinueLocal` means the
prefill flows straight into decode and **the routing decision costs nothing**, which is the property that made this
design worth measuring in the first place.

Two consequences worth recording because they are not obvious:

- **Prefix caching is an optimisation, not a contract.** The two-request scheme depends on the resubmission landing
  on the same endpoint with the cache still warm, and on `max_tokens=0` meaning the same thing across servers. It
  also puts an internal residual in an HTTP header. None of these is a guarantee, so the scheme cannot be the base
  design even though it is contractually equivalent on paper.
- **Stage 2 has a commit problem the measurement did not surface.** Generation length is the stage-2 signal
  (F52: 0.6978, beating the J-lens which loses to its own random control at −0.0165), and length is only known while
  decoding — by which point output may already be streaming to the client and cannot be replaced. So the policy must
  declare **buffered commit** (hold the cheap response until the final decision) or **early commit** (stage 2 becomes
  audit and next-round calibration, not substitution). This is a declaration the buyer makes, not a property of the
  detector.

**What tierbook must not build.** Named explicitly by an adversarial round: endpoint discovery and readiness, pod
enumeration, queue / KV-utilisation / prefix-cache / adapter-affinity scoring, scorer composition, pod fallback,
destination-header manipulation, Envoy body wiring, profile management, per-endpoint metrics collection.
**Re-implementing these produces compatibility debt rather than value.** The four blocks resolve to: serving wiring
**mostly deleted**, flow executor **split**, outcome ledger **kept**, and measurement **the core** — buyer-data base
rates, the utility curve, convention checks, detector drift.

**The closed loop, without forking upstream.** The plugin surface has no `PostResponse`, and the fix is not to add
one: **a response callback must never mutate a running scorer**, because then results depend on execution order and
reproducibility and auditability are lost. Instead an asynchronous outcome plane — the picker leaves
`request_id` / endpoint / profile version in metadata, the engine emits `decision_id` and per-stage outcomes as
telemetry events, the access log supplies status and latency, a collector joins on the ids, the ledger appends, and a
calibration job produces an **immutable snapshot** that the next policy version reads. Within one request, stage 1 to
escalation is the engine's business; only cross-request learning returns to the ledger. The upstream proposal that
follows is a **telemetry SPI rather than a scheduler plugin**: an observer that cannot change endpoint selection, is
non-blocking, takes the body only on explicit opt-in, carries versions, and declares a drop policy under
backpressure.

**The condition under which tierbook has no reason to exist**, stated so it can be checked rather than assumed: the
decision completes on prompt, headers and endpoint state alone; candidate models are fixed in advance by traffic
split; no internal observation, extra API call or extra inference is used; there is no admission or provenance
requirement for a third-party detector; and outcome feedback feeds only ordinary scheduler tuning. Everything this
project has measured lives outside that set, which is the honest form of the claim.

## F64 — The engine-side gate runs on a real server, and four of its five obstacles were invisible from the design

**Where it bit.** F63 chose speculative dispatch, which makes one assumption load-bearing: **a running vLLM can, per
request, expose the residual at a chosen layer at prefill time and act on it before decode, through supported
extension points and without a fork.** Designing on top of an unverified assumption of that size is how a phase-5
failure invalidates the work built on it, so this was checked on real hardware with a real server and real HTTP
requests before anything else was built.

**It works.** A `vllm.general_plugins` entry wraps the model runner's `load_model` to install a forward hook, and a
class loaded through `--logits-processors` reads what the hook captured on a request's first step. Real requests
through the OpenAI-compatible endpoint produced, per request, a residual of shape `[37, 4096]` at layer 18 against a
logits tensor of 1 row.

**Four of the five obstacles were not visible from the design, and each cost a run.**

| what failed | what it means |
|---|---|
| `--disable-log-requests` was removed in this version | trivial, but a design that names flags is dated the day it is written |
| the runner's `self.model` is a `CUDAGraphWrapper` | `self.model` is not the model. It forwards attribute access, so a walk following `.model` lands back on the wrapper |
| after unwrapping, the model exposes no `.layers` at all | guessing attribute paths does not converge across families; the fix is to find the decoder stack **by structure** (the longest `ModuleList`), which landed on `language_model.model.layers`, 32 blocks |
| a wall-clock read inside the hook raised | the hook body runs inside traced user code |
| **`torch.compiler.disable` on the capture also raised** | **the model is compiled as a full graph, so a graph break is a hard failure at engine start rather than a slowdown** |

**The fifth is the one that constrains the design.** A side-effecting forward hook and a fully compiled model are
incompatible, and no care inside the hook changes that. The run that produced the measurement therefore has
compilation disabled. That is the right shape for establishing what the gate can see, and it names the production
requirement exactly: either the capture becomes a **traceable write into a preallocated buffer**, or the engine offers
an observation point of its own. The second is the upstream ask that F63 anticipated, and it is now backed by a
failure rather than a preference.

**The row correspondence, derived from data rather than assumed.** This is the part that would have failed silently.

| batch | residual rows | logits rows | rows at first step | sum of prompt lengths |
|---|---|---|---|---|
| 1 | **37** | 1 | 1 | **37** |
| 6 | **163** | 6 | 5 | **162** |

`163 = 162 + 1`: the residual's rows are the step's **scheduled tokens** — five prefills totalling 162 tokens plus one
decode token belonging to a sixth request already past its first step. **Prefill and decode share a step.** So a
request's last prompt position sits at the cumulative sum of the preceding requests' scheduled token counts, minus
one — **not at its batch index, and not derivable from its prompt length**, because a long prompt is split across
steps by chunked prefill and the two stop agreeing.

**A concrete gap follows.** `BatchUpdate` carries prompt token ids but **not the per-step scheduled token count**, so
the quantity needed to locate the row is not in what the extension point provides. Short prompts make the two agree
by coincidence, which is the worst case: it works in a demo and misattributes every decision once prompts get long.
Either the count comes from the model runner by another route, or it is the second thing to ask upstream for.

**One measurement-hygiene defect worth recording.** The gate's log is opened in append mode on a persistent volume,
so a first read of it mixed two runs and showed 5 initialisation records with the hook absent alongside 8 with it
present. Nothing was concluded from the mixture, but a run-scoped file would have made the mistake impossible rather
than merely visible.

**What would discharge it.** The row selection implemented against scheduled-token counts rather than prompt lengths,
verified with a prompt long enough to be chunked; the four readout features computed on the worker; escalation
expressed as an immediate end-of-sequence; and the throughput cost measured against the same server with the gate
absent. The compiled-mode question is separate and is an upstream conversation, not a workaround.

## F65 — Speculative dispatch works on a real server, and the row-mapping failure it was built to avoid reproduced on cue

**Where it bit.** F63 chose speculative dispatch and F64 established the engine-side observation is reachable. What
remained was whether the whole path runs: locate the right residual row, compute the readout, express an escalation,
and cost something bounded. All four are now measured on a real vLLM server driven over HTTP.

**The readout runs with the real Jacobian.** `norm=yes lm_head=yes J=yes`, verbaliser sets resolved to 9 and 8
single-token forms, and the four features computed on 48 of 82 first-step records. The verbaliser log-odds spread
across requests — min −0.070, median 0.845, max 1.223 — so the gate is reading something that varies rather than a
constant.

**Two engine guards had to be respected rather than worked around.** The unembedding cannot be called: it raises
`RuntimeError: LMHead's weights should be used in the sampler`, because the engine wires the head through its own
sampling path. So the readout uses `lm_head.weight` as a weight and applies the normalisation as arithmetic — the
engine's RMSNorm takes an optional residual and returns a tuple when given one, so calling it as a module is the same
class of mistake. Both are deliberate guards, and a plugin that patched around them would be lying about what it is.

**The row-mapping failure reproduced exactly as predicted, which is the result worth having.** F64 argued that
locating a request's last prompt position by cumulative prompt length works while prompts are short and misattributes
decisions once chunked prefill splits them. Both methods were computed on every step and compared:

| requests in flight | steps with a scheduled-token row map | the two methods agree |
|---|---|---|
| light | 9 of 43 | **7 of 9** |
| under load | 48 of 82 | **15 of 48** |

The disagreement, printed verbatim from the run: `sched=[2048]`, `from_len={'0': 2205}`, `map={'0': 2047}`. The
prompt-length method points at **row 2205 of a 2048-row residual** — a row that does not exist. And agreement falls
from 7/9 to 15/48 as load rises, because decode rows share a step with prefill rows. **The convenient method is right
only in the simplest case**, which is the shape of failure that ships.

**Escalation works through an immediate end-of-sequence.** With the threshold at 0.85, **27 of 48 requests escalated**
— the request stops before producing a token and the caller re-issues to the upper tier. The engine never names the
upper endpoint, so the standard's division of labour is untouched.

**The first throughput comparison was invalid and I caught it before reporting it.**

| arm | req/s | completion tokens | tok/s |
|---|---|---|---|
| gate off | 4.666 | **1536** | **149.3** |
| **gate on, threshold unreachable** | 4.590 | **1536** | **146.9** |
| gate on, threshold 0.85 | **6.134** | 916 | 117.1 |

The third arm looks like a 31% throughput *gain*, and it is nothing of the kind: 27 requests ended instantly, so the
server did less decode. **Requests per second is not comparable between arms that do different amounts of work.** The
valid comparison needed a third condition — the gate running and never escalating — so that both arms produce
identically 1536 tokens and the only difference is the gate's own compute. That gives **149.3 against 146.9 tok/s, a
1.6% difference.**

**And 1.6% is not a bound.** Each arm is a single run with no repetition, so there is no interval, and a 1.6%
difference on one run of 48 requests is well inside what run-to-run variation can produce. The honest statement is
that **no cost is measurable at this resolution**, and that bounding it needs repeats — which is a cheap experiment
and the right next one, not something to assert past.

**Two remaining constraints, both named rather than worked around.** The run has compilation disabled, because a
side-effecting forward hook and a fully compiled model are incompatible (F64); the production form needs either a
traceable write into a preallocated buffer or an engine-provided observation point. And the per-step scheduled-token
counts had to be taken by wrapping `execute_model` — read on entry they are empty, because the input batch's row
order is populated inside the call, and an empty order produces a **silently absent** row map rather than a wrong one,
which is why the first attempt reported zero maps with no error at all.

**What would discharge it.** Repeats to bound the gate's cost; the threshold chosen on a calibration fold rather than
set by hand; and the escalation's other half — the caller re-issuing, with the child-request fields that stop loops
and double billing — measured end to end against a second tier.

## F66 — Both halves of speculative dispatch run end to end, and the engine has no channel for returning an action

**Where it bit.** F65 measured the engine's half: the gate reads the residual after prefill and stops the request. The
caller's half was untested, and it is where the accidents live — a re-issue that loops, one billed twice, one that
re-runs the stage it just left. This runs both halves against **two real servers on two devices**, so an escalation is
a network hop whose cost is measured rather than a function call that would hide it.

| | |
|---|---|
| cheap tier | `ornith-ai/Ornith-1.5-9B`, device 0, gate loaded, threshold 0.85 |
| upper tier | `empero-ai/Qwen3.8-9B-Distill`, device 1, no gate |
| requests | 32 over 4 rounds |
| **escalated to the upper tier** | **12 (37.5%), every one detected by the explicit signal** |
| refused by the hop bound | 0 |
| median latency | cheap 1722.6 ms, upper 1723.1 ms |
| **a full escalation** | **3445.7 ms at the median — cheap plus upper, paid in full** |
| duplicate idempotency keys across different requests | **0** |

The child request carries `parent_request_id`, `decision_id`, `policy_version`, `target_profile`, `hop_count` and
`idempotency_key`, and `target_profile` is the **caller's** choice: the engine said only that it should not answer,
never where the work should go. The hop bound and the key collision check are verified rather than asserted — the keys
were checked for collisions across distinct requests and there are none, so a retry cannot be counted as a second
escalation.

**The finding that changes the upstream ask.** A logits processor cannot set a response header, so **the engine has no
channel for returning an action** and the action has to be encoded in what the model emits. The first attempt used a
single rare token as the signal — and none of four candidate rare strings encoded to a single token in this
248,320-entry vocabulary, so it fell back to an end-of-sequence and the caller read the escalation from an empty
completion. That reading is **ambiguous**: a zero-token completion with a normal stop reason is indistinguishable from
a request the model genuinely answered with nothing. The run reported `by signal: {'empty-stop (ambiguous)': 12}` and
the number was right for the wrong reason.

The fix removes the vocabulary dependency rather than working around it: a fixed string spread across successive steps,
one token per step, then a stop. `TIERBOOK_ESCALATE` becomes `[51, 15810, 35413, 29287, 47868, 2260]` and the rerun
reported `by signal: {'sentinel': 12}` with zero ambiguous detections. **So an unambiguous out-of-band signal is
achievable but it is a workaround**: it spends six decode steps to say one bit, and it depends on the caller agreeing
on a magic string. The clean form is an action in the response metadata, which is the second concrete thing to ask
upstream for, alongside the outcome observer of F63 and the per-step scheduled-token counts of F65.

**What the latency says about the economics, stated as a bound rather than a conclusion.** An escalation costs the
cheap tier's full latency on top of the upper tier's, because the cheap prefill and the cheap tier's own decode of the
sentinel are both paid before the upper tier starts. At these medians that is 3445.7 ms against 1723.1 ms for going
straight to the upper tier — **a 2.0x latency penalty on every escalated request.** The design's claim was never that
escalation is free; it was that **the common path is free**, and that holds: a request the gate passes flows from
prefill into decode with no extra hop. Whether the arithmetic closes depends on the pass rate and on the tiers' price
difference, and this run measures neither — the two models here are the same size, chosen to make the plumbing
observable rather than to represent a real price gap.

**What would discharge it.** Repeats to bound the gate's compute cost (F65 leaves it unmeasurable at n=1); the
threshold chosen on a calibration fold rather than by hand; and a genuine price gap between the tiers so the
escalation's latency penalty can be weighed against what it saves.

## F67 — On real serving hardware the gate does not beat random escalation, and the reason is already in this ledger

**Where it bit.** F65 and F66 established that speculative dispatch runs: the gate reads the residual, stops the
request, the caller re-issues, nothing loops or double-bills. None of that asks whether escalating the items the gate
picks is better than escalating the same number at random. This does, on both real servers, over 239 labelled items
with both tiers answering every one.

**Two evaluation errors of mine, in order, before the result.**

The readout convention failed for the third time in this project. A chat request with a terse instruction and a short
budget returned **no letter at all on 239 of 239 items** — the model writes prose regardless and the budget cuts it
before a letter appears — so both tiers scored 0.0000 and the script went on to report a threshold and a criterion
anyway. **The base-rate floor that catches exactly this was written into F59 and I did not apply it here.** It is now
in the harness, the raw completion text is stored so the next failure is diagnosable, and the convention is an
explicit `Answer:` cue rather than a scan of prose.

Then the threshold selection degenerated. Choosing it to maximise accuracy picked a threshold that escalates
**100%**, because the upper tier is better and with no cost term "escalate everything" is optimal — at which point the
random control becomes the same policy and the comparison has no content. The question with content is
coverage-constrained: at a fixed rate, does the gate pick better items than chance?

**The result, at fixed escalation rates, threshold chosen on calibration and scored on test:**

| escalation rate | gate | **oracle at the same rate** | random mean | random 97.5th | gate verdict |
|---|---|---|---|---|---|
| 9.7% | 0.5172 | **0.5724** | 0.5184 | 0.5310 | FAIL |
| 20.0% | 0.5103 | **0.5724** | 0.5198 | 0.5379 | FAIL |
| 30.3% | 0.5034 | **0.5724** | 0.5209 | 0.5448 | FAIL |
| 40.0% | 0.5103 | **0.5724** | 0.5229 | 0.5448 | FAIL |
| 49.7% | 0.5241 | **0.5724** | 0.5243 | 0.5517 | FAIL |

**FAIL at every rate.** And the oracle column is what makes the negative readable: a perfect selector passes at every
rate, so **the setup had the power to detect a good selector and the gate is not one.** This is a statement about the
signal, not about the sample size.

**The explanation is already in this ledger, and that is the point.** F39 recorded that the residual reads difficulty
rather than uplift, and F42 that on box-wrong items the residual sits at the null. The gate predicts *whether the cheap
tier will be wrong* — F48 and F51 measured that and it holds. Escalation needs a different quantity: *whether the upper
tier will be right where the cheap tier is wrong.* On this pair that class is **8 of 145 test items**, and picking
difficulty does not find them.

**What the setup could and could not have shown.** Cheap 0.5169, upper 0.5424, oracle over the two 0.5805 — so the most
any router can add over cheap-only is **6.36 points** while the upper tier *breaks* 9 items for the 15 it fixes. The
two models are the same size, chosen in F66 to make the plumbing observable rather than to represent a capability gap.
A wider pair would raise the ceiling; it would not change what the readout is reading.

**What this does and does not withdraw.** It does not touch F48 (the J-lens readout predicts difficulty better than a
logit lens and a random Jacobian), F61 (the coordinates are causally upstream of the verbaliser), or F65–F66 (the
mechanism runs, the escalation channel works, the common path costs nothing extra). It does withdraw any reading of the
cascade as an accuracy play routed on difficulty: **on this pair, at every rate, choosing by difficulty is
indistinguishable from choosing at random.** The cascade's remaining case is economic rather than accuracy-driven — a
cheap tier that is much cheaper and a threshold set to spend the upper tier only where the cheap one is likely wrong —
and that case needs a real price gap and an uplift signal, neither of which this run has.

**What would discharge it.** A tier pair with a genuine capability gap, so the fixable class is large enough to route
on; and a signal fitted to **uplift** rather than to difficulty, which F40 already bounds at a 0.9291 ceiling with 78%
of it unpredicted. Until one of those changes, the honest position is that the mechanism works and the quantity it
reads is the wrong one for choosing when to escalate.

## F68 — Uplift is predictable and the Jacobian is not the reason: the plain logit lens wins at every rate

**Where it bit.** F67 failed to beat random escalation and named the reason — the readout reads difficulty, escalation
needs uplift — but could not separate the two, because its tier pair left 8 fixable items in the test fold. A free pair
with 15 times the signal was already in hand: the same box answering the same 888 questions **terse** (0.6171) and
**explaining** (0.7928). The explaining path **fixes 195 items and breaks 39**, so the oracle is 0.8367 and the test
fold holds **123 fixable items**. The observation is the terse prefill's residual, which is what a router actually has
before it chooses.

Threshold chosen on calibration, scored on test, at fixed escalation rates, against random selection of the same
number of items:

| rate | **J-lens** | **logit lens** | random J | free (length + letter) | random 97.5th | oracle |
|---|---|---|---|---|---|---|
| ~10% | 0.6252 **FAIL** | **0.6497 PASS** | 0.6384 PASS | 0.6271 FAIL | 0.6309 | 0.6987 |
| ~20% | 0.6497 **FAIL** | **0.6930 PASS** | 0.6648 PASS | 0.6855 PASS | 0.6535 | 0.7985 |
| ~30% | 0.7062 PASS | **0.7194 PASS** | 0.6836 PASS | 0.7100 PASS | 0.6723 | 0.8305 |
| ~40% | 0.7458 PASS | **0.7495 PASS** | 0.6987 PASS | 0.7269 PASS | 0.6949 | 0.8305 |
| ~50% | 0.7608 PASS | **0.7684 PASS** | 0.7175 PASS | 0.7458 PASS | 0.7119 | 0.8305 |

**Two results, and the second is the consequential one.**

**Uplift is predictable.** F67's failure was not a property of the quantity — with enough fixable items, a readout at
the cheap prefill picks which ones a better path will fix, well above random selection at the same coverage. At a 20%
escalation rate the logit lens reaches 0.6930 against a random ceiling of 0.6535 and a terse-only baseline of 0.5989.

**The Jacobian is not the reason, and at low coverage it is worse than nothing.** The logit lens beats the J-lens at
**all five rates**, and at the two lowest rates the J-lens fails while the logit lens passes. The J-lens does beat a
random Jacobian of matched norm everywhere, so its readout is not noise — it simply loses to the identity.

**This is the exact reversal of F48**, where the J-lens beat the logit lens on difficulty, 0.7626 against 0.6729, and
the mechanism there was the verbaliser log-odds moving from chance to 0.7629. The interpretation that survives both
results: **`J` moves the readout off the next token and onto what the model would say, which is the right move for
"will this model be wrong" and the wrong move for "will a different computation succeed".** Uplift is a question about
another path, and the plain next-token distribution reads it better than the workspace projection does.

**What this removes from the design, which is most of the apparatus.** F56, F57 and F58 exist to ship a Jacobian
safely: the weight digest that must key on published rather than loaded weights, the `measured_on` provenance for
constants that cannot be declared, the amplitude that differs by a factor of four between structurally identical
models, the refusal on digest mismatch. **All of it is machinery for distributing `J`.** If the decision that matters
is read by a logit lens, then the judge carries no Jacobian, needs no amplitude, has no measured constant to license,
and the compatibility contract shrinks to what any readout needs: the tokenizer and the vocabulary. The engine-side
plumbing of F64–F66 is unaffected — a residual is still read at prefill and an action still comes back — but what
travels with the judge becomes small enough that most of F56–F58 stops being a requirement.

**What is not withdrawn.** F47 (J exists and is stable), F48 (it predicts difficulty better than both controls), F61
(its coordinates are causally upstream of the verbaliser) all stand as measured. What changes is their bearing on
routing: **the Jacobian is established as a real object and is not the right instrument for the escalation decision.**

**What remains unclaimed.** The oracle reaches 0.8305 at a 30% rate where the logit lens reaches 0.7194, so **6.2
points of the available uplift are still unpredicted** — consistent with the 0.9291 ceiling and 78% unpredicted
recorded earlier. And the free features (prompt length plus the emitted letter) reach 0.6855 at 20%, only 0.0075 below
the logit lens, so **most of what is being captured at moderate coverage needs no internals at all**. Whether an
internal readout earns its cost over the free signal is the next question, and it is a smaller claim than the one this
project started with.

## F69 — The free signal that matches the internal readout is the one the existing gateway router already computes

**Where it bit.** F68 left the internal readout 0.0075 above a "free" baseline and flagged that as too thin to build
on. It was also measured against a broken control: the free arm's length feature was `len(question_id)`, an
identifier of four or five characters, not the prompt's length. Fixing a control that was too weak is the direction an
honest correction goes, and it changes the conclusion.

Same 888 items, same instrument — threshold on calibration, accuracy on test at fixed escalation rates:

| rate | internal (logit lens) | **prompt length alone** | **tokens + category** | + emitted letter | length + internal |
|---|---|---|---|---|---|
| 10% | 0.6497 | 0.6045 | **0.6704** | 0.6685 | 0.6554 |
| 20% | 0.6930 | 0.6139 | **0.7024** | 0.7024 | 0.6987 |
| 30% | 0.7194 | 0.6516 | 0.7194 | **0.7288** | 0.7232 |
| 40% | **0.7495** | 0.6704 | 0.7382 | 0.7495 | 0.7552 |
| 50% | **0.7684** | 0.6817 | 0.7439 | 0.7589 | 0.7684 |

internal minus length-alone, paired bootstrap: **+0.0452 [+0.0226, +0.0678]** at 10%, rising to **+0.0866 [+0.0584,
+0.1168]** at 50% — PASS at every rate.

**Three findings, and the third closes the line.**

**Prompt length alone is not enough.** The internal readout beats it significantly at every rate. So "just look at how
long the prompt is" is not the answer, and a round that had only compared against a broken length feature would have
concluded otherwise.

**Category is the load-bearing free feature.** Adding it to length reaches 0.6704 and 0.7024 at the two lowest rates,
**at or above the internal readout**, and adding internals on top of it changes nothing there — the values are
identical. This is the fourth independent time in this project that the free signal has matched or beaten an internal
one; earlier rounds found difficulty survives decontamination with the free signal having all of it, that category *is*
the free signal, and that 84.3% of a discriminant sat in the letter span.

**And the free feature that does the work is the one the industry's gateway already computes.** F63 identified a
structural mismatch: the standard's decision point runs before any engine has processed the request, so a residual read
after prefill does not exist there. That mismatch is why speculative dispatch was designed, built and measured in
F64–F66. **If the load-bearing signal is the prompt's category, the mismatch dissolves** — a category is a function of
the prompt, computable at the gateway, and vLLM's router is a *semantic* router whose whole business is classifying the
prompt. The decision fits `Filter`/`Scorer`/`Picker` natively: no engine hook, no residual, no Jacobian, no plugin, no
conflict with a fully compiled model, no scheduled-token row mapping.

**Where internals still win, stated fairly.** At 40% and 50% escalation the internal readout is ahead of tokens plus
category, 0.7495 against 0.7382 and 0.7684 against 0.7439. But escalating half the traffic saves little, so the region
where internals help is the region where the cascade has least reason to exist. A design should be judged in its
operating region, and in the 10–30% band the free signal is at least as good.

**What this does to the engine-side work.** It does not make F64–F66 wrong — the plumbing runs, the escalation channel
works, the common path costs nothing, and the failures they found (the compiled-model conflict, the row mapping, the
missing action channel) are real properties of the extension points that anyone doing this would meet. It makes them
**unnecessary for this decision.** The honest summary of the line is: the Jacobian is a real object that predicts
difficulty better than its controls and is causally upstream of the verbaliser; it is not the right instrument for
choosing when to escalate; and the instrument that is turns out to live at the gateway, where the standard already puts
the decision.

**What would still be worth measuring.** The oracle reaches 0.8305 where the best arm reaches 0.7288, so **10 points of
available uplift remain unclaimed by anything tried here.** Whether a classifier trained for *uplift* rather than for
topic closes any of it is a gateway-side question and needs no internals to answer, which makes it cheap.

## F70 — Every cheap prompt-side signal is equivalent, none reaches the oracle, and the cheapest one needs no classifier

**Where it bit.** F69 named the last open question of this line: the topic label is a proxy, and the quantity wanted is
whether a longer computation will fix the item, so does a classifier trained directly on **uplift** from the prompt text
close any of the 10 unclaimed points? Everything needed is available at the gateway, so the test is cheap.

**First attempt, and its diagnosis.** Hashed word unigrams and bigrams — 2,048 features plus 10 surface counts —
against 357 calibration items with 72 positives. It lost **7 and 10 points** at the two lowest rates. That is not a test
of the idea; it is a demonstration of overfitting, and reporting it as evidence against text features would have been
the mirror image of the power failure recorded two entries earlier.

**Second attempt, at a dimension this sample can train:**

| rate | tokens + category | **surface counts alone (10)** | surface + category (17) | hashed (2048) |
|---|---|---|---|---|
| 10% | **0.6704** | 0.6535 | 0.6685 | 0.6008 |
| 20% | 0.7024 | **0.7081** | **0.7081** | 0.6045 |
| 30% | 0.7194 | **0.7326** | 0.7250 | 0.7363 |
| 40% | 0.7382 | **0.7439** | 0.7326 | 0.7401 |
| 50% | 0.7439 | 0.7495 | **0.7571** | 0.7401 |

Every paired interval crosses zero; the largest difference is 0.0132. **FAIL at every rate**, and this time the failure
is informative: the arms are equal, not broken.

**Two conclusions the whole line comes down to.**

**The topic label is not needed either.** Ten surface counts of the prompt — its token count, its length, its digit and
symbol and question-mark counts, its longest word, its type-token ratio, its option count — match tokens plus category
everywhere. So the practical recommendation is the cheapest arm available: **no classifier, no embedding service, no
model call, no engine hook.** Given F69 showed the internal readout does not beat the topic label in the operating band,
and this shows surface counts match the topic label, the chain runs from the residual all the way down to counting
characters with no measurable loss.

**And nothing reaches the oracle.** The best arm anywhere is 0.7571 against an oracle of 0.8305 — **7 to 10 points of
available uplift are unclaimed by every signal tried in this project**: the layer-32 residual, the J-lens readout, the
logit lens, the topic label, surface counts, hashed text. The consistency of that gap across such different instruments
is itself the finding. Earlier rounds bounded uplift prediction at a 0.9291 ceiling with 78% of it unpredicted, and this
is that bound met again from a different direction.

**What is genuinely still open, stated narrowly.** More labelled items would let a text classifier be tested properly —
357 calibration items cannot train 2,058 features and the low-dimension arms may simply be at their own ceiling rather
than at the problem's. And no signal tried here looks at what the *upper* path would do; every arm predicts from the
item alone. A cheap partial run of the upper path is the one untried family, and it is not free, which is exactly the
trade the ledger's cost accounting exists to price.

**Where this leaves the design.** The decision is a gateway-side function of the prompt, computable from counts, and it
belongs in the standard's `Filter`/`Scorer`/`Picker` shape. The engine-side apparatus — plugin, hook, Jacobian artefact,
weight digest, measured amplitude, sentinel channel — is not required for it. What the engine-side work leaves behind is
a set of true facts about the extension points that anyone attempting this will meet, and a clear statement that this
particular decision does not need them.

## F71 — The model's own count of remaining options adds to the baseline; its surprise at the prompt is a subject effect

**Where it bit.** F70 closed the line with "every cheap prompt-side signal is equivalent and none reaches the oracle",
and the equivalent signals were all *external* descriptions of the prompt — counts of characters, symbols, options, a
topic label. Two quantities of a different kind had not been tested: **what the model says about the item when asked**,
and **how surprised it is by the item's text.** The second is the direct proxy for "have I seen much like this", which
is the intuition that rare material should be unsolvable.

**Surprise is measured as the negative log probability the model assigns to the prompt's own tokens** — mean, 90th
percentile, maximum, and the share of tokens above 5 and 8 nats. It costs nothing extra: the numbers fall out of the
same forward pass that reads the prompt. **The reported count** comes from asking, at a fixed cue after the question,
how many options remain plausible, and reading the answer as a distribution over the digits 1 to 9 without generating
anything.

| quantity | correlation with "the box is wrong" |
|---|---|
| **the model's reported count of remaining options** | **+0.1791** |
| the count's own uncertainty | +0.1143 |
| **mean surprise over the prompt** | **−0.1052** |
| 90th percentile surprise | −0.1024 |
| share of tokens above 5 nats | −0.0972 |
| prompt token count | +0.0483 |

**The reported count is the first thing in a long while to beat the baseline.** Held-out AUC for difficulty, against
the ten surface counts at 0.6298:

| features | AUC | vs the baseline | verdict |
|---|---|---|---|
| surprise alone | 0.5462 | −0.0836 [−0.1211, −0.0464] | FAIL |
| reported count alone | 0.6614 | +0.0316 [−0.0096, +0.0699] | FAIL |
| **surface + reported count** | **0.6715** | **+0.0417 [+0.0229, +0.0610]** | **PASS** |
| everything | 0.6648 | +0.0350 [+0.0139, +0.0559] | PASS |

So asking the model how many options are still live **adds real information about difficulty that no external
description of the prompt contains.** It does not help uplift — at every escalation rate, surface plus count is within
0.003 of surface alone — which is the same split this project keeps finding: difficulty is readable, uplift is not.

**And the surprise result is a textbook confound, with the sign the intuition did not expect.** Across the seven
subjects, accuracy and mean surprise correlate **+0.7840**:

| subject | accuracy | mean surprise |
|---|---|---|
| math | **0.4157** | **1.4133** |
| engineering | 0.4363 | 1.3704 |
| law | 0.5868 | 1.8053 |
| philosophy | **0.7277** | **1.9718** |
| economics | 0.7536 | 1.6508 |

Mathematics and engineering are the **least surprising text and the hardest problems**; philosophy and economics are
the most surprising text and the easiest. **Within each subject the correlation between surprise and error is +0.0061
pooled**, ranging from −0.1063 to +0.0783 with no consistent sign.

**So surprisal carries no information about difficulty once subject is held fixed.** The −0.105 seen over the pool is
Simpson's paradox: a between-subject effect whose sign is opposite to a within-subject effect that is zero. What
surprisal measures is **the surface style of the text, not the thickness of the relevant knowledge** — a formula-dense
maths question is easy to predict token by token and hard to answer, and fluent prose is the reverse. The intuition
that "material I have barely seen is material I cannot solve" is not refuted as an idea; it is refuted for *this
measure of familiarity*, and the failure mode is now named: prompt surprisal is a style detector.

**One configuration fact worth recording because it bears on all of the above.** Every capture in this project ran with
the model's thinking mode **disabled** (`enable_thinking=False` in the chat template). So every readout is of a model
answering directly, and none of these numbers describes what the same readouts would say with a reasoning trace
enabled. That is a real limitation on the scope of every entry from F47 onward, not only this one.

**What is still running.** The count tested here is "how many options remain plausible". The related question — "into
how many sub-problems does this decompose" — was refused by a sanity gate on an earlier attempt, because that gate
checks the distribution of answer *letters* and a decomposition count has no letter to check. It is relaunched with the
gate checking the cue's own reply variability instead, which is the check with content: if the model reports the same
count everywhere, the cue installed nothing.

## F72 — Asking the model to count sub-problems correlates with difficulty and adds nothing; asking it to count live options adds

**Where it bit.** F71 found that the model's reported count of remaining options beats the surface-count baseline, and
that its surprise at the prompt is a subject effect with no within-subject signal. The adjacent question was asked
directly: **into how many sub-problems does this decompose?** An earlier attempt at that cue was refused by a sanity gate
that checks the distribution of answer *letters*, which a decomposition count does not have; rerun with the gate checking
the cue's own reply variability instead, it completed on 1,664 items.

**The correlation is real and, unlike surprise, it is not a subject effect.**

| | pooled correlation with "the box is wrong" | **within-category, pooled** |
|---|---|---|
| **reported sub-problem count** | **+0.1486** | **+0.1303** |
| prompt surprise (F71) | −0.1052 | **+0.0061** |

Six of seven categories are positive (engineering +0.2749, computer science +0.2074, law +0.1848, math +0.1423,
philosophy +0.1185, health +0.0438, economics −0.0593). So the model's estimate of how many steps a question takes
carries information about whether it will get it wrong, and that information survives holding the subject fixed — which
is exactly the check that killed surprise.

**The reported count is effectively binary.** Its argmax is 1 on 868 items and 3 on 714, with 22 items spread over the
rest. The model does not use the 1-to-9 range it was offered; it distinguishes "one step" from "a few steps" and little
else.

**And it adds nothing to the baseline.** Held-out AUC on the items carrying every measurement, against surface counts at
0.6957:

| features | AUC | vs the baseline | verdict |
|---|---|---|---|
| reported sub-problem count alone | 0.5813 | −0.1145 [−0.1724, −0.0603] | FAIL |
| reported option count alone | 0.6907 | −0.0051 [−0.0442, +0.0349] | FAIL |
| **surface + option count** | **0.7221** | **+0.0264 [+0.0101, +0.0425]** | **PASS** |
| surface + sub-problem count | 0.7052 | +0.0095 [−0.0112, +0.0287] | FAIL |
| **surface + both counts** | **0.7267** | **+0.0310 [+0.0082, +0.0533]** | **PASS** |
| everything including surprise | 0.7293 | +0.0336 [+0.0092, +0.0576] | PASS |

**Correlating and adding are different things, and this is a clean case of the difference.** The sub-problem count
correlates with difficulty at +0.15 and contributes nothing over ten surface counts of the prompt, because a question
that decomposes into several steps is also a question with more symbols, more numbers and more clauses — the surface
counts already have it. The option count is the one that adds, and what it has that the surface cannot is the model's
own read of how many answers are still live. This is the same shape as the earlier finding that the topic label is the
free signal and a per-category policy fails: **a quantity can be genuinely informative and entirely redundant.**

**On uplift the counts look better than they did.** At a 20% escalation rate, surface plus both counts reaches 0.7407
against the baseline's 0.7003, and at 30% 0.7677 against 0.7542. That is a change from the pattern in which nothing
helped uplift — but the subset carrying all measurements has 297 test items with 126 fixable, no paired intervals were
computed for it, and the earlier rounds' lesson about small subsets is exactly why this is recorded as a direction
rather than a result.

**What this leaves.** Of the four things asked, three are answered: the decomposition count correlates but is
redundant; surprise is a style detector; and every capture so far ran with thinking disabled. The fourth — what happens
with thinking enabled — is measuring now, and its interim numbers already show the one thing every earlier tier pair
lacked: **a 256-fold token ratio between the two arms.**

## F73 — Thinking on versus off is the first tier pair with a real price gap: 170x the tokens for 20.6 accuracy points

**Where it bit.** Every capture in this project ran with thinking disabled (F71), and every tier pair it had was
economically uninteresting: F67's two models differed by 2.5 accuracy points, and F68's terse-versus-explaining pair
differed in prompt only, with no token cost recorded. Turning thinking on is not just a missing condition — it is the
**cheap/expensive pair the project never had**, on one set of weights, with a cost ratio that makes routing worth
arguing about.

One vLLM server, `empero-ai/Qwen3.8-9B-Distill`, 180 labelled items, each answered twice. The two arms differ by a
per-request chat-template flag, not by a deployment, so this measures two conditions rather than two servers.

| | thinking off | thinking on | ratio |
|---|---|---|---|
| accuracy | 0.5222 | **0.7278** | **+0.2056** |
| completion tokens, median | 4 | **682** | **170.5x** |
| latency, median | 210 ms | **24,477 ms** | 116x |
| **fixes / breaks** | — | **44 (24.4%) / 7 (3.9%)** | oracle 0.7667 |

**The arithmetic that makes a router worth building.** Escalating every item costs 170x for +20.6 points. Escalating
only the 24.4% that thinking actually fixes would cost roughly **42x** for the same gain — so a selector that finds
those items is worth about a factor of four in serving cost. Every previous pair in this ledger had a gap too small for
that argument to matter; this one does not.

**Two facts about how thinking arrives, both of which affect how it can be used.**

**There is no separate reasoning channel.** `reasoning_content` was returned on **0 of 180 items** — with
`enable_thinking: true` the trace appears in the ordinary content field, beginning `Thinking Process:\n\n1. **Analyze
the Request:**`. So a caller cannot separate the reasoning from the answer by field, and any harness that assumes it can
will read the first sentence of the reasoning as the answer. The answer here is read at an explicit `Answer:` cue over
the whole trace, which is the convention that finally survived three earlier failures.

**A third of the traces never finished.** 62 of 180 hit the 1,024-token cap, so the thinking-on accuracy of 0.7278 is a
**lower bound**: those items answered from a truncated trace. Raising the cap would raise both the accuracy and the
cost, which is exactly the trade the next measurement is about.

**The routing test needs more items than this run has.** At three coverage rates the readout at the cheap prefill scored
0.5618, 0.5843 and 0.6517 against random-selection ceilings of 0.5618, 0.5843 and 0.6292 — **exact ties at two of the
three rates.** With 89 test items accuracy moves in steps of 1/89 = 0.0112, so a tie is what a coarse instrument
produces, not what a null looks like. The signal question is open here; what failed was the resolution.

**What is measuring now.** Thinking is a stream, so it can be cut off, and if most of the benefit arrives early then the
price is nothing like 170x and the decision becomes **how long to think** rather than **whether to think**. That curve
is arranged to cost one generation rather than one per budget: the trace is generated once at the full cap, and for each
budget the first k tokens of it are taken, a cue appended, and the answer read — under greedy decoding the first k tokens
of the full trace are exactly what a request capped at k would have produced. The readout is captured at every budget
too, because a mid-generation gate would have to decide from what the model looks like after k steps.

## F74 — Cutting thinking short loses benefit, and a readout 64 tokens in can pick which items are worth continuing

**Where it bit.** F73 measured thinking at 170x the tokens for +20.6 accuracy points and left the obvious question:
thinking is a stream, so if most of the benefit arrives early the price is nothing like 170x. The curve was arranged to
cost one generation rather than one per budget — the trace is generated once at the cap, and for each budget k the first
k tokens are taken, a cue appended, and the answer read, which under greedy decoding is exactly what a request capped at
k would have produced. 230 items, budgets 0 to 1024.

**Split by whether the trace concluded, because pooling the two hides the answer.** Two thirds concluded and a third hit
the cap, and for the latter the "full budget" arm is itself a truncated trace — so pooled numbers compare
truncated-at-256 with truncated-at-1024 and say nothing about concluding.

| budget | **concluded (154 items)** | cut off (76 items) |
|---|---|---|
| 0 | 0.6169 | 0.3553 |
| 128 | 0.6688 | 0.3289 |
| 256 | 0.7662 | **0.4737** |
| 512 | 0.8442 | 0.3816 |
| **1024** | **0.8766** | 0.4474 |

**For items whose trace concludes, the curve rises monotonically to the cap and does not flatten.** The smallest budget
within 0.02 of the full one is the full one. **So cutting thinking short loses benefit** — the price cannot be reduced
by truncation without paying in accuracy, and the answer to "would a truncated trace do as well" is no.

**And I had this wrong at the halfway point.** At 56 concluded items the curve looked flat from 512, and I reported 512
as giving the full benefit at half the cost. At 154 it keeps climbing. The interim reading was a small-sample plateau,
and the correction is the reason a curve should not be read before it is finished.

**The cut-off group peaks at 256 and the intervals do not support it.** 0.4737 [0.3654, 0.5845] against 0.4474 [0.3408,
0.5590] at the cap — heavy overlap. The pooled non-monotonicity that looked like "thinking too long hurts" is a mixture
of two groups whose base rates differ by 26 points, which is the third Simpson-shaped artefact in this ledger.

**The finding that changes the picture: a mid-generation readout works, once.** Asked whether the four readout features
after k tokens of thinking pick the items that continuing to a larger budget would fix, threshold on calibration and
scored on test against random selection of the same coverage:

| transition | 20% coverage | 30% | 50% |
|---|---|---|---|
| **64 → 256** | **0.5929 > 0.5714 PASS** | **0.6000 > 0.5929 PASS** | **0.6500 > 0.6286 PASS** |
| 128 → 512 | 0.5857 FAIL | 0.6214 FAIL | 0.6571 FAIL |
| 256 → 1024 | 0.6786 FAIL | 0.6857 FAIL | 0.7286 FAIL |

**This is the first time in this project that an internal readout has beaten its control on a routing decision.** Every
earlier attempt — the J-lens on difficulty against a logit lens, the logit lens against surface counts, the residual
against random escalation — either lost or tied. Here the readout after 64 tokens of thinking passes at all three
coverage rates, and it passes on the transition where there is most to gain.

**The caveats are real and the claim is narrow.** The test fold holds 26 items that continuing fixes; the margins are
0.0215, 0.0071 and 0.0214, and the middle one is thin. Nine cells were tested and three passed — but **all three are the
same transition**, which is the coherent pattern rather than three scattered hits, and the two failing transitions have
fewer fixable items (23 and 15). A confirmation at a larger sample is what this needs, and it is cheap: the expensive
part is the generation, which is already done once per item.

**Why the shape makes sense, offered as a reading rather than a result.** Early in a trace the model has set up the
problem and not yet committed; whether the setup is going anywhere is plausibly visible then. Later the trace has
committed, and by 256 tokens the readout is describing a line of reasoning already underway rather than a decision
still open. That is consistent with the transition ordering, and it is not established by it.

**And one separation larger than any predictor here.** Whether the trace concluded at all is worth **26 accuracy points**
(0.6169 against 0.3553 at zero thinking, 0.8766 against 0.4474 at the cap). No signal tried in this project separates
items that well. It is known only after paying, so it cannot route — but it does say that "will this finish" is the
quantity with the most information in it, which is a different target from either difficulty or uplift.

## F75 — A correction: the served readout had three features, not four; and conclusion is not predictable before paying

**Two things, one of them a correction to every serving entry.**

**The correction.** The served plugin's readout was written as four features — entropy, maximum probability, verbaliser
log-odds, and the rank of the letter the model is about to emit — and **the fourth was left as a constant zero.** It was
never computed. So every result from F65 onward, including F74's mid-generation gate, ran on **three** features, and
every sentence in those entries saying "four readout features" is wrong. The bug surfaced only because a correlation
against it came back as `nan`, which is the kind of thing a summary statistic catches and a passing test does not.

The direction of the error is worth naming: **F74's PASS was achieved with less than it claimed**, so the finding
survives the correction and is if anything understated. The feature is computed now, and the confirmation run uses it.

**The measurement.** F74 found that whether a trace concludes within the cap is worth 26 accuracy points — 0.6169
against 0.3553 with no thinking, 0.8766 against 0.4474 at the cap — a bigger separation than any signal this project has
produced. It is known only after paying, so the question is whether it can be predicted from the readout at the prompt's
own prefill, before any thinking is generated. If it could, the decision would gain a third target beside difficulty and
uplift, and one whose **label is free**: a finish reason, with no second arm to run.

| | held-out AUC for "the trace will hit the cap" |
|---|---|
| the prefill readout | 0.5977 |
| the same pipeline on shuffled labels | 0.5761 |
| difference | **+0.0216 [−0.0062, +0.0503] FAIL** |

**FAIL.** And the shuffled-label control at 0.5761 is the reason to report it that way rather than as "0.5977, weakly
predictive": with 140 test items and 46 positives, refitting the same pipeline on nonsense labels reaches 0.576 by
itself, so the honest reading of 0.5977 is that it is inside what the fitting procedure buys for nothing. A control that
measures what the machinery achieves on noise is the one that makes a weak positive readable, and without it this would
have been written up as a small effect.

Per-feature correlations with hitting the cap, for whatever they are worth: entropy **+0.2233**, verbaliser log-odds
+0.1126, maximum probability −0.0664. So entropy at the prompt does carry something about whether the answer will run
long — it just does not survive as a fitted predictor at this sample size.

**What is running.** The confirmation of F74's passing transition, at double the sample, with the fourth feature actually
computed. 26 fixable items in the test fold is what the original PASS rested on, and doubling the sample is the cheapest
thing that could overturn it.

## F76 — The signal is the entropy after a short think, it is specific to early positions, and AUC shows it clearly

**Where it bit.** F74's mid-generation gate passed at 64 → 256 with coverage-constrained margins of 0.0215, 0.0071 and
0.0214 — thin enough to want confirmation and thin enough that the instrument was suspect. A coverage-constrained
comparison forces a threshold onto a discrete item count, so with 140 test items the accuracy moves in steps of 1/140 and
the margin is quantised. Held-out AUC has no threshold, so the sample enters through the interval alone. Re-measured that
way, against the same pipeline fitted on shuffled labels:

| transition | fixable in test | **AUC** | shuffled-label control | difference | verdict |
|---|---|---|---|---|---|
| **64 → 256** | 26 | **0.7149** | 0.4150 | **+0.2999 [+0.0941, +0.4922]** | **PASS** |
| 128 → 512 | 23 | 0.5663 | 0.5180 | +0.0483 [−0.0305, +0.1379] | FAIL |
| 256 → 1024 | 15 | 0.5477 | 0.4731 | +0.0747 [−0.1763, +0.3056] | FAIL |

**0.7149 against a shuffled-label control of 0.4150.** The same finding that looked like a 0.02 margin is a 0.30 margin
once the threshold is removed, and the instrument was the reason. This is the clearest positive result in this ledger.

**What carries it is the entropy.** Three features were live in this data (the fourth was the constant recorded in F75),
and the fitted coefficients are **entropy +0.186**, maximum probability +0.007, verbaliser log-odds −0.048. So the
signal is: **after 64 tokens of thinking, if the readout is still spread out, more thinking helps; if it has already
peaked, it will not.** That is a mechanism simple enough to state in one sentence and to check against the transition
ordering, which it survives.

**The signal is specific to position, not to the size of the jump.** 64 → 256 and 256 → 1024 are both fourfold
increases, and only the early one works. So it is not "predicting a 4x extension"; it is that early in a trace the
question of whether the reasoning is going anywhere is still open, and by 256 tokens the model has committed and the
readout describes a line already underway. The later transitions also have fewer fixable items (23 and 15 against 26),
so sample size is a competing explanation for their failure — but it cannot explain 128 → 512's failure at 23 items when
64 → 256 passes at 26.

**The policy this suggests, with its arithmetic.** Thinking costs a median of 682 tokens for +20.6 accuracy points
(F73). Instead: **give every item 64 tokens of thinking — a tenth of the cost — read the entropy, and continue only
where it is high.** The gate's job is then not "should this item think" but "has this item finished being worth
thinking about", which is a question asked 64 tokens in rather than zero tokens in, and that is precisely where the
signal turns out to live. The prefill-time gate that this project spent most of its effort on sits at zero tokens, where
F69 and F70 showed counting characters does as well as reading the residual.

**What this does not yet establish.** The margin is wide but so is its interval, the confirmation run at double the
sample is in flight, and the budgets tested are a coarse grid — whether the signal is strongest at 64 or somewhere
between 32 and 128 is not resolved by three passing cells at one budget. And the accuracy gain a real policy would
capture has not been computed: the AUC says the ordering is good, not what a threshold on it earns after paying for the
64 tokens on every item.

## F77 — The gate buys tokens, not accuracy; and a truncated reasoning trace is worse than none at all

**Where it bit.** F76 measured the ordering — AUC 0.7149 for picking which items an extension fixes — and said plainly
that an AUC is not what a policy earns, because the policy pays the probe on **every** item and the extension only on the
selected ones. This puts accuracy and tokens on one table for every policy, with the threshold chosen on calibration and
applied to test, so the numbers are what a deployed policy would have got rather than the best a threshold could get.

| policy | accuracy | mean tokens |
|---|---|---|
| answer with no thinking | 0.5214 | 0 |
| **64 tokens on everything, then answer** | **0.5071** | 64 |
| extend everything to 256 | **0.6857** | 256 |
| think fully on everything | 0.7286 | 1024 |
| **gated: probe 64, extend 52%** | **0.6571** | **164** |
| gated: probe 64, extend 29% | 0.6286 | 120 |
| **oracle gate at the same coverage** | **0.6929** | 164 |

**The gate cannot buy accuracy. The oracle at the same coverage reaches 0.6929 and extending everything reaches
0.6857** — a perfect selector is worth **0.007 accuracy points** over the policy with no selector at all. Everything the
gate achieves is on the token axis: 164 against 256 is **36% fewer tokens for 2.9 accuracy points**, and against the full
budget it is **84% fewer tokens for 7.2 points**. Whether that exchange is worth making is a deployment question with a
price attached; what is settled is that there is nothing else on offer. A write-up that reported the AUC and stopped
would have implied otherwise.

**And a finding worth more than the gate: a truncated reasoning trace is worse than no reasoning at all.** Answering
after 64 tokens of thinking scores **0.5071 against 0.5214 for never thinking**. Stopping mid-deliberation leaves the
model having raised options it had not yet rejected, and reading an answer off that is worse than reading it off the
question. So the branch of the gate that declines to extend should **throw the partial trace away**, and doing so
improves every coverage for free:

| coverage | keep the partial trace | **discard it** | gain |
|---|---|---|---|
| 20% | 0.5929 | **0.6143** | +0.0214 |
| 29% | 0.6000 | **0.6286** | +0.0286 |
| 39% | 0.6143 | **0.6429** | +0.0286 |
| 52% | 0.6500 | **0.6571** | +0.0071 |

**This generalises past this experiment.** Any system that caps a reasoning budget and answers from whatever the trace
reached is doing measurable harm relative to not having thought — 1.4 accuracy points here — and the fix costs nothing:
discard the trace and answer from the prompt. The 34% of traces that hit the cap in F73 were all answered from partial
traces, so **that entry's thinking-on accuracy of 0.7278 is understated by whatever this effect is worth on those
items**, and the same is true of every truncated arm in F74's curve.

**What this leaves for the thinking line.** The signal is real and early (F76). Its value is a token saving with a small
accuracy cost, and the ceiling on any selector at this transition is 0.007 over the no-selector policy. The remaining
question with money in it is not a better selector but a better **operating point**: whether some budget pair other
than 64 → 256 has a wider oracle gap, because a transition where the oracle beats always-extend by more than 0.007 is
the only place a selector can earn accuracy rather than only tokens. That is a sweep over pairs, and the confirmation run
in flight gives the sample to do it on.

## F78 — Accuracy lives in predicting HARM, the room exists at every pair, and no fitted selector claims any of it

**Where it bit.** F77 found that a perfect selector at probe 64 / extend 256 is worth 0.007 accuracy points over
extending everything, and asked whether some other budget pair has more room. The question has an exact answer rather
than an empirical one, and stating it first is what makes the sweep readable.

**A selector can only earn accuracy where extending HURTS.** If extension never hurts, "extend everything" already
captures every item extension fixes, and the best a selector can do is match that accuracy while spending less. So the
oracle's advantage over always-extend equals exactly the share of items that extension **breaks** — right at the probe
budget and wrong at the extended one. Room for a selector is not a property of the signal; it is a property of the pair.

Sweeping all 26 pairs over the eight budgets:

| probe → extend | fixes | **breaks** | always-extend | oracle | **oracle advantage** | **fitted selector achieved** |
|---|---|---|---|---|---|---|
| 256 → 1024 | 28 | **13** | 0.7286 | 0.7929 | **+0.0643** | — |
| 0 → 64 | 9 | **15** | 0.5071 | 0.5714 | **+0.0643** | **−0.0071** |
| 16 → 128 | 19 | 12 | 0.5786 | 0.6286 | +0.0500 | +0.0000 |
| 256 → 512 | 17 | 12 | 0.7143 | 0.7643 | +0.0500 | **+0.0000** (the best of any pair) |
| 64 → 256 | 42 | **4** | 0.6857 | 0.6929 | +0.0071 | — |

**The room exists — up to 6.4 accuracy points — and no fitted selector claims any of it.** The best achieved advantage
at any pair is **±0.0000**, and several are negative. Meanwhile the same readout predicts the *helping* direction at
AUC 0.7149 (F76). So the asymmetry is sharp: **the readout can tell that more thinking will help; it cannot tell that
more thinking will hurt** — and accuracy gains live entirely in the second.

**Why that asymmetry is not surprising once stated.** "This is still unsettled, keep going" is a property of the current
state, which is what a readout of the current state can see. "Continuing will talk this model out of a correct answer" is
a property of a computation that has not happened yet, and nothing in the present state distinguishes an item that will
be reasoned into a mistake from one that will be reasoned into a correction. The helping direction asks about the
model's uncertainty now; the harming direction asks about a future trajectory.

**The sample caveat is large and must be stated with the claim.** Breaks number 3 to 15 out of 230 items, which leaves
roughly 6 in the calibration fold — **no fitting procedure can work on six positives**, so the honest claim is not "the
readout is blind to harm" but "**at this sample size the harm direction cannot be fitted at all**". The confirmation run
in flight has 529 items and will bring breaks to roughly 30, of which about 12 in calibration. That is still small, and
if the harm direction is to be tested properly it needs a dataset built for it — items selected for being near the
boundary where extension flips them — rather than a uniform sample where they are 2% of the data.

**What this settles about the design, provisionally.** A budget gate is a **token-saving device** with a measured price
(F77: 36% fewer tokens for 2.9 accuracy points at the best operating point). It is not an accuracy device, and the
reason is not a weak signal but a missing one: the quantity that would buy accuracy is unobserved at decision time and
unfitted at this scale. Any claim that a thinking-budget router improves quality needs to produce the harm predictor
first, and this ledger does not have it.

## F79 — Pooling the budget pairs removes the power excuse: harm is below chance, and pooled "help" is explained by the budgets alone

**Where it bit.** F78 could not fit the harm direction because any single budget pair leaves about six positives in
calibration, and said so rather than concluding from it. Pooling fixes that: an item appears in up to 26 pairs and the
same question is asked at each, so 230 items become **6,440 pair-instances with 248 harm cases** — 113 in calibration,
135 in test. The split is by **item**, so an item's readout never appears on both sides; splitting by instance would have
made the held-out number a memory test.

| direction | readout + budgets | **budgets alone** | shuffled labels | difference over the stronger control |
|---|---|---|---|---|
| **help** (extension fixes it) | 0.6474 | **0.6494** | 0.5098 | −0.0020 [−0.0095, +0.0070] FAIL |
| **harm** (extension breaks it) | **0.4614** | 0.5134 | 0.5009 | −0.0520 [−0.1135, +0.0041] FAIL |

**Harm is below chance with 113 calibration positives.** The power excuse is gone: six features fitted on 113 positives
is a fit that can work, and it does not. F78's asymmetry — the readout sees that thinking will help and not that it will
hurt — is now measured rather than inferred from two differently-powered fits.

**And pooled, the help direction is entirely explained by the budgets.** Budgets alone reach 0.6494 and adding the
readout reaches 0.6474 — no gain, and the fitted coefficients say why: `log extend` is **+0.421**, dwarfing entropy's
+0.182. Pooled, the dominant fact is that a larger extension fixes more items, which is trivially true and needs no
readout to know.

**This does not overturn F76, and saying how is the point.** F76 fitted at a **single** pair, 64 → 256, where the budget
is constant and cannot explain anything, and its control was shuffled labels: AUC 0.7149 against 0.4150. That measures
**the ordering of items within one pair**, which is what a deployed policy needs, because a policy operates at one
operating point. The pooled AUC mixes between-pair variation with within-pair variation, and the between-pair part is
large and uninformative, so it swamps the within-pair signal. Both numbers are correct and they answer different
questions. The consistency check is the coefficient: entropy is **+0.182** pooled against **+0.186** at the single pair,
so the same relationship is being found in both.

**The lesson about the instrument, which is the transferable part.** A pooled fit over conditions can hide a real
within-condition effect behind a trivial between-condition one, and a within-condition fit can lack the positives to
test the direction that matters. Neither is the wrong analysis; running only one of them is. Here the pooled version was
the only way to power the harm test, and the single-pair version was the only way to see the help signal at all.

**What is now established about the thinking-budget line.**

1. The readout after a short think orders items by whether continuing helps, within a pair, at AUC 0.7149 (F76).
2. That ordering buys **tokens and not accuracy**, because extending everything already captures all the help (F77).
3. Accuracy would require predicting harm, and harm is **not predictable from the readout** at a sample size where it
   could have been (this entry).
4. So the ceiling on a thinking-budget gate is the token saving measured in F77: 36% fewer tokens for 2.9 accuracy
   points at the best operating point.

**What would still change the picture.** A harm predictor from something other than the current readout — the trajectory
so far rather than the state now, since harm is a property of where the reasoning is going. The readout is four scalars of
the present distribution; the direction of travel over the last k tokens is a different object and is not in this data.
That is the next thing worth capturing, and it needs the residual at several points in the trace rather than one.

## F80 — The confirmation at 529 items: the signal reaches further than claimed, harm is settled at chance, and the gate is cheaper than it looked

**Where it bit.** F76 to F79 rested on 230 items, and every entry named what a larger sample would decide. The
confirmation ran at **529 items** — 333 traces concluding within the cap and 196 hitting it — and it changes three
numbers, in three different directions.

**The signal reaches further than F76 concluded.** Held-out AUC for "extending from p to e fixes this item", against the
same pipeline on shuffled labels:

| transition | fixable (test) | AUC | shuffled | difference | verdict |
|---|---|---|---|---|---|
| **64 → 256** | 47 | **0.6803** | 0.3944 | **+0.2858 [+0.1527, +0.4149]** | **PASS** |
| **128 → 512** | 58 | **0.6059** | 0.4983 | **+0.1077 [+0.0373, +0.1779]** | **PASS** (failed at 230 items) |
| 256 → 1024 | 46 | 0.5942 | 0.4923 | +0.1019 [−0.0190, +0.2232] | FAIL, and the interval nearly excludes zero |

F76 said the signal was "specific to early positions" on the strength of one passing transition and two failing ones. At
double the sample **128 → 512 passes**, with entropy's coefficient at **+0.268** — its largest anywhere. So the correct
statement is **early to middle**, and the failure at 256 → 1024 may still be power rather than absence: its interval runs
from −0.019 to +0.223.

**The budget curve is now monotone in both groups, which withdraws a reading twice made.** At 230 items the truncated
group appeared to peak at 256 and fall by the cap, and both F74 and this ledger's summary of it noted the possibility
that over-long truncated traces answer worse. At 529 the truncated group rises monotonically as well — 0.3827 → 0.4337 →
0.4439 → **0.4796** — so **truncating never helps, in either group**, and the earlier peak was noise resolved by sample
size.

**The gate is materially cheaper than it looked.**

| policy | accuracy | mean tokens |
|---|---|---|
| answer with no thinking | 0.5222 | 0 |
| extend everything to 256 | 0.6297 | 256 |
| think fully on everything | 0.7278 | 1024 |
| **gated: probe 64, extend 57%, discard the partial trace** | **0.6234** | **173** |
| oracle gate at the same coverage | **0.6677** | 173 |

**32% fewer tokens for 0.6 accuracy points** against extending everything, where the 230-item measurement said 36% for
2.9 points. And the oracle at that coverage now reaches 0.6677 against always-extend's 0.6297 — **+3.8 points of room**,
where at 230 items the oracle and always-extend were within 0.007 of each other. So F77's "a perfect selector is worth
0.007" was a small-sample figure and the room is real.

**But no selector captures it, and this is now settled rather than underpowered.** Pooling the 26 budget pairs by item
gives **14,812 instances with 627 harm cases — 260 in calibration, 367 in test**:

| direction | readout + budgets | budgets alone | shuffled | difference |
|---|---|---|---|---|
| help | 0.6781 | 0.6710 | 0.3876 | +0.0071 [+0.0033, +0.0118] — **interval above zero, magnitude below the registered 0.02 floor: FAIL** |
| **harm** | **0.5083** | 0.5238 | 0.5236 | −0.0155 [−0.0316, +0.0014] **FAIL** |

**Harm is at chance with 260 calibration positives.** Six features on 260 positives is a fit that works when there is
something to find. F78 said the harm result might be a sample artefact and F79 said 113 positives had removed that
excuse; 260 removes it beyond argument. And the sweep agrees: the best advantage any fitted selector achieves at any
operating point is **+0.0032**, against oracle room of up to +0.0506.

**The help direction pooled deserves its own sentence, because the honest reading is awkward.** The readout adds
**+0.0071 with an interval entirely above zero** — a real effect — and the pre-registered floor was 0.02, so it is
recorded as FAIL. Both facts belong in the record: the effect exists and is too small to have been worth the floor that
was set for it. Restating the floor now would be the failure this project has avoided fifteen times.

**Where the thinking-budget line stands.** A gate on the entropy after a short think orders items well enough to cut
token spend by roughly a third at a cost under one accuracy point, and it works from 64 tokens through 128. Accuracy
gains require predicting harm, harm is unpredictable from the present readout at a sample size that settles it, and the
+3.8 points of oracle room is therefore unclaimed. The remaining candidate is the one F79 named: **the direction of
travel over the last k tokens rather than the state now**, which is not in this data and needs the residual captured at
several points in the trace.

## F81 — The trajectory moves the harm number off the floor, and both directions miss the floor for opposite reasons

**Where it bit.** F79 and F80 settled that harm — continuing turns a right answer wrong — is unpredictable from the
readout at the probe budget, and offered a reading: harm is a property of where the reasoning is going, and the readout
is four scalars of where it is now. That reading names a feature set, and **the feature set was already in the data**.
Each item has a readout at every budget, so the differences between consecutive readouts below the probe describe how the
state has been moving. Nothing new had to be captured.

Pooled over budget pairs, split by item, 14,812 instances with 627 harm cases (260 in calibration, 367 in test):

**HARM**, against the stronger control of budgets alone at 0.5238:

| features | AUC | difference | verdict |
|---|---|---|---|
| **the level alone** (what F79 and F80 tested) | **0.5083** | **−0.0155** | FAIL — *worse than knowing nothing* |
| level + velocity | 0.5429 | +0.0191 [−0.0069, +0.0479] | FAIL |
| **level + 3 differences** | **0.5466** | **+0.0228 [−0.0027, +0.0491]** | FAIL — the interval grazes zero |
| **3 differences, level removed** | 0.5415 | +0.0177 [−0.0091, +0.0431] | FAIL |

**HELP**, against budgets alone at 0.6710:

| features | AUC | difference | verdict |
|---|---|---|---|
| the level alone | 0.6781 | +0.0071 [+0.0033, +0.0117] | FAIL |
| **level + 3 differences** | **0.6889** | **+0.0179 [+0.0106, +0.0256]** | FAIL |

**Both directions miss the registered floor, for opposite reasons, and that is worth stating precisely.** The help
direction has a **solid interval and too small a magnitude** — +0.0179 against a floor of 0.02, with the interval running
from +0.0106 to +0.0256, so the effect is real and under-sized. The harm direction has **the magnitude and not the
interval** — +0.0228 clears the floor while the interval reaches −0.0027. Neither is a claim. Recording them as PASS by
softening the floor is the failure this ledger has avoided fifteen times, and recording them as "nothing" would discard
the first movement the harm number has shown.

**The structural fact inside the harm column is the reason to keep going.** The level is **worse than the control**
(0.5083 against 0.5238) — knowing where the readout is actively misleads about harm — while the motion alone is better
than the level (0.5415). So if harm information exists anywhere in this data, it is in **the direction of travel and not
the position**, which is exactly what F79 and F80 predicted from the shape of the problem rather than from a number. A
prediction made for structural reasons and then borne out weakly is a different thing from a hypothesis fitted after the
fact, and it is why this is worth one more measurement instead of a conclusion.

**What that measurement is.** Only 5,290 of the 14,812 instances have three differences available, because a probe at a
low budget has few budgets beneath it. A **finer grid** below 256 — say 24, 48, 96, 192 — would give every probe more
history at no extra generation cost, since the trace is generated once and every budget is a cheap forward pass over its
prefix. That is the cheapest thing that could turn +0.0228 [−0.0027, +0.0491] into a decided number, and it needs no new
model, no new items, and no new capture design.

**One implementation note carried forward.** F75 recorded the readout's fourth feature as a constant zero, and the fix
attempted after it was also wrong: it took the rank of the argmax token, which is zero by definition. Every number in
F73 through this entry rests on **three** live features. The correct fourth feature is the rank of the best answer-letter
token — how far down the distribution the most likely letter sits — which is meaningful and is not what was computed.

## F82 — The fourth feature took three attempts, and the failure that took the engine down was the good one

**Where it bit.** F75 recorded that the readout's fourth feature was a constant zero. The fix after it was also wrong,
and F81 recorded that too: it took the rank of the **argmax** token, which is zero by definition because nothing outranks
a maximum. The third attempt is the rank of the most likely **answer letter** — how far down the distribution the best of
A through J sits — which is near the top when the model is about to answer and far down when it is still writing prose.
That is a property of the readout the other three features do not carry, and it is now live: values around 10.1 to 11.5
with a standard deviation of 0.571 across items, where it had been exactly 0.0000.

**Three attempts at one four-line function, and the three failures are three different kinds.**

| attempt | what it did | how it failed | how it was caught |
|---|---|---|---|
| 1 | left `rank = zeros_like(...)` as a placeholder and never returned to it | silently constant | a correlation returned `nan` |
| 2 | ranked the argmax token | **zero by definition** — mathematically guaranteed wrong | the standard deviation was still 0.0000 in the next run |
| 3 | ranks the best answer letter | live | the standard deviation is 0.571 |

**The third failure mode is the one worth recording.** Referencing `LETTERS` before it was defined took the engine down
at start-up with a `NameError`, costing one nine-minute launch. That is the **best** of the three failures: it produced no
number at all. Attempts 1 and 2 each produced a full run of numbers that looked fine, went into two ledger entries, and
were wrong in a way only a summary statistic could reveal. **A failure that stops the run is cheaper than a failure that
completes it**, and the ordering of those costs is the argument for computing a standard deviation over every feature
before trusting a fit — which is now what the harness does.

**What is running.** The deciding measurement F81 named, with a finer budget grid: **14 budgets — 0, 12, 24, 36, 48, 64,
96, 128, 192, 256, 384, 512, 768, 1024 — dense below 256 where the harm signal showed its first movement.** Only a third
of the pooled instances previously had three consecutive differences available, because a probe at a low budget has few
budgets beneath it. Adding budgets costs nothing in generation: the trace is produced once at the cap and each budget is a
forward pass over its prefix. 419 items, and every number from F73 onward will be recomputable with four live features
rather than three.

**What that measurement decides.** F81 left harm at +0.0228 [−0.0027, +0.0491] over the budgets-alone control with the
trajectory included, and help at +0.0179 [+0.0106, +0.0256] — one missing the registered floor by its interval and the
other by its magnitude. The denser grid roughly triples the instances that have a usable history and adds a fourth live
feature, so both should move. If harm stays at chance with that, the reading offered in F79 and F80 — that harm is a
property of the trajectory — will have been given its best shot and failed it.

## F83 — Removing instances where extension cannot change anything turns both directions into a PASS, and the ordering of that decision matters

**Where it bit.** A trace that ended at 200 tokens returns the same answer at every budget above 200. So for an
instance whose probe budget already exceeds the trace length, "extending fixes it" and "extending breaks it" are
**structurally zero** — not measured as zero, impossible. Pooling those in inflates the budget features, which partly
encode "this instance is already decided", and dilutes the readout, which is being asked to predict an outcome that
cannot occur.

Restricting to **live** instances — the trace still running at the probe budget — removes 306 of 14,812 instances, 2%:

| direction, level + history + budgets | all instances | **live instances only** |
|---|---|---|
| **HARM** | 0.5466, **+0.0228 [−0.0019, +0.0500] FAIL** | **0.5541, +0.0272 [+0.0029, +0.0503] PASS** |
| **HELP** | 0.6889, **+0.0179 [+0.0108, +0.0261] FAIL** | **0.6962, +0.0208 [+0.0140, +0.0285] PASS** |

**Both clear the registered floor with intervals above zero, and the harm direction passes for the first time.** A 2%
removal moving a result that much is not surprising once the removed instances are described: their labels are
guaranteed zero, so in the fit they were pure noise.

**And the ordering of this decision is a problem I am not going to write around.** The restriction was applied **after**
seeing the earlier FAIL. That is the shape of a post-hoc analysis choice, and this ledger has fifteen withdrawals in it
precisely because results that arrive that way are unreliable. Two things can be said in its defence and neither is
sufficient:

- the restriction follows from a **structural** argument about what extension can do, not from inspecting the outcome;
- it is the same restriction anyone would impose having thought about it first.

Neither changes the fact that I did not think about it first. So the finding is recorded as **provisional**, and the
proper test is stated now rather than later.

**Pre-registered here, before the data exists.** A run with **14 budgets — 0, 12, 24, 36, 48, 64, 96, 128, 192, 256,
384, 512, 768, 1024 — over 419 items** is in flight and will finish with **four** live readout features rather than
three (F82). On that data, before any of it is inspected:

1. the analysis is **live instances only**, by the definition above, with no unrestricted variant reported as the
   headline;
2. the quantity is held-out AUC for harm and for help, pooled over budget pairs, **split by item**;
3. the controls are budgets alone and a shuffled-label fit, and the comparison is against **whichever is stronger**;
4. the floor is **0.02 with the bootstrap interval above zero**, unchanged;
5. **PASS on harm at that floor confirms this entry. FAIL withdraws it**, and the reading offered in F79 and F80 — that
   harm lives in the trajectory rather than the state — will have been given a dense grid, a fourth feature, and a
   correctly-restricted sample, and failed with all three.

**Why this is worth the ceremony.** Harm is the only direction that can buy accuracy (F78), the room for it is +3.8
points at the best operating point (F80), and every other feature family tried in this project has come back at chance.
A first PASS on it is either the most useful result here or an artefact of a choice made in the wrong order, and the
only thing that separates those is a test declared in advance.

## F84 — The pre-registered test passes: harm is predictable. Entropy carries it, the fourth feature contributes nothing, and help does not replicate

**Where it bit.** F83 found a first PASS on the harm direction after restricting to instances where extension can change
the answer, flagged that the restriction was applied **after** seeing a failure, and pre-registered five conditions for a
test on data that did not yet exist. That data exists now: **410 items, 14 budgets, four live readout features, 36,266
live instances, 1,594 harm cases with 683 in calibration.**

**The registered test, exactly as declared:**

| direction | features | AUC | difference over the stronger control | verdict |
|---|---|---|---|---|
| **HARM** | **level + budgets** | **0.5531** | **+0.0392 [+0.0295, +0.0493]** | **PASS** |
| **HARM** | level + history + budgets | 0.5475 | +0.0336 [+0.0216, +0.0455] | **PASS** |
| HELP | level + budgets | 0.6738 | +0.0115 [+0.0068, +0.0161] | FAIL |
| HELP | level + history + budgets | 0.6747 | +0.0124 [+0.0068, +0.0176] | FAIL |

**Harm passes on independent data, by a wider margin than the provisional finding (+0.0392 against +0.0272), with 683
calibration positives.** F83's provisional result on harm is confirmed. Its result on help is **not**: help fell from
+0.0208 to +0.0115 and now misses the floor, so that half of F83 is withdrawn.

**Three things I predicted about the mechanism, and two were wrong.** These are diagnostics, run after the registered
test, and are labelled exploratory:

| leave one feature out | AUC | change |
|---|---|---|
| **without entropy** | 0.5214 | **−0.0317** |
| without maximum probability | 0.5465 | −0.0066 |
| without verbaliser log-odds | 0.5469 | −0.0062 |
| **without the fourth feature** | 0.5563 | **+0.0032** |
| **without `log extend`** | **0.5810** | **+0.0279** |
| budgets alone, for reference | 0.5139 | |

- **Wrong: I attributed the change from F83 to the newly-live fourth feature.** Removing it *improves* the fit by
  +0.0032 — it contributes nothing. Whatever moved the result between F83 and here is the denser grid and the larger
  sample, not the feature I had just spent three attempts fixing.
- **Wrong: I expected the trajectory to be the carrier**, on the structural argument in F79 and F80 that harm is a
  property of where the reasoning is going. With four features and a dense grid the **level** passes at +0.0392 and
  adding history *lowers* it to +0.0336. The structural argument was appealing and the data does not need it.
- **Right, and it is the same feature as before: entropy carries harm**, the largest leave-one-out drop by a factor of
  five. Entropy also carries the help direction (F76, coefficient +0.186). **One quantity, both directions** — a readout
  still spread out means both that continuing can help and that continuing can hurt, which is what "unsettled" ought to
  mean and is a tidier story than two separate signals.

**One diagnostic that is not a result and must not be read as one.** Dropping `log extend` from the full model raises the
AUC to **0.5810**, +0.0671 over budgets alone. That is a feature dropped after inspecting leave-one-out, so it is
exploratory; the registered number is +0.0392. It does say something worth following up: a budget feature is actively
misleading the fit, which usually means collinearity with what the readout already encodes.

**And the honest size of it.** An AUC of 0.5531 is statistically solid at this sample and **weak as a predictor**. F78
established that the accuracy available from avoiding harm is +3.8 points at the best operating point, and a 0.55-AUC
selector will capture a small fraction of that. **Confirming that harm is predictable is not the same as showing a gate
that earns accuracy**, and the next thing owed is the policy table for the harm direction — what a threshold on it
actually earns after paying the probe — which is the same discipline F77 applied to the help direction and which turned
an AUC into a 0.007-point ceiling.

## F85 — The harm predictor is worthless as a policy, and the reason is a base-rate ratio that any such gate must beat

**Where it bit.** F84 confirmed harm is predictable at AUC 0.5531 on pre-registered data and said plainly that this is
not the same as a gate that earns accuracy, citing F77 — where an AUC on the help direction became a 0.007-point ceiling
once turned into a policy. The policy table for harm is what was owed.

The policy: extend everything **except** the items the harm predictor flags, since declining is the only way a selector
can earn accuracy (F78). The predictor is the one F84 fitted, on calibration, pooled over live instances, applied per
pair on the test fold. 22,313 test instances across the pairs with enough data:

| policy | accuracy | against always-extend |
|---|---|---|
| always extend | 0.6409 | — |
| decline 2% | 0.6390 | **−0.0020** |
| decline 5% | 0.6385 | −0.0024 |
| decline 10% | 0.6318 | −0.0091 |
| decline 20% | 0.6199 | −0.0210 |
| **oracle** | **0.6818** | **+0.0408** |

**The ceiling is +4.1 accuracy points and the fitted predictor is negative at every decline rate.** Declining costs
tokens nothing — it spends less, not more — so this is not an exchange where accuracy was traded for cost. The gate is
simply worse than not having it.

**The reason is arithmetic and it generalises past this predictor.** An item declined is one of three things: it would
have been **broken** by extension, in which case declining gains a point; it would have been **fixed**, in which case
declining loses one; or extension would have changed nothing, in which case declining is free. So a harm-avoidance gate
breaks even only when, among the items it declines, **harm cases outnumber help cases**. The base rates here are
**harm 4.4% against help 14.1%** — a **3.2 : 1 disadvantage** the predictor must invert before its first point of gain.
An AUC of 0.5531 concentrates harm cases in its top slice by nowhere near a factor of 3.2, so every item it declines is
in expectation a loss.

**This is the condition any such gate has to state, and none of the entries above stated it.** The whole framing of
"predict harm, decline those items" was pursued from F78 onward on the strength of the oracle's room, and the room is
real — +4.1 points — but the entry price is not an AUC above chance, it is **a precision on harm that beats the local
help-to-harm ratio.** Writing that down turns a search for a better signal into a check that can be run before the search:
measure the ratio, divide, and see what precision is required. Here it would have said 3.2:1 from the first day, and
nothing this project has produced comes close.

**Where this leaves the thinking-budget line, and it is a clean close.**

| claim | status |
|---|---|
| thinking is worth +20.6 accuracy points at 170x the tokens | measured (F73) |
| the readout after a short think orders items by whether continuing helps, AUC 0.6803 | measured (F76, F80) |
| that ordering buys a **token saving**: 32% fewer for 0.6 points | measured (F80) |
| accuracy requires declining items extension would break | structural (F78) |
| harm is predictable at AUC 0.5531 | measured, pre-registered (F84) |
| **a harm-avoidance policy loses accuracy at every rate** | **measured (this entry)** |
| the entry price for such a policy is precision beating a 3.2 : 1 base-rate ratio | **derived (this entry)** |

**So the deployable result of the whole thinking line is the token saving**, and the accuracy story is closed with a
number that says why: not a weak signal, but a threshold that a weak signal cannot clear and that was never computed
until now.

## F86 — Two corrections: the readout's value was mis-stated, and on one cost axis the gate is dominated everywhere

**Two things in this ledger were framed wrongly, both pointed out rather than discovered.**

### Correction 1: judging difficulty without generating is the claim, and it holds

Entries from F67 onward summarised the readout's value as "it loses to a plain logit lens, which loses to counting
characters", and concluded the internals were unnecessary. That conflated **two different targets**, and the readout wins
on one of them:

| target | J-lens | logit lens | random J | verdict |
|---|---|---|---|---|
| **difficulty** — will the cheap path be wrong | **0.7626** | 0.6729 | 0.6797 | **J-lens beats both controls** |
| the stage-1 gate in the deployment condition | **0.8571** | 0.7744 | 0.8007 | beats the box's own 0.7853 |
| **uplift** — will a longer path fix it | 0.6497 | 0.6930 | — | J-lens loses |

**For judging difficulty at prefill, with nothing generated, the J-lens readout is the best instrument measured here.**
The prefill happens anyway, so the reading costs nothing. What failed was **using difficulty to decide escalation**,
because uplift is a different quantity — and that is a failure of the *use*, not of the instrument. Writing "the readout
is unnecessary" was a summary of the wrong target, and the surface-count comparisons in F69 and F70 were all on uplift.

### Correction 2: accuracy and tokens were reported as a pair, and a pair cannot be ranked

Every policy above was given two numbers and compared against its neighbour. Combining them the way the processor world
combines energy and delay makes the comparison total: **cost per query = tokens + λ · (1 − accuracy)**, where λ is the
number of tokens one avoided error is worth. A product form is degenerate here because a policy can spend zero tokens; the
weighted sum has no such hole and λ is a quantity a deployment can state.

| policy | accuracy | tokens |
|---|---|---|
| answer immediately | 0.5178 | 0 |
| think 64, then answer | 0.5138 | 64 |
| **think 256 always** | **0.6561** | 256 |
| **think 1024 always** | **0.7391** | 1024 |
| gate: probe 64, extend 45% | 0.5771 | 151 |

Sweeping λ from 1 to 100,000 gives **two boundaries and three regimes**:

| λ (tokens per avoided error) | the winning policy |
|---|---|
| below **1,850** | **answer immediately** |
| 1,850 to **9,253** | **think 256 always** |
| above 9,253 | **think 1024 always** |

**The gate never wins, at any λ.** It is dominated everywhere, and the reason is visible in the table: at 45% coverage it
spends 151 tokens for 0.5771, while thinking 256 always spends 105 more tokens and buys **7.9 accuracy points** — a far
better rate than the gate's own trade. The gate occupies a bad middle.

**So F77's and F80's "32% fewer tokens for 0.6 accuracy points" was a comparison against one neighbour, not against the
policy set.** That framing made a dominated policy look like a favourable trade, and the single axis is what exposes it.
The lesson is not about this gate: **a policy reported as a pair of numbers has not been compared to anything, and the
comparison it needs is total, not local.**

**And λ ≈ 1,850 is a number a deployment can act on.** At an output price of one dollar per million tokens, 1,850 tokens is
**$0.0019**, so: **if one avoided error is worth more than a fifth of a cent, think; otherwise do not.** No gate, no
readout, no probe. That is the deployable result of the thinking line, and it is simpler than anything the previous nine
entries proposed.

**What survives of the internal readout, stated against the corrected target.** Judging *difficulty* before generating,
where the J-lens beats a logit lens by 0.0897 and a random Jacobian by 0.0829 — a measurement that stands (F48, F51) and
that costs nothing because the prefill is paid regardless. What does not survive is any policy built on top of it that
has been checked on a single cost axis, because none of them has been, and the one checked here is dominated.

## F87 — The combination works, in a band: deciding think-or-not from the prompt wins where the mid-generation gate lost

**Where it bit.** The two pieces had been measured on different models and never together: a readout at the prompt that
says whether the cheap path will be wrong, and a workload-level number that says whether a reasoning budget is worth its
tokens. This runs them as one policy on **410 items of one model** — read the prompt, decide per item whether to think,
spend nothing on the decision because the prefill is paid regardless.

Base facts: no thinking **0.5317**, full thinking **0.7415**, thinking **fixes 107 items and breaks 21**, and costs a
mean of **696 tokens**.

| policy | accuracy | tokens | against random selection at the same rate |
|---|---|---|---|
| never think | 0.5178 | 0 | — |
| readout picks 17% | 0.5810 | 107 | ties the 97.5th percentile — does not beat |
| **readout picks 28%** | **0.6126** | 185 | 0.5805 mean, 0.6087 ceiling — **beats** |
| **readout picks 48%** | **0.6601** | 330 | 0.6251 mean, 0.6561 ceiling — **beats** |
| readout picks 70% | 0.6680 | 489 | does not beat |
| always think | 0.7391 | 682 | — |

On the single cost axis — `tokens + λ · (1 − accuracy)`, λ in tokens per avoided error — the regimes are:

| λ | winner |
|---|---|
| below **1,691** | never think |
| **1,691 – 2,466** | **readout picks 17%** |
| **2,466 – 3,053** | **readout picks 28%** |
| **3,053 – 4,460** | **readout picks 48%** |
| above **4,460** | always think |

**The readout policy wins in a band roughly 2.6× wide in λ, and the saving at its best is about 8% of total cost** — at
λ = 3,000 it costs 1,347 against 1,447 for never thinking and 1,465 for always thinking. Outside the band it wins
nothing, and the honest form of the result is the band together with its width, because a deployment whose λ sits outside
it should use neither the readout nor a gate.

**And this is the exact opposite of F86, for a reason that is the whole point.** F86 gated a *mid-generation* decision —
after 64 tokens of thinking, extend to 256 or not — and found it dominated at every λ. Here the decision is made *at the
prompt*, before any token exists. Same model, same readout features, same cost axis, opposite verdicts:

| where the decision is made | result |
|---|---|
| after generation has started | **dominated at every λ** (F86) |
| **before generation starts** | **wins in a band** (this entry) |

So the value of the readout is specifically that it is available **before generating**, and that is not a framing
preference — it is the difference between a policy that wins somewhere and one that wins nowhere. Every entry from F76 to
F86 was measuring the mid-generation version, which is why they accumulated negatives.

**What is still not shown.** The band's location is a property of this model and this item set; another deployment
re-measures λ and finds its own boundaries. The readout used here is the plain next-token readout, not the J-lens, so
whether the Jacobian widens the band is untested — F48 measured the J-lens ahead on the difficulty target by 0.0897, and
this policy is fitted on "thinking will fix it", which is closer to uplift. Testing the J-lens in this policy is the
obvious next measurement and it needs only the Jacobian for this model, which does not exist yet.

## F88 — Comparing two runs on different subsets nearly produced a verdict, and the fix belongs in the harness

**Where it bit.** F87 left one measurement outstanding: the readout it used was the plain next-token one, and the
Jacobian lens had been measured ahead of that on the difficulty target by 0.0897 (F48). So a Jacobian was built for the
model the thinking work used, its digest checked against the served weights, and a second budget run started with the
readout passing through it. The comparison was to be **band width** and **best saving** — the two things a deployment can
act on — with the criterion registered before the data existed: the Jacobian improves the result only if it widens the
band or raises the saving.

**And the first comparison compared 410 items against 90.** The Jacobian run was a fifth of the way through, and the
analysis happily reported:

| | plain | Jacobian |
|---|---|---|
| band width | 2.64× | 3.92× |
| best saving | 7.9% | 4.9% |
| verdict | | **IMPROVES** |

The base rates give it away: the plain run's items answered 0.5178 without thinking, the Jacobian run's 0.4340. **Those
are different item sets, not different readouts.** Restricting the plain run to the same 90 items collapses its numbers to
a band of **1.52×** and a saving of **1.0%** — so 2.64× and 7.9% were properties of the 410-item sample, and the "IMPROVES"
verdict was comparing subsets.

**The fix is in the harness rather than in my attention.** The comparison now **intersects on question id** before
analysing either arm, and **withholds the verdict below 150 shared items** rather than printing one. Both are one-line
changes, and the reason they belong in code is that this failure has a shape: two runs of the same script on the same
model differ only in the thing under test *until one of them is unfinished*, and an unfinished run looks exactly like a
finished one to an analysis that does not check.

**This is the second time in this ledger that a comparison was invalid because the arms did different work**, and the
first was the same shape: F65's throughput comparison put a gate that escalated 27 of 48 requests against one that
escalated none, and the escalating arm looked 31% faster because it decoded less. Both were caught, both by asking what
else differs between the arms — which is the only question that finds this class, and which is now asked by the code in
one of the two places.

**The measurement itself is still running** and its verdict is registered and unchanged. What is recorded here is the
near-miss, because a near-miss caught by a base-rate check is the cheapest kind of evidence that the checks are worth
running, and because the corrected numbers on 90 shared items say something on their own: **the band and the saving are
sample-dependent at this size**, which means F87's 2.64× and 7.9% need the same treatment when the run finishes — quoted
against the same items or not quoted at all.

## F89 — The Jacobian doubles the band and raises the saving: reading through it before generating is the deployable result

**Where it bit.** F87 measured the policy the whole line had been looking for — read the prompt, decide per item whether
to spend a reasoning budget, pay nothing for the decision because the prefill is paid regardless — and found it wins on
a single cost axis in a band of λ. But the readout it used was the **plain next-token** one, while F48 had measured the
**Jacobian lens** ahead of that on the difficulty target by 0.0897. So a Jacobian was built for this model at its own
amplitude, its digest checked against the served weights, and the same 419 items rerun with the readout passing through
it. The criterion was registered before the data existed: the Jacobian counts only if it **widens the band** or **raises
the best saving**.

Both arms on the **same 410 items**, with identical base rates confirming it — no thinking **0.5178**, full thinking
**0.7391**, **682** tokens — so the readout is the only thing that differs:

| | plain next-token readout | **readout through the Jacobian** |
|---|---|---|
| **band width in λ** | 2.64× (1,713 – 4,519) | **5.28× (1,817 – 9,591)** |
| **best saving** | 7.9% | **10.0%** |
| verdict | | **PASS on both** |

**The policy table shows where it comes from:**

| readout | coverage | accuracy | tokens |
|---|---|---|---|
| plain | 70% | 0.6680 | 489 |
| **Jacobian** | **65%** | **0.7154** | **459** |
| always think | 100% | 0.7391 | 682 |

**The Jacobian gate reaches 0.7154 on 459 tokens where the plain readout's best was 0.6680 on 489** — 4.7 accuracy points
higher at slightly fewer tokens, and within 2.4 points of thinking on everything at **two thirds of the tokens**.

**What this settles about the whole line.** The value of the Jacobian readout is what the user stated in two sentences
and what nine entries of mine had obscured: **it tells you, before a single token is generated, whether the cheap path
will do.** Measured against the plain readout on the one axis a deployment can act on, it **doubles the range of
exchange rates where the decision is worth making** and raises the best saving by a fifth. Every negative in F67 through
F86 was measuring either the wrong target (uplift rather than difficulty) or the wrong decision point (mid-generation
rather than pre-generation), and neither error touches this measurement.

**What is not established.** Both figures are point estimates from one run of one model on one item set with one fold
split; there is no interval on the band width or the saving, and producing one means repeating the pair of runs rather
than resampling within them. The band's **location** is a property of the workload — a deployment measures its own λ and
finds its own boundaries — and only the *shape* of the result transfers: that a Jacobian readout at the prompt beats a
plain one, and that both beat having no gate somewhere in the middle of the λ range.

**And the practical statement, in the form the ledger's summary already uses.** Read the prompt through the Jacobian.
Send the items it marks easy straight to the cheap path. Spend the reasoning budget on the rest. That is worth **10% of
total cost** at the best exchange rate on this workload, over a **5.3-fold range** of exchange rates, and it costs nothing
to decide.

## F90 — F89 is substantially withdrawn: the Jacobian's advantage does not survive an interval, and neither does the gate's own value

**Where it bit.** F89 reported that the Jacobian readout widens the band from 2.64× to 5.28× and raises the best saving
from 7.9% to 10.0%, and called it a PASS on both pre-registered criteria. It also said producing an interval "means
repeating the pair of runs". **That was wrong, and the correction is what undid the result.** Decoding is greedy, so
repeating a run on the same items reproduces the same traces and the same numbers exactly. The only randomness is which
items were drawn, so the interval comes from **resampling items** — and it costs nothing, which is why there was no
excuse for not having it.

Each replicate draws items with replacement, **refits the threshold on the replicate's own calibration half**, and
recomputes both quantities. Both readouts see the same resampled items, so the difference is paired.

**With coverage fixed at 0.5 in advance — the version with no selection over coverages:**

| quantity | 2.5% | median | 97.5% |
|---|---|---|---|
| plain band width | 1.00 | 1.56 | 4.33 |
| Jacobian band width | 1.00 | 1.99 | 6.17 |
| plain best saving | **0.0%** | 5.2% | 15.0% |
| Jacobian best saving | **0.0%** | 7.7% | 15.4% |
| **Jacobian − plain, band width** | | **+0.38** | **95% [−1.98, +4.24] — includes zero** |
| **Jacobian − plain, saving** | | **+2.5%** | **95% [−8.7%, +12.2%] — includes zero** |

Taking the maximum over seven coverages, as F89 did, gives differences of +1.56 and +2.7% and **both intervals still
include zero**.

**Three things follow and all three cost something.**

**F89's verdict is withdrawn.** The point estimates favour the Jacobian and the intervals do not exclude zero by a wide
margin. The registered criterion was met by the point estimates and the criterion did not require an interval — that was
my omission in writing it, not a loophole, and the fix is that a criterion on a difference now requires an interval.

**The gate's own value is uncertain, not just the Jacobian's advantage.** The saving's 2.5th percentile is **0.0% for
both arms**: there are item samples in which the gate wins nothing at any λ. So F87's 7.9% and this entry's 9.9% are
medians of a distribution whose lower tail touches zero, and the honest statement of the deployable result is
**"plausibly 5 to 8 percent, possibly nothing"** rather than a number.

**And "band width" is not usable as a headline statistic.** Its 97.5th percentile reaches **143×** under the
maximum-over-coverages arm, because it is a ratio of the extremes of a bootstrapped region and both extremes move. A
quantity whose interval spans two orders of magnitude cannot carry a comparison, and I chose it because it sounded like
what a deployment cares about rather than because it was stable. The saving is the better statistic of the two and even
it has a lower bound of zero.

**What would settle it.** More items, and the arithmetic is unforgiving: at 410 items the interval on the saving spans 15
points, and halving an interval takes four times the data. **1,640 items per arm is roughly 14 GPU-hours per arm** at the
current rate, for a pair. That is the price of turning "plausibly 5 to 8 percent" into a number, and it is worth stating
before spending it rather than after.

**What survives untouched.** Everything measured without a difference-of-differences: thinking is worth +22 accuracy
points at 170× the tokens (F73); the readout at the prompt orders items by whether thinking will fix them and beats
random selection at the same coverage (F87, where the comparison is against a control on the same items rather than
against another readout); and the decision belongs before generation rather than during it (F86 against F87), which is a
comparison of two verdicts of opposite sign rather than of two point estimates.

## F91 — A statistics review found five defects; fixing them tests the band's existence for the first time, and it passes

**Where it bit.** A review of the central result named five defects. All five are fixed here, and the most important
was a genuine bug rather than a matter of taste.

| defect | what it was | fix |
|---|---|---|
| **1** | the coverage was chosen **on the test fold** — seven options, cheapest picked at every λ | the λ → coverage mapping is decided on **calibration alone** and the test fold is scored once with it frozen |
| **2** | **the band's existence was never tested.** At the indifference λ the two trivial policies cost the same, so any curvature in the readout — including noise — wins near it. The null is not "no band" | a **permutation test**: shuffle the readout across items, rerun the whole pipeline, build a null distribution |
| 3 | the saving was a **maximum over λ**, a winner's curse whose bias differs between arms | the saving is reported at a **pre-specified** λ*, the indifference point computed from the calibration fold |
| 4 | replicates with no band were hidden inside a percentile | the empty-band fraction is a primary number (it is **0/150** for both arms) |
| 5 | the bootstrap was iid over items that come in **seven subject clusters** | stratified by category, plus leave-one-category-out |

**The permutation test is the first real test of whether the readout does anything, and it passes.**

| arm | observed saving at λ* | null median | p |
|---|---|---|---|
| plain | 3.3% | **−5.0%** | **0.027** |
| **Jacobian** | **8.1%** | −5.2% | **0.000** |

A shuffled readout **loses 5%** on average — it spends the probe and selects badly — so the null is not zero, which is
exactly the reviewer's point. Against that null both arms are significant. The band *width* is not: p = 0.640 for plain
and 0.067 for the Jacobian.

**And a second test disagrees, which is informative rather than awkward.** The category-stratified bootstrap, with the
threshold refitted in each replicate:

| quantity | 2.5% | median | 97.5% |
|---|---|---|---|
| plain saving at λ* | −24.2% | **−0.8%** | +10.8% |
| Jacobian saving at λ* | −20.7% | **+2.6%** | +15.4% |
| Jacobian − plain | | +3.6% | [−10.6%, +19.8%] — includes zero |

**The two tests ask different questions and both answers are needed.** The permutation asks *does the readout beat a
random ordering of these items* — signal. The bootstrap asks *would this number hold on another draw of items* —
generalisation. So: **the signal is real and its size does not generalise at n = 410.** F90 withdrew the result
wholesale on the bootstrap alone; that was half the picture.

**Leave-one-category-out is where the arms genuinely separate, and it does not depend on comparing point estimates.**

| category removed | plain | Jacobian |
|---|---|---|
| **math** | **−18.9%** | **+4.2%** |
| economics | −2.2% | +0.1% |
| law | −2.0% | +3.6% |
| the other four | +2.3% to +5.3% | +5.6% to +7.6% |

**The plain readout's benefit collapses without mathematics.** The Jacobian's survives every removal, ranging from
+0.1% to +7.6%. That is the strongest available argument for the Jacobian and it is structural: a benefit that depends on
one subject being present is not a benefit a deployment can rely on, and the review's Simpson warning was right to ask.

**Where this leaves the central claim.** Reading the prompt through the Jacobian and deciding whether to spend a
reasoning budget **carries real signal** (permutation p = 0.000, against a null that loses 5%), **is robust to removing
any one subject** (+0.1% to +7.6%), and has a **benefit whose size is not yet pinned down** (bootstrap median +2.6%,
interval −20.7% to +15.4%). The plain readout carries signal too (p = 0.027) and is not robust. Everything about "how
much" needs four times the items, and everything about "whether" is now tested.

**Two lessons about instruments, both from the reviewer.** A criterion on a difference must require an interval, or a
point estimate satisfies it — F89 was registered without one and that was my omission. And **a quantity chosen because
it sounds like what a deployment cares about is not therefore measurable**: band width spans 2.1 to 130 across
replicates, and I made it a headline before checking whether it was stable.

## F92 — The base-rate condition is a known likelihood-ratio result, I stated it wrongly, and the theory names the experiment I had not run

**Where it bit.** A theoretical review was asked to check the paper's formalism against the measurements and to say what
follows. Four corrections and one experiment came back. The experiment is the valuable part, and it explains an empirical
failure that had been recorded three times without a mechanism.

### The condition I derived is standard, and my wording of it was wrong

F85 derived that a policy declining to extend helps only when harm cases outnumber help cases among the declined, and
said the predictor must "invert a 3.2 : 1 base-rate disadvantage" — phrased as a **precision** requirement. The correct
general form is a **likelihood ratio**. With `π(X) ∈ {0,1}` the decision to spend the budget, the rejection set
`S = {π = 0}`, and potential outcomes `Y(0), Y(1)`:

    V(π) − V(π_all) = Pr(S, H) − Pr(S, B)     where H = {Y(0)=1, Y(1)=0}, B = {Y(0)=0, Y(1)=1}

so the rejection set helps **iff** `Pr(H|S) > Pr(B|S)`, which by Bayes is

    **Pr(S | H) / Pr(S | B)  >  Pr(B) / Pr(H)**

**So the requirement is on the rejection RATES, not on precision.** The correct statement of my own number: the rule must
**reject harmful items at more than 3.2× the rate at which it mistakenly rejects beneficial ones.** Precision over the
whole population is not the quantity — with a large no-change group, accuracy can be made arbitrarily high while the
condition fails.

**And with cost included it is the textbook individualized treatment rule**: spending is optimal iff
`τ(X) = E[Y(1) − Y(0) | X] > c(X)`. My λ sweep is that rule with `c` expressed in tokens, which means the whole cost-axis
analysis has a name and a literature: **Manski (2004), *Statistical Treatment Rules for Heterogeneous Populations*,
Econometrica; Qian & Murphy (2011), Annals of Statistics; Zhao et al. (2012), *Outcome Weighted Learning*, JASA;
Kitagawa & Tetenov (2018), *Who Should Be Treated? Empirical Welfare Maximization*, Econometrica; Athey & Wager (2021),
Econometrica; Frangakis & Rubin (2002), *Principal Stratification*, Biometrics.**

**One observation from the review that changes what my statistical problem is.** Because both paths are run
deterministically on the same items, **both potential outcomes are directly observed** — so partial identification, the
usual obstacle in this literature, is not my problem. What is left is generalisation to a new prompt population, which is
precisely what F90 and F91 found to be unresolved. The framework says my difficulty is the ordinary one and not the deep
one.

### Three corrections to how I described the mechanism

- **My linear-closure argument was right in outcome and wrong in wording.** I wrote that only a nonlinear readout "can
  say something new". The sharper statement: `J` is a deterministic function of `h`, so it **adds no information at all**;
  what it changes is *readability* under a particular nonlinear inductive bias. "New information" was never available to
  it.
- **High entropy is not a measurement of "the internal state is unsettled".** Writing `N` for the RMSNorm with gain
  `D_g`, the J-lens logits are `z_J(h) = W_U N(Jh) ≈ √d · W_U D_g · Jh/‖Jh‖`, so the margin between tokens `i` and `j` is
  `√d (w_i − w_j)ᵀ D_g (Jh/‖Jh‖)`. **What `J` changes is the direction** `h/‖h‖ → Jh/‖Jh‖`, and entropy aggregates that
  direction's alignment with the vocabulary difference directions `D_g(w_i − w_j)`. So high entropy means **the direction
  predicted to reach the output has not yet produced a vocabulary margin** — a statement about the predicted endpoint,
  not about deliberation.
- **The rank-448 truncation has no general sign on entropy.** I had assumed it would bias one way; it does not, and
  deciding needs a rank sweep and several independent random sketches.

### The experiment the theory names, and why it explains a three-times-repeated failure

**Difficulty is a property of `Y(0)`. Uplift is `Y(1) − Y(0)`.** The Jacobian I built is `J^(0)` — the sensitivity of the
**short** path's endpoint. It cannot identify a difference involving the long path's endpoint, and that is not a weakness
of the estimate but a statement about what it is. F67, F68 and F84 each recorded that the readout predicts difficulty and
not uplift; none of them had this reason.

So: build **two** Jacobians from the same pre-generation state, one per continuation protocol —
`J^(0)` under the direct-answer template and `J^(1)` under the thinking-enabled template — and score with

    s(h) = H(P_0(h)) − H(P_1(h))     where P_a(h) = softmax(W_U N(J^(a) h))

**the entropy drop the long path is predicted to produce.** That targets `Y(1) − Y(0)` directly instead of `Y(0)`, and it
is available before a token is generated, which is the property the whole line rests on. Fixing the score in advance
matters — the review offered Jensen-Shannon divergence and margin change as alternatives, and choosing among them after
seeing results is the selection failure this ledger has recorded twice.

## F93 — Reported as a cost-effectiveness frontier: the numbers reconcile, the unit joins the two analyses, and the selector closes 12 to 57 percent of the available gap

**Where it bit.** Two reviews converged on the reporting rather than the result. A band width in λ is a geometric
summary nobody deploys against; a percentage saving hides its denominator; and one review found that **my integers and my
accuracies did not reconcile**. All three are fixed here, and one of them was a real error.

### The error: counts from the whole sample, rates from the test fold

I had written "thinking fixes 107 and breaks 21" beside "0.5178 → 0.7391". Those come from different denominators —
107 and 21 are over all 410 items, the accuracies are the test fold's 253. Reported on one fold:

| set | n | answer directly | think fully | fixes | breaks | net |
|---|---|---|---|---|---|---|
| all items | 410 | 218/410 = 0.5317 | 304/410 = 0.7415 | 107 | 21 | 86 = +0.2098 |
| **test** | **253** | **131/253 = 0.5178** | **187/253 = 0.7391** | **68** | **12** | **56 = +0.2213** |

On the test fold alone the counts and the rate agree: 56/253 = +0.2213. **Every accuracy in this entry is an integer over
253.**

A second objection did not hold: the cost was said to use the median 682 tokens. The code multiplies **per-item** tokens
by the selection mask, so the expected cost is a per-item mean; it was my prose that quoted a median as if it were the
cost. Two related facts from checking it: trace length correlates **+0.1987** with the direct path being wrong, and only
**−0.0557** with thinking fixing the item — **hard items do have long traces, and the items thinking repairs are not the
long ones.**

### The frontier, and a unit error in my first version of it

The standard object is incremental cost against incremental effect, dominated points removed, with the ratio between
adjacent efficient points. My first version divided **per-item** tokens by a **count** of extra correct answers, which is
not a unit of anything. Corrected, the ratio is total tokens per additional correct answer — **and that is the same unit
as the exchange rate λ**, which is how the frontier and the λ sweep turn out to be one statement.

| from → to | extra tokens per item | extra correct | **tokens per additional correct answer** |
|---|---|---|---|
| answer directly → think 9% | 63.9 | 7 | 2,356 |
| 9% → 16% | 41.5 | 6 | 1,783 |
| **16% → 21%** | 39.2 | 8 | **1,265** — the cheapest step |
| 21% → 29% | 55.0 | 6 | 2,364 |
| 29% → 43% | 98.6 | 11 | 2,312 |
| **43% → 52%** | 53.9 | 3 | **4,638** — the dearest step |
| 52% → 66% | 115.3 | 11 | 2,703 |
| 66% → 77% | 68.4 | 7 | 2,520 |

**A deployment reads this by comparing its own λ against the last column and stopping where the column exceeds it.** At
the λ* of 3,759 computed earlier, the step from 43% to 52% costs 4,638 and is refused, so the answer is **think for 43%
of items** — which the λ sweep and the frontier now agree on, because they are the same arithmetic in the same unit.

### The selector's quality, with no λ in it

| coverage | this policy | random at the same rate | oracle at the same rate | **share of the gap closed** |
|---|---|---|---|---|
| 9% | 0.5426 | 0.5346 | 0.6008 | 12.2% |
| 21% | 0.5969 | 0.5636 | 0.7287 | 20.2% |
| 43% | 0.6628 | 0.6127 | 0.7868 | 28.8% |
| **77%** | 0.7442 | 0.6888 | 0.7868 | **56.5%** |

**The selector closes 12% to 57% of the distance between random selection and perfect selection**, rising with coverage.
That is the cleanest single statement of how good the readout is: it is not near-perfect and it is far from useless, and
the number needs no exchange rate, no threshold and no band.

**What is still owed.** The frontier is a point estimate; F90 and F91 established that the size of the benefit does not
generalise at this sample, and nothing here changes that. And one review's larger objection stands unaddressed: **tokens
are a weak proxy for cost**. GPU-seconds, KV-cache occupancy and the effect of long traces on other requests under
continuous batching are the quantities a serving system feels, and a policy that looks good in tokens can lose in
GPU-seconds. Measuring that needs load, not more items.

## F94 — Reseeding the probe directions makes two Jacobians of the same object nearly orthogonal, and a reproducibility claim was mis-stated

**Where it bit.** The theory review proposed a contrastive score built from two Jacobians, one per continuation
protocol. Building them produced a small difference — cosine **0.9811**, relative Frobenius **0.2074** — so the control
question was whether that difference exceeds the estimator's own noise. The right control is **the same protocol with a
different probe-direction seed**, everything else held. The first theoretical review had named exactly this and I had not
run it.

| comparison | cosine | relative Frobenius |
|---|---|---|
| the two protocols, short template against long | **0.9811** | 0.2074 |
| **the same protocol, a different probe seed** | **0.0929** | **1.3508** |

**Two estimates of the same Jacobian, differing only in the random directions probed, are nearly orthogonal.** The
protocol difference is a sixth of the estimator's own variation, so a contrastive score built from these two is the
difference of two noisy views of one object, and the measurement the theory asked for cannot be made this way.

**Why, and it is not a bug.** The estimator is `J_hat = Y V⁺` with 384 random directions in a 4,096-dimensional space, so
`V` spans **9.4%** of the space and `J_hat` is `J` seen through that subspace. Two independent 384-dimensional random
subspaces overlap in almost nothing, so two estimates agree only on a small shared component. Both are valid partial
views; as matrices they are nearly orthogonal. **The construction was always a projection and I had been calling it an
estimate.**

**And a reproducibility claim in F47 was mis-stated.** That entry reported split-half element correlation 0.9612 and
relative Frobenius 0.3355 and concluded "J is stable". Those halves were **halves of the prompts, with the probe
directions held fixed**. The variance that matters — the directions — was never varied, and it is **six times larger**
than the one that was. The sentence should have read "the estimate is stable under resampling prompts", which is a much
smaller claim than the one made and than the one every later entry relied on.

**What this does and does not threaten.** It does **not** invalidate the measurements that used a Jacobian: a projection
of `J` can be a useful readout even if a different projection would also be, and F89 through F93 measured that the
readout works, against controls, on held-out items. What it does is make every one of those results a statement about
**one random projection** rather than about the Jacobian, and that is a materially weaker claim than the entries make.

**The decisive test is running.** Same model, same layer, same amplitude, same items, same everything — with the Jacobian
rebuilt from different probe directions. **If the headline result is a property of the model it survives; if it is a
property of one draw of `V` it does not.** No analysis can substitute for it, because the residuals were never stored and
the readout has to be recomputed inside the engine.

**The methodological lesson, which is the transferable part.** A reproducibility check is only as good as the source of
variation it varies. Mine varied the data and held the estimator's randomness fixed, which is the easier half and the
less important one — and the review that named it did so before any of this was measured. **When an estimator has its own
random ingredient, resampling the data measures the wrong thing.**

## F95 — F94's control was the wrong one: common random numbers cancel the variance it measured, and the whole forward-difference machinery is unnecessary

**Where it bit.** F94 compared the difference between two continuation protocols (relative Frobenius 0.2074) against the
variability of the estimator under a different probe seed (1.3508) and concluded the protocol difference was "within the
estimator's noise". A design review overturned that in one observation.

**The two protocols were built with the SAME random directions.** With common random numbers, the direction-derived
Monte-Carlo noise **cancels in the difference** `D = J^(1) − J^(0)`. So the variability of `J` alone across seeds is not
the variability that applies to `D`, and comparing them is comparing two different quantities. **F94's conclusion is
withdrawn.**

**The correct control, which is now specified rather than guessed.** For each of `K ≥ 5` seeds, build the pair
`(J^(0)_s, J^(1)_s)` with the **same** directions, form `D_s`, and ask whether the `D_s` agree with each other — high
cosine between differences means signal, scattered directions mean noise. Three statistics fixed in advance: the
Frobenius norm of `D`, its top singular value, and the held-out mean of the score `s(h)`.

**A second constraint that is larger than the first, and I had not registered it at all.** The Jacobians are built from
**eight prompts**. Whatever variance is tested against seeds, the quantity that decides generalisation is the **prompt
sample**, and significance against seed variance supports only "a difference on these eight prompts". The correct test is
a **paired sign-flip permutation over prompts** — compute `D_i` per prompt, enumerate all `2^8 = 256` sign assignments,
and take the fraction exceeding the observed statistic. Its minimum attainable p is 1/256 ≈ 0.004 and its power at
n = 8 is hopeless; 30 to 50 prompts is the fix. And **"not significant" is not "no difference"**: claiming the template
does not matter needs an equivalence test with a pre-justified margin (Lakens 2017, *Equivalence Tests: A Practical
Primer*).

**What survives from F94, because not all of it was wrong.** Two `J` estimates with different probe seeds *are* nearly
orthogonal (cosine 0.0929), the estimator *is* a projection onto a random 9.4% of the space rather than an estimate of
`J`, and F47's stability claim *was* mis-stated — it varied prompts with directions held fixed and reported the result as
"J is stable". Those stand. What does not stand is using the seed variance to dismiss a common-random-number paired
difference.

**And the review made the entire construction obsolete, which is the most useful thing in it.** The score's first-order
form needs not `J` but a **vector-Jacobian product**: for each condition, the gradient of the endpoint entropy with
respect to the layer-18 residual,

    g^(c)_t = ∇_{h_t} H(p_endpoint)        so        s(h) ≈ ⟨ g^(0) − g^(1), h ⟩

and **one backward pass gives every position `t` at once**. That replaces 384 forward-difference probes with **one forward
and one backward pass per prompt**, scales linearly in sequence length so the generated reasoning trace can be included —
which is exactly what F94 identified as missing from my `J^(1)` — and is the standard approximation known as
**attribution patching** (Nanda 2023; Kramár et al. 2024, *AtP\**).

**So three things change at once.** The comparison that produced F94 is void; the construction it was comparing is
unnecessary; and the replacement is cheaper by two orders of magnitude and can do the thing the original could not. The
budget run currently in flight — the reseeded-Jacobian replication of F89 — is still worth finishing, because whether the
headline survives a different random projection is a question about the results already published and does not depend on
which construction is used going forward.

## F96 — Two nearly-orthogonal projections of the Jacobian both beat the plain readout, so the benefit is not one lucky draw

**Where it bit.** F94 found that two Jacobian estimates built with different probe directions are nearly orthogonal as
matrices (cosine **0.0929**), which made every earlier result a statement about **one random 384-dimensional projection**
rather than about the Jacobian. F95 corrected how that finding should be used but left the threat standing: if the
benefit came from one lucky draw of the probe directions, it would not replicate. The replication ran with everything held
and only the directions reseeded.

**On the same 400 items, at the same pre-specified λ\* of 3,456, with the coverage mapping fixed on calibration and the
permutation null from F91:**

| readout | saving at λ* | null median | p |
|---|---|---|---|
| **plain, no Jacobian** | **4.16%** | −3.24% | **0.033** |
| **Jacobian, seed 0** (published) | **6.96%** | −3.36% | **0.000** |
| **Jacobian, seed 7** (reseeded) | **7.90%** | −3.47% | **0.000** |

**Both projections beat the plain readout and both are significant against the null.** The two Jacobians agree on almost
nothing as matrices and agree closely on the quantity a deployment reads — 6.96% against 7.90%, on either side of each
other rather than one being a fluke above the other.

**So the benefit is a property of passing through the Jacobian, not of a particular draw.** F94's worry is answered for
the deployable quantity. The explanation that fits: the readout's useful content is a **coarse** property of
`softmax(W_U N(Jh))` — its entropy — and two different random projections both destroy the fine structure while
preserving the coarse one. A matrix cosine of 0.09 is compatible with two maps that reshape the direction of `h` similarly
in the respect the entropy is sensitive to.

**What this does and does not settle.** It settles that the Jacobian's advantage replicates across the estimator's own
randomness, which was the specific threat F94 raised and the one no analysis could have answered. It does **not** settle
the size — F90 and F91 established that the bootstrap interval on the saving spans zero at this sample, and adding a
second projection does not add items. Two point estimates agreeing is evidence about the estimator and not about the
population.

**And band width is now definitively unusable.** The same three runs give 4.03×, 21.24× and 7.51× — the two Jacobian
projections differ by a factor of nearly three on a quantity whose savings differ by one point. F91 measured its bootstrap
interval spanning 2.1 to 130; this shows the same instability across a change that barely moves the number anyone cares
about. **The saving at a pre-specified λ\* is the statistic; the band is a picture.**

**One methodological note, since three entries in a row have turned on controls.** F94's control was wrong for a reason
(common random numbers), F95 named the right one, and this entry ran a different control that answers the original worry
directly. The lesson is not "run more controls" — it is that **a control has to be matched to the specific alternative
explanation**, and "the result is a property of one random draw" is answered by drawing again, not by measuring how much
draws vary.

## F97 — Attribution patching replaces the Jacobian, and three of its four obstacles were mine rather than the method's

**Where it bit.** F95 recorded that the score's first-order form needs a vector-Jacobian product rather than the matrix:
one backward pass gives the endpoint-entropy gradient at every position, replacing 384 forward-difference probes with two
passes and scaling to sequences that include the generated reasoning trace — which is the thing the Jacobian version could
not do. Implementing it produced four obstacles and only one belonged to the method.

| obstacle | cause | fix |
|---|---|---|
| `can't retain_grad on Tensor that has requires_grad=False` | freezing every weight leaves nothing in the graph requiring grad, and token ids are integers | enter the network at the **embeddings**, a float tensor that can be marked |
| out of memory at cap 768 | a backward keeps every layer's activations — **the eighth memory failure here and the first caused by a backward** rather than by a vocabulary-sized tensor | gradient checkpointing |
| **out of memory again at cap 1024, at the same size** | **checkpointing was a silent no-op**: the call succeeds but the checkpointed path is skipped outside training mode | check that every dropout is zero, then enter train mode, so eval and train agree |
| the generation's key-value cache resident during the backward | never freed | free it explicitly before the backward |

**The silent no-op is the one worth keeping.** The log said "gradient checkpointing on" and the run then failed at
**exactly the same allocation size** as before. A memory failure that does not move when the fix is applied is the
signature of a fix that did nothing, and the log line was reporting that a call had returned rather than that anything had
changed. The harness now verifies the precondition — every dropout zero — and says which mode it entered and why.

**And two design flaws in my own measurement, found by looking at 30 interim items rather than by waiting.**

**The endpoints were not the same kind of position.** Condition 0's last position is where the answer comes next;
condition 1's was wherever the trace happened to stop, often mid-sentence. The measured consequence: the long path
appeared to **raise** the endpoint entropy by 0.488 (0.1467 → 0.6347), which is not a property of thinking but of
comparing an answer position with an arbitrary one. Both conditions now get the explicit answer cue.

**And fitting the measurement into memory had removed the effect it was measuring.** At cap 512 thinking neither helped
nor hurt — 0.5333 against 0.5333, three fixed and three broken on 30 items — where at cap 1024 it goes 0.5222 to 0.7391.
**The cap that fit was the cap with no uplift in it**, so the run as configured could not have answered the question at
any sample size. The sample was cut instead of the cap.

**One encouraging measurement from the same interim data.** The two conditions' endpoint-entropy gradients are **nearly
orthogonal** — cosine median −0.0018, range −0.039 to +0.017 — where the template-only Jacobians of F94 had cosine
**0.9811**. So the contrastive score is not degenerate: measuring the sensitivity of two genuinely different computations
gives genuinely different objects, which is what the theory asked for and what changing a chat template did not deliver.

**What the run will answer.** Whether the entropy the long path is predicted to remove — now measured at comparable
endpoints, over a trace long enough for thinking to help — orders items by whether thinking fixes them, against the
short path's own readout on the same items. The comparison and the statistic were registered before the second Jacobian
existed and are unchanged.

## F98 — Two fixes that each removed the effect being measured, and the pattern they make

**Where it bit.** F97 recorded four obstacles in implementing the attribution-patching score. Running it produced two
more, and both had the same consequence: **the measurement's treatment stopped doing anything, so no sample size could
have answered the question.** That is now the third and fourth instance of the same failure in this project, which makes
it a pattern rather than an accident.

| what was wrong | how it showed | consequence |
|---|---|---|
| **only one end token was passed.** The model declares **two** in its generation config (248046 and 248044); `tok.eos_token_id` is one of them | **100% of traces hit the cap**, against 63% stopping on their own through the serving path, which reads the config | truncated traces are worse than none (F77), so thinking gained **2 items in 60** where it gains twenty-two points at the same cap through the server |
| **checkpointing disables the key-value cache.** transformers prints "Caching is incompatible with gradient checkpointing" and turns it off | every new token re-ran the whole sequence: **175 seconds an item** | the cost forced a cap of 512, and at 512 thinking neither helped nor hurt — the cap that fit was the cap with no uplift in it |

**Both fixed, measured:** 175 s per item became **44 s**, and the cap-hit rate went from 100% to **60%**. The fix for the
second is to toggle checkpointing per phase — off for generation, on for the backward — because **the thing the backward
needs is the thing generation cannot afford**, and nothing about that is visible from either requirement alone.

**And one design flaw of mine, corrected before the run rather than after.** The two conditions' endpoints were not the
same kind of position: the direct one sits where an answer comes next, the long one sat wherever the trace stopped. The
measured consequence and its repair:

| | endpoints unaligned | endpoints both at the answer cue |
|---|---|---|
| entropy the long path appears to add | **+0.4880** | **+0.0956** |
| cosine between the two gradients | −0.0018 | **+0.6689** |

**Four fifths of the entropy anomaly was the position mismatch**, and the near-orthogonality that looked like a good sign
in F97 was the same artefact. Aligned, the two gradients are correlated and distinct, which is what two genuinely
different computations should look like.

**The pattern, stated so it can be checked next time.** Four times now — the letter readout collapsing to chance, the cap
with no uplift, the never-stopping generation, and the 512-token cap — a measurement was built whose **treatment had no
effect in it**, and each time the tell was available in the first ten items: a base rate at chance, a fix rate near zero,
a cap-hit rate of 100%. **None of those needed the run to finish.** The harness now prints the cap-hit rate every five
items and flags it above 90%, which is the cheapest of the four checks and the one that would have caught two of them.

**What the running measurement can now answer.** Whether the entropy the long path is predicted to remove — at comparable
endpoints, over traces that stop on their own, with thinking actually helping — orders items by whether thinking fixes
them, against the short path's own readout on the same items. Registered before the second Jacobian existed and unchanged
since.

## F99 — The theory's quantity works, my approximation of it does not, and both arrive too late to be used

**Where it bit.** The theory named a contrastive score — the entropy the long path is predicted to remove — and F95
replaced the Jacobian with a first-order surrogate computable by one backward pass. Four implementation failures later
(F97, F98) the setting is finally correct: **123 items, direct 0.5041, thinking 0.7398, 33 fixes against 4 breaks**, the
long path halving the endpoint entropy from 0.9880 to 0.4179, and the two conditions' gradients far from parallel at
cosine 0.1479. So the measurement can be read.

**Single features, AUC for "thinking fixes this item", no fitting, each against its own permutation null:**

| AUC | p | feature |
|---|---|---|
| **0.7785** | 0.000 | **the entropy the long path actually removes, `H0 − H1`** |
| 0.7242 | 0.000 | the short path's own entropy `H0` — the incumbent |
| 0.6687 | 0.001 | the contrastive score, **negated** |
| 0.5391 | 0.265 | the long path's entropy `H1` |
| 0.3620 | 0.991 | the generated length |
| **0.3313** | 0.999 | **the contrastive score as the theory signs it** |
| 0.1384 | 1.000 | the two gradients' cosine |

**Two results, and they point opposite ways.**

**The theory's quantity is real.** `H0 − H1` reaches **0.7785** against the incumbent's 0.7242, with the sign the theory
predicted: an item whose endpoint entropy the long path removes more of is more likely to be repaired by it. Fitted and
held out, `H0` alone gives 0.7111 and adding `H1` gives 0.7481.

**My first-order surrogate is not.** The gradient projection `⟨g⁰ − g¹, h⟩` sits at **0.3313** as signed — anti-predictive
— and 0.6687 negated, which is *below* the incumbent. So the approximation does not track the quantity it approximates,
and the four implementation failures were spent producing a worse signal than the two entropies it was standing in for.

**And the finding that matters most is a circularity I should have seen before building any of it.** `H1` is the endpoint
entropy **after the long path has run**. Knowing it requires running the long path. My `g¹` is computed over prompt plus
trace, so it requires the same. **Neither `H0 − H1` nor the contrastive score is available at the moment the decision is
made.** The only pre-generation quantity in the table is `H0`, at 0.7242 — which is the signal this project already had.

**So the +0.054 that knowing the long path buys is real and unreachable.** The theory's proposal is only non-circular if
`J^(1)` can be **estimated from other prompts** and applied to a new item's residual without running its trace. That is
exactly what F94 attempted, and the attempt failed for a reason it recorded: a `J^(1)` built by changing the chat template
has cosine **0.9811** with `J^(0)`, so it carries no information about the long path that the short path did not already
have. **Building `J^(1)` from the actual continuation is what would close the loop, and that is expensive per item in the
same way `H1` is** — the construction has to average over prompts, so it must be built once and reused, which means it
cannot depend on each item's own trace.

**What this leaves.** The deployable signal is unchanged: the readout at the prompt, `H0`, at AUC 0.7242 on this set. The
contrastive line is closed as a **pre-generation** signal, with a clear statement of what would reopen it — a `J^(1)`
estimated from a corpus of traces rather than from a template change, which is a construction nobody in this project has
built and whose cost is one generation per prompt in the construction set rather than per item at serving time.

**And a note on the four failures that preceded this.** They were real and each was a distinct defect, but the object they
were fixing turned out to be the wrong object. **The circularity was visible from the definition and no amount of correct
implementation would have removed it** — which is the argument for checking what a quantity requires before building the
machinery that computes it, and the fourth such argument this ledger has recorded.

## F100 — Three requirements the experiments produced, implemented so the wrong state is unrepresentable

**Where it bit.** Ninety-nine entries of experiment feedback, sixty-two with an explicit discharge clause, and a check
of the code found that three of the requirements they name existed **nowhere in it**: `weight_digest` in 0 files,
`idempotency` in 0, `hop_count` in 0, `parent_request_id` in 0, `decision_id` in 0. `measured_on`, `policy_version`, the
frontier and the exchange rate were already there; these were not.

**`src/tierbook/judge.py` — what a judge carries and what a candidate must match.** Three categories, kept apart because
they are checked differently and collapsing them is how a manifest looks complete while admitting a judge that cannot
work:

| category | how it is checked | what it closes |
|---|---|---|
| **declared** | compared against the served candidate | F56, F57: two models agreed on architecture, `d_model`, depth, vocabulary size, tied flag, dtype and `len(tokenizer)` — 248,077 in both — with residual cosine 0.56–0.61 where two *different prompts* in one model reach 0.88–0.90 |
| **measured** | cannot be compared, only re-measured; the digest licenses it | F58: two models identical in architecture, dtype and depth fraction had optimal amplitudes a factor of four apart |
| **assumes** | checkable by neither | F59: a readout convention gave 0.0899 against a 0.10 floor on a model whose digest would have matched |

The refusals are the content. `WeightDigest` refuses `subject="loaded_tensors"` **by name**, because hashing parameters in
memory made a correct artefact refuse its own model — an engine fuses projections and changes dtypes, so identical
published weights hash differently once served. Each of the eight keys measured to be insufficient is refused as a
declared key rather than deprecated. A `MeasuredConstant` cannot be constructed with a string where a digest belongs. A
constant measured on other weights cannot sit in a contract for these. And `admissible` refuses a **missing** base rate
rather than treating absent as clear, in the order digest-then-base-rate, because the first is free and the second costs
a pass over the buyer's items.

**`src/tierbook/escalate.py` — what a re-issue carries.** From the 32-request two-server run where 12 escalated:

- **the engine returns an action, not a destination.** `target_profile` refuses anything that looks like an address,
  because naming one is how a gate quietly becomes a second router and duplicates the endpoint selection the standard
  mechanism already performs.
- **the idempotency key is derived and has no parameter.** A key the caller supplies is a key a retry varies, and then
  one escalation is billed twice. Two attempts at one escalation collide by construction.
- **the hop bound is enforced at construction.** A depth that only gets logged is a loop with a paper trail. And
  `next_hop` derives the depth from the previous hop rather than accepting an asserted one, refuses a chain whose links
  name different parents, and refuses re-escalating to the profile that just declined.
- **`commit_semantics` is a closed vocabulary** because generation length is known only while decoding, by which point
  output may be streaming and cannot be replaced — so whether a late escalation may substitute is the buyer's
  declaration.
- **an empty completion is not read as an escalation.** It cannot be told apart from a request answered with nothing,
  and a run that relied on it reported the right count for the wrong reason.
- **`upstream_ask()` states what would replace the sentinel**, so a workaround is not mistaken for the design.

**60 new tests, and the suite is green at 1,569 passed and 3 skipped.** Every test names the defect it closes, and each
defect is one a measurement produced rather than one imagined: the numbers in the test bodies are the numbers that
occurred.

**What is deliberately not here.** No endpoint discovery, no queue or cache scoring, no pod fallback, no profile
management — F63 named those as things the standard mechanism already does, and re-implementing them produces
compatibility debt rather than value. And no asynchronous outcome plane yet: F63 designed it and it is a larger piece
than these three, which are each small enough to be got right in one sitting.

## F101 — The outcome plane, and the one design that would have destroyed the log

**The defect, stated before the fix.** An outcome is knowable only after the decision it judges, so something must
carry it back. The obvious design lets the callback that receives an outcome update the thresholds the router is
using — and that makes decision N behave according to how many outcomes happened to arrive before it, which is a
function of network timing. **Replaying the same traffic then decides differently.** There is no error and no log
line; the system works and performs plausibly. A policy that cannot be replayed cannot be audited, and cannot be
compared against another, which removes the reason the ledger exists.

**`src/tierbook/plane.py` separates three things a single callback collapses.**

| what | how it is enforced |
|---|---|
| observations append and nothing else | `register` **inspects the observer's signature** and refuses a parameter named for anything it could mutate |
| a snapshot is immutable and its name is derived | `snapshot_id` is a **property, not a field** — there is no parameter to supply |
| one policy version reads one snapshot | `refuse_drift` raises when a version is seen against two snapshot ids |

**The inspection matters more than the docstring.** "The observer must not mutate the scorer" is a rule, and a rule is
what the next person breaks for a good reason. Refusing a parameter named `policy`, `scorer`, `picker`, `router`,
`gate`, `threshold` or `snapshot` — and refusing `**kwargs`, because a signature accepting anything accepts a policy,
and refusing a C callable, because it exposes nothing to inspect and admitting it is admitting an observer on trust.

**`built_from` is a closed range.** A snapshot built from "everything up to now" cannot be rebuilt, because *now* has
moved, so no claim made from it can be rechecked. And `unobserved` is a first-class terminal state: a request whose
fate is genuinely unknown must be representable, or it is recorded as a failure and biases every rate computed from
the log.

**What this costs, stated rather than hidden.** The separation means an outcome observed now changes behaviour only at
the next snapshot. Nothing here makes the loop faster — it makes it replayable — so `staleness()` reports how many
observations the live snapshot does not include, which is what lets somebody choose the rebuild cadence instead of
assuming the loop is closed.

**33 tests, and each mechanism was mutated to check the tests are not vacuous:** removing the signature inspection
fails 9, disabling the drift check fails 1, and dropping the constants from the derived id fails 1. Suite green at
**1,602 passed, 3 skipped**.

**One defect found in my own test rather than in the module.** The no-signature case picked its subject with a
conditional that selected the wrong branch, landing on a `**kwargs` C wrapper and passing for the neighbouring
reason. Both paths refuse, so the module was right and the test was evidence of nothing.

## F102 — Two defects found by wiring the new contracts into the existing code

The four contracts of F100 and F101 had **zero production callers**. A mechanism only its own tests call has no
coverage of the thing it exists to protect, so the next step was connecting them — and connecting them is what found
both defects below. Neither was visible while the modules stood alone.

**A name collision that inverted a meaning.** `plane.Observation` and the long-standing `observe.Observation` are
opposites: the second is the state observed **before** a decision, the first the outcome observed **after** it. Two
types with one name, in one package, one of them the input to `route_once` and the other the thing that judges its
result. Renamed to `plane.Outcome`.

**The drift check landed on a field the log already had.** `Decision` carries `policy_digest`, a content hash of the
compiled artifact a decision was made from — which is exactly what `refuse_drift`'s snapshot id means. So the check
needed no schema change and no new field; it needed to be *run*. Measured before writing anything: two decisions under
`policy_version` "gate/0.1" with digests differing, and **`read()` accepted both and reported nothing**. Any rate
computed for that version is then over a mixture of two different compiled policies, while the log looks complete.

**Reported, not refused, and the distinction is the code's own.** `read` already draws it: a rewritten label **raises**,
because a rewrite makes every criterion over the log a criterion over the rewrite and no reading of the bytes recovers
the original; an orphan label is **reported**, because it makes a label absent rather than corrupt. A mixture sits with
the orphan: every row truthfully names the artifact it decided from, so grouping by digest still gives a clean answer
and only grouping by *version* is a mixture. Refusing would make an otherwise-readable log unreadable over a fact that
invalidates one grouping of it. `plane.refuse_drift` remains the raising version, for a caller that must not proceed at
all.

**One false positive designed out.** A version 1 or 2 row carries `policy_digest: ""` by S4, so an absent digest is not
counted as a second artifact — otherwise every log spanning the upgrade reports as a mixture, and a check that fires on
every healthy log is a check somebody switches off.

`tierbook logs` surfaces it as `version_mixtures`, always present rather than appearing only when something is wrong,
for the reason the two keys beside it already give: absent-when-clean leaves a reader unable to tell "every version
names one artifact" from "this version of the tool did not look".

**Suite green at 1,606 passed, 3 skipped.** The mixture detection was mutated to `{}` and the new test fails, so it is
not passing vacuously.

**And one process note.** The rename was first attempted with `sed -i '' 's/\bObservation\b/.../'`, which is a silent
no-op on macOS because BSD `sed` does not implement `\b`. The chained command reported success for two of its three
edits and left the test file half-renamed. A rename is not a text substitution worth trusting without reading the
result.

## F103 — Giving the contracts a real caller, and the three defects that surfaced on the way

All three new modules had **zero production importers**, measured rather than assumed: the earlier grep looked like it
found callers and was matching the word "judge" followed by a full stop in prose. A mechanism only its own tests reach
has no coverage of the thing it protects.

**Defect 1: the reader grew a second copy of the drift rule.** F102 put the version-mixture grouping inline in
`record.read()` while `plane.refuse_drift` already had it. Two implementations of one rule, one edit from disagreeing
about what a mixture is — and then a log passes one check and fails the other. Split into the fact and the two policies
over it: `plane.mixtures()` returns the grouping, `refuse_drift` raises on it for a caller that must not proceed, and
`read()` reports it while still returning its rows. **Proved wired by breaking `plane.mixtures` and watching a `record`
test fail** — two modules both existing is not evidence that one calls the other.

**Defect 2: I wrote unreachable code and a comment describing it.** The new `mixtures` had a branch for a reading with
no snapshot id, explained at length. `Reading` refuses an empty id, so the branch could never run. The invariant now
lives in one place and the docstring says where the filtering happens instead of pretending to do it twice.

**Defect 3: the CLI door printed stack traces where it promised sentences.** `admit-judge` now exists — the door the
judge contract was built for, offline rather than per request because the digest comparison gives the same answer every
time and the base rate costs a pass over the buyer's items. Its first version put `digest_published()` and the digest
parse **outside** the try, so a `--served` directory with no `config.json` and a `--digest` that was a model *name* both
exited with a traceback. A refusal an operator cannot read is a refusal that gets worked around rather than fixed. Six
paths verified by running the command, exit code measured correctly the second time (the first attempt read `tail`'s
status, not the program's):

| input | exit | refusal |
|---|---|---|
| matched, base rate 180/253 | 0 | admitted |
| wrong model served | 1 | cannot be caught downstream |
| base rate 21/234 against a floor of 0.20 | 1 | ordering of noise |
| no base rate | 1 | the only check that sees it |
| `--digest Qwen3.8-9B-Distill` | 1 | not a lowercase 64-character sha256 |
| `--served` with no config, `--constant threshold`, `--constant threshold=high`, empty `--judge-id` | 1 | each names what to fix |

**And the repo caught my own omission.** A standing guard asserts the module docstring's verb list matches what
`--help` prints; adding a subcommand without listing it failed that test immediately. This is the shape worth having
more of: the omission is a failure rather than an absence.

**Suite green at 1,617 passed, 3 skipped.** The door was mutated (removing the `admissible` call) and two tests fail, so
they exercise the door rather than the library beside it.

## F104 — The log can now hold a re-issue, and answers the two questions no single record can

`escalate.py` was the last of the three contracts with no production caller, and the log could not represent an
escalation at all -- so **the cost of escalating, which is the central number of this whole line of work, was not
computable from a tierbook log.**

**The smaller shape was the better one.** The obvious move was a field on `Decision`, which meant bumping the schema
and editing **44 construction sites**. Rejected in favour of the precedent the log already sets: an outcome is its own
line joined by `request_id`, not a field on the decision. So a re-issue is `append_escalation`, identified by an
`escalated_from` key, with **no schema change and no churn** -- and it catches strictly more, because the questions that
matter are about the SET of lines rather than any one of them.

**And an escalation has a second reason to be its own line that the other two kinds do not have: it is a
RELATIONSHIP.** A field on the child records only the child's side. What the log must answer is "was this one
escalation retried, or two escalations", and that is not a property of either decision.

| check | why no single line can make it |
|---|---|
| **double charge** -- one idempotency key naming two `decision_id`s | the key is derived from the parent and the hop *so that a retry collides with itself*, so a collision across two decisions means one re-issue was recorded twice and every cost total counts it twice |
| **hop bound in composition** -- a chain deeper than `MAX_HOPS` | each line is inside the bound on its own; a chain assembled from lines written by different callers is not, which is why `next_hop` derives the depth rather than accepting an asserted one |

Both reported rather than refused, on the line the reader already draws: recoverable (deduplicate by the key) means
report. A loose dict is refused at the door, because it would carry whatever the caller set -- which is how a hop bound
gets exceeded on a line nothing checked. A re-issue naming a `request_id` no decision carries is refused too: one read
here beats a cost total nobody can reconcile.

**These three keys appear only when the log holds re-issues**, unlike the mixture and orphan keys which are always
present. The distinction is real: a log with no escalations is not a log whose escalation checks did not run, it is a
log with nothing to check.

**One defect fixed on the way.** Adding two imports left the existing cycle-check comment sitting above three of them
while describing one. Rewritten to say what each import is for and to record that `escalate` and `plane` import nothing
from this package, so no edge closes a loop.

**Suite green at 1,624 passed, 3 skipped.** Both whole-log checks were mutated and each fails a test.

## F105 — F18's requirement, discharged in the code: a comparison names its setting or has none

**F18 named a mechanism-level duty** -- "a policy comparison must name its operating point or integrate over it" --
and `counterfactual.Comparison`, the general paired-comparison surface, reported an accuracy delta, a cost delta and
a p-value **while naming no setting at all.** A comparison reported that way reads as a general ranking, and F18's own
measurement is that it is not one: three signals that separate cleanly at one floor all converge at the last tenth.

**`OperatingPoint` is required on every comparison, with no default**, and `compare()` takes it keyword-only. A default
would put the unnamed comparison back wearing a field that claims it was named.

| kind | what it means | what it may carry |
|---|---|---|
| `fixed` | true at one setting | the value, the knob it sets, and where the setting came from -- all three, refused apart |
| `integrated` | reported over the whole curve | no setting; a value here would be read as the one it holds at |
| `not_applicable` | neither arm has a tunable setting | the honest answer for two fixed candidates, a dishonest default for anything with a gate |

**The sharp part is `chosen_on`, and it is the one thing here that was measured rather than reasoned.** Choosing the
setting on the items then scored gave **seven candidate settings at every price of accuracy**, and taking the best of
them inflated the reported interval directly. So a comparison built that way is representable -- it says what the best
case looked like -- and **cannot support a verdict**: `is_significant()` raises `Unsupported` with the sentence that the
p-value is not the p-value of the procedure that produced the number. The escape is an explicit argument at the call
site, on the shape `table.lookup` already uses for an unvalidated entry, so a reader of that line sees the claim being
made. `__str__` prints "no verdict: the setting was chosen on the scored items" **in the place a reader looks for the
verdict**, rather than omitting it.

**Three existing tests broke, and one of them is the evidence.** Two were mechanical. The third asserted
`c.significant` on a comparison that named no setting -- the behaviour this change declares wrong -- so it was changed
deliberately with the reason recorded beside it. A test that has to change is the argument; the two arms in that
fixture are fixed candidates with no gate, so `not_applicable` is the true statement about them rather than a way past
the requirement.

**Suite green at 1,642 passed, 3 skipped.** Three mechanisms mutated -- the verdict refusal, the `supports_a_verdict`
rule, and the kind vocabulary -- and each fails tests.

**One piece of cruft removed from my own test file**: a helper referencing `cf.Run` behind a `hasattr` guard, written
before I knew the fixture's shape. A guard that makes a helper silently return `None` is worse than the helper being
absent.

## F106 — A cost names its unit, so two units can no longer be subtracted

**F93 records this as unaddressed and gives the reason:** tokens are a weak proxy for cost, and a policy ahead in
tokens can lose in GPU-seconds, because a token count does not see KV-cache occupancy or the effect of a long trace on
every other request sharing the batch. **Measuring GPU-seconds needs load rather than more items, so that half stays
owed.** What is checkable without the measurement is the part that was silently wrong: nothing said what unit a cost
was in, and every experiment in this study measured **tokens** while the field holding the number was named `usd`.

**`COST_UNITS = ("usd", "tokens", "gpu_seconds")`, and deliberately no conversion function.** `tokens` to `usd` needs a
price card; `tokens` to `gpu_seconds` needs a throughput measured under load. A coefficient assumed instead of measured
once moved a published figure in this project **by a factor of six and changed which candidate was selected**, so a
`convert` helper here would invite exactly that. A test asserts no name in the module contains "convert".

**The default is `usd`, and that is honest rather than plausible-looking.** The field is named `usd`, so every existing
caller put dollars in it and "usd" is the true statement about those runs. What the default does not do is let a
token-measured run pass as a dollar one: a caller measuring tokens has to say so.

**Two names, split by how many call sites they had.** `usd_delta` had four uses, so it is renamed `cost_delta`.
`usd_per_item` had **fifty-nine**, so it is kept and now **refuses unless the run really is in dollars** — a name
asserting a unit the value is not in is what makes an incommensurable comparison look like arithmetic. `cost_per_item`
is the unit-agnostic accessor beside it.

**`compare()` refuses two runs measured in different units.** Subtracting them produces a number in no unit at all, and
it looks exactly like a cost advantage.

**And the report cannot put a currency symbol on something that is not currency.** A `$` in front of a token count is
the strongest possible reason for a reader to assume two figures are in the same thing, so a token cost prints as
"300.0 tokens" and a GPU-second cost as "0.300 GPU-s".

**Suite green at 1,657 passed, 3 skipped.** Four mechanisms mutated -- the cross-unit refusal, the dollar-only accessor,
the vocabulary, and the formatter -- and each fails tests.

**One process note.** The first attempt anchored an insertion on `class Run:` and hit an indented occurrence inside a
docstring, producing a syntax error at an unrelated line. Anchoring on `@dataclass\nclass Run:` and asserting the match
count is exactly one is the fix; a `replace` that does not check how many times it matched is not an edit, it is a
guess.

## F107 — "Not significant" is not "no difference", and a test with five discordant pairs could never have said either

**The ledger recorded this error twice** -- F30 ("a p-value of 0.17 to 0.39 is not evidence of equivalence without an
equivalence margin and power") and F95 ("**'not significant' is not 'no difference'**: claiming the template does not
matter needs an equivalence test with a pre-justified margin"). Neither existed in the code, so
`is_significant() == False` was the only answer available and it is not the claim anyone wanted.

**`equivalent_within(margin, margin_source=...)`** is the second claim, as a confidence interval on the paired
difference lying wholly inside the margin (Lakens 2017). The interval is built from the **discordant counts**, not the
two marginals, because that is where a paired design's information is -- two marginals whose intervals overlap can hide
a difference every item agrees on.

**`post_hoc` is refused, and that refusal is the entry's point.** A margin chosen after seeing the difference is a
margin chosen to contain it, and this is the one place where the order of operations decides whether the answer means
anything. A margin of zero is refused too: it declares that only an exact tie counts as the same, which no finite
sample can show.

**And a second guard, which the same passage implies and which turned out to be the sharper one.** The exact two-sided
sign test puts both extremes in the tail, so with `d` discordant pairs **the smallest p it can ever produce is
`2/2**d`**, whatever the data said:

| discordant pairs | smallest possible p | can reach alpha=0.05 |
|---|---|---|
| 4 | 0.1250 | no |
| 5 | 0.0625 | no |
| 6 | 0.0312 | yes |

**With five or fewer, no outcome could have been significant** -- so a `False` from that test describes the sample size
and not the world, and the danger is exactly that it reads like evidence of no difference. `is_significant()` now raises
rather than returning False there, and the message names both ways out: collect more units, or ask `equivalent_within`
if the claim you want is sameness. This is the same arithmetic that makes a sign-flip permutation over **eight prompts**
bottom out at 1/256 with no power worth having.

**The printed form names which verdict is missing and why**, separately for the two refusals, because the reader's next
move differs: one needs the setting chosen elsewhere, the other needs more units.

**One duplication removed while wiring it.** `policy` held a private five-entry normal-quantile table and
`counterfactual` needed the same one. It now lives in `evidence`, the leaf both already import, because two copies are
one edit from disagreeing about what alpha=0.05 means. It stays **conservative between entries** -- a finer alpha
returns the next coarser quantile, widening the interval -- since an interpolation would be a number nobody checked
sitting where it decides whether a result is claimed. A test asserts `_z_for` no longer appears in `policy`.

**Suite green at 1,679 passed, 3 skipped.** Five mechanisms mutated -- the attainability guard, the post-hoc refusal,
the interval containment, the p-floor formula, and the quantile table -- and each fails tests.

## F108 — A judge binds to a box somebody already runs, and "blocked" is not "provision"

**F56's clause named this and only half of it was built:** "the same matching that lets a judge BIND to an
already-standing shared box rather than provisioning its own — requirement and provisioning are two readings of one
comparison, so the contract does double duty." Admission existed; binding did not. It is also the requirement stated
directly in this project: **an administrator stands a box up from a template and ordinary users build judges against
it**, because if every judge silos its own hardware a marketplace of judges does not work at any scale.

**`bind(contract, boxes, requester=...)` reuses the digest the contract already carries** rather than introducing a
second notion of compatibility, which is what "two readings of one comparison" means in code.

**Three outcomes, and keeping the last two apart is the entire point.**

| outcome | what it means | what the caller does |
|---|---|---|
| `bound` | a standing box serves this digest and will take you | bind to it |
| `provision` | **nothing** standing serves this digest | start one; there is no shared resource to point at |
| `blocked` | something serves it and will not take you -- not shared, or full | ask that owner; **provisioning another would leave two copies of one model** |

Reporting `blocked` as `provision` is precisely how a shared box ends up idle beside a second copy of itself: every
judge whose access request is pending starts its own. So the rejections are carried per box with a closed vocabulary
(`digest_mismatch`, `not_shared`, `at_capacity`), and `Binding.instruction` turns them into the sentence the caller
acts on. A `Binding` names a box **exactly when it succeeded** -- a named box with any other outcome reads as usable,
and an unnamed one claiming success cannot be acted on.

**Wired into `admit-judge`, after admission rather than before**: a judge that may not run against this model at all
should not be told which box to point at. Exit codes separate the two problems -- **1 for a judge that must not run, 2
for a judge that is fine and has nowhere to run** -- because only one of them involves starting a machine.

**One real defect in my own wiring, caught by trying to reach each outcome.** The first `--standing-box` spec had no
digest field, so every box was constructed with the digest of the model actually served. `digest_mismatch` could then
never occur and **`provision` was unreachable from the door** -- a command able to report two of its three answers with
nothing saying so. The spec is now `ID:DIGEST:OWNER:SHARED_WITH:TENANTS:MAX`, and all three outcomes were exercised
against the real command.

**Suite green at 1,699 passed, 3 skipped.** Three mechanisms mutated -- the blocked/provision split, the grant check and
the capacity check -- and each fails tests.

**One process note that cost several minutes.** Five verification runs all reported a malformed spec, and the code was
correct: **zsh's `:a` modifier had eaten part of `"box-1:$RD:admin:..."`**, turning the digest into an absolute path and
leaving `dmin` behind. Building the argument with `printf` into a variable fixes it. A shell that rewrites an argument
silently produces a failure that looks exactly like a bug in the program under test, and the tell was that the same
values passed through `argv` in Python worked first time.

## F109 — The one defect this ledger names five times: a number that does not carry the condition it was measured under

**F1, F15, F16, F22 and F31 are the same defect in five places.** F15 states the ask exactly: "a number carrying the
condition it was measured under, so that a comparison between two conditions is **refused instead of performed**" --
and then the fact that makes it urgent: **every economic threshold in this project is conditioned on a box accuracy,
and none of them says which box.** F31's process audit found the common cause of every withdrawal in this study to be
a **silent substitution of the subject** between two numbers.

**F1 also said exactly where it goes**: "`serves` already records the model, endpoint and deployment; the prompt is the
same kind of fact and is currently absent." It was still absent.

**`Elicitation` keys on the template's text, not on what the template was called.** This study labelled its conditions
"terse" and "explaining" and **reused both labels across templates that were not the same text** -- the identical
failure the model-identity digest records, and the reason `name` is kept for the reader and explicitly refused as the
key. Two templates both called "terse" are two templates; the same template under two names is one condition.

**The refusal is at the comparison door**, so it needed no churn: `compare()` raises `Substituted` when both sides
recorded a condition and the digests differ, naming both, with the reason spelled out -- **the difference between the
two numbers is not a difference between the arms, it is partly the difference between the questions.**

**What is deliberately left representable, and why.** An *unrecorded* elicitation is allowed, because every run written
before this field existed is in that state and refusing it would make the mechanism unusable on the data that exists.
What is not representable is comparing two **different recorded** conditions -- which is the defect that was actually
measured. And an unrecorded comparison is made **visible** rather than silent: the printed form says "elicitation
unrecorded", because printing nothing leaves a reader unable to tell "both arms were asked the same way" from "nobody
wrote down how either was asked".

**One recorded side carries its condition onto the result** rather than being dropped, since losing it would make that
result indistinguishable from one where neither side recorded anything.

**Still owed, and stated rather than implied.** F1's other half is a field on the **tier record** itself, which is a
schema change; this discharges the comparison half only. F16's variant -- a quantity from a fitted model carrying its
hyper-parameters and geometry -- and F22's -- an effect saying whether it is one setting or a sweep, with the control's
value beside it -- are the same shape in two more places and are not done.

**Suite green at 1,715 passed, 3 skipped.** Five mechanisms mutated -- the digest comparison, the condition travelling
onto the result, the bare-string refusal, the sha256 check, and digesting the template rather than the name -- and each
fails tests.

**One process note.** A field insertion anchored on a two-line pattern silently matched nothing because comment lines
added in an earlier iteration now sat between them, and `compare()` then passed twelve positional arguments to a
ten-field dataclass. Asserting the match count is exactly one caught it on the retry; the first attempt reported
success while changing nothing, which is the failure mode of every edit that does not check what it matched.

## F110 — Reading the prompt and writing the answer are priced apart, and a signal's price is a pass count

**F13 and F14 asked for the same thing and neither existed.** F13: "a cost model that separates prefill from
generation... a router that decides whether to generate needs those two priced apart, and no record here does that."
F14: "nothing in the mechanism records how many passes a signal cost, so that trade cannot be stated."

**The measurement is the whole argument.** On the same server: reading the prompt **0.109 s**, writing the answer at the
box's own median length **10.42 s**. Charged at one rate per token those are the same thing; they differ by about 95, and
**98.96%** of a generating request is the part a gate can avoid. `Spend.generation_share` reproduces that figure.

**`Spend` keeps the legs apart and derives the total.** `total` is a property, not a field: a supplied total can
disagree with the legs it claims to sum, and it is also the field a caller reaches for when they have not thought about
which leg their change touches -- which is the defect. `avoided(before, after)` returns a **saving with its legs**,
because a saving that is all generation is a gate working and a saving of the same size that is all prefill is a shorter
prompt, and those need different things done next.

**`SignalPrice` counts passes, and the marginal/absolute distinction is where I got it wrong first.** My initial
`share_of` counted every pass and returned **2.09%** against the ledger's recorded 1%. **The ledger was right**: a
request that answers at all reads its prompt once, so the recorded 1% is the *second* read. A signal computed from the
read the request makes anyway is **free**, `extra_passes` is `passes - 1`, and `share_of` is marginal by default:

| signal | extra passes | share of a whole generation avoided |
|---|---|---|
| read from the prompt the request already reads | 0 | **0.0** |
| an intervention needing a second read | 1 | **0.0105** -- the recorded 1% |
| the same, priced absolutely (only when asked for) | -- | 0.0209 |

That 1% is the entire argument for **buying even a small additive gain**, and it is a statement no scalar total can
make.

**The cost vocabulary now has one home.** `COST_UNITS` and `format_cost` moved out of the comparison module into
`spend.py` and 29 duplicated lines were deleted, because two copies of a unit list are one edit from disagreeing about
what a cost is. A test asserts the comparison code reads them from here rather than holding a copy.

**Refusals worth naming**: a negative leg (it would make a total smaller than one of its parts); a pass count that is
not an integer, including a bool, which would count `True` as one pass silently; a scalar `per_pass`, since it cannot
say whether the pass is a prompt read or a generation; and a share of a saving of zero, because returning a large number
would read as "too expensive" when the fact is that nothing was saved.

**Suite green at 1,740 passed, 3 skipped.** Six mechanisms mutated and each fails tests.

## F111 — The cost legs reach production: evidence file to cell to run to comparison

**F110 left `Spend` and `SignalPrice` called only by their own tests**, which by this project's own rule is zero
coverage of the thing they exist to protect. This connects them, and the path is the whole point: **evidence file →
`Cell` → `Run` → `Comparison`**, with each hop refusing the state that would make the next one lie.

**`Cell.spend`, paired with the scalar it must agree with.** Three refusals, all the same shape as `bound` /
`bound_provenance`: a split whose total disagrees with `usd` (two numbers then describe one cost and nothing says which
is right -- the state the derived total exists to prevent, reintroduced by writing them side by side); a split with
`usd` absent (they are one cost seen two ways, so carrying the split and not the total says the total was never known
when it was); and a split in another unit beside a field named `usd`.

**One parameter, two shapes.** `from_evidence(cost_per_item=...)` takes a float or a `Spend` per item. The alternative
was a second parallel dict, which is a list one caller fills and another has to remember to fill too -- the shape this
package refuses everywhere else. Its type hint was updated in the same edit, because a hint saying `float` while the
body accepts `Spend` is the documentation defect this ledger keeps recording.

**All or nothing on a run.** `simulate` drops the split to `None` the moment any cell it touched lacks it. A partly
split run reports a leg total smaller than the scalar beside it, and a reader finding that discrepancy has nothing to
attribute it to; a tuple with a hole in it makes every caller check every element, which the first version of anything
does not.

**Both directions on a comparison, not one signed number.** `saving` and `overspend` are separate, clamped at zero,
because `Spend` refuses a negative leg -- a signed cost is not a cost, and inventing one to hold a delta would undo the
refusal that keeps a total from being smaller than its parts. And the two directions are the measured shape: the gate
here **avoids a whole generation at the price of an extra prompt read**, so the net would hide the trade the decision
actually made. A test asserts exactly that: `overspend.prefill` is one prompt read while `overspend.generation` is a
generation, on a cascade against the dear arm.

**Suite green at 1,751 passed, 3 skipped.** Five links in the path were mutated -- the per-cell accumulation, the
all-or-nothing rule, the leg deltas, the loader's shape test and the total/split agreement -- and each fails tests.

**Two of my own defects, and the first is a repeat.** F109 recorded that an unasserted `replace` reports success while
changing nothing, and I then wrote five replacements in one edit and **asserted the count on only some of them**. The
unasserted one silently matched nothing and `compare()` passed fourteen arguments to a twelve-field dataclass -- the
identical failure, one iteration later. The discipline has to be applied to every replacement rather than to the ones
I remember. Second: a test asserted on the loader's **source text** rather than its behaviour, and it failed for the
irrelevant reason that I had guessed the method's name. Replaced with a test that calls `from_evidence` and reads the
cell, which is what the claim was about.

## F112 — How an answer was extracted, and a refusal calibrated to half the failure that cost a GPU run

**F5's ask, unimplemented until now**: "an outcome recording the extraction rule that produced it, and a refusal when
the resulting answer distribution is degenerate. This is the same shape as `bound_provenance`: a value whose meaning
depends on how it was produced, currently recorded without that."

**The design driver is F5's second sentence, not its first.** The break was loud -- 1,822 of 2,364 items on `A`, 77.1%
of a ten-option corpus, accuracy 0.1599 against a 0.10 floor -- and F5 says: *the same failure at half the rate would
have produced a plausible middle value and been believed.* So every bound here is answerable to **half** the measured
break, and `bound_from_options` refuses a tolerance that would let it through, naming both numbers.

**`Degenerate` is a distinct failure from a low accuracy, and that is why the check earns its place.** 0.1599 against
0.10 is a *plausible* number and sends a reader looking for a weak model. **The mass on one option is what says the
reader is broken.** So the refusal happens at table construction, before any accuracy is computed from the answers.

**The rule is a closed vocabulary and each entry is one that was actually used**: `next_token` (the one that broke,
correct under a terse instruction only), `answer_cue` (the repair, which must carry its cue -- appending it in one
condition and not the other is what made two runs' endpoints different kinds of position), `regex_in_reply`,
`parsed_structure`, and `unrecorded` for every outcome written before this existed.

**Two defects of my own, both found by testing an input I had not considered.**

1. **The guard compared shares across different option counts.** It checked a caller's absolute bound against
   0.3854 -- half of a share measured on a **ten**-option task -- so a two-option task was refused at *every*
   tolerance, because uniform is already 0.5 there. A binary task could never have obtained a bound and the check
   would have been switched off exactly where it is most usable. Clustering has to be compared as a **multiple of
   uniform** or not at all.
2. **A derived bound that admits everything was being clamped rather than refused.** At the default tolerance a
   two-option task derives 1.5, clamped to 1.0 -- and the check would then be present, called, green and **incapable
   of refusing anything**. That is coverage that is not coverage, so it now raises and sends the caller to state a
   bound with the reason. At two options nothing derivable from the option count alone can tell a broken reader from a
   skewed answer key, and pretending otherwise is the dishonest option.

**And one fabrication caught before it shipped.** My first wiring read `e.answers` off an `Evidence` object, which has
no such attribute -- an evidence artifact records the verdict per item, not the extracted answer. The answers now
arrive as a parameter for the same reason `cost_per_item` does: neither is derivable from the artifact.

**Suite green at 1,777 passed, 3 skipped.** Six mechanisms mutated -- the modal refusal, the tolerance guard, the
saturation guard, the unparsed refusal, the denominator that counts unparsed replies, and the loader's call -- and each
fails tests.

## F113 — F21's one structure, assembled from the parts the previous iterations built

**F21 is the entry that says the other nineteen were circling one shape**: "one structure, replacing six separate
requirements... the only entry here that would let the J-space work reach the mechanism at all -- as an optional
observation with a price, rather than a signal the mechanism knows the name of." `Quantity` is that structure, and the
mechanism now holds **no readout-specific feature at all**: entropy, a hidden-state probe, a price and a queue length
are the same kind of thing.

**It is assembled rather than restated, and that is the return on the earlier iterations.** The price is a
`spend.SignalPrice`, the prompt condition an `evidence.Elicitation`, the model a `judge.WeightDigest`. A sixth home for
"which model" would have been a sixth thing to get wrong.

**The register refusal is the sharpest thing here and it is a factor of four.** Moving an internal direction moves the
words a model uses about its own competence and moves **15%** of its answers. A mechanism that could register that as a
lever on output quality would act on a 15% effect as though it were the 59% a paper reports for a different claim. So
`control_action` is refused outright, and the register is **checked against the price**: a passive observation costing
an extra pass is an active probe wearing the cheaper label, and a probe costing nothing extra is a passive observation
that would be declined on a budget it does not consume.

**A layer number is refused as an availability by name**, because it is provider-specific detail below that axis and a
mechanism keyed on it would refuse a quantity from a model of different depth for no reason that matters.

**Three defects of my own this round.**

1. **I put the availability axis in the wrong order** -- `during_compute` after `after_prefill` -- and the
   `usable_before_generating` predicate then **excluded the one quantity this entire study is about**: a hidden-state
   readout taken during the prefill computation, reported as useless to the gate it was built for. Fixed, and the
   predicate now reads the axis's own index rather than a hand-written list of good values, so a stage added between
   the existing ones cannot leave it silently wrong.
2. **The new door raised a stack trace on a malformed spec** -- the identical defect fixed in `admit-judge` two entries
   ago, reappearing in a new door. That is a defect fixed at the instance rather than at the class, so the colon-spec
   parsing is now **one shared function** that names the shape it wanted. A third option of this form cannot repeat it
   without deleting that call.
3. The door also had to catch a non-numeric `PASSES`, for the same reason: argparse cannot check inside a positional
   string, so the operator gets a sentence rather than a trace.

**The door is `tierbook admissible-quantities`**, and the digest and the condition are deliberately **not** in the
manifest spec: they come from `--served` and `--elicitation-template`, so a declaration cannot assert a match instead of
being checked for one. Exit 2 when nothing is admissible -- nothing is malformed and the gate has nothing to decide
with, which is a different problem from a declaration that could not be read.

**Suite green at 1,807 passed, 3 skipped.** Six mechanisms mutated and each fails tests.

## F114 — Store the curve, carry every baseline, and close a door defect at its third occurrence

**Two entries, both absent, both about a signal's recorded performance.** F6: "whatever records a signal's strength
recording what it was compared against, so 'beats 0.5' cannot be written where 'loses to the category prior' is the
fact." F29: "a signal's recorded performance being its `U(λ)` curve over the price range, with any scalar derived from it
at the point of use and **never stored in its place**."

**The measured story is the test case.** An abstention rule was reported at **0.5000** as a structural result. That is
the AUC of a constant score by construction and says nothing about the signal; the real decision-time baseline,
measured, was a **category dictionary at 0.6583**. `Performance` reproduces it: at the cheap end the signal loses to
both, and **at the dear end it still loses to the category prior**.

**F6 and F30 pull in opposite directions and both are respected.** Quoting the weakest baseline is F6's defect; taking
the maximum over several controls is F30's winner's curse. So every baseline is carried, `beats` **requires the caller
to name which one**, there is deliberately no method answering "is it better", and `loses_to_any` returns the **whole
list** -- reporting only the strongest loss is the curse from the other side and reporting none is how "beats 0.5" got
written.

**The curve is stored and every scalar is derived**, with two refusals that make the stored-scalar defect
unrepresentable: a curve of one point is "a scalar wearing a curve's name", and a price **between** measured points is
refused rather than interpolated -- because between two points is exactly where the ranking measured here changes, so a
straight line through it reports a ranking that was never observed.

**And the same door defect appeared a third time, so it is closed as a class.** A malformed box spec, a malformed
quantity spec, and now a price outside a measured curve each raised from a line **outside** the door's own `try` and
surfaced as a stack trace where a sentence was promised. A `try` covers the region its author remembered, and **a region
an author chooses is a region an author gets wrong**. The floor is now a `@_refuses` decorator over the whole function,
with a test asserting the doors wear it -- so a new door cannot be added without a decision about it.

**The door reports the loss beside the verdict**: a quantity can be admissible on every axis this structure checks and
still be beaten by the category prior, and that is the fact a score alone hides. An unmeasured performance prints as
unmeasured rather than as passing, because nobody having measured it is not the same as it having performed well.

**Suite green at 1,826 passed, 3 skipped.** Five mechanisms mutated -- the one-point refusal, the no-baseline refusal,
the loss list, the interpolation refusal and the decorator's own catch -- and each fails tests.

## F115 — A floor with the target it is claimed for, and the bar that was unsatisfiable on the day it was written

**F17 and F19 asked for this and only a different ceiling existed.** `accept.floor_is_reachable` checks a floor against
the ceiling a **sample size** imposes on a lower confidence bound; F17/F19's ceiling is the **capability** one -- what
escalating every item could reach -- and nothing computed it. F19: "a floor accepted only alongside the escalation target
it is claimed for... the infeasibility was in the pairing of a floor with a target."

**Two impossibilities, kept apart because they have different fixes.**

| condition | box solves | needs, for floor 0.90 | verdict |
|---|---|---|---|
| terse | 722 / 1,187 | 347 | `gamma` **1.24** -- above what escalating EVERY item reaches. Needs a better target. |
| explaining | 902 / 1,187 | 167 | the bar permitted **141**. Needs a bigger budget or a lower floor. |

A single "infeasible" would send a reader to look for the wrong one. And both are arithmetic, so **the bar could have
been refused on the day it was written** -- which is what did not happen: it stood through several rounds of being
blamed on signals.

**`gamma` is what makes two conditions comparable.** One absolute floor of 0.90 demands 347 rescues in one condition and
167 in the other -- a factor of two -- so every comparison made between them was a comparison of two different
requirements. `comparable()` answers that directly.

**The door exits 2, not 1.** Nothing is malformed and no policy is at fault: the finding is about the bar, and reporting
it as a failure of the thing being measured is the confusion this door exists to end. Exit 1 stays for a bar that could
not be read.

**One defect of mine, and one finding about the ledger's own numbers.**

1. **I took rates and the count came out wrong by one.** `floor(0.608 x 1187)` is 721, while the count the reported 347
   implies is **722**. `round` happens to be right there and is not right in general: a rate stated to three decimals
   over 1,187 items covers a window more than one item wide, so the count is recoverable only when that window holds
   exactly one integer, which nobody checks. `Bar` now takes **counts**, and the off-by-one is unrepresentable.
2. **The two reported figures are not equally consistent with their rates.** 347 implies 722 solved, whose rate is
   0.6083 against the prose's 0.608 -- consistent. But 167 implies 902, whose rate is **0.7599** while the prose says
   **0.7597**, and *no* integer count over 1,187 items gives 0.7597. So in that row the rate and the rescue count came
   from slightly different computations. The entry's ordinal conclusions survive it; the pair does not round-trip, and
   that is worth knowing before either number is quoted as the other's provenance. Recorded as a test.

**Suite green at 1,848 passed, 3 skipped.** Five mechanisms mutated and each fails tests.

## F116 — A rate that cannot be reported bare, and an existing check that was reading the centre

**F32's first mechanical rule**: "a rate reported with its sample size and interval, never as a bare number, whenever it
is used to rule something out. **F19's 0.8934 would never have carried its conclusion if 0.9156 had been printed beside
it.**"

**Reproduced before implementing anything.** At every plausible sample size, a rate of 0.8934 has an interval that
**contains 0.90** -- n=300 gives [0.8533, 0.9234], n=1000 gives [0.8723, 0.9107]. The point estimate was not wrong; it
was reported alone, and alone it read as a fact about the world rather than about a sample.

**`Rate` has no formatting that shows the centre alone**, and `rules_out` reads the **interval**. `cannot_decide` is a
first-class answer beside it, because "the rate is below the floor" and "this sample cannot tell which side of the floor
it is on" send a reader to different places: the first is a finding, the second is a request for more items.

**And the rule found a live defect in code written four entries ago.** `judge.BaseRate.clears` compared the **point
estimate** to the floor, so a base rate of **0.2137 over 234 items cleared a floor of 0.20** while its interval ran from
**0.166 to 0.272** -- a sample that cannot tell which side of the floor it is on, admitted as evidence that the readout
works. It now reads the interval, and admission has two refusals with different messages rather than one.

**The refusal that mattered was decisive anyway, and checking that was the point.** The broken readout at 21/234 has an
interval of [0.0594, 0.1333], **entirely below** 0.20 -- so refusing that judge was a finding and not a point-estimate
accident. Both refusals now print the interval, so the number that would have stopped a conclusion is beside it.

**F32's second rule is already discharged and is recorded as such** rather than reimplemented: "a threshold or
hyper-parameter chosen on the data it is scored on flagged automatically" is `OperatingPoint.chosen_on ==
"scored_items"`, which refuses a verdict outright.

**Still owed from this cluster**: F8 and F11 ask for a strength reported **conditional on the population it will be used
on**, stating whether the model was refitted within the stratum or carried from the pooled fit -- a measured difference of
0.045 -- and conditioning only on quantities available at decision time. `Quantity.usable_before_generating` is the piece
that makes the last part checkable; the structure is not built.

**Suite green at 1,861 passed, 3 skipped.** Four mechanisms mutated and each fails tests, including reverting `clears`
to the point estimate.

## F117 — A strength reported per stratum, and a Wilson interval refused around an area under a curve

**F8 and F11, the pair I named as owed last entry.** F8: a strength reported **conditional on the population it will be
used on** rather than pooled, because "a pooled AUC of 0.75 is an average over a population where the signal is strong on
the easy half and **absent on the half that matters**". F11: the report must say whether the model was **refitted within
the stratum or carried from the pooled fit**, and must condition on something **available at decision time**.

**Both measured facts come out of the implementation.**

| | items | probe | what it says |
|---|---|---|---|
| settles early | 1,827 | 0.7482 | the box is already right three times in four |
| settles late | 537 | **0.5350** | the box is wrong seven times in ten and the readout is a coin |
| pooled | 2,364 | 0.75 | **sits 0.2150 above the stratum that matters** |

And F11's separation: the same slow group read **0.5787** when the probe was refitted inside it, against 0.5350 carried
from the pooled fold -- a gap of **0.0437**, so a carried figure cannot tell an absence of information here from a
direction learned for the other group.

**The refusal with the most teeth is about availability, not statistics.** Settling depth is known only **after
generation**, so which stratum a request falls in is not knowable when the decision is made -- the report is true of the
corpus and cannot be performed in production. It stays *constructible*, because the analysis that found the collapse is
worth keeping, and `production_strength` refuses instead of the constructor. The availability refusal comes **before** the
fit one, so a reader is not sent to refit something unusable.

**A defect I was one step from writing.** The numbers here are areas under a curve and the nearest interval already in
this package is Wilson's -- which is **for a binomial proportion**. Putting one around an AUC returns a plausible pair of
bounds computed for a statistic nobody measured, and nothing downstream could tell that from a correct one. So a
`Strength` names its statistic and its interval method, and `wilson_on_a_proportion` is refused for anything but a
proportion.

**Then I audited every existing `wilson()` caller against that rule** -- sixteen call sites across four modules -- and
**every one wraps a genuine count over a count**: solved over items, stopped over items, wrong-stopped over items. The
audit came back clean, and that is the result rather than a step skipped.

**One class-level fix.** The shared colon-spec parser refused my own `@`-separated stratum chunks, correctly, and the fix
was to give it a separator rather than to write a second parser -- so the one thing that reports a malformed option stays
one thing.

**Suite green at 1,880 passed, 3 skipped.** Six mechanisms mutated and each fails tests.

## F118 — What a signal is ABOUT, and the audit that found a production caller taking it bare

**F9's ask**: "a router that consumes a signal recording WHAT the signal is about. 'The model can name the topic' and
'the model knows whether it can answer' are different facts with different uses, and a mechanism that takes one score
cannot tell which it was handed."

**The measurement does not merely distinguish them, it inverts them.** At one layer the same readout:

| what it was scored against | value | chance |
|---|---|---|
| naming the item's field | **0.7593** | 0.1429 |
| predicting its own error | **0.4227** | 0.5000 |

**Five times chance on the subject, and below a coin on competence.** A mechanism handed one number cannot tell which of
those two it got, and the two point in opposite directions.

**`SUBJECTS` is closed over four**, and `own_competence` and `item_difficulty` are kept apart even though both route by
difficulty: one asks whether THIS candidate can answer and the other how hard the item is for anyone, and a signal
fitted to the second has been measured not to predict the first's uplift. `admissible_for_a_gate` gained a fourth
filter, so a topic signal is **not admissible to a gate however strong it is** -- admitting it would route by subject
while reporting that it routes by difficulty.

**Then the audit, and it found a live one.** Sixteen call sites were clean last entry; this time
`quorum.evaluate_signal` -- which builds an **escalation** policy -- took a bare `dict[str, float]` with nothing saying
what the numbers were about. A topic classifier and a confidence readout arrived there identically and produced policies
described identically. It now requires the subject and refuses anything outside `ESCALATION_SUBJECTS`.

**Three things the assertions caught before they shipped, and each is a rule from this loop's own prompt.**

1. **A cycle.** `quorum` importing the structure's module would have closed `quantity -> judge -> reproduce -> quorum`.
   The vocabulary moved to `evidence`, the leaf both reach -- one home, as with the quantile table and the elicitation.
2. **A third meaning of one word in one file.** `evaluate_signal`'s own body used `subject` for a **list of item ids**,
   while "subject" already means a candidate in this package. The parameter is `about` and the local is now `item_ids`.
   My grep found four uses of that local; **the asserted count found a fifth**, two on one line.
3. **Two fabrications in my own tests.** I called a helper `_t()` that does not exist and imported an exception the file
   does not import, then assumed `evaluate_signal` was imported at module level when this file imports it **inside each
   test**. All three were assumptions about existing code, which is the one rule in this loop's prompt I keep breaking --
   and the cost each time is a failing test rather than a shipped defect, because the prompt also says to run them.

**Suite green at 1,896 passed, 3 skipped.** Four mechanisms mutated -- the subject vocabulary, the gate filter, the
escalation-subject predicate and the quorum refusal -- and each fails tests.

## F119 — The price basis behind a decision, and a refusal I talked myself out of

**F3's ask**: "a decision derived from prices recording the price basis it used -- not the prices themselves, which go
stale, but enough to re-derive them: **the source, the date, and the resulting ordering**."

**The measured cost, and it is the reason the third item is there.** A cheap/dear split over nine candidates had to be
**reverse-engineered from prose in three documents** and confirmed by checking that it reproduced an original count of
**168 items exactly**. No static rate card existed; prices came from a live pricing API at run time and the reading was
not kept. A day went into recovering an input the original derivation had used and not recorded -- and it was recoverable
**only because that count happened to be known**.

**`PriceBasis` carries all three, and the ordering is the one nobody writes down.** A decision does not turn on a price,
it turns on **which candidate was cheaper**, and that comparison is what has to be reproduced. The ordering is also
**read** rather than recorded: a basis whose ordering omits the candidate it is attached to cannot have decided that
candidate's position, and `Candidate` refuses it.

**And here is the design decision I got wrong first, then corrected.** I paired `cost_usd` with `price_basis` in both
directions, exactly as `bound` is paired with `bound_provenance`. It broke every existing caller -- and the symmetry was
false. A bound with no provenance let **three fabricated bounds certify identically**: it is load-bearing for admission,
so it is refused. A cost with no basis is a **reproducibility** debt -- the decision is sound and the derivation cannot be
repeated -- and refusing it would leave the record unable to hold a cost at all. The honest channel for "this record
cannot support X" already existed: `Decision.gaps`, with its own closed vocabulary, which `tierbook assign` already
prints. So `unrecorded_price_basis` is a **new gap reason**, `route_once` appends it when costs were supplied and a basis
was not, and the churn is **zero**.

**The audit against the new rule found the basis existing upstream and not being carried down.** `price_card` requires
`source`, and every tier record requires `measured_at` -- so the source and the date were already there, in the ledger,
and the decision that used them recorded neither. That is a sharper finding than a missing field: nothing had to be
measured, only carried.

**Three of my own errors this round, all the same one.** I guessed `route_once`'s signature text, guessed
`compile_policy`'s arguments, and wrote a test that **skipped itself** when the guess failed -- which is worse than no
test, because it reads as coverage. Each was caught by an assertion or a run, and the third was replaced with one driven
through `test_serve.py`'s own `route` helper, so it exercises the real composition. This is the rule the loop prompt now
marks as the one I keep breaking, and it cost three failures in one entry.

**Suite green at 1,912 passed, 3 skipped.** Five mechanisms mutated -- the ordering check, the ordering requirement, the
date requirement, the asserted-price note and the gap itself -- and each fails tests.

## F120 — A price that does not exist until the call is over cannot be an argument to the call

**F28's ask, and it lands directly on what F119 built.** "An `availability` field on it -- F21's word -- that makes
'realised after the call' unusable as an input to a decision made before it. The second half is the general fix... and
that is checkable rather than a matter of care."

**The number that makes it urgent: 87% of a price term's measured value was leakage.** The rule read what the gateway
**actually charged** -- a figure that does not exist until the call it was supposed to inform is finished. What survived
was the tier's rate, not the item's charge.

**`PRICE_KNOWN_BEFORE_THE_CALL` is a total classification over `PRICE_SOURCES`, not a list of the bad ones.** That is
the move that makes forgetting a failure: adding a source without deciding when it is known **breaks a test** rather than
defaulting the new source to usable. A rate is readable in advance whether static or fetched -- the date on a live
reading is what makes it re-readable, not what makes it late -- and a metered charge is not.

**Refused where it would be an argument, and nowhere else.** A `Candidate` is by its own docstring "one member of the
candidate set", so its price **was** an input to the decision that chose between candidates, and a metered basis there is
leakage by construction. A metered `PriceBasis` stays constructible, because recording what was actually charged is
legitimate; what is refused is attaching it to a decision input. **Nothing is lost by that refusal**, and the tests say
so: `Decision.gateway_quote_usd` holds the pre-call quote and `Decision.outcome` holds what arrived afterwards, so the
refusal removes an argument rather than a record -- and the message names both homes, because a refusal that does not say
where the number should go gets worked around by dropping the number.

**The audit came back clean, and here is what was checked.** Every place a decision reads something money-shaped:
`metered_authorised` is a **forward-looking authorisation flag supplied by the caller** before the call, not a charge;
`compile_policy`'s `metered_ids` is a set of candidate ids, not amounts. Nothing else feeds an after-the-call number into
a decision.

**Suite green at 1,919 passed, 3 skipped.** Three mechanisms mutated -- the refusal, the classification of the metered
source, and the property that reads it -- and each fails tests.

## F121 — A criterion registered with its null, and the report that passed while the conclusion failed

**F36's ask**: "a criterion registered together with its null, computed on a fixture before the real data is opened. It
is the ninth failure and **the first the gates could not have caught**."

**Reproduced end to end before anything was built.** Feeding the entry's own numbers through the new structure returns
the entry's own conclusion:

| | value | verdict |
|---|---|---|
| the internal direction, held out | 0.8285 | -- |
| its permutation null, 95th percentile | 0.7928 | criterion (i) **holds** by +0.0357 |
| fraction inside the answer-letter span | 0.754 against a bound of 0.50 | criterion (ii) **fails** by -0.2540 |
| a freely available readout, same items | **0.8895** | **beats the direction by 0.0610** |

**"Beats its null" is true and the conclusion does not follow.** A report of the first line alone is a report that
passed.

**Three refusals, one per way that report could be produced.**

**A null is a distribution, not a scalar.** Median 0.7584, 95th percentile 0.7928 -- the gain over one is 0.0701 and over
the other 0.0357, so "beats the null" without naming the quantile is a sentence that can mean either. Both ends are
carried, the quantile is declared, and **a draw count that cannot resolve it is refused**: at 0.95 with ten draws the
tail is a single draw or none, so nothing could have failed.

**A conclusion needs every criterion it was registered with**, so `supported` requires all of them and there is **no
method that reports one** -- a test asserts no `any_supported`, `best_criterion` or `first_pass` exists. Reporting the
test that passed is not a partial result, it is a different claim.

**And a null is not an alternative.** Beating a permutation of your own labels says the signal is not an artefact of the
label distribution; it says nothing about whether something cheaper already does the job, and here the two answers
**disagreed**. Losing to a free alternative withholds support on its own.

**What the mechanism cannot close, stated rather than glossed.** It cannot know how many criteria a claim needs -- someone
may still register only the test that passed, and there the registration's job is to make the shortness visible. What it
**can** refuse is a conclusion that never asked the cheaper question at all: an empty alternatives list is ambiguous
between "nothing cheaper exists" and "nobody looked", so it is refused unless the reason is declared, and the two are
refused together.

**One duplication avoided.** "Was this number fixed on the data it is scored against" already existed for a comparison's
operating point. Rather than a third copy, `FIXED_ON` moved to `evidence` -- the leaf both reach -- and `CHOSEN_ON` is now
an alias, with a test asserting they are the same object.

**The audit came back clean, with the reason.** Every existing verdict in `accept` compares against a **declared
threshold** -- a floor, a cohort ceiling, section 2's clauses -- and not against a permutation null, so the
"a null is not an alternative" rule has nothing to bite on there.

**Suite green at 1,946 passed, 3 skipped.** Six mechanisms mutated and each fails tests.

## F122 — A typed-output interface taken in: the form guarantee is real, the calibration claim is not a measurement

**Where it came from.** A vendor shipping "unstructured state in, typed probabilistic decisions out", where "the model
never makes type errors" and "all answers are accompanied with calibrated probabilities", at **$0.042 / MTok input**
against a frontier range of $0.20-$10. This project audited its published claims in an earlier round; what is
implemented here is the **interface**, not the claims.

**It cannot be measured today: the API is early access behind a waitlist.** So the interface is representable and no
number about it enters this ledger. That is stated rather than worked around.

**Two claims travel together in the copy and neither implies the other.**

| claim | about | verdict |
|---|---|---|
| "never makes type errors" | **form** | real, checkable, and now representable: `schema_constrained` |
| "calibrated probabilities" | **content** | a claim. A decoder can place 0.99 on the wrong member of an enum without violating its grammar once |

**The form half is a genuine capability and is recorded as one.** `RULE_CAN_FAIL_TO_PARSE` is a total classification
over the extraction rules, so `schema_constrained` is the only rule whose unparsed share is **0 by construction** rather
than small -- and adding a rule without deciding this breaks a test. It carries no cue, because the constraint is on
what may be emitted rather than on where to look.

**And the degeneracy check still runs for it, which is the point of taking it in this way.** This project's measured
break was **1,822 of 2,364 answers on one option out of ten, every one of them perfectly well formed**. Skipping the
check for a rule that cannot produce a parse failure would be reading "no format errors" as "no reader errors". A
constrained run that clusters is refused exactly as any other is.

**The content half gets a receptacle that cannot launder it.** `Confidence` requires `evidence` from a closed
vocabulary, and `may_be_trusted` **refuses for anything but `measured_here`** -- with a message naming the use that needs
no calibration at all: **ranking**. Ordering items by an uncalibrated score is free; reading 0.85 as 85% is the claim.
`measured_here` cannot be declared without the gap and the bin count, so the weaker claim cannot wear the stronger word,
and one bin is refused because a single average says nothing about whether high confidence differs from low.

**Why this is worth having at all**, stated plainly: a probability returned **beside the answer costs zero extra
passes**, which by this project's own cost arithmetic makes it the cheapest thing a gate can condition on -- and it is a
`own_competence` signal, so it is admissible to a gate on every axis. What it does not touch is the gap this project has
been unable to fill: routing turns on `P(strong correct) - P(box correct)`, and a confidence returned by the box is
another estimator of the **second** term.

**The audit came back clean, with the reason.** Every existing use of "confidence" in this codebase is a statistical
**bound** -- `abstain`'s stop test deliberately uses an upper bound so an uncertain "probably hopeless" keeps spending --
and nothing consumes a model-returned probability, because until now there was nowhere to put one.

**Suite green at 1,964 passed, 3 skipped.** Four mechanisms mutated and each fails tests.

## F123 — What surrounds the model, identified; and where each fact about it can come from

**The hypothesis this answers, and this repository's own numbers support it.** Building the harness well may lower cost
more than routing does. From F1, same box, same 1,187 items, only the instruction changed:

| condition | accuracy |
|---|---|
| terse (`Answer with the option letter only. Do not explain.`) | **0.6243** |
| explaining | **0.7447** |
| per-item agreement | **0.7346** — one item in four flips |

**+12.04 points from one sentence.** Against that, the best routing saving measured here was 7.9%, and it fell to
**1.0%** once the comparison was restricted to the same items. So the thing around the model moved accuracy by twelve
points while the choice of model moved cost by one percent — **and only one of the two had a name in the record.**

**Three of the harness's parts were already identified** (`Elicitation` the instruction, `Extraction` the readout,
`WeightDigest` the model) and **the agent-shaped parts were not**: no `system_prompt`, no scaffold, no turn budget, no
tool set, in any module. `harness.py` names eight parts and composes them into one identity.

**The part that needed the care asked for: where a fact comes from decides what it can support.**

| mode | verifiable here | contemporaneous | may key an identity |
|---|---|---|---|
| **in the request** | yes — we hold the bytes | yes, exactly | **only this one** |
| **pulled by us** | yes | **no** — read at one moment, ran at another | no; carries its lag |
| **pushed by the owner** | **no** — their word | claimed | no |
| **not observable** | — | — | — |

**The fourth entry is the finding rather than an option.** A tool's *schema* is in the request; its *behaviour* is not.
Somebody can change what a tool does, leave the schema alone, and **nothing in the request differs.** So
`BEST_AVAILABLE_SOURCING` is a total classification over the eight parts, `tool_behaviour` maps to `not_observable`, and
**claiming it as request-sourced is refused by name** — because the alternative is a record that looks complete and
groups two different harnesses under one identity.

**A pulled fact carries its lag**, required there and refused elsewhere: bytes in the request have no lag by definition,
and a pushed claim's timing is the owner's word rather than a measurement. **A pushed label may not be the key**, which
is the third time this package has had to say it — a model name and a prompt condition both stayed the same while the
thing underneath moved.

**Only the parts we hold bytes for enter the identity, and that is deliberate.** A name that moved when the owner edited
a sentence about their own loop would not group anything. The owner's description is recorded and reported as
**unobserved**, alongside the parts nothing was recorded about at all.

**`refuse_incomparable` generalises the refusal already in place for a prompt condition**, one level up: the instruction
is one part of a harness, and the 12-point swing came from changing it.

**Fifth vocabulary of this shape, and it went in the leaf.** `PRICE_SOURCES`, `CALIBRATION_EVIDENCE`, `FIXED_ON` and
`EXTRACTION_RULES` all ask "what may this fact support"; `HARNESS_SOURCING` is in `evidence` rather than beside the
structure that needed it first, because more than one place asks.

**Suite green at 1,982 passed, 3 skipped.** Five mechanisms mutated and each fails tests.

**Also added `docs/TODO.md`**, with the two tasks registered by request — benchmark and sampling from a configuration
file, and the `distributed-ai` dependency and its responsibility line — plus seven this side already knew, each with
what would tell us it is finished, and a table of what is deliberately not being done.

## F124 — The 1.0% routing saving is WITHDRAWN, and the standards survey that led there

**Withdrawal first, because it is the actionable part.** The published figure "routing saved 1.0% of cost"
(the corrected value after intersecting on item id, F88's neighbourhood) **is withdrawn as a claim.** The raw
measurements stay as data, with the bias declared unknown.

**Why.** Cache hits depend on whether the previous call in that context shared a prefix. **Routing breaks the
prefix**, so one routing decision raises the cost of *subsequent* requests — and a per-request cost model
attributes that nowhere. If those 1,187 items were independent single calls the bias is second-order; if they
were multi-turn sequences where the cacheable prefix grows, the bias is **first-order and 1.0% could be zero
or negative**. Which shape the run had is not recorded, so the sign is undetermined.

**Two independent reviewers reached this separately**, and the sharper phrasing is worth keeping verbatim: *a
published point estimate whose **sign** is undetermined is not an imprecise claim, it is a claim with no
content beyond its framing. Keeping it published while labelled "unverifiable" is exactly the special
pleading this design exists to police in others — a harness owner who published an accuracy number under the
same conditions would be told to retract it.*

**The accuracy findings are untouched.** 0.6243 against 0.7447 with per-item agreement 0.7346 is not a cost
claim. Withdrawing the routing figure **strengthens** F123's thesis rather than weakening it, because the
comparison's other side disappears.

**Remediation, concretely.** Re-account both arms on the price card's four legs (`fresh_in`, `cached_in`,
`cache_write`, `output`) plus `cache_hit_rate_observed`, attach `Spend` at the **conversation** scope rather
than per request, and republish as an interval. Also: the counterfactual "what would this sequence have cost
unrouted" is **only definable if the context-partitioning policy was recorded**, which is an independent
reason for the ninth harness part.

## Two implementation debts this exposes

**`Spend` has two legs where this project's own price card has four.** The schema carries `fresh_in`,
`cached_in`, `cache_write`, `output`, `cache_hit_rate_observed` and `reusable_cache_tokens`; `spend.LEGS` is
`("prefill", "generation")`. **The cost model cannot express the price card it is priced against.**

**Cost is attached at the wrong scope.** It is a property of a context trajectory, not of a request.

## The standards survey, so it is not repeated

Eight specifications checked against primary sources. **None carries a content digest of a configuration
artifact; all identify by name plus version** — the failure this ledger records twice (a model whose every
declarable field matched another, and a prompt condition called "terse" whose text differed).

| specification | usable | absent |
|---|---|---|
| OTel GenAI semconv | 6 of 9 harness parts as named attributes; zero-code auto-instrumentation | `digest`/`sha256`: **0 occurrences in 122 KB**. No notion of who observed a fact or whether it is verifiable. `gen_ai.prompt.version` is explicitly "any versioning scheme chosen by the application" |
| in-toto Statement v1 | subject identified **purely by digest**; `predicateType` is a URI so third parties extend it; `ResourceDescriptor` already pairs name with digest | no guidance on stating what an attestation does not cover |
| SCITT — **RFC 9943**, Proposed Standard, 2026-06 | issuer mandatory and first-class; conflicting statements from multiple issuers are explicit; **"does not verify statement accuracy — only authenticity"** | subject is an issuer-defined claim, not a digest |
| C2PA 2.1 | hash binding, can cover **a portion**; the only spec with a vocabulary for unverifiable provenance (`unknownProvenance`, well-formed against valid) | no assertion-level trust metadata |
| MCP 2025-06-18 | tool definition: name, title, description, inputSchema, outputSchema, annotations | **no version, hash or digest.** Annotations explicitly untrusted unless the server is. Cannot express "behaviour changed, schema did not" |
| CycloneDX ML-BOM | model and dataset inventory | not per-request; no inference-time configuration |
| MLflow prompt registry | versions immutable | **no content addressing**; model config mutable without a version bump; creator an unverified tag |
| OpenInference | LLM conventions over OTel | hashing: 0 |

## What the two review rounds broke, and what survived

**Four cores did not survive and are dropped rather than standardised.**

1. **Canonicalisation reintroduces the failure in the unsafe direction.** The model consumes **tokens, not
   semantics**: a tool schema embedded in the prompt pretty-printed in one deployment and minified in another
   is two different token sequences, and JCS gives them **the same digest**. Applying JCS to a captured wire
   body also alters it away from what was sent. Fix: **hash raw bytes for anything the model consumes**,
   canonicalise only control-plane facts and say so, carry the **capture point** on every digest, and read
   digest inequality as **"unknown", never "different meaning"**.
2. **The cohort line is not a property of a fact.** Dynamically discovered tool schemas and a live example
   corpus both sit on it. The rule becomes "anything the protocol holds fixed before workloads are assigned
   and that can change the outcome distribution", and the honest consequence is that **a dynamic harness may
   have no defensible cohort until its dependencies are frozen**.
3. **A pushed fact can only subtract confidence.** A session caches `tools/list` at connect time and runs
   after the owner's signed change window; the receiver records the new version and the run used the old one
   — **undetectably**, because absence of observation is the channel's admission criterion. So a pushed fact
   without a run-time-observable discriminator may only **widen** a verdict to unknown, never narrow one or be
   recorded as the value used.
4. **No comparability policy prevents loosening, only quiet loosening.** The smallest useful form is
   default-deny over the **union** of both runs' coverage lists, with waivers enumerated in the verdict and
   the policy content-addressed and dated. It **converts a false guarantee into an auditable confession** and
   should be described that way.

**What survived every attack, and is therefore what to build:** raw bytes at the capture point with no
canonicalisation; a published list of the parts not captured; and cost at conversation scope on four legs.
**No cohort digest in the record** — grouping is a downstream analysis whose key is enumerated per analysis.
**No pushed-fact channel** — an unobservable change is recorded as unobserved.

**One genuine divergence between the reviewers, left open rather than papered over.** Whether the cohort
manifest should be pre-registered and signed (one view) or absent from the record with grouping done post hoc
(the other). Both concede the full design only ever made tuning **loud**, not impossible. That single question
is the next thing to settle.

## F125 — The protocol is named Surround, and the four consumers do NOT need the same information

Requested: name the protocol provisionally, take whatever is takeable as-is, leave the use of it to the
judge, and settle whether the information a log needs and the information routing needs have to be the same
set — accepting some flexibility rather than a rigid thing nobody can use.

**Design in `docs/DESIGN-surround-protocol.md`. Reviewed once by Fable 5.1 and GPT-5.6 sol, independently. Two
findings were fatal and the document was rewritten.**

### The answer to the question asked

**The four consumers cannot need the same set, for a structural reason.** Routing decides before the call; a
trajectory exists only after it. The axis is already in the code — `quantity.AVAILABILITY` — and
`Quantity.usable_before_generating()` is already derived from its order rather than from a list of the good
values, because the first version of that predicate excluded `during_compute` and reported this study's own
readout as useless to its own gate.

So the bar differs by **what being wrong costs**: a bad route is one avoidable escalation, bounded and priced
and recoverable next call, so it proceeds on a partial record. A bad verdict is a published false claim,
unbounded and not recoverable, so it refuses. **One bar for both is wrong in both directions**: strict enough
for the verdict and routing stops serving traffic whenever a part is missing, which is most of the time since
four of the eight parts still have no collector (T8); loose enough for routing and a verdict is published on a
partial record, which is what F124 withdrew a number for.

### The sentence both reviewers rejected, and the object it confused

The draft said "collection never refuses; the judge refuses". That conflates two refusals about different
objects, and the correct form is:

> **Execution never refuses because of collection. A record may still be refused as a record.**

**Toward the sender the collector is maximally permissive; about itself it must be exact.** The defect that
forces it: **a collector cannot record its own absence.** Not only the crude case where nothing is emitted —
the case that would have shipped is shim version N+1 losing the ability to read `decoding` and writing the
same absence reason it writes when the sender genuinely sent none. Every consumer then behaves exactly as
designed while the regression stays invisible. **A closed vocabulary constrains spelling, not truth.**

Four additions, and they are the minimum that makes an absence checkable: an envelope created before any part
is extracted carrying `complete` / `aborted` / `collector_failed`; absence reasons that say **whose** absence
it is (`not_provided`, `not_reachable`, `extraction_failed`, `redacted`, `not_observable`); a shim capability
manifest, so `not_reachable` becomes checkable and a manifest claiming a part the record reports absent is a
contradiction; and a contradiction mark when a pushed claim and an observation disagree **inside one record**
(owner pushes `turn_budget: 5`, transcript shows nine turns — both facts are in one hand and deferring the
join discards it for free). This is SCITT's own separation applied to the collector rather than only to the
sender, which the draft borrowed and then failed to use on itself.

### The fatal finding: the router leaks into the judge, and the reviewers split on the object

Two runs identical on every identifying part; run A's shim reached `context_partitioning` and run B's did not.
The router falls back for B and sends it elsewhere. **The judge compares them as the same surround, because
nothing it keys identity on differs**, and publishes a delta that is an artefact of missingness — correlated
with whichever side has the weaker shim.

One reviewer proposed a tenth harness part keyed into identity. **That is wrong and the other reviewer said
why**: a routing decision is not something around the model, it is the **treatment assignment**. Keying it
into harness identity would make two runs of one harness sent to two destinations count as different
harnesses, destroying the grouping the identifier exists to provide. And recording the fallback does not
remove the confounding: missingness changed which model was tried, how many attempts ran, what context
accumulated and what it cost, and adaptive escalation loads the harder requests into the later tiers — so
judging only the final attempt hides the cheap model's failures while keeping some of their cost.

It is therefore a **separate object**: assignment provenance, mandatory for the judge, invisible to the
router's bar. Per attempt: policy digest, the facts consulted **and their missingness**, the fallback applied,
the destination, the attempt number and parent, the termination reason, and the selection probability when
randomised. The judge may then **refuse a model-against-model claim when assignment depended on state nobody
recorded**.

### `tool_behaviour -> not_observable` was too strong, and the veto that replaced it was unsound

The classification is true of a tool as a *function* and false of a tool *restricted to the inputs actually
exercised* — and those are bytes the run produced, the strongest mode in the vocabulary, held here and
contemporaneous. So the part splits: `tool_extension` stays unobservable; `tool_trace` is collected, **may
never key an identity** (a per-run outcome is unique per run), and is **not always collectable** either, since
a client shim cannot see a server-side or provider-managed tool runner.

The draft's veto — equal arguments plus unequal response digest proves different tools — was refuted three
ways, and any one of them is disqualifying:

1. **It could fire against a single run.** Write `k`, then read `k`: equal arguments, unequal responses, one
   run, one tool. The rule said "some call has equal arguments" and **never used the ordering it had already
   collected**.
2. **It fires on essentially every networked tool.** Request ids, timestamps and trace headers sit in response
   bodies, and canonicalisation is refused, so any two runs touching such a tool veto each other. An
   always-firing veto means the judge can never publish for a harness with a real tool — **the pathway
   destroys itself**.
3. **The conclusion was false even when firing is right.** A clock, a live search, a moved index: blocking the
   comparison is correct and "different tools, proven" is not what was observed.

Restated: **equal effective invocation context and an unequal stable projection of the response establish a
divergence in recorded execution**, for that invocation and nothing else — where the context is the trace
prefix, the arguments, the credentials class and the attempt number, and the projection is over the response
**as rendered to the model**. Graded rather than absolute: automatic veto only where the tool's contract
declares determinism over the recorded context, **widen to unknown** for a stochastic or mutable tool, no veto
for a known-volatile field.

**One-sidedness survives, and a review case proves it**: two serialisations of the same logical arguments make
the arguments compare unequal, so the veto misses a real difference. That miss is safe **only** because the
rule can refuse and can never authorise.

### Three boundaries, so a digest says what it is a digest of

Refusing canonicalisation is right and is not sufficient, because three things were being called "the bytes":
`transport`, `parsed`, and `model_visible`. **Only a `model_visible` digest may support a claim that two runs
had the same input.** A canonical digest is permitted as an **index** that may narrow candidates and may never
authorise a comparison — the same one-sided shape as the veto. Two SDK versions can serialise differently and
decode to an identical model-visible string; two strings that canonicalise to one JSON value can behave
differently embedded verbatim in a prompt.

### The fourth consumer, and one arithmetic error worth recording

Both reviewers named a consumer the draft missed: the **replayer**, whose bar is genuinely distinct — it needs
bytes where the judge needs digests, and refuses on missing payloads rather than on missing identity. Naming it
is the whole action; the mistake it prevents is folding its requirements into the log because the log happens
to be the thing that stores things.

And the draft said "nine parts" while listing ten, then wrote a done-when condition about eight. **A protocol
whose own part inventory is inconsistent cannot enumerate an absence**, which is the entire mechanism above.
Ten parts.

## F126 — An absence now says WHOSE it is, and the collector attests its own reach

Closes T15. `harness.py` had one undifferentiated hole: a part was present or it was not. The failure that
makes this worth building is not the crude one where nothing is emitted — it is the one that would have
shipped:

> A collector loses the ability to read `decoding` because an SDK renamed a field. It writes the same absence
> it writes when the sender genuinely sent no decoding settings. The router falls back, the judge refuses, and
> **every consumer behaves exactly as designed while the regression is invisible.**

**A closed vocabulary constrains spelling, not truth.** The first design said the vocabulary made holes
visible, and nothing checked whether a hole's reason was true.

### What was built

`ABSENCE_REASONS` in the leaf, with `ABSENCE_BLAMES` in `harness.py` as a **total** classification over it, so
a reason added without deciding whose absence it is breaks a test:

| reason | blames | what it means |
|---|---|---|
| `not_provided` | sender | the sender sent nothing |
| `not_reachable` | **collector** | this collector, here, cannot see a thing that may well be there |
| `extraction_failed` | **collector** | it was there and we failed |
| `redacted` | sender | deliberately withheld — a fact about policy, not the run |
| `not_observable` | nobody | structural. A tool's implementation behind an unchanged schema |

`COLLECTION_STATUS` (`complete` / `aborted` / `collector_failed`), so **a collector that died cannot present
its failure as the sender's silence**. Anything but `complete` stays fully usable as a log and is refused a
verdict.

`Manifest` — the collector's claim about which parts it can reach here. This is SCITT's own separation
(who said this against is this true) **applied to the collector instead of only to the harness owner**, which
the first design borrowed and then failed to use on itself. It makes `not_reachable` checkable: a manifest
claiming a part the record does not carry is a **contradiction**, not a fact, and `Collection.why_not()` says
so.

`Collection` — permissive toward the sender, exact about itself. A record with one part is valid; a record
with nothing identifying still exists and supports no claim. Refusals: a part held **and** absent at once (a
record that answers "was this collected" two ways), two absences sharing a kind, a reachable part recorded as
structurally invisible (**the direction that matters** — it makes our failure look like a fact about the
world), an unobservable part blamed on somebody, a collector-blamed absence with no detail (a measurement
failure nobody described is one nobody can fix), and a manifest claiming a part no mode reaches (it would
raise a contradiction on every run and train a reader to ignore the signal).

`unaccounted` is kept distinct from `absences` on purpose: **an absence is a statement, and unaccounted is the
silence an absence was invented to replace.** A record with an empty `absences` and eight unaccounted parts
looks like a bare harness and is a collector nobody finished.

### Wired to a production caller

`harness.py` had **no production caller** — only tests, which is coverage in appearance only. It now has one:
`tierbook collect-harness`, which prints each held part, each absence with whose it is, what is ours to fix,
what is unaccounted, and one sentence naming what stands between the record and a claim. Exit 2 when the
record is well formed and cannot support a claim, matching `registered-criteria`: that is a finding about the
record rather than an error in the input.

Adding the door failed an existing guard immediately — `test_the_module_docstrings_verb_list_matches_help`
compares the module docstring's verb list against argparse's own subcommand list. Working as designed.

### Verified by breaking it

Five mutations, all caught: removing the contradiction check, dropping `status` from admissibility, letting a
collector-blamed absence omit its detail, permitting held-and-absent at once, and allowing an unobservable
part to be blamed on somebody. Suite: **1,699 passing, 3 skipped.**

### The audit the new rule demands, and its one hit

Every new rule gets checked against existing code. `decide.GAP_REASONS` has four entries and **none of them
is blamed**, and one is the identical ambiguity: `uncollected_variable` does not distinguish "the state did
not carry it" from "we failed to collect it".

**It is a reporting gap and not a correctness defect**, and the reason is worth writing down: `observe.py`
documents that an absent variable becomes `uncollected_variable` and the decision declines to certify — so
**both readings produce the same conservative outcome there.** Fourteen references, no wrong answer among
them. Blaming that vocabulary is recorded as T18 rather than done here, because churning fourteen sites to
improve a message that already fails safe is the over-engineering the v0.4.0 policy exists to stop.

## F127 — A comparison whose arms were missing different facts is refused, not performed

Closes T16, and closes it **much smaller than the design asked for**, which is the finding.

The design (F125) listed what assignment provenance had to carry: policy digest, the facts consulted and
their missingness, the fallback applied, the destination, the attempt number and parent, the termination
reason, the selection probability when randomised. **Checking the record first, almost all of it was already
there.** `record.Decision` carries `policy_digest`, `policy_version`, `chosen`, `selection_probability`,
`exploration`, `state_ref` and `gaps`; `escalate.Escalation` carries `parent_request_id`, `decision_id` and
`hop_count`. Missingness is already reported through the existing `gaps` channel, whose vocabulary
(`decide.GAP_REASONS`) already has `uncollected_variable` for exactly this.

**What was missing was not a field. It was the refusal.** Nothing stopped a model-against-model claim from
being published over two arms that did not have the same facts available.

### The failure, in the shape review found it

Two runs identical on every part their identity is keyed on. One collector reached a fact, the other did not.
The router falls back for the second arm and sends it somewhere else. **Nothing the verdict keys on differs**,
so the verdict is published — and the delta it reports is an artefact of missingness, systematically
correlated with whichever arm was collected worse. Adaptive escalation makes it worse: the harder items load
into the later tiers, so judging only the final attempt hides the cheap candidate's failures while keeping
part of their cost.

**Recording the fallback does not close it**, and that is the sentence worth keeping: recording puts the fact
in the log, and the log is not where a verdict reads admission from.

### What was built

`Run.assignment_gaps`, in the same shape as `elicitation` — `None` means nobody recorded it, left
representable because refusing it would make the mechanism unusable on the data that already exists.

`gap_keys` normalises a decision's gap strings by dropping the value: `uncollected_variable: queue_depth -- 41`
and `-- 12` are one gap seen twice, and comparing raw strings would call two arms incomparable because a number
moved.

`refuse_differential_missingness`, called from `compare()` beside the refusals already there for mismatched
item lists, substituted elicitations and incommensurable cost units. Three outcomes:

| arms | outcome |
|---|---|
| the same facts missing on both | compared |
| **different facts missing** | refused — part of the difference was caused by the gap rather than chosen by the policy |
| **one recorded, one did not** | refused — an unrecorded arm is not an arm with no gaps, and the arm collected worse is the one most likely to have recorded nothing |
| neither recorded | compared, because refusing would refuse every run written before the field existed |

Production caller: `tierbook admit-comparison`, exit 2 when both arms are well formed and cannot be compared.

### This would have caught the withdrawn number

F124 withdrew the 1.0% routing saving because the run's shape was not recorded and the sign is therefore
undetermined. **The same record gap is what this refusal keys on.** Had it existed, the comparison would have
been refused rather than published and later withdrawn — which is the difference between a mechanism that
catches a defect and a ledger that records one.

### Verified by breaking it

Four mutations, all caught: removing the call from `compare()`, allowing differing gap sets, reading an
unrecorded arm as empty, and letting `gap_keys` keep the value. Suite: **1,705 passing, 3 skipped.**

Two guesses were made writing the tests and both failed immediately rather than silently — `OperatingPoint`
was not in the test module's namespace, and `Comparison` has `items` rather than `n`. Recorded because the
standing rule is to verify a name before using it, and the rule was not followed here.

### The audit, and its miss

One other `compare` exists — `reproduce.compare`, over two collections of the same matrix. **The rule does not
apply there**, and the reason is worth stating rather than leaving as a silence: that function checks a run
against its own repeat, so differential missingness between the two is a finding about reproducibility rather
than a confound in an assignment. Nothing else in the package forms a model-against-model claim.

## F128 — A digest says which of three things it is a digest of

Closes T17. Three different objects were all being called "the bytes", and the two mistakes they cause run in
**opposite directions**, so neither is fixed by being careful:

| boundary | what it is | keying an identity on it |
|---|---|---|
| `transport` | what a client put on the wire | **splits runs that were identical** -- two client versions serialise differently and decode to the same text |
| `parsed` | the protocol value after decoding | **merges runs that were not** -- two strings that canonicalise to one value can behave differently embedded verbatim in a prompt |
| `model_visible` | the exact text the model read | the only one that can support "these two runs had the same input" |

`DIGEST_BOUNDARIES` and `IDENTIFYING_BOUNDARIES` in the leaf; `Part.boundary` carrying it, defaulting to
`model_visible` because that is **the true statement about every existing caller** (the instruction text, the
tool schemas as sent) rather than a plausible-looking default. A digest over anything else is recorded and
refused an identity.

### One piece of machinery was built and then deleted

The first version also hashed the boundary into `Harness.identity`, so that two digests of different things
could not collide under one name. **That is variation which cannot occur**: every part entering an identity has
already been refused unless its boundary is `model_visible`, so the extra term was dead. The refusal is the
mechanism and the hash was decoration; it was reverted.

It surfaced because the test written for it asserted a string the test had built itself, which checks nothing.
Rewriting that test to pin the real claim -- **there is no way to construct an identifying part on another
boundary** -- is what showed the code under it was unreachable.

### The audit: this is the second instance of one shape

`judge.DIGEST_SUBJECTS` is the same idea under another name. It is `("published_weights",)` with
`loaded_tensors` in `REFUSED_KEYS`, for the same reason: an engine fuses projections and changes dtypes and
shardings, so a digest of what was loaded is a digest of a different object than what was published.

**So the rule was already here once, and nobody noticed it generalised.** Merging the two vocabularies is not
done: they name boundaries in different domains (a served model's weights against a request's text), and
collapsing them would produce one list whose entries are only alike in shape. Recorded so the third instance is
recognised as a class rather than fixed again as an instance.

### Verified by breaking it

Three mutations, all caught: allowing an identifying part on any boundary, allowing an unknown boundary, and
changing the default to the wire format -- the last failing 17 tests, which is the default being load-bearing
rather than cosmetic. Suite: **1,710 passing, 3 skipped.**

## F129 — The cost model can now express the price card it is priced against

Closes T11. `spend.LEGS` was `("prefill", "generation")` and the schema's `price_card` bills four:
`fresh_in`, `cached_in`, `cache_write`, `output`. **The cost model could not represent its own price card**, and
every cache-related conclusion sits on that.

**Why the split is not cosmetic.** The cache discount attaches to the **shape** of a request, not to its text:
identical content sent as one long message measured a **0%** cache rate where the same content as a growing
conversation measured **99.9%**. So two runs can send the same words, be billed on different legs, and differ by
most of the input side — and a cost model that cannot say which leg was charged reports that as a difference
between the arms.

### What was built

`BILLED_LEGS`, and `Spend.cached_in` / `Spend.cache_write` as `float | None`, **all-or-nothing**: one recorded
without the other leaves a fresh remainder wrong by exactly the leg omitted. They are **parts of** the input
cost rather than additions to it, so a caller adding them on top is refused for double-charging the tokens the
cache served. `fresh_in` is derived, so it cannot disagree.

`None` on both means the legs were never split — the state of every cost recorded before this, left
representable because refusing it would make the module unusable on the data that exists. **An unrecorded split
is not a zero cache rate**, and the printed form distinguishes the two.

`refuse_mixed_cache`, called from `avoided`, with three outcomes: a cached arm against a fresh one is refused; a
recorded split against an unrecorded one is refused; both unrecorded still subtract.

### The refusal had to arrive at the verdict, not just exist

`avoided` is reached from `counterfactual.compare` through `_leg_deltas`, and what it subtracts is
`Run.spend_per_item` — **a mean over items**. That mean was dropping the cache legs entirely, so the guard would
never have fired on a real comparison. It now carries them **only when every cell recorded them**: a mean over a
mixture would put the unsplit cells' whole input cost into the fresh leg, which is the direction that makes a
cache effect look like a saving.

The end-to-end test compares two priced arms through `compare` rather than calling the guard directly, because
**a guard that only fires when a test calls it is a guard nothing depends on**.

### This is the second half of what withdrew the 1.0%

F124 withdrew the routing saving because routing breaks a cache prefix, so one decision changes which leg the
*next* request is billed on — and with no record of the shape the sign is undetermined rather than imprecise.
F127 gave the refusal for arms missing different facts; this gives the one for arms billed on different legs.
**Neither existed when the number was published.**

What is still missing is T12: cost is attached per request, and cache eligibility depends on the previous call
in the same context. The legs now exist; the scope does not.

### Verified by breaking it

Six mutations, all caught: removing the call from `avoided`, dropping either half of the refusal, unpairing the
two legs, letting them exceed the input side, and letting a mixed mean claim a split. Suite: **1,724 passing,
3 skipped.**

## F130 — Cost at conversation scope, and the one invariant that is arithmetic

Closes T12, and closes the recordable half only — the part that is genuinely blocked is named at the end rather
than papered over.

**A per-request cost is incomplete by construction.** Whether a turn's input is billed as a cache read depends on
the turn *before* it in the same context, so the cheapest turn in a sequence is cheap because an earlier one paid
to populate the cache. Attributing that discount to the turn that received it credits the wrong request, and
subtracting two such turns from different sequences subtracts two numbers that mean different things.

### `Conversation`, and the invariant worth having

`Conversation(context, turns)` with `total` over the sequence, and four refusals — no context identifier (nothing
says which turns shared a cache prefix), no turns, mixed units, and turns that disagree about whether they are
split (a total over that mixture would put the unrecorded turns' whole input into the fresh leg).

The fifth is the one that is **arithmetic rather than convention**: **the first turn of a context cannot have been
served from a cache belonging to it**, because nothing was in the context before it. A record that says otherwise
is either mis-ordered or is charging another context's cache to this one, and in both cases the discount is
credited to a turn that did not earn it.

`paid_for_nothing` is **reported rather than refused**: a single turn that paid a cache write bought a discount
for a turn that never came. That is a real thing that happens and the record should show it.

### `refuse_incomparable_shapes` — the check the withdrawn number needed

Two sequences of different length are not two prices for the same work. The measured reason is the same one
throughout: identical content billed **0%** as one long message and **99.9%** as a growing conversation, so most
of the difference between a one-turn arm and a five-turn arm is the number of turns. **Routing changes the shape
of every turn after the one it moved**, which is why a routing verdict is exactly the claim that needs this.

Production caller: `tierbook conversation-cost`, which prices one sequence or refuses a pair. The three input
legs are taken separately and summed into the input side, because asking an operator for a total *and* two of its
parts lets the three disagree.

### What this does NOT settle, and why it is not a gap in this entry

**The counterfactual.** "What would this have cost unrouted" needs to know how many contexts exist and what
crosses between them, which is the context-partitioning policy — T13, still open. This type makes the **shape
recordable**; it does not make the **alternative computable**. T10's note stands: if a published run's shape was
never recorded, there may be no defensible replacement figure, and leaving it withdrawn is then the correct end
state rather than a gap.

### Verified by breaking it

Six mutations, all caught: letting the first turn claim a cache read, totalling mixed splits, totalling mixed
units, allowing an empty conversation, comparing different lengths, and dropping the write from
`paid_for_nothing`. Suite: **1,734 passing, 3 skipped.**

## F131 — The ninth harness part, priced: counting contexts is not enough

Closes T13. `context_partitioning` is now the ninth part in `HARNESS_PARTS`, classified `pushed_by_owner` for the
same reason `loop` is: how many contexts a caller keeps and what it copies between them is a property of their
scaffold, and we see one request at a time and cannot tell a second context from a second conversation in the
first.

Adding it broke a test immediately — the enumeration of unrecorded parts. **That is the total classification
working**: a part cannot be added without every place that enumerates parts being made to agree.

### Counting contexts is not enough, and that is the whole point of the second field

`Partitioning(contexts, crosses)` with `CONTEXT_CROSSINGS = ("nothing", "briefs_and_results", "whole_history")`,
because **the three have opposite economics**:

| crossing | what it costs |
|---|---|
| `nothing` | two independent runs |
| `briefs_and_results` | both caches stay warm, because neither context ever switches model. **This is the arrangement the published 39.2% rests on** |
| `whole_history` | the transcript is copied, so the **entire prefix is billed as fresh input in the second context** — the split costs more than not splitting |

**A record that counts contexts without saying what crossed cannot tell the third from the second**, and they
differ in sign. `duplicates_prefix` names it.

One context with something crossing it is refused: there is nothing for it to cross to, so either a second
context went unrecorded — and then the fresh input it was billed is attributed to the first — or the crossing
describes something that did not happen.

### The counterfactual is now definable, and refused when it is not

`refuse_undefined_counterfactual` refuses to state what an alternative would have cost when either side's
partitioning is unrecorded. The wording is deliberate: **undefined rather than uncertain**, because the two have
different remedies. An unmeasured quantity can be measured later from the same record; an undefined one cannot,
because **the record does not contain the question**.

It also refuses an alternative that copies a transcript where the actual run did not — that alternative pays the
whole prefix as fresh input in its second context, and the difference would be reported as a cost of whatever the
arms were supposed to differ in.

**This is the refusal T10 asked for.** If a published run's shape was never recorded there may be no defensible
replacement figure, and leaving the 1.0% withdrawn is then the correct end state rather than a gap to be filled
with an assumption.

### Verified by breaking it

Seven mutations, all caught, including deleting the ninth part's sourcing classification. Suite: **1,742 passing,
3 skipped.**

## F132 — Four decisions settled, and checking the record changed one of the answers

### T10 — the withdrawal stands, and the REASON on the record was wrong

F124 withdrew the 1.0% routing saving on the grounds that routing breaks a cache prefix, so the sign is
undetermined, **and that the run's shape was never recorded**. Reading the record rather than the summary of it:

**The shape is determinable and it is single-call.** The 1.0% comes from the thinking-budget comparison, over a
multiple-choice corpus whose readout is `Answer with the option letter only. Do not explain.` There are no turns
in it. **So the cache-prefix objection does not apply to this measurement** — there is no next turn whose input
leg a routing decision could move.

**What disqualifies it is stronger and was already in the same paragraph.** The figure is a saving over **90
shared items**, arrived at after the original 410-item result was found to be a subset artefact. This project's
own rule, added in that same entry, is that a comparison **withholds the verdict below 150 shared items**. 90 is
below 150, so **the 1.0% fails a floor this repository wrote for itself.**

**Resolution: withdrawn, permanently, and the ledger says why.** Not "the shape is unknown" — the shape is known.
"Below our own minimum for a comparison to be reported at all." That is not a gap waiting to be filled; the items
do not exist to fill it with.

The correction matters beyond this number: **the summary of a finding drifted from the finding.** The cache
argument is a real argument and it is attached to the wrong measurement, and it survived two review rounds and
three of my own retellings because everybody was reading the withdrawal note rather than the paragraph it came
from.

### T5 — the estimate, which was the one thing blocking a decision

Measuring the reliability ceiling of an uplift label needs `K=8` repeats of **both** arms on the same items, then
split-half with `r_max = sqrt(rho)`. Priced from figures already measured here:

| leg | figure on the record | for K=8 over 699 items |
|---|---|---|
| box, terse arm | 488 items in about 2 minutes on a node at $15.2174/hour | 23 minutes of node time, **$5.81** |
| strong arm, API | **$0.00325 an item** (the gate-1 corpus) | **$18.17** |
| | | **about $24, and under half an hour of GPU** |

**That is 6.5% of one Hyper-tau-bench pass ($370).** The measurement that decides whether routing has any value
costs a rounding error against the measurements that depend on it, which settles the ordering argument: this one
first, and the expensive ones only if it clears 0.15.

### T14 — the cohort identifier stays out of the record

Reviewers split; taking the option that matches the failures this project actually had. **A name that stays fixed
while the thing under it moves has been recorded twice here** (a model name, and a prompt condition called
"terse"), and a pre-registered signed manifest is the same shape a third time — it can name a cohort that does
not exist. Grouping is enumerated per analysis instead, where the analysis text is the record.

**The rejected option's argument is real and is recorded with it**: pre-registration is the only mechanism that
shows "this was changed afterwards", so **if an external audit is ever in scope, this decision is the one to
revisit.**

### T1 — Hyper-tau-bench gets no split, declared in advance

53 tasks, and the interval on 53 items is already **[0.361, 0.621]**. Halving it leaves 26 items a side, which
cannot support anything. So: **all 53 items as one set, no held-out split, written down before the first run.**

The cost is stated rather than hidden: with no held-out fold, **a policy selected by searching this suite cannot
be reported with a guarantee** — only as a point estimate with the selection named. This repository has already
measured what that costs, at 6.7 points between a point estimate and a selection-valid bound.

### T18 — not doing it, and the reason is the record

`decide.GAP_REASONS` blames none of its four entries and `uncollected_variable` carries the ambiguity F126
closed. **It stays.** `observe.py` documents that an absent variable declines to certify, so both readings land on
the same conservative outcome; 14 references, no wrong answer among them. Rewriting 14 call sites to improve a
message that already fails safe is the over-engineering the v0.4.0 policy exists to stop.

## F133 — The tenth part: the trace is held evidence, and the veto that reads it can only refuse

Closes the last item of the Surround design. `tool_behaviour` was one classification covering **two different
objects**, and calling the whole thing unobservable threw away evidence already in hand.

* `tool_extension` — the function. A tool's implementation can change behind an unchanged schema and nothing in
  the request differs. Unobservable, non-identifying, unchanged.
* `tool_trace` — the same tool **restricted to the inputs actually exercised**. Those are bytes the run itself
  produced: `in_the_request`, the strongest mode in the vocabulary, held here and contemporaneous.

**And the trace may never key an identity, enforced by name rather than by mode.** The sourcing rule alone would
admit it, because we do hold the bytes — but a per-run outcome is unique per run, so keying on it makes every pair
of runs incomparable. That is the same defect the identifier split was introduced to fix, arriving from the other
direction, so `Part.NEVER_IDENTIFYING` excludes it explicitly.

### The veto, restated after three refutations

The draft rule said an equal-argument, unequal-response pair **proved** two runs used different tools. Any one of
the three refutations is disqualifying:

1. **It fires against a single run.** Write a key, then read it: equal arguments, unequal responses, one tool
   behaving correctly. The rule compared arguments and **never used the ordering it had already collected.**
2. **It fires on essentially every networked tool.** Request ids and timestamps sit in response bodies and
   canonicalisation is refused, so any two runs touching such a tool veto each other — and an always-firing veto
   means no harness with a real tool can ever be compared. **The pathway destroys itself.**
3. **The conclusion is false even where firing is right.** A clock or a moved index makes the environments differ
   without the tool changing.

Two calls are now comparable only on the same **occasion** — the tool, the **trace prefix before the call**, the
arguments, the credentials class, and the attempt number. The prefix is what kills refutation 1. The response
digest is over the response **as rendered to the model**, a stable projection rather than the raw body, which is
what kills refutation 2 and is the same rule that governs canonicalisation elsewhere.

And the strength is graded, `DIVERGENCE_LICENSES` total over `TOOL_DETERMINISM`:

| the tool's contract | a divergence licenses |
|---|---|
| `declared_deterministic` | **refuse** — a promise was broken |
| `known_to_vary` | **unknown** — widen the verdict |
| `unstated` | **unknown** — nobody promised anything, so nothing is contradicted |

`known_to_vary` and `unstated` license the same thing and are **separate entries on purpose**: collapsing them
would let a silence be reported as a declared property of the tool.

### One-sidedness, and the test that had to be rewritten to say so

`no_divergence` is **not an authorisation**. Agreement on the occasions both runs exercised says nothing about the
occasions neither touched. The remaining hole is safe only because of this: two serialisations of the same logical
arguments compare unequal, so a genuine difference is **missed** — and a rule that could authorise would turn that
miss into a false licence.

The first test written for this asserted that the outcome string did not contain the substrings `refuse` or
`authorise`, which checks nothing. The claim it should have made is behavioural and now is: **for identical traces
the outcome is the same under every determinism value**, so a stronger contract cannot upgrade agreement into a
licence, and the set of reachable outcomes contains no authorisation.

### Wired, and verified by breaking it

Production caller `tierbook admit-traces`. Exit 2 on a refusal and **0 on `unknown`** — widening a verdict is not
an error, and treating it as one would push a caller toward not recording traces at all.

Renaming the part broke 10 tests immediately, all mechanical, and adding it broke the unrecorded-parts enumeration
again. Six mutations, all caught: letting the trace key an identity, dropping the prefix from the occasion (twice,
in two places), making an unstated promise refuse, allowing a missing digest, and defaulting an unknown
determinism. Suite: **1,755 passing, 3 skipped.**

## Not requirements, deliberately

Kept here so they are not re-proposed as work.

- **A general residual-capture component in tierbook.** The capture is research code and belongs to the study,
  not the mechanism. Building it into tierbook is the over-engineering the policy change exists to stop.
- **A J-lens implementation in tierbook.** Whether the readout is worth anything is unsettled. Nothing goes into
  the mechanism until an experiment asks for it, and no experiment has.
- **Acting on `tenant_scope`.** v0.3.0 records it and says in its own interface that nothing acts on it. No
  experiment has needed it acted on.
