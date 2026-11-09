"""The certification plane: observations in, a per-task-type assignment with a stated guarantee out.

See `docs/DESIGN-v0.5-certification-plane.md`. Each function owns one sentence:

* `compose` -- the attempts of each declared cascade arm, built from the attempts of its parts;
* `tally_items` -- per (task type, arm, item) results over fresh attempts, partitioned by a declared split;
* `derive` -- bounds, the comparison, the status of each assignment, and the fallback;
* `as_table` -- the policy in the shape the v0.4 router exporter reads (translation only);
* `drift`  -- the diff against a deployed policy, and whether fresh evidence contradicts it.

Everything that decides what counts as certified is declared by the caller (`Declarations`). Nothing here knows
which arm, task type or signal is good; it knows how to count, price, bound and compare what it is given.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from tierbook.bounds import Bound, resolve
from tierbook.config import Config
from tierbook.evidence import EvidenceError
from tierbook.observation import Observation, digest as observations_digest

FORMAT = 1

#: Statuses. Each says what the evidence did, never what the arm is.
CERTIFIED = "certified"          # held-out lower bound clears the floor
UNCONFIRMED = "unconfirmed"      # the floor lies inside the held-out interval
CONTRADICTED = "contradicted"    # held-out upper bound is below the floor
UNASSIGNABLE = "unassignable"    # nothing cleared selection, or a declaration is missing

REPEAT_RULES = ("all", "any", "majority")
UNOBSERVED_AS = ("rejected", "excluded")
HELD_OUT_CORRECTIONS = ("none", "bonferroni_over_task_types")
PRICE_KEYS = {"fresh_in": ("fresh_in",), "cached_in": ("cached_in",), "out": ("out",)}


class DeclarationError(ValueError):
    """A declarations file that does not say everything a certification depends on."""


@dataclass(frozen=True)
class Declarations:
    alpha: float
    bound: str
    holdout_fraction: float
    split_salt: str
    unobserved_as: str
    max_observation_age_days: float | None
    held_out_correction: str
    floors: dict[str, float]
    repeat_rule: str | None = None
    min_items: int | None = None
    fallback_arm: str | None = None
    usd_per_attempt: dict[str, dict] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"alpha": self.alpha, "bound": self.bound, "holdout_fraction": self.holdout_fraction,
                "split_salt": self.split_salt, "unobserved_as": self.unobserved_as,
                "max_observation_age_days": self.max_observation_age_days,
                "held_out_correction": self.held_out_correction, "repeat_rule": self.repeat_rule,
                "min_items": self.min_items, "fallback_arm": self.fallback_arm,
                "usd_per_attempt": self.usd_per_attempt,
                "task_types": {t: {"floor": f} for t, f in sorted(self.floors.items())}}


_REQUIRED = ("alpha", "bound", "holdout_fraction", "split_salt", "unobserved_as", "max_observation_age_days",
             "held_out_correction", "task_types")
_OPTIONAL = ("format", "repeat_rule", "min_items", "fallback_arm", "usd_per_attempt", "_comment")


def load_declarations(raw: dict | str | Path) -> Declarations:
    """Every problem at once, not the first of several: an operator fixes the file in one pass."""
    if not isinstance(raw, dict):
        raw = json.loads(Path(raw).read_text())
    problems = [f"missing required key {k!r}" for k in _REQUIRED if k not in raw]
    problems += [f"unknown key {k!r}" for k in sorted(set(raw) - set(_REQUIRED) - set(_OPTIONAL))]
    if raw.get("format", FORMAT) > FORMAT:
        problems.append(f"format {raw['format']} is newer than this reader ({FORMAT})")
    a = raw.get("alpha")
    if "alpha" in raw and not (isinstance(a, (int, float)) and 0 < a < 1):
        problems.append(f"alpha must be in (0, 1), not {a!r}")
    h = raw.get("holdout_fraction")
    if "holdout_fraction" in raw and not (isinstance(h, (int, float)) and 0 < h < 1):
        problems.append(f"holdout_fraction must be in (0, 1), not {h!r}: selection and the check need items each")
    if "unobserved_as" in raw and raw["unobserved_as"] not in UNOBSERVED_AS:
        problems.append(f"unobserved_as must be one of {UNOBSERVED_AS}")
    if "held_out_correction" in raw and raw["held_out_correction"] not in HELD_OUT_CORRECTIONS:
        problems.append(f"held_out_correction must be one of {HELD_OUT_CORRECTIONS}")
    rr = raw.get("repeat_rule")
    if rr is not None and rr not in REPEAT_RULES:
        try:
            resolve_repeat_rule(str(rr))
        except EvidenceError as e:
            problems.append(f"repeat_rule must be one of {REPEAT_RULES} or 'module:attribute' ({e})")
    age = raw.get("max_observation_age_days")
    if age is not None and not (isinstance(age, (int, float)) and age > 0):
        problems.append("max_observation_age_days must be a positive number, or null for an explicit no-limit")
    mi = raw.get("min_items")
    if mi is not None and not (isinstance(mi, int) and mi > 0):
        problems.append("min_items must be a positive integer")
    floors: dict[str, float] = {}
    for t, d in (raw.get("task_types") or {}).items():
        f = (d or {}).get("floor") if isinstance(d, dict) else None
        if not isinstance(f, (int, float)) or not 0 <= f <= 1:
            problems.append(f"task type {t!r} needs a floor in [0, 1], not {f!r}")
        else:
            floors[t] = float(f)
        extra = sorted(set(d or {}) - {"floor"}) if isinstance(d, dict) else []
        if extra:
            problems.append(f"task type {t!r} has unknown keys {extra}")
    for arm, p in (raw.get("usd_per_attempt") or {}).items():
        if not isinstance(p, dict) or not isinstance(p.get("usd"), (int, float)) or p["usd"] < 0 \
                or not p.get("source"):
            problems.append(f"usd_per_attempt[{arm!r}] needs a non-negative 'usd' and a 'source' saying where "
                            "it was derived from")
    if "bound" in raw:
        try:
            resolve(str(raw["bound"]))
        except EvidenceError as e:
            problems.append(str(e))
    if problems:
        raise DeclarationError("declarations cannot be used:\n  - " + "\n  - ".join(problems))
    return Declarations(alpha=float(a), bound=str(raw["bound"]), holdout_fraction=float(h),
                        split_salt=str(raw["split_salt"]), unobserved_as=raw["unobserved_as"],
                        max_observation_age_days=age, held_out_correction=raw["held_out_correction"],
                        floors=floors, repeat_rule=raw.get("repeat_rule"), min_items=mi,
                        fallback_arm=raw.get("fallback_arm"), usd_per_attempt=dict(raw.get("usd_per_attempt") or {}))


# --- tally ---------------------------------------------------------------------------------------------------------


def resolve_repeat_rule(rule: str) -> Callable[[list[str]], str]:
    """How graded runs of one item combine into one verdict: a shipped name, or a callable the caller injects.

    The shipped rules are three common answers, not a judgement that they are the only ones; a caller who wants
    "the latest graded run" or a weighted vote passes `module:attribute` taking the list of `accepted`/`rejected`
    strings (in observation order) and returning one of them.
    """
    if rule == "all":
        return lambda v: "accepted" if all(x == "accepted" for x in v) else "rejected"
    if rule == "any":
        return lambda v: "accepted" if any(x == "accepted" for x in v) else "rejected"
    if rule == "majority":
        return lambda v: "accepted" if 2 * sum(x == "accepted" for x in v) > len(v) else "rejected"
    fn = resolve(rule)   # same `module:attribute` loader as bounds
    return fn            # type: ignore[return-value]


# --- tally ---------------------------------------------------------------------------------------------------------

def partition_of(item: str, salt: str, holdout_fraction: float) -> str:
    h = int.from_bytes(hashlib.sha256(f"{salt}\0{item}".encode()).digest()[:8], "big") / 2 ** 64
    return "held_out" if h < holdout_fraction else "selection"


def _when(ts: str) -> datetime | None:
    if not ts:
        return None
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


@dataclass
class ItemResult:
    """One item on one arm: its verdict and what all of its fresh attempts consumed."""

    verdict: str | None          # accepted / rejected, or None when it does not count toward the rate
    graded_runs: int
    attempts: int
    unobserved_attempts: int
    cut_off_attempts: int
    tokens: dict[str, int]
    usage_missing_graded: int    # graded attempts that reported no usage: the arm cannot be priced on them
    usage_missing_unobserved: int  # unobserved attempts with no usage: counted at $0 because nothing says otherwise
    billed_usd: float | None
    newest: datetime | None
    label_sources: set[str]
    #: What each arm whose attempts make up this item consumed: {arm: {"tokens", "attempts", "usage_missing_graded"}}.
    #: One entry for an ordinary arm; for a cascade, one per part that was called (the primary always, the fallback
    #: when deferred to). Pricing is per part.
    parts: dict[str, dict] = field(default_factory=dict)
    fallback_missing_attempts: int = 0   # cascade attempts deferred to a fallback that never made them


def _verdict(runs: list[Observation], decl: Declarations) -> tuple[str | None, int]:
    """The item's verdict, and how many graded runs it rests on.

    `unobserved_as` decides only what an item with NO graded run counts as. An item that has a graded answer is judged
    on its graded answers; a retry that timed out beside an accepted answer does not turn the answer into a
    rejection, and does not make the item look like a repeated measurement.
    """
    graded = [o.outcome for o in runs if o.outcome != "unobserved"]
    if not graded:
        return ("rejected" if decl.unobserved_as == "rejected" and runs else None), 0
    if len(graded) == 1:
        return graded[0], 1
    if decl.repeat_rule is None:
        raise DeclarationError(
            f"item {runs[0].item!r} has {len(graded)} graded runs on arm {runs[0].arm!r} and no repeat_rule is "
            f"declared. Runs of one item are not independent, so they are combined into one item verdict; say how "
            f"({REPEAT_RULES} or 'module:attribute').")
    v = resolve_repeat_rule(decl.repeat_rule)(graded)
    if v not in ("accepted", "rejected"):
        raise DeclarationError(f"repeat_rule {decl.repeat_rule!r} returned {v!r}, not accepted/rejected")
    return v, len(graded)


def _attempt_key(o: Observation) -> tuple[str, str, str, str]:
    return (o.task_type, o.arm, o.item, o.run)


def dedupe(observations: Iterable[Observation]) -> list[Observation]:
    """One record per attempt. An identical line read twice is one attempt; two different lines for the same attempt
    are refused, because counting both would double its cost and choosing one would be a judgement."""
    seen: dict[tuple[str, str, str, str], Observation] = {}
    for o in observations:
        k = _attempt_key(o)
        if k in seen and seen[k] != o:
            raise EvidenceError(f"two different records for attempt {k}; give repeated attempts distinct runs")
        seen[k] = o
    return list(seen.values())


@dataclass(frozen=True)
class ComposedAttempt(Observation):
    """An attempt of a cascade arm, derived from the attempts of its parts. Never written: it exists only between
    `compose` and `tally_items`, so the record format is unchanged."""

    parts: tuple[Observation, ...] = ()
    #: Deferred to a fallback that has no attempt at this item and run: evidence the cascade needs and lacks.
    fallback_missing: bool = False


def _parts(o: Observation) -> tuple[Observation, ...]:
    return o.parts if isinstance(o, ComposedAttempt) else (o,)


def _composed(o: Observation, parts: tuple[Observation, ...], **changes) -> ComposedAttempt:
    values = {f.name: getattr(o, f.name) for f in dataclass_fields(Observation)}
    values.update(changes)
    return ComposedAttempt(**values, parts=parts)


def compose(observations: Iterable[Observation], cfg: Config) -> list[Observation]:
    """The observations, plus one attempt of each cascade arm for every attempt of its primary.

    A primary attempt with a score at or above the cascade's threshold is the cascade's attempt, whatever its outcome
    (an ungraded answer the cascade would have served stays ungraded). Below the threshold, the cascade's attempt is
    the fallback's attempt at the same item and run, and its cost is both. A primary attempt with no score is handled
    as the cascade's declared `on_no_score` says. A deferred attempt the fallback never made is `unobserved`, and
    counts as `unobserved_as` declares. Composed attempts carry no score: they are not evidence of the cascade's
    confidence, and a cascade cannot be another cascade's primary.

    An attempt recorded under a cascade's own name is refused: the record format cannot say which part answered it
    or what each part consumed. Record the parts' attempts and let them be composed.
    """
    base = dedupe(observations)
    by_arm: dict[str, dict[tuple[str, str, str], Observation]] = {}
    task_of: dict[tuple[str, str, str], str] = {}    # (arm, item, run) -> task type, to catch a mislabelled part
    for o in base:
        cand = cfg.candidates.get(o.arm)
        if cand is not None and cand.cascade is not None:
            raise EvidenceError(
                f"attempt {(o.task_type, o.item, o.run)} is recorded under the cascade {o.arm!r}; the record format "
                "cannot say which part answered or what each consumed. Record the attempts of its parts instead.")
        by_arm.setdefault(o.arm, {})[(o.task_type, o.item, o.run)] = o
        task_of[(o.arm, o.item, o.run)] = o.task_type
    built: dict[str, dict[tuple[str, str, str], Observation]] = {}

    def attempts(arm: str) -> dict[tuple[str, str, str], Observation]:
        cand = cfg.candidates.get(arm)
        if cand is None or cand.cascade is None:
            return by_arm.get(arm, {})
        if arm in built:
            return built[arm]
        c = cand.cascade
        primary, fallback = attempts(c.primary), attempts(c.fallback)
        out: dict[tuple[str, str, str], Observation] = {}
        for key, p in primary.items():
            if p.score is not None and p.score >= c.threshold:
                out[key] = _composed(p, (p,), arm=arm, usage={}, score=None)
                continue
            if p.score is None and c.on_no_score == "unobserved":
                why = f"{c.primary!r} reported no score, and on_no_score is 'unobserved'"
                out[key] = _composed(p, (p,), arm=arm, outcome="unobserved", usage={}, grader="", score=None,
                                     reason=f"{p.reason}; {why}" if p.outcome == "unobserved" and p.reason else why)
                continue
            f = fallback.get(key)
            if f is None:
                other = task_of.get((c.fallback, key[1], key[2]))
                if other is not None and other != key[0]:
                    raise EvidenceError(
                        f"cascade {arm!r}: item {key[1]!r} run {key[2]!r} is task type {key[0]!r} for "
                        f"{c.primary!r} and {other!r} for {c.fallback!r}; the parts disagree about what the item is")
                out[key] = _composed(p, (p,), arm=arm, outcome="unobserved", usage={}, grader="", score=None,
                                     fallback_missing=True,
                                     reason=f"deferred to {c.fallback!r}, which has no attempt at this item and run")
                continue
            parts = (p,) + _parts(f)
            times = [q.observed_at for q in parts]
            out[key] = _composed(
                f, parts, arm=arm, usage={}, score=None,
                # Freshness is judged on the oldest part, and an undated part leaves the whole attempt undated.
                observed_at=min(times, key=_when) if all(times) else "",
                latency_s=(p.latency_s + f.latency_s) if p.latency_s is not None and f.latency_s is not None else None,
                billed_usd=(p.billed_usd + f.billed_usd) if p.billed_usd is not None and f.billed_usd is not None
                else None)
        built[arm] = out
        return out

    composed = [o for arm, cand in sorted(cfg.candidates.items()) if cand.cascade is not None
                for _, o in sorted(attempts(arm).items())]
    return base + composed


def tally_items(observations: Iterable[Observation], decl: Declarations,
                as_of: datetime) -> tuple[dict[tuple[str, str, str], ItemResult], dict[tuple[str, str], int]]:
    """Per (task type, arm, item) results over FRESH attempts, and per (task type, arm) how many were too old.

    Freshness is judged per attempt: evidence older than `max_observation_age_days` is dropped before anything is
    counted, so one new attempt cannot carry a cell of old ones.
    """
    by_item: dict[tuple[str, str, str], list[Observation]] = {}
    stale: dict[tuple[str, str], int] = {}
    limit = decl.max_observation_age_days
    for o in dedupe(observations):
        if limit is not None:
            t = _when(o.observed_at)
            if t is None or (as_of - t).total_seconds() > limit * 86400:
                stale[(o.task_type, o.arm)] = stale.get((o.task_type, o.arm), 0) + 1
                continue
        by_item.setdefault((o.task_type, o.arm, o.item), []).append(o)
    out = {}
    for key, runs in by_item.items():
        verdict, graded = _verdict(runs, decl)
        tokens = {"fresh_in": 0, "cached_in": 0, "out": 0}
        parts: dict[str, dict] = {}
        billed: float | None = 0.0
        missing_graded = missing_unobserved = 0
        for o in runs:
            # A part's missing usage counts as graded when the attempt it makes up was graded: the primary of a
            # cascade answer is often never graded itself, and must not be priced at $0 for that.
            graded_attempt = o.outcome != "unobserved"
            for q in _parts(o):
                pt = parts.setdefault(q.arm, {"tokens": {"fresh_in": 0, "cached_in": 0, "out": 0}, "attempts": 0,
                                              "usage_missing_graded": 0})
                pt["attempts"] += 1
                for k, v in q.usage.items():
                    tokens[k] += v
                    pt["tokens"][k] += v
                if not q.usage:
                    if graded_attempt:
                        pt["usage_missing_graded"] += 1
                        missing_graded += 1
                    else:
                        missing_unobserved += 1
            billed = None if (billed is None or o.billed_usd is None) else billed + o.billed_usd
        times = [t for t in (_when(o.observed_at) for o in runs) if t is not None]
        out[key] = ItemResult(
            verdict=verdict, graded_runs=graded, attempts=len(runs),
            unobserved_attempts=sum(o.outcome == "unobserved" for o in runs),
            cut_off_attempts=sum(o.finish_reason == "length" for o in runs), tokens=tokens,
            usage_missing_graded=missing_graded, usage_missing_unobserved=missing_unobserved,
            billed_usd=billed, newest=max(times) if times else None,
            label_sources={q.label_source for o in runs for q in _parts(o) if q.label_source}, parts=parts,
            fallback_missing_attempts=sum(getattr(o, "fallback_missing", False) for o in runs))
    return out, stale


# --- pricing -------------------------------------------------------------------------------------------------------

def price_tokens(tokens: dict[str, int], attempts: int, arm: str, cfg: Config,
                 decl: Declarations) -> tuple[float | None, str]:
    """Spend at today's prices for these tokens, or None with the reason it cannot be priced."""
    cand = cfg.candidates.get(arm)
    if cand is None:
        return None, "not in the candidate file, so it has no price and cannot be routed to"
    if cand.is_fixed_cost:
        p = decl.usd_per_attempt.get(arm)
        if p is None:
            return None, ("a fixed-cost arm; its price per attempt is an hourly bill over a measured throughput and "
                          "must be declared in usd_per_attempt with its source")
        return p["usd"] * attempts, f"declared: {p['source']}"
    card = cand.price_per_mtok or {}
    total = 0.0
    for kind, n in tokens.items():
        if n == 0:
            continue
        rate = next((card[k] for k in PRICE_KEYS[kind] if card.get(k) is not None), None)
        if rate is None:
            return None, f"used {n} {kind} tokens and the price card has no {kind} rate"
        total += n * float(rate) / 1e6
    return total, "price card"


