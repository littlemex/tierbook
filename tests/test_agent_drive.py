"""The driver's outcomes row, which ran on a cluster and therefore had no tests.

It broke exactly the way an untested path breaks: a reference to a name that was not in scope raised inside the
row's dict, so thirteen instances ran to completion, cost real GPU time, and wrote no rows at all. Nothing failed
loudly; the sweep simply produced an empty outcomes file, and it was found by reading a stack trace out of a
state file afterwards.
"""
import json
import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import agent_drive as ad  # noqa: E402


def run_row(**kw):
    base = {"trace_id": "t" * 32, "returned": "/work/returned/x.tar", "timed_out": False,
            "returncode": 0, "wall_s": 12.5}
    base.update(kw)
    return base


def test_the_row_is_built_without_a_cluster():
    """The regression this file exists for: the row must be constructible from plain data."""
    row = ad.outcome_row(run_row(), {"agent_definition": "build"}, "opencode", 0,
                         item_id="astropy__astropy-14365", run_group="g1")
    assert row["trace_id"] == "t" * 32
    assert row["item_id"] == "astropy__astropy-14365" and row["run_group"] == "g1"
    assert row["agent_definition"] == "build" and row["agent"] == "opencode"
    assert row["wall_s"] == 12.5 and row["returncode"] == 0


def test_the_driver_never_states_an_outcome():
    """The oracle has not run. A driver that wrote "solved" here would be inventing the measurement."""
    row = ad.outcome_row(run_row(), {}, "opencode", 0, item_id="i", run_group=None)
    assert row["state"] == "pending_oracle"
    assert "solved" not in json.dumps(row)


def test_a_spec_with_no_definition_records_none_rather_than_an_empty_string():
    """An empty string would join as a candidate whose definition is the empty definition; None says absent."""
    assert ad.outcome_row(run_row(), {}, "a", 0, item_id="i", run_group=None)["agent_definition"] is None
    assert ad.outcome_row(run_row(), {"agent_definition": ""}, "a", 0,
                          item_id="i", run_group=None)["agent_definition"] is None


def test_a_timeout_and_a_nonzero_return_are_both_carried():
    """Both are things the driver OBSERVED, and the scorer needs them to tell a transport fault from a candidate
    that produced nothing."""
    row = ad.outcome_row(run_row(timed_out=True, returncode=124), {"agent_definition": "build"},
                         "opencode", 2, item_id="i", run_group="g")
    assert row["timed_out"] is True and row["returncode"] == 124 and row["iteration"] == 2


def test_a_run_that_returned_no_tree_says_so():
    row = ad.outcome_row(run_row(returned=None), {}, "a", 0, item_id="i", run_group=None)
    assert row["returned"] is None


def test_every_field_the_join_and_the_scorer_read_is_present():
    """The row is the contract between the driver, the oracle and the join. A field silently missing here surfaces
    as an unjoined row much later."""
    row = ad.outcome_row(run_row(), {"agent_definition": "build"}, "opencode", 0,
                         item_id="i", run_group="g")
    required = {"trace_id", "item_id", "run_group", "agent_definition", "agent", "iteration",
                "state", "returned", "timed_out", "returncode", "wall_s"}
    assert required <= set(row), f"missing {required - set(row)}"


def test_the_row_serialises():
    """It is written with json.dumps in an append loop, so a value that cannot serialise loses the whole run."""
    json.dumps(ad.outcome_row(run_row(), {"agent_definition": "build"}, "opencode", 0,
                              item_id="i", run_group="g"))


def test_the_run_records_the_prompt_it_was_actually_given(monkeypatch):
    """The manifest-level `prompt` is the template and still holds the workspace marker, so it cannot say whether
    the one sentence under measurement reached the agent. Each run records its own filled text."""
    ws = "/tmp/run-opencode-0ae4d3229d"
    text = ad.task_prompt.build("astropy/astropy", "an issue",
                                workspace=ad.task_prompt.WORKSPACE_MARKER, variant="workspace-bound")
    filled = ad.task_prompt.fill_workspace(text, ws)
    assert ad.task_prompt.WORKSPACE_MARKER not in filled
    assert ws in filled
    # The substitution is the driver's, done once, in run_one -- pinned here because a second caller doing it
    # again is how a prompt ends up half filled.
    assert filled.count(ws) == 1


