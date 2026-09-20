"""The seam between `infra/tierbook-up` and `tools/verify_ops_live.py`, checked by running both halves.

**Why this file exists.** Two programs write and read one JSON shape, and they are in different languages. Nothing in
either one fails at the moment the shape drifts: the script keeps writing a key nobody reads, or the driver keeps
looking for a key nobody writes, and the failure surfaces on a real cluster with a paid gateway standing by. So the
shape is checked here, with the script's own `connect` producing the file and the driver's own reader consuming it.

What is deliberately NOT here: the script's `up`, `measure` and `down`. Those create and destroy paid infrastructure and
cannot be exercised in a test suite; `docs/verify/` carries their evidence instead. `connect` is the one door that
touches no cloud resource, which is exactly why it is the one that can be pinned.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "tierbook-up"
DRIVER = ROOT / "tools" / "verify_ops_live.py"


def run_connect(tmp_path: Path, *, with_measurement: bool, api_price: str | None = "5.0") -> subprocess.CompletedProcess:
    """Run the real script's `connect` against a work directory we seeded, and return the process.

    `connect` reads files rather than the cloud: the probe output and the derived price are files that `measure` leaves
    behind, and the gateway URL comes from a stack lookup that simply yields nothing here. That is the honest shape for
    a test -- the absence of a gateway is a state the script has to report rather than crash on.
    """
    work = tmp_path / "work"
    work.mkdir()
    if with_measurement:
        (work / "probe.json").write_text(json.dumps({
            "per_hour": 718410.0, "arrivals": "open_loop", "deadline_seconds": 8.0,
            "goodput_per_hour": 718410.0, "understated_because": "load_fully_absorbed",
            "offered": {"concurrency": 444, "seats": 256, "generator": "open_loop_probe poisson rate=200/s"},
            "observed": {"wall_seconds": 60.6, "output_tokens": 299426, "completed": 12099},
        }))
        (work / "box-price.json").write_text(json.dumps({
            "instance_usd_per_hour": 2.699, "output_tokens_per_hour": 17779175.0,
            "usd_per_output_mtok": 0.1518, "throughput_is_lower_bound": True,
            "understated_because": "load_fully_absorbed", "price_is_upper_bound": True,
        }))
        (work / "api-key.txt").write_text("sk-not-a-real-key")

    env = dict(os.environ)
    env.update({
        "TIERBOOK_WORK_DIR": str(work),
        "TIERBOOK_CONNECTION_FILE": str(tmp_path / "connection.json"),
        "TIERBOOK_INFRA_CONFIG": str(tmp_path / "absent.env"),
        "TIERBOOK_GATEWAY_PREFIX": "", "TIERBOOK_CLUSTER_NAME": "",
        "TIERBOOK_API_MODEL": "some-metered-model",
        "TIERBOOK_BOX_MODEL": "some/served-model",
        "TIERBOOK_REQUIRED_PER_HOUR": "100",
        # No AWS profile and no credentials needed: `connect` only looks up a stack that is not there, and the lookup
        # failing is the state it reports.
        "AWS_PROFILE": "",
    })
    if api_price is None:
        env.pop("TIERBOOK_API_PRICE_PER_MTOK", None)
    else:
        env["TIERBOOK_API_PRICE_PER_MTOK"] = api_price
    return subprocess.run(["bash", str(SCRIPT), "connect"], capture_output=True, text=True, env=env, cwd=str(ROOT))


def read_with_driver(path: Path):
    """Read the file with the driver's own reader, imported rather than reimplemented."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("verify_ops_live", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_script_is_executable_and_its_usage_lists_every_door():
    """A door the usage text does not mention is a door nobody finds."""
    assert SCRIPT.exists() and os.access(SCRIPT, os.X_OK)
    out = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode != 0, "with no argument the script should print usage and fail, not proceed"
    for door in ("doctor", "status", "up", "connect", "measure", "down"):
        assert door in out.stdout, f"the usage text does not mention `{door}`"


