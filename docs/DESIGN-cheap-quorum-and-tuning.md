# Agreement among cheap candidates is a better escalation signal than the box's own doubt, and it is the only part of the terse-decision idea that survived

**Written 2026-09-01**, after two reviews and five measurements taken the same day on the existing matrix at no
cost. It answers two questions that were asked together: how to strengthen the cheap tier as a measured
experiment, and whether the frontier model can be reserved for genuinely-high-intelligence decisions with terse
input and output while everything else is done by the box and mid-priced APIs.

The second question has a sharp answer and it is negative: a terse frontier *decision* is not worth buying, and
a terse frontier *answer* on fewer items is. The measurement that killed the first half is section 3, and it only
died on the frozen fold after looking significant on the first one.

## The shape both families ended up in, stated first because it is the finding

Every construction measured here — arbitration, a quorum, a probe threshold, a cascade that learns when to give
up — costs money and cannot be shown to buy accuracy. On the knowledge corpus the frontier's whole middle band is
owned by **one mid-priced candidate answering everything** (section 3c). On agentic work **no pair of routing
arrangements separates on outcomes at all**, while their prices differ by up to 48-fold (section 6b). Two
independent families, the same shape: machinery adds cost, and the accuracy it is supposed to buy does not appear.

That is the verdict the mechanism was asked to be able to produce, and it produced it. It is worth being precise
about what it does and does not say:

- **It is a statement about these pools at these prices**, which is why the deliverable is `gain(prices)` and an
  optimiser rather than a policy. On a pool whose candidates are further apart, or a rate card where the dear tier
  is dearer, the same code returns a different answer — and sections 3b and 4d are two occasions when it did.
- **It is not "routing never works".** Routing is on the frontier at both ends: quorums own the cheap band from
  81% to 87%, and the probe threshold owns one point at 91.4% that nothing else reaches for the money. What is
  refuted is the assumption that a construction is *better* than the simplest thing, held without measuring the
  simplest thing.
- **The reason the assumption survived so long is a comparison error, not a measurement error.** Every table in
  this document until section 3b fixed the frontier tier as the thing to beat and asked how cheaply its accuracy
  could be approached. Nobody asked which single candidate was cheapest at a given accuracy, though
  `optimise.single_tier` had been in the repository the whole time. **Choosing the baseline is choosing the
  answer.**

## 1. Terse input and output is not where the saving is

The frontier tiers on this corpus spend most of their bill on *output*, but they do not emit much of it: the
median `claude-opus-5` answer is 297 prompt tokens and 63 completion tokens. **Asking for one letter does not
make the reply short**, because reasoning tokens are billed as output and the model spends them whether or not
the answer is one character: measured over 257 hard items, a decision prompt that invites the model to work the
answer out costs $0.01329 against $0.00870 for the same tier answering the same items normally — **53% more, not
less**. The benchmark's 63-token median came from an instruction that suppresses reasoning, and reproducing that
instruction brings the decision down to $0.01052, still dearer than answering.

Showing it only the candidates' letters and not the question would be cheap, but that is weighted voting, and
voting over all nine candidates reaches 89.1% against `claude-opus-5`'s own 89.6%. Counting is not deciding.

**The saving has to come from calling it less often, not from calling it more cheaply.** That reframes the
question as: what is a reliable, cheap certificate that the frontier model is not needed?

## 2. The certificate is agreement, and it beats the incumbent signal at equal cost

Measured over the 1,165 items left after removing the 22 items whose answer key is confirmed wrong
(see [`results-label-audit.md`](results-label-audit.md)):

| cheap pool that answers first | they agree on | accuracy when they agree | ceiling with a perfect arbiter | cost per item |
|---|---|---|---|---|
| `claude-opus-5` answering everything (reference) | — | — | 91.2% | $0.00617 |
| box + `nemotron-super-3-120b` + `qwen3-next-80b` | 47% | **89.7%** | **91.0%** | **$0.00165** |
| box + `grok-4.6` | 66% | 94.4% | 93.6% | $0.00406 |
| those three plus `claude-sonnet-5` | 42% | **97.2%** | 95.4% | $0.00462 |

**When three cheap candidates give the same answer, that answer is right 89.7% of the time — as often as the
frontier model is right on the whole corpus, at a quarter of the price.** Add `claude-sonnet-5` and unanimity
among four is right 97.2% of the time, which is well above anything a single candidate achieves.

The ceiling column is what a *perfect* arbiter would reach on the escalated remainder. It is quoted as a bound
only: section 3 measures a real arbiter and finds it worth nothing, so the operative policy escalates and lets the
dear tier answer.

And the comparison that matters, because the incumbent router rests entirely on the box's own prefill
uncertainty. Escalating to `claude-opus-5` when the box's answer-letter entropy is high, against escalating when
three cheap candidates disagree:

| policy | escalated | accuracy | cost per item |
|---|---|---|---|
| probe threshold at the median | 50% | 85.2% | $0.00454 |
| probe threshold at the 40th percentile | 60% | 87.3% | $0.00509 |
| **three cheap candidates disagree** | **53%** | **87.9%** | **$0.00488** |

**The quorum dominates the probe**: more accurate than the probe router that escalates 60% of items, and cheaper
than it. The box's own doubt says "I do not know"; it carries no information about whether anyone else knows,
which is exactly the mechanism reason a probe reads "everyone can do this" at 0.83 and "nobody can do this" at
0.51. Three independent opinions answer a different question, and it is the one the router needs.

**The three cheap candidates cost $0.00068 for all three.** Running them on every item is 14% of one
`claude-opus-5` call, so there is no cascade to design inside the quorum — buy all three opinions always.

## 3. Arbitration is dead: the calibration fold's effect did not survive the frozen fold

**The registered single evaluation, run on the frozen fold's 338 escalated items:** the arbiter scores 88.5%
against 88.2% for the same tier answering the same items — 9 wins, 8 losses, exact two-sided p = 1.0000. The
calibration fold's +3.5 points at p = 0.035 **did not replicate at all**, and the mid-priced arbiter's apparent
parity reversed in the same way.

| policy over the 687 clean frozen-fold items | accuracy | cost per item | against the frontier tier |
|---|---|---|---|
| `claude-opus-5` answers everything | 92.4% | $0.00593 | — |
| **quorum, then `claude-opus-5` answers the 49% it escalates** | **89.2%** | **$0.00441** | **−26%** |
| quorum, then `claude-opus-5` arbitrates | 89.4% | $0.00657 | +11% |
| quorum, then `claude-sonnet-5` arbitrates | 85.9% – 86.6% | $0.00295 | −50% |

**So the answer to "reserve the expensive model for a terse high-intelligence decision" is no, on this pool.**
Showing the frontier tier three candidate answers changes nothing it does — two points and a tenth on 338 items,
at 57% more money because thinking tokens are billed as output. What pays is not asking it at all: the quorum
stops on half the items and the tier that does get asked simply answers.

**Two effects that looked real on one fold both vanished on the next**, and they vanished in opposite directions:
the frontier arbiter's gain evaporated, the mid-priced arbiter's parity became a 3-point loss. The reason is
visible in the noise floor measured earlier — these tiers flip 3.6% and 5.1% of their answers between identical
runs, which is the same size as the effects being chased. **A single fold cannot see a 3-point effect here, and
the pre-registration is the only reason this was caught rather than shipped.**