# --- D1: the run's own code comes first -----------------------------------------------------------


def test_pythonpath_names_the_runs_own_workspace_and_its_src():
    """Two entries because layouts differ: `<ws>` for astropy, django and pylint, `<ws>/src` for flask."""
    got = ad.python_path_export("/tmp/run-opencode-0ae4d3229d")
    assert got == ("export PYTHONPATH='/tmp/run-opencode-0ae4d3229d:"
                   "/tmp/run-opencode-0ae4d3229d/src'; ")


def test_a_trailing_slash_does_not_produce_a_doubled_separator():
    assert "//" not in ad.python_path_export("/tmp/run-opencode-0ae4d3229d/")


def test_a_relative_workspace_is_refused_because_it_would_depend_on_cwd():
    """The whole defect is about cwd deciding what a run imports, so a relative entry would reintroduce it."""
    for bad in ("", ".", "run-opencode-0ae4d3229d", "~/work"):
        with pytest.raises(ValueError, match="absolute"):
            ad.python_path_export(bad)


def test_a_workspace_with_a_space_is_quoted():
    got = ad.python_path_export("/tmp/run opencode")
    assert "'" in got and got.endswith("; ")


def test_the_export_composes_before_the_telemetry_exports():
    """PYTHONPATH must be set whether or not telemetry is on, which an earlier shape got wrong by building the
    environment string only inside the telemetry branch."""
    assert ad.python_path_export("/tmp/x").endswith("; ")


# --- D3: the workspace goes when the run is done ---------------------------------------------------


WS_T = "/tmp/w/xarray"
BACK = f" ; mkdir -p /work/returned && tar cf /work/returned/x.tar -C {WS_T} ."


def test_the_sweep_up_comes_after_the_hand_back_and_before_the_exit():
    """Order is the whole correctness of this. Removing the tree before the tar would hand back nothing, and removing
    it after the exit would never happen."""
    inner = ad.build_inner(WS_T, ad.python_path_export(WS_T), "", "", BACK, True)
    # Two removals now: W2 makes the workspace fresh at the start, W3 sweeps it up at the end. The one this test is
    # about is the LAST, so it is found from the right rather than from the left.
    assert inner.index("tar cf") < inner.rindex("rm -rf") < inner.index("exit $")


def test_the_agents_status_survives_the_sweep_up():
    """`rm` must not become the command whose exit code the driver reads."""
    inner = ad.build_inner(WS_T, "", "", "", BACK, True)
    assert inner.endswith("exit ${exec_rc:-0}")


def test_nothing_is_removed_at_the_END_when_cleanup_is_off():
    """The opening removal is not optional -- a stale tree from an earlier run of the same item must never be
    inherited, and `--keep-workspace` is for reading one run's tree afterwards, not for starting from a dirty one."""
    inner = ad.build_inner(WS_T, "", "", "", BACK, False)
    assert inner.count("rm -rf") == 1
    assert inner.index("rm -rf") < inner.index(f"mkdir -p {ad._shq(WS_T)}")
    assert inner.rindex("rm -rf") < inner.index("tar cf"), "no sweep-up after the hand-back"
    assert "tar cf" in inner


def test_the_environment_is_exported_before_the_agent_starts():
    """A `PYTHONPATH` set after the exec would reach nothing."""
    inner = ad.build_inner(WS_T, ad.python_path_export(WS_T), "", "", "", True)
    assert inner.index("export PYTHONPATH") < inner.index('"$@"')


def test_the_workspace_is_made_before_anything_is_staged_into_it():
    inner = ad.build_inner(WS_T, "", "", f"tar xf /work/x.tar -C {WS_T} && ", "", True)
    assert inner.index("mkdir -p") < inner.index("tar xf")


def test_a_run_with_no_staged_tree_neither_hands_back_nor_keeps_its_workspace():
    inner = ad.build_inner(WS_T, "", "", "", "", True)
    assert "tar cf" not in inner and "rm -rf" in inner


def test_the_pre_commands_run_inside_the_guarded_setup_and_the_exports_after_it():
    """The order changed when setup became one guarded chain: `pre` is now inside it, so a failed configuration step
    is a setup failure rather than a run of a candidate that was never configured. The exports moved out because they
    cannot fail, and putting them in the chain was what broke it -- the string ends in `; `."""
    inner = ad.build_inner(WS_T, ad.python_path_export(WS_T), "setup >/dev/null 2>&1 && ", "", "", True)
    # `exit 91` appears twice: the busy-workspace check comes first, then the setup guard. This is about the second.
    assert inner.index("setup >") < inner.rindex("exit 91") < inner.index("export PYTHONPATH") < inner.index('"$@"')


