"""C3 -- the tenant term's cardinality is declared, not assumed.

SCOPE section 6's multiplicity family is candidates x families x tenants x the selection process. No tenant
field exists anywhere in the record, the config or the artifact (before this entry), and SCOPE section 7 is
normative: pooling across tenants while holding per-tenant floors is "a declared policy input, not an
emergency measure." So the document requires a declaration for which there was no field, and every bound ever
computed assumed cardinality 1 without saying so. `config.FamilyDeclaration.tenant_scope` is required and
refused when absent, naming the family and the field; declaring `single` is legitimate and is the common
case -- what is refused is silence, not the value `single` itself. `per_tenant` together with an
`exploration_rate` is refused, because R11 found the rate and the selection-process term are coupled and this
release corrects over neither.

Fixtures are built from the real shipped ledger, `examples/ledger/candidates.json`, modified minimally,
because it carries two families with genuinely different existing shapes (`agentic-coding` declares an
`exploration_rate`, `tool-agent-user-retail` does not) -- a hand-typed single-family fixture would let an
implementation that only validates the first family pass. Every negative fixture here changes exactly one
family in exactly one way and leaves the other family valid, so exactly one refusal can apply and the test can
pin the message that refusal produces, not a message some other, unrelated refusal happened to produce first.

Only C3 is in scope here. C1, C2, C4 and C5's own fields and refusals are tested in their own files; this file
does not re-test `load_config`'s aggregation (C8, `test_config_aggregation.py`) or any other family key's
correctness.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tierbook.config import ConfigError, load_config  # noqa: E402

LEDGER_PATH = ROOT / "examples" / "ledger" / "candidates.json"

AGENTIC = "agentic-coding"                # ships with exploration_rate=0.05, label_independent_of_candidate=True
RETAIL = "tool-agent-user-retail"         # ships with no exploration_rate, label_independent_of_candidate=False


# --- fixture builders: the real shipped ledger, modified minimally ----------------------------------


def _base_ledger() -> dict:
    """A deep copy of the real shipped ledger. Neither family carries `tenant_scope` yet -- it predates C3 --
    so every fixture below adds it explicitly to whichever family must be valid, and omits it (or sets it)
    only on the family actually under test."""
    return copy.deepcopy(json.loads(LEDGER_PATH.read_text()))


def _set_tenant_scope(ledger: dict, family: str, value: str) -> None:
    ledger["families"][family]["tenant_scope"] = value


def _drop_exploration_rate(ledger: dict, family: str) -> None:
    ledger["families"][family].pop("exploration_rate", None)


def _write(tmp_path: Path, body: dict) -> Path:
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps(body))
    return p


def _load(tmp_path: Path, ledger: dict):
    return load_config(_write(tmp_path, ledger))


# --- 1/2: a family omitting tenant_scope is refused, and the refusal says `single` is legitimate ----


def _ledger_with_agentic_missing_tenant_scope() -> dict:
    """The one fixture both tests 1 and 2 share: `tool-agent-user-retail` is given a valid `tenant_scope` so
    it cannot be the source of any refusal, and `agentic-coding` is left exactly as the real ledger ships it
    -- a shape that loads cleanly today, with no other defect introduced -- so the ONLY problem `load_config`
    can find is the omitted field on `agentic-coding`. If it also had a stale exploration_rate/tenant_scope
    conflict or a missing unrelated key, a test reading the raised message could not tell which check fired."""
    ledger = _base_ledger()
    _set_tenant_scope(ledger, RETAIL, "single")
    return ledger


def test_a_family_omitting_tenant_scope_is_refused_naming_the_family_and_the_field(tmp_path):
    """Catches an implementation that treats an absent `tenant_scope` as `single` by default, or as any other
    silent fallback, rather than refusing to load. Section 6 requires the term be part of every bound
    computed; a default that never asks the operator is the same silent cardinality-1 assumption the entry
    exists to end, just moved from "nobody wrote a field" to "the loader invented one nobody typed."""
    ledger = _ledger_with_agentic_missing_tenant_scope()
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, ledger)
    msg = str(excinfo.value)
    assert AGENTIC in msg
    assert "tenant_scope" in msg


def test_the_omission_refusal_says_declaring_single_is_legitimate(tmp_path):
    """The requirement most likely to be skipped, and it is contracted: an operator reading a refusal that
    does not say the easy answer is legitimate will conclude they must build multi-tenancy before they can
    route anything at all. Catches a refusal that names the family and the field (satisfying the test above)
    but never tells the reader that declaring `tenant_scope: "single"` and moving on is the correct, common
    response to seeing it."""
    ledger = _ledger_with_agentic_missing_tenant_scope()
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, ledger)
    msg = str(excinfo.value)
    assert "single" in msg
    assert "legitimate" in msg


