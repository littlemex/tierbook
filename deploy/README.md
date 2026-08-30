# Putting this on a cluster you already have

These manifests assume a running Kubernetes cluster and take no position on it. There is no cluster creation,
no node group, no storage class, no ingress, no GPU scheduling and no model server here, because none of that
is this component's responsibility: whoever owns the cluster owns those, and this connects to what is already
running. The only thing that must exist before `kustomize build` is a namespace and a way to reach at least
one OpenAI-compatible endpoint.

## The three pieces, and why they are separate objects

| object | when it runs | what it may write |
|---|---|---|
| `measure` (Job) | when you want a new observation | one record into the ledger |
| `compile` (CronJob) | on a schedule, and after a measurement | the compiled table, into a ConfigMap |
| `router` (Deployment) | always | nothing; it reads the table |

They are separate because their failure modes must not be shared. A measurement that dies half way leaves the
previous table in place and the router serving the previous decision. A compile that refuses -- and it will
refuse, whenever no held-out fold supports an entry -- leaves the router serving what it was already serving
rather than falling back to something nobody chose.

Nothing here writes to the ledger except `measure`, and nothing routes except `router`. That is the same
boundary the library enforces in code, expressed in objects so that a cluster's RBAC can enforce it too.

## What you supply

- **`candidates.json`** in the `tierbook-candidates` ConfigMap: the endpoints that may be measured. It holds
  no measurements; the library refuses to load one that does.
- **a Secret per credential**, referenced by the *name of an environment variable*. Candidate files carry
  variable names and never keys, so the file is safe to commit.
- **a volume for the ledger.** Any `ReadWriteMany` claim will do. The records are small JSON files; what
  matters is that they outlive the Job that wrote them, since a decision made last week must stay explicable.

## What sits in front, and what sits behind

Either may be anything that speaks an OpenAI-compatible HTTP API.

In front: nothing, an existing gateway, or a service mesh. If a gateway is already terminating your traffic,
point the router at it and let it keep doing what it does -- authentication, quota, audit. This component adds
a decision, not a hop you have to adopt.

Behind: a vendor API, several vendor APIs through one gateway, or a model server running in this same cluster.
The library's endpoint abstraction is a `base_url`, a model name and which of the two wire protocols the
endpoint speaks. It cannot tell a rented API from a pod next door, and the only place that distinction
survives is the cost model, where a per-token bill and a per-hour bill are different arithmetic.

## Verified on a real cluster

The manifests here are not written from the shape of a router config. They were applied to a Kubernetes
cluster, traffic was sent, and the upstream that answered was checked against the tier the compiled table
named. What that run found, and what it corrected, is in
`docs/results-router-on-a-cluster.md`.

The short version: the router's own log names the decision it took, so the claim is checkable rather than
inferred.

```
{"msg":"routing_decision","decision":"tierbook_tool_agent_user_retail","selected_model":"api-cheap-a"}
{"msg":"No decision matched"}
{"msg":"routing_decision","decision":"","selected_model":"api-strong-a"}
```

The first line is a request whose family the table assigned to the cheap tier, and the upstream that answered
said so. The last two are a request the classifier put in no declared family, which reached the deliberate
default rather than the cheapest thing on offer.

## The one thing to get right

`compile` writes a ConfigMap the router reads at start. Rolling the router on a ConfigMap change is deliberate
and annotated: a router holding a table that no longer matches the ledger is the failure the registry hash
exists to catch, and catching it at start beats discovering it during an incident.
