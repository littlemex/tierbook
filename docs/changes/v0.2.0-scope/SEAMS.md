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
