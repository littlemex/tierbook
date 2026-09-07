"""What the table says, said out loud: the policy's kind, the frontier, and whether the box can be used.

Three questions a compiled table already contains the answers to and did not state. Each is stated because
its silence is a failure mode rather than an omission.

**The policy's kind.** "The framework cannot tell you which policy is supported" is the failure this project
is guarding against, and a table that names one candidate without saying whether that is a degenerate answer,
an arrangement, or nothing-is-supported leaves a reader to infer it. A degenerate answer -- one candidate for
the whole family -- is a *correct* answer, and it must be reported as one rather than looking like a default.

**The frontier, not only the selected point.** An operator who cannot see what a point of accuracy costs
cannot choose a floor, and a floor chosen without seeing that is a guess wearing a policy's clothes. This
project already measured what happens when a search winner is quoted at its point estimate: over 480 policies
on 571 problems the certified lower bound sat 6.7 points below it and 9 of 10 recommended floors were
unwarranted.

**Whether the self-hosted candidate can be used.** A standing question, asked per family, answered with a
reason from a closed set when the answer is no -- because "no" without a reason cannot be acted on, and the
useful form is "what would have to change".
"""
from __future__ import annotations

#: Why a self-hosted candidate is not usable for a family. Closed, so a new reason is a deliberate addition
#: rather than a free-text note nobody can aggregate.
NOT_USABLE_REASONS = (
    "selected",                 # it is the chosen candidate
    "on_frontier_not_chosen",   # admissible and cheaper or better on one axis, but not the objective's pick
    "not_certified",            # no held-out fold supports it for this family
    "dominated",                # another candidate is at least as good on both axes
    "no_record",                # nothing measured it on this family
    "cannot_be_reached",        # no path from the serving contract in use
)

DEGENERATE, ARRANGEMENT, UNSUPPORTED = "degenerate", "arrangement", "unsupported"


def _on_frontier(points: list[dict]) -> list[dict]:
    """Mark the Pareto set over (cost down, quality up).

    Ties are kept on the frontier rather than broken: two candidates at the same cost and quality are
    genuinely both available, and dropping one would hide a choice from whoever reads this. A point with an
    unknown quality bound cannot be compared, so it is off the frontier and says why.
    """
    out = []
    for p in points:
        q, c = p.get("quality_lcb"), p.get("cost_per_request")
        if q is None or c is None:
            out.append({**p, "on_frontier": False, "frontier_note": "no comparable bound or cost"})
            continue
        dominated_by = [
            o["candidate"] for o in points
            if o is not p and o.get("quality_lcb") is not None and o.get("cost_per_request") is not None
            and o["cost_per_request"] <= c and o["quality_lcb"] >= q
            and (o["cost_per_request"] < c or o["quality_lcb"] > q)
        ]
        out.append({**p, "on_frontier": not dominated_by,
                    **({"dominated_by": sorted(dominated_by)} if dominated_by else {})})
    return out


def frontier_for(entry: dict) -> list[dict]:
    """Every arrangement the compiler ranked, as points, with the Pareto set marked."""
    points = [{
        "candidate": "+".join(r["arrangement"]),
        "kind": r.get("kind"),
        "quality_lcb": r.get("quality_lcb"),
        "cost_per_request": r.get("cost_per_request"),
        "certified": r.get("certified"),
        # Carried because a cost figure without its basis invites the reader to take it as the deployment's.
        # The number this project produced first was $0.25 per request, six times the token side, entirely
        # because one experimenter at concurrency 1 left the GPU idle -- true, and useless to anyone who does
        # not see the concurrency.
        "note": r.get("note"),
    } for r in entry.get("ranked", [])]
    return _on_frontier(points)


def policy_kind(entry: dict) -> tuple[str, str]:
    """The kind of policy this entry represents, and the reason in the compiler's own terms."""
    chosen = entry.get("chosen") or []
    status = entry.get("status")
    if not chosen:
        return UNSUPPORTED, "the compiler named no candidate for this family"
    if status not in ("assigned",):
        # Still a policy, and still named -- but not one a held-out fold supports. Saying "unsupported" here
        # would erase the distinction between "nothing was chosen" and "something was chosen on evidence
        # that does not certify it", and those need different responses.
        kind = ARRANGEMENT if len(chosen) > 1 else DEGENERATE
        why = (entry.get("validation") or {}).get("reason") or "no held-out fold supports this"
        return kind, f"{kind}, but not certified: {why}"
    if len(chosen) > 1:
        return ARRANGEMENT, f"an arrangement of {len(chosen)} stages: {' then '.join(chosen)}"
    return DEGENERATE, ("one candidate for the whole family. This is a correct answer, not a fallback: on "
                        "this evidence nothing is gained by splitting the family")