def _price(items: list[ItemResult], cfg: Config, decl: Declarations) -> tuple[float | None, str, dict[str, dict]]:
    """Spend at today's prices for these items, summed over the arms whose attempts they are made of, or None with
    the reason. One arm for an ordinary cell; each part of a cascade priced on its own card or declaration."""
    parts: dict[str, dict] = {}
    for r in items:
        for a, pt in r.parts.items():
            acc = parts.setdefault(a, {"tokens": {"fresh_in": 0, "cached_in": 0, "out": 0}, "attempts": 0,
                                       "usage_missing_graded": 0})
            acc["attempts"] += pt["attempts"]
            acc["usage_missing_graded"] += pt["usage_missing_graded"]
            for kind, v in pt["tokens"].items():
                acc["tokens"][kind] += v
    total: float | None = 0.0
    how: list[str] = []
    for a, pt in sorted(parts.items()):
        cand = cfg.candidates.get(a)
        # A fixed-cost arm is priced per attempt from its declared usd_per_attempt, so its tokens are not what it is
        # priced on and an answer that reports none (a decision model, a student) is not unpriceable for that.
        missing = 0 if cand is not None and cand.is_fixed_cost else pt["usage_missing_graded"]
        if missing:
            total = None
            how.append(f"{missing} graded attempt(s) of {a} reported no usage; empty usage is unknown, not zero")
            continue
        p, why = price_tokens(pt["tokens"], pt["attempts"], a, cfg, decl)
        if p is None:
            total = None
        elif total is not None:
            total += p
        how.append(why if len(parts) == 1 else f"{a}: {why}")
    return total, ("; ".join(how) if how else "no attempts"), parts