def test_a_connection_file_the_driver_can_read(tmp_path):
    """The whole point: the script writes it, the driver's own reader accepts it, and every value survives the trip."""
    got = run_connect(tmp_path, with_measurement=True)
    assert got.returncode == 0, got.stderr
    conn = tmp_path / "connection.json"
    assert conn.exists()

    mod = read_with_driver(conn)
    # The gateway is absent in this environment, so the reader must refuse -- and say which half is missing.
    with pytest.raises(SystemExit) as e:
        mod.from_connection(str(conn))
    assert "gateway URL" in str(e.value) or "API key" in str(e.value)

    # With the gateway's half filled in, the same file reads cleanly and carries the derived price and the capacity.
    payload = json.loads(conn.read_text())
    payload["api"]["chat_completions_url"] = "https://example.invalid/v1/chat/completions"
    conn.write_text(json.dumps(payload))
    args = mod.from_connection(str(conn))
    assert args["box_price_per_mtok"] == pytest.approx(0.1518)
    assert args["api_price_per_mtok"] == pytest.approx(5.0)
    assert args["required_per_hour"] == pytest.approx(100.0)
    assert args["capacity"]["understated_because"] == "load_fully_absorbed"
    assert args["capacity"]["seats"] == 256


def test_every_key_the_driver_declares_is_actually_written(tmp_path):
    """The drift check. The driver names the keys it reads as a constant; this asserts the script writes all of them."""
    got = run_connect(tmp_path, with_measurement=True)
    assert got.returncode == 0, got.stderr
    payload = json.loads((tmp_path / "connection.json").read_text())
    mod = read_with_driver(tmp_path / "connection.json")

    for side in ("box", "api"):
        for key in mod.CONNECTION_KEYS[side]:
            assert key in payload[side], f"the driver reads {side}.{key} and the script does not write it"
    for key in mod.CONNECTION_KEYS["top"]:
        assert key in payload, f"the driver reads {key} and the script does not write it"
    for key in mod.CONNECTION_CAPACITY_KEYS:
        assert key in payload["box"]["capacity"], f"the capacity block is missing {key}"


def test_the_capacity_block_carries_exactly_what_a_throughput_needs(tmp_path):
    """A capacity block is only worth writing if it can become a `Throughput`. This builds one from it."""
    from tierbook import throughput as th
    got = run_connect(tmp_path, with_measurement=True)
    assert got.returncode == 0, got.stderr
    cap = json.loads((tmp_path / "connection.json").read_text())["box"]["capacity"]
    rate = th.Throughput(per_hour=cap["per_hour"], goodput_per_hour=cap["goodput_per_hour"],
                         deadline_seconds=cap["deadline_seconds"], arrivals=cap["arrivals"],
                         understated_because=cap["understated_because"],
                         offered=th.Offered(concurrency=cap["offered_concurrency"], seats=cap["seats"],
                                            generator="from the connection file"))
    assert rate.is_lower_bound is True
    assert rate.supports_a_service_level_claim() is True
    assert th.deliverable(100.0, measured=rate)[0] == "deliverable"


def test_a_missing_box_price_is_refused_rather_than_invented(tmp_path):
    """`measure` never ran, so there is no derived price. The driver must stop, not substitute one."""
    got = run_connect(tmp_path, with_measurement=False)
    assert got.returncode == 0, got.stderr
    out = got.stdout
    assert "NOT USABLE YET" in out, "the script wrote an unusable file without saying so"

    mod = read_with_driver(tmp_path / "connection.json")
    with pytest.raises(SystemExit) as e:
        mod.from_connection(str(tmp_path / "connection.json"))
    assert "no derived box price" in str(e.value)


def test_the_metered_price_is_refused_rather_than_defaulted(tmp_path):
    """The two prices are different kinds of fact. The derived one is computed; the published one has to be supplied,
    and a default here would put a guess in the record beside a measurement."""
    got = run_connect(tmp_path, with_measurement=True, api_price=None)
    assert got.returncode == 2, f"expected the script's refusal exit code, got {got.returncode}: {got.stdout}"
    assert "TIERBOOK_API_PRICE_PER_MTOK" in got.stderr
    assert not (tmp_path / "connection.json").exists(), "a refusal must not leave a half-written connection file"


