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
import math
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

#: The newest format this reader understands. A row is written in the oldest format that can carry it: 5 only when it
#: names an `arm_harness`, 4 only when it names an `arm_artifact`, 3 only when it names an `arm_version` or a `path`,
#: 2 only when it has a `score`, so an older file stays readable by an older reader.
FORMAT = 5


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
    #: The arm's own score for this attempt (a confidence, a probability, a margin), as the arm reported it. Read only
    #: by a cascade that routes on it; tierbook does not interpret its scale.
    score: float | None = None
    #: The exact thing that answered, as the sender names it (a weights digest, an image digest, or any composition).
    #: Opaque: tierbook compares it for equality and never parses it. Empty means the sender did not say, which is not
    #: the same as "the same as every other row".
    arm_version: str = ""
    #: The stored artifact that answered, as the sender names it -- what a trainer can name at save time, before any
    #: server has loaded it (perigraph's artifact identity is one such name). Opaque like `arm_version`, and compared
    #: only against an arm's provenance: `arm_version` names what answered, which a trainer cannot know in advance.
    arm_artifact: str = ""
    #: What surrounded the model for this attempt, as the sender names it: the system text, the wrapper around the item,
    #: the decoding settings -- whatever the sender composes (perigraph's harness identity is one such name). Opaque and
    #: compared for equality only, like `arm_version`: the same weights answer differently under a different wrapper,
    #: so two harnesses under one arm name pool two configurations. Empty means the sender did not say.
    arm_harness: str = ""
    #: The component arms that actually ran for this attempt, in order, when `arm` names something that routes inside
    #: itself (a router assigned this request, then a student and a fallback answered). Recorded for the reader and
    #: listed by `check-observations`; a rate is never split by it, because the router's choice is part of the arm.
    path: tuple[str, ...] = ()

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
        if self.score is not None and (isinstance(self.score, bool) or not isinstance(self.score, (int, float))
                                       or not math.isfinite(self.score)):
            raise EvidenceError(f"score {self.score!r} must be a finite number (item {self.item!r})")
        if self.billed_usd is not None and self.billed_usd < 0:
            raise EvidenceError(f"billed_usd {self.billed_usd!r} is negative")
        for name in ("item", "task_type", "arm"):
            if not getattr(self, name):
                raise EvidenceError(f"an observation needs a non-empty {name}")
        for name in ("arm_version", "arm_artifact", "arm_harness"):
            if not isinstance(getattr(self, name), str):
                raise EvidenceError(f"{name} must be a string, not {type(getattr(self, name)).__name__}")
        if not isinstance(self.path, tuple) or not all(isinstance(a, str) and a for a in self.path):
            raise EvidenceError(f"path must be a list of non-empty arm names, not {self.path!r} (item {self.item!r})")

    def to_row(self) -> dict:
        fmt = (5 if self.arm_harness else 4 if self.arm_artifact else 3 if (self.arm_version or self.path)
               else 2 if self.score is not None else 1)
        row = {"format": fmt, "item": self.item, "task_type": self.task_type, "arm": self.arm,
               "outcome": self.outcome, "usage": dict(self.usage)}
        for name in ("billed_usd", "latency_s", "score"):
            if getattr(self, name) is not None:
                row[name] = getattr(self, name)
        for name in ("run", "reason", "grader", "observed_at", "label_source", "finish_reason", "source",
                     "arm_version", "arm_artifact", "arm_harness"):
            if getattr(self, name):
                row[name] = getattr(self, name)
        if self.path:
            row["path"] = list(self.path)
        return row

    @classmethod
    def from_row(cls, row: dict) -> "Observation":
        fmt = row.get("format", FORMAT)
        if fmt > FORMAT:
            raise EvidenceError(f"observation format {fmt} is newer than this reader ({FORMAT})")
        if fmt < 2 and "score" in row:
            raise EvidenceError(f"a format-{fmt} observation carries `score`, which format 2 introduced; a format-1 "
                                "reader would refuse this row")
        if fmt < 3 and ("arm_version" in row or "path" in row):
            raise EvidenceError(f"a format-{fmt} observation carries `arm_version` or `path`, which format 3 "
                                "introduced; an older reader would refuse this row")
        if fmt < 4 and "arm_artifact" in row:
            raise EvidenceError(f"a format-{fmt} observation carries `arm_artifact`, which format 4 introduced; an "
                                "older reader would refuse this row")
        if fmt < 5 and "arm_harness" in row:
            raise EvidenceError(f"a format-{fmt} observation carries `arm_harness`, which format 5 introduced; an "
                                "older reader would refuse this row")
        known = {"format", "item", "task_type", "arm", "outcome", "usage", "billed_usd", "latency_s", "run",
                 "reason", "grader", "observed_at", "label_source", "finish_reason", "source", "score",
                 "arm_version", "arm_artifact", "arm_harness", "path"}
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
                   source=str(row.get("source", "")), score=row.get("score"),
                   arm_version=row.get("arm_version", ""), arm_artifact=row.get("arm_artifact", ""),
                   arm_harness=row.get("arm_harness", ""),
                   path=tuple(row["path"]) if isinstance(row.get("path"), list) else row.get("path", ()))


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
    observations = list(observations)
    for o in observations:
        if type(o) is not Observation:
            raise EvidenceError(f"{type(o).__name__} for {(o.task_type, o.arm, o.item, o.run)} is derived, not "
                                "observed, and is never written as evidence")
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
                         latency_s: float | None = None, cache_additive: bool = False, **extra) -> Observation:
    """An observation from an OpenAI-compatible chat completion body.

    Both spellings of the token counts are read (`prompt_tokens`/`completion_tokens`, `input_tokens`/`output_tokens`)
    and both cache fields seen in the wild (`prompt_tokens_details.cached_tokens`, `cache_read_input_tokens`).

    Whether cached tokens are part of the prompt count is a property of the wire, and one endpoint can serve both: an
    OpenAI-family model's `prompt_tokens` includes them (the OpenAI meaning), while a gateway that renders an
    Anthropic-family response onto the same shape may report them beside it. `cache_additive=True` says the second
    holds for this arm; the caller knows its gateway and this function does not guess. The `input_tokens` spelling is
    additive by definition.

    Usage is left EMPTY -- unknown, not zero -- when a count is missing; when cached tokens exceed a prompt count
    that is supposed to contain them, which says the declared meaning is wrong for this wire; and when cache WRITES
    are reported, because no price-card kind bills them and pricing them as fresh input would be a guess.
    """
    u = response.get("usage") or {}
    details = u.get("prompt_tokens_details") or {}
    prompt = u.get("prompt_tokens", u.get("input_tokens"))
    completion = u.get("completion_tokens", u.get("output_tokens"))
    cached = int(details.get("cached_tokens") or u.get("cache_read_input_tokens") or 0)
    writes = int(details.get("cache_write_tokens") or u.get("cache_creation_input_tokens") or 0)
    usage: dict[str, int] = {}
    if prompt is not None and completion is not None and writes == 0:
        prompt = int(prompt)
        if cache_additive or "prompt_tokens" not in u:
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
                    source: str = "", cache_additive_arms: Iterable[str] = ()) -> list[Observation]:
    """Join a chat-completions call log to the caller's grades, by `(item, arm, run)`.

    A source row carries `item`, `task_type`, `arm`, optional `run`, `latency_s`, `observed_at`, `label_source`,
    `score` (the arm's own score for the answer, for a cascade to route on), and either `response` (the completion body) or `error` (why no body came back). An outcome row carries `item`,
    `arm`, optional `run`, `outcome` (`accepted` | `rejected` | `unobserved`), optional `reason` and `grader`.

    Mapping and joining only. A call with no grade becomes `unobserved: ungraded`; a call that errored becomes
    `unobserved` with the error as its reason. A grade for a call that errored is refused rather than overridden:
    the two files disagree about whether there was an answer, and choosing between them is not a mapping. A grade
    with no call is refused too: it would be an outcome nobody paid for. `billed_usd` on a source row is carried.
    `cache_additive_arms` names the arms whose gateway reports cached tokens beside the prompt count rather than in
    it (see `from_chat_completion`).
    """
    additive = frozenset(cache_additive_arms)
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
                      billed_usd=r.get("billed_usd"), score=r.get("score"), cache_additive=key[1] in additive)
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
