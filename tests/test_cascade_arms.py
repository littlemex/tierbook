"""Cascade arms: a student answers when its own score clears a declared threshold, otherwise a fallback answers.

Written against the contract in `config.Cascade` and `certify.compose`: the cascade's attempt is the primary's at or
above the threshold (whatever its outcome) and the fallback's below it; its cost is what both consumed; a primary attempt
with no score goes where the declared `on_no_score` says; a deferred attempt the fallback never made is unobserved; an
attempt recorded under a cascade's own name is refused; composed attempts are never written as evidence.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import certify  # noqa: E402
from tierbook import config as cfgmod  # noqa: E402
from tierbook import export_vsr  # noqa: E402
from tierbook.evidence import EvidenceError  # noqa: E402
from tierbook.observation import Observation, ingest_chat_log, read, write  # noqa: E402

SALT, FRACTION, T = "cascade-salt", 0.5, "sentiment"


def cascade(threshold=0.8, on_no_score="fallback", primary="student", fallback="teacher"):
    return {"cascade": {"primary": primary, "fallback": fallback, "threshold": threshold, "on_no_score": on_no_score}}


def candidates(tmp_path: Path, extra: dict | None = None) -> cfgmod.Config:
    c = {
        "student": {"deployment": "self_hosted", "hourly_usd": 0.2,
                    "endpoint": {"base_url": "http://student/v1", "model": "student"}},
        "teacher": {"deployment": "api", "endpoint": {"base_url": "http://teacher/v1", "model": "teacher"},
                    "price_per_mtok": {"fresh_in": 10.0, "cached_in": 0.0, "out": 0.0}},
        "routed": cascade(0.8),
    }
    c.update(extra or {})
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps({"config_format": 2, "candidates": c, "families": {}}))
    return cfgmod.load_config(p)


def declarations(**over) -> certify.Declarations:
    d = dict(alpha=0.05, bound="tierbook.bounds:wilson", holdout_fraction=FRACTION, split_salt=SALT,
             unobserved_as="rejected", max_observation_age_days=None, held_out_correction="none", holdout_ladder=1,
             task_types={T: {"floor": 0.1}}, repeat_rule="all",
             usd_per_attempt={"student": {"usd": 0.001, "source": "test: 0.2 USD/h over 200 items/h"}})
    d.update(over)
    return certify.load_declarations(d)


def obs(item, arm, outcome, *, score=None, tokens=None, run="1", observed_at="2026-11-10T00:00:00Z",
        label_source="dataset"):
    usage = {} if tokens is None else {"fresh_in": tokens, "cached_in": 0, "out": 0}
    return Observation(item=item, task_type=T, arm=arm, outcome=outcome, usage=usage, run=run, score=score,
                       observed_at=observed_at, label_source=label_source,
                       reason="" if outcome != "unobserved" else "no answer")


def composed(observations, cfg, arm="routed"):
    return {o.item: o for o in certify.compose(observations, cfg) if o.arm == arm}


# --- composition ---------------------------------------------------------------------------------------------------

def test_primary_answers_at_or_above_threshold_and_fallback_below(tmp_path):
    cfg = candidates(tmp_path)
    got = composed([
        obs("a", "student", "accepted", score=0.9), obs("a", "teacher", "rejected", tokens=100),
        obs("b", "student", "rejected", score=0.8), obs("b", "teacher", "accepted", tokens=100),
        obs("c", "student", "rejected", score=0.79), obs("c", "teacher", "accepted", tokens=100),
    ], cfg)
    assert got["a"].outcome == "accepted"          # served by the student
    assert got["b"].outcome == "rejected"          # 0.8 is at the threshold: the student answers
    assert got["c"].outcome == "accepted"          # below: the teacher answers
    assert all(o.score is None for o in got.values())


def test_an_ungraded_answer_above_the_threshold_is_served_and_stays_ungraded(tmp_path):
    cfg = candidates(tmp_path)
    got = composed([obs("a", "student", "unobserved", score=0.95), obs("a", "teacher", "accepted", tokens=10)], cfg)
    assert got["a"].outcome == "unobserved"
    assert [p.arm for p in got["a"].parts] == ["student"]


def test_a_primary_attempt_with_no_score_goes_where_on_no_score_says(tmp_path):
    cfg = candidates(tmp_path, {"strict": cascade(on_no_score="unobserved")})
    rows = [obs("a", "student", "rejected"), obs("a", "teacher", "accepted", tokens=10)]
    assert composed(rows, cfg, "routed")["a"].outcome == "accepted"
    strict = composed(rows, cfg, "strict")["a"]
    assert strict.outcome == "unobserved" and "no score" in strict.reason


def test_deferred_attempt_the_fallback_never_made_is_unobserved_with_a_reason(tmp_path):
    cfg = candidates(tmp_path)
    got = composed([obs("a", "student", "accepted", score=0.1)], cfg)
    assert got["a"].outcome == "unobserved"
    assert "teacher" in got["a"].reason


def test_fallback_is_matched_on_the_same_run(tmp_path):
    cfg = candidates(tmp_path)
    got = composed([obs("a", "student", "accepted", score=0.1, run="1"),
                    obs("a", "teacher", "accepted", tokens=10, run="2")], cfg)
    assert got["a"].outcome == "unobserved"


def test_an_attempt_recorded_under_a_cascade_is_refused(tmp_path):
    cfg = candidates(tmp_path)
    with pytest.raises(EvidenceError, match="recorded under the cascade"):
        certify.compose([obs("a", "routed", "rejected"), obs("a", "student", "accepted", score=0.9)], cfg)


def test_a_cascade_may_fall_back_to_a_cascade(tmp_path):
    cfg = candidates(tmp_path, {
        "mid": {"deployment": "self_hosted", "hourly_usd": 1.0, "endpoint": {"base_url": "http://mid/v1", "model": "m"}},
        "mid-or-teacher": cascade(0.7, primary="mid"),
        "chain": cascade(0.9, fallback="mid-or-teacher"),
    })
    rows = [obs("a", "student", "rejected", score=0.5), obs("a", "mid", "rejected", score=0.6),
            obs("a", "teacher", "accepted", tokens=10),
            obs("b", "student", "rejected", score=0.5), obs("b", "mid", "accepted", score=0.95)]
    got = composed(rows, cfg, "chain")
    assert got["a"].outcome == "accepted" and sorted(p.arm for p in got["a"].parts) == ["mid", "student", "teacher"]
    assert got["b"].outcome == "accepted" and sorted(p.arm for p in got["b"].parts) == ["mid", "student"]


def test_an_undated_part_leaves_the_composed_attempt_undated_and_stale_under_a_limit(tmp_path):
    cfg = candidates(tmp_path)
    rows = [obs(f"i{k}", "student", "rejected", score=0.1) for k in range(20)]
    rows += [obs(f"i{k}", "teacher", "accepted", tokens=10, observed_at="") for k in range(20)]
    assert all(o.observed_at == "" for o in composed(rows, cfg).values())
    policy = certify.derive(rows, cfg, declarations(max_observation_age_days=30),
                            as_of=datetime(2026, 11, 11, tzinfo=timezone.utc))
    assert policy["task_types"][T]["arms"]["routed"]["stale_attempts"] == 20


# --- pricing and the policy ----------------------------------------------------------------------------------------

def test_cost_is_every_primary_attempt_plus_fallback_on_deferred_items_only(tmp_path):
    cfg = candidates(tmp_path)
    rows = []
    for k in range(40):
        deferred = k % 4 == 0
        rows.append(obs(f"i{k}", "student", "accepted", score=0.5 if deferred else 0.95))
        rows.append(obs(f"i{k}", "teacher", "accepted", tokens=1000))
    arms = certify.derive(rows, cfg, declarations())["task_types"][T]["arms"]["routed"]
    for part in ("selection", "held_out"):
        cell = arms[part]
        n, deferred = cell["attempts"], cell["part_attempts"].get("teacher", 0)
        assert cell["part_attempts"]["student"] == n
        assert cell["part_tokens"]["teacher"]["fresh_in"] == 1000 * deferred
        assert cell["spend_usd"] == pytest.approx(0.001 * n + deferred * 1000 * 10.0 / 1e6)


def test_label_sources_cover_every_part_that_was_called(tmp_path):
    cfg = candidates(tmp_path)
    rows = []
    for k in range(20):
        rows += [obs(f"i{k}", "student", "rejected", score=0.1, label_source="dataset"),
                 obs(f"i{k}", "teacher", "accepted", tokens=10, label_source="human")]
    arms = certify.derive(rows, cfg, declarations())["task_types"][T]["arms"]["routed"]
    assert set(arms["selection"]["label_sources"]) == {"dataset", "human"}


def test_the_policy_says_which_assignment_is_a_cascade_and_how(tmp_path):
    cfg = candidates(tmp_path)
    rows = []
    for k in range(400):
        sure = k % 10 != 0
        rows += [obs(f"i{k}", "student", "accepted" if sure else "rejected", score=0.95 if sure else 0.1),
                 obs(f"i{k}", "teacher", "accepted", tokens=10**6)]
    # the student alone accepts 0.9, below the floor; the teacher accepts everything at $10 an attempt; the cascade
    # accepts everything at the student's price plus the teacher on a tenth of the items
    policy = certify.derive(rows, cfg, declarations(task_types={T: {"floor": 0.95}}))
    e = policy["task_types"][T]
    assert e["arm"] == "routed", e["reason"]
    assert e["cascade"] == {"primary": "student", "fallback": "teacher", "threshold": 0.8, "on_no_score": "fallback"}
    assert certify.as_table(policy, allow_unconfirmed=True)["families"][T]["cannot_reject"]["kind"] == "cascade"


def test_threshold_variants_are_ordinary_candidates_chosen_on_selection_and_checked_on_held_out(tmp_path):
    cfg = candidates(tmp_path, {f"routed-{t}": cascade(t) for t in (0.5, 0.95)})
    rows = []
    for k in range(200):
        sure = k % 2 == 0
        rows.append(obs(f"i{k}", "student", "accepted" if sure else "rejected", score=0.99 if sure else 0.6))
        rows.append(obs(f"i{k}", "teacher", "accepted", tokens=1000))
    entry = certify.derive(rows, cfg, declarations(task_types={T: {"floor": 0.9}}))["task_types"][T]
    assert entry["arm"] in ("routed", "routed-0.95")
    assert entry["arms"]["routed-0.5"]["selection"]["rate"] == pytest.approx(0.5, abs=0.1)
    assert entry["status"] == "certified"
    assert entry["held_out"]["items"] > 50 and entry["held_out"]["rate"] == 1.0
    assert entry["held_out"]["lower"] >= 0.9


def test_needs_measurement_lists_the_parts_not_the_cascade(tmp_path):
    cfg = candidates(tmp_path)
    rows = [obs(f"i{k}", "teacher", "accepted", tokens=10) for k in range(40)]
    d = declarations(min_items=5)
    policy = certify.derive(rows, cfg, d)
    arms = {n["arm"] for n in certify.drift(policy, policy, [], d, cfg)["needs_measurement"]}
    assert "student" in arms and "routed" not in arms


def test_vsr_export_refuses_a_cascade_it_cannot_run(tmp_path):
    cfg = candidates(tmp_path)
    with pytest.raises(export_vsr.ExportError, match="cascade"):
        export_vsr._provider_model(cfg.candidates["routed"])


# --- the record ----------------------------------------------------------------------------------------------------

def test_composition_does_not_change_the_record_format(tmp_path):
    cfg = candidates(tmp_path)
    rows = [obs("a", "student", "accepted", score=0.9), obs("a", "teacher", "accepted", tokens=10)]
    path = tmp_path / "obs.jsonl"
    write(rows, path)
    back = read(path)
    assert back == rows and back[0].score == 0.9
    assert all(set(dataclasses.asdict(o)) == set(Observation.__dataclass_fields__) for o in back)
    certify.derive(back, cfg, declarations())


def test_composed_attempts_are_never_written_as_evidence(tmp_path):
    cfg = candidates(tmp_path)
    rows = certify.compose([obs("a", "student", "accepted", score=0.9)], cfg)
    with pytest.raises(EvidenceError, match="never written"):
        write(rows, tmp_path / "out.jsonl")


def test_a_row_is_written_in_the_oldest_format_that_carries_it(tmp_path):
    path = tmp_path / "obs.jsonl"
    write([obs("a", "teacher", "accepted", tokens=1), obs("a", "student", "accepted", score=0.5)], path)
    assert [json.loads(line)["format"] for line in path.read_text().splitlines()] == [1, 2]


def test_ingest_carries_the_score_from_the_call_log():
    calls = [{"item": "a", "task_type": T, "arm": "student", "run": "1", "score": 0.73,
              "response": {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}]}}]
    grades = [{"item": "a", "arm": "student", "run": "1", "outcome": "accepted"}]
    (o,) = ingest_chat_log(calls, grades)
    assert o.score == 0.73


# --- declarations --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("entry, message", [
    ({"cascade": {"primary": "student", "fallback": "teacher", "threshold": 0.5}}, "on_no_score"),
    (cascade(0.5, on_no_score="guess"), "on_no_score must be one of"),
    (cascade(True), "must be a number"),
    ({**cascade(0.5), "hourly_usd": 1.0}, "own price"),
    ({**cascade(0.5), "endpoint": {"base_url": "http://r/v1", "model": "r"}}, "has none of its own"),
    (cascade(0.5, fallback="nobody"), "not a candidate"),
    (cascade(0.5, fallback="student"), "both"),
    ({**cascade(0.5), "deployment": "api"}, "no deployment of its own"),
])
def test_cascade_declarations_are_checked(tmp_path, entry, message):
    with pytest.raises(cfgmod.ConfigError, match=message):
        candidates(tmp_path, {"bad": entry})


def test_a_cascade_cannot_be_another_cascades_primary(tmp_path):
    with pytest.raises(cfgmod.ConfigError, match="as its primary"):
        candidates(tmp_path, {"outer": cascade(0.7, primary="routed")})


def test_a_cascade_containing_itself_is_refused(tmp_path):
    with pytest.raises(cfgmod.ConfigError, match="contains itself"):
        candidates(tmp_path, {"x": cascade(0.5, fallback="y"), "y": cascade(0.5, fallback="x")})


def test_a_missing_part_deep_in_a_chain_is_a_config_error(tmp_path):
    with pytest.raises(cfgmod.ConfigError, match="not a candidate"):
        candidates(tmp_path, {"x": cascade(0.5, fallback="y"), "y": cascade(0.5, fallback="nobody")})


# --- second review round -------------------------------------------------------------------------------------------

def test_an_arm_reached_twice_along_a_fallback_chain_is_refused(tmp_path):
    with pytest.raises(cfgmod.ConfigError, match="more than once"):
        candidates(tmp_path, {"inner": cascade(0.5), "outer": cascade(0.9, fallback="inner")})


def test_parts_that_disagree_about_the_task_type_are_refused(tmp_path):
    cfg = candidates(tmp_path)
    other = Observation(item="a", task_type="other", arm="teacher", outcome="accepted", run="1",
                        usage={"fresh_in": 1, "cached_in": 0, "out": 0}, observed_at="2026-11-10T00:00:00Z")
    with pytest.raises(EvidenceError, match="disagree"):
        certify.compose([obs("a", "student", "rejected", score=0.1), other], cfg)


def test_an_unscored_failed_call_keeps_its_own_reason(tmp_path):
    cfg = candidates(tmp_path, {"strict": cascade(on_no_score="unobserved")})
    failed = Observation(item="a", task_type=T, arm="student", outcome="unobserved", reason="HTTP 503", run="1")
    got = composed([failed], cfg, "strict")["a"]
    assert got.reason.startswith("HTTP 503") and "no score" in got.reason


def test_an_ungraded_primary_with_no_usage_makes_a_graded_cascade_attempt_unpriceable(tmp_path):
    cfg = candidates(tmp_path, {"api-student": {"deployment": "api", "endpoint": {"base_url": "http://s/v1",
                                                                                  "model": "s"},
                                                "price_per_mtok": {"fresh_in": 1.0, "cached_in": 0.0, "out": 0.0}},
                                "api-routed": cascade(0.8, primary="api-student")})
    rows = []
    for k in range(20):
        ungraded = Observation(item=f"i{k}", task_type=T, arm="api-student", outcome="unobserved", reason="ungraded",
                               run="1", score=0.1, observed_at="2026-11-10T00:00:00Z")
        rows += [ungraded, obs(f"i{k}", "teacher", "accepted", tokens=10)]
    cell = certify.derive(rows, cfg, declarations())["task_types"][T]["arms"]["api-routed"]["selection"]
    assert cell["spend_usd"] is None and "reported no usage" in cell["priced_by"]


def test_deferrals_the_fallback_never_answered_are_listed_as_needing_measurement(tmp_path):
    cfg = candidates(tmp_path)
    rows = [obs(f"i{k}", "student", "rejected", score=0.1) for k in range(30)]
    rows += [obs(f"i{k}", "teacher", "accepted", tokens=10) for k in range(10)]
    d = declarations(min_items=5)
    policy = certify.derive(rows, cfg, d)
    needs = certify.drift(policy, policy, [], d, cfg)["needs_measurement"]
    assert any(n["arm"] == "teacher" and "'routed'" in n["why"] for n in needs)


def test_drift_refuses_a_cascade_redefined_under_the_deployed_name(tmp_path):
    cfg = candidates(tmp_path)
    rows = []
    for k in range(400):
        sure = k % 10 != 0
        rows += [obs(f"i{k}", "student", "accepted" if sure else "rejected", score=0.95 if sure else 0.1),
                 obs(f"i{k}", "teacher", "accepted", tokens=10**6)]
    d = declarations(task_types={T: {"floor": 0.95}}, min_items=5)
    policy = certify.derive(rows, cfg, d)
    assert policy["task_types"][T]["arm"] == "routed"
    (tmp_path / "changed").mkdir()
    changed = candidates(tmp_path / "changed", {"routed": cascade(0.5)})
    with pytest.raises(certify.DeclarationError, match="defines it differently"):
        certify.drift(policy, policy, rows, d, changed)


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_a_score_must_be_finite(value):
    with pytest.raises(EvidenceError, match="finite"):
        obs("a", "student", "accepted", score=value)


def test_a_threshold_must_be_finite(tmp_path):
    with pytest.raises(cfgmod.ConfigError, match="must be a number"):
        candidates(tmp_path, {"bad": cascade(float("inf"))})


def test_a_format_1_row_carrying_a_score_is_refused():
    with pytest.raises(EvidenceError, match="format 2 introduced"):
        Observation.from_row({"format": 1, "item": "a", "task_type": T, "arm": "s", "outcome": "accepted",
                              "usage": {}, "score": 0.5})


def test_a_refused_write_leaves_the_existing_file_untouched(tmp_path):
    cfg = candidates(tmp_path)
    path = tmp_path / "obs.jsonl"
    write([obs("a", "teacher", "accepted", tokens=1)], path)
    before = path.read_text()
    with pytest.raises(EvidenceError):
        write(certify.compose([obs("a", "student", "accepted", score=0.9)], cfg), path)
    assert path.read_text() == before


def test_vsr_export_refuses_a_cascade_assignment_from_the_table(tmp_path):
    cfg = candidates(tmp_path)
    table = {"families": {T: {"cannot_reject": {"status": "assigned", "kind": "cascade", "chosen": ["routed"],
                                                "why": "test", "cascade": {"primary": "student", "fallback": "teacher",
                                                                           "threshold": 0.8}}}}}
    with pytest.raises(export_vsr.ExportError, match="cascade"):
        export_vsr.export(table, cfg, signal_for_family={T: T}, default_model="teacher")
