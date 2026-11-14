"""Observation format 3: `arm_version` binds evidence to the exact thing that answered, `path` records which components
ran, and a declared `interfaces` filter keeps arms a router cannot serve out of selection.

Written against `observation.Observation`, `certify.arm_versions`, `certify.derive` and `certify.drift`: an arm whose
rows name two versions (or a version on some rows and none on others) is refused; the policy names the version of the
arm it chose, per component for a cascade; drift refuses fresh rows from a version other than the certified one; a
format-3 row round-trips and an older format may not carry the new keys; `interfaces` filters before selection.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from tierbook import certify  # noqa: E402
from tierbook.evidence import EvidenceError  # noqa: E402
from tierbook.observation import Observation, read, write  # noqa: E402

from test_cascade_arms import T, candidates, declarations, obs  # noqa: E402


def versioned(o: Observation, v: str) -> Observation:
    return dataclasses.replace(o, arm_version=v)


def many(arm, n, outcome="accepted", version="", score=None, tokens=None):
    return [versioned(obs(f"i{k}", arm, outcome, score=score, tokens=tokens), version) for k in range(n)]


# --- the record ----------------------------------------------------------------------------------------------------

def test_format_3_round_trips_and_is_written_only_when_needed(tmp_path):
    a = dataclasses.replace(obs("x", "student", "accepted"), arm_version="sha256:abc", path=("student",))
    b = obs("y", "student", "accepted", score=0.5)
    c = obs("z", "student", "accepted")
    p = tmp_path / "o.jsonl"
    write([a, b, c], p)
    rows = [json.loads(line) for line in p.read_text().splitlines()]
    assert [r["format"] for r in rows] == [3, 2, 1]
    assert read(p) == [a, b, c]


@pytest.mark.parametrize("key,value", [("arm_version", "v1"), ("path", ["student"])])
def test_an_older_format_may_not_carry_the_new_keys(key, value):
    row = {"format": 2, "item": "x", "task_type": T, "arm": "student", "outcome": "accepted", key: value}
    with pytest.raises(EvidenceError, match="format 3"):
        Observation.from_row(row)


def test_path_entries_must_be_arm_names():
    with pytest.raises(EvidenceError, match="path"):
        dataclasses.replace(obs("x", "student", "accepted"), path=("",))


# --- version binding -----------------------------------------------------------------------------------------------

def test_two_versions_under_one_arm_are_refused(tmp_path):
    cfg, decl = candidates(tmp_path), declarations()
    rows = many("student", 10, version="v1") + [versioned(obs("j", "student", "accepted"), "v2")]
    with pytest.raises(EvidenceError, match="2 versions"):
        certify.derive(rows, cfg, decl)


def test_a_version_on_some_rows_and_none_on_others_is_refused(tmp_path):
    cfg, decl = candidates(tmp_path), declarations()
    rows = many("student", 10, version="v1") + [obs("j", "student", "accepted")]
    with pytest.raises(EvidenceError, match="<none>"):
        certify.derive(rows, cfg, decl)


def test_the_policy_names_the_version_it_certified(tmp_path):
    cfg, decl = candidates(tmp_path), declarations()
    policy = certify.derive(many("student", 60, version="sha256:abc"), cfg, decl)
    entry = policy["task_types"][T]
    assert entry["status"] == certify.CERTIFIED and entry["arm"] == "student"
    assert entry["arm_version"] == "sha256:abc"


def test_an_unversioned_arm_is_reported_as_none_not_guessed(tmp_path):
    cfg, decl = candidates(tmp_path), declarations()
    entry = certify.derive(many("student", 60), cfg, decl)["task_types"][T]
    assert entry["arm_version"] is None


def test_a_cascade_reports_its_components_versions(tmp_path):
    cfg, decl = candidates(tmp_path), declarations(usd_per_attempt={
        "student": {"usd": 0.5, "source": "test"}})
    rows = many("student", 60, version="s1", score=0.9) + many("teacher", 60, version="t1", tokens=10)
    policy = certify.derive(rows, cfg, decl)
    cell = policy["task_types"][T]["arms"]["routed"]
    assert cell["arm_version"] is None and cell["component_versions"] == {"student": "s1", "teacher": "t1"}


def test_drift_refuses_fresh_rows_from_another_version(tmp_path):
    cfg, decl = candidates(tmp_path), declarations(min_items=5)
    deployed = certify.derive(many("student", 60, version="v1"), cfg, decl)
    fresh = many("student", 20, version="v2")
    with pytest.raises(EvidenceError, match="different version"):
        certify.drift(deployed, deployed, fresh, decl, cfg)
    certify.drift(deployed, deployed, many("student", 20, version="v1"), decl, cfg)


def test_drift_does_not_refuse_an_arm_with_no_fresh_rows(tmp_path):
    cfg, decl = candidates(tmp_path), declarations(min_items=5)
    deployed = certify.derive(many("student", 60, version="v1"), cfg, decl)
    report = certify.drift(deployed, deployed, many("teacher", 20, tokens=10), decl, cfg)
    assert report["version_unchecked"] == []


def test_drift_says_when_an_unversioned_certificate_meets_versioned_rows(tmp_path):
    cfg, decl = candidates(tmp_path), declarations(min_items=5)
    deployed = certify.derive(many("student", 60), cfg, decl)
    report = certify.drift(deployed, deployed, many("student", 20, version="v9"), decl, cfg)
    assert report["version_unchecked"] == [{"task_type": T, "arm": "student", "fresh_version": "v9"}]


def test_an_aged_out_version_does_not_block_the_new_one(tmp_path):
    from datetime import datetime, timezone
    cfg, decl = candidates(tmp_path), declarations(max_observation_age_days=30)
    old = [dataclasses.replace(o, observed_at="2026-01-01T00:00:00Z", run="old") for o in many("student", 60, version="v1")]
    new = many("student", 60, version="v2")
    policy = certify.derive(old + new, cfg, decl, as_of=datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert policy["task_types"][T]["arm_version"] == "v2"


# --- interfaces ----------------------------------------------------------------------------------------------------

def tagged(tmp_path, cascade_interface="generates"):
    from test_cascade_arms import cascade
    routed = cascade(0.8)
    if cascade_interface:
        routed["interface"] = cascade_interface
    return candidates(tmp_path, {
        "student": {"deployment": "self_hosted", "hourly_usd": 0.2, "interface": "scores_options",
                    "endpoint": {"base_url": "http://student/v1", "model": "student"}},
        "teacher": {"deployment": "api", "interface": "generates",
                    "endpoint": {"base_url": "http://teacher/v1", "model": "teacher"},
                    "price_per_mtok": {"fresh_in": 10.0, "cached_in": 0.0, "out": 0.0}},
        "routed": routed})


def test_interfaces_filter_applies_before_selection(tmp_path):
    cfg = tagged(tmp_path, cascade_interface="scores_options")
    rows = many("student", 60) + many("teacher", 60, tokens=1000)
    open_ = certify.derive(rows, cfg, declarations())["task_types"][T]
    assert open_["arm"] == "student" and "excluded_by_interface" not in open_
    only = certify.derive(rows, cfg, declarations(interfaces=["generates"]))["task_types"][T]
    assert only["arm"] == "teacher"
    assert only["excluded_by_interface"] == ["routed", "student"]


def test_a_cascade_is_never_given_its_primarys_interface(tmp_path):
    cfg = tagged(tmp_path, cascade_interface=None)
    with pytest.raises(certify.DeclarationError, match=r"\['routed'\] declare no interface"):
        certify.derive(many("teacher", 60, tokens=10), cfg, declarations(interfaces=["generates"]))


def test_an_interface_name_no_candidate_carries_is_refused(tmp_path):
    with pytest.raises(certify.DeclarationError, match="carried by no candidate"):
        certify.derive(many("teacher", 60, tokens=10), tagged(tmp_path), declarations(interfaces=["generate"]))


def test_a_declared_fallback_outside_the_filter_is_refused(tmp_path):
    with pytest.raises(certify.DeclarationError, match="fallback_arm"):
        certify.derive(many("teacher", 60, tokens=10), tagged(tmp_path),
                       declarations(interfaces=["generates"], fallback_arm="student"))


def test_when_the_filter_removes_every_passing_arm_the_reason_says_so(tmp_path):
    cfg = tagged(tmp_path, cascade_interface="scores_options")
    entry = certify.derive(many("student", 60), cfg, declarations(interfaces=["generates"]))["task_types"][T]
    assert entry["status"] == certify.UNASSIGNABLE and entry["reason_code"] == "excluded_by_interface"


def test_interfaces_must_be_a_non_empty_list():
    with pytest.raises(certify.DeclarationError, match="interfaces"):
        declarations(interfaces=[])


# --- the CLI -------------------------------------------------------------------------------------------------------

def run(*args):
    return subprocess.run([sys.executable, "-m", "tierbook.cli", *args], capture_output=True, text=True,
                          env={"PYTHONPATH": str(ROOT / "src")})


def test_check_observations_reports_cells_and_refuses_mixed_versions(tmp_path):
    good, bad = tmp_path / "good.jsonl", tmp_path / "bad.jsonl"
    write(many("student", 3, version="v1"), good)
    write(many("student", 3, version="v1") + [versioned(obs("q", "student", "rejected"), "v2")], bad)
    ok = run("check-observations", str(good))
    assert ok.returncode == 0 and "student\tv1\taccepted=3" in ok.stdout
    no = run("check-observations", str(bad))
    assert no.returncode == 2 and "2 versions" in no.stderr


def test_ingest_stamps_a_declared_version(tmp_path):
    calls, out = tmp_path / "calls.jsonl", tmp_path / "obs.jsonl"
    calls.write_text(json.dumps({"item": "a", "task_type": T, "arm": "student", "response": {
        "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}]}}) + "\n")
    r = run("ingest", "--calls", str(calls), "--out", str(out), "--arm-version", "student=sha256:abc")
    assert r.returncode == 0, r.stderr
    assert read(out)[0].arm_version == "sha256:abc"
    assert "arm_version declared at ingest" in read(out)[0].source
    assert run("ingest", "--calls", str(calls), "--out", str(out), "--arm-version", "student").returncode == 2
    assert run("ingest", "--calls", str(calls), "--out", str(out), "--arm-version", "studnet=v1").returncode == 2
    assert run("ingest", "--calls", str(calls), "--out", str(out), "--arm-version", "student=a",
               "--arm-version", "student=b").returncode == 2
    assert run("ingest", "--calls", str(calls), "--out", str(out), "--append",
               "--arm-version", "student=other").returncode == 2


def test_format_4_is_written_only_for_an_artifact_and_an_older_format_may_not_carry_it(tmp_path):
    a = dataclasses.replace(obs("x", "student", "accepted"), arm_artifact="perigraph/2/artifact/" + "a" * 24)
    p = tmp_path / "o.jsonl"
    write([a], p)
    assert json.loads(p.read_text())["format"] == 4 and read(p) == [a]
    row = {"format": 3, "item": "x", "task_type": T, "arm": "student", "outcome": "accepted", "arm_artifact": "a"}
    with pytest.raises(EvidenceError, match="format 4"):
        Observation.from_row(row)


# --- harness binding -----------------------------------------------------------------------------------------------

def harnessed(o: Observation, h: str) -> Observation:
    return dataclasses.replace(o, arm_harness=h)


def test_format_5_is_written_only_for_a_harness_and_an_older_format_may_not_carry_it(tmp_path):
    a = harnessed(obs("x", "student", "accepted"), "perigraph/3/harness/" + "b" * 24)
    p = tmp_path / "o.jsonl"
    write([a, obs("y", "student", "accepted")], p)
    assert [json.loads(line)["format"] for line in p.read_text().splitlines()] == [5, 1]
    assert read(p)[0] == a
    row = {"format": 4, "item": "x", "task_type": T, "arm": "student", "outcome": "accepted", "arm_harness": "h"}
    with pytest.raises(EvidenceError, match="format 5"):
        Observation.from_row(row)
    with pytest.raises(EvidenceError, match="arm_harness"):
        harnessed(obs("x", "student", "accepted"), 3)


def test_two_harnesses_under_one_arm_are_refused_even_at_one_version(tmp_path):
    cfg, decl = candidates(tmp_path), declarations()
    rows = [harnessed(o, "h1") for o in many("student", 10, version="v1")]
    rows += [harnessed(versioned(obs("j", "student", "accepted"), "v1"), "h2")]
    with pytest.raises(EvidenceError, match="2 harnesses"):
        certify.derive(rows, cfg, decl)


def test_a_harness_on_some_rows_and_none_on_others_is_refused(tmp_path):
    cfg, decl = candidates(tmp_path), declarations()
    rows = [harnessed(o, "h1") for o in many("student", 10)] + [obs("j", "student", "accepted")]
    with pytest.raises(EvidenceError, match="<none>"):
        certify.derive(rows, cfg, decl)


def test_the_policy_names_the_harness_only_when_the_rows_do(tmp_path):
    cfg, decl = candidates(tmp_path), declarations()
    entry = certify.derive([harnessed(o, "h1") for o in many("student", 60)], cfg, decl)["task_types"][T]
    assert entry["arm_harness"] == "h1" and entry["arms"]["student"]["arm_harness"] == "h1"
    plain = certify.derive(many("student", 60), cfg, decl)["task_types"][T]
    assert "arm_harness" not in plain and "arm_harness" not in plain["arms"]["student"]


def test_a_cascade_reports_its_components_harnesses(tmp_path):
    cfg, decl = candidates(tmp_path), declarations(usd_per_attempt={"student": {"usd": 0.5, "source": "test"}})
    rows = [harnessed(o, "hs") for o in many("student", 60, score=0.9)] + many("teacher", 60, tokens=10)
    cell = certify.derive(rows, cfg, decl)["task_types"][T]["arms"]["routed"]
    assert cell["component_harnesses"] == {"student": "hs", "teacher": None}


def test_drift_refuses_fresh_rows_under_another_harness(tmp_path):
    cfg, decl = candidates(tmp_path), declarations(min_items=5)
    deployed = certify.derive([harnessed(o, "h1") for o in many("student", 60)], cfg, decl)
    with pytest.raises(EvidenceError, match="different harness"):
        certify.drift(deployed, deployed, [harnessed(o, "h2") for o in many("student", 20)], decl, cfg)
    with pytest.raises(EvidenceError, match="different harness"):
        certify.drift(deployed, deployed, many("student", 20), decl, cfg)
    certify.drift(deployed, deployed, [harnessed(o, "h1") for o in many("student", 20)], decl, cfg)


def test_drift_says_when_a_certificate_without_a_harness_meets_rows_with_one(tmp_path):
    cfg, decl = candidates(tmp_path), declarations(min_items=5)
    deployed = certify.derive(many("student", 60), cfg, decl)
    report = certify.drift(deployed, deployed, [harnessed(o, "h9") for o in many("student", 20)], decl, cfg)
    assert report["harness_unchecked"] == [{"task_type": T, "arm": "student", "fresh_harness": "h9"}]
    assert certify.drift(deployed, deployed, many("student", 20), decl, cfg)["harness_unchecked"] == []


def test_check_observations_refuses_mixed_harnesses_and_reports_an_unstated_one(tmp_path):
    same, mixed, absent = tmp_path / "same.jsonl", tmp_path / "mixed.jsonl", tmp_path / "absent.jsonl"
    write([harnessed(o, "h1") for o in many("student", 3)], same)
    write([harnessed(o, "h1") for o in many("student", 3)] + [harnessed(obs("q", "student", "rejected"), "h2")], mixed)
    write(many("student", 3), absent)
    ok = run("check-observations", str(same))
    assert ok.returncode == 0 and "harness\tstudent\th1\n" in ok.stdout
    no = run("check-observations", str(mixed))
    assert no.returncode == 2 and "2 harnesses" in no.stderr
    quiet = run("check-observations", str(absent))
    assert quiet.returncode == 0 and "harness\tstudent\t<none>\tnot stated" in quiet.stdout
