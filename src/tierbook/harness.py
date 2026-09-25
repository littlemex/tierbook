"""What surrounds the model, identified so two runs can be told apart, and honest about what it cannot see.

**Why this matters more than the routing, on this project's own numbers.** Same box, same 1,187 items, and only the
instruction changed:

| condition | accuracy |
|---|---|
| terse (`Answer with the option letter only. Do not explain.`) | **0.6243** |
| explaining | **0.7447** |
| per-item agreement between them | **0.7346** -- one item in four flips |

**+12.04 points from one sentence.** Against that, the best cost saving routing between models produced here was 7.9%,
and it fell to **1.0%** once the comparison was restricted to the same items. So the thing around the model moved
accuracy by twelve points while the choice of model moved cost by one percent, and only one of the two had a name in
the record.

**What a harness is, concretely.** The instruction, the tools offered and their schemas, the loop that calls them, how
many turns it may take, what it retries, how the answer is finally read. Change any of those and the same model on the
same items is a different measurement.

## The part that needed careful thought: where each fact comes from

Three ways a fact about the harness can reach us, and they are **not interchangeable**:

* **in the request** -- we hold the bytes. It *is* what was sent: verifiable and contemporaneous. This is the only mode
  that may key an identity.
* **pulled by us** -- we fetched it. Verifiable and **not contemporaneous**: we read at one moment, the request ran at
  another, and whatever changed in between is invisible. A pulled fact therefore carries its lag, and a lag nobody
  bounded cannot support a per-request claim.
* **pushed by the owner** -- they told us. Not checkable here, and **a label they control can stay fixed while the thing
  underneath it changes** -- which is exactly the failure a prompt "version" invites.

And a fourth, which is the finding rather than an option: **not observable**. A tool's *schema* is in the request; its
*implementation* is not. Somebody can change what a tool does, leave its schema alone, and nothing in the request
differs. Recording that as unobservable is the only honest move -- the alternative is a record that looks complete and
silently groups two different harnesses under one identity.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from tierbook.evidence import (ABSENCE_REASONS, COLLECTION_STATUS, DIGEST_BOUNDARIES, HARNESS_SOURCING,
                              IDENTIFYING_BOUNDARIES, IDENTIFYING_SOURCING, EvidenceError)

#: The parts of a harness this package can name, as a DEFAULT rather than a gate (TB-045). A part nobody named is a
#: part that changes without the identity changing, and that is still the whole defect this vocabulary closes -- what
#: changed is who names the parts. `PartVocabulary`, below, is what a caller declares to name a different set; these
#: ten are what perigraph's own spec names today, offered so a caller with the same needs does not retype them.
DEFAULT_HARNESS_PARTS = (
    "instruction",          # the system prompt / the instruction text
    "tool_schemas",         # what tools were offered, and their declared shapes
    # What a tool actually does, split in two because one classification was covering two different objects. The
    # FUNCTION is unobservable -- somebody can change what a tool does behind an unchanged schema and nothing in the
    # request differs. Its RESTRICTION TO THE INPUTS ACTUALLY EXERCISED is not: those are bytes the run itself produced,
    # which is the strongest mode in the vocabulary, held here and contemporaneous. Classifying the whole part as
    # unobservable threw away evidence already in hand.
    "tool_extension",       # the function. Still unobservable, still non-identifying
    "tool_trace",           # the calls that actually happened. Collected, never identifying, and a veto only
    "loop",                 # the scaffold: how calls are sequenced, what ends the run
    "turn_budget",          # how many turns it may take
    "retry_policy",         # what it retries and how often
    "readout",              # how the final answer is taken out of the reply
    "decoding",             # temperature, top-p, and whether output is grammar-constrained
    # The ninth, and the part a whole published saving lives inside. Local Fusion reports $7.47 to $4.54 (39.2%) and
    # the entire mechanism is that a frontier model and a cheap one run in SEPARATE persistent contexts exchanging only
    # briefs and results, because switching models inside one context breaks prompt caching. The other eight cannot
    # express that at all: every one of them describes a single context.
    #
    # It is also what makes the counterfactual definable. "What would this have cost unrouted" is a question about how
    # many contexts there would have been and what would have crossed between them, and with the partitioning
    # unrecorded the alternative is not computable rather than merely unmeasured.
    "context_partitioning",
)

#: For each of the default parts, the BEST mode that can reach it, as a total classification. Total on purpose: adding
#: a part without deciding how it is observed breaks a test rather than defaulting the new part to observable.
#:
#: `tool_extension` is the entry that forced this table to exist. Its schema is in the request and its behaviour is not,
#: so a change to what a tool does behind an unchanged schema is invisible from the request -- and a record that did not
#: say so would group two different harnesses under one identity.
#: A `MappingProxyType`, not a plain `dict`, because a round-3 review found `conforms_to_perigraph` (below) read
#: this "constant" live: `hn.BEST_AVAILABLE_SOURCING["tool_extension"] = "in_the_request"` would have flipped
#: which vocabularies conform, silently, from outside this module. `conforms_to_perigraph` reads
#: `DEFAULT_PART_VOCABULARY`'s own canonicalised snapshot instead (see `PartVocabulary.__post_init__`), which this
#: proxy cannot reach even if a caller somehow bypassed the proxy -- two independent reasons the same mutation
#: cannot land, not one.
DEFAULT_BEST_AVAILABLE_SOURCING = MappingProxyType({
    "instruction": "in_the_request",
    "tool_schemas": "in_the_request",
    "tool_extension": "not_observable",
    # In the request, and after the fact: the trace is bytes the run produced. It may never key an identity, and that is
    # enforced below rather than here -- a per-run outcome is unique per run, so keying on it would make every pair of
    # runs incomparable, which is the defect the identifier split was introduced to fix.
    "tool_trace": "in_the_request",
    "loop": "pushed_by_owner",
    "turn_budget": "pushed_by_owner",
    "retry_policy": "pushed_by_owner",
    "readout": "in_the_request",
    "decoding": "in_the_request",
    # Pushed, and the reason is the same one that puts `loop` there: how many contexts a caller keeps and what it copies
    # between them is a property of their scaffold, not of any request we hold. We see one request at a time and cannot
    # tell a second context from a second conversation in the first.
    "context_partitioning": "pushed_by_owner",
})


class Unidentified(EvidenceError):
    """A harness fact was recorded in a way that lets two different harnesses wear one identity.

    Raised at construction, because the whole point is to make the grouping wrong *before* anything is measured under
    it. By the time two runs have been compared, the fact that they were different harnesses is not recoverable from
    the numbers.
    """


@dataclass(frozen=True)
class PartVocabulary:
    """Which harness parts a deployment can name, and the best sourcing mode for each -- a DECLARATION this package
    receives and checks, never a vocabulary it owns (TB-045).

    `DEFAULT_HARNESS_PARTS`/`DEFAULT_BEST_AVAILABLE_SOURCING` used to be the only ten parts a `Part`, `Absence`,
    `Harness` or `Manifest` could name, so a new harness construction (a self-hosted loop that retains a part these
    ten do not cover) could not be represented without editing this module -- the same shape of defect F140/F141 fixed
    for `evidence.SUBJECTS`/`decide.STATE_VARS`, found here by the same sweep. What this package still owns is the
    CHECK: `best_sourcing` must be total over `parts` (every part has exactly one best mode) and name nothing else --
    that totality is a structural property of a manifest, not a judgement about which parts are worth having, and
    perigraph is the corpus that gets to say what the parts ARE.

    `name`/`version` are this vocabulary's OWN identity, so a record built against it can say which vocabulary it is
    -- see `identity` and `conforms_to_perigraph` below. A caller who declares neither gets `"custom"`: declaring
    nothing is not the same claim as vendoring the spec, so silence must not read as perigraph's name.
    """

    parts: tuple[str, ...]
    #: Accepts a mapping OR a sequence of `(kind, mode)` pairs -- what this field itself holds after construction
    #: (see below). Typed as a mapping because that is the common case for a caller writing a new declaration.
    best_sourcing: dict[str, str] | tuple[tuple[str, str], ...]
    name: str = "custom"
    version: str = "unversioned"

    def __post_init__(self) -> None:
        # Normalise FIRST, before any check reads `best_sourcing`. A round-3 review found the check order the
        # other way around: once this constructor canonicalises `best_sourcing` into a tuple of pairs (below),
        # `dataclasses.replace(some_vocabulary, name="x")` and `PartVocabulary(parts=v.parts,
        # best_sourcing=v.best_sourcing)` -- both ordinary ways to build one `PartVocabulary` from another's own
        # fields -- fed that tuple BACK into this same constructor, where `set(self.best_sourcing)` yields pairs
        # rather than part names and the totality check breaks. `dict(...)` accepts a mapping or a sequence of
        # pairs identically, so normalising through it first makes every check below correct for either input,
        # and makes `replace`/reconstruction-from-fields round-trip.
        #
        # But `dict(...)` on a sequence of pairs SILENTLY COLLAPSES a duplicate key, keeping only the last
        # entry -- a reviewer found `best_sourcing=(("instruction", "in_the_request"), ("instruction",
        # "not_observable")))` passes with the second value winning and no sign that two contradictory
        # declarations were made for the same part. Checked here, before the collapse, and only for the
        # sequence-of-pairs input: a `Mapping` cannot carry a duplicate key at all (its own `__setitem__` already
        # resolved that before this constructor ever saw it).
        if not isinstance(self.best_sourcing, Mapping):
            pairs = list(self.best_sourcing)
            keys = [k for k, _ in pairs]
            if len(keys) != len(set(keys)):
                dupes = sorted({k for k in keys if keys.count(k) > 1})
                raise Unidentified(
                    f"best_sourcing names {dupes} more than once. dict(...) would silently keep only the last "
                    f"entry, hiding a contradiction between two declared sourcing modes for the same part")
        sourcing = dict(self.best_sourcing)
        if not self.parts:
            raise Unidentified("a vocabulary with no parts names nothing a harness could be built from")
        if len(set(self.parts)) != len(self.parts):
            raise Unidentified(f"a part is named twice in {self.parts}")
        missing = sorted(set(self.parts) - set(sourcing))
        if missing:
            raise Unidentified(
                f"{missing} have no best_sourcing entry. Total on purpose: a part without a decided sourcing mode "
                f"would default to observable rather than fail a test the moment it is used")
        extra = sorted(set(sourcing) - set(self.parts))
        if extra:
            raise Unidentified(f"best_sourcing names {extra}, which {self.parts} does not declare as a part")
        bad_modes = sorted(set(sourcing.values()) - set(HARNESS_SOURCING))
        if bad_modes:
            raise Unidentified(
                f"best_sourcing names sourcing mode(s) {bad_modes}, not one of {HARNESS_SOURCING}. A typo here (a "
                f"misspelled 'not_observable', say) would not equal the string `Manifest`/`Absence` compare it "
                f"against, so an invalid mode would silently count as reachable instead of refusing")
        # Canonicalised into an immutable, hashable snapshot -- decoupled from whatever mapping the caller passed in,
        # not merely copied from it. Two things this fixes at once: a `dict` field makes every frozen dataclass that
        # carries a `PartVocabulary` (`Part`, `Absence`, `Harness`, `Manifest`) unhashable, breaking any existing
        # caller that put one in a set or a dict key; and `DEFAULT_PART_VOCABULARY` aliasing the module-level
        # `DEFAULT_BEST_AVAILABLE_SOURCING` dict would let a later mutation of that module dict change this
        # vocabulary's answers silently, after the totality check above had already run against the un-mutated copy.
        object.__setattr__(self, "best_sourcing", tuple(sorted(sourcing.items())))

    def sourcing_of(self, kind: str) -> str:
        """The best sourcing mode for one part -- the lookup `best_sourcing` offered before it became a hashable
        tuple of pairs rather than a dict."""
        for k, v in self.best_sourcing:
            if k == kind:
                return v
        raise KeyError(kind)

    @property
    def identity(self) -> str:
        """Which vocabulary this is, for a reader who has to tell one caller's declaration from another's."""
        return f"{self.name}/{self.version}"

    @property
    def conforms_to_perigraph(self) -> bool:
        """Whether a record built against this vocabulary may be presented as perigraph-conforming.

        Structural, never by name: declaring `name="perigraph"` does not make it true, and a vocabulary that never
        heard of perigraph but happens to be an additions-only superset of it does conform. Two conditions, both read
        against perigraph's OWN ten parts and OWN sourcing table -- additions beyond them are exactly what this
        vocabulary exists to allow (TB-045) and never affect this property:

        * every one of perigraph's parts is named here too. A vocabulary that dropped one would compute `missing`/
          `unaccounted` against a shorter reference set, so a hole perigraph would flag would not exist in this
          record at all -- the record would look complete about a part it cannot even ask about.
        * every one of perigraph's parts has here the IDENTICAL best_sourcing perigraph gives it. The best sourcing
          of a spec-defined part is a structural fact -- `tool_extension`'s behaviour is invisible from the request
          whatever a caller declares -- not a caller's choice, so a declaration that widened it (claimed
          `in_the_request` where perigraph says `not_observable`, say) would let a `Manifest` admit as reachable
          something no mode actually reaches.

        Read against `DEFAULT_PART_VOCABULARY`'s own canonicalised snapshot, not the module-level
        `DEFAULT_BEST_AVAILABLE_SOURCING` "constant" directly -- a round-3 review found this property reading that
        mutable dict live, so `hn.BEST_AVAILABLE_SOURCING["tool_extension"] = "in_the_request"` from OUTSIDE this
        module would have flipped which vocabularies conform. `DEFAULT_PART_VOCABULARY.best_sourcing` was already
        copied into an immutable tuple at construction time (above), so this reads a value nothing outside this
        module can reach, on top of the module constant now being a read-only `MappingProxyType`.
        """
        if not set(DEFAULT_HARNESS_PARTS) <= set(self.parts):
            return False
        return all(self.sourcing_of(k) == DEFAULT_PART_VOCABULARY.sourcing_of(k) for k in DEFAULT_HARNESS_PARTS)

    @property
    def non_conformance_reason(self) -> str:
        """One sentence naming why `conforms_to_perigraph` is False. Refused when it is True -- there is nothing to
        explain about a vocabulary that conforms, the same shape as `Collection.why_not` refusing when admissible."""
        if self.conforms_to_perigraph:
            raise Unidentified(f"{self.identity} conforms to perigraph; there is no non-conformance to explain")
        dropped = sorted(set(DEFAULT_HARNESS_PARTS) - set(self.parts))
        redefined = sorted(k for k in DEFAULT_HARNESS_PARTS
                           if k in self.parts and self.sourcing_of(k) != DEFAULT_PART_VOCABULARY.sourcing_of(k))
        reasons = []
        if dropped:
            reasons.append(f"drops perigraph part(s) {dropped}")
        if redefined:
            reasons.append(f"redefines perigraph part(s) {redefined}'s best_sourcing")
        return f"{self.identity} " + " and ".join(reasons)


#: The vocabulary a caller gets by declaring nothing: today's ten parts and today's sourcing table -- this IS
#: perigraph's own vocabulary, so it identifies as `perigraph`, and `conforms_to_perigraph` is trivially true for it.
#: Every existing caller keeps working exactly as before; a caller whose harness construction this default does not
#: cover declares its own `PartVocabulary` instead of editing this module.
DEFAULT_PART_VOCABULARY = PartVocabulary(parts=DEFAULT_HARNESS_PARTS, best_sourcing=DEFAULT_BEST_AVAILABLE_SOURCING,
                                         name="perigraph", version="1")

#: Aliases of the names above, kept for any importer who held the pre-TB-045 names. `HARNESS_PARTS` and
#: `BEST_AVAILABLE_SOURCING` were the only names this module ever exported for these two constants; renaming them to
#: `DEFAULT_*` without an alias would break any external importer, in violation of "a caller who declares nothing
#: sees exactly today's behaviour" -- the same promise TB-045 makes to every caller INSIDE this package.
HARNESS_PARTS = DEFAULT_HARNESS_PARTS
BEST_AVAILABLE_SOURCING = DEFAULT_BEST_AVAILABLE_SOURCING


@dataclass(frozen=True)
class Part:
    """One component of the harness, with how we know it and what that permits.

    `digest` is over bytes and is **required for anything identifying**. `label` is for the reader and is explicitly not
    the key: a version string the owner controls can stay `v3` while the text under it changes, which is the failure
    this separation exists to prevent -- and the same failure this project already recorded for a model name and for a
    prompt condition called "terse".
    """

    kind: str
    sourcing: str
    label: str = ""
    digest: str = ""
    #: Which of the three things this digest is over. Defaults to `model_visible` because that is what every existing
    #: caller hashed -- the instruction text, the tool schemas as sent -- so the default is the true statement about
    #: them rather than a plausible-looking one. What the default does NOT do is let a digest over a client's wire
    #: format pass as one over the text the model read: a caller hashing that has to say so, and the identity then
    #: refuses to be keyed on it.
    boundary: str = "model_visible"
    #: How long before the request this fact was read, for a pulled fact. Required there and refused elsewhere: a fetched
    #: copy describes a different moment than the request, and a lag nobody wrote down is a lag nobody can bound.
    read_lag_seconds: float | None = None
    #: Which parts this `kind` is checked against, and each one's best sourcing mode. Declared here rather than fixed
    #: in the module (TB-045); empty callers get `DEFAULT_PART_VOCABULARY`, so every existing caller works unchanged.
    vocabulary: PartVocabulary = DEFAULT_PART_VOCABULARY

    def __post_init__(self) -> None:
        if self.kind not in self.vocabulary.parts:
            raise Unidentified(
                f"{self.kind!r} is not one of {self.vocabulary.parts}. A part nobody named is a part that can change "
                f"without the identity changing, which is the defect this vocabulary exists to close. Declare a "
                f"wider `vocabulary` if this harness has a part {self.vocabulary.parts} does not name")
        if self.sourcing not in HARNESS_SOURCING:
            raise Unidentified(f"{self.sourcing!r} is not one of {HARNESS_SOURCING}")
        best = self.vocabulary.sourcing_of(self.kind)
        if self.sourcing == "in_the_request" and best != "in_the_request":
            raise Unidentified(
                f"{self.kind!r} is claimed as being in the request, and the best any mode can do for it is {best!r}. "
                f"For `tool_extension` that is not a limitation of this implementation: a tool's schema is in the "
                f"request and its behaviour is not, so a change behind an unchanged schema is invisible from the bytes "
                f"we hold")
        if self.sourcing == "not_observable":
            if self.digest:
                raise Unidentified(
                    f"{self.kind!r} is recorded as not observable and carries a digest, so something was hashed. If "
                    f"bytes exist, name the mode that produced them; if they do not, the digest is of something else")
        elif not self.digest:
            raise Unidentified(
                f"{self.kind!r} has no digest. A part identified by a label alone is a part whose label can stay fixed "
                f"while its content moves -- this project has that failure recorded twice, for a model name and for a "
                f"prompt condition both called the same thing while differing underneath")
        if self.sourcing == "pulled_by_us" and self.read_lag_seconds is None:
            raise Unidentified(
                f"{self.kind!r} was pulled and carries no lag. We read at one moment and the request ran at another; a "
                f"lag nobody wrote down is a lag nobody can bound, and everything that changed inside it is invisible")
        if self.sourcing != "pulled_by_us" and self.read_lag_seconds is not None:
            raise Unidentified(
                f"{self.kind!r} is {self.sourcing!r} and carries a read lag, which only a pulled fact has: bytes in the "
                f"request have no lag by definition, and a pushed claim's timing is the owner's word rather than a "
                f"measurement")
        if self.boundary not in DIGEST_BOUNDARIES:
            raise Unidentified(f"{self.boundary!r} is not one of {DIGEST_BOUNDARIES}")
        if self.read_lag_seconds is not None and self.read_lag_seconds < 0:
            raise Unidentified(f"read_lag_seconds={self.read_lag_seconds!r} would mean it was read after the request it "
                               f"describes")

    #: Parts that may never key an identity whatever their sourcing says. `tool_trace` is bytes we hold, so the sourcing
    #: rule alone would admit it -- and it is a per-run OUTCOME, unique per run, so keying on it would make every pair of
    #: runs incomparable. That is the same defect the identifier split was introduced to fix, arriving from the other
    #: direction, so the exclusion is by name rather than by mode.
    NEVER_IDENTIFYING = ("tool_trace",)

    @property
    def identifying(self) -> bool:
        """Whether this part may contribute to the harness's identity. Three conditions, and all of them are needed.

        The first version refused a part whose digest was over the wrong boundary. That was the wrong mechanism, and
        writing the first real collector is what showed it: a `tools` array and a sampler setting are **in the request**
        and are **not text the model reads**, so `in_the_request` with a `parsed` digest is the common case and the
        refusal made it unrepresentable. Widening this predicate instead makes the wrong identity unrepresentable rather
        than the ordinary part refused -- and the two mistakes the boundary rule exists to stop are still stopped,
        because such a part simply never enters the hash.
        """
        if self.kind in Part.NEVER_IDENTIFYING:
            return False
        if self.digest and self.boundary not in IDENTIFYING_BOUNDARIES:
            return False
        return self.sourcing in IDENTIFYING_SOURCING

    def __str__(self) -> str:
        who = {"in_the_request": "in the request", "pulled_by_us": "pulled", "pushed_by_owner": "owner says",
               "not_observable": "NOT OBSERVABLE"}[self.sourcing]
        head = f"{self.kind} ({who}"
        if self.read_lag_seconds is not None:
            head += f", {self.read_lag_seconds:g}s before the request"
        head += ")"
        return head + (f" {self.label}" if self.label else "") + (f" {self.digest[:8]}" if self.digest else "")


@dataclass(frozen=True)
class Harness:
    """Everything around the model for one run, and an identity derived from the parts we actually hold.

    `identity` is a property, not a field. A supplied identity is one somebody can keep across a change to the parts,
    and then two harnesses wear one name -- which is the same defect as a supplied snapshot id, a supplied total, or a
    prompt condition identified by the word "terse".

    Only the parts we hold bytes for enter the identity. A pushed loop description and an unobservable tool behaviour
    are recorded and **do not** change the name, because a name that moved when the owner edited a sentence about
    themselves would not group anything.
    """

    parts: tuple[Part, ...]
    #: Which parts this harness's `missing` is read against. See `Part.vocabulary` (TB-045); empty callers get
    #: `DEFAULT_PART_VOCABULARY`, so every existing caller works unchanged.
    vocabulary: PartVocabulary = DEFAULT_PART_VOCABULARY

    def __post_init__(self) -> None:
        if not self.parts:
            raise Unidentified("a harness with no parts is not a harness; it is the absence of a record about one")
        kinds = [p.kind for p in self.parts]
        if len(set(kinds)) != len(kinds):
            raise Unidentified(f"two parts share a kind in {sorted(kinds)}, so nothing says which one applied")
        mismatched = sorted(p.kind for p in self.parts if p.vocabulary != self.vocabulary)
        if mismatched:
            raise Unidentified(
                f"{mismatched} were built against a different vocabulary than this harness declares. A harness and "
                f"the parts inside it have to agree on what a part IS, or `missing` and a part's own admissibility "
                f"check would be reading two different vocabularies for the same record")

    @property
    def has_identity(self) -> bool:
        """Whether anything here is identified by bytes we hold that the model provably read."""
        return any(p.identifying for p in self.parts)

    @property
    def identity(self) -> str:
        """Derived from the identifying parts, in a fixed order, so it cannot be kept across a change to them.

        Raised rather than returned when nothing identifies this harness. The refusal used to be at CONSTRUCTION, and
        writing the first collector showed that was the wrong place: a request carrying sampler settings and no system
        message yields parts that are real and cannot key anything, and refusing the object threw those parts away --
        they then appeared neither held nor explained, which the contradiction check correctly flagged as the collector
        saying nothing about a part it claimed. The parts are not the problem. The identity is, and it is missing exactly
        where it is read.

        **The vocabulary enters the hash for any vocabulary other than perigraph's own default.** A reviewer found
        that two harnesses declared against DIFFERENT vocabularies, but built from identifying parts of the same
        kind and digest, hash to the SAME identity -- `comparable_with`/`refuse_incomparable` already catch that
        for a direct comparison, but any OTHER grouping keyed on `identity` alone (a set, a dict key, a persisted
        identity) would still silently merge them. Folding the vocabulary in closes that, but NOT for the default
        vocabulary: `identity`'s bytes for perigraph's own ten parts are pinned to a cross-language digest
        algorithm a second, TypeScript implementation was built against (see the spec conformance test), and
        changing those bytes for every perigraph-conforming harness would break interoperability with every
        compliant consumer to fix a collision that, for the default vocabulary alone, `comparable_with` already
        prevents from being misread. So: unchanged, byte-for-byte, when `self.vocabulary == DEFAULT_PART_VOCABULARY`
        (value equality -- a caller's own default-shaped `PartVocabulary` counts, not only the literal module
        object); prefixed with the vocabulary's own identity for anything else.
        """
        if not self.has_identity:
            raise Unidentified(
                "no part of this harness is identified by bytes we hold that the model provably read, so an identity "
                "would be constant across every possible harness. At minimum the instruction is in the request; a "
                "record without it describes somebody's account of a run rather than the run")
        h = hashlib.sha256()
        if self.vocabulary != DEFAULT_PART_VOCABULARY:
            h.update(f"vocabulary={self.vocabulary.identity};".encode())
        for p in sorted((p for p in self.parts if p.identifying), key=lambda p: p.kind):
            h.update(f"{p.kind}={p.digest};".encode())
        return h.hexdigest()[:24]

    @property
    def unobserved(self) -> tuple[str, ...]:
        """Which parts nothing here can check. Reported, because a record that hid them would look complete."""
        return tuple(p.kind for p in self.parts if p.sourcing in ("pushed_by_owner", "not_observable"))

    @property
    def missing(self) -> tuple[str, ...]:
        """Which parts of a harness this record says nothing at all about."""
        return tuple(k for k in self.vocabulary.parts if k not in {p.kind for p in self.parts})

    @property
    def conforms_to_perigraph(self) -> bool:
        """Whether this harness may be presented to a perigraph consumer as perigraph-conforming.

        Delegates entirely to `self.vocabulary.conforms_to_perigraph`: a caller-declared vocabulary is checked here
        rather than at construction, because a non-conforming vocabulary is not invalid -- TB-045 exists precisely so
        a deployment with a genuinely different harness can be represented. What must not happen is presenting the
        result as perigraph's without saying so; see `__str__` below and the module's conformance test.
        """
        return self.vocabulary.conforms_to_perigraph

    @property
    def grouping_key(self) -> tuple[PartVocabulary, str] | None:
        """A key safe to put in a `set` or use as a `dict` key when two harnesses might have been declared
        against DIFFERENT vocabularies, stronger than `identity` alone even after `identity` started folding a
        NON-default vocabulary's own `identity` STRING into its hash (see `identity`'s docstring): two
        vocabularies that forgot to declare different `name`/`version` -- both left at `"custom"`/`"unversioned"`
        -- but differ in their actual `parts`/`best_sourcing` would still share that string and could still
        collide in `identity`'s hash. This uses the WHOLE `PartVocabulary` object instead, which is
        value-comparable on every field (`parts`, `best_sourcing`, `name` AND `version`), so two vocabularies
        that differ in content but not in self-declared name are still told apart. `None` when this harness has
        no identity at all, matching the state `identity` itself refuses to return.
        """
        if not self.has_identity:
            return None
        return (self.vocabulary, self.identity)

    def to_dict(self) -> dict:
        """A JSON/dict-safe structured representation, carrying `vocabulary_identity` and `conforms_to_perigraph`
        -- both PROPERTIES, so `dataclasses.asdict(self)` would silently omit them and leave a consumer with no
        way to tell which vocabulary produced this record or whether it conforms to perigraph. This project has
        no other JSON/dict output path for a `Harness` today (checked across `src/`, `harness/`, `examples/`,
        `tools/`); this is the safe path for the day one is added, not `dataclasses.asdict`.
        """
        return {
            "identity": self.identity if self.has_identity else None,
            "has_identity": self.has_identity,
            "vocabulary_identity": self.vocabulary.identity,
            "conforms_to_perigraph": self.conforms_to_perigraph,
            "parts": [
                {"kind": p.kind, "sourcing": p.sourcing, "label": p.label, "digest": p.digest,
                 "boundary": p.boundary, "identifying": p.identifying}
                for p in self.parts
            ],
            "unobserved": list(self.unobserved),
            "missing": list(self.missing),
        }

    def comparable_with(self, other: Harness) -> bool:
        """Whether two runs measured what is otherwise the same thing.

        Only the identifying parts decide it, and that is deliberate: a difference in what the owner *says* about their
        loop is not evidence that the loop differed, and treating it as such would refuse comparisons that are fine
        while still missing the ones that are not.

        A prerequisite comes first, though: two harnesses declared against DIFFERENT vocabularies are never
        comparable, whatever their identities say. `missing` and a part's own admissibility check read the
        vocabulary they were each built against, so two harnesses under different vocabularies are reading two
        different definitions of what a part IS for a same-shaped record -- comparing their identities would
        attribute that difference to the arms instead of to the declaration.
        """
        if self.vocabulary != other.vocabulary:
            return False
        return self.identity == other.identity

    def __str__(self) -> str:
        who = self.identity if self.has_identity else "no identity"
        head = (f"harness {who} from {len(self.parts)} part(s); vocabulary {self.vocabulary.identity}; "
                f"unobserved {list(self.unobserved) or 'none'}; unrecorded {list(self.missing) or 'none'}")
        if self.conforms_to_perigraph:
            return head
        return head + f"; NOT perigraph-conforming ({self.vocabulary.non_conformance_reason})"


def refuse_incomparable(a: Harness, b: Harness) -> None:
    """Refuse a comparison across two harnesses, naming what differs.

    The same shape as the refusal already in place for a prompt condition, one level up: the instruction is one part of
    a harness, and the measured 12-point swing came from changing it. A comparison across harnesses attributes to the
    arms a difference that is partly the difference between what surrounded them.
    """
    if a.comparable_with(b):
        return
    if a.vocabulary != b.vocabulary:
        raise Unidentified(
            f"these runs declared different vocabularies ({a.vocabulary.identity} against {b.vocabulary.identity}); "
            f"comparing them would read `missing` and a part's own admissibility against two different definitions "
            f"of what a part IS for a same-shaped record, which is a difference in declaration, not in the arms")
    ka = {p.kind: p.digest for p in a.parts if p.identifying}
    kb = {p.kind: p.digest for p in b.parts if p.identifying}
    differ = sorted(k for k in set(ka) | set(kb) if ka.get(k) != kb.get(k))
    raise Unidentified(
        f"these runs used different harnesses ({a.identity} against {b.identity}); the identifying parts that differ "
        f"are {differ}. Changing the instruction alone moved accuracy from 0.6243 to 0.7447 on the same box and the same "
        f"1,187 items, with one item in four flipping, so a difference between the arms cannot be separated from a "
        f"difference between what surrounded them")


#: Who each absence is about, as a total classification. Total on purpose: an absence reason added without deciding
#: whose it is breaks a test rather than defaulting to the harmless answer.
#:
#: The split that matters is `sender` against `collector`. An absence blamed on the sender is a fact about the run; one
#: blamed on the collector is a **measurement failure**, and the two were the same string until a shim losing the ability
#: to read a part was found to be indistinguishable from a sender that sent nothing.
ABSENCE_BLAMES = {
    "not_provided": "sender",
    "not_reachable": "collector",
    "extraction_failed": "collector",
    "redacted": "sender",
    "not_observable": "nobody",
}


@dataclass(frozen=True)
class Absence:
    """One part that is not in the record, and whose absence it is.

    A part is present or absent and never both: the same kind appearing in a harness's parts and in its absences is a
    record that answers "was this collected" two ways, and a consumer reading one of them is reading whichever it
    happened to check first.
    """

    kind: str
    reason: str
    #: What the collector was doing when it failed, for a `collector` absence. Required there, because a measurement
    #: failure nobody described is one nobody can fix, and refused elsewhere: the sender's silence has no detail we hold.
    detail: str = ""
    #: Which parts this `kind` is checked against. See `Part.vocabulary` (TB-045); empty callers get
    #: `DEFAULT_PART_VOCABULARY`, so every existing caller works unchanged.
    vocabulary: PartVocabulary = DEFAULT_PART_VOCABULARY

    def __post_init__(self) -> None:
        if self.kind not in self.vocabulary.parts:
            raise Unidentified(
                f"{self.kind!r} is not one of {self.vocabulary.parts}. An absence of something the vocabulary does not "
                f"name is not a hole in the record; it is a hole in the vocabulary, and counting it as the first would "
                f"report a record as complete about a part nobody can ask for. Declare a wider `vocabulary` if this "
                f"harness has a part {self.vocabulary.parts} does not name")
        if self.reason not in ABSENCE_REASONS:
            raise Unidentified(f"{self.reason!r} is not one of {ABSENCE_REASONS}")
        best = self.vocabulary.sourcing_of(self.kind)
        if self.reason == "not_observable" and best != "not_observable":
            raise Unidentified(
                f"{self.kind!r} is absent as {self.reason!r} and the best any mode can do for it is {best!r}, so "
                f"something reachable is being recorded as structurally invisible. That is the direction that matters: "
                f"it makes a collector's failure look like a fact about the world, and nothing downstream can tell them "
                f"apart afterwards")
        if self.reason != "not_observable" and best == "not_observable":
            raise Unidentified(
                f"{self.kind!r} is structurally unobservable and is absent as {self.reason!r}, which claims somebody "
                f"could have had it. A tool's implementation behind an unchanged schema is invisible from the bytes we "
                f"hold, and blaming that on a sender or on a collector invites work that cannot succeed")
        if self.blames == "collector" and not self.detail:
            raise Unidentified(
                f"{self.kind!r} is absent because of us ({self.reason!r}) and carries no detail. This is the entry that "
                f"exists to be actionable -- a measurement failure nobody described is one nobody can fix, and it will "
                f"read as the sender's silence at every later glance")
        if self.blames != "collector" and self.detail:
            raise Unidentified(
                f"{self.kind!r} is absent as {self.reason!r}, which is not our failure, and carries detail "
                f"{self.detail!r}. Detail here describes what we were doing when we failed; there is no such moment")

    @property
    def blames(self) -> str:
        return ABSENCE_BLAMES[self.reason]

    def __str__(self) -> str:
        head = f"{self.kind} absent ({self.reason}, blames {self.blames})"
        return head + (f": {self.detail}" if self.detail else "")


@dataclass(frozen=True)
class Manifest:
    """What the collector claims it can reach here, so that `not_reachable` becomes checkable rather than merely spelled.

    This is the separation borrowed from SCITT -- who said this against is this true -- applied to the collector instead
    of only to the harness owner, which the first version of this design borrowed and then failed to use on itself.

    `reaches` is a claim, not an observation, and that is why it is worth having: a claim contradicts a record, and a
    contradiction is louder than a hole.
    """

    collector: str
    version: str
    reaches: tuple[str, ...]
    #: Which parts `reaches` is checked against, and `Collection.unaccounted`'s reference set. See `Part.vocabulary`
    #: (TB-045); empty callers get `DEFAULT_PART_VOCABULARY`, so every existing caller works unchanged.
    vocabulary: PartVocabulary = DEFAULT_PART_VOCABULARY

    def __post_init__(self) -> None:
        if not self.collector or not self.version:
            raise Unidentified(
                "a manifest without a collector and a version cannot be compared against another run's, so a part that "
                "stopped being readable between two versions is a change nobody can attribute")
        unknown = sorted(set(self.reaches) - set(self.vocabulary.parts))
        if unknown:
            raise Unidentified(f"the manifest claims to reach {unknown}, which are not parts in {self.vocabulary.parts}")
        if len(set(self.reaches)) != len(self.reaches):
            raise Unidentified(f"the manifest lists a part twice in {sorted(self.reaches)}")
        impossible = sorted(k for k in self.reaches if self.vocabulary.sourcing_of(k) == "not_observable")
        if impossible:
            raise Unidentified(
                f"the manifest claims to reach {impossible}, which no mode reaches. A collector that claims an "
                f"impossible part will report a contradiction on every run it ever produces, which trains a reader to "
                f"ignore the one signal this structure exists to raise")

    def __str__(self) -> str:
        return f"{self.collector}/{self.version} reaches {list(self.reaches)}"


@dataclass(frozen=True)
class Collection:
    """One run's record of what surrounded the model: the parts held, the parts not held, and how the collector itself did.

    Two refusals live here and they are about different objects, which is the correction the first version of this design
    needed. **Toward the sender this is maximally permissive**: any combination of parts may be absent and the record is
    still valid, because a collector that refuses a partial record produces no record, and a run that emitted nothing is
    indistinguishable from a run that emitted a perfect record of nothing. **About itself it is exact**: the status says
    whether the collector finished, and a collector that failed cannot present its failure as the sender's silence.

    `harness` is optional, and that is the permissive half made concrete: a run where nothing identifying was reachable
    still produces a record. It is simply not admissible to anything that publishes a claim.
    """

    manifest: Manifest
    status: str = "complete"
    harness: Harness | None = None
    absences: tuple[Absence, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in COLLECTION_STATUS:
            raise Unidentified(f"{self.status!r} is not one of {COLLECTION_STATUS}")
        if self.harness is not None and not isinstance(self.harness, Harness):
            raise Unidentified(f"harness={self.harness!r} is not a Harness")
        kinds = [a.kind for a in self.absences]
        if len(set(kinds)) != len(kinds):
            raise Unidentified(f"two absences share a kind in {sorted(kinds)}, so nothing says why the part is missing")
        held = {p.kind for p in self.harness.parts} if self.harness else set()
        both = sorted(held & set(kinds))
        if both:
            raise Unidentified(
                f"{both} are recorded as held and as absent at once, so this record answers 'was this collected' two "
                f"ways and a consumer reads whichever it happened to check first")
        if self.harness is not None and self.harness.vocabulary != self.manifest.vocabulary:
            raise Unidentified(
                "the harness and the manifest declare different vocabularies, so `unaccounted` (read against the "
                "manifest's) and the harness's own `missing` would disagree about which parts exist for the same run")
        mismatched = sorted(a.kind for a in self.absences if a.vocabulary != self.manifest.vocabulary)
        if mismatched:
            raise Unidentified(
                f"absence(s) {mismatched} declare a different vocabulary than the manifest, which `unaccounted` "
                f"(read against the manifest's) treats as authoritative. An absence built against a WIDER vocabulary "
                f"could name a part the manifest's own vocabulary does not have, and `unaccounted` would then silently "
                f"ignore that recorded absence rather than reading it -- the same disagreement the harness check "
                f"above exists to catch, for the other place a `PartVocabulary` travels on this record")

    @property
    def conforms_to_perigraph(self) -> bool:
        """Whether this collection may be presented to a perigraph consumer as perigraph-conforming.

        Reading `manifest.vocabulary` alone is enough: `__post_init__` already requires the harness and every
        absence to declare the SAME vocabulary as the manifest, so there is exactly one vocabulary for this record
        to conform or not conform against.
        """
        return self.manifest.vocabulary.conforms_to_perigraph

    @property
    def unaccounted(self) -> tuple[str, ...]:
        """Parts this record says nothing about at all -- neither held nor explained.

        Distinct from an absence, and the distinction is the point: an absence is a statement, and this is the silence
        an absence was invented to replace. A record with an empty `absences` and eight unaccounted parts looks like a
        record of a bare harness and is a record of a collector nobody finished.
        """
        named = ({p.kind for p in self.harness.parts} if self.harness else set()) | {a.kind for a in self.absences}
        return tuple(k for k in self.manifest.vocabulary.parts if k not in named)

    @property
    def contradictions(self) -> tuple[str, ...]:
        """Parts the collector claims it can reach here and then said it could not see, or said nothing about.

        The one alarm this structure exists to raise. A hole the manifest says should not be there is not a property of
        the run -- it is the collector regressing, and it is invisible in every other reading because the absence is
        spelled exactly the way a legitimate one is.

        **The sender's silence is NOT a contradiction, and getting that wrong inverts the whole vocabulary.** A manifest
        claims "I can reach this IF it is there", not "this will be there". The first version of this property compared
        the manifest against the parts held and called every difference a contradiction, so a request that simply
        carried no decoding settings was reported as the collector regressing -- blaming us for the sender's silence,
        which is the exact confusion `ABSENCE_BLAMES` exists to prevent. It was found by writing the first real
        collector, whose every ordinary run tripped it.

        So the two cases that ARE contradictions: the part is absent as `not_reachable`, which directly denies the
        manifest's claim; or the part is unaccounted for entirely, which claims a capability and then says nothing.
        `extraction_failed` is consistent with the claim -- it says the capability exists and failed on this input --
        and it is reported by `our_failures` instead.
        """
        held = {p.kind for p in self.harness.parts} if self.harness else set()
        denied = {a.kind for a in self.absences if a.reason == "not_reachable"}
        explained = {a.kind for a in self.absences}
        return tuple(k for k in self.manifest.reaches
                     if k in denied or (k not in held and k not in explained))

    @property
    def our_failures(self) -> tuple[str, ...]:
        """Absences that are our fault rather than the sender's. Separated because only these are ours to fix."""
        return tuple(a.kind for a in self.absences if a.blames == "collector")

    def admissible_to_a_verdict(self) -> bool:
        """Whether anything may publish a claim from this record.

        Three conditions, and each is a different failure. An incomplete status means the record does not describe the
        run it appears to. A contradiction means the collector is lying about its own reach, so no absence in the record
        can be read at face value. And no identifying part means the identity would be constant across every possible
        harness, so a comparison against it groups things that have nothing in common.
        """
        return (self.status == "complete" and not self.contradictions
                and self.harness is not None and self.harness.has_identity)

    def why_not(self) -> str:
        """One sentence naming everything standing between this record and a published claim."""
        if self.admissible_to_a_verdict():
            return (f"admissible: {self.status}, no contradiction, identity "
                    f"{self.harness.identity}")
        parts = []
        if self.status != "complete":
            parts.append(f"the collector reports {self.status!r}, so the record does not describe the run it looks like")
        if self.contradictions:
            parts.append(f"the manifest claims to reach {list(self.contradictions)} and did not deliver them, so no "
                         f"absence here can be read at face value")
        if self.harness is None or not self.harness.has_identity:
            parts.append("no part was identified by bytes we hold that the model provably read, so the identity would "
                         "be the same for every possible harness")
        return "not admissible to a verdict -- " + "; and ".join(parts)

    def to_dict(self) -> dict:
        """A JSON/dict-safe structured representation, carrying `vocabulary_identity` and `conforms_to_perigraph`
        -- see `Harness.to_dict` for why `dataclasses.asdict` is not the safe path for this either."""
        return {
            "status": self.status,
            "harness": self.harness.to_dict() if self.harness is not None else None,
            "absences": [{"kind": a.kind, "reason": a.reason, "detail": a.detail, "blames": a.blames}
                        for a in self.absences],
            "manifest": {"collector": self.manifest.collector, "version": self.manifest.version,
                        "reaches": list(self.manifest.reaches)},
            "vocabulary_identity": self.manifest.vocabulary.identity,
            "conforms_to_perigraph": self.conforms_to_perigraph,
            "unaccounted": list(self.unaccounted),
            "contradictions": list(self.contradictions),
            "our_failures": list(self.our_failures),
            "admissible_to_a_verdict": self.admissible_to_a_verdict(),
        }

    def __str__(self) -> str:
        who = self.harness.identity if (self.harness and self.harness.has_identity) else "no identity"
        head = (f"collection {who} ({self.status}); vocabulary {self.manifest.vocabulary.identity}; held "
                f"{len(self.harness.parts) if self.harness else 0}; absent {len(self.absences)}; "
                f"unaccounted {list(self.unaccounted) or 'none'}; contradictions {list(self.contradictions) or 'none'}")
        if self.conforms_to_perigraph:
            return head
        return head + f"; NOT perigraph-conforming ({self.manifest.vocabulary.non_conformance_reason})"