What survives is section 2's stopping rule, and it survives well against the *probe*: **89.2% at 74% of the
frontier tier's cost.** Section 3b, written after this one, shows that surviving against the probe is not the
same as being the right policy, and that a single mid-priced candidate dominates this point.

The rest of this section is what the calibration fold showed and how it failed, kept because the failure is the
finding.

### What the calibration fold showed

**Experiment A, run.** On the 257 escalated items of the calibration fold, the arbiter saw the question and the
cheap candidates' letters — unlabelled, order-randomised, free to pick a letter nobody offered — and emitted one
answer. The registered bar was to beat the same tier simply answering those items, which scores 82.9%.

| arbiter | accuracy on the escalated items | wins / losses against answering | cost per escalated item |
|---|---|---|---|
| `claude-opus-5`, invited to reason | **86.4%** | 12 / 3, exact p = 0.035 | $0.01329 |
| `claude-opus-5`, terse instruction | 85.2% | 8 / 2, p = 0.11 | $0.01052 |
| the same tier answering, no proposals | 82.9% | — | $0.00870 |
| a perfect chooser among the proposals | 74.7% | — | — |
| a perfect chooser allowed its own answer too | 90.7% | — | — |

**The anchoring risk did not materialise.** Seeing three answers, mostly wrong, made the frontier tier *better*
than answering unaided, by 3.5 points with a paired p of 0.035. It stayed inside the proposals on 82% of items,
and the 74.7% ceiling for choosing only among proposals confirms that the gain comes from being allowed to
override all three.

**None of that replicated.** It is recorded because the shape of the mistake is instructive: a paired test at
p = 0.035 on 257 items, with a mechanism story that fit ("it is allowed to override all three"), and it was
noise. On the frozen fold the same wording, same tier, same quorum gives 9 wins and 8 losses.

**And the whole policy was already unfavourable even taking the calibration numbers at face value:**

| policy over the 478 clean calibration items | accuracy | cost per item | against the frontier tier |
|---|---|---|---|
| `claude-opus-5` answers everything | 89.5% | $0.00652 | — |
| quorum, then `claude-opus-5` answers the 54% it escalates | 86.0% | $0.00540 | −17% |
| quorum, then `claude-opus-5` arbitrates, terse | 87.2% | $0.00638 | −2% |
| quorum, then `claude-opus-5` arbitrates, reasoning | 87.9% | $0.00787 | **+21%** |
| **quorum, then `claude-sonnet-5` arbitrates, reasoning** | **85.1% – 86.8%** | **$0.00232** | **−64%** |

**So the answer to "use the expensive model only for the genuinely hard decision" is yes, and the decider should
not be the expensive model.** A mid-priced arbiter reaches the same accuracy as escalating to the frontier tier
and letting it answer, for a third of that policy's cost and just over a third of the frontier tier's. The
frontier tier's role on this pool at these prices collapses to nothing: it buys 2.7 to 4.4 accuracy points for
2.8 times the money.

The `claude-sonnet-5` figure is a range because 8 of its 257 replies came back as an **empty stream** — content
of zero length with no finish reason — which is the same gateway defect this design ranks as the first piece of
work. The range's floor scores those 8 as wrong and its ceiling as right.

**Two gateway defects were found by running this**, both recorded because they distort measurement rather than
merely annoy:

- A reply truncated at the token limit returns **empty content and is billed in full**. Before this was noticed,
  36% of one arm's replies were empty and the arm appeared to score 60.7%. An experiment that does not record
  `finish_reason` cannot see this.
- The streaming path **emits no usage block** even when `stream_options.include_usage` is set, so a streamed call
  cannot be costed from its own response. The rows affected here are priced at the arm's median instead.

## 3b. The optimiser was built, and its first act was to overturn section 3

Added 2026-09-01, after section 3's conclusion was written. `tierbook.quorum` enumerates every policy
— every subset of candidates as the quorum, every candidate as the escalation tier — prices each one
against a rate card, and returns the ones nothing dominates. Run on the same frozen fold, it reproduces
the reported point exactly (51% stop, 90.3% accuracy on agreement, 89.2% overall, $0.00441), and then
says the point should not have been reported:

| policy | accuracy | cost per item |
|---|---|---|
| what section 3 recommends: three cheap candidates, escalating to `claude-opus-5` | 89.2% | $0.00441 |
| **`grok-4.6` answering everything** | **89.7%** | **$0.00333** |

**A single mid-priced candidate is more accurate and 24% cheaper than the whole construction** on this
run. **Section 3d withdraws that specific recommendation**: asked a second time the comparison reverses,
because the candidate's own output length doubled between collections. The comparison *error* below
stands; the replacement answer does not.

The reason the earlier sections missed it is worth naming, because it is a comparison error and not a
measurement error. Every table above fixes `claude-opus-5` as the thing to beat and asks how cheaply
its accuracy can be approached. Nobody asked the other question — **which single candidate is cheapest
at a given accuracy** — even though `optimise.single_tier` has existed in this repository the whole
time. Choosing the baseline is choosing the answer, and one baseline was chosen and never revisited.

The full frontier over nine candidates at this rate card, and it is mostly single candidates:

| policy | stop | accuracy | cost per item |
|---|---|---|---|
| `gpt-5.6-terra` alone | 100% | 85.0% | $0.00251 |
| `claude-sonnet-5` alone | 98% | 87.2% | $0.00322 |
| **`grok-4.6` alone** | 99% | **89.7%** | **$0.00333** |
| `claude-opus-5` alone | 100% | 92.4% | $0.00593 |
| `claude-sonnet-5` + `nemotron-super-3-120b` + `qwen3-next-80b`, escalating to `claude-opus-5` | 51% | **92.7%** | $0.00708 |
| `claude-opus-5` + `grok-4.6`, escalating to `claude-fable-5` | 90% | 93.4% | $0.01138 |

**Where the quorum does earn its place is above the best single candidate, not below it.** 92.7% is
higher than anything one candidate reaches here, and it costs 19% more than `claude-opus-5` alone to
get 0.3 points — which is inside these tiers' own 3.6% to 5.1% run-to-run flip rate, so it is not a
difference this fold can resolve. The two quorum points at the cheap end (81% and 87%) are real and
are the only place the rule is clearly the right tool.

**What stands from section 3, and what does not.** The measurement that agreement beats the box's own
prefill probe at equal cost stands: those are two escalation *signals* compared against each other,
and the quorum won. What does not stand is the implied conclusion that the resulting policy is what to
ship. Comparing two signals says which signal is better; it does not say a signal is needed.

**And this is the argument for building the mechanism rather than reporting the optimum.** Both were
asked for; only one of them catches this. The mechanism found in one run, at no measurement cost, an
error that three rounds of adversarial review over the same numbers did not — because the reviewers
were reviewing the analysis and the optimiser was enumerating the alternatives.

## 3c. All three mechanisms on one frontier, and none of them dominates

Added 2026-09-01, after 3b. A frontier that cannot express a mechanism cannot rule it out either, and
3b's error was exactly that: the quorum was compared against a probe threshold and against the dear
tier answering everything, while a single candidate answering everything was never enumerated. So the
optimiser now enumerates all three shapes and ranks them together — 1,620 policies over nine
candidates on the frozen fold, at no measurement cost.

