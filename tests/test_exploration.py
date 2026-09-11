"""C3 -- exploration, specified before it is implemented.

The eligible set, the draw and the recorded propensity, each pinned in the contract because a review found each one
under-specified. This file tests three things `src/tierbook/explore.py` (a new module) must provide --
`clears_floor`, `eligible`, `draw` -- plus the two seams the contract records at the boundary between C3 and the
entries either side of it:

  * S4 / amendment 5.2 -- `record.Decision` gains `exploration_reason` and `eligible_set`, neither with a dataclass
    default, and `record.from_row` is the one place that supplies the version-1 values (`no_mechanism`, `[]`)
    rather than the dataclass defaulting them -- because a default would read a v0.2.0 writer that forgot to stamp
    the field the same as a v0.1.0 row that never had the concept, which is exactly the count this release reports.
  * Amendment 5.1 -- `config.FamilyDeclaration` gains `staleness_limit_days`, refused when absent like C4's three
    fields, and refused in combination with `exploration_rate` when it is `null` (no limit): the door C3 opens
    exists to reach a candidate whose evidence expired, so an unbounded staleness there is a bound from any past
    environment at all.
  * C3's own closing clause -- `accept.floor_compliance` reports two rates, certified and all-served, so exploring
    below the floor cannot be laundered by shrinking the denominator that would otherwise show it. Amendment 6
    settles that `floor_compliance` stays ONE verdict (SCOPE section 12 names nine criteria, and splitting one
    would silently make it ten): the two rates, their two bounds and their two sub-verdicts live in `numbers`, and
    the criterion's own verdict is the WORSE of the two.
  * Amendment 6's substantive addition -- an arm reached only through `clears_floor`'s expiry override is SERVED
    but UNCERTIFIED. SCOPE section 2 had listed admissibility as three conditions while `record.admissible` has
    enforced four (freshness) since v0.1.0; SCOPE now carries the fourth clause, and `certified` is decided from
    full admissibility -- freshness included -- never from `explore.eligible`'s verdict, which answers a different
    question (is this arm reachable by exploration at all) than the one `certified` answers (does this specific
    assignment, right now, meet every condition needed to trust it). The two decisions can and do disagree on the
    same candidate, and that disagreement -- served by the stale arm, uncertified for it, still visible in
    `floor_compliance`'s `all_served` population -- is what closes F8 rather than reopening it.

Only C3 (plus these seams) is in scope here. C1's reader, C2's parameter plumbing, C4's labeller declaration and
C5's pooling refusal each have their own test files and are not re-tested.

**A reconstruction this file depends on, stated so it is not mistaken for something the contract settled:**
`explore.eligible`'s keyword arguments (`authorised`, `latency_feasible`, `available`, `evidence_age_days`) have no
stated type in the interface section. `src/tierbook/serve.py`'s existing `candidate_set`/`_why_not` -- which computes
the same five-way exclusion vocabulary for the ordinary (non-exploring) path -- treats `authorised` and
`latency_feasible` and `evidence_age_days` as single values for the whole decision (the gateway's authorisation, the
operator's latency feasibility, and the observation's evidence age are properties of the REQUEST, not of any one
candidate) and `available` as a dict keyed by candidate id (because serving status genuinely differs per candidate,
carried in `observation.state[f"available:{cid}"]`). This file follows that precedent for `eligible`'s equivalent
keywords. It is a reconstruction, not a contract fact -- see the report for why it is flagged as an ambiguity rather
than asserted as settled.
"""
from __future__ import annotations

import json
import datetime as _dt
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import accept as ac  # noqa: E402
from tierbook import decide as dc  # noqa: E402
from tierbook import explore  # noqa: E402
from tierbook import observe as ob  # noqa: E402
from tierbook import record as rec  # noqa: E402
from tierbook import serve as sv  # noqa: E402
from tierbook.config import ConfigError, load_config  # noqa: E402

V010_FIXTURE = ROOT / "docs" / "verify" / "v0.1.0-decisions.jsonl"


def _real_v010_row() -> dict:
    """A line actually written by v0.1.0, not a hand-typed stand-in -- amendment 5 and C1's own test file both
    insist on this for the same reason: a reader tuned to a fixture's exact shape would pass the wrong test."""
    for line in V010_FIXTURE.read_text().splitlines():
        parsed = json.loads(line)
        if "request_id" in parsed:
            return parsed
    raise AssertionError(f"{V010_FIXTURE} has no decision line")


# ======================================================================================================
# explore.clears_floor
# ======================================================================================================


def mk_candidate(*, cid="box", bound=0.90, excluded_because="chosen", cost_usd=0.01,
                 evidence_as_of="2026-09-01") -> rec.Candidate:
    """A `record.Candidate`, the same object `admissible` takes -- `clears_floor` is explicitly "separate from
    `admissible`", not a different domain object, so building the fixture any other way would test a function this
    module does not define."""
    return rec.Candidate(id=cid, excluded_because=excluded_because, bound=bound, cost_usd=cost_usd,
                         evidence_as_of=evidence_as_of)


def test_clears_floor_no_bound_is_false_no_bound():
    """Catches a `clears_floor` that only checks the floor comparison and lets `bound is None` fall through to a
    numeric comparison (`None < floor`), which raises `TypeError` in Python 3 rather than returning the named
    negative result the contract states first."""
    c = mk_candidate(bound=None)
    assert explore.clears_floor(c, 0.80) == (False, "no_bound")


def test_clears_floor_below_floor_is_false_below_floor():
    """Catches the floor comparison being inverted or dropped -- a bound strictly under the floor must be refused
    by name, not silently treated as eligible because no expiry limit was declared."""
    c = mk_candidate(bound=0.70)
    assert explore.clears_floor(c, 0.80) == (False, "below_floor")


def test_clears_floor_at_exactly_the_floor_is_eligible():
    """The boundary the contract's ordering implies: `admissible` refuses strictly-under (`bound < floor`), and
    nothing in C3's entry says `clears_floor` uses a different comparison. A bound equal to the floor must clear
    it -- catches an off-by-one that refuses ties."""
    c = mk_candidate(bound=0.80)
    assert explore.clears_floor(c, 0.80) == (True, "eligible")


def test_clears_floor_with_no_staleness_limit_and_no_age_is_eligible():
    """The ordinary case: a fresh bound, no declared staleness limit, no age to compare. Needed as a baseline --
    without it, the boundary tests below would not tell you whether the function ever returns `eligible` at all
    versus refusing everything unconditionally."""
    c = mk_candidate(bound=0.90)
    assert explore.clears_floor(c, 0.80) == (True, "eligible")


def test_clears_floor_with_no_declared_limit_is_eligible_no_matter_how_old_the_evidence_is():
    """`staleness_limit_days=None` means no limit, stated in the contract as the door's whole point: exploration
    exists to reach a candidate whose evidence expired, so a declared absence of a limit must not silently become
    an implicit one (e.g. an implementer defaulting `None` to some fixed number)."""
    c = mk_candidate(bound=0.90)
    result = explore.clears_floor(c, 0.80, staleness_limit_days=None, evidence_age_days=10_000.0)
    assert result == (True, "eligible")


def test_clears_floor_age_exactly_at_the_staleness_limit_is_eligible_not_too_stale():
    """The contract's word is "exceeds", not "meets or exceeds": age equal to the declared limit must clear.
    Catches a `>=` implementation where the contract specifies `>`."""
    c = mk_candidate(bound=0.90)
    result = explore.clears_floor(c, 0.80, staleness_limit_days=30.0, evidence_age_days=30.0)
    assert result == (True, "eligible")


def test_clears_floor_age_just_past_the_staleness_limit_is_too_stale_to_explore():
    """The adjacent value on the other side of the same boundary as the test above -- together they are the pair
    that actually exercises `>` versus `>=`, not either alone."""
    c = mk_candidate(bound=0.90)
    result = explore.clears_floor(c, 0.80, staleness_limit_days=30.0, evidence_age_days=30.01)
    assert result == (False, "too_stale_to_explore")


def test_clears_floor_age_comfortably_past_the_limit_is_too_stale_to_explore():
    """A value away from the boundary, so the boundary-exact tests above are not the only cases this function is
    ever run against -- catches a unit error (days vs seconds) that happens to cancel out only at the boundary."""
    c = mk_candidate(bound=0.90)
    result = explore.clears_floor(c, 0.80, staleness_limit_days=30.0, evidence_age_days=90.0)
    assert result == (False, "too_stale_to_explore")


def test_clears_floor_does_not_consult_max_evidence_age_days_the_override_is_the_whole_point():
    """The single most important negative case in this file. Constructs a candidate that `record.admissible`
    refuses as `evidence_expired` against a `max_evidence_age_days` of 30 -- the ordinary expiry ratchet -- with the
    SAME candidate, SAME floor and SAME evidence age handed to `clears_floor` instead, declaring only a
    `staleness_limit_days` of 60 (not exceeded). `clears_floor`'s signature has no `max_evidence_age_days`
    parameter at all, so an implementation that reused `admissible` wholesale, or that consulted some other stored
    "already expired" fact on the candidate (its `excluded_because` is deliberately set to `"evidence_expired"`
    here, as an upstream caller might have already computed), would refuse this candidate -- exactly the arm the
    expiry ratchet locked out, which C3 exists to reach. The correct answer is `(True, "eligible")`."""
    c = mk_candidate(bound=0.90, excluded_because="evidence_expired")
    ok, why = rec.admissible(c, floor=0.80, authorised=True, latency_feasible=None,
                             evidence_age_days=40.0, max_age_days=30.0)
    assert (ok, why) == (False, "evidence_expired"), (
        "fixture sanity check: admissible must refuse this exact candidate for the test below to mean anything"
    )
    result = explore.clears_floor(c, 0.80, staleness_limit_days=60.0, evidence_age_days=40.0)
    assert result == (True, "eligible")