#: Whether a tool's contract promises the same answer for the same effective context. Closed, and the reason it is not a
#: bool: the two useful cases are "promised deterministic" and "known to vary", and the third -- nobody said -- is the
#: common one and must not collapse into either.
TOOL_DETERMINISM = ("declared_deterministic", "known_to_vary", "unstated")

#: What a divergence between two runs' traces licenses, given what the tool promised. TOTAL over TOOL_DETERMINISM, so a
#: determinism value added without deciding what it licenses fails a test.
#:
#: The first version of this rule said an equal-argument, unequal-response pair PROVED two runs used different tools. It
#: was refuted three ways and any one is disqualifying: it fires against a SINGLE run (write a key, then read it -- equal
#: arguments, unequal responses, one tool); it fires on essentially every networked tool, because request ids and
#: timestamps sit in response bodies and canonicalisation is refused, so an always-firing veto means no harness with a
#: real tool can ever be compared; and the conclusion is false even where firing is right, because a clock or a moved
#: index makes the environments differ without the tool changing.
DIVERGENCE_LICENSES = {
    "declared_deterministic": "refuse",     # the contract was broken, so the comparison cannot stand
    "known_to_vary": "unknown",             # widen the verdict; neither authorise nor refuse
    "unstated": "unknown",                  # nobody promised anything, so nothing is contradicted
}


