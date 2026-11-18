# Getting started

This guide takes a fresh clone to one finished, collected run on one machine: the smallest
Transport task with a 30-minute limit. It follows the steps of the "Getting started" section of
the [README](../README.md) and adds what each command checks and what to do when it fails. Run
every command from the repository root.

The examples use Claude Code. For Codex, replace `--harness claude` with `--harness codex` and
leave out `--max-budget-usd`.

Words this guide uses:

| Word | Meaning |
| --- | --- |
| Task (or case) | One of the 36 released tasks, such as `transport-small-l1` |
| Run | One attempt at one task by one team of agents. A run is one trial |
| Batch | A folder of prepared runs that start and are supervised together |
| Harness | The coding-agent program the agents run in: Codex or Claude Code |
| Model | An entry of [`models.json`](../models.json), such as `sol` or `opus`. It names the provider's model and its credential |
| System | How the agents are organized: `adaptive`, `single-agent`, `hierarchical` or `decentralized` |
| Policy | The team of agents that is measured in a run |
| World | The simulation of one run. It advances in real time from the run's START |

The [documentation index](README.md#terms) defines the other terms the guides use.

## 1. What you need

| Need | Version and notes |
| --- | --- |
| Operating system | macOS on Apple silicon, or Linux with glibc 2.28 or newer |
| [uv](https://docs.astral.sh/uv/) | Installs Python 3.12 (`.python-version`) and the locked packages of `uv.lock` |
| Node.js and npm | Node.js 22 is what CI uses. The harness CLIs and the Codex host need it |
| `ffmpeg` | Encodes the video of a run when recording is on (`render.record_realtime_video`); some tests use it |
| Harness CLI | Exactly the pinned version: Claude Code `2.1.316` or Codex `0.165.0` (`roboteam/runtime/run/versions.py`). Install only the harness you will run |
| Rendering | macOS: its own OpenGL. Linux: an NVIDIA GPU with EGL, or Mesa OSMesa on the CPU (the system package `libosmesa6` or its equivalent) |
| Linux sandbox | `bwrap` and `socat` where user namespaces work; otherwise Linux 6.7 or newer (Landlock ABI 4) with `libseccomp` |
| A model account | An API key, or a Claude subscription token, for a model in `models.json` |
| Network | For `bootstrap` (an archive of about 190 MB), for building the policy environment, and for the model provider |

`prepare` and `run` refuse a harness CLI, MuJoCo, NumPy or Pillow version other than the pinned
one.

## 2. Install

```sh
git clone https://github.com/changxuanfan/RoboTeam.git
cd RoboTeam
uv sync --locked
.venv/bin/roboteam bootstrap
```

`bootstrap` downloads the asset archive named in `benchmark/assets.json`, checks its SHA-256
and restores every file with a hash check: the scene meshes and textures under
`benchmark/<task type>/<case>/assets/`, the built factory hall under `benchmark/hall/built/`
and the Franka Panda model under `vendor/panda/`. It reuses files that are already correct and
calls no model. On failure it names the file or hash that differs; do not substitute another
archive. On a machine without network access, copy the archive over and run
`.venv/bin/python -m roboteam.launch.results.assets setup-assets --archive /path/to/archive.tar.gz`.

Install the harness CLI at its pinned version:

```sh
npm install --global @anthropic-ai/claude-code@2.1.316  # Claude Code
npm install --global @openai/codex@0.165.0              # Codex
```

The CLI must come first on `PATH` in every shell that prepares, checks or runs. Check with
`claude --version` or `codex --version`.

## 3. Credentials

```sh
cp .env.example .env
chmod 600 .env
```

Fill in only the variable your model reads. `.env` is ignored by Git. Values are read
literally, and a variable already set in the process environment wins.

| Variable | Used by |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude Code `opus` (the default Claude Code model) and `haiku` |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code `opus_subscription` and `haiku_subscription_token`; create the token with `claude setup-token` |
| `OPENAI_API_KEY` | Codex `sol` (the default model) and `luna` |
| `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `KIMI_API_KEY`, `KIMI_CODE_API_KEY`, `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`, `DASHSCOPE_ANTHROPIC_BASE_URL` | Third-party models of either harness |

Keep credentials in `.env`, not exported in the shell: runs load the file themselves, and the
Claude subscription token reaches the CLI on a pipe, so no shell of the agents can read it.
Never put a credential in a TOML file, a command argument or a commit. Codex subscription
models use a login instead of a variable ([Codex authentication](harness/codex.md#authentication)).
Every model and its credential is in the
[authentication matrix](harness/README.md#authentication-matrix).

## 4. Choose what to run

[`roboteam.toml`](../roboteam.toml) holds the defaults: Codex with the model `sol`
(gpt-6.1-sol), effort `high`, the `adaptive` system, all 36 tasks, 36 runs at once, 24 hours
per run, and a renderer picked for the host. `--harness claude` without a model selects `opus`
(claude-opus-5-5).

Change settings with command options, or with a small TOML file of your own that names only
what differs (a *site TOML*). For this guide, create `site.toml` in the repository root:

```toml
[policy]
harness = "claude"

[batch]
parallel = 1
task_wall_limit_s = 1800.0     # 30 minutes instead of 24 hours

[selection]
cases = ["transport-small-l1"]
```

`--config` goes before the command. Command options override the file.

```sh
.venv/bin/roboteam --config site.toml config
.venv/bin/roboteam --config site.toml plan
.venv/bin/roboteam --config site.toml doctor
```

| Command | What it does |
| --- | --- |
| `config` | Prints the resolved settings. Unknown fields and invalid values are errors |
| `plan` | Lists the selected tasks (`jobs`), the harness, model and system, and the policy environment the runs will use. It writes nothing and calls no model |
| `doctor` | Starts the harness CLI and its sandbox, and renders one real image. It reads no credential and calls no model. It exits 2 when a check fails; the JSON report has one entry per check with `passed` and, on failure, `error` |

A failed render check means the renderer does not match the machine. `render.device = "auto"`
picks `native` on macOS, `nvidia` on Linux with an NVIDIA GPU and `cpu` otherwise; `--render`
or `render.device` sets it by hand. One renderer never falls back to another.

The options that select what to run are `--harness`, `--model`, `--effort`, `--system`,
`--tools`, `--observation`, `--task-types`, `--level`, `--min-arms`, `--cases` and
`--parallel`. The [command-line guide](cli.md) lists every option and setting, and
[`docs/hosts/examples/`](hosts/examples) has a starting site TOML for a Mac, a Linux host and
Slurm.

## 5. Build and check the policy environment

The agents may write and run Python. Every run gives them one frozen Python 3.12 environment,
the *policy environment*, never the host's Python. It also freezes an *access table*: the list
of folders the agents' file tools and shell can read or write. The checkout, the home folder
and other runs are closed to them.

Build the environment once per host, in a folder outside your home folder, the repository and
`/tmp`. This needs the network. Then check that its sandbox holds on this host:

```sh
.venv/bin/python -m scripts.release.build_policy_env --base /Users/Shared/roboteam
.venv/bin/python -m scripts.release.check_policy_env /Users/Shared/roboteam/policy-env-<id> \
  --harness claude
```

The first command prints the build's folder (`root`); pass that folder to the second. The
check starts the real CLI against a local stub model, with no model calls, and tries about 50
things an agent must and must not be able to do. A pass writes a record beside the build.
Without `--harness` it checks both harnesses, so both CLIs must be installed. Run the check
again after changing a CLI version.

On macOS, `prepare` uses the build under `/Users/Shared/roboteam` by default. On Linux, pick a
base folder (for example under `/var/tmp` or on a data volume) and set
`ROBOTEAM_POLICY_ENV_BASE` to it in the shell that prepares runs; without it `prepare` refuses.
On Linux also keep batches and `TMPDIR` outside `/tmp`.
[Policy environment](hosts/policy-environment.md) has the details and the known limits of each
platform.

## 6. Preflight, then run

```sh
.venv/bin/roboteam --config site.toml preflight --confirm-spend --max-budget-usd 1
.venv/bin/roboteam --config site.toml prepare --output runs/policy/first-run
.venv/bin/roboteam run runs/policy/first-run
.venv/bin/roboteam status runs/policy/first-run
```

**`preflight`** makes a few small, paid model calls. It checks that the model works with the
harness's images, tools, sessions and forks, and writes a *receipt*: a file under
`runs/engineering/` that records the model, the CLI version and the result. `run` refuses a
batch without a passed receipt that matches, so run `preflight` again after changing the model,
the effort or the CLI. Without `--confirm-spend` it calls no model and does not pass. For
Claude Code, `--max-budget-usd` is required and caps the cost the CLI reports for each check.

**`prepare`** writes the batch folder and freezes, for each run, the task, the scene, the
rules and prompts, the source code, the resolved settings, the policy environment and the
hashes of all of them. It calls no model and starts no world. `--output` must be a new folder.
Later edits to the TOML or the code do not change a prepared batch; prepare a new one instead.

**`run`** loads `.env`, checks the frozen settings, every run's input hashes, the pinned
versions and the receipts, and then starts the runs. On macOS it hands the batch to launchd
and returns, so the batch outlives the terminal; `--foreground` keeps it in the current
process. On Linux, add `--durable` for a background service; without it the batch runs in the
current shell.

**`status`** prints the supervisor's last snapshot: each run's state, and the service's state
on macOS or with `--durable`.

Each run has its own START. From START it gets its time limit of active running time (here 30
minutes, by default 24 hours) and is scored at that cutoff, or earlier when the agents call
`finish` and it is accepted. Host sleep, a network outage and a used-up usage limit do not
count as active time; an outage or a usage limit pauses the run in place and it resumes by
itself ([time and pauses](runs/time.md)).

To end a batch early:

```sh
.venv/bin/roboteam stop runs/policy/first-run
```

`stop` asks every run to stop in order. Check `status` afterwards.

A run that stops unexpectedly (its host, world or model session ended without a finish, a
cutoff or a stop) continues by itself once, as the same trial. After that, continue stopped
runs by hand ([continuing a stopped run](runs/continuation.md)):

```sh
.venv/bin/roboteam continue runs/policy/first-run
```

## 7. Read the results

```text
runs/policy/first-run/
  batch.json  effective-config.json  control/  logs/  models/
  opus/transport-small-l1/          one run: <model>/<case>/
    public/                         what the agents read: inputs, observations, results
    workspace/                      the agents' only writable folder (skills.md and their own files)
    private/inputs/                 the frozen task, scene, source and settings
    private/outputs/                evaluation.json (the score), seal.json, report.json, motion/
    private/state/  private/logs/  private/harness/    database, logs, harness sessions
```

`private/outputs/evaluation.json` holds the score; `task_success` says whether the task was
completed. `seal.json` is the run's closing record: it says the world closed, that final
images were taken and whether any action was left unresolved.

When every run has stopped, the batch collects its evidence into
`runs/exports/<batch>-<hash>/` and writes a verified ZIP beside it. The originals stay. By
hand:

```sh
.venv/bin/roboteam collect runs/policy/first-run --output runs/exports/first-run
.venv/bin/roboteam archive runs/exports/first-run --output runs/exports/first-run.zip
```

To look at a batch in a browser, during or after the runs:

```sh
.venv/bin/python -m scripts.dev.view_batch runs/policy/first-run
```

Nothing under `runs/` is in Git; back it up separately
([evidence storage](runs/evidence-storage.md)). Runs, receipts and exports go under
`paths.runs_root`, by default `<repo>/runs`; `ROBOTEAM_RUNS_ROOT` overrides it.

## Next

- A full experiment: remove the three settings from `site.toml` to run all 36 tasks for 24
  hours each, and read the guide for your platform first: [Mac](hosts/mac.md),
  [Linux](hosts/linux.md), [Slurm](hosts/slurm.md), [Docker](hosts/docker.md).
- The conditions of the paper: `--system`, `--tools robot_only`
  ([robot-only runs](benchmark/robot-tool-only.md)), `--observation ground_truth`
  ([ground-truth observation](benchmark/rules.md#ground-truth-observation)) and
  `render.observation_profile = "jpeg_128x80_q95"` for low-resolution images.
- Harnesses: [overview](harness/README.md), [Codex](harness/codex.md),
  [Claude Code](harness/claude-code.md).
- What a run is: [the tasks](tasks/README.md), [rules of a run](benchmark/rules.md),
  [physics and robot limits](benchmark/physics.md), [architecture](development/architecture.md).
