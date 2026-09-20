# patches: the two changes the other repositories need, kept as diffs

**Each file here is a change to another project, held as a diff so that it can be sent there.** `infra/tierbook-up`
applies them to a fresh checkout before deploying, and the same diffs are the contribution — nothing has to be
re-derived to upstream them.

```
patches/
  stratoclave/     0001-pass-the-bootstrap-admin-email-into-the-task-definition.patch
  distributed-ai/  0001-gpu-serving-vllm-accepts-extra-engine-args.patch
```

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

## What each patch is for

**`stratoclave/0001`** — the gateway's documented first-admin procedure cannot work. The backend reads
`STRATOCLAVE_BOOTSTRAP_ADMIN_EMAIL` at startup, the ECS stack pre-creates the secret for the password and grants the
task write access to exactly its ARN, and the variable appears nowhere in the infrastructure code, so it never reaches
the container. Observed on a clean deployment: the procedure reports success and the user pool has zero users. Without
this patch there is no administrator, and without an administrator no API key, and without a key tierbook has no way in.

**`distributed-ai/0001`** — the serving chart renders a closed list of five engine arguments. A request carrying `tools`
is rejected unless the engine was started with two more flags, and every request a coding agent sends carries tools. The
patch appends a caller-supplied list; the default is empty, so the rendered Deployment is unchanged for anyone not using
it (checked by rendering both ways).

## When one of these lands upstream

Delete the file. Nothing else: the script finds the directory shorter and says so. If a directory empties completely,
delete it too — `tests/test_infra_connection.py` fails on a patch directory that exists with nothing in it, which is the
state that means "somebody upstreamed these and left the scaffolding behind".

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
