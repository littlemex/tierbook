"""The gate between "the calibration fold chose this" and "you may route traffic to it".

This module exists because of a measured failure, not a principle. On the one family where this project
checked its own compiler, a 20-item calibration fold selected a tier at margins 0.15 and 0.20 whose quality
bound on a held-out fold was -0.241 — outside both. The saving it promised was real and the quality claim was
not. Worse, the two candidates within ten points of each other **swapped rank between folds**: calibration
preferred the one that turned out to be further from the reference.

No minimum sample size would have caught that. At n = 20 the bound was computed correctly and was simply
about the wrong twenty items. So the gate is empirical rather than a threshold:

    measured  ->  compiled draft (provisional)  ->  validated on a different cohort  ->  active

An entry is `assigned` only when a held-out fold **with a different cohort hash** was measured and the claim
still holds on it. Otherwise it is `provisional`, and the runtime refuses to serve a provisional entry
without an explicit flag whose presence in someone's deploy script is the audit trail.

That cohort hash is content-addressed, from the suite manifest and the exact item ids, only for a family
carrying `evidence`; `_cohort_from_record` derives it there instead of trusting the record's own `cohort`
field. A family still carrying the legacy `paired_vs_reference` summary keeps a hand-written cohort label,
and this gate compares that label by string equality -- a rename, or two differently-labelled folds that
happen to share items, both pass silently for a record in that state. Migrating a family to evidence closes
this gap for it; nothing here closes it retroactively for one that has not been migrated.
"""
from __future__ import annotations

import json
from pathlib import Path

from tierbook.evidence import EvidenceError
from tierbook.evidence import load as _load_evidence
from tierbook.evidence import paired as _evidence_paired
from tierbook.policy import MAY_ASSIGN, evidence_class, paired_difference_lcb

ASSIGNED = "assigned"
PROVISIONAL = "provisional"
REFUSED = "refused"


def load_validations(path: str | Path) -> dict[str, list[dict]]:
    """Read every held-out record, keyed by family.

    A validation record is deliberately a different file from a tier record. Folding a held-out fold into
    the records the compiler reads would destroy the only thing that made it held out, and the next compile
    would be fitted to the set that is supposed to judge it.

    Each record carries its own `_ledger_root` (this directory's parent), so a per-tier `evidence` pointer
    inside it -- a repo-relative path such as `examples/ledger/evidence/...` -- resolves and stays bounded
    the same way a tier record's does. The key is prefixed with an underscore because it is not part of the
    validation record's own documented shape; it is plumbing this loader adds.
    """
    out: dict[str, list[dict]] = {}
    p = Path(path)
    if not p.exists():
        return out
    ledger_root = str(p.parent)
    for f in sorted(p.glob("*.json")):
        d = json.loads(f.read_text())
        fam = d.get("family")
        if not fam:
            continue
        d["_ledger_root"] = ledger_root
        out.setdefault(fam, []).append(d)
    return out


def _ledger_root_for(rec: dict, ledger_root: str | None) -> str:
    """Where an `evidence.path` inside this record should resolve relative to.

    `ledger_root`, when the caller supplies it, always wins: it comes from a `Tier` that was loaded from the
    real ledger (`load_registry`'s `ledger_root`), which is the ledger an evidence path is repo-relative TO --
    regardless of which directory the validation JSON that references it happens to live in or be copied to.
    `rec["_ledger_root"]` (set by `load_validations` from the validations directory's own location) is only a
    fallback for a caller that has no `Tier` in scope to ask.
    """
    return ledger_root if ledger_root is not None else rec.get("_ledger_root", ".")


