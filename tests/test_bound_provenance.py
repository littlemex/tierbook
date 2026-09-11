"""C1 -- a bound says which corrections produced it, and `certified` stops meaning two things.

Two defects, one entry (CONTRACT's own framing), so this file has two halves.

**Half one, the centre.** Measured on the shipped v0.2.0 code: three records carrying a fabricated `bound` of
`0.99` against a floor of `0.92`, with `bound_kind` of `lcb`, `point_estimate` and `asserted_by_operator`, all
certify identically -- `admissible` compares only `bound < floor` and nothing reads the kind. Under the new shape a
provenance claiming a correction the mechanism did not perform must be REFUSED rather than certified, because a
kind that is checked and not merely recorded is the whole point of replacing a free string with a closed,
structured claim.

**Half two.** `decide.py`'s `certified` is compile-time non-inferiority validation against a reference (`entry.get
("status") == "assigned"`); `record.check_certification`'s is SCOPE section 2 admissibility, computed per decision
from a floor, authorisation, latency and freshness. Both travelled under one word. `decide.Policy.certified`
becomes `validated`; `record.Decision.certified` keeps its name because section 2's meaning is the one SCOPE
defines and the falsifier tests. An artifact written before this landed cannot be read as if the ambiguity had
never existed -- `from_dict` on a raw artifact carrying `certified` refuses, naming both words.

Following `tests/test_reason_vocabulary.py`'s convention: every test below states, in its docstring, what defect it
catches, not just what it calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import decide as dc  # noqa: E402
from tierbook import record as rec  # noqa: E402

V020_SMOKE_POLICY = ROOT / "docs" / "verify" / "v0.2.0-smoke-policy.json"


def prov(**kw) -> "rec.BoundProvenance":
    """A legal provenance by default -- the one estimator this release ships, no correction claimed."""
    base = dict(estimator="clopper_pearson_fixed_sample", confidence=0.95, corrected_over=())
    base.update(kw)
    return rec.BoundProvenance(**base)


def cand(**kw):
    """A candidate carrying a bound and a legal provenance by default, so each test overrides only what it means
    to test rather than re-typing every field."""
    base = dict(id="c", excluded_because="chosen", bound=0.99, bound_provenance=prov(), cost_usd=0.004,
               evidence_as_of="2026-09-01")
    base.update(kw)
    return rec.Candidate(**base)


# --- half one, the centre: a fabricated correction is refused, not certified -------------------------


def test_a_correction_the_mechanism_never_performed_is_refused_not_certified():
    """THE test this entry exists for. Measured on the shipped v0.2.0 code: a bound of 0.99 against a floor of
    0.92, with a fabricated `bound_kind`, certified -- `admissible` compared only `bound < floor` and nothing read
    the kind. Here the bound clears the floor by the same margin (0.99 >= 0.92) and every other admissibility
    condition holds, so the ONLY thing standing between this candidate and `chosen` is whether its provenance's
    claim is checked. `corrected_over=("families",)` claims a correction over the family term of section 6's
    multiplicity family; this release corrects over none of the four terms (out-of-scope table), so the claim is
    fabricated exactly the way the three v0.2.0 records were, and `admissible` must refuse it rather than return
    `(True, "chosen")`."""
    fabricated = cand(bound=0.99, bound_provenance=prov(corrected_over=("families",)))
    ok, why = rec.admissible(fabricated, floor=0.92, authorised=True, latency_feasible=True)
    assert ok is False, (
        "a bound whose provenance claims a correction over 'families' -- a term this release never corrects "
        "over -- was certified. That is the exact defect this entry exists to close: a fabricated correction "
        "claim must be refused, not merely unlabelled")
    # Whatever it refuses as, the reason has to be one `Candidate.excluded_because` can hold -- the same
    # closed-vocabulary discipline `admissible`'s other refusals already carry.
    assert why in rec.EXCLUSION_REASONS


def test_three_records_that_used_to_certify_identically_do_not_now():
    """Reproduces the measured shape of the v0.2.0 defect with three DIFFERENT fabricated claims, each stopped by
    a different guard rather than all three sliding through `admissible` unchecked. Under v0.2.0, `bound_kind` of
    `lcb`, `point_estimate` and `asserted_by_operator` on the same 0.99-against-0.92 bound all certified
    identically. Under the new shape none of the three analogous fabrications produces a certified candidate:
    the first is refused by the constructor's closed estimator vocabulary, the second by `admissible`'s provenance
    check, and the third by the dataclass no longer having a `bound_kind` field to accept at all."""
    # (1) An estimator naming a correction this release does not build -- refused at construction, before a
    # Candidate carrying it could even exist.
    with pytest.raises(rec.Incomplete):
        prov(estimator="anytime_valid_lower_bound")
    # (2) A legal estimator whose corrected_over claims a term nothing in this release corrects over -- refused
    # by admissible, exactly as the centre test above establishes.
    ok, _why = rec.admissible(cand(bound=0.99, bound_provenance=prov(corrected_over=("selection_process",))),
                              floor=0.92, authorised=True, latency_feasible=True)
    assert ok is False
    # (3) The old free-string field itself -- refused because it no longer exists on the dataclass to accept a
    # value at all, which is stronger than checking it and finding it wanting.
    with pytest.raises(TypeError):
        rec.Candidate(id="c", excluded_because="chosen", bound=0.99, bound_kind="asserted_by_operator")


# --- BOUND_CORRECTIONS, tied to admissible the way EXCLUSION_REASONS is tied to its producers ---------
#
# `test_reason_vocabulary.py`'s shape is: derive the cases from the vocabulary itself (never a second,
# independently-typed list of the same strings -- that second list is the C7 defect one level up), drive the one
# named producer of the behaviour through every branch, and add a reachability test so a term the tuple grows
# later cannot silently stop being exercised. `record.admissible` is the interface's one named producer of
# provenance-refusal behaviour ("record.admissible reads it"), and this release corrects over none of section 6's
# multiplicity terms (out-of-scope table) -- so every term in BOUND_CORRECTIONS other than the empty claim is, by
# construction, a term nothing here has performed, and admissible must refuse every one of them.

#: Every multiplicity term this release could be lied about. Derived FROM `rec.BOUND_CORRECTIONS`, not typed a
#: second time -- a term added to the tuple without a matching refusal is caught by the membership check below,
#: not by this list going stale next to it.
_UNPERFORMED_TERMS = tuple(t for t in rec.BOUND_CORRECTIONS if t != "none")


@pytest.mark.parametrize("term", _UNPERFORMED_TERMS, ids=_UNPERFORMED_TERMS)
def test_admissible_refuses_every_multiplicity_term_this_release_does_not_correct_over(term):
    """Catches a term being added to BOUND_CORRECTIONS without `admissible` being taught to refuse a claim over
    it -- the same gap `test_reason_vocabulary.py` closed for EXCLUSION_REASONS, one level up: a vocabulary
    checked only against itself and never against the function that is supposed to enforce it."""
    ok, _why = rec.admissible(cand(bound=0.99, bound_provenance=prov(corrected_over=(term,))),
                              floor=0.92, authorised=True, latency_feasible=True)
    assert ok is False, (
        f"admissible certified a bound claiming a correction over {term!r}, which this release never performs")


def test_the_parametrised_cases_above_are_not_vacuous():
    """Catches the case above passing only because every input happened to land on the same branch, which is
    exactly how four of nine EXCLUSION_REASONS values were once found to be unreachable while the suite stayed
    green. Every unperformed term must independently produce a refusal, not just the first one tried."""
    produced_refusals = {
        term: rec.admissible(cand(bound=0.99, bound_provenance=prov(corrected_over=(term,))),
                             floor=0.92, authorised=True, latency_feasible=True)[0]
        for term in _UNPERFORMED_TERMS
    }
    assert _UNPERFORMED_TERMS, "BOUND_CORRECTIONS has nothing left to refuse a claim over; this test is vacuous"
    assert all(ok is False for ok in produced_refusals.values()), produced_refusals


def test_a_correction_outside_the_vocabulary_is_refused_at_construction():
    """The guard the two tests above are tied to has to still exist, or this file checks admissible against a
    vocabulary nothing enforces at the boundary. Mirrors
    `test_a_reason_outside_the_vocabulary_is_still_refused` for EXCLUSION_REASONS."""
    with pytest.raises(rec.Incomplete):
        prov(corrected_over=("an invented multiplicity term",))


# --- corrected_over = () is legal, and is what this release produces ----------------------------------


def test_corrected_over_empty_tuple_is_legal_and_admissible():
    """`corrected_over = ()` is explicitly legal per the interface, and it is what every bound this release
    produces actually carries -- an implementation that refused the empty tuple, reasoning that a bound must name
    SOMETHING it corrected over, would refuse every bound v0.3.0 writes, which is the opposite of what a closed
    vocabulary for an absent claim is for."""
    clean = cand(bound=0.99, bound_provenance=prov(corrected_over=()))
    assert clean.bound_provenance.corrected_over == ()
    ok, why = rec.admissible(clean, floor=0.92, authorised=True, latency_feasible=True)
    assert (ok, why) == (True, "chosen")


# --- estimator: a closed tuple with exactly one member this release ships -----------------------------


def test_the_one_shipped_estimator_is_legal():
    """The estimator this release actually produces bounds with. If this ever raises, nothing in this release can
    write a bound at all -- the floor this whole file stands on."""
    p = prov(estimator="clopper_pearson_fixed_sample")
    assert p.estimator == "clopper_pearson_fixed_sample"


def test_an_estimator_naming_a_correction_this_release_does_not_build_is_refused():
    """THE test the interface calls out by name: 'adding anytime_valid_* is a later release's act and the
    vocabulary makes its absence explicit rather than implied.' A vocabulary that only ever validated the one
    legal value would pass against an implementation that accepted anything else too -- this asserts the refusal
    side, not just the acceptance side."""
    with pytest.raises(rec.Incomplete):
        prov(estimator="anytime_valid_lower_bound")


def test_an_arbitrary_free_string_estimator_is_also_refused():
    """Catches the closed tuple being enforced only against the ONE name the release happens to ship and not
    against arbitrary strings -- an implementation that special-cased 'anytime_valid_lower_bound' specifically,
    rather than closing the vocabulary, would pass the test above and fail this one."""
    with pytest.raises(rec.Incomplete):
        prov(estimator="whatever a caller felt like typing")


# --- bound_kind is gone, and there is no alias for it --------------------------------------------------


def test_bound_kind_is_not_a_constructible_field_at_all():
    """The interface is explicit that the old field is not kept as an alias: 'keeping it would leave a writer of
    an unchecked claim that the new check cannot see.' A caller passing the old keyword must fail outright, not
    be silently accepted and ignored -- silent acceptance would be just as invisible to `admissible`'s new check
    as the alias the interface refuses."""
    with pytest.raises(TypeError):
        cand(bound_kind="lcb95")


# --- bound_provenance = None means no bound, and is legal (C6 needs it representable) -----------------


def test_bound_provenance_none_is_legal_and_reads_as_no_bound():
    """C6's candidate set names a candidate the ledger cannot bound `with no bound rather than omitted`
    (candidates_for maps to `bound` or to `None`), and C1 owns the field that has to represent that. An
    implementation that required a BoundProvenance object even for a bound that does not exist would make C6's
    'no bound' unrepresentable again, one field over from where it was fixed."""
    unbounded = cand(id="u", excluded_because="no_bound", bound=None, bound_provenance=None)
    assert unbounded.bound_provenance is None
    ok, why = rec.admissible(unbounded, floor=0.92, authorised=True, latency_feasible=True)
    assert (ok, why) == (False, "no_bound")


# --- half two: `validated` and `certified` are two names for two judgments -----------------------------


def test_decide_policy_exposes_validated():
    """`decide.Policy.certified` -- compile-time non-inferiority against a reference -- is renamed `validated`. If
    this attribute is absent, nothing downstream can distinguish 'this cascade beat the reference on a held-out
    fold' from section 2's per-decision admissibility, which is the entire defect C1's second half exists to
    close."""
    pol = dc.Policy(family="f", rules=(), default=("api",), validated=True)
    assert pol.validated is True


def test_as_dict_writes_validated_and_not_certified():
    """`decide.as_dict` is the artifact's writer. The interface says it writes `validated`; it says nothing about
    still writing `certified` under the compiled-policy artifact's own key, and 'the word certified appears in the
    online path only where section 2's judgment is meant' rules it out here -- this is the non-inferiority
    judgment, not section 2's. Catches a writer that adds the new key without removing the old one, which would
    leave exactly the two-words-one-fact ambiguity C1 exists to close, just written twice instead of once."""
    pol = dc.Policy(family="f", rules=(), default=("api",), validated=True)
    d = dc.as_dict(pol)
    assert d.get("validated") is True
    assert "certified" not in d, (
        "decide.as_dict wrote a 'certified' key into the compiled-policy artifact; that word is reserved for "
        "section 2's per-decision judgment and this artifact carries the compile-time one")


def test_a_validated_artifact_round_trips():
    """The inverse of the write above: a freshly-written artifact must be readable as the same policy, or the
    rename only works in one direction and every consumer that reads a policy back off disk regresses."""
    pol = dc.Policy(family="f", rules=(), default=("api",), validated=False,
                    parameters={"floor": 0.5, "max_evidence_age_days": None, "staleness_limit_days": None})
    back = dc.from_dict(dc.as_dict(pol))
    assert back.validated is False


def test_a_real_v020_artifact_carries_certified_and_no_validated_key():
    """Not a hand-written fixture: `docs/verify/v0.2.0-smoke-policy.json` was produced by calling the actual,
    unmodified v0.2.0 `decide.as_dict` (before C1 existed) against a policy built the same way
    `docs/verify/v0.1.0-smoke-policy.json` was, so it is a genuine artifact an operator holds today rather than a
    guess at what one might look like. If this assertion ever fails, the fixture stopped being the case C1's
    refusal is about."""
    raw = json.loads(V020_SMOKE_POLICY.read_text())
    assert raw["rules"], "the fixture must carry rules to be a realistic compiled artifact"
    assert "certified" in raw
    assert "validated" not in raw


def test_from_dict_refuses_a_v020_artifact_naming_both_words():
    """THE test C1's second half exists for: a real v0.2.0 artifact loaded the way an operator's own tooling would
    load it. `certified` there meant the compile-time non-inferiority judgment; reading it as `validated` today
    would be silently correct by luck and reading it as section 2's `certified` would be silently wrong -- so
    `from_dict` must refuse rather than guess, naming both words so the operator knows which judgment each one
    was."""
    raw = json.loads(V020_SMOKE_POLICY.read_text())
    with pytest.raises(ValueError, match="certified"):
        dc.from_dict(raw)


def test_the_refusal_names_both_words():
    """'naming both words and saying which judgment each is' is load-bearing in the contract's own wording -- an
    operator reading only 'refused: ambiguous artifact' still cannot tell which word to type into their own
    tooling. Catches a refusal that fires for the right artifact but for the wrong, unstated reason."""
    raw = json.loads(V020_SMOKE_POLICY.read_text())
    with pytest.raises(ValueError) as excinfo:
        dc.from_dict(raw)
    message = str(excinfo.value)
    assert "certified" in message
    assert "validated" in message


def test_record_decision_certified_keeps_its_name():
    """The half of the rename that must NOT happen: `record.Decision.certified` is section 2's admissibility, 'the
    one SCOPE defines and the falsifier tests', and C1 does not touch it. If a worker renamed both `certified`
    fields out of an overcorrection, `record.check_certification` -- section 12's falsifier -- would break, and
    this is the test that catches the field disappearing before that falsifier does."""
    decision = rec.Decision(
        family="f", request_id="r", feature_vector_version="fv1", state_ref="o",
        candidates=[cand(id="box", excluded_because="chosen"),
                    cand(id="api", excluded_because="below_floor", bound=0.10)],
        chosen="box", selection_probability=1.0, exploration=False, certified=True, policy_version="p",
        policy_digest="0123456789abcdef",
        mechanism_version="0.3.0", agent="a", model="m", endpoint="http://e",
        gateway_quote_usd=0.004, gateway_authorised=True, exploration_reason="no_mechanism", eligible_set=[])
    assert decision.certified is True
    assert decision.as_dict()["certified"] is True
