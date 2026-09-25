"""TB-107: the exporter must be told which router contract it is writing for, and the claim that a written
config matches that contract must be checked against the router's own Go parser, not assumed from a diff.

Every test below is a regression for a specific way the old, target-less `export()` failed silently: an
undeclared target guessed at the nearest shape, a shape choice invented instead of read back, or "the router
did not raise an exception" mistaken for "the file did what tierbook meant". The read-back tests are the only
ones in this suite that call out to a real Go toolchain and a real `vllm-project/semantic-router` checkout;
where either is missing they skip with the reason rather than failing, but the structural tests just above them
run unconditionally and catch the same defect shape from the Python side.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.config import load_config
from tierbook.export_vsr import ExportError, SR_TARGETS, export
from tierbook.policy import load_registry
from tierbook.table import compile_to_file

LEDGER = str(ROOT / "examples" / "ledger" / "tiers")
CANDIDATES = str(ROOT / "examples" / "ledger" / "candidates.json")
VALIDATION = str(ROOT / "examples" / "ledger" / "validation")
FAMILY = "tool-agent-user-retail"
READBACK_MAIN_GO = ROOT / "tools" / "sr_readback" / "main.go"

# Where a `vllm-project/semantic-router` checkout at (or, for "main-867155c9", after) the commit this target
# was read back against lives. Overridable per target: these checkouts are several hundred megabytes of an
# external project and live outside this repo on purpose, so a default that only holds on the machine this
# fix was built on is expected, and the env var is the escape hatch for anywhere else.
_CHECKOUT_ENV = {
    "v0.3.0": "TIERBOOK_SR_CHECKOUT_V0_3_0",
    "main-867155c9": "TIERBOOK_SR_CHECKOUT_MAIN",
}
_DEFAULT_CHECKOUT = {
    "v0.3.0": "/Users/akazawt/tmp/tb-wt-export-sr/sr-v030",
    "main-867155c9": "/Users/akazawt/tmp/tb-wt-export-sr/sr-main",
}


def _module_dir(target: str) -> Path | None:
    """The directory holding the `go.mod` that declares `pkg/config`, or None if no checkout is configured."""
    env = os.environ.get(_CHECKOUT_ENV[target])
    root = Path(env) if env else Path(_DEFAULT_CHECKOUT[target])
    mod_dir = root / "src" / "semantic-router"
    return mod_dir if (mod_dir / "go.mod").is_file() else None


def _go_available() -> bool:
    return shutil.which("go") is not None


def _skip_reason(target: str) -> str | None:
    if not _go_available():
        return "go toolchain not found on PATH; TB-107's read-back check needs the router's own Go parser"
    if _module_dir(target) is None:
        return (f"no semantic-router checkout configured for target {target!r}; set "
                f"{_CHECKOUT_ENV[target]}=/path/to/checkout (containing src/semantic-router/go.mod) at or "
                f"after commit {SR_TARGETS[target].sr_commit}")
    return None


def _read_back(target: str, config_path: Path) -> dict:
    """Parse `config_path` with the real router Go config package for `target`. Not a schema check: this runs
    the same `config.Parse` the router binary calls at start-up, from inside that checkout's own module so its
    internal `replace` directives apply, and reports what it actually saw -- including a refusal, which is a
    successful run of this helper, not a failure of it.
    """
    mod_dir = _module_dir(target)
    assert mod_dir is not None
    env = dict(os.environ)
    env.setdefault("GOPROXY", "direct")  # the module proxy is unreachable in some sandboxes; VCS-direct is not
    env.setdefault("GOSUMDB", "off")
    got = subprocess.run(["go", "run", str(READBACK_MAIN_GO), str(config_path)],
                         cwd=mod_dir, capture_output=True, text=True, env=env, timeout=240)
    assert got.returncode == 0, (
        f"sr_readback itself failed to run for target {target!r} (this is a harness problem, not a config "
        f"problem):\nstdout: {got.stdout}\nstderr: {got.stderr}")
    return json.loads(got.stdout)


def _compiled_table(tmp_path: Path) -> dict:
    return compile_to_file(load_registry(LEDGER), {FAMILY: "api-strong-a"}, tmp_path / "t.json",
                           margin=0.25, today="2026-08-30", validations=VALIDATION)


def _export(tmp_path: Path, target: str):
    cfg = load_config(CANDIDATES)
    table = _compiled_table(tmp_path)
    return export(table, cfg, signal_for_family={FAMILY: "retail"}, default_model="api-strong-a", target=target)


# --- refusal of an undeclared target ---------------------------------------------------------------------


def test_an_undeclared_target_is_refused(tmp_path):
    cfg = load_config(CANDIDATES)
    table = _compiled_table(tmp_path)
    with pytest.raises(ExportError, match="not a router contract this exporter knows"):
        export(table, cfg, signal_for_family={FAMILY: "retail"}, default_model="api-strong-a",
               target="v0.4.0-does-not-exist")


def test_the_refusal_names_every_declared_target_rather_than_just_failing(tmp_path):
    cfg = load_config(CANDIDATES)
    table = _compiled_table(tmp_path)
    with pytest.raises(ExportError) as e:
        export(table, cfg, signal_for_family={FAMILY: "retail"}, default_model="api-strong-a", target="")
    msg = str(e.value)
    for name in SR_TARGETS:
        assert repr(name) in msg, msg


def test_target_has_no_default_and_must_be_named(tmp_path):
    """A missing `target` is a `TypeError` from the keyword-only signature, not a silently guessed shape."""
    cfg = load_config(CANDIDATES)
    table = _compiled_table(tmp_path)
    with pytest.raises(TypeError):
        export(table, cfg, signal_for_family={FAMILY: "retail"}, default_model="api-strong-a")  # no target=


# --- both declared shapes, checked structurally without needing Go ---------------------------------------


@pytest.mark.parametrize("target", sorted(SR_TARGETS))
def test_each_target_emits_its_own_declared_shape(tmp_path, target):
    conf, prov = _export(tmp_path, target)
    shape = SR_TARGETS[target]

    assert conf["providers"]["defaults"] == {shape.default_model_key: "api-strong-a"}
    other_default_key = "default_model" if shape.default_model_key == "model" else "model"
    assert other_default_key not in conf["providers"]["defaults"]

    other_backend_key = "type" if shape.backend_ref_type_key == "provider" else "provider"
    for model in conf["providers"]["models"]:
        for ref in model["backend_refs"]:
            assert ref[shape.backend_ref_type_key] in ("openai", "vllm")
            assert other_backend_key not in ref, (
                f"target {target!r} must not emit {other_backend_key!r} on a backend_ref -- that is the other "
                "contract's key name for the same thing, and TB-107 is exactly this key surviving into the "
                "wrong contract's config")

    has_quality = any("quality_score" in card for card in conf["routing"]["modelCards"])
    assert has_quality == shape.emit_quality_score

    assert prov["export_target"] == target
    assert prov["export_target_sr_commit"] == shape.sr_commit
    assert prov["export_target_identity"] == shape.identity
    # The target identity travels beside the config, per the module's own established convention for the
    # registry hash -- never inside it, because both contracts pin the router's own `version` field to the
    # literal "v0.3" and TB-107 is precisely that this string cannot carry a second meaning.
    assert "export_target" not in conf


def test_the_two_targets_disagree_on_exactly_the_three_tb_107_keys(tmp_path):
    conf_old, _ = _export(tmp_path, "v0.3.0")
    conf_new, _ = _export(tmp_path, "main-867155c9")

    assert conf_old["providers"]["defaults"] == {"default_model": "api-strong-a"}
    assert conf_new["providers"]["defaults"] == {"model": "api-strong-a"}

    old_ref = conf_old["providers"]["models"][0]["backend_refs"][0]
    new_ref = conf_new["providers"]["models"][0]["backend_refs"][0]
    assert old_ref["type"] == new_ref["provider"]  # same value, TB-107's key rename, not a value change

    assert any("quality_score" in c for c in conf_old["routing"]["modelCards"])
    assert not any("quality_score" in c for c in conf_new["routing"]["modelCards"])

    # Everything else -- decisions, signals, entrypoints, recipes -- must be identical: TB-107 is three keys,
    # not a second, uncatalogued divergence this exporter is quietly carrying.
    for key in ("routing", "entrypoints", "recipes", "listeners", "global"):
        old_val, new_val = json.dumps(conf_old[key], sort_keys=True), json.dumps(conf_new[key], sort_keys=True)
        if key == "routing":
            # modelCards is the one part of routing that legitimately differs (quality_score); compare the
            # rest of routing on its own.
            for sub in ("strategy", "signals", "decisions"):
                assert conf_old["routing"][sub] == conf_new["routing"][sub], sub
        else:
            assert old_val == new_val, key


# --- read back with the real router Go config package ----------------------------------------------------


@pytest.mark.parametrize("target", sorted(SR_TARGETS))
def test_the_real_router_parses_its_own_target_and_keeps_the_values_tierbook_meant(tmp_path, target):
    reason = _skip_reason(target)
    if reason:
        pytest.skip(reason)
    conf, _ = _export(tmp_path, target)
    out = tmp_path / "router.json"
    out.write_text(json.dumps(conf))
    got = _read_back(target, out)

    assert got["parsed"] is True, got
    # "Parses" is not the claim TB-107 broke; the router parsed the post-PR#3489 shape on the pre-PR#3489
    # router too, with the default silently empty. The values have to survive, and this is where that is
    # actually checked rather than assumed from the earlier structural test.
    assert got["default_model"] == "api-strong-a", got
    assert got["decisions"] == [
        {"name": "tierbook_tool_agent_user_retail", "model_refs": ["self-hosted-a"]}
    ], got


def test_the_wrong_shape_reproduces_both_halves_of_tb_107_on_the_real_parsers(tmp_path):
    """The failure this module exists to prevent, reproduced on purpose against the real router, not assumed.

    Feeding the pre-PR#3489 shape to the post-PR#3489 router's own parser is refused at start-up, naming the
    three deprecated keys. Feeding the post-PR#3489 shape to the pre-PR#3489 parser is accepted, but the
    default model comes back empty. This is TB-107 exactly, and it is why `target` has no default: the router
    that would hit either half of this is the one deployed against the wrong export.
    """
    old_reason, new_reason = _skip_reason("v0.3.0"), _skip_reason("main-867155c9")
    if old_reason or new_reason:
        pytest.skip(old_reason or new_reason)

    conf_old, _ = _export(tmp_path, "v0.3.0")
    conf_new, _ = _export(tmp_path, "main-867155c9")
    old_path, new_path = tmp_path / "old.json", tmp_path / "new.json"
    old_path.write_text(json.dumps(conf_old))
    new_path.write_text(json.dumps(conf_new))

    refused = _read_back("main-867155c9", old_path)
    assert refused["parsed"] is False, refused
    assert "providers.defaults.default_model" in refused["error"], refused
    assert "backend_refs[0].type" in refused["error"], refused
    assert "quality_score" in refused["error"], refused

    silently_emptied = _read_back("v0.3.0", new_path)
    assert silently_emptied["parsed"] is True, silently_emptied
    assert silently_emptied["default_model"] == "", silently_emptied
    # The decisions survive even in the broken pairing -- only the top-level default is TB-107's casualty,
    # because a decision's modelRefs never went through the renamed key.
    assert silently_emptied["decisions"] == [
        {"name": "tierbook_tool_agent_user_retail", "model_refs": ["self-hosted-a"]}
    ], silently_emptied
