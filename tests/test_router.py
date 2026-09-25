"""The router, pinned by the refusals rather than by the happy path.

Most of these assert that it declines to exist. That is deliberate: every measurement this project got
wrong was a case of something being reported at a confidence it had not earned, so the tests that matter
are the ones proving the object cannot be built in that state.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dataclasses import replace  # noqa: E402

from tierbook.evidence import INCORRECT, SOLVED, EvidenceError  # noqa: E402
from tierbook.outcomes import Cell, OutcomeTable  # noqa: E402
from tierbook.quorum import agreement  # noqa: E402
from tierbook.router import Decision, Router, audit_broken_keys, certify_pool, default_stop_rule  # noqa: E402


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
    assert r.stop_rule is default_stop_rule
    members = r.certificate.members
    assert r.decide({m: "B" for m in members}) == default_stop_rule(r.certificate, r.ladder, {m: "B" for m in members})


def test_swapping_the_runtime_rule_without_refitting_is_refused():
    """TB-034's fix found a second gap by its own reviewers: swapping `stop_rule` on a fitted `Router` changed what
    runs while the certificate went on asserting the accuracy `agreement` earned. A mismatched swap must be refused
    at construction, not silently accepted -- see `test_a_declared_stop_rule_is_carried_and_used_in_place_of_the_default`
    for the way to inject a different rule that keeps the certificate honest."""
    def always_abandon(certificate, ladder, answers):
        return Decision("abandon", fallback="Z", reason="a different study's rule")

    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.80)
    with pytest.raises(EvidenceError, match="was never measured against"):
        replace(r, stop_rule=always_abandon)
    # The router this was copied from is untouched.
    members = r.certificate.members
    assert r.decide({m: "B" for m in members}).action == "answer"


def test_a_declared_stop_rule_is_carried_and_used_in_place_of_the_default():
    """A different study's rule -- here, one that never escalates and always abandons with a fixed fallback -- must be
    expressible without editing `Router.decide` or `default_stop_rule`. The consistent path names BOTH the batch rule
    `enumerate_policies` scores with and the runtime rule that will execute, so the certificate describes what
    actually runs."""
    def never_stop(table, members, items):
        return [], list(items)
    never_stop.rule_id = "never_stop"

    def always_abandon(certificate, ladder, answers):
        return Decision("abandon", fallback="Z", reason="a different study's rule")
    always_abandon.rule_id = "never_stop"

    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.10,
                   min_stopped=0, stop_rule=never_stop, runtime_stop_rule=always_abandon)
    assert r.certificate.stop_rule_id == "never_stop"
    members = r.certificate.members
    d = r.decide({m: "B" for m in members})
    assert d.action == "abandon" and d.fallback == "Z" and d.reason == "a different study's rule"

    # The default, un-declared path still reproduces today's behaviour exactly.
    default_r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.80)
    assert default_r.certificate.stop_rule_id == "agreement"
    assert default_r.decide({m: "B" for m in default_r.certificate.members}).action == "answer"


def test_a_custom_batch_rule_with_no_runtime_counterpart_is_refused():
    """`Router.decide` needs something to execute per request; there is no general way to derive that from a batch
    partition rule, so declaring one without the other refuses rather than silently keeping `default_stop_rule`."""
    def never_stop(table, members, items):
        return [], list(items)
    never_stop.rule_id = "never_stop"

    t = _table()
    with pytest.raises(EvidenceError, match="no runtime counterpart"):
        Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.10,
                  min_stopped=0, stop_rule=never_stop)


def test_verify_rescopes_under_the_certificates_own_rule_not_the_module_default():
    """A router fitted under an injected rule must be re-checked against THAT rule on a second collection, not
    against `agreement` -- otherwise `verify` would silently score something the certificate does not describe."""
    def never_stop(table, members, items):
        return [], list(items)
    never_stop.rule_id = "never_stop"

    def always_abandon(certificate, ladder, answers):
        return Decision("abandon", fallback=None, reason="never stops")
    always_abandon.rule_id = "never_stop"

    t = _table()
    r = Router.fit(t, candidates=["cheap", "cheap2", "dear"], escalate_to=["dear"], accuracy_floor=0.10,
                   min_stopped=0, stop_rule=never_stop, runtime_stop_rule=always_abandon)
    held, point, low = r.verify(t)
    # `verify` must score under `never_stop` (r's own `_item_stop_rule`), which stops nothing -- not under the
    # module's `agreement` default, which would stop on the same members' agreeing items and read a different
    # accuracy for the identical (members, escalate_to) pair.
    from tierbook.quorum import agreement as _agreement
    from tierbook.quorum import evaluate as _evaluate
    scored_under_never_stop = _evaluate(t, r.certificate.members, r.certificate.escalate_to,
                                        stop_rule=never_stop).accuracy
    scored_under_agreement = _evaluate(t, r.certificate.members, r.certificate.escalate_to,
                                       stop_rule=_agreement).accuracy
    assert point == pytest.approx(scored_under_never_stop)
    assert scored_under_never_stop != scored_under_agreement, "the fixture needs the two rules to actually disagree"


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
