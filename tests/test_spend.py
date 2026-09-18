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


# --- the production path: evidence file -> cell -> run -> comparison ------------------------------------------------

def _cell(usd=None, legs=None, state=None):
    from tierbook.evidence import SOLVED
    from tierbook.outcomes import Cell
    return Cell(state=state or SOLVED, usd=usd, spend=legs)


def test_a_cell_carrying_the_split_and_a_disagreeing_total_is_refused():
    """Two numbers would then describe one cost with nothing saying which is right -- the state the derived total in
    Spend exists to prevent, reintroduced by writing them side by side."""
    with pytest.raises(EvidenceError, match="disagree"):
        _cell(usd=1.0, legs=sp.Spend(prefill=0.1, generation=10.0))


def test_a_cell_carrying_the_split_and_no_total_is_refused():
    """They are one cost seen two ways, so carrying the split and not the total says the total was never known."""
    with pytest.raises(EvidenceError, match="usd is None"):
        _cell(usd=None, legs=sp.Spend(prefill=0.1, generation=10.0))


def test_a_cell_cannot_hold_a_token_split_beside_a_dollar_scalar():
    """A token count sitting next to a dollar figure is the mismatch this package refuses elsewhere."""
    with pytest.raises(EvidenceError, match="named `usd`"):
        _cell(usd=10.1, legs=sp.Spend(prefill=0.1, generation=10.0, unit="tokens"))


def test_a_cell_with_no_split_is_fine_because_that_is_every_cell_written_before_the_field_existed():
    assert _cell(usd=0.5).spend is None


def _table(legs_for=("cheap", "dear")):
    """A two-candidate table where the named candidates carry the split and any others do not."""
    from tierbook.evidence import SOLVED, INCORRECT
    from tierbook.outcomes import OutcomeTable
    t = OutcomeTable(suite="s", manifest_digest="d" * 64)
    for item, cheap_ok in (("i1", True), ("i2", False), ("i3", True), ("i4", False),
                           ("i5", True), ("i6", False), ("i7", True), ("i8", True)):
        for tier, ok, pf, gen in (("cheap", cheap_ok, PREFILL, GENERATION), ("dear", True, PREFILL, GENERATION * 2)):
            legs = sp.Spend(prefill=pf, generation=gen) if tier in legs_for else None
            t.cells.setdefault(item, {})[tier] = _cell(usd=(pf + gen), legs=legs,
                                                       state=SOLVED if ok else INCORRECT)
    return t


def test_a_run_built_from_cells_with_the_split_carries_it_through():
    from tierbook.counterfactual import simulate
    r = simulate(_table(), lambda tb, i: ("cheap",), ["i1", "i2", "i3"], label="cheap")
    assert r.spend is not None
    assert r.spend_per_item.prefill == pytest.approx(PREFILL)
    assert r.cost_per_item == pytest.approx(r.spend_per_item.total)


def test_a_run_touching_one_cell_without_the_split_reports_none_rather_than_a_hole():
    """All or nothing: a partly-split run reports a leg total smaller than the scalar beside it, and a tuple with a
    hole in it makes every caller check every element, which the first version of anything does not."""
    from tierbook.counterfactual import simulate
    r = simulate(_table(legs_for=("dear",)), lambda tb, i: ("cheap",), ["i1", "i2"], label="cheap")
    assert r.spend is None
    assert r.spend_per_item is None


def test_a_run_that_escalates_accumulates_both_candidates_legs():
    from tierbook.counterfactual import simulate
    r = simulate(_table(), lambda tb, i: ("cheap", "dear"), ["i1", "i2"], label="cascade")
    assert r.spend_per_item.prefill == pytest.approx(2 * PREFILL)
    assert r.spend_per_item.generation == pytest.approx(GENERATION * 3)


def test_the_comparison_says_which_leg_the_saving_came_from():
    """F13's ask, end to end: a gate working and a shorter prompt are the same scalar and different facts."""
    from tierbook.counterfactual import OperatingPoint, compare, simulate
    items = ["i1", "i2", "i3", "i4", "i5", "i6", "i7", "i8"]
    cheap = simulate(_table(), lambda tb, i: ("cheap",), items, label="cheap")
    dear = simulate(_table(), lambda tb, i: ("dear",), items, label="dear")
    c = compare(cheap, dear, operating_point=OperatingPoint(kind="not_applicable"))
    assert c.saving is not None
    assert c.saving.generation == pytest.approx(GENERATION)   # cheap generates half as much
    assert c.saving.prefill == 0.0                            # both read the prompt once
    assert c.overspend.total == 0.0