@dataclass(frozen=True)
class ToolCall:
    """One call in a run's trace, keyed on the context that actually determined its answer.

    `prefix_digest` is over the calls BEFORE this one, and it is the field that stops the veto firing against a single
    run: writing a key and then reading it has equal arguments and unequal responses, and it is one tool behaving
    correctly. The first version of the rule compared arguments alone and never used the ordering it had collected.

    `response_digest` is over the response **as rendered to the model**, for the same reason the canonicalisation rule
    exists: those are the bytes that mattered. It is a stable projection rather than the raw body, because request ids
    and timestamps in a body would make every pair of runs diverge.
    """

    tool: str
    prefix_digest: str
    arguments_digest: str
    response_digest: str
    credentials_class: str = "same"
    attempt: int = 1

    def __post_init__(self) -> None:
        if not self.tool:
            raise Unidentified("a call with no tool name cannot be matched against another run's, so a divergence "
                               "could not say which tool diverged")
        for name in ("prefix_digest", "arguments_digest", "response_digest"):
            if not getattr(self, name):
                raise Unidentified(
                    f"{name} is empty on a call to {self.tool!r}. All three decide whether two calls are the same "
                    f"occasion, and a missing one makes two different occasions compare equal -- which is the "
                    f"direction that turns a real divergence into silence")
        if self.attempt < 1:
            raise Unidentified(f"attempt={self.attempt} is not an attempt; a retry is a different occasion and the "
                               f"count is what separates it from the call it retried")

    @property
    def occasion(self) -> tuple[str, str, str, int]:
        """What has to match before two calls are the same occasion. Everything except the response."""
        return (self.tool, self.prefix_digest, self.arguments_digest, self.credentials_class, self.attempt)


