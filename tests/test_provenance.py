"""Provenance and consulted sets only subtract: an arm is excluded from selection when its held-out items appear in a
set it was trained on or consulted, when its observed version is not its provenance's, or when a required arm's
observed version is not the required one; a citation that does not match its digest is refused at load time.

Written against `tierbook.provenance` and `certify.derive`. The stub trainer below uses only the standard library:
any trainer that writes a manifest and a provenance file passes through the same door.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from tierbook import certify  # noqa: E402
from tierbook import config as cfgmod  # noqa: E402
from tierbook.evidence import EvidenceError  # noqa: E402
from tierbook.provenance import file_sha256, load_manifest  # noqa: E402

from test_cascade_arms import SALT, FRACTION, T, declarations, obs  # noqa: E402


def manifest(tmp_path, name, items):
    p = tmp_path / f"{name}.jsonl"
    rows = [{"item": i, "content_sha256": hashlib.sha256(i.encode()).hexdigest()} for i in items]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p, file_sha256(p)


def stub_trainer(tmp_path, trained_items, *, version="v1", requires=()):
    """A majority-class 'trainer': it only writes what the contract asks for."""
    mpath, digest = manifest(tmp_path, "trained", trained_items)
    prov = {"format": 1, "arm": "student", "arm_version": version,
            "trained_on": [{"set": "trained", "manifest": mpath.name, "sha256": digest}],
            "requires": [{"arm": a, "arm_version": v} for a, v in requires],
            "trainer": {"name": "majority-class", "anything": [1, 2, 3]}}
    path = tmp_path / "student.provenance.json"
    path.write_text(json.dumps(prov))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def config(tmp_path, prov=None, consulted=None):
    student = {"deployment": "self_hosted", "hourly_usd": 0.2,
               "endpoint": {"base_url": "http://student/v1", "model": "student"}}
    if prov is not None:
        student["arm_provenance"] = {"path": prov[0].name, "sha256": prov[1]}
    if consulted is not None:
        student["consulted"] = consulted
    c = {"student": student,
         "teacher": {"deployment": "api", "endpoint": {"base_url": "http://teacher/v1", "model": "teacher"},
                     "price_per_mtok": {"fresh_in": 10.0, "cached_in": 0.0, "out": 0.0}}}
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps({"config_format": 2, "candidates": c, "families": {}}))
    return cfgmod.load_config(p)


def rows(n=60, version="v1", arm="student"):
    return [dataclasses.replace(obs(f"i{k}", arm, "accepted"), arm_version=version) for k in range(n)]


def held_out(n=60):
    return [f"i{k}" for k in range(n) if certify.partition_of(f"i{k}", SALT, FRACTION) == "held_out"]


def test_a_clean_provenance_does_not_change_the_choice(tmp_path):
    cfg = config(tmp_path, stub_trainer(tmp_path, ["train-1", "train-2"]))
    entry = certify.derive(rows(), cfg, declarations())["task_types"][T]
    assert entry["arm"] == "student" and entry["status"] == certify.CERTIFIED
    assert "excluded_by_provenance" not in entry


def test_one_held_out_item_in_trained_on_excludes_the_arm_and_says_how_many(tmp_path):
    leaked = held_out()[0]
    cfg = config(tmp_path, stub_trainer(tmp_path, ["train-1", leaked]))
    entry = certify.derive(rows(), cfg, declarations())["task_types"][T]
    assert entry["arm"] != "student"
    assert entry["excluded_by_provenance"] == ["student"]
    hit = entry["arms"]["student"]["provenance"]["exclude"]["held_out_overlap"]
    assert hit == {"student:trained_on:trained": {"count": 1, "examples": [leaked]}}


def test_a_selection_item_in_trained_on_does_not_exclude_but_is_reported(tmp_path):
    sel = next(f"i{k}" for k in range(60) if certify.partition_of(f"i{k}", SALT, FRACTION) == "selection")
    cfg = config(tmp_path, stub_trainer(tmp_path, [sel]))
    entry = certify.derive(rows(), cfg, declarations())["task_types"][T]
    assert entry["arm"] == "student"
    assert entry["arms"]["student"]["provenance"]["selection_overlap"] == {"student:trained_on:trained": 1}


def test_a_consulted_set_counts_like_trained_on(tmp_path):
    mpath, digest = manifest(tmp_path, "tuning", held_out()[:2])
    cfg = config(tmp_path, consulted=[{"set": "tuning", "manifest": mpath.name, "sha256": digest}])
    entry = certify.derive(rows(), cfg, declarations())["task_types"][T]
    hit = entry["arms"]["student"]["provenance"]["exclude"]["held_out_overlap"]
    assert hit["student:consulted:tuning"]["count"] == 2


def test_overlap_is_found_by_content_when_item_ids_are_content_digests(tmp_path):
    texts = [f"text {k}" for k in range(60)]
    ids = ["sha256:" + hashlib.sha256(t.encode()).hexdigest() for t in texts]
    observations = [dataclasses.replace(obs(i, "student", "accepted"), arm_version="v1") for i in ids]
    target = next(i for i in ids if certify.partition_of(i, SALT, FRACTION) == "held_out")
    text = texts[ids.index(target)]
    p = tmp_path / "trained.jsonl"
    p.write_text(json.dumps({"item": "some-other-id", "content_sha256": hashlib.sha256(text.encode()).hexdigest()}) + "\n")
    prov = tmp_path / "student.provenance.json"
    prov.write_text(json.dumps({"format": 1, "arm": "student", "arm_version": "v1",
                                "trained_on": [{"set": "trained", "manifest": p.name, "sha256": file_sha256(p)}]}))
    cfg = config(tmp_path, (prov, hashlib.sha256(prov.read_bytes()).hexdigest()))
    entry = certify.derive(observations, cfg, declarations())["task_types"][T]
    hit = entry["arms"]["student"]["provenance"]["exclude"]["held_out_overlap"]
    assert hit["student:trained_on:trained"]["examples"] == [target]


def test_an_observed_version_other_than_the_provenances_excludes(tmp_path):
    cfg = config(tmp_path, stub_trainer(tmp_path, ["x"], version="v1"))
    entry = certify.derive(rows(version="v2"), cfg, declarations())["task_types"][T]
    assert entry["arms"]["student"]["provenance"]["exclude"]["version_mismatch"][0]["observed"] == "v2"


def test_a_requirement_on_another_arms_version_excludes_on_mismatch_only(tmp_path):
    cfg = config(tmp_path, stub_trainer(tmp_path, ["x"], requires=[("teacher", "t1")]))
    teacher_t1 = [dataclasses.replace(obs(f"i{k}", "teacher", "accepted", tokens=1000), arm_version="t1")
                  for k in range(60)]
    ok = certify.derive(rows() + teacher_t1, cfg, declarations())["task_types"][T]
    assert ok["arm"] == "student"
    teacher_t2 = [dataclasses.replace(o, arm_version="t2") for o in teacher_t1]
    bad = certify.derive(rows() + teacher_t2, cfg, declarations())["task_types"][T]
    assert bad["arms"]["student"]["provenance"]["exclude"]["requirement_mismatch"][0]["observed"] == "t2"
    alone = certify.derive(rows(), cfg, declarations())["task_types"][T]
    assert alone["arm"] == "student"
    assert {"arm": "student", "check": "requires teacher", "why": "the required arm has no fresh rows"} in \
        alone["arms"]["student"]["provenance"]["unchecked"]


def test_a_citation_that_does_not_match_its_digest_is_refused(tmp_path):
    path, _ = stub_trainer(tmp_path, ["x"])
    cfg = config(tmp_path, (path, "0" * 64))
    with pytest.raises(EvidenceError, match="sha256"):
        certify.derive(rows(), cfg, declarations())
    mpath, _ = manifest(tmp_path, "tuning", ["a"])
    cfg = config(tmp_path, consulted=[{"set": "tuning", "manifest": mpath.name, "sha256": "f" * 64}])
    with pytest.raises(EvidenceError, match="sha256"):
        certify.derive(rows(), cfg, declarations())


def test_every_citation_needs_a_digest(tmp_path):
    path, _ = stub_trainer(tmp_path, ["x"])
    with pytest.raises(cfgmod.ConfigError, match="sha256"):
        config(tmp_path, (path, None))
    mpath, _ = manifest(tmp_path, "tuning", ["a"])
    with pytest.raises(cfgmod.ConfigError, match="sha256"):
        config(tmp_path, consulted=[{"set": "tuning", "manifest": mpath.name}])


def test_renaming_an_id_in_a_cited_manifest_breaks_the_citation(tmp_path):
    leaked = held_out()[0]
    path, digest = stub_trainer(tmp_path, [leaked])
    cfg = config(tmp_path, (path, digest))
    m = tmp_path / "trained.jsonl"
    m.write_text(m.read_text().replace(leaked, "renamed"))
    with pytest.raises(EvidenceError, match="sha256"):
        certify.derive(rows(), cfg, declarations())


def test_a_nested_cascades_inner_consulted_set_counts(tmp_path):
    mpath, digest = manifest(tmp_path, "tuning", held_out()[:1])
    c = {"student": {"deployment": "self_hosted", "hourly_usd": 0.2,
                     "endpoint": {"base_url": "http://s/v1", "model": "s"}},
         "teacher": {"deployment": "self_hosted", "hourly_usd": 0.2, "endpoint": {"base_url": "http://t/v1", "model": "t"}},
         "big": {"deployment": "self_hosted", "hourly_usd": 0.2, "endpoint": {"base_url": "http://b/v1", "model": "b"}},
         "inner": {"cascade": {"primary": "teacher", "fallback": "big", "threshold": 0.5, "on_no_score": "fallback"},
                   "consulted": [{"set": "tuning", "manifest": mpath.name, "sha256": digest}]},
         "outer": {"cascade": {"primary": "student", "fallback": "inner", "threshold": 0.5, "on_no_score": "fallback"}}}
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps({"config_format": 2, "candidates": c, "families": {}}))
    cfg = cfgmod.load_config(p)
    pc = certify.provenance_check("outer", set(held_out()), set(), {}, certify._Claims(cfg), cfg)
    assert "inner:consulted:tuning" in pc["exclude"]["held_out_overlap"]


def test_manifest_digests_must_be_lowercase_hex(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_text(json.dumps({"item": "a", "content_sha256": "A" * 64}) + "\n")
    with pytest.raises(EvidenceError, match="lowercase hex"):
        load_manifest("m", p, file_sha256(p))


# --- arm_artifact: the stored files the trainer wrote, not how a server loaded them ---------------------------------

def artifact_trainer(tmp_path, artifact):
    """A trainer that names only what it holds at save time: the artifact, not the served version."""
    mpath, digest = manifest(tmp_path, "trained", ["train-1"])
    prov = {"format": 1, "arm": "student", "arm_artifact": artifact,
            "trained_on": [{"set": "trained", "manifest": mpath.name, "sha256": digest}]}
    path = tmp_path / "student.provenance.json"
    path.write_text(json.dumps(prov))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_rows(artifact, version="perigraph/2/model/" + "1" * 24, n=60):
    return [dataclasses.replace(r, arm_artifact=artifact) for r in rows(n, version=version)]


A1, A2 = "perigraph/2/artifact/" + "a" * 24, "perigraph/2/artifact/" + "b" * 24


def test_a_retrained_artifact_under_the_same_arm_name_is_excluded(tmp_path):
    """R5 -> R6: the certificate was over bytes that no longer existed. The trainer named R5's files; R6's answer."""
    cfg = config(tmp_path, artifact_trainer(tmp_path, A1))
    entry = certify.derive(artifact_rows(A2), cfg, declarations())["task_types"][T]
    assert entry["arm"] != "student"
    pv = entry["arms"]["student"]["provenance"]
    assert pv["exclude"]["artifact_mismatch"] == [{"arm": "student", "provenance": A1, "observed": A2}]


def test_a_runtime_change_does_not_break_a_claim_bound_to_the_artifact(tmp_path):
    """Phase 6 and R14: what the server ran changed (arm_version moved), the trainer's files did not. A provenance
    naming only the artifact still applies, so it neither excludes the arm nor goes unchecked."""
    cfg = config(tmp_path, artifact_trainer(tmp_path, A1))
    entry = certify.derive(artifact_rows(A1, version="perigraph/2/model/" + "9" * 24), cfg,
                           declarations())["task_types"][T]
    assert entry["arm"] == "student" and entry["status"] == certify.CERTIFIED
    pv = entry["arms"]["student"]["provenance"]
    assert not pv["exclude"] and not [u for u in pv["unchecked"] if u["check"] == "arm_artifact"]


def test_two_artifacts_under_one_arm_name_are_refused():
    mixed = artifact_rows(A1, n=4) + artifact_rows(A2, n=4)
    with pytest.raises(EvidenceError, match="2 artifacts"):
        certify.arm_artifacts(mixed)
    with pytest.raises(EvidenceError, match="2 artifacts"):
        certify.arm_artifacts(artifact_rows(A1, n=4) + rows(4))


def test_an_artifact_claim_against_rows_that_name_no_artifact_excludes_rather_than_passes(tmp_path):
    cfg = config(tmp_path, artifact_trainer(tmp_path, A1))
    entry = certify.derive(rows(), cfg, declarations())["task_types"][T]
    pv = entry["arms"]["student"]["provenance"]
    assert pv["exclude"]["artifact_mismatch"][0]["observed"] == certify.NO_VERSION
