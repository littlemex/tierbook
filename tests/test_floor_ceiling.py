"""CONTRACT C5 (docs/changes/v0.3.0-scope/CONTRACT.md): the ceiling is reported, and something reads it.

A declared floor above `alpha ** (1/n)` can never be cleared, whatever the measurement says. The shipped ledger
declares `tool-agent-user-retail` at 0.92 on a 20-item cohort whose ceiling is 0.8609 -- an impossible floor. Before
this entry, an impossible floor and no floor at all produced byte-identical `compile`/`route` output, `certified:
true` either way, with no warning anywhere (R7 in the contract's own findings).

The fix has two halves and both are tested here, separately, because a fix that only did the first half would still
be R16's mistake repeated a third time: `bound_kind` and two `"warning"` strings were already written into artifacts
and read by nobody.

    1. The compiler computes the ceiling and the cohort size the declared floor would need, and RECORDS both
       (`compile_policy` writes `floor_ceiling` into `Policy.parameters`). It does not refuse -- R3 established
       that an unreachable floor is a true fact about the evidence budget, and SCOPE sections 2, 8 and 12 all make
       serving the declared default uncertified the correct behaviour in that state.
    2. A criterion READS it (`accept.CRITERIA` gains `floor_is_reachable`, the tenth criterion), so an unreachable
       floor is a stated verdict rather than a comment in JSON nobody consults.

Following the convention `tests/test_bound_provenance.py` and `tests/test_bound_guards.py` already use: every test
below states, in its docstring, the defect it catches, not just what it calls.

Nothing here asserts on the internal shape of the `floor_ceiling` value `compile_policy` writes -- the contract does
not pin one. Wherever this file needs the ceiling and the required cohort size for a real family, it gets them from
`accept.floor_reachable` itself (the one function the interface DOES pin), or it reads them back out of the verdict's
own human-readable `detail`, through the CLI, the way an operator actually would.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import accept as ac  # noqa: E402
from tierbook import cli  # noqa: E402
from tierbook import decide as D  # noqa: E402
from tierbook import policy as P  # noqa: E402

EXAMPLE_TIERS = ROOT / "examples" / "ledger" / "tiers"
EXAMPLE_CANDIDATES = ROOT / "examples" / "ledger" / "candidates.json"

# The shipped ledger's own declared floors (examples/ledger/candidates.json), on the same 20-item cohort
# (examples/ledger/tiers/api-strong-a.json's `tool-agent-user-retail` and `agentic-coding` outcomes both carry
# `"attempted": 20`, and every one of the three shipped tiers agrees on that count for both families -- checked
# below in `test_the_shipped_ledgers_cohort_really_is_twenty_for_both_families` so the rest of this file is not
# resting on an unstated assumption).
RETAIL_FLOOR = 0.92
AGENTIC_FLOOR = 0.80
SHIPPED_COHORT_N = 20
SIGNIFICANCE = 0.05  # the only alpha the contract's own checked-claims table cites: clopper_pearson_lower(20, 20, 0.05)


def run_cli(argv: list[str]) -> int:
    """Same normalisation every other CLI test file in this suite uses."""
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


def _brute_force_min_n(floor: float, alpha: float, cap: int = 100_000) -> int:
    """An oracle for 'the smallest n at which the floor becomes reachable', computed independently of
    `accept.floor_reachable` by the most literal possible reading of the definition, so a test comparing the two
    is not just comparing the implementation with itself under a different name."""
    n = 1
    while alpha ** (1.0 / n) < floor:
        n += 1
        if n > cap:
            raise AssertionError(f"no n <= {cap} reaches floor={floor} at alpha={alpha}")
    return n


def _mentions(detail: str, value: float) -> bool:
    """Whether a verdict's human-readable `detail` plausibly states this number, under any of the formats this
    codebase's other `Verdict` detail strings already use: a bare decimal (`0.92`), a decimal rounded to four
    places (`0.8609`), or a percentage (`92%`, `92.0%`, `86.09%`) -- `_rate_against_floor`'s own FAIL message
    formats a floor as `{floor:.1%}`, so a new criterion's message is not guaranteed to use the plain decimal.
    This file does not pin `floor_ceiling`'s internal shape; it should not quietly pin a display format either."""
    candidates = {
        str(value), f"{value:.2f}", f"{value:.4f}",
        f"{value * 100:.0f}%", f"{value * 100:.1f}%", f"{value * 100:.2f}%",
    }
    return any(c in detail for c in candidates)


# =====================================================================================================
# Section 1 -- `accept.floor_reachable(n, floor, alpha) -> tuple[bool, float, int]`, in isolation.
# =====================================================================================================


