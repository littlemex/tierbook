# The same Ops loop, driven through HarnessRouter

**This directory is one adapter. The loop is `examples/opencode_ops`, unchanged.** [HarnessRouter](https://github.com/HarnessRouter/harnessrouter)
runs a coding agent -- Codex, Claude Code, opencode and others, each a *harness*: the scaffold, tools and turn loop
around a model -- behind an OpenAI Responses-compatible API, and the caller names both the harness
(`metadata.harness_id`) and the model on every request. That is the one surface the opencode example asks of an agent,
so this example supplies `harnessrouter_adapter` and nothing else. If driving a different agent backend required
changing the loop, the policy or the state, the mechanism would not be agent-agnostic; the test here runs the opencode
loop through this adapter and requires it to measure both arms and derive a preference.

## Where the harness sits

The harness is a **conditioning variable**, not a candidate. tierbook routes a request among candidates given the
harness it arrived through, and choosing the harness is a task-admission decision upstream of that (SCOPE section 4).
HarnessRouter is that upstream layer made concrete, so the two stack rather than overlap:

```
task -> HarnessRouter runs the chosen harness -> the harness calls a model -> the loop's candidate for that call
```

An adapter is therefore built for one `harness_id`. Comparing harnesses means running one loop per harness and comparing
what each recorded -- spend per accepted answer, acceptance, how often a call was never answered -- not adding harnesses
to the candidate set.

## What the adapter maps, and what it does not

| loop | HarnessRouter |
|---|---|
| `body["messages"]` | `input` items, one per message |
| the candidate | `model` |
| the adapter's `harness_id` | `metadata.harness_id` |
| `body["tools"]`, sampler settings | **not sent**: the harness owns its tools and its loop. They stay in the body the loop records, so `tierbook.harness` still reads what the loop sent |
| `usage.input_tokens` / `output_tokens` | `Reply.input_mtok` / `output_mtok` |
| HTTP 400, 404, 422 | `unobserved_because="unsupported"`: the request never reached a model |
| other HTTP errors, or `status` not `completed` | `unobserved_because="execution_error"` |

The last two rows are the lesson the opencode example learned from a real run: a call that produced no answer is not a
wrong answer, and averaging the two makes a misconfigured harness look like a bad model forever.

`accept` is the deployment's quality signal. The default -- the task completed with non-empty text -- is as crude as the
opencode example's and a real run replaces it with what it can observe, such as the patch applying and its tests passing.

## Running it

```bash
PYTHONPATH=src python -m pytest examples/harnessrouter_ops/tests -q
```

The tests drive the loop through the adapter with a fake HarnessRouter. Against a running instance, build the adapter
with the instance's harness API root and a key issued in its Console, and hand it to `Ops` exactly as the opencode
example's live run does:

```python
import os
from examples.harnessrouter_ops.adapter import harnessrouter_adapter
from examples.opencode_ops.ops import Ops

agent = harnessrouter_adapter(os.environ["HARNESSROUTER_BASE_URL"], os.environ["HARNESS_ID"],
                              api_key=os.environ["HARNESSROUTER_API_KEY"])
```

The candidates' names must be models the instance's connected provider serves.
