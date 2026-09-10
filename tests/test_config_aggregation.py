"""C8 (amendment 8) -- `load_config` collects every problem across every family and raises once.

Before C8, `load_config` raises on the first problem it meets and stops. The journey author took the real
candidate file this project shipped at its own `v0.1.0` tag and fixed exactly what each error named, nothing
more: it took six loads (`config_format`, the first family's shape, that family's four missing keys, the
second family's shape, that family's four missing keys, then success). Every one of those five problems is
knowable on the first read; a correct implementation of five individually-correct refusals is still a hostile
journey. C8 aggregates all of them into one `ConfigError`, each individual refusal keeping the wording it has
today (that wording explains what changed and why -- the part an operator needs), and the round trip against
the real file drops from six loads to two: read one message, fix everything it names, load again.

Only C8 is in scope here. C1-C7 and C5's pooling rule are tested in their own files; this file does not
re-test any individual refusal's correctness, only whether `load_config` aggregates them.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.config import CONFIG_FORMAT, ConfigError, load_config  # noqa: E402

# --- shared fixture builders ------------------------------------------------------------------------


def _candidate(ref: str) -> dict:
    """One minimal, otherwise-always-valid api candidate, so a test's only defect is the one it introduces."""
    return {
        "deployment": "api",
        "endpoint": {"base_url": f"https://x.invalid/{ref}/v1", "model": ref},
        "price_per_mtok": {"fresh_in": 1.0, "cached_in": 0.1, "out": 5.0},
    }


def _full_family(reference: str, floor: float = 0.8) -> dict:
    """A family declaration with every C2/C3/C4 key present and valid -- the shape `load_config` accepts."""
    return {
        "reference": reference,
        "floor": floor,
        "label_source": "human_label",
        "max_label_latency_s": 3600.0,
        "label_independent_of_candidate": True,
        "staleness_limit_days": 14.0,
    }


def _write(tmp_path: Path, body: dict) -> Path:
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps(body))
    return p


def _v010_candidates_raw() -> dict:
    """The real candidate file this project shipped at its own `v0.1.0` tag -- two families, both using the
    config_format-1 bare-string shape. Read from git rather than typed by hand, because a one-family
    reduction typed for this test would not exercise cross-family aggregation, which is the point of C8.
    """
    text = subprocess.check_output(["git", "show", "v0.1.0:examples/ledger/candidates.json"], cwd=ROOT, text=True)
    return json.loads(text)


# --- the honest fixer: derives a fix from a message substring, nothing more -----------------------

#: Defaults used only when a message names a key and gives no concrete value for it (the bare-string
#: message says "change it to {reference, floor}" but does not supply a floor number; the missing-keys
#: message names label_source etc. by key, not by value). This mapping is this test's model of what an
#: operator reading the message would type in -- not derived from the message, because the message does not
#: contain it. It must never supply a value for a key the message did NOT name.
_FAMILY_KEY_DEFAULTS = {
    "floor": 0.8,
    "label_source": "human_label",
    "max_label_latency_s": 3600.0,
    "label_independent_of_candidate": True,
    "staleness_limit_days": 14.0,
}

_RE_CONFIG_FORMAT = re.compile(r"config_format must be (\d+)")
_RE_BARE_STRING = re.compile(r"family '([^']+)' names its reference candidate as a bare string, '([^']+)'")
_RE_MISSING_KEYS = re.compile(r"family '([^']+)' is missing \[([^\]]*)\]")