def test_clears_floor_below_floor_takes_precedence_over_a_stale_age_fixture_is_below_floor_only():
    """Fixture isolation (amendment 3's general obligation): a candidate that is BOTH below the floor AND past the
    staleness limit must report exactly one reason, and it must be a reason this exact candidate produces --
    `below_floor`, not `too_stale_to_explore` or a value that could have come from either flaw. Built so only the
    floor comparison can be blamed for the refusal: age is left far inside the limit's boundary is not tested here
    (see the next test for the mirror), it is tested with age comfortably inside the limit."""
    c = mk_candidate(bound=0.50)
    result = explore.clears_floor(c, 0.80, staleness_limit_days=30.0, evidence_age_days=5.0)
    assert result == (False, "below_floor")


# ======================================================================================================
# explore.eligible
# ======================================================================================================
#
# `candidates` is a list of `record.Candidate` (the same object `clears_floor` and `admissible` take -- nothing in
# the interface introduces a third candidate shape for this one function). Each fixture below is built so exactly
# one exclusion can fire: every OTHER candidate in the list is unambiguously eligible, and the one candidate under
# test carries exactly one flaw.


def _good_candidates(*ids: str) -> list:
    return [mk_candidate(cid=i, bound=0.90, cost_usd=0.01) for i in ids]


def test_eligible_all_good_candidates_are_all_eligible():
    """Baseline: without this, every exclusion test below would not tell you whether `eligible` ever returns
    anything at all versus refusing unconditionally."""
    cands = _good_candidates("a", "b", "c")
    got = explore.eligible(cands, floor=0.80, authorised=True, latency_feasible=True,
                           available={"a": True, "b": True, "c": True},
                           staleness_limit_days=None, evidence_age_days=None)
    assert set(got) == {"a", "b", "c"}


def test_eligible_excludes_a_candidate_below_the_floor():
    """The fundamental criterion the whole entry is named after: "exploration draws from candidates whose bound
    clears the floor". Not one of the five exclusions the contract calls "not overridden" -- it is the base case
    the override sits on top of -- so it is tested on its own, separately from the enumerated five below."""
    cands = _good_candidates("a", "b") + [mk_candidate(cid="low", bound=0.50, cost_usd=0.01)]
    got = explore.eligible(cands, floor=0.80, authorised=True, latency_feasible=True,
                           available={"a": True, "b": True, "low": True},
                           staleness_limit_days=None, evidence_age_days=None)
    assert "low" not in got and set(got) == {"a", "b"}


def test_eligible_excludes_not_authorised_alone():
    """One of the five exclusions the contract says exploration does NOT override, isolated: every candidate here
    clears the floor and is otherwise fine, and `authorised=False` is the ONLY flaw in the whole fixture -- a test
    of this exclusion's effect that also broke availability or pricing could not tell which refusal fired."""
    cands = _good_candidates("a", "b")
    got = explore.eligible(cands, floor=0.80, authorised=False, latency_feasible=True,
                           available={"a": True, "b": True},
                           staleness_limit_days=None, evidence_age_days=None)
    assert got == []


def test_eligible_excludes_latency_infeasible_alone():
    """The second of the five, isolated the same way: `latency_feasible=False` with every other input clean."""
    cands = _good_candidates("a", "b")
    got = explore.eligible(cands, floor=0.80, authorised=True, latency_feasible=False,
                           available={"a": True, "b": True},
                           staleness_limit_days=None, evidence_age_days=None)
    assert got == []


def test_eligible_excludes_unavailable_candidate_only():
    """The third of the five, and the one that is per-candidate rather than per-decision (`available` is a dict
    keyed by id, following `serve.py`'s existing convention): only `"b"` is marked unavailable, and `"a"` -- built
    identically otherwise -- must stay eligible. A fixture that marked every candidate unavailable could not tell
    this exclusion apart from a bug that refuses the whole call."""
    cands = _good_candidates("a", "b")
    got = explore.eligible(cands, floor=0.80, authorised=True, latency_feasible=True,
                           available={"a": True, "b": False},
                           staleness_limit_days=None, evidence_age_days=None)
    assert "b" not in got and "a" in got


def test_eligible_excludes_not_priced_candidate_only():
    """The fourth of the five: a candidate with no `cost_usd`, isolated from the others which all carry one.
    `Candidate.cost_usd` is read directly off the object -- `eligible`'s signature carries no separate `costs`
    mapping -- so this is the fixture that would catch a version that forgot to check it at all."""
    cands = _good_candidates("a") + [mk_candidate(cid="b", bound=0.90, cost_usd=None)]
    got = explore.eligible(cands, floor=0.80, authorised=True, latency_feasible=True,
                           available={"a": True, "b": True},
                           staleness_limit_days=None, evidence_age_days=None)
    assert "b" not in got and "a" in got


def test_eligible_excludes_no_bound_candidate_only():
    """The fifth of the five: a candidate with no bound at all, which `clears_floor` itself names `no_bound` --
    isolated here at the `eligible` level to confirm the exclusion actually propagates up to the returned id list,
    not merely to the predicate `eligible` may call internally."""
    cands = _good_candidates("a") + [mk_candidate(cid="b", bound=None, cost_usd=0.01)]
    got = explore.eligible(cands, floor=0.80, authorised=True, latency_feasible=True,
                           available={"a": True, "b": True},
                           staleness_limit_days=None, evidence_age_days=None)
    assert "b" not in got and "a" in got


def test_eligible_does_not_override_any_of_the_five_even_when_every_other_condition_is_generous():
    """The five together, catching an implementation that overrides everything (F22's rejected alternative,
    "exploration overriding every exclusion" -- "routes paid traffic through a randomiser whose eligible set
    nobody could enumerate"). Five separately-flawed candidates, one flaw each, none surviving into the result."""
    cands = [
        mk_candidate(cid="not_auth", bound=0.90, cost_usd=0.01),
        mk_candidate(cid="no_latency", bound=0.90, cost_usd=0.01),
        mk_candidate(cid="unavail", bound=0.90, cost_usd=0.01),
        mk_candidate(cid="unpriced", bound=0.90, cost_usd=None),
        mk_candidate(cid="no_bound", bound=None, cost_usd=0.01),
        mk_candidate(cid="good", bound=0.90, cost_usd=0.01),
    ]
    # authorised/latency_feasible are decision-level in this reconstruction, so a single False would exclude every
    # candidate and defeat the isolation this test needs -- so this test only isolates the per-candidate exclusions
    # (unavailable, not_priced, no_bound) and leaves not_authorised/latency_infeasible to their own tests above.
    got = explore.eligible(
        [c for c in cands if c.id not in ("not_auth", "no_latency")],
        floor=0.80, authorised=True, latency_feasible=True,
        available={"unavail": False, "unpriced": True, "no_bound": True, "good": True},
        staleness_limit_days=None, evidence_age_days=None,
    )
    assert got == ["good"]


def test_eligible_overrides_expiry_a_candidate_within_the_staleness_limit_is_included():
    """The override's positive case at the `eligible` level: age past nothing declared (`staleness_limit_days`
    generous), candidate is included. Needed as a baseline for the negative case immediately below -- a version
    that excludes everything would pass a too-stale test vacuously."""
    cands = _good_candidates("a")
    got = explore.eligible(cands, floor=0.80, authorised=True, latency_feasible=True,
                           available={"a": True}, staleness_limit_days=60.0, evidence_age_days=40.0)
    assert got == ["a"]


def test_eligible_excludes_a_candidate_past_the_declared_staleness_limit():
    """The override is bounded, not unlimited: "the door exists to reach a candidate whose evidence expired... an
    unbounded staleness is a bound from any past environment" -- a declared `staleness_limit_days` still excludes
    a candidate whose age exceeds IT, even though ordinary expiry (`max_evidence_age_days`) plays no role here at
    all. Catches an implementation that reads "expiry is overridden" as "no age limit applies, ever"."""
    cands = _good_candidates("a")
    got = explore.eligible(cands, floor=0.80, authorised=True, latency_feasible=True,
                           available={"a": True}, staleness_limit_days=30.0, evidence_age_days=90.0)
    assert got == []


# ======================================================================================================
# explore.draw
# ======================================================================================================
#
# `rng` is exercised as a `random.Random(seed)` instance -- the convention already used for every other seeded draw
# in this codebase (`audit.py`, `counterfactual.py`, both `random.Random(seed)` then `.choice`/`.randrange`/
# `.sample`) -- so a fixed seed makes a specific run's outcome reproducible without this file needing to predict,
# ahead of any implementation existing, exactly which internal method is called. Every assertion below is written
# to hold under EITHER of the two arms a seeded run can land on, so it does not depend on knowing which one a given
# seed happens to pick.


def test_draw_rate_zero_returns_deterministic_with_propensity_one_and_reason_rate_zero():
    """The first of the two `exploration: false` causes this function must distinguish. A real alternative is
    present in `eligible` so this cannot be confused with the OTHER cause below (`no_eligible_arm`) -- only `rate`
    is zero here."""
    result = explore.draw("box", ["box", "alt"], 0.0, random.Random(1))
    assert result == ("box", 1.0, "rate_zero")