# --- 3: all three values load, against a two-family ledger -----------------------------------------


@pytest.mark.parametrize("value", ["single", "pooled", "per_tenant"])
def test_every_tenant_scope_value_loads_and_round_trips(tmp_path, value):
    """Catches an implementation that hardcodes `single` (or any one value) and silently ignores whatever the
    file actually says -- a test that only ever wrote `single` would still pass against that implementation.
    `tool-agent-user-retail` is the family under test because it carries no `exploration_rate`, so `per_tenant`
    cannot also trip the C3 coupling refusal tested below; `agentic-coding` supplies its own valid
    `tenant_scope` and is otherwise untouched, so the two-family loop is exercised for real on every value."""
    ledger = _base_ledger()
    _set_tenant_scope(ledger, AGENTIC, "single")
    _set_tenant_scope(ledger, RETAIL, value)
    cfg = _load(tmp_path, ledger)
    assert cfg.families[RETAIL].tenant_scope == value


# --- 4: per_tenant + exploration_rate is refused naming both; the other three combinations load ----


def test_per_tenant_with_exploration_rate_is_refused_naming_both(tmp_path):
    """Catches an implementation that never checks the coupling at all: `agentic-coding` ships with
    `exploration_rate: 0.05` already legal under every OLDER rule (label_source is not `none`,
    `label_independent_of_candidate` is `True`), so declaring `tenant_scope: "per_tenant"` on it introduces
    exactly one new defect -- the C3 coupling -- and no other refusal can be the one that fires.
    `tool-agent-user-retail` is given a valid, unrelated `tenant_scope` so it contributes no problem of its
    own."""
    ledger = _base_ledger()
    _set_tenant_scope(ledger, AGENTIC, "per_tenant")           # exploration_rate 0.05 already present
    _set_tenant_scope(ledger, RETAIL, "single")
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, ledger)
    msg = str(excinfo.value)
    assert "per_tenant" in msg
    assert "exploration_rate" in msg


def test_per_tenant_without_exploration_rate_loads(tmp_path):
    """The mirror of the refusal above, and the sharper of the two possible mistakes: an implementation that
    refuses `per_tenant` outright -- rather than only `per_tenant` co-declared with a rate -- would make the
    value undeclarable and defeat the entry, since `per_tenant` is one of exactly three values C3 requires be
    representable. `exploration_rate` is removed from `agentic-coding` before `tenant_scope: "per_tenant"` is
    set, so the only thing under test is whether `per_tenant` loads on its own."""
    ledger = _base_ledger()
    _drop_exploration_rate(ledger, AGENTIC)
    _set_tenant_scope(ledger, AGENTIC, "per_tenant")
    _set_tenant_scope(ledger, RETAIL, "single")
    cfg = _load(tmp_path, ledger)
    assert cfg.families[AGENTIC].tenant_scope == "per_tenant"
    assert cfg.families[AGENTIC].exploration_rate is None


def test_single_with_exploration_rate_loads(tmp_path):
    """One of the two combinations the coupling refusal must NOT reach: `single` says nothing about pooling
    tenants together for evidence, so it has no tension with drawing an exploration rate. Catches an
    implementation that generalises the new refusal to "any tenant_scope plus a rate" instead of the specific
    pairing the contract names."""
    ledger = _base_ledger()
    _set_tenant_scope(ledger, AGENTIC, "single")               # exploration_rate 0.05 already present
    _set_tenant_scope(ledger, RETAIL, "pooled")
    cfg = _load(tmp_path, ledger)
    assert cfg.families[AGENTIC].tenant_scope == "single"
    assert cfg.families[AGENTIC].exploration_rate == 0.05


def test_pooled_with_exploration_rate_loads(tmp_path):
    """The other combination the coupling refusal must not reach. `pooled` is itself the declared evidence-
    transfer policy SCOPE section 7 describes and is orthogonal to whether the family explores; only
    `per_tenant` is coupled to the rate, because `per_tenant` is the value that claims per-tenant evidence
    rather than a declared transfer across tenants."""
    ledger = _base_ledger()
    _set_tenant_scope(ledger, AGENTIC, "pooled")               # exploration_rate 0.05 already present
    _set_tenant_scope(ledger, RETAIL, "single")
    cfg = _load(tmp_path, ledger)
    assert cfg.families[AGENTIC].tenant_scope == "pooled"
    assert cfg.families[AGENTIC].exploration_rate == 0.05
