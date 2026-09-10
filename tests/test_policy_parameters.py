"""C2 -- the policy artifact records the parameters it was compiled under.

Verified in the contract: the compiled policy carries `certified: true` and does NOT carry the floor. The floor has
three supply points (`assign_family`'s argument, `serve.route_once --floor`, `accept --floor`) and zero recorded
copies, so `docs/verify/v0.1.0-accept.json`'s published `no_false_certification: pass` is conditional on a number
typed at a shell prompt matching one the artifact never wrote down -- and nothing checks that it does.

C2 closes that: the artifact records `floor` and `max_evidence_age_days` (and, for C3, `staleness_limit_days`); every
consumer reads them through `decide.parameter`; and a consumer given a conflicting value refuses rather than
preferring one. Every test below is either that refusal or a way it could quietly stop refusing.

Only C2 is in scope here. Nothing about `schema_version`, `from_row`, exploration, a labeller, or pooling across
versions is tested in this file.

Amendment 2 (below the original tests): the code author found the floor never entered the compile path at all --
it was not lost, it had never been declared anywhere. A2.2/A2.3 move it into the ledger's per-family declaration:
`families` in the candidate file stops mapping a family name to a bare reference-id string and becomes an object
`{"reference": <candidate id>, "floor": <float>}`, and `config_format` goes from 1 to 2. `compile --floor` never
existed and is not tested. A2.4 (a labeller and max label latency joining the same object, for C4) is out of scope
here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tierbook import cli  # noqa: E402
from tierbook import decide as D  # noqa: E402
from tierbook.config import ConfigError, load_config  # noqa: E402

V010_SMOKE_POLICY = ROOT / "docs" / "verify" / "v0.1.0-smoke-policy.json"
EXAMPLE_CANDIDATES = ROOT / "examples" / "ledger" / "candidates.json"
EXAMPLE_LEDGER_TIERS = str(ROOT / "examples" / "ledger" / "tiers")


def run_cli(argv: list[str]) -> int:
    """Invoke the CLI the way a caller would, through its documented entry point.

    `cli.main` sometimes returns a status and sometimes (via `sys.exit`/`parser.error`) raises `SystemExit` -- both
    are "the process exits with this code" from a caller's point of view, and this test file does not care which
    mechanism a worker chose. Normalising here keeps every CLI test asserting on the one thing the contract names:
    the exit status, not which internal function produced it.
    """
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


def minimal_policy_dict(*, floor=0.05, max_evidence_age_days=None, staleness_limit_days=None) -> dict:
    """A well-formed v0.2.0-shaped artifact: uncertified, no rules, and the parameters block C2 adds.

    Uncertified and rule-less on purpose: these CLI tests are about whether the floor supplied on the command line
    is checked against the one the artifact recorded, not about what a rule fires. A minimal artifact keeps that the
    only thing under test.
    """
    return {
        "family": "agentic-coding",
        "default": ["api"],
        "certified": False,
        "note": "",
        "domain": {},
        "provenance": {},
        "rules": [],
        "parameters": {"floor": floor, "max_evidence_age_days": max_evidence_age_days,
                       "staleness_limit_days": staleness_limit_days},
    }


# --- decide.Policy carries parameters, and as_dict/from_dict move them -----------------------------


def test_as_dict_writes_the_parameters_the_policy_was_compiled_under():
    """`as_dict` is the artifact's writer. The floor is exactly the thing the contract says is missing today, so this
    is the test that would have caught its absence before it shipped."""
    pol = D.Policy(family="f", rules=(), default=("api",),
                   parameters={"floor": 0.10, "max_evidence_age_days": 30.0, "staleness_limit_days": 14.0})
    d = D.as_dict(pol)
    assert d["parameters"] == {"floor": 0.10, "max_evidence_age_days": 30.0, "staleness_limit_days": 14.0}


def test_from_dict_reads_parameters_back():
    """The inverse of the write above, read from a raw artifact dict -- not from `as_dict`'s own output -- because a
    consumer reading a policy off disk never goes through `as_dict` either."""
    raw = minimal_policy_dict(floor=0.20, max_evidence_age_days=45.0, staleness_limit_days=None)
    pol = D.from_dict(raw)
    assert pol.parameters["floor"] == 0.20
    assert pol.parameters["max_evidence_age_days"] == 45.0
    assert pol.parameters["staleness_limit_days"] is None


def test_a_compiled_policy_with_parameters_round_trips():
    pol = D.Policy(family="f", rules=(), default=("api",),
                   parameters={"floor": 0.075, "max_evidence_age_days": 60.0, "staleness_limit_days": 20.0})
    back = D.from_dict(D.as_dict(pol))
    assert back.parameters == pol.parameters


# --- a v0.1.0 artifact carries rules but no parameters, and is refused rather than trusted ---------


def test_a_real_v010_artifact_has_rules_and_no_parameters_key():
    """Not a hand-written fixture: the actual artifact the contract cites. If this assertion ever fails, the fixture
    stopped being the case the rest of this file is about."""
    raw = json.loads(V010_SMOKE_POLICY.read_text())
    assert raw["rules"], "the fixture must carry rules for this to be the case C2 names"
    assert "parameters" not in raw


def test_from_dict_refuses_a_v010_artifact_that_carries_rules_but_no_parameters():
    """This is the test the C2 entry exists for: the exact artifact behind the conditional
    `no_false_certification: pass` in docs/verify/v0.1.0-accept.json, loaded the way a consumer would load it."""
    raw = json.loads(V010_SMOKE_POLICY.read_text())
    with pytest.raises(ValueError, match="parameters"):
        D.from_dict(raw)


def test_the_refusal_names_the_absent_key_and_says_to_recompile():
    """"naming the absent key" and "recompile" are both load-bearing in the contract's wording -- naming the key so
    an operator does not have to diff schemas, and "recompile" because the artifact is not the source and cannot be
    patched into a v0.2.0 shape by hand."""
    raw = json.loads(V010_SMOKE_POLICY.read_text())
    with pytest.raises(ValueError) as excinfo:
        D.from_dict(raw)
    message = str(excinfo.value)
    assert "parameters" in message
    assert "recompile" in message.lower()


# --- decide.parameter: the single reader, and its four contracted paths ----------------------------


def test_parameter_with_no_supplied_value_returns_the_artifacts_value():
    pol = D.Policy(family="f", rules=(), default=("api",),
                   parameters={"floor": 0.30, "max_evidence_age_days": 30.0})
    assert D.parameter(pol, "floor") == 0.30
    assert D.parameter(pol, "floor", supplied=None) == 0.30


def test_parameter_with_a_supplied_value_equal_to_the_artifacts_returns_it():
    pol = D.Policy(family="f", rules=(), default=("api",), parameters={"floor": 0.15})
    assert D.parameter(pol, "floor", supplied=0.15) == 0.15


def test_parameter_raises_on_mismatch_and_names_both_values():
    """The test the C2 entry is FOR: a supplied floor that disagrees with the artifact's must be a hard failure, not
    a quiet preference for either number. This is what stands between "no_false_certification: pass" and a floor
    that was never actually the one the policy was built against."""
    pol = D.Policy(family="f", rules=(), default=("api",), parameters={"floor": 0.05})
    with pytest.raises(ValueError) as excinfo:
        D.parameter(pol, "floor", supplied=0.08)
    message = str(excinfo.value)
    assert "0.05" in message and "0.08" in message


def test_parameter_raises_symmetrically_whichever_side_of_the_artifact_the_supplied_value_falls():
    """"It does not prefer either" needs checking in both directions: an implementation that only refuses a LOWER
    supplied value (and silently accepted a higher one as an update) would still pass a test that only tried one
    direction."""
    pol = D.Policy(family="f", rules=(), default=("api",), parameters={"floor": 0.20})
    with pytest.raises(ValueError):
        D.parameter(pol, "floor", supplied=0.25)   # higher than the artifact's
    with pytest.raises(ValueError):
        D.parameter(pol, "floor", supplied=0.10)   # lower than the artifact's


def test_parameter_raises_when_the_artifact_does_not_carry_the_name_and_a_value_is_supplied():
    """An artifact that never recorded a parameter cannot confirm a caller's guess at it, even if the guess happens
    to be reasonable. `staleness_limit_days` is left out of `parameters` entirely here -- not present with a null
    value, absent as a key -- which is the unambiguous case the contract states."""
    pol = D.Policy(family="f", rules=(), default=("api",), parameters={"floor": 0.05})
    with pytest.raises(ValueError):
        D.parameter(pol, "staleness_limit_days", supplied=7.0)


def test_parameter_with_no_supplied_value_and_the_artifact_carrying_it_as_none_returns_none():
    """`max_evidence_age_days` is `float | None` by contract, and `None` is a real declared value ("no freshness
    bound"), not an absence. With nothing supplied, the reader returns exactly what is there."""
    pol = D.Policy(family="f", rules=(), default=("api",),
                   parameters={"floor": 0.05, "max_evidence_age_days": None})
    assert D.parameter(pol, "max_evidence_age_days", supplied=None) is None


# --- cli: assign --floor is optional, checked against the artifact when given -----------------------


def test_assign_with_no_floor_flag_uses_the_artifacts_value(tmp_path):
    """The non-failure path has to work too, or the mismatch test below would not be distinguishing anything: a CLI
    that always exits 4 would also pass a test that only tried the mismatch."""
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(minimal_policy_dict(floor=0.05)))
    rc = run_cli(["assign", "--policy", str(policy_path), "--request-id", "r1"])
    assert rc == 0


