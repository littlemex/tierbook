"""One-off migration: tau-bench retail raw per-item runs -> evidence artifacts.

Documented in `examples/ledger/evidence/MIGRATION.md`, which also records the exact assertion this script
makes and the numbers it produced. Run once, from the repo root:

    python3 examples/ledger/evidence/migrate_tau_bench.py

Reads the raw per-item run files at `/Users/akazawt/tmp/e02/tau/{cal,ho}-{api-strong-a,api-cheap-a,
self-hosted-a}.json` (outside this repo; not committed here), writes one evidence artifact per
(fold, tier) under `examples/ledger/evidence/`, and rewrites the three tier records under
`examples/ledger/tiers/` plus the held-out record at `examples/ledger/validation/tau-bench-retail-test.json`
to reference them in place of `paired_vs_reference`.

Only the `tool-agent-user-retail` family is touched. `agentic-coding` is left exactly as it is: its raw
per-item observations were never kept, so there is nothing to migrate it FROM, and reconstructing a fake
per-item breakdown from a stored 2x2 would be inventing evidence rather than recovering it.

State mapping, and the one thing worth being honest about: a raw row's `solved` field is `True` -> `solved`,
`False` -> `incorrect`. This is a plain two-state mapping, not three -- the raw runs carry no reliable signal
that would let this script tell a wrong answer apart from a transport-shaped failure. One row in particular
(`ho-api-strong-a.json`, task 26) has `error` set to a 400 BadRequestError with `reward: null` and
`turns: null`, which looks exactly like the `unobserved/execution_error` case the new state enum exists to
name. It is deliberately NOT classified that way here. See MIGRATION.md for why, and for the number that
would have come out differently if it were.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = Path("/Users/akazawt/tmp/e02/tau")
LEDGER_ROOT = Path(__file__).resolve().parent.parent          # examples/ledger
EVIDENCE_DIR = LEDGER_ROOT / "evidence"
TIERS_DIR = LEDGER_ROOT / "tiers"
VALIDATION_DIR = LEDGER_ROOT / "validation"

FAMILY = "tool-agent-user-retail"
REFERENCE_TIER = "api-strong-a"
CANDIDATE_TIERS = ("api-cheap-a", "self-hosted-a")
FOLDS = {
    "dev": {"raw_prefix": "cal", "suite_label": "tau-bench-retail-dev"},
    "test": {"raw_prefix": "ho", "suite_label": "tau-bench-retail-test"},
}

# The recorded 2x2s this migration must reproduce exactly, or stop. Key: (fold, candidate) ->
# (both, candidate_only, reference_only, neither).
EXPECTED = {
    ("dev", "api-cheap-a"): (18, 0, 2, 0),
    ("dev", "self-hosted-a"): (19, 0, 1, 0),
    ("test", "api-cheap-a"): (82, 9, 13, 11),
    ("test", "self-hosted-a"): (70, 6, 25, 14),
}

MIGRATION_DATE = "2026-08-30"
SOURCE_COMMIT = "ebc5621a0b596ffd8f3ebc0b01811a7f9966d2af"
SOURCE_RUN_DATE = "2026-08-24"


def load_raw(fold: str, tier: str) -> dict:
    prefix = FOLDS[fold]["raw_prefix"]
    return json.loads((RAW_DIR / f"{prefix}-{tier}.json").read_text())


def state_of(row: dict) -> str:
    """The two-state mapping this migration uses. See the module docstring for the one item this elides."""
    return "solved" if row["solved"] else "incorrect"


def suite_manifest_digest(fold: str, all_item_ids: list[str]) -> tuple[str, str]:
    """A stand-in manifest digest: sha256 of the suite label plus the sorted item ids.

    No upstream tau-bench manifest digest was available at migration time -- the raw runs recorded a task
    index and a pass/fail, nothing that identifies which release of the benchmark's task definitions produced
    them. Inventing a plausible-looking digest from nothing would be worse than admitting that: it would look
    exactly like a real content check while checking nothing about content, only about which numeric indices
    were used. So this hashes what actually IS known -- the suite's name and the exact set of item ids -- and
    the header says so. It still does real work: it catches a different item COUNT or a different item SET
    under the same suite label, which is what an id-only join would otherwise miss entirely.
    """
    label = FOLDS[fold]["suite_label"]
    h = hashlib.sha256()
    h.update(label.encode())
    for i in sorted(all_item_ids):
        h.update(b"\0")
        h.update(i.encode())
    return f"standin:sha256:{h.hexdigest()}", label


def build_artifact_lines(fold: str, tier: str, rows: list[dict], manifest_digest: str) -> list[str]:
    header = {
        "suite_manifest_digest": manifest_digest,
        "suite_manifest_digest_caveat": (
            "no upstream tau-bench manifest digest was available when this artifact was migrated on "
            f"{MIGRATION_DATE}; this digest is a stand-in derived from the suite label and the sorted item "
            "ids of this fold, not from the benchmark's own task definitions. It detects a different item "
            "SET under this label, not a changed upstream release."
        ),
        "run_id": (
            f"migrated-{MIGRATION_DATE}-from-{SOURCE_RUN_DATE}-mom-vsr-eks-benchmark:{tier}:{fold}"
        ),
        "scorer_version": (
            "tau-bench retail: final database state compared against the annotated goal, as run in the "
            f"{SOURCE_RUN_DATE} mom-vsr-eks-benchmark measurement (repo commit {SOURCE_COMMIT}). This "
            f"artifact is a {MIGRATION_DATE} migration of that run's already-scored per-item results into "
            "the evidence format; the scoring itself was not re-run."
        ),
        "subject": tier,
        "family": FAMILY,
        "trials_per_item": 1,
        "produced_at": MIGRATION_DATE,
    }
    lines = [json.dumps(header, sort_keys=True)]
    for row in sorted(rows, key=lambda r: r["task"]):
        note = row.get("error") or None
        lines.append(json.dumps({
            "item_id": str(row["task"]),
            "state": state_of(row),
            "unobserved_reason": None,
            "note": note,
        }, sort_keys=True))
    return lines


def write_artifact(fold: str, tier: str, lines: list[str]) -> tuple[Path, str]:
    content = ("\n".join(lines) + "\n").encode()
    digest_hex = hashlib.sha256(content).hexdigest()
    short = digest_hex[:16]
    filename = f"{FAMILY}-{fold}-{tier}-{short}.jsonl"
    path = EVIDENCE_DIR / filename
    path.write_bytes(content)
    return path, f"sha256:{digest_hex}"


def main() -> None:
    import sys

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from tierbook.evidence import load, paired  # noqa: E402  (path must be set up first)

    written: dict[tuple[str, str], dict] = {}
    for fold in FOLDS:
        ref_rows = load_raw(fold, REFERENCE_TIER)["rows"]
        all_ids = [str(r["task"]) for r in ref_rows]
        digest, _ = suite_manifest_digest(fold, all_ids)
        for tier in (REFERENCE_TIER, *CANDIDATE_TIERS):
            rows = load_raw(fold, tier)["rows"]
            lines = build_artifact_lines(fold, tier, rows, digest)
            path, full_digest = write_artifact(fold, tier, lines)
            written[(fold, tier)] = {
                "path": f"examples/ledger/evidence/{path.name}",
                "digest": full_digest,
            }
            print(f"wrote {path.relative_to(LEDGER_ROOT)} ({full_digest[:23]}...)")

    # Re-load every artifact just written through the real loader (digest check, uniqueness, everything)
    # and assert the derived 2x2 against each expected value. Any mismatch stops the script rather than
    # adjusting the expectation.
    mismatches = []
    for fold in FOLDS:
        ref_ev = load(written[(fold, REFERENCE_TIER)]["path"], ledger_root=str(LEDGER_ROOT))
        for tier in CANDIDATE_TIERS:
            cand_ev = load(written[(fold, tier)]["path"], ledger_root=str(LEDGER_ROOT))
            p = paired(cand_ev, ref_ev)
            got = (p.both, p.candidate_only, p.reference_only, p.neither)
            want = EXPECTED[(fold, tier)]
            status = "OK" if got == want else "MISMATCH"
            print(f"{fold:5} {tier:14} got={got} want={want} excluded={p.excluded['count']} {status}")
            if got != want:
                mismatches.append((fold, tier, got, want))

    if mismatches:
        print("\nSTOPPING: derived 2x2 does not match the recorded values for:")
        for fold, tier, got, want in mismatches:
            print(f"  {fold}/{tier}: derived {got} != recorded {want}")
        raise SystemExit(1)

    print("\nall four derived 2x2s match the recorded values exactly.")

    # Rewrite the tier records and the held-out record to point at the artifacts, removing paired_vs_reference.
    for tier in (REFERENCE_TIER, *CANDIDATE_TIERS):
        tier_path = TIERS_DIR / f"{tier}.json"
        rec = json.loads(tier_path.read_text())
        fam = rec["families"][FAMILY]
        fam.pop("paired_vs_reference", None)
        # The calibration ledger's own suite/cohort text already says this is the dev fold (20 items); the
        # held-out record below is the test fold (115 items). Point each at the matching artifact.
        fam["evidence"] = written[("dev", tier)]
        tier_path.write_text(json.dumps(rec, indent=2) + "\n")
        print(f"rewrote {tier_path.relative_to(LEDGER_ROOT)}: {FAMILY}.evidence -> {fam['evidence']['path']}")

    ho_path = VALIDATION_DIR / "tau-bench-retail-test.json"
    ho = json.loads(ho_path.read_text())
    for tier in (REFERENCE_TIER, *CANDIDATE_TIERS):
        entry = ho["tiers"][tier]
        entry.pop("paired_vs_reference", None)
        entry["evidence"] = written[("test", tier)]
    ho_path.write_text(json.dumps(ho, indent=2) + "\n")
    print(f"rewrote {ho_path.relative_to(LEDGER_ROOT)}")


if __name__ == "__main__":
    main()