def test_the_metered_arms_capacity_is_null_rather_than_asserted(tmp_path):
    """Nothing measured the metered endpoint, and `null` becomes `unknown` downstream rather than a claim."""
    got = run_connect(tmp_path, with_measurement=True)
    assert got.returncode == 0, got.stderr
    payload = json.loads((tmp_path / "connection.json").read_text())
    assert payload["api"]["capacity"] is None

    from tierbook import throughput as th
    assert th.deliverable(100.0)[0] == "unknown"


def test_the_two_prices_say_where_they_came_from(tmp_path):
    """A number without its provenance gets quoted as the other kind. Both bases are written into the file."""
    got = run_connect(tmp_path, with_measurement=True)
    assert got.returncode == 0, got.stderr
    payload = json.loads((tmp_path / "connection.json").read_text())
    assert "derived" in payload["box"]["price_basis"]
    assert payload["box"]["price_is_upper_bound"] is True, \
        "the throughput behind this price is a lower bound, so the price is an upper bound"
    assert "supplied" in payload["api"]["price_basis"]


def seed_repo(root: Path, content: str) -> Path:
    """A throwaway git repository, so the applier's three branches can be exercised on content this test controls."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "thing.txt").write_text(content)
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
        subprocess.run(["git", *cmd], cwd=root, check=True, capture_output=True)
    return root


def run_patches(tmp_path: Path, patch_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({"TIERBOOK_WORK_DIR": str(tmp_path / "work"),
                "TIERBOOK_CONNECTION_FILE": str(tmp_path / "connection.json"),
                "TIERBOOK_INFRA_CONFIG": str(tmp_path / "absent.env"),
                "TIERBOOK_PATCH_DIR": str(patch_dir)})
    return subprocess.run(["bash", str(SCRIPT), "patches"], capture_output=True, text=True, env=env, cwd=str(ROOT))


def a_patch(patch_dir: Path, *, before: str, after: str) -> None:
    patch_dir.mkdir(parents=True, exist_ok=True)
    body = (
        "A header explaining the gap, which git apply skips.\n---\n"
        "diff --git a/thing.txt b/thing.txt\n"
        "--- a/thing.txt\n+++ b/thing.txt\n"
        f"@@ -1 +1 @@\n-{before}\n+{after}\n")
    (patch_dir / "0001-change-the-thing.patch").write_text(body)


def test_a_patch_that_applies_is_reported_as_applying(tmp_path):
    seed_repo(tmp_path / "work" / "stratoclave", "before\n")
    a_patch(tmp_path / "patches" / "stratoclave", before="before", after="after")
    got = run_patches(tmp_path, tmp_path / "patches")
    assert got.returncode == 0, got.stderr
    assert "applies" in got.stdout and "ALREADY UPSTREAM" not in got.stdout


def test_a_patch_already_in_the_checkout_is_reported_as_upstream(tmp_path):
    """The state that matters most, because it is the one the other projects are about to put these patches into.

    A mechanism that cannot tell "already fixed" from "applies" either re-applies a fix and fails, or keeps carrying a
    patch nobody needs. The detection is `git apply --reverse --check`, which is a real question with a real answer.
    """
    seed_repo(tmp_path / "work" / "stratoclave", "after\n")
    a_patch(tmp_path / "patches" / "stratoclave", before="before", after="after")
    got = run_patches(tmp_path, tmp_path / "patches")
    assert got.returncode == 0, got.stderr
    assert "ALREADY UPSTREAM" in got.stdout
    assert "delete it" in got.stdout, "it should say the patch can go, not just that it is redundant"


def test_a_patch_that_no_longer_matches_is_reported_rather_than_forced(tmp_path):
    """Upstream moved the code the patch is about. Applying part of it would deploy half a fix."""
    seed_repo(tmp_path / "work" / "stratoclave", "something else entirely\n")
    a_patch(tmp_path / "patches" / "stratoclave", before="before", after="after")
    got = run_patches(tmp_path, tmp_path / "patches")
    assert got.returncode == 0, got.stderr
    assert "DOES NOT APPLY" in got.stdout
    assert "regenerate" in got.stdout.lower()


def run_patches_apply(tmp_path: Path, patch_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({"TIERBOOK_WORK_DIR": str(tmp_path / "work"),
                "TIERBOOK_CONNECTION_FILE": str(tmp_path / "connection.json"),
                "TIERBOOK_INFRA_CONFIG": str(tmp_path / "absent.env"),
                "TIERBOOK_PATCH_DIR": str(patch_dir)})
    return subprocess.run(["bash", str(SCRIPT), "patches", "--apply"], capture_output=True, text=True,
                          env=env, cwd=str(ROOT))


def test_applying_a_patch_that_no_longer_matches_refuses_rather_than_continuing(tmp_path):
    """The refusal, exercised rather than read. Reporting is not enough: the path that actually changes a checkout has to
    stop, because applying part of a patch deploys half a fix.

    An earlier version of this test asserted that the word `die` appeared in the applier, and a mutation that turned the
    relevant `die` into a `warn` passed it -- there is another `die` in the same function, and the assertion found that
    one. A test has to sit where the two candidate behaviours differ, which for a refusal means the exit code.
    """
    seed_repo(tmp_path / "work" / "stratoclave", "something else entirely\n")
    a_patch(tmp_path / "patches" / "stratoclave", before="before", after="after")
    got = run_patches_apply(tmp_path, tmp_path / "patches")
    assert got.returncode != 0, f"applying a patch that no longer matches must fail; got {got.returncode}"
    assert "no longer matches" in got.stderr
    assert (tmp_path / "work" / "stratoclave" / "thing.txt").read_text() == "something else entirely\n", \
        "the checkout must be left alone when the patch is refused"


def test_applying_a_patch_that_fits_changes_the_checkout(tmp_path):
    """The other side of the same door: when it applies, the file really changes, so the deploy that follows carries it."""
    repo = seed_repo(tmp_path / "work" / "stratoclave", "before\n")
    a_patch(tmp_path / "patches" / "stratoclave", before="before", after="after")
    got = run_patches_apply(tmp_path, tmp_path / "patches")
    assert got.returncode == 0, got.stderr
    assert (repo / "thing.txt").read_text() == "after\n"


def test_applying_a_patch_already_upstream_is_a_no_op_rather_than_a_failure(tmp_path):
    """The state these patches are about to be in. Re-applying would fail; skipping has to be the behaviour."""
    repo = seed_repo(tmp_path / "work" / "stratoclave", "after\n")
    a_patch(tmp_path / "patches" / "stratoclave", before="before", after="after")
    got = run_patches_apply(tmp_path, tmp_path / "patches")
    assert got.returncode == 0, got.stderr
    assert "already upstream" in got.stdout
    assert (repo / "thing.txt").read_text() == "after\n"


def test_every_shipped_patch_is_a_real_diff_that_says_why_it_exists():
    """Whatever patches ship must be readable by the project they are aimed at, because upstreaming them is the point.

    Zero patches is a valid state and is the current one: both gaps this mechanism was built for are fixed upstream, and
    the pinned commits name the fixes. What is NOT valid is a patch directory that exists and is empty -- that is
    scaffolding somebody left behind, and it makes `patches` report on a repository it carries nothing for.
    """
    root = ROOT / "infra" / "patches"
    dirs = [d for d in root.iterdir() if d.is_dir()] if root.exists() else []
    for d in dirs:
        patches = sorted(d.glob("*.patch"))
        assert patches, f"{d.name}/ exists with no patches in it; delete the directory too"
        for p in patches:
            text = p.read_text()
            assert "diff --git" in text, f"{p.name} is not a diff"
            assert "---\n" in text.split("diff --git")[0], f"{p.name} has no header separated from its diff"
            head = text.split("diff --git")[0]
            for needed in ("THE GAP", "OBSERVED", "THE FIX", "Delete this patch once it is upstream"):
                assert needed in head, f"{p.name} does not say {needed!r}"


# --- the pin, which is what replaces the patches now that both fixes are upstream ------------------------------------

def pinned_refs() -> dict:
    """The two commit ids the script defaults to, read out of the script rather than duplicated here."""
    body = SCRIPT.read_text()
    out = {}
    for name, var in (("gateway", "TIERBOOK_GATEWAY_REF"), ("cluster", "TIERBOOK_CLUSTER_REF")):
        line = next(l for l in body.splitlines() if l.startswith(f"{name.upper()}_REF="))
        assert var in line, f"{name} pin does not read {var}"
        out[name] = line.split(":-", 1)[1].rstrip('"}')
    return out


def test_both_sides_are_pinned_to_a_full_commit_id():
    """Neither repository cuts versions, so a commit is the only thing that names a state of them.

    Full 40 characters, not abbreviated: fetching a single commit needs the complete id -- an abbreviated one is refused
    by the server, and the failure arrives at deploy time rather than here.
    """
    for name, ref in pinned_refs().items():
        assert len(ref) == 40, f"the {name} pin is {len(ref)} characters; fetching one commit needs the full 40"
        assert all(c in "0123456789abcdef" for c in ref), f"the {name} pin is not a hex commit id: {ref!r}"


def run_checkout_pinned(tmp_path: Path, repo: str, ref: str) -> subprocess.CompletedProcess:
    """Run the script's own `checkout_pinned` against a repository, with the smallest possible harness around it.

    The function is sourced out of the real script rather than reimplemented, so what is under test is what ships. The
    remote is a local bare repository, so this needs no network and no credentials.
    """
    harness = tmp_path / "harness.sh"
    harness.write_text(
        'set -uo pipefail\n'
        'info() { printf "[i] %s\\n" "$1"; }\n'
        'warn() { printf "[w] %s\\n" "$1"; }\n'
        'die() { printf "[die] %s\\n" "$1" >&2; exit 1; }\n'
        'state_set() { :; }\n'
        f'. <(sed -n "/^checkout_pinned() {{/,/^}}/p" "{SCRIPT}")\n'
        f'checkout_pinned "{tmp_path}/co" "{repo}" "{ref}" cluster\n')
    return subprocess.run(["bash", str(harness)], capture_output=True, text=True, cwd=str(ROOT))


def a_bare_remote(tmp_path: Path) -> tuple[str, str]:
    """A local bare repository with two commits, returning its path and the first commit's id."""
    src = tmp_path / "src"; src.mkdir()
    def git(*a, cwd=src):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True,
                       capture_output=True)
    git("init", "-q", "-b", "main")
    (src / "a.txt").write_text("one\n"); git("add", "."); git("commit", "-qm", "one")
    first = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True).stdout.strip()
    (src / "a.txt").write_text("two\n"); git("add", "."); git("commit", "-qm", "two")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(bare)], check=True, capture_output=True)
    return str(bare), first


