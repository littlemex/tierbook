"""The refusals, each pinned by the mistake it prevents.

Every test here corresponds to something that either went wrong in this project or would have gone wrong
silently. They are written as regressions rather than as feature tests because that is what they are: the
value of a refusal is that it keeps firing after everyone has forgotten why it exists.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.config import ConfigError, Objective, draft_from_model_list, load_config
from tierbook.logs import (AgreementStudy, LoggedTask, coverage, disagreement_audit, extract_tasks,
                           temporal_split)
from tierbook.policy import (EXECUTABLE_CHECK, HUMAN_LABEL, MODEL_REFERENCE, comparable, evidence_class,
                             load_registry, may_assign, tautological, throughput_for)


LEDGER = str(ROOT / "examples" / "ledger" / "tiers")
# No path needed: the schema travels with the package, which is what makes the refusal
# below apply to a candidate file deployed on its own.
SCHEMA = None
CANDIDATES = str(ROOT / "examples" / "ledger" / "candidates.json")
VALIDATION = str(ROOT / "examples" / "ledger" / "validation")


def _write(tmp_path, body: dict, name="candidates.json"):
    p = tmp_path / name
    p.write_text(json.dumps(body))
    return p


def _minimal(**over) -> dict:
    base = {
        "config_format": 1,
        "candidates": {
            "ref": {"deployment": "api",
                    "endpoint": {"base_url": "https://x/v1", "model": "m"},
                    "price_per_mtok": {"fresh_in": 1.0, "cached_in": 0.1, "out": 5.0}},
        },
        "families": {"f": "ref"},
        "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.15}}},
    }
    base.update(over)
    return base


# --- requirement 1: serving is somebody else's job ------------------------------------------------


@pytest.mark.parametrize("key,value", [
    ("image", "vllm/vllm-openai:latest"),
    ("launch", "vllm serve"),
    ("replicas", 2),
    ("gpu", "8"),
    ("weights", "/models/qwen"),
])
def test_a_candidate_that_says_how_to_start_a_model_does_not_load(tmp_path, key, value):
    """The boundary is a refusal rather than a sentence in a README.

    Anyone writing these keys is doing something reasonable in the wrong file, so the message names the
    boundary and points at the field that belongs here instead.
    """
    body = _minimal()
    body["candidates"]["ref"][key] = value
    with pytest.raises(ConfigError, match="how to START a model"):
        load_config(_write(tmp_path, body))


# --- requirement 2: configuration is not evidence -------------------------------------------------


@pytest.mark.parametrize("key,value", [
    ("families", {"f": {"solved": 18, "attempted": 20}}),
    ("reliability", {"failures": 0, "attempts_observed": 100}),
    ("latency", {"p50": 3.0}),
    ("solved", 18),
    ("paired_vs_reference", {"both": 10}),
])
def test_a_candidate_cannot_hand_write_a_measurement(tmp_path, key, value):
    """Derived from the record schema, so the two cannot drift apart.

    The failure this prevents is the easy one: the candidate file is the file an operator edits, and without
    this rule it is also the shortest path to a routing decision backed by a number somebody typed.
    """
    body = _minimal()
    body["candidates"]["ref"][key] = value
    with pytest.raises(ConfigError, match="only a measurement may set"):
        load_config(_write(tmp_path, body))


def test_a_self_hosted_candidate_without_an_hourly_bill_does_not_load(tmp_path):
    body = _minimal()
    body["candidates"]["box"] = {"deployment": "self_hosted",
                                 "endpoint": {"base_url": "http://svc:8000/v1", "model": "m"}}
    with pytest.raises(ConfigError, match="bills while it is idle"):
        load_config(_write(tmp_path, body))


def test_a_discovered_draft_does_not_load(tmp_path):
    """Discovery prints stationery, and the stationery is deliberately unusable until a human fills it in.

    A gateway advertises names. Asked live, the one this project uses returns identifiers and display names
    and nothing else -- no price, no capability, no quality. A draft that loaded would let a routing decision
    depend on a gateway's publication state that nobody committed to.
    """
    draft = draft_from_model_list([{"id": "vendor/model-a"}, {"id": "vendor/model-b"}],
                                  base_url="https://gw/v1", api_key_env="K")
    assert len(draft["candidates"]) == 2
    assert all(c["price_per_mtok"] is None for c in draft["candidates"].values())
    with pytest.raises(ConfigError, match="price_per_mtok"):
        load_config(_write(tmp_path, draft))


# --- requirement 3: one objective, and constraints that cannot be switched off ---------------------


def test_there_is_no_syntax_for_weighting_quality_against_cost(tmp_path):
    """Refused rather than defaulted.

    Once quality is a term in a weighted sum, "cheapest" stops denoting anything a reader can check, and the
    exchange rate between a defect and a dollar has been chosen by whoever wrote the default.
    """
    body = _minimal(objective={"objective": "cost", "weights": {"quality": 0.7, "cost": 0.3}})
    with pytest.raises(ConfigError, match="refused"):
        load_config(_write(tmp_path, body))


def test_the_margin_is_always_present_even_when_nobody_writes_one(tmp_path):
    body = _minimal(objective={"objective": "cost"})
    cfg = load_config(_write(tmp_path, body))
    assert cfg.objective.margin == 0.15          # a default, because there is no way to mean "no bound"


def test_only_the_two_objectives_exist():
    with pytest.raises(ConfigError):
        Objective(objective="quality")           # quality is the constraint, never the thing maximised


def test_choosing_latency_can_choose_a_different_tier_than_choosing_cost():
    """The two objectives are not the same ordering, which is why the table records which one it used."""
    from tierbook.policy import assign_family

    tiers = load_registry(LEDGER)
    fam, ref = "tool-agent-user-retail", "api-strong-a"
    by_cost = assign_family(tiers, fam, ref, margin=0.25, today="2026-08-30", objective="cost")
    by_latency = assign_family(tiers, fam, ref, margin=0.25, today="2026-08-30", objective="latency")
    assert by_cost.objective == "cost" and by_latency.objective == "latency"
    # The cheapest per request and the fastest to an accepted answer are different tiers on this family.
    assert by_cost.chosen.head != by_latency.chosen.head
    assert by_latency.chosen.head == "self-hosted-a"


def test_reliability_is_a_constraint_and_not_a_discount():
    """A tier that cannot finish is excluded, not repriced.

    Folding reliability into the objective would let a cheap-but-unfinishing tier win by being cheap enough.
    It is a requirement its owner states, so it removes candidates instead of adjusting them.
    """
    from tierbook.policy import assign_family

    tiers = load_registry(LEDGER)
    d = assign_family(tiers, "tool-agent-user-retail", "api-strong-a", margin=0.25, today="2026-08-30",
                      min_completion_probability=1.01)     # nothing can satisfy this
    assert not d.certified
    assert "Excluded by constraint" in d.why
    assert d.chosen.head == "api-strong-a"


# --- the correction: a per-task latency is not a throughput ---------------------------------------


def test_a_fixed_cost_tier_with_no_latency_for_this_family_refuses_rather_than_borrowing_one():
    """The refusal that caught a published figure in this repository.

    A cost per request was published having divided an hourly bill by the observed per-task time times an
    *assumed* sixteen requests in flight. The run recorded no timestamps, so its realised throughput was never
    measured; the assumption moved the figure by a factor of six and changed which tier the rule chose.
    """
    tiers = load_registry(LEDGER)
    box = tiers["self-hosted-a"]
    # This family has no latency recorded, so nothing may be substituted for it.
    value, refusal = throughput_for(box, "agentic-coding", None)
    assert value is None
    assert refusal is not None and "must not be borrowed" in refusal
    # The family that does have one derives a throughput from it, at the concurrency it was observed at.
    value, refusal = throughput_for(box, "tool-agent-user-retail", None)
    assert refusal is None
    # 3600 / 16.5s mean at concurrency 1. The mean rather than the p50, because amortisation divides an
    # hourly bill by tasks completed and that is total time over tasks, which is what a mean is.
    assert 210 < value < 230


def test_a_per_token_tier_needs_no_throughput_at_all():
    tiers = load_registry(LEDGER)
    assert throughput_for(tiers["api-cheap-a"], "agentic-coding", None) == (None, None)


# --- requirement 4: the log benchmark, and what it may not become ---------------------------------


def _task(i, *, check=None, at="2026-08-01"):
    return LoggedTask(id=f"t{i}", family="f", request={"messages": []}, check=check, recorded_at=at)


def test_a_check_the_candidate_wrote_is_not_a_check():
    """Measured here: tests taken from a model's own output passed on 100% of the items it failed to solve.

    A model that cannot fix a bug writes a test that agrees with it, so a candidate-authored check is a
    model's opinion wearing a shell script. The origin field is the whole test.
    """
    from_log = _task(1, check={"kind": "test_suite", "origin": "log"})
    from_model = _task(2, check={"kind": "test_suite", "origin": "candidate"})
    assert from_log.admissible
    assert not from_model.admissible
    assert "cannot certify the candidate" in from_model.inadmissible_reason


def test_coverage_reports_the_subset_rather_than_extrapolating():
    tasks = [_task(i, check={"kind": "exit_status", "origin": "log"}) for i in range(3)] + \
            [_task(i) for i in range(3, 25)]
    cov = coverage(tasks)
    assert cov["logs_considered"] == 25 and cov["with_admissible_check"] == 3
    assert cov["fraction"] == pytest.approx(0.12)
    assert any("no independent check" in r for r in cov["excluded_reasons"])


def test_an_agreement_study_cannot_assign_and_cannot_validate():
    """The structural cap, checked through the same function the compiler uses.

    Named `reference_agreement` rather than `accuracy`, and the reason is a measurement: the strongest tier
    here solved 95 of 115 while cheaper tiers solved 101, missing six to nine items they got right. Scoring
    by agreement with the strongest would have marked them down exactly where they were right.
    """
    study = AgreementStudy(reference_model="strong-x", reference_revision="2026-07",
                           generated_at="2026-07-01", prompt_digest="abc123")
    for i in range(90):
        study.observe(f"t{i}", agrees=True)
    for i in range(90, 100):
        study.observe(f"t{i}", agrees=False)
    rec = study.record(tier_id="cheap-y", family="f", tasks=[_task(i) for i in range(100)],
                       bill_usd=1.0, measured_at="2026-08-30")
    assert rec["claim"]["kind"] == "reference_agreement"
    assert rec["claim"]["metric"].startswith("agreement@ref=strong-x:2026-07:")
    assert evidence_class(rec) == MODEL_REFERENCE
    assert not may_assign(rec)
    assert study.rate == pytest.approx(0.90)


def test_an_agreement_record_may_not_be_compared_with_a_solve_rate():
    """0.85 agreement inside a 0.15 margin of a 0.90 solve rate is a type error, not a close call."""
    study = AgreementStudy("strong-x", "2026-07", "2026-07-01", "abc")
    study.observe("t1", agrees=True)
    agreement = study.record(tier_id="cheap-y", family="f", tasks=[_task(1)], bill_usd=0.1,
                             measured_at="2026-08-30")
    correctness = json.loads(open(f"{LEDGER}/api-cheap-a.json").read())
    why = comparable(agreement, correctness)
    assert why is not None and "different classes of evidence" in why


def test_a_model_scored_against_its_own_answers_is_refused_not_reported():
    reference = {"oracle": {"kind": "model_generated_reference", "independent_of_candidate": False,
                            "generator": {"model": "strong-x"}}}
    assert tautological({"id": "strong-x"}, reference) is not None
    assert tautological({"id": "cheap-y"}, reference) is None


def test_an_audit_of_every_disagreement_yields_evidence_that_can_assign():
    """The one promotion path, and it is minimal for a structural reason.

    Where the two agree the study says nothing about which is right, so labelling agreements buys nothing.
    Labelling the disagreements -- typically dozens -- is what turns triage into evidence.
    """
    study = AgreementStudy("strong-x", "2026-07", "2026-07-01", "abc")
    for i in range(50):
        study.observe(f"t{i}", agrees=True)
    for i in range(50, 56):
        study.observe(f"t{i}", agrees=False)
    partial = disagreement_audit(study, {f"t{i}": "candidate" for i in range(50, 53)})
    assert not partial["usable"] and "unlabelled" in partial["reason"]

    full = disagreement_audit(study, {**{f"t{i}": "candidate" for i in range(50, 53)},
                                      **{f"t{i}": "reference" for i in range(53, 55)},
                                      "t55": "neither"})
    assert full["usable"] and full["evidence_class"] == HUMAN_LABEL
    assert full["paired_vs_reference"] == {"both": 50, "candidate_only": 3, "reference_only": 2, "neither": 1}


def test_a_record_that_does_not_say_what_judged_it_cannot_assign():
    """Default deny, and it fired on this project's own held-out record before it was annotated."""
    assert evidence_class({}) == MODEL_REFERENCE
    assert evidence_class({"oracle": {"kind": "executable_acceptance",
                                      "independent_of_candidate": True}}) == EXECUTABLE_CHECK
    assert evidence_class({"oracle": {"kind": "human_label", "independent_of_candidate": True}}) == HUMAN_LABEL


