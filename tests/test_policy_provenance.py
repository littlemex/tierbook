"""Tests for CONTRACT C2 -- a record can name the artifact it came from.

`Decision`'s version-shaped fields were `feature_vector_version`, `policy_version`, `mechanism_version` and
`schema_version`, and `policy_version` was a hand-typed CLI string defaulting to `"unversioned"`. So the
falsifier's own premise -- "the record carries which artifact" -- was unimplementable as written.

C2 gives the compiled policy a content hash the same way `policy.registry_version` already hashes the ledger
(`decide.policy_digest`), writes it into the artifact, and adds `Decision.policy_digest` so a record can carry
it. `route_once` reads the digest from the policy itself rather than trusting a caller's string, and refuses a
caller-supplied `policy_version` that disagrees, naming both -- `decide.parameter`'s existing rule, applied to a
value the mechanism can now derive.

Every test below is either that property or a way it could look true while not being true: a digest that is
really a constant, a caller value that quietly overrides the artifact's, a version-3 row that is missing the
field and is read anyway, or a CLI flag that still hands over a fabricated default.

Only observable behaviour is asserted -- no private attributes, no internal serialisation format.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import decide as dc  # noqa: E402
from tierbook import observe as ob  # noqa: E402
from tierbook import record as rec  # noqa: E402
from tierbook import serve as sv  # noqa: E402

V010_FIXTURE = ROOT / "docs" / "verify" / "v0.1.0-decisions.jsonl"


# --- fixtures, self-contained (no dependency on other test files' helpers) -----------------------------------


def pt(c, tph, p95, failed=0):
    return {"concurrency": c, "tasks_per_hour": tph, "p95_latency_s": p95, "failed": failed}


#: Two runs that agree, the same shape test_decide.py's own CURVE is: one run is refused on this project's own
#: history (a real probe's bound moved 2.6x between runs), so a compiled-policy fixture needs two.
_RUN = [pt(1, 60, 3.0), pt(2, 118, 5.0), pt(4, 230, 9.0), pt(8, 420, 18.0), pt(16, 415, 40.0)]
_RUN2 = [pt(1, 58, 3.1), pt(2, 120, 5.2), pt(4, 233, 9.4), pt(8, 415, 18.6), pt(16, 410, 41.0)]
CURVE = [_RUN, _RUN2]


def entry(chosen, *, status="assigned", reason=None):
    return {"chosen": list(chosen), "status": status,
            "validation": {"reason": reason} if reason else {}}


def compiled(chosen=("box",), *, family="f", default_by="the test", status="assigned", reason=None, **kw):
    """A policy the way `compile_policy` actually produces one -- not a hand-built `decide.Policy(...)` -- because
    C2's digest is a property of what the compiler wrote, and a fixture assembled by hand around the compiler
    would not exercise the compiler's own serialisation at all."""
    return dc.compile_policy(family, entry(chosen, status=status, reason=reason), reserved_ids={"box"},
                             metered_ids={"strong", "cheap"}, default=("strong",), default_declared_by=default_by,
                             max_evidence_age_days=30, floor=0.8, **kw)


def _obs(**state):
    """Same shape as tests/test_serve.py's `obs()`: a candidate's quantities are qualified with `:box`, the
    family's are not."""
    o = ob.Observation(candidate="box")
    for k, v in state.items():
        key = f"{k}:box" if k in ob.PER_CANDIDATE else k
        o.state[key] = v
        o.readings[key] = ob.Reading(value=v, as_of=1000.0, source="a fixture")
    return o


def _route(o, pol, **kw):
    base = dict(policy=pol, observation=o, request_id="r1", feature_vector_version="fv1",
                policy_version=pol.policy_digest, mechanism_version="0.1.0", agent="opencode", model="m",
                endpoint="http://e", gateway_quote_usd=0.004, bounds={"box": 0.90, "strong": 0.70},
                costs={"box": 0.004, "strong": 0.012}, evidence_as_of="2026-09-01", floor=0.8,
                bound_provenance=rec.BoundProvenance(estimator="clopper_pearson_fixed_sample", confidence=0.95))
    base.update(kw)
    return sv.route_once(**base)


