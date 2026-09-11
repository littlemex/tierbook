"""CONTRACT v0.3.0 C4 -- the door to a labelled log.

`Log.attach_outcome` and `record.classify_label` already existed; a family already declares a labeller and a
maximum label latency. What did not exist was any CLI verb reaching either of them, and no mention in
`README.md`, `SCOPE.md` or any `--help` -- an operator working from the documented surface could not produce a
labelled log without reading `src/`, so every criterion needing a realised rate was permanently `unsupported`
for them, and the report attributed that to a missing MEASUREMENT rather than to a missing DOOR.

`tierbook attach-outcome --log <path> --request-id <id> --label-state <state> [--label true|false] [--tokens N]
[--latency-s S]`. Three exit codes: 0 on success, 2 on a missing required argument, 1 when the log refuses the
outcome. It attaches. It does not read a family's `label_source`, does not invoke anything, and does not decide
`label_state` -- `classify_label` owns that and the caller states what it observed.

CONTRACT amendment 11 found two more refusals needed than the interface's own sentence claimed, and both are one
shape: **the door reports success and the operator's label does not land.** A label that changes used to be
accepted at append time, with the refusal coming one `Log.read()` later -- after which the log is unreadable and
append-only means the mistake cannot be taken back. An outcome for a `request_id` the log does not contain used
to be accepted outright and landed as an orphan nothing will ever read, leaving a realised-rate criterion
`unsupported` for a reason the report calls "missing measurement" when the true reason is a typo -- which is
word for word the failure this door exists to end, reproduced by the door itself. So the verb reads the log
BEFORE it appends, and refuses both at the door, in addition to `Log.attach_outcome`'s own append-time refusal
for an out-of-enum state or a state/label mismatch, which already worked. `Log.read()`'s own refusal for a
changed label is UNCHANGED and stays: it refuses a log written by anything else -- a second implementation, an
older version, a hand edit -- which the door cannot see coming.

Only C4 is in scope here. Nothing about `assign`'s own certification arithmetic (C1), the ceiling (C5) or the
candidate set (C6) is tested in this file; where a test needs a log with a decision in it, the decision is built
directly through `record.Decision`/`record.Log` -- the documented, producer-agnostic shape `cli.py`'s own first
paragraph already certifies ("anything that can write a record in the documented shape is a valid producer of
one") -- rather than through `assign`, so a change to a different contract entry's arithmetic cannot break a C4
test for a reason that has nothing to do with the door.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook import cli  # noqa: E402
from tierbook import record as rec  # noqa: E402


def run_cli(argv: list) -> int:
    """Invoke the CLI through its documented entry point, normalising `SystemExit` the way
    `test_policy_parameters.py` and `test_falsifier_freshness.py` already do: `cli.main` sometimes returns a
    status and sometimes raises `SystemExit` (argparse's own errors do), and a CLI test should assert on the
    exit status, not on which mechanism produced it."""
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


def cand(cid="box", why="chosen", bound=0.82, cost=0.004):
    """`bound_provenance` (CONTRACT C1) travels paired with `bound`; an honest bound this release could
    actually produce. Copied from `test_record.py`'s own helper rather than imported, the same reasoning
    `test_label_declaration.py` gives for keeping its fixtures apart from the bigger ledger: a C4 test failing
    because a C1 fixture helper changed shape would be harder to read than it needs to be."""
    return rec.Candidate(id=cid, excluded_because=why, bound=bound, cost_usd=cost,
                         evidence_as_of="2026-09-01",
                         bound_provenance=(None if bound is None else
                                           rec.BoundProvenance(estimator="clopper_pearson_fixed_sample",
                                                               confidence=0.95)))


def decision(**kw) -> rec.Decision:
    """A minimal, otherwise-complete `Decision` -- `certified=False` by default, since none of these tests are
    about certification (C1's subject); a test that needs `certified=True` overrides it explicitly."""
    base = dict(
        family="agentic-coding", request_id="r1", feature_vector_version="fv1", state_ref="obs:abc",
        candidates=[cand()], chosen="box",
        selection_probability=1.0, exploration=False, certified=False, policy_version="p1",
        policy_digest="0123456789abcdef",
        mechanism_version="0.3.0", agent="opencode", model="Qwen/Qwen3.6-35B-A3B",
        endpoint="http://vllm:8000", gateway_quote_usd=0.004, gateway_authorised=True, decided_at=1_000_000.0,
        exploration_reason="no_mechanism", eligible_set=[])
    base.update(kw)
    return rec.Decision(**base)


def build_log(path: Path, *decisions: rec.Decision) -> rec.Log:
    log = rec.Log(path)
    for d in decisions:
        log.append(d)
    return log


# --- exit 2: a missing required argument -------------------------------------------------------------------


def test_missing_log_exits_2(tmp_path):
    rc = run_cli(["attach-outcome", "--request-id", "r1", "--label-state", "labelled", "--label", "true"])
    assert rc == 2


def test_missing_request_id_exits_2(tmp_path):
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision())
    rc = run_cli(["attach-outcome", "--log", str(log_path), "--label-state", "labelled", "--label", "true"])
    assert rc == 2


def test_missing_label_state_exits_2(tmp_path):
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision())
    rc = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1", "--label", "true"])
    assert rc == 2


