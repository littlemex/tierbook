"""The router, pinned by the refusals rather than by the happy path.

Most of these assert that it declines to exist. That is deliberate: every measurement this project got
wrong was a case of something being reported at a confidence it had not earned, so the tests that matter
are the ones proving the object cannot be built in that state.
"""
from __future__ import annotations

import dataclasses
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.evidence import INCORRECT, SOLVED, EvidenceError  # noqa: E402
from tierbook.outcomes import Cell, OutcomeTable  # noqa: E402
from tierbook.quorum import agreement  # noqa: E402
from tierbook.router import (  # noqa: E402
    AGREEMENT,
    Decision,
    Router,
    audit_broken_keys,
    certify_pool,
    decide_from_score,
    default_stop_rule,
)


def _table(n: int = 400, *, cheap_ok=lambda i: i % 4 != 0, dear_ok=lambda i: i % 40 != 0,
           second_ok=None) -> OutcomeTable:
    """A pool where two cheap candidates mostly agree and a dear one cleans up."""
    second_ok = second_ok or (lambda i: i % 4 != 0)
    t = OutcomeTable(suite="s", manifest_digest="d")
    for i in range(n):
        t.cells[f"i{i}"] = {
            "cheap": Cell(SOLVED if cheap_ok(i) else INCORRECT,
                          usd=1e-5, answer="B" if cheap_ok(i) else "C"),
            "cheap2": Cell(SOLVED if second_ok(i) else INCORRECT,
                           usd=2e-5, answer="B" if second_ok(i) else "D"),
            "dear": Cell(SOLVED if dear_ok(i) else INCORRECT,
                         usd=1e-3, answer="B" if dear_ok(i) else "E"),
        }
    return t


def test_it_refuses_a_floor_it_cannot_certify_and_says_why():
    """The load-bearing test. A point-estimate winner must not become a router."""
    t = _table()
    with pytest.raises(EvidenceError) as exc:
        Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.99)
    msg = str(exc.value)
    assert "certif" in msg or "reach" in msg
    # The message has to name the size of the search, because that is what the reader needs to judge it.
    assert "polic" in msg


def test_a_router_that_builds_certifies_its_floor():
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    c = r.certificate
    assert c.certified
    assert c.accuracy_lower >= 0.80
    assert c.accuracy_lower <= c.accuracy_point, "the bound cannot exceed the point estimate"
    assert c.considered >= 1
    assert c.manifest_digest == "d"


def test_the_certificate_names_the_search_size_so_the_bound_can_be_judged():
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    text = str(r.certificate)
    assert "policies" in text and "at least" in text
    assert f"{r.certificate.considered}" in text


def test_agreement_returns_the_agreed_answer_and_records_unanimity():
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    ans = {m: "B" for m in r.certificate.members}
    d = r.decide(ans)
    assert d.action == "answer" and d.answer == "B"


def test_an_unparseable_answer_is_not_agreement():
    """Two silences are not a consensus. Measured: recovered malformed cells were wrong every time."""
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    members = r.certificate.members
    if len(members) < 2:
        pytest.skip("this fixture chose a single-member policy")
    ans = {m: None for m in members}
    d = r.decide(ans)
    assert d.action == "call", "all-None must escalate, not agree on nothing"


def test_disagreement_escalates_to_the_single_named_tier_and_does_not_branch():
    """One axis means one ordering, so there is nothing to branch on."""
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    members = r.certificate.members
    if len(members) < 2:
        pytest.skip("this fixture chose a single-member policy")
    ans = dict(zip(members, ["B", "C"] + ["B"] * len(members)))
    d = r.decide(ans)
    assert d.action == "call" and d.tiers == (r.certificate.escalate_to,)
    assert len(r.ladder) == 1


def test_run_calls_members_together_and_escalation_after():
    """Stage count is the latency claim: members are one stage however many there are."""
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    members = r.certificate.members
    replies = {m: "B" for m in members}
    with ThreadPoolExecutor(max_workers=4) as ex:
        out = r.run(lambda tier: replies.get(tier), cost=lambda tier: 1.0, executor=ex)
    assert out.answer == "B"
    assert out.stages == 1, "agreement must not cost a second stage"
    assert set(out.calls) == set(members)
    assert out.usd == float(len(members))