def test_draw_no_alternative_arm_returns_deterministic_with_propensity_one_and_reason_no_eligible_arm():
    """The second of the two causes, isolated from the first: `rate` is a real positive number here, and the ONLY
    reason nothing is drawn is that `eligible` contains no id besides the deterministic one."""
    result = explore.draw("box", ["box"], 0.05, random.Random(1))
    assert result == ("box", 1.0, "no_eligible_arm")


def test_draw_rate_zero_and_no_alternative_both_hold_returns_rate_zero():
    """Amendment 6 settles the precedence this test used to leave open: `rate_zero` wins when both conditions
    hold, because with a rate of zero the eligible set is never consulted -- reporting `no_eligible_arm` would be
    reporting on a code path that did not run. Catches an implementation that checks the eligible set first and
    only falls through to `rate` afterwards, which would report the wrong one of the two whenever both are true."""
    result = explore.draw("box", ["box"], 0.0, random.Random(1))
    assert result == ("box", 1.0, "rate_zero")


def test_draw_rate_outside_zero_one_raises_value_error_at_one():
    """The contract's own reason: "a rate of 1 would leave the deterministic arm propensity 0, which the record
    refuses." `Decision.selection_probability` requires `> 0`, so `rate == 1.0` must be refused here rather than
    reaching a record that would refuse it more confusingly, further from the cause."""
    with pytest.raises(ValueError):
        explore.draw("box", ["box", "alt"], 1.0, random.Random(1))


def test_draw_rate_outside_zero_one_raises_value_error_above_one():
    with pytest.raises(ValueError):
        explore.draw("box", ["box", "alt"], 1.5, random.Random(1))


def test_draw_rate_outside_zero_one_raises_value_error_below_zero():
    with pytest.raises(ValueError):
        explore.draw("box", ["box", "alt"], -0.1, random.Random(1))


def test_draw_rate_just_under_one_does_not_raise():
    """The boundary adjacent to the refused value: `[0, 1)` is half-open, so a rate just under 1 must be accepted
    -- catches an implementation that refuses the whole neighbourhood rather than the single excluded endpoint."""
    chosen, prob, reason = explore.draw("box", ["box", "alt"], 0.999, random.Random(1))
    assert chosen in ("box", "alt")
    assert 0.0 < prob <= 1.0


def test_draw_two_arms_at_rate_0_05_gives_propensities_0_95_and_0_05_not_0_975_and_0_025():
    """The contract's own corrected example, and the sharpest arithmetic test in this file: with ONE alternative
    (k=1), the deterministic arm's propensity is `1 - rate = 0.95` and the alternative's is `rate / k = 0.05`. An
    implementation that spreads the exploration rate over ALL arms including the incumbent -- the contract's own
    named defect -- would instead compute `(1 - rate) + rate / (k + 1) = 0.975` for the deterministic arm and
    `rate / (k + 1) = 0.025` for the alternative. Both branches below are pinned to their EXACT value, not merely
    "close to" or "less than 1" -- whichever arm a given seed draws, the buggy mechanism's number for that arm
    disagrees with the correct one, so this test fails against either arm's outcome under the bug."""
    chosen, prob, reason = explore.draw("box", ["box", "alt"], 0.05, random.Random(7))
    assert reason == "explored" or chosen == "box"
    if chosen == "box":
        assert prob == pytest.approx(0.95)
    else:
        assert chosen == "alt"
        assert prob == pytest.approx(0.05)


def test_draw_three_arms_at_rate_0_05_gives_propensities_0_95_and_0_025_each():
    """The three-arm case the contract calls out by name: the first draft's own worked example (0.95 and 0.025)
    is only internally consistent with k=2 alternatives (`rate / k = 0.05 / 2 = 0.025`), not with one. Whichever
    of the three ids a seed draws, its propensity must be exactly 0.95 (the deterministic arm) or exactly 0.025
    (either alternative) -- both values pinned precisely, so a `rate / (k+1) = 0.05/3 = 0.0167`-style bug (spread
    over all three arms) disagrees with this test no matter which id was drawn."""
    chosen, prob, reason = explore.draw("box", ["box", "alt1", "alt2"], 0.05, random.Random(3))
    if chosen == "box":
        assert prob == pytest.approx(0.95)
    else:
        assert chosen in ("alt1", "alt2")
        assert prob == pytest.approx(0.025)


def test_draw_alternative_propensities_and_deterministic_propensity_sum_to_one():
    """A cross-check on the arithmetic above that does not depend on which arm was drawn at all: for any single
    draw, the returned propensity is the CHOSEN arm's -- but the mechanism's own accounting must still be
    internally consistent. Verified across many seeds landing on both arms of a 2-arm draw, so a bug that only
    shows up for one arm's branch cannot hide behind a seed that happens to avoid it.

    2,000 seeds, not 30: at rate 0.05 the probability of a correct mechanism never landing on the alternative in 30
    draws is 0.95**30 = 21.5%, and the first seed (starting from 0) that does land on it is 31 -- one past a
    30-seed loop's end. An earlier version of this test used 30 and failed one run in five against a CORRECT
    mechanism, for a reason that had nothing to do with a defect. 2,000 seeds also makes the realised alternative
    share a meaningful check on its own: asserted within 0.02 of 0.05 below, which is what actually separates the
    two mechanisms empirically -- spreading the rate over all arms including the incumbent gives the alternative a
    realised share near 0.025, and a test that only checks both arms were reached at all (never mind how often)
    passes against either mechanism."""
    seen = set()
    alt_count = 0
    n = 2000
    for seed in range(n):
        chosen, prob, _ = explore.draw("box", ["box", "alt"], 0.05, random.Random(seed))
        seen.add(chosen)
        if chosen == "alt":
            alt_count += 1
        expected = 0.95 if chosen == "box" else 0.05
        assert prob == pytest.approx(expected)
    assert seen == {"box", "alt"}, f"{n} seeds never landed on both arms of a 5% draw -- fixture is not exercising the draw at all"
    share = alt_count / n
    assert abs(share - 0.05) < 0.02, (
        f"realised alternative share {share:.4f} over {n} draws is not within 0.02 of the declared rate 0.05 -- "
        "this is the number that would read ~0.025 under a mechanism that spreads the rate over all arms "
        "including the incumbent, which the per-draw exact-value assertions above catch too, but this is the "
        "empirical signature named in amendment 6's integration note"
    )


# ======================================================================================================
# record.Decision: exploration_reason / eligible_set, and S4's version rule
# ======================================================================================================


def _cand_row(cid="box", why="chosen", bound=0.90, cost=0.004):
    return {"id": cid, "excluded_because": why, "bound": bound, "bound_kind": "lcb95", "cost_usd": cost,
           "evidence_as_of": "2026-09-01"}


def _v2_row(**kw):
    """A row shaped like something a v0.2.0 writer produces -- C1's full shape plus C3's two new fields, both
    present and well-formed by default so a test exercising ONE omission does not also trip C1's own required-field
    refusals (amendment 3's fixture-isolation rule)."""
    base = {
        "family": "agentic-coding", "request_id": "r1", "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": [_cand_row(), _cand_row("api", "below_floor", 0.70, 0.012)], "chosen": "box",
        "selection_probability": 1.0, "exploration": False, "certified": True,
        "policy_version": "p1", "mechanism_version": "0.2.0", "agent": "opencode", "model": "m",
        "endpoint": "http://e", "gateway_quote_usd": 0.004, "gateway_authorised": True, "decided_at": DECIDED_AT,
        "gaps": [], "label_state": "pending", "label": None, "outcome": {},
        "schema_version": 2, "exploration_reason": "no_mechanism", "eligible_set": [],
    }
    base.update(kw)
    return base


def test_from_row_reads_no_mechanism_and_empty_eligible_set_for_a_real_v010_line():
    """S4's positive case, against the real fixture the contract asks for by name (not a hand-typed stand-in): a
    genuine v0.1.0 line has no `exploration_reason` or `eligible_set` key at all, and `from_row` must supply
    `no_mechanism` and `[]` for a row at `schema_version == 1` -- not raise `Incomplete`, which is exactly the
    regression amendment 5 exists to prevent (C3's two fields, added without a default, reintroducing C1's own
    launch blocker one release later)."""
    d, ignored = rec.from_row(_real_v010_row())
    assert d.schema_version == 1
    assert d.exploration_reason == "no_mechanism"
    assert d.eligible_set == []
    assert ignored == []


def test_from_row_reads_no_mechanism_and_empty_eligible_set_for_a_hand_built_v1_row():
    """The same clause against a row this file controls, so the boundary case (a v1 row that also happens to be
    missing OTHER v2-only fields) is exercised directly rather than only through one fixed real-world example."""
    row = _v2_row()
    row["schema_version"] = 1
    del row["exploration_reason"]
    del row["eligible_set"]
    d, ignored = rec.from_row(row)
    assert d.schema_version == 1
    assert d.exploration_reason == "no_mechanism"
    assert d.eligible_set == []


def test_from_row_v2_row_missing_exploration_reason_raises_incomplete_naming_the_field():
    """S4's negative case, and the one a dataclass default would have made silent (amendment 5's own reasoning): a
    v0.2.0 writer that forgot to stamp `exploration_reason` must be caught at read time, loudly, naming the field
    -- not read as `no_mechanism`, which is indistinguishable from a mechanism that was genuinely never installed
    and would corrupt the count this release reports."""
    row = _v2_row()
    del row["exploration_reason"]
    with pytest.raises(rec.Incomplete, match="exploration_reason"):
        rec.from_row(row)