def _real_v010_row() -> dict:
    """A line actually written by v0.1.0, not a hand-written stand-in -- the same fixture test_record_versioning.py
    insists on for C1, for the same reason: a reader tuned to a fixture's exact shape would pass the wrong test."""
    for line in V010_FIXTURE.read_text().splitlines():
        parsed = json.loads(line)
        if "request_id" in parsed:
            return parsed
    raise AssertionError(f"{V010_FIXTURE} has no decision line")


def _v2_row(**kw):
    """A row shaped like something a v0.2.0 (C1-era) writer produced: `schema_version: 2`, no `policy_digest` --
    that field did not exist yet."""
    base = {
        "family": "f", "request_id": "r1", "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": [{"id": "box", "excluded_because": "chosen", "bound": 0.9,
                        "bound_provenance": {"estimator": "clopper_pearson_fixed_sample", "confidence": 0.95,
                                              "corrected_over": []},
                        "cost_usd": 0.004, "evidence_as_of": "2026-09-01"}],
        "chosen": "box", "selection_probability": 1.0, "exploration": False, "certified": True,
        "policy_version": "p1", "mechanism_version": "0.1.0", "agent": "opencode", "model": "m",
        "endpoint": "http://e", "gateway_quote_usd": 0.004, "gateway_authorised": True,
        "exploration_reason": "no_mechanism", "eligible_set": [], "gaps": [], "label_state": "pending",
        "label": None, "outcome": {}, "schema_version": 2,
    }
    base.update(kw)
    return base


def _v3_row(**kw):
    """A row shaped like something a C2 writer produces: `schema_version` bumped to the current one, carrying
    `policy_digest`. Keyed off `rec.SCHEMA_VERSION` rather than a literal 3, so this file does not silently stop
    exercising 'the current version' if the constant it locks (`test_schema_version_becomes_3` below) changes for
    a reason this file was not written to anticipate."""
    base = _v2_row(schema_version=rec.SCHEMA_VERSION)
    base["policy_digest"] = "the-real-digest"
    base.update(kw)
    return base


# --- decide.policy_digest is a function of the artifact's content, not a label attached to it -----------------


def test_schema_version_becomes_3():
    """Locks the version C2 bumps to, the way test_record_versioning.py's `test_schema_version_is_2` locks C1's --
    every other test in this file that builds a 'current' row is keyed against this constant, not a literal."""
    assert rec.SCHEMA_VERSION == 3


def test_two_independently_compiled_policies_with_identical_content_agree():
    """A content hash whose value depended on which Python call produced it, rather than on what the artifact
    says, would not be a digest -- it would be a second `id()`. Two separate `compile_policy` calls with
    identical arguments must land on the same digest."""
    a = compiled()
    b = compiled()
    assert dc.policy_digest(a) == dc.policy_digest(b)


def test_a_tighter_latency_constraint_changes_the_digest():
    """test_decide.py's own `test_a_tighter_constraint_moves_the_bound_down` shows 20s -> 8, 10s -> 4 in-flight
    over the same curve: two policies compiled under different constraints have different rules, and a digest
    that did not move with them would be constant regardless of content -- the exact defect C2 exists to close,
    restated as a hash."""
    a = compiled(service_curve=CURVE, latency_p95_slo_s=20.0)
    b = compiled(service_curve=CURVE, latency_p95_slo_s=10.0)
    assert dc.policy_digest(a) != dc.policy_digest(b)


def test_changing_the_family_changes_the_digest():
    a = compiled(family="f")
    b = compiled(family="g")
    assert dc.policy_digest(a) != dc.policy_digest(b)


def test_an_unvalidated_policy_still_gets_a_digest():
    """`compile_policy`'s no-rule branch (nothing validated for this family) is still an artifact route_once will
    be handed later, and C2's whole point is that every record can name the artifact it came from -- including
    this one, not only the branch with rules in it."""
    p = compiled(status="provisional", reason="held out below the margin")
    assert p.rules == ()
    assert dc.policy_digest(p) != ""


def test_the_digest_is_truncated_the_same_way_registry_version_is():
    """CONTRACT C2 says the truncation matches `policy.registry_version`'s own -- checked against a real call to
    that function rather than a literal length, so a later change to registry_version's truncation is not
    silently un-mirrored here."""
    from tierbook.policy import registry_version

    reference_length = len(registry_version({}))
    digest = dc.policy_digest(compiled())
    assert len(digest) == reference_length
    int(digest, 16)  # every character is hexadecimal; raises ValueError otherwise


