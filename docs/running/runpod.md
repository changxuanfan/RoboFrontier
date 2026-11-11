# Running on RunPod (plain Linux)

A RunPod pod, or any Linux host without Slurm, runs a batch as a background service started by
`run --durable`. [`configs/examples/runpod.toml`](../../configs/examples/runpod.toml) is a
starting site TOML (four level-3 runs, Codex subscription, CPU rendering): copy it to an
untracked file (here `site.toml`) and edit it.

## 1. Prerequisites

- A pod with a persistent volume (`/workspace`) and outbound access to GitHub, PyPI, npm and the
  model API.
- Linux 6.7 or newer (Landlock ABI 4) with `libseccomp`. A pod forbids user namespaces, so
  Claude Code's bubblewrap sandbox cannot run and both engines use Landlock + seccomp
  (`landlock-v1`).
- Python 3.12, [uv](https://docs.astral.sh/uv/) (with `uvx`), Node.js, `ffmpeg`, and the engine
  CLI at its pinned version (`robofrontier/runtime/versions.py`: Claude Code 2.1.316, Codex
  0.165.0).
- Put the Node.js and CLI folders on `PATH` in every shell that prepares, runs or checks (on the
  author's pod `/workspace/tools/node/bin` and `/workspace/tools/npm/bin`):

  ```sh
  export PATH=/workspace/tools/node/bin:/workspace/tools/npm/bin:$PATH
  ```

## 2. Install

```sh
cd /workspace
git clone https://github.com/changxuanfan/RoboFrontier.git
cd RoboFrontier
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap
```

## 3. Credentials

```sh
cp .env.example .env && chmod 600 .env
```

Fill in only your profile's variable (`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, ...; see `configs/models.json`). For a Codex subscription profile log in once
with `CODEX_HOME=~/.robofrontier/codex-home codex login` (the example uses
`runtime.codex_home_scope = "shared"`). Keep credentials in `.env`, not exported: runs load it
themselves and the background service is started without them.

## 4. Site settings

The example already sets these; keep them in your `site.toml`:

```toml
[render]
device = "cpu"                       # Mesa llvmpipe; the world limits it to two threads per run

[runtime]
codex_tool_backend = "landlock-v1"   # the only Codex backend the Linux policy check admits

[paths]
runs_root = "/workspace/robofrontier-runs"   # receipts, exports and caches on the persistent volume
```

## 5. Policy environment

Build it on the pod, outside `/tmp` and the checkout, and name the base in every shell that
prepares runs:

```sh
export ROBOFRONTIER_POLICY_ENV_BASE=/workspace/robofrontier-env
.venv/bin/python -m scripts.build_policy_env --base $ROBOFRONTIER_POLICY_ENV_BASE   # prints its root
.venv/bin/python -m scripts.check_policy_env $ROBOFRONTIER_POLICY_ENV_BASE/policy-env-<id> \
  --scratch /workspace/robofrontier-runs
```

`prepare` refuses without a checked build. The check passes for both engines on a pod (48 CPUs,
kernel 6.8, Landlock ABI 4), with process pools as a recorded known limit (below). Details:
[policy environment](policy-environment.md).

## 6. Local check and preflight

```sh
.venv/bin/robofrontier --config site.toml doctor
.venv/bin/robofrontier --config site.toml preflight --confirm-spend                      # Codex
.venv/bin/robofrontier --config site.toml preflight --confirm-spend --max-budget-usd 1   # Claude
```

Receipts go under `<runs root>/engineering/`; `run` refuses a batch without matching ones.

## 7. Prepare and run

```sh
B=/workspace/robofrontier-runs/policy/my-batch
.venv/bin/robofrontier --config site.toml prepare --output $B
.venv/bin/robofrontier run $B --durable
.venv/bin/robofrontier status $B          # includes "durable": the service record and whether it runs
.venv/bin/robofrontier stop $B            # an orderly stop
.venv/bin/robofrontier continue $B --durable   # continue stopped runs by hand, in the background
```

Without a systemd user manager (RunPod containers have none), `--durable` starts a `setsid`
daemon in its own session; with one, a transient user service (`robofrontier/batch/linux.py`).
`<batch>/control/durable/` holds `service.json`, `stdout.log` and `stderr.log`; a second
submission of the same batch is refused. Without `--durable`, `run` and `continue` run in the
current shell and end with it.

Each run gets 24 h of active time from START and is scored at the cutoff or when the team
finishes. A run that stops unexpectedly continues by itself once; outages and usage limits
pause it in place ([continuation](continuation.md)).

## 8. Results

Runs stay under the batch folder; when the batch ends it is collected into
`<runs root>/exports/<batch>-<hash>/` with a verified ZIP beside it
([evidence storage](evidence-storage.md)).

## Limits

- **No process pools in policy scripts.** Without user namespaces no command gets a private
  `/dev/shm`, so it stays closed: `multiprocessing.Pool` and `ProcessPoolExecutor` fail; threads
  and plain subprocesses work.
- **Processes stay visible.** Landlock cannot hide other processes from a policy shell; their
  environments cannot be read, traced or signalled.
- **The access table closes `/workspace`** as a whole; a run's own `public/` and `workspace/`
  and the policy environment are the only places a policy reaches there.
- No GPU rendering unless the pod has an NVIDIA GPU and `render.device = "nvidia"`.
