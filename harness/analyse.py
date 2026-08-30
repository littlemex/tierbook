"""The held-out reading, exactly as the pre-registration fixed it."""
import json, math, statistics as st, sys
from pathlib import Path

sys.path.insert(0, "/Users/akazawt/tierbook/routing")
import policy

REF = "api-strong-a"
TIERS = ("self-hosted-a", "api-cheap-a", "api-strong-a")
D = Path("/Users/akazawt/tmp/e02/tau")

rows = {}
for t in TIERS:
    rows[t] = json.load(open(D / f"ho-{t}.json"))["rows"]
common = sorted(set.intersection(*[{r["task"] for r in v} for v in rows.values()]))
print(f"held-out tasks complete in every arm: {len(common)} of 115\n")
by = {t: {r["task"]: r for r in rows[t]} for t in TIERS}

print(f"{'tier':16} {'solved':>9} {'spend':>9} {'$/request':>11} {'wall p50':>9} {'turns p50':>10}")
summary = {}
for t in TIERS:
    rs = [by[t][i] for i in common]
    s = sum(r["solved"] for r in rs); usd = sum(r["agent_usd"] for r in rs)
    turns = [r["turns"] for r in rs if r["turns"]]
    summary[t] = dict(solved=s, n=len(rs), usd=usd)
    print(f"{t:16} {s:>4}/{len(rs):<4} {usd:>9.4f} {usd/len(rs):>11.5f} "
          f"{st.median([r['wall_s'] for r in rs]):>9.0f} {(st.median(turns) if turns else 0):>10.0f}")

print("\npaired against the reference, on the same held-out tasks:")
bounds = {}
for t in TIERS:
    if t == REF:
        continue
    both = cand = ref_only = neither = 0
    for i in common:
        a, b = by[t][i]["solved"], by[REF][i]["solved"]
        both += a and b; cand += a and not b; ref_only += b and not a; neither += (not a) and (not b)
    lcb = policy.paired_difference_lcb(both, cand, ref_only, neither)
    bounds[t] = lcb
    print(f"  {t:16} both {both:>3} candidate_only {cand:>3} reference_only {ref_only:>3} neither {neither:>3}"
          f"   lower bound {lcb:+.4f}")

print("\nreading 4 -- does nesting hold on this family?")
for t in TIERS:
    if t == REF:
        continue
    cross = [i for i in common if by[t][i]["solved"] and not by[REF][i]["solved"]]
    print(f"  {t:16} solves and the reference does not: {len(cross)} {cross[:6]}")

print("\nreading 3 -- what each margin compiled, and how it did out of fold")
tiers_reg = policy.load_registry("/Users/akazawt/tierbook/registry/tiers")
# throughput from this family's own latency, at the same sixteen in flight used elsewhere
box_lat = tiers_reg["self-hosted-a"].record["families"]["tool-agent-user-retail"]["latency"]["p50"]
tph = 3600 / box_lat * 16
print(f"  (fixed-cost tier amortised at {tph:,.0f} tasks/h, from this family's own {box_lat}s p50 at 16 in flight)")
ref_cost = summary[REF]["usd"] / summary[REF]["n"]
cheapest = min((t for t in TIERS if t != REF), key=lambda t: summary[t]["usd"])
for margin in (0.10, 0.15, 0.20, 0.25):
    d = policy.assign_family(tiers_reg, "tool-agent-user-retail", REF, margin=margin,
                             realised_tasks_per_hour=tph, today="2026-08-30")
    head = d.chosen.head
    hs = summary[head]
    per_req = hs["usd"] / hs["n"] + (tiers_reg[head].amortised_cost_per_task(tph) if head != REF else 0.0)
    verdict = []
    verdict.append("quality" if head == REF or bounds.get(head, -9) >= -margin else "QUALITY FAILS")
    verdict.append("beats the reference" if per_req < ref_cost else "NOT cheaper than the reference")
    cheap_req = summary[cheapest]["usd"] / summary[cheapest]["n"] + tiers_reg[cheapest].amortised_cost_per_task(tph)
    verdict.append("beats cheapest-alone" if per_req <= cheap_req + 1e-12 else "not better than cheapest-alone")
    print(f"  margin {margin:.2f} -> compiled {head:16} certified={str(d.certified):5} "
          f"${per_req:.5f}/req vs reference ${ref_cost:.5f}  [{'; '.join(verdict)}]")