# --- exit 0: success, and what a successful attach actually records --------------------------------------


def test_a_labelled_outcome_for_a_real_request_exits_0_and_is_readable(tmp_path):
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1"))
    rc = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1",
                 "--label-state", "labelled", "--label", "true"])
    assert rc == 0
    decisions, outcomes = rec.Log(log_path).read()
    assert len(decisions) == 1
    assert outcomes["r1"]["label_state"] == "labelled" and outcomes["r1"]["label"] is True


@pytest.mark.parametrize("state", ["missing", "pending"])
def test_a_missing_or_pending_outcome_with_no_label_flag_exits_0(tmp_path, state):
    """The positive contrast the two label-state refusal tests below need: a state that does not carry a label
    (`missing`, `pending`) must succeed with `--label` simply absent, or a fixer that refuses every call
    unconditionally would still pass the refusal tests on their own."""
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1"))
    rc = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1", "--label-state", state])
    assert rc == 0
    _, outcomes = rec.Log(log_path).read()
    assert outcomes["r1"]["label_state"] == state and outcomes["r1"]["label"] is None


def test_tokens_and_latency_s_are_recorded_under_their_own_flag_names(tmp_path):
    """`[--tokens N] [--latency-s S]` are the interface's own two optional fields, and `record.Log`'s own
    `**outcome` kwargs already use exactly these key names (`test_record.py`,
    `log.attach_outcome(..., tokens=1234, latency_s=41.0)`), so a door that forwards them under a different key
    would leave the recorded outcome unreadable by anything that expects the established names."""
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1"))
    rc = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1",
                 "--label-state", "labelled", "--label", "true", "--tokens", "1234", "--latency-s", "41.0"])
    assert rc == 0
    _, outcomes = rec.Log(log_path).read()
    assert outcomes["r1"]["tokens"] == 1234
    assert outcomes["r1"]["latency_s"] == 41.0


def test_a_pending_outcome_later_superseded_by_a_real_label_exits_0_both_times(tmp_path):
    """`record.Log.read`'s own long-standing rule: 'a pending or missing outcome may be superseded by a real
    label, because that is the label arriving rather than changing.' The door's amendment-11 pre-append check
    must apply the SAME definition of 'changed' the reader does, not a stricter one that would block this
    legitimate transition -- a door that refused any second attach for an already-outcome-bearing request would
    still pass every amendment-11 test below while breaking this one."""
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1"))
    rc1 = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1", "--label-state", "pending"])
    assert rc1 == 0
    rc2 = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1",
                  "--label-state", "labelled", "--label", "true"])
    assert rc2 == 0
    _, outcomes = rec.Log(log_path).read()
    assert outcomes["r1"]["label_state"] == "labelled" and outcomes["r1"]["label"] is True


# --- exit 1: the log refuses the outcome, with record.Incomplete's own message, UNMODIFIED -----------------


