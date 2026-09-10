"""C4 -- the family declares its labeller, and no labeller means no exploration rate.

Amendment 4 replaced C4's original interface section: `label_source`, `max_label_latency_s` and
`label_independent_of_candidate` live on the per-family declaration in `candidates.json`
(`config.FamilyDeclaration`, the object C2 created for the floor), not on the tier record's `families` block, and
`load_config` is the verb that refuses a bad declaration -- not `validate`, which never opens the config. The enum
for `label_source` is `oracle.kind`'s seven values (from `src/tierbook/schema.json`) plus `none`, read from the
schema file rather than copied by hand, so the config-side vocabulary and the record-side vocabulary cannot drift
apart. `record.classify_label` is unchanged from the section amendment 4 replaced.

Only C4 is in scope here. Nothing about `schema_version`, `from_row`, the floor itself, exploration's draw, or
pooling across versions is tested in this file -- those belong to C1, C2, C3 and C5's own test files.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tierbook  # noqa: E402
from tierbook import record as rec  # noqa: E402
from tierbook.config import ConfigError, load_config  # noqa: E402

V010_FIXTURE = ROOT / "docs" / "verify" / "v0.1.0-decisions.jsonl"
SCHEMA_PATH = ROOT / "src" / "tierbook" / "schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

#: Read from the schema file, not copied by hand -- the whole point of A4.3/A4.4 is that the config-side
#: vocabulary and this one must not drift apart. If this line ever needs to become a hardcoded tuple to make a
#: test pass, that test is testing the wrong thing.
ORACLE_KIND_ENUM = tuple(SCHEMA["properties"]["oracle"]["properties"]["kind"]["enum"])


# --- fixtures: a minimal, otherwise well-formed candidate file ------------------------------------


_SENTINEL = object()


def _family_c4(*, reference="ref", floor=0.5, label_source="human_label",
               max_label_latency_s=_SENTINEL, label_independent_of_candidate=True,
               exploration_rate=None) -> dict:
    """One family's declaration, C2's shape plus C4's three fields, all otherwise well-formed.

    `max_label_latency_s` defaults to `None` when `label_source` is `"none"` and to a plain number otherwise, so a
    caller exercising one C4 field does not accidentally trip the label_source/max_label_latency_s consistency
    refusal at the same time -- the fixture-isolation rule amendment 3 states as a general obligation.
    """
    if max_label_latency_s is _SENTINEL:
        max_label_latency_s = None if label_source == "none" else 3600.0
    d = {
        "reference": reference, "floor": floor,
        "label_source": label_source,
        "max_label_latency_s": max_label_latency_s,
        "label_independent_of_candidate": label_independent_of_candidate,
    }
    if exploration_rate is not None:
        d["exploration_rate"] = exploration_rate
    return d


def _candidates(*, families: dict) -> dict:
    """The smallest candidate file `load_config` will look at, `config_format: 2`, one loadable reference
    candidate, and whatever `families` mapping the caller supplies. Kept apart from the example ledger on purpose,
    the same reasoning C2's test file gives: tying a C4 refusal to the bigger fixture would make a failure harder
    to read than it needs to be."""
    return {
        "config_format": 2,
        "candidates": {
            "ref": {"deployment": "api",
                    "endpoint": {"base_url": "https://x/v1", "model": "m"},
                    "price_per_mtok": {"fresh_in": 1.0, "cached_in": 0.1, "out": 5.0}},
        },
        "families": families,
        "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.15}}},
    }


def _write(tmp_path, body: dict) -> Path:
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps(body))
    return p


def _load(tmp_path, family: dict):
    return load_config(_write(tmp_path, _candidates(families={"f": family})))


def _schema_copy_with_oracle_kind(tmp_path, *, add=(), remove=()) -> Path:
    """A full copy of the real schema, with `oracle.kind`'s enum list edited -- used only to prove the loader
    reads the enum from the schema file at call time rather than from a hardcoded copy of it. Everything else in
    the schema is left untouched, so nothing outside the enum check is affected by the patch."""
    schema = copy.deepcopy(SCHEMA)
    enum = list(schema["properties"]["oracle"]["properties"]["kind"]["enum"])
    for v in add:
        if v not in enum:
            enum.append(v)
    for v in remove:
        if v in enum:
            enum.remove(v)
    schema["properties"]["oracle"]["properties"]["kind"]["enum"] = enum
    p = tmp_path / "patched-schema.json"
    p.write_text(json.dumps(schema))
    return p


# --- A4.2: load_config is the verb, and it refuses an omission naming the family and the field ------


def test_a_family_omitting_label_source_is_refused_naming_the_family_and_the_field(tmp_path):
    """A4.2/A4.1: catches the omission being read as absent-and-fine, or being caught by `validate` instead of
    `load_config` -- the contract moved the refusal to whichever command loads the config, because `validate`
    (`cmd_validate`) reads the tier registry and never opens the candidate file at all."""
    fam = _family_c4()
    del fam["label_source"]
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, fam)
    msg = str(excinfo.value)
    assert "f" in msg and "label_source" in msg


def test_a_family_omitting_max_label_latency_s_is_refused_naming_the_family_and_the_field(tmp_path):
    """Same clause, the second of the three added fields: an omission here must be a load failure naming the
    field, not a default of `None` invented by the loader on the family's behalf."""
    fam = _family_c4()
    del fam["max_label_latency_s"]
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, fam)
    msg = str(excinfo.value)
    assert "f" in msg and "max_label_latency_s" in msg