# --- W1/W3: a workspace name a model does not have to memorise --------------------------------------


def test_the_workspace_is_named_after_the_repository_and_nothing_else():
    """Low entropy so a model can reproduce it -- six runs across three arms failed to reproduce the ten-character
    random id this replaces, one with the absolute path written in its prompt -- and NOT identifying, because naming it
    after the full instance id handed one agent its own answer."""
    assert ad.workspace_for("pydata__xarray-4695") == "/tmp/w/xarray"
    assert ad.workspace_for("matplotlib__matplotlib-26208") == "/tmp/w/matplotlib"
    assert ad.workspace_for("scikit-learn__scikit-learn-15100") == "/tmp/w/scikit-learn"
    assert ad.workspace_for("pallets__flask-5014") == "/tmp/w/flask"


def test_the_instance_number_never_appears_in_the_path():
    """The whole point. `astropy__astropy-14369` read 14369 off its path, inferred the upstream pull request, and
    downloaded the merged diff -- 14,013 bytes, successfully -- and that run solved."""
    for tag in ("astropy__astropy-14369", "pydata__xarray-4695", "django__django-11880"):
        ws = ad.workspace_for(tag)
        digits = tag.rsplit("-", 1)[-1]
        assert digits not in ws, (tag, ws)
        assert not any(c.isdigit() for c in ws.rsplit("/", 1)[-1]), ws


def test_two_items_from_one_repository_share_a_directory_deliberately():
    """A per-process sequence cannot distinguish them -- the driver is a fresh process per item -- and a sequence
    derived from the instance id would put the id back in the path recoverably. Sharing is safe because the workspace
    is removed before anything is staged and the run refuses to start if a live process is working there."""
    assert ad.workspace_for("astropy__astropy-14365") == ad.workspace_for("astropy__astropy-14369")


def test_a_run_without_an_item_id_is_refused_rather_than_naming_the_root():
    """The failure this guards: an empty tag would name the root, and the driver removes a workspace with rm -rf."""
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            ad.workspace_for(bad or "")


def test_the_guard_refuses_anything_outside_the_root():
    for bad in ("/tmp", "/tmp/", "/", "/tmp/other/x", "/home/akazawt/work", "relative/path", ""):
        with pytest.raises(ValueError):
            ad.guard_workspace(bad)


def test_the_guard_refuses_the_root_itself_however_it_is_spelled():
    for bad in (ad.WORKSPACE_ROOT, ad.WORKSPACE_ROOT + "/", ad.WORKSPACE_ROOT + "//", ad.WORKSPACE_ROOT + "/."):
        with pytest.raises(ValueError):
            ad.guard_workspace(bad)


def test_the_guard_refuses_a_traversal_that_would_climb_out():
    for bad in ("/tmp/w/../../etc", "/tmp/w/x/../..", "/tmp/w/../w2/x"):
        with pytest.raises(ValueError):
            ad.guard_workspace(bad)


def test_the_guard_accepts_a_real_workspace_and_normalises_the_trailing_slash():
    assert ad.guard_workspace("/tmp/w/pydata__xarray-4695/") == "/tmp/w/pydata__xarray-4695"


def test_a_template_still_goes_through_the_guard():
    assert ad.workspace_for("x", "/tmp/w/custom-{tag}") == "/tmp/w/custom-x"
    with pytest.raises(ValueError):
        ad.workspace_for("x", "/var/lib/{tag}")


# --- W2: fresh, not merely present -----------------------------------------------------------------


def test_the_workspace_is_removed_before_it_is_made():
    """With a deterministic name, inheriting a leftover from an earlier run of the same item is worse than a random
    name would have been, and `tar x` over an existing tree keeps what the archive does not overwrite."""
    inner = ad.build_inner("/tmp/w/i1", "", "", "tar xf /work/x.tar -C /tmp/w/i1 && ", "", True)
    # `mkdir -p` appears twice: the root, which is checked for being a symlink first, then the workspace. This test is
    # about the second, so it is named rather than found by position.
    assert inner.index("rm -rf") < inner.index("mkdir -p '/tmp/w/i1'") < inner.index("tar xf")