def divergences(a: tuple[ToolCall, ...], b: tuple[ToolCall, ...]) -> tuple[str, ...]:
    """Which tools produced a different response on the same occasion in these two traces.

    Matching on the occasion rather than on the arguments is the whole correction. Two calls are comparable only when
    the trace before them, the arguments, the credentials class and the attempt number all agree; anything else is a
    different occasion and says nothing about the tool.
    """
    by_occasion = {c.occasion: c for c in a}
    out = []
    for call in b:
        other = by_occasion.get(call.occasion)
        if other is not None and other.response_digest != call.response_digest:
            out.append(call.tool)
    return tuple(sorted(set(out)))


def license_for(determinism: str) -> str:
    """What a divergence licenses. Refused for an unknown determinism rather than defaulted to the harmless answer."""
    if determinism not in TOOL_DETERMINISM:
        raise Unidentified(f"{determinism!r} is not one of {TOOL_DETERMINISM}")
    return DIVERGENCE_LICENSES[determinism]


def veto(a: tuple[ToolCall, ...], b: tuple[ToolCall, ...], *, determinism: str) -> tuple[str, tuple[str, ...]]:
    """Read two traces and say what the comparison is allowed to do. One-sided by construction.

    Returns the outcome and the tools that diverged. Three outcomes, and the middle one is what the first version of
    this rule lacked:

    * `refuse` -- the tool promised determinism over the recorded occasion and did not deliver it.
    * `unknown` -- something diverged and nobody promised it would not, so the verdict widens and is neither authorised
      nor refused.
    * `no_divergence` -- **not an authorisation.** Agreement on the occasions both runs exercised says nothing about
      the occasions neither touched, which is why the whole mechanism can refuse and can never permit.

    The one-sidedness is what makes the remaining hole safe: two serialisations of the same logical arguments compare
    unequal, so a genuine difference is missed. A rule that could authorise would turn that miss into a false licence.
    """
    diverged = divergences(a, b)
    if not diverged:
        return "no_divergence", ()
    return license_for(determinism), diverged