# --- cells ---------------------------------------------------------------------------------------------------------

def _cell(items: list[ItemResult], arm: str, cfg: Config, decl: Declarations, bound: Bound, alpha: float,
          stale_attempts: int = 0) -> dict:
    counted = [r for r in items if r.verdict is not None]
    n, k = len(counted), sum(r.verdict == "accepted" for r in counted)
    lo, hi = bound(k, n, alpha) if n else (0.0, 1.0)
    tokens = {"fresh_in": 0, "cached_in": 0, "out": 0}
    for r in items:
        for kind, v in r.tokens.items():
            tokens[kind] += v
    attempts = sum(r.attempts for r in items)
    total, priced_by, parts = _price(items, cfg, decl)
    free = sum(r.usage_missing_unobserved for r in items)
    if free and total is not None:
        priced_by += f"; {free} unobserved attempt(s) reported no usage and are counted at $0"
    billed = [r.billed_usd for r in items]
    newest = max((r.newest for r in items if r.newest), default=None)
    return {
        "items": n, "accepted": k, "graded_items": sum(r.graded_runs > 0 for r in items),
        "unobserved_items": sum(r.graded_runs == 0 for r in items),
        "attempts": attempts, "unobserved_attempts": sum(r.unobserved_attempts for r in items),
        "cut_off_attempts": sum(r.cut_off_attempts for r in items), "stale_attempts": stale_attempts,
        "usage_missing_unobserved": sum(r.usage_missing_unobserved for r in items),
        "tokens": tokens, "rate": (k / n) if n else None, "lower": lo, "upper": hi,
        "spend_usd": total, "priced_by": priced_by,
        "spend_per_accepted_usd": (total / k) if total is not None and k else None,
        "billed_usd": (sum(billed) if billed and all(b is not None for b in billed) else None),
        "newest": newest.isoformat() if newest else "",
        "label_sources": sorted(set().union(*(r.label_sources for r in items)) if items else set()),
        "part_attempts": {a: pt["attempts"] for a, pt in sorted(parts.items())},
        "part_tokens": {a: pt["tokens"] for a, pt in sorted(parts.items())},
        "fallback_missing_attempts": sum(r.fallback_missing_attempts for r in items),
    }