def _pair_from_record(rec: dict, tier_id: str, reference: str, ledger_root: str | None = None) -> dict | None:
    """The 2x2 for `tier_id` against `reference`, both read from within one held-out record.

    Mirrors `Tier.paired`: derives from evidence, re-verified now, when both this tier's and the reference's
    entries carry it, and falls back to the hand-written `paired_vs_reference` summary on `tier_id`'s own
    entry otherwise. A held-out fold is read the same way a calibration fold is -- the whole promise this
    gate makes is that the two are comparable, and reading them through two different mechanisms would be a
    good way to make that stop being true without anyone noticing.
    """
    tiers = rec.get("tiers") or {}
    entry = tiers.get(tier_id) or {}
    ev_ref = entry.get("evidence")
    if ev_ref:
        ref_entry = tiers.get(reference) or {}
        ref_ev_ref = ref_entry.get("evidence")
        if ref_ev_ref:
            root = _ledger_root_for(rec, ledger_root)
            try:
                cand_ev = _load_evidence(ev_ref["path"], ledger_root=root)
                ref_ev = _load_evidence(ref_ev_ref["path"], ledger_root=root)
                p = _evidence_paired(cand_ev, ref_ev)
            except EvidenceError:
                return None
            return {"both": p.both, "candidate_only": p.candidate_only,
                    "reference_only": p.reference_only, "neither": p.neither, "excluded": p.excluded}
        return None
    return entry.get("paired_vs_reference")


def _cohort_from_record(rec: dict, tier_id: str, ledger_root: str | None = None) -> str | None:
    """The held-out cohort for `tier_id`, derived from evidence when present.

    Without this, the fold-collision gate below compares `rec["cohort"]` -- a hand-written label -- against
    the calibration fold's own hand-written label, and a rename of either defeats it (C10). Derived here
    from the same content-addressed hash `Tier.cohort` uses, so renaming a label can no longer make two
    different item sets compare equal, or the same item set compare unequal.
    """
    entry = (rec.get("tiers") or {}).get(tier_id) or {}
    ev_ref = entry.get("evidence")
    if ev_ref:
        try:
            return _load_evidence(ev_ref["path"], ledger_root=_ledger_root_for(rec, ledger_root)).cohort
        except EvidenceError:
            return None
    return rec.get("cohort")


def check(
    validations: dict[str, list[dict]],
    family: str,
    chosen_tier: str,
    reference: str,
    *,
    margin: float,
    alpha: float = 0.05,
    calibration_cohort: str | None = None,
    ledger_root: str | None = None,
) -> dict:
    """Decide the status of one compiled entry, and say why in a form a machine can read.

    The reference tier being chosen is always `assigned`: there is no cheaper claim to validate, and
    refusing to serve the reference because nothing was held out would leave the caller with nothing at all.

    `ledger_root` should be the same ledger root the calibration `Tier`s were loaded with (`table.py` passes
    it). Without it, a held-out record's `evidence.path` falls back to resolving against the validations
    directory's own location, which is wrong whenever a caller keeps validation records somewhere other than
    beside the ledger the evidence actually lives in.
    """
    verdict = {"status": PROVISIONAL, "reason": "", "holdout": None,
               "margin": margin, "alpha": alpha, "chosen": chosen_tier}
    if chosen_tier == reference:
        verdict.update(status=ASSIGNED, reason="the reference tier carries no cheaper claim to validate")
        return verdict

    records = validations.get(family) or []
    if not records:
        verdict["reason"] = ("no held-out fold has been measured for this family, so the calibration "
                             "fold's own choice is all there is")
        return verdict

    for rec in records:
        cohort = _cohort_from_record(rec, chosen_tier, ledger_root)
        cls = evidence_class(rec)
        if cls not in MAY_ASSIGN:
            # A fold judged by a model cannot promote an entry, however large it is and however well the
            # bound holds. It is a diagnostic: it says where to look, never what is true. The one path from
            # here to `assigned` is an audit of the items where candidate and reference disagreed, since
            # where they agree the fold contains no information about which of them is right.
            verdict["reason"] = (
                f"the held-out fold on {cohort!r} is {cls} evidence, which cannot assign. Agreement with a "
                "strong model is not an estimate of correctness: measured here, the strongest tier missed 6 "
                "to 9 items that cheaper tiers solved, so agreement would have scored them down exactly "
                "where they were right. Audit the disagreements to promote this."
            )
            continue
        if calibration_cohort and cohort == calibration_cohort:
            verdict["reason"] = (f"the held-out record reuses the calibration cohort {cohort!r}; a fold that "
                                 "shares its items with calibration validates nothing")
            continue
        entry = (rec.get("tiers") or {}).get(chosen_tier)
        if not entry:
            verdict["reason"] = f"the held-out fold does not include {chosen_tier!r}"
            continue
        pair = _pair_from_record(rec, chosen_tier, reference, ledger_root)
        if not pair:
            verdict["reason"] = "the held-out record carries no paired 2x2 against the reference"
            continue
        lcb = paired_difference_lcb(pair["both"], pair["candidate_only"], pair["reference_only"],
                                    pair["neither"], alpha=alpha)
        held = {"cohort": cohort, "attempted": entry.get("attempted"), "solved": entry.get("solved"),
                "lower_bound": (None if lcb is None else round(lcb, 4))}
        verdict["holdout"] = held
        if lcb is None:
            verdict["reason"] = "the held-out bound could not be computed"
            return verdict
        if lcb >= -margin:
            verdict.update(status=ASSIGNED,
                           reason=(f"held out on {cohort} at {entry.get('attempted')} items: bound "
                                   f"{lcb:+.4f} is inside the margin of {-margin:+.2f}"))
            return verdict
        verdict.update(status=REFUSED,
                       reason=(f"held out on {cohort} at {entry.get('attempted')} items: bound {lcb:+.4f} "
                               f"is OUTSIDE the margin of {-margin:+.2f}. The calibration fold chose this "
                               "tier and the held-out fold does not support it."))
        return verdict
    return verdict