def test_an_out_of_enum_label_state_exits_2_naming_the_tuple(tmp_path, capsys):
    """Deliberately changed by CONTRACT amendment 13.1. This asserted exit 1, and the interface stated no code for
    this case at all -- exit 1 is "the log refuses the outcome", exit 2 is a usage error, and a value outside the
    enum never reaches the log to be refused. The operator typed something the flag does not accept, which is the
    class exit 2 already means everywhere else in this CLI, so it fails before the log is opened.

    The tuple must still be named, which is the part of the contract that was never in doubt."""
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1"))
    rc = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1", "--label-state", "bogus"])
    assert rc == 2
    err = capsys.readouterr().err
    for state in rec.LABEL_STATES:
        assert state in err, f"{state!r} is not named in the refusal: {err!r}"


@pytest.mark.parametrize("state,label", [("labelled", None), ("missing", True), ("pending", False)])
def test_a_label_state_label_mismatch_exits_1_with_the_disagreement_body_carried_through(tmp_path, capsys, state, label):
    """The second half of amendment 11's case 1: `label_state` says one thing and `label` says another --
    `labelled` with no label, or a non-`labelled` state carrying one. Three of the four illegal combinations
    `test_record.py::test_an_outcome_whose_label_state_disagrees_with_its_label_is_refused` already drives at
    the `record.Log` level; this drives the same three through the CLI and checks the stderr text.

    Deliberately changed by CONTRACT amendment 13.2. This asserted a byte-exact BARE message, on the interface's
    word "unmodified". Read against `cli.py`, `refused: {e}` is the established form at six existing sites, so the
    sentence asked one verb to print bare where every sibling prints a marker. What "unmodified" was protecting is
    the message BODY -- not reworded, not truncated, not replaced by a paraphrase -- and that is what is asserted
    here, so a future author who rewords it still fails."""
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1"))
    argv = ["attach-outcome", "--log", str(log_path), "--request-id", "r1", "--label-state", state]
    if label is not None:
        argv += ["--label", "true" if label else "false"]
    rc = run_cli(argv)
    assert rc == 1
    err = capsys.readouterr().err
    body = f"label_state {state!r} and label {label!r} disagree"
    assert err.strip() == f"refused: {body}"


# --- exit 1: amendment 11's two NEW door-side refusals, checked BEFORE the append happens -------------------


def test_a_changed_label_is_refused_before_a_second_line_is_appended(tmp_path):
    """Amendment 11 case 2: 'appended label=False, then label=True for the same request' used to be ACCEPTED,
    with the refusal arriving only from a later `Log.read()` -- by which point the log is unreadable and,
    append-only, the mistake cannot be undone. The proof this test needs is not merely 'exit 1': a door that
    printed a refusal AND appended anyway would still exit 1 while reproducing exactly the defect amendment 11
    describes. So the file's own line count is checked before and after the rejected call, and the log is read
    again afterwards to confirm it is still WHOLE -- not merely that it starts with the same bytes, but that
    `Log.read()` does not raise and the original label is still what is recorded.
    """
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1"))
    rc1 = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1",
                  "--label-state", "labelled", "--label", "false"])
    assert rc1 == 0
    lines_after_first = log_path.read_text().splitlines()
    assert len(lines_after_first) == 2  # the decision, then the first outcome

    rc2 = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1",
                  "--label-state", "labelled", "--label", "true"])
    assert rc2 == 1

    lines_after_second = log_path.read_text().splitlines()
    assert lines_after_second == lines_after_first, (
        "the rejected, label-changing attach-outcome call appended a line anyway -- this is amendment 11's "
        "case 2 defect, reproduced by the door built to end it"
    )
    decisions, outcomes = rec.Log(log_path).read()
    assert len(decisions) == 1
    assert outcomes["r1"]["label_state"] == "labelled" and outcomes["r1"]["label"] is False