def test_floor_reachable_returns_a_reachable_flag_a_ceiling_and_a_required_cohort():
    """The interface's own shape: three values, not a bundled dict and not a bare bool -- a caller that only got
    the bool would have nowhere to report the ceiling or the cohort size a fix would need."""
    reachable, ceiling, required_n = ac.floor_reachable(20, 0.80, 0.05)
    assert isinstance(reachable, bool)
    assert isinstance(ceiling, float)
    assert isinstance(required_n, int)


@pytest.mark.parametrize("n,alpha", [(5, 0.05), (20, 0.05), (100, 0.01), (3, 0.5), (1, 0.05)])
def test_the_ceiling_is_alpha_to_the_one_over_n(n, alpha):
    """Asserted as a RELATION, not against a decimal literal: a fixed implementation could hardcode 0.8609 for
    n=20 and pass a test that only tried n=20. Sweeping n and alpha and checking the relation itself is what a
    hardcoded constant cannot survive."""
    _, ceiling, _ = ac.floor_reachable(n, 0.5, alpha)
    assert ceiling == pytest.approx(alpha ** (1.0 / n))


@pytest.mark.parametrize("floor,ceiling_n,alpha", [(0.80, 20, 0.05), (0.92, 20, 0.05), (0.5, 5, 0.05)])
def test_reachable_is_true_exactly_when_the_floor_does_not_exceed_the_ceiling(floor, ceiling_n, alpha):
    """The boolean is not a second, independently-tunable knob -- it must be the direct comparison against the
    ceiling this same call computed, in both directions."""
    reachable, ceiling, _ = ac.floor_reachable(ceiling_n, floor, alpha)
    assert reachable == (floor <= ceiling)


def test_reachable_is_true_on_the_boundary_where_the_floor_equals_the_ceiling_exactly():
    """The inclusive edge: a floor declared at exactly the ceiling is reachable, not almost. Fed back the ceiling
    this same function just computed, so this is not comparing against an independently-rounded literal that
    floating point could make it miss by an epsilon."""
    _, ceiling, _ = ac.floor_reachable(20, 0.5, 0.05)
    reachable_at_boundary, _, _ = ac.floor_reachable(20, ceiling, 0.05)
    assert reachable_at_boundary is True


@pytest.mark.parametrize("floor,alpha", [(0.92, 0.05), (0.80, 0.05), (0.999, 0.01), (0.5, 0.5), (0.6, 0.2)])
def test_the_required_cohort_matches_an_independent_brute_force_search(floor, alpha):
    """Pins `floor_reachable`'s third return value against an oracle written from the definition alone
    (`_brute_force_min_n` above), not against the implementation calling itself under a different name."""
    _, _, required_n = ac.floor_reachable(SHIPPED_COHORT_N, floor, alpha)
    assert required_n == _brute_force_min_n(floor, alpha)


@pytest.mark.parametrize("floor,alpha", [(0.92, 0.05), (0.80, 0.05), (0.999, 0.01), (0.6, 0.2)])
def test_the_required_cohort_is_truly_the_minimum_not_merely_sufficient(floor, alpha):
    """The word 'smallest' is load-bearing: a required_n one larger than necessary would still make every
    caller-visible check above pass, since 'sufficient' is a weaker claim than 'minimal'. Checked the only way a
    minimum can be checked -- it must work, and one less must not."""
    _, _, required_n = ac.floor_reachable(SHIPPED_COHORT_N, floor, alpha)
    reachable_at_required, _, _ = ac.floor_reachable(required_n, floor, alpha)
    assert reachable_at_required is True, "the claimed minimum does not itself reach the floor"
    if required_n > 1:
        reachable_one_below, _, _ = ac.floor_reachable(required_n - 1, floor, alpha)
        assert reachable_one_below is False, "one cohort smaller already reaches the floor, so this was not the minimum"


def test_the_worked_example_the_contract_checked_by_hand():
    """The contract's own 'every claim checked' table: `clopper_pearson_lower(20, 20, 0.05)` is 0.8609, and the
    shipped ledger declares `tool-agent-user-retail` at 0.92 on exactly that cohort -- above the ceiling, so
    unreachable. `agentic-coding`'s 0.80 on the same cohort is below it, so reachable. If this test ever fails, the
    two CLI-level tests further down are testing a fixture that no longer matches the contract's own example."""
    retail_reachable, retail_ceiling, retail_required_n = ac.floor_reachable(SHIPPED_COHORT_N, RETAIL_FLOOR, SIGNIFICANCE)
    assert retail_ceiling == pytest.approx(0.8609, abs=5e-5)
    assert retail_reachable is False
    assert retail_required_n > SHIPPED_COHORT_N

    agentic_reachable, agentic_ceiling, _ = ac.floor_reachable(SHIPPED_COHORT_N, AGENTIC_FLOOR, SIGNIFICANCE)
    assert agentic_ceiling == pytest.approx(0.8609, abs=5e-5)
    assert agentic_reachable is True