def _apply_fixes_named_in_message(raw: dict, message: str) -> int:
    """Mutate `raw` to fix exactly and only the problems named in `message`, deriving each fix from the
    message text itself rather than from foreknowledge of the target shape. Returns how many distinct
    problems it recognised and fixed, so a caller can tell a fixer that did nothing from one that converged.

    Three problem shapes are recognised, each straight off an existing `ConfigError` string:
    `config_format must be N` (set config_format to N); a family reported as a bare string, whose message
    literally spells out the replacement shape `{"reference": ..., "floor": ...}` (only the number is not
    given, so one is supplied from `_FAMILY_KEY_DEFAULTS`); and a family reported as missing named keys
    (each named key gets its default value, and nothing not named is touched). If a message names a fourth
    kind of problem, this fixer does not recognise it and applies nothing for it -- which is deliberate: a
    fixer that "helpfully" repaired an unnamed problem would hide exactly the defect this file exists to
    catch, an aggregation that lists fewer problems than a second load would reveal.
    """
    applied = 0

    m = _RE_CONFIG_FORMAT.search(message)
    if m:
        raw["config_format"] = int(m.group(1))
        applied += 1

    for fam, ref in _RE_BARE_STRING.findall(message):
        raw["families"][fam] = {"reference": ref, "floor": _FAMILY_KEY_DEFAULTS["floor"]}
        applied += 1

    for fam, keys_blob in _RE_MISSING_KEYS.findall(message):
        keys = re.findall(r"'([^']+)'", keys_blob)
        decl = raw["families"].get(fam)
        assert isinstance(decl, dict), (
            f"message named family {fam!r} as missing keys {keys}, but this fixer has not yet turned "
            f"{fam!r} into an object -- either the message named a family this fixer never saw a shape "
            "message for, or fix ordering within one message matters and this fixer's is wrong"
        )
        for key in keys:
            assert key in _FAMILY_KEY_DEFAULTS, f"missing-keys message names {key!r}, no default is on file for it"
            decl[key] = _FAMILY_KEY_DEFAULTS[key]
        applied += 1

    return applied


# --- the centre: the round trip is measured, not assumed --------------------------------------------


def test_round_trip_against_real_v0_1_0_file_is_two_loads():
    """Catches an aggregation that is incomplete: one that collects some problems but not all of them, so
    fixing everything a message names still leaves a later message with something new. The loop below is the
    operator described in C8's own text -- load, fix only what the message names, load again -- run against
    the actual file this project shipped at `v0.1.0`, and the load count is asserted at exactly 2, not derived
    from counting the five known problems, because a message that lists five things is not the same claim as
    a message that lists all five things the *next* load would otherwise raise.
    """
    raw = _v010_candidates_raw()
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "candidates.json"
        loads = 0
        last_message = ""
        while loads < 10:
            loads += 1
            p.write_text(json.dumps(raw))
            try:
                load_config(p)
                break
            except ConfigError as e:
                last_message = str(e)
                applied = _apply_fixes_named_in_message(raw, last_message)
                assert applied > 0, (
                    f"load {loads} raised but named no problem this fixer recognises: {last_message}"
                )
        else:
            pytest.fail(f"did not converge within 10 loads; last message was: {last_message}")

    assert loads == 2, (
        f"C8's own stop condition is a two-load round trip against the real v0.1.0 file; measured {loads} "
        f"loads. Last message before success: {last_message!r}"
    )


# --- every one of the five problems is named, individually, in the one raised message ----------------


def test_all_five_v010_problems_are_named_in_the_single_message():
    """Catches an aggregation that drops one of the five known problems -- each assertion is a distinct
    substring lifted verbatim from today's individual refusal messages (not a count), so a message that
    aggregates four of the five problems fails this test and says which one is missing. This also pins that
    each refusal keeps its current wording: an aggregation that summarised these into a terse list would lose
    the explanation of what changed and why, which is exactly the amendment 8 text this entry answers.
    """
    raw = _v010_candidates_raw()
    with tempfile.TemporaryDirectory() as d:
        p = _write(Path(d), raw)
        with pytest.raises(ConfigError) as exc_info:
            load_config(p)
    message = str(exc_info.value)

    assert f"config_format must be {CONFIG_FORMAT}, found 1" in message
    assert "family 'agentic-coding' names its reference candidate as a bare string" in message
    assert "family 'agentic-coding' is missing" in message
    assert "family 'tool-agent-user-retail' names its reference candidate as a bare string" in message
    assert "family 'tool-agent-user-retail' is missing" in message


# --- two independent problems in two different families, aggregated -- the case that is not ambiguous ---