# --- derive --------------------------------------------------------------------------------------------------------

def derive(observations: list[Observation], cfg: Config, decl: Declarations, *,
           as_of: datetime | None = None, candidates_digest: str = "") -> dict:
    as_of = as_of or datetime.now(timezone.utc)
    bound = resolve(decl.bound)
    for arm in decl.usd_per_attempt:
        cand = cfg.candidates.get(arm)
        if cand is None or not cand.is_fixed_cost:
            where = cfg.source or "the candidate file"
            raise DeclarationError(
                f"usd_per_attempt names {arm!r}, which is not a fixed-cost candidate in {where}; a declared price "
                "may only stand in for an hourly bill, never for a price card or for an arm the router cannot reach")
    results, stale = tally_items(compose(observations, cfg), decl, as_of)
    part = {key: partition_of(key[2], decl.split_salt, decl.holdout_fraction) for key in results}
    observed_types = sorted({t for t, _, _ in results} | {t for t, _ in stale})
    arms_seen = sorted({a for _, a, _ in results} | {a for _, a in stale})
    certifiable = [t for t in observed_types if t in decl.floors]
    alpha_ho = decl.alpha / max(1, len(certifiable)) if decl.held_out_correction != "none" else decl.alpha

    def items(t: str, a: str, p: str | None) -> list[ItemResult]:
        return [r for key, r in results.items() if key[0] == t and key[1] == a and (p is None or part[key] == p)]

    task_types: dict[str, dict] = {}
    for t in sorted(set(observed_types) | set(decl.floors)):
        if t not in decl.floors:
            task_types[t] = {"status": UNASSIGNABLE, "arm": None, "reason_code": "no_floor",
                             "reason": "observed but no floor is declared for it"}
            continue
        floor = decl.floors[t]
        per_arm = {}
        for a in arms_seen:
            if not items(t, a, None) and not stale.get((t, a)):
                continue
            sel = _cell(items(t, a, "selection"), a, cfg, decl, bound, decl.alpha)
            ho = _cell(items(t, a, "held_out"), a, cfg, decl, bound, alpha_ho)
            whole = _cell(items(t, a, None), a, cfg, decl, bound, decl.alpha, stale.get((t, a), 0))
            per_arm[a] = {"selection": sel, "held_out": ho, "stale_attempts": stale.get((t, a), 0),
                          "fresh": whole["attempts"] > 0, "priced": whole["spend_usd"] is not None,
                          "priced_by": whole["priced_by"]}
        if not per_arm:
            task_types[t] = {"status": UNASSIGNABLE, "arm": None, "reason_code": "no_observations",
                             "reason": "a floor is declared and nothing was observed", "floor": floor}
            continue
        # Priced on BOTH partitions: the shipped cost is the held-out one, so an arm whose held-out attempts cannot
        # be priced cannot ship a cost and is not eligible, however it looked on selection.
        eligible = [a for a, s in per_arm.items()
                    if s["fresh"] and s["priced"] and s["selection"]["accepted"] > 0
                    and s["selection"]["lower"] >= floor]
        entry: dict = {"floor": floor, "arms": per_arm}
        if not eligible:
            miss = max(sorted(per_arm), key=lambda a: per_arm[a]["selection"]["lower"])
            s = per_arm[miss]
            why = (f"stale: all {s['stale_attempts']} attempt(s) older than max_observation_age_days"
                   if not s["fresh"] else f"unpriced: {s['priced_by']}" if not s["priced"]
                   else f"selection lower bound {s['selection']['lower']:.4f} < floor {floor}")
            entry.update(status=UNASSIGNABLE, arm=None, reason_code="nothing_clears_floor",
                         reason=f"no fresh, priced arm clears the floor on selection; nearest miss {miss} ({why})")
            task_types[t] = entry
            continue
        chosen = min(eligible, key=lambda a: (per_arm[a]["selection"]["spend_per_accepted_usd"],
                                              -per_arm[a]["selection"]["lower"], a))
        ho = per_arm[chosen]["held_out"]
        if ho["items"] == 0:
            status, code, why = UNCONFIRMED, "no_held_out_items", "no held-out items were observed for it"
        elif ho["lower"] >= floor:
            status, code, why = CERTIFIED, "held_out_clears", (
                f"held-out lower bound {ho['lower']:.4f} >= floor {floor} on {ho['items']} items")
        elif ho["upper"] < floor:
            status, code, why = CONTRADICTED, "held_out_below", (
                f"held-out upper bound {ho['upper']:.4f} < floor {floor}: selection chose it and the held-out "
                "items contradict it")
        else:
            status, code, why = UNCONFIRMED, "held_out_inconclusive", (
                f"floor {floor} lies inside the held-out interval [{ho['lower']:.4f}, {ho['upper']:.4f}]")
        labels = sorted(set(per_arm[chosen]["selection"]["label_sources"]) | set(ho["label_sources"]))
        cas = cfg.candidates[chosen].cascade if chosen in cfg.candidates else None
        if cas is not None:
            entry["cascade"] = {"primary": cas.primary, "fallback": cas.fallback, "threshold": cas.threshold,
                                "on_no_score": cas.on_no_score}
        entry.update(status=status, arm=chosen, reason_code=code, held_out=ho, label_sources=labels,
                     reason=(f"cheapest per accepted task among {len(eligible)} that cleared selection; {why}; "
                             f"conditional on task_type labels from {labels or ['unrecorded']}"))
        task_types[t] = entry

    single = _single_best(results, part, arms_seen, certifiable, cfg, decl, bound)
    fallback = _fallback(decl, single, cfg)
    return {
        "format": FORMAT,
        "derived_at": as_of.isoformat(),
        "observations_digest": observations_digest(observations),
        "candidates_digest": candidates_digest,
        "candidates_source": cfg.source,
        "declarations": decl.as_dict(),
        "guarantee": ("each certified task type: held-out lower bound at confidence "
                      + (f"1 - alpha/{len(certifiable)} (Bonferroni over task types, so the policy holds as a whole "
                         f"at 1 - {decl.alpha})" if decl.held_out_correction != "none"
                         else f"1 - {decl.alpha}, per task type; not a guarantee for the policy as a whole")
                      + ", conditional on the task_type labels in the observations"),
        "task_types": task_types,
        "single_best": single,
        "fallback": fallback,
        "comparison": _comparison(task_types, single, results, part, cfg, decl),
    }