@pytest.mark.parametrize("bad_n", [0, -1, -20])
def test_n_at_most_zero_is_refused_by_c14s_rule(bad_n):
    """C14's own rule, restated for this function rather than only for `clopper_pearson_lower`: `alpha ** (1/n)`
    at `n <= 0` either divides by zero or, for a negative n, produces a number nobody asked for. C14's finding was
    exactly this shape of bug -- a caller that passed the wrong argument in the wrong slot got a plausible-looking
    number back instead of a refusal (transposed `(n, k)` returning a HIGH bound, 0.8293 against a true 0.4922).
    A silently-accepted `n <= 0` here would be the same defect in a new function: an argument-order mistake that
    reads as an answer."""
    with pytest.raises(ValueError):
        ac.floor_reachable(bad_n, 0.80, 0.05)


# =====================================================================================================
# Section 2 -- `compile_policy` writes `floor_ceiling` into `Policy.parameters`, and only when there is
# evidence to compute it from.
# =====================================================================================================


def test_compile_policy_writes_no_floor_ceiling_when_the_family_has_no_evidence_to_count():
    """`floor_ceiling` needs a cohort size to compute a ceiling from. A family this compile has never seen any
    tier measure at all has no cohort to derive one from, and inventing one (n=0? n=1?) would be reporting a
    ceiling the evidence never earned -- the same mistake R1 rejects for the bound itself, one door over."""
    pol = D.compile_policy("nobody-has-measured-this-family", {}, reserved_ids=set(), metered_ids=set(),
                          default=("fallback",), default_declared_by="test", floor=0.80, tiers={})
    assert pol.parameters.get("floor_ceiling") is None


def test_compile_policy_writes_floor_ceiling_when_the_family_has_evidence():
    """The real shipped ledger, called through `compile_policy` directly (not only through the CLI), for both
    families -- `entry={}` still takes the 'nothing was validated' early-return branch inside `compile_policy`,
    which is exactly the branch the shipped ledger's own compile takes today (see Section 4 below), and the
    ceiling must be recorded on that branch too: an unreachable floor is discovered by looking at the ledger, not
    by looking at whether any rule happened to fire."""
    tiers = P.load_registry(EXAMPLE_TIERS)
    for family, floor in (("tool-agent-user-retail", RETAIL_FLOOR),
                          ("agentic-coding", AGENTIC_FLOOR)):
        pol = D.compile_policy(family, {}, reserved_ids=set(), metered_ids=set(),
                              default=("api-strong-a",), default_declared_by="test", floor=floor, tiers=tiers)
        assert pol.parameters.get("floor_ceiling") is not None, family


def test_a_policy_with_no_floor_declared_does_not_crash_computing_floor_ceiling():
    """A family may decline to declare a floor at all (`floor=None` is legal everywhere else this codebase reads
    it). `floor_ceiling`'s own required-cohort half is meaningless with no floor to reach, so this must not raise
    even though evidence exists."""
    tiers = P.load_registry(EXAMPLE_TIERS)
    D.compile_policy("agentic-coding", {}, reserved_ids=set(), metered_ids=set(),
                     default=("api-strong-a",), default_declared_by="test", floor=None, tiers=tiers)


def test_from_dict_loads_an_artifact_whose_parameters_lack_floor_ceiling():
    """The v0.2.0 shape, at the loader boundary: `parameters` present (C2 already requires it) but with no
    `floor_ceiling` key inside it. This must NOT be refused the way a wholly absent `parameters` or `candidates`
    key is refused -- C5 adds a criterion that reads `floor_ceiling` as UNSUPPORTED when absent, which only means
    something if an artifact missing it still loads at all."""
    raw = {
        "family": "fam", "default": ["api"], "validated": False, "note": "", "domain": {}, "provenance": {},
        "rules": [],
        "parameters": {"floor": 0.80, "max_evidence_age_days": None, "staleness_limit_days": None},
        "candidates": ["api"],
    }
    pol = D.from_dict(raw)
    assert pol.parameters.get("floor_ceiling") is None


# =====================================================================================================
# Section 3 -- end to end, on the real shipped ledger, through the documented CLI. This is where the criterion's
# verdict is checked, without this file ever having to guess `floor_ceiling`'s internal shape or any new keyword
# argument's name: `compile` writes the artifact, `accept` reads it, and only the printed JSON is inspected.
# =====================================================================================================