def test_from_row_v2_row_missing_eligible_set_raises_incomplete_naming_the_field():
    """The same treatment, for the field amendment 5 says gets it too: "the same treatment applies to
    `eligible_set`, whose version 1 value is the empty list.\""""
    row = _v2_row()
    del row["eligible_set"]
    with pytest.raises(rec.Incomplete, match="eligible_set"):
        rec.from_row(row)


def test_a_written_decision_carries_the_reason_and_the_eligible_set_it_was_drawn_over():
    """The positive case for a decision built the way a writer builds one (not via `from_row`): `exploration_reason`
    is one of the four closed values, and `eligible_set` is the list `draw` was actually run over, "so the
    propensity can be checked rather than reconstructed" -- catches a writer that omits either field or invents a
    fifth reason outside the closed set."""
    base = _v2_row(exploration_reason="explored", eligible_set=["box", "alt"])
    candidates = [rec.Candidate(**c) for c in base["candidates"]]
    kw = {k: v for k, v in base.items() if k not in ("candidates", "schema_version")}
    kw["candidates"] = candidates
    d = rec.Decision(**kw)
    assert d.exploration_reason == "explored"
    assert d.eligible_set == ["box", "alt"]


@pytest.mark.parametrize("reason", ["explored", "no_eligible_arm", "rate_zero", "no_mechanism"])
def test_every_contracted_exploration_reason_is_a_legal_value_on_a_written_decision(reason):
    """The closed vocabulary itself: all four values the contract names must be constructible, catching an
    implementation that narrows the set (e.g. refusing `no_mechanism` on a freshly-written v0.2.0 record) or that
    never actually restricts it at all (see the next test for that direction)."""
    base = _v2_row(exploration_reason=reason, eligible_set=[])
    candidates = [rec.Candidate(**c) for c in base["candidates"]]
    kw = {k: v for k, v in base.items() if k not in ("candidates", "schema_version")}
    kw["candidates"] = candidates
    d = rec.Decision(**kw)
    assert d.exploration_reason == reason


# ======================================================================================================
# config.FamilyDeclaration.staleness_limit_days (amendment 5.1)
# ======================================================================================================


_SENTINEL = object()


def _family(*, reference="ref", floor=0.5, label_source="human_label", max_label_latency_s=_SENTINEL,
           label_independent_of_candidate=True, staleness_limit_days=_SENTINEL, exploration_rate=None) -> dict:
    """One family's declaration, C4's shape plus C3's `staleness_limit_days`, all otherwise well-formed --
    mirroring `test_label_declaration.py`'s own `_family_c4` helper and its fixture-isolation reasoning: every
    field a test is not deliberately exercising defaults to a legal value, so a test of one refusal cannot also
    trip another by accident."""
    if max_label_latency_s is _SENTINEL:
        max_label_latency_s = None if label_source == "none" else 3600.0
    if staleness_limit_days is _SENTINEL:
        staleness_limit_days = 30.0
    d = {
        "reference": reference, "floor": floor,
        "label_source": label_source, "max_label_latency_s": max_label_latency_s,
        "label_independent_of_candidate": label_independent_of_candidate,
        "staleness_limit_days": staleness_limit_days,
        "tenant_scope": "single",
    }
    if exploration_rate is not None:
        d["exploration_rate"] = exploration_rate
    return d


def _candidates_file(*, families: dict) -> dict:
    return {
        "config_format": 2,
        "candidates": {
            "ref": {"deployment": "api",
                    "endpoint": {"base_url": "https://x/v1", "model": "m"},
                    "price_per_mtok": {"fresh_in": 1.0, "cached_in": 0.1, "out": 5.0}},
        },
        "families": families,
        "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.15}}},
    }


def _write_config(tmp_path, body: dict) -> Path:
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps(body))
    return p


def _load(tmp_path, family: dict):
    return load_config(_write_config(tmp_path, _candidates_file(families={"f": family})))


def test_a_family_omitting_staleness_limit_days_is_refused_naming_the_family_and_the_field(tmp_path):
    """Amendment 5.1: "refused when absent, like C4's three [fields]" -- the fourth append to the same object,
    same refusal shape. Every other field is well-formed, so this is the only refusal that can fire."""
    fam = _family()
    del fam["staleness_limit_days"]
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, fam)
    msg = str(excinfo.value)
    assert "f" in msg and "staleness_limit_days" in msg


def test_a_family_with_a_null_staleness_limit_and_no_exploration_rate_loads(tmp_path):
    """The legal half of amendment 5.1's pairing rule: "`null` is a legitimate declaration meaning no limit" on its
    own, with no `exploration_rate` present to collide with it. Needed as a baseline for the refusal test below --
    without it, that test could not tell "null is always refused" apart from "null is refused only in combination"."""
    fam = _family(staleness_limit_days=None)
    cfg = _load(tmp_path, fam)
    assert cfg.families["f"].staleness_limit_days is None


def test_a_family_with_a_numeric_staleness_limit_and_an_exploration_rate_loads(tmp_path):
    """The legal half of the OTHER direction: a declared numeric limit coexists with `exploration_rate` -- the one
    combination amendment 5.1 says is fine ("a family may decline to state a limit OR may explore, not both"
    implies the fourth combination, numeric-limit-plus-rate, is exactly the one that is allowed)."""
    fam = _family(staleness_limit_days=45.0, exploration_rate=0.05)
    cfg = _load(tmp_path, fam)
    assert cfg.families["f"].staleness_limit_days == 45.0
    assert cfg.families["f"].exploration_rate == 0.05


def test_a_family_with_null_staleness_limit_and_an_exploration_rate_is_refused_naming_both(tmp_path):
    """The refusal itself, in the words of the contract: "`null` ... is refused in combination with an
    `exploration_rate`, because the door C3 opens exists to reach a candidate whose evidence expired, so an
    unbounded staleness there is a bound from any past environment at all." Every other field here is well-formed
    (a real labeller, independent, a legal reference) so this refusal cannot be confused with a C4 refusal firing
    instead -- the fixture-isolation rule this release states as a general obligation."""
    fam = _family(staleness_limit_days=None, exploration_rate=0.05)
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, fam)
    msg = str(excinfo.value)
    assert "staleness_limit_days" in msg and "exploration_rate" in msg


def test_a_family_with_a_numeric_staleness_limit_and_no_exploration_rate_loads(tmp_path):
    """The fourth combination, completing the 2x2 amendment 5.1 describes: a numeric limit with no rate at all
    must load -- catches an implementation that conflates "has a rate" with "must have a rate" and refuses a
    family for merely being capable of one."""
    fam = _family(staleness_limit_days=45.0)
    cfg = _load(tmp_path, fam)
    assert cfg.families["f"].staleness_limit_days == 45.0
    assert cfg.families["f"].exploration_rate is None


# ======================================================================================================
# accept.floor_compliance: two rates
# ======================================================================================================


def _acc_cand(cid="box", why="chosen", bound=0.90, cost=0.004):
    return {"id": cid, "excluded_because": why, "bound": bound, "bound_kind": "lcb95", "cost_usd": cost,
           "evidence_as_of": "2026-09-01"}


def _acc_dec(rid="r1", certified=True, chosen="box", candidates=None):
    return {
        "family": "agentic-coding", "request_id": rid, "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": candidates or [_acc_cand(), _acc_cand("api", "below_floor", 0.70, 0.012)], "chosen": chosen,
        "selection_probability": 1.0, "exploration": False, "certified": certified,
        "policy_version": "p1", "mechanism_version": "0.1.0", "agent": "opencode", "model": "m",
        "endpoint": "http://e", "gateway_quote_usd": 0.004, "gateway_authorised": True, "decided_at": DECIDED_AT,
        "gaps": [], "label_state": "pending", "label": None, "outcome": {},
    }


def test_floor_compliance_numbers_gains_served_labelled_and_served_rate(tmp_path):
    """The contract's own words, checked at the level of the guaranteed key names: "`numbers` gains
    `served_labelled` and `served_rate`". Ten certified successes and no uncertified traffic at all, so this test
    alone cannot distinguish the two rates being equal by construction from the mechanism genuinely reporting two
    separate numbers -- that distinction is the next test's job."""
    rows = [_acc_dec(rid=f"r{i}") for i in range(10)]
    outcomes = {f"r{i}": {"label_state": "labelled", "label": True} for i in range(10)}
    v = ac.floor_compliance(rows, outcomes, floor=0.80)
    assert "served_labelled" in v.numbers
    assert "served_rate" in v.numbers


def test_floor_compliance_certified_and_all_served_rates_differ_when_uncertified_traffic_fares_worse(tmp_path):
    """The test amendment 5's own reasoning demands: "two rates that are always equal would pass a test that only
    checks both keys exist." Ten certified decisions, all successful (certified rate 100%); five MORE decisions
    that were served but NOT certified, mostly unsuccessful (2 of 5). The certified-only rate must stay 100% --
    unaffected by traffic the floor was never claimed for -- while the all-served rate must fall to reflect all 15,
    a real and different number, not a copy of the certified one."""
    certified_rows = [_acc_dec(rid=f"c{i}", certified=True) for i in range(10)]
    uncertified_rows = [
        _acc_dec(rid=f"u{i}", certified=False, chosen="fallback",
                candidates=[_acc_cand("fallback", "chosen", 0.50), _acc_cand("box", "not_priced", 0.95)])
        for i in range(5)
    ]
    rows = certified_rows + uncertified_rows
    outcomes = {f"c{i}": {"label_state": "labelled", "label": True} for i in range(10)}
    outcomes.update({f"u{i}": {"label_state": "labelled", "label": i < 2} for i in range(5)})
    v = ac.floor_compliance(rows, outcomes, floor=0.80)
    certified_rate = v.numbers["rate"]
    served_rate = v.numbers["served_rate"]
    assert certified_rate == pytest.approx(1.0)
    assert served_rate == pytest.approx(12 / 15)
    assert served_rate != certified_rate, (
        "the two rates coincided on a fixture built specifically so they should not -- either the all-served rate "
        "is a copy of the certified one, or it is not counting the uncertified traffic at all"
    )
    assert v.numbers["served_labelled"] == 15


