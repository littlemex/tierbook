"""The certification plane's verbs: `ingest`, `check-observations`, `check-provenance`, `power`, `derive`, `drift`,
`export-policy`.

Kept beside `cli.py` rather than inside it so the plane's door can be read on its own; `cli.main` registers these.
Each verb reads files and writes at most one file (the two `check-*` verbs and `power` write none; `derive --ledger` also appends to its ledger), and prints what it refused.

Exit codes: 0 done; 2 refused (bad input, a missing declaration, an export the target cannot express);
3 `drift` found a deployed assignment contradicted by fresh evidence. A refusal and a contradiction never share a code,
so a scheduler can tell "the world moved" from "the run did not happen".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REFUSED, CONTRADICTED_EXIT = 2, 3


def _refusals():
    from tierbook.certify import DeclarationError
    from tierbook.config import ConfigError
    from tierbook.evidence import EvidenceError
    from tierbook.export_vsr import ExportError

    return (DeclarationError, ConfigError, EvidenceError, ExportError, OSError, json.JSONDecodeError, KeyError,
            ValueError)


def _as_of(args) -> datetime:
    if not getattr(args, "as_of", None):
        return datetime.now(timezone.utc)
    t = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _pairs(specs, what: str) -> dict:
    out = {}
    for spec in specs or []:
        k, sep, v = spec.partition("=")
        if not sep or not k or not v:
            raise ValueError(f"{what} {spec!r} must be KEY=VALUE")
        out[k] = v
    return out


def _rows(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _dump(obj: dict, path: str) -> None:
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def cmd_ingest(args) -> int:
    from tierbook.observation import ingest_chat_log, write

    try:
        obs = ingest_chat_log(_rows(args.calls), _rows(args.outcomes) if args.outcomes else [], source=args.source,
                              cache_additive_arms=args.cache_additive_arm or ())
    except _refusals() as e:
        print(f"refused: {e}", file=sys.stderr)
        return REFUSED
    if args.arm_version:
        import dataclasses

        from tierbook.certify import arm_versions
        from tierbook.observation import read
        tags: dict[str, str] = {}
        for spec in args.arm_version:
            arm, sep, ver = spec.partition("=")
            if not sep or not arm or not ver:
                print(f"refused: --arm-version takes ARM=VERSION, not {spec!r}", file=sys.stderr)
                return REFUSED
            if tags.get(arm, ver) != ver:
                print(f"refused: --arm-version gives {arm!r} two versions", file=sys.stderr)
                return REFUSED
            tags[arm] = ver
        absent = sorted(set(tags) - {o.arm for o in obs})
        if absent:
            print(f"refused: --arm-version names {absent}, which have no calls in the log", file=sys.stderr)
            return REFUSED
        # The stamp is the operator's assertion, not the sender's report, and the row says so.
        obs = [dataclasses.replace(o, arm_version=tags[o.arm],
                                   source=(o.source + ";" if o.source else "") + "arm_version declared at ingest")
               if o.arm in tags else o for o in obs]
        if args.append and Path(args.out).exists():
            try:
                arm_versions(read(args.out) + obs)
            except _refusals() as e:
                print(f"refused: appending would mix versions: {e}", file=sys.stderr)
                return REFUSED
    n = write(obs, args.out, append=args.append)
    ungraded = sum(o.reason == "ungraded" for o in obs)
    print(f"wrote {n} observations to {args.out}" + (f" ({ungraded} ungraded)" if ungraded else ""))
    return 0


def cmd_check_observations(args) -> int:
    """Parse observation files the way `derive` parses rows, and print what they hold per (task type, arm, version).

    The validator a sender runs before handing files over: a row this reader refuses is refused here first, with its
    file and line, and an arm that mixes versions is named. Candidates, declarations and freshness are not read, so
    a file that passes here can still be refused by `derive` for those. Nothing is written."""
    from tierbook.certify import NO_VERSION, arm_versions
    from tierbook.observation import read

    try:
        obs = read(args.observations)
        arm_versions(obs)
    except _refusals() as e:
        print(f"refused: {e}", file=sys.stderr)
        return REFUSED
    cells: dict[tuple[str, str, str], dict[str, int]] = {}
    for o in obs:
        c = cells.setdefault((o.task_type, o.arm, o.arm_version or NO_VERSION), {})
        c[o.outcome] = c.get(o.outcome, 0) + 1
        if o.path:
            k = "path=" + ">".join(o.path)
            c[k] = c.get(k, 0) + 1
    for (t, a, v), c in sorted(cells.items()):
        print(f"{t}\t{a}\t{v}\t" + " ".join(f"{k}={n}" for k, n in sorted(c.items())))
    print(f"{len(obs)} observations in {len(args.observations)} file(s): parsed")
    return 0


def cmd_check_provenance(args) -> int:
    """Read an arm's provenance and the manifests it cites, and print what it claims and the digest to cite it by."""
    from tierbook.certify import NO_VERSION
    from tierbook.provenance import load_provenance

    try:
        pv = load_provenance(args.provenance, args.sha256)
    except _refusals() as e:
        print(f"refused: {e}", file=sys.stderr)
        return REFUSED
    print(f"arm {pv.arm} version {pv.arm_version or NO_VERSION}; cite as sha256 {pv.sha256}")
    for s in pv.trained_on:
        print(f"trained_on {s.name}: {len(s.items)} items, manifest sha256 {s.sha256}")
    for arm, v in pv.requires:
        print(f"requires {arm} at {v}")
    print("these are claims: they can only remove the arm from selection, and none is verified")
    return 0