def test_both_directions_are_reported_because_a_policy_can_save_one_leg_and_spend_another():
    """The gate measured here has exactly that shape: a whole generation avoided at the price of an extra prompt
    read, and reporting only the net would hide the trade the decision made."""
    from tierbook.counterfactual import OperatingPoint, compare, simulate
    items = ["i1", "i2"]
    cascade = simulate(_table(), lambda tb, i: ("cheap", "dear"), items, label="cascade")
    dear = simulate(_table(), lambda tb, i: ("dear",), items, label="dear")
    c = compare(cascade, dear, operating_point=OperatingPoint(kind="not_applicable"))
    assert c.overspend.prefill == pytest.approx(PREFILL)      # the cascade read the prompt twice
    assert c.overspend.generation == pytest.approx(GENERATION)


def test_a_comparison_of_runs_without_the_split_reports_neither_direction():
    from tierbook.counterfactual import OperatingPoint, compare, simulate
    t = _table(legs_for=())
    items = ["i1", "i2"]
    c = compare(simulate(t, lambda tb, i: ("cheap",), items, label="a"),
                simulate(t, lambda tb, i: ("dear",), items, label="b"),
                operating_point=OperatingPoint(kind="not_applicable"))
    assert c.saving is None and c.overspend is None


def _evidence(subject, items):
    from tierbook.evidence import SOLVED, Evidence
    return Evidence(path=subject,
                    header={"suite_manifest_digest": "sha256:" + "a" * 64, "subject": subject,
                            "family": "s", "trials_per_item": 1},
                    verdicts={i: (SOLVED, None) for i in items})


def test_the_loader_takes_a_split_through_the_same_parameter_as_a_total():
    """One parameter, two accepted shapes. The alternative is a second parallel dict, which is a list one caller fills
    and another has to remember to fill too -- the shape this package refuses."""
    from tierbook.outcomes import OutcomeTable
    items = ["i1", "i2"]
    legs = sp.Spend(prefill=PREFILL, generation=GENERATION)
    table = OutcomeTable.from_evidence([_evidence("cheap", items)],
                                       cost_per_item={"cheap": {"i1": legs, "i2": 0.5}})
    assert table.cells["i1"]["cheap"].spend == legs
    assert table.cells["i1"]["cheap"].usd == pytest.approx(legs.total)
    # A plain float through the same parameter still works and carries no split, which is what makes this an addition
    # rather than a migration.
    assert table.cells["i2"]["cheap"].spend is None
    assert table.cells["i2"]["cheap"].usd == 0.5


# --- the four legs the price card actually bills ---------------------------------------------------------------------------

def cached(prefill=0.010, cached_in=0.008, cache_write=0.001, generation=0.90):
    return sp.Spend(prefill=prefill, generation=generation, cached_in=cached_in, cache_write=cache_write)


def test_the_price_card_bills_four_legs_and_the_vocabulary_says_so():
    assert sp.BILLED_LEGS == ("fresh_in", "cached_in", "cache_write", "generation")


def test_the_fresh_remainder_is_derived_so_it_cannot_disagree():
    s = cached()
    assert abs(s.fresh_in - 0.001) < 1e-12
    assert s.cache_split is True and s.served_from_cache is True


def test_an_unsplit_cost_says_it_does_not_know_rather_than_reporting_zero():
    """An unrecorded split is not a zero cache rate, and every cost written before these fields is unsplit."""
    s = sp.Spend(prefill=0.010, generation=0.90)
    assert s.cache_split is False
    assert s.fresh_in is None and s.served_from_cache is None


def test_the_input_side_is_split_on_all_legs_or_none():
    with pytest.raises(EvidenceError, match=r"all three legs or on\s+none"):
        sp.Spend(prefill=0.010, generation=0.90, cached_in=0.008)


def test_the_cache_legs_are_parts_of_the_input_cost_not_additions_to_it():
    """A caller adding them on top is double-charging the tokens the cache served."""
    with pytest.raises(EvidenceError, match="double-charging"):
        sp.Spend(prefill=0.010, generation=0.90, cached_in=0.009, cache_write=0.005)


def test_subtracting_a_cached_arm_from_a_fresh_one_is_refused_rather_than_averaged():
    """The discount attaches to the request's shape: identical content measured 0% as one long message and 99.9% as a
    growing conversation, so the difference is mostly the cache under whatever name the arms differed in."""
    with pytest.raises(EvidenceError, match="discount attaches to the request's shape"):
        sp.avoided(cached(), sp.Spend(prefill=0.010, generation=0.90, cached_in=0.0, cache_write=0.0))


def test_a_recorded_split_cannot_be_subtracted_from_an_unrecorded_one():
    with pytest.raises(EvidenceError, match="not a zero cache rate"):
        sp.avoided(cached(), sp.Spend(prefill=0.010, generation=0.90))


def test_two_unrecorded_costs_are_still_subtractable():
    """Refusing them would refuse every cost written before the legs existed."""
    got = sp.avoided(sp.Spend(prefill=0.010, generation=0.90), sp.Spend(prefill=0.004, generation=0.10))
    assert got.cache_split is False


