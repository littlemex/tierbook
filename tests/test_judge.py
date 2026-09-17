"""Tests for the judge contract.

Every refusal here exists because a measurement showed the alternative admits a judge that produces a
working-looking gate on the wrong model, or on the right model behaving in a way the judge did not assume. Both
failures are invisible downstream: the gate does not error, it orders items badly and reports a number.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import judge as j  # noqa: E402

A = "a" * 64
B = "b" * 64


def dig(hex_=A):
    return j.WeightDigest(hex=hex_)


def contract(**kw):
    base = dict(judge_id="prefill-gate/0.1", weight_digest=dig())
    base.update(kw)
    return j.JudgeContract(**base)


def rate(correct=180, total=253, floor=0.20):
    return j.BaseRate(correct=correct, total=total, floor=floor)


# --- the digest, and the keys it replaces ------------------------------------------------------------------------

def test_a_digest_of_the_loaded_tensors_is_refused_by_name():
    """The mistake a careful implementer makes first: hashing the parameters in memory. It refuses a correct
    artefact on the very model it was built for, because an engine's layout is not the publisher's."""
    with pytest.raises(j.Inadmissible, match="different digest"):
        j.WeightDigest(hex=A, subject="loaded_tensors")


@pytest.mark.parametrize("bad", ["", "abc", A.upper(), "z" * 64, A[:63], A + "a"])
def test_only_a_lowercase_sha256_is_a_digest(bad):
    """A short, upper-case or non-hex value is not something this mechanism computed, and accepting one lets a
    caller pass an identifier that looks like a digest and is not."""
    with pytest.raises(j.Inadmissible, match="sha256"):
        j.WeightDigest(hex=bad)


@pytest.mark.parametrize("key", j.REFUSED_KEYS)
def test_the_insufficient_keys_cannot_be_declared_as_the_key(key):
    """Two served models agreed on every one of these and their residuals were further apart than two different
    questions within one model. A field measured to be insufficient is refused rather than deprecated."""
    with pytest.raises(j.Inadmissible, match="the KEY is the digest"):
        contract(declared={key: "whatever"})


def test_description_that_is_not_one_of_the_refused_keys_is_allowed():
    """The refusal is of those keys as identifiers, not of description in general: a judge may say what it needs in
    prose without that becoming the compatibility key."""
    c = contract(declared={"probe_layer": 18, "readout": "entropy of the vocabulary distribution"})
    assert c.declared["probe_layer"] == 18


# --- measured constants, and the digest that licenses them -------------------------------------------------------

def test_a_measured_constant_needs_a_digest_not_a_string():
    """The amplitude's optimum differed by a factor of four between two models identical in architecture, dtype and
    depth fraction, so a constant keyed on anything weaker is a number true of something else."""
    with pytest.raises(j.Inadmissible, match="not a WeightDigest"):
        j.MeasuredConstant(name="amplitude", value=0.2, measured_on="published_weights")


def test_a_constant_measured_elsewhere_cannot_be_carried():
    """Supporting a second model is a second measurement campaign, not a configuration change. A constant measured
    on other weights inside a contract for these would be exactly the silent mismatch."""
    other = j.MeasuredConstant(name="amplitude", value=0.05, measured_on=dig(B))
    with pytest.raises(j.Inadmissible, match="second measurement campaign"):
        contract(measured=(other,))


def test_a_constant_the_judge_does_not_carry_is_refused_rather_than_defaulted():
    """A default here is a number nobody measured, wearing the name of one that was."""
    c = contract(measured=(j.MeasuredConstant(name="amplitude", value=0.2, measured_on=dig()),))
    assert c.constant("amplitude") == 0.2
    with pytest.raises(j.Inadmissible, match="nobody measured"):
        c.constant("probe_layer")


# --- the base rate, which is the only check on a convention ------------------------------------------------------

def test_a_base_rate_over_no_items_is_not_a_measurement():
    with pytest.raises(j.Inadmissible, match="not a measurement"):
        j.BaseRate(correct=0, total=0, floor=0.2)


@pytest.mark.parametrize("floor", [0.0, 1.0, -0.1, 1.5])
def test_a_floor_outside_the_open_unit_interval_is_refused(floor):
    """A floor of zero admits the noise the check exists to refuse; a floor of one admits nothing."""
    with pytest.raises(j.Inadmissible, match="strictly between"):
        j.BaseRate(correct=1, total=2, floor=floor)


def test_the_measured_convention_failure_is_what_the_floor_catches():
    """The number is the one that occurred: a model matching its sibling in every declarable field, whose readout
    convention did not hold, answering 0.0899 against a ten-option floor of 0.10."""
    broken = j.BaseRate(correct=21, total=234, floor=0.20)   # 0.0897
    assert not broken.clears
    with pytest.raises(j.Inadmissible, match="ordering of noise"):
        j.admissible(contract(), served=dig(), base_rate=broken)


# --- admission ---------------------------------------------------------------------------------------------------

def test_a_matched_judge_with_a_clearing_base_rate_is_admitted():
    j.admissible(contract(), served=dig(), base_rate=rate())


def test_the_wrong_model_is_refused_with_the_reason_it_cannot_be_caught_later():
    with pytest.raises(j.Inadmissible, match="cannot be caught downstream"):
        j.admissible(contract(), served=dig(B), base_rate=rate())


def test_a_weaker_identifier_for_the_served_model_is_refused():
    """Passing a name or a shape here would reintroduce the key the digest replaced, at the one place where the
    comparison actually happens."""
    with pytest.raises(j.Inadmissible, match="weaker identifier"):
        j.admissible(contract(), served="Qwen3.8-9B-Distill", base_rate=rate())


def test_a_missing_base_rate_is_refused_rather_than_treated_as_passing():
    """Absent is not clear. A convention failure is neither declared nor measurable from the weights, so admitting
    a judge with no base rate is admitting the one failure the digest cannot see."""
    with pytest.raises(j.Inadmissible, match="only check that sees it"):
        j.admissible(contract(), served=dig(), base_rate=None)


def test_the_digest_is_checked_before_the_base_rate():
    """Ordering is deliberate: the digest is decidable from the manifest and free, the base rate costs a pass over
    the buyer's items. A run that pays for the second before failing the first has wasted the cheaper check."""
    with pytest.raises(j.Inadmissible, match="cannot be caught downstream"):
        j.admissible(contract(), served=dig(B), base_rate=None)


