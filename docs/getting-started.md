# Getting started

This guide takes a fresh clone to a finished, collected run on one machine. Every step names
the command, what it checks and what to do when it fails. Commands run from the repository
root. Global options such as `--config FILE` go before the subcommand:
`.venv/bin/robofrontier --config site.toml plan`.

Platform details are in the [Mac](running/mac.md), [RunPod and plain Linux](running/runpod.md),
[Slurm](running/slurm.md) and [Docker](running/docker.md) guides; every setting is in the
[command-line guide](unified-cli.md).

## 1. Prerequisites

| Need | Version and notes |
| --- | --- |
| Operating system | macOS, or Linux with glibc 2.28 or newer |
| [uv](https://docs.astral.sh/uv/) | Installs Python 3.12 (`.python-version`) and the locked packages from `uv.lock` |
| Node.js and npm | Node.js 22 is what CI uses; the Codex host and the engine CLIs need it |
| Engine CLI | Exactly the pinned version in `robofrontier/runtime/versions.py`: Codex `0.165.0`, Claude Code `2.1.316`. Install only the engine you will run |
| Rendering | macOS: native OpenGL (`render.device = "native"`). Linux: NVIDIA EGL (`nvidia`, the default) or Mesa OSMesa (`cpu`, needs the system `libosmesa6` package or equivalent) |
| Network | For `bootstrap` (about 186 MB of pinned assets), building the policy environment, and the model provider |

`prepare` and `run` refuse a different engine CLI, MuJoCo, NumPy or Pillow version than the
pinned ones.

## 2. Install

```sh
git clone https://github.com/changxuanfan/RoboFrontier.git
cd RoboFrontier
uv sync --locked --extra oracle
```

Install the engine CLI at its pinned version, for example globally:

```sh
npm install --global @openai/codex@0.165.0              # Codex
npm install --global @anthropic-ai/claude-code@2.1.316  # Claude Code
codex --version; claude --version
```

The CLI folder must come first on `PATH` in every shell that prepares, runs or checks. On a
RunPod pod that means adding the Node.js and npm `bin` folders (on the author's pod
`/workspace/tools/node/bin` and `/workspace/tools/npm/bin`). Claude Code's self-update is turned
off for runs.

## 3. Restore the assets

```sh
.venv/bin/robofrontier bootstrap
```

`bootstrap` downloads the policy asset archive pinned in `configs/policy-assets.json`, checks its
SHA-256, and restores every referenced file (the scene meshes and textures under
`benchmark/<family>/<case>/assets/` and the Franka Panda model under `vendor/panda/`), checking
each file's hash. It reuses files that already verify and calls no model. On failure it names
the file or hash that differs: do not substitute another archive. For a machine without network
access, copy the archive named in `configs/policy-assets.json` over and run
`.venv/bin/python -m robofrontier.batch.handoff setup-assets --archive /path/to/the-archive.tar.gz`.

## 4. Credentials: `.env`

```sh
.venv/bin/python -m robofrontier.batch.handoff init-env
```

This copies `.env.example` to `.env` with mode 0600 and refuses to overwrite an existing `.env`.
(By hand: `cp .env.example .env && chmod 600 .env`.) Fill in only the variables of the profiles
you use; `.env` is ignored by Git. Values are read literally, and a variable already set in the
process environment wins.

| Variable | Used by |
| --- | --- |
| `OPENAI_API_KEY` | Codex `luna` (the default profile) |
| `OPENLUX_API_KEY` | Codex `openlux-luna`, `openlux-terra` |
| `ANTHROPIC_API_KEY` | Claude Code `haiku`, `opus` |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code `haiku_subscription_token` (the default Claude profile) and `opus_subscription`; create it with `claude setup-token` |
| `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `KIMI_API_KEY`, `KIMI_CODE_API_KEY`, `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`, `DASHSCOPE_ANTHROPIC_BASE_URL` | Third-party profiles of either engine |

Codex subscription profiles (`luna_subscription` and others) use a login in
`~/.robofrontier/codex-home` instead: `CODEX_HOME=~/.robofrontier/codex-home codex login`. Never
put credentials in a TOML file, a command argument or a commit. The Claude subscription token
reaches the CLI on a pipe, never in an environment variable. Profiles and their authentication
are listed in the [provider guide](engines/README.md#providers).

## 5. A site TOML

`robofrontier.toml` holds the defaults: Codex, profile `luna`, effort `high`, topology
`adaptive`, all 36 released cases, 36 parallel runs, NVIDIA rendering. Override what differs in
a partial, untracked TOML, starting from the example for your platform:

```sh
cp configs/examples/mac.toml site.toml      # or slurm.toml, runpod.toml
.venv/bin/robofrontier --config site.toml config
```

`config` prints the resolved settings. Unknown fields and invalid values are errors. Command
options override the TOML: `--engine`, `--profile`, `--effort`, `--topology` (`single`,
`controller-worker`, `worker-worker`, `adaptive`), `--parallel`, `--render`, `--level`,
`--min-arms`, `--cases`, `--families`. Runs, receipts, exports and caches go under
`paths.runs_root`; empty means `<repo>/runs`, and `ROBOFRONTIER_RUNS_ROOT` overrides both.

## 6. Check the machine: `doctor`

```sh
.venv/bin/robofrontier --config site.toml doctor
```

Doctor starts the selected engine CLI (and Codex's tool sandbox when selected) and renders a real
RGB frame with the configured backend. It authenticates nothing and calls no model. The JSON
report has one entry per check with `passed` and, on failure, `error`. A render failure means the
backend does not match the machine: use `--render native` on macOS and `--render cpu` on Linux
without an NVIDIA GPU. A backend never falls back to another one.

## 7. See what would run: `plan`

```sh
.venv/bin/robofrontier --config site.toml plan
```

`plan` lists the selected cases (`jobs`), the engine, profile and topology, and
`policy_environment`, the environment the runs will use. It writes nothing and calls no model.

## 8. The policy Python environment

Every run gives the policy one frozen Python 3.12 environment, never the host's Python, and a
closed access table: the checkout, the home folder, other runs and shared storage stay out of
reach. Build it once per host, into a folder outside the home folder and the repository (this
needs network access and `uvx`):

```sh
.venv/bin/python -m scripts.build_policy_env --base /Users/Shared/robofrontier
```

Then check it where the runs will run (on Slurm, on a compute node). The check drives each
engine CLI with a local stub model, so it contacts no provider:

```sh
.venv/bin/python -m scripts.check_policy_env /Users/Shared/robofrontier/policy-env-<id> \
  --scratch <folder next to where batches go>
```

On macOS `prepare` uses the build under `/Users/Shared/robofrontier` by default. On Linux set
`ROBOFRONTIER_POLICY_ENV_BASE` to the base folder you built into; without it `prepare` refuses.
`ROBOFRONTIER_POLICY_ENV=PATH` names a specific build. Preparation also refuses a build that is
missing, changed, or has no passing check for this engine and its CLI version, and prints the two
commands above; run the check again after changing a CLI. On Linux keep runs and `TMPDIR`
outside `/tmp` (for example under `/var/tmp`). Details and known limits:
[policy environment](running/policy-environment.md).

## 9. Check the provider: `preflight`

```sh
.venv/bin/robofrontier --config site.toml preflight --confirm-spend
```

Preflight makes real, possibly billable model calls: it checks that the selected profile and
effort work with the engine's images, tools and sessions, and writes a receipt (for Codex under
`<runs root>/engineering/model-compatibility/<profile>/`). Without `--confirm-spend` it calls no
model and does not pass. `--smoke-only` runs a smaller check whose receipt does not admit runs;
for Claude, `--max-budget-usd N` caps the check's estimated cost. `run` refuses a profile, effort
or CLI version without a matching passed receipt, so check again after changing any of them.

## 10. Freeze a batch: `prepare`

```sh
.venv/bin/robofrontier --config site.toml prepare --output runs/policy/my-batch
```

`prepare` writes the batch folder and freezes, per run, the task, scene, rules, prompts, source
code, resolved configuration, policy environment and input hashes. It calls no model and starts
no world. `--output` must be a new folder. Later edits to the TOML or the code do not change a
prepared batch; prepare a new one instead. To try four small cases first:
`prepare --level 1 --min-arms --parallel 4 --output runs/policy/my-l1`.

## 11. Run: `run`

```sh
.venv/bin/robofrontier run runs/policy/my-batch
```

`run` loads `.env`, checks the frozen configuration's fingerprint, every run's input hashes, the
pinned versions, the receipts and the local prerequisites, then starts the runs, 0.3 s apart.
On macOS it runs as a launchd service with Interactive priority under `caffeinate` and outlives
the terminal; `--foreground` keeps it in the current process. On Linux add `--durable` for a
background service (a systemd user service, or a `setsid` daemon where there is none).

Each run has its own START. It gets 24 hours of active running time from START and is scored at
that cutoff, or earlier when the policy's `finish` is accepted. Host stops, network outages and
used-up usage limits do not count as active time; a network outage or usage limit pauses the run
in place and it resumes by itself.

## 12. Watch and stop: `status`, `stop`

```sh
.venv/bin/robofrontier status runs/policy/my-batch
.venv/bin/robofrontier stop runs/policy/my-batch
```

`status` prints the supervisor's snapshot (each run's state, and the service's state on Mac or
with `--durable`); it never opens a live database. `stop` asks every run to stop in order; check
`status` and each run's seal afterwards, because a stop request does not prove that every
action has settled.

## 13. Continue a stopped run: `continue`

When a run stops unexpectedly (a host, world or model session ends without a finish, cutoff or
stop), the batch continues it by itself, once per run, as the same trial: same run folder,
database and model sessions, with the world rebuilt from the last recorded frame. Any later
continuation is by hand:

```sh
.venv/bin/robofrontier continue runs/policy/my-batch                     # every run that may continue
.venv/bin/robofrontier continue runs/policy/my-batch --cases transport-a04-d1
```

A continuation after the finish or the cutoff keeps the score recorded at that stop. If the
supervisor itself died, `run runs/policy/my-batch --continue` resumes the batch. Rules and
files: [continuation](running/continuation.md).

## 14. Where results go

```text
runs/policy/my-batch/
  batch.json  effective-config.json  control/  logs/  profiles/
  <profile>/<case>/                 one run
    public/                         what the policy reads: inputs, observations, results
    workspace/                      the policy's only writable folder (skills.md, its own files)
    private/inputs/                 frozen task, scene, harness, source and manifest
    private/outputs/                evaluation.json (the score), seal.json, report.json, motion/, segments
    private/state/  private/logs/  private/engine/   live database, host logs, engine sessions
```

When every run has stopped, the batch collects its evidence into
`<runs root>/exports/<batch>-<hash>/` and writes a verified ZIP next to it; the originals stay.
To do it by hand:

```sh
.venv/bin/robofrontier collect runs/policy/my-batch --output runs/exports/my-batch
.venv/bin/robofrontier archive runs/exports/my-batch --output runs/exports/my-batch.zip
.venv/bin/robofrontier extract runs/exports/my-batch.zip --output runs/restored/my-batch
```

None of `runs/` is in Git; back it up separately ([evidence storage](running/evidence-storage.md)).
`.venv/bin/python -m scripts.view_policy_batch runs/policy/my-batch` serves a read-only viewer of
a batch ([viewer](running/local-viewer.md)).

## Next

- Platforms: [Mac](running/mac.md), [RunPod and plain Linux](running/runpod.md),
  [Slurm](running/slurm.md) (on the cluster used here, `module load slurm` may be needed before
  `srun` or `sbatch`), [Docker](running/docker.md).
- Engines: [Codex](engines/codex.md), [Claude Code](engines/claude-code.md).
- What a run is: [architecture](architecture.md), [runtime protocol](protocol.md),
  [physics and robot limits](physics.md), [the tasks](tasks/README.md).
- Reference runs and video: [Oracle](oracle/README.md), [Factory](factory/README.md).
