"""The prompt text, which the recordings identified as the cause of two zero-edit runs.

It had lived inside a heredoc where no test could see it. Each test here is a way the change could look applied
and not be, or could break something the oracle depends on.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import task_prompt as tp  # noqa: E402


def test_the_workspace_variant_states_an_absolute_path():
    """The recordings' failure signature: `glob {"path":"/tmp"}` and `git clone` from the internet, both refused,
    from agents that never looked inside their own workspace. The prompt had said "in the current directory"."""
    out = tp.build("pydata/xarray", "the issue", workspace="/tmp/run-opencode-abc",
                   variant="workspace-bound")
    assert "/tmp/run-opencode-abc" in out
    assert "in the current directory" not in out
    # Once, in the first sentence. The draft named it twice and the second mention was inside a sentence about
    # enforcement that a phase-4 review showed the contract did not license.
    assert out.count("/tmp/run-opencode-abc") == 1


def test_it_states_the_checkout_is_complete_which_is_the_true_and_useful_part():
    out = tp.build("pytest-dev/pytest", "the issue", workspace="/w", variant="workspace-bound")
    assert "complete checkout" in out, "one run tried to clone the repository"
    assert "no need to fetch or clone" in out


def test_it_does_not_claim_the_environment_is_offline_because_it_is_not():
    """A run that solved fetched 5,010 bytes from raw.githubusercontent.com successfully. The `git clone` in the
    other failure was stopped by the permission system, not by the absence of a network, and telling a model
    something it can disprove in one call invites it to discount the rest of the prompt."""
    out = tp.build("r", "p", workspace="/w", variant="workspace-bound")
    assert "no network access" not in out
    assert "cannot be fetched" not in out


def test_it_does_not_talk_about_enforcement():
    """A statement that paths outside the workspace "are refused" is about enforcement -- the text-channel twin of
    the harness lever this change deliberately excluded, so that the prompt could be told apart from it."""
    out = tp.build("r", "p", workspace="/w", variant="workspace-bound")
    assert "refused" not in out and "not permitted" not in out


def test_the_instructions_the_oracle_depends_on_survive_the_change():
    """Both are load-bearing for the oracle rather than for the agent: the instance's test patch is applied after
    the diff is taken, and a run that does not stop is a timeout rather than an answer."""
    for variant in ("baseline", "workspace-bound"):
        out = tp.build("r", "p", workspace="/w", variant=variant)
        assert "Do not write any tests" in out
        assert "When you are done, stop" in out
        assert "--- issue ---" in out and out.rstrip().endswith("p")


def test_the_baseline_is_kept_so_it_can_be_reproduced_exactly():
    """A before/after needs the before to be reconstructible, not approximated."""
    out = tp.build("pydata/xarray", "the issue")
    assert out.startswith("You are working in a checkout of the pydata/xarray repository in the current "
                          "directory.")
    assert "no network access" not in out


def test_a_variant_that_names_the_workspace_refuses_to_run_without_one():
    """A prompt that says "at {workspace}" literally is worse than the wording it replaced."""
    with pytest.raises(ValueError) as e:
        tp.build("r", "p", variant="workspace-bound")
    assert "must be given one" in str(e.value)
    with pytest.raises(ValueError):
        tp.build("r", "p", workspace="", variant="workspace-bound")


def test_an_unknown_variant_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        tp.build("r", "p", variant="whatever")
    assert "unknown prompt variant" in str(e.value)


def test_an_empty_problem_statement_is_refused():
    """It would ask the agent to fix nothing and the run would look like a capability failure."""
    with pytest.raises(ValueError) as e:
        tp.build("r", "   ", workspace="/w", variant="workspace-bound")
    assert "fix nothing" in str(e.value)


def test_the_problem_statement_is_not_reformatted():
    """A statement whose whitespace or braces were mangled is a different task."""
    problem = "line one\n\n    indented { braces } and a %s\n"
    out = tp.build("r", problem, workspace="/w", variant="workspace-bound")
    assert problem in out


# --- the marker, because the workspace is a per-session fact the sweep cannot know ------------------


def test_the_marker_survives_the_file_and_is_filled_at_run_time():
    """The sweep writes the task before a run exists; the driver creates the workspace. So the text carries a
    marker until the driver fills it, and a prompt shipped with the marker still in it would be worse than the
    wording it replaced."""
    text = tp.build("r", "p", workspace=tp.WORKSPACE_MARKER, variant="workspace-bound")
    assert tp.WORKSPACE_MARKER in text
    filled = tp.fill_workspace(text, "/tmp/run-opencode-abc")
    assert tp.WORKSPACE_MARKER not in filled
    assert filled.count("/tmp/run-opencode-abc") == 1


def test_filling_refuses_when_the_text_needs_a_workspace_and_none_is_given():
    """Invisible in an outcome: the agent would be told to work at a literal placeholder."""
    text = tp.build("r", "p", workspace=tp.WORKSPACE_MARKER, variant="workspace-bound")
    with pytest.raises(ValueError) as e:
        tp.fill_workspace(text, "")
    assert tp.WORKSPACE_MARKER in str(e.value)


def test_filling_a_text_with_no_marker_is_a_no_op():
    """The baseline names no workspace, and passing it through must not change a character of it."""
    text = tp.build("r", "p")
    assert tp.fill_workspace(text, "/tmp/anything") == text


def test_a_problem_statement_containing_braces_is_not_mangled_by_the_marker_path():
    """The text passes through a file, so a brace in the issue must not be read as a format field. That is why the
    marker is a literal string rather than another `{}` placeholder."""
    problem = "the call f(**{'a': 1}) raises, and {workspace} appears in the traceback"
    text = tp.build("r", problem, workspace=tp.WORKSPACE_MARKER, variant="workspace-bound")
    filled = tp.fill_workspace(text, "/tmp/run-x")
    assert problem in filled, "the issue text is untouched"
    assert "{workspace}" in filled, "a brace in the issue stays a brace"
    assert filled.count("/tmp/run-x") == 1, "only the marker was replaced"


# --- C1 says absolute, and the delivery gate ------------------------------------------------------


def test_a_relative_workspace_is_refused_because_c1_says_absolute():
    """`.` or `../repo` passes every other check while telling the agent the relative thing this change replaces."""
    for bad in (".", "../repo", "tmp/run-opencode-0ae4d3229d", "~/work"):
        with pytest.raises(ValueError, match="absolute"):
            tp.build("astropy/astropy", "an issue", workspace=bad, variant="workspace-bound")
        with pytest.raises(ValueError, match="absolute"):
            tp.fill_workspace(f"work at {tp.WORKSPACE_MARKER}", bad)


def test_the_marker_itself_is_allowed_through_build_because_the_driver_fills_it_later():
    text = tp.build("astropy/astropy", "an issue", workspace=tp.WORKSPACE_MARKER, variant="workspace-bound")
    assert tp.WORKSPACE_MARKER in text
    assert tp.fill_workspace(text, "/tmp/run-opencode-0ae4d3229d").count("/tmp/run-opencode-0ae4d3229d") == 1


def test_an_unfilled_marker_is_refused_at_delivery_rather_than_shipped():
    """Without this gate a skipped substitution produces a run, an outcome, and a row in a comparison, with the one
    sentence the change is about reading `at <<WORKSPACE>>`. Nothing downstream tells that from the change working."""
    text = tp.build("astropy/astropy", "an issue", workspace=tp.WORKSPACE_MARKER, variant="workspace-bound")
    with pytest.raises(ValueError, match="fill_workspace"):
        tp.check_deliverable(text)


def test_the_gate_passes_a_filled_prompt_and_returns_it_unchanged():
    text = tp.fill_workspace(
        tp.build("astropy/astropy", "an issue", workspace=tp.WORKSPACE_MARKER, variant="workspace-bound"),
        "/tmp/run-opencode-0ae4d3229d")
    assert tp.check_deliverable(text) is text


def test_the_baseline_variant_needs_no_workspace_and_passes_the_gate():
    text = tp.build("astropy/astropy", "an issue")
    assert "current directory" in text
    assert tp.check_deliverable(text) is text