def test_the_assembled_command_refuses_a_workspace_the_guard_rejects():
    """build_inner interpolates into `rm -rf`, so it re-checks rather than trusting its caller."""
    for bad in ("/tmp", "/", "/tmp/w"):
        with pytest.raises(ValueError):
            ad.build_inner(bad, "", "", "", "", True)


def test_both_removals_name_the_same_guarded_and_quoted_path():
    """The trailing slash is normalised once, by the guard, so the two removals cannot disagree."""
    inner = ad.build_inner("/tmp/w/i1/", "", "", "", " ; tar cf /work/returned/x.tar -C /tmp/w/i1 .", True)
    assert inner.count("rm -rf '/tmp/w/i1'") == 2
    assert "/tmp/w/i1/'" not in inner


# --- the rm -rf lines, which are the dangerous part -------------------------------------------------


def test_a_name_the_shell_would_split_is_refused():
    """`rm -rf /tmp/w/x y` unquoted removes `/tmp/w/x` AND the relative path `y`. Found by reading the assembled
    command rather than by a reviewer, and refused as well as quoted."""
    for bad in ("/tmp/w/x y", "/tmp/w/x\ty", "/tmp/w/a;rm -rf /", "/tmp/w/$HOME", "/tmp/w/a`b`",
                "/tmp/w/a&b", "/tmp/w/a|b", "/tmp/w/a*", "/tmp/w/a'b", '/tmp/w/a"b'):
        with pytest.raises(ValueError, match="shell"):
            ad.guard_workspace(bad)


def test_real_instance_ids_are_accepted():
    """The assumption the refusal above documents: SWE-bench ids are word characters, dashes and underscores."""
    for ok, repo in (("pydata__xarray-4695", "xarray"), ("matplotlib__matplotlib-26208", "matplotlib"),
                     ("scikit-learn__scikit-learn-15100", "scikit-learn"), ("pylint-dev__pylint-4551", "pylint"),
                     ("psf__requests-1142", "requests")):
        assert ad.workspace_for(ok) == f"/tmp/w/{repo}"


def test_the_workspace_is_quoted_wherever_it_reaches_the_shell():
    inner = ad.build_inner("/tmp/w/i1", "", "", "", "", True)
    assert inner.count("'/tmp/w/i1'") >= 3, "opening rm, mkdir, cd and the sweep-up"
    assert "rm -rf /tmp/w/i1 " not in inner, "no bare occurrence"


def test_a_failed_hand_back_keeps_the_tree_instead_of_deleting_the_only_copy():
    """`;` would delete the workspace whether or not the archive was written, and a run whose hand-back failed is
    unscoreable either way -- the difference is whether anybody can look at it."""
    back = " ; mkdir -p /work/returned && tar cf /work/returned/x.tar -C /tmp/w/i1 ."
    inner = ad.build_inner("/tmp/w/i1", "", "", "", back, True)
    assert "tar cf /work/returned/x.tar -C /tmp/w/i1 . && rm -rf" in inner
    assert ". ; rm -rf" not in inner


def test_with_no_archive_to_hand_back_the_sweep_up_is_unconditional():
    """Nothing to depend on, so nothing to condition it against."""
    inner = ad.build_inner("/tmp/w/i1", "", "", "", "", True)
    assert " ; rm -rf '/tmp/w/i1'" in inner


def test_removing_a_symlinked_workspace_removes_the_link_not_its_target():
    """Recorded rather than tested against a filesystem: `rm -rf` on a symlink removes the link. A workspace that is
    a symlink is therefore not a route out of the root, unlike a `..` component."""
    assert ad.guard_workspace("/tmp/w/link") == "/tmp/w/link"


# --- the assembled command, actually executed -------------------------------------------------------
#
# String inspection said the ordering was right while the chain was silently broken by the `; ` at the end of the
# environment exports: a failed opening `rm -rf` skipped `mkdir` and the exports and staged over the stale tree
# anyway, then exited with the agent's status. Both reviewers found it and neither could have found it from a test
# that only read the string. These run it.


import os
import subprocess


def _run(inner, agent_argv, *, cwd):
    """`sh -c inner sh <agent argv>`, which is how kubectl exec invokes it."""
    return subprocess.run(["sh", "-c", inner, "sh", *agent_argv], capture_output=True, text=True, cwd=cwd)


