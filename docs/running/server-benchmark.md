# Linux policy benchmark handoff

This page describes the current unified integration checkout. It has not yet
replaced the GitHub default branch; the [acceptance ledger](../archive/unified-main.md)
records remaining qualification work. For new runs, use the unified CLI and its
frozen configuration rather than a mixture of older branch-specific commands.

Each task has its own physical world, runtime database, native sessions, logs,
and motion evidence. Planning and preparation are separate from paid inference.
Factory Cycles rendering is a later, independent workflow.

## Select the execution environment

- [Native configuration and commands](../unified-cli.md): install the locked Python
  environment and the native CLI for the selected policy engine.
- [Slurm](slurm.md): freeze committed source and verified assets on the submission
  host; execute active state on node-local storage; return stopped evidence.
- [Docker](docker.md): build committed source and use the command wrapper's local
  runtime volumes. The policy image contains both native CLIs and pinned assets.
- [Factory](../factory/replay.md): import a compatible recording and select an explicit
  Blender/Cycles backend for complex-background video.

Python 3.12, uv, and the chosen native CLI are required for native policy
execution. Follow the selected engine's guide for its Node.js and authentication
requirements. Use the platform's documented graphics dependencies and run an
actual RGB check before starting tasks. Do not copy a macOS `.venv` to Linux.

The Linux observation default is NVIDIA EGL. Install working NVIDIA drivers and
EGL dependencies, or explicitly choose CPU rendering with Mesa OSMesa/llvmpipe.
Physics runs on CPU in both cases. The current headless paths do not require
GLFW/Xvfb as the normal launch method, and do not silently switch from GPU to CPU.
A hidden legacy GLFW window alone never established headless compatibility.

## Prepare the checkout

Run from the intended Linux checkout:

```sh
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap
.venv/bin/python -m scripts.benchmark_handoff init-env
.venv/bin/robofrontier plan
.venv/bin/robofrontier doctor
```

`init-env` creates the local private `.env` only when absent. Fill the selected
credential there or export its environment variable; do not put secret values
in TOML, model JSON, command arguments, or logs. Existing process environment
variables take precedence. The `.env` reader accepts literal assignments and
does not execute shell commands. API authentication does not require a Codex
subscription login. Subscription authentication is a separate engine-specific
choice; concurrent refresh and Slurm credential staging are not qualified by
these instructions.

`bootstrap` downloads the pinned policy release archive, verifies its SHA-256,
and restores/checks the referenced files. It reuses already verified assets.
Preparation also checks and restores needed pinned assets. Neither action calls
a model. Current tasks do not require a colleague's private `runs/state-assets/`
cache or their original worktree. Optional Factory recordings use a separate
bundle. Do not replace missing assets with similar-looking images or change
hashes to bypass an audit.

For a CPU-only host, create a local partial settings file:

```toml
# cpu.toml
[render]
device = "cpu"
```

Pass `--config cpu.toml` before each subcommand and use
`robofrontier --config cpu.toml doctor`. A renderer selected only for doctor does
not change an already frozen batch.

## Authorize and launch a new batch

Review `plan` first. The defaults select all 36 tasks, Luna high through the
official API, Adaptive, 36 concurrent task slots, and 0.3 seconds between initial
host launches. Those settings are configurable; they are not a claim that a
particular host or provider can sustain 36 tasks and all their delegates.

A provider preflight is a separate billable operation:

```sh
.venv/bin/robofrontier preflight --confirm-spend
.venv/bin/robofrontier prepare --output runs/policy/NEW_BATCH
.venv/bin/robofrontier run runs/policy/NEW_BATCH
.venv/bin/robofrontier status runs/policy/NEW_BATCH
```

These commands use the repository defaults, including NVIDIA rendering. Apply
the same explicit settings file when choosing another engine, model, provider,
renderer, or concurrency. A prepared batch retains its frozen settings even if
the operator later edits TOML. Preparing does not start task physics or inference
and refuses to overwrite an existing run. Prepare and execute on the target
host: frozen absolute paths are not a portable live checkpoint.

The matching Codex compatibility receipt checks the selected profile/catalog
and native CLI version. A smoke-only result is insufficient. Local image/tool,
manual compaction, and fork checks do not establish the full context window,
automatic compaction threshold, underlying provider identity, or long-term
capacity. Recheck after relevant profile or CLI changes. Claude execution remains
an explicitly unqualified engineering entry requiring `run --engineering`;
see its [native standing-team guide](../engines/claude-code.md#standing-teams).

For queue execution, use `slurm-submit` as documented in the Slurm guide rather
than running policy simulation on a login node. Parallel task slots count whole
tasks, not API requests or roles. Native forks and standing Workers can generate
additional simultaneous requests. Measure CPU, memory, scratch space, image
latency, and provider limits before choosing a large allocation. The launcher
does not silently lower requested concurrency.

## Monitor, stop, and preserve evidence

Use atomic status JSON or the supported command/service interfaces. Keep active
SQLite, CLI state, sessions, and temporary files on local storage. Do not open a
container's live database from macOS or copy a running database to Lustre/NFS.
The Slurm and Docker wrappers enforce their own stopped-data export workflows.

Each public task's default limit is 24 hours from persisted START. The initial
reading and observations count toward that time. A short engineering stop is a
separate external interruption; it must not rewrite the public task's limit.
Request a native orderly stop with:

```sh
.venv/bin/robofrontier stop runs/policy/NEW_BATCH
```

A stop request is not proof of successful sealing. Inspect the execution result,
uncertain calls, evaluation, and collection issues. Query an uncertain physical
request with its original ID; do not automatically replay it under a new ID.
After physical-owner loss, preserve the interrupted run and create a new run
rather than silently reconstructing the old world.

Task evidence resides under the prepared batch's profile/case directories.
Native sessions are collected from the task's recorded engine-specific home.
Current JPEG observations and compressed motion support later offline rendering;
video quality is independent of the model's observation size. See the
[evidence format](evidence-storage.md) and [collection commands](../unified-cli.md).
Do not treat archive creation as a claim that the task succeeded.

## Legacy interfaces

`python -m scripts.benchmark` and `scripts.tasks` remain available for existing
Codex workflows. Their historical defaults, receipts, and frozen paths are not
a substitute for the current TOML. `restore_scene_assets` can restore historical
assets from an original state-asset cache; it audits more historical scenes than
are required by the current policy release. Prefer pinned `bootstrap` for a new
current-task checkout. Historical GLFW/Xvfb and manual cache-copy instructions
apply only to the recordings or runners that actually used them.
