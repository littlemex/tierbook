"""CONTRACT C6 (docs/changes/v0.3.0-scope/CONTRACT.md): the candidate set comes from the ledger's outcomes, not
from `policy.rules`.

The defect this closes actually happened: a shipped policy compiled with zero rules (a 20-item calibration
fold that certified nothing) left `serve.candidate_set` deriving its set from `policy.rules` and `policy.default`
alone, so the set collapsed to the one default candidate. Exploration then had nothing to draw into on any of
400 decisions -- `no_eligible_arm` every time -- and the two candidates that DID have measured outcomes were
never labelled, never re-measured, and never visible to an incident review.

Every test below is either that regression, reproduced on the real shipped ledger, or one of the two escape
hatches amendment 8 names for it: a candidate the ledger cannot bound (mapped to `None`, not omitted), and a
candidate `assign_family` itself excludes by a stated constraint (also named with no bound, not omitted).

Nothing here asserts on a private attribute. `policy.candidates_for` and `decide.Policy`/`decide.from_dict`/
`serve.candidate_set`/`explore.eligible` are the documented interface; the CLI `compile` command is used for the
end-to-end cases so this file does not depend on `compile_policy`'s own parameter list, which the interface section
does not pin.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tierbook import cli  # noqa: E402
from tierbook import decide as dc  # noqa: E402
from tierbook import observe as ob  # noqa: E402
from tierbook import policy as P  # noqa: E402
from tierbook import record as rec  # noqa: E402
from tierbook import serve as sv  # noqa: E402

EXAMPLE_TIERS = ROOT / "examples" / "ledger" / "tiers"
EXAMPLE_CANDIDATES = ROOT / "examples" / "ledger" / "candidates.json"
SHIPPED_TIER_IDS = {"api-strong-a", "api-cheap-a", "self-hosted-a"}


def run_cli(argv: list[str]) -> int:
    """Same normalisation `test_policy_parameters.py` uses: `cli.main` sometimes raises `SystemExit` and
    sometimes returns a status, and no test here cares which."""
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


def registry():
    return P.load_registry(EXAMPLE_TIERS)


# =====================================================================================================
# Section 1 -- `policy.candidates_for(tiers, family)`, on the real shipped ledger.
# =====================================================================================================


def test_candidates_for_covers_every_candidate_with_an_outcome_for_the_family():
    """The core C6 defect, at its source. `serve.candidate_set` used to derive its set from `policy.rules`, so a
    candidate with no rule was absent from it -- invisible to exploration, never labelled, never re-measured.
    `candidates_for` is the ledger-derived universe that fixes that: every one of the three shipped tiers has a
    measured outcome for both shipped families, and all three must be here regardless of what any policy's rules
    happen to name."""
    tiers = registry()
    for family in ("agentic-coding", "tool-agent-user-retail"):
        assert set(P.candidates_for(tiers, family)) == SHIPPED_TIER_IDS


def test_candidates_for_excludes_a_candidate_with_no_outcome_for_this_family_at_all():
    """The other side of the same coin: the universe is "has an outcome for THIS family", not "exists in the
    registry". A tier measured on one family and never attempted on another must not appear for the family it
    was never run on -- that is a different fact from "attempted and unbounded", which C6 represents as `None`
    rather than as absence."""
    tiers = registry()
    extra = {**tiers["api-strong-a"].record}
    extra["id"] = "only-on-agentic-coding"
    extra["families"] = {"agentic-coding": dict(tiers["api-strong-a"].record["families"]["agentic-coding"])}
    tiers["only-on-agentic-coding"] = P.Tier("only-on-agentic-coding", extra)
    assert "only-on-agentic-coding" in P.candidates_for(tiers, "agentic-coding")
    assert "only-on-agentic-coding" not in P.candidates_for(tiers, "tool-agent-user-retail")


def test_candidates_for_values_are_a_float_bound_or_none_and_nothing_else():
    """`dict[str, float | None]` is the contracted return type. A caller downstream (`compile_policy`, then
    `serve.candidate_set`) treats `None` as a structured fact -- "no bound" -- so a value of any other shape
    (a string, a nested dict) would make that downstream check silently pass or silently crash depending on
    what it happened to compare against."""
    tiers = registry()
    for family in ("agentic-coding", "tool-agent-user-retail"):
        for cid, bound in P.candidates_for(tiers, family).items():
            assert bound is None or isinstance(bound, float), (family, cid, bound)


def test_every_shipped_candidate_is_bounded_for_both_shipped_families():
    """`None` is C6's escape hatch for a candidate the ledger genuinely cannot bound, not the default outcome
    for well-formed evidence. All three shipped tiers carry an executable-checked, non-tautological, paired
    outcome for both families, so none of them should come back unbounded -- if this starts failing it means
    either the fixture changed or `candidates_for` is defaulting to `None` far more often than the evidence
    calls for."""
    tiers = registry()
    for family in ("agentic-coding", "tool-agent-user-retail"):
        bounds = P.candidates_for(tiers, family)
        unbounded = {cid for cid, b in bounds.items() if b is None}
        assert not unbounded, f"{family}: {unbounded} came back with no bound on well-formed shipped evidence"


# =====================================================================================================
# Section 2 -- `serve.candidate_set` reads `policy.candidates`, not `policy.rules`.
# =====================================================================================================


def _raw_policy(*, default, candidates, rules=None, validated=True) -> dict:
    """The smallest artifact `decide.from_dict` will load: no rules needed for these tests, since the point
    under test is that the SET comes from `candidates`, not from what a rule or the default happens to name."""
    return {
        "family": "fam",
        "default": list(default),
        "validated": validated,
        "note": "",
        "domain": {},
        "provenance": {},
        "rules": rules or [],
        "parameters": {"floor": None, "max_evidence_age_days": None, "staleness_limit_days": None},
        "candidates": candidates,
    }


def test_candidate_set_includes_a_candidate_no_rule_and_no_default_ever_names():
    """The regression itself, at the `serve.candidate_set` boundary: before C6, the set was `{rule.assign for
    rule in policy.rules} | set(policy.default)`, so a candidate named by neither was simply not in it. Here
    "quiet" is named by nothing except `policy.candidates`, and it must still show up."""
    pol = dc.from_dict(_raw_policy(default=("box",), candidates={"box": 0.9, "quiet": 0.5}))
    prov = rec.BoundProvenance(estimator="clopper_pearson_fixed_sample", confidence=0.95)
    out = sv.candidate_set(pol, "box", bounds={"box": 0.9, "quiet": 0.5}, costs={"box": 0.01, "quiet": 0.01},
                          bound_provenance=prov)
    assert {c.id for c in out} == {"box", "quiet"}


def test_a_candidate_with_no_bound_is_present_and_excluded_for_no_bound_not_omitted():
    """C6's own words: "a candidate present with `None` is in the set with no bound, excluded for `no_bound`" --
    the distinction that made it invisible before. `bounds` deliberately does not mention "quiet" either, so
    this holds regardless of whether a value's SOURCE ends up being `policy.candidates` or the live `bounds`
    dict: both agree there is no bound for it, and the candidate must still be named."""
    pol = dc.from_dict(_raw_policy(default=("box",), candidates={"box": 0.9, "quiet": None}))
    prov = rec.BoundProvenance(estimator="clopper_pearson_fixed_sample", confidence=0.95)
    out = sv.candidate_set(pol, "box", bounds={"box": 0.9}, costs={"box": 0.01}, bound_provenance=prov)
    quiet = next(c for c in out if c.id == "quiet")
    assert quiet.bound is None
    assert quiet.excluded_because == "no_bound"


def test_the_rule_less_policy_from_the_real_regression_does_not_collapse_to_one_candidate():
    """Direct reproduction of the shipped incident: `rules=()`, a lone default, and (before C6) a candidate set
    of size one -- the state every one of 400 decisions actually observed, each returning `no_eligible_arm`
    because there was nothing else to draw into. With `candidates` carrying all three measured candidates, the
    set must have three members even though the policy fired zero rules."""
    pol = dc.from_dict(_raw_policy(
        default=("api-strong-a",), validated=False, rules=[],
        candidates={"api-strong-a": 0.0, "api-cheap-a": -0.35, "self-hosted-a": -0.47}))
    prov = rec.BoundProvenance(estimator="clopper_pearson_fixed_sample", confidence=0.95)
    out = sv.candidate_set(pol, "api-strong-a",
                           bounds={"api-strong-a": 0.0, "api-cheap-a": -0.35, "self-hosted-a": -0.47},
                           costs={"api-strong-a": 0.01, "api-cheap-a": 0.001, "self-hosted-a": 0.0005},
                           bound_provenance=prov)
    assert len(out) == 3, "the exact collapse the shipped incident hit: one candidate where three were measured"
    assert {c.id for c in out} == {"api-strong-a", "api-cheap-a", "self-hosted-a"}


# --- the same distinction, seen from `explore.eligible` through the whole `route_once` composition --------


def obs(**state):
    """A fixture in the keys `decide` reads, mirroring `test_serve.py`'s helper: a candidate's own quantities
    are qualified by it, the family's are not."""
    o = ob.Observation(candidate="box")
    for k, v in state.items():
        key = f"{k}:box" if k in ob.PER_CANDIDATE else k
        o.state[key] = v
        o.readings[key] = ob.Reading(value=v, as_of=1000.0, source="a fixture")
    return o