def _root(monkeypatch, tmp_path):
    root = tmp_path / "w"
    monkeypatch.setattr(ad, "WORKSPACE_ROOT", str(root))
    return root


def test_a_normal_run_stages_works_hands_back_and_sweeps_up(monkeypatch, tmp_path):
    root = _root(monkeypatch, tmp_path)
    ws = ad.workspace_for("pydata__xarray-4695")
    src = tmp_path / "staged"
    (src / "xarray").mkdir(parents=True)
    (src / "xarray" / "core.py").write_text("original\n")
    tar = tmp_path / "staged.tar"
    subprocess.run(["tar", "cf", str(tar), "-C", str(src), "."], check=True)
    back_dir = tmp_path / "returned"
    back_dir.mkdir()
    ret = back_dir / "run.tar"
    inner = ad.build_inner(ws, ad.python_path_export(ws), "",
                           f"tar xf {tar} --no-same-owner -C {ws} && ",
                           f" ; tar cf {ret} -C {ws} .", True)
    p = _run(inner, ["sh", "-c", "test -f xarray/core.py && echo edited > xarray/core.py"], cwd=tmp_path)
    assert p.returncode == 0, p.stderr
    assert not os.path.exists(ws), "swept up"
    assert ret.exists(), "handed back"
    listing = subprocess.run(["tar", "tf", str(ret)], capture_output=True, text=True).stdout
    assert "./xarray/core.py" in listing


def test_the_agents_own_status_is_what_the_driver_sees(monkeypatch, tmp_path):
    _root(monkeypatch, tmp_path)
    ws = ad.workspace_for("i1")
    inner = ad.build_inner(ws, ad.python_path_export(ws), "", "", "", True)
    assert _run(inner, ["sh", "-c", "exit 7"], cwd=tmp_path).returncode == 7
    assert _run(inner, ["sh", "-c", "exit 0"], cwd=tmp_path).returncode == 0


def test_a_setup_failure_exits_with_its_own_status_and_never_runs_the_agent(monkeypatch, tmp_path):
    """The defect both reviewers found. A previous run left a directory it had made unwritable -- something agents do
    while testing permission bugs -- so `rm -rf` fails. It used to skip mkdir and the exports, stage over the stale
    tree, run the agent, and exit 0."""
    root = _root(monkeypatch, tmp_path)
    ws = ad.workspace_for("i1")
    stale = Path(ws) / "sub"
    stale.mkdir(parents=True)
    (stale / "leftover.py").write_text("from an earlier run\n")
    os.chmod(stale, 0o500)             # unwritable: its child cannot be unlinked
    marker = tmp_path / "agent-ran"
    try:
        inner = ad.build_inner(ws, ad.python_path_export(ws), "", "", "", True)
        p = _run(inner, ["sh", "-c", f"touch {marker}"], cwd=tmp_path)
        assert p.returncode == ad.SETUP_FAILED, (p.returncode, p.stderr)
        assert "setup failed" in p.stderr
        assert not marker.exists(), "the agent must not have run"
    finally:
        os.chmod(stale, 0o700)


def test_a_setup_failure_does_not_stage_over_the_stale_tree(monkeypatch, tmp_path):
    """The contamination the freshness clause exists to prevent, and the case where it used to happen."""
    root = _root(monkeypatch, tmp_path)
    ws = ad.workspace_for("i1")
    stale = Path(ws) / "sub"
    stale.mkdir(parents=True)
    (stale / "leftover.py").write_text("from an earlier run\n")
    os.chmod(stale, 0o500)
    src = tmp_path / "staged"
    src.mkdir()
    (src / "fresh.py").write_text("staged\n")
    tar = tmp_path / "staged.tar"
    subprocess.run(["tar", "cf", str(tar), "-C", str(src), "."], check=True)
    try:
        inner = ad.build_inner(ws, ad.python_path_export(ws), "",
                              f"tar xf {tar} --no-same-owner -C {ws} && ", "", True)
        p = _run(inner, ["sh", "-c", "true"], cwd=tmp_path)
        assert p.returncode == ad.SETUP_FAILED
        assert not (Path(ws) / "fresh.py").exists(), "nothing was staged over the stale tree"
        assert (stale / "leftover.py").exists(), "and the stale tree is left for someone to look at"
    finally:
        os.chmod(stale, 0o700)