def test_an_outcome_for_an_unknown_request_id_is_refused_before_landing_as_an_orphan(tmp_path):
    """Amendment 11 case 3: an outcome for a `request_id` the log does not contain used to be accepted outright
    and land as an orphan `Log.read()` returns but nothing else will ever join to a decision -- so a
    realised-rate criterion stays `unsupported` for a reason the report calls 'missing measurement' when the
    true reason is a typo. Checked the same way as case 2: the line count must not grow, and after the refusal
    the log must still read as exactly the one decision it started with, with no trace of the mistyped id
    anywhere in `outcomes`.
    """
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1"))
    lines_before = log_path.read_text().splitlines()
    assert len(lines_before) == 1

    rc = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1-typo",
                 "--label-state", "labelled", "--label", "true"])
    assert rc == 1

    lines_after = log_path.read_text().splitlines()
    assert lines_after == lines_before, (
        "an outcome for a request_id absent from the log appended anyway -- this is amendment 11's case 3 "
        "defect (the found-on-the-way orphan), reproduced by the door built to end this class of failure"
    )
    decisions, outcomes = rec.Log(log_path).read()
    assert len(decisions) == 1 and decisions[0]["request_id"] == "r1"
    assert "r1-typo" not in outcomes
    assert "r1" not in outcomes  # the real request never received the mistyped outcome either


# --- Log.read()'s own refusal is unchanged: it still catches what the door cannot see --------------------


def test_log_read_still_refuses_a_changed_label_when_something_other_than_the_door_wrote_it(tmp_path):
    """CONTRACT amendment 11's own words: 'Log.read()'s refusal stays exactly as it is ... the door refuses
    THIS OPERATOR's mistake with a message they can act on, and the reader refuses a log written by ANYTHING
    ELSE -- a second implementation, an older version, a hand edit. Removing the reader's check because the
    door now has one would trust every future writer.' This bypasses `attach-outcome` entirely and calls
    `record.Log.attach_outcome` directly -- exactly the kind of second writer the door cannot see coming --
    and the two conflicting labels land uncontested, because `Log.attach_outcome` itself has never read the log
    before appending. `Log.read()` must still catch it, unmodified by this release.
    """
    log_path = tmp_path / "decisions.jsonl"
    log = build_log(log_path, decision(request_id="r1"))
    log.attach_outcome("r1", label_state="labelled", label=False)
    log.attach_outcome("r1", label_state="labelled", label=True)
    with pytest.raises(rec.Incomplete, match="a criterion over the rewrite"):
        rec.Log(log_path).read()


# --- the verb attaches; it does not invoke anything and does not read label_source --------------------------


def test_help_names_only_the_documented_flags(capsys):
    """The documented surface itself: `--help` must show every flag the interface names, and none of a
    labeller's own inputs (`--config`, `--policy`, `--family`, `--label-source`) -- there is no way to point
    this verb at a family declaration at all, which is the strongest observable evidence that it cannot read
    one."""
    rc = run_cli(["attach-outcome", "--help"])
    assert rc == 0
    out = capsys.readouterr().out
    for flag in ("--log", "--request-id", "--label-state", "--label", "--tokens", "--latency-s"):
        assert flag in out, f"{flag!r} is not documented in attach-outcome --help"
    for absent in ("--config", "--policy", "--family", "--label-source", "--max-label-latency-s"):
        assert absent not in out, f"{absent!r} unexpectedly appears in attach-outcome --help"


def test_an_unrecognised_labeller_input_flag_is_rejected_by_the_parser(tmp_path):
    """The complement of the help check: the parser itself refuses a flag it was never given, which is a
    second, independent proof that nothing about a labeller can be threaded through this verb -- not merely
    that `--help` forgot to print it."""
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1"))
    rc = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1",
                 "--label-state", "labelled", "--label", "true", "--label-source", "human_label"])
    assert rc == 2