def _compile_shipped_ledger(tmp_path) -> dict:
    out_path = tmp_path / "table.json"
    rc = run_cli(["compile", "--config", str(EXAMPLE_CANDIDATES), "--out", str(out_path),
                 "--registry", str(EXAMPLE_TIERS)])
    assert rc == 0, "compile must succeed on the shipped ledger even though one family's floor is unreachable"
    return json.loads(out_path.read_text())


def _accept(tmp_path, policy_dict: dict, tag: str) -> dict:
    """Run `tierbook accept` against a policy artifact exactly the way an operator would: write it to disk, point
    `--log` at a file that is never created (an absent log reads as empty, per `test_policy_parameters.py`), and
    read back the JSON `--out` writes."""
    policy_path = tmp_path / f"policy-{tag}.json"
    policy_path.write_text(json.dumps(policy_dict))
    log_path = tmp_path / f"log-{tag}.jsonl"
    out_path = tmp_path / f"out-{tag}.json"
    rc = run_cli(["accept", "--log", str(log_path), "--policy", str(policy_path), "--out", str(out_path)])
    return {"rc": rc, "out": json.loads(out_path.read_text())}


def _verdict(result: dict, criterion: str) -> dict:
    matches = [v for v in result["out"]["verdicts"] if v["criterion"] == criterion]
    assert len(matches) == 1, f"expected exactly one verdict for {criterion!r}, got {matches}"
    return matches[0]


def test_the_shipped_ledgers_cohort_really_is_twenty_for_both_families():
    """Guards the constants at the top of this file against the fixture changing under it: every shipped tier
    must agree its evidence for both families is 20 items, since the rest of this section's numeric assertions
    (0.8609, the required cohort of 36) are only correct for n=20."""
    tiers = P.load_registry(EXAMPLE_TIERS)
    for tier in tiers.values():
        for family in ("agentic-coding", "tool-agent-user-retail"):
            assert (tier.outcome(family) or {}).get("attempted") == SHIPPED_COHORT_N, (tier.id, family)


def test_compiling_the_shipped_ledger_does_not_refuse_the_retail_familys_unreachable_floor(tmp_path):
    """The R3 requirement, checked at the only place it can fail visibly: `compile`'s exit code. `tool-agent-
    user-retail` declares 0.92 on a 20-item cohort whose ceiling is 0.8609 -- an impossible floor -- and R3
    rejected refusing to compile that as an outage manufactured from a true fact about the evidence budget.
    SCOPE sections 2, 8 and 12 all make serving the default uncertified the correct behaviour instead."""
    table = _compile_shipped_ledger(tmp_path)
    entry = table["decide"]["tool-agent-user-retail"]["cannot_reject"]
    # And the default really is what gets served, uncertified: nothing here refused down to an error state, and
    # nothing here manufactured a certification the evidence cannot support either.
    assert entry["default"], "an unreachable floor must still leave a default to fall back to"
    pol = D.from_dict(entry)
    decision = D.decide(pol, {})
    assert decision["assign"] == list(pol.default)
    assert decision["validated"] is False


def test_the_compiled_artifact_records_floor_ceiling_for_both_shipped_families(tmp_path):
    """The write half of C5, on the real ledger rather than a hand-built one: whatever `compile_policy` writes,
    it must be present -- not merely present in the artifact the CLI happens to keep in memory, but written all
    the way out to the file on disk, since that is the only copy `accept --policy` ever reads back."""
    table = _compile_shipped_ledger(tmp_path)
    for family in ("agentic-coding", "tool-agent-user-retail"):
        params = table["decide"][family]["cannot_reject"]["parameters"]
        assert params.get("floor_ceiling") is not None, family


def test_the_retail_familys_unreachable_floor_fails_floor_is_reachable_naming_both_numbers(tmp_path):
    """The read half of C5, on the exact case the contract states by name: `tool-agent-user-retail` at 0.92 on a
    20-item cohort. This must be reported as a stated FAIL -- naming the declared floor, the ceiling, and the
    cohort size the floor would need -- and not as a silent pass or an unread warning string, which is R7's
    finding and R16's rejected alternative."""
    table = _compile_shipped_ledger(tmp_path)
    result = _accept(tmp_path, table["decide"]["tool-agent-user-retail"]["cannot_reject"], "retail")
    v = _verdict(result, "floor_is_reachable")
    assert v["verdict"] == "fail"
    _, ceiling, required_n = ac.floor_reachable(SHIPPED_COHORT_N, RETAIL_FLOOR, SIGNIFICANCE)
    detail = v["detail"]
    assert _mentions(detail, RETAIL_FLOOR), f"the declared floor must be named: {detail!r}"
    assert _mentions(detail, ceiling), f"the ceiling must be named: {detail!r}"
    assert str(required_n) in detail, f"the cohort size the declared floor would need must be named: {detail!r}"