def test_escalation_costs_exactly_one_more_stage():
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    members = list(r.certificate.members)
    if len(members) < 2:
        pytest.skip("this fixture chose a single-member policy")
    replies = {members[0]: "B", members[1]: "C", r.certificate.escalate_to: "E"}
    for m in members[2:]:
        replies[m] = "B"
    with ThreadPoolExecutor(max_workers=4) as ex:
        out = r.run(lambda tier: replies.get(tier), cost=lambda tier: 1.0, executor=ex)
    assert out.answer == "E"
    assert out.stages == 2
    assert not out.abandoned


def test_a_router_that_declares_no_stop_rule_gets_the_default_and_todays_decisions():
    """TB-034's fix: injectable, not a claim that the shape changed. A caller who declares nothing must see exactly
    what `decide` returned before this change -- unanimity stops, disagreement escalates through `ladder`."""
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.80)
    assert r.rule is AGREEMENT
    assert AGREEMENT is agreement
    members = r.certificate.members
    assert r.decide({m: "B" for m in members}) == default_stop_rule(r.certificate, r.ladder, {m: "B" for m in members})


def test_router_is_frozen_so_assignment_cannot_bypass_the_check():
    """Round 2's `Router` was a plain mutable dataclass: `r.stop_rule = something_else` skipped `__post_init__`
    entirely, which is the TB-034 failure with one extra step. Freezing closes that specific door; the only way
    left to change `rule` is through `__init__`/`replace`, both of which run `__post_init__`."""
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.80)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.rule = AGREEMENT
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.certificate = r.certificate


def test_swapping_the_rule_without_refitting_is_refused():
    """Swapping `rule` on a fitted `Router` via `replace` must not silently keep the OLD certificate's accuracy
    while a different rule executes -- the TB-034 failure `replace` can still reach even on a frozen dataclass,
    since `replace` constructs a new instance rather than mutating the old one. `__post_init__` runs on that new
    instance and must catch the mismatch. This time the check is OBJECT IDENTITY (`certificate.stop_rule is
    rule`), not a name: a reviewer showed round 3's name check let `Rule(name="agreement", score=agreement,
    runtime=always_abandon)` straight through `replace`, because a name is self-declared and a caller can put
    ANY name on ANY callable. A same-named, differently-behaving callable must fail here too."""
    def always_abandon_score(table, members, items):
        return {}

    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.80)
    with pytest.raises(EvidenceError, match="not the exact object"):
        replace(r, rule=always_abandon_score)
    # Even naming it "agreement" (the default's own display name) must not let it through: identity, not name.
    always_abandon_score.__qualname__ = "agreement"
    with pytest.raises(EvidenceError, match="not the exact object"):
        replace(r, rule=always_abandon_score)
    # The router this was copied from is untouched.
    members = r.certificate.members
    assert r.decide({m: "B" for m in members}).action == "answer"


def test_a_declared_rule_is_carried_and_used_in_place_of_the_default():
    """A different study's rule -- here, one that never stops on anything -- must be expressible without editing
    `Router.decide` or `default_stop_rule`. Round 4's fix: there is exactly ONE callable to inject (the batch
    scorer), and the runtime behaviour is DERIVED from it generically (`decide_from_score`), so there is no
    second, independently-injectable callable that could disagree with it -- unlike round 3's `Rule`, which
    bundled two callables that were still free to disagree."""
    def never_stop_score(table, members, items):
        return {}

    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.10,
                   min_stopped=0, stop_rule=never_stop_score)
    assert "never_stop_score" in r.certificate.stop_rule_id
    assert r.rule is never_stop_score
    members = r.certificate.members
    escalate = r.ladder[0]
    # It never stops, so it must escalate every time, then answer with whatever the escalation tier said.
    d = r.decide({m: "B" for m in members})
    assert d.action == "call" and d.tiers == (escalate,)
    d2 = r.decide({**{m: "B" for m in members}, escalate: "E"})
    assert d2.action == "answer" and d2.answer == "E" and d2.reason == f"escalated to {escalate}"
    # An injected rule is not the fold-derived rule this project measured, so the adaptive-analysis warning that
    # applies to `agreement` must not be printed for someone else's rule.
    assert r.certificate.rules_are_fold_derived is False

    # The default, un-declared path still reproduces today's behaviour exactly.
    default_r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.80)
    assert default_r.certificate.stop_rule_id == "agreement"
    assert default_r.certificate.rules_are_fold_derived is True
    assert default_r.decide({m: "B" for m in default_r.certificate.members}).action == "answer"


