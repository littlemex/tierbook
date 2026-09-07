"""The three statements a table must make, and the ways each could be made falsely.

A compiled table already contains the answers; the failure being guarded against is silence. Each test here
is a reading a silent table would permit.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tierbook import report  # noqa: E402


def entry(chosen, *, status="assigned", ranked=None, reason=None):
    return {"chosen": list(chosen), "status": status, "ranked": ranked or [],
            "validation": {"reason": reason} if reason else {}}


def ranked(name, q, c, *, kind="outright", certified=True):
    return {"arrangement": name.split("+"), "kind": kind, "quality_lcb": q,
            "cost_per_request": c, "certified": certified}


# --- the policy's kind is stated, and a degenerate answer is a correct answer ---------------------


def test_one_candidate_is_degenerate_and_says_it_is_not_a_fallback():
    kind, why = report.policy_kind(entry(["a"]))
    assert kind == report.DEGENERATE
    assert "correct answer" in why and "fallback" in why


def test_two_stages_are_an_arrangement_and_the_order_is_stated():
    kind, why = report.policy_kind(entry(["cheap", "dear"]))
    assert kind == report.ARRANGEMENT
    assert "cheap then dear" in why


def test_nothing_chosen_is_unsupported_not_degenerate():
    kind, _ = report.policy_kind(entry([]))
    assert kind == report.UNSUPPORTED


def test_chosen_but_uncertified_keeps_its_kind_and_says_it_is_uncertified():
    """The distinction that matters: "nothing was chosen" and "something was chosen on evidence that does
    not certify it" need different responses, and collapsing them to `unsupported` erases that."""
    kind, why = report.policy_kind(entry(["a"], status="provisional", reason="held out below the margin"))
    assert kind == report.DEGENERATE
    assert "not certified" in why and "held out below the margin" in why


# --- the frontier, with domination computed rather than asserted ----------------------------------


def test_a_dominated_point_is_off_the_frontier_and_names_what_dominates_it():
    fr = report.frontier_for(entry(["a"], ranked=[
        ranked("a", 0.00, 0.10),          # cheaper and no worse
        ranked("b", -0.05, 0.20),         # dearer and worse
    ]))
    by = {p["candidate"]: p for p in fr}
    assert by["a"]["on_frontier"] is True
    assert by["b"]["on_frontier"] is False
    assert by["b"]["dominated_by"] == ["b" if False else "a"]


def test_a_tie_keeps_both_on_the_frontier():
    """Two candidates at the same cost and quality are genuinely both available; dropping one would hide a
    choice from whoever reads this."""
    fr = report.frontier_for(entry(["a"], ranked=[ranked("a", 0.0, 0.1), ranked("b", 0.0, 0.1)]))
    assert all(p["on_frontier"] for p in fr)


def test_a_point_with_no_bound_is_off_the_frontier_and_says_why():
    """It cannot be compared, so it cannot be claimed to be on the frontier. Silence here would let an
    uncomparable candidate look admissible."""
    fr = report.frontier_for(entry(["a"], ranked=[ranked("a", None, 0.1), ranked("b", 0.0, 0.2)]))
    a = next(p for p in fr if p["candidate"] == "a")
    assert a["on_frontier"] is False and "no comparable bound" in a["frontier_note"]


def test_a_cheaper_but_worse_point_stays_on_the_frontier():
    """The whole point of a frontier: it is a set of trades, not a ranking. A cheaper candidate with a
    lower bound is a real option for an operator with a lower floor."""
    fr = report.frontier_for(entry(["dear"], ranked=[
        ranked("cheap", -0.10, 0.01),
        ranked("dear", 0.00, 0.50),
    ]))
    assert all(p["on_frontier"] for p in fr)


# --- the self-hosted question is answered every time, with an actionable reason -------------------


def test_selected_is_the_answer_when_it_was_chosen():
    e = entry(["box"], ranked=[ranked("box", 0.0, 0.01)])
    ans = report.self_hosted_answer(e, report.frontier_for(e), self_hosted_ids={"box"})
    assert ans == {"usable": True, "reason": "selected", "candidates": ["box"]}


def test_on_the_frontier_but_not_chosen_is_usable_and_says_what_would_change_it():
    """Certified, on the frontier, not selected: a real option for an operator with a lower floor."""
    e = entry(["dear"], ranked=[ranked("box", -0.10, 0.01, certified=True), ranked("dear", 0.00, 0.50)])
    ans = report.self_hosted_answer(e, report.frontier_for(e), self_hosted_ids={"box"})
    assert ans["usable"] is True and ans["reason"] == "on_frontier_not_chosen"
    assert "moves along the frontier" in ans["detail"]


def test_uncertified_says_more_evidence_rather_than_a_different_threshold():
    """A "no" that cannot be acted on is not an answer. The useful form names what would change it, and
    widening a margin is not that."""
    e = entry(["dear"], ranked=[ranked("box", -0.30, 0.01, certified=False),
                                ranked("dear", 0.00, 0.50)])
    ans = report.self_hosted_answer(e, report.frontier_for(e), self_hosted_ids={"box"})
    assert ans["usable"] is False and ans["reason"] == "not_certified"
    assert "more evidence, not a different threshold" in ans["detail"]