def test_explore_eligible_can_see_a_bound_candidate_and_cannot_draw_into_an_unbound_one():
    """The payoff of the whole entry, stated as C6 states it: "visible to `explore.eligible` as a candidate
    that exists and cannot be drawn into -- which is the distinction that made it invisible before." Before
    C6, "quiet" was not in `d.candidates` at all, so there was no way to tell "cannot be drawn into" from
    "does not exist". After C6 it is in `d.candidates` and absent from `d.eligible_set` -- two different facts,
    both visible on the one record."""
    pol = dc.from_dict(_raw_policy(default=("box",), candidates={"box": 0.9, "quiet": None}))
    o = obs(metered_authorised=True)
    _, d = sv.route_once(
        policy=pol, observation=o, request_id="r1", feature_vector_version="fv1",
        mechanism_version="0.1.0", agent="a", model="m", endpoint="http://e", gateway_quote_usd=0.001,
        bounds={"box": 0.9}, costs={"box": 0.01}, evidence_as_of="2026-09-01", floor=0.80,
        bound_provenance=rec.BoundProvenance(estimator="clopper_pearson_fixed_sample", confidence=0.95))
    ids = {c.id for c in d.candidates}
    assert ids == {"box", "quiet"}, "both must be visible on the record"
    assert "quiet" not in d.eligible_set, "unbound, so it cannot be drawn into"
    quiet = next(c for c in d.candidates if c.id == "quiet")
    assert quiet.excluded_because == "no_bound"


