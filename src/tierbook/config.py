"""What may be considered, kept mechanically separate from what was observed.

Two files, and the boundary between them is the whole point:

    candidates.json   what MAY be measured -- reachable endpoints, and the priced inputs no measurement
                      can produce. Every value in it is an unverified claim by whoever wrote it.
    <ledger>/tiers/   what WAS observed. Only this can route.

The separation is enforced rather than described. A key that exists in the record schema is **illegal in a
candidate entry**, so a hand-written "accuracy": 0.9 or "solved": 18 cannot be smuggled into the thing the
compiler trusts by editing the easier file. This is mechanical on purpose: a rule that lives in prose is a
rule that a busy operator edits around at two in the morning.

Two refusals sit here rather than in a document:

  * **a candidate that describes how to START a model is rejected.** `image`, `weights`, `launch`, `command`,
    `replicas`, `gpu` and their kin belong to whoever owns the cluster. This component decides where a
    request goes; it does not own a lifecycle, and the way to mean that is for the file to fail to load.
  * **a candidate is not a measurement.** A candidate with no records is visible as unmeasured, and routing
    to it raises. Removing a candidate de-lists it and never deletes its records: the ledger is append-only,
    because a decision made last week must stay explicable after the candidate is gone.

Discovery from a gateway is a stationery printer, not a runtime feature. `tierbook discover` prints a draft
candidate file for a human to edit and commit. Reading a live model list at compile or route time would make
a routing decision depend on a gateway's publication state that nobody committed to, which is the one thing
this project exists to refuse.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: Bumped to 2 when `families` stopped mapping a family to a bare reference-candidate string and started
#: mapping it to an object -- see `FamilyDeclaration`. The floor moved here because SCOPE sections 2, 5 and 12
#: all call it "the family's floor": a single `--floor` flag shared by every family in the ledger was a wrong
#: answer with nothing to compare it against, which is worse than the defect it was meant to fix.
CONFIG_FORMAT = 2

# Keys that describe how to bring a model into existence rather than how to reach one. Rejected with the
# name of the boundary they cross, because the person who wrote them is usually doing something reasonable
# in the wrong file.
LIFECYCLE_KEYS = (
    "image", "images", "weights", "model_path", "checkpoint", "launch", "command", "args", "entrypoint",
    "replicas", "gpu", "gpus", "accelerator", "resources", "node_selector", "nodeSelector", "tolerations",
    "helm", "chart", "manifest", "kustomize", "docker", "compose", "systemd", "engine_args", "serve",
)

# Keys that only a measurement may set. Derived from the record schema at load time so the two cannot drift,
# with a small identity allowlist: a candidate must be able to say which tier it is, or the join has no key.
JOIN_KEYS = frozenset({"id", "schema_version"})


class ConfigError(ValueError):
    """A candidate file that cannot be loaded, with the boundary it crossed named in the message."""


@dataclass(frozen=True)
class Endpoint:
    """How to reach a candidate. Generic by construction: anything that speaks an OpenAI-compatible wire.

    `base_url` is a URL and nothing more. A gateway in front, a vendor API, a model server on the cluster
    next door, something behind a corporate proxy -- this module cannot tell them apart and deliberately does
    not try. `deployment` distinguishes them only where the *cost model* must differ: a per-token bill and an
    hourly bill are arithmetic, not architecture.

    `gateway_version` pins whatever sits in front. This matters for the same reason `revision` does and is
    more tractable: a provider will not tell you which checkpoint is behind an alias, but a gateway you or
    your organisation runs can be asked which version it is. A gateway changes what a measurement means --
    it decides the wire, the parameters it forwards, the prices it charges against, and what it reports as
    success -- so a record taken against one version does not describe another. Pinned here, recorded in the
    measurement, and checked before routing.
    """

    base_url: str
    model: str
    wire: str = "chat"                  # "chat" | "responses"; declared, then pre-flighted before measuring
    api_key_env: str | None = None      # the NAME of an environment variable, never a key
    revision: str | None = None         # pinned identity, checked against the record at route time
    gateway_version: str | None = None  # the pinned version of whatever sits in front, if anything does
    refuses_params: tuple[str, ...] = ()  # parameters this endpoint rejects, discovered by pre-flight
    headers: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 600.0


@dataclass(frozen=True)
class Candidate:
    """One thing that may be measured, and the priced inputs measurement cannot produce.

    Prices live here because they are quoted, not observed -- but the record that consumes them cites them,
    so a price change invalidates the record rather than silently repricing an old decision.
    """

    id: str
    endpoint: Endpoint
    deployment: str                       # "api" (per token) | "self_hosted" (per hour)
    price_per_mtok: dict[str, float] | None = None   # api: fresh_in / cached_in / out
    hourly_usd: float | None = None                  # self_hosted: the bill while it is up
    note: str = ""

    @property
    def is_fixed_cost(self) -> bool:
        return self.deployment == "self_hosted"


@dataclass(frozen=True)
class Objective:
    """One objective and the constraints that cannot be switched off.

    There are no axis switches. Three checkboxes labelled accuracy, performance and cost would misdescribe
    the problem in a way that leaks into every later decision:

      * **accuracy is a constraint, not a preference.** There is no syntax for removing `margin`, because a
        router that may trade quality for money without a stated bound is choosing an unstated exchange rate
        on its owner's behalf.
      * **reliability cannot be deselected because it is the denominator.** Both objectives are computed to
        *acceptance*, not per attempt: a failure means paying the attempt again, in dollars if the objective
        is cost and in seconds if it is latency. Measured here once: retries reordered the arrangements.
      * **latency is not automatically a constraint.** For a fixed-capacity tier it is an input to the cost
        model, via throughput. Turning that into an SLO would invent a requirement nobody stated. If an SLO
        is genuinely wanted it is written down, separately and optionally.

    Weights are refused rather than defaulted. Once quality is a weighted term, "cheapest" stops denoting
    anything a reader can check.
    """

    objective: str = "cost"               # "cost" | "latency", each expected-to-acceptance
    margin: float = 0.15                  # mandatory: no key removes it
    alpha: float = 0.05
    latency_slo_p95_ms: float | None = None
    min_completion_probability: float | None = None
    max_age_days: int = 90

    def __post_init__(self) -> None:
        if self.objective not in ("cost", "latency"):
            raise ConfigError(f"objective must be 'cost' or 'latency', not {self.objective!r}")
        if not 0.0 < self.margin < 1.0:
            raise ConfigError(f"margin must be a solve-rate difference in (0, 1), not {self.margin!r}")


@dataclass(frozen=True)
class FamilyDeclaration:
    """One family's row in the candidate file -- what an operator declares rather than what a measurement
    produces, keyed by the family it is about.

    `floor` lives here, not in a flag, because it is stated in exactly those words as a per-family fact by
    SCOPE sections 2, 5 and 12 ("the family's floor"), and it is what the compiled policy's thresholds are
    derived against (A2.1) -- supplying it is right, deriving it would not be. A single command-line flag
    shared by every family in a ledger let two families with different requirements silently share whichever
    number was typed, which is worse than the config_format 1 defect this replaced: that defect at least left
    a second typed number to compare against, and one flag for two families leaves nothing to compare at all.

    C4 (SEAMS.md S1, amendment 4) appends `label_source`, `max_label_latency_s` and
    `label_independent_of_candidate` to this same object rather than to the record schema. `Log.attach_outcome`
    exists and nothing calls it, and exploration on top of an unjoinable log would produce randomised
    assignments nobody can learn from -- so a family declares HOW its future traffic gets a label before it may
    declare a rate to explore with. Amendment 4 found the schema (`schema.json`) already names this concept as
    `oracle.kind`, ordered strongest to weakest, plus the gate `oracle.independent_of_candidate` ("a standard
    produced by a model that is also a candidate scores that candidate perfectly by construction"). Reusing
    that vocabulary rather than inventing a second, coarser one is the whole point of the amendment: a
    hardcoded second copy is exactly the drift it exists to remove.

    `label_source` is one of `oracle.kind`'s seven values, read from the schema at load time, or `none` -- the
    one state a measurement record has no reason to express, because a measurement always has a label by the
    time it is written.

    `max_label_latency_s` is `None` if and only if `label_source` is `none`: a family with no labeller has no
    latency to wait out, and a family with one must say how long to wait for it.

    `label_independent_of_candidate` has no default. `False` is a legitimate declaration, not a bug -- an
    operator may be running a judge that is also a candidate in the same family and must be able to say so --
    and it costs the family its exploration rate for the same reason `label_source: none` does: a candidate
    grading itself is not evidence, so exploring to generate evidence a self-graded judge cannot supply buys
    nothing.

    `exploration_rate` is the one optional key here (C3 draws with it; this entry only decides when it may
    exist at all). `load_config` refuses it outright when the family cannot represent what it would mean --
    that is a load failure, not a runtime discovery, because the combination has no meaning for `explore.draw`
    to discover.

    `staleness_limit_days` (amendment 5) is required and refused when absent, like C4's three fields above --
    the same reasoning applies without change: it is per family for the same reason the floor is (how stale a
    bound THIS family's operator will accept, which no measurement settles), and C2's `compile --floor` mistake
    is exactly what amendment 5 found this field about to repeat if it were left to invent its own supply point.
    `null` is a legitimate declaration meaning no limit -- an operator may have no evidence-age concern for a
    family that never explores. But `null` combined with a present `exploration_rate` is refused: the door C3
    opens exists to reach a candidate whose evidence expired (`explore.clears_floor` overrides
    `max_evidence_age_days` for exactly that candidate), so an unbounded staleness there is a bound from any
    past environment at all, not a declared one. A family may decline to state a limit, or may explore, but not
    both.
    """

    reference: str
    floor: float
    label_source: str
    max_label_latency_s: float | None
    label_independent_of_candidate: bool
    staleness_limit_days: float | None
    exploration_rate: float | None = None


@dataclass(frozen=True)
class Config:
    candidates: dict[str, Candidate]
    families: dict[str, FamilyDeclaration]      # family -> its declaration
    objective: Objective
    throughput_per_family: dict[str, float] = field(default_factory=dict)
    source: str = ""

    def reference_for(self, family: str) -> str:
        try:
            return self.families[family].reference
        except KeyError:
            raise ConfigError(
                f"no reference candidate configured for family {family!r}; the configured families are "
                f"{sorted(self.families)}"
            ) from None


def _record_schema_keys(schema_path: str | Path | None = None) -> frozenset[str]:
    """Every key a record may set, so a candidate entry can be refused for setting one.

    Read from the schema rather than listed here: a hand-maintained copy of this set would fall behind the
    schema, and the first field it missed would be the one someone hand-edited.

    Defaults to the schema packaged with the code, and raises rather than returning an empty set when it is
    missing. An earlier version fell back to "no forbidden keys" when it could not find a schema file, which
    silently disabled this refusal in exactly the case that matters -- a candidate file deployed on its own,
    nowhere near a ledger.
    """
    from tierbook import SCHEMA_PATH

    p = Path(schema_path) if schema_path is not None else SCHEMA_PATH
    if not p.exists():
        raise ConfigError(
            f"the record schema is missing at {p}. It is what decides which keys a candidate file may not "
            "contain, so loading configuration without it would drop that check rather than apply it."
        )
    schema = json.loads(p.read_text())
    keys: set[str] = set(schema.get("properties") or {})
    fam = ((schema.get("properties") or {}).get("families") or {})
    for holder in ("additionalProperties", "patternProperties"):
        node = fam.get(holder)
        if isinstance(node, dict):
            for sub in ([node] if "properties" in node else node.values()):
                if isinstance(sub, dict):
                    keys |= set(sub.get("properties") or {})
    return frozenset(keys - JOIN_KEYS)


def _label_source_values(schema_path: str | Path | None = None) -> frozenset[str]:
    """The vocabulary a family's `label_source` may take: `oracle.kind`'s seven values, read from the record
    schema, plus `none`.

    Read from the schema rather than copied here, for the reason amendment 4 exists at all: `oracle.kind` is
    the schema's own name for what decided an outcome, ordered strongest to weakest, and a hand-typed second
    copy of those seven strings would drift the moment the schema gained an eighth -- the loader would go on
    accepting the seven it remembers and silently refuse the new one, which is a worse failure than never
    checking, because it looks like a check that is still working.

    `none` is not read from the schema. It is the one value a measurement record has no reason to express --
    every record that exists was written because something produced a label -- so it is added here, once, as
    the online-traffic case the offline vocabulary was never asked to cover.

    Raises rather than returning an empty set when the schema file is missing, matching `_record_schema_keys`:
    a silent fallback here would accept every string as a `label_source`, refusing nothing where a real check
    exists, in exactly the deployment -- a candidate file shipped on its own -- where the check matters most.
    """
    from tierbook import SCHEMA_PATH

    p = Path(schema_path) if schema_path is not None else SCHEMA_PATH
    if not p.exists():
        raise ConfigError(
            f"the record schema is missing at {p}. It is what decides which label_source values a family may "
            "declare, so loading configuration without it would drop that check rather than apply it."
        )
    schema = json.loads(p.read_text())
    kind_enum = (((schema.get("properties") or {}).get("oracle") or {}).get("properties") or {}).get("kind", {})
    values = kind_enum.get("enum") or []
    if not values:
        raise ConfigError(
            f"{p} carries no oracle.kind enum to read label_source from -- the schema this loader was given "
            "is not the one label_source is defined against."
        )
    return frozenset(values) | {"none"}


def _reject_illegal(cid: str, raw: dict, observed: frozenset[str]) -> None:
    lifecycle = sorted(k for k in raw if k in LIFECYCLE_KEYS)
    if lifecycle:
        raise ConfigError(
            f"candidate {cid!r} sets {lifecycle}, which describes how to START a model rather than how to "
            "reach one. Serving is the cluster owner's responsibility; tierbook connects to what is already "
            "running. Give it a base_url instead."
        )
    measured = sorted(k for k in raw if k in observed)
    if measured:
        raise ConfigError(
            f"candidate {cid!r} sets {measured}, which only a measurement may set -- those keys exist in the "
            "record schema. Configuration says what may be measured; the ledger says what was observed, and "
            "only the ledger can route. Measure it and write a record."
        )


def load_config(path: str | Path, *, schema: str | Path | None = None) -> Config:
    """Read a candidate file, refusing the two things it must not contain."""
    p = Path(path)
    raw = json.loads(p.read_text())
    raw_format = raw.get("config_format")
    # C8 (amendment 8) measured six `load_config` round trips to upgrade the real v0.1.0 ledger this project
    # shipped at its own tag, because every refusal below stopped at the first problem it met. Amendment 10
    # found this check itself was half the reason a two-load fix was impossible: a config_format mismatch
    # was treated as "the whole shape is unknown, stop here" in BOTH directions, but format 1's shape IS
    # known -- `families` mapped a name to a string, format 2 maps it to an object, and that difference is
    # exactly what the family check below reports. So an OLDER format (this project has only ever had one:
    # 1) is validated all the way through and its problem is collected beside every other one; only a format
    # this reader has never seen -- newer, or not a plain integer at all -- stops here alone, because there
    # is no established shape left to check the rest against. Same rule C1 already applies to the decision
    # log's `schema_version`.
    config_format_known_older = (
        isinstance(raw_format, int) and not isinstance(raw_format, bool) and raw_format < CONFIG_FORMAT
    )
    if raw_format != CONFIG_FORMAT and not config_format_known_older:
        raise ConfigError(f"{p}: config_format must be {CONFIG_FORMAT}, found {raw_format!r}")
    problems: list[str] = []
    if raw_format != CONFIG_FORMAT:
        problems.append(f"{p}: config_format must be {CONFIG_FORMAT}, found {raw_format!r}")
    observed = _record_schema_keys(schema)

    candidates: dict[str, Candidate] = {}
    for cid, entry in (raw.get("candidates") or {}).items():
        if not isinstance(entry, dict):
            raise ConfigError(f"candidate {cid!r} must be an object")
        _reject_illegal(cid, entry, observed)
        ep = entry.get("endpoint") or {}
        _reject_illegal(f"{cid}.endpoint", ep, observed)
        if not ep.get("base_url") or not ep.get("model"):
            raise ConfigError(
                f"candidate {cid!r} needs endpoint.base_url and endpoint.model: the only thing tierbook "
                "needs to know about a backend is how to reach it and what to ask it for."
            )
        deployment = entry.get("deployment")
        if deployment not in ("api", "self_hosted"):
            raise ConfigError(f"candidate {cid!r}: deployment must be 'api' or 'self_hosted', not {deployment!r}")
        if deployment == "self_hosted" and entry.get("hourly_usd") is None:
            raise ConfigError(
                f"candidate {cid!r} is self_hosted with no hourly_usd. A machine bills while it is idle, so "
                "without its hourly bill its cost per request cannot be computed at all -- and an idle "
                "fixed-cost tier is infinitely expensive per request, which is the honest answer."
            )
        if deployment == "api" and not entry.get("price_per_mtok"):
            raise ConfigError(f"candidate {cid!r} is an api with no price_per_mtok; a token has to cost something")
        candidates[cid] = Candidate(
            id=cid,
            endpoint=Endpoint(
                base_url=ep["base_url"], model=ep["model"], wire=ep.get("wire", "chat"),
                api_key_env=ep.get("api_key_env"), revision=ep.get("revision"),
                gateway_version=ep.get("gateway_version"),
                refuses_params=tuple(ep.get("refuses_params") or ()),
                headers=dict(ep.get("headers") or {}), timeout_s=float(ep.get("timeout_s", 600.0)),
            ),
            deployment=deployment,
            price_per_mtok=entry.get("price_per_mtok"),
            hourly_usd=entry.get("hourly_usd"),
            note=entry.get("note", ""),
        )

    obj_raw = dict(raw.get("objective") or {})
    if "weights" in obj_raw:
        raise ConfigError(
            "objective.weights is refused. Quality is a constraint here, not a term in a weighted sum: "
            "once it is weighted, 'cheapest' no longer denotes anything a reader can check. Set a margin."
        )
    cons = dict(obj_raw.pop("constraints", None) or {})
    objective = Objective(
        objective=obj_raw.get("objective", "cost"),
        margin=float((cons.get("non_inferiority") or {}).get("margin", 0.15)),
        alpha=float((cons.get("non_inferiority") or {}).get("alpha", 0.05)),
        latency_slo_p95_ms=(cons.get("latency_slo") or {}).get("p95_ms"),
        min_completion_probability=(cons.get("reliability") or {}).get("min_completion_probability"),
        max_age_days=int(obj_raw.get("max_age_days", 90)),
    )
    # Read once for every family rather than once per family: the vocabulary does not change mid-loop, and a
    # ConfigError from a missing schema should name the loader's own action, not an arbitrary family.
    label_source_values = _label_source_values(schema)
    families: dict[str, FamilyDeclaration] = {}
    for fam, decl in (raw.get("families") or {}).items():
        if isinstance(decl, str):
            # Amendment 10.2: this used to print only `reference` and `floor` -- two of the six keys a family
            # object now requires. An operator who did exactly what it said met a SECOND refusal naming the
            # four keys C4 and C3/amendment 5 append to this same object, and across two families that was
            # four of the measured six round trips on its own, independent of aggregation. A refusal that
            # names a shape now names the WHOLE shape, so the object printed below is one that actually loads.
            problems.append(
                f"family {fam!r} names its reference candidate as a bare string, {decl!r} -- the config_format 1 "
                f"shape. As of config_format {CONFIG_FORMAT} a family is an object carrying its own floor beside "
                "its reference, because the floor is the family's own requirement (SCOPE calls it \"the family's "
                "floor\" in sections 2, 5 and 12) and a single flag shared by every family in the ledger let two "
                "families with different requirements silently share whichever number was typed. Since then, C4 "
                "and C3 have each appended their own required keys to this same object (SEAMS.md S1) without a "
                "second config_format bump: how a future request's label will be produced (label_source), how "
                "long to wait for one (max_label_latency_s, null only when label_source is 'none'), whether "
                "that labeller is independent of any candidate in the family (label_independent_of_candidate), "
                "and how stale a bound exploration may draw into before it is refused (staleness_limit_days, "
                f'null meaning no limit). Change it to {{"reference": {decl!r}, "floor": <this family\'s '
                'success-rate floor>, "label_source": <one of oracle.kind\'s values, or "none">, '
                '"max_label_latency_s": <seconds to wait for a label, or null only if label_source is "none">, '
                '"label_independent_of_candidate": <true or false>, "staleness_limit_days": <days, or null '
                'for no limit>}.'
            )
            continue
        if not isinstance(decl, dict):
            problems.append(f"family {fam!r} must be an object with 'reference' and 'floor', not {decl!r}")
            continue
        # config_format 2's shape (S1) plus the three keys amendment 4 appends to it without a second bump:
        # a family cannot be joined to an outcome, and therefore cannot be given an exploration rate, without
        # saying where its label comes from and how long to wait for one.
        required = ("reference", "floor", "label_source", "max_label_latency_s", "label_independent_of_candidate",
                   "staleness_limit_days")
        missing = [k for k in required if k not in decl]
        if missing:
            problems.append(
                f"family {fam!r} is missing {missing}: a family object needs the candidate it falls back to, "
                "the floor its certified assignment must clear, how a future request's label will be produced "
                "(label_source), how long to wait for one (max_label_latency_s, null only when label_source is "
                "'none'), whether that labeller is independent of any candidate in the family "
                "(label_independent_of_candidate) -- since C4 -- and how stale a bound exploration may draw "
                "into before it is refused (staleness_limit_days, null meaning no limit) -- since C3"
            )
            continue
        label_source = decl["label_source"]
        if label_source not in label_source_values:
            problems.append(
                f"family {fam!r}.label_source is {label_source!r}, which is not one of "
                f"{sorted(label_source_values)}. label_source is oracle.kind's vocabulary, read from the record "
                "schema so the two cannot drift, plus 'none' for a family with no labeller for online traffic."
            )
            continue
        max_label_latency_s = decl["max_label_latency_s"]
        if label_source == "none":
            if max_label_latency_s is not None:
                problems.append(
                    f"family {fam!r} declares label_source 'none' and max_label_latency_s {max_label_latency_s!r}; "
                    "a family with no labeller for online traffic has no latency to wait out, so "
                    "max_label_latency_s must be null exactly when label_source is 'none'."
                )
                continue
        elif max_label_latency_s is None:
            problems.append(
                f"family {fam!r} declares label_source {label_source!r} and max_label_latency_s null; a family "
                "with a labeller must say how long to wait for a label, so max_label_latency_s must be a number "
                "unless label_source is 'none'."
            )
            continue
        elif not isinstance(max_label_latency_s, (int, float)) or isinstance(max_label_latency_s, bool):
            problems.append(
                f"family {fam!r}.max_label_latency_s must be a number, not {max_label_latency_s!r}"
            )
            continue
        label_independent_of_candidate = decl["label_independent_of_candidate"]
        if not isinstance(label_independent_of_candidate, bool):
            problems.append(
                f"family {fam!r}.label_independent_of_candidate must be a boolean, not "
                f"{label_independent_of_candidate!r} -- there is no default, because a judge that is also a "
                "candidate in its own family is a fact only the operator declaring the family knows."
            )
            continue
        staleness_limit_days = decl["staleness_limit_days"]
        if staleness_limit_days is not None and (
                not isinstance(staleness_limit_days, (int, float)) or isinstance(staleness_limit_days, bool)):
            problems.append(
                f"family {fam!r}.staleness_limit_days must be a number or null, not {staleness_limit_days!r}"
            )
            continue
        exploration_rate = decl.get("exploration_rate")
        if "exploration_rate" in decl and (label_source == "none" or not label_independent_of_candidate):
            reason = ("label_source is 'none'" if label_source == "none"
                     else "label_independent_of_candidate is false")
            problems.append(
                f"family {fam!r} declares exploration_rate {exploration_rate!r}, but {reason}: exploration "
                "exists to generate evidence, and a candidate grading itself -- or traffic with no labeller at "
                "all -- is not evidence, so this family cannot represent an exploration rate. This is a load "
                "failure, not a runtime discovery: remove exploration_rate, or fix the reason above."
            )
            continue
        # Amendment 5: an unbounded staleness limit combined with a rate to explore with is refused. Exploration
        # exists to reach a candidate whose evidence has expired (`explore.clears_floor` overrides
        # `max_evidence_age_days` for exactly that candidate), so `staleness_limit_days: null` there is a bound
        # from any past environment at all, not a declared one -- a family may decline to state a limit, or may
        # explore, but not both.
        if "exploration_rate" in decl and staleness_limit_days is None:
            problems.append(
                f"family {fam!r} declares exploration_rate {exploration_rate!r} and staleness_limit_days null: "
                "exploration exists to reach a candidate whose evidence has expired, so an unbounded staleness "
                "limit there is a bound from any past environment at all. Declare a staleness_limit_days, or "
                "remove exploration_rate."
            )
            continue
        families[fam] = FamilyDeclaration(
            reference=decl["reference"], floor=float(decl["floor"]),
            label_source=label_source,
            max_label_latency_s=(float(max_label_latency_s) if max_label_latency_s is not None else None),
            label_independent_of_candidate=label_independent_of_candidate,
            staleness_limit_days=(float(staleness_limit_days) if staleness_limit_days is not None else None),
            exploration_rate=(float(exploration_rate) if exploration_rate is not None else None),
        )
    unknown = {f: d.reference for f, d in families.items() if d.reference not in candidates}
    if unknown:
        problems.append(f"families name references that are not candidates: {unknown}")
    if problems:
        # C8: every problem collected above is named once, in the SAME refusal, instead of the operator
        # meeting them one family (or one config_format bump) at a time. Measured against the real v0.1.0
        # ledger this project shipped at its own tag: six `load_config` round trips before this entry, two
        # after -- one load naming everything wrong, a fix, and a second load that either succeeds or names
        # whatever is still wrong.
        if len(problems) == 1:
            raise ConfigError(problems[0])
        raise ConfigError(
            f"{p}: {len(problems)} problems must be fixed before this file loads:\n"
            + "\n".join(f"{i}. {msg}" for i, msg in enumerate(problems, 1))
        )
    return Config(
        candidates=candidates, families=families, objective=objective,
        throughput_per_family={k: float(v) for k, v in (raw.get("throughput_per_family") or {}).items()},
        source=str(p),
    )


def draft_from_model_list(models: list[dict], *, base_url: str, api_key_env: str,
                          wire_by_id: dict[str, str] | None = None) -> dict:
    """Turn a gateway's model list into a draft candidate file for a human to edit and commit.

    Deliberately incomplete. Every draft entry carries `price_per_mtok: null` and a `note` saying so, which
    means the draft **does not load** until someone fills in what a token costs. A gateway advertises names;
    it does not tell you what it charges you, what it can do, or whether it is any good. A discovery feature
    that produced a loadable file would be inviting exactly the unrecorded premise this design refuses.
    """
    wire_by_id = wire_by_id or {}
    out = {
        "config_format": CONFIG_FORMAT,
        "_draft": ("Printed from a live model list. Nothing here is measured. Fill in price_per_mtok or "
                   "hourly_usd, delete what you will not measure, then commit it -- the file will not load "
                   "until you do, which is intentional."),
        "_draft_is_not_an_inventory": (
            "A model list is not the set of models a gateway can serve. On the gateway this project uses, "
            "the list was generated from a hand-maintained table rather than from the registry the request "
            "path dispatches on, and five servable models appeared in no list at all. So treat this draft as "
            "a starting point that may be missing entries, never as a complete inventory -- if a model you "
            "know exists is absent, add it by hand rather than concluding it is unavailable."),
        "candidates": {},
        "families": {},
        "objective": {"objective": "cost", "constraints": {"non_inferiority": {"margin": 0.15}}},
    }
    for m in models:
        mid = m.get("id") or m.get("model") or ""
        if not mid:
            continue
        out["candidates"][mid.replace("/", "-")] = {
            "deployment": "api",
            "endpoint": {"base_url": base_url, "model": mid, "wire": wire_by_id.get(mid, "chat"),
                         "api_key_env": api_key_env,
                         # `revision` or nothing. A model list's `created_at` is not a revision -- on the
                         # gateway this project uses it is generated at request time -- so falling back to it
                         # would write a timestamp into a field whose whole purpose is to pin a checkpoint.
                         "revision": m.get("revision") or None},
            "price_per_mtok": None,
            "note": "drafted from a model list; price and wire are unverified claims until someone checks them",
        }
    return out