A **signal** policy is strictly more expressive than a one-member quorum and had to be added for that
reason: a lone candidate always agrees with itself and so can never escalate, whereas a threshold
escalates exactly the items the signal flags. Reading the signal is charged at $0.00024, and an item
with no reading escalates rather than defaulting to confident — defaulting the other way sends
unmeasured items to the cheap tier, which is the direction that flatters the policy.

The frontier, one row per mechanism that owns a region:

| region | mechanism | policy | accuracy | cost per item |
|---|---|---|---|---|
| cheapest | single | the box, escalation never fires | 66.7% | $0.00010 |
| cheap | quorum | box + `nemotron-super-3-120b` → `gpt-5.6-terra` | 81.1% | $0.00154 |
| cheap | quorum | box + two cheap APIs → `grok-4.6` | 87.0% | $0.00258 |
| **middle** | **single** | **`grok-4.6` answering everything** | **89.7%** | **$0.00333** |
| upper | signal | the box, escalating the 80% of items its probe flags → `claude-opus-5` | 91.4% | $0.00571 |
| upper | single | `claude-opus-5` answering everything | 92.4% | $0.00593 |
| top | quorum | `claude-sonnet-5` + two cheap APIs → `claude-opus-5` | 92.7% | $0.00708 |
| top | single | `claude-opus-5` + `grok-4.6` → `claude-fable-5` | 93.4% | $0.01138 |

**Fourteen frontier points are single candidates, nine are quorums, five are signal thresholds.** So
the answer to "which mechanism should the router use" is: *it depends on the accuracy you need*, and
the mechanism's job is to say which one at which floor rather than to have a favourite.

Three readings worth keeping.

**A single mid-priced candidate owns the middle outright.** From $0.00258 to $0.00510 nothing beats
`grok-4.6` answering everything, and that band is where most of the interesting operating points sit.
Any construction proposed in that region has to beat 89.7% at $0.00333 or it is not a candidate.

**The incumbent probe router is on the frontier, at one point, and it is a high-escalation one.** Its
best surviving configuration escalates **80%** of items — the box handles only a fifth — reaching
91.4% at $0.00571, which beats the best quorum at the same cost by 0.6 points. That is a real result
for the probe and a narrow one: the signal earns its place only where you want more accuracy than any
single candidate below `claude-opus-5` delivers, and it earns it by mostly getting out of the way.

**The machinery's own sanity check passes.** `box → opus, escalating 100%` scores 92.4% at $0.00627
against `opus alone` at 92.4% for $0.00593: identical accuracy, dearer by exactly the wasted box
call, and correctly excluded from the frontier. A pricing bug would have shown up here as the
degenerate policy winning.

## 3d. The frontier was measured twice, and its recommendation does not reproduce

Added 2026-09-01. Section 3b's correction — that a single mid-priced candidate dominates the quorum
policy — rested on one run and turned on half a point, which is inside the flip rate these tiers were
separately measured to have. So the matrix was collected again at the same configuration and the
frontier recomputed on both. 571 items are complete in both runs across the eight API candidates; the
self-hosted box is absent because it is not currently served, so this covers the all-API subset.
Spend: about $18.

**The flip rates reproduce the earlier noise-floor measurement closely, which is the one solid result
here:**

| candidate | run 1 | run 2 | flip rate | measured separately earlier |
|---|---|---|---|---|
| `claude-fable-5` | 94.9% | 94.7% | 0.9% | 2.9% |
| `claude-opus-5` | 94.6% | 93.9% | 1.8% | 3.6% |
| `claude-sonnet-5` | 90.4% | 92.5% | 3.2% | 5.1% |
| `gpt-5.6-sol` | 91.1% | 90.7% | 3.2% | 6.6% |
| `gpt-5.6-terra` | 88.4% | 89.3% | 4.0% | 5.1% |
| `grok-4.6` | 92.5% | 93.0% | 3.7% | 9.3% |
| `qwen3-next-80b` | 72.3% | 75.8% | **10.9%** | 10.2% |
| `nemotron-super-3-120b` | 61.5% | 64.1% | **24.0%** | 22.3% |
| pooled | — | — | **6.4%** | 8.0% |

Two independent measurements, months apart in method, agree on the ordering and on the two large
values. The weak candidates are a fifth of their own answers away from themselves.

**And the frontier's recommendation differs between the runs at half the floors tested:**

| accuracy floor | cheapest policy, run 1 | cheapest policy, run 2 | same? |
|---|---|---|---|
| 85% | `nemotron` + `qwen3-next` → `gpt-5.6-terra`, $0.00115 | the same, $0.00122 | yes |
| 88% | `gpt-5.6-terra` alone, $0.00165 | `nemotron` + `qwen3-next` → `claude-sonnet-5`, $0.00140 | **no** |
| 90% | `claude-sonnet-5` alone, $0.00170 | `claude-sonnet-5` alone, $0.00169 | same member |
| 92% | `gpt-5.6-terra` + `qwen3-next` → `grok-4.6`, $0.00291 | `claude-sonnet-5` alone, $0.00169 | **no** |

At 88% and 92% the answer changes materially — a single candidate becomes a two-member quorum, and a
quorum becomes a single candidate. The mechanism is the same, the prices are the same, and the data is
the same corpus asked twice. What moves is a candidate whose accuracy sits near the floor crossing it:
`claude-sonnet-5` reads 90.4% in run 1 and 92.5% in run 2, so it clears a 92% floor in one run and not
the other, and being the cheapest thing that clears it changes the whole answer.

**So section 3b's specific recommendation is withdrawn.** Asked twice:

| | `grok-4.6` alone | cheapest quorum at or above its accuracy | verdict |
|---|---|---|---|
| run 1 | 93.0% at $0.00298 | 93.5% at $0.00358 | the single candidate is cheapest |
| run 2 | 93.0% at $0.00623 | 93.3% at $0.00365 | **the quorum dominates it** |

Its accuracy is identical in both runs. What doubled is its **cost**, because its median output length
went from 346 tokens to 698 on the same prompts — so this reversal is not sampling noise but a change in
the candidate's own behaviour between two collections a few weeks apart. Either way the claim does not
survive being asked twice, and a recommendation that does not survive that is not a recommendation.

**What stands, and it is less than section 3b claimed.** The comparison error 3b identified is real:
every table before it fixed the frontier tier as the thing to beat and never asked which single
candidate was cheapest at a given accuracy. That criticism holds. What does not hold is 3b's
replacement answer. The correct statement is weaker and more useful: **on this pool no single-run
frontier point should be quoted as a policy, and the mechanism's most valuable output is the
disagreement between two runs of it.**

**Three defects this check found in the machinery itself, all now fixed.**

**Ties were being reported as differences.** A policy that never escalates exists once per candidate
escalation tier, identical in accuracy and cost, differing in a field no request read. `frontier` and
`cheapest_meeting` now canonicalise, because before they did so two runs of the same data appeared to
disagree at the 90% floor when they had chosen the same member.

**The collector's bearer token expired mid-run and biased the subset.** 1,366 cells came back HTTP 401.
Because the pool processes work in submission order, the lost cells were a contiguous block of item ids
rather than a random sample, so the surviving subset was **biased and not merely smaller** — and the
first version of this comparison was run on it. The token is now re-read on a 401.