# =====================================================================================================
# Section 3 -- a v0.2.0 artifact has no `candidates` key, and `from_dict` refuses it rather than reading it
# as an empty or rules-derived set.
# =====================================================================================================


def _pre_c6_shaped_dict(*, rules=None) -> dict:
    """Every key a well-formed pre-C6 artifact carries, and deliberately no `candidates` key -- the shape
    `compile_policy` wrote before this entry existed."""
    return {
        "family": "fam",
        "default": ["api"],
        "validated": True,
        "note": "",
        "domain": {},
        "provenance": {},
        "rules": rules or [],
        "parameters": {"floor": 0.05, "max_evidence_age_days": None, "staleness_limit_days": None},
    }


def test_from_dict_refuses_an_artifact_with_no_candidates_key():
    """The exact case C6 names: "a v0.2.0 artifact has no `candidates` key. `from_dict` refuses it rather than
    falling back to the rules, because falling back is what made the omission silent." A rules-less artifact
    is the sharper of the two shapes to pin, since it is also the shape the shipped incident produced."""
    with pytest.raises(ValueError, match="candidates"):
        dc.from_dict(_pre_c6_shaped_dict(rules=[]))


def test_from_dict_does_not_fall_back_to_the_rules_when_candidates_is_absent():
    """The failure mode this specifically guards against: an artifact that DOES carry rules naming a candidate
    is exactly the shape a silent rules-fallback would read happily, producing a set from `policy.rules` as if
    C6 had never landed. This must still be refused."""
    populated = _pre_c6_shaped_dict(rules=[
        {"when": ["fixture"],
         "guards": [{"var": "inflight:box", "op": "<", "threshold": 8.0, "derived_from": "fixture"}],
         "assign": ["box"], "because": "fixture"},
    ])
    with pytest.raises(ValueError, match="candidates"):
        dc.from_dict(populated)


