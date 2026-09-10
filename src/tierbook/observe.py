"""Observing the state a policy decides from, and refusing to invent the parts that were not observed.

`decide` is handed a state; this is what produces one. That gap was the first entry in
`decide.MISSING_FOR_A_CLOSED_LOOP`, and it is the difference between a policy that could be deployed and one that
has been.

**Nothing here defaults.** A variable that could not be read is absent from the returned state, with a reason, and
`decide` already treats an absent variable as `uncollected_variable` and declines to certify. That is the whole design:
a fabricated zero for `inflight` reads as an idle engine and sends the next request to the reserved candidate, so the
one value a collector must never guess is the one a naive implementation defaults.

**Every reading carries its own `as_of`.** Section 10 of SCOPE requires estimates to carry freshness limits, and a
state assembled from readings taken minutes apart is not a state. `freshest`/`stalest` are reported so a caller can see
the spread rather than trusting the youngest number in it.

**State keys are qualified by candidate where the quantity is a candidate's.** `decide`'s guards read
`inflight:<candidate>`, not `inflight`, and `var_name` strips the qualifier only for validation -- the lookup itself
uses the whole spec. A collector that emitted a bare `inflight` would produce a state no guard matches, so every rule
would report `uncollected_variable` and every request would take the default while the metrics endpoint answered
perfectly. That happened, and it was caught by wiring this module to `decide` in a test rather than by reading either.
Occupancy and availability are a candidate's; an arrival rate, an authorisation and an evidence age are the family's.

**A rate cannot come from one sample.** `arrival_rate_per_hour` is a derivative of a counter, so a single scrape
refuses and says so; two scrapes with their timestamps give a rate. An implementation that returned a rate from one
reading would be reporting a total as a rate, which is the kind of error that looks like a working collector.

What this does not do: decide anything, choose a candidate, or write a record. `decide` decides and `record` records.
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .decide import STATE_VARS

#: A Prometheus sample line: `name{label="v",...} 1.0`. Written here rather than pulled in as a dependency because
#: the three metrics this reads are a fixed, small set and a parser for them is six lines.
_SAMPLE = re.compile(r"^(?P<name>[A-Za-z_:][\w:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+0-9.eE]+|NaN)\s*$")

#: How many requests a vLLM engine is holding. Both, because a queued request occupies the candidate from the
#: caller's point of view: `waiting` above zero means the seats are already full, and a collector that reported only
#: `running` would report a saturated engine as having room.
RUNNING = "vllm:num_requests_running"
WAITING = "vllm:num_requests_waiting"

#: A monotonic counter of finished requests, which is what an arrival rate is differenced from.
FINISHED = "vllm:request_success_total"

#: Which state variables belong to a candidate rather than to the family. `decide`'s guards read these qualified --
#: `inflight:box` -- because one number called `inflight` cannot describe two candidates.
PER_CANDIDATE = frozenset({"inflight", "available"})


class NotObserved(Exception):
    """A variable could not be read. Carries the reason, because `decide` reports gaps and a gap with no reason is
    indistinguishable from a variable nobody tried to collect."""


@dataclass(frozen=True)
class Reading:
    """One observed value and when it was observed."""

    value: float | bool
    as_of: float
    source: str


@dataclass
class Observation:
    """A state for `decide`, plus what could not be observed and why.

    `state` is deliberately a plain dict of only the variables that were read, so it can be passed straight to
    `decide`, and `decide`'s own `uncollected_variable` gap is what reports the absences. They are also listed here,
    because a caller that logs the state alone loses the reason.
    """

    state: dict = field(default_factory=dict)
    readings: dict = field(default_factory=dict)
    not_observed: dict = field(default_factory=dict)
    #: Which candidate the per-candidate readings belong to, so `complete` knows the names to expect.
    candidate: str = ""

    @property
    def freshest(self) -> float | None:
        return max((r.as_of for r in self.readings.values()), default=None)

    @property
    def stalest(self) -> float | None:
        return min((r.as_of for r in self.readings.values()), default=None)

    @property
    def spread_s(self) -> float | None:
        """How far apart the oldest and youngest readings are. A state assembled over minutes is not a state, and a
        caller cannot see that from the values."""
        if not self.readings:
            return None
        return round(self.freshest - self.stalest, 3)

    @property
    def expected(self) -> set:
        """The state keys a complete observation carries, qualified the way `decide` reads them."""
        out = set()
        for var in STATE_VARS:
            out.add(f"{var}:{self.candidate}" if self.candidate and var in PER_CANDIDATE else var)
        return out

    @property
    def complete(self) -> bool:
        return not self.not_observed and self.state.keys() >= self.expected

    def as_dict(self) -> dict:
        return {
            "state": dict(self.state),
            "readings": {k: {"value": r.value, "as_of": r.as_of, "source": r.source}
                         for k, r in self.readings.items()},
            "not_observed": dict(self.not_observed),
            "spread_s": self.spread_s,
            "complete": self.complete,
        }


def parse_metrics(text: str, name: str, labels: dict | None = None) -> list[tuple[dict, float]]:
    """Every sample of one metric, with its labels. Returns a list rather than a value because a vLLM engine
    exports one series per `model_name` and per `engine`, and summing across models would report another
    candidate's occupancy as this one's."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _SAMPLE.match(line)
        if not m or m.group("name") != name:
            continue
        got = {}
        for part in (m.group("labels") or "").split(","):
            if "=" in part:
                k, _, v = part.partition("=")
                got[k.strip()] = v.strip().strip('"')
        if labels and any(got.get(k) != v for k, v in labels.items()):
            continue
        try:
            got_value = float(m.group("value"))
        except ValueError:
            continue
        # NaN parses as a float and then poisons every comparison downstream: `inflight >= B` is false for NaN, so a
        # saturated engine with one broken series would read as having room. Dropped here, which makes the metric
        # absent, which makes the variable absent, which is the behaviour this module exists to have.
        if got_value != got_value:
            continue
        out.append((got, got_value))
    return out


