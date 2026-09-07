"""Turn joined observations into ledger records, so the compiler can be asked what policy they support.

**Reads the join, not the sweep.** The three sources -- the oracle's outcome, the agent's telemetry and the
gateway's charge -- meet in `join_sources.py` on a trace id, and this reads that output. An earlier version
read a sweep state and a recording pass-through directly, which made this a second producer of token figures
alongside the agent's own telemetry; two producers of one number is two things to keep correct and a
disagreement that surfaces later as a contradiction in a report.

This closes the loop the project has never closed on real data: measurement -> ledger -> compile -> policy.
Until it is closed, "the framework emits the supported policy" is a claim about code nobody has run on
anything measured.

Two decisions here matter more than the code.

**A candidate is `(agent, model, endpoint, decode policy)`, so that is what a record is.** Not the model. On
this sweep one agent is the model's own CLI fork, and its lead over another agent therefore contains an
affinity term that no amount of aggregation by model can separate from agent quality. A ledger keyed by model
would launder that affinity into the model's score.

**A validity condition travels with the record or the record is a trap.** Every figure here was taken with
one user at a time, sequentially, one repository per instance, against one engine, one run per instance, in a
fixed agent order over a prefix cache that cannot be flushed. Each of those bounds what the number may be
quoted for, so each is written into the record's own provenance rather than into a document beside it.

What is deliberately NOT written: any accuracy figure for a family with no verifier. This sweep's family has
one — the instances' own FAIL_TO_PASS and PASS_TO_PASS — which is why it can carry a solve rate at all.

SCOPE (see ../SCOPE.md, which governs this file): this is an instrument that supplies parameters. The policy
it enables the compiler to emit may well be degenerate -- one candidate for everything -- and that is a
correct output, not a disappointment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: The legs a record carries, in the ledger's own spelling.
LEG_KEYS = ("fresh_in", "cached_in", "cache_write", "out")

#: The engine the sweep ran against. Part of the candidate, not context: a measurement of an agent on one
#: model does not transfer to another model, and the affinity case in this sweep is why.
DEFAULT_MODEL = "Qwen/Qwen3.6-35B-A3B"
DEFAULT_ENDPOINT = "http://qwen-serving:8000/v1 (self-hosted vLLM, in-cluster)"

#: What bounds every figure in this sweep. Written into each record so it cannot be separated from the data.
VALIDITY = [
    "one user at a time, sequential; concurrency was 1",
    "one repository per instance; prefix reuse is within an instance, not across users",
    "one run per instance; the same agent varied 1.9x in input tokens across two runs of one task",
    "fixed agent order per instance, over a prefix cache that survives a run and has no reset endpoint",
    "solve rate is the instance's own FAIL_TO_PASS plus PASS_TO_PASS; no judge",
    "cost is the self-hosted rate card, which amortises a GPU hour over throughput measured at saturation; "
    "at low occupancy the true figure is hourly divided by realised tasks and is larger",
]


def legs_of(rows: list[dict]) -> tuple[int, int, int, int]:
    """The four billed legs, in whichever spelling and convention each arrived under."""
    fresh = read = write = out = 0
    for r in rows:
        u = r.get("usage") or {}
        det = u.get("prompt_tokens_details") or {}
        prompt = int(u.get("prompt_tokens") or 0)
        out += int(u.get("completion_tokens") or 0)
        dr, dw = u.get("cache_read_input_tokens"), u.get("cache_creation_input_tokens")
        if dr is not None or dw is not None:
            fresh += prompt
            read += int(dr or 0)
            write += int(dw or 0)
            continue
        r_leg = int(det.get("cached_tokens") or 0)
        w_leg = int(det.get("created_cache_tokens") or 0)
        read += r_leg
        write += w_leg
        fresh += max(0, prompt - r_leg - w_leg)
    return fresh, read, write, out


def _latency(wall: list[float]) -> dict:
    """Latency from the wall times the driver observed.

    The schema wants numbers, and a record with nulls here is refused -- correctly: a tier whose latency is
    unstated cannot be excluded by a latency constraint, so the absence would silently widen the admissible
    set. `concurrency_when_measured` is 1 and stated, because a latency measured alone is not the latency
    under load and a reader who cannot see the concurrency will assume it was the deployment's.
    """
    w = sorted(wall)
    n = len(w)
    if not n:
        raise SystemExit("[FAIL] no wall times in the joined rows; a record cannot state a latency it does "
                         "not have, and the schema is right to refuse nulls here")
    return {
        "unit": "seconds_per_task",
        "p50": round(w[n // 2], 1),
        "mean": round(sum(w) / n, 1),
        "p95": round(w[min(n - 1, int(0.95 * n))], 1),
        "max": round(w[-1], 1),
        "concurrency_when_measured": 1,
    }


def from_joined(a, doc: dict, rate: dict) -> int:
    """Build one record per candidate from joined rows.

    The candidate is the tuple the telemetry reported, so a record cannot be keyed by model with the agent
    demoted to metadata -- which is the laundering that would hide an agent-model affinity inside a model's
    score.
    """
    per: dict[str, dict] = {}
    for row in doc["rows"]:
        c = row.get("candidate") or {}
        key = f"{c.get('agent')}|{c.get('model')}|{c.get('provider')}"
        p = per.setdefault(key, {"candidate": c, "items": [], "legs": dict.fromkeys(LEG_KEYS, 0),
                                 "turns": 0, "cost_kinds": set(), "metered_usd": 0.0, "wall": []})
        p["items"].append({
            "item_id": row.get("item_id"),
            "state": row.get("state"),
            "unobserved_reason": row.get("unobserved_reason"),
        })
        for k in LEG_KEYS:
            p["legs"][k] += int((row.get("legs") or {}).get(k) or 0)
        p["turns"] += int(row.get("turns") or 0)
        if row.get("wall_s"):
            p["wall"].append(float(row["wall_s"]))
        cost = row.get("cost") or {}
        p["cost_kinds"].add(cost.get("kind"))
        if cost.get("kind") == "per_request_metered" and cost.get("usd") is not None:
            p["metered_usd"] += float(cost["usd"])

    out_root = Path(a.out)
    tiers_dir, ev_dir = out_root / "tiers", out_root / "evidence"
    tiers_dir.mkdir(parents=True, exist_ok=True)
    ev_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for key, p in sorted(per.items()):
        c = p["candidate"]
        agent = c.get("agent") or "unknown"
        ids = sorted(i["item_id"] for i in p["items"] if i["item_id"])
        suite_digest = hashlib.sha256(
            ("SWE-bench-Verified-pilot-subset\0" + "\0".join(ids)).encode()).hexdigest()
        header = {
            "suite_manifest_digest": f"standin:sha256:{suite_digest}",
            "suite_manifest_digest_caveat":
                "derived from the suite label and this cohort's sorted item ids, not from the benchmark's "
                "own task definitions. It detects a different item SET under this label, not a changed "
                "upstream release.",
            "run_id": f"joined-{a.family}:{agent}",
            "scorer_version": "SWE-bench Verified FAIL_TO_PASS + PASS_TO_PASS via agent/score.py; the test "
                              "patch is applied only after the candidate's diff is taken",
            "subject": f"agent-{agent}",
            "family": a.family,
            "trials_per_item": 1,
            "produced_at": "2026-09-07",
        }
        lines = [json.dumps(header, sort_keys=True)]
        for it in sorted(p["items"], key=lambda x: x["item_id"] or ""):
            v = {"item_id": it["item_id"], "state": it["state"]}
            if it["state"] == "unobserved":
                # The reason is required for an unobserved verdict and forbidden otherwise; the loader
                # refuses a row that carries both, which is the check that keeps a configuration fact out of
                # a capability rate.
                v["unobserved_reason"] = it["unobserved_reason"] or "execution_error"
            lines.append(json.dumps(v, sort_keys=True))
        body = "\n".join(lines) + "\n"
        digest = hashlib.sha256(body.encode()).hexdigest()
        ev_name = f"{a.family}-agent-{agent}-{digest[:16]}.jsonl"
        (ev_dir / ev_name).write_text(body)

        legs = p["legs"]
        total_in = legs["fresh_in"] + legs["cached_in"] + legs["cache_write"]
        solved = sum(1 for i in p["items"] if i["state"] == "solved")
        kinds = sorted(k for k in p["cost_kinds"] if k)
        rec = {
            "schema_version": 1,
            "id": f"agent-{agent}",
            "serves": {"model": c.get("model"), "endpoint": c.get("provider")},
            "measured_at": "2026-09-07",
            "provenance": {
                "repo": "github.com/littlemex/tierbook",
                **({"commit": a.commit} if a.commit else {}),
                "harness": "harness/sweep_agents.py, joined by harness/join_sources.py on a trace id",
                "candidate_is": "(agent definition, model, endpoint, decode policy)",
                "validity_conditions": VALIDITY,
                # Which kinds of cost the rows carried. A record whose rows are all amortised has no
                # per-request charge by construction, and saying so beats leaving a reader to infer it.
                "cost_kinds": kinds,
            },
            "claim": {"kind": "correctness", "metric": "resolved by the instance's own tests"},
            "oracle": {
                "kind": "executable_acceptance",
                "checker_id": "SWE-bench Verified FAIL_TO_PASS + PASS_TO_PASS via agent/score.py",
                "independent_of_candidate": True,
                "existed_before_candidate_output": True,
                "generator": None, "coverage": None,
            },
            "measurement_target": {
                "endpoint": c.get("provider"),
                "served_model_version": c.get("model"),
                "harness_commit": a.commit,
                "serving_stack": "vLLM, FP8, prefix caching on, max-num-seqs 128, 2 replicas",
                "gateway_version": None, "gateway_surface": None,
            },
            "adapter": {
                "wire": "chat_completions", "tool_calling": "native", "agent": agent,
                "compliance": {
                    "empty_diff_rate": round(
                        sum(1 for i in p["items"] if i["unobserved_reason"] == "unsupported")
                        / len(p["items"]), 4) if p["items"] else None,
                    "timeout_rate": round(
                        sum(1 for i in p["items"] if i["unobserved_reason"] == "execution_error")
                        / len(p["items"]), 4) if p["items"] else None,
                    "steps_observed": p["turns"],
                },
            },
            "price_card": {
                "unit": "usd_per_mtok",
                "source": f"measured rate card for the self-hosted engine, read from {Path(a.tiers).name}",
                "fresh_in": rate["fresh_in"], "cached_in": rate["cache_read"],
                "cache_write": rate["cache_write"], "output": rate["out"],
                "hourly_fixed_usd": None,
                "cache_hit_rate_observed": round(legs["cached_in"] / total_in, 4) if total_in else None,
                "reusable_cache_tokens": None,
            },
            "latency": _latency(p["wall"]),
            "reliability": {
                "attempts_observed": len(p["items"]),
                "failures": sum(1 for i in p["items"] if i["unobserved_reason"] == "execution_error"),
                "mean_sunk_usd": None,
                "failure_classes": sorted({i["unobserved_reason"] for i in p["items"]
                                           if i["unobserved_reason"]}),
            },
            "families": {
                a.family: {
                    "solved": solved,
                    "attempted": len(p["items"]),
                    "suite": "SWE-bench Verified, pilot-subset.json (stratified on repository and "
                             "difficulty with a fixed seed, chosen before any of this ran)",
                    "runs_per_item": 1,
                    "evidence": {"path": f"evidence/{ev_name}", "digest": f"sha256:{digest}"},
                    "tokens": dict(legs),
                }
            },
        }
        (tiers_dir / f"agent-{agent}.json").write_text(json.dumps(rec, indent=1) + "\n")
        written.append((agent, solved, len(p["items"]), total_in, kinds))

    print(f"wrote {len(written)} records to {tiers_dir} and artifacts to {ev_dir}")
    for agent, s_, at, ti, kinds in written:
        print(f"  agent-{agent:11s} {s_:2d}/{at}  in={ti:,}  cost_kinds={kinds}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--joined", help="output of join_sources.py: the single source for outcomes, tokens "
                                     "and charge. Preferred over --state")
    ap.add_argument("--state", help="legacy: a sweep state file, when no join output exists")
    ap.add_argument("--tap", help="legacy: the pass-through log. Not a producer; see --joined")
    ap.add_argument("--pods", help="legacy: kubectl get pods -o json, to attribute pass-through calls")
    ap.add_argument("--workdir", default=str(Path.home() / "tmp/e02/tap"))
    ap.add_argument("--out", required=True, help="directory to write records into")
    ap.add_argument("--family", default="agentic-coding")
    ap.add_argument("--tiers", default=str(HERE / "tiers.function-calling.json"),
                    help="where the self-hosted rate card is read from, rather than restated here")
    ap.add_argument("--commit", default=None, help="the sweep's commit, for provenance")
    a = ap.parse_args()

    rate = json.loads(Path(a.tiers).read_text())["self_hosted"]["rate"]
    if not a.joined and not a.state:
        raise SystemExit("[FAIL] one of --joined or --state is required")

    if a.joined:
        # The supported path. Every figure here came through the join, so a record can never disagree with
        # the telemetry it was built from.
        doc = json.loads(Path(a.joined).read_text())
        cov = doc.get("coverage") or {}
        if cov.get("rate") is not None and cov["rate"] < 1.0:
            # The join already refuses to price a partial set; refusing to build records from one is the
            # same rule one step later. A ledger built on the rows that happened to join reads as complete.
            raise SystemExit(
                f"[FAIL] the join covered {cov['rate']:.1%} of its outcomes ({cov.get('joined')} of "
                f"{cov.get('outcomes')}). Records are not built from a partial join: fix the unjoined rows "
                f"named in {a.joined} first.")
        return from_joined(a, doc, rate)

    state = json.loads(Path(a.state).read_text())
    done = {k: v for k, v in state["instances"].items() if v.get("outcome") == "done"}

    ips = {}
    if a.pods:
        for item in json.loads(Path(a.pods).read_text()).get("items", []):
            ip = (item.get("status") or {}).get("podIP")
            name = (item.get("metadata") or {}).get("name", "")
            if ip and name:
                parts = name.split("-")
                ips[ip] = "-".join(parts[:-2]) if len(parts) > 2 else name
    rows = []
    if a.tap:
        for line in Path(a.tap).read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("request"):
                rows.append(r)

    # Per-item outcomes, because the ledger's own validator refuses a hand-written summary for anything
    # measured after its 2026-08-31 evidence cutover -- and it is right to: a paired bound needs the items,
    # not the counts. The cohort is then derived from the evidence rather than asserted.
    items: dict[str, list[dict]] = {}
    per: dict[str, dict] = {}
    for inst, rec in sorted(done.items()):
        for key, run in (rec.get("runs") or {}).items():
            agent = key.split("#")[0]
            p = per.setdefault(agent, {"solved": 0, "attempted": 0, "empty": 0, "timeouts": 0,
                                       "wall": [], "legs": [0, 0, 0, 0], "calls": 0})
            p["attempted"] += 1
            if run.get("resolved"):
                p["solved"] += 1
            if run.get("files_touched") == 0:
                p["empty"] += 1
            if run.get("timed_out"):
                p["timeouts"] += 1
            if run.get("wall_s"):
                p["wall"].append(run["wall_s"])
            items.setdefault(agent, []).append({
                "item_id": inst,
                "solved": bool(run.get("resolved")),
                # An empty diff is a configuration fact and is carried so a reader can exclude it rather
                # than discovering later that it was folded into a solve rate.
                "empty_diff": run.get("files_touched") == 0,
                "timed_out": bool(run.get("timed_out")),
                "wall_s": run.get("wall_s"),
            })

            manifest = Path(a.workdir) / f"runs-{inst}.json"
            if not rows or not manifest.exists():
                continue
            for r in json.loads(manifest.read_text())["runs"]:
                if f"{r['agent']}#{r['iteration']}" != key:
                    continue
                lo, hi = r["started_wall"] - 1.0, r["ended_wall"] + 1.0
                mine = [x for x in rows if lo <= (x.get("ts") or 0) <= hi
                        and (not ips or ips.get(x.get("peer_ip", "")) == agent)]
                p["calls"] += len(mine)
                for i, v in enumerate(legs_of(mine)):
                    p["legs"][i] += v

    # The layout the ledger expects: records under <root>/tiers, artifacts under <root>/evidence, and an
    # evidence path in a record is resolved against <root> -- which the loader derives as the registry
    # directory's PARENT. Writing the artifacts next to the records puts them one level too deep and the
    # loader reports "no such artifact file" while the file plainly exists.
    root = Path(a.out)
    out = root / "tiers"
    ev_dir = root / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    ev_dir.mkdir(parents=True, exist_ok=True)

    def write_evidence(agent: str) -> tuple[str, str]:
        """One JSONL per candidate: a provenance header, then one verdict line per item.

        The filename carries the first 16 hex of the file's own digest, so the name is fixed once the bytes
        are and a merged or edited artifact cannot keep it. That is the ledger's mechanism for noticing that
        evidence changed under a record, and it is why the digest is computed before the name is chosen.

        **`unobserved` is not `incorrect`.** A run that timed out or edited nothing was not observed to be
        wrong; recording it as a failure would put a configuration fact into a capability rate. Three of the
        four agents here silently edited nothing until an autonomy flag was found, so this distinction is the
        difference between a solve rate and a fiction.
        """
        ids = sorted(r["item_id"] for r in items[agent])
        suite_digest = hashlib.sha256(
            ("SWE-bench-Verified-pilot-subset\0" + "\0".join(ids)).encode()).hexdigest()
        header = {
            "suite_manifest_digest": f"standin:sha256:{suite_digest}",
            "suite_manifest_digest_caveat":
                "derived from the suite label and this cohort's sorted item ids, not from SWE-bench's own "
                "task definitions. It detects a different item SET under this label, not a changed upstream "
                "release.",
            "run_id": f"sweep-2026-09-07:{agent}:pilot-subset",
            "scorer_version": "SWE-bench Verified FAIL_TO_PASS + PASS_TO_PASS via agent/score.py; the test "
                              "patch is applied only after the candidate's diff is taken",
            "subject": f"agent-{agent}",
            "family": a.family,
            "trials_per_item": 1,
            "produced_at": "2026-09-07",
        }
        lines = [json.dumps(header, sort_keys=True)]
        for r in sorted(items[agent], key=lambda r: r["item_id"]):
            if r["solved"]:
                v = {"item_id": r["item_id"], "state": "solved"}
            elif r["timed_out"]:
                v = {"item_id": r["item_id"], "state": "unobserved",
                     "unobserved_reason": "execution_error"}
            elif r["empty_diff"]:
                v = {"item_id": r["item_id"], "state": "unobserved",
                     "unobserved_reason": "unsupported"}
            else:
                v = {"item_id": r["item_id"], "state": "incorrect"}
            lines.append(json.dumps(v, sort_keys=True))
        body = "\n".join(lines) + "\n"
        digest = hashlib.sha256(body.encode()).hexdigest()
        name = f"{a.family}-agent-{agent}-{digest[:16]}.jsonl"
        (ev_dir / name).write_text(body)
        return f"evidence/{name}", f"sha256:{digest}"
    written = []
    for agent, p in sorted(per.items()):
        fresh, read, write, o = p["legs"]
        ev_path, ev_digest = write_evidence(agent)
        wall = sorted(p["wall"])
        n = len(wall)
        total_in = fresh + read + write
        # A record with no solved instances still belongs in the ledger: "this candidate solved none of 24"
        # is a measurement, and omitting it would let a reader assume it was never tried.
        rec = {
            "schema_version": 1,
            "id": f"agent-{agent}",
            "serves": {"model": DEFAULT_MODEL, "endpoint": DEFAULT_ENDPOINT},
            "measured_at": "2026-09-07",
            "provenance": {
                "repo": "github.com/littlemex/tierbook",
                **({"commit": a.commit} if a.commit else {}),
                "harness": "harness/sweep_agents.py over SWE-bench Verified pilot-subset",
                "candidate_is": "(agent, model, endpoint, decode policy); this record varies only the agent",
                "validity_conditions": VALIDITY,
            },
            "adapter": {
                "wire": "chat_completions",
                "tool_calling": "native",
                "agent": agent,
                "compliance": {
                    # An empty diff is a configuration fact, not incapability: three of four agents in this
                    # cluster silently edited nothing until an autonomy flag was found.
                    "empty_diff_rate": round(p["empty"] / p["attempted"], 4) if p["attempted"] else None,
                    "timeout_rate": round(p["timeouts"] / p["attempted"], 4) if p["attempted"] else None,
                    "steps_observed": p["calls"],
                },
            },
            "price_card": {
                "unit": "usd_per_mtok",
                "source": f"measured rate card for the self-hosted engine, read from {Path(a.tiers).name}",
                "fresh_in": rate["fresh_in"],
                "cached_in": rate["cache_read"],
                "cache_write": rate["cache_write"],
                "output": rate["out"],
                "hourly_fixed_usd": None,
                "cache_hit_rate_observed": round(read / total_in, 4) if total_in else None,
                "reusable_cache_tokens": None,
            },
            "latency": {
                "unit": "seconds_per_task",
                "p50": round(wall[n // 2], 1) if n else None,
                "mean": round(sum(wall) / n, 1) if n else None,
                "p95": round(wall[min(n - 1, int(0.95 * n))], 1) if n else None,
                "max": round(wall[-1], 1) if n else None,
                "concurrency_when_measured": 1,
            },
            "reliability": {
                "attempts_observed": p["attempted"],
                "failures": p["timeouts"],
                "mean_sunk_usd": None,
                # Named rather than counted, so a reader can tell a transport fault from a candidate that
                # produced nothing. The second is the one that looked like incapability here.
                "failure_classes": sorted(
                    ([] if not p["timeouts"] else ["timeout_at_agent_deadline"])
                    + ([] if not p["empty"] else ["produced_no_edit"])
                ),
            },
            # `claim` and `oracle` are structural, not notes: the difference between "this candidate solved
            # the task" and "this candidate agreed with a strong model" is the difference between a routable
            # measurement and a diagnostic, and an oracle produced by something that is also a candidate
            # scores that candidate perfectly by construction.
            "claim": {"kind": "correctness", "metric": "resolved by the instance's own tests"},
            "oracle": {
                "kind": "executable_acceptance",
                "checker_id": "SWE-bench Verified FAIL_TO_PASS + PASS_TO_PASS via agent/score.py",
                "independent_of_candidate": True,
                # The judging tests are absent from the checkout the candidate worked in, by construction:
                # the test patch is applied after the candidate's diff is taken.
                "existed_before_candidate_output": True,
                "generator": None,
                "coverage": None,
            },
            "measurement_target": {
                "endpoint": DEFAULT_ENDPOINT,
                "served_model_version": DEFAULT_MODEL,
                "harness_commit": a.commit,
                "serving_stack": "vLLM, FP8, prefix caching on, max-num-seqs 128, 2 replicas",
                "gateway_version": None,
                "gateway_surface": None,
            },
            "families": {
                a.family: {
                    "solved": p["solved"],
                    "attempted": p["attempted"],
                    "suite": "SWE-bench Verified, pilot-subset.json (stratified on repository and "
                             "difficulty with a fixed seed, chosen before any of this ran)",
                    "runs_per_item": 1,
                    "evidence": {"path": ev_path, "digest": ev_digest},
                    "tokens": {"fresh_in": fresh, "cached_in": read, "cache_write": write, "out": o},
                }
            },
        }
        path = out / f"agent-{agent}.json"
        path.write_text(json.dumps(rec, indent=1) + "\n")
        written.append((agent, p["solved"], p["attempted"], total_in))

    print(f"wrote {len(written)} records to {out} and artifacts to {ev_dir}")
    for agent, s, at, ti in written:
        print(f"  agent-{agent:11s} {s:2d}/{at}  in={ti:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
