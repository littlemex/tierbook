"""The command line, which is deliberately four verbs.

    tierbook validate    are these records well formed, and what is missing from them
    tierbook explain     what does the ledger say about a family, and what would each margin choose
    tierbook compile     write the table, with the evidence and the registry hash in it
    tierbook route       look a family up in a compiled table, and print why
    tierbook discover    print a DRAFT candidate file from a gateway's model list, for a human to edit
    tierbook preflight   ask each configured endpoint whether it will accept what a measurement needs
    tierbook export-vsr  turn a compiled table into a router configuration
    tierbook logs        what a log file can and cannot support as a benchmark
    tierbook attach-outcome  attach an observed outcome (label, tokens, latency) to a decision already logged

There is no `serve`. A component that decides where money goes should not also be the thing holding the
socket: the online decision is a dictionary lookup, and the caller already has a process.

There is no `measure` either, and that is the same boundary from the other side: running a benchmark is
somebody's suite, and anything that can write a record in the documented shape is a valid producer of one.
What is here is the part that must not be reinvented per suite -- the pre-flight that stops a transport
failure being recorded as a score, and the coverage report that stops a measurement over 12% of your traffic
being read as a measurement of your traffic.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from tierbook import SCHEMA_PATH, SCHEMA_VERSION, __version__, report
from tierbook.config import ConfigError, draft_from_model_list, load_config
from tierbook.decide import as_dict as decide_as_dict
from tierbook.decide import compile_policy
from tierbook.evidence import EvidenceError
from tierbook.policy import (assign_family, break_even_price, capacity_note, capacity_priority,
                             cutover_violation, evidence_class, load_registry, occupancy_at, registry_version,
                             reservation_verdict)
from tierbook.table import Unvalidated, check_fresh, compile_to_file, load_table, lookup

REQUIRED_FOR_A_DECISION = (
    ("families[<family>].attempted", "how many items the outcome was measured on"),
    ("families[<family>].cohort OR .evidence", "which items, so two records can be compared as a pair -- "
                                               "derived from evidence when present, hand-written otherwise"),
    ("families[<family>].paired_vs_reference OR .evidence",
     "the 2x2 against the reference on that same cohort -- derived from evidence when present"),
    ("price_card.fresh_in", "what a token costs"),
    ("measured_at", "when, so a stale record cannot win a comparison"),
)


def _registry(args) -> dict:
    tiers = load_registry(args.registry)
    if not tiers:
        sys.exit(f"no tier records found under {args.registry}")
    return tiers


def cmd_validate(args) -> int:
    tiers = _registry(args)
    print(f"{len(tiers)} records, registry version {registry_version(tiers)}")
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
        print("note: jsonschema is not installed, so shape is not checked (pip install 'tierbook[schema]')")
    schema = json.loads(SCHEMA_PATH.read_text()) if jsonschema else None
    bad = 0
    for t in tiers.values():
        if schema is not None:
            try:
                jsonschema.validate(t.record, schema)
            except Exception as e:  # noqa: BLE001 - the message is the product here
                bad += 1
                print(f"  {t.id}: does not match the schema -- {str(e).splitlines()[0]}")
        # The cutover: a record dated on or after EVIDENCE_CUTOVER_DATE may not carry a hand-written
        # summary for any family. Checked once per record, since measured_at lives at the record level.
        cutover = cutover_violation(t.record)
        if cutover:
            bad += 1
            print(f"  {t.id}: {cutover}")
        # A record can be schema-valid and still unable to support a decision. Say which.
        for family in (t.record.get("families") or {}):
            missing = []
            o = t.outcome(family) or {}
            if not o.get("attempted"):
                missing.append("attempted")
            if o.get("evidence"):
                # Re-verified now, not read back from a cached load: digest, path, schema, uniqueness,
                # trials_per_item -- everything `evidence.load` checks, checked again on every `validate`.
                try:
                    t.evidence(family)
                except EvidenceError as e:
                    bad += 1
                    print(f"  {t.id} / {family}: evidence does not load -- {e}")
            else:
                if not o.get("cohort"):
                    missing.append("cohort")
                if o.get("paired_vs_reference") is None and t.id != args.reference:
                    missing.append("paired_vs_reference")
            if missing:
                print(f"  {t.id} / {family}: schema-valid but cannot be certified -- missing {missing}")
    if bad:
        return 1
    print("every record can be read; see any notes above for what they cannot support")
    return 0


def cmd_explain(args) -> int:
    tiers = _registry(args)
    fam = args.family
    print(f"family {fam!r}, reference {args.reference!r}, registry {registry_version(tiers)}\n")
    print(f"{'tier':22} {'solved':>10} {'per request':>13} {'crossovers':>11}  cohort")
    for t in tiers.values():
        o = t.outcome(fam)
        if not o:
            print(f"{t.id:22} {'not measured':>10}")
            continue
        per = (o.get("bill_usd") or 0.0) / (o.get("attempted") or 1)
        # args.reference is in scope here, so a family carrying evidence derives the real 2x2 rather than
        # the None a lone Tier.paired(fam) would have to return without the other side. A manifest mismatch
        # is reported as "nothing to show" in this listing, not a crash of the whole explain command.
        try:
            p = t.paired(fam, tiers.get(args.reference)) or {}
        except EvidenceError:
            p = {}
        print(f"{t.id:22} {o['solved']:>4}/{o['attempted']:<5} {per:>13.5f} "
              f"{str(p.get('candidate_only')):>11}  {o.get('cohort')}")
    print("\nwhat each margin would choose:")
    for margin in args.margins:
        d = assign_family(tiers, fam, args.reference, margin=margin,
                          realised_tasks_per_hour=args.throughput, today=args.today,
                          request_can_reject=args.can_reject)
        print(f"  margin {margin:>5.2f} -> {'/'.join(d.chosen.tiers):28} certified={str(d.certified):5}")
        print(f"                  {d.why}")
    return 0


def cmd_compile(args) -> int:
    tiers = _registry(args)
    # The config is the source of families, objective and constraints when one is given. Flags stay for the
    # one-off case, but a deployment should be reading a committed file rather than a command line nobody
    # can review afterwards.
    cfg = _config(args) if args.config else None
    if cfg:
        families = {fam: decl.reference for fam, decl in cfg.families.items()}
        # The floor lives beside the reference in the SAME declaration, keyed the same way: it is a per-family
        # requirement (SCOPE sections 2, 5, 12 all say "the family's floor"), and a config file is where an
        # operator states one, not a flag -- see config.FamilyDeclaration.
        floors = {fam: decl.floor for fam, decl in cfg.families.items()}
        # Same reasoning, same shape, for the two numbers amendment 5 and S3 add to the same declaration: a
        # staleness limit and an exploration rate are per-family facts an operator states in the ledger, not a
        # flag -- threading them from anywhere else would be the `compile --floor` mistake amendment 2 found,
        # repeated for a second and third number.
        staleness_limits = {fam: decl.staleness_limit_days for fam, decl in cfg.families.items()}
        exploration_rates = {fam: decl.exploration_rate for fam, decl in cfg.families.items()}
        args.margin = args.margin if args.margin is not None else cfg.objective.margin
        args.alpha = cfg.objective.alpha
        args.max_age_days = cfg.objective.max_age_days
    else:
        if args.margin is None:
            sys.exit("--margin is required unless --config supplies one")
        if not args.family:
            sys.exit("--family FAMILY=REFERENCE is required unless --config supplies families")
        families = dict(pair.split("=", 1) for pair in args.family)
        # No config, so no family declaration to read a floor, a staleness limit or an exploration rate from.
        # `--family` is documented as the one-off path; a deployment that needs any of these three recorded
        # reads them from a committed candidate file instead.
        floors = {}
        staleness_limits = {}
        exploration_rates = {}
    tp = dict(cfg.throughput_per_family) if cfg else {}
    tp.update((k, float(v)) for k, v in (p.split("=", 1) for p in args.throughput_per_family or []))
    o = cfg.objective if cfg else None
    table = compile_to_file(tiers, families, args.out, margin=args.margin, alpha=args.alpha,
                            throughput_per_family=tp, today=args.today, max_age_days=args.max_age_days,
                            note=args.note or "", validations=args.validations,
                            objective=(o.objective if o else "cost"),
                            latency_slo_p95_ms=(o.latency_slo_p95_ms if o else None),
                            min_completion_probability=(o.min_completion_probability if o else None))
    # The three statements the table already contained the answers to and did not make: which kind of
    # policy this is, the frontier rather than only the chosen point, and whether the self-hosted candidate
    # can be used. Added to the artifact rather than printed only, because the next reader is a program.
    self_hosted = {t.id for t in tiers.values()
                   if (t.record.get("price_card") or {}).get("hourly_fixed_usd")}
    # A reservation's economics are a period question, so they are computed here -- where the window and a
    # metered candidate to quote the same traffic are available -- rather than inside a per-request price.
    # `undecidable` is a real answer and the common one: it says get a quote, not route away.
    metered = sorted(t for t in tiers if t not in self_hosted)
    counterfactual = tiers[metered[0]] if metered else None
    economics, capacity = {}, {}
    for fam in table.get("families", {}):
        for sid in sorted(self_hosted):
            economics[fam] = reservation_verdict(
                tiers[sid], fam, window_hours=args.window_hours, counterfactual=counterfactual)
            capacity[fam] = capacity_note(tiers[sid], fam)
            break

    # The policy as a function of observed state, not only as the point the cohort's state produced. Every
    # threshold in it is a measurement or a named gap; the reference is the declared default, because when no
    # rule holds the cheapest candidate is the one there is least reason to trust.
    # REPLICATES. A bound from a single probe run is refused, because repeating this deployment's own probe moved
    # p95 at 64 in flight from 17.5 s to 45.7 s. `--service-curve` is repeatable; each occurrence is one run.
    interleaved = json.loads(Path(args.interleaved).read_text()) if args.interleaved else None
    shape_for_family = (json.loads(args.shape_for_family) if args.shape_for_family else None)
    runs = []
    for path in (args.service_curve or []):
        probe = json.loads(Path(path).read_text())
        pts = probe.get("points") if isinstance(probe, dict) else probe
        if not pts:
            raise SystemExit(f"[FAIL] {path} carries no probe points")
        runs.append(pts)
    points = runs[0] if runs else None
    table["decide"] = {}
    # Occupancy per task AT THE BOUND, not at whatever concurrency was convenient: the slot value is a saving
    # divided by the occupancy it costs, and that occupancy is a property of the operating point. Taken from the
    # probe's own point at the derived bound when both exist, so the two numbers come from one measurement.
    seconds_at_bound = None
    for fam, entry in (table.get("families") or {}).items():
        for label in ("can_reject", "cannot_reject"):
            e = entry.get(label)
            if not isinstance(e, dict):
                continue
            pol = compile_policy(fam, e, reserved_ids=self_hosted,
                                 metered_ids={t for t in tiers} - self_hosted,
                                 default=(families[fam],),
                                 default_declared_by=("--config" if cfg else "--family FAMILY=REFERENCE"),
                                 # CONTRACT v0.3.0 C6: the ledger itself, so `compile_policy` can name every
                                 # candidate it records an outcome for rather than only the arm this compile
                                 # chose.
                                 tiers=tiers,
                                 service_curve=(runs or None),
                                 latency_p95_slo_s=(args.capacity_p95_slo_s
                                                    or ((o.latency_slo_p95_ms / 1000.0)
                                                        if o and o.latency_slo_p95_ms else None)),
                                 max_evidence_age_days=args.max_age_days,
                                 # Read from the family's own declaration (config.FamilyDeclaration), not a
                                 # flag: the floor is per family, and a table compiled without --config has no
                                 # declaration to read one from, so `floors.get(fam)` is `None` there -- absent
                                 # rather than guessed, and not one flag silently shared by every family. Same
                                 # source, same absence, for the two C3/amendment-5 numbers beside it.
                                 floor=floors.get(fam),
                                 staleness_limit_days=staleness_limits.get(fam),
                                 exploration_rate=exploration_rates.get(fam),
                                 # CONTRACT v0.3.0 C5: the same significance level `compile_to_file` above
                                 # already used for this table's non-inferiority calibration -- `alpha ** (1/n)`
                                 # is the ceiling a lower confidence bound at that same significance can ever
                                 # reach, so this is the existing number, not a second one.
                                 alpha=args.alpha)
            table["decide"].setdefault(fam, {})[label] = decide_as_dict(pol)
            bound = ((pol.domain or {}).get(f"inflight:{sorted(self_hosted)[0]}")
                     if self_hosted else None)
            if points and pol.can_ever_fire:
                target = next((g.threshold for r in pol.rules for g in r.guards
                               if g.var.startswith("inflight:") and g.measured), None)
                if target is not None:
                    # Little's law at the bound, not the mean latency there. A mean latency is a per-request
                    # wait; what a contended slot allocates is capacity, and capacity per task is concurrency
                    # over throughput. Using the latency inflated every slot value by about 23 percent.
                    seconds_at_bound, _ = occupancy_at(points, float(target))
            if not pol.can_ever_fire and pol.validated:
                print(f"  [WARN] {fam}/{label}: no rule can fire, so every request takes the declared "
                      f"default. Unmeasured: {pol.gaps}")
    # What a second of the box's occupancy is worth to each family, and therefore which family should get a
    # contended slot. Emitted as an order rather than applied: admitting a request is a scheduling act, and
    # this project decides which candidate rather than which request.
    if self_hosted:
        box = tiers[sorted(self_hosted)[0]]
        table["capacity_priority"] = capacity_priority(
            box, table.get("families") or {},
            alternatives={fam: tiers.get(families[fam]) for fam in (table.get("families") or {})
                          if families.get(fam) not in self_hosted},
            seconds_per_task=seconds_at_bound,
            interleaved=interleaved, shape_for_family=shape_for_family,
            # Whether the alternative is interchangeable on a family is the compiler's own finding, read from
            # the table rather than re-derived: a second, weaker answer to a question already answered is how
            # two parts of one program come to disagree.
            certified={fam: (((entry or {}).get("cannot_reject") or {}).get("status") == "assigned")
                       for fam, entry in (table.get("families") or {}).items()})
    report.annotate(table, self_hosted_ids=self_hosted, economics=economics, capacity=capacity)
    Path(args.out).write_text(json.dumps(table, indent=1) + "\n")
    if args.report:
        Path(args.report).write_text(report.render(table))
        print(f"wrote {args.report}")
    print(f"wrote {args.out} (format {table['table_format']}, registry {table['registry_version']}, "
          f"objective {table['objective']}, margin {table['margin']})")
    for family, entry in table["families"].items():
        ev = entry["evidence"]
        print(f"  {family}: cannot_reject -> {'/'.join(entry['cannot_reject']['chosen'])} "
              f"(certified={entry['cannot_reject']['certified']}), "
              f"can_reject -> {'/'.join(entry['can_reject']['chosen'])}")
        print(f"    evidence: {ev['reference_attempted']} items, nested={ev['nested']}, "
              f"crossovers={ev['crossovers']}")
        for label in ("cannot_reject", "can_reject"):
            v = entry[label]
            print(f"    {label:14} status={v['status']:12} {v['validation']['reason'][:110]}")
        rs = entry.get("rank_stability")
        if rs and not rs["stable"]:
            print(f"    RANK UNSTABLE across folds: calibration {rs['calibration_order']} "
                  f"vs held-out {rs['holdout_order']} -- the calibration fold cannot pick between these")
        if (ev["reference_attempted"] or 0) < args.min_items:
            print(f"    WARNING: {ev['reference_attempted']} items is below --min-items={args.min_items}. "
                  "This project compiled a wrong answer from 20.")
    return 0


def cmd_route(args) -> int:
    table = load_table(args.table)
    if args.registry:
        stale = check_fresh(table, load_registry(args.registry))
        if stale:
            print(f"WARNING: {stale}", file=sys.stderr)
    try:
        arrangement, entry = lookup(table, args.family, request_can_reject=args.can_reject,
                                    allow_unvalidated=args.allow_unvalidated)
    except Unvalidated as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(json.dumps({
        "family": args.family,
        "send_to": arrangement.tiers[0],
        "then": list(arrangement.tiers[1:]),
        # CONTRACT C1 (amendment 3): reported as `validated`, not `certified`. `entry["certified"]` (`policy.py`'s
        # `Decision.certified`, the offline calibration-fold judgment `assign_family` computes) is unchanged and
        # stays under its own name in its own subsystem; only the KEY this online JSON reports it under changes,
        # because this is exactly the JSON a persona round found an operator trusting as a section 2 floor check
        # when it was never that.
        "validated": entry["certified"],
        "why": entry["why"],
        "status": entry.get("status"),
        "validated_by": (entry.get("validation") or {}).get("holdout"),
        "escalate_only_on": list(__import__("tierbook").OBSERVABLE_FAILURES),
    }, indent=2))
    return 0


def _config(args):
    try:
        return load_config(args.config)
    except ConfigError as e:
        sys.exit(f"{args.config}: {e}")


def cmd_discover(args) -> int:
    """Print a draft candidate file. Deliberately does not write one, and deliberately does not load.

    A gateway advertises names. It does not tell you what it charges you, what it can do, or whether it is
    any good -- this project checked, and a live model list returned identifiers and display names and
    nothing else. So the draft comes out with every price left null, which means it will not load until a
    human fills one in. That is the intended friction: a candidate discovered at compile time would make a
    routing decision depend on a gateway's publication state that nobody committed to.
    """
    import urllib.request

    url = args.base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    key = os.environ.get(args.api_key_env or "")
    if key:
        req.add_header("authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read().decode())
    models = body.get("data") or body.get("models") or []
    draft = draft_from_model_list(models, base_url=args.base_url,
                                  api_key_env=args.api_key_env or "TIERBOOK_API_KEY")
    print(json.dumps(draft, indent=2))
    print(f"\n{len(draft['candidates'])} candidates drafted from {url}. Every price is null, so this file "
          "will not load until you fill in what a token costs or delete the entry. Nothing here is measured.",
          file=sys.stderr)
    return 0


def cmd_preflight(args) -> int:
    """Ask each endpoint the smallest version of the question a measurement will ask.

    Exits non-zero on an incompatibility so that a Job fails here rather than recording a zero. The three
    answers are kept apart because they need different actions: capable, reachable-but-refusing this feature
    combination, and unreachable.
    """
    from tierbook.endpoints import INCOMPATIBLE, OK, UNREACHABLE, negotiate

    cfg = _config(args)
    bad = 0
    for cid, cand in sorted(cfg.candidates.items()):
        ep, probe = negotiate(cand.endpoint, needs_tools=args.require_tools)
        mark = {OK: "ok", INCOMPATIBLE: "INCOMPATIBLE", UNREACHABLE: "UNREACHABLE"}[probe.status]
        print(f"{cid:24} {mark:14} wire={probe.wire:9} {probe.detail[:150]}")
        if probe.status != OK:
            bad += 1
        elif ep.wire != cand.endpoint.wire:
            print(f"{'':24} note: measure this over {ep.wire!r}, not the declared {cand.endpoint.wire!r}, "
                  "and record the wire that was used")
    if bad:
        print(f"\n{bad} endpoint(s) cannot be measured as configured. This is a transport fact, not a "
              "capability one: do not record the resulting score.", file=sys.stderr)
    return 1 if bad else 0


def cmd_export_vsr(args) -> int:
    """Write the router config, and the Envoy config beside it.

    Both, because a router config alone routes nothing: the ExtProc names a model in a header and something
    has to dial the upstream that name refers to. Emitting only the first is how this exporter previously
    produced a deployment with no data plane in it.
    """
    from tierbook.export_vsr import ExportError, envoy_config, export, models_used, write

    cfg = _config(args)
    table = load_table(args.table)
    signals = dict(pair.split("=", 1) for pair in (args.signal or []))
    cats = {}
    for spec in (args.signal_categories or []):
        label, _, joined = spec.partition("=")
        cats[label] = [c for c in joined.split(",") if c]
    try:
        conf, prov = export(table, cfg, signal_for_family=signals, default_model=args.default_model,
                            listener_port=args.port, entrypoint=args.entrypoint,
                            request_can_reject=args.can_reject,
                            allow_provisional=args.allow_provisional, signal_kind=args.signal_kind,
                            signal_categories=cats)
    except ExportError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    write(conf, args.out)
    # Beside the config, not inside it: the router rejects an unknown top-level key with a warning on every
    # start, and a config that warns every time is a config whose warnings stop being read.
    prov_path = write(prov, f"{args.out}.provenance.json")
    print(f"wrote {args.out}: {len(conf['routing']['decisions'])} decision(s) from registry "
          f"{prov['compiled_from_registry']}")
    print(f"wrote {prov_path}: what this config was compiled from")
    if args.envoy_out:
        try:
            envoy = envoy_config(cfg, models_used(conf), listen_port=args.envoy_port,
                                 extproc_port=args.extproc_port)
        except ExportError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 2
        write(envoy, args.envoy_out)
        print(f"wrote {args.envoy_out}: {len(envoy['static_resources']['clusters'])} cluster(s), "
              "including the ExtProc over loopback")
    for skipped in prov["families_skipped"]:
        print(f"  skipped {skipped}")
    return 0


def _tri(v: str):
    """A three-valued flag. `--authorised` and `--latency-feasible` are absent, true or false, and absent is not
    false: SCOPE section 2 makes a latency condition ABSENT where the operator set none, and reading an unset flag as
    false would refuse every candidate for a constraint nobody imposed."""
    if v is None or v == "" or v.lower() in ("none", "unset", "absent"):
        return None
    if v.lower() in ("1", "true", "yes", "y"):
        return True
    if v.lower() in ("0", "false", "no", "n"):
        return False
    raise argparse.ArgumentTypeError(f"{v!r} is not true, false, or absent")


def cmd_observe(args) -> int:
    """Read the state a policy would decide from, and say what could not be read.

    Separate from `assign` so an operator can see the state before trusting a decision made from it. A collector that
    could only be exercised through the decision would hide its own refusals behind an assignment.
    """
    from tierbook.observe import observe

    prev = None
    if args.previous and Path(args.previous).exists():
        prev = json.loads(Path(args.previous).read_text()).get("readings")
    got = observe(candidate=args.candidate, metrics_url=args.metrics_url, model_name=args.model_name,
                  gateway_authorised=args.authorised, measured_on=args.measured_on, previous=prev)
    print(json.dumps(got.as_dict(), indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(got.as_dict(), indent=1))
    # Non-zero when the state is incomplete, so a deploy script cannot proceed on a state nobody looked at.
    return 0 if got.complete else 3


def cmd_assign(args) -> int:
    """One turn of the loop: observe, decide, record.

    Every request is assigned somewhere -- section 2 of SCOPE is explicit that there is no "choose nothing" -- so this
    prints an assignment even when nothing could be certified, and the record says which it was.

    `--floor` is optional here: the policy artifact carries the floor it was compiled under (decide.Policy.parameters,
    C2), so a caller with nothing to add gets the artifact's own value. A caller who DOES supply one is checked
    against the artifact through `decide.parameter` rather than trusted outright -- a floor typed at this shell prompt
    that disagrees with the one the table was compiled under is exactly the "two homes for one number" this exists to
    refuse, so a mismatch exits 4 rather than picking a side.

    `--policy-version` is optional for the same reason and checked the same way: `route_once` reads the artifact's
    own digest (`decide.policy_digest`, CONTRACT C2), and a value typed here that disagrees with it exits 4 rather
    than being written into the record as if it had been confirmed.
    """
    from tierbook.decide import from_dict, parameter
    from tierbook.observe import observe
    from tierbook.record import BoundProvenance, Log
    from tierbook.serve import route_once

    policy = from_dict(json.loads(Path(args.policy).read_text()))
    try:
        floor = parameter(policy, "floor", args.floor)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 4
    # No CLI flag for either (amendment 2's lesson, applied to the two numbers amendment 5 adds beside the
    # floor): the artifact is the one source, read with `supplied=None` because there is nothing typed at this
    # shell prompt to check it against.
    staleness_limit_days = parameter(policy, "staleness_limit_days", None)
    exploration_rate = parameter(policy, "exploration_rate", None)
    prev = None
    if args.previous and Path(args.previous).exists():
        prev = json.loads(Path(args.previous).read_text()).get("readings")
    got = observe(candidate=args.candidate, metrics_url=args.metrics_url, model_name=args.model_name,
                  gateway_authorised=args.authorised, measured_on=args.measured_on, previous=prev)
    # CONTRACT C1: `--bound-provenance` replaces `--bound-kind`. A free string could assert any correction at all;
    # this is parsed into `record.BoundProvenance` so `estimator` and `corrected_over` are checked against their
    # closed vocabularies before the record is ever written, not after.
    bp_raw = json.loads(args.bound_provenance) if args.bound_provenance else None
    bound_provenance = (BoundProvenance(estimator=bp_raw["estimator"], confidence=bp_raw["confidence"],
                                        corrected_over=tuple(bp_raw.get("corrected_over", ())))
                        if bp_raw else None)
    try:
        decision, record = route_once(
            policy=policy, observation=got, request_id=args.request_id,
            feature_vector_version=args.feature_vector_version, policy_version=args.policy_version,
            mechanism_version=__version__,
            agent=args.agent, model=args.model_name or "", endpoint=args.endpoint,
            gateway_quote_usd=args.quote_usd,
            bounds=json.loads(args.bounds) if args.bounds else None,
            costs=json.loads(args.costs) if args.costs else None,
            evidence_as_of=args.measured_on or "",
            # Without a floor, every non-chosen candidate is recorded `not_evaluated` rather than being assigned a
            # reason nobody computed. With one, the reason comes from the same admissibility function the
            # falsifier uses.
            bound_provenance=bound_provenance, floor=floor, latency_feasible=args.latency_feasible,
            max_age_days=args.max_age_days,
            exploration_rate=exploration_rate, staleness_limit_days=staleness_limit_days,
            log=Log(args.log) if args.log else None)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 4
    print(json.dumps({
        # `decision["assign"]` is decide()'s own proposed cascade, unchanged by exploration -- useful on its own
        # to see what the deterministic policy would have done. `served` is `record.chosen`, the arm exploration
        # actually drew (CONTRACT C3): the two can now differ, where before C3 they never could, so both are
        # printed rather than one silently standing in for the other.
        "assign": decision["assign"], "served": record.chosen, "certified": record.certified,
        "reason": decision["reason"], "gaps": record.gaps,
        "state_ref": record.state_ref, "logged_to": args.log,
        "exploration": record.exploration, "exploration_reason": record.exploration_reason,
    }, indent=2))
    return 0


def cmd_accept(args) -> int:
    """SCOPE section 12's criteria over a decision log, each with its own verdict.

    Exits non-zero on a failure and zero otherwise, including when most criteria are `unsupported`: an unsupported
    criterion is a measurement nobody has made, not a defect in the mechanism, and treating it as a failure would make
    the check impossible to adopt.

    `--floor` is optional given `--policy`: the artifact carries the floor it was compiled under (C2), and a supplied
    value is checked against it through `decide.parameter` rather than trusted outright -- a mismatch exits 4. Without
    `--policy` there is nothing to check against, so `--floor` is required and the output records that the number was
    operator-supplied and unchecked, which is the honest description of what `no_false_certification: pass` in
    docs/verify/v0.1.0-accept.json actually rested on.
    """
    from tierbook.accept import FAIL, check_all, summarise
    from tierbook.decide import from_dict, parameter
    from tierbook.record import Log

    max_age_days = None
    max_age_provenance = "not checked: no --policy was given to read a limit from"
    floor_ceiling = None
    if args.policy:
        policy = from_dict(json.loads(Path(args.policy).read_text()))
        try:
            floor = parameter(policy, "floor", args.floor)
        except ValueError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 4
        floor_provenance = (f"checked against {args.policy} through decide.parameter"
                            if args.floor is not None else f"read from {args.policy}'s compiled parameters")
        # The artifact's own value, `supplied=None` because there is no CLI flag to check it against (amendment
        # 7, C6, following amendment 2's rule for the floor): a second typed number here would reopen the very
        # defect amendment 2 closed, in a second value.
        max_age_days = parameter(policy, "max_evidence_age_days", None)
        # CONTRACT v0.3.0 C5: same reason and same rule as `max_evidence_age_days` above -- no flag confirms
        # it, because there is nothing an operator would type here that the artifact did not already compute.
        # `None` for a v0.2.0 artifact (no `floor_ceiling` key at all) makes `floor_is_reachable` UNSUPPORTED
        # rather than this command guessing a verdict for a policy that never carried the number.
        floor_ceiling = parameter(policy, "floor_ceiling", None)
        # Recorded, not just used. The floor got `floor_provenance` because a number that reached the
        # computation with no copy in the record is exactly what C2 audited and found -- zero recorded
        # copies. This value arrived the same way, and `null` alone is ambiguous between "the operator
        # declared no limit, so the condition is absent" and "there was no artifact to read it from".
        max_age_provenance = (f"read from {args.policy}'s compiled parameters"
                              if max_age_days is not None else
                              f"{args.policy} declares no limit, so freshness is absent as a condition "
                              f"rather than unchecked")
    else:
        if args.floor is None:
            # 2, argparse's own code for an argument that had to be supplied and was not, because that is the
            # operator action here: supply something. 4 is reserved for two present numbers that disagree, which is
            # a different action -- one of the two sources is wrong and has to be found. Collapsing them would tell
            # an operator to go looking for a conflict that does not exist.
            print("--floor is required without --policy: there is no artifact to read it from or check it against",
                  file=sys.stderr)
            return 2
        floor = args.floor
        floor_provenance = "operator-supplied and unchecked: no --policy was given to confirm it against"

    decisions, outcomes = Log(args.log).read()
    verdicts = check_all(decisions, outcomes, floor=floor,
                         latency_feasible=args.latency_feasible,
                         uncertified_tolerance=args.uncertified_tolerance,
                         budgeted_exploration=args.budgeted_exploration,
                         latency_limit_s=args.latency_limit_s, slo_tolerance=args.slo_tolerance,
                         significance=args.significance, max_age_days=max_age_days,
                         floor_ceiling=floor_ceiling)
    out = {"verdicts": [v.as_dict() for v in verdicts], "summary": summarise(verdicts),
          "floor": floor, "floor_provenance": floor_provenance,
          "max_age_days": max_age_days, "max_age_days_provenance": max_age_provenance,
          # CONTRACT C12. Always present, empty when the reader understood every field: a key that
          # appears only when something went wrong leaves a reader unable to tell "this reader
          # understood everything" from "this version of the tool did not look". It does NOT make a
          # criterion unsupported -- nothing was lost from the population, unlike C11's two classes.
          "ignored_keys": dict(outcomes.get("__ignored_keys__") or {}),
          # CONTRACT amendment 12 (C4). Always present for the same reason `ignored_keys` is: a key that appears
          # only when something went wrong leaves a reader unable to tell "every label found its decision" from
          # "this version did not look". Labels aimed at ids no decision carries are why a realised rate can be
          # missing from a log that visibly contains labels, and a report that omitted them would attribute the
          # gap to a measurement nobody took.
          "orphan_outcomes": dict(outcomes.get("__orphan_outcomes__") or {})}
    print(json.dumps(out, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1))
    return 1 if any(v.verdict == FAIL for v in verdicts) else 0


def cmd_logs(args) -> int:
    """What a log file can support, stated before anyone builds a benchmark out of it."""
    from tierbook.logs import coverage, extract_tasks

    tasks = extract_tasks(args.path)
    cov = coverage(tasks)
    print(json.dumps(cov, indent=2))
    if cov["with_admissible_check"] == 0:
        print("\nNot measurable for correctness from these logs: no item carries a check that something "
              "other than a model decided. That is a real result -- it says what you would have to record to "
              "make your own traffic measurable, and it is better than a number built from a model's "
              "opinion of another model's answer.", file=sys.stderr)
        return 1
    print(f"\n{cov['with_admissible_check']} of {cov['logs_considered']} items "
          f"({cov['fraction']:.1%}) can support a correctness measurement. A record built from them is about "
          "that subset and not about the rest of your traffic.", file=sys.stderr)
    return 0


def cmd_attach_outcome(args) -> int:
    """Attach an observed outcome to a decision already in the log -- the documented door onto a labelled log.

    Attaches only. `label_state` and `label` are read as facts the caller observed, not decided here: this
    command does not read a family's `label_source`, does not invoke a labeller, and does not call
    `record.classify_label` -- deciding what a label is belongs to `classify_label`, and a component here that
    ran a labeller would cross the boundary this module's own docstring draws between what this project does
    and "somebody's suite."

    CONTRACT amendment 11: the log is read BEFORE the append, and two mistakes are refused at this door rather
    than left for the next `Log.read()` to catch. Both were measured to be accepted by `Log.attach_outcome`
    alone: an outcome for a `request_id` this log holds no decision for (it joins to nothing, and
    `Log.read` never complains because nothing there conflicts), and a label that disagrees with one already
    recorded for this `request_id` (append succeeds, and the log becomes unreadable only on the NEXT
    `Log.read()` -- one append too late, because the log is append-only and that append cannot be undone).
    `Log.read`'s own check for the second case is left exactly as it is: it is what catches a second writer, a
    second implementation, or a hand-edited line -- callers this door was never shown to.
    """
    from tierbook.record import Incomplete, Log

    decisions, outcomes = Log(args.log).read()
    known_ids = {d["request_id"] for d in decisions}
    if args.request_id not in known_ids:
        print(f"refused: {args.request_id!r} is not a request_id this log holds a decision for. An outcome "
              f"attached to a request the log never recorded joins to nothing, and this door only joins an "
              f"outcome to a decision already logged", file=sys.stderr)
        return 1
    prev = outcomes.get(args.request_id)
    if prev is not None and prev.get("label_state") == "labelled":
        if prev.get("label") != args.label or args.label_state != "labelled":
            print(f"refused: {args.request_id!r} already carries the label {prev.get('label')!r} and this call "
                  f"says {args.label!r} ({args.label_state}). A label that changes makes every criterion "
                  f"computed over this log a criterion over the rewrite", file=sys.stderr)
            return 1
    outcome_kw = {}
    if args.tokens is not None:
        outcome_kw["tokens"] = args.tokens
    if args.latency_s is not None:
        outcome_kw["latency_s"] = args.latency_s
    try:
        Log(args.log).attach_outcome(args.request_id, label_state=args.label_state, label=args.label,
                                     **outcome_kw)
    except Incomplete as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    print(f"attached outcome for {args.request_id!r}: label_state={args.label_state} label={args.label}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Deferred, like `record.Log`/`record.Incomplete` elsewhere in this module: only `attach-outcome` needs
    # LABEL_STATES, to build its own `--label-state` choices below.
    from tierbook.record import LABEL_STATES

    # --registry is accepted before or after the subcommand, because both read naturally and a tool that
    # rejects the second spelling is teaching its user a lesson nobody asked for.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--registry", default="registry/tiers", help="directory of tier records")

    p = argparse.ArgumentParser(prog="tierbook", description=__doc__.splitlines()[0], parents=[common])
    p.add_argument("--version", action="version", version=f"tierbook {__version__} (schema {SCHEMA_VERSION})")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", parents=[common],
                       help="check the records, and say what they cannot support")
    v.add_argument("--reference", default="", help="the reference tier, which needs no paired 2x2")
    v.set_defaults(fn=cmd_validate)

    e = sub.add_parser("explain", parents=[common], help="what the ledger says, and what each margin would choose")
    e.add_argument("--family", required=True)
    e.add_argument("--reference", required=True)
    e.add_argument("--margins", type=float, nargs="+", default=[0.05, 0.10, 0.15, 0.20, 0.25])
    e.add_argument("--throughput", type=float, default=None,
                   help="realised tasks per hour FOR THIS FAMILY, for a fixed-cost tier")
    e.add_argument("--can-reject", action="store_true",
                   help="requests in this family carry a check that can reject the artifact")
    e.add_argument("--today", default=None)
    e.set_defaults(fn=cmd_explain)

    c = sub.add_parser("compile", parents=[common], help="write the table an online path may read")
    c.add_argument("--config", default=None,
                   help="candidate file supplying families, objective and constraints")
    c.add_argument("--family", action="append", metavar="FAMILY=REFERENCE_TIER")
    c.add_argument("--out", required=True)
    c.add_argument("--margin", type=float, default=None,
                   help="non-inferiority margin in solve-rate points, fixed BEFORE looking at outcomes")
    c.add_argument("--alpha", type=float, default=0.05)
    c.add_argument("--throughput-per-family", action="append", metavar="FAMILY=TASKS_PER_HOUR")
    c.add_argument("--max-age-days", type=int, default=90)
    c.add_argument("--min-items", type=int, default=100,
                   help="warn below this many measured items per family; 20 produced a wrong answer here")
    c.add_argument("--service-curve", action="append", default=None,
                   help="the load probe's own output (harness/service_curve.py), carrying a concurrency, a "
                        "throughput and a p95 latency per point. The reserved candidate's occupancy bound is "
                        "DERIVED from those points against the p95 below. A scalar is deliberately not "
                        "accepted: a number a caller passes is a configured threshold whatever the "
                        "documentation beside it says. REPEATABLE, and at least two runs are required: repeating "
                        "this deployment's probe moved p95 at 64 in flight from 17.5 s to 45.7 s, so one run does "
                        "not measure a property of the candidate. Without agreeing runs the guard is emitted "
                        "unmeasured, no rule can fire, and the missing measurement is named")
    c.add_argument("--interleaved", default=None,
                   help="the mixed-traffic probe's output (harness/service_curve.py --interleave), which gives "
                        "each request shape's occupancy at ONE operating point. The only source that makes "
                        "families comparable: shapes measured separately sit at different operating points, and "
                        "two real shapes at 64 in flight differed by a factor of twelve")
    c.add_argument("--shape-for-family", default=None,
                   help="JSON map of family to the shape label it was measured under in that probe")
    c.add_argument("--capacity-p95-slo-s", type=float, default=None,
                   help="the p95 seconds this family must meet, used to locate the occupancy bound on the "
                        "measured curve. Defaults to the objective's own latency SLO when a config supplies "
                        "one, because it is the same constraint. Throughput alone cannot locate a bound: one "
                        "real probe rose half a percent from 64 to 128 in flight and then 21 percent from 128 "
                        "to 256, so the first flat step is not the limit")
    c.add_argument("--window-hours", type=float, default=None,
                   help="how many hours the reservation was held for, so its bill can be compared against "
                        "what the traffic it absorbed would have cost elsewhere. A POLICY INPUT: a "
                        "reservation has no cost without a window, and without this the economics are "
                        "reported as undecidable rather than resolved into a per-request price")
    c.add_argument("--report", default=None,
                   help="also write a human reading of the policy kind, the frontier and the self-hosted "
                        "answer, per family")
    c.add_argument("--validations", default=None,
                   help="directory of held-out records. Without one, every entry stays provisional: a "
                        "calibration fold cannot validate its own choice")
    c.add_argument("--note", default=None)
    c.add_argument("--today", default=None)
    c.set_defaults(fn=cmd_compile)

    r = sub.add_parser("route", parents=[common], help="look a family up in a compiled table, and print why")
    r.add_argument("--table", required=True)
    r.set_defaults(registry=None)
    r.add_argument("--family", required=True)
    r.add_argument("--can-reject", action="store_true")
    r.add_argument("--allow-unvalidated", action="store_true",
                   help="route an entry no held-out fold has supported. Deliberately awkward; its presence "
                        "in a deploy script is the audit trail")
    r.set_defaults(fn=cmd_route)

    d = sub.add_parser("discover", parents=[common],
                       help="print a DRAFT candidate file from a gateway's model list")
    d.add_argument("--base-url", required=True)
    d.add_argument("--api-key-env", default="TIERBOOK_API_KEY")
    d.set_defaults(fn=cmd_discover)

    f = sub.add_parser("preflight", parents=[common],
                       help="ask each endpoint whether it accepts what a measurement needs")
    f.add_argument("--config", required=True)
    f.add_argument("--require-tools", action="store_true",
                   help="the run needs function tools; probe for them and fail if the endpoint refuses")
    f.set_defaults(fn=cmd_preflight)

    x = sub.add_parser("export-vsr", parents=[common], help="turn a compiled table into a router config")
    x.add_argument("--table", required=True)
    x.add_argument("--config", required=True)
    x.add_argument("--out", required=True)
    x.add_argument("--signal", action="append", metavar="FAMILY=CLASSIFIER_LABEL",
                   help="how a measured family maps to a label your classifier emits; refused if absent")
    x.add_argument("--default-model", required=True,
                   help="where traffic no decision matched goes. Not the cheapest tier: an unclassified "
                        "request is one there is no evidence about")
    x.add_argument("--entrypoint", default="tierbook/routed",
                   help="the virtual model name a client asks for. Not 'auto', which the "
                        "router reserves")
    x.add_argument("--port", type=int, default=8801)
    x.add_argument("--can-reject", action="store_true")
    x.add_argument("--allow-provisional", action="store_true")
    x.add_argument("--envoy-out", default=None,
                   help="also write the Envoy config. A router config alone routes nothing: something has "
                        "to dial the upstream the router named")
    x.add_argument("--envoy-port", type=int, default=8801,
                   help="the port the data plane listens on. Not 8080: the router binds that "
                        "for its classification API in the same network namespace")
    x.add_argument("--extproc-port", type=int, default=50051)
    x.add_argument("--signal-kind", default="domain",
                   help="the condition type the classifier emits; 'domain' for the shipped classifier")
    x.add_argument("--signal-categories", action="append", metavar="LABEL=cat1,cat2",
                   help="what the chosen classifier keys a label on, when it needs more than a name")
    x.set_defaults(fn=cmd_export_vsr)

    g = sub.add_parser("logs", parents=[common], help="what a log file can and cannot support")
    g.add_argument("path")
    g.set_defaults(fn=cmd_logs)

    ao = sub.add_parser("attach-outcome", parents=[common],
                        help="attach an observed outcome to a decision already in the log")
    ao.add_argument("--log", required=True, help="the decision log to read and append to")
    ao.add_argument("--request-id", required=True, help="which logged decision this outcome belongs to")
    ao.add_argument("--label-state", required=True, choices=LABEL_STATES)
    ao.add_argument("--label", type=_tri, default=None,
                    help="true or false; required exactly when --label-state is labelled")
    ao.add_argument("--tokens", type=int, default=None)
    ao.add_argument("--latency-s", type=float, default=None)
    ao.set_defaults(fn=cmd_attach_outcome, registry=None)

    o = sub.add_parser("observe", parents=[common],
                       help="read the state a policy would decide from, and say what could not be read")
    o.add_argument("--candidate", default="", help="whose occupancy this is; the state key is qualified with it")
    o.add_argument("--metrics-url", help="a vLLM /metrics endpoint")
    o.add_argument("--model-name", help="the served model name, so another model's series is not counted as this one's")
    o.add_argument("--authorised", type=_tri, default=None,
                   help="whether the gateway authorises spend. Not probed: it is a question about a budget")
    o.add_argument("--measured-on", help="the policy's evidence date, from which its age is computed")
    o.add_argument("--previous", help="a previous observation's json, which is what makes an arrival rate obtainable")
    o.add_argument("--out")
    o.set_defaults(fn=cmd_observe, registry=None)

    a = sub.add_parser("assign", parents=[common], help="one turn of the loop: observe, decide, record")
    a.add_argument("--policy", required=True, help="a compiled policy, as decide.as_dict wrote it")
    a.add_argument("--request-id", required=True)
    a.add_argument("--candidate", default="")
    a.add_argument("--metrics-url")
    a.add_argument("--model-name")
    a.add_argument("--authorised", type=_tri, default=None)
    a.add_argument("--measured-on")
    a.add_argument("--previous")
    a.add_argument("--agent", default="")
    a.add_argument("--endpoint", default="")
    a.add_argument("--quote-usd", type=float, default=None)
    a.add_argument("--bounds", help="json of candidate -> lower bound, for the record's candidate set")
    a.add_argument("--costs", help="json of candidate -> cost per task")
    a.add_argument("--feature-vector-version", default="fv1")
    a.add_argument("--policy-version", default=None,
                   help="checked against --policy's own digest (decide.policy_digest, CONTRACT C2) rather than "
                        "trusted outright; a mismatch exits 4. Left absent, the artifact's own digest is used -- "
                        "there is no 'unversioned' default any more, because a value the mechanism can derive "
                        "is not a value a caller supplies")
    a.add_argument("--floor", type=float, default=None,
                   help="the family's floor. Checked against the value --policy was compiled under (decide.parameter) "
                        "rather than trusted outright; a mismatch exits 4. Left absent, the artifact's own value is "
                        "used, and without one there either every non-chosen candidate is recorded as not_evaluated, "
                        "because a reason nobody computed is worse than no reason")
    a.add_argument("--bound-provenance", default=None,
                   help="json object {estimator, confidence, corrected_over} naming what --bounds carries and "
                        "which of record.BOUND_CORRECTIONS it was corrected over. Never inferred: a log of point "
                        "estimates must not claim to be a log of corrected lower bounds. Absent means no bound")
    a.add_argument("--latency-feasible", type=_tri, default=None)
    a.add_argument("--max-age-days", type=float, default=None,
                   help="the freshness limit past which evidence stops being usable")
    a.add_argument("--log", help="append the decision record here")
    a.set_defaults(fn=cmd_assign, registry=None)

    k = sub.add_parser("accept", parents=[common],
                       help="SCOPE section 12's criteria over a decision log, each with its own verdict")
    k.add_argument("--log", required=True)
    k.add_argument("--policy", default=None,
                   help="a compiled policy, as decide.as_dict wrote it. Gives --floor something to be checked "
                        "against through decide.parameter; without it --floor is required and the run is "
                        "recorded as operator-supplied and unchecked")
    k.add_argument("--floor", type=float, default=None,
                   help="the family's floor. Required unless --policy supplies one to check it against; a "
                        "value that disagrees with the artifact's exits 4 rather than picking a side")
    k.add_argument("--latency-feasible", type=_tri, default=None)
    k.add_argument("--uncertified-tolerance", type=float, default=None)
    k.add_argument("--budgeted-exploration", type=float, default=None)
    k.add_argument("--latency-limit-s", type=float, default=None)
    k.add_argument("--slo-tolerance", type=float, default=None)
    k.add_argument("--significance", type=float, default=0.05)
    k.add_argument("--out")
    k.set_defaults(fn=cmd_accept, registry=None)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