def test_a_rule_certifies_a_majority_stop_correctly():
    """The scoring gap a round-3 review found persists: confirm a MAJORITY rule (which round 2's `evaluate`
    misjudged, see `test_quorum.py`) certifies through `Router.fit` at the accuracy it actually earns. Round 4
    adds: its RUNTIME needs no separate declaration at all -- `decide_from_score` derives it from the same
    scorer, and this test checks that the derived runtime actually answers with the majority's own answer."""
    def majority_of_three(table, members, items):
        out = {}
        for item in items:
            cells = table.cells.get(item, {})
            answers = [cells[m].answer for m in members if m in cells and cells[m].answer is not None]
            if not answers:
                continue
            out[item] = max(set(answers), key=answers.count)
        return out

    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.10,
                   min_stopped=0, stop_rule=majority_of_three)
    assert "majority_of_three" in r.certificate.stop_rule_id
    # Cross-check: the certificate's point accuracy must equal what quorum.evaluate independently computes for
    # the SAME (members, escalate_to, rule) -- i.e. Router.fit is not silently using a different scorer.
    from tierbook.quorum import evaluate as _evaluate
    independently_scored = _evaluate(t, r.certificate.members, r.certificate.escalate_to,
                                     stop_rule=majority_of_three).accuracy
    assert r.certificate.accuracy_point == pytest.approx(independently_scored)

    # The runtime derivation, checked directly against a synthetic three-member certificate so this assertion
    # does not depend on `Router.fit`'s own search happening to prefer three members over fewer on this pool.
    from tierbook.router import Certificate
    synthetic = Certificate(
        members=("a", "b", "c"), escalate_to="dear", accuracy_floor=0.10, accuracy_point=1.0, accuracy_lower=1.0,
        usd_per_item=0.0, usd_upper=0.0, stop_rate=1.0, stop_rate_interval=(1.0, 1.0), agreement_lift=0.0,
        wrong_stop_rate=0.0, wrong_stop_interval=(0.0, 0.0), considered=1, items=1, suite="s", manifest_digest="d",
        abandon_depth=1, stop_rule_id="majority_of_three", stop_rule=majority_of_three)
    # Two of three say "B", one says "C": the derived runtime must answer "B" without ever consulting `ladder`.
    d = decide_from_score(majority_of_three, synthetic, (), {"a": "B", "b": "B", "c": "C"})
    assert d.action == "answer" and d.answer == "B"


def test_verify_rescores_under_the_certificates_own_rule_not_the_module_default():
    """A router fitted under an injected rule must be re-checked against THAT rule on a second collection, not
    against `agreement` -- otherwise `verify` would silently score something the certificate does not describe."""
    def never_stop_score(table, members, items):
        return {}

    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.10,
                   min_stopped=0, stop_rule=never_stop_score)
    held, point, low = r.verify(t)
    # `verify` must score under `never_stop_score` (r's own `rule`), which stops nothing -- not under the
    # module's `agreement` default, which would stop on the same members' agreeing items and read a different
    # accuracy for the identical (members, escalate_to) pair.
    from tierbook.quorum import agreement as _agreement
    from tierbook.quorum import evaluate as _evaluate
    scored_under_never_stop = _evaluate(t, r.certificate.members, r.certificate.escalate_to,
                                        stop_rule=never_stop_score).accuracy
    scored_under_agreement = _evaluate(t, r.certificate.members, r.certificate.escalate_to,
                                       stop_rule=_agreement).accuracy
    assert point == pytest.approx(scored_under_never_stop)
    assert scored_under_never_stop != scored_under_agreement, "the fixture needs the two rules to actually disagree"


def _reference_default_stop_rule(certificate, ladder, answers):
    """A verbatim copy of round 3's hand-written `default_stop_rule` body -- kept ONLY so the test below can
    compare the new generic derivation against the exact logic it replaces. Not exported; do not import this
    from outside this file."""
    members = certificate.members
    missing = tuple(m for m in members if m not in answers)
    if missing:
        return Decision("call", tiers=missing, reason="the members have not all answered")
    vals = [answers[m] for m in members]
    parsed = [v for v in vals if v is not None]
    if len(parsed) == len(vals) and len(set(parsed)) == 1:
        return Decision("answer", answer=parsed[0], reason="every member produced the same answer")
    reason = ("a member produced no parseable answer, which is not agreement"
              if len(parsed) < len(vals) else "the members disagreed")
    for tier in ladder:
        if tier not in answers:
            return Decision("call", tiers=(tier,), reason=reason)
        if answers[tier] is not None:
            return Decision("answer", answer=answers[tier], reason=f"escalated to {tier}")
    called = len(members) + len(ladder)
    fallback = parsed[0] if parsed else None
    return Decision("abandon", fallback=fallback,
                    reason=(f"{called} tiers produced nothing parseable; abandoning at the fixed depth of "
                            f"{certificate.abandon_depth}"))