def _load(args):
    from tierbook.certify import file_digest, load_declarations
    from tierbook.config import load_config
    from tierbook.observation import read

    cfg = load_config(args.candidates)
    return cfg, load_declarations(args.declarations), read(args.observations), file_digest(args.candidates)


def cmd_derive(args) -> int:
    from tierbook.certify import derive

    try:
        cfg, decl, obs, cdig = _load(args)
        policy = derive(obs, cfg, decl, as_of=_as_of(args), candidates_digest=cdig)
        _record_looks(policy, args.ledger)
    except _refusals() as e:
        print(f"refused: {e}", file=sys.stderr)
        return REFUSED
    _dump(policy, args.out)
    for t, e in sorted(policy["task_types"].items()):
        ho = e.get("held_out") or {}
        cost = ho.get("spend_per_accepted_usd")
        print(f"{t:<24} {e['status']:<13} {e.get('arm') or '-':<24} "
              f"{'' if cost is None else f'${cost:.6f}/accepted  '}{e['reason']}")
    c = policy.get("comparison")
    if c and c.get("policy_spend_per_accepted_usd") and c.get("single_best_spend_per_accepted_usd"):
        print(f"policy ${c['policy_spend_per_accepted_usd']:.6f}/accepted vs single best "
              f"{policy['single_best']['arm']} ${c['single_best_spend_per_accepted_usd']:.6f}/accepted "
              f"on {c['common_held_out_items']} common held-out items of {len(c['task_types'])} certified task type(s)")
    print(f"fallback: {(policy.get('fallback') or {}).get('arm')}  wrote {args.out}")
    return 0


def _record_looks(policy: dict, ledger: str | None) -> None:
    """Count this judgement as one more look at each task type's held-out items, and say how many looks they had.

    A held-out half is spent by being looked at: three floors, a re-run with a different ladder, or a second look
    after adding items are all looks at (some of) the same items. The ledger is append-only JSONL with each look's
    held-out item ids; `look` is one more than the number of earlier looks at this task type that shared any item, and
    `items_seen_before` says how many of today's held-out items an earlier look already used. Without a ledger the
    policy says looks were not recorded rather than implying this was the first. One writer at a time."""
    entries = {t: e for t, e in policy["task_types"].items() if "held_out_items" in e}
    if ledger is None:
        policy["looks"] = "not recorded (no --ledger)"
        for e in entries.values():
            e["look"] = None
            e.pop("held_out_items")
        return
    path = Path(ledger)
    prior = []
    if path.exists():
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip():
                try:
                    prior.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"{ledger}:{n}: {e.msg}") from None
    rows = []
    d = policy["declarations"]
    for t, e in sorted(entries.items()):
        items = set(e.pop("held_out_items"))
        earlier = [r for r in prior if r.get("task_type") == t and items & set(r.get("held_out_items") or [])]
        seen = set().union(*(set(r["held_out_items"]) for r in earlier)) & items if earlier else set()
        e["look"] = 1 + len(earlier)
        e["items_seen_before"] = len(seen)
        rows.append({"task_type": t, "held_out_set": e["held_out_set"], "held_out_items": sorted(items),
                     "look": e["look"], "floor": e.get("floor"), "alpha": d["alpha"], "bound": d["bound"],
                     "holdout_ladder": d["holdout_ladder"], "split_salt": d["split_salt"],
                     "holdout_fraction": d["holdout_fraction"], "held_out_correction": d["held_out_correction"],
                     "candidates_digest": policy["candidates_digest"],
                     "observations_digest": policy["observations_digest"], "derived_at": policy["derived_at"],
                     "status": e.get("status"), "arm": e.get("arm")})
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    policy["looks"] = {"ledger": ledger, "earlier_rows": len(prior)}