def test_the_verb_never_calls_load_config_so_it_never_reaches_a_label_source(tmp_path, monkeypatch):
    """`label_source` lives only on a family's declaration in `candidates.json`
    (`config.FamilyDeclaration`, per `tests/test_label_declaration.py`), and `config.load_config` is the only
    function anywhere in this project that reads one. Arming that one function to raise and then successfully
    running `attach-outcome` is a direct spy on the only door through which the verb could reach a labeller's
    declared kind: if attach-outcome still exits 0 with `load_config` set to explode, it did not go through
    that door. Patched on both plausible binding sites -- the module it is defined in, and `cli`'s own
    module-level name for it (bound at import time the way `cmd_assign` and `cmd_accept` already use it) --
    since either style of import inside a new `cmd_attach_outcome` would otherwise slip past a spy on only one
    of them.
    """
    import tierbook.config as config_mod

    def boom(*a, **kw):
        raise AssertionError("attach-outcome must never call load_config: it does not read label_source")

    monkeypatch.setattr(config_mod, "load_config", boom)
    monkeypatch.setattr(cli, "load_config", boom, raising=False)

    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1"))
    rc = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1",
                 "--label-state", "labelled", "--label", "true"])
    assert rc == 0


# --- the reason C4 exists: the door actually closes ---------------------------------------------------------


def test_the_door_moves_a_realised_rate_criterion_off_unsupported(tmp_path, capsys):
    """The proof C4 is FOR, stated as an assertion instead of a paragraph. Before any outcome is attached,
    `floor_compliance` -- the criterion SCOPE section 12 needs a realised rate for -- is `unsupported` over a
    log holding one unlabelled decision. `attach-outcome` runs, using only the documented surface, and the SAME
    criterion over the SAME log is no longer `unsupported`. Not asserted as a specific PASS or FAIL: the
    fixture is built so a single labelled decision genuinely settles the question either way (`certified=False`
    keeps the certified population permanently unsupported and unrelated to this proof; `floor=0.99` against
    one observed failure makes the one-sided binomial tail test for the all-served population conclusive at
    `n=1`, `k=0`: `binom_tail_at_most(1, 0, 0.99) = 0.01 < 0.05`) -- what matters for THIS test is only that the
    verdict stops being the word this door exists to make avoidable.
    """
    log_path = tmp_path / "decisions.jsonl"
    build_log(log_path, decision(request_id="r1", certified=False))

    rc = run_cli(["accept", "--log", str(log_path), "--floor", "0.99"])
    assert rc == 0  # an unsupported criterion is not, on its own, a failing accept run
    before = {v["criterion"]: v["verdict"] for v in json.loads(capsys.readouterr().out)["verdicts"]}
    assert before["floor_compliance"] == "unsupported", (
        "the fixture must start unsupported, or the second half of this test could not tell 'the door closed "
        "it' apart from 'it was never unsupported to begin with'"
    )

    rc = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1",
                 "--label-state", "labelled", "--label", "false"])
    assert rc == 0
    capsys.readouterr()  # discard attach-outcome's own stdout before the next accept's is captured

    run_cli(["accept", "--log", str(log_path), "--floor", "0.99"])
    after = {v["criterion"]: v["verdict"] for v in json.loads(capsys.readouterr().out)["verdicts"]}
    assert after["floor_compliance"] != "unsupported", (
        "attach-outcome ran and the log now carries a label, but floor_compliance is still unsupported -- "
        "which is word for word the failure C4's own scope entry exists to end, reproduced by the door built "
        "to end it"
    )


# --- amendment 12: the door's backstop, for every writer that is not the door ------------------------------


def test_read_reports_an_outcome_naming_a_request_no_decision_carries(tmp_path):
    """Amendment 12. Amendment 11 justified keeping `Log.read()`'s own refusal by saying the door catches this
    operator's mistake and the reader catches a log written by anything else. Measured, that held for a changed
    label and was FALSE here: an outcome for a `request_id` no decision carries passed `read()` in silence and
    came back keyed to an id nothing matches, so the sentence claimed a backstop for two cases and had one.

    Reported rather than refused, because that is what the fact is. A rewritten label makes every criterion over
    the log a criterion over the rewrite. An orphan makes a label silently ABSENT -- a gap in the population, not
    a corruption of it -- which is `__ignored_keys__`'s shape and C11's before it: the reader names what it could
    not use instead of quietly using less."""
    log = build_log(tmp_path / "decisions.jsonl", decision(request_id="r1"))
    log.attach_outcome("r1-typo", label_state="labelled", label=True)
    decisions, outcomes = log.read()
    assert len(decisions) == 1
    got = outcomes["__orphan_outcomes__"]
    assert got["count"] == 1 and got["request_ids"] == ["r1-typo"]


