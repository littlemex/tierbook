# Pre-registration: does the router transfer to a family it has never seen?

**Written 2026-08-30, before any τ-bench task is run.** Every measurement this repository ships comes from
one traffic family — agentic coding on SWE-bench Verified — and the assignment was compiled from it. The
question a router has to answer is whether the *mechanism* transfers, not whether that one family's numbers
do. So it is put to a family that has never been measured, on a benchmark none of these tiers has been
evaluated against here: **τ-bench**, tool-using agents talking to a simulated user.

## Why this benchmark and not another

Three properties make it the right test rather than a convenient one.

**It is a different family, not a harder instance of the same one.** SWE-bench is one agent editing a
repository against hidden tests. τ-bench is an agent holding a multi-turn conversation with a *simulated
user* while calling domain tools, judged on whether the database ends in the required state and the required
information was communicated. Different unit, different failure modes, different tool surface.

**Its splits are the authors', not mine.** The retail domain ships `tasks_train` (500), `tasks_dev` (20) and
`tasks_test` (115). Using their boundary removes the most obvious way to cheat an out-of-fold claim: I do not
get to choose where the fold falls.

**It has an acceptance check built in.** A τ-bench task carries the actions that must have happened and the
outputs that must have been communicated, and the harness checks the resulting database state. That makes it
the first family in this repository where the condition for a cheap-first chain — *the request carries
something that can reject the artifact* — is genuinely present rather than hypothetical. The router's own
design says that is the one case where a chain is justified, so this benchmark can test that branch.

## What is being claimed, and what would refute it

> **At quality non-inferior to the reference tier, the assignment the router compiles from a calibration fold
> costs less per request on the held-out fold than the reference tier used alone.**

Refuted if any of these is true on the held-out fold:

- the compiled assignment's quality lower bound falls below the margin against the reference;
- its cost per request is not lower than the reference alone;
- it is not lower than the *cheapest tier alone*, since a router that cannot beat "always use the cheap one"
  has bought nothing but complexity;
- the rule refuses to compile at all and the honest answer is "this family cannot be routed on 20 items".

The last is a real possible outcome and is not a failure of the experiment. The rule is built to say *not
certified* rather than to guess.

## Procedure, fixed now

**Family.** `tool-agent-user-retail`. The airline domain is not touched: it is held in reserve as a second
unseen family in case anything about retail turns out to be idiosyncratic.

**Folds.** Calibration = the authors' `tasks_dev`, 20 tasks. Held-out = the authors' `tasks_test`, 115 tasks.
If wall clock forces a subset of the held-out fold, it is **the first N by the authors' task order**, stated
in the results with N, and never a subset chosen after seeing outcomes.

**Tiers.** The same three already in the registry, at the same configurations, addressed through their own
native tool-calling interfaces.

**The user simulator is fixed and is never the tier under test.** It is one model for every arm, so that the
thing being varied is the agent and not its interlocutor. Using the tier under test to simulate its own user
would make an arm's difficulty depend on the arm.

**One trial per task**, as on the earlier corpus, and stated as such: one run measures an episode, not a
stable capability. τ-bench's own pass^k metric needs repeats, which are out of scope here and named as a
limitation rather than skipped silently.

**Concurrency is fixed across arms** and recorded, because a latency figure taken at one concurrency is not
comparable to one taken at another.

## The readings, in order

1. **The mechanism check, before any measurement.** With no record for this family, `assign_family` must
   raise rather than route. If it silently picks something, that is a defect and the experiment stops until
   it is fixed.
2. **Calibration.** All three tiers on the 20 dev tasks. Write the tier records, including the paired 2×2
   against the reference on the same cohort. Then compile the assignment and record the `Decision` — the
   ranked candidates, the bounds, and which of the three reasons led to whatever it chose.
3. **Held-out, three arms.** The compiled assignment; the reference alone; the cheapest tier alone. Report
   quality with the paired lower bound against the reference, and cost per *incoming request*.
4. **Does nesting hold on this family?** Counted, not assumed. A crossover here would be the first one in
   this project and would mean the cheap tier has a capability argument on this traffic.
5. **Does the chain branch earn anything?** τ-bench supplies a check, so the router may offer a chain. Report
   what the chain costs and solves against the outright assignment. This is the first time that branch has
   been exercisable.

## What this cannot show

**Not a τ-bench leaderboard result.** One trial per task, a subset if time forces it, and a user simulator
chosen for comparability rather than for fidelity. The numbers are for comparing arms on identical
conditions, not for comparing against published τ-bench scores.

**Not transfer to a third family.** Two families is two families. If the mechanism holds here it means the
compiler is not obviously overfitted to coding, not that it generalises.

**Nothing about production traffic.** Still a public benchmark. The repository's rule that no traffic is
admitted to a cheaper tier until the work actually being routed is measured is unchanged by this.

---

## Addendum, written after calibration and before the held-out run

**Two things had to be decided, and both are recorded here rather than chosen later.**

**The throughput used to amortise a fixed-cost tier must come from the family, not from another one.** The
first compile of this family reused 616 tasks an hour, which was measured on the coding family at 94 seconds
a task. On this family the same tier takes **13 seconds** a task, so at the same sixteen episodes in flight it
sustains about **4,430 an hour** and its amortised share falls from $0.0247 to $0.0034 a task. That is not a
detail: at the coding figure the self-hosted tier looks *more expensive per request than the cheap API*
($0.0317 against $0.0293), and at its own family's figure it is three times cheaper. **The schema now carries
latency per family**, because the second family made it clear that latency is a property of the tier-and-family
pair rather than of the tier.

**The margin is an input nobody has supplied, so the held-out run reports a grid rather than a chosen value.**
The non-inferiority margin should come from the cost of an escaped defect, which no one has priced. Picking a
single number now would mean picking the number that produces the answer I already saw at calibration, since
the compiled choice moves with it:

| margin | what the calibration fold compiles |
|---|---|
| 0.10 | the reference — nothing cheaper is certified |
| 0.15 | the self-hosted tier |
| 0.20 | the self-hosted tier |
| 0.25 | the cheap API, which becomes certified and is cheaper still at some throughputs |

So the grid **(0.10, 0.15, 0.20, 0.25)** is fixed now, all four are reported on the held-out fold, and no
single one is called the answer. What the held-out fold tests is whether the arrangement each margin compiles
holds up out of fold — not which margin is right.

**One thing calibration already showed that the design did not predict.** The self-hosted tier's advantage
over the cheap API on this family is **quality, not price**: its paired lower bound is −0.130 against the
cheap API's −0.210, while the two cost within 10% of each other per request once the machine is amortised at
its own family's throughput. On the coding family the story was the reverse. A router that assumed the cheap
API is always the quality floor and the self-hosted tier always the price play would have got this family
backwards.