def test_the_agentic_coding_familys_floor_passes_on_the_identical_cohort(tmp_path):
    """`agentic-coding` declares 0.80 on the SAME 20-item cohort whose ceiling is 0.8609 -- reachable, so this
    must PASS. Paired with the FAIL above, on one compile of one ledger, this is the test that shows the
    criterion is not returning a constant: the ceiling is identical between the two calls and the verdict is
    not."""
    table = _compile_shipped_ledger(tmp_path)
    result = _accept(tmp_path, table["decide"]["agentic-coding"]["cannot_reject"], "agentic")
    v = _verdict(result, "floor_is_reachable")
    assert v["verdict"] == "pass"


def test_fail_and_pass_sit_side_by_side_on_one_ledger_proving_the_criterion_is_not_a_constant(tmp_path):
    """Restates the previous two tests as one comparison, which is the actual claim: a criterion that always
    returned FAIL (or always PASS) regardless of the artifact handed to it would pass either test above in
    isolation. It cannot pass both of these at once."""
    table = _compile_shipped_ledger(tmp_path)
    retail = _verdict(_accept(tmp_path, table["decide"]["tool-agent-user-retail"]["cannot_reject"], "retail2"),
                      "floor_is_reachable")
    agentic = _verdict(_accept(tmp_path, table["decide"]["agentic-coding"]["cannot_reject"], "agentic2"),
                       "floor_is_reachable")
    assert retail["verdict"] == "fail"
    assert agentic["verdict"] == "pass"
    assert retail["verdict"] != agentic["verdict"]


def test_an_artifact_with_no_floor_ceiling_is_unsupported_not_a_silent_pass(tmp_path):
    """The v0.2.0 case, built from the real compiled artifact with exactly one key removed: an artifact that
    never recorded `floor_ceiling` must report UNSUPPORTED for this criterion, not PASS (which would be exactly
    R7's defect: an impossible floor and 'nothing was checked' becoming indistinguishable) and not FAIL (which
    would accuse a floor that was never evaluated). Built by deleting the key from a real compiled artifact
    rather than hand-writing one, so this is the actual key `compile_policy` writes and not a guess at its name."""
    table = _compile_shipped_ledger(tmp_path)
    entry = dict(table["decide"]["tool-agent-user-retail"]["cannot_reject"])
    entry["parameters"] = {k: v for k, v in entry["parameters"].items() if k != "floor_ceiling"}
    assert "floor_ceiling" not in entry["parameters"], "the fixture must actually lack the key for this to be the case"
    result = _accept(tmp_path, entry, "no-ceiling")
    v = _verdict(result, "floor_is_reachable")
    assert v["verdict"] == "unsupported"


# =====================================================================================================
# Section 4 -- `accept.CRITERIA` grows to ten, and `check_all` keeps working for a caller that supplies nothing
# new at all (backward compatibility every prior amendment to `check_all`'s keyword arguments preserved).
# =====================================================================================================


def test_criteria_has_ten_entries_including_floor_is_reachable():
    """SCOPE section 12 defines nine criteria; C5 in v0.2.0 kept `floor_compliance` as one criterion carrying two
    rates specifically to avoid a tenth. This entry reverses that on purpose, for a different reason: floor
    reachability is a question about the declared floor against its own cohort, not about traffic against the
    floor, so it is a different criterion rather than a second rate folded into an existing one."""
    assert len(ac.CRITERIA) == 10
    assert "floor_is_reachable" in ac.CRITERIA


def test_check_all_with_no_new_argument_still_returns_ten_verdicts(tmp_path):
    """A caller written before this entry -- every existing call site in this test suite included -- passes none
    of whatever new keyword argument carries the ceiling information. That call must still succeed and must still
    get a verdict for every one of the ten criteria, `floor_is_reachable` among them, reported as UNSUPPORTED
    rather than raising `TypeError` for a newly-required argument nobody old ever supplied."""
    got = ac.check_all([], {}, floor=0.80)
    assert len(got) == len(ac.CRITERIA) == 10
    assert [v.criterion for v in got] == list(ac.CRITERIA)
    v = next(v for v in got if v.criterion == "floor_is_reachable")
    assert v.verdict == ac.UNSUPPORTED
