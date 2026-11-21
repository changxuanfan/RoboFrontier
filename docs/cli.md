# Command line and settings

The `roboteam` command plans, prepares, checks, runs and collects batches for both harnesses.
Run it from the repository root as `.venv/bin/roboteam`. [Getting started](getting-started.md)
walks through a first run; this page is the reference.

## Commands

Two global options go before the command: `--config FILE` (a site TOML that overrides some
defaults) and `--result-file FILE` (also write the command's result as JSON to a file).

| Command | What it does | Calls a model |
| --- | --- | --- |
| `config` | Prints the resolved settings | No |
| `plan` | Lists the selected tasks, the model and the policy environment | No |
| `doctor` | Checks the harness CLI, its sandbox and the renderer on this machine | No |
| `bootstrap` | Downloads and verifies the pinned assets | No |
| `preflight [--confirm-spend] [--smoke-only] [--max-budget-usd N]` | Checks that the model works with the harness and writes a receipt | Yes, with `--confirm-spend` |
| `prepare --output DIR` | Freezes a new batch into `DIR`; starts no world | No |
| `run BATCH [--durable] [--foreground] [--continue]` | Runs a prepared batch | Yes |
| `continue BATCH [--cases ...] [--durable] [--foreground]` | Continues stopped runs by hand, as the same trials | Yes |
| `status BATCH` | Prints the supervisor's last status snapshot | No |
| `stop BATCH` | Asks every run of the batch to stop in order | No |
| `collect BATCH --output DIR` | Copies a stopped batch's evidence into a collection | No |
| `archive COLLECTION --output ZIP` | Packs a collection into a verified ZIP | No |
| `extract ZIP --output DIR` | Verifies and unpacks an evidence ZIP | No |
| `slurm-submit --output DIR [--queue]` | Freezes a Slurm submission and, with `--queue`, queues it ([Slurm](hosts/slurm.md)) | No |
| `container ...` | Runs the same commands inside Docker ([Docker](hosts/docker.md)) | Depends on the command |

`config`, `plan`, `doctor`, `preflight`, `prepare` and `slurm-submit` accept the selection
options:

| Option | Values | Setting |
| --- | --- | --- |
| `--harness` | `codex`, `claude` | `policy.harness` |
| `--model` | An entry of the harness's section of `models.json` | `policy.model` |
| `--effort` | `minimal`, `low`, `medium`, `high`, `xhigh`, `max` | `policy.effort` |
| `--system` | `adaptive`, `single-agent`, `hierarchical`, `decentralized` | `policy.system` |
| `--tools` | `full`, `robot_only` | `policy.tools` |
| `--observation` | `images`, `ground_truth` | `policy.observation` |
| `--task-types` | One or more of `transport`, `mosaic`, `relay`, `dial` | `selection.task_types` |
| `--level` | `1`, `2`, `3` | `selection.level` |
| `--min-arms` | Flag: only the cases with the fewest arms in each selected task type | `selection.min_arms` |
| `--cases` | One or more task ids, such as `transport-small-l1` | `selection.cases` |
| `--parallel` | 1 to 36 | `batch.parallel` |
| `--render` | `nvidia`, `cpu`, `native` | `render.device` |

```sh
.venv/bin/roboteam config
.venv/bin/roboteam plan --level 1 --min-arms --parallel 4
.venv/bin/roboteam plan --harness claude --task-types relay --level 1
.venv/bin/roboteam --config docs/hosts/examples/mac.toml plan
```

## Defaults and precedence

`roboteam.toml` holds the defaults. A site TOML (`--config`) overrides the settings it names,
and command options override both. Unknown fields, wrong types and invalid values are errors.
`schema_version` is 11, the only version read; a site TOML may omit it. Credentials go in
`.env` or the environment, never in a TOML file.

The default plan selects all 36 tasks with Codex and the model `sol` (gpt-6.1-sol) at effort
`high`, the `adaptive` system, 36 runs at once and 24 hours of active time per run.
`--harness claude` without a model selects `opus` (claude-opus-5-5).

| Setting | Meaning |
| --- | --- |
| `policy.harness` | `codex` or `claude` |
| `policy.model` | An entry of the harness's section of `models.json`. Defaults: `sol` for Codex, `opus` for Claude Code |
| `policy.effort` | The reasoning effort requested from the model; must match the preflight receipt |
| `policy.system` | `adaptive`, `single-agent`, `hierarchical` or `decentralized` |
| `policy.tools` | `full` (default) or `robot_only`: the robot tool alone ([robot-only runs](benchmark/robot-tool-only.md)) |
| `policy.observation` | `images` (default) or `ground_truth`: the simulator's state instead of camera images ([ground-truth observation](benchmark/rules.md#ground-truth-observation)) |
| `batch.parallel` | Runs at once, 1 to 36 |
| `batch.startup_interval_s` | Gap between the launches of two runs (0.3 s) |
| `batch.task_wall_limit_s` | Active time per run, 86,400 s ([how it is counted](runs/time.md)); at most 86,400 for Claude Code |
| `batch.startup_timeout_s` | How long a run's world may take to become ready (600 s) |
| `selection.task_types`, `selection.cases` | Filters on the released tasks; empty selects all |
| `selection.level` | 0 for every level, else 1, 2 or 3 |
| `selection.min_arms` | Only the cases with the fewest arms in each selected task type, after the level filter. With every level selected this leaves 10 cases: Dial has 4 arms only at level 1 |
| `render.device` | `auto` (default), `nvidia` (Linux EGL), `cpu` (Linux OSMesa) or `native` (macOS). `auto` picks `native` on macOS, `nvidia` on Linux with an NVIDIA GPU, else `cpu` |
| `render.observation_profile` | `jpeg_1280x800_q90` (default) or `jpeg_128x80_q95`, the low-resolution condition ([observation images](benchmark/rules.md#observation-images)) |
| `render.record_realtime_video` | Record an MP4 of each run while it runs; off by default; needs `ffmpeg` |
| `runtime.codex_tool_backend` | `auto` (default), `native` or `landlock-v1`. `auto` picks `native` on macOS and `landlock-v1` on Linux ([Codex isolation](harness/codex.md#isolation)). Codex only |
| `runtime.codex_home_scope` | Where Codex keeps its sessions and login: `task` (one home per run, the default), `shared` (one home with a ChatGPT login) or `job` (Slurm subscription jobs) |
| `runtime.codex_home` | The home's folder; empty picks one automatically; must be outside the batch |
| `evidence.auto_collect`, `evidence.auto_archive` | Collect the batch when it ends, then build a verified ZIP; both on by default |
| `evidence.delete_sources` | Must stay `false` |
| `slurm.*` | The allocation, authentication and network route of a Slurm job ([Slurm](hosts/slurm.md)) |
| `container.workspace`, `container.image`, `container.memory_gib`, `container.cpus` | Docker volumes, image tag and limits (0 adds none) |
| `container.seccomp_profile` | `default`, or `unconfined` where Docker's seccomp filter refuses the sandbox ([Docker](hosts/docker.md#limits)) |
| `paths.runs_root` | Where runs, receipts and exports go; empty is `<repo>/runs`; `ROBOTEAM_RUNS_ROOT` overrides it |

## Settings files

Settings for new runs come from these files. `prepare` freezes the result into each new batch;
changing a file never changes a prepared batch.

| Path | What it is |
| --- | --- |
| `roboteam.toml` | The defaults for new runs |
| `models.json` | Every selectable model, one section per harness (`harnesses.codex`, `harnesses.claude`). A run freezes its harness's section |
| `roboteam/runtime/run/defaults.json` | Settings of the runtime inside a run: timeouts, check intervals, message limits, motion and video rates. A batch sets the harness, system, model and effort over it |
| `roboteam/runtime/sandbox/policy-env/` | The package lists and locks of the [policy Python environment](hosts/policy-environment.md) |
| `roboteam/harness/adapters/*/requirements.txt` | The optional dependencies of the two [adapters](harness/README.md#guides) |
| `benchmark/assets.json` | The pinned asset archive, restored by `roboteam bootstrap` |
| `docs/hosts/examples/mac.toml`, `linux.toml`, `slurm.toml` | A starting site TOML for each platform; copy one to an untracked file |

Choosing a model name does not make the model work with a harness: a run needs a passed
preflight receipt for its model.

## Renderers

`nvidia` creates a headless EGL context. `cpu` uses Mesa's software renderer through OSMesa.
`native` uses macOS OpenGL. A renderer for the wrong operating system is an error, and one
never falls back to another. Physics runs on the CPU with every renderer. `uv sync` installs
no graphics drivers or system OpenGL libraries.

## Preflight

```sh
.venv/bin/roboteam preflight --confirm-spend                 # Codex, full check
.venv/bin/roboteam preflight --confirm-spend --smoke-only    # Codex, smaller check; does not admit a run
.venv/bin/roboteam preflight --harness claude --max-budget-usd 1 --confirm-spend
```

Without `--confirm-spend` no model is called and the result is `not_run`. Receipts go under
`<runs root>/receipts/`. `run` refuses a batch whose model, model catalog or CLI version
does not match a passed receipt. Details: [Codex](harness/codex.md#preflight-and-receipts),
[Claude Code](harness/claude-code.md#preflight-and-receipts).

## Run, watch and stop

```sh
.venv/bin/roboteam run runs/batches/my-batch
.venv/bin/roboteam status runs/batches/my-batch
.venv/bin/roboteam stop runs/batches/my-batch
.venv/bin/roboteam continue runs/batches/my-batch --cases transport-small-l1
```

`run` reads the batch's frozen `effective-config.json`, not `--config`. To change anything,
prepare a new batch.

| Platform | `run` and `continue` |
| --- | --- |
| macOS | Submit the batch as a user launchd job under `caffeinate` and return. The job outlives the terminal. `--foreground` runs in the current process instead |
| Linux | Run in the current shell. `--durable` starts a background service instead: a systemd user service, or a `setsid` daemon where there is no user systemd |

A background service keeps using the source it started from. Keep active runs on a checkout
that nothing edits, and develop in another worktree ([Mac](hosts/mac.md#6-prepare-and-run)).

`run --continue` picks up a batch whose supervisor died. `continue` continues stopped runs by
hand, also after a finish or a cutoff (the score stands). An unexpected stop already continues
by itself once ([continuing a stopped run](runs/continuation.md)).

`status` reads a JSON snapshot that the supervisor writes; it never opens a live database.
`stop` writes stop markers; check `status` and each run's `seal.json` afterwards.

Keep live run databases on local storage, never on Lustre or NFS, and never open the database
of a run inside Docker from the host.

## Evidence and ZIP output

When every run of a batch has stopped, `run` collects the batch into
`<runs root>/exports/<batch>-<hash>/` and writes the verified ZIP `<batch>-<hash>.zip` beside
it. By hand:

```sh
.venv/bin/roboteam collect runs/batches/my-batch --output runs/exports/my-batch
.venv/bin/roboteam archive runs/exports/my-batch --output runs/exports/my-batch.zip
.venv/bin/roboteam extract runs/exports/my-batch.zip --output runs/restored/my-batch-objects
.venv/bin/python -m roboteam.launch.results.archive_batch restore runs/restored/my-batch-objects \
  --output runs/restored/my-batch
```

`extract` verifies the ZIP and unpacks its compressed objects. `restore` rebuilds the original
files from them and checks every hash. Nothing is deleted: the batch and the collection stay
until you remove them. See [evidence storage](runs/evidence-storage.md).