def test_the_shipped_records_all_say_what_judged_them():
    for tier in load_registry(LEDGER).values():
        assert may_assign(tier.record), f"{tier.id} would be unable to assign"


def test_a_temporal_split_is_the_one_that_matches_how_a_router_is_used():
    tasks = [_task(i, at=f"2026-0{1 + i // 3}-01") for i in range(9)]
    before, after = temporal_split(tasks, at="2026-02-15")
    assert len(before) == 6 and len(after) == 3
    assert {t.id for t in before}.isdisjoint({t.id for t in after})


def test_extraction_reads_a_log_and_leaves_the_family_to_the_caller(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"id": "a", "messages": [{"role": "user", "content": "hi"}], "family": "chat"},
        {"id": "b", "messages": [], "check": {"kind": "exit_status", "origin": "log"}},
    ]))
    tasks = extract_tasks(p)
    assert [t.family for t in tasks] == ["chat", "unclassified"]
    assert [t.admissible for t in tasks] == [False, True]


# --- the export boundary --------------------------------------------------------------------------


def test_a_chain_is_not_exported_as_its_head(tmp_path):
    """Exporting the head alone would drop the safety net that justified the arrangement."""
    from tierbook.export_vsr import ExportError, export
    from tierbook.table import compile_to_file

    cfg = load_config(CANDIDATES)
    table = compile_to_file(load_registry(LEDGER), {"agentic-coding": "api-strong-a"},
                            tmp_path / "table.json", margin=0.30, today="2026-08-30")
    entry = table["families"]["agentic-coding"]["can_reject"]
    assert entry["kind"] == "chain"                     # otherwise this test is not testing anything
    with pytest.raises(ExportError, match="chain"):
        export(table, cfg, signal_for_family={"agentic-coding": "computer_science"},
               default_model="api-strong-a", request_can_reject=True, allow_provisional=True)