def self_hosted_answer(entry: dict, frontier: list[dict], *, self_hosted_ids: set[str]) -> dict:
    """Whether a self-hosted candidate can be used for this family, and if not, why.

    Asked every time because the owner has decided to keep one; the job here is to make the question
    answerable from the table rather than from an opinion.
    """
    if not self_hosted_ids:
        return {"usable": False, "reason": "no_record",
                "detail": "no candidate in this registry is marked self-hosted"}
    chosen = set(entry.get("chosen") or [])
    hit = sorted(self_hosted_ids & chosen)
    if hit:
        return {"usable": True, "reason": "selected", "candidates": hit}

    mine = [p for p in frontier
            if any(sid in p["candidate"].split("+") for sid in self_hosted_ids)]
    if not mine:
        return {"usable": False, "reason": "no_record",
                "detail": "the compiler ranked no arrangement containing a self-hosted candidate, so nothing "
                          "measured it on this family"}
    # Certification is checked BEFORE frontier position, and the order is the whole correctness of this
    # function. An uncertified candidate can sit on the frontier -- it is cheap and its bound is low, so
    # nothing dominates it -- and an earlier version therefore reported it as "usable, just move along the
    # frontier". Moving along a frontier to an uncertified point is precisely the selection-invalid step this
    # project measured the cost of: certified lower bounds 6.7 points below point estimates, 9 of 10
    # recommended floors unwarranted. Being on the frontier is not a licence; a bound is.
    if not any(p.get("certified") for p in mine):
        return {"usable": False, "reason": "not_certified",
                "candidates": sorted(p["candidate"] for p in mine),
                "detail": "measured on this family but no held-out fold supports it. What would change the "
                          "answer is more evidence, not a different threshold"}
    on = [p for p in mine if p.get("on_frontier") and p.get("certified")]
    if on:
        return {"usable": True, "reason": "on_frontier_not_chosen",
                "candidates": sorted(p["candidate"] for p in on),
                "detail": "certified and on the frontier, but the objective picked another point. It "
                          "becomes the choice if the operator moves along the frontier"}
    return {"usable": False, "reason": "dominated",
            "candidates": sorted(p["candidate"] for p in mine),
            "detail": "another candidate is at least as good on both cost and quality, so nothing is gained "
                      "by routing here"}


def annotate(table: dict, *, self_hosted_ids: set[str]) -> dict:
    """Add `policy_kind`, `frontier` and `self_hosted` to every family entry of a compiled table.

    Additive on purpose: the table is read by other things, and a reader that does not know these keys is
    unaffected while one that does gets the three statements without recomputing them.
    """
    for family, entry in (table.get("families") or {}).items():
        for label in ("can_reject", "cannot_reject"):
            e = entry.get(label)
            if not isinstance(e, dict):
                continue
            fr = frontier_for(e)
            kind, why = policy_kind(e)
            e["policy_kind"] = kind
            e["policy_kind_reason"] = why
            e["frontier"] = fr
            e["self_hosted"] = self_hosted_answer(e, fr, self_hosted_ids=self_hosted_ids)
    return table


def render(table: dict) -> str:
    """A human reading of the three statements, per family."""
    lines = []
    for family, entry in sorted((table.get("families") or {}).items()):
        lines.append(f"## {family}")
        for label in ("cannot_reject", "can_reject"):
            e = entry.get(label)
            if not isinstance(e, dict) or "policy_kind" not in e:
                continue
            lines.append(f"\n### {label}")
            lines.append(f"- **policy**: {e['policy_kind']} — {e['policy_kind_reason']}")
            sh = e["self_hosted"]
            detail = sh.get("detail")
            lines.append(f"- **self-hosted usable**: {'yes' if sh['usable'] else 'no'} ({sh['reason']})"
                         + (f" — {detail}" if detail else ""))
            lines.append("\n| candidate | kind | quality LCB | cost/req | certified | on frontier |")
            lines.append("|---|---|---|---|---|---|")
            for p in e["frontier"]:
                q = "-" if p["quality_lcb"] is None else f"{p['quality_lcb']:+.4f}"
                c = "-" if p["cost_per_request"] is None else f"{p['cost_per_request']:.6f}"
                lines.append(f"| {p['candidate']} | {p['kind']} | {q} | {c} | "
                             f"{'yes' if p['certified'] else 'no'} | "
                             f"{'yes' if p.get('on_frontier') else 'no'} |")
            # On what basis each cost was priced, below the table rather than inside it: it is a sentence, and
            # a sentence in a cell is unreadable. Omitted where the compiler qualified nothing.
            bases = [(p["candidate"], p["note"]) for p in e["frontier"] if p.get("note")]
            if bases:
                lines.append("")
                for cand, note in bases:
                    lines.append(f"- `{cand}`: {note}")
    return "\n".join(lines) + "\n"
