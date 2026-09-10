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
    below the floor cannot be laundered by shrinking the denominator that would otherwise show it.

Only C3 (plus these two seams) is in scope here. C1's reader, C2's parameter plumbing, C4's labeller declaration and
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
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import accept as ac  # noqa: E402
from tierbook import explore  # noqa: E402
from tierbook import record as rec  # noqa: E402
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


def test_draw_rate_zero_and_no_alternative_both_hold_the_result_is_still_deterministic_with_propensity_one():
    """AMBIGUITY, not a gap: the contract states two conditions and two reasons ("rate is 0, or eligible has no
    member other than deterministic... distinguishable") but does not say which reason wins when BOTH hold at
    once. This test pins only what both branches agree on -- the chosen id and its propensity -- and accepts
    either reason string, rather than asserting a precedence the contract never settled. See the report: a test
    author guessing one order here would be pinning an implementer's coin flip, not the contract."""
    chosen, prob, reason = explore.draw("box", ["box"], 0.0, random.Random(1))
    assert (chosen, prob) == ("box", 1.0)
    assert reason in ("rate_zero", "no_eligible_arm")


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
    internally consistent. Verified indirectly here across many seeds landing on both arms of a 2-arm draw, so a
    bug that only shows up for one arm's branch cannot hide behind a seed that happens to avoid it."""
    seen = set()
    for seed in range(30):
        chosen, prob, _ = explore.draw("box", ["box", "alt"], 0.05, random.Random(seed))
        seen.add(chosen)
        expected = 0.95 if chosen == "box" else 0.05
        assert prob == pytest.approx(expected)
    assert seen == {"box", "alt"}, "30 seeds never landed on both arms of a 5% draw -- fixture is not exercising the draw at all"


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
        "endpoint": "http://e", "gateway_quote_usd": 0.004, "gateway_authorised": True, "decided_at": 1000.0,
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
        "endpoint": "http://e", "gateway_quote_usd": 0.004, "gateway_authorised": True, "decided_at": 1000.0,
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