def test_assign_floor_mismatch_against_the_artifact_exits_4_with_the_message_on_stderr(tmp_path, capsys):
    """The CLI-level version of the test the whole entry exists for: `assign --floor` disagreeing with what the
    policy was compiled under must not silently proceed with either number."""
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(minimal_policy_dict(floor=0.05)))
    rc = run_cli(["assign", "--policy", str(policy_path), "--request-id", "r1", "--floor", "0.08"])
    assert rc == 4
    err = capsys.readouterr().err
    assert "0.05" in err and "0.08" in err


def test_assign_floor_matching_the_artifact_is_not_a_failure(tmp_path):
    """A supplied value equal to the artifact's must not be refused merely for having been supplied."""
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(minimal_policy_dict(floor=0.05)))
    rc = run_cli(["assign", "--policy", str(policy_path), "--request-id", "r1", "--floor", "0.05"])
    assert rc == 0


# --- cli: accept --floor is optional when --policy is given, required when it is not -----------------


def test_accept_with_policy_and_no_floor_flag_uses_the_artifacts_value(tmp_path):
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(minimal_policy_dict(floor=0.05)))
    log_path = tmp_path / "decisions.jsonl"     # never written: an absent log reads as empty, not an error
    rc = run_cli(["accept", "--log", str(log_path), "--policy", str(policy_path)])
    assert rc == 0


