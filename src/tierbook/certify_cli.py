"""The certification plane's verbs: `ingest`, `derive`, `drift`, `export-policy`.

Kept beside `cli.py` rather than inside it so the plane's door can be read on its own; `cli.main` registers these.
Each verb reads files and writes one file, and prints what it refused.

Exit codes: 0 done; 2 refused (bad input, a missing declaration, an export the target cannot express);
3 `drift` found a deployed assignment contradicted by fresh evidence. A refusal and a contradiction never share a code,
so a scheduler can tell "the world moved" from "the run did not happen".
"""
from __future__ import annotations

import json
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
    n = write(obs, args.out, append=args.append)
    ungraded = sum(o.reason == "ungraded" for o in obs)
    print(f"wrote {n} observations to {args.out}" + (f" ({ungraded} ungraded)" if ungraded else ""))
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
        policy = json.loads(Path(args.policy).read_text())
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
                            listener_address=args.listener_address)
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
    i.set_defaults(fn=cmd_ingest)

    for name, fn, helptext in (("derive", cmd_derive, "certify a per-task-type assignment from observations"),
                               ("drift", cmd_drift, "diff a deployed policy against today's evidence and prices")):
        d = sub.add_parser(name, parents=[common], help=helptext)
        d.add_argument("--observations", nargs="+", required=True)
        d.add_argument("--candidates", required=True)
        d.add_argument("--declarations", required=True)
        d.add_argument("--out", required=True)
        d.add_argument("--as-of", default=None, help="ISO time freshness is judged at; default now, recorded")
        if name == "drift":
            d.add_argument("--deployed", required=True, help="the policy the router is running")
            d.add_argument("--fresh", nargs="*", default=None, help="observations since it was deployed")
            d.add_argument("--rederived-out", default=None)
        d.set_defaults(fn=fn)

    x = sub.add_parser("export-policy", parents=[common], help="turn a derived policy into a router config")
    x.add_argument("--policy", required=True)
    x.add_argument("--target", choices=("vsr", "table"), required=True)
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