**A verbose candidate was being scored as wrong for being slow.** `grok-4.6`'s long generations exceeded
the edge's timeout on a non-streamed reply, and 26 of its 181 replies came back as transport errors,
which — being unparseable — score as wrong answers. Retrying the same shape cannot help, so a timeout
now goes straight to the streaming path. This is the same gateway limitation filed upstream, and it was
silently deflating one candidate's measured accuracy.

**Coverage, stated rather than buried.** 571 of 699 items are complete in both runs. The 80 items with a
remaining gap are scattered across the id range but skew to the last two deciles, so the subset is not
perfectly representative; 96 cells remain unanswered after retries, mostly `grok-4.6` streams that never
completed and six `claude-fable-5` content-filter refusals.

## 3e. The check is now a module, and the module found my reading of 3d wrong

Added 2026-09-01. Section 3d compared two runs by hand. `tierbook.reproduce` makes it a routine, because
the hand version was written after three reversals had already shipped as findings, and what caught all
three was repetition rather than review. Two adversarial rounds were then run on the module itself, and
they found two defects that **invalidate part of what 3d and the first draft of this section claimed**.

**Defect one: restricting to the shared items changes run 1's own answer, so the comparison was
confounded.** The module labels each claim "what run 1 said", but run 1 is re-evaluated on the items
*both* runs completed — 571 of 687 here, 16.9% dropped, a third of the losses in one contiguous block,
`grok-4.6`'s gaps dominating. Asked whether that restriction alone moves run 1's conclusion, the answer
is **yes, at all four accuracy floors.** So the differences 3d attributed to run-to-run variation are
partly the subset, and the two cannot be separated from this data.

The module now computes that check first and reports it first, because every claim after it is about a
reconstruction rather than a recollection.

**Defect two: the ordering swap I built a story on was never a claim.** The first draft of this section
said the frontier's instability was "localised, not diffuse" and traced three floor failures to one
swap: `claude-sonnet-5` against `gpt-5.6-sol`, 90.4% / 91.1% becoming 92.5% / 90.7%. With eight
candidates there are 28 such pairs, and a paired exact test on run 1's own margin does not clear 0.05 for
that one. **It was noise reversing, reported as a mechanism.** The module now requires run 1's margin to
be significant before an ordering is a claim at all, and with that gate the ordering failure disappears
and the claim count drops from 33 to 28.

**Four more defects the second reviewer found, all now fixed, and two of them changed the output.**

**The two tables were never checked for being the same questions.** `OutcomeTable` carries a suite and a
manifest digest precisely so that a reused item id whose content changed cannot pass as a match, and the
comparison joined on ids without looking at either. It now refuses two tables that disagree on them.

**Both runs finding a floor unreachable was reported as a disagreement.** That is the same conclusion,
and calling it a failure told a reader two runs differed where they had agreed exactly.

**A tie-break could manufacture a disagreement.** Several policies at the same price, with the tie
breaking differently in the two runs, looked like a changed recommendation. The comparison is now of the
co-minimal *sets*.

**And the floor claim is now two layers, which changed what the output says.** The members are the
routing gate; the escalation tier is the fallback vendor. Separating them:

| floor | policy identity | members |
|---|---|---|
| 88% | changed | **changed** (`gpt-5.6-terra` alone → `nemotron` + `qwen3-next`) |
| 90% | changed | **held** — `claude-sonnet-5` in both runs; only the fallback moved |
| 92% | changed | **changed** (a two-member quorum → `claude-sonnet-5` alone) |

So "three of four floors disagree" was too blunt: at one of them the gate held and only the fallback
vendor moved, which is a different instruction to an operator. And the frontier claim is now
one-directional and reports both counts — 16 of run 1's 22 points lost, 6 newly present — because a
point run 2 *adds* is not a failure of anything run 1 asserted.

**What can still be said, stated precisely because the boundary is the whole point:**

- **Valid.** On the 571 shared items, the two runs disagree about the cheapest policy at three of four
  floors — at two of them including its members — and share **6 of run 1's 22 frontier points**. Both
  runs are read over the same items, so this is a genuine two-run disagreement.
- **Not valid.** That the recommendations published from run 1 — read over 687 items — failed *because
  of* run-to-run variation. The subset moves them on its own.
- **Withdrawn.** That the instability is localised to one candidate near a threshold.

**The flip rates stand**, since they are a paired measurement over the same items in both runs:

| candidate | run 1 | run 2 | flip rate | 95% interval |
|---|---|---|---|---|
| `claude-fable-5` | 94.9% | 94.7% | 0.9% | [0.4%, 2.0%] |
| `claude-opus-5` | 94.6% | 93.9% | 1.8% | [1.0%, 3.2%] |
| `gpt-5.6-sol` | 91.1% | 90.7% | 3.2% | [2.0%, 4.9%] |
| `claude-sonnet-5` | 90.4% | 92.5% | 3.2% | [2.0%, 4.9%] |
| `grok-4.6` | 92.5% | 93.0% | 3.7% | [2.4%, 5.6%] |
| `gpt-5.6-terra` | 88.4% | 89.3% | 4.0% | [2.7%, 6.0%] |
| `qwen3-next-80b` | 72.3% | 75.8% | **10.9%** | [8.6%, 13.7%] |
| `nemotron-super-3-120b` | 61.5% | 64.1% | **24.0%** | [20.7%, 27.7%] |
| pooled | — | — | 6.4% | [5.8%, 7.2%] |

**And the module refuses to call anything reproducible.** Its wording is "identical in this one repeat",
not "reproducible" and not "have not yet failed" — the second was the first attempt and a reviewer
pointed out it still reads as verified stability to anyone skimming, so the number of runs stays in the
sentence. It also reports how many failures chance alone would produce, here 0.0, because after the
significance gate none of the surviving claims has a null hypothesis. That is itself worth knowing: every
failure is a structural claim about a policy, and "expected by chance" cannot speak to those.

**Two statistical labels were wrong and are now stated rather than implied.** The pooled flip rate treats
`items x candidates` as that many independent trials, which they are not — one item correlates across
candidates and a provider incident inside one run correlates across all of them — so its interval is
narrower than the truth, and pooling compresses 0.9% and 24.0% into 6.4% when it is the 24.0% that
decides whether a policy built on that candidate can be trusted. And the Wilson interval is uncertainty
about the rate on the population the benchmark stands for, **not** about the run: two collections give one
difference, and no interval computed from them says how much a third would move.

**The uncomfortable lesson is about the order of operations.** The correction in 3b was written from one
run. Section 3d's correction of it was written from a confounded comparison. This section's correction of
3d came from a module that two reviewers then found two defects in. Each layer was more careful than the
one before and each was still wrong, and the only thing that has consistently worked is building the
check as code and letting someone else attack the code.

## 3f. Folding in a self-hosted model, and what its serving configurations exposed

Added 2026-09-01. A self-hosted `qwen3.6-35b-a3b` was measured on the calibration fold in nine serving
configurations, alongside seven API candidates including `claude-sonnet-4-6` — 16 candidates over 488
items, 9,200 policies. Two questions were put to both reviewers first, and the measurement answered one
of them against my own proposal.

**"Candidates sharing weights are correlated" is false, and the matrix says so.** The plan was a discrete
correlation group. Measured:

| pair kind | answer disagreement | median |
|---|---|---|
| same weights, different serving configuration (36 pairs) | 2.7% – 35.7% | **31.9%** |
| different model families (84 pairs) | 9.4% – 46.3% | **31.8%** |