def _sum_metric(text: str, name: str, labels: dict | None) -> float:
    samples = parse_metrics(text, name, labels)
    if not samples:
        raise NotObserved(f"{name} is absent from the metrics this endpoint served"
                          + (f" for {labels}" if labels else ""))
    return sum(v for _, v in samples)


def fetch(url: str, timeout: float = 5.0) -> str:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as fh:      # noqa: S310 - an operator-supplied URL
            return fh.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise NotObserved(f"{url} did not answer: {type(exc).__name__}: {exc}") from exc


def inflight(metrics_text: str, model_name: str | None = None) -> float:
    """Running plus waiting. See `RUNNING`/`WAITING` for why both."""
    labels = {"model_name": model_name} if model_name else None
    return _sum_metric(metrics_text, RUNNING, labels) + _sum_metric(metrics_text, WAITING, labels)


def arrival_rate_per_hour(before: tuple[float, float], after: tuple[float, float]) -> float:
    """Two `(counter, timestamp)` readings into a rate.

    Refuses a single sample, a zero interval and a counter that went backwards. The last of those is a restart, not
    a negative rate, and a collector that returned the difference would report a large negative arrival rate for a
    candidate that had just come back.
    """
    (c0, t0), (c1, t1) = before, after
    if t1 <= t0:
        raise NotObserved(f"the two readings are {t1 - t0:.3f}s apart, so no rate can be differenced from them")
    if c1 < c0:
        raise NotObserved(f"the counter went backwards ({c0} -> {c1}), which is a restart and not a negative rate")
    return (c1 - c0) / (t1 - t0) * 3600.0