def rank_stability(
    tiers: dict,
    validations: dict[str, list[dict]],
    family: str,
    reference: str,
    *,
    alpha: float = 0.05,
) -> dict | None:
    """Did the candidates keep their order between folds?

    Reported whether or not it matters for the current margin, because it is the thing that most cheaply
    tells a reader how much the calibration fold can be trusted. On this project's own data the answer was
    no: calibration ranked the two cheap candidates -0.130 and -0.210, and the held-out fold ranked the same
    two -0.241 and -0.102.
    """
    records = validations.get(family) or []
    if not records:
        return None
    rec = records[0]
    cal, hold = {}, {}
    for tid, t in tiers.items():
        if tid == reference:
            continue
        # `reference` is in scope, so a family carrying evidence derives the real 2x2 here instead of the
        # `None` a lone `Tier.paired(family)` would have to return without the other side.
        try:
            p = t.paired(family, tiers[reference])
        except EvidenceError:
            p = None
        if p:
            cal[tid] = paired_difference_lcb(p["both"], p["candidate_only"], p["reference_only"],
                                             p["neither"], alpha=alpha)
        hp = _pair_from_record(rec, tid, reference, tiers[reference].ledger_root)
        if hp:
            hold[tid] = paired_difference_lcb(hp["both"], hp["candidate_only"], hp["reference_only"],
                                              hp["neither"], alpha=alpha)
    shared = [t for t in cal if t in hold and cal[t] is not None and hold[t] is not None]
    if len(shared) < 2:
        return None
    cal_order = sorted(shared, key=lambda t: -cal[t])
    hold_order = sorted(shared, key=lambda t: -hold[t])
    return {
        "calibration_order": cal_order,
        "holdout_order": hold_order,
        "stable": cal_order == hold_order,
        "calibration_bounds": {t: round(cal[t], 4) for t in shared},
        "holdout_bounds": {t: round(hold[t], 4) for t in shared},
        "reading": ("An unstable order means the calibration fold cannot be trusted to pick between these "
                    "candidates, whatever bound it reported for either of them."),
    }