def test_floor_compliance_overall_verdict_is_the_worse_of_the_two_sub_verdicts(tmp_path):
    """Amendment 6: `floor_compliance` stays ONE verdict rather than splitting into two -- SCOPE section 12 names
    nine criteria, and a split would silently move `accept.CRITERIA` to ten, diverging from the governing document
    over a presentation choice. The two rates, their two bounds and their two sub-verdicts live in `numbers`; the
    criterion's OWN `.verdict` is the WORSE of the two.

    Built so the two halves disagree hard, not just numerically: 30 certified successes clear the floor with room
    to spare (a 95% lower bound around 90%), and 30 further SERVED-but-uncertified decisions, all unsuccessful,
    drag the all-served rate to 50% against an 80% floor -- far enough below that no confidence bound rescues it.
    A criterion that reported PASS here, because the certified half alone would pass, is exactly the defeat F8
    describes, reintroduced through the *report* instead of the *definition*: uncertified traffic quietly
    excluded from the number a reader actually looks at."""
    certified_rows = [_acc_dec(rid=f"c{i}", certified=True) for i in range(30)]
    uncertified_rows = [
        _acc_dec(rid=f"u{i}", certified=False, chosen="fallback",
                candidates=[_acc_cand("fallback", "chosen", 0.50), _acc_cand("box", "not_priced", 0.95)])
        for i in range(30)
    ]
    rows = certified_rows + uncertified_rows
    outcomes = {f"c{i}": {"label_state": "labelled", "label": True} for i in range(30)}
    outcomes.update({f"u{i}": {"label_state": "labelled", "label": False} for i in range(30)})
    v = ac.floor_compliance(rows, outcomes, floor=0.80)
    assert v.numbers["rate"] == pytest.approx(1.0)          # the certified half, alone, clearly clears the floor
    assert v.numbers["served_rate"] == pytest.approx(0.5)   # the all-served half does not, by a wide margin
    assert v.verdict == ac.FAIL, (
        f"certified alone would PASS (rate 100%, well clear of an 80% floor) and all-served alone FAILs (rate "
        f"50%); the combining rule says the criterion's own verdict is the worse of the two, which is FAIL -- "
        f"got {v.verdict!r}, which is what a criterion that reports the certified half's verdict alone would give"
    )


# ======================================================================================================
# Amendment 6 -- an arm reached through the expiry override is served but uncertified
# ======================================================================================================
#
# The code author's integration report, quoted in the coordinator's message: `explore.clears_floor` said
# `(True, "eligible")` for an arm `record.admissible` refused as `(False, "evidence_expired")`, and
# `check_certification` correctly flagged the resulting `certified=True` row as a false certification. Root cause
# was in SCOPE, not the contract: section 2 had listed admissibility as three conditions while `record.admissible`
# has enforced four (freshness) since v0.1.0; SCOPE now carries the fourth clause. The resolution the tests below
# pin: `certified` is decided from FULL admissibility, freshness included, never from `explore.eligible`'s
# verdict -- the two answer different questions (is this arm reachable by exploration at all, versus does this
# specific assignment meet every condition needed to trust it right now) and can disagree on the same candidate.
#
# These tests work at the record/accept layer -- constructing the row a correct writer produces and checking it
# against `record.admissible`, `accept.no_false_certification`, `accept.default_is_not_a_hiding_place` and
# `accept.floor_compliance` -- rather than through whatever function in `serve.py` now wires `explore.draw`'s
# output into a `Decision`. That wiring is not named in C3's interface section, and reaching it would mean reading
# the code author's own integration work, which the split keeps this file blind to. Every one of amendment 6's
# six requirements is, however, fully checkable at this layer: "the recorded decision", "check_certification",
# "default_is_not_a_hiding_place" and "floor_compliance" are all record/accept-level objects and functions.

FLOOR = 0.80
MAX_EVIDENCE_AGE_DAYS = 30.0     # the ordinary expiry ratchet -- record.admissible's fourth condition
STALENESS_LIMIT_DAYS = 60.0      # C3's per-family override limit
STALE_AGE_DAYS = 40.0            # past MAX_EVIDENCE_AGE_DAYS, inside STALENESS_LIMIT_DAYS

# C6 derives each candidate's age from its own `evidence_as_of` against the decision's `decided_at`, so these two
# have to agree. The earlier fixtures paired `decided_at: 1000.0` -- the epoch, 1970 -- with a 2026 evidence date,
# which is a negative age: readable only because nothing consulted it. Both are now computed from one anchor, so the
# ages below are what they say regardless of when the suite runs.
_ANCHOR = _dt.datetime(2026, 9, 10, tzinfo=_dt.timezone.utc)
DECIDED_AT = _ANCHOR.timestamp()


def _as_of(age_days: float) -> str:
    return (_ANCHOR - _dt.timedelta(days=age_days)).date().isoformat()



def _stale_candidate():
    return rec.Candidate(id="stale_box", excluded_because="chosen", bound=0.90, cost_usd=0.01,
                         evidence_as_of=_as_of(STALE_AGE_DAYS))


def _draw_into_stale_arm(rate=0.99, tries=50):
    """Run the REAL `explore.draw`, at a rate high enough that the alternative is drawn nearly every time, until it
    actually lands on `stale_box` -- so items 1 and 2 below exercise the genuine composition (`draw` decides
    `chosen`; `record.admissible`, given full freshness data, decides `certified`; neither function is given the
    other's output) instead of a hand-picked dict, which would assert on values this file chose and would pass
    unconditionally regardless of what any implementation does. At `rate=0.99` the alternative's propensity is
    0.99, so the loop is a robustness margin against the rare seed that lands on the deterministic arm, not the
    mechanism the test is checking."""
    for seed in range(tries):
        chosen, prob, reason = explore.draw("reference", ["reference", "stale_box"], rate, random.Random(seed))
        if chosen == "stale_box":
            return chosen, prob, reason
    raise AssertionError(f"no seed among the first {tries} landed on the alternative at rate={rate} -- fixture "
                         f"problem, not a defect in the mechanism under test")


def _explored_into_stale_arm_row(rid="exp1"):
    """The row amendment 6 is about, with `chosen` and `certified` computed the same way items 1 and 2 compute
    them -- `explore.draw` decides `chosen`, `record.admissible` (with full freshness data) decides `certified` --
    so the fixture used by items 3-5 is built by the same rule those two tests verify, not by a second, independent
    hand-typed guess at what the row should look like.

    The reference/default candidate is its own, separately non-admissible candidate (below the floor, for a
    reason that has nothing to do with freshness) so that `check_certification`'s scan over every candidate does
    not stumble on an incidental hiding place -- nothing in this candidate set is admissible, which is the
    realistic shape of the case the expiry override exists for: A3's ratchet describes a family with NO fresh
    admissible option, which is exactly why reaching the stale one mattered enough to specify."""
    chosen, prob, _reason = _draw_into_stale_arm()
    certified, _why = rec.admissible(_stale_candidate(), floor=FLOOR, authorised=True, latency_feasible=True,
                                     evidence_age_days=STALE_AGE_DAYS, max_age_days=MAX_EVIDENCE_AGE_DAYS)
    return {
        "family": "agentic-coding", "request_id": rid, "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": [
            {"id": "stale_box", "excluded_because": "chosen", "bound": 0.90, "bound_kind": "lcb95",
             "cost_usd": 0.01, "evidence_as_of": _as_of(STALE_AGE_DAYS)},
            {"id": "reference", "excluded_because": "below_floor", "bound": 0.60, "bound_kind": "lcb95",
             "cost_usd": 0.004, "evidence_as_of": _as_of(5.0)},
        ],
        "chosen": chosen,
        "selection_probability": prob, "exploration": True, "certified": certified,
        "policy_version": "p1", "mechanism_version": "0.2.0", "agent": "opencode", "model": "m",
        "endpoint": "http://e", "gateway_quote_usd": 0.01, "gateway_authorised": True, "decided_at": DECIDED_AT,
        "gaps": [], "label_state": "pending", "label": None, "outcome": {},
        "schema_version": 2, "exploration_reason": "explored", "eligible_set": ["stale_box", "reference"],
    }


