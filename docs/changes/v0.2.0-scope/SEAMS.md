# Seams between v0.2.0's contract entries

Two objects no single entry watches: the boundaries between the entries, and the journey across them. Every entry's
author is deliberately blind to the others, so a boundary belongs to the integrator or it belongs to nobody.

One entry per seam, with the reason the other resolution was rejected — same discipline as the contract's
rejected-alternatives table, because a seam gets re-litigated the same way a rejected option does.

## S1 — `families` stops being a bare string, and two entries need it

**Raised by** amendment 2, before either entry's implementation reached it.

C2 needs a per-family floor. C4 needs a per-family labeller and maximum label latency. Both are new keys on the same
object, and today `families` maps a family name to a reference candidate id as a **plain string**:

```json
"families": {"agentic-coding": "api-strong-a"}
```

**Resolved:** C2 owns the shape change, because it needs it first. `families` becomes an object with `reference` and
`floor`; `config_format` goes from 1 to 2; a bare string is refused naming what to change. C4 then **appends**
`label_source`, `max_label_latency_s` and `label_independent_of_candidate` to the shape C2 created and does **not**
re-bump `config_format`.

Amendment 4 settled which file that object lives in, and the seam is the reason it was caught: C4's interface section
named `schema.json`, the **tier record** — a measurement artifact — while this entry said C4 appends to the config
object C2 created. The two could not both be true, and reading the schema file decided it in favour of this entry. A
seam recorded before implementation is what made a wrong interface visible without a worker building on it first.

**Rejected: each entry adds its own keys independently.** Two authors bumping `config_format` in the same release gives
two version 2s that are not each other, and a reader cannot tell which it has. Worse, whichever merges second discovers
the collision at integration, which is the point at which a shape change is most expensive.

**Rejected: a separate top-level block per concern** (`floors: {...}`, `labellers: {...}`). It keys three mappings by
family name and nothing enforces that they agree, so a family present in two of them and absent from the third is
representable — the omission-is-silent shape this project's review discipline exists to make unrepresentable. One object
per family makes a missing key a missing key.

**Consequence for C4's author:** the ledger will already be at `config_format: 2` when C4 starts. C4 reads the shape as
given, adds two keys, and leaves the version alone. If C4 finds the shape wrong rather than merely incomplete, that is a
contract amendment, not a second bump.

## S2 — a candidate row's shape is now C1's and F12 will grow it

**Raised by** amendment 1.

C1 made `from_row` report and refuse on a candidate row's fields by position. F12 proposes replacing
`bound_n`/`bound_attempted` with a per-candidate evidence reference, which lands in exactly that shape.

**Resolved:** F12 is out of scope for v0.2.0 and the seam is recorded so that whoever implements it knows the reader is
already prepared: a new candidate key is *named as ignored* by an older reader rather than dropped, which is the
property that makes the change safe to roll out and roll back. No entry in this release adds the field.

**Rejected: adding the field now because the reader is ready.** The reader being ready is not a reason to write the
producer; nothing in this release computes an evidence reference, so the field would be present-and-absent — assumption
A4's failure mode, already recorded in phase 1.

## S3 — `exploration_rate` is parsed by C4 and drawn from by C3

**Raised by** C4's code author, from the implementation side, and it is a genuine boundary rather than a gap in either
entry.

C4's interface says `exploration_rate` may appear on a family only under two conditions, and names neither the field's
type nor its owner. But a loader cannot refuse the *presence* of a key it does not parse, and parsing a key only to
discard it would make the refusal a statement about a value nothing can read.

**Resolved:** `FamilyDeclaration` carries `exploration_rate: float | None = None`, added by C4. C4 decides whether a rate
**may** exist; C3 reads the rate and draws from it. C3's author will find the field already present and must not add it
again.

**Rejected: C3 adds the field and C4 refuses on the raw dict.** It splits one value across two entries — C4 validating
`raw["families"][fam]["exploration_rate"]` while C3 owns the parsed attribute — so the declaration's shape would be
stated in one entry and its parsing in another. C2's amendment 2 exists because a number with two homes and no recorded
copy is the defect this release opened with; reproducing that shape inside the fix would be worse than the original.

**Rejected: C4 refuses without parsing, by checking key presence only.** It works, and it leaves the rate readable only
as an unparsed dict key, so C3 would have to re-derive the type and the absent-versus-zero distinction that C4 already
decided. Two readers of one value again.

## S4 — a field added by C3 is read by C1, and the two rules contradict unless the version decides

**Raised by** amendment 5, by listing `Decision`'s fields that have no default rather than reading C3's prose.

C1's `from_row` raises `Incomplete` naming any field the row lacks that the dataclass declares without a default —
sixteen fields today. C3 adds `exploration_reason` and `eligible_set` to the same dataclass, and the contract says
"version 1 rows read as `no_mechanism`". Those two statements cannot both hold for a field with no default.

**Resolved:** `from_row` supplies the version 1 value — `no_mechanism` and `[]` — for `schema_version == 1`, and raises
`Incomplete` naming the field for `schema_version >= 2`. The dataclass declares no default, so nothing else can supply
one. C3 owns the fields; C1's reader owns the version rule; the rule is stated here because it belongs to the boundary.

**Rejected: a dataclass default of `no_mechanism`.** It reads correctly for a version 1 row and wrongly for a version 2
row that omits the field — a writer that forgot to stamp the reason would be indistinguishable from a mechanism that was
never installed, and "how many decisions had no exploration mechanism" is a number this release reports. The cheaper
option makes the omission silent in exactly the direction that corrupts a reported count.

**Rejected: C3 backfills existing rows.** Rewriting the log to carry a field its writer never wrote makes the log
append-only in bytes and mutable in meaning, which `record.Log` already refuses for labels and would have no reason to
permit for this.