def test_the_checkout_lands_on_the_pinned_commit_and_not_on_the_branch_tip(tmp_path):
    """The pin has to win over the branch. Asking for the first of two commits must not produce the second."""
    repo, first = a_bare_remote(tmp_path)
    got = run_checkout_pinned(tmp_path, repo, first)
    assert got.returncode == 0, got.stderr
    at = subprocess.run(["git", "-C", str(tmp_path / "co"), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip()
    assert at == first, f"the checkout is at {at}, not at the pinned {first}"
    assert (tmp_path / "co" / "a.txt").read_text() == "one\n", "the working tree is not the pinned commit's"


def test_an_existing_checkout_is_moved_onto_the_pin(tmp_path):
    """A stale tree that happens to be sitting there is the quiet form of deploying unpinned code."""
    repo, first = a_bare_remote(tmp_path)
    assert run_checkout_pinned(tmp_path, repo, first).returncode == 0
    # Move it off the pin, the way a previous run with a different pin would have left it.
    subprocess.run(["git", "-C", str(tmp_path / "co"), "fetch", "-q", "origin", "main"], check=True)
    subprocess.run(["git", "-C", str(tmp_path / "co"), "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
    assert (tmp_path / "co" / "a.txt").read_text() == "two\n"
    # And a second run must put it back.
    assert run_checkout_pinned(tmp_path, repo, first).returncode == 0
    assert (tmp_path / "co" / "a.txt").read_text() == "one\n", "the existing checkout was left off the pin"


def test_an_unfetchable_pin_fails_instead_of_falling_back_to_a_branch(tmp_path):
    """The refusal, exercised rather than read.

    An earlier version of this test asserted that the words `die` and `FULL 40 character id` appeared in the function,
    and a mutation that replaced the refusal with a fallback to `main` passed it -- the function has another `die` and
    the phrase survived in the fallback's message. A refusal has to be checked by its exit code and by what it did NOT
    leave behind.
    """
    repo, _ = a_bare_remote(tmp_path)
    got = run_checkout_pinned(tmp_path, repo, "0" * 40)
    assert got.returncode != 0, f"an unfetchable pin was tolerated: {got.stdout}"
    assert "could not fetch" in got.stderr
    # Nothing must be checked out: falling back to a branch would leave a usable tree at the wrong commit.
    out = subprocess.run(["git", "-C", str(tmp_path / "co"), "rev-parse", "HEAD"], capture_output=True, text=True)
    assert out.returncode != 0, f"a tree was left at {out.stdout.strip()} after the pin could not be fetched"


def test_the_pinned_fetch_asks_for_one_commit(tmp_path):
    """Depth one, because the history of another project is not something this needs a copy of."""
    body = SCRIPT.read_text()
    fn = body[body.index("checkout_pinned() {"):body.index("gateway_checkout() {")]
    assert "--depth 1 origin" in fn
    assert "clean -qfd" in fn, "a reused checkout is not cleaned, so a stale untracked file survives the pin"


def test_the_connection_file_records_which_commit_produced_it(tmp_path):
    """A measurement whose subject cannot be named again is a measurement nobody can repeat."""
    got = run_connect(tmp_path, with_measurement=True)
    assert got.returncode == 0, got.stderr
    payload = json.loads((tmp_path / "connection.json").read_text())
    assert "sources" in payload
    for side in ("gateway", "cluster"):
        entry = payload["sources"][side]
        assert entry["repo"]
        # `requested` is the pin and is always present; `at` is null here because this run checked nothing out.
        assert entry["requested"] and len(entry["requested"]) == 40
        assert entry["at"] is None
    assert "not checked out by this script" in got.stdout


def test_a_pin_that_resolved_elsewhere_is_reported(tmp_path):
    """The two fields differ exactly when something went wrong, so the difference has to be said out loud."""
    work = tmp_path / "work"; work.mkdir()
    (work / "state.json").write_text(json.dumps({"gateway_commit": "0" * 40, "cluster_commit": "0" * 40}))
    (work / "probe.json").write_text(json.dumps({
        "per_hour": 1.0, "arrivals": "open_loop", "deadline_seconds": 8.0, "goodput_per_hour": 1.0,
        "understated_because": "", "offered": {"concurrency": 1, "seats": 1, "generator": "x"},
        "observed": {"wall_seconds": 1.0, "output_tokens": 1, "completed": 1}}))
    (work / "box-price.json").write_text(json.dumps({"usd_per_output_mtok": 1.0, "price_is_upper_bound": False}))
    (work / "api-key.txt").write_text("k")
    env = dict(os.environ)
    env.update({"TIERBOOK_WORK_DIR": str(work), "TIERBOOK_CONNECTION_FILE": str(tmp_path / "c.json"),
                "TIERBOOK_INFRA_CONFIG": str(tmp_path / "absent.env"),
                "TIERBOOK_API_PRICE_PER_MTOK": "5.0", "TIERBOOK_API_MODEL": "m",
                "TIERBOOK_GATEWAY_PREFIX": "", "TIERBOOK_CLUSTER_NAME": "", "AWS_PROFILE": ""})
    got = subprocess.run(["bash", str(SCRIPT), "connect"], capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert got.returncode == 0, got.stderr
    assert "WARNING" in got.stdout and "pin asked for" in got.stdout


def test_nothing_operates_on_another_projects_live_resources():
    """The whole point of moving to patches: the compensation is a diff, not surgery on a deployed object.

    Live surgery cannot be sent upstream, drifts silently against a resource whose shape moved, and cannot answer "is
    this fixed yet". Each of these strings is one of the operations the first version performed.
    """
    body = SCRIPT.read_text()
    for smell, what in (("register_task_definition", "rewriting another project's task definition"),
                        ("patch deployment", "patching another project's Deployment in place")):
        assert smell not in body, f"the script still does {what}; that belongs in infra/patches as a diff"


def test_down_destroys_nothing_when_it_has_no_record_of_creating_anything(tmp_path):
    """The invariant that matters most, checked in the state where it is easiest to get wrong: no state file at all.

    A teardown whose default is "destroy" deletes somebody's gateway the first time the state file goes missing. The
    default here is the safe direction, and this asserts it by running `down` with an empty work directory -- which also
    covers the case of a state file written by an older version of the script that did not have these keys.
    """
    work = tmp_path / "work"
    work.mkdir()
    env = dict(os.environ)
    env.update({"TIERBOOK_WORK_DIR": str(work),
                "TIERBOOK_CONNECTION_FILE": str(tmp_path / "connection.json"),
                "TIERBOOK_INFRA_CONFIG": str(tmp_path / "absent.env"),
                "TIERBOOK_GATEWAY_PREFIX": "some-prefix", "TIERBOOK_CLUSTER_NAME": "some-cluster"})
    got = subprocess.run(["bash", str(SCRIPT), "down"], capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert got.returncode == 0, got.stderr
    assert "nothing to destroy" in got.stdout
    # And it must not have reached for either destroyer.
    assert "terraform" not in got.stdout.lower()
    assert "cdk destroy" not in got.stdout


def test_down_names_which_side_it_owns_before_acting(tmp_path):
    """A teardown that does not say what it is about to destroy cannot be stopped in time."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "state.json").write_text(json.dumps({"gateway_owned": False, "cluster_owned": False}))
    env = dict(os.environ)
    env.update({"TIERBOOK_WORK_DIR": str(work),
                "TIERBOOK_CONNECTION_FILE": str(tmp_path / "connection.json"),
                "TIERBOOK_INFRA_CONFIG": str(tmp_path / "absent.env")})
    got = subprocess.run(["bash", str(SCRIPT), "down"], capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert got.returncode == 0, got.stderr
    assert "gateway created by us: false" in got.stdout
    assert "cluster created by us: false" in got.stdout


def test_a_side_marked_as_ours_actually_reaches_the_destroy(tmp_path):
    """The other half of the teardown invariant, and the one a defect hid in.

    `state_get` used to print Python's `True` while the shell compared against the literal `true`, so a resource this
    script had created was reported as ours and then silently skipped -- a cluster left billing with the teardown
    reporting success. This asserts the owned path is actually entered, by watching it fail on the missing working
    directory rather than quietly declaring there was nothing to do.
    """
    work = tmp_path / "work"
    work.mkdir()
    (work / "state.json").write_text(json.dumps({"cluster_owned": True, "gateway_owned": False,
                                                 "cluster_dir": str(tmp_path / "gone")}))
    env = dict(os.environ)
    env.update({"TIERBOOK_WORK_DIR": str(work),
                "TIERBOOK_CONNECTION_FILE": str(tmp_path / "connection.json"),
                "TIERBOOK_INFRA_CONFIG": str(tmp_path / "absent.env")})
    got = subprocess.run(["bash", str(SCRIPT), "down"], capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert "cluster created by us: true" in got.stdout
    assert "nothing to destroy" not in got.stdout, "a resource marked as ours was skipped"
    assert got.returncode != 0, "a teardown that cannot find its working directory must fail loudly"
    assert "destroy it by hand" in got.stderr