Identical medians, and `claude-fable-5` against `claude-opus-5` disagreed on 9.4% — two frontier models
of one family agreeing far more closely than two configurations of one open-weights model. **Provenance
predicts nothing about behaviour.** So correlation is measured per pair from the matrix, and provenance
is kept for the three things a measurement cannot give: invalidating pair statistics when a weight
version changes, flagging a pair whose disagreement has never been measured, and noting the risks a
few-hundred-question corpus cannot see at all — a blind spot in the weights, a simultaneous update, a
shared cluster. That is `tierbook.lineage`, named lineage because "correlation group" promises
statistics these numbers refuse.

**A stop rate is the most misleading figure available, and two new ones replace it.**

`joint_failure`, the largest `P(both wrong | at least one wrong)` over member pairs, correlates
**−0.791** with the accuracy of the answer a quorum stops on — while the stop rate *rises* with it. Over
120 pairs, sorted into quartiles by joint failure:

| joint failure | accuracy when stopped | stop rate |
|---|---|---|
| 25.1% | **91.9%** | 65.0% |
| 35.3% | 89.6% | 68.9% |
| 42.0% | 88.2% | 71.5% |
| 64.4% | **80.5%** | **78.4%** |

**A correlated quorum stops more often and worse.** Anyone optimising a stop rate is optimising the
wrong direction.

`agreement_lift` — accuracy when stopped, minus the best member's accuracy over all items — says whether
the quorum does anything at all. It runs from **+14.8%** down to **+0.9%**, and the bottom is a pair of
near-duplicate serving configurations that stop on 97% of items and add nothing: **one model wearing two
hats**, indistinguishable from a real quorum by stop rate alone. 136 of 8,960 enumerated quorums are in
that shape.

**And the figure an operator actually feels is `wrong_stop_rate`**, `stop_rate x (1 - accuracy_when_stopped)`:
how often the policy returns a confident wrong answer with no second look. It reorders the frontier at a
fixed accuracy floor, which neither of the numbers it is built from can do:

| at an 85% accuracy floor | members | cost per item | wrong-stop rate |
|---|---|---|---|
| cheapest | 2 | $0.00306 | 8.2% |
| **fewest confident errors** | 3 | $0.00385 (1.26x) | **5.3%** |

26% more money buys a 35% reduction in confidently-wrong answers at the same accuracy. And the policy
that clears a 75% floor has a wrong-stop rate of **21.1%** — one request in five answered wrongly and
never escalated, from a policy whose accuracy column looks unremarkable.

**The residency-constrained answer now comes out of the optimiser** rather than a script. Restricted to
candidates that can be inferred domestically — the `qwen3.6` configurations plus `claude-sonnet-4-6`:

| accuracy floor | cheapest policy | accuracy | cost per item | handled locally |
|---|---|---|---|---|
| 80% | `q36:v2` + `q36:v3` → `q36:tersec1b`, **no API at all** | 80.1% | **$0.00048** | 80% |
| 85% | `q36:tersec1b` + `q36:v2` → `claude-sonnet-4-6` | 85.0% | $0.00306 | 67% |
| 86% | unreachable | — | — | — |

At an 80% floor the API is not needed at all, at a sixth of the 85% policy's cost. At 85% the answer
matches the figure computed by hand earlier, which is the mechanism reproducing a result rather than a
new one. 86% is out of reach, which bounds the pool.

**Two invariants both reviewers named, now pinned by tests.** A policy's score is never derived from a
product of marginal accuracies — two matrices with identical per-candidate accuracy and different joint
structure must score differently, and they do — because if no independence formula appears in the code
then correlation is a measured fact rather than a distortion needing a correction factor. And **no
candidate is ever pruned by its own accuracy**: the best member of the best pair here was a
configuration 9 points weaker on its own, so single-accuracy pruning would have removed exactly the one
that mattered. If pruning is ever needed for combinatorics, only proven dominance on joint statistics
will do.

**What is deliberately not claimed.** Every figure here is one run of the calibration fold, and section
3d exists because single-run policy recommendations reversed three times. The disagreement rates are
task-distribution dependent — 31.9% on MMLU-Pro says nothing certain about production traffic — and
`reproduce.compare` is the tool for both problems, not yet applied to this table because the
`qwen3.6` configurations have not been collected twice.

## 4. Abstention: the tail is four different things and only one of them is routing

The 51 items nobody solves carry 54.8% of the cascade bill. Both reviews independently said not to build a
detector for them, and the audit says why: the tail is a confluence of mechanisms, not a class.

| what it is | items | what removes it |
|---|---|---|
| the answer key is wrong | 22 confirmed | a hand audit, triggered by unanimous disagreement with the key |
| the same question appears twice | 10 redundant | deduplication on normalised question text |
| the question has two correct answers | 1 confirmed | widening the key |
| genuinely unanswerable by this pool | 29 | an abstention rule — **this** is the routing problem |

**The detector for the first row already exists and is free.** Every candidate agreeing while the verifier says
they are all wrong fired on exactly 19 items over the whole corpus and all 19 were bad keys, with no false
positives. In a tenant this generalises without change: unanimity against a verifier's rejection is evidence
about the verifier. It does not treat a prediction as evidence of correctness — its output is "a human should
look at these".

For the 29 that remain, neither review recommends a classifier, and both propose the same shape:

- **Deterministic pre-flight first.** Input completeness, dependency and environment availability, whether the
  verifier can even execute, contradictions in the specification. Anything decided here is an immediate
  abstention and needs no model at all. Crucially this separates *unverifiable* from *candidates failed*, and
  conflating those two is what makes the 0.51 figure unfixable.
- **Then sequential evidence, not a new signal.** Each failed tier updates the item's difficulty posterior
  upward, and `P(the next tier succeeds | the failures so far)` falls out of the shared item model the mechanism
  already fits. Stop when the expected value of a success falls below the next call's price.
- **Stop on the lower bound, not the point estimate.** The decision rule is a one-sided confidence bound on "no
  remaining candidate will succeed", with an **ex-ante cap on the lost-success rate inside the stopped set**. The
  learned part runs in shadow mode until that cap is demonstrably met; only the deterministic pre-flight gates
  real traffic before then.

## 4b. The abstention rule is built, and the failure count alone cannot drive it

Added 2026-09-01. `tierbook.abstain` implements section 4: the two free repairs, and the sequential
rule that stops when the bound on continuing no longer pays for the next call.

**The free repairs reproduce exactly.** `broken_key_candidates` flags 19 items over the 1,187 — the
same 19 a human confirmed — and `duplicate_groups` finds the 10 groups covering 20 items.

**The sequential rule, swept over its two parameters, never clears a 5% lost-success cap.** The
oracle that skips exactly the 51 items nobody solves saves 54.8% of the bill and loses nothing, which
is the ceiling. Against it:

| value of a success | decay per failure | items stopped | bill saved | solvable items given up |
|---|---|---|---|---|
| $0.30 | 0.70 | 21 | 35.9% | **19.0%** |
| $0.10 | 0.50 | 76 | 70.6% | 32.9% |
| $0.05 | 0.50 | 104 | 78.4% | 51.0% |
| $0.01 | 0.20 | 266 | 96.4% | 80.8% |

The best point loses nearly a fifth of the work it abandons. **So the learned part stays in shadow
mode**, which is what section 4 registered, and only the deterministic pre-flight gates traffic.

