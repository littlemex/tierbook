# Recording what a coding agent actually sends

Four agents in this cluster point at one Service alias and reach one model. Whatever differs between
them in cost, latency and solve rate is the agent's contribution, and none of it is readable from their
configs: those set a base URL and little else, while every sampling default, tool schema,
context-management rule and retry policy lives inside the binary.

This deploys a recording pass-through in front of the engine. It forwards the request byte-identically,
relays streams chunk by chunk, and appends one JSON line per call: the whole request, the usage block,
time to first byte, total time, and which pod called.

## Why it is a Service repoint and not a sidecar

The agents are not modified and are not restarted. The alias's selector is moved onto the tap, and the
tap forwards to the engine's own Service. An agent restarted in order to be measured has had its
caches, sessions and warm state discarded by the measurement.

```
before:  agents ──> qwen-serving ──────────────────> vllm-qwen-...  (engine pods)
after:   agents ──> qwen-serving ──> agent-tap ────> vllm-qwen-...  (engine pods)
```

## Apply

The engine's own Service name is the tap's upstream; set it if yours differs. Never point the tap at the
alias — once the alias selects the tap, that is a loop that presents as a hang under load.

```bash
kubectl -n qwen-trial create configmap agent-tap-src --from-file=agent_tap.py=harness/agent_tap.py
kubectl -n qwen-trial apply -f deploy/base/agent-tap.yaml
kubectl -n qwen-trial rollout status deploy/agent-tap
```

Exercise the tap directly, before any agent traffic goes near it:

```bash
kubectl -n qwen-trial run tapcheck --rm -it --restart=Never --image=curlimages/curl -- \
  curl -sS http://agent-tap:8000/v1/models
```

Then move the alias. Record what it was first, because that is the rollback:

```bash
kubectl -n qwen-trial get svc qwen-serving -o jsonpath='{.spec.selector}'
kubectl -n qwen-trial patch svc qwen-serving \
  -p '{"spec":{"selector":{"app.kubernetes.io/name":"agent-tap"}}}'
```

Rolling back is the same command with the selector that was printed.

## Read the observations

```bash
kubectl -n qwen-trial exec deploy/agent-tap -- sh -c 'ls -la /data/agent-tap'
kubectl -n qwen-trial exec deploy/agent-tap -- sh -c 'cat /data/agent-tap/*.jsonl' > tap.jsonl
python3 harness/agent_tap_report.py tap.jsonl
```

## What the observations are for

1. **The content of the agent effect.** Which fields each agent sets, how its prompt grows per turn, how
   many tools it exposes, what it does when context fills. Known before a single arm is run, rather than
   inferred from the arms' outcomes.
2. **A confound, quantified.** The billing gateway in front of the paid tiers honours some OpenAI-shaped
   fields on one upstream wire and drops them on the other. If one agent sends `reasoning_effort` and
   another does not, part of "the agent effect" measured across models is "which agent happened to send
   a field this wire discards". The tap turns that from an unfalsifiable worry into a column.
3. **The input-to-output ratio, measured.** Coding agents are prefill-heavy and the ratio decides whether
   a self-hosted box can ever be cheaper. That ratio is a property of the agent, not of the task, which
   is why it belongs here and not in a task description.

## What it does not do

It does not touch the paid tiers: nothing here sees traffic that does not go through this alias. It does
not price anything — costing stays with the ledger and the rate cards, and a proxy that also computed
money would be a second place that could be wrong about it. It records request bodies, which contain
repository contents, so the log stays on the in-cluster volume and is not copied anywhere a repository's
contents should not go.