def test_a_family_with_no_classifier_label_is_refused_rather_than_guessed(tmp_path):
    from tierbook.export_vsr import ExportError, export
    from tierbook.table import compile_to_file

    cfg = load_config(CANDIDATES)
    table = compile_to_file(load_registry(LEDGER), {"tool-agent-user-retail": "api-strong-a"},
                            tmp_path / "t.json", margin=0.25, today="2026-08-30",
                            validations=VALIDATION)
    with pytest.raises(ExportError, match="no classifier label"):
        export(table, cfg, signal_for_family={}, default_model="api-strong-a")


def test_a_provisional_entry_is_not_exported_without_the_flag(tmp_path):
    from tierbook.export_vsr import ExportError, export
    from tierbook.table import compile_to_file

    cfg = load_config(CANDIDATES)
    table = compile_to_file(load_registry(LEDGER), {"agentic-coding": "api-strong-a"},
                            tmp_path / "t.json", margin=0.25, today="2026-08-30")
    with pytest.raises(ExportError, match="provisional"):
        export(table, cfg, signal_for_family={"agentic-coding": "cs"}, default_model="api-strong-a")


def test_the_exported_config_names_the_tier_the_holdout_supported(tmp_path):
    from tierbook.export_vsr import export
    from tierbook.table import compile_to_file

    cfg = load_config(CANDIDATES)
    table = compile_to_file(load_registry(LEDGER), {"tool-agent-user-retail": "api-strong-a"},
                            tmp_path / "t.json", margin=0.25, today="2026-08-30",
                            validations=VALIDATION)
    conf, prov = export(table, cfg, signal_for_family={"tool-agent-user-retail": "retail"},
                        default_model="api-strong-a")
    decisions = conf["routing"]["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["modelRefs"][0]["model"] == "api-cheap-a"
    # The registry hash travels beside the config -- not inside it, because the router warns on an unknown
    # top-level key and a config that warns on every start is one whose warnings stop being read. It also
    # appears in the recipe description, so a reader of the config alone can still check it.
    assert prov["compiled_from_registry"] == table["registry_version"]
    assert table["registry_version"] in conf["recipes"][0]["description"]
    assert "_tierbook" not in conf, "the router rejects unknown top-level keys"
    # The model catalog is shared, so a recipe may not redefine the cards. The router refuses to start
    # otherwise, and it names exactly that reason.
    assert "modelCards" not in conf["recipes"][0]["routing"]
    assert "modelCards" in conf["routing"]
    # Pricing is translated into the router's key names, not the ledger's.
    pricing = conf["providers"]["models"][0].get("pricing") or {}
    assert "prompt_per_1m" in pricing and "fresh_in" not in pricing
    # The default for unmatched traffic is the reference, not the cheapest thing on offer.
    assert conf["providers"]["defaults"]["default_model"] == "api-strong-a"


def test_the_schema_travels_with_the_installed_package():
    """Pinned because the refusal it powers fails silently the moment it does not.

    `config.py` derives the set of keys a candidate file may not contain from this schema. An earlier version
    looked for it beside the ledger and fell back to an empty set when it was not there, which disabled the
    check in exactly the case that matters: a candidate file deployed on its own.
    """
    from tierbook import SCHEMA_PATH
    from tierbook.config import _record_schema_keys

    assert SCHEMA_PATH.exists(), "the schema must ship inside the package, not beside a ledger"
    keys = _record_schema_keys()
    assert {"families", "reliability", "latency", "price_card", "oracle", "claim"} <= keys
    assert "id" not in keys, "a candidate has to be able to say which tier it is, or the join has no key"


def test_a_missing_schema_raises_rather_than_dropping_the_check(tmp_path):
    from tierbook.config import _record_schema_keys

    with pytest.raises(ConfigError, match="record schema is missing"):
        _record_schema_keys(tmp_path / "nope.json")


def test_a_model_lists_created_at_is_never_read_as_a_revision():
    """A refusal that always fires teaches an operator to ignore it, which is worse than one that never does.

    An earlier version fell back to `created_at` when a model list carried no `revision`. The operators of the
    gateway this project measured then confirmed that their `/v1/models` generates `created_at` at request
    time -- it is neither a registration date nor a model revision. Comparing a fresh timestamp against a
    stored one reports a mismatch on every call, so the one warning that protects the ledger's core promise
    would have become noise.
    """
    from tierbook.config import draft_from_model_list

    draft = draft_from_model_list(
        [{"id": "vendor/a", "created_at": "2026-08-30T12:00:00Z"},
         {"id": "vendor/b", "revision": "2026-07", "created_at": "2026-08-30T12:00:00Z"}],
        base_url="https://gw/v1", api_key_env="K")
    assert draft["candidates"]["vendor-a"]["endpoint"]["revision"] is None
    assert draft["candidates"]["vendor-b"]["endpoint"]["revision"] == "2026-07"
    # And the draft says a model list is not an inventory: on that gateway five servable models appeared in
    # no list at all, so absence from the list is not evidence of absence from the gateway.
    assert "inventory" in " ".join(k for k in draft) or "_draft_is_not_an_inventory" in draft


@pytest.mark.parametrize("port,what", [(8080, "classification API"), (50051, "ExtProc"), (9190, "metrics")])
def test_the_data_plane_cannot_listen_on_a_port_the_router_binds(port, what):
    """Found on a real cluster: a collision here fails as a crash loop, not as a config error.

    The ExtProc and the data plane share a network namespace because the ExtProc call is on the request path
    for every request and must not cross a node boundary. So an Envoy listener on the router's own
    classification API port produces one process that cannot bind, which surfaces as a pod that never becomes
    ready rather than as anything pointing at the port number that caused it.
    """
    from tierbook.export_vsr import ExportError, envoy_config

    cfg = load_config(CANDIDATES)
    with pytest.raises(ExportError, match="cannot listen on"):
        envoy_config(cfg, ["api-cheap-a"], listen_port=port)


def test_a_reserved_entrypoint_name_is_refused_at_export_time(tmp_path):
    """Found on a real cluster: the router reserves `auto` and refuses to start, in a stack trace.

    An entrypoint is the virtual model name a client asks for. Refusing it here rather than at start-up is the
    difference between a message naming the field and a Go stack trace in a crash loop.
    """
    from tierbook.export_vsr import ExportError, export
    from tierbook.table import compile_to_file

    cfg = load_config(CANDIDATES)
    table = compile_to_file(load_registry(LEDGER), {"tool-agent-user-retail": "api-strong-a"},
                            tmp_path / "t.json", margin=0.25, today="2026-08-30", validations=VALIDATION)
    with pytest.raises(ExportError, match="reserves"):
        export(table, cfg, signal_for_family={"tool-agent-user-retail": "retail"},
               default_model="api-strong-a", entrypoint="auto")