def test_a_stray_file_from_an_earlier_run_of_the_same_item_is_gone(monkeypatch, tmp_path):
    """Clause 3 of the contract, executed rather than asserted about a string."""
    root = _root(monkeypatch, tmp_path)
    ws = ad.workspace_for("i1")
    Path(ws).mkdir(parents=True)
    (Path(ws) / "stray.py").write_text("from an earlier run\n")
    inner = ad.build_inner(ws, ad.python_path_export(ws), "", "", "", True)
    p = _run(inner, ["sh", "-c", "test -e stray.py && exit 3 || exit 0"], cwd=tmp_path)
    assert p.returncode == 0, "the agent must not have seen the stray file"


def test_a_failed_hand_back_keeps_the_tree(monkeypatch, tmp_path):
    """The only copy of what the run did must not be deleted because the archive could not be written."""
    root = _root(monkeypatch, tmp_path)
    ws = ad.workspace_for("i1")
    ret = tmp_path / "no-such-dir" / "run.tar"        # the directory does not exist, so `tar cf` fails
    inner = ad.build_inner(ws, ad.python_path_export(ws), "", "", f" ; tar cf {ret} -C {ws} .", True)
    p = _run(inner, ["sh", "-c", "echo work > done.txt"], cwd=tmp_path)
    assert p.returncode == 0, "the agent's status, not tar's"
    assert (Path(ws) / "done.txt").exists(), "the tree survived a failed hand-back"


def test_pythonpath_reaches_the_agent_and_names_the_runs_own_workspace(monkeypatch, tmp_path):
    root = _root(monkeypatch, tmp_path)
    ws = ad.workspace_for("i1")
    inner = ad.build_inner(ws, ad.python_path_export(ws), "", "", "", True)
    p = _run(inner, ["sh", "-c", 'printf "%s" "$PYTHONPATH"'], cwd=tmp_path)
    assert p.stdout == f"{ws}:{ws}/src", p.stdout


def test_a_failing_pre_command_is_a_setup_failure_too(monkeypatch, tmp_path):
    """`pre` configures an agent that cannot be told where to work. A run whose configuration step failed is not a
    run of the candidate it claims to be."""
    root = _root(monkeypatch, tmp_path)
    ws = ad.workspace_for("i1")
    marker = tmp_path / "agent-ran"
    inner = ad.build_inner(ws, ad.python_path_export(ws), "false >/dev/null 2>&1 && ", "", "", True)
    p = _run(inner, ["sh", "-c", f"touch {marker}"], cwd=tmp_path)
    assert p.returncode == ad.SETUP_FAILED
    assert not marker.exists()


def test_a_symlinked_root_is_a_setup_failure(monkeypatch, tmp_path):
    """The guard is lexical and this is not. Two reviews made the same point: if a previous run left the root a
    symlink -- every run executes arbitrary agent-chosen code as the same user on a shared pod -- then `rm -rf` under
    it resolves through the link and deletes outside the directory the guard exists to protect."""
    root = tmp_path / "w"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "precious.txt").write_text("someone else's data\n")
    root.symlink_to(elsewhere)
    monkeypatch.setattr(ad, "WORKSPACE_ROOT", str(root))
    ws = ad.workspace_for("i1")
    marker = tmp_path / "agent-ran"
    inner = ad.build_inner(ws, ad.python_path_export(ws), "", "", "", True)
    p = _run(inner, ["sh", "-c", f"touch {marker}"], cwd=tmp_path)
    assert p.returncode == ad.SETUP_FAILED, (p.returncode, p.stderr)
    assert not marker.exists()
    assert (elsewhere / "precious.txt").exists(), "nothing outside the root was touched"


def test_a_real_root_is_created_when_absent(monkeypatch, tmp_path):
    root = tmp_path / "w"
    monkeypatch.setattr(ad, "WORKSPACE_ROOT", str(root))
    ws = ad.workspace_for("i1")
    inner = ad.build_inner(ws, ad.python_path_export(ws), "", "", "", True)
    assert _run(inner, ["sh", "-c", "true"], cwd=tmp_path).returncode == 0
    assert root.is_dir() and not root.is_symlink()


