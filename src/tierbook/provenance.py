"""What an arm was made from and which items its maker saw, so a certificate is not computed over held-out items the arm
is claimed to have seen.

Two files, both written by someone other than tierbook and both read only to *subtract*:

**A set manifest** (JSONL) names items, one per line: ``{"item": ..., "content_sha256": ...}``. ``content_sha256`` is the
lowercase hex SHA-256 of the item's content as its sender defines it (Prismyra's writer uses ``[context, question]`` as
compact JSON). A manifest is cited by the SHA-256 of its file bytes, which pins ids and contents together.

**An arm's provenance** (JSON), written by whatever trained or froze the arm (a distillation trainer, a fine-tune
script, an RL system's snapshot):

    {"format": 1, "arm": "student-a", "arm_version": "...",
     "trained_on": [{"set": "stream", "manifest": "sets/stream.jsonl", "sha256": "..."}],
     "requires": [{"arm": "teacher", "arm_version": "..."}],
     "trainer": {...anything...}}

``requires`` names arms the arm cannot be served without (a student whose features come from a teacher's hidden state
needs that teacher), at the version it was built against. A candidate cites the provenance as
``"arm_provenance": {"path": "...", "sha256": "..."}`` and the sets its maker saw for choices (a recipe compared, a
threshold tuned) as ``"consulted": [{"set", "manifest", "sha256"}]``. Every citation carries its digest.

The one rule. These are claims tierbook cannot verify, so they can only remove an arm from selection, never admit one.
An arm is excluded when an item of its held-out half appears in a set it was trained on or consulted, when its observed
`arm_version` differs from its provenance's, or when a required arm is observed at another version. A check that
cannot be made (an arm or a requirement not observed) is reported as unchecked, not passed. Overlap is by item id, and
also by content when an observation's id has the form ``sha256:<content_sha256>``.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from tierbook.evidence import EvidenceError

FORMAT = 1
#: The id form whose tail is an item's content digest, so a manifest that names other ids still matches by content.
CONTENT_ID_PREFIX = "sha256:"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PROVENANCE_KEYS = {"format", "arm", "arm_version", "trained_on", "requires", "trainer"}


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class ItemSet:
    name: str
    items: frozenset[str]
    contents: frozenset[str]
    sha256: str


def _read(path: Path, what: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as e:
        raise EvidenceError(f"{what} {path}: {e.strerror or e}") from None


def load_manifest(name: str, path: str | Path, sha256: str) -> ItemSet:
    """A set manifest, refused unless its file bytes match the cited digest."""
    p = Path(path)
    data = _read(p, f"set {name!r}: manifest")
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        raise EvidenceError(f"set {name!r}: manifest {p} has sha256 {got}, not the cited {sha256}; the claim cannot "
                            "be read as made")
    items, contents = set(), set()
    for n, line in enumerate(data.decode("utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            raise EvidenceError(f"{p}:{n}: {e.msg}") from None
        if not isinstance(raw, dict) or not isinstance(raw.get("item"), str) or not raw["item"]:
            raise EvidenceError(f"{p}:{n}: a manifest row needs an 'item'")
        c = raw.get("content_sha256")
        if not (isinstance(c, str) and _HEX64.match(c)):
            raise EvidenceError(f"{p}:{n}: 'content_sha256' must be 64 lowercase hex characters")
        items.add(raw["item"])
        contents.add(c)
    return ItemSet(name=name, items=frozenset(items), contents=frozenset(contents), sha256=got)


def load_sets(entries, base: Path, what: str) -> tuple[ItemSet, ...]:
    if not isinstance(entries, list):
        raise EvidenceError(f"{what}: sets must be a list")
    out = []
    for e in entries:
        if not isinstance(e, dict) or not e.get("set") or not e.get("manifest") or not e.get("sha256"):
            raise EvidenceError(f"{what}: each set needs 'set', 'manifest' and the manifest file's 'sha256'")
        p = Path(e["manifest"])
        out.append(load_manifest(e["set"], p if p.is_absolute() else base / p, e["sha256"]))
    return tuple(out)


@dataclass(frozen=True)
class Provenance:
    arm: str
    arm_version: str
    trained_on: tuple[ItemSet, ...]
    requires: tuple[tuple[str, str], ...]
    sha256: str


def load_provenance(path: str | Path, sha256: str | None) -> Provenance:
    """A provenance file, refused unless it matches `sha256` (None only for `check-provenance`, which prints it)."""
    p = Path(path)
    data = _read(p, "provenance")
    got = hashlib.sha256(data).hexdigest()
    if sha256 is not None and got != sha256:
        raise EvidenceError(f"provenance {p} has sha256 {got}, not the cited {sha256}; the claim cannot be read as made")
    try:
        raw = json.loads(data)
    except json.JSONDecodeError as e:
        raise EvidenceError(f"provenance {p}: {e.msg}") from None
    if not isinstance(raw, dict):
        raise EvidenceError(f"provenance {p} must be a JSON object")
    if raw.get("format") != FORMAT:
        raise EvidenceError(f"provenance {p}: 'format' must be {FORMAT}, not {raw.get('format')!r}")
    unknown = sorted(set(raw) - _PROVENANCE_KEYS)
    if unknown:
        raise EvidenceError(f"provenance {p}: unknown keys {unknown}; put a trainer's own fields under 'trainer'")
    if not isinstance(raw.get("arm"), str) or not raw["arm"]:
        raise EvidenceError(f"provenance {p} names no arm")
    req = []
    for r in raw.get("requires") or []:
        if not isinstance(r, dict) or not r.get("arm") or r.get("arm_version") in (None, ""):
            raise EvidenceError(f"provenance {p}: each requirement needs 'arm' and 'arm_version'")
        req.append((str(r["arm"]), str(r["arm_version"])))
    return Provenance(arm=raw["arm"], arm_version=str(raw.get("arm_version") or ""),
                      trained_on=load_sets(raw.get("trained_on") or [], p.parent, f"provenance {p}"),
                      requires=tuple(req), sha256=got)


def overlap(items, sets: tuple[ItemSet, ...]) -> dict[str, list[str]]:
    """Per set, the given item ids that appear in it, by id or, for content-digest ids, by content."""
    hits: dict[str, list[str]] = {}
    for s in sets:
        for it in sorted(items):
            c = it[len(CONTENT_ID_PREFIX):] if it.startswith(CONTENT_ID_PREFIX) else None
            if it in s.items or (c is not None and c in s.contents):
                hits.setdefault(s.name, []).append(it)
    return hits