def test_read_says_nothing_about_orphans_when_every_outcome_found_its_decision(tmp_path):
    """The key is absent rather than zero-valued when nothing is orphaned, the same way `__ignored_keys__` is --
    but the report layer must still carry it always, which the test below fixes in place. Absent here, so a
    caller reading the mapping cannot mistake "every label found its decision" for one more bookkeeping key."""
    log = build_log(tmp_path / "decisions.jsonl", decision(request_id="r1"))
    log.attach_outcome("r1", label_state="labelled", label=True)
    _decisions, outcomes = log.read()
    assert "__orphan_outcomes__" not in outcomes


def test_the_bookkeeping_keys_are_not_themselves_counted_as_orphans(tmp_path):
    """The orphan check walks the outcomes mapping, which is also where `read()` files `__observations__`,
    `__bad_lines__`, `__unreadable_rows__` and `__ignored_keys__`. A check that did not skip them would report
    the reader's own bookkeeping as labels that landed on nothing -- and would do it on every log carrying a
    truncated line, which is the log an operator is already trying to understand."""
    path = tmp_path / "decisions.jsonl"
    log = build_log(path, decision(request_id="r1"))
    log.attach_outcome("r1", label_state="labelled", label=True)
    with path.open("a") as fh:
        fh.write('{"truncated\n')
    _decisions, outcomes = log.read()
    assert outcomes["__bad_lines__"]["count"] == 1
    assert "__orphan_outcomes__" not in outcomes


def test_the_accept_report_carries_orphan_outcomes_always(tmp_path, capsys):
    """A realised rate can be missing from a log that VISIBLY contains labels, and this is the only thing in the
    report that says why. Present even when empty, for `ignored_keys`'s own reason: a key appearing only when
    something went wrong leaves a reader unable to tell "every label found its decision" from "this version did
    not look"."""
    path = tmp_path / "decisions.jsonl"
    log = build_log(path, decision(request_id="r1"))
    log.attach_outcome("r1-typo", label_state="labelled", label=True)
    rc = run_cli(["accept", "--log", str(path), "--floor", "0.80"])
    assert rc in (0, 1)
    report = json.loads(capsys.readouterr().out)
    assert report["orphan_outcomes"]["request_ids"] == ["r1-typo"]

    clean = tmp_path / "clean.jsonl"
    log2 = build_log(clean, decision(request_id="r1"))
    log2.attach_outcome("r1", label_state="labelled", label=True)
    run_cli(["accept", "--log", str(clean), "--floor", "0.80"])
    report2 = json.loads(capsys.readouterr().out)
    assert report2["orphan_outcomes"] == {}


def test_the_module_docstrings_verb_list_matches_help(capsys):
    """Found in phase 4: `cli.py`'s header said "deliberately four verbs" and listed eight, omitting `observe`,
    `assign` and `accept`, and C4 added a ninth line to that list without touching the claim. `--help` showed
    twelve.

    The count is gone and the list is checked here rather than kept by hand, because a hand-kept list beside the
    thing it lists drifts on the next entry -- which is what happened twice already. A verb added to `main` and
    not to the docstring now fails, and so does the reverse."""
    import re
    doc = (cli.__doc__ or "").splitlines()
    listed = {m.group(1) for m in (re.match(r"    tierbook ([a-z-]+)", ln) for ln in doc) if m}
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    shown = re.search(r"\{([a-z,\-]+)\}", capsys.readouterr().out)
    assert shown, "argparse stopped printing the subcommand list, so this check is no longer checking anything"
    real = set(shown.group(1).split(","))
    assert listed == real, f"docstring lists {sorted(listed - real)} that do not exist and omits {sorted(real - listed)}"