def test_accept_floor_mismatch_against_the_policy_exits_4_with_the_message_on_stderr(tmp_path, capsys):
    """`accept --floor` is the third of the three supply points the contract names (`assign_family`'s argument and
    `serve.route_once --floor` are the other two). This is the one SCOPE's own published acceptance report used, so
    it is the most direct reproduction of the exact failure C2 exists to close."""
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(minimal_policy_dict(floor=0.05)))
    log_path = tmp_path / "decisions.jsonl"
    rc = run_cli(["accept", "--log", str(log_path), "--policy", str(policy_path), "--floor", "0.08"])
    assert rc == 4
    err = capsys.readouterr().err
    assert "0.05" in err and "0.08" in err


def test_accept_with_no_policy_requires_floor(tmp_path):
    """This is the fifth named negative case: an `accept` run with no `--policy` and no `--floor` has no artifact to
    read a floor from and no operator-supplied one either, so it must not silently proceed -- SCOPE's own criteria
    are computed against a floor, and there is none here at all.

    Exit code 2, the CLI's existing code for a missing required argument -- not 4. 4 is reserved for a mismatch
    between two PRESENT numbers, which is a different operator action: 2 means supply something, 4 means two
    sources disagree and one is wrong. Amendment 2 settled this; it was previously reported as an open ambiguity."""
    log_path = tmp_path / "decisions.jsonl"
    rc = run_cli(["accept", "--log", str(log_path)])
    assert rc == 2