# --- compile_policy writes the digest into the artifact, not only computes it --------------------------------


def test_compile_policy_writes_policy_digest_matching_the_function():
    p = compiled()
    assert p.policy_digest == dc.policy_digest(p)
    assert p.policy_digest != ""


def test_the_digest_reaches_as_dict_not_only_the_object():
    """`decide.as_dict`'s own docstring says it is the policy 'for the artifact' -- a digest that lived only on
    the Python object and never reached `as_dict` would not be a property of the artifact on disk at all."""
    p = compiled()
    d = dc.as_dict(p)
    assert d["policy_digest"] == p.policy_digest


# --- Decision.policy_digest: no default -----------------------------------------------------------------------


def test_policy_digest_has_no_default():
    """Catches a plausible-looking default sneaking in -- exactly the thing C1's `schema_version` guard exists to
    keep out of every other field on this dataclass: a default here would be a value nothing measured that a
    reader could mistake for one that was."""
    import dataclasses

    f = next(f for f in dataclasses.fields(rec.Decision) if f.name == "policy_digest")
    assert f.default is dataclasses.MISSING
    assert f.default_factory is dataclasses.MISSING


# --- from_row: version decides how policy_digest is supplied (SEAMS S4's rule) ---------------------------------


def test_a_real_v010_row_reads_policy_digest_as_empty():
    """Against the real fixture, not a hand-written stand-in: a v0.1.0 line never had this field, and no artifact
    for it was ever hashed, so the empty string is the true statement about it -- not a guess this reader makes
    up to keep the row loadable."""
    d, _ignored = rec.from_row(_real_v010_row())
    assert d.schema_version == 1
    assert d.policy_digest == ""


def test_a_version_2_row_with_no_policy_digest_key_also_reads_as_empty():
    """SEAMS S4's rule is named by version, not just for version 1: a genuine v0.2.0 (C1-era) log never wrote this
    field either, and its absence there is the same true statement, not an omission a v0.2.0 writer made."""
    d, _ignored = rec.from_row(_v2_row())
    assert d.schema_version == 2
    assert d.policy_digest == ""


def test_a_current_row_missing_policy_digest_is_refused_naming_the_field():
    """The other half of SEAMS S4: at the current schema version the field is required, not defaulted, so a row
    that omits it is a writer that forgot to stamp a fact the mechanism did produce -- indistinguishable from
    'no artifact was ever hashed' unless this raises."""
    bad = _v3_row()
    del bad["policy_digest"]
    with pytest.raises(rec.Incomplete, match="policy_digest"):
        rec.from_row(bad)


def test_a_current_row_carrying_policy_digest_reads_it_through_unignored():
    d, ignored = rec.from_row(_v3_row(policy_digest="a-real-hash"))
    assert d.policy_digest == "a-real-hash"
    assert "policy_digest" not in ignored


# --- route_once reads the digest from the policy, and checks a caller-supplied value against it ----------------


def test_route_once_records_the_policys_own_digest():
    """C2's title, restated as a check on the record itself: the decision's `policy_digest` has to be the
    artifact's own hash, not merely a caller-typed string that happens to equal it -- the two are indistinguishable
    on THIS request and distinguishable only on the next one, where a caller could have typed something else."""
    p = compiled(service_curve=CURVE, latency_p95_slo_s=20.0)
    _got, d = _route(_obs(inflight=2.0, metered_authorised=True), p)
    assert d.policy_digest == p.policy_digest
    assert d.policy_digest != ""


def test_route_once_accepts_no_supplied_policy_version():
    """A caller with nothing to confirm still gets a decision that names its artifact: the digest comes from the
    policy either way, the same way `decide.parameter(policy, name, supplied=None)` hands back whatever the
    artifact has when nothing was supplied to check it against."""
    p = compiled(service_curve=CURVE, latency_p95_slo_s=20.0)
    _got, d = _route(_obs(inflight=2.0, metered_authorised=True), p, policy_version=None)
    assert d.policy_digest == p.policy_digest