def test_a_live_process_working_in_the_workspace_stops_the_run(monkeypatch, tmp_path):
    """A risk this change CREATED. A kubectl exec timeout does not reliably kill the remote process tree, so an orphan
    from an earlier run can still be alive -- and with a name derived from the item, the next run of that item takes its
    tree away mid-write. With random names the orphan held a directory nothing would reuse."""
    if not Path("/proc/self/cwd").exists():
        pytest.skip("this check reads /proc, which this platform does not have")
    root = tmp_path / "w"
    monkeypatch.setattr(ad, "WORKSPACE_ROOT", str(root))
    ws = Path(ad.workspace_for("i1"))
    ws.mkdir(parents=True)
    (ws / "orphan-was-writing.txt").write_text("mid-write\n")
    holder = subprocess.Popen(["sh", "-c", "sleep 30"], cwd=str(ws))
    try:
        inner = ad.build_inner(str(ws), ad.python_path_export(str(ws)), "", "", "", True)
        p = _run(inner, ["sh", "-c", "true"], cwd=str(tmp_path))
        assert p.returncode == ad.SETUP_FAILED, (p.returncode, p.stdout, p.stderr)
        assert "another process is working" in p.stderr
        assert (ws / "orphan-was-writing.txt").exists(), "the orphan's tree was not taken away"
    finally:
        holder.kill()
        holder.wait()


def test_an_empty_workspace_with_nobody_in_it_starts_normally(monkeypatch, tmp_path):
    root = tmp_path / "w"
    monkeypatch.setattr(ad, "WORKSPACE_ROOT", str(root))
    ws = ad.workspace_for("i1")
    inner = ad.build_inner(ws, ad.python_path_export(ws), "", "", "", True)
    assert _run(inner, ["sh", "-c", "true"], cwd=str(tmp_path)).returncode == 0


def test_the_runs_own_shell_does_not_match_itself(monkeypatch, tmp_path):
    """The check runs before `cd`, so the shell executing it is not yet in the workspace."""
    root = tmp_path / "w"
    monkeypatch.setattr(ad, "WORKSPACE_ROOT", str(root))
    ws = ad.workspace_for("i1")
    inner = ad.build_inner(ws, ad.python_path_export(ws), "", "", "", True)
    assert inner.index("readlink") < inner.index("cd '")
    p = _run(inner, ["sh", "-c", "pwd"], cwd=str(tmp_path))
    assert p.returncode == 0 and p.stdout.strip().endswith("/w/i1")


def test_the_busy_check_matches_a_directory_boundary_not_a_name_prefix(monkeypatch, tmp_path):
    """A bare `<ws>*` would also match `/tmp/w/astropy-scratch`, which is a different directory. With repo-only names
    the workspace is short, so a prefix match has more neighbours to hit."""
    if not Path("/proc/self/cwd").exists():
        pytest.skip("this check reads /proc, which this platform does not have")
    root = tmp_path / "w"
    monkeypatch.setattr(ad, "WORKSPACE_ROOT", str(root))
    ws = ad.workspace_for("astropy__astropy-14369")
    neighbour = Path(str(ws) + "-scratch")
    neighbour.mkdir(parents=True)
    holder = subprocess.Popen(["sh", "-c", "sleep 20"], cwd=str(neighbour))
    try:
        inner = ad.build_inner(ws, ad.python_path_export(ws), "", "", "", True)
        p = _run(inner, ["sh", "-c", "true"], cwd=str(tmp_path))
        assert p.returncode == 0, (p.returncode, p.stderr)
    finally:
        holder.kill()
        holder.wait()


def test_a_process_below_the_workspace_still_stops_the_run(monkeypatch, tmp_path):
    if not Path("/proc/self/cwd").exists():
        pytest.skip("this check reads /proc, which this platform does not have")
    root = tmp_path / "w"
    monkeypatch.setattr(ad, "WORKSPACE_ROOT", str(root))
    ws = Path(ad.workspace_for("astropy__astropy-14369"))
    deep = ws / "astropy" / "units"
    deep.mkdir(parents=True)
    holder = subprocess.Popen(["sh", "-c", "sleep 20"], cwd=str(deep))
    try:
        inner = ad.build_inner(str(ws), ad.python_path_export(str(ws)), "", "", "", True)
        assert _run(inner, ["sh", "-c", "true"], cwd=str(tmp_path)).returncode == ad.SETUP_FAILED
    finally:
        holder.kill()
        holder.wait()