def _explored_into_fresh_arm_row(rid="exp2"):
    """Amendment 6's mirror positive (item 6): an explored arm that happens to be fresh and fully admissible --
    not past `max_evidence_age_days` at all, authorised, latency feasible, priced, above the floor."""
    return {
        "family": "agentic-coding", "request_id": rid, "feature_vector_version": "fv1", "state_ref": "obs:a",
        "candidates": [
            {"id": "fresh_alt", "excluded_because": "chosen", "bound": 0.90, "bound_kind": "lcb95",
             "cost_usd": 0.01, "evidence_as_of": _as_of(5.0)},
            {"id": "reference", "excluded_because": "below_floor", "bound": 0.60, "bound_kind": "lcb95",
             "cost_usd": 0.004, "evidence_as_of": _as_of(5.0)},
        ],
        "chosen": "fresh_alt",
        "selection_probability": 0.05, "exploration": True, "certified": True,
        "policy_version": "p1", "mechanism_version": "0.2.0", "agent": "opencode", "model": "m",
        "endpoint": "http://e", "gateway_quote_usd": 0.01, "gateway_authorised": True, "decided_at": DECIDED_AT,
        "gaps": [], "label_state": "pending", "label": None, "outcome": {},
        "schema_version": 2, "exploration_reason": "explored", "eligible_set": ["fresh_alt", "reference"],
    }


def test_amendment_6_clears_floor_and_admissible_genuinely_disagree_on_the_stale_candidate():
    """Fixture precondition for items 1 and 2, run as its own test rather than a silent helper: without this, a
    future edit to `FLOOR`/`MAX_EVIDENCE_AGE_DAYS`/`STALENESS_LIMIT_DAYS`/`STALE_AGE_DAYS` that accidentally closed
    the divergence between `explore.clears_floor` and `record.admissible` would make items 1 and 2 pass vacuously
    -- correct output for a scenario that no longer exercises the override at all -- rather than failing loudly at
    the fixture that stopped meaning what it claims to."""
    stale = _stale_candidate()
    clears, why = explore.clears_floor(stale, FLOOR, staleness_limit_days=STALENESS_LIMIT_DAYS,
                                       evidence_age_days=STALE_AGE_DAYS)
    assert (clears, why) == (True, "eligible")
    ok, reason = rec.admissible(stale, floor=FLOOR, authorised=True, latency_feasible=True,
                                evidence_age_days=STALE_AGE_DAYS, max_age_days=MAX_EVIDENCE_AGE_DAYS)
    assert (ok, reason) == (False, "evidence_expired")


def test_amendment_6_explored_assignment_past_max_evidence_age_but_inside_staleness_limit_is_uncertified():
    """Item 1: assert on the RECORDED decision, not on a predicate. `certified` is computed here by
    `record.admissible`, called with the REAL freshness data (`evidence_age_days=40`, `max_age_days=30`) on the
    candidate the REAL `explore.draw` actually chose (see `_draw_into_stale_arm`) -- not by this file asserting a
    value it picked for itself. The composition -- draw decides which arm, admissible (freshness included) decides
    whether it is trusted -- is what the row that ought to be written carries: `certified: False`, not because the
    exploration override says so (it does not; it only says the arm was reachable), but because the arm's evidence
    is genuinely past the family's ordinary limit."""
    chosen, _prob, _reason = _draw_into_stale_arm()
    certified, why = rec.admissible(_stale_candidate(), floor=FLOOR, authorised=True, latency_feasible=True,
                                    evidence_age_days=STALE_AGE_DAYS, max_age_days=MAX_EVIDENCE_AGE_DAYS)
    assert chosen == "stale_box"
    assert (certified, why) == (False, "evidence_expired")


def test_amendment_6_the_same_explored_assignment_is_still_served_by_the_stale_arm_not_the_default():
    """Item 2, the sharpest test in the group. `chosen` is decided by `explore.draw` alone, run for real above;
    `certified` is decided by `record.admissible` alone, on the same candidate, with neither function given the
    other's output as an input. If a real implementation "solved" the false-certification bug by making
    eligibility (or certification) gate SERVING itself -- declining to draw an arm whose full admissibility later
    fails -- `draw` would refuse to land on `stale_box` at all, and this test, which asserts on `draw`'s own
    output independent of what `admissible` says about the same candidate, is the one that would catch it: the
    expiry override would be re-closed and A3's ratchet would be back -- an arm nobody routes to is never
    labelled, so it can never re-earn a fresh bound and is locked out forever, which is the exact failure C3
    exists to open a door out of. The test above, which only checks `certified is False`, passes against that
    broken mechanism too if `chosen` silently fell back to `reference` -- this is the one that would not."""
    chosen, _prob, _reason = _draw_into_stale_arm()
    assert chosen == "stale_box"
    assert chosen != "reference"
    certified, _why = rec.admissible(_stale_candidate(), floor=FLOOR, authorised=True, latency_feasible=True,
                                     evidence_age_days=STALE_AGE_DAYS, max_age_days=MAX_EVIDENCE_AGE_DAYS)
    assert certified is False  # both facts hold about the SAME assignment; neither computation depended on the other


def test_amendment_6_check_certification_falls_silent_on_the_explored_uncertified_row():
    """Item 3: the falsifier (`accept.no_false_certification`, section 12's own name for it) must fall silent on
    the corrected behaviour. The code author's integration report quoted the exact violation this used to raise --
    "certified but the chosen candidate 'box' was not admissible: evidence_expired" -- which could only fire while
    `certified` was wrongly True. Here it is correctly False, so that specific violation cannot occur regardless of
    freshness data; this test is what proves NOTHING else does either, which is the evidence the fix landed at the
    source rather than in the falsifier itself.

    `evidence_age_days`/`max_age_days` are passed through explicitly, matching `record.check_certification`'s own
    keyword names -- a reconstruction, since amendment 6's message does not state whether
    `no_false_certification`/`default_is_not_a_hiding_place`/`check_all` gained these keywords or compute
    per-candidate freshness some other way. It is not a free-standing guess: the code author's own bug report
    could only have observed `evidence_expired` as a violation reason if SOME call path already threads this data
    into `check_certification`, and `evidence_age_days`/`max_age_days` are the names that call already uses."""
    row = _explored_into_stale_arm_row()
    v = ac.no_false_certification([row], floor=FLOOR, latency_feasible=True,
                                  max_age_days=MAX_EVIDENCE_AGE_DAYS)
    assert v.verdict == ac.PASS
    assert v.numbers.get("violations", 0) == 0


def test_amendment_6_default_is_not_a_hiding_place_also_falls_silent_on_the_explored_uncertified_row():
    """Item 4: an interaction nobody had named before the code author's report. `default_is_not_a_hiding_place`
    flags an uncertified decision made while an admissible candidate existed; here the chosen candidate is not
    admissible (evidence_expired, once freshness is actually consulted -- see the reconstruction note on the test
    above) and the fixture's reference candidate is not admissible either -- so nothing in the candidate set is
    admissible, and the rule must stay silent rather than accuse the mechanism of hiding behind the default when
    there was no admissible option to hide from.

    Without `evidence_age_days`/`max_age_days` passed through, `admissible` cannot see the freshness condition at
    all (it is a no-op when either is `None`) and would misjudge the stale chosen candidate as admissible on bound
    and authorisation alone -- which is precisely the wrong answer this test exists to rule out, and exactly what
    happens if this keyword-threading reconstruction turns out to be wrong: this test fails loudly (a spurious
    "hiding place" verdict) rather than silently passing for an unrelated reason."""
    row = _explored_into_stale_arm_row()
    v = ac.default_is_not_a_hiding_place([row], floor=FLOOR, latency_feasible=True,
                                         max_age_days=MAX_EVIDENCE_AGE_DAYS)
    assert v.verdict != ac.FAIL
    assert "hiding place" not in v.detail


def test_amendment_6_explored_uncertified_row_counts_in_all_served_and_not_in_certified():
    """Item 5: the test that keeps F8 closed. F8's objection to "uncertified by construction" was that it removes
    traffic from `floor_compliance`'s denominator; the two-rate report is the answer, and this is the test that
    verifies the traffic actually lands where the answer says it does. Ten ordinary certified successes, plus this
    one explored-and-uncertified row labelled a failure: the certified rate must stay exactly what it was without
    it (10 labelled, rate 100%), while `served_labelled` must read 11 and the all-served rate must reflect the
    failure -- if this row were silently dropped instead of counted in `all_served`, `served_labelled` would still
    read 10 and the two rates would coincide, which is precisely the gap this test is built to catch."""
    certified_rows = [_acc_dec(rid=f"c{i}", certified=True) for i in range(10)]
    explored_row = _explored_into_stale_arm_row(rid="exp1")
    rows = certified_rows + [explored_row]
    outcomes = {f"c{i}": {"label_state": "labelled", "label": True} for i in range(10)}
    outcomes["exp1"] = {"label_state": "labelled", "label": False}
    v = ac.floor_compliance(rows, outcomes, floor=FLOOR)
    assert v.numbers["labelled"] == 10 and v.numbers["rate"] == pytest.approx(1.0)
    assert v.numbers["served_labelled"] == 11
    # abs=5e-5, not a bare pytest.approx: accept.py rounds every reported rate to four places (and has since
    # v0.1.0), and 10/11 = 0.909090... rounds to 0.9091, a ~9.09e-6 difference that a default relative tolerance
    # (~9e-7 here) is tighter than the artifact's own precision -- failing against a correct implementation.
    assert v.numbers["served_rate"] == pytest.approx(10 / 11, abs=5e-5)


