"""The compiled table as an artefact on disk, which is the only thing the online path may read.

`assign_family` computes a decision from the ledger. That computation is offline: it involves paired
statistics over a whole family and it must not run per request. So it is written down — with the registry
hash it was computed from, the margin it was given, and the full ranked list including the candidates that
lost — and the online path looks up a family in the file.

Two properties this buys, and both were paid for by getting them wrong first:

  * **an incident can be replayed.** A decision that exists only as a Python object in a process that has
    since exited cannot be reviewed. The file records why each entry is what it is, and which of three
    different facts led to a reference being used: nothing measurable, something cheaper that failed the
    margin, or the reference genuinely being cheapest.
  * **a stale table is visible.** The table carries the registry hash, so an online path can refuse to serve
    a table compiled from records that have since changed rather than silently using the old answer.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from tierbook.policy import Arrangement, Decision, Tier, assign_family, registry_version
from tierbook.validate import ASSIGNED, PROVISIONAL, REFUSED, check, load_validations, rank_stability


TABLE_FORMAT = 1


def _decision_json(d: Decision) -> dict:
    return {
        "family": d.family,
        "reference": d.reference,
        "chosen": list(d.chosen.tiers),
        "kind": d.chosen.kind,
        "certified": d.certified,
        "why": d.why,
        "margin": d.margin,
        "alpha": d.alpha,
        "registry_version": d.registry_version,
        # Every candidate, not just the winner. A reader deciding whether to trust this entry needs to see
        # what it beat and by how much.
        "ranked": [
            {
                "arrangement": list(c.arrangement.tiers),
                "kind": c.arrangement.kind,
                "quality_lcb": c.quality_lcb,
                "cost_per_request": (None if c.cost_per_request == float("inf") else round(c.cost_per_request, 6)),
                "certified": c.certified,
                "note": c.note,
            }
            for c in d.ranked
        ],
    }


def compile_to_file(
    tiers: dict[str, Tier],
    families: dict[str, str],
    out: str | Path,
    *,
    margin: float,
    alpha: float = 0.05,
    throughput_per_family: dict[str, float] | None = None,
    today: str | None = None,
    max_age_days: int = 90,
    note: str = "",
    validations: str | Path | None = None,
) -> dict:
    """Compile every family into one file, one entry per family per check condition.

    `throughput_per_family` is per family on purpose. A fixed-cost tier's amortised share is its hourly bill
    divided by realised throughput, and throughput is a property of the tier *and the family*: the same tier
    measured 94 seconds a task on one family and 17 on another, which moved its cost per request by a factor
    of three and changed which tier was cheapest. Passing one global number is how that goes wrong.
    """
    today = today or date.today().isoformat()
    tp = throughput_per_family or {}
    vals = load_validations(validations) if validations else {}
    table = {
        "table_format": TABLE_FORMAT,
        "compiled_at": today,
        "registry_version": registry_version(tiers),
        "margin": margin,
        "alpha": alpha,
        "max_age_days": max_age_days,
        "note": note,
        "warning": (
            "This table is only as good as the fold it was compiled from. On the one family where this "
            "project checked, a 20-item calibration fold compiled a tier whose quality bound failed out of "
            "fold at two of four margins, and the ranking of two close candidates swapped between folds. "
            "Check `evidence` on each entry before routing anything you care about."
        ),
        "families": {},
    }
    for family, reference in families.items():
        entry = {}
        for label, can_reject in (("can_reject", True), ("cannot_reject", False)):
            d = assign_family(
                tiers, family, reference,
                margin=margin, alpha=alpha,
                realised_tasks_per_hour=tp.get(family),
                request_can_reject=can_reject,
                today=today, max_age_days=max_age_days,
            )
            j = _decision_json(d)
            # The gate between "calibration chose this" and "you may route to it". Compiling produces a
            # draft; only a held-out fold on a different cohort can make it assigned.
            cal_cohort = (tiers[reference].outcome(family) or {}).get("cohort")
            j["validation"] = check(vals, family, d.chosen.head, reference,
                                    margin=margin, alpha=alpha, calibration_cohort=cal_cohort)
            j["status"] = j["validation"]["status"] if d.certified else PROVISIONAL
            if not d.certified:
                j["validation"]["reason"] = ("nothing was certified on the calibration fold either; "
                                             + j["validation"]["reason"])
            entry[label] = j
        entry["evidence"] = _evidence(tiers, family, reference)
        entry["rank_stability"] = rank_stability(tiers, vals, family, reference, alpha=alpha)
        table["families"][family] = entry
    Path(out).write_text(json.dumps(table, indent=2) + "\n")
    return table


def _evidence(tiers: dict[str, Tier], family: str, reference: str) -> dict:
    """What the entry rests on, in the same file as the entry.

    Put here rather than in documentation because a user reading a table to decide whether to trust it will
    not go and find the documentation. The numbers that matter are the sample size and whether the family
    was nested, since those are the two things that made this project's own compiled answer wrong.
    """
    ref = tiers[reference].outcome(family) or {}
    rows = []
    for t in tiers.values():
        o = t.outcome(family)
        if not o:
            continue
        p = t.paired(family) or {}
        rows.append({
            "tier": t.id,
            "solved": o.get("solved"),
            "attempted": o.get("attempted"),
            "runs_per_item": o.get("runs_per_item"),
            "cohort": o.get("cohort"),
            "solves_items_the_reference_does_not": p.get("candidate_only"),
        })
    crossovers = sum((r["solves_items_the_reference_does_not"] or 0) for r in rows)
    return {
        "reference_attempted": ref.get("attempted"),
        "suite": ref.get("suite"),
        "tiers": rows,
        "nested": crossovers == 0,
        "crossovers": crossovers,
        "reading": (
            "A crossover is an item a cheaper tier solved and the reference did not. Zero of them is not "
            "proof of nesting -- with n items the true rate is only bounded around 3/n -- and a non-zero "
            "count means the reference is not this family's ceiling, so a cascade is not a safe shape for it "
            "and the compiler refuses to build one."
        ),
    }


def load_table(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


class Unvalidated(RuntimeError):
    """Raised when a caller asks to route an entry no held-out fold has supported."""


def lookup(table: dict, family: str, *, request_can_reject: bool,
           allow_unvalidated: bool = False) -> tuple[Arrangement, dict]:
    """The whole online decision: one dictionary lookup, and the entry that justified it.

    Raises rather than guessing for a family the table does not contain. A router that silently picks
    something for unseen traffic is the failure this design exists to avoid -- the first check this project
    ran on itself was that an unmeasured family raises.
    """
    entry = (table.get("families") or {}).get(family)
    if not entry:
        raise KeyError(
            f"no compiled entry for family {family!r}; the table has "
            f"{sorted((table.get('families') or {}))}. Measure the family and recompile rather than routing it."
        )
    d = entry["can_reject" if request_can_reject else "cannot_reject"]
    status = d.get("status", PROVISIONAL)
    if status != ASSIGNED and not allow_unvalidated:
        raise Unvalidated(
            f"the entry for {family!r} is {status!r}, not {ASSIGNED!r}: {d.get('validation', {}).get('reason')}\n"
            "Routing it needs allow_unvalidated=True, which is deliberately awkward: on this project's own "
            "data a calibration fold chose a tier whose held-out bound was outside the margin by eleven "
            "points of solve rate."
        )
    return Arrangement(tuple(d["chosen"]), d["kind"]), d


def check_fresh(table: dict, tiers: dict[str, Tier]) -> str | None:
    """Whether the table still matches the ledger it was compiled from.

    Returns None when it does, and a description when it does not. The caller decides what to do; this only
    refuses to be silent about it.
    """
    now = registry_version(tiers)
    was = table.get("registry_version")
    if was != now:
        return (f"the table was compiled from registry {was} and the registry is now {now}; "
                "recompile before trusting it")
    return None