def test_independent_problems_in_two_different_families_are_collected_together():
    """Catches an implementation that aggregates within one family but stops at the first family -- passing
    this alone is not enough (a single-family test cannot see that defect), which is why this fixture puts an
    unrelated, self-contained problem in each of two families rather than two problems in one. Both are
    detectable without any cascading: a bare string is a shape defect regardless of what it would contain
    once reshaped, and a dict missing required keys is a defect regardless of whether some other family is
    also broken. `config_format` is deliberately correct here so this test says nothing about the config_format
    ambiguity below.
    """
    body = {
        "config_format": CONFIG_FORMAT,
        "candidates": {"ref-a": _candidate("ref-a"), "ref-b": _candidate("ref-b")},
        "families": {
            "family-one": "ref-a",  # config_format-1 bare-string shape: a self-contained shape defect
            "family-two": {"reference": "ref-b", "floor": 0.8},  # a dict missing the four C4/C3 keys
        },
        "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.15}}},
    }
    with tempfile.TemporaryDirectory() as d:
        p = _write(Path(d), body)
        with pytest.raises(ConfigError) as exc_info:
            load_config(p)
    message = str(exc_info.value)

    assert "family 'family-one' names its reference candidate as a bare string" in message
    assert "family 'family-two' is missing" in message


# --- the config_format boundary: defensible only, the rest is reported as an open question -----------


def test_a_config_format_mismatch_is_named_when_present():
    """Catches a config_format refusal that goes missing entirely once C8 lands (e.g. dropped while wiring
    the aggregator). Deliberately asserts only what is certain -- that the config_format problem is named --
    and asserts nothing about whether family-level problems are also collected alongside it in this message:
    whether validating families against an unestablished config_format is itself a problem worth collecting,
    or noise to suppress until the format is fixed, is a question the contract leaves to the implementer (see
    this file's docstring in the test report). A test asserting either answer here would be asserting a
    behaviour C8's text does not settle.
    """
    body = {
        "config_format": 1,
        "candidates": {"ref": _candidate("ref")},
        "families": {"f": _full_family("ref")},
        "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.15}}},
    }
    with tempfile.TemporaryDirectory() as d:
        p = _write(Path(d), body)
        with pytest.raises(ConfigError) as exc_info:
            load_config(p)
    message = str(exc_info.value)

    assert f"config_format must be {CONFIG_FORMAT}, found 1" in message


# --- the two negative cases: aggregation must not invent a new failure mode ---------------------------


def test_a_single_problem_produces_a_message_about_only_that_problem():
    """Catches an aggregator that always frames its output as a list, even for one item, in a way that reads
    like something is missing (e.g. always naming a count, or wrapping a lone message in enumeration
    artefacts) or that pads a one-problem message with unrelated content. With exactly one defect introduced
    (a single family's bare-string shape, everything else valid) the message names that family's problem and
    names none of the others this file knows the wording for.
    """
    body = {
        "config_format": CONFIG_FORMAT,
        "candidates": {"ref": _candidate("ref")},
        "families": {"only-family": "ref"},
        "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.15}}},
    }
    with tempfile.TemporaryDirectory() as d:
        p = _write(Path(d), body)
        with pytest.raises(ConfigError) as exc_info:
            load_config(p)
    message = str(exc_info.value)

    assert "family 'only-family' names its reference candidate as a bare string" in message
    assert "config_format must be" not in message
    assert "is missing" not in message


def test_a_valid_file_still_loads_with_no_error():
    """Catches an aggregator that turns a valid file into a false positive -- e.g. a collection pass that
    accumulates warnings and raises even when the list ends up empty, or a refactor that changed a check's
    condition while moving it into the collector. Two families, both fully specified and referencing real
    candidates, must load without raising anything.
    """
    body = {
        "config_format": CONFIG_FORMAT,
        "candidates": {"ref-a": _candidate("ref-a"), "ref-b": _candidate("ref-b")},
        "families": {
            "family-one": _full_family("ref-a", floor=0.8),
            "family-two": _full_family("ref-b", floor=0.9),
        },
        "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.15}}},
    }
    with tempfile.TemporaryDirectory() as d:
        p = _write(Path(d), body)
        cfg = load_config(p)

    assert set(cfg.families) == {"family-one", "family-two"}
    assert cfg.families["family-one"].floor == 0.8
    assert cfg.families["family-two"].floor == 0.9
