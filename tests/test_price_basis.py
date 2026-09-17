"""Tests for what makes a price obtainable again.

The measured cost: a cheap/dear split over nine candidates had to be reverse-engineered from prose in three documents
and then confirmed by checking that it reproduced an original count of 168 items exactly. No static rate card existed;
prices were read from a live pricing API at run time and the reading was not kept. A day went into recovering an input
the original derivation had used and not recorded -- and it was recoverable only because that count was known.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import record as rec  # noqa: E402
from tierbook.decide import GAP_REASONS  # noqa: E402


def basis(**kw):
    base = dict(source="published_rate_card", as_of="2026-09-01", ordering=("box", "api"))
    base.update(kw)
    return rec.PriceBasis(**base)


# --- three things, and dropping any one leaves the derivation unrepeatable ---------------------------------------------

def test_an_open_ended_source_cannot_be_read_again():
    with pytest.raises(rec.Incomplete, match="cannot be read again"):
        basis(source="wherever prices come from")


def test_a_basis_with_no_date_is_a_note_saying_prices_were_consulted():
    """A live pricing API returns a different number next week, and the date is the whole difference."""
    with pytest.raises(rec.Incomplete, match="whole difference between a basis and a note"):
        basis(as_of="")


def test_a_basis_with_no_ordering_records_where_the_prices_came_from_and_not_what_they_decided():
    """A decision turns on which candidate was cheaper, and that comparison is what has to be reproduced."""
    with pytest.raises(rec.Incomplete, match="not what they decided"):
        basis(ordering=())


def test_an_ordering_naming_a_candidate_twice_is_not_an_ordering():
    with pytest.raises(rec.Incomplete, match="not an ordering"):
        basis(ordering=("box", "api", "box"))


def test_an_operator_asserted_price_needs_its_note():
    """It is re-derivable from nothing, so the note is the only thing standing between it and an unattributable
    number."""
    with pytest.raises(rec.Incomplete, match="re-derivable from nothing"):
        basis(source="operator_asserted")
    assert basis(source="operator_asserted", note="the account manager quoted it").note


def test_every_source_in_the_vocabulary_can_be_constructed():
    for source in rec.PRICE_SOURCES:
        kw = {"note": "why"} if source == "operator_asserted" else {}
        assert basis(source=source, **kw).source == source


# --- it travels on the candidate, and the ordering is read rather than recorded ----------------------------------------

def test_a_candidate_carries_its_basis():
    c = rec.Candidate(id="box", excluded_because="chosen", cost_usd=0.004, price_basis=basis())
    assert c.price_basis.as_of == "2026-09-01"


def test_an_ordering_that_does_not_place_this_candidate_cannot_have_decided_its_position():
    """READ rather than merely recorded, which is what `admissible` does with a bound's correction: an ordering that
    omits the candidate does not describe the comparison this decision turned on."""
    with pytest.raises(rec.Incomplete, match="not in it"):
        rec.Candidate(id="third", excluded_because="chosen", cost_usd=0.004, price_basis=basis())


def test_a_basis_cannot_describe_a_price_that_is_not_there():
    with pytest.raises(rec.Incomplete, match="price that is not there"):
        rec.Candidate(id="box", excluded_because="chosen", cost_usd=None, price_basis=basis())


def test_a_free_string_is_refused_where_a_basis_belongs():
    with pytest.raises(rec.Incomplete, match="cannot carry the date and the ordering"):
        rec.Candidate(id="box", excluded_because="chosen", cost_usd=0.004, price_basis="the rate card")


def test_a_cost_without_a_basis_is_permitted_and_that_is_deliberate():
    """A bound with no provenance let three fabricated bounds certify identically, so it is refused. A cost with no
    basis is a reproducibility debt: the decision is sound and the derivation cannot be repeated. Refusing it would make
    every existing caller unable to record a cost at all, so it is reported through the gap channel instead."""
    c = rec.Candidate(id="box", excluded_because="chosen", cost_usd=0.004)
    assert c.price_basis is None


# --- and the record says so, through the vocabulary built for exactly this ---------------------------------------------

def test_the_gap_reason_exists_in_the_closed_vocabulary():
    assert "unrecorded_price_basis" in GAP_REASONS


def test_a_decision_priced_with_no_basis_carries_the_gap():
    """`tierbook assign` already prints gaps, so the operator sees that this decision's price ordering cannot be
    re-derived without anything new having to be wired to show it. Driven through the same `route` helper the serve
    tests use, so this exercises the real composition rather than a shape."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_serve import obs, route

    _, d = route(obs(inflight=2.0, metered_authorised=True))
    assert any(g.startswith("unrecorded_price_basis:") for g in d.gaps), d.gaps