def test_a_family_omitting_label_independent_of_candidate_is_refused_naming_the_family_and_the_field(tmp_path):
    """The third added field. The contract says it 'has no default', so an omission must be a hard refusal, not a
    loader that assumes `True` (the family is safe) or `False` (the family loses exploration) on its own -- either
    default would be a value nobody declared, standing in for one that was never a syntax."""
    fam = _family_c4()
    del fam["label_independent_of_candidate"]
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, fam)
    msg = str(excinfo.value)
    assert "f" in msg and "label_independent_of_candidate" in msg


def test_a_family_carrying_all_three_c4_fields_loads_and_the_declared_values_round_trip(tmp_path):
    """The positive case the three refusals above need for contrast: a family that supplies everything must load,
    and the values it declared must be readable back off the `Config` object exactly -- not merely 'did not
    raise'. Without this, a loader that refused every family unconditionally would still pass the omission tests."""
    fam = _family_c4(label_source="deterministic_metric", max_label_latency_s=1800.0,
                     label_independent_of_candidate=True)
    cfg = _load(tmp_path, fam)
    decl = cfg.families["f"]
    assert decl.label_source == "deterministic_metric"
    assert decl.max_label_latency_s == 1800.0
    assert decl.label_independent_of_candidate is True


def test_label_independent_of_candidate_false_is_a_legitimate_declaration_and_loads(tmp_path):
    """The contract's own words: 'false is a legitimate declaration.' Catches an implementation that treats
    `False` as itself a refusal-worthy value (e.g. mistaking 'not independent' for 'malformed') instead of a
    normal fact about an operator's judge that is also a candidate in the family."""
    fam = _family_c4(label_source="human_label", label_independent_of_candidate=False)
    cfg = _load(tmp_path, fam)
    assert cfg.families["f"].label_independent_of_candidate is False


# --- max_label_latency_s / label_source consistency, each direction in isolation --------------------


def test_label_source_none_loads_with_max_label_latency_s_null(tmp_path):
    """The one legal pairing for `label_source: none`. Needed as a baseline: without it, the two refusal tests
    below would not tell you whether the loader ever accepts `none` at all versus rejecting it outright."""
    fam = _family_c4(label_source="none", max_label_latency_s=None)
    cfg = _load(tmp_path, fam)
    assert cfg.families["f"].label_source == "none"
    assert cfg.families["f"].max_label_latency_s is None


def test_a_number_paired_with_label_source_none_is_refused_naming_both(tmp_path):
    """Catches a loader that only checks 'is max_label_latency_s a number-or-null' in isolation, without cross-
    checking it against `label_source` -- `null` is required EXACTLY when the source is `none`, so a number here
    is the specific contradiction the contract calls out, not a generic type error."""
    fam = _family_c4(label_source="none", max_label_latency_s=60.0)
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, fam)
    msg = str(excinfo.value)
    assert "max_label_latency_s" in msg and "label_source" in msg


def test_null_paired_with_a_non_none_label_source_is_refused_naming_both(tmp_path):
    """The mirror case: a declared labeller with no maximum latency to wait for it. Catches a loader that treats
    `null` as always acceptable (e.g. 'unbounded wait') instead of refusing it for every `label_source` except
    `none`, which is the direction the contract states explicitly."""
    fam = _family_c4(label_source="human_label", max_label_latency_s=None)
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, fam)
    msg = str(excinfo.value)
    assert "max_label_latency_s" in msg and "label_source" in msg


# --- A4.3: label_source's enum is oracle.kind's seven values, plus none -----------------------------