def test_an_agreeing_caller_supplied_policy_version_is_not_treated_as_a_conflict():
    """The non-refusal side of the rule: a caller who confirms the SAME value the artifact hashes to must not be
    refused merely for having supplied a value at all -- `decide.parameter` hands the value back when it matches
    rather than treating any supplied value as suspect."""
    p = compiled(service_curve=CURVE, latency_p95_slo_s=20.0)
    _got, d = _route(_obs(inflight=2.0, metered_authorised=True), p, policy_version=p.policy_digest)
    assert d.policy_digest == p.policy_digest


def test_a_disagreeing_caller_supplied_policy_version_is_refused_naming_both_values():
    """The CLI operator who still hand-types a `--policy-version` is caught here, not two log lines later: a value
    that disagrees with what the artifact actually hashes to must be refused with BOTH numbers named, `decide.
    parameter`'s own rule (`'{name!r} supplied as {supplied!r} does not match {compiled!r}'`) applied to a value
    the mechanism can now derive instead of one only a human ever typed."""
    p = compiled(service_curve=CURVE, latency_p95_slo_s=20.0)
    with pytest.raises(ValueError) as exc:
        _route(_obs(inflight=2.0, metered_authorised=True), p, policy_version="a-hand-typed-string")
    msg = str(exc.value)
    assert "a-hand-typed-string" in msg
    assert p.policy_digest in msg


def test_a_policy_carrying_no_digest_refuses_a_supplied_version_as_unconfirmable_not_as_a_mismatch():
    """CONTRACT amendment 9. `decide.parameter` has TWO refusals and they are not interchangeable: a name the
    artifact never recorded "cannot confirm" a supplied value, while a name recorded differently "does not match" it.
    An artifact carrying no digest is in the first case, and reporting it as `does not match ''` states an absence as
    though it were a rival claim -- the over-statement this release spent five amendments removing from `certified`,
    one layer out. Only a policy from `compile_policy` carries a digest, so a hand-built one reaching this path is
    the normal way to arrive here rather than a contrived state."""
    bare = dc.Policy(family="f", rules=(), default=("box",), domain={}, validated=True, note="never compiled")
    assert bare.policy_digest == ""
    with pytest.raises(ValueError) as exc:
        _route(_obs(inflight=2.0, metered_authorised=True), bare, policy_version="a-hand-typed-string")
    msg = str(exc.value)
    assert "a-hand-typed-string" in msg
    assert "no digest" in msg and "cannot confirm" in msg
    # And it must NOT read as a comparison against a value: an empty string is not the other side of a mismatch.
    assert "does not match" not in msg


# --- --policy-version loses its "unversioned" default ----------------------------------------------------------


def test_policy_version_flag_no_longer_defaults_to_unversioned(monkeypatch, tmp_path):
    """CONTRACT C2's own checked-claims table names the row this falsifies: `--policy-version` defaulted to
    `"unversioned"`, a placeholder the record then carried as though it meant something. Checked through the real
    argparse wiring in `cli.py`'s `assign` subcommand -- not by grepping the source for the literal string, which
    a worker could delete from one line while leaving the fallback-string-becomes-the-record behaviour intact by
    substituting a different placeholder.

    `cmd_assign` is monkeypatched to a stub that only records what argparse handed it, rather than actually
    running a decision through `route_once` -- this test is about the flag's default, not about the rest of the
    command, and giving it a real policy artifact and a real observation would make a failure here ambiguous
    between 'the default changed' and 'something else about assign broke'.
    """
    from tierbook import cli

    captured = {}

    def fake_cmd_assign(args):
        captured["policy_version"] = args.policy_version
        return 0

    monkeypatch.setattr(cli, "cmd_assign", fake_cmd_assign)
    rc = cli.main(["assign", "--policy", str(tmp_path / "unused.json"), "--request-id", "r1"])
    assert rc == 0
    assert captured["policy_version"] != "unversioned"
    # A value the mechanism can derive is not a value a caller supplies (CONTRACT C2's own words for this entry):
    # `None` is "nothing was supplied to check", the same sentinel `decide.parameter`'s own `supplied=None` already
    # gives that fact everywhere else in this codebase.
    assert captured["policy_version"] is None