def test_supplying_the_basis_removes_the_gap():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_serve import COSTS, obs, route

    _, d = route(obs(inflight=2.0, metered_authorised=True),
                 price_basis=basis(ordering=tuple(COSTS)))
    assert not any(g.startswith("unrecorded_price_basis:") for g in d.gaps), d.gaps
    priced = [c for c in d.candidates if c.cost_usd is not None]
    assert priced and all(c.price_basis is not None for c in priced)


def test_a_decision_with_no_costs_at_all_carries_no_price_gap():
    """Nothing was priced, so nothing about a price is missing -- and reporting a gap there would train a reader to
    ignore it."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_serve import obs, route

    _, d = route(obs(inflight=2.0, metered_authorised=True), costs={})
    assert not any(g.startswith("unrecorded_price_basis:") for g in d.gaps), d.gaps


def test_the_gap_text_names_what_cannot_be_re_derived():
    """The sentence an operator reads has to say which thing is lost, not that something is."""
    import inspect

    from tierbook import serve as sv
    src = inspect.getsource(sv.route_once)
    assert "unrecorded_price_basis" in src
    assert "cannot be re-derived" in src


# --- when a price is knowable, which decides whether it can be an argument ---------------------------------------------

def test_every_source_is_classified_so_forgetting_one_is_a_failure():
    """A total map rather than a list of the bad ones: adding a source without deciding when it is known breaks this
    test rather than defaulting the new source to usable."""
    assert set(rec.PRICE_KNOWN_BEFORE_THE_CALL) == set(rec.PRICE_SOURCES)


def test_a_metered_charge_does_not_exist_until_the_call_is_over():
    assert rec.PRICE_KNOWN_BEFORE_THE_CALL["gateway_metered"] is False
    assert basis(source="gateway_metered").known_before_the_call is False


def test_a_rate_is_readable_in_advance_whether_it_is_static_or_fetched():
    """The date on a live reading is what makes it re-readable, not what makes it late."""
    for source in ("published_rate_card", "live_price_api"):
        assert basis(source=source).known_before_the_call is True


def test_a_metered_basis_is_constructible_and_refused_only_where_it_would_be_an_argument():
    """Recording what was actually charged is legitimate; using it to decide is not. 87% of a price term's measured
    value was leakage of exactly this shape."""
    b = basis(source="gateway_metered")
    assert b.source == "gateway_metered"
    with pytest.raises(rec.Incomplete, match="does not exist until the call is over"):
        rec.Candidate(id="box", excluded_because="chosen", cost_usd=0.004, price_basis=b)


def test_the_refusal_names_where_the_charge_does_belong():
    """A refusal that does not say where the number should go gets worked around by dropping the number."""
    with pytest.raises(rec.Incomplete) as exc:
        rec.Candidate(id="box", excluded_because="chosen", cost_usd=0.004,
                      price_basis=basis(source="gateway_metered"))
    assert "outcome" in str(exc.value)


def test_a_rate_based_basis_is_accepted_on_a_candidate():
    c = rec.Candidate(id="box", excluded_because="chosen", cost_usd=0.004, price_basis=basis())
    assert c.price_basis.known_before_the_call is True


def test_the_after_the_call_figure_has_its_own_homes():
    """Nothing is lost by refusing it on a candidate: the quote before the call and the charge after it both already
    have fields, so the refusal removes an argument rather than a record."""
    import dataclasses
    fields = {f.name for f in dataclasses.fields(rec.Decision)}
    assert "gateway_quote_usd" in fields          # the pre-call quote
    assert "outcome" in fields                    # attached after, by attach_outcome
