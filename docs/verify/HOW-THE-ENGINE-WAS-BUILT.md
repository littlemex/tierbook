# Standing up the engine for a phase-5 run, and the five failures on the way

This is not part of tierbook. It is recorded because the next person to verify this project against a real engine
will hit the same wall, and because four of the five failures presented as something they were not.

## The shape of the problem

The Deep Learning AMI ships a **driver**. vLLM 0.29 JIT-compiles kernels during engine startup, so it needs a build
toolchain the AMI does not have, and every tool it needs was present *inside the pip environment, off `PATH`*.

Each failure arrived **after** the model had loaded, CUDA graphs had been captured and 18.84 GiB of KV cache had been
allocated. So each one read as a model or memory problem. None was.

| # | what the log said | what it was |
|---|---|---|
| 1 | `Python.h: No such file or directory` from `/tmp/.../cuda_utils.c` | the venv was built from a system interpreter with no `python3.11-dev`; Triton needs the headers |
| 2 | `Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist` | the toolkit vLLM's own dependencies installed lives at `<site-packages>/nvidia/cu13` |
| 3 | `FileNotFoundError: 'ninja'` | `ninja` is a pip package in the venv, and the server was launched with the venv's interpreter but not its `bin` on `PATH` |
| 4 | `"CUDA compiler and CUDA toolkit headers are incompatible"` | a real version conflict: flashinfer's bundled CCCL headers reject the CUDA 13.4 `nvcc` that vLLM's own pip dependencies install |
| 5 | the same message again, after pinning the attention backend | it was the **sampler**, not attention — `topk_topp_sampler.py:508 flashinfer_sample` |

## What changed in response, and the one that mattered

The first two were fixed by naming the missing thing. After the third, the task stopped chasing tools one at a time
and started **establishing its preconditions before launch**: it resolves `CUDA_HOME` from the venv, puts both that
and the venv's `bin` on `PATH`, and then checks that `nvcc`, `ninja` and `cc` all resolve, failing with a message
that says why a missing one would otherwise surface five minutes later looking like a memory problem.

That change is the point. Three failures came from the same shape and the fix for the shape is worth more than three
fixes for three instances.

The fourth and fifth were a genuine incompatibility rather than a missing tool. `VLLM_USE_FLASHINFER_SAMPLER=0`
takes the native sampling path and the engine starts. `--attention-backend FLEX_ATTENTION` was set while chasing the
fourth and is kept only because a run whose outcome depends on an unrecorded selection is not a result — it was not
what fixed anything.

## Two operational notes

**The security group is pinned to an operator IP, and that IP moved twice during the run**, which looked exactly like
the instance dying. The robust path is SSM: `aws ssm start-session --document-name AWS-StartPortForwardingSession`
reaches the engine's port without depending on the caller's address at all, and the instance already has the
permission for it. A verification run behind a connection whose egress address changes should use that from the start.

**CDK caches an AMI lookup in `cdk.context.json`.** A stack synthesised by name pattern and deployed later will
silently use the cached id. `cdk.context.json` was deleted before this run's deploy so the lookup was fresh, and the
resolved id is recorded in `v0.2.0-README.md` rather than left to be inferred.
