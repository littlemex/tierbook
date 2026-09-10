"""The journey layer for tierbook v0.2.0.

Every other test in this repository asserts a requirement one contract entry owns. This file asserts
something no entry owns: that a real person gets through the mechanism end to end, and that what they are
told along the way is true. It does not re-read `tests/` for fixtures or argument shapes -- by design, so
that walking a journey does not degrade into re-asserting a requirement. Everything here is built from
`README.md`, `SCOPE.md`, `docs/`, `examples/`, and the CLI's own `--help` and error text, exactly as a real
operator would have it.

Three personas (see the journey-layer brief for the full description):

    P1  the first-time operator -- empty-handed, reads README.md and SCOPE.md, wants a cheaper routing
        decision without losing accuracy.
    P2  the upgrading operator -- already ran v0.1.0, has a `candidates.json` at `config_format: 1` and a
        `decisions.jsonl` v0.1.0 wrote, wants to be on v0.2.0.
    P3  the analyst -- was not there when the log was written, has a `decisions.jsonl` mixing v0.1.0 and
        v0.2.0 lines, wants to know whether a different choice would have been better.

Two genuine findings are recorded here as `xfail(strict=True)`, not fixed:

    P2's round trip: fixing exactly what `load_config`'s error names, one message at a time, on the
    v0.1.0-shaped ledger this project itself shipped at the v0.1.0 tag, takes 5 failed attempts (6 total)
    for a two-family file, not the single aggregated correction a `config_format` migration is capable of
    giving in one message.

    P3's silent pooling: `accept.check_all` accepts a `pool_across_versions` keyword and documents, in its
    own docstring, that refusing a version-mixed log is "the entry that gives it a behaviour" -- and that
    entry (referred to in the code as C5) was never merged into this integration. The CLI never even
    threads the keyword. A log mixing v0.1.0 rows (no exploration mechanism existed) with v0.2.0 rows (a
    real exploration draw) is pooled into one `exploration_cost` number with nothing in the report
    distinguishing the two mechanisms.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def run_cli(args: list, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI exactly as an operator would after `pip install .` -- `python -m tierbook.cli ...` --
    with the checkout's own `src/` on the path, since this sandbox cannot reach the network to actually
    install the package. What is exercised is the CLI module and its argument parsing, not the packaging
    step."""
    full_env = dict(os.environ if env is None else env)
    full_env["PYTHONPATH"] = str(SRC) + (os.pathsep + full_env["PYTHONPATH"] if full_env.get("PYTHONPATH") else "")
    return subprocess.run([sys.executable, "-m", "tierbook.cli", *args], cwd=str(cwd),
                          capture_output=True, text=True, env=full_env)


def cli_help(*args: str) -> str:
    r = run_cli([*args, "--help"], cwd=ROOT)
    assert r.returncode == 0, r.stderr
    return r.stdout


# ---------------------------------------------------------------------------------------------------------
# P1 -- the first-time operator
# ---------------------------------------------------------------------------------------------------------

