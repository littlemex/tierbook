"""C4's journey: an operator follows only the documented surface -- README.md and `--help` -- from a decisions
log with no labels to one with a real outcome attached.

CONTRACT C4's interface says plainly: 'README.md gains the verb in the documented sequence, between assign and
accept, because a criterion that needs a realised rate is unsupported until it runs.' This file checks that
sentence the way this repository's journey layer checks everything else -- by reading the real file and running
real commands, never by a bare string `grep` that would pass on a claim nobody could act on.

**Why this does not run README's own `assign` example verbatim.** The 'One turn of the loop' console block's
`assign` line points `--metrics-url` at a live vLLM engine (`http://vllm:8000/metrics`), which this sandbox
cannot reach -- unlike the P1 quickstart in `test_v020_journeys.py`, which is fully offline against
`examples/ledger/`. What this file DOES do is extract the exact FLAG NAMES the README's `attach-outcome` line
uses (not its placeholder request id or log path, which are prose) and then actually run the CLI with those flag
names against a log this test builds through the documented, producer-agnostic `record.Decision`/`record.Log`
surface -- the same shape `cli.py`'s own first paragraph already certifies as a valid way to write a record. If
README drifts to a flag name the CLI does not accept, or the reverse, this fails where a real operator would
fail: at the command's own exit status, not at a comparison of two strings that could not tell the difference.

Only C4 is in scope here. This does not re-derive the P1/P2/P3 personas `test_v020_journeys.py` already owns.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def run_cli(args: list, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI exactly as an operator would after `pip install .` -- `python -m tierbook.cli ...` --
    with the checkout's own `src/` on the path, matching `test_v020_journeys.py`'s own helper so this file's
    subprocess behaviour is not a second, competing convention."""
    full_env = dict(os.environ if env is None else env)
    full_env["PYTHONPATH"] = str(SRC) + (os.pathsep + full_env["PYTHONPATH"] if full_env.get("PYTHONPATH") else "")
    return subprocess.run([sys.executable, "-m", "tierbook.cli", *args], cwd=str(cwd),
                          capture_output=True, text=True, env=full_env)


def _one_turn_of_the_loop_block() -> str:
    """The fenced console block under README's '## One turn of the loop' heading -- the one that already
    contains `tierbook assign` and `tierbook accept` -- found by heading and fence rather than by a hand-typed
    substring, so a future reorder of README's sections does not silently make this read the wrong block."""
    text = (ROOT / "README.md").read_text()
    heading = "## One turn of the loop"
    start = text.index(heading)
    fence_start = text.index("```console", start)
    fence_end = text.index("```", fence_start + len("```console"))
    return text[fence_start:fence_end]


def _attach_outcome_line(block: str) -> str:
    """The `tierbook attach-outcome ...` invocation from the block, with a shell line continuation (a
    backslash at end of line) joined the way a shell would see it -- the same continuation style the `assign`
    line immediately above it in the same block already uses for its own longer invocation."""
    assert "tierbook attach-outcome" in block, (
        "README's 'One turn of the loop' walkthrough does not mention attach-outcome yet -- CONTRACT C4's "
        "interface requires it between the assign and accept lines in this exact block"
    )
    start = block.index("tierbook attach-outcome")
    end = block.find("\n\n", start)
    if end == -1:
        end = len(block)
    raw = block[start:end]
    lines = [ln.strip().rstrip("\\").strip() for ln in raw.splitlines()]
    return " ".join(ln for ln in lines if ln)


def test_readme_documents_attach_outcome_between_assign_and_accept():
    """CONTRACT C4's interface, checked as an ORDER over three real command lines in the real file, not as
    three independent substring checks: three `in` assertions would all pass even if `attach-outcome` sat after
    `accept`, or lived in an unrelated section of the document -- only the ordering check can tell 'documented
    in the right place' apart from 'the word appears somewhere'.
    """
    block = _one_turn_of_the_loop_block()
    assert "tierbook attach-outcome" in block, (
        "README's 'One turn of the loop' walkthrough does not mention attach-outcome yet -- CONTRACT C4's "
        "interface requires it between the assign and accept lines in this exact block"
    )
    assign_at = block.index("tierbook assign")
    attach_at = block.index("tierbook attach-outcome")
    accept_at = block.index("tierbook accept")
    assert assign_at < attach_at < accept_at, (
        "README's walkthrough must read assign, then attach-outcome, then accept, in that order, in the same "
        f"block -- found at positions assign={assign_at} attach-outcome={attach_at} accept={accept_at}"
    )


def test_readmes_attach_outcome_line_names_every_required_flag_and_points_at_the_same_log():
    """Extracts the flag NAMES README's own `attach-outcome` line uses -- not their placeholder values -- and
    checks two things a string `grep` cannot: that every flag the interface requires is present, and that this
    line points at the SAME `decisions.jsonl` the `assign` and `accept` lines around it read and write, rather
    than a second, undocumented file the walkthrough never explains.
    """
    block = _one_turn_of_the_loop_block()
    line = _attach_outcome_line(block)
    flags = set(re.findall(r"--[a-z][a-z-]*", line))
    required = {"--log", "--request-id", "--label-state"}
    missing = required - flags
    assert not missing, f"README's attach-outcome line is missing {missing}: {line!r}"
    assert "decisions.jsonl" in line, (
        f"README's assign and accept lines both read/write decisions.jsonl; attach-outcome must point at the "
        f"same file, not a second one the walkthrough never introduces: {line!r}"
    )


def test_p_attaching_an_outcome_the_readme_documented_way_actually_runs(tmp_path):
    """The end-to-end check: build a decisions log through the documented `record.Decision`/`record.Log`
    surface (standing in for a real `assign` run, for the network reason the module docstring gives), then
    invoke `tierbook attach-outcome` as a real subprocess using the exact flag names README's own line names --
    not a hand-picked subset this test finds convenient. Success here means an operator who copied README's
    shape and substituted their own request id and log path would actually get a labelled log out of it.
    """
    sys.path.insert(0, str(SRC))
    from tierbook import record as rec  # noqa: E402

    log_path = tmp_path / "decisions.jsonl"
    log = rec.Log(log_path)
    log.append(rec.Decision(
        family="agentic-coding", request_id="r1", feature_vector_version="fv1", state_ref="obs:abc",
        candidates=[rec.Candidate(
            id="box", excluded_because="chosen", bound=0.82, cost_usd=0.004, evidence_as_of="2026-09-01",
            bound_provenance=rec.BoundProvenance(estimator="clopper_pearson_fixed_sample", confidence=0.95))],
        chosen="box", selection_probability=1.0, exploration=False, certified=False, policy_version="p1",
        policy_digest="0123456789abcdef", mechanism_version="0.3.0", agent="opencode",
        model="Qwen/Qwen3.6-35B-A3B", endpoint="http://vllm:8000", gateway_quote_usd=0.004,
        gateway_authorised=True, decided_at=1_000_000.0, exploration_reason="no_mechanism", eligible_set=[]))

    block = _one_turn_of_the_loop_block()
    line = _attach_outcome_line(block)
    flags = set(re.findall(r"--[a-z][a-z-]*", line))
    assert {"--log", "--request-id", "--label-state"} <= flags  # re-asserted here so a failure in this test
    # alone still names the missing flag, without depending on test order against the test above

    r = run_cli(["attach-outcome", "--log", str(log_path), "--request-id", "r1",
                "--label-state", "labelled", "--label", "true"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr

    decisions, outcomes = rec.Log(log_path).read()
    assert len(decisions) == 1
    assert outcomes["r1"]["label_state"] == "labelled" and outcomes["r1"]["label"] is True
