# Where this harness came from

Imported from [`distributed-ai`](https://github.com/littlemex/distributed-ai) at commit
`ebc5621a0b596ffd8f3ebc0b01811a7f9966d2af`, path `2026-08-24-mom-vsr-eks-benchmark/agent/`.

Its history stays in that repository, and so do the measurements it produced. That is deliberate: the
figures in `../registry/tiers/` were produced by the code as it was at that commit, and the code has since
changed on purpose — the argument grammar, the second wire protocol and the per-tier thinking switch each
moved the numbers. **To reproduce a figure in the registry, use the harness at the revision the tier record
cites, not this one.** The record carries that commit for exactly this reason.

## Why it is here rather than there

It stopped being an experiment record the fourth time it was rewritten in a week, and `distributed-ai`'s
own rule is that a maintained asset does not live in a dated directory. It is here rather than in a
date-less directory of that repository because what it produces — per-family outcomes, protocol compliance
rates, latency distributions — is the input this repository's ledger is made of. It is the instrument, and
the instrument belongs with the instrument's output.

## What it is

One episode is one benchmark instance attempted end to end by one policy, in the instance's own official
evaluation image, scored by the repository's own tests. The unit is a task, not a call, because the cost
that matters is the cost of solving something.

```
dataset.py    which instances a run uses, and the stratified subset
tools.py      what the agent can do, and what each action is a step of
policy.py     who takes the next step, why, and what it cost
transport.py  one model call, on the standard library only, across two wire protocols
loop.py       the driver: runs an episode and writes what it spent
score.py      runs after the loop: decides resolved or not, and refuses a cheat
run.sh        submits one episode as a Job in the instance's own image
tests/        the decisions that would produce a plausible wrong number if they were wrong
```

`policy.py` here is the *episode* policy — who takes the next step inside one attempt. It is not
`../routing/policy.py`, which decides which tier an attempt goes to in the first place. The two never
import each other, and that separation is the point: the harness measures a tier, the router reads the
measurement.

## The scorer was checked against an unmodified tree (2026-09-08)

A review raised the right alarm: a run whose model received 3-token prompts reported 11 solved of 24, which is
prima facie evidence that the solve metric is generous or broken -- and a broken metric invalidates every arm, not
just that one.

Checked directly. The staged (unmodified) tree for `django__django-11880` was submitted to the scorer:

    python3 harness/testbed.py score --instance django__django-11880 \
        --workspace /work/returned/pristine-check.tar --context distai-eks --namespace qwen-trial

It returned `"resolved": false` with 111 tests passing and the FAIL_TO_PASS set unmet. So the metric does
discriminate: a tree with no fix in it does not score as solved, and the instance's own tests are what decide.

What that leaves open, and what it does not. It does not explain how a degraded run fixed 11 of 24 -- the solves
carried real diffs of 428 to 1,572 bytes across one or two files, so they were not empty. And it does not make
10 against 11 a difference: with 24 items and one run per arm, binomial noise is worth two or three tasks, so
those two numbers are indistinguishable whatever else is true. Any claim of a difference between arms needs
repetition, not a cleaner pipeline.

## Three controls on the solve metric (2026-09-08)

The negative control above was the first answer to "is the metric generous". A second review pointed out it was
only the first: a tree with no fix grading not-solved shows the grader does not rubber-stamp, and says nothing
about whether it can recognise a correct fix or whether it can be fooled by a patch that removes the tests it
grades on. Both were run, on `django__django-11880`, with `harness/scorer_controls.py`:

    negative   unmodified staged tree        -> not solved     (111 tests pass, FAIL_TO_PASS unmet)
    positive   the dataset's own gold patch  -> solved         (446 diff bytes, 1 file)
    tamper     the graded test file deleted  -> unscoreable    (not a pass)

The tamper result is the one worth keeping: removing the file the instance grades on yields "cannot score", not a
pass, so a deletion cannot enter a solve rate.

Still open, and stated because it is cheap and has not been done: the battery ran on one instance of twenty-four.
Graders can be misconfigured per task, so it belongs across the set. It needs no model and does not compete for
the reservation.

## Per-conversation context growth (2026-09-08)

A review overturned the aggregate evidence for the replacement metered arm and was right to try: pooled medians by
conversation length can hide individual conversations that go flat, and the pooled numbers even showed an apparent
stall -- 25,805 to 27,631 tokens between two buckets, about 180 tokens per message against 700 earlier, which is
what trimming near a context limit looks like.

Checked per conversation instead of pooled. Across 43 reconstructed conversations and 707 forwarded requests, the
input token count dropped at **zero** steps; the longest reached 142 messages and 95,229 tokens against a 200,000
limit, with no plateau at any round number. The apparent stall was an artifact of pooling: later buckets are
dominated by long conversations whose individual messages are small tool results.

## Prompt caching is not available through this gateway, and asking for it drops content (2026-09-08)

A review made the sharpest cost objection of the project: the reported break-even price compared an *optimised*
reservation against a metered arm nobody had optimised. The self-hosted arm read 91.4% of its input from a prefix
cache; the metered path read 0%, because nothing on it asked for caching. With caching at a typical discount and
the same 91% hit pattern, the break-even would move from about $0.69 per million tokens to several dollars, which
flips the decision.

So caching was switched on in the translator and measured. The result is worse than caching being unavailable:
the gateway does not cache the marked blocks, it **drops** them. A four-message request that carried 4,333 input
tokens unmarked came back reporting 25, with both cache legs at zero and the system prompt, the tool schemas and
the history all missing. That is the same silent shrinking that made an earlier arm worthless, reproduced by a
change intended to fix a different distortion.

Two consequences, both in the code. Caching defaults off and carries the measurement in its own comment. And a
general guard now refuses any reply whose billed input is implausibly small for the bytes the request carried:
real traffic on this path runs about 45 billed tokens per 100 bytes, both observed failures were two orders of
magnitude under that, and both were invisible in the outcomes. The floor is far below anything observed because
its job is to catch a collapse rather than to police a tokenizer.

What this leaves open, and it is the live question for the cost comparison: the metered arm's price advantage
cannot be evaluated on caching terms through this gateway at all. Deciding it needs a path that supports caching
-- the provider's own endpoint, or a gateway that forwards the directive -- and until then the break-even figure
holds only for an uncached metered path.

## The 27,051-token gap between the ledger and the cohort (2026-09-08)

A review caught the report using two figures for one quantity: the break-even divided by 23,616,541 tokens while
the ledger reconciliation used 23,643,592. The difference is 27,051 and it is exactly the driver's 24 preflight
calls, one per instance -- tool-free, three messages each, which the ledger counts and no run's trace carries.
Confirmed by summing the tool-free requests in the translator's log: 24 calls, 27,051 tokens, matching to the
token. The per-task comparison uses the cohort; the reconciliation uses the ledger; and the 0.11% between them is
harness overhead rather than an unexplained discrepancy.