def test_every_oracle_kind_value_and_none_is_accepted_as_label_source(tmp_path):
    """Catches a loader that re-derives its own, narrower vocabulary for `label_source` instead of taking
    `oracle.kind`'s enum wholesale plus `none` -- driven from the schema file at test time (`ORACLE_KIND_ENUM`),
    not from a list typed into this test, so a value added to the schema later cannot silently leave this test
    (or the loader it exercises) behind."""
    for value in ORACLE_KIND_ENUM + ("none",):
        cfg = _load(tmp_path, _family_c4(label_source=value))
        assert cfg.families["f"].label_source == value


def test_a_label_source_outside_the_enum_and_not_none_is_refused(tmp_path):
    """Catches a loader that accepts an arbitrary string for `label_source`, which would let the config-side
    vocabulary silently diverge from `oracle.kind`'s -- exactly the second vocabulary A4.3 says this amendment
    exists to prevent."""
    assert "an_invented_kind" not in ORACLE_KIND_ENUM
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, _family_c4(label_source="an_invented_kind", max_label_latency_s=3600.0))
    assert "an_invented_kind" in str(excinfo.value)


def test_label_source_enum_is_read_from_the_schema_file_a_value_the_schema_adds_is_accepted(tmp_path, monkeypatch):
    """The test that would FAIL against a hardcoded copy of the seven values, in the direction a hardcoded copy
    gets wrong by being too narrow: `SCHEMA_PATH` is patched to a schema whose `oracle.kind` enum has an EIGHTH
    value that does not exist in the real schema or in any plausible hand-typed list. A loader that reads the
    enum from the schema file at call time accepts it; a loader carrying its own copy of 'the seven values'
    cannot, because that value was never in anyone's hardcoded list."""
    patched = _schema_copy_with_oracle_kind(tmp_path, add=("a_schema_only_addition",))
    monkeypatch.setattr(tierbook, "SCHEMA_PATH", patched)
    cfg = _load(tmp_path, _family_c4(label_source="a_schema_only_addition", max_label_latency_s=3600.0))
    assert cfg.families["f"].label_source == "a_schema_only_addition"


def test_label_source_enum_is_read_from_the_schema_file_a_value_the_schema_removes_is_refused(tmp_path, monkeypatch):
    """The mirror direction, and the sharper of the two: `SCHEMA_PATH` is patched to a schema with `human_label`
    REMOVED from `oracle.kind`'s enum. A loader that reads the enum from the schema file at call time now refuses
    `human_label`; a loader carrying a hardcoded copy of the (real, unpatched) seven values keeps accepting it
    regardless of what the schema file says, which is exactly the drift A4.3 exists to make impossible -- a
    hardcoded copy passes the 'add a value' test above by accident if it is unusually permissive, but it cannot
    pass this one, because passing this one requires actually consulting the file every time."""
    assert "human_label" in ORACLE_KIND_ENUM
    patched = _schema_copy_with_oracle_kind(tmp_path, remove=("human_label",))
    monkeypatch.setattr(tierbook, "SCHEMA_PATH", patched)
    with pytest.raises(ConfigError):
        _load(tmp_path, _family_c4(label_source="human_label", max_label_latency_s=3600.0))


# --- A4.4: exploration_rate needs BOTH a real labeller AND label independence, checked separately ----


@pytest.mark.parametrize("label_source,independent", [
    ("none", True),          # only the labeller condition fails
    ("none", False),         # both conditions fail
    ("human_label", False),  # only the independence condition fails
])
def test_exploration_rate_is_refused_naming_the_rate_and_the_reason(tmp_path, label_source, independent):
    """A4.4: three of the four (label_source, label_independent_of_candidate) combinations must refuse a family
    that also carries `exploration_rate`. All three are exercised, not just one, because a loader that checks only
    `label_source != "none"` and ignores `label_independent_of_candidate` (or the reverse) would still pass a test
    that tried only one of them -- this is the exact gap amendment 4 raises against the coarser three-value
    vocabulary the original section proposed."""
    fam = _family_c4(label_source=label_source, label_independent_of_candidate=independent, exploration_rate=0.05)
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, fam)
    msg = str(excinfo.value)
    assert "exploration_rate" in msg


def test_exploration_rate_loads_when_the_labeller_is_real_and_independent(tmp_path):
    """The fourth combination, and the one that must NOT refuse: a real labeller (`label_source != "none"`) that
    is independent of every candidate in the family. Needed for the same reason the C2 test file gives for its own
    positive case -- a loader that refused every family carrying `exploration_rate` unconditionally would still
    pass all three refusal tests above."""
    fam = _family_c4(label_source="human_label", label_independent_of_candidate=True, exploration_rate=0.05)
    cfg = _load(tmp_path, fam)
    assert cfg.families["f"].label_source == "human_label"