# --- the digest over a published snapshot -------------------------------------------------------------------------

def test_digest_of_a_snapshot_needs_both_a_config_and_weights(tmp_path):
    """A digest over weight files alone collides across two quantisations of one checkpoint; over a config alone it
    collides across two fine-tunes of one base."""
    with pytest.raises(j.Inadmissible, match="no config.json"):
        j.digest_published(tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"model_type": "x"}))
    with pytest.raises(j.Inadmissible, match="no .safetensors"):
        j.digest_published(tmp_path)


def test_the_snapshot_digest_separates_two_models_that_agree_on_every_declarable_field(tmp_path):
    """The pair this contract exists for: same architecture, same sizes, different weights. Here the file sizes
    differ, which is the cheap thing that distinguishes them and the reason the digest need not read contents."""
    one, two = tmp_path / "one", tmp_path / "two"
    cfg = json.dumps({"model_type": "qwen3_5", "hidden_size": 4096, "num_hidden_layers": 32,
                      "vocab_size": 248320, "tie_word_embeddings": False})
    for d, size in ((one, 1000), (two, 1001)):
        d.mkdir()
        (d / "config.json").write_text(cfg)
        (d / "model.safetensors").write_bytes(b"\0" * size)
    assert j.digest_published(one) != j.digest_published(two)


def test_the_snapshot_digest_is_stable_across_calls(tmp_path):
    """A digest that moved between the builder and the server would refuse every artefact, which is the failure the
    published-weights subject exists to avoid."""
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "model.safetensors").write_bytes(b"\0" * 8)
    assert j.digest_published(tmp_path) == j.digest_published(tmp_path)
    assert j.digest_published(tmp_path).subject == "published_weights"


# --- the CLI door, which is what actually runs before traffic ------------------------------------------------------

def _snapshot(d, size=1000):
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"model_type": "qwen3_5", "hidden_size": 4096}))
    (d / "model.safetensors").write_bytes(b"\0" * size)
    return d


def _admit(argv, capsys):
    """Returns (exit_code, everything printed). The exit code is what a deployment reads."""
    from tierbook import cli
    code = cli.main(["admit-judge", *argv])
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def test_a_matched_judge_is_admitted_through_the_cli(tmp_path, capsys):
    right = _snapshot(tmp_path / "right")
    code, text = _admit(["--judge-id", "prefill-gate/0.1", "--digest", j.digest_published(right).hex,
                         "--served", str(right), "--constant", "threshold=0.62",
                         "--base-rate-correct", "180", "--base-rate-total", "253"], capsys)
    assert code == 0
    assert "admitted" in text and "0.7115" in text


def test_the_wrong_model_refuses_with_exit_one(tmp_path, capsys):
    right, wrong = _snapshot(tmp_path / "right"), _snapshot(tmp_path / "wrong", size=1001)
    code, text = _admit(["--judge-id", "g", "--digest", j.digest_published(right).hex, "--served", str(wrong),
                         "--base-rate-correct", "180", "--base-rate-total", "253"], capsys)
    assert code == 1
    assert "cannot be caught downstream" in text


def test_a_chance_base_rate_refuses_with_exit_one(tmp_path, capsys):
    right = _snapshot(tmp_path / "right")
    code, text = _admit(["--judge-id", "g", "--digest", j.digest_published(right).hex, "--served", str(right),
                         "--base-rate-correct", "21", "--base-rate-total", "234"], capsys)
    assert code == 1
    assert "ordering of noise" in text


@pytest.mark.parametrize("argv,expect", [
    (["--digest", "Qwen3.8-9B-Distill"], "not a lowercase 64-character sha256"),
    (["--served", "MISSING"], "no config.json"),
    (["--constant", "threshold"], "NAME=VALUE"),
    (["--constant", "threshold=high"], "NAME=VALUE"),
    (["--judge-id", ""], "cannot be named in a decision record"),
])
def test_every_bad_input_refuses_with_a_readable_sentence(tmp_path, capsys, argv, expect):
    """DEFECT: with the snapshot read and the digest parsed outside the try, a --served holding no config.json and a
    --digest that is a model NAME both exited with a stack trace. A refusal an operator cannot read is a refusal that
    gets worked around rather than fixed."""
    right = _snapshot(tmp_path / "right")
    base = {"--judge-id": "g", "--digest": j.digest_published(right).hex, "--served": str(right)}
    for i in range(0, len(argv), 2):
        base[argv[i]] = argv[i + 1]
    if base["--served"] == "MISSING":
        base["--served"] = str(tmp_path / "nothing-here")
    flat = [x for kv in base.items() for x in kv]
    code, text = _admit([*flat, "--base-rate-correct", "180", "--base-rate-total", "253"], capsys)
    assert code == 1, text
    assert expect in text
