"""The one record the certification plane reads: one attempt of one item by one arm.

An observation says what happened and what it consumed. A choice is never made on what it cost in money: price is
applied later, from the candidate file, so that a price change re-derives a policy without re-measuring anything.
A billed amount, where the source knows it, is recorded beside the tokens for reconciliation only. Quality is a
rate the certifier computes over many of these; an observation never says whether an arm is good.

`usage` is empty when the source did not report consumption. Empty is not zero: an arm whose graded answers carry no
usage cannot be priced, rather than being priced as free.

Acceptance is the caller's verdict. A test suite, an exact-match key, a human label -- tierbook does not grade and
does not know which grader was used beyond the `grader` string the caller records.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from tierbook.evidence import EvidenceError

#: What an attempt can have come to. Closed because these are the only three states an attempt can be in, not a
#: judgement about which attempts matter: either the caller's grader accepted it, rejected it, or never saw an
#: answer it could grade. Whether the third counts against a rate is the caller's `unobserved_as` declaration; either
#: way it is counted beside the rate, so an arm that fails silently is visible.
OUTCOMES = ("accepted", "rejected", "unobserved")

#: Token kinds a price card can bill differently. Names are the candidate file's `price_per_mtok` keys.
USAGE_KEYS = ("fresh_in", "cached_in", "out")

FORMAT = 1


@dataclass(frozen=True)
class Observation:
    item: str
    task_type: str
    arm: str
    outcome: str
    usage: dict[str, int] = field(default_factory=dict)
    billed_usd: float | None = None
    latency_s: float | None = None
    run: str = ""
    reason: str = ""
    grader: str = ""
    observed_at: str = ""
    label_source: str = ""
    finish_reason: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise EvidenceError(f"outcome must be one of {OUTCOMES}, not {self.outcome!r} (item {self.item!r})")
        if self.outcome == "unobserved" and not self.reason:
            raise EvidenceError(
                f"item {self.item!r} on arm {self.arm!r} is unobserved with no reason; an attempt that produced "
                "nothing gradable must say why, or a transport failure and an empty answer become the same row")
        for k, v in self.usage.items():
            if k not in USAGE_KEYS:
                raise EvidenceError(f"usage key {k!r} is not one of {USAGE_KEYS} (item {self.item!r})")
            if not isinstance(v, int) or v < 0:
                raise EvidenceError(f"usage {k}={v!r} must be a non-negative integer token count")
        if self.observed_at:
            try:
                datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
            except ValueError:
                raise EvidenceError(f"observed_at {self.observed_at!r} is not ISO 8601 (item {self.item!r})") from None
        if self.billed_usd is not None and self.billed_usd < 0:
            raise EvidenceError(f"billed_usd {self.billed_usd!r} is negative")
        for name in ("item", "task_type", "arm"):
            if not getattr(self, name):
                raise EvidenceError(f"an observation needs a non-empty {name}")

    def to_row(self) -> dict:
        row = {"format": FORMAT, "item": self.item, "task_type": self.task_type, "arm": self.arm,
               "outcome": self.outcome, "usage": dict(self.usage)}
        for name in ("billed_usd", "latency_s"):
            if getattr(self, name) is not None:
                row[name] = getattr(self, name)
        for name in ("run", "reason", "grader", "observed_at", "label_source", "finish_reason", "source"):
            if getattr(self, name):
                row[name] = getattr(self, name)
        return row

    @classmethod
    def from_row(cls, row: dict) -> "Observation":
        fmt = row.get("format", FORMAT)
        if fmt > FORMAT:
            raise EvidenceError(f"observation format {fmt} is newer than this reader ({FORMAT})")
        known = {"format", "item", "task_type", "arm", "outcome", "usage", "billed_usd", "latency_s", "run",
                 "reason", "grader", "observed_at", "label_source", "finish_reason", "source"}
        unknown = sorted(set(row) - known)
        if unknown:
            raise EvidenceError(f"unknown observation keys {unknown}; a field this reader drops silently is a "
                                "field a later reader trusts that was never applied")
        return cls(item=str(row.get("item", "")), task_type=str(row.get("task_type", "")),
                   arm=str(row.get("arm", "")), outcome=str(row.get("outcome", "")),
                   usage={k: int(v) for k, v in (row.get("usage") or {}).items()},
                   billed_usd=row.get("billed_usd"), latency_s=row.get("latency_s"),
                   run=str(row.get("run", "")), reason=str(row.get("reason", "")),
                   grader=str(row.get("grader", "")), observed_at=str(row.get("observed_at", "")),
                   label_source=str(row.get("label_source", "")), finish_reason=str(row.get("finish_reason", "")),
                   source=str(row.get("source", "")))


def read(paths: str | Path | Iterable[str | Path]) -> list[Observation]:
    """Every observation in one or more JSONL files, with the line that failed named on a bad row."""
    if isinstance(paths, (str, Path)):
        paths = [paths]
    out: list[Observation] = []
    for path in paths:
        for n, line in enumerate(Path(path).read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                out.append(Observation.from_row(json.loads(line)))
            except (EvidenceError, json.JSONDecodeError, TypeError, ValueError) as e:
                raise EvidenceError(f"{path}:{n}: {e}") from None
    return out


def write(observations: Iterable[Observation], path: str | Path, *, append: bool = False) -> int:
    n = 0
    with open(path, "a" if append else "w") as f:
        for o in observations:
            f.write(json.dumps(o.to_row(), sort_keys=True) + "\n")
            n += 1
    return n


def digest(observations: Iterable[Observation]) -> str:
    """Order-independent content hash, so a policy can name exactly the evidence it was derived from."""
    rows = sorted(json.dumps(o.to_row(), sort_keys=True) for o in observations)
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]


def from_chat_completion(response: dict, *, item: str, task_type: str, arm: str, outcome: str,
                         latency_s: float | None = None, **extra) -> Observation:
    """An observation from an OpenAI-compatible chat completion body.

    Both spellings of the token counts are read (`prompt_tokens`/`completion_tokens`, `input_tokens`/`output_tokens`)
    and both cache fields seen in the wild (`prompt_tokens_details.cached_tokens`, `cache_read_input_tokens`). On the
    OpenAI spelling, cached tokens are part of `prompt_tokens` and fresh input is the difference; on the Anthropic
    spelling they are not. Usage is left EMPTY -- unknown, not zero -- when either count is missing, or when the
    cached count exceeds `prompt_tokens`, which says the wire does not follow the OpenAI convention and the split
    between fresh and cached input cannot be read off it.
    """
    u = response.get("usage") or {}
    prompt = u.get("prompt_tokens", u.get("input_tokens"))
    completion = u.get("completion_tokens", u.get("output_tokens"))
    cached = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens"))
                 or u.get("cache_read_input_tokens") or 0)
    usage: dict[str, int] = {}
    if prompt is not None and completion is not None:
        prompt = int(prompt)
        if "prompt_tokens" not in u:
            usage = {"fresh_in": prompt, "cached_in": cached, "out": int(completion)}
        elif cached <= prompt:
            usage = {"fresh_in": prompt - cached, "cached_in": cached, "out": int(completion)}
    # Recorded, not interpreted. An answer cut off at the output budget and graded wrong is the grader's verdict on
    # what came back; the finish reason is what lets a reader see that the budget, not the arm, may have decided it.
    choices = response.get("choices") or [{}]
    finish = str((choices[0] or {}).get("finish_reason") or "")
    return Observation(item=item, task_type=task_type, arm=arm, outcome=outcome, usage=usage, latency_s=latency_s,
                       finish_reason=finish, **extra)


def by_key(observations: Iterable[Observation]) -> Iterator[tuple[tuple[str, str], list[Observation]]]:
    groups: dict[tuple[str, str], list[Observation]] = {}
    for o in observations:
        groups.setdefault((o.task_type, o.arm), []).append(o)
    yield from sorted(groups.items())


def ingest_chat_log(source_rows: Iterable[dict], outcome_rows: Iterable[dict], *,
                    source: str = "") -> list[Observation]:
    """Join a chat-completions call log to the caller's grades, by `(item, arm, run)`.

    A source row carries `item`, `task_type`, `arm`, optional `run`, `latency_s`, `observed_at`, `label_source`,
    and either `response` (the completion body) or `error` (why no body came back). An outcome row carries `item`,
    `arm`, optional `run`, `outcome` (`accepted` | `rejected` | `unobserved`), optional `reason` and `grader`.

    Mapping and joining only. A call with no grade becomes `unobserved: ungraded`; a call that errored becomes
    `unobserved` with the error as its reason. A grade for a call that errored is refused rather than overridden:
    the two files disagree about whether there was an answer, and choosing between them is not a mapping. A grade
    with no call is refused too: it would be an outcome nobody paid for. `billed_usd` on a source row is carried.
    """
    grades: dict[tuple[str, str, str], dict] = {}
    for g in outcome_rows:
        key = (str(g["item"]), str(g["arm"]), str(g.get("run", "")))
        if key in grades:
            raise EvidenceError(f"two grades for {key}")
        grades[key] = g
    out: list[Observation] = []
    seen: set[tuple[str, str, str]] = set()
    for r in source_rows:
        key = (str(r["item"]), str(r["arm"]), str(r.get("run", "")))
        if key in seen:
            raise EvidenceError(f"two calls for {key}; give repeated attempts distinct runs")
        seen.add(key)
        common = dict(item=key[0], task_type=str(r["task_type"]), arm=key[1], run=key[2],
                      latency_s=r.get("latency_s"), observed_at=str(r.get("observed_at", "")),
                      label_source=str(r.get("label_source", "")), source=source,
                      billed_usd=r.get("billed_usd"))
        g = grades.get(key)
        if (r.get("error") or not r.get("response")) and g is not None:
            raise EvidenceError(f"{key} has a grade but the call returned no answer ({r.get('error')!r})")
        if r.get("error") or not r.get("response"):
            reason = str(r.get("error") or "no response body")
            body = r.get("response") or {}
            obs = from_chat_completion(body, outcome="unobserved", reason=reason[:300], **common)
        elif g is None:
            obs = from_chat_completion(r["response"], outcome="unobserved", reason="ungraded", **common)
        else:
            obs = from_chat_completion(r["response"], outcome=str(g["outcome"]), reason=str(g.get("reason", "")),
                                       grader=str(g.get("grader", "")), **common)
        out.append(obs)
    orphans = sorted(set(grades) - seen)
    if orphans:
        raise EvidenceError(f"{len(orphans)} grades match no call, e.g. {orphans[:3]}")
    return out
