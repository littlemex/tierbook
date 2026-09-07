"""Join what happened to what it cost, by trace id, and refuse to price a partial join.

Three sources have to meet, and they have three different owners:

    outcomes    the task's own oracle said solved / incorrect / unobserved   (this project)
    telemetry   four token legs, turn order, latency, candidate tuple        (the agent, via OTLP)
    charge      what was actually billed                                     (the billing gateway)

They meet on a **trace id issued before the run starts** and passed into the agent, not on a time window.
The window join was the first design and it breaks the moment two runs overlap, which is the normal case in
a deployment and was already the case in one sweep here.

**Cost has two kinds and they are never one number.** A metered candidate's charge is authored by the
gateway and known per request. A fixed-cost candidate has no per-request charge to look up: its figure is the
period's bill divided by the work that period carried, so it exists only after a window closes. Dividing an
hourly bill by one sequential experimenter's task rate and calling it a cost per task is a mistake this
project already published; the amortised kind therefore never enters this join at all. It is applied later,
against a stated window, by whoever computes the frontier.

**Four refusals, and each of them is a cost figure that would have read as complete.** A partial join. A
charge with no outcome row -- money spent and attributed to nothing, which excluding leaves the cost of the part
that joined. A trace id collision, where the surviving row's state may belong to either run and everything
downstream keys on that id. And a row missing a billed leg, whose total is below what was paid. Counting any of
them and continuing was the earlier behaviour, and a count in a field nobody reads is not a guard.

**A partial join does not produce a partial cost figure; it produces no cost figure.** A cost summed over
the rows that happened to join reads as complete, and that is the failure this refuses. Coverage is reported
and a shortfall names the rows that are missing rather than the count.

**Which runs are this cohort's is decided here, and by two independent means.** The driver stamps a
`run_group` on every row so an orphaned driver from an aborted sweep cannot pose as this one's -- that is the
*intent*, and it can be lost: a sweep already running keeps executing the code it started with while each
child driver it spawns picks up the newer file, so one cohort here came out with the stamp present on 15 rows
and absent on 8. A stamp that a mid-flight edit can silently drop is not enough on its own, so the *invariant*
is checked too: a record asserts how many trials each item had, and this counts them. Two rows for one
(item, candidate) when one was asserted is the shape of the duplicate that reached a ledger once before, and
it is visible in the data whether or not anybody stamped anything.

SCOPE (see ../SCOPE.md, which governs this file): an instrument. It supplies parameters and states what it
cannot support; it decides nothing.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

#: How a cost may be described. The distinction is load-bearing, not descriptive: mixing them silently is
#: how a fixed bill becomes a per-request price.
METERED = "per_request_metered"
AMORTISED = "per_period_amortised"

#: Span attributes this join reads. Named so a change in the producer's vocabulary fails loudly here rather
#: than quietly producing zeros -- an absent leg read as 0 is the defect the ledger's own evidence rules
#: exist to prevent.
LEGS = {
    "fresh_in": "llm.token_count.prompt",
    "cached_in": "llm.token_count.prompt_details.cache_read",
    "cache_write": "llm.token_count.prompt_details.cache_write",
    "out": "llm.token_count.completion",
    "reasoning": "llm.token_count.completion_details.reasoning",
}
#: The legs a gateway bills. `reasoning` is read and carried but is NOT one of these: this project's price
#: cards charge reasoning tokens under output, so a span without a reasoning attribute is an ordinary
#: non-reasoning turn rather than a gap in the billing record. Priceability is judged on these four only.
BILLED_LEGS = ("fresh_in", "cached_in", "cache_write", "out")

CANDIDATE_ATTRS = {"agent": "agent.name", "model": "llm.model_name", "provider": "llm.provider"}


def _attr(span: dict) -> dict:
    out = {}
    for a in span.get("attributes", []):
        v = a.get("value") or {}
        out[a["key"]] = next(iter(v.values()), None) if v else None
    return out


def read_traces(path: Path) -> dict[str, dict]:
    """Group spans by trace id, keeping turn order from the LLM spans' own sequence.

    Turn order comes from the spans, not from a sort on a timestamp we chose: the session span is the parent
    and the LLM spans are its children, so the structure is the producer's rather than our reconstruction.
    """
    by_trace: dict[str, dict] = defaultdict(lambda: {"turns": [], "session": None})
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        for rs in doc.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for sp in ss.get("spans", []):
                    tid = sp.get("traceId")
                    if not tid:
                        continue
                    attrs = _attr(sp)
                    rec = by_trace[tid]
                    name = sp.get("name", "")
                    if name.endswith(".session"):
                        rec["session"] = attrs
                    elif name.endswith(".llm"):
                        rec["turns"].append({
                            "span_id": sp.get("spanId"),
                            "start": sp.get("startTimeUnixNano"),
                            "legs": {k: int(attrs.get(v) or 0) for k, v in LEGS.items()},
                            "missing_legs": sorted(k for k, v in LEGS.items() if v not in attrs),
                            "candidate": {k: attrs.get(v) for k, v in CANDIDATE_ATTRS.items()},
                            "finish_reason": attrs.get("llm.finish_reason"),
                            "duration_ms": attrs.get("duration_ms"),
                        })
    for rec in by_trace.values():
        # Ordered by the producer's own start time, and the index is assigned here so a reader never has to
        # re-derive it. A turn with no start time sorts last rather than being dropped.
        rec["turns"].sort(key=lambda t: int(t["start"] or 0))
        for i, t in enumerate(rec["turns"]):
            t["index"] = i
    return dict(by_trace)


def read_outcomes(path: Path, *, run_group: str | None = None,
                  admit_unstamped: bool = False) -> tuple[dict[str, dict], dict]:
    """Outcomes keyed by trace id, restricted to one cohort when one is named.

    Returns `(selected, selection)`. Three populations, kept apart because collapsing any two of them loses
    the thing the selection is for:

    - `run_group == the requested group` -- this cohort, always in.
    - another group                      -- another invocation's business, out, and counted.
    - no group at all                    -- written by a driver that did not stamp. Out by default and
                                            named, because admitting it silently would defeat the guard; in
                                            with `admit_unstamped`, and then recorded as admitted on the
                                            operator's word rather than on the driver's stamp, so a reader
                                            of the output can tell which it was.
    """
    rows, other, unstamped, collided = {}, [], [], []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not r.get("trace_id"):
            continue

        def take(row):
            # Keyed by trace id, so a second row under one id would silently replace the first -- the
            # plausible artifact of a driver that retried while reusing the id it had already issued. Counted
            # instead: a collision never reaches the trials invariant, because collapsing two rows into one is
            # exactly what makes the count look right.
            tid = row["trace_id"]
            if tid in rows:
                collided.append({"trace_id": tid, "item_id": row.get("item_id"),
                                 "kept_state": rows[tid].get("state"), "dropped_state": row.get("state")})
                return
            rows[tid] = row

        if run_group is None:
            take(r)
            continue
        g = r.get("run_group")
        if g == run_group:
            take(r)
        elif g is None:
            unstamped.append({"trace_id": r["trace_id"], "item_id": r.get("item_id")})
            if admit_unstamped:
                # Marked on the row itself, not only in the selection summary. Every consumer reads rows, and
                # a row indistinguishable from a stamped one loses the assertion-versus-observation
                # distinction that admitting it was supposed to record.
                take({**r, "cohort_membership": "asserted_by_operator_no_driver_stamp"})
        else:
            other.append({"trace_id": r["trace_id"], "item_id": r.get("item_id"), "run_group": g})
    selection = {
        "run_group": run_group,
        "selected": len(rows),
        "other_groups_excluded": other,
        "trace_id_collisions": collided,
        "unstamped": unstamped,
        "unstamped_admitted": bool(unstamped) and admit_unstamped,
        **({"unstamped_note":
            "these rows carry no run_group and were admitted on the operator's word, not on the driver's "
            "stamp. Their membership in this cohort is an assertion, not an observation"}
           if unstamped and admit_unstamped else {}),
    }
    return rows, selection


def read_charges(path: Path | None) -> dict[str, dict]:
    """Charges keyed by trace id, as the gateway reported them.

    Absent file means no metered candidate was involved, which is a legitimate state and not an error: a run
    entirely on a fixed-cost candidate has nothing here by construction.
    """
    if not path or not path.exists():
        return {}
    out = {}
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("trace_id"):
            out[r["trace_id"]] = r
    return out


def trials_per_item(rows: list[dict]) -> dict:
    """How many trials each (item, candidate) actually got, and whether that is one number.

    The ledger's records assert a `trials_per_item`, and an assertion nobody counts is how a duplicate row
    from an orphaned driver became a second trial of one item while the header still said one. Counted from
    the joined rows, so it holds whether or not the driver stamped a cohort.
    """
    counts: dict[tuple, list[str]] = defaultdict(list)
    for r in rows:
        c = r.get("candidate") or {}
        # Keyed by the WHOLE candidate, because that is what a record is keyed by. Keyed on the agent alone, a
        # three-model sweep counts three trials per item, and a duplicate of (item, model A) alongside a
        # missing (item, model B) still sums to three and passes as uniform -- so the very duplicate this
        # exists to catch is invisible whenever it coincides with a gap.
        counts[(r.get("item_id"), c.get("agent"), c.get("model"), c.get("provider"))].append(r["trace_id"])
    seen = sorted({len(v) for v in counts.values()})
    uneven = [{"item_id": k[0], "agent": k[1], "model": k[2], "provider": k[3],
               "trials": len(v), "trace_ids": sorted(v)}
              for k, v in sorted(counts.items(), key=lambda kv: str(kv[0])) if len(v) != (seen[0] if seen else 0)]
    return {"observed": seen, "uniform": len(seen) <= 1,
            "trials_per_item": seen[0] if len(seen) == 1 else None, "uneven": uneven,
            "candidates_seen": len({k[1:] for k in counts}),
            "uniformity_caveat":
                "uniform trials do not rule out a whole cohort collected twice: two runs of everything are "
                "uniform at two. The stamp is what distinguishes those, and this counts what the stamp cannot"}


def join(outcomes: dict, traces: dict, charges: dict, *, metered_providers: set[str]) -> dict:
    """One row per trace, plus the coverage figures that decide whether a cost may be stated at all."""
    rows, unjoined = [], []
    for tid, oc in sorted(outcomes.items()):
        tr = traces.get(tid)
        if tr is None:
            unjoined.append({"trace_id": tid, "missing": "telemetry", "item_id": oc.get("item_id")})
            continue
        providers = {t["candidate"].get("provider") for t in tr["turns"] if t["candidate"].get("provider")}
        metered = bool(providers & metered_providers)
        ch = charges.get(tid)
        if metered and ch is None:
            unjoined.append({"trace_id": tid, "missing": "charge", "item_id": oc.get("item_id"),
                             "providers": sorted(providers)})
            continue
        legs = {k: sum(t["legs"][k] for t in tr["turns"]) for k in LEGS}
        absent = sorted({m for t in tr["turns"] for m in t["missing_legs"] if m in BILLED_LEGS})
        # The module's own rule, applied to its own output. `read_traces` reads an absent attribute as 0, so a
        # total over turns that were missing a leg is BELOW what was billed -- and reporting `missing_legs`
        # beside that total leaves the total looking usable. Marked unpriceable here, where the row is built,
        # rather than hoping a refusal downstream sees the marker.
        priceable = not absent
        # A run whose turns did not all go to one candidate cannot be attributed to one -- but "candidate" is
        # (model, endpoint, decode policy), and the AGENT DEFINITION is not part of it. An agent that delegates
        # emits a different `agent.name` per subagent, so keying on the whole span attribute split one run across
        # several records: a first pass produced `agent-build` and `agent-unknown` from one cohort, and the paired
        # comparison then had two arms it could not line up. The definitions observed are recorded instead, which
        # is the delegation being visible rather than being mistaken for a candidate.
        served = {(t["candidate"].get("model"), t["candidate"].get("provider")) for t in tr["turns"]}
        definitions = sorted({t["candidate"].get("agent") for t in tr["turns"]
                              if t["candidate"].get("agent")})
        mixed = len(served) > 1
        # The definition the driver asked for, which is a property of the run rather than of a delegate's turn.
        root_definition = oc.get("agent_definition") or (definitions[0] if definitions else None)
        rows.append({
            "trace_id": tid,
            "item_id": oc.get("item_id"),
            "state": oc.get("state"),
            "unobserved_reason": oc.get("unobserved_reason"),
            "candidate": ({"agent": root_definition,
                           "model": tr["turns"][0]["candidate"].get("model"),
                           "provider": tr["turns"][0]["candidate"].get("provider")}
                          if tr["turns"] and not mixed else None),
            **({"agent_definitions_observed": definitions} if len(definitions) > 1 else {}),
            **({"served_mixed": [{"model": m, "provider": pr} for m, pr in sorted(
                served, key=lambda x: (str(x[0]), str(x[1])))]} if mixed else {}),
            # Carried onto the joined row, not left on the outcome row: `join` builds a new dict, and every
            # consumer reads these rows rather than the outcomes file.
            **({"cohort_membership": oc["cohort_membership"]} if oc.get("cohort_membership") else {}),
            "priceable": priceable,
            **({"unpriceable_because": f"token legs {absent} were absent from at least one turn, so the total "
                                       "is below what was billed. An absent leg is not a zero leg"}
               if absent else {}),
            "turns": len(tr["turns"]),
            "legs": legs,
            # Wall time as the driver observed it. Carried because the ledger needs a latency figure and the
            # driver is the only thing that saw the process start and stop; it is not a token count, so this
            # is not a second producer of anything.
            "wall_s": oc.get("wall_s"),
            # Two kinds, never one number. The amortised kind is deliberately absent here: it does not exist
            # per request and is applied against a closed window elsewhere.
            "cost": ({"kind": METERED, "usd": ch.get("usd"), "source": "gateway",
                      "gateway_request_id": ch.get("request_id")} if ch else
                     {"kind": AMORTISED, "usd": None,
                      "note": "fixed-cost candidate: no per-request charge exists; apply a period bill "
                              "divided by that period's work, with the window stated"}),
            "missing_legs": absent,
        })

    n = len(outcomes)
    # Charges with no outcome row are money that was spent and attributed to nothing. For a framework whose
    # purpose is cost this is the worst silent loss available, and iterating outcomes alone cannot see it: the
    # loop above never visits a charge it has no outcome for.
    orphan_charges = [{"trace_id": t, "usd": (c or {}).get("usd"),
                       "gateway_request_id": (c or {}).get("request_id")}
                      for t, c in sorted(charges.items()) if t not in outcomes]
    unpriceable = [{"trace_id": r["trace_id"], "item_id": r["item_id"],
                    "why": r.get("unpriceable_because")} for r in rows if not r.get("priceable")]
    return {
        "rows": rows,
        "coverage": {
            "outcomes": n,
            "joined": len(rows),
            "rate": round(len(rows) / n, 4) if n else None,
            "unjoined": unjoined,
            "charges_with_no_outcome": orphan_charges,
            "charges_with_no_outcome_usd": round(sum(c["usd"] or 0.0 for c in orphan_charges), 6),
            "unpriceable_rows": unpriceable,
        },
        # Counted, not asserted. A consumer that writes a `trials_per_item` into a record reads it from here
        # rather than hardcoding one, so a repeated sweep cannot be described as a single-trial one.
        "trials": trials_per_item(rows),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outcomes", required=True, help="JSONL, one row per run, with trace_id and state")
    ap.add_argument("--traces", required=True, help="the collector's traces.jsonl")
    ap.add_argument("--charges", help="JSONL from the gateway, with trace_id and usd. Absent is legitimate")
    ap.add_argument("--metered-providers", default=None,
                    help="comma-separated provider names whose charge the gateway authors. A provider not "
                         "listed is treated as fixed-cost, so its absence of a charge is not a shortfall")
    ap.add_argument("--no-metered-candidates", action="store_true",
                    help="state that this cohort involved no metered candidate at all. Required instead of "
                         "--metered-providers, so that 'everything is fixed-cost and no charge was ever "
                         "demanded' has to be asserted rather than reached by forgetting a flag")
    ap.add_argument("--run-group", help="restrict to one sweep invocation's rows. Without it every row in "
                                       "the file is taken, which is right for a file written by one sweep "
                                       "and wrong for one that outlived an aborted run")
    ap.add_argument("--admit-unstamped", action="store_true",
                    help="also take rows that carry no run_group. They exist: a sweep already running keeps "
                         "executing the code it started with, so a stamp added mid-flight appears only on "
                         "the children spawned after it. Their membership is then an assertion and is "
                         "recorded as one")
    ap.add_argument("--min-coverage", type=float, default=1.0,
                    help="below this, no cost figure is produced. Default 1.0 on purpose: a cost over the "
                         "rows that happened to join reads as complete")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    # The unsafe state was the default: with no `--metered-providers`, every provider is treated as
    # fixed-cost, no charge is ever demanded of anything, and coverage comes out 100% on a cohort where the
    # gateway's own figures were never consulted. So the two cases have to be told apart explicitly.
    if a.metered_providers is None and not a.no_metered_candidates:
        raise SystemExit(
            "[FAIL] give --metered-providers, or --no-metered-candidates to state that this cohort had none. "
            "Defaulting to 'none' would make a join that never demanded a charge look complete, which is the "
            "one failure this file exists to prevent.")

    outcomes, selection = read_outcomes(Path(a.outcomes), run_group=a.run_group,
                                        admit_unstamped=a.admit_unstamped)
    res = join(outcomes, read_traces(Path(a.traces)),
               read_charges(Path(a.charges) if a.charges else None),
               metered_providers={p for p in (a.metered_providers or "").split(",") if p})
    res["selection"] = selection
    cov = res["coverage"]

    if a.run_group:
        print(f"run_group {a.run_group}: {selection['selected']} rows selected, "
              f"{len(selection['other_groups_excluded'])} from other groups excluded, "
              f"{len(selection['unstamped'])} unstamped "
              f"({'admitted' if selection['unstamped_admitted'] else 'excluded'})")
        for u in selection["unstamped"][:8]:
            print(f"    unstamped: {u['trace_id'][:16]}… (item {u.get('item_id')})")

    rate = "n/a" if cov["rate"] is None else f"{cov['rate']:.1%}"
    print(f"outcomes {cov['outcomes']}  joined {cov['joined']}  coverage {rate}")
    metered = [r for r in res["rows"] if r["cost"]["kind"] == METERED]
    fixed = [r for r in res["rows"] if r["cost"]["kind"] == AMORTISED]
    print(f"  metered rows {len(metered)}  fixed-cost rows {len(fixed)}  "
          f"trials/item {res['trials']['trials_per_item']}")
    if cov["unjoined"]:
        print(f"  {len(cov['unjoined'])} unjoined, named in the output:")
        for u in cov["unjoined"][:8]:
            print(f"    {u['trace_id'][:16]}… missing {u['missing']} (item {u.get('item_id')})")
    missing_legs = sorted({m for r in res["rows"] for m in r["missing_legs"]})
    if missing_legs:
        print(f"  WARNING: token legs absent from some spans: {missing_legs}. Absent is not zero; the "
              "producer's vocabulary may have changed")
    def emit(refusal: str | None) -> None:
        """Write the artifact, and when refusing, write one that cannot be mistaken for a priced join.

        The output is still written on a refusal, because naming what is missing is the whole point of the
        file. But an earlier version wrote it BEFORE the checks ran, so a run that printed "[REFUSED] ... no
        cost figure is produced" left the full per-row costs on disk -- and anything reading the file rather
        than the exit code got exactly what the refusal claimed to withhold. So a refused artifact carries the
        refusal and has its cost fields replaced by it.
        """
        doc = dict(res)
        if refusal:
            doc["refused"] = refusal
            doc["rows"] = [{**r, "cost": {"kind": r["cost"]["kind"], "usd": None,
                                          "withheld_because": refusal}} for r in res["rows"]]
        Path(a.out).write_text(json.dumps(doc, indent=1) + "\n")

    if selection.get("trace_id_collisions"):
        print(f"\n[REFUSED] {len(selection['trace_id_collisions'])} trace id collision(s): two outcome rows "
              "under one id. Which run each row describes is ambiguous, and the surviving row's state may be "
              "either one -- counting the collision is not enough, because everything downstream keys on the "
              "trace id:")
        for c in selection["trace_id_collisions"][:6]:
            print(f"    {c['trace_id'][:16]}… item {c['item_id']}: kept {c['kept_state']}, "
                  f"dropped {c['dropped_state']}")
        emit(f"{len(selection['trace_id_collisions'])} trace id collision(s): attribution is ambiguous")
        return 6

    tr = res["trials"]
    if not tr["uniform"]:
        print(f"\n[REFUSED] trials per item are not uniform: {tr['observed']}. A record asserts one number "
              "here, and these rows do not have one. The rows below are the ones that differ -- an orphaned "
              "driver's row from an aborted sweep looks exactly like this:")
        for u in tr["uneven"][:8]:
            print(f"    {u['item_id']} / {u['agent']} / {u['model']}: {u['trials']} trials "
                  f"{[t[:12] for t in u['trace_ids']]}")
        emit(f"trials per item are not uniform: {tr['observed']}")
        return 4

    if cov["rate"] is not None and cov["rate"] < a.min_coverage:
        print(f"\n[REFUSED] coverage {cov['rate']:.1%} is below --min-coverage {a.min_coverage:.1%}. No cost "
              "figure is produced: a cost summed over the joined subset reads as complete.")
        emit(f"coverage {cov['rate']:.4f} is below the required {a.min_coverage:.4f}")
        return 3
    if cov["charges_with_no_outcome"]:
        print(f"\n[REFUSED] {len(cov['charges_with_no_outcome'])} charge(s) totalling "
              f"${cov['charges_with_no_outcome_usd']:.6f} have no outcome row. That is money spent and "
              "attributed to nothing, and a cost figure that excludes it is not this cohort's cost -- it is the "
              "cost of the part that joined:")
        for c in cov["charges_with_no_outcome"][:6]:
            print(f"    {c['trace_id'][:16]}… ${c['usd']} (gateway {c.get('gateway_request_id')})")
        emit(f"${cov['charges_with_no_outcome_usd']:.6f} of charges have no outcome row")
        return 7

    if cov["unpriceable_rows"]:
        print(f"\n[REFUSED] {len(cov['unpriceable_rows'])} row(s) are missing a token leg, so their totals "
              "are below what was billed. An absent leg is not a zero leg:")
        for u in cov["unpriceable_rows"][:6]:
            print(f"    {u['item_id']}: {u['why']}")
        emit("some rows are missing a token leg and their totals are below what was billed")
        return 5
    emit(None)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
