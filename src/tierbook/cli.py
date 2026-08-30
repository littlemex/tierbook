"""The command line, which is deliberately four verbs.

    tierbook validate    are these records well formed, and what is missing from them
    tierbook explain     what does the ledger say about a family, and what would each margin choose
    tierbook compile     write the table, with the evidence and the registry hash in it
    tierbook route       look a family up in a compiled table, and print why
    tierbook discover    print a DRAFT candidate file from a gateway's model list, for a human to edit
    tierbook preflight   ask each configured endpoint whether it will accept what a measurement needs
    tierbook export-vsr  turn a compiled table into a router configuration
    tierbook logs        what a log file can and cannot support as a benchmark

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

from tierbook import SCHEMA_PATH, SCHEMA_VERSION, __version__
from tierbook.config import ConfigError, draft_from_model_list, load_config
from tierbook.evidence import EvidenceError
from tierbook.policy import assign_family, cutover_violation, evidence_class, load_registry, registry_version
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
        families = dict(cfg.families)
        args.margin = args.margin if args.margin is not None else cfg.objective.margin
        args.alpha = cfg.objective.alpha
        args.max_age_days = cfg.objective.max_age_days
    else:
        if args.margin is None:
            sys.exit("--margin is required unless --config supplies one")
        if not args.family:
            sys.exit("--family FAMILY=REFERENCE is required unless --config supplies families")
        families = dict(pair.split("=", 1) for pair in args.family)
    tp = dict(cfg.throughput_per_family) if cfg else {}
    tp.update((k, float(v)) for k, v in (p.split("=", 1) for p in args.throughput_per_family or []))
    o = cfg.objective if cfg else None
    table = compile_to_file(tiers, families, args.out, margin=args.margin, alpha=args.alpha,
                            throughput_per_family=tp, today=args.today, max_age_days=args.max_age_days,
                            note=args.note or "", validations=args.validations,
                            objective=(o.objective if o else "cost"),
                            latency_slo_p95_ms=(o.latency_slo_p95_ms if o else None),
                            min_completion_probability=(o.min_completion_probability if o else None))
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
        "certified": entry["certified"],
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
    from tierbook.export_vsr import ExportError, export, write

    cfg = _config(args)
    table = load_table(args.table)
    signals = dict(pair.split("=", 1) for pair in (args.signal or []))
    try:
        conf = export(table, cfg, signal_for_family=signals, default_model=args.default_model,
                      listener_port=args.port, request_can_reject=args.can_reject,
                      allow_provisional=args.allow_provisional)
    except ExportError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    write(conf, args.out)
    skipped = conf["_tierbook"]["families_skipped"]
    print(f"wrote {args.out}: {len(conf['routing']['decisions'])} decision(s) from registry "
          f"{conf['_tierbook']['compiled_from_registry']}")
    for s in skipped:
        print(f"  skipped {s}")
    return 0


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


def main(argv: list[str] | None = None) -> int:
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
    x.add_argument("--port", type=int, default=8801)
    x.add_argument("--can-reject", action="store_true")
    x.add_argument("--allow-provisional", action="store_true")
    x.set_defaults(fn=cmd_export_vsr)

    g = sub.add_parser("logs", parents=[common], help="what a log file can and cannot support")
    g.add_argument("path")
    g.set_defaults(fn=cmd_logs)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
