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
"""
from __future__ import annotations

import json
from pathlib import Path

from tierbook.policy import MAY_ASSIGN, evidence_class, paired_difference_lcb

ASSIGNED = "assigned"
PROVISIONAL = "provisional"
REFUSED = "refused"


def load_validations(path: str | Path) -> dict[str, list[dict]]:
    """Read every held-out record, keyed by family.

    A validation record is deliberately a different file from a tier record. Folding a held-out fold into
    the records the compiler reads would destroy the only thing that made it held out, and the next compile
    would be fitted to the set that is supposed to judge it.
    """
    out: dict[str, list[dict]] = {}
    p = Path(path)
    if not p.exists():
        return out
    for f in sorted(p.glob("*.json")):
        d = json.loads(f.read_text())
        fam = d.get("family")
        if not fam:
            continue
        out.setdefault(fam, []).append(d)
    return out


def check(
    validations: dict[str, list[dict]],
    family: str,
    chosen_tier: str,
    reference: str,
    *,
    margin: float,
    alpha: float = 0.05,
    calibration_cohort: str | None = None,
) -> dict:
    """Decide the status of one compiled entry, and say why in a form a machine can read.

    The reference tier being chosen is always `assigned`: there is no cheaper claim to validate, and
    refusing to serve the reference because nothing was held out would leave the caller with nothing at all.
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
        cohort = rec.get("cohort")
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
        pair = entry.get("paired_vs_reference")
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
        p = t.paired(family)
        if p:
            cal[tid] = paired_difference_lcb(p["both"], p["candidate_only"], p["reference_only"],
                                             p["neither"], alpha=alpha)
        e = (rec.get("tiers") or {}).get(tid) or {}
        hp = e.get("paired_vs_reference")
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
