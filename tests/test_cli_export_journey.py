"""The compile-then-export path, driven through the command line, because CI was its only home.

**Why this file exists.** `export()` is covered by `tests/test_boundary.py`, and the CLI door in front of it was
covered only by a shell step in `.github/workflows/ci.yml`. When the decision about reserved capacity changed on
2026-09-10 -- a reservation is no longer amortised into a per-request price, so the marginal charge of a reserved
candidate is zero and it wins a cost objective outright -- the suite was updated and the two shell steps were not.
They asserted the pre-decision tier for eleven days, which nobody saw locally because nobody runs the workflow
locally.

So the claim lives here now. The shell steps remain, and they are redundant coverage rather than the only place the
CLI's behaviour is written down.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "examples" / "ledger" / "tiers"
VALIDATION = ROOT / "examples" / "ledger" / "validation"
CANDIDATES = ROOT / "examples" / "ledger" / "candidates.json"
FAMILY = "tool-agent-user-retail"


def cli(*args: str) -> subprocess.CompletedProcess:
    got = subprocess.run([sys.executable, "-m", "tierbook.cli", *args],
                         cwd=ROOT, capture_output=True, text=True,
                         env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin:/usr/local/bin"})
    assert got.returncode == 0, f"tierbook {' '.join(args)} failed:\n{got.stdout}\n{got.stderr}"
    return got


def compiled(tmp_path: Path) -> dict:
    table = tmp_path / "t.json"
    cli("compile", "--registry", str(LEDGER), "--validations", str(VALIDATION),
        "--config", str(CANDIDATES), "--out", str(table), "--today", "2026-08-30")
    return json.loads(table.read_text())


def test_a_reservation_is_not_amortised_into_a_per_request_price(tmp_path):
    """The defect the shell step was built to catch, checked at its cause rather than at a ranking.

    A reserved candidate's bill arrives whether or not a request uses the capacity, and an average per request
    would be circular: routing to it is what changes the denominator. So with no accounting window stated there is
    no per-request price to be had, and inventing one -- which is how an unmeasured throughput gets back in -- makes
    this cost non-zero.
    """
    entry = compiled(tmp_path)["families"][FAMILY]["cannot_reject"]
    reserved = next(r for r in entry["ranked"] if r["arrangement"] == ["self-hosted-a"])
    if entry["self_hosted_economics"]["verdict"] == "undecidable":
        assert reserved["cost_per_request"] == 0.0, (
            "a reservation with no stated accounting window was given a per-request price",
            reserved, entry["self_hosted_economics"])


def test_the_reserved_candidate_wins_a_cost_objective_while_its_marginal_charge_is_zero(tmp_path):
    """The outcome, pinned so the two CI steps and `test_boundary.py` cannot drift apart again."""
    entry = compiled(tmp_path)["families"][FAMILY]["cannot_reject"]
    assert entry["status"] == "assigned", entry["status"]
    assert entry["chosen"] == ["self-hosted-a"], entry["chosen"]


def test_exporting_refuses_while_the_policy_has_a_guard_nobody_measured(tmp_path):
    """The shipped example stops one step short of a router config, and that is the correct behaviour.

    Its only rule guards on the occupancy at which the reserved candidate stops meeting its latency target, and no
    load probe has been run, so no rule can fire. A config exported from such a policy would send everything to the
    declared default while looking like a decision -- an inert component that resembles a working one, which is the
    state this refusal exists to prevent.

    The workflow asserted a successful export with a model name here until 2026-09-21. That has been impossible
    since 2026-09-08, when a single probe stopped supporting a capacity bound, and nothing noticed because the only
    place the claim lived was a shell step that fails after an earlier step in the same job had already failed.
    """
    table = tmp_path / "t.json"
    cli("compile", "--registry", str(LEDGER), "--validations", str(VALIDATION),
        "--config", str(CANDIDATES), "--out", str(table), "--today", "2026-08-30")
    out = tmp_path / "router.json"
    got = subprocess.run([sys.executable, "-m", "tierbook.cli", "export-vsr", "--table", str(table),
                          "--config", str(CANDIDATES), "--signal", f"{FAMILY}=retail",
                          "--default-model", "api-strong-a", "--out", str(out)],
                         cwd=ROOT, capture_output=True, text=True,
                         env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin:/usr/local/bin"})
    assert got.returncode != 0, got.stdout
    assert "no family produced an exportable decision" in got.stderr
    # The family and the guard, both named, because "nothing was exportable" without saying what stopped it is a
    # refusal nobody can act on.
    assert FAMILY in got.stderr, got.stderr
    assert "no load probe has been run" in got.stderr, got.stderr
    assert not out.exists(), "a refused export left a file behind"


def test_the_refusal_advises_a_probe_when_a_measurement_is_the_only_obstacle(tmp_path):
    """The advice adapts to the obstacles, and the case worth pinning is the one where a flag cannot help.

    Exported from a table compiled without the candidate file, the only family left is the one with the unmeasured
    guard, and the refusal says to run the probe and that `allow_provisional` will not help -- because the obstacle
    is a measurement rather than a fold. With the candidate file, a second family is skipped as provisional too and
    the advice covers that instead, which is why this is a separate test rather than a stricter assertion above.
    """
    table = tmp_path / "t.json"
    cli("compile", "--registry", str(LEDGER), "--validations", str(VALIDATION),
        "--family", f"{FAMILY}=api-strong-a", "--margin", "0.25", "--out", str(table), "--today", "2026-08-30")
    got = subprocess.run([sys.executable, "-m", "tierbook.cli", "export-vsr", "--table", str(table),
                          "--config", str(CANDIDATES), "--signal", f"{FAMILY}=retail",
                          "--default-model", "api-strong-a", "--out", str(tmp_path / "r.json")],
                         cwd=ROOT, capture_output=True, text=True,
                         env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin:/usr/local/bin"})
    assert got.returncode != 0, got.stdout
    assert "Run the load probe those guards name" in got.stderr, got.stderr
    assert "allow_provisional will not help" in got.stderr, got.stderr


def test_the_capacity_claim_is_still_refused_on_one_latency_point(tmp_path):
    """The other half of the original correction, which must not quietly come back either.

    One observation at one concurrency bounds nothing: throughput at higher concurrency may be higher, flat or
    lower. The compiled artifact has to keep saying so rather than turning that point into a capacity figure.
    """
    entry = compiled(tmp_path)["families"][FAMILY]["cannot_reject"]
    said = entry["self_hosted_capacity"]
    assert "not a saturation figure" in said, said
    assert "several concurrencies" in said, said
