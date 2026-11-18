# Unified command-line configuration

The `roboteam` command plans, prepares, checks, runs and collects batches for both harnesses.
Run it from this checkout's editable installation (`.venv/bin/roboteam`). Global options go
before the subcommand: `--config FILE` (a partial TOML) and `--result-file FILE` (write the
command's result as JSON).

| Command | Does |
| --- | --- |
| `config` | Print the resolved configuration |
| `plan` | List the selected cases; no model calls |
| `prepare --output DIR` | Freeze a new batch; no model calls, no world |
| `doctor` | Local CLI, sandbox and render checks; no model calls |
| `preflight [--confirm-spend] [--smoke-only] [--max-budget-usd N]` | Paid compatibility check |
| `slurm-submit --output DIR [--queue]` | Freeze a Slurm submission, and queue it with `--queue` ([Slurm](hosts/slurm.md)) |
| `bootstrap` | Restore and verify pinned policy assets |
| `run BATCH [--durable] [--foreground] [--continue]` | Run a prepared batch |
| `continue BATCH [--cases ...] [--durable] [--foreground]` | Continue stopped runs by hand |
| `status BATCH`, `stop BATCH` | Read the status snapshot; request a stop |
| `collect`, `archive`, `extract` | Evidence collection and ZIP files ([below](#evidence-and-zip-output)) |
| `container` | The same commands in Docker volumes ([Docker](hosts/docker.md)) |

`config`, `plan`, `prepare`, `doctor`, `preflight` and `slurm-submit` accept the selection
options `--harness {codex,claude}`, `--model`, `--effort`, `--system`,
`--tools {full,robot_only}`, `--parallel`,
`--render {nvidia,cpu,native}`, `--level {1,2,3}`, `--min-arms`, `--cases` and `--task-types`.

## Installation

```sh
uv sync --locked
.venv/bin/roboteam bootstrap
.venv/bin/roboteam plan
```

`bootstrap` downloads the pinned policy asset archive if needed, checks its SHA-256 and restores
every referenced file with hash checks, reusing files that are already correct. Install the CLI of the harness you will use at its pinned
version (`roboteam/runtime/run/versions.py`: Codex 0.165.0, Claude Code 2.1.316); `prepare` and
`run` refuse others ([harness setup](harness/README.md#shared-setup)).

## Defaults and precedence

`roboteam.toml` holds the defaults. A partial user TOML (`--config`) overrides the settings
it names, and command-line options override both. Unknown fields, wrong types, non-finite
intervals and invalid limits are errors. Credentials go in `.env` or the environment, never in
TOML. The `schema_version` is 11, the only one read; a partial TOML may omit it.

```sh
.venv/bin/roboteam config
.venv/bin/roboteam --config my-site.toml plan
.venv/bin/roboteam plan --level 1 --min-arms --parallel 4
```

The default plan selects all 36 released cases with Codex `sol` (gpt-6.1-sol) at effort high, the adaptive
system, 36 runs at once, 0.3 s between host launches, and 24 h of active time per run.

| Setting | Meaning |
| --- | --- |
| `policy.harness` | `codex` or `claude` |
| `policy.model` | Entry in the harness's section of `models.json`. Defaults: `sol` for Codex, `opus` for Claude. |
| `policy.effort` | Requested reasoning effort; must match the preflight receipt |
| `policy.system` | `adaptive`, `single-agent`, `hierarchical` or `decentralized` |
| `policy.tools` | `full` (default) or `robot_only`: the robot tool alone ([robot-only runs](benchmark/robot-tool-only.md)) |
| `batch.parallel` | Runs at once, 1 to 36 |
| `batch.startup_interval_s` | Gap between host launches (0.3 s); never between robot calls |
| `batch.task_wall_limit_s` | Active time per run, 86,400 s ([how it is counted](runs/continuation.md#time)); at most 86,400 for Claude Code |
| `batch.startup_timeout_s` | Owner readiness timeout (600 s) |
| `selection.task_types` / `cases` | Filters on `benchmark/release.json`; empty selects all |
| `selection.level` | 0 for every level, else 1, 2 or 3 |
| `selection.min_arms` | The smallest arm count in each selected task type |
| `render.device` | `nvidia` (Linux EGL), `cpu` (Linux OSMesa) or `native` (macOS) |
| `render.observation_profile` | `jpeg_1280x800_q90` (default) or `jpeg_128x80_q95` (the low-resolution condition) |
| `render.record_realtime_video` | Live MP4 recording, off by default |
| `runtime.codex_home_scope` | `task` (one home per run), `shared` (ChatGPT login) or `job` (Slurm subscription) |
| `runtime.codex_home` | Home root; empty picks one automatically; must be outside the batch |
| `runtime.codex_tool_backend` | `native` or `landlock-v1` ([Codex isolation](harness/codex.md#isolation)) |
| `evidence.auto_collect` / `auto_archive` | Collect after the supervisor exits; then build a verified ZIP |
| `evidence.delete_sources` | Must stay false |
| `slurm.*` | Allocation, authentication and egress settings ([Slurm](hosts/slurm.md)) |
| `container.workspace` / `image` / `memory_gib` / `cpus` | Docker volumes, image tag and limits (0 adds none) |
| `container.seccomp_profile` | `default`, or `unconfined` for Codex's nested sandbox |
| `paths.runs_root` | Where runs, receipts, exports and caches go; empty is `<repo>/runs`; `ROBOTEAM_RUNS_ROOT` overrides |

## Settings files

Settings for new runs start in `roboteam.toml`. The loader layers the repository defaults, a
partial site TOML (`roboteam --config FILE ...`) and command-line options, in that order, rejects
unknown fields, and freezes the result into each new batch; changing a setting never changes a
prepared batch.

| Path | What it is |
| --- | --- |
| `roboteam.toml` | The defaults for new runs |
| `models.json` | Every selectable model, one section per harness (`harnesses.codex`, `harnesses.claude`, which also holds Claude transcript prices). A run freezes its harness's section |
| `roboteam/runtime/run/defaults.json` | The policy runtime's settings (system, startup protocol, timeouts, check intervals, motion and video rates); no speeds or forces, which every action states. A batch sets the harness, system, model and effort over it |
| `roboteam/runtime/sandbox/policy-env/` | The policy Python environment's inputs (`core.in`, `store.in`) and locks (`core.lock`, `all.lock`) |
| `roboteam/harness/adapters/*/requirements.txt` | The optional dependencies of the two model adapters: `claude_in_codex` (opus-5.5 in Codex) and `gpt_in_claude` (gpt-6.1-sol in Claude Code) |
| `benchmark/assets.json` | The pinned policy asset archive and its inventory, restored by `roboteam bootstrap` |
| `docs/hosts/examples/mac.toml`, `slurm.toml`, `linux.toml` | A starting site TOML for each platform; copy one to an untracked file |

Credentials belong in the ignored `.env` or the environment, never in these files. Choosing a
model name alone does not establish provider compatibility: a run needs passed preflight
receipts for its model.

## Startup in all four modes

| Agent system | START |
| --- | --- |
| `adaptive` | `direct_controller` |
| `single-agent` | `direct_controller` |
| `hierarchical` | `direct_team` |
| `decentralized` | `direct_team` |

The owner prepares the world and the host binds every initial session; then the runtime persists
one START and the host tells each initial role that the run has started. Reading, observing and
planning count. `ready` is only a capability query. A binding or START failure, or a stop during
setup, blocks the first model input. Starting does not give a Controller its Workers' robots.

## Render backends

`nvidia` creates a headless EGL context; `cpu` uses Mesa llvmpipe through OSMesa and hides CUDA
devices from the process; `native` uses macOS OpenGL. A backend for the wrong OS is an error, and
nothing falls back silently. Physics runs on the CPU with every backend. Drivers and system GL
libraries are not installed by `uv sync`.

## Models, credentials and preflight

Each model names its credential variable ([authentication matrix](harness/README.md#authentication-matrix)).
`.env` is read as literal values; a variable already in the environment wins.

```sh
.venv/bin/roboteam preflight --confirm-spend                 # Codex, full
.venv/bin/roboteam preflight --confirm-spend --smoke-only    # Codex, does not qualify a run
.venv/bin/roboteam preflight --harness claude --max-budget-usd 1 --confirm-spend
```

Without `--confirm-spend` no model is called and the result is `not_run`. Receipts go under
`<runs_root>/engineering/`; `run` refuses a batch whose model, catalog or CLI version does not
match a passed receipt. Details: [Codex](harness/codex.md#preflight-and-receipts) and
[Claude Code](harness/claude-code.md#preflight-and-receipts).

## Run, monitor and stop

```sh
.venv/bin/roboteam run runs/policy/my-batch
.venv/bin/roboteam status runs/policy/my-batch
.venv/bin/roboteam stop runs/policy/my-batch
.venv/bin/roboteam continue runs/policy/my-batch [--cases CASE ...]
```

`run` reads the frozen `effective-config.json`, checks its fingerprint against the batch metadata
and every run's input inventory; a changed local TOML does not affect a prepared batch, so prepare
a new batch to change anything. On macOS `run` submits the batch as a user launchd job with
`ProcessType=Interactive` under `caffeinate`, which outlives the terminal; `run --continue` and
`continue` get jobs of their own (`control/durable/continue-N/`). `--foreground` runs the
supervisor in the current process. On Linux `--durable` uses a systemd user service or a setsid
daemon; without it the supervisor runs in the foreground. A service keeps using the source it
started from, so keep active runs on their checkout and develop in another worktree.

`status` reads the supervisor's JSON snapshot, never a live database. `stop` writes stop markers;
check the seal and status afterwards. `continue` continues stopped runs by hand as the same trials,
also after a finish or cutoff (the score stands); an unexpected stop already continues by itself
once ([continuation](runs/continuation.md#continuing-by-hand)). Platforms:
[Mac](hosts/mac.md), [RunPod and plain Linux](hosts/linux.md), [Slurm](hosts/slurm.md),
[Docker](hosts/docker.md). Keep live databases on local storage, never Lustre or NFS, and never
open a Docker writer's database from the host.

## Evidence and ZIP output

With `evidence.auto_collect`, once every task host has exited the CLI collects the batch into
`<runs_root>/exports/<batch-name>-<hash>/` and, with `auto_archive`, writes the verified
`<batch-name>-<hash>.zip` beside it. By hand:

```sh
.venv/bin/roboteam collect runs/policy/my-batch --output runs/exports/manual-collection
.venv/bin/roboteam archive runs/exports/manual-collection --output runs/exports/manual.zip
.venv/bin/roboteam extract runs/exports/manual.zip --output runs/restored/manual-archive
.venv/bin/python -m roboteam.launch.results.archive_batch restore runs/restored/manual-archive \
  --output runs/restored/manual-evidence
```

`extract` recovers the manifest and deduplicated objects; `restore` rebuilds native session and
motion paths and checks every original byte hash. The archive replaces repeated image payloads with
reversible references; motion keeps its float32 capture and XOR/ZIP encoding. Nothing is deleted:
the batch and the collection stay until an operator removes them after verifying a restore. See
[evidence storage](runs/evidence-storage.md).