def test_two_cached_arms_subtract_leg_by_leg():
    got = sp.avoided(cached(), cached(prefill=0.004, cached_in=0.003, cache_write=0.0005, generation=0.10))
    assert abs(got.cached_in - 0.005) < 1e-12
    assert abs(got.cache_write - 0.0005) < 1e-12


def test_adding_a_split_cost_to_an_unsplit_one_gives_an_unsplit_total():
    """Claiming a split for the total would attribute the whole of the unsplit input to the fresh leg."""
    got = cached() + sp.Spend(prefill=0.004, generation=0.10)
    assert got.cache_split is False
    assert abs(got.prefill - 0.014) < 1e-12


def test_the_printed_form_distinguishes_a_split_cost_from_an_unsplit_one():
    assert "cached" in str(cached()) and "cache write" in str(cached())
    assert "prefill" in str(sp.Spend(prefill=0.010, generation=0.90))


# --- cost at conversation scope, because a per-request cost is incomplete by construction ---------------------------------

def first_turn(cache_write=0.002):
    """A turn that populates a cache. Nothing was in the context before it, so it cannot be a cache read."""
    return sp.Spend(prefill=0.010 + cache_write, generation=0.90, cached_in=0.0, cache_write=cache_write)


def warm_turn():
    """A later turn whose input was mostly served from the cache the first turn paid for."""
    return sp.Spend(prefill=0.010, generation=0.90, cached_in=0.008, cache_write=0.0)


def test_the_total_is_over_the_sequence_because_the_discount_was_earned_by_an_earlier_turn():
    c = sp.Conversation(context="ctx", turns=(first_turn(), warm_turn(), warm_turn()))
    assert c.turn_count == 3
    assert abs(c.total.cached_in - 0.016) < 1e-12
    assert abs(c.total.cache_write - 0.002) < 1e-12


def test_the_first_turn_cannot_have_been_served_from_a_cache_that_did_not_exist_yet():
    """Arithmetic rather than convention: either the turns are out of order, or another context's cache is being
    charged to this one, and both credit the discount to a turn that did not earn it."""
    with pytest.raises(EvidenceError, match="nothing was in this context before it"):
        sp.Conversation(context="ctx", turns=(warm_turn(), first_turn()))


def test_a_conversation_needs_a_context_identifier():
    with pytest.raises(EvidenceError, match="which turns shared a cache prefix"):
        sp.Conversation(context="", turns=(first_turn(),))


def test_an_empty_conversation_is_the_absence_of_a_record():
    with pytest.raises(EvidenceError, match="absence of a record"):
        sp.Conversation(context="ctx", turns=())


def test_turns_that_disagree_about_whether_they_are_split_cannot_be_totalled():
    with pytest.raises(EvidenceError, match="whole input into the fresh leg"):
        sp.Conversation(context="ctx", turns=(first_turn(), sp.Spend(prefill=0.010, generation=0.90)))


def test_turns_in_two_units_cannot_be_totalled():
    with pytest.raises(EvidenceError, match="no unit at all"):
        sp.Conversation(context="ctx", turns=(
            first_turn(),
            sp.Spend(prefill=0.010, generation=0.90, unit="tokens", cached_in=0.0, cache_write=0.0)))


def test_a_single_turn_that_paid_a_cache_write_bought_a_discount_for_a_turn_that_never_came():
    """Reported rather than refused: it is a real thing that happens, and the record should show it."""
    assert sp.Conversation(context="ctx", turns=(first_turn(),)).paid_for_nothing is True
    assert sp.Conversation(context="ctx", turns=(first_turn(cache_write=0.0),)).paid_for_nothing is False
    assert sp.Conversation(context="ctx", turns=(first_turn(), warm_turn())).paid_for_nothing is False


def test_two_sequences_of_different_length_are_not_two_prices_for_the_same_work():
    """The check the withdrawn saving needed: routing changes the shape of every turn after the one it moved."""
    long_ = sp.Conversation(context="warm", turns=(first_turn(), warm_turn(), warm_turn()))
    short = sp.Conversation(context="single", turns=(first_turn(cache_write=0.0),))
    with pytest.raises(EvidenceError, match="Most of the difference between arms of different length is the length"):
        sp.refuse_incomparable_shapes(long_, short)


def test_two_sequences_of_the_same_length_are_comparable():
    a = sp.Conversation(context="a", turns=(first_turn(), warm_turn()))
    b = sp.Conversation(context="b", turns=(first_turn(), warm_turn()))
    sp.refuse_incomparable_shapes(a, b)


def test_the_printed_form_says_when_a_cache_was_paid_for_and_never_read():
    assert "nobody read" in str(sp.Conversation(context="ctx", turns=(first_turn(),)))