**The reason is structural and it says what the fix has to be.** "How many tiers have failed so far"
is a good signal for *this item is hard* and a bad one for *this item is hopeless*, and the two are
not close in size here: 51 items are solved by nobody while 143 need a tier dearer than the cheap
ones. Failing four cheap tiers is therefore overwhelmingly evidence for "escalate", not for "stop", and
a bound driven by the failure count alone must confuse them. The rule needs the item model's posterior
— which conditions on the item's own features, not only on the count — and until that posterior exists
the rule has nothing usable to read.

**A defect found by running it, worth recording because of its direction.** The first measurement
reported savings of up to 242% of the entire bill. `usd_saved` was counting every remaining tier,
including the ones a cheapest-first cascade would never reach because it stops at the first success.
Fixed, and pinned by a test. The direction is the point: the error inflated the rule's benefit, which
is the direction an author's own instrumentation errs in, and the absurd number is the only reason it
was caught in one run rather than becoming the headline.

## 4c. The cascade's own history cannot drive the stopping rule, and the proof is an exact 0.5

Added 2026-09-01. Section 4b said the rule needed the item model's posterior rather than a failure
count, so `tierbook.latent_ability` fits one: a one-dimensional item-response model,
`P(m solves i) = sigmoid(b_m - a_m * theta_i)`, on a grid over `theta` so the posterior after observed
failures is available in closed form and the bound can be a quantile of it. Candidate parameters are
fitted on the calibration fold and the rule is evaluated on the frozen fold; `theta` never leaks,
because at request time the rule reads `p(theta | the failures in this cascade)` starting from the
prior.

**It improves the rule and still cannot clear a 5% cap.** The best positive-saving point saves 16.5%
of the frozen fold's bill and gives up 33% of the work it abandons.

**And then the reason turned out to be exact rather than approximate.** At the moment the decision
matters — every cheap tier has failed and the question is whether to call the dearest one or stop —
there are 31 such items, 3 of which the dearest tier solves. Asking the posterior to separate them:

| discriminating between "the dear tier will solve it" and "it will not" | AUC |
|---|---|
| posterior mean of `P(dear solves)` | **0.5000** |
| upper bound of `P(dear solves)` | **0.5000** |

Not approximately a coin. **Exactly** one, and the mean predicted probability is 0.166 in both groups
to three decimals. The reason is that the conditioning set is *identical* for all 31 items — the same
eight failures — so the posterior is the same distribution and `p_next` is the same number. A rule
whose only evidence is which tiers failed assigns one value to every item in that state, by
construction.

**So in this evidence class the rule is not a learned rule at all; it is a fixed abandonment depth.**
That collapses the design space to nine points, and they are all measurable:

| abandon when this many cheapest tiers have failed | accuracy | bill saved | of the abandoned, share that were solvable |
|---|---|---|---|
| never | 96.0% | — | — |
| **all 8** | **95.6%** | **24.4%** | **9.7%** |
| all 7 | 95.4% | 36.0% | 12.5% |
| all 6 | 94.6% | 52.1% | 26.3% |
| all 4 | 92.7% | 69.7% | 45.1% |
| all 2 | 74.0% | 96.0% | 84.6% |

**The usable operating point is the deepest one: 24.4% of the bill for 0.4 accuracy points, giving up
9.7% of the work it abandons.** That fails a 5% cap and passes a 10% one, so whether it ships is the
owner's cap and not a modelling question — which is the right place for that decision to sit.

**What this closes and what it opens.** It closes the idea that a cascade can learn when to give up
from its own history: the history is a constant where the decision is, and the ladder structure
measured earlier is why — closely spaced rungs mean early failures cannot identify what the top rung
will also fail. It opens exactly one avenue, the one the design already registered: evidence from the
**item**, through `theta` regressed from cheap features, since that is the only quantity that differs
between the 3 rescuable items and the 28 hopeless ones at the moment of the decision.

## 4d. Before spending GPU time: what the box is worth, and at which floor

Added 2026-09-01. Section 5 registers a tuning pilot whose prize was estimated at −25.9% of the bill,
computed when `claude-opus-5` was the only escalation tier considered. Sections 3b and 3c changed the
comparison, so the prize was recomputed on the frontier before any GPU time is bought. It costs
nothing to ask, and it moves the answer.

**The box is on the frontier — eleven of twenty-four points involve it — and its marginal value is
almost entirely confined to one accuracy floor.** Deleting it from the candidate set and re-solving:

| accuracy floor | cheapest policy with the box | cheapest without it | what the box is worth |
|---|---|---|---|
| 85% | `gpt-5.6-terra` alone, $0.00251 | the same | **0.0%** |
| 88% | `grok-4.6` alone, $0.00333 | the same | **0.0%** |
| **90%** | `gpt-5.6-terra` + box → `claude-opus-5`, $0.00537 | `claude-opus-5` alone, $0.00593 | **+9.4%** |
| 92% | `claude-opus-5` alone, $0.00593 | the same | **0.0%** |

At three of four floors the box contributes exactly nothing at these prices: it holds frontier points
below 87% accuracy, which is beneath where anyone would operate. Its whole present value is 9.4% of the
bill at a 90% floor, and there it works as a **quorum member** rather than as the tier that answers.

**And tuning it is worth more than section 5 estimated, not less.** Simulating a better box by granting
it the correct answer on items it currently misses — an upper bound, since tuning has to actually
achieve that — and re-solving the 90% floor each time:

| box solve rate | cheapest policy at a 90% floor | cost per item | against today |
|---|---|---|---|
| 66.4% (today) | `gpt-5.6-terra` + box → `claude-opus-5` | $0.00537 | — |
| 73.7% (+50 items) | `claude-sonnet-5` + box → `grok-4.6` | $0.00393 | **−27%** |
| 80.9% (+100 items) | `qwen3-next-80b` + box → `claude-opus-5` | $0.00358 | **−33%** |
| 88.2% (+150 items) | `claude-sonnet-5` + `qwen3-next-80b` → box | $0.00309 | −42% |

**So a +14.5 point improvement is worth about a third of the bill at a 90% floor**, and the box stays a
quorum member throughout rather than taking over — which is consistent with section 2 and is the shape
the pilot should be designed to produce.

**Two things this changes about section 5.** The prize is bigger than −25.9%, so the pilot is better
justified than it was. And it is conditional in a way the original registration was not: **the owner's
operating floor has to be established before the GPU time is bought**, because at 85%, 88% or 92% on
this pool the answer is that tuning the box is worth nothing at all and the money should not be spent.
The last row is also a warning about its own method — at a near-perfect box the simulation says "just
use the box" for $0.00010, which is true and circular, since the simulation hands over correctness for
free. Read the middle rows.

## 5. The box-tuning experiment

**The ceiling is known and it is modest.** All-API costs $2.6289 over these items; today's box saves 11.3%; a box
at frontier ability would save 25.9%, because escalations already land on cheap APIs, so the box's value is
bounded by the gap to the *cheapest adequate* API rather than to the dearest one. The most valuable target is the
95 items the box misses that currently need a dear tier: capturing all of them is −20.0% of the bill, and such an
item is worth 4.0 times more than an average one ($0.00554 against $0.00137).