def cmd_power(args) -> int:
    """How many held-out items an arm with an assumed true rate needs to pass a floor with a given probability.
    Arithmetic only, for before a look: every input is the caller's and none is defaulted."""
    from tierbook.bounds import false_pass_at_floor, items_for_power, resolve

    try:
        bound = resolve(args.bound)
        n = items_for_power(args.floor, args.assumed_rate, args.alpha, args.power, bound, args.max_n)
    except _refusals() as e:
        print(f"refused: {e}", file=sys.stderr)
        return REFUSED
    if n is None:
        print(f"not reached by {args.max_n} held-out items")
        return 0
    fp = false_pass_at_floor(n, args.floor, args.alpha, bound)
    print(f"{n} held-out items (the first size, counting up, that reaches it): an arm at {args.assumed_rate} passes "
          f"floor {args.floor} with probability >= {args.power}; an arm exactly at the floor passes with {fp:.4f}")
    return 0


def cmd_drift(args) -> int:
    from tierbook.certify import dedupe, derive, drift
    from tierbook.observation import read

    try:
        cfg, decl, obs, cdig = _load(args)
        deployed = json.loads(Path(args.deployed).read_text())
        fresh = read(args.fresh) if args.fresh else []
        as_of = _as_of(args)
        rederived = derive(dedupe(obs + fresh), cfg, decl, as_of=as_of, candidates_digest=cdig)
        report = drift(deployed, rederived, fresh, decl, cfg, as_of=as_of)
    except _refusals() as e:
        print(f"refused: {e}", file=sys.stderr)
        return REFUSED
    report["rederived_policy"] = args.rederived_out
    if args.rederived_out:
        _dump(rederived, args.rederived_out)
    _dump(report, args.out)
    if report["rederivation_changes"]:
        print(f"inputs   declarations changed: {report['declarations_changed']}, "
              f"candidates changed: {report['candidates_changed']}")
    for c in report["rederivation_changes"]:
        print(f"changed  {c['task_type']}: {c['deployed']} -> {c['rederived']['status']} {c['rederived']['arm']}")
    for c in report["contradiction_checks"]:
        print(f"check    {c['task_type']} on {c['arm']}: {c['verdict']} ({c['accepted']}/{c['items']})")
    for c in report["unattributed_attempts"]:
        print(f"lost     {c['task_type']}: {c['attempts']} attempt(s) reached no candidate arm {c['reasons']}")
    for c in report["needs_measurement"]:
        print(f"measure  {c['task_type']} x {c['arm']}: {c['why']}")
    print(f"wrote {args.out}")
    return CONTRADICTED_EXIT if any(c["verdict"] == "contradicted" for c in report["contradiction_checks"]) else 0


