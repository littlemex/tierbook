# patches: changes the other repositories need, kept as diffs

**Each file here is a change to another project, held as a diff so that it can be sent there.** `infra/tierbook-up`
applies them to a pinned checkout before deploying, and the same diffs are the contribution — nothing has to be
re-derived to upstream them.

## There are none right now

Both gaps this mechanism was built for are fixed upstream, and `GATEWAY_REF` / `CLUSTER_REF` in `infra/tierbook-up` name
the commits that carry the fixes:

| gap | fixed as |
|---|---|
| the gateway's first-admin variable never reached its task definition | the variable is passed through beside `ALLOW_ADMIN_CREATION` |
| the serving chart's engine arguments were a closed list, so a request carrying tool schemas was rejected with 400 | `extraArgs` on the three serving workloads |

So this directory holds only this document. That is the intended end state for a patch, not a sign the mechanism went
unused — and a patch directory that exists with nothing in it is a test failure, because scaffolding left behind makes
`patches` report on a repository it carries nothing for.

## Why a diff rather than fixing the deployed resource

The first version of this wiring reached into the deployed resources instead: it registered a task definition revision
and patched a running Deployment. That was wrong in three ways, and they share a root — **a change made to a live
resource is not a change anybody upstream can read.**

| | live surgery | a patch |
|---|---|---|
| can be sent upstream | no, it has to be re-derived by hand | **yes, this file is the contribution** |
| behaviour when upstream moves | keeps "working" against a shape that changed | **fails, loudly** |
| answering "is it fixed yet" | inspect a deployed object that may have been hand-edited | **`git apply --reverse --check`** |

## The three states, all handled

`apply_patches` puts every patch in exactly one of three states. Two would not be enough: without the first, the day
these land upstream every deploy starts failing on a patch that is no longer needed.

| state | how it is detected | what happens |
|---|---|---|
| already upstream | `git apply --reverse --check` succeeds | skipped, and it says the patch can be deleted |
| applies | `git apply --3way --check` succeeds | applied with `--3way`, which tolerates upstream moving around the hunk |
| no longer matches | neither | **refused.** Applying part of it would deploy half a fix |

Read the state without deploying anything:

```bash
./infra/tierbook-up patches
```

## When a patch lands upstream

Delete the file, and move the pin forward to the commit that carries the fix. Those two go together: without the pin
moving, the next run checks out code that still needs the patch you just deleted.

If a directory empties completely, delete it too — `tests/test_infra_connection.py` fails on a patch directory that
exists with nothing in it.

## Adding one

Write the diff against the **pinned** checkout in the work directory, not against the tip of the other project's main
branch. A patch generated against a newer tree may refuse to apply to the pin, and the refusal arrives at deploy time.

## Regenerating a patch

When upstream moves the code a patch is about, the applier refuses and the fix is to regenerate rather than to force:

```bash
git clone --depth 1 <the repository> /tmp/regen && cd /tmp/regen
# make the change again, by hand, against the current code
git diff > <path-to-the-patch>
# then put the header back on top, above a line containing only ---
```

The header is not decoration. `tests/test_infra_connection.py` requires each patch to state the gap, what was observed,
what the fix does, and that it can be deleted once upstream carries it — a patch without those is one the next reader
cannot judge, and these are meant to be read by people in another project.