def digest_bytes(payload: str) -> str:
    """Hash a part's content. Over the bytes, because that is the only thing a label cannot drift away from."""
    if not payload.strip():
        raise Unidentified("an empty payload has no content to identify; a part that is genuinely empty is a part that "
                           "was not applied, and that is a different record")
    return hashlib.sha256(payload.encode()).hexdigest()

#: What this collector claims it can reach from a request body, and nothing more. Static per version on purpose: a
#: manifest that adapted to what it happened to find could never contradict a record, which is the one thing it is for.
FROM_A_REQUEST = ("instruction", "tool_schemas", "readout", "decoding")

#: Which boundary each of those digests is actually over -- and this table is the finding rather than a detail.
#:
#: Only the instruction is text the model reads. A `tools` array, a `response_format` and the sampler settings are
#: PROTOCOL VALUES: the provider renders them into the prompt however it likes, or does not render them at all, and we
#: do not hold that rendering. So they are `parsed`, and because only a `model_visible` digest may key an identity,
#: **a harness identified from a request body is identified by its instruction and by nothing else.**
#:
#: That is not a limitation of this function. It is the same fact the measurement found from the other side: the
#: instruction moved accuracy 12.04 points, and it is also the only part of a request whose exact bytes we can prove the
#: model read.
REQUEST_BOUNDARIES = {
    "instruction": "model_visible",
    "tool_schemas": "parsed",
    "readout": "parsed",
    "decoding": "parsed",
}


