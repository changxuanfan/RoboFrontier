# Unified command-line configuration

This interface is being integrated on `integration/unified-main`. It has not yet
replaced the GitHub default branch. See the [acceptance ledger](archive/unified-main.md)
for checks still required before publishing a unified release.

## Installation in this checkout

```sh
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap
.venv/bin/robofrontier plan
```

Before a paid provider check or run, use `robofrontier doctor --render cpu` on
Linux software rendering, `--render native` on macOS, or the default NVIDIA
backend on an equipped Linux host. Doctor performs only local native CLI,
Codex-sandbox and actual RGB-render checks. It does not authenticate or call a
model. Confirmed preflight checks local native prerequisites first; run checks
both native prerequisites and the frozen renderer before starting task hosts.

`bootstrap` downloads the pinned policy asset package if needed, checks its
SHA-256, and restores each referenced file with hash verification. It reuses
already verified files. It does not call a model or download the larger optional
Factory recording bundle. A plain `git clone` cannot execute an installation
step; run the bootstrap command after installing Python dependencies.

The development checks use Codex CLI 0.165.0 and Claude Code 2.1.312. These are
observed local versions, not a claim about the latest upstream versions. Install
the CLI for the engine you intend to use. A changed Codex CLI version invalidates
an existing provider compatibility receipt and requires another preflight.

The `robofrontier` executable selects the unified CLI. Run these commands from an editable repository installation;
a standalone wheel containing the required catalogs and assets is not yet a
qualified distribution format.

For queue execution, use the frozen, node-local [Slurm submission flow](running/slurm.md).
It has a separate `[slurm]` section in the same TOML and does not copy active
SQLite databases to shared storage. Real-cluster acceptance remains pending.

For Linux Docker or Docker Desktop, use the [container command flow](running/docker.md).
It builds committed source and keeps active runtime/session data in plain local
Docker volumes. Verified stopped ZIPs are exported back to the worktree.

## Defaults and precedence

The repository's `robofrontier.toml` contains the defaults. A partial user TOML
overrides its named settings; explicit CLI options override those settings.
Unknown fields, incorrect types, non-finite intervals and invalid limits are
errors. Credentials belong in `.env` or the environment, never in TOML.

New settings use `schema_version=5`, with independent Factory and Oracle sections
and an explicit Oracle evaluation mode. Frozen version 1, 2 and 3 configurations retain their exact shapes and hashes;
new sections are not appended to archived configurations. New partial user TOML files
can omit the version to inherit the current schema. A frozen configuration is
evidence, not an operator settings template to overwrite.

```sh
.venv/bin/robofrontier config
.venv/bin/robofrontier --config /path/to/my-settings.toml plan
.venv/bin/robofrontier plan --level 1 --min-arms --parallel 4
```

The default plan selects all 36 current released cases, Luna high, the official
OpenAI API profile, adaptive topology, 36 concurrent task slots, and a minimum
0.3-second interval between host-launch attempts. START is independent per task;
36 launches span at least approximately 10.5 seconds. Preparation/initialization
is additional. The interval does not delay individual robot calls, file reads,
physics steps, or model turns. It is not a provider rate-limit guarantee.