def test_decide_from_score_reproduces_default_stop_rule_exactly():
    """The coordinator's own requirement: `decide_from_score(quorum.agreement, ...)` must reproduce round 3's
    hand-written `default_stop_rule` exactly, over every branch that function had. Where it does NOT reproduce
    exactly, this test names the one known difference rather than silently loosening the comparison."""
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.80)
    cert, ladder = r.certificate, r.ladder
    members = cert.members
    if len(members) < 2:
        pytest.skip("this fixture chose a single-member policy")
    escalate = ladder[0]

    cases = {
        "missing answers": {members[0]: "B"},
        "unanimous": {m: "B" for m in members},
        "one silent member": {**{m: "B" for m in members[:-1]}, members[-1]: None},
        "disagreement, escalation not yet answered": {**{m: "B" for m in members[:-1]}, members[-1]: "C"},
        "disagreement, escalation answers": {**{m: "B" for m in members[:-1]}, members[-1]: "C", escalate: "E"},
        "disagreement, escalation silent -> abandon": {**{m: "B" for m in members[:-1]}, members[-1]: "C",
                                                        escalate: None},
    }
    for label, answers in cases.items():
        got = decide_from_score(agreement, cert, ladder, answers)
        want = _reference_default_stop_rule(cert, ladder, answers)
        assert (got.action, got.answer, got.tiers, got.fallback) == (want.action, want.answer, want.tiers,
                                                                      want.fallback), (
            f"{label}: behaviour differs -- decide_from_score gave {got!r}, the reference gave {want!r}")
        if want.reason == "every member produced the same answer":
            # The ONE known, reported difference: the generic derivation cannot know WHY an arbitrary injected
            # rule stopped (a custom rule need not be unanimity-based at all), so its reason is deliberately
            # generic ("the rule selected an answer") rather than asserting unanimity specifically, which would
            # be a false claim for a non-unanimous rule using the same derivation. Every other field, and every
            # other branch's reason text, reproduces exactly.
            assert got.reason == "the rule selected an answer", label
        else:
            assert got.reason == want.reason, f"{label}: reason differs unexpectedly -- {got.reason!r} vs {want.reason!r}"
        # And the named entry point (what a caller actually calls) matches the derivation for every case.
        assert default_stop_rule(cert, ladder, answers) == decide_from_score(agreement, cert, ladder, answers), label


def test_everything_silent_abandons_rather_than_guessing():
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    with ThreadPoolExecutor(max_workers=4) as ex:
        out = r.run(lambda tier: None, cost=lambda tier: 1.0, executor=ex)
    assert out.abandoned and out.answer is None


