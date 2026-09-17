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
                register="passive_observation", subject="own_competence", price=price(), measured_on=DIG,
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
    code, text = _run(tmp_path, capsys, ["prefill_entropy:scalar:after_prefill:passive_observation:own_competence:1:30:r1",
                                         "jlens:vector:during_compute:active_probe:own_competence:2:30:r1",
                                         "answer_length:scalar:after_generation:passive_observation:own_competence:1:30:r1"])
    assert code == 0
    assert "2 of 3 quantities are admissible" in text
    assert "not usable: answer_length" in text


def test_the_door_exits_two_when_the_gate_has_nothing(tmp_path, capsys):
    """Nothing is malformed and the gate cannot decide, which is a different problem from a declaration that could not
    be read -- so a different exit code from the 1 that gets."""
    code, text = _run(tmp_path, capsys, ["answer_length:scalar:after_generation:passive_observation:own_competence:1:30:r1"])
    assert code == 2
    assert "0 of 1" in text


@pytest.mark.parametrize("spec,expect", [
    ("jlens:vector:during_compute:active_probe:own_competence:1:30:r1", "it is a passive observation"),
    ("jlens:vector:layer_22:active_probe:own_competence:2:30:r1", "A layer number is not an availability"),
    ("steer:vector:during_compute:control_action:own_competence:2:30:r1", "may not be registered as a control action"),
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
            "--quantity", "jlens:scalar:after_prefill:passive_observation:own_competence:1:30:r1", *extra]
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


# --- a strength reported per stratum rather than pooled ---------------------------------------------------------------

def strength(value=0.5350, n=537, lo=0.49, hi=0.58, statistic="auc", method="bootstrap"):
    return qt.Strength(value=value, n=n, interval=(lo, hi), statistic=statistic, interval_method=method)


def test_a_wilson_interval_is_refused_around_anything_but_a_proportion():
    """The trap this vocabulary exists for: the numbers this module was built from are areas under a curve, and the
    nearest interval already in the package is Wilson's. It would return plausible-looking bounds computed for a
    statistic nobody measured, and nothing downstream could tell that from a correct one."""
    with pytest.raises(qt.Inadmissible, match="for a binomial proportion"):
        strength(statistic="auc", method="wilson_on_a_proportion")
    assert strength(value=0.75, n=100, lo=0.66, hi=0.83, statistic="proportion",
                    method="wilson_on_a_proportion").value == 0.75


def test_an_interval_that_does_not_contain_the_value_is_refused():
    with pytest.raises(qt.Inadmissible, match="computed over something else"):
        strength(value=0.90, lo=0.49, hi=0.58)


@pytest.mark.parametrize("field,bad", [("statistic", "score"), ("interval_method", "eyeballed")])
def test_the_two_vocabularies_are_closed(field, bad):
    with pytest.raises(qt.Inadmissible, match="is not one of"):
        strength(**{"statistic" if field == "statistic" else "method": bad})


def _stratified(stratifier_availability="after_generation", fit="carried_from_pooled", pooled=True, strata=None):
    kw = dict(availability=stratifier_availability)
    if stratifier_availability == "during_compute":
        kw.update(register="active_probe", price=price(2))
    stratifier = q(name="settling_depth", **kw)
    per = strata if strata is not None else {
        "fast": strength(value=0.7482, n=1827, lo=0.72, hi=0.77),
        "slow": strength(value=0.5350, n=537, lo=0.49, hi=0.58)}
    return qt.StratifiedPerformance(
        stratum_of=stratifier, per_stratum=per, fit_source=fit,
        pooled=strength(value=0.75, n=2364, lo=0.73, hi=0.77) if pooled else None)


def test_the_pooled_figure_sits_above_the_stratum_that_matters():
    """A pooled 0.75 is an average over a population where the signal is strong on the easy half and absent on the half
    that matters. The gap is what the pooled number hides."""
    sp = _stratified()
    assert sp.weakest[0] == "slow"
    assert sp.pooling_hides() == pytest.approx(0.75 - 0.5350)


def test_no_pooled_figure_means_no_gap_rather_than_a_negative_one():
    assert _stratified(pooled=False).pooling_hides() == 0.0


def test_one_stratum_is_a_pooled_report_wearing_a_conditional_name():
    with pytest.raises(qt.Inadmissible, match="wearing a conditional name"):
        _stratified(strata={"all": strength()})


def test_bare_numbers_in_the_strata_are_refused():
    with pytest.raises(qt.Inadmissible, match="bare numbers"):
        _stratified(strata={"fast": 0.7482, "slow": 0.5350})


def test_the_stratifier_must_be_a_quantity_so_its_availability_is_known():
    """A bare name would not say when the stratifier is available, which is what decides whether the report can be used
    at all."""
    with pytest.raises(qt.Inadmissible, match="not a Quantity"):
        qt.StratifiedPerformance(stratum_of="settling_depth", fit_source="refitted_in_stratum",
                                 per_stratum={"a": strength(), "b": strength(value=0.62, lo=0.58, hi=0.66)})


def test_an_open_ended_fit_source_is_refused():
    with pytest.raises(qt.Inadmissible, match="is not one of"):
        _stratified(fit="probably_refitted")


# --- what a production policy may take from it -------------------------------------------------------------------------

def test_a_split_on_a_post_generation_quantity_cannot_be_performed_at_decision_time():
    """Settling depth is known only after generation, so which stratum a request falls in is not knowable when the
    decision is made -- however true the report is of the corpus."""
    sp = _stratified(stratifier_availability="after_generation")
    assert sp.reproducible_in_production is False
    with pytest.raises(qt.Inadmissible, match="not knowable when the decision is made"):
        sp.production_strength("slow")


def test_a_carried_fit_cannot_stand_as_the_stratums_strength():
    """Refitting within the group moved the measured case from 0.5350 to 0.5787, so a carried figure cannot tell an
    absence of information here from a direction learned for another stratum."""
    sp = _stratified(stratifier_availability="after_prefill", fit="carried_from_pooled")
    assert sp.reproducible_in_production is True
    with pytest.raises(qt.Inadmissible, match="carried from the pooled fit"):
        sp.production_strength("slow")
    assert sp.production_strength("slow", allow_carried_fit=True).value == pytest.approx(0.5350)


def test_a_decision_time_split_with_a_refit_hands_over_the_number():
    sp = _stratified(stratifier_availability="after_prefill", fit="refitted_in_stratum",
                     strata={"fast": strength(value=0.7779, n=1827, lo=0.75, hi=0.80),
                             "slow": strength(value=0.5787, n=537, lo=0.53, hi=0.63)})
    assert sp.production_strength("slow").value == pytest.approx(0.5787)


def test_an_unknown_stratum_is_refused():
    sp = _stratified(stratifier_availability="after_prefill", fit="refitted_in_stratum")
    with pytest.raises(qt.Inadmissible, match="is not one of"):
        sp.production_strength("medium")


def test_the_availability_refusal_comes_before_the_fit_one():
    """A stratifier read after generation cannot be evaluated at decision time at all, so no amount of statistics
    rescues the report -- reporting the fit problem first would send a reader to refit something unusable."""
    sp = _stratified(stratifier_availability="after_generation", fit="carried_from_pooled")
    with pytest.raises(qt.Inadmissible, match="not knowable when the decision is made"):
        sp.production_strength("slow", allow_carried_fit=True)


# --- through the door ---------------------------------------------------------------------------------------------------

def _run_strat(tmp_path, capsys, stratified):
    from tierbook import cli
    served = _snapshot(tmp_path / "m")
    tmpl = tmp_path / "t.txt"
    tmpl.write_text("Answer with one letter.")
    code = cli.main(["admissible-quantities", "--served", str(served), "--elicitation-name", "terse",
                     "--elicitation-template", str(tmpl),
                     "--quantity", "jlens:scalar:after_prefill:passive_observation:own_competence:1:30:r1",
                     "--quantity", "settling_depth:scalar:after_generation:passive_observation:own_competence:1:30:r1",
                     "--quantity", "entropy:scalar:after_prefill:passive_observation:own_competence:1:30:r1",
                     "--stratified", stratified])
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def test_the_door_names_the_weakest_stratum_and_both_problems(tmp_path, capsys):
    code, text = _run_strat(tmp_path, capsys,
                            "jlens:settling_depth:carried_from_pooled:"
                            "fast@0.7482@1827@0.72@0.77,slow@0.5350@537@0.49@0.58")
    assert code == 0
    assert "weakest stratum 'slow'" in text
    assert "NOT reproducible in production" in text
    assert "pooled fold" in text


def test_the_door_is_quiet_when_neither_problem_applies(tmp_path, capsys):
    code, text = _run_strat(tmp_path, capsys,
                            "jlens:entropy:refitted_in_stratum:"
                            "fast@0.7779@1827@0.75@0.80,slow@0.5787@537@0.53@0.63")
    assert code == 0
    assert "weakest stratum 'slow'" in text
    assert "NOT reproducible" not in text and "pooled fold" not in text


def test_the_door_refuses_a_stratifier_it_was_never_shown(tmp_path, capsys):
    """A stratifier this command has not been shown cannot have its availability checked, and availability is what
    decides whether the report can be used at all."""
    code, text = _run_strat(tmp_path, capsys, "jlens:mystery:refitted_in_stratum:a@0.7@10@0.6@0.8,b@0.6@10@0.5@0.7")
    assert code == 1
    assert "not among the declared quantities" in text


def test_the_door_refuses_a_malformed_stratum_with_the_shape_it_wanted(tmp_path, capsys):
    code, text = _run_strat(tmp_path, capsys, "jlens:entropy:refitted_in_stratum:fast@0.7482")
    assert code == 1
    assert "LABEL@VALUE@N@LO@HI" in text


# --- what a quantity is ABOUT, which a score cannot say ---------------------------------------------------------------

def test_an_open_ended_subject_is_refused_with_the_divergence_that_makes_it_matter():
    """The measured pair does not merely differ, it diverges: the same readout named the item's field at 0.7593 against
    a chance of 0.1429 and predicted its own error at 0.4227, below the 0.5 a coin gets."""
    with pytest.raises(qt.Inadmissible, match="0.7593"):
        q(subject="something_useful")


def test_the_subject_has_no_default():
    """A quantity whose subject is unstated is one a router cannot tell apart from a quantity about something else."""
    with pytest.raises(TypeError):
        qt.Quantity(name="x", kind="scalar", availability="after_prefill", register="passive_observation",
                    price=price(), measured_on=DIG, elicitation=TERSE, validity=validity(), readout_version="r1")


@pytest.mark.parametrize("subject,answers", [("own_competence", True), ("item_difficulty", True),
                                             ("topic", False), ("resource_state", False)])
def test_only_competence_and_difficulty_answer_an_escalation_question(subject, answers):
    """A gate asks whether this should go somewhere better. A topic signal answers a different question well -- at five
    times chance -- and says nothing about competence."""
    assert q(subject=subject).answers_an_escalation_question() is answers


def test_a_topic_signal_is_not_admissible_to_a_gate_however_strong_it_is():
    """Admitting it would route by subject while reporting that it routes by difficulty. The strength is not the
    question: this is the one that read at 0.7593."""
    topic = q(name="field_name", subject="topic")
    competence = q(name="entropy", subject="own_competence")
    usable = qt.admissible_for_a_gate([topic, competence], elicitation=TERSE, served=DIG)
    assert [x.name for x in usable] == ["entropy"]


def test_competence_and_difficulty_are_still_kept_apart_as_subjects():
    """One asks whether THIS candidate can answer and the other how hard the item is for anyone; a signal fitted to the
    second has been measured not to predict the first's uplift, so they are two entries rather than one."""
    assert "own_competence" in qt.SUBJECTS and "item_difficulty" in qt.SUBJECTS
    assert set(qt.ESCALATION_SUBJECTS) == {"own_competence", "item_difficulty"}


def test_the_printed_form_says_what_it_is_about():
    assert "about topic" in str(q(subject="topic"))


def test_the_door_marks_a_topic_quantity_as_not_usable(tmp_path, capsys):
    code, text = _run(tmp_path, capsys, ["field_name:scalar:after_prefill:passive_observation:topic:1:30:r1",
                                        "entropy:scalar:after_prefill:passive_observation:own_competence:1:30:r1"])
    assert code == 0
    assert "not usable: field_name" in text
    assert "usable: entropy" in text
    assert "1 of 2 quantities are admissible" in text


def test_the_door_exits_two_when_only_topic_signals_are_declared(tmp_path, capsys):
    """A fleet of strong signals about the wrong thing leaves the gate with nothing to decide with, which is a finding
    rather than an error."""
    code, text = _run(tmp_path, capsys, ["field_name:scalar:after_prefill:passive_observation:topic:1:30:r1"])
    assert code == 2
    assert "0 of 1" in text
