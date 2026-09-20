"""The deploy manifests: that they parse, and that they decide nothing about somebody else's cluster.

**Why this is a test and not a workflow step.** It was a workflow step, and it imported PyYAML, which this package
never declared. Nothing noticed for as long as an earlier step in the same job failed first -- a failing step hides
every step after it, so a broken check and an unreached one look identical in a log. It surfaced the moment the
earlier steps were fixed.

The manifests are YAML, so a test that they parse needs a parser; PyYAML is declared in the `dev` extra for this and
nothing else. The "no runtime dependencies" rule is about the router, which reads JSON and does arithmetic.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # declared in the dev extra; a skip here would hide the missing dependency this file exists because of

BASE = Path(__file__).resolve().parents[1] / "deploy" / "base"


def manifests() -> list[Path]:
    found = sorted(BASE.glob("*.yaml"))
    assert found, f"no manifests under {BASE}, so this file would check nothing"
    return found


@pytest.mark.parametrize("path", [p.name for p in sorted(BASE.glob("*.yaml"))])
def test_the_manifest_parses(path):
    """A manifest that does not parse is one nobody can apply, and `kubectl` is a slow place to find out."""
    docs = list(yaml.safe_load_all((BASE / path).read_text()))
    assert docs, f"{path} parsed to nothing"
    assert all(d is None or isinstance(d, dict) for d in docs), f"{path} has a document that is not a mapping"


def test_no_manifest_names_a_namespace():
    """A manifest that names a namespace has made a decision about somebody else's cluster.

    The three objects here are meant to be applied into whichever namespace the operator chooses, which is why
    `deploy/README.md` documents `kubectl apply -n`. A hardcoded namespace turns that choice into ours.
    """
    named = []
    for path in manifests():
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if line.startswith("  namespace:"):
                named.append(f"{path.name}:{i}: {line.strip()}")
    assert not named, "these manifests name a namespace: " + "; ".join(named)