**95 items is a pilot, not a study.** Both reviews said so and gave the same reasons: memorising surface patterns
of dear-tier-dependent items, forgetting the easy centre, leakage through near-duplicates, and a threshold that
becomes self-fulfilling because it was fitted before the improvement. The duplicate groups found in the audit are
a concrete instance of the leakage risk.

The experiment, with everything that has to be fixed before it starts:

- **Freeze a new hold-out first**, collected by the same rule as the target, before any training. Group
  near-duplicates by normalised text and semantic cluster so that no group straddles the split. Use the 95 items
  for pilot training only.
- **Three arms, three seeds each.** Untuned box; the box tuned on the 95 target items; and a control tuned on the
  same number of items drawn from routing byproducts that are *not* dear-tier-dependent. Without that control a
  gain cannot be attributed to the targeting.
- **Four evaluation faces.** The target hold-out; the easy centre the cheap tier already handles; the
  nobody-solves distribution; and a time-ordered hold-out of the tenant's own traffic. Two runs per cell, a third
  on any cell that flips.
- **Promotion needs all three of:** a reproducible verified gain on the target hold-out; degradation on the easy
  centre below a cap set in advance; and a one-sided lower bound on the expected cost saving that is positive.
- **The policy and the thresholds are frozen during the comparison.** Moving the threshold after tuning makes the
  target set grow by construction.
- **A tuned box is a new candidate.** It is placed on the anchor set of 100 to 200 items, which is necessary but
  **not sufficient** — anchors position it against the others and say nothing about whether the tuning was worth
  it. The anchor set must include repeat cells so the tuned box's own flip rate is re-estimated; this project has
  already measured a 7-point accuracy swing from one chat-template flag and an 8% outcome flip rate from
  batching, so "same weights" is not "same candidate".
- **The probe must be a pinned, frozen artifact.** The item model regresses difficulty from the box's own probe
  features. If the probe is the serving box, tuning it shifts the probe's distribution and the regression decays
  silently — improving the fleet would break the instrument that measures it.
- **Cut condition.** No consistent hold-out gain across three seeds, or one breach of the centre-regression cap,
  and the line stops. Because the theoretical ceiling is −20.0% of the bill, the cumulative cost of collection,
  training and maintenance is capped at a conservative fraction of that.

## 6. The agentic re-measurement

**The existing agentic evidence is withdrawn from the evidence base.** Twenty instances, three candidates, one
run each, with one candidate solving all twenty: that supports no statement about ability ordering, about
Loevinger's H, or about the value of a predictor. It stays on file as an exploratory note.

The minimum that would replace it, from the stricter of the two reviews: **200 independently verified instances,
six candidates spanning cheap, middle and frontier, two runs per cell** — 2,400 runs — with a third run on every
cell whose two runs disagree. If the budget does not reach that, the conclusions are restricted to protocol
calibration and **no routing claim is made at all**. Before committing to 200, run an 80-instance calibration at
the same shape to fix the flip rate, the degenerate-instance rate and the cost variance.

- **Stratify** by the current three candidates' pattern (all pass, mixed, all fail), repository and language,
  change size, testability, tool and network dependence, runtime, and a static difficulty proxy. Sample mixed
  strata heavily and keep all-pass and all-fail as small quotas.
- **Do not delete the eight instances every candidate solved.** They exist in the production distribution, so
  they carry weight in cost and quality aggregates; they are reweighted by sampling probability rather than
  dropped. They simply contribute nothing to ordering or prediction, so they are not over-sampled.
- **The noise floor is estimated per candidate and per stratum** and enters the correctness matrix's error model,
  so H is reported as an interval rather than a point.
- **The bill-concentration analysis comes first**, and it is kept as `P(verified success)` per instance together
  with measured tokens, tool calls and wall-clock per candidate, so the deliverable is a cost curve per quality
  floor rather than one table at today's prices.

## 6b. The agentic episodes that do exist say escalation bought nothing, and 37% were censored

Added 2026-09-01, as the free first step section 6 requires before any re-measurement is commissioned.
103 scored episodes over 21 SWE-bench instances and five routing arrangements were already on disk. They
do not meet section 6's bar and are not offered as one; what they do is change what the study should be.

| arrangement | episodes | resolved | total spend | per episode | median steps |
|---|---|---|---|---|---|
| `cheap-always` | 19 | **42.1%** | $2.32 | **$0.122** | 12 |
| `cheap-then-escalate` | 21 | 42.9% | $17.24 | $0.821 | 12 |
| `role-based` | 21 | 52.4% | $18.50 | $0.881 | 40 |
| `premium-always` | 21 | **61.9%** | $19.36 | $0.922 | 5 |
| `capacity-first` | 21 | 19.0% | $125.13 | $5.958 | 40 |

**On outcomes, almost nothing here is separable.** Paired exact sign tests over the instances where
both arrangements ran, all ten pairs:

| comparison | instances | wins / losses | p | verdict |
|---|---|---|---|---|
| `capacity-first` vs `premium-always` | 21 | 0 / 9 | **0.004** | `capacity-first` worse |
| `capacity-first` vs `role-based` | 21 | 0 / 7 | **0.016** | `capacity-first` worse |
| `cheap-always` vs `premium-always` | 19 | 0 / 4 | 0.125 | not detectable |
| `cheap-always` vs `cheap-then-escalate` | 19 | 1 / 1 | 1.000 | not detectable |
| `cheap-then-escalate` vs `premium-always` | 21 | 0 / 4 | 0.125 | not detectable |
| the other five pairs | 19–21 | — | 0.06–0.69 | not detectable |

**Two of ten pairs separate, and both of them only say `capacity-first` is worse.** So the headline
resolution rates above — 42.1% against 61.9% — are point estimates whose difference this sample cannot
establish. Writing "the cheap arrangement gets 68% of the frontier's resolution rate" would be reading a
ratio of two numbers that are not distinguishable.

**What is not sampling noise is the cost**, because it is the sum of what was actually paid rather than
an estimate of anything: `cheap-then-escalate` costs **6.7 times** `cheap-always` and `capacity-first`
costs **48 times** it. So the only demonstrable statement on this sample is uncomfortable and useful:
**the arrangements are indistinguishable on outcomes and differ by up to 48-fold in price**, and the
one arrangement that is separably worse is also the dearest. On evidence of this shape the decision is
to take the cheapest and spend the difference on a study that can separate the rest.

**Where the money goes, and it rhymes with the knowledge corpus:**

| instances | count | share of the bill |
|---|---|---|
| no arrangement resolved | 6 | **32.1%** |
| every arrangement resolved | 4 | 8.8% |
| mixed — the only ones that inform a comparison | 11 | 59.1% |

A third of the agentic bill is spent on instances nobody solves, against 47.8% on the knowledge corpus.
The abstention question is the same question there, and it is worth more per instance: one episode costs
$1.77 on average, which is **537 times** a knowledge item at the cheapest arrangement's rate.

**Three facts that a re-measurement has to be designed around, and none of them was in the withdrawn
analysis.**

**Only 11 of 21 instances inform anything.** Six were resolved by nobody and four by everybody, so
48% of the sample carries no comparative information. Section 6's stratification has to sample the mixed
band deliberately rather than hoping for it, and 200 instances drawn at this rate would yield about a
hundred informative ones.