# =====================================================================================================
# Section 4 -- the real shipped ledger, compiled through the documented CLI, reproduces and then closes the
# incident end to end.
# =====================================================================================================


def _compile_shipped_ledger(tmp_path) -> dict:
    """`compile`, against the real example ledger, with no `--validations` -- the exact condition the shipped
    incident occurred under: nothing has been measured on a held-out fold, so both families compile with zero
    rules (`status` is `provisional`, never `assigned`). Reproduced live against this checkout before writing
    this fixture, so it is asserted here rather than merely claimed as a precondition."""
    out_path = tmp_path / "table.json"
    rc = run_cli(["compile", "--config", str(EXAMPLE_CANDIDATES), "--out", str(out_path),
                 "--registry", str(EXAMPLE_TIERS)])
    assert rc == 0
    return json.loads(out_path.read_text())


def test_the_shipped_incidents_precondition_still_reproduces(tmp_path):
    """Not a C6 assertion -- a guard on the fixture above. If this ever starts producing non-empty rules, the
    "real regression" story the rest of this section tells stops being about the real regression."""
    table = _compile_shipped_ledger(tmp_path)
    for family in table["decide"]:
        for label in ("can_reject", "cannot_reject"):
            assert table["decide"][family][label]["rules"] == []
            assert table["decide"][family][label]["validated"] is False


def test_compiling_the_shipped_ledger_lists_every_candidate_despite_zero_rules(tmp_path):
    """The money test. On the real shipped ledger, with no validations, every family compiles to zero rules --
    and before C6 that meant `serve.candidate_set` would have seen exactly one candidate (the default) for
    each. After C6 the artifact's `candidates` names all three measured candidates for both families."""
    table = _compile_shipped_ledger(tmp_path)
    for family in ("agentic-coding", "tool-agent-user-retail"):
        for label in ("can_reject", "cannot_reject"):
            cands = table["decide"][family][label]["candidates"]
            assert set(cands) == SHIPPED_TIER_IDS, (family, label, cands)


def test_the_compiled_artifact_feeds_candidate_set_three_candidates_not_one(tmp_path):
    """The same fact, read back through the actual consumer rather than through the raw JSON: load the
    compiled artifact with `decide.from_dict` and hand it to `serve.candidate_set` exactly as `route_once`
    would. Three candidates come back, not the one the shipped incident actually served for 400 decisions."""
    table = _compile_shipped_ledger(tmp_path)
    pol = dc.from_dict(table["decide"]["agentic-coding"]["cannot_reject"])
    out = sv.candidate_set(pol, pol.default[0], bounds={}, costs={})
    assert len(out) == 3
    assert {c.id for c in out} == SHIPPED_TIER_IDS


# =====================================================================================================
# Section 5 -- amendment 8: a candidate `assign_family` itself excludes by a stated constraint is named with
# no bound in the compiled artifact, not omitted the way deriving from `ranked` would have omitted it.
# =====================================================================================================