| Setting | Meaning |
| --- | --- |
| `policy.engine` | Native `codex` or native `claude` runner |
| `policy.profile` | Engine-specific entry in `configs/models.json` or `configs/claude-models.json` |
| `policy.effort` | Explicit requested reasoning effort; must pass the provider's preflight |
| `policy.topology` | `single`, `controller-worker`, `worker-worker`, or `adaptive` |
| `batch.parallel` | Maximum concurrent task hosts, from 1 to 36; no automatic reduction |
| `batch.startup_interval_s` | Global interval within this batch supervisor, default 0.3 seconds |
| `batch.task_wall_limit_s` | Per-task limit of active running time, default 86,400 seconds ([how it is counted](running/run-segments.md#time)) |
| `batch.startup_timeout_s` | Owner readiness timeout; distinct from task time and transport acknowledgement timeouts |
| `selection.families` / `cases` | Filters against the current release registry |
| `selection.level` | 0 for every level, otherwise 1, 2 or 3 |
| `selection.min_arms` | Select the smallest released arm count within each selected family |
| `render.device` | Explicit backend; no silent GPU-to-CPU fallback |
| `render.observation_profile` | Default `jpeg_896x560_q85`; legacy `png_1280x800` remains readable |
| `render.record_realtime_video` | Optional live video recording, disabled by default; separate from later motion-based rendering |
| `runtime.codex_home_scope` | Isolate API task homes, or explicitly retain shared-home behavior |
| `runtime.codex_home` | Optional home root; must remain outside the batch's collected evidence tree |
| `runtime.codex_tool_backend` | `native` by default; explicit `landlock-v1` confines Codex file tools on Linux containers without namespaces |
| `evidence.auto_collect` | Collect stopped native sessions, motion and audit evidence after the supervisor exits |
| `evidence.auto_archive` | Create a verified portable ZIP from that collection |
| `evidence.delete_sources` | Must remain false; automatic destructive cleanup is not implemented |
| `container.workspace` | Separate persistent Docker volumes for this checkout/workspace |
| `container.image` | Optional image tag; its source revision must match the checkout commit |
| `container.memory_gib` / `cpus` | Optional container resource limits; zero adds no quota |
| `container.seccomp_profile` | `default`, or explicit `unconfined` for Codex containers whose namespace sandbox is otherwise denied; see Docker security notes |
| `factory.device` / `blender` | Explicit offline Cycles backend and optional executable path; separate from observation rendering |
| `factory.width` / `height` / `samples` | Independent offline video quality; default 1920 x 1080, 64 samples |
| `factory.mode` / `views` | Station views or the full 210.5-second Factory tour |
| `factory.duration_s` | 0 preserves the reviewed full timeline; a positive value explicitly caps a preview |
| `factory.data_root` / `asset_lock` / `source` | Pinned release installation or an explicitly imported closed-recording bundle |
| `factory.import_speedup` | Speed for a newly imported recording only; 0 uses the family release speedup; existing release edits remain intact |
| `factory.parallel` | Render array concurrency, independent of benchmark task concurrency |
| `oracle.wall_limit_s` | Engineering elapsed limit from native owner launch, including planning and pauses; independent of policy START |
| `oracle.stop_grace_s` | Cleanup allowance after a stop request before forced process-group termination |
| `oracle.mosaic_planning_workers` / `mosaic_physics_workers` | Scratch endpoint processes / optional threads in the one live Mosaic world |
| `oracle.mosaic_max_goals` | 0 attempts the full Mosaic task; positive limits are partial commissioning |

The current schema covers policy execution, evidence, Slurm resources,
Factory replay/render preparation and native Oracle supervision. See the
[Factory guide](factory/replay.md) and [Oracle guide](oracle/README.md) for their subcommands.
Editorial camera/title/subtitle inputs use the
[project commands](factory/editorial.md): `factory project`,
`factory prepare --project`, and `factory edit-video`. These specialized project
files and typed live Oracle recovery retain their native interfaces. They are
not interpreted as unsupported TOML
options. The policy evidence auto-collection flags apply to policy batches, not
to a native Oracle directory.

## Startup in all four modes

New Single and Adaptive tasks use `direct_controller_v2`. New Controller + Worker
and Worker-Worker tasks use `direct_team_v3`. The owner first prepares the world
and the host binds every required initial native session. The runtime then
persists one START timestamp and the host explicitly tells each initial role
that the experiment has started. Initial reading, observation and planning are
inside the task clock. Session/environment preparation happens before START.

`ready` is an optional capability query for every role under direct start. It
does not unlock START and its response does not require a waiting turn. New
requests follow the current role's ownership and communication permissions:
direct start does not give a coordinating Controller its Workers' robots.

Existing `ready_barrier_v1` inputs retain their legacy startup behavior. They
are not rewritten or silently upgraded. A new fixed-team batch prepared through
either the unified CLI or a profile with `benchmark_topology` uses direct team
start. Binding/START failure or STOP during setup blocks initial model input.

## Render backends

Linux NVIDIA EGL is the default. `render.device="cpu"` selects Linux OSMesa with
Mesa llvmpipe and disables CUDA visibility in that process environment.
`render.device="native"` selects macOS native OpenGL. Native macOS rendering does
not promise CPU-only rendering. Choosing a backend for the wrong OS is an error.

```sh
# A partial macOS configuration
cat > /tmp/robofrontier-mac.toml <<'EOF'
[render]
device = "native"
EOF

# Plan/prepare only: no model calls or simulation launch.
.venv/bin/robofrontier --config /tmp/robofrontier-mac.toml prepare \
  --output runs/policy/my-l1-batch --level 1 --min-arms --parallel 4
```

On macOS, `robofrontier run BATCH` submits the batch as a user launchd job with
`ProcessType=Interactive` by default (`--durable` says so explicitly), so benchmark work
receives application-class CPU and I/O scheduling, keeps the Mac awake through `caffeinate`
for the job's life, and outlives the terminal or the agent session that started it.
`run BATCH --continue` does the same in a job of its own (`control/durable/continue-N/`).
Follow it with `robofrontier status BATCH`. `--foreground` runs the supervisor in the
current process at that process's own priority, as on Linux. This process classification does not
force every thread to use the highest QoS. It applies to newly submitted services;
changing source code does not reload an existing service. Keep active runs on
their original source checkout and use a separate worktree for development,
because run integrity checks verify the live source files.

The NVIDIA/EGL owner path now creates a headless EGL context rather than opening
a GLFW window. NVIDIA hardware verification remains required. Installing a
Python environment alone does not install NVIDIA drivers or system OSMesa/EGL
libraries. MuJoCo dynamics remain on the CPU for every observation backend.

## Models, credentials and preflight

The API `luna` profile reads `OPENAI_API_KEY`. OpenLux profiles read
`OPENLUX_API_KEY`; third-party profiles declare their own environment variable
names and protocol endpoints in their catalog. `.env` is parsed as literal
values; existing process environment values take precedence. Never paste secrets
into a shared prompt, Git commit, task file or report.

```sh
# Explicit paid image/tool/compaction/fork connectivity check.
.venv/bin/robofrontier preflight --confirm-spend

# A smaller image/tool smoke test does not qualify scored runs.
.venv/bin/robofrontier preflight --confirm-spend --smoke-only
```

Calling `preflight` without `--confirm-spend` makes no model calls and returns a
non-success status. Full Codex receipts are written under
`runs/engineering/model-compatibility/<profile>/report.json`. The requested
profile, generated model catalog and actual CLI version must match before a task
can run. A passed preflight does not establish the provider's internal model
identity, unlimited capacity, or full benchmark qualification.

New unified Codex runs use the checked-in model metadata template rather than a
different Desktop session's mutable model cache. Preparation and preflight use
the same policy, and the resulting catalog is frozen with each task.

API task homes are created automatically and initialized serially before any
task host launches. Each task's Controller, delegate snapshots and delegates use
that task's same home so native fork lineage stays accessible. Different tasks
have different homes. The default root is `.robofrontier/codex/`; each task stores
its resolved location in `<run>/codex-home.json`. Native transcripts are under
that home's `sessions/` tree. These locations are Git-ignored.

The new isolated-home path does not clone subscription credentials. Native
subscription profiles currently require an explicitly configured shared home
and matching preflight; refresh/isolation qualification is pending. A 0.3-second
launch interval alone does not prove that all shared-config races are solved.
See [official Codex authentication documentation](https://developers.openai.com/codex/auth/)
for file versus OS credential storage and native sign-in behavior.

Claude planning/preparation uses its native catalog and runner. All four
topologies have engineering entries. Standing modes create one native Claude
session per initial role and use the shared mailbox/scheduler; they are not
simulated Adaptive delegations. See [Claude standing teams](engines/claude-code.md#standing-teams)
for role counts and the scoped checks. Formal scored qualification remains closed.

```sh
.venv/bin/robofrontier plan --engine claude --profile haiku --level 1 --min-arms
.venv/bin/robofrontier preflight --engine claude --profile haiku \
  --max-budget-usd 1 --confirm-spend
.venv/bin/robofrontier prepare --engine claude --profile haiku --render native \
  --output runs/engineering/claude-l1 --level 1 --min-arms --parallel 4
.venv/bin/robofrontier run runs/engineering/claude-l1
```

Claude preflight's cost estimate is not an absolute provider billing cap. Normal
Claude policy execution retains optional budgets rather than introducing new
default dollar limits.

## Run, monitor and stop

```sh
.venv/bin/robofrontier run runs/policy/my-l1-batch
.venv/bin/robofrontier status runs/policy/my-l1-batch
.venv/bin/robofrontier stop runs/policy/my-l1-batch
```

`run` reads the frozen `effective-config.json`, verifies its fingerprint against
batch metadata, and checks every task's immutable input inventory. Changing
local TOML after preparation does not alter that batch. Prepare a new batch for
a changed model, topology, image profile or task limit. An existing world is
never automatically recreated or restarted.

`status` reads the supervisor's atomic JSON snapshot. It does not open a live
SQLite database, and it is not a live per-arm view. `stop` writes stop markers;
inspect the resulting seal and status because a stop request is not proof that
all physical actions have settled. Preserve uncertain-action evidence for review.

Active SQLite/Codex state must be on node-local storage. The legacy Slurm scripts
are not qualified by this new CLI alone; the node-local benchmark staging path
is still an integration gate. Do not use a shared Lustre/NFS batch directory as
live runtime storage. Do not open a Docker writer's active database from macOS.

## Evidence and ZIP output

After every task host has exited, automatic collection acquires the existing
writer locks, verifies stable input files and native session associations, and
collects evidence under `runs/exports/<batch-name>-<path-hash>/`. The adjacent
`<batch-name>-<path-hash>.zip` contains a verified content-addressed archive.
Incomplete or reviewed runs keep their recorded issues; archival does not turn
them into successful or qualified runs.

```sh
.venv/bin/robofrontier collect runs/policy/my-l1-batch --output runs/exports/manual-collection
.venv/bin/robofrontier archive runs/exports/manual-collection --output runs/exports/manual.zip
.venv/bin/robofrontier extract runs/exports/manual.zip --output runs/restored/manual-archive
.venv/bin/python -m robofrontier.batch.archive_policy_batch restore runs/restored/manual-archive \
  --output runs/restored/manual-evidence
```

Extraction recovers the archive's manifest and deduplicated objects; the final
restore reconstructs native session and motion paths. It verifies the original
byte hashes, including images removed from Base64 fields during archival.

Native sessions remain append-only while running. The archive replaces repeated
image payloads with reversible references and shares identical files/objects;
it does not remove images from provider requests. Motion's existing float32
capture and XOR/ZIP encoding are retained, including stationary frames, timing
and appearance events. No extra quantization or frame deletion is introduced.
Old uncompressed motion and native image-bearing sessions remain supported.

Both the original batch and collected files remain after ZIP creation. This
costs additional storage until an operator verifies a restore and explicitly
cleans up the intended original paths. The automatic commands never delete
running evidence, credentials, original data or a pre-existing output directory.