def test_p1_readme_quickstart_is_true_end_to_end(tmp_path: Path):
    """P1, the first-time operator, has never seen this repository. They read the three lines of shell at
    the top of README.md and the paragraph right after them, which quotes an exact refusal. This test does
    not know that text by having read it once and trusted it -- it re-derives every number the README quotes
    by actually running the commands, in a scratch copy of the shipped example ledger (the same one
    README's own 'What a stranger does on day one' section tells a newcomer to copy), and fails if the
    README's claim and the CLI's behaviour diverge.

    Observed at each step:
      1. `validate` -- reads clean, notes one family missing a paired comparison (expected: it has no
         records for that family yet).
      2. `explain` -- shows the ledger's own numbers per tier before any decision is made.
      3. `compile --margin 0.15` -- succeeds (exit 0) but produces a table whose entry a held-out fold does
         not support: the README's quoted refusal text ("bound -0.2407 is OUTSIDE the margin of -0.15" and
         the rank swap) appears verbatim in the compiler's own stdout.
      4. `route` against that table, without `--allow-unvalidated`, is REFUSED (exit 2) with a message that
         also matches what README promises would happen.
      5. `compile --margin 0.25` -- the README says "run the same command at --margin 0.25 and it assigns".
         It does.
      6. `route` against the wider-margin table now succeeds, and the JSON it prints says `certified: true`
         and `status: assigned` -- a checked routing decision, reached with nothing but README.md's own
         quickstart and the shipped example.

    No finding here: this is the front page's central promise, and it holds exactly as written.
    """
    ledger = tmp_path / "examples" / "ledger"
    ledger.parent.mkdir(parents=True)
    import shutil
    shutil.copytree(ROOT / "examples" / "ledger", ledger)

    # Step 1: validate.
    r = run_cli(["validate", "--registry", "examples/ledger/tiers"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "every record can be read" in r.stdout

    # Step 2: explain -- the ledger's own numbers, before any decision.
    r = run_cli(["explain", "--registry", "examples/ledger/tiers",
                "--family", "tool-agent-user-retail", "--reference", "api-strong-a"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tool-agent-user-retail" in r.stdout

    # Step 3: compile at the README's first margin. Exit 0 -- a refusal is a written, provisional table,
    # not a crash -- and the refusal text README quotes verbatim.
    r = run_cli(["compile", "--registry", "examples/ledger/tiers",
                "--validations", "examples/ledger/validation",
                "--family", "tool-agent-user-retail=api-strong-a",
                "--margin", "0.15", "--out", "table.json"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "bound -0.2407 is OUTSIDE the margin of -0.15" in r.stdout
    assert "RANK UNSTABLE" in r.stdout

    # Step 4: route the refused entry -- REFUSED, exactly as README's "That last command refuses" promises.
    r = run_cli(["route", "--table", "table.json", "--family", "tool-agent-user-retail"], cwd=tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "refused" in r.stderr
    assert "allow_unvalidated" in r.stderr

    # Step 5: the README's own next line -- run the same command at --margin 0.25, and it assigns.
    r = run_cli(["compile", "--registry", "examples/ledger/tiers",
                "--validations", "examples/ledger/validation",
                "--family", "tool-agent-user-retail=api-strong-a",
                "--margin", "0.25", "--out", "table25.json"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr

    # Step 6: route now succeeds, and P1 has a checked routing decision.
    r = run_cli(["route", "--table", "table25.json", "--family", "tool-agent-user-retail"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    decision = json.loads(r.stdout)
    assert decision["certified"] is True
    assert decision["status"] == "assigned"
    assert decision["send_to"]


def test_p1_help_names_the_two_files_and_the_config_shape_to_copy(tmp_path: Path):
    """P1 needs to know where to put their OWN prices and endpoints, as opposed to the worked example. The
    CLI's own `compile --help` names `--config` only as "candidate file supplying families, objective and
    constraints" -- it does not spell out `config_format` or the six required per-family keys. README does
    not print a complete candidates.json either. The one place the actual shape lives is
    examples/ledger/candidates.json, and the only sentence pointing there is README's "What a stranger does
    on day one" paragraph ("examples/ledger/ is a worked ledger whose shape you can copy").

    This test follows exactly that pointer -- copy the shipped candidate file, change only what belongs to
    an operator's own environment (the margin) -- and confirms the result is a loadable, compilable,
    routable config. It is a real path through the documentation, not the quickstart's --family shortcut,
    and it works.
    """
    ledger = tmp_path / "examples" / "ledger"
    ledger.parent.mkdir(parents=True)
    import shutil
    shutil.copytree(ROOT / "examples" / "ledger", ledger)

    cfg = json.loads((ledger / "candidates.json").read_text())
    cfg["objective"]["constraints"]["non_inferiority"]["margin"] = 0.25
    (tmp_path / "my-candidates.json").write_text(json.dumps(cfg))

    r = run_cli(["compile", "--registry", "examples/ledger/tiers",
                "--validations", "examples/ledger/validation",
                "--config", "my-candidates.json", "--out", "table.json"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr

    r = run_cli(["route", "--table", "table.json", "--family", "tool-agent-user-retail"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["certified"] is True


# ---------------------------------------------------------------------------------------------------------
# P2 -- the upgrading operator
# ---------------------------------------------------------------------------------------------------------

#: The exact shape README and the v0.1.0 tag shipped: config_format 1, a family is a bare reference string.
V010_CANDIDATES = {
    "config_format": 1,
    "candidates": {
        "api-strong-a": {
            "deployment": "api",
            "endpoint": {"base_url": "https://gateway.example.invalid/v1", "model": "strong-model-a",
                         "wire": "chat", "api_key_env": "TIERBOOK_API_KEY"},
            "price_per_mtok": {"fresh_in": 10.0, "cached_in": 1.0, "out": 50.0},
        },
        "self-hosted-a": {
            "deployment": "self_hosted",
            "endpoint": {"base_url": "http://model-service.example:8000/v1", "model": "open-weights-b"},
            "hourly_usd": 15.2174,
        },
    },
    "families": {
        "agentic-coding": "api-strong-a",
        "tool-agent-user-retail": "api-strong-a",
    },
    "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.25}}},
}

#: Values a real operator would supply when the loader names a missing policy input. Not guesses about
#: what the loader wants structurally (that comes from the message alone) -- these are the two numbers
#: SCOPE section 5 says only an operator can supply, so the round-trip experiment needs SOME value to keep
#: moving, exactly as a real person filling in the message's own `<...>` placeholder would.
_OPERATOR_SUPPLIED_FLOORS = {"agentic-coding": 0.80, "tool-agent-user-retail": 0.92}


def _fix_exactly_what_the_message_said(cfg: dict, message: str) -> dict:
    """Apply exactly the correction `load_config`'s error names, and nothing else -- the discipline the
    persona brief specifies: a real person acts on this message, not on knowledge of the target shape."""
    import re

    cfg = json.loads(json.dumps(cfg))  # deep copy
    if "config_format must be 2" in message:
        cfg["config_format"] = 2
        return cfg
    m = re.search(r"family '([^']+)' names its reference candidate as a bare string, '([^']+)'", message)
    if m:
        fam, ref = m.group(1), m.group(2)
        # The message's own suggested replacement names `floor` with a placeholder
        # ("<this family's success-rate floor>"): a real operator fills it with their own number, which is
        # exactly what SCOPE section 5 says only an operator can supply.
        cfg["families"][fam] = {"reference": ref, "floor": _OPERATOR_SUPPLIED_FLOORS[fam]}
        return cfg
    m = re.search(r"family '([^']+)' is missing (\[[^\]]*\])", message)
    if m:
        fam, missing = m.group(1), eval(m.group(2))  # noqa: S307 -- a literal list from our own error text
        for key in missing:
            if key == "floor":
                cfg["families"][fam][key] = _OPERATOR_SUPPLIED_FLOORS[fam]
            elif key == "label_source":
                cfg["families"][fam][key] = "executable_acceptance"
            elif key == "max_label_latency_s":
                cfg["families"][fam][key] = 3600.0
            elif key == "label_independent_of_candidate":
                cfg["families"][fam][key] = True
            elif key == "staleness_limit_days":
                cfg["families"][fam][key] = None
        return cfg
    raise AssertionError(f"the round-trip helper does not know how to act on this message: {message!r}")


def _load_config_round_trips(cfg: dict, tmp_path: Path) -> tuple[int, dict]:
    """Load `cfg` with `tierbook.config.load_config`, and on every `ConfigError` apply exactly the fix the
    message names and try again. Returns (failed_attempts_before_success, final_cfg)."""
    sys.path.insert(0, str(SRC))
    from tierbook.config import ConfigError, load_config  # noqa: E402

    path = tmp_path / "candidates.json"
    failures = 0
    for _ in range(20):
        path.write_text(json.dumps(cfg))
        try:
            load_config(str(path))
            return failures, cfg
        except ConfigError as e:
            failures += 1
            cfg = _fix_exactly_what_the_message_said(cfg, str(e))
    raise AssertionError("did not converge in 20 round trips")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "P2's upgrade path surfaces one problem per family per pass instead of one aggregated correction: a "
        "real two-family v0.1.0 candidates.json (the exact file this project shipped at the v0.1.0 tag) "
        "takes 5 failed load_config attempts -- config_format, then per family: the bare-string-to-object "
        "migration, then that family's four missing keys -- before it loads, when the loader already knows "
        "about every family and every missing key on the first read and could have said so once."
    ),
)
def test_p2_upgrade_round_trip_count_from_a_real_v010_ledger(tmp_path: Path):
    """P2 already ran v0.1.0 and has a `candidates.json` at `config_format: 1` -- this is not a synthetic
    minimal example, it is the exact two-family shape this project itself shipped in its own v0.1.0 tag
    (`git show v0.1.0:examples/ledger/candidates.json`). They upgrade to v0.2.0, run any command that loads
    it, and follow the error message: fix exactly what it names, try again.

    This asserts the ideal a `config_format` migration is capable of -- one comprehensive error naming every
    problem across every family, so the honest number of failed attempts before success is at most 1 (fix
    everything the single message named, then it loads). The measured number is 5: the loader raises on the
    FIRST problem it meets and stops, so a two-family file surfaces its first family's shape problem, then
    that family's four missing keys, then repeats both steps for the second family, before ever mentioning
    it. The persona brief's fear -- "five sequential load failures, each naming one key" -- is realized at
    family granularity rather than key granularity, which is still five round trips an operator making
    exactly the correction each message asked for cannot avoid.
    """
    failures, _final = _load_config_round_trips(dict(V010_CANDIDATES), tmp_path)
    assert failures <= 1, (
        f"upgrading a real two-family v0.1.0 candidates.json took {failures} failed load_config attempts "
        f"before it loaded -- each one naming only the next problem instead of all of them"
    )


def test_p2_old_decisions_log_gets_a_full_accept_report_not_a_crash(tmp_path: Path):
    """P2 also has a `decisions.jsonl` that v0.1.0 wrote -- rows with no `schema_version` key, no
    `exploration_reason`, no `eligible_set`, because none of those existed yet. They run v0.2.0's `accept`
    on it directly (no `--policy`, so `--floor` is required and unchecked, exactly as the CLI's own
    `accept --help` documents).

    Observed: a full nine-criterion report, not an error. `record.from_row` reads a row with no
    `schema_version` as version 1 and supplies `no_mechanism` / `[]` for the two fields that did not exist
    yet (SEAMS.md S4) -- the property this test exists to check, from the outside, through the CLI rather
    than by reading record.py's own tests. `no_false_certification` passes because the certified decision
    was genuinely admissible; `default_is_not_a_hiding_place` fails because half the toy log's traffic was
    uncertified against a 10% tolerance -- an honest fact about this fixture, not a defect. No finding: the
    version-tagging design in record.py does exactly what the upgrading operator needs here.
    """
    def v1_row(rid: str, chosen: str, certified: bool, candidates: list) -> dict:
        return {
            "family": "tool-agent-user-retail", "request_id": rid, "feature_vector_version": "fv1",
            "state_ref": f"obs:{rid}", "candidates": candidates, "chosen": chosen,
            "selection_probability": 1.0, "exploration": False, "certified": certified,
            "policy_version": "v0.1.0-policy", "mechanism_version": "0.1.0", "agent": "agent-x",
            "model": "m1", "endpoint": "https://gateway.example.invalid/v1", "gateway_quote_usd": 0.01,
            "gateway_authorised": True, "decided_at": time.time() - 86400, "gaps": [],
            "label_state": "pending", "label": None, "outcome": {},
            # Deliberately absent: schema_version, exploration_reason, eligible_set -- v0.1.0 never wrote them.
        }

    rows = [
        v1_row("r1", "self-hosted-a", True,
              [{"id": "self-hosted-a", "excluded_because": "chosen", "bound": 0.90, "bound_kind": "lcb"},
               {"id": "api-strong-a", "excluded_because": "not_evaluated", "bound": None}]),
        v1_row("r2", "api-strong-a", False,
              [{"id": "self-hosted-a", "excluded_because": "below_floor", "bound": 0.70, "bound_kind": "lcb"},
               {"id": "api-strong-a", "excluded_because": "chosen", "bound": None}]),
    ]
    log = tmp_path / "decisions.jsonl"
    with log.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
        fh.write(json.dumps({"outcome_for": "r1", "label_state": "labelled", "label": True,
                             "at": time.time()}) + "\n")
        fh.write(json.dumps({"outcome_for": "r2", "label_state": "labelled", "label": True,
                             "at": time.time()}) + "\n")

    r = run_cli(["accept", "--log", str(log), "--floor", "0.80", "--uncertified-tolerance", "0.10"],
               cwd=tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr  # non-zero because of a genuine FAIL below, not a crash
    out = json.loads(r.stdout)
    assert out["summary"]["of"] == 9
    verdicts = {v["criterion"]: v for v in out["verdicts"]}
    assert verdicts["no_false_certification"]["verdict"] == "pass"
    assert verdicts["default_is_not_a_hiding_place"]["verdict"] == "fail"
    assert "operator-supplied and unchecked" in out["floor_provenance"]


# ---------------------------------------------------------------------------------------------------------
# P3 -- the analyst
# ---------------------------------------------------------------------------------------------------------

def _v1_row(rid: str, family: str = "agentic-coding") -> dict:
    return {
        "family": family, "request_id": rid, "feature_vector_version": "fv1", "state_ref": f"obs:{rid}",
        "candidates": [{"id": "api-strong-a", "excluded_because": "chosen", "bound": 0.90, "bound_kind": "lcb"}],
        "chosen": "api-strong-a", "selection_probability": 1.0, "exploration": False, "certified": True,
        "policy_version": "v0.1.0-policy", "mechanism_version": "0.1.0", "agent": "agent-x", "model": "m1",
        "endpoint": "https://gateway.example.invalid/v1", "gateway_quote_usd": 0.01,
        "gateway_authorised": True, "decided_at": time.time() - 200000, "gaps": [], "label_state": "pending",
        "label": None, "outcome": {},
        # No schema_version: v0.1.0 wrote this before C3's exploration mechanism existed.
    }


def _v2_row(rid: str, *, exploration: bool, family: str = "agentic-coding") -> dict:
    return {
        "family": family, "request_id": rid, "feature_vector_version": "fv1", "state_ref": f"obs:{rid}",
        "candidates": [{"id": "self-hosted-a", "excluded_because": "chosen", "bound": 0.90,
                       "bound_kind": "lcb"}],
        "chosen": "self-hosted-a", "selection_probability": (0.05 if exploration else 1.0),
        "exploration": exploration, "certified": True, "policy_version": "v0.2.0-policy",
        "mechanism_version": "0.2.0", "agent": "agent-x", "model": "m1",
        "endpoint": "https://gateway.example.invalid/v1", "gateway_quote_usd": 0.01,
        "gateway_authorised": True, "decided_at": time.time() - 3600, "gaps": [], "label_state": "pending",
        "label": None, "outcome": {}, "schema_version": 2,
        "exploration_reason": ("explored" if exploration else "rate_zero"),
        "eligible_set": ["self-hosted-a"],
    }


def test_p3_mixed_version_log_pools_two_mechanisms_instead_of_refusing(tmp_path: Path):
    """P3, the analyst, was not there when this log was written and has a `decisions.jsonl` containing both
    v0.1.0 and v0.2.0 lines -- exactly the log SCOPE section 8 and CONTRACT C3 describe an operator ending
    up with the day a policy that didn't explore is replaced by one that does. They run `tierbook accept`
    -- the only tool this project gives them for asking whether a different choice would have been better --
    and read its report.

    Constructed here: 8 decisions from before C3's exploration mechanism existed (schema_version absent,
    `exploration: false` because there was no mechanism to set it true), and 2 decisions from after it was
    installed, both of which the mechanism genuinely chose to explore. A v0.1.0 row could never have
    explored -- the mechanism did not exist -- so pooling it with v0.2.0 rows when asking "is the CURRENT
    exploration mechanism within its budget" answers a different, easier question than the one asked.

    Observed: `exploration_cost` reports one number, 20% (2 of 10 decisions), against a 25% budget, and
    passes. The number a question about the current mechanism needs -- its rate over the 2 decisions it was
    actually eligible to explore -- is 100%, over budget by four times, and is not visible anywhere in the
    report: no verdict's `numbers` dict carries anything naming a schema version, so an analyst reading this
    report cannot tell which lines support which question, and the two mechanisms are pooled rather than
    refused or distinguished.
    """
    rows = [_v1_row(f"legacy-{i}") for i in range(8)]
    rows += [_v2_row("new-1", exploration=True), _v2_row("new-2", exploration=True)]
    log = tmp_path / "decisions.jsonl"
    with log.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    r = run_cli(["accept", "--log", str(log), "--floor", "0.80", "--budgeted-exploration", "0.25"],
               cwd=tmp_path)
    out = json.loads(r.stdout)
    verdicts = {v["criterion"]: v for v in out["verdicts"]}
    exploration = verdicts["exploration_cost"]

    # No numbers dict anywhere in the report distinguishes a v0.1.0 row from a v0.2.0 row -- the pooling is
    # total, not specific to this one criterion.
    for v in out["verdicts"]:
        for key in v["numbers"]:
            assert "schema_version" not in key.lower(), (
                f"{v['criterion']} unexpectedly reports a per-version number ({key}); if this is new, the "
                f"pooling finding above may already be fixed and this xfail should be removed"
            )

    # The claim this test is actually about: the mechanism the operator can currently tune should not be
    # reported as within budget when its own, eligible-only rate is four times over it.
    assert exploration["verdict"] != "pass" or exploration["numbers"]["exploration_share"] >= 0.5, (
        f"exploration_cost reports {exploration['numbers']['exploration_share']:.0%} pooled across two "
        f"mechanisms and PASSES a 25% budget, while the v0.2.0-only rate over its 2 eligible decisions is "
        f"100% -- 4x over budget -- with nothing in the report distinguishing the two"
    )