def _ledger_with_a_latency_slo_violation(tmp_path) -> tuple[Path, Path]:
    """A p95 that exceeds a declared SLO, on a family that can otherwise compile from the shipped ledger
    unmodified. Amendment 8's own text: this path is unreachable with the shipped evidence, because the retail
    family's latency carries `p50`/`mean` and no `p95_ms`, and `agentic-coding`'s outcomes carry no per-family
    latency at all -- so this fixture manufactures the one field that makes `assign_family`'s
    `latency_slo_p95_ms` guard actually fire, reproduced live against this checkout before being written here.

    Restricted to the `agentic-coding` family alone: `tool-agent-user-retail`'s evidence files are repo-relative
    to the real ledger root and do not resolve from a copy in `tmp_path`, and this fixture is about the SLO
    guard, not about evidence resolution.
    """
    tiers_dir = tmp_path / "tiers"
    tiers_dir.mkdir()
    for name in ("api-strong-a.json", "api-cheap-a.json", "self-hosted-a.json"):
        d = json.loads((EXAMPLE_TIERS / name).read_text())
        d["families"] = {"agentic-coding": d["families"]["agentic-coding"]}
        if name == "api-cheap-a.json":
            # Comfortably over the 1000ms SLO declared below, on a family this record's own outcome already
            # attempted -- so it stays a candidate the ledger recorded, not one it never measured.
            d["families"]["agentic-coding"]["latency"] = {"unit": "seconds_per_task", "p95_ms": 5000,
                                                          "mean": 60}
        (tiers_dir / name).write_text(json.dumps(d))

    cfg = json.loads(EXAMPLE_CANDIDATES.read_text())
    cfg["families"] = {"agentic-coding": cfg["families"]["agentic-coding"]}
    cfg["objective"]["constraints"]["latency_slo"] = {"p95_ms": 1000}
    cfg_path = tmp_path / "candidates.json"
    cfg_path.write_text(json.dumps(cfg))
    return tiers_dir, cfg_path


def test_the_latency_slo_fixture_actually_excludes_the_candidate_via_assign_family(tmp_path):
    """Not a C6 assertion -- a guard on the fixture above, so the amendment-8 test below is known to be
    exercising a real exclusion and not compiling around it by accident."""
    tiers_dir, cfg_path = _ledger_with_a_latency_slo_violation(tmp_path)
    out_path = tmp_path / "table.json"
    rc = run_cli(["compile", "--config", str(cfg_path), "--out", str(out_path), "--registry", str(tiers_dir)])
    assert rc == 0
    table = json.loads(out_path.read_text())
    entry = table["families"]["agentic-coding"]["cannot_reject"]
    assert "api-cheap-a" in entry["excluded_by_constraint"]
    assert "p95" in entry["excluded_by_constraint"]["api-cheap-a"]
    # Amendment 8's own point, checked directly against `ranked`: the excluded tier reaches neither
    # `arrangements` nor `ranked`, which is exactly why a set derived from `ranked` would have omitted it.
    ranked_heads = {tuple(c["arrangement"]) for c in entry["ranked"]}
    assert not any("api-cheap-a" in heads for heads in ranked_heads)


def test_a_candidate_assign_family_excludes_is_named_in_the_compiled_artifact_with_no_bound(tmp_path):
    """Amendment 8, directly: "the set is derived from every candidate the ledger records an outcome for, and
    a candidate `assign_family` excluded is named with the reason it was excluded and no bound -- the same
    treatment C6 already gives a candidate the ledger cannot bound." `api-cheap-a` has a recorded outcome for
    `agentic-coding` (attempted=20) and is excluded by the SLO guard; it must be present in the compiled
    artifact's `candidates`, not omitted the way a `ranked`-derived set would have omitted it, and it must
    carry no bound -- the guard that excluded it says nothing about whether the ledger could otherwise have
    bounded it, so `None` (not some numeric leftover) is the only honest value here."""
    tiers_dir, cfg_path = _ledger_with_a_latency_slo_violation(tmp_path)
    out_path = tmp_path / "table.json"
    rc = run_cli(["compile", "--config", str(cfg_path), "--out", str(out_path), "--registry", str(tiers_dir)])
    assert rc == 0
    table = json.loads(out_path.read_text())
    cands = table["decide"]["agentic-coding"]["cannot_reject"]["candidates"]
    assert "api-cheap-a" in cands, "excluded by a constraint, not omitted -- the same fate C6 gives no_bound"
    assert cands["api-cheap-a"] is None
    # The two candidates the constraint did not touch are still both there: this is not a second collapse
    # wearing amendment 8's justification.
    assert set(cands) == SHIPPED_TIER_IDS
