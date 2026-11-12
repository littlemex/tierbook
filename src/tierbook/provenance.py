"""What an arm was made from and which items a choice about it consulted, so a certificate is never computed over items
the arm already saw.

Two files, both written by someone other than tierbook and both read only to *subtract*:

**A set manifest** (JSONL) names items, one per line: ``{"item": ..., "content_sha256": ...}``. ``content_sha256`` is the
hex SHA-256 of the item's model-visible input as UTF-8. A set's digest is the SHA-256 of its sorted content digests, one
per line, so two manifests with the same texts under different ids have the same digest.

**An arm's provenance** (JSON), written by whatever trained or froze the arm (a distillation trainer, a fine-tune
script, an RL system's snapshot):

    {"format": 1, "arm": "student-bge", "arm_version": "...",
     "trained_on": [{"set": "stream-w1-9", "manifest": "sets/stream.jsonl", "digest": "..."}],
     "requires": [{"arm": "teacher", "arm_version": "..."}],
     "trainer": {...anything...}}

A candidate cites them: ``"arm_provenance": {"path": "...", "sha256": "..."}`` and ``"consulted": [{"set", "manifest",
"digest"}]`` for the sets a choice about the arm was made on (a recipe compared, a threshold tuned).

The one rule. These are claims tierbook cannot verify, so they can only remove an arm from selection, never admit one.
An arm is excluded when an item of its held-out half appears in a set it was trained on or consulted (by item id, or by
content digest when the observation's item id is itself a content digest), when its observed `arm_version` differs from
its provenance's, or when a required arm's observed version differs from the one required. A file that does not match
its declared digest is refused outright: the claim cannot even be read as made.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from tierbook.evidence import EvidenceError

FORMAT = 1
_PROVENANCE_KEYS = {"format", "arm", "arm_version", "trained_on", "requires", "trainer"}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ItemSet:
    name: str
    items: frozenset[str]
    contents: frozenset[str]
    digest: str


def load_manifest(name: str, path: str | Path, digest: str | None = None) -> ItemSet:
    """A set manifest, checked against its declared digest when one is given."""
    items, contents = set(), set()
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw.get("item"), str) or not raw["item"]:
            raise EvidenceError(f"{path}:{n}: a manifest row needs an 'item'")
        c = raw.get("content_sha256")
        if not (isinstance(c, str) and len(c) == 64):
            raise EvidenceError(f"{path}:{n}: 'content_sha256' must be a 64-character hex digest")
        items.add(raw["item"])
        contents.add(c)
    got = set_digest(contents)
    if digest is not None and got != digest:
        raise EvidenceError(f"set {name!r}: manifest {path} has digest {got}, not the declared {digest}; the claim "
                            "cannot be read as made")
    return ItemSet(name=name, items=frozenset(items), contents=frozenset(contents), digest=got)


def set_digest(contents) -> str:
    return sha256_text("\n".join(sorted(contents)))


@dataclass(frozen=True)
class Provenance:
    arm: str
    arm_version: str
    trained_on: tuple[ItemSet, ...]
    requires: tuple[tuple[str, str], ...]
    raw: dict = field(default_factory=dict, compare=False)


def _sets(entries, base: Path, what: str) -> tuple[ItemSet, ...]:
    out = []
    for e in entries or []:
        if not isinstance(e, dict) or not e.get("set") or not e.get("manifest"):
            raise EvidenceError(f"{what}: each set needs 'set' and 'manifest' (and should give 'digest')")
        p = Path(e["manifest"])
        out.append(load_manifest(e["set"], p if p.is_absolute() else base / p, e.get("digest")))
    return tuple(out)


def load_provenance(path: str | Path, sha256: str | None = None) -> Provenance:
    p = Path(path)
    data = p.read_bytes()
    if sha256 is not None and hashlib.sha256(data).hexdigest() != sha256:
        raise EvidenceError(f"provenance {p} does not match its declared sha256; the claim cannot be read as made")
    raw = json.loads(data)
    if raw.get("format", FORMAT) > FORMAT:
        raise EvidenceError(f"provenance format {raw['format']} is newer than this reader ({FORMAT})")
    unknown = sorted(set(raw) - _PROVENANCE_KEYS)
    if unknown:
        raise EvidenceError(f"provenance {p}: unknown keys {unknown}; put a trainer's own fields under 'trainer'")
    if not raw.get("arm"):
        raise EvidenceError(f"provenance {p} names no arm")
    req = []
    for r in raw.get("requires") or []:
        if not isinstance(r, dict) or not r.get("arm") or not r.get("arm_version"):
            raise EvidenceError(f"provenance {p}: each requirement needs 'arm' and 'arm_version'")
        req.append((r["arm"], r["arm_version"]))
    return Provenance(arm=raw["arm"], arm_version=str(raw.get("arm_version") or ""),
                      trained_on=_sets(raw.get("trained_on"), p.parent, f"provenance {p}"),
                      requires=tuple(req), raw=raw)


def held_out_overlap(held_out_items, sets: tuple[ItemSet, ...]) -> list[str]:
    """Held-out item ids that appear in any of ``sets``, by id or (for content-digest ids) by content."""
    hit = []
    for it in sorted(held_out_items):
        c = it[len("sha256:"):] if it.startswith("sha256:") else None
        if any(it in s.items or (c is not None and c in s.contents) for s in sets):
            hit.append(it)
    return hit
