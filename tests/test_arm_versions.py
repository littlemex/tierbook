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
    assert policy["task_types"][T]["arms"]["routed"]["arm_version"] == {"student": "s1", "teacher": "t1"}


def test_drift_refuses_fresh_rows_from_another_version(tmp_path):
    cfg, decl = candidates(tmp_path), declarations(min_items=5)
    deployed = certify.derive(many("student", 60, version="v1"), cfg, decl)
    fresh = many("student", 20, version="v2")
    with pytest.raises(EvidenceError, match="different version"):
        certify.drift(deployed, deployed, fresh, decl, cfg)
    certify.drift(deployed, deployed, many("student", 20, version="v1"), decl, cfg)


# --- interfaces ----------------------------------------------------------------------------------------------------

def test_interfaces_filter_applies_before_selection(tmp_path):
    cfg = candidates(tmp_path, {
        "student": {"deployment": "self_hosted", "hourly_usd": 0.2, "interface": "scores_options",
                    "endpoint": {"base_url": "http://student/v1", "model": "student"}},
        "teacher": {"deployment": "api", "interface": "generates",
                    "endpoint": {"base_url": "http://teacher/v1", "model": "teacher"},
                    "price_per_mtok": {"fresh_in": 10.0, "cached_in": 0.0, "out": 0.0}}})
    rows = many("student", 60) + many("teacher", 60, tokens=1000)
    open_ = certify.derive(rows, cfg, declarations())["task_types"][T]
    assert open_["arm"] == "student" and "excluded_by_interface" not in open_
    only = certify.derive(rows, cfg, declarations(interfaces=["generates"]))["task_types"][T]
    assert only["arm"] == "teacher"
    assert only["excluded_by_interface"] == ["routed", "student"]   # the cascade inherits its primary's


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
    assert run("ingest", "--calls", str(calls), "--out", str(out), "--arm-version", "student").returncode == 2