def cmd_export_policy(args) -> int:
    from tierbook.certify import as_table, assignments
    from tierbook.config import load_config
    from tierbook.export_vsr import export, write

    try:
        policy_bytes = Path(args.policy).read_bytes()
        policy = json.loads(policy_bytes)
        if args.target == "prismyra-learn":
            # The fallback here is the tag's own model, Prismyra, not an arm of the policy.
            return _export_prismyra_learn(policy, policy_bytes, args)
        fb = (policy.get("fallback") or {}).get("arm")
        if not fb:
            raise ValueError("the policy has no fallback arm, so traffic with no certified assignment has nowhere "
                             "the policy chose to go")
        if args.target == "table":
            _dump({"assignments": assignments(policy, allow_unconfirmed=args.allow_unconfirmed),
                   "fallback": policy["fallback"], "guarantee": policy["guarantee"],
                   "observations_digest": policy["observations_digest"]}, args.out)
            print(f"wrote {args.out}")
            return 0
        if not args.candidates:
            raise ValueError("--target vsr needs --candidates: the router config names endpoints only it holds")
        cfg = load_config(args.candidates)
        signals = _pairs(args.signal, "--signal")
        cats = {k: [c for c in v.split(",") if c] for k, v in _pairs(args.signal_categories,
                                                                      "--signal-categories").items()}
        conf, prov = export(as_table(policy, allow_unconfirmed=args.allow_unconfirmed), cfg,
                            signal_for_family=signals, default_model=fb, listener_port=args.port,
                            entrypoint=args.entrypoint, allow_provisional=args.allow_unconfirmed,
                            signal_kind=args.signal_kind, signal_categories=cats,
                            management_bind_address=args.management_bind, management_port=args.management_port,
                            listener_address=args.listener_address, cascade_confidence=args.cascade_confidence)
    except _refusals() as e:
        print(f"refused: {e}", file=sys.stderr)
        return REFUSED
    prov["policy_guarantee"] = policy["guarantee"]
    prov["fallback"] = policy["fallback"]
    write(conf, args.out)
    write(prov, f"{args.out}.provenance.json")
    print(f"wrote {args.out}: {len(conf['routing']['decisions'])} decision(s), default {fb}")
    for s in prov["families_skipped"]:
        print(f"  skipped {s}")
    return 0


def _export_prismyra_learn(policy: dict, policy_bytes: bytes, args) -> int:
    """Write a Prismyra learn spec whose per-tag `router` follows the policy. Translation only.

    Prismyra's own router decides, per request, between a tag's distilled student and Prismyra itself; this sets
    which of those the policy certified. What router block an arm means is the caller's (`--arm-router`, arm ->
    a Prismyra `router` object, or null for "Prismyra alone"), because this module does not know how a student
    artifact or a confidence threshold is named. A task type certified on an arm the map does not name is refused:
    Prismyra cannot serve a metered API, and dropping the entry would leave the old router in place. A task type
    that is not certified gets no router, so its traffic is answered by Prismyra, the tag's own model.

    A tag given a student also gets an admission record in Prismyra's own format (learn-spec admission mode
    ``"external"``): the one version the policy judged for the student, the router block written, and the policy
    file's path and SHA-256 as evidence. Prismyra then serves only an artifact of that version under exactly that
    block, whatever its own bar said. The version is the entry's `arm_version`, or for a cascade the component
    `--served-student` names. The router block is the caller's declaration, not something the policy judged. A
    policy that names no version is refused unless `--allow-unversioned`, which writes the router with no record.
    An admission the learn spec already declares in another mode is refused rather than replaced. Records are
    written beside the output, each atomically, before the spec that points at them; records in that directory
    the written spec no longer points at are removed.
    """
    if not args.learn_spec or not args.arm_router:
        raise ValueError("--target prismyra-learn needs --learn-spec and --arm-router")
    spec = json.loads(Path(args.learn_spec).read_text())
    arms = json.loads(Path(args.arm_router).read_text())
    served_student = _pairs(args.served_student, "--served-student")
    tags = _pairs(args.signal, "--signal")
    by_task = {e["task"]: e for e in spec}
    decisions, records = {}, {}
    out = Path(args.out)
    record_dir = out.parent / f"{out.name}.admission"
    evidence = {"uri": str(Path(args.policy).resolve()), "sha256": hashlib.sha256(policy_bytes).hexdigest()}
    for t, e in sorted(policy["task_types"].items()):
        if t not in tags:
            continue
        tag = tags[t]
        if tag not in by_task:
            raise ValueError(f"task type {t!r} maps to tag {tag!r}, which the learn spec does not register")
        entry = by_task[tag]
        prior = (entry.get("admission") or {}).get("mode")
        ok = e["status"] == "certified" or (args.allow_unconfirmed and e["status"] == "unconfirmed")
        if not ok:
            entry.pop("router", None)
            _drop_external(entry)
            decisions[tag] = {"arm": None, "status": e["status"], "router": None,
                              "why": f"not certified ({e['status']}): Prismyra answers"}
            continue
        if e["arm"] not in arms:
            raise ValueError(f"task type {t!r} is certified on {e['arm']!r}, which --arm-router does not map to a "
                             "Prismyra router; this target can only express arms the Prismyra server serves")
        block = arms[e["arm"]]
        record = None
        if block is None:
            entry.pop("router", None)
            _drop_external(entry)
        else:
            version = _student_version(t, e, served_student, args.allow_unversioned)
            if prior not in (None, "external") and version is not None:
                raise ValueError(f"tag {tag!r} already declares admission mode {prior!r}; this target will not "
                                 "replace an operator's admission. Remove it from the learn spec to hand the "
                                 "decision to this policy")
            entry["router"] = block
            if version is None:
                _drop_external(entry)
            else:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
                    raise ValueError(f"tag {tag!r} cannot name a record file; tags here are letters, digits, '.', "
                                     "'_' and '-'")
                record = f"{record_dir.name}/{tag}.json"
                records[record] = {"format": 1, "tag": tag, "version": version, "router": block,
                                   "admitted_by": "tierbook export-policy", "evidence": evidence}
                entry["admission"] = {"mode": "external", "record": record}
        decisions[tag] = {"arm": e["arm"], "status": e["status"], "router": block, "why": e["reason"],
                          "admission_record": record}
    unmapped = sorted(set(tags) - set(policy["task_types"]))
    if unmapped:
        raise ValueError(f"--signal names task types the policy does not have: {unmapped}")
    for rel, rec in records.items():
        record_dir.mkdir(parents=True, exist_ok=True)
        _write_atomic(out.parent / rel, json.dumps(rec, indent=2) + "\n")
    _write_atomic(out, json.dumps(spec, indent=2) + "\n")
    referenced = {(e.get("admission") or {}).get("record") for e in spec}
    if record_dir.is_dir():
        for f in record_dir.glob("*.json"):
            if f"{record_dir.name}/{f.name}" not in referenced:
                f.unlink()
    _dump({"decisions": decisions, "observations_digest": policy["observations_digest"],
           "guarantee": policy["guarantee"], "allow_unversioned": bool(args.allow_unversioned)},
          f"{args.out}.provenance.json")
    for tag, d in sorted(decisions.items()):
        rec = d.get("admission_record")
        note = f", admission record {rec}" if rec else (", no admission record (--allow-unversioned): Prismyra's "
                                                         "own bar decides" if d["router"] else "")
        print(f"{tag}: {d['arm'] or 'prismyra'} ({d['status']}{note})")
    print(f"wrote {args.out}")
    return 0