def _single_best(results, part, arms, task_types, cfg, decl, bound) -> dict | None:
    """The one arm a reader would send everything to, chosen on selection items of the certifiable task types.

    Coverage is reported beside it: an arm observed on only some task types is chosen on those alone, and the
    report says which, rather than presenting a partial pooled score as an answer for all traffic.
    """
    pooled = {}
    for a in arms:
        if a not in cfg.candidates:
            continue
        sel = [r for key, r in results.items()
               if key[1] == a and key[0] in task_types and part[key] == "selection" and r.verdict is not None]
        if not sel:
            continue
        k = sum(r.verdict == "accepted" for r in sel)
        pooled[a] = (bound(k, len(sel), decl.alpha)[0],
                     sorted({key[0] for key in results if key[1] == a and key[0] in task_types}))
    if not pooled:
        return None
    best = min(pooled, key=lambda a: (-pooled[a][0], a))
    return {"arm": best, "chosen_on": "pooled selection lower bound over the certifiable task types",
            "selection_lower": pooled[best][0], "covers": pooled[best][1],
            "missing_task_types": sorted(set(task_types) - set(pooled[best][1]))}


def _fallback(decl: Declarations, single: dict | None, cfg: Config) -> dict | None:
    if decl.fallback_arm:
        if decl.fallback_arm not in cfg.candidates:
            raise DeclarationError(f"fallback_arm {decl.fallback_arm!r} is not in the candidate file")
        return {"arm": decl.fallback_arm, "why": "declared"}
    if single:
        return {"arm": single["arm"], "why": "no fallback declared, so the single best arm on selection"}
    return None