def test_amendment_6_explored_assignment_into_a_fresh_admissible_arm_is_certified():
    """Item 6, the mirror positive amendment 6 names explicitly. Without this test, an implementation that simply
    never certifies an explored assignment -- the "uncertified by construction" position C3's own interface
    section rejects by name (F8) -- would pass every negative test above. A fresh arm, above the floor, with
    authorisation and latency otherwise holding: `certified` must be True, and the falsifier must have nothing to
    say about it."""
    fresh = rec.Candidate(id="fresh_alt", excluded_because="chosen", bound=0.90, cost_usd=0.01,
                          evidence_as_of=_as_of(5.0))
    ok, reason = rec.admissible(fresh, floor=FLOOR, authorised=True, latency_feasible=True,
                                evidence_age_days=5.0, max_age_days=MAX_EVIDENCE_AGE_DAYS)
    assert (ok, reason) == (True, "chosen"), "fixture sanity check: this candidate must be fully admissible"
    row = _explored_into_fresh_arm_row()
    assert row["certified"] is True
    v = ac.no_false_certification([row], floor=FLOOR, latency_feasible=True,
                                  max_age_days=MAX_EVIDENCE_AGE_DAYS)
    assert v.verdict == ac.PASS


# ======================================================================================================
# Amendment 6, corrected: the fix is in route_once's WIRING, not in either function it calls
# ======================================================================================================
#
# The section above composed `explore.draw` and `record.admissible` independently and asserted on their outputs
# directly -- a real improvement over asserting on values this file picked itself, but it moved the subject. The
# defect amendment 6 fixes was never in either function: it was in `serve.route_once` reading the WRONG one of
# them when deciding `certified` for an explored assignment. Confirmed by reverting the fix -- replacing the
# full-admissibility call with a hardcoded `certified = True` in `route_once`'s explored branch -- and finding
# every test in the section above still passed, because a test of both halves separately passes against any
# wiring between them, including none at all. Every test below goes THROUGH `route_once`.
#
# The helper shapes mirror `tests/test_serve.py`'s own `policy()`/`obs()`/`route()` fixtures (see that file) rather
# than being assembled from `route_once`'s signature from scratch, per the coordinator's own instruction: an
# observation or policy built by hand tends to be built wrong in a way that hides in a passing test. The three new
# keywords below -- `exploration_rate`, `staleness_limit_days`, `rng` -- are not independently verified against a
# published interface section; they are the names the coordinator's own instructions use verbatim to describe this
# gap ("route_once with exploration_rate=0", "a state where ... inside staleness_limit_days", "drive it with a
# seeded rng"), so this file treats them as given rather than reconstructed.


def _rt_policy(certified=True, domain=None):
    """Same shape as `tests/test_serve.py`'s `policy()`: box below a capacity bound, api above it, api the
    declared default."""
    return dc.Policy(
        family="agentic-coding",
        rules=(
            dc.Rule(guards=(dc.Guard(var="inflight:box", op="<", threshold=8.0,
                                     derived_from="a measured capacity bound"),),
                    assign=("box",), because="the reserved candidate has a free seat"),
            dc.Rule(guards=(dc.Guard(var="inflight:box", op=">=", threshold=8.0,
                                     derived_from="a measured capacity bound"),),
                    assign=("api",), because="the reserved candidate is full"),
        ),
        default=("api",),
        domain=domain or {"inflight:box": (0.0, 128.0)},
        certified=certified,
        note="a fixture",
    )


def _rt_obs(**state):
    """Same shape as `tests/test_serve.py`'s `obs()`: a candidate's quantities are qualified with `:box`, the
    family's (`metered_authorised`, `evidence_age_days`) are not."""
    o = ob.Observation(candidate="box")
    for k, v in state.items():
        key = f"{k}:box" if k in ob.PER_CANDIDATE else k
        o.state[key] = v
        o.readings[key] = ob.Reading(value=v, as_of=1000.0, source="a fixture")
    return o


def _rt_route(o, pol=None, **kw):
    """Same base kwargs as `tests/test_serve.py`'s `route()`, with `floor`/`latency_feasible` filled in (needed
    for `explore.eligible`'s admissibility check, unused by the pre-C3 tests that helper serves) and whatever
    exploration keywords a caller supplies via `**kw`."""
    base = dict(policy=pol or _rt_policy(), observation=o, request_id="r1", feature_vector_version="fv1",
               policy_version="p1", mechanism_version="0.2.0", agent="opencode", model="m",
               endpoint="http://e", gateway_quote_usd=0.004, bounds={"box": 0.90, "api": 0.70},
               costs={"box": 0.01, "api": 0.012}, evidence_as_of=_as_of(STALE_AGE_DAYS), floor=FLOOR,
               latency_feasible=True, max_age_days=MAX_EVIDENCE_AGE_DAYS)
    base.update(kw)
    return sv.route_once(**base)


def _rt_route_into_stale_arm(tries=50, rate=0.999):
    """Loop seeded rngs until `route_once` actually draws the stale arm -- the same robustness pattern as
    `_draw_into_stale_arm` earlier in this file: deterministic and reproducible across runs (the same seeds are
    tried in the same fixed order every time, so a given implementation either always finds one within the loop
    or never does), not a flaky "sometimes explores" test. `box` is full (`inflight=20`) so the policy's own
    deterministic choice is `api`; `box` itself carries evidence 40 days old -- past `max_age_days=30` but inside
    `staleness_limit_days=60` -- and clears the floor, so it is the alternative exploration can reach."""
    o = _rt_obs(inflight=20.0, metered_authorised=True, available=True, evidence_age_days=STALE_AGE_DAYS)
    for seed in range(tries):
        got, d = _rt_route(o, exploration_rate=rate, staleness_limit_days=STALENESS_LIMIT_DAYS,
                           rng=random.Random(seed))
        if d.chosen == "box":
            return got, d
    raise AssertionError(f"no seed among the first {tries} explored into the stale arm at rate={rate} -- a "
                         f"fixture problem (or route_once not exploring at all), not a defect in the arithmetic")


def test_amendment_6_route_once_explored_stale_arm_is_recorded_uncertified():
    """Item 1, through `route_once`, not composed by hand. `box` is full under the deterministic policy (`api` is
    the default), so landing on `box` requires the randomiser to actually override the policy's own choice; its
    evidence is 40 days old, past `max_age_days=30` but inside `staleness_limit_days=60`. The returned
    `Decision.certified` must be `False` -- this is the test that failed when the coordinator reverted the fix
    (replacing the explored branch's admissibility call with a hardcoded `certified = True`)."""
    _got, d = _rt_route_into_stale_arm()
    assert d.chosen == "box"
    assert d.certified is False


def test_amendment_6_route_once_still_serves_the_stale_arm_not_the_default():
    """Item 2: the same call's `chosen`, asserted on its own and not conditioned on what `certified` says. The
    composition version of the earlier (insufficient) test 2: a fix that made the explored assignment uncertified
    by declining to draw `box` at all -- falling back to `api` -- would still leave `certified` looking correct in
    some other case, but `chosen` here would read `api`, not `box`, and this assertion is the one that catches
    that, independent of the test above."""
    _got, d = _rt_route_into_stale_arm()
    assert d.chosen == "box"
    assert d.chosen != "api"


def test_amendment_6_route_once_explored_fresh_arm_above_the_floor_is_certified():
    """Item 3: the mirror positive, through `route_once`. Without this, a `route_once` that hardcodes
    `certified = False` for every explored assignment -- the "uncertified by construction" position C3's
    interface section rejects by name (F8) -- would pass items 1 and 2 above unconditionally. `box` is full so
    `api` is the deterministic default; `box` here is fresh (evidence 5 days old, well inside `max_age_days=30`)
    and must come back certified when exploration lands on it."""
    o = _rt_obs(inflight=20.0, metered_authorised=True, available=True, evidence_age_days=5.0)
    for seed in range(50):
        _got, d = _rt_route(o, exploration_rate=0.999, staleness_limit_days=STALENESS_LIMIT_DAYS,
                            rng=random.Random(seed))
        if d.chosen == "box":
            assert d.certified is True
            return
    raise AssertionError("no seed among the first 50 explored into the fresh arm -- fixture problem")


def test_amendment_6_route_once_with_exploration_rate_zero_is_unaffected():
    """Item 4, first half: the unexplored path must not have changed shape just because the exploration machinery
    is present. The free-seat scenario from `tests/test_serve.py`'s own
    `test_a_free_seat_goes_to_the_reserved_candidate_and_is_recorded`, run again with `exploration_rate=0.0` and a
    real `rng` supplied: the call must still return the deterministic assignment (`box`, via the policy's own
    rule, not via exploration) with its own correct `certified`, and `exploration` must read `False` -- a rate of
    zero is a decision NOT to explore, not a silent no-op that happens to look the same by coincidence."""
    o = _rt_obs(inflight=2.0, metered_authorised=True, available=True, evidence_age_days=5.0)
    _got, d = _rt_route(o, exploration_rate=0.0, staleness_limit_days=STALENESS_LIMIT_DAYS, rng=random.Random(0))
    assert d.chosen == "box"
    assert d.certified is True
    assert d.exploration is False


def test_amendment_6_route_once_with_no_eligible_alternative_is_unaffected():
    """Item 4, second half: a positive `exploration_rate` with nothing eligible to explore into. `box` is full
    (`api` is the deterministic default) and this call supplies no bound for `box` at all (`bounds={"api": 0.70}`),
    so `explore.eligible` can name no alternative -- the assignment must fall through to the ordinary deterministic
    path exactly as it would with no exploration machinery present, rather than erroring or exploring into
    something anyway."""
    o = _rt_obs(inflight=20.0, metered_authorised=True, evidence_age_days=5.0)
    _got, d = _rt_route(o, bounds={"api": 0.70}, costs={"api": 0.012}, exploration_rate=0.99,
                        staleness_limit_days=STALENESS_LIMIT_DAYS, rng=random.Random(0))
    assert d.chosen == "api"
    assert d.exploration is False


