# The router on a cluster: what a real deployment corrected

**Measured 2026-08-30** on a four-node Kubernetes cluster (EKS 1.35, us-east-2). Before this run, the exporter
and the manifests in `deploy/` were written from the shape of a working configuration recalled from another
project. Every claim about them was therefore unverified, and four of them were wrong.

## What was proven

A request reaches the tier the compiled table named, and the router says so in its own log:

```
{"msg":"routing_decision","decision":"tierbook_tool_agent_user_retail","selected_model":"api-cheap-a"}
{"msg":"No decision matched"}
{"msg":"routing_decision","decision":"","selected_model":"api-strong-a"}
```

Three requests through Envoy on the same deployment. Two were classified into the family the table assigned to
the cheap tier, and the upstream that answered identified itself as that tier's model. One was classified into
no declared family and reached the default -- which is the reference tier, deliberately, because an
unclassified request is one there is no evidence about.

The chain end to end: a ledger of per-item observations, a held-out fold, a compiled table, an exported router
config, a classifier, an ExtProc decision, an Envoy route, and an upstream whose answer names itself. Every
link was exercised with real traffic.

**The model name is rewritten on the wire.** The client asked for the virtual model `tierbook/routed`; the
upstream reported receiving `cheap-model-a`. A tier id is tierbook's name for something and no upstream has
heard of it, so this is the step that has to work for any of it to mean anything.

## What it corrected, in the order the cluster reported it

Each of these was a claim the code made and could not support. They are listed with the failure signature,
because that is the part worth keeping.

| what was wrong | how it failed | fix |
|---|---|---|
| `providers.models[]` carried a bare `address` | `runtime_config_load_failed`: no `backend_refs`, so the router had a model name and no way to reach anything | emit `backend_refs` with endpoint, protocol, type and weight, plus `external_model_ids` |
| decisions used a per-decision `signals` block | the router read no condition and matched nothing | `rules: {operator, conditions}` |
| `signals.domains` was a list of strings | labels were never declared | objects with a name, and whatever the chosen classifier keys them on |
| the recipe redefined `modelCards` | `the model catalog is shared; define modelCards under top-level routing` -- refused to start | a recipe carries strategy, signals and decisions only |
| the entrypoint defaulted to `auto` | `model name "auto" is already an auto-model alias` -- refused to start | a new virtual name, and `auto` is now refused at export time |
| pricing used the ledger's key names | an unknown-field warning per key, on every start | translated to `prompt_per_1m` / `completion_per_1m` / `cached_input_per_1m` |
| provenance sat in a `_tierbook` top-level key | unknown-field warning on every start | written beside the config, with the registry hash also in the recipe description |
| **there was no data plane at all** | a Service pointing at a port nothing listened on | Envoy in the same pod, config generated alongside |
| Envoy listened on 8080 | the router binds 8080 for its classification API in the same network namespace, so one process did not bind and the pod never became ready | 8801, and the exporter now refuses a reserved port |
| the models volume was an 8Gi emptyDir | `Usage of EmptyDir volume "models" exceeds the limit "8Gi"` -- evicted every time the classifier finished downloading | a 40Gi PVC, so it also survives a pod replacement |
| `/health` was guessed as the readiness path | it does not exist | TCP on the gRPC port |

Six of those eleven were **fatal or eviction-level**: the deployment could not have worked. Five were warnings
on every start, which is its own defect -- a config that warns every time is a config whose warnings stop
being read.

## What this run does not support

**Not a latency or throughput measurement.** The upstreams were small servers that answer immediately, chosen
so that the answer identifies which tier served it. Nothing here says what the routing costs on the request
path.

**Not a classifier evaluation.** Which label the classifier assigns to a given request is a property of the
classifier, and the third request landing in no declared family is an illustration of that rather than a
defect. tierbook refuses to guess the mapping from a family to a label for exactly this reason: the label set
belongs to whoever chose the classifier.

**Not a statement about the tiers.** The measurements the table was compiled from are about different models
than the two upstreams dialled here. This run verifies the delivery path, not the decision's subject matter.
The decision itself came from the real, held-out-validated ledger; where it pointed is what was checked.
