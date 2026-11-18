# Running on Linux

A Linux workstation, server or cloud container (for example a RunPod pod) without Slurm runs a
batch as a background service started by `run --durable`.
[`docs/hosts/examples/linux.toml`](examples/linux.toml) is a starting site TOML (four level-3
runs, Codex subscription, CPU rendering): copy it to an untracked file (here `site.toml`) and
edit it. The commands below keep data under `/workspace`, the persistent volume of a RunPod
pod; use any persistent folder outside your home folder and `/tmp`.

## 1. Prerequisites

- Persistent storage and outbound access to GitHub, PyPI, npm and the model API.
- A sandbox for the agents' shell. Where unprivileged user namespaces work, `bwrap` and `socat`
  let Claude Code use its own bubblewrap sandbox. Otherwise (most cloud containers forbid user
  namespaces) the host needs Linux 6.7 or newer (Landlock ABI 4) with `libseccomp`, and the
  runs use this project's `landlock-v1` sandbox. Codex on Linux always uses `landlock-v1`.
- Python 3.12, [uv](https://docs.astral.sh/uv/) (with `uvx`), Node.js, `ffmpeg`, and the harness
  CLI at its pinned version (`roboteam/runtime/run/versions.py`: Claude Code 2.1.316, Codex
  0.165.0).
- The Node.js and CLI folders on `PATH` in every shell that prepares, runs or checks.

## 2. Install

```sh
cd /workspace
git clone https://github.com/changxuanfan/RoboTeam.git
cd RoboTeam
uv sync --locked
.venv/bin/roboteam bootstrap
```

## 3. Credentials

```sh
cp .env.example .env && chmod 600 .env
```

Fill in only your model's variable (`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, ...; see `models.json`). For a Codex subscription model log in once
with `CODEX_HOME=~/.roboteam/codex-home codex login` (the example uses
`runtime.codex_home_scope = "shared"`). Keep credentials in `.env`, not exported: runs load it
themselves and the background service is started without them.

## 4. Site settings

The example sets these; keep them in your `site.toml`:

```toml
[render]
device = "cpu"                       # Mesa's software renderer; "nvidia" with an NVIDIA GPU

[paths]
runs_root = "/workspace/roboteam-runs"   # runs, receipts and exports on persistent storage
```

Without `render.device`, the default picks `nvidia` when the host has an NVIDIA GPU and `cpu`
otherwise. The CPU renderer uses two threads per run.

## 5. Policy environment

Build it on the host, outside `/tmp` and the checkout, and name the base folder in every shell
that prepares runs:

```sh
export ROBOTEAM_POLICY_ENV_BASE=/workspace/roboteam-env
.venv/bin/python -m scripts.release.build_policy_env --base $ROBOTEAM_POLICY_ENV_BASE   # prints its root
.venv/bin/python -m scripts.release.check_policy_env $ROBOTEAM_POLICY_ENV_BASE/policy-env-<id> \
  --scratch /workspace/roboteam-runs
```

`prepare` refuses without a checked build. With one CLI installed, add `--harness claude` or
`--harness codex` to the check. Details: [policy environment](policy-environment.md).

## 6. Local check and preflight

```sh
.venv/bin/roboteam --config site.toml doctor
.venv/bin/roboteam --config site.toml preflight --confirm-spend
```

For Claude Code, add `--max-budget-usd 1`.

Receipts go under `<runs root>/engineering/`; `run` refuses a batch without matching ones.

## 7. Prepare and run

```sh
B=/workspace/roboteam-runs/policy/my-batch
.venv/bin/roboteam --config site.toml prepare --output $B
.venv/bin/roboteam run $B --durable
.venv/bin/roboteam status $B          # includes "durable": the service record and whether it runs
.venv/bin/roboteam stop $B            # an orderly stop
.venv/bin/roboteam continue $B --durable   # continue stopped runs by hand, in the background
```

With a systemd user manager, `--durable` starts a transient user service. Without one (most
containers have none), it starts a `setsid` daemon in its own session
(`roboteam/launch/local/linux.py`).
`<batch>/control/durable/` holds `service.json`, `stdout.log` and `stderr.log`; a second
submission of the same batch is refused. Without `--durable`, `run` and `continue` run in the
current shell and end with it.

Each run gets 24 h of active time from START and is scored at the cutoff or when the team
finishes. A run that stops unexpectedly continues by itself once; outages and usage limits
pause it in place ([time and pauses](../runs/time.md),
[continuing a stopped run](../runs/continuation.md)).

## 8. Results

Runs stay under the batch folder; when the batch ends it is collected into
`<runs root>/exports/<batch>-<hash>/` with a verified ZIP beside it
([evidence storage](../runs/evidence-storage.md)).

## Limits

- **No process pools in policy scripts.** Without user namespaces no command gets a private
  `/dev/shm`, so it stays closed: `multiprocessing.Pool` and `ProcessPoolExecutor` fail; threads
  and plain subprocesses work.
- **Processes stay visible.** Landlock cannot hide other processes from a policy shell; their
  environments cannot be read, traced or signalled.
- **The access table closes `/workspace`** as a whole; a run's own `public/` and `workspace/`
  and the policy environment are the only places the agents reach there
  ([what the agents can reach](policy-environment.md#what-a-policy-can-reach)).