# ======================================================================================================
# C10 (amendment 13) -- "explored" meant "the randomiser ran", not "traffic was diverted"
#
# `explore.draw` returned `"explored"` for BOTH outcomes of an active draw: the alternative winning, and the
# deterministic arm winning anyway. `serve.route_once` set `exploration=(exploration_reason == "explored")`, so a
# decision where nothing was diverted was recorded as if it had been. Measured over 5,000 seeds at rate 0.05,
# before this fix:
#
#     reason == 'explored' : 100.0% of draws
#     actually diverted    : 5.5%
#     seed 0                : ('box', 0.95, 'explored')   <- the incumbent won and the reason still said explored
#
# `accept.exploration_cost` computed its share straight off that field, reporting ~100% against a budget the
# mechanism was 5.5% inside -- a FAIL for a mechanism well within budget. The fix: a fifth `exploration_reason`,
# `not_diverted`, for the randomiser-ran-but-incumbent-won case; `explore.draw` returns it in place of `explored`
# for that outcome; `serve.route_once` derives `exploration` from `chosen != deterministic` (the signal it already
# computes three lines away to decide whether to re-derive `certified`) rather than from the reason string. The
# propensity is UNCHANGED: `1 - rate` for the incumbent under an active draw remains correct and is the common case.
# ======================================================================================================


def test_draw_incumbent_wins_returns_not_diverted_with_propensity_one_minus_rate():
    """Amendment 13 / C10's own reproduction, seed for seed: `random.Random(0).random()` is 0.8442..., past the
    0.05 boundary, so the deterministic arm wins under an active draw -- exactly the `seed 0` line in the
    contract's measured reproduction above. The propensity is still `1 - rate = 0.95` (that does not change), but
    the reason must now be `not_diverted`, not `explored`: the randomiser ran and nothing was diverted."""
    chosen, prob, reason = explore.draw("box", ["box", "alt"], 0.05, random.Random(0))
    assert (chosen, reason) == ("box", "not_diverted")
    assert prob == pytest.approx(0.95)


def test_draw_alternative_wins_still_returns_explored_with_propensity_rate_over_k():
    """The other outcome of the same active draw, deliberately seeded to land on the alternative -- seed 31 is
    the first, starting from 0, whose `rng.random()` falls under the 0.05 boundary (the existing cross-check test
    above, `test_draw_alternative_propensities_and_deterministic_propensity_sum_to_one`, names 31 for the same
    reason). This branch's reason stays `explored`: traffic actually diverted to the alternative, which is what
    the field must mean after C10 as much as before it."""
    chosen, prob, reason = explore.draw("box", ["box", "alt"], 0.05, random.Random(31))
    assert (chosen, reason) == ("alt", "explored")
    assert prob == pytest.approx(0.05)


def test_draw_explored_share_over_many_seeds_tracks_the_diverted_rate_not_1_0():
    """THE test that would have caught the defect, made deliberately the sharpest one in this file. Before C10,
    every draw's reason read `explored` regardless of which arm won, so this fraction read 1.0 (100%) no matter
    what `rate` was declared -- amendment 13 measured exactly that over 5,000 seeds at rate=0.05:

        reason == 'explored' : 100.0% of draws
        actually diverted    : 5.5%

    After C10 the reason for an incumbent win is `not_diverted`, so the fraction of draws whose reason reads
    `explored` must track the actual rate of diversion (~0.05 here), not saturate at 1.0 independent of it."""
    n = 5000
    rate = 0.05
    explored = sum(1 for seed in range(n)
                   if explore.draw("box", ["box", "alt"], rate, random.Random(seed))[2] == "explored")
    share = explored / n
    assert abs(share - rate) < 0.02, (
        f"{share:.4f} of {n} draws read 'explored' at rate={rate} -- under the pre-C10 defect this reads ~1.0 "
        f"(100%) regardless of rate, because 'explored' covered both outcomes of the draw instead of only the "
        f"one where traffic was actually diverted"
    )


def _rt_route_incumbent_wins_under_active_draw(tries=10, rate=0.05):
    """Loop seeded rngs until `route_once`'s randomiser ran (a real eligible alternative existed) and still left
    the incumbent in place -- the common case C10's own contract text names by that word, complementary to
    `_rt_route_into_stale_arm` above which loops for the opposite outcome. `box` is full (`inflight=20`) so the
    policy's deterministic default is `api`; `box` itself is fresh (5 days, well inside `max_age_days=30`) and
    clears the floor, so it is a real eligible alternative the draw ran over. At `rate=0.05` most seeds leave the
    incumbent (`api`) in place, so this is expected to succeed on the first or second try, not by exhausting the
    loop."""
    o = _rt_obs(inflight=20.0, metered_authorised=True, available=True, evidence_age_days=5.0)
    for seed in range(tries):
        got, d = _rt_route(o, exploration_rate=rate, staleness_limit_days=STALENESS_LIMIT_DAYS,
                           rng=random.Random(seed))
        if d.chosen == "api":
            return got, d
    raise AssertionError(f"no seed among the first {tries} left the incumbent ('api') in place at rate={rate} -- "
                         f"a fixture problem, not a defect in the arithmetic")


def test_route_once_incumbent_wins_under_active_randomiser_records_not_diverted():
    """Through `route_once`, with a seeded rng -- nothing in the pre-C10 suite exercised this exact branch (an
    active randomiser whose draw still left the incumbent in place), which is why the defect shipped unnoticed.
    The recorded decision must read `exploration is False`, `exploration_reason == 'not_diverted'`, and the
    UNCHANGED propensity `1 - rate` -- not `1.0`, because that is the probability of the arm actually chosen
    under the draw actually performed, and not `True`/`'explored'`, which is exactly what C10 corrects."""
    _got, d = _rt_route_incumbent_wins_under_active_draw(rate=0.05)
    assert d.chosen == "api"
    assert d.exploration is False
    assert d.exploration_reason == "not_diverted"
    assert d.selection_probability == pytest.approx(1.0 - 0.05)


def test_accept_exploration_cost_reports_the_diverted_share_not_the_share_of_draws():
    """SCOPE section 8 defines the exploration budget as a share of TRAFFIC AND SPEND -- diverted traffic, not
    every decision an active randomiser merely touched. 100 decisions, all under an active randomiser: 5 diverted
    (`exploration: True`), 95 where the incumbent won and stayed (`exploration: False`). The diverted share is
    5%, not the ~100% the pre-C10 defect would have produced by counting every draw whose reason read
    'explored' regardless of outcome. Against a 25% budget this must PASS."""
    rows = [{"exploration": True} for _ in range(5)] + [{"exploration": False} for _ in range(95)]
    v = ac.exploration_cost(rows, budgeted_share=0.25)
    assert v.numbers["exploration_share"] == pytest.approx(0.05)
    assert v.verdict == ac.PASS


def test_from_row_v1_row_still_reads_no_mechanism_after_c10():
    """C10 adds a fifth value to `EXPLORATION_REASONS`; `from_row`'s version-1 default is untouched by it -- a
    real v0.1.0 line (not a hand-typed stand-in, per amendment 5's own rule) still reads `no_mechanism`, never
    the new `not_diverted`, because no draw was ever performed for a row written before C3's mechanism existed."""
    d, _ignored = rec.from_row(_real_v010_row())
    assert d.exploration_reason == "no_mechanism"


def test_exploration_reasons_vocabulary_gains_not_diverted_as_a_fifth_member():
    """C10's own statement of the fix: the vocabulary was one value short, which is why the field could not carry
    the distinction between 'nothing to explore' and 'explored and the incumbent won anyway'. `not_diverted` is
    the fourth cause of `exploration: false` -- the randomiser ran and the incumbent won -- alongside the three
    C3 already named (no mechanism, an empty eligible set, a zero rate)."""
    assert set(rec.EXPLORATION_REASONS) == {"explored", "no_eligible_arm", "rate_zero", "no_mechanism",
                                            "not_diverted"}
    assert len(rec.EXPLORATION_REASONS) == 5


@pytest.mark.parametrize("reason", ["explored", "no_eligible_arm", "rate_zero", "no_mechanism", "not_diverted"])
def test_c10_every_one_of_the_five_exploration_reasons_is_a_legal_value_on_a_written_decision(reason):
    """All five values, including the four the pre-C10 suite already covered plus C10's new `not_diverted`, must
    be constructible on a `Decision` -- catching an implementation that adds the value to `EXPLORATION_REASONS`
    without actually letting `__post_init__` accept it, or that narrows the set some other way."""
    base = _v2_row(exploration_reason=reason, eligible_set=[])
    candidates = [rec.Candidate(**c) for c in base["candidates"]]
    kw = {k: v for k, v in base.items() if k not in ("candidates", "schema_version")}
    kw["candidates"] = candidates
    d = rec.Decision(**kw)
    assert d.exploration_reason == reason


def test_a_sixth_exploration_reason_outside_the_five_is_refused():
    """The vocabulary is closed at write time, the same way `EXCLUSION_REASONS` is (CONTRACT C10: 'refused at
    write time like the others'): a value outside the five legal reasons raises `Incomplete` naming it, rather
    than writing an open-ended reason a log could not aggregate."""
    base = _v2_row(exploration_reason="sort_of_explored", eligible_set=[])
    candidates = [rec.Candidate(**c) for c in base["candidates"]]
    kw = {k: v for k, v in base.items() if k not in ("candidates", "schema_version")}
    kw["candidates"] = candidates
    with pytest.raises(rec.Incomplete, match="not one of"):
        rec.Decision(**kw)