def _comparison(task_types, single, results, part, cfg, decl) -> dict | None:
    """Spend per accepted task of the policy against the single best arm, on the SAME held-out items.

    Per certified task type, only items that both arms were observed on (with a verdict) count, so both sides are
    graded on one population and priced alike. A task type with no common items is listed as omitted with why.
    """
    if not single:
        return None
    one = single["arm"]
    pol_spend = pol_acc = one_spend = one_acc = 0.0
    used, omitted, n_items = [], {}, 0
    for t, e in task_types.items():
        if e.get("status") != CERTIFIED:
            continue
        mine = {key[2]: r for key, r in results.items()
                if key[0] == t and key[1] == e["arm"] and part[key] == "held_out" and r.verdict is not None}
        theirs = {key[2]: r for key, r in results.items()
                  if key[0] == t and key[1] == one and part[key] == "held_out" and r.verdict is not None}
        common = sorted(set(mine) & set(theirs))
        if not common:
            omitted[t] = f"no held-out item observed on both {e['arm']} and {one}"
            continue
        ps = _price([mine[i] for i in common], cfg, decl)[0]
        os_ = _price([theirs[i] for i in common], cfg, decl)[0]
        if ps is None or os_ is None:
            omitted[t] = "one side cannot be priced on the common items"
            continue
        used.append(t)
        n_items += len(common)
        pol_spend += ps
        one_spend += os_
        pol_acc += sum(mine[i].verdict == "accepted" for i in common)
        one_acc += sum(theirs[i].verdict == "accepted" for i in common)
    if not used:
        return {"task_types": [], "omitted": omitted} if omitted else None
    return {"task_types": used, "omitted": omitted, "common_held_out_items": n_items,
            "policy_accepted": int(pol_acc), "single_best_accepted": int(one_acc),
            "policy_spend_per_accepted_usd": pol_spend / pol_acc if pol_acc else None,
            "single_best_spend_per_accepted_usd": one_spend / one_acc if one_acc else None,
            "ratio": ((pol_spend / pol_acc) / (one_spend / one_acc)) if pol_acc and one_acc and one_spend else None}