def evidence_age_days(measured_on: str, now: float | None = None) -> float:
    """How old the evidence a policy was compiled from is, in days.

    From the policy's own `measured_on`, because a policy that does not carry the date of its evidence cannot expire,
    and section 10 requires estimates to stop being usable rather than to fade.
    """
    import datetime as _dt

    try:
        day = _dt.date.fromisoformat(measured_on)
    except (TypeError, ValueError) as exc:
        raise NotObserved(f"measured_on {measured_on!r} is not an ISO date, so the evidence has no age") from exc
    now = time.time() if now is None else now
    then = _dt.datetime(day.year, day.month, day.day, tzinfo=_dt.timezone.utc).timestamp()
    return round((now - then) / 86400.0, 3)


def observe(*, candidate: str = "", metrics_url: str | None = None, model_name: str | None = None,
            gateway_authorised: bool | None = None, measured_on: str | None = None,
            previous: dict | None = None, now: float | None = None,
            fetcher=fetch) -> Observation:
    """Assemble a state from whatever can be read, and say what could not be.

    `previous` carries the counter reading from the last call, which is what makes `arrival_rate_per_hour`
    obtainable at all: pass the `counter` entry from a previous `Observation.as_dict()["readings"]`.

    `gateway_authorised` is passed in rather than probed. Whether the gateway will authorise spend is a question
    about a budget and a tenant, and guessing it from an endpoint being reachable would answer a different question.
    """
    now = time.time() if now is None else now
    obs = Observation(candidate=candidate)

    def key(var: str) -> str:
        return f"{var}:{candidate}" if candidate and var in PER_CANDIDATE else var

    def record(var: str, value, source: str) -> None:
        obs.state[key(var)] = value
        obs.readings[key(var)] = Reading(value=value, as_of=now, source=source)

    def refuse(var: str, why: str) -> None:
        obs.not_observed[key(var)] = why

    text = None
    if metrics_url:
        try:
            text = fetcher(metrics_url)
            record("available", True, metrics_url)
        except NotObserved as exc:
            # An endpoint that does not answer IS an observation of `available`, and the only one here that is
            # safe to conclude from a failure: the others stay absent.
            record("available", False, metrics_url)
            refuse("inflight", str(exc))
            refuse("arrival_rate_per_hour", str(exc))
    else:
        refuse("available", "no metrics url was given, so nothing was asked")
        refuse("inflight", "no metrics url was given, so nothing was asked")
        refuse("arrival_rate_per_hour", "no metrics url was given, so nothing was asked")

    if text is not None:
        try:
            record("inflight", inflight(text, model_name), f"{metrics_url} ({RUNNING}+{WAITING})")
        except NotObserved as exc:
            refuse("inflight", str(exc))
        try:
            counter = _sum_metric(text, FINISHED, {"model_name": model_name} if model_name else None)
            obs.readings["counter"] = Reading(value=counter, as_of=now, source=f"{metrics_url} ({FINISHED})")
            prev = (previous or {}).get("counter")
            if prev is None:
                    refuse("arrival_rate_per_hour",
                       "a rate is a difference of two counter readings and this is the first; pass the previous "
                       "reading as `previous` to obtain one")
            else:
                record("arrival_rate_per_hour",
                       arrival_rate_per_hour((prev["value"], prev["as_of"]), (counter, now)),
                       f"{metrics_url} ({FINISHED}, differenced)")
        except NotObserved as exc:
            refuse("arrival_rate_per_hour", str(exc))

    if gateway_authorised is None:
        refuse("metered_authorised",
               "not passed. Whether the gateway authorises spend is a question about a budget and a tenant, and it "
               "is not inferable from an endpoint being reachable")
    else:
        record("metered_authorised", bool(gateway_authorised), "supplied by the caller")

    if measured_on is None:
        refuse("evidence_age_days", "the policy did not carry a measured_on, so its evidence has no age")
    else:
        try:
            record("evidence_age_days", evidence_age_days(measured_on, now), f"policy measured_on={measured_on}")
        except NotObserved as exc:
            refuse("evidence_age_days", str(exc))

    return obs