def _canonical_scalars(pairs: list[tuple[str, object]]) -> str:
    """Render protocol scalars for hashing, in the order given rather than sorted.

    Canonicalising IS allowed here, and the rule that forbids it elsewhere says why: a machine reads these, so two
    spellings of the same setting behave identically. The instruction is the opposite case and is hashed raw.
    """
    return ";".join(f"{k}={v!r}" for k, v in pairs)


def collect_from_request(body: dict, *, collector: str, version: str) -> Collection:
    """Read what a request body says about the harness around the model. The shim, reduced to a pure function.

    No dependency and no network: this package has none by design, and a component that decides where money goes should
    not be able to break because something it did not need moved. It takes the body a gateway already holds.

    Everything it cannot reach becomes an absence that says WHOSE it is, which is the whole point of F126's vocabulary
    meeting its first real caller:

    * the four pushed parts (`loop`, `turn_budget`, `retry_policy`, `context_partitioning`) are `not_provided` when the
      sender declared nothing -- **their absence is the sender's, not ours.** A request body has no place to put them.
    * `tool_extension` is `not_observable`, structurally and permanently.
    * `tool_trace` is `not_provided`: at request time the calls have not happened, so there is nothing to have sent.
    """
    parts: list[Part] = []
    absences: list[Absence] = []

    def add(kind: str, payload: str, label: str = "") -> None:
        parts.append(Part(kind=kind, sourcing="in_the_request", label=label,
                          digest=digest_bytes(payload), boundary=REQUEST_BOUNDARIES[kind]))

    messages = body.get("messages") or []
    system = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
    if system.strip():
        add("instruction", system)
    else:
        absences.append(Absence(kind="instruction", reason="not_provided"))

    tools = body.get("tools")
    if tools:
        # The declared shapes, not the implementations. Sorted by name, because the order a caller lists tools in is not
        # part of what it offered -- and an unsorted digest would make two identical toolsets look different.
        shapes = sorted(_canonical_scalars([("name", (tl.get("function") or tl).get("name")),
                                            ("params", (tl.get("function") or tl).get("parameters"))])
                        for tl in tools)
        add("tool_schemas", "|".join(shapes), label=f"{len(tools)} tool(s)")
    else:
        absences.append(Absence(kind="tool_schemas", reason="not_provided"))

    fmt = body.get("response_format")
    if fmt:
        add("readout", _canonical_scalars([("response_format", fmt)]),
            label=str(fmt.get("type", "")) if isinstance(fmt, dict) else "")
    else:
        # Not our failure: without a declared format the answer is read out of prose by a convention that lives on the
        # caller's side, and this repository has measured what that costs -- a mis-set convention put 1,822 of 2,364
        # answers on one option.
        absences.append(Absence(kind="readout", reason="not_provided"))

    knobs = [(k, body[k]) for k in ("temperature", "top_p", "top_k", "seed") if k in body]
    if knobs:
        add("decoding", _canonical_scalars(knobs), label=",".join(k for k, _ in knobs))
    else:
        absences.append(Absence(kind="decoding", reason="not_provided"))

    for kind in ("loop", "turn_budget", "retry_policy", "context_partitioning"):
        absences.append(Absence(kind=kind, reason="not_provided"))
    absences.append(Absence(kind="tool_extension", reason="not_observable"))
    absences.append(Absence(kind="tool_trace", reason="not_provided"))

    return Collection(manifest=Manifest(collector=collector, version=version, reaches=FROM_A_REQUEST),
                      status="complete",
                      # Every part that was reached is kept, whether or not any of them can key an identity. A
                      # request carrying sampler settings and no system message holds real parts and identifies nothing,
                      # and discarding them made them look like parts the collector never mentioned.
                      harness=Harness(parts=tuple(parts)) if parts else None,
                      absences=tuple(absences))