def _student_version(task_type: str, e: dict, served_student: dict, allow_unversioned: bool) -> str | None:
    """The one version a record admits: the arm's own, or the named component of a cascade."""
    comps = e.get("component_versions")
    if comps:
        name = served_student.get(e["arm"])
        if name is None:
            raise ValueError(f"task type {task_type!r} is certified on cascade {e['arm']!r}; name the component "
                             f"Prismyra serves as its student with --served-student {e['arm']}=COMPONENT "
                             f"(components: {sorted(comps)})")
        if name not in comps:
            raise ValueError(f"--served-student {e['arm']}={name}: not a component of it ({sorted(comps)})")
        version = comps[name]
    else:
        version = e.get("arm_version")
    if not version and not allow_unversioned:
        raise ValueError(f"task type {task_type!r}: the policy names no version for what it certified, so no record "
                         "can bind the judgement to an artifact; ingest with versions, or pass --allow-unversioned "
                         "to let Prismyra's own bar decide")
    return version or None


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _drop_external(entry: dict) -> None:
    """A tag that gets no student from this policy keeps no record pointing at a judgement this policy withdrew."""
    if (entry.get("admission") or {}).get("mode") == "external":
        entry.pop("admission")


def register(sub, common) -> None:
    i = sub.add_parser("ingest", parents=[common], help="join a call log to its grades as observations")
    i.add_argument("--calls", required=True, help="JSONL of chat-completion calls")
    i.add_argument("--outcomes", default=None, help="JSONL of the caller's grades; absent means all ungraded")
    i.add_argument("--out", required=True)
    i.add_argument("--source", default="")
    i.add_argument("--cache-additive-arm", action="append", metavar="ARM",
                   help="an arm whose gateway reports cached tokens beside prompt_tokens rather than inside it "
                        "(repeatable); without it the OpenAI meaning, cached tokens inside prompt_tokens, is read")
    i.add_argument("--append", action="store_true",
                   help="append to --out rather than replace it. Off by default: re-running an ingest must not "
                        "count the same attempts twice")
    i.add_argument("--arm-version", action="append", metavar="ARM=VERSION",
                   help="stamp every attempt of ARM with an opaque version string (repeatable), for a call log that "
                        "does not carry one; tierbook compares versions and never parses them")
    i.set_defaults(fn=cmd_ingest)

    c = sub.add_parser("check-observations", parents=[common],
                       help="parse observation files as derive does and print each arm's versions and outcomes, writing nothing")
    c.add_argument("observations", nargs="+")
    c.set_defaults(fn=cmd_check_observations)

    pw = sub.add_parser("power", parents=[common],
                        help="held-out items an assumed rate needs to pass a floor, before looking")
    pw.add_argument("--floor", type=float, required=True)
    pw.add_argument("--assumed-rate", type=float, required=True)
    pw.add_argument("--alpha", type=float, required=True)
    pw.add_argument("--power", type=float, required=True)
    pw.add_argument("--bound", required=True, help="e.g. tierbook.bounds:wilson or tierbook.bounds:clopper_pearson")
    pw.add_argument("--max-n", type=int, required=True)
    pw.set_defaults(fn=cmd_power)

    pv = sub.add_parser("check-provenance", parents=[common],
                        help="read an arm's provenance and the manifests it cites, writing nothing")
    pv.add_argument("provenance")
    pv.add_argument("--sha256", default=None, help="the digest the candidate file declares for it")
    pv.set_defaults(fn=cmd_check_provenance)

    for name, fn, helptext in (("derive", cmd_derive, "certify a per-task-type assignment from observations"),
                               ("drift", cmd_drift, "diff a deployed policy against today's evidence and prices")):
        d = sub.add_parser(name, parents=[common], help=helptext)
        d.add_argument("--observations", nargs="+", required=True)
        d.add_argument("--candidates", required=True)
        d.add_argument("--declarations", required=True)
        d.add_argument("--out", required=True)
        d.add_argument("--as-of", default=None, help="ISO time freshness is judged at; default now, recorded")
        if name == "derive":
            d.add_argument("--ledger", default=None,
                           help="append-only looks ledger (JSONL): this judgement is counted as one more look at "
                                "each task type's held-out set, and the policy says which look it is")
        if name == "drift":
            d.add_argument("--deployed", required=True, help="the policy the router is running")
            d.add_argument("--fresh", nargs="*", default=None, help="observations since it was deployed")
            d.add_argument("--rederived-out", default=None)
        d.set_defaults(fn=fn)

    x = sub.add_parser("export-policy", parents=[common], help="turn a derived policy into a router config")
    x.add_argument("--policy", required=True)
    x.add_argument("--target", choices=("vsr", "table", "prismyra-learn"), required=True)
    x.add_argument("--learn-spec", default=None, help="prismyra-learn: the Prismyra learn spec to update")
    x.add_argument("--cascade-confidence", default=None,
                    help="vsr: the router's confidence_method a cascade's recorded score was computed as "
                         "(e.g. avg_logprob); required to export a cascade")
    x.add_argument("--arm-router", default=None,
                   help="prismyra-learn: JSON mapping an arm to a Prismyra router block, or to null for Prismyra alone")
    x.add_argument("--served-student", action="append", metavar="CASCADE_ARM=COMPONENT",
                   help="prismyra-learn: which component of a certified cascade Prismyra serves as the student")
    x.add_argument("--allow-unversioned", action="store_true",
                   help="prismyra-learn: write a router for a certificate that names no version, with no admission "
                        "record, so Prismyra's own bar decides")
    x.add_argument("--candidates", default=None)
    x.add_argument("--out", required=True)
    x.add_argument("--signal", action="append", metavar="TASK_TYPE=CLASSIFIER_LABEL")
    x.add_argument("--signal-categories", action="append", metavar="LABEL=cat1,cat2")
    x.add_argument("--signal-kind", default="domain")
    x.add_argument("--entrypoint", default="tierbook/routed")
    x.add_argument("--port", type=int, default=8801)
    x.add_argument("--allow-unconfirmed", action="store_true")
    x.add_argument("--management-bind", default="127.0.0.1",
                   help="the router's management API bind inside its container. vllm-sr 0.4.0's Docker stack "
                        "requires 0.0.0.0 there; exposure is decided by the host port publish")
    x.add_argument("--management-port", type=int, default=None)
    x.add_argument("--listener-address", default="127.0.0.1",
                   help="where the router's Docker stack publishes the listener on the host. Loopback unless "
                        "the listener must be reachable from other machines")
    x.set_defaults(fn=cmd_export_policy)
