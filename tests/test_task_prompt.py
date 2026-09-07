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
    assert out.count("/tmp/run-opencode-abc") >= 2, "named where the agent reads and where it edits"


def test_it_states_the_two_environment_facts_the_failures_ran_into():
    out = tp.build("pytest-dev/pytest", "the issue", workspace="/w", variant="workspace-bound")
    assert "complete checkout" in out, "one run tried to clone the repository"
    assert "no network access" in out
    assert "refused" in out, "the permission wall is stated rather than discovered"


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
    assert filled.count("/tmp/run-opencode-abc") >= 2


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
    assert filled.count("/tmp/run-x") == 2, "only the marker was replaced"