def test_an_uncertified_point_on_the_frontier_is_still_not_usable():
    """The bug this ordering fixes. An uncertified candidate CAN sit on the frontier -- it is cheap and its
    bound is low, so nothing dominates it -- and an earlier version reported it as "usable, just move along
    the frontier". Moving along a frontier to an uncertified point is the selection-invalid step this
    project measured: bounds 6.7 points below point estimates, 9 of 10 floors unwarranted."""
    e = entry(["dear"], ranked=[ranked("box", -0.10, 0.01, certified=False),
                                ranked("dear", 0.00, 0.50, certified=True)])
    fr = report.frontier_for(e)
    box = next(p for p in fr if p["candidate"] == "box")
    assert box["on_frontier"] is True, "cheap and undominated, so genuinely on the frontier"
    ans = report.self_hosted_answer(e, fr, self_hosted_ids={"box"})
    assert ans["usable"] is False and ans["reason"] == "not_certified", \
        "on the frontier is not a licence; a bound is"


def test_no_record_is_distinguished_from_not_certified():
    e = entry(["dear"], ranked=[ranked("dear", 0.0, 0.5)])
    ans = report.self_hosted_answer(e, report.frontier_for(e), self_hosted_ids={"box"})
    assert ans["reason"] == "no_record"


def test_every_reason_is_from_the_closed_set():
    """A free-text reason cannot be aggregated across families, so the set is closed and this holds it."""
    cases = [
        (entry(["box"], ranked=[ranked("box", 0.0, 0.01)]), {"box"}),
        (entry(["dear"], ranked=[ranked("box", -0.1, 0.01), ranked("dear", 0.0, 0.5)]), {"box"}),
        (entry(["dear"], ranked=[ranked("box", -0.3, 0.01, certified=False), ranked("dear", 0.0, 0.5)]),
         {"box"}),
        (entry(["dear"], ranked=[ranked("dear", 0.0, 0.5)]), {"box"}),
        (entry(["dear"], ranked=[ranked("dear", 0.0, 0.5)]), set()),
    ]
    for e, ids in cases:
        ans = report.self_hosted_answer(e, report.frontier_for(e), self_hosted_ids=ids)
        assert ans["reason"] in report.NOT_USABLE_REASONS, ans


# --- annotate is additive, so an existing reader is unaffected ------------------------------------


def test_annotate_adds_the_three_keys_and_changes_nothing_else():
    table = {"families": {"f": {"cannot_reject": entry(["box"], ranked=[ranked("box", 0.0, 0.01)]),
                                "can_reject": entry(["box"], ranked=[ranked("box", 0.0, 0.01)]),
                                "evidence": {"nested": True}}}}
    before = dict(table["families"]["f"]["evidence"])
    report.annotate(table, self_hosted_ids={"box"})
    e = table["families"]["f"]["cannot_reject"]
    assert {"policy_kind", "policy_kind_reason", "frontier", "self_hosted"} <= set(e)
    assert e["chosen"] == ["box"], "the existing fields are untouched"
    assert table["families"]["f"]["evidence"] == before


def test_render_states_all_three_for_every_family():
    table = {"families": {"f": {"cannot_reject": entry(["box"], ranked=[ranked("box", 0.0, 0.01)])}}}
    report.annotate(table, self_hosted_ids={"box"})
    text = report.render(table)
    assert "policy" in text and "self-hosted usable" in text and "on frontier" in text


# --- a cost figure travels with the basis it was priced on ----------------------------------------


def test_the_basis_of_each_cost_is_rendered_below_the_table():
    """A cost without its basis invites the reader to take it as the deployment's. The first figure this
    project produced was $0.25 per request -- six times the token side, entirely because one experimenter at
    concurrency 1 left the GPU idle. True, and useless to anyone who cannot see the concurrency."""
    table = {"families": {"f": {"cannot_reject": entry(["box"], ranked=[
        {"arrangement": ["box"], "kind": "outright", "quality_lcb": 0.0, "cost_per_request": 0.250665,
         "certified": True, "note": "priced on its hourly reservation divided by throughput at concurrency 1"},
    ])}}}
    report.annotate(table, self_hosted_ids={"box"})
    text = report.render(table)
    assert "0.250665" in text
    assert "- `box`: priced on its hourly reservation" in text


def test_a_candidate_the_compiler_did_not_qualify_gets_no_empty_bullet():
    table = {"families": {"f": {"cannot_reject": entry(["box"], ranked=[ranked("box", 0.0, 0.01)])}}}
    report.annotate(table, self_hosted_ids={"box"})
    assert "- `box`:" not in report.render(table)


def test_selected_renders_without_a_trailing_dash():
    """`selected` has nothing to add, and a dangling em dash reads like a truncated sentence."""
    table = {"families": {"f": {"cannot_reject": entry(["box"], ranked=[ranked("box", 0.0, 0.01)])}}}
    report.annotate(table, self_hosted_ids={"box"})
    line = next(x for x in report.render(table).splitlines() if "self-hosted usable" in x)
    assert line.rstrip().endswith("(selected)")