@pytest.mark.parametrize("label_source,independent", [
    ("none", True), ("none", False), ("human_label", False), ("human_label", True),
])
def test_a_family_with_no_exploration_rate_loads_under_every_labeller_combination(tmp_path, label_source, independent):
    """The complement of the four cases above, with `exploration_rate` absent entirely rather than present and
    refused. Catches a loader that conflates 'this family CANNOT have a rate' with 'this family is otherwise
    invalid' -- a family with no declared rate at all must load under all four combinations, including the three
    that would refuse a rate if one were present."""
    fam = _family_c4(label_source=label_source, label_independent_of_candidate=independent)
    cfg = _load(tmp_path, fam)
    assert cfg.families["f"].label_independent_of_candidate is independent


# --- record.classify_label -----------------------------------------------------------------------


def test_a_present_label_is_labelled_even_when_the_elapsed_time_is_far_past_the_latency(tmp_path):
    """Catches an implementation that checks the elapsed time BEFORE checking whether a label arrived, which
    would misreport an actually-labelled, merely-late outcome as `missing`. The contract's first bullet ('a label
    present returns labelled') carries no time qualifier, unlike the second and third."""
    state = rec.classify_label(1000.0, 5000.0, 60.0, True)
    assert state == "labelled"
    assert state in rec.LABEL_STATES


def test_no_label_exactly_at_the_latency_boundary_is_pending_not_missing(tmp_path):
    """The boundary the contract states with `<=`: elapsed time EQUAL to `max_label_latency_s`, with no label, is
    `pending`. A test that only tried a value comfortably inside and one comfortably outside the window could not
    tell a `<=` implementation from a `<` one -- this is the exact value that distinguishes them."""
    assert rec.classify_label(1000.0, 1100.0, 100.0, None) == "pending"


def test_no_label_just_past_the_latency_boundary_is_missing(tmp_path):
    """The adjacent value on the other side of the same boundary. Together with the exactly-at-boundary test
    above, this is the pair that actually exercises `<=` versus `<` -- neither test alone would."""
    assert rec.classify_label(1000.0, 1100.01, 100.0, None) == "missing"


def test_no_label_comfortably_inside_the_window_is_pending(tmp_path):
    """A value away from the boundary, so the boundary tests above are not the only cases this function is ever
    run against -- catches an off-by-one or unit error that happens to cancel out exactly at the boundary."""
    assert rec.classify_label(1000.0, 1010.0, 100.0, None) == "pending"


def test_no_label_and_no_declared_latency_raises_value_error(tmp_path):
    """The contract's fourth bullet: with no declared `max_label_latency_s`, the pending/missing distinction is
    not the join's to make, and the function must refuse rather than guess a default window. This is the family
    whose `label_source` is `"none"` reaching this function with no label, which is the case that motivates the
    refusal."""
    with pytest.raises(ValueError):
        rec.classify_label(1000.0, 1100.0, None, None)


# --- Log.read does not reclassify a pre-upgrade row --------------------------------------------------


def _real_v010_lines() -> list[str]:
    return [line for line in V010_FIXTURE.read_text().splitlines() if line.strip()]


def test_log_read_never_calls_classify_label_while_reading_a_real_pre_upgrade_log(tmp_path, monkeypatch):
    """The contract's own words: 'classify_label is never applied' to a row at `schema_version < 2`. A real
    v0.1.0 log (no line in this fixture carries a `schema_version` key at all) is written and read whole, with
    `classify_label` replaced by a spy -- the only assertion that can actually tell 'never reclassified' apart
    from 'reclassified and happened to compute the same label_state already on disk', which asserting on the
    output alone cannot distinguish."""
    log = rec.Log(tmp_path / "log.jsonl")
    with log.path.open("a") as fh:
        for line in _real_v010_lines():
            fh.write(line + "\n")
    calls = []
    monkeypatch.setattr(rec, "classify_label", lambda *a, **kw: calls.append((a, kw)))
    log.read()
    assert calls == []


def test_log_read_keeps_the_pre_upgrade_label_state_written_on_disk(tmp_path):
    """The observable half of the same clause: the decision line in the real v0.1.0 fixture was written with
    `label_state: "pending"`, and reading it back must report that exact state -- not a value recomputed from
    `decided_at` and today's clock, which for a fixture this old would not necessarily agree."""
    log = rec.Log(tmp_path / "log.jsonl")
    with log.path.open("a") as fh:
        for line in _real_v010_lines():
            fh.write(line + "\n")
    decisions, _outcomes = log.read()
    assert len(decisions) == 1
    d = decisions[0]
    label_state = d["label_state"] if isinstance(d, dict) else d.label_state
    assert label_state == "pending"