def test_accept_with_no_policy_but_a_supplied_floor_still_runs(tmp_path):
    """Without a policy an operator-supplied floor is exactly what SCOPE section 12's criteria are computed
    against; refusing this path entirely would make `accept` unusable on a log that predates C2's artifacts."""
    log_path = tmp_path / "decisions.jsonl"
    rc = run_cli(["accept", "--log", str(log_path), "--floor", "0.05"])
    assert rc == 0


def test_accept_with_no_policy_records_that_the_floor_was_operator_supplied_and_unchecked(tmp_path, capsys):
    """The contract's own words: "the output records that the floor was operator-supplied and unchecked". This is
    the recurrence-detector for the exact defect C2 is about -- a floor nobody can trace to a compiled artifact,
    now at least labelled as such in the one place a reader of `accept`'s output would look."""
    log_path = tmp_path / "decisions.jsonl"
    rc = run_cli(["accept", "--log", str(log_path), "--floor", "0.05", "--out", str(tmp_path / "out.json")])
    assert rc == 0
    out = (tmp_path / "out.json").read_text() + capsys.readouterr().out
    assert "operator" in out.lower()
    assert "unchecked" in out.lower() or "not checked" in out.lower() or "not_checked" in out.lower()


# =====================================================================================================
# Amendment 2 -- the floor moves from a CLI flag to the ledger's per-family declaration.
# =====================================================================================================
#
# A2.2: the floor is per FAMILY, not one global number threaded through the compile path.
# A2.3: the home is `families` in the candidate file, which stops being `{family: reference_id}` and
# becomes `{family: {"reference": reference_id, "floor": float}}`. `config_format` goes 1 -> 2.
# A2.4 (a labeller and max label latency joining the same object) is C4's and is not tested here.


def _minimal_candidates(*, config_format=2, families=None) -> dict:
    """The smallest candidate file `load_config` will look at. Deliberately not the example ledger: the
    config_format / families-shape refusals are about the loader's own checks, not about whether real
    evidence backs the family, and tying them to the bigger fixture would make a failure here harder to
    read than it needs to be."""
    return {
        "config_format": config_format,
        "candidates": {
            "ref": {"deployment": "api",
                    "endpoint": {"base_url": "https://x/v1", "model": "m"},
                    "price_per_mtok": {"fresh_in": 1.0, "cached_in": 0.1, "out": 5.0}},
        },
        "families": families if families is not None else {"f": {"reference": "ref", "floor": 0.5}},
        "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.15}}},
    }


def _write_candidates(tmp_path, body: dict) -> Path:
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps(body))
    return p


# --- decide.parameter, amendment 2's answers to ambiguities 2 and 3 --------------------------------


def test_parameter_treats_an_artifacts_explicit_none_as_carrying_the_parameter():
    """Amendment 2's answer to ambiguity 2: a key present with value `None` DOES carry the parameter --
    `None` is the declared value "no limit", not an absence. Supplying a real number against it is a
    MISMATCH (raise naming both), the same refusal as any other disagreement, not the separate "cannot
    confirm" refusal that fires only when the key is missing entirely. The two are one line apart in the
    reader and the wrong one is invisible: this is the artifact-carries-None half of that pair."""
    pol = D.Policy(family="f", rules=(), default=("api",),
                   parameters={"floor": 0.05, "max_evidence_age_days": None})
    with pytest.raises(ValueError) as excinfo:
        D.parameter(pol, "max_evidence_age_days", supplied=30.0)
    message = str(excinfo.value)
    assert "30.0" in message or "30" in message
    assert "none" in message.lower()


def test_parameter_with_the_name_genuinely_absent_still_raises_on_a_supplied_value():
    """The other half of the same pair: a key ABSENT from `parameters` (not present-as-None) still raises
    the "cannot confirm" refusal on a supplied value, distinct from the mismatch above. Restated here beside
    the None case on purpose, since amendment 2 says the two are one line apart in the implementation."""
    pol = D.Policy(family="f", rules=(), default=("api",), parameters={"floor": 0.05})
    with pytest.raises(ValueError):
        D.parameter(pol, "max_evidence_age_days", supplied=30.0)


