# Prior art, 2026-11: what routers do now, and what the literature says about task-level cost

The survey behind `docs/DESIGN-v0.5-certification-plane.md`. Facts were checked against primary sources (repositories,
documentation, release notes, arXiv abstracts and bodies) on 2026-11-08. Where a statement is about a project's
documentation rather than its behaviour, it says so.

## 1. vLLM Semantic Router

* **Releases.** v0.1.0 (2026-01-05), v0.2.0 (2026-03-10), v0.3.0 (2026-06-05), v0.4.0 "Hermes" (2026-09-27). `main` is
  several hundred commits past v0.4.0; standalone mode (no Envoy) and the built-in model runtime are `main`-only.
* **Routing.** A declarative signal -> projection -> decision -> algorithm pipeline. Selection algorithms listed as
  supported: static, random, decision, router_dc, latency_aware, multi_factor, hybrid; experimental: automix,
  gmtrouter, prompt, knn, kmeans, svm, mlp. The `domain` signal's labels are MMLU-Pro's categories.
* **Cost and quality.** Prices are a static `pricing` block per model, written by the operator. Quality comes from
  the project's Open Intelligence Index (six public benchmarks, missing entries not imputed). `multi_factor` combines
  quality, latency, cost and load by weights or lexicographically.
* **Learning.** "Router Learning": online `routing_sampling` adapts within a process (experience is not shared across
  replicas); `vllm-sr optimize recipe-learning` reads the replay log and writes *proposals* a human applies. The
  documentation states that learning does not rewrite deployed recipes.
* **The proposal that names the gap.** `website/docs/proposals/success-constrained-selection.md` (2026-09-04, status
  Proposal): choose, among candidates whose calibrated P(success | request, candidate) meets a target, the one with the
  lowest lifecycle cost. No implementation as of 2026-11-08.
* **Scope decision.** A decision record (2026-07-14) keeps the router per-query and leaves capacity, queueing and
  replica choice to the inference-router layer (GAIE, llm-d, AIBrix).
* **Contract.** One generated JSON Schema (`version: v0.3`, separate from the release number), `config validate`,
  `config migrate`, and `config apply` with ETag compare-and-swap and hot reload.

## 2. Other routers and gateways

| project | unit | quality estimate | prices, latency, capacity | learns from outcomes |
|---|---|---|---|---|
| RouteLLM | request | classifiers trained on preference data | one static cost threshold | no (inactive since 2024-08) |
| NotDiamond | request, now session for coding agents | proprietary | cache expiry modelled | stated, closed |
| OpenRouter Auto / provider routing | request | proprietary | live prices and latency windows | operational metrics, closed |
| LiteLLM Router | request | none | latency/usage-based strategies, budgets | recent-performance only |
| Portkey | request | none | static rules and weights | no |
| Plano (formerly Arch) + Arch-Router | request/turn | 1.5B generative router, fixed after SFT | fallback | no |
| Kong AI Gateway | request | several, advanced ones enterprise-only | rate limits, breakers, EWMA | short-term EWMA |
| Cloudflare AI Gateway | request | trained classifier | cost in the score | not stated |
| Azure AI Foundry Model Router | request | proprietary | failover | vendor-side retraining |
| Bedrock Intelligent Prompt Routing | request | proprietary, two models of one family | per-request surcharge | documented as none |
| NVIDIA LLM Router -> NeMo Switchyard | request | small classifiers | thresholds in config | manual offline retraining |
| llm-d router (EPP) | request | KV-aware heuristics, learned latency predictor | SLO headers, priority | latency predictor only |
| HarnessRouter | task | not documented | not documented | not documented; switches the agent harness, a different layer |

**Commodity:** failover and load balancing, static cost thresholds, semantic caching, session affinity, per-request
classification. **Not done by anyone surveyed:** a post-hoc quality loop from the operator's own graded outcomes,
prices and capacity as live first-class inputs, selection-corrected guarantees, and evaluation tied to the deployed
configuration.

## 3. The literature on task-level cost

* **Cost per solved task is the unit.** arXiv:2504.13359 (Cost-of-Pass) defines expected spend per correct answer;
  arXiv:2510.11977 (Holistic Agent Leaderboard) puts cost beside accuracy for agents and finds that more reasoning
  effort does not reliably buy accuracy.
* **Most routing gain is a static per-task-type assignment.** arXiv:2608.23023: of 29 recoverable items in a
  twice-collected 14-model x 294-item matrix, 21 are recovered by one model per task type. arXiv:2606.07587 (The
  Routing Plateau): 21 learned routers on 5 benchmarks converge to a narrow band well below the oracle.
  arXiv:2608.08265: deployed routers recover 7.5-14.4% of a selection-valid oracle gap.
* **Selection overstates the winner.** arXiv:2510.18161 and arXiv:2607.18545 (winner's curse); arXiv:2608.08265
  (selection-valid bounds). Sample splitting is the simplest correction that is valid whatever the search did.
* **Calibration before thresholds, abstention allowed.** arXiv:2605.18796 (UCCI), arXiv:2502.09054 (early abstention).
* **Non-stationarity.** arXiv:2604.00136 (ParetoBandit: budget-paced routing under price and quality shifts),
  arXiv:2607.23765 (WISERouter: workload budgets), arXiv:2506.17254 (StageRoute: which models to keep and how to route
  are decisions on different time scales).
* **Fixed cost and capacity.** arXiv:2606.17949 (RouteBalance), arXiv:2602.07663 (joint configuration selection and
  admission control), arXiv:2611.01152 (capacity planning): fleet composition moves cost more than routing policy, and
  separating the two breaks under load.
* **Labels and backends move scores.** arXiv:2605.19537: inference backend alone moves benchmark scores by up to 16.6
  points. arXiv:2608.00794: agent evaluation validity compounds across task generation, simulation and judging.
  arXiv:2610.05982 (CASLR): several models answering correctly is label noise for a router trained on one-hot labels.
* **Decomposition is not free.** arXiv:2610.37700 (Coordination Tax) gives break-even conditions for multi-agent
  pipelines and finds them usually unmet; arXiv:2606.20629 (AgentCARD) finds role specialisation pays. Contested.

## 4. What this means for tierbook

The per-request selector is solved and crowded; the static per-task-type assignment is where measured gains are; a
choice made on the same data it is reported on is optimistic; prices move faster than measurements should be
repeated. The object nobody ships is a per-task-type assignment derived from the operator's own graded outcomes,
priced at today's rates, checked on held-out items, and handed to the router that is already on the request path.