# --- export translation --------------------------------------------------------------------------------------------

def as_table(policy: dict, *, allow_unconfirmed: bool = False) -> dict:
    """The policy in the compiled-table shape `export_vsr.export` reads. Translation only.

    `certified` maps to the exporter's `assigned`; `unconfirmed` maps to its `provisional`, which the exporter
    skips unless told otherwise; `contradicted` and `unassignable` produce no entry at all, so no flag can export
    them.
    """
    fams = {}
    for t, e in policy["task_types"].items():
        if e["status"] == CERTIFIED:
            status = "assigned"
        elif e["status"] == UNCONFIRMED:
            status = "provisional"
        else:
            continue
        kind = "cascade" if e.get("cascade") else "single"
        fams[t] = {"cannot_reject": {"status": status, "kind": kind, "chosen": [e["arm"]], "why": e["reason"],
                                     **({"cascade": e["cascade"]} if e.get("cascade") else {}),
                                     "label_sources": e.get("label_sources", []),
                                     "validation": {"reason": e["reason"]}}}
    return {"families": fams, "registry_version": policy["observations_digest"],
            "compiled_at": policy["derived_at"], "margin": None, "objective": "spend per accepted task",
            "allow_unconfirmed": allow_unconfirmed}


def assignments(policy: dict, *, allow_unconfirmed: bool = False) -> dict:
    """The exportable assignments as plain data, from the same translation the router exporter reads."""
    out = {}
    for t, e in as_table(policy)["families"].items():
        d = e["cannot_reject"]
        if d["status"] == "assigned" or allow_unconfirmed:
            out[t] = {"arm": d["chosen"][0], "status": policy["task_types"][t]["status"], "why": d["why"],
                      "label_sources": d["label_sources"]}
    return out


# --- drift ---------------------------------------------------------------------------------------------------------