def test_parameter_with_no_supplied_value_and_the_name_entirely_absent_returns_none():
    """Amendment 2's answer to ambiguity 3: reading the artifact is a read, and with nothing supplied there
    is nothing to disagree with, so this returns `None` rather than raising. The alternative -- refusing
    because the artifact never carried the name -- would break every caller that reads an optional parameter
    with no opinion of its own, which is most of them."""
    pol = D.Policy(family="f", rules=(), default=("api",), parameters={"floor": 0.05})
    assert D.parameter(pol, "staleness_limit_days", supplied=None) is None


# --- config.load_config, A2.3: a bare string is refused and A2.3/A2.4's version bump ----------------


def test_a_bare_string_family_entry_is_refused_and_names_what_to_change(tmp_path):
    """`families` stops being `{family: reference_id}`. The old shape has to be refused outright -- not
    read with the floor silently treated as absent -- and the message has to tell an operator what object
    to write and why, not merely that loading failed."""
    body = _minimal_candidates(config_format=2, families={"f": "ref"})
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write_candidates(tmp_path, body))
    message = str(excinfo.value)
    assert "f" in message
    assert "reference" in message and "floor" in message
    # Disabling the migration branch was caught by nothing: the generic "must be an object with 'reference' and
    # 'floor'" check downstream refuses a bare string too, and names all three, so every assertion above passed
    # against a loader that had lost the explanation of WHAT CHANGED. The migration message is the only thing
    # telling an operator their file was valid yesterday, so it is what this pins.
    assert "config_format" in message


def test_config_format_1_is_refused_rather_than_read_as_the_new_shape(tmp_path):
    """The same reasoning as C1's schema_version check, applied to the candidate file: a file written to a
    shape this reader does not know cannot be validated against the shape it does know. `config_format: 1`
    together with the OLD bare-string families shape was a completely valid file under format 1 -- and must
    now be refused outright rather than parsed optimistically as if it were format 2.

    The families shape here is the NEW one on purpose, which is the opposite of how this test first read. With
    the old bare-string shape the file trips TWO refusals, and the bare-string one names `config_format` in its
    migration text -- so accepting format 1 outright still produced a `ConfigError` matching `config_format` and
    the test passed against a loader that read the old format happily. A file that is otherwise entirely
    well-formed leaves the version check as the only thing that can refuse it."""
    body = _minimal_candidates(config_format=1, families={"f": {"reference": "ref", "floor": 0.80}})
    with pytest.raises(ConfigError, match="config_format"):
        load_config(_write_candidates(tmp_path, body))


# --- A2.2: the floor is genuinely per family, proven by compiling two that disagree -----------------


def test_two_families_with_different_floors_each_carry_their_own_in_the_compiled_artifact(tmp_path):
    """The sharpest test in this group, by design. A later change that collapsed the per-family floor back
    into one global value threaded through the compile path would still pass a test that only checked ONE
    family's floor against ITS declared value -- a global floor equal to that one family's number looks
    identical from the inside. Asserting on BOTH families, against DIFFERENT floors, is what makes that
    regression fail here specifically rather than surviving unnoticed, which is the exact failure mode A2.2
    exists to close: two families with different accuracy requirements silently sharing one number."""
    raw = json.loads(EXAMPLE_CANDIDATES.read_text())
    raw["config_format"] = 2
    raw["families"] = {
        "agentic-coding": {"reference": "api-strong-a", "floor": 0.65},
        "tool-agent-user-retail": {"reference": "api-strong-a", "floor": 0.85},
    }
    config_path = _write_candidates(tmp_path, raw)
    out_path = tmp_path / "table.json"
    rc = run_cli(["compile", "--config", str(config_path), "--out", str(out_path),
                 "--registry", EXAMPLE_LEDGER_TIERS])
    assert rc == 0
    table = json.loads(out_path.read_text())
    coding_floor = table["decide"]["agentic-coding"]["cannot_reject"]["parameters"]["floor"]
    retail_floor = table["decide"]["tool-agent-user-retail"]["cannot_reject"]["parameters"]["floor"]
    assert coding_floor == 0.65
    assert retail_floor == 0.85
    assert coding_floor != retail_floor
