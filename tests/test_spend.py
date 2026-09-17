"""Tests for a cost with its legs kept apart.

The measurement behind every refusal here: on the same server, reading the prompt took 0.109 s and writing the answer
took 10.42 s at the box's own median length. Priced as one number at one rate per token, those are the same thing; they
differ by a factor of about 95, and a gate's entire job is to trade one against the other.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import spend as sp  # noqa: E402
from tierbook.evidence import EvidenceError  # noqa: E402

GPU = "gpu_seconds"
PREFILL, GENERATION = 0.109, 10.42


def measured():
    """The two legs as they were measured, so the tests are about the real ratio rather than a made-up one."""
    return sp.Spend(prefill=PREFILL, generation=GENERATION, unit=GPU)


def one_prompt_read():
    return sp.Spend(prefill=PREFILL, generation=0.0, unit=GPU)


def a_generation_avoided():
    return sp.Spend(prefill=0.0, generation=GENERATION, unit=GPU)


# --- the legs, and a total nobody can contradict ---------------------------------------------------------------------

def test_the_total_is_derived_not_supplied():
    """A supplied total can disagree with the legs it claims to sum, and then two numbers describe one cost. It is also
    the field a caller reaches for when they have not thought about which leg their change touches."""
    with pytest.raises(TypeError):
        sp.Spend(prefill=0.1, generation=10.0, unit=GPU, total=10.1)
    assert measured().total == pytest.approx(PREFILL + GENERATION)


def test_the_measured_ratio_comes_out_where_the_ledger_put_it():
    """Generation is 98.96% of a request that generates, which is why the gate's own depth barely matters."""
    assert measured().generation_share == pytest.approx(0.9896, abs=5e-5)


def test_a_negative_leg_is_refused():
    """A leg that gives cost back would make a total smaller than one of its parts."""
    for kw in ({"prefill": -0.1}, {"generation": -1.0}):
        with pytest.raises(EvidenceError, match="is not a cost"):
            sp.Spend(prefill=kw.get("prefill", 0.1), generation=kw.get("generation", 1.0), unit=GPU)


def test_an_open_ended_unit_is_refused():
    with pytest.raises(EvidenceError, match="not one of"):
        sp.Spend(prefill=0.1, generation=1.0, unit="seconds-ish")


def test_a_zero_cost_has_no_generation_share_rather_than_dividing_by_zero():
    assert sp.Spend(prefill=0.0, generation=0.0, unit=GPU).generation_share == 0.0


def test_two_units_cannot_be_added():
    """The sum would be a number in no unit at all, and it would look exactly like a cost."""
    with pytest.raises(EvidenceError, match="no unit at all"):
        measured() + sp.Spend(prefill=1.0, generation=2.0, unit="tokens")


def test_adding_keeps_the_legs_apart():
    s = one_prompt_read() + a_generation_avoided()
    assert (s.prefill, s.generation) == (pytest.approx(PREFILL), pytest.approx(GENERATION))


def test_a_spend_prints_its_legs_and_never_a_currency_symbol_for_gpu_seconds():
    text = str(measured())
    assert "prefill" in text and "generation" in text and "$" not in text


# --- a saving says which leg it came from ----------------------------------------------------------------------------

def test_a_saving_that_is_all_generation_is_a_gate_working():
    """A saving of the same size that is all prefill is a shorter prompt, and those need different things done next."""
    saved = sp.avoided(measured(), one_prompt_read())
    assert saved.generation == pytest.approx(GENERATION)
    assert saved.prefill == 0.0


def test_a_saving_that_is_all_prefill_is_a_different_fact_of_the_same_size():
    before = sp.Spend(prefill=GENERATION, generation=0.0, unit=GPU)
    saved = sp.avoided(before, sp.Spend(prefill=0.0, generation=0.0, unit=GPU))
    assert saved.total == pytest.approx(sp.avoided(measured(), one_prompt_read()).total)
    assert saved.prefill > 0 and saved.generation == 0.0


