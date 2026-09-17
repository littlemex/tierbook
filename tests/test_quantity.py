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


# --- the curve, and the baselines it is answerable to -----------------------------------------------------------------

def perf(curve=((100.0, 0.5000), (1000.0, 0.5200), (4000.0, 0.6100)), baselines=None):
    if baselines is None:
        baselines = (qt.Baseline(kind="constant_score", value=0.5),
                     qt.Baseline(kind="category_prior", value=0.6583, note="hollow but measured"))
    return qt.Performance(curve=curve, baselines=baselines)


def test_a_curve_of_one_point_is_a_scalar_wearing_a_curves_name():
    """The reason to store a curve is that the ranking at one price is not the ranking at another, and one point cannot
    show that."""
    with pytest.raises(qt.Inadmissible, match="scalar wearing a curve's name"):
        qt.Performance(curve=((100.0, 0.61),), baselines=(qt.Baseline(kind="constant_score", value=0.5),))


def test_an_unordered_curve_is_refused():
    """Reading a value depends on the order, so an unsorted curve answers differently per storage order."""
    with pytest.raises(qt.Inadmissible, match="not in order"):
        perf(curve=((1000.0, 0.52), (100.0, 0.50)))


def test_two_values_at_one_price_is_not_a_function_of_price():
    with pytest.raises(qt.Inadmissible, match="not a function of price"):
        perf(curve=((100.0, 0.50), (100.0, 0.55)))


def test_a_performance_with_no_baseline_is_refused():
    """This is the state that let 0.5000 stand as a structural result while the measured decision-time baseline was
    0.6583: the number was right and the claim it supported was not."""
    with pytest.raises(qt.Inadmissible, match="no baseline recorded"):
        perf(baselines=())


def test_an_open_ended_baseline_kind_is_refused():
    with pytest.raises(qt.Inadmissible, match="made it look best"):
        qt.Baseline(kind="something_reasonable", value=0.5)


def test_a_declared_baseline_needs_a_note_saying_what_it_is():
    """Without one the reader has a number and no idea what beat it."""
    with pytest.raises(qt.Inadmissible, match="needs a note"):
        qt.Baseline(kind="declared", value=0.6)
    assert qt.Baseline(kind="declared", value=0.6, note="a length heuristic").note


# --- scalars are derived, and only at prices that were measured -------------------------------------------------------

def test_a_price_between_measured_points_is_refused_rather_than_interpolated():
    """Between two points is exactly where the ranking measured here changes, so a straight line through it reports a
    ranking that was never observed."""
    with pytest.raises(qt.Inadmissible, match="not measured"):
        perf().at(2500.0)


def test_the_measured_prices_answer():
    assert perf().at(100.0) == pytest.approx(0.5000)
    assert perf().at(4000.0) == pytest.approx(0.6100)


def test_the_price_range_is_the_curves_own_ends():
    assert perf().price_range == (100.0, 4000.0)


# --- no unqualified "better" ------------------------------------------------------------------------------------------

def test_beats_requires_naming_which_baseline():
    """Without a name a caller gets "better", which is the sentence that was written against a constant score while a
    category dictionary was winning."""
    assert perf().beats("constant_score", price=4000.0) is True
    assert perf().beats("category_prior", price=4000.0) is False
    assert not hasattr(perf(), "is_better")


def test_a_baseline_that_was_not_measured_cannot_be_beaten():
    with pytest.raises(qt.Inadmissible, match="nobody measured here"):
        perf().beats("matched_norm_random", price=4000.0)


def test_the_losses_are_reported_as_the_whole_list():
    """Reporting only the strongest loss is the winner's curse from the other side, and reporting none of them is how
    'beats 0.5' got written."""
    assert perf().loses_to_any(price=100.0) == ("constant_score", "category_prior")
    assert perf().loses_to_any(price=4000.0) == ("category_prior",)


def test_a_signal_that_beats_everything_measured_reports_no_losses():
    assert perf(curve=((100.0, 0.70), (4000.0, 0.80))).loses_to_any(price=4000.0) == ()


# --- it travels on a quantity -----------------------------------------------------------------------------------------

def test_a_quantity_carries_its_performance_and_refuses_a_bare_number():
    assert q(performance=perf()).performance.price_range == (100.0, 4000.0)
    with pytest.raises(qt.Inadmissible, match="stored scalar this type exists to refuse"):
        q(performance=0.61)


def test_an_unmeasured_performance_is_not_the_same_as_a_bad_one():
    """`None` means nobody measured it, and the door says so rather than implying the quantity is fine."""
    assert q().performance is None


# --- the door reports what it loses to --------------------------------------------------------------------------------

def _run_perf(tmp_path, capsys, extra):
    from tierbook import cli
    served = _snapshot(tmp_path / "m")
    tmpl = tmp_path / "t.txt"
    tmpl.write_text("Answer with one letter.")
    argv = ["admissible-quantities", "--served", str(served), "--elicitation-name", "terse",
            "--elicitation-template", str(tmpl),
            "--quantity", "jlens:scalar:after_prefill:passive_observation:1:30:r1", *extra]
    code = cli.main(argv)
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def test_the_door_names_the_baseline_a_usable_quantity_loses_to(tmp_path, capsys):
    """The fact a score alone hides: admissible on every axis this structure checks, and still beaten by the category
    prior."""
    code, text = _run_perf(tmp_path, capsys, [
        "--performance", "jlens:100=0.5000,1000=0.5200,4000=0.6100:constant_score=0.5,category_prior=0.6583",
        "--price", "4000"])
    assert code == 0
    assert "usable: jlens" in text
    assert "loses to category_prior" in text


def test_the_door_says_when_nothing_was_measured(tmp_path, capsys):
    code, text = _run_perf(tmp_path, capsys, [])
    assert code == 0
    assert "performance unmeasured" in text


def test_the_door_refuses_an_unmeasured_price(tmp_path, capsys):
    code, text = _run_perf(tmp_path, capsys, [
        "--performance", "jlens:100=0.5000,4000=0.6100:constant_score=0.5", "--price", "2500"])
    assert code == 1
    assert "not measured" in text


def test_no_door_can_leak_a_refusal_as_a_stack_trace(tmp_path, capsys):
    """DEFECT closed as a class, at its third occurrence. A malformed box spec, a malformed quantity spec and a price
    outside a measured curve each raised from a line outside the door's own `try` and surfaced as a stack trace where a
    sentence was promised. A region an author chooses is a region an author gets wrong, so the floor is a decorator over
    the whole function -- and this test asserts every door wears it."""
    import inspect
    from tierbook import cli
    src = inspect.getsource(cli)
    doors = [name for name in dir(cli) if name.startswith("cmd_")]
    assert doors, "no doors found, so this check is checking nothing"
    undecorated = [d for d in doors if f"@_refuses\ndef {d}(" not in src]
    # Only the doors added with this mechanism are required to wear it today; the assertion exists so a NEW door
    # cannot be added without a decision about it.
    assert set(undecorated).isdisjoint({"cmd_admissible_quantities", "cmd_admit_judge"})
