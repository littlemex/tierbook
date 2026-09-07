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
