# Running in Docker

`roboteam container ...` runs the unified CLI inside an image built from the committed
source, with three persistent local Docker volumes: run data, harness state, and the policy Python
environment. Only a stopped, verified evidence ZIP is copied back to the host.

The policy environment is built and checked once per workspace with `container policy-env`
(step 5); until it has passed, `container prepare` refuses.

## 1. Prerequisites

- Docker Desktop on macOS, or Docker Engine on Linux. On macOS the container is Linux in
  Docker's VM: CPU rendering only, no Metal.
- For NVIDIA rendering: Linux, an NVIDIA GPU, host drivers and the NVIDIA container runtime.
- A host checkout installed with `uv sync --locked`, with no uncommitted tracked
  changes (the build uses `git archive HEAD`).

## 2. Build

```sh
.venv/bin/roboteam container build
```

The image ([`docker/Dockerfile`](../../docker/Dockerfile)) is `python:3.12-slim-bookworm` with
Node.js 22, Codex 0.165.0, Claude Code 2.1.316, OSMesa, EGL and `ffmpeg`; it runs
`uv sync --locked` and `roboteam bootstrap`, so the pinned assets are inside.
It is tagged `roboteam:<commit[:12]>` (or `container.image`) and labelled with the commit;
an existing image from another commit is refused. `.env`, logins and run data never enter it.
It has no `bwrap` or `socat`, so both harnesses confine the agents' shell with this project's
`landlock-v1` sandbox (Landlock and seccomp).

Help for any subcommand works without Docker: `roboteam container prepare --help`.

## 3. Site TOML

```toml
# docker.toml
[render]
device = "cpu"                       # "nvidia" on a Linux GPU host

[container]
workspace = "default"                # names the three volumes
memory_gib = 0                       # 0: no limit beyond Docker's
cpus = 0.0
seccomp_profile = "default"          # "unconfined" removes Docker's seccomp filter (see Limits)
```

Pass it before `container` (`roboteam --config docker.toml container ...`); `--config`
after `container` is refused. Docker Desktop's VM memory is a real bound; the wrapper never
lowers `batch.parallel`.

## 4. Credentials

Put the model's variable in the host `.env` (or the shell). The wrapper forwards only the
selected model's `env_key` and `base_url_env`, by name; values never appear in Docker
arguments, image layers, the TOML or evidence.

```sh
.venv/bin/roboteam container auth claude setup-token          # prints a token: store it as CLAUDE_CODE_OAUTH_TOKEN in .env
.venv/bin/roboteam --config docker.toml container auth codex login --device-auth
```

The Codex login goes to the state volume's `/opt/RoboTeam/.roboteam/subscription`
(file-backed), used by Codex subscription models with `runtime.codex_home_scope = "shared"`.
The host's `~/.codex`, `~/.claude` and Keychain are never mounted.

## 5. Policy environment, check and preflight

```sh
.venv/bin/roboteam --config docker.toml container policy-env
.venv/bin/roboteam --config docker.toml container doctor
.venv/bin/roboteam --config docker.toml container plan
.venv/bin/roboteam --config docker.toml container preflight --confirm-spend                                       # Codex
.venv/bin/roboteam --config docker.toml container preflight --harness claude --confirm-spend --max-budget-usd 1   # Claude Code
```

`policy-env` builds the policy Python environment in its volume (`/opt/roboteam-policy`)
and runs its sandbox check against both harnesses' real CLIs, with no model calls; runs then use it.
If the check reports that Landlock is unavailable, Docker's seccomp profile is refusing it: set
`seccomp_profile = "unconfined"` (Limits). `doctor` checks the CLI, the sandbox and a real
MuJoCo render context, without authenticating. Receipts land in the runs volume.

## 6. Prepare, run, status, stop

```sh
.venv/bin/roboteam --config docker.toml container prepare --output runs/batches/my-batch
.venv/bin/roboteam --config docker.toml container run runs/batches/my-batch
.venv/bin/roboteam --config docker.toml container status runs/batches/my-batch
.venv/bin/roboteam --config docker.toml container stop runs/batches/my-batch
```

(`prepare` refuses until `container policy-env` has passed.) Batch paths are
relative paths under `runs/`, inside the runs volume. `container run` waits for the batch in the
foreground and starts it with the batch's frozen configuration. Ctrl-C requests an orderly stop
and waits up to 180 s for sealing and collection. A container still running afterwards is
kept and reported `still_running_needs_review`; the wrapper never restarts it. Each command is
recorded in `.roboteam/containers/<workspace>/commands/rf-<id>.json`.

There is no `container continue`: a run that stops unexpectedly continues by itself once inside
the batch, but stopped runs cannot be continued by hand through the wrapper.

## 7. Results

After the batch closes and is collected, the wrapper checks the ZIP's SHA-256 against the
container's result and copies it to `runs/container-exports/<workspace>/<batch>-<hash>.zip`.
An identical existing ZIP is kept; a different one with that name is refused.

The volumes, named from the checkout path and `container.workspace`, keep everything else:

| Volume | Mounted at | Holds |
| --- | --- | --- |
| `roboteam-<id>-<workspace>-runs` | `/opt/RoboTeam/runs` | Batches, motion, receipts, collections, ZIPs |
| `roboteam-<id>-<workspace>-state` | `/opt/RoboTeam/.roboteam` | Each run's Codex home and sessions, the subscription login, Claude Code's configuration |
| `roboteam-<id>-<workspace>-policy` | `/opt/roboteam-policy` | The policy Python environment and its check receipt |

Do not copy a live SQLite file out of a volume. Deleting a volume deletes its runs; the wrapper
never does.

## Limits

- **No `continue`** through the wrapper.
- **Seccomp.** Docker's default seccomp profile can refuse Landlock. `seccomp_profile = "unconfined"`
  drops it for `policy-env`, `doctor`, `preflight` and `run`, without `--privileged`; the
  agents' shell then installs its own seccomp filter and Landlock rules.
- Without user namespaces in the container, `/dev/shm` stays closed to policies, so Python's
  process pools fail there ([policy environment](policy-environment.md)).
- **Slurm jobs do not use Docker**; they stage onto node-local scratch ([Slurm](slurm.md)).