**37% of episodes were cut off by the step budget, not by finishing.** Thirty-eight of 103 stopped on
"step budget exhausted" and the binding constraint was `steps` in exactly those. So the comparison is
partly measuring which arrangement fits inside 40 steps, and the two arrangements at the budget ceiling
(`role-based` and `capacity-first`, both at a median of 40) are the two whose outcomes are least
interpretable. Either the budget is raised until it stops binding, or censoring is modelled explicitly —
and a survival model is what section 6 already proposes, so this is evidence for that shape rather than
a new problem.

**Seven episodes are unusable and six of them for the same reason.** Six died on "the premium tier could
not be reached: the provider answered 200 with an empty stream" and one on a 200,000-character cap. The
empty-stream failure is the gateway defect filed upstream; it is still corrupting agentic measurement,
and it lands on the premium tier, which biases exactly the arrangement a comparison most needs intact.

## 5b. The tuning pilot's splits are frozen, and the pilot is gated on one number nobody has given

Added 2026-09-01. Section 5 says the hold-out must be frozen before any training, and near-duplicate
groups must not straddle the split. Both are done, and the manifest is written:

| | |
|---|---|
| target: the box misses it, no cheap tier solves it, some dear tier does | **168** items |
| grouped by normalised question stem | 167 groups |
| groups whose text also appears on a **non**-target item, so training one copy contaminates the other | 1, excluded |
| **frozen split** | **105 train / 62 hold-out**, no group straddling |
| the four evaluation faces | 62 target hold-out, 765 easy centre, 29 nobody-solves, 1,165 all-clean |

The contamination manifest names the 105 training ids and states what they may not be used for: an
anchor set, calibration, or any reported gain. That obligation runs from the training side back to
routing, and section 5 already says an interface whose correctness depends on the other side's goodwill
is a design that fails quietly — so the list exists as a file rather than as a promise.

**Capturing every training target would take the box from 65.7% to 74.7%**, which section 4d prices at
about a 27% reduction in the cheapest policy meeting a 90% accuracy floor.

**And that is where the pilot stops until someone answers one question.** Section 4d measured the box's
marginal value as **0.0% at an 85%, 88% or 92% floor** and 9.4% at 90%. Buying GPU time before the
owner's operating floor is known therefore risks spending it on a change that is worth nothing by
construction. The precondition is in the manifest's `gates` block, and it is a decision rather than a
measurement: at what accuracy does this pool actually have to operate?

## 6c. What the existing traces already say about trajectory features

Added 2026-09-01. Section 6 proposes cheap trajectory counters ahead of embeddings. The 103 episodes on
disk carry per-step traces, so the counters can be checked before the study is commissioned.

**Failing episodes churn, and it is the clearest signal available.** Mean steps of each kind, resolved
against not:

| step type | resolved | not resolved | ratio |
|---|---|---|---|
| `patch` | 2.62 | **6.95** | **0.38** |
| `read` | 4.40 | 7.72 | 0.57 |
| `search` | 2.47 | 4.05 | 0.61 |
| `verify` | 2.73 | 2.60 | 1.05 |
| `finish` | 2.71 | 1.69 | 1.60 |
| `handoff` | 2.42 | 1.72 | 1.40 |

An episode that fails writes **2.7 times as many patches** as one that succeeds, and reads and searches
about 1.7 times as much, while verifying the same amount. That is the edit-churn feature the design
names, and it is visible at 103 episodes without any embedding.

**The outcome is partly callable from the first step or two, and not from more than that.** Grouping
episodes by the prefix of `(step type, tier)` pairs and taking the majority label within each group:

| prefix length | distinct prefixes | in-group majority accuracy | prefixes seen once |
|---|---|---|---|
| 1 step | 11 | **69.9%** | 1 |
| 2 steps | 24 | 70.9% | 9 |
| 3 steps | 39 | 76.7% | 17 |
| 8 steps | 99 | 98.1% | **95** |
| 12 steps | 101 | 99.0% | **99** |

**The bottom two rows are memorisation, not prediction, and reporting them as accuracy would be a
mistake.** At twelve steps there are 101 prefixes over 103 episodes and 99 of them occur once, so the
"majority" inside each group is that single episode's own label. The readable rows are the top two,
where groups have several members each: **about 70% against a base rate of 56.3%**, from one or two
steps. That is a real but modest signal, and it is the honest version of the information-value curve
section 6 asks for — with the sample size, not the method, as what limits it.

**The triggers that exist already fire on the right episodes.** Fifteen of 103 escalated, at a median of
step 8, on two counters: `same_action_3x` and `verifier_disagreed`. Both are cheap counters of exactly
the kind section 6 proposes. The escalated episodes resolved 53.3%, and within `cheap-then-escalate` the
six that never escalated resolved 1 of 6 — so the triggers were firing on the harder trajectories rather
than at random. That is a selection effect and not evidence that escalating helps; section 6b already
shows the outcome difference is not detectable. What it does establish is that the counters are
informative enough to be worth logging in the larger study.

## 7. Order of work, and why

1. **Fix the gateway's empty completions.** An upstream zero-token completion is relayed as a success and
   charged: $17.69 discarded against $14.59 of successful spend on the affected arm. It is recovered directly
   with no quality trade-off, and until it is fixed it keeps poisoning the labels every other measurement uses.
2. **Deduplicate and audit the labels.** Free, done for the unanimous case, and it shrinks the biggest number on
   the page from 54.8% to 47.8% of the bill.
3. **Experiment A, the arbiter — done and killed, $10.20 across both folds.** Arbitration adds nothing the
   frontier tier does not already do by answering. The quorum stopping rule that came out of it is the keeper.
4. **The quorum optimiser (experiment B).** No new measurement; this is the code that makes the answer survive a
   price change.
5. **Abstention, deterministic pre-flight only at first**, with the sequential rule in shadow mode behind a
   lost-success cap.
6. **The box-tuning pilot**, under the gates in section 5.
7. **The agentic re-measurement**, starting with the 80-instance calibration.

The two reviews disagreed on nothing material here. They ordered tuning against the agentic re-measurement
differently, and the tie-break is stated: the agentic work moves ahead of tuning only if agentic spend comes to
dominate the bill and a product decision on agentic routing is imminent.

## What this does not claim

**About 7% of the mid-priced arm's cost is imputed, not measured.** The gateway's Converse transport
accepts `stream_options.include_usage` and emits no usage chunk, so the rows that had to be collected
over the streaming path — 24 of 338 on the frozen fold, 17 of 257 on the calibration fold — carry a
crude local token estimate rather than the provider's count. The measurement client tags those rows so
imputed spend is separable, and the `$0.00295` figure should be read as measured to within that
fraction. The accuracy figures are unaffected; only the cost column is.

**No arm has been repeated.** The frozen-fold figures are single runs, and the tiers involved flip 3.6% and 5.1%
of their answers between identical runs. That is smaller than the 3.2-point accuracy gap the quorum policy gives
up, so the ranking is safe, but it is the same size as the arbitration effect that failed to replicate — which is
the reason to distrust any single-fold difference of that size here.

**Every accuracy figure here is on a corpus with known residual label noise.** The 22 confirmed bad keys are
removed; the unmeasured remainder is larger and biases all of these figures downward by an unknown amount.

**The quorum table is one price vector.** The three-candidate quorum is not the answer; the optimiser is. At a
different price vector the best quorum is a different subset, and possibly a single candidate.

**No tuning has been done and no arbiter has been run.** Sections 3, 5 and 6 are registrations.
