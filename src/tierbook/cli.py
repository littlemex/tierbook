"""The command line, which is deliberately four verbs.

    tierbook validate    are these records well formed, and what is missing from them
    tierbook explain     what does the ledger say about a family, and what would each margin choose
    tierbook compile     write the table, with the evidence and the registry hash in it
    tierbook route       look a family up in a compiled table, and print why

There is no `serve`. A component that decides where money goes should not also be the thing holding the
socket: the online decision is a dictionary lookup, and the caller already has a process.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tierbook import SCHEMA_VERSION, __version__
from tierbook.policy import assign_family, load_registry, registry_version
from tierbook.table import Unvalidated, check_fresh, compile_to_file, load_table, lookup

REQUIRED_FOR_A_DECISION = (
    ("families[<family>].attempted", "how many items the outcome was measured on"),
    ("families[<family>].cohort", "which items, so two records can be compared as a pair"),
    ("families[<family>].paired_vs_reference", "the 2x2 against the reference on that same cohort"),
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
    schema = json.loads((Path(args.registry).parent / "schema.json").read_text()) if jsonschema else None
    bad = 0
    for t in tiers.values():
        if schema is not None:
            try:
                jsonschema.validate(t.record, schema)
            except Exception as e:  # noqa: BLE001 - the message is the product here
                bad += 1
                print(f"  {t.id}: does not match the schema -- {str(e).splitlines()[0]}")
        # A record can be schema-valid and still unable to support a decision. Say which.
        for family in (t.record.get("families") or {}):
            missing = []
            o = t.outcome(family) or {}
            if not o.get("attempted"):
                missing.append("attempted")
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
        p = t.paired(fam) or {}
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
    families = dict(pair.split("=", 1) for pair in args.family)
    tp = dict((k, float(v)) for k, v in (p.split("=", 1) for p in args.throughput_per_family or []))
    table = compile_to_file(tiers, families, args.out, margin=args.margin, alpha=args.alpha,
                            throughput_per_family=tp, today=args.today, max_age_days=args.max_age_days,
                            note=args.note or "", validations=args.validations)
    print(f"wrote {args.out} (format {table['table_format']}, registry {table['registry_version']})")
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
    c.add_argument("--family", action="append", required=True, metavar="FAMILY=REFERENCE_TIER")
    c.add_argument("--out", required=True)
    c.add_argument("--margin", type=float, required=True,
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

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