def drift(deployed: dict, rederived: dict, fresh: list[Observation], decl: Declarations, cfg: Config, *,
          as_of: datetime | None = None) -> dict:
    """Separate reports -- re-derivation changes, contradiction checks, cells that need measuring, attempts that reached
    no arm -- and none of them decides to redeploy."""
    as_of = as_of or datetime.now(timezone.utc)
    changes = []
    for t in sorted(set(deployed["task_types"]) | set(rederived["task_types"])):
        a, b = deployed["task_types"].get(t, {}), rederived["task_types"].get(t, {})
        if (a.get("status"), a.get("arm")) != (b.get("status"), b.get("arm")):
            changes.append({"task_type": t, "deployed": {"status": a.get("status"), "arm": a.get("arm")},
                            "rederived": {"status": b.get("status"), "arm": b.get("arm"),
                                          "reason": b.get("reason")}})
    if decl.min_items is None and any(e.get("status") == CERTIFIED for e in deployed["task_types"].values()):
        raise DeclarationError("drift needs min_items declared: below it a window says nothing, and the report "
                               "must not read as 'no change'")
    for t, e in sorted(deployed["task_types"].items()):
        cas = e.get("cascade")
        cand = cfg.candidates.get(e.get("arm") or "")
        now = cand.cascade if cand is not None else None
        if cas is not None and (now is None or cas != {"primary": now.primary, "fallback": now.fallback,
                                                        "threshold": now.threshold, "on_no_score": now.on_no_score}):
            raise DeclarationError(
                f"the deployed policy assigns {t!r} to the cascade {e['arm']!r} defined as {cas}, and the candidate "
                f"file now defines it differently; fresh traffic would be checked against a cascade nobody "
                "certified. Give the changed cascade a new name.")
    bound = resolve(decl.bound)
    window, _ = tally_items(compose(fresh, cfg), decl, as_of)
    checks = []
    for t, e in sorted(deployed["task_types"].items()):
        if e.get("status") != CERTIFIED:
            continue
        rs = [r for key, r in window.items() if key[0] == t and key[1] == e["arm"]]
        graded = [r for r in rs if r.graded_runs > 0]
        counted = [r for r in rs if r.verdict is not None]
        n, k = len(counted), sum(r.verdict == "accepted" for r in counted)
        row = {"task_type": t, "arm": e["arm"], "floor": e["floor"], "graded_items": len(graded),
               "items": n, "accepted": k}
        if len(graded) < decl.min_items:
            row.update(verdict="undetermined", why=f"{len(graded)} graded items < min_items {decl.min_items}")
        else:
            lo, hi = bound(k, n, decl.alpha)
            row.update(lower=lo, upper=hi)
            row["verdict"] = ("contradicted" if hi < e["floor"] else "confirmed" if lo >= e["floor"]
                              else "consistent")
        checks.append(row)
    needs = []
    types = sorted(t for t, e in rederived["task_types"].items() if e.get("reason_code") != "no_floor")
    for t in types:
        arms = rederived["task_types"][t].get("arms") or {}
        for a in sorted(cfg.candidates):
            cas = cfg.candidates[a].cascade
            if cas is not None:
                # Measured through its parts, which are listed themselves -- except the items it deferred to a
                # fallback that never answered them, which only the cascade knows about.
                s = arms.get(a) or {}
                gap = sum((s.get(p) or {}).get("fallback_missing_attempts", 0) for p in ("selection", "held_out"))
                if gap:
                    needs.append({"task_type": t, "arm": cas.fallback,
                                  "why": f"{gap} attempt(s) deferred to it by the cascade {a!r} were never made"})
                continue
            s = arms.get(a)
            if s is None:
                needs.append({"task_type": t, "arm": a, "why": "never observed"})
            elif not s["fresh"]:
                needs.append({"task_type": t, "arm": a, "why": f"{s['stale_attempts']} attempt(s), all older than "
                                                                f"max_observation_age_days"})
    # Fresh attempts that never reached a candidate arm -- a router that failed before naming the arm it chose
    # records none. They cannot count for or against any assignment, and a window full of them must not read as
    # quiet, so they are counted beside the checks rather than dropped.
    unattributed: dict[str, dict] = {}
    for o in fresh:
        if o.arm not in cfg.candidates:
            u = unattributed.setdefault(o.task_type, {"attempts": 0, "arms": set(), "reasons": {}})
            u["attempts"] += 1
            u["arms"].add(o.arm)
            u["reasons"][o.reason[:80]] = u["reasons"].get(o.reason[:80], 0) + 1
    unattributed_rows = [{"task_type": t, "attempts": u["attempts"], "arms": sorted(u["arms"]),
                          "reasons": u["reasons"]} for t, u in sorted(unattributed.items())]
    return {"rederivation_changes": changes, "contradiction_checks": checks, "needs_measurement": needs,
            "unattributed_attempts": unattributed_rows,
            # Why a re-derivation may differ besides the evidence: the inputs it was derived under.
            "declarations_changed": deployed.get("declarations") != rederived.get("declarations"),
            "candidates_changed": deployed.get("candidates_digest") != rederived.get("candidates_digest")}


def file_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
