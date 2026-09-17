"""Tests for the one structure the ledger says replaces six separate requirements.

Each of those six was a number stored without the argument that gives it meaning. The refusals here are what makes the
omission a failure rather than an absence, and the sharpest of them is the register: moving an internal direction moves
the words a model uses about its own competence and moves 15% of its answers, so a mechanism that could register that
as a lever on output quality would act on a 15% effect as though it were the 59% reported for a different claim.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import quantity as qt  # noqa: E402
from tierbook.evidence import elicitation_from_template  # noqa: E402
from tierbook.judge import WeightDigest  # noqa: E402
from tierbook.spend import SignalPrice, Spend  # noqa: E402

TERSE = elicitation_from_template("terse", "Answer with one letter.")
EXPLAIN = elicitation_from_template("explaining", "Think step by step, then answer with one letter.")
DIG = WeightDigest(hex="a" * 64)
OTHER = WeightDigest(hex="b" * 64)


def price(passes=1):
    return SignalPrice(passes=passes, per_pass=Spend(prefill=0.109, generation=0.0, unit="gpu_seconds"))


def validity(**kw):
    base = dict(calibrated_for=TERSE, fresh_for_days=30.0)
    base.update(kw)
    return qt.Validity(**base)


def q(**kw):
    base = dict(name="prefill_entropy", kind="scalar", availability="after_prefill",
                register="passive_observation", price=price(), measured_on=DIG,
                elicitation=TERSE, validity=validity(), readout_version="r1")
    base.update(kw)
    return qt.Quantity(**base)


# --- the closed vocabularies, and what each closes -------------------------------------------------------------------

@pytest.mark.parametrize("field,bad", [("kind", "number-ish"), ("availability", "layer_22"),
                                       ("register", "sort-of-passive")])
def test_an_open_ended_value_is_refused_for_each_axis(field, bad):
    with pytest.raises(qt.Inadmissible, match="is not one of"):
        q(**{field: bad})


def test_a_layer_number_is_refused_as_an_availability_by_name():
    """It is provider-specific detail below this axis, and a mechanism keyed on it would refuse a quantity from a model
    of different depth for no reason that matters."""
    with pytest.raises(qt.Inadmissible, match="A layer number is not an availability"):
        q(availability="layer_22")


def test_a_quantity_may_not_be_registered_as_a_control_action():
    """The factor-of-four refusal: registering a 15% effect there would have it acted on as though it were 59%."""
    with pytest.raises(qt.Inadmissible, match="may not be registered as a control action"):
        q(register="control_action", price=price(2), availability="during_compute")


# --- the register and the price are checked against each other ------------------------------------------------------

def test_a_passive_observation_that_costs_an_extra_pass_is_an_active_probe():
    """The register is what a caller checks before deciding it is free, so the cheaper label on a costlier thing is the
    one mislabelling that matters."""
    with pytest.raises(qt.Inadmissible, match="wearing the cheaper register"):
        q(register="passive_observation", price=price(2))


def test_an_active_probe_that_costs_nothing_extra_is_a_passive_observation():
    """Calling it a probe would have it declined on a budget it does not consume."""
    with pytest.raises(qt.Inadmissible, match="it is a passive observation"):
        q(register="active_probe", price=price(1), availability="during_compute")


def test_a_probe_that_really_costs_an_extra_pass_is_admitted():
    assert q(register="active_probe", price=price(2), availability="during_compute").is_free is False


# --- the availability axis is ordered, and the order is what the predicate reads --------------------------------------

def test_the_order_is_the_requests_order():
    """DEFECT the first version had: `during_compute` was listed after `after_prefill`, and the predicate below then
    excluded it -- reporting the one quantity this study is about, a hidden-state readout taken during the prefill
    computation, as unusable by the gate it was built for."""
    assert qt.AVAILABILITY.index("during_compute") < qt.AVAILABILITY.index("after_prefill")
    assert qt.AVAILABILITY[-1] == "after_generation"


@pytest.mark.parametrize("availability,usable", [("before_prefill", True), ("during_compute", True),
                                                 ("after_prefill", True), ("after_generation", False)])
def test_everything_before_generation_can_inform_a_gate(availability, usable):
    kw = dict(availability=availability)
    if availability == "during_compute":
        kw.update(register="active_probe", price=price(2))
    assert q(**kw).usable_before_generating() is usable


def test_the_predicate_is_derived_from_the_axis_rather_than_a_hand_written_list():
    """A list of the good values can be left silently wrong about a stage added between the existing ones, which is
    exactly how the first version went wrong."""
    import inspect
    src = inspect.getsource(qt.Quantity.usable_before_generating)
    assert "AVAILABILITY.index" in src


# --- provenance and validity ------------------------------------------------------------------------------------------

def test_the_model_must_be_a_digest_not_a_name():
    """Two models agreeing on every declarable field had probe amplitudes a factor of four apart."""
    with pytest.raises(qt.Inadmissible, match="not a WeightDigest"):
        q(measured_on="Qwen3.8-9B-Distill")


def test_the_prompt_condition_must_be_an_elicitation():
    with pytest.raises(qt.Inadmissible, match="part of what was measured"):
        q(elicitation="terse")


def test_a_calibration_for_a_different_condition_is_refused():
    """A quantity fitted in one condition does not transfer to another by recalibration -- it is about different items,
    so the calibration does not describe this quantity at all."""
    with pytest.raises(qt.Inadmissible, match="does not transfer to the other by recalibration"):
        q(elicitation=TERSE, validity=validity(calibrated_for=EXPLAIN))


def test_a_validity_calibrated_for_a_bare_label_is_refused():
    with pytest.raises(qt.Inadmissible, match="two templates both called"):
        qt.Validity(calibrated_for="terse", fresh_for_days=30.0)


def test_a_calibration_that_was_never_fresh_is_refused():
    """A quantity with no freshness window is one nothing may condition on, and that is expressed by not declaring it
    rather than by declaring it stale."""
    for bad in (0.0, -1.0):
        with pytest.raises(qt.Inadmissible, match="never valid"):
            validity(fresh_for_days=bad)


def test_a_missing_readout_version_is_refused():
    """The same model and the same prompt with a changed readout give a different number under one name."""
    with pytest.raises(qt.Inadmissible, match="readout_version is empty"):
        q(readout_version="")


def test_an_unnamed_quantity_is_refused():
    with pytest.raises(qt.Inadmissible, match="cannot be referred to by a policy"):
        q(name="")


# --- what a gate may actually use -------------------------------------------------------------------------------------

def test_the_three_rejections_are_separate_because_they_send_a_caller_to_different_places():
    wrong_model = q(name="a", measured_on=OTHER)
    wrong_condition = q(name="b", elicitation=EXPLAIN, validity=validity(calibrated_for=EXPLAIN))
    too_late = q(name="c", availability="after_generation")
    good = q(name="d")
    usable = qt.admissible_for_a_gate([wrong_model, wrong_condition, too_late, good],
                                      elicitation=TERSE, served=DIG)
    assert [x.name for x in usable] == ["d"]


def test_no_admissible_quantity_is_an_answer_rather_than_an_error():
    """It means the gate has nothing to decide with, which a caller acts on."""
    assert qt.admissible_for_a_gate([q(availability="after_generation")], elicitation=TERSE, served=DIG) == []


def test_it_prints_enough_to_tell_two_readouts_of_one_name_apart():
    text = str(q(readout_version="r2"))
    assert "prefill_entropy/r2" in text and "after_prefill" in text and "free" in text


# --- the door ---------------------------------------------------------------------------------------------------------

def _snapshot(d):
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text('{"model_type": "x"}')
    (d / "model.safetensors").write_bytes(b"\0" * 1000)
    return d


def _run(tmp_path, capsys, quantities):
    from tierbook import cli
    served = _snapshot(tmp_path / "m")
    tmpl = tmp_path / "t.txt"
    tmpl.write_text("Answer with one letter.")
    argv = ["admissible-quantities", "--served", str(served), "--elicitation-name", "terse",
            "--elicitation-template", str(tmpl)]
    for spec in quantities:
        argv += ["--quantity", spec]
    code = cli.main(argv)
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def test_the_door_reports_which_are_usable(tmp_path, capsys):
    code, text = _run(tmp_path, capsys, ["prefill_entropy:scalar:after_prefill:passive_observation:1:30:r1",
                                         "jlens:vector:during_compute:active_probe:2:30:r1",
                                         "answer_length:scalar:after_generation:passive_observation:1:30:r1"])
    assert code == 0
    assert "2 of 3 quantities are admissible" in text
    assert "not usable: answer_length" in text


def test_the_door_exits_two_when_the_gate_has_nothing(tmp_path, capsys):
    """Nothing is malformed and the gate cannot decide, which is a different problem from a declaration that could not
    be read -- so a different exit code from the 1 that gets."""
    code, text = _run(tmp_path, capsys, ["answer_length:scalar:after_generation:passive_observation:1:30:r1"])
    assert code == 2
    assert "0 of 1" in text


@pytest.mark.parametrize("spec,expect", [
    ("jlens:vector:during_compute:active_probe:1:30:r1", "it is a passive observation"),
    ("jlens:vector:layer_22:active_probe:2:30:r1", "A layer number is not an availability"),
    ("steer:vector:during_compute:control_action:2:30:r1", "may not be registered as a control action"),
    ("short:spec", "NAME:KIND"),
])
def test_the_door_refuses_a_bad_declaration_with_a_readable_sentence(tmp_path, capsys, spec, expect):
    code, text = _run(tmp_path, capsys, [spec])
    assert code == 1, text
    assert expect in text