def test_a_cost_that_went_up_is_not_reported_as_a_negative_saving():
    saved = sp.avoided(one_prompt_read(), measured())
    assert saved.total == 0.0


def test_subtracting_two_units_is_refused():
    with pytest.raises(EvidenceError, match="cannot subtract"):
        sp.avoided(measured(), sp.Spend(prefill=0.0, generation=0.0, unit="tokens"))


# --- what a signal costs, in passes ---------------------------------------------------------------------------------

def test_a_signal_read_from_the_prompt_the_request_reads_anyway_is_free():
    """The prompt read happens whether or not the signal is computed, so charging the signal for it prices a cost
    nobody avoids."""
    free = sp.SignalPrice(passes=1, per_pass=one_prompt_read())
    assert free.extra_passes == 0
    assert free.share_of(a_generation_avoided()) == 0.0


def test_an_intervention_needing_a_second_read_costs_the_one_percent_the_ledger_recorded():
    """DEFECT this method's default fixes: counting all passes rather than the extra ones gave 2.09%, twice the
    recorded figure, and the ledger was right -- its 1% is about the SECOND read, not both."""
    probe = sp.SignalPrice(passes=2, per_pass=one_prompt_read())
    assert probe.extra_passes == 1
    assert probe.share_of(a_generation_avoided()) == pytest.approx(0.0105, abs=5e-4)


def test_the_absolute_share_is_available_but_only_when_asked_for():
    """It answers a different question, and getting it by default would have it read as the trade."""
    probe = sp.SignalPrice(passes=2, per_pass=one_prompt_read())
    assert probe.share_of(a_generation_avoided(), marginal=False) == pytest.approx(0.0209, abs=5e-4)


def test_a_signal_costing_no_passes_is_refused():
    """Every feature measured here costs at least one read of the prompt, and recording zero would make the trade come
    out free."""
    with pytest.raises(EvidenceError, match="read from nothing"):
        sp.SignalPrice(passes=0, per_pass=one_prompt_read())


@pytest.mark.parametrize("bad", [1.5, "2", True, None])
def test_a_pass_count_that_is_not_an_integer_is_refused(bad):
    """A bool would count True as one pass silently."""
    with pytest.raises(EvidenceError, match="not an integer"):
        sp.SignalPrice(passes=bad, per_pass=one_prompt_read())


def test_a_scalar_per_pass_cost_is_refused():
    """It cannot say whether the pass costs a prompt read or a generation, and those differ by a factor of about 95."""
    with pytest.raises(EvidenceError, match="factor of about 95"):
        sp.SignalPrice(passes=2, per_pass=0.109)


def test_the_signals_total_cost_scales_with_its_passes():
    probe = sp.SignalPrice(passes=3, per_pass=one_prompt_read())
    assert probe.cost.prefill == pytest.approx(3 * PREFILL)
    assert probe.marginal_cost.prefill == pytest.approx(2 * PREFILL)


def test_a_share_of_nothing_saved_is_refused_rather_than_reported_as_expensive():
    """Returning a large number would read as 'too expensive' when the fact is that nothing was saved."""
    probe = sp.SignalPrice(passes=2, per_pass=one_prompt_read())
    with pytest.raises(EvidenceError, match="nothing was saved"):
        probe.share_of(sp.Spend(prefill=0.0, generation=0.0, unit=GPU))


def test_a_share_across_units_is_refused():
    probe = sp.SignalPrice(passes=2, per_pass=one_prompt_read())
    with pytest.raises(EvidenceError, match="not a fraction of anything"):
        probe.share_of(sp.Spend(prefill=0.0, generation=500.0, unit="tokens"))


# --- one home for the cost vocabulary --------------------------------------------------------------------------------

def test_the_comparison_code_reads_the_vocabulary_from_here_rather_than_holding_a_copy():
    """Two copies of a unit list are one edit from disagreeing about what a cost is."""
    from tierbook import counterfactual as cf
    assert cf.COST_UNITS is sp.COST_UNITS
    assert cf.format_cost is sp.format_cost