def test_the_broken_key_auditor_needs_the_answer_key_and_is_not_a_runtime_rule():
    """It fires on 'everyone agreed AND everyone was wrong', which no runtime can see."""
    t = OutcomeTable(suite="s", manifest_digest="d")
    for i in range(10):
        # item 3 is the broken one: all three agree on Z and all three are graded wrong.
        broken = i == 3
        t.cells[f"i{i}"] = {
            c: Cell(INCORRECT if broken else SOLVED, usd=1e-4,
                    answer="Z" if broken else ("B" if c != "dear" else "B"))
            for c in ("cheap", "cheap2", "dear")}
    flagged = audit_broken_keys(t, candidates=["cheap", "cheap2", "dear"])
    assert flagged == ["i3"], flagged
    # And the runtime path has no audit channel at all: agreement returns the answer, full stop.
    # Fitted on the larger fixture, because a 10-item table cannot certify anything and the point here
    # is the absence of a flag, not the bound.
    r = Router.fit(_table(), candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    d = r.decide({m: "B" for m in r.certificate.members})
    assert d.action == "answer"
    assert not hasattr(d, "unanimous"), "the runtime must not carry an audit flag it cannot use"


def test_certify_pool_distinguishes_unreachable_from_uncertifiable():
    t = _table()
    out = certify_pool(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                       floors=(0.70, 0.80, 0.999))
    assert hasattr(out[0.80], "certified")
    assert isinstance(out[0.999], str), "an impossible floor must come back as a reason, not a router"


def test_cost_carries_an_upper_bound_because_cost_is_also_selected_on():
    """`fit` chooses the cheapest of the eligible, so the cost point estimate has a winner's curse too."""
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    c = r.certificate
    assert c.usd_upper >= c.usd_per_item


def test_the_certificate_warns_that_the_rules_came_from_the_same_fold():
    """No divisor corrects for choosing the rules by reading the data. It has to be said in the object."""
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    assert r.certificate.rules_are_fold_derived
    assert "adaptive data analysis" in str(r.certificate)


def test_trying_several_floors_is_recorded_as_a_second_search():
    t = _table()
    r = Router.fit_verified(t, t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                            floors=(0.99, 0.95, 0.80))
    assert r.certificate.floors_attempted > 1
    assert "floors were tried" in str(r.certificate)


def test_abandoning_hands_back_the_best_answer_heard():
    """A caller has to return something, and whether an abstention scores wrong changes the floor."""
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    members = list(r.certificate.members)
    if len(members) < 2:
        pytest.skip("this fixture chose a single-member policy")
    replies = {members[0]: "B", members[1]: "C", r.certificate.escalate_to: None}
    for m in members[2:]:
        replies[m] = "B"
    out = r.run(lambda tier: replies.get(tier), cost=lambda tier: 1.0)
    assert out.abandoned
    assert out.answer in ("B", "C"), "the material heard has to come back, not be discarded"


def test_effectively_single_is_named_so_a_reader_does_not_credit_a_quorum():
    """Above an 82% floor the search returns a single model on the measured pool."""
    t = _table()
    r = Router.fit(t, candidates=["cheap", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.70, max_members=1, min_stopped=1)
    assert r.certificate.effectively_single
    assert "effectively a single model" in str(r.certificate)


def test_compare_to_single_charges_each_family_for_its_own_search():
    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                   accuracy_floor=0.80)
    res = r.compare_to_single(t, candidates=["cheap", "cheap2", "dear"],
                             prices={"cheap": 1e-5, "cheap2": 2e-5, "dear": 1e-3})
    assert "verdict" in res
    if res.get("single"):
        assert res["single_bound"] >= r.certificate.accuracy_floor


def test_fit_best_prefers_a_single_model_when_it_is_cheaper():
    """The comparison that decides the deliverable. Each family pays for its own search size."""
    t = _table()
    r = Router.fit_best(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                        accuracy_floor=0.80)
    q = None
    try:
        q = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                       accuracy_floor=0.80)
    except EvidenceError:
        pass
    if q is not None:
        assert r.certificate.usd_per_item <= q.certificate.usd_per_item, (
            "fit_best must never be dearer than the quorum-only fit")


def test_a_single_model_router_carries_no_adaptive_rules_warning():
    """A single candidate is the absence of a rule, not a rule chosen by reading the fold."""
    t = _table()
    r = Router._best_single(t, candidates=["cheap", "cheap2", "dear"],
                            items=list(t.items), accuracy_floor=0.80, alpha=0.05)
    assert r is not None
    assert not r.certificate.rules_are_fold_derived
    assert r.certificate.effectively_single
    assert "adaptive data analysis" not in str(r.certificate)


def test_a_single_model_router_answers_without_escalating():
    t = _table()
    r = Router._best_single(t, candidates=["cheap", "cheap2", "dear"],
                            items=list(t.items), accuracy_floor=0.80, alpha=0.05)
    out = r.run(lambda tier: "B", cost=lambda tier: 1.0)
    assert out.answer == "B" and out.stages == 1 and not out.abandoned
    assert out.usd == 1.0, "one call, not two"


def test_fit_best_raises_when_neither_family_certifies():
    t = _table()
    with pytest.raises(EvidenceError):
        Router.fit_best(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"],
                        accuracy_floor=0.999)


def test_fit_refuses_a_non_callable_stop_rule_with_a_readable_message():
    """Round 3's `Rule` wrapper (`score=`/`runtime=` on one object) no longer exists; a caller who still passes
    one, or any other non-callable, must get a sentence naming what changed rather than an `AttributeError` deep
    inside `enumerate_policies`."""
    t = _table()
    with pytest.raises(EvidenceError, match="is not callable"):
        Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.80,
                  stop_rule="agreement")


def test_stoprule_is_a_deprecated_alias_for_runtimestoprule():
    """Round 2 renamed `router.StopRule` to `RuntimeStopRule` (to stop colliding with `quorum.StopRule`'s
    incompatible signature) with no alias, which breaks any importer who held the old bare name."""
    import tierbook.router as router_mod
    assert router_mod.StopRule is router_mod.RuntimeStopRule
