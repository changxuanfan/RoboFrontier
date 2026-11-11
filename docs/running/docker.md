# Running in Docker

`robofrontier container ...` runs the unified CLI inside an image built from the committed
source, with two persistent local Docker volumes for run data and native state. Only a stopped,
verified evidence ZIP is copied back to the host.

**Current limit: a batch cannot be prepared in the image.** The image contains no policy Python
environment and no way to name one (`ROBOFRONTIER_POLICY_ENV` and
`ROBOFRONTIER_POLICY_ENV_BASE` are not passed in), and every run needs a checked one, so
`container prepare` refuses with "No policy environment". `build`, `doctor`, `plan`,
`preflight` and `auth` work; `run` has nothing to run until the image carries a checked policy
environment. See [policy environment](policy-environment.md).

## 1. Prerequisites

- Docker Desktop on macOS, or a Docker engine on Linux. On macOS the container is Linux in
  Docker's VM: CPU rendering only, no Metal.
- For NVIDIA rendering: Linux, an NVIDIA GPU, host drivers and the NVIDIA container runtime.
- A host checkout installed with `uv sync --locked --extra oracle`, with no uncommitted tracked
  changes (the build uses `git archive HEAD`).

## 2. Build

```sh
.venv/bin/robofrontier container build
```

The image ([`docker/Dockerfile`](../../docker/Dockerfile)) is `python:3.12-slim-bookworm` with
Node.js 22, Codex 0.165.0, Claude Code 2.1.316, OSMesa, EGL and `ffmpeg`; it runs
`uv sync --locked --extra oracle` and `robofrontier bootstrap`, so the pinned assets are inside.
It is tagged `robofrontier:<commit[:12]>` (or `container.image`) and labelled with the commit;
an existing image from another commit is refused. `.env`, logins and run data never enter it.
It has no `bwrap` or `socat`, so Claude Code's Bash uses Landlock + seccomp (`landlock-v1`).

Help for any subcommand works without Docker: `robofrontier container prepare --help`.

## 3. Site TOML

```toml
# docker.toml
[render]
device = "cpu"                       # "nvidia" on a Linux GPU host

[runtime]
codex_tool_backend = "landlock-v1"   # the only Codex backend the Linux policy check admits

[container]
workspace = "default"                # names the volume pair
memory_gib = 0                       # 0: no limit beyond Docker's
cpus = 0.0
seccomp_profile = "default"          # "unconfined" removes Docker's seccomp filter for Codex doctor/preflight/run
```

Pass it before `container` (`robofrontier --config docker.toml container ...`); `--config`
after `container` is refused. Docker Desktop's VM memory is a real bound; the wrapper never
lowers `batch.parallel`.

## 4. Credentials

Put the profile's variable in the host `.env` (or the shell). The wrapper forwards only the
selected profile's `env_key` and `base_url_env`, by name; values never appear in Docker
arguments, image layers, the TOML or evidence.

```sh
.venv/bin/robofrontier container auth claude setup-token          # prints a token: store it as CLAUDE_CODE_OAUTH_TOKEN in .env
.venv/bin/robofrontier --config docker.toml container auth codex login --device-auth
```

The Codex login goes to the state volume's `/opt/RoboFrontier/.robofrontier/subscription`
(file-backed), used by Codex subscription profiles with `runtime.codex_home_scope = "shared"`.
The host's `~/.codex`, `~/.claude` and Keychain are never mounted.

## 5. Check and preflight

```sh
.venv/bin/robofrontier --config docker.toml container doctor
.venv/bin/robofrontier --config docker.toml container plan
.venv/bin/robofrontier --config docker.toml container preflight --confirm-spend                      # Codex
.venv/bin/robofrontier --config docker.toml container preflight --confirm-spend --max-budget-usd 1   # Claude
```

`doctor` checks the CLI, the Codex sandbox and a real MuJoCo render context, without
authenticating. Receipts land in the runs volume.

## 6. Prepare, run, status, stop

```sh
.venv/bin/robofrontier --config docker.toml container prepare --output runs/policy/my-batch
.venv/bin/robofrontier --config docker.toml container run runs/policy/my-batch
.venv/bin/robofrontier --config docker.toml container status runs/policy/my-batch
.venv/bin/robofrontier --config docker.toml container stop runs/policy/my-batch
```

(`prepare` refuses until the image has a policy environment; see the top.) Batch paths are
relative paths under `runs/`, inside the runs volume. `container run` waits for the batch in the
foreground and starts it with the batch's frozen configuration. Ctrl-C requests an orderly stop
and waits up to 180 s for sealing and collection. A container still running afterwards is
kept and reported `still_running_needs_review`; the wrapper never restarts it. Each command is
recorded in `.robofrontier/containers/<workspace>/commands/rf-<id>.json`.

There is no `container continue`: a run that stops unexpectedly continues by itself once inside
the batch, but stopped runs cannot be continued by hand through the wrapper.

## 7. Results

After the batch closes and is collected, the wrapper checks the ZIP's SHA-256 against the
container's result and copies it to `runs/container-exports/<workspace>/<batch>-<hash>.zip`.
An identical existing ZIP is kept; a different one with that name is refused.

The volumes, named from the checkout path and `container.workspace`, keep everything else:

| Volume | Mounted at | Holds |
| --- | --- | --- |
| `robofrontier-<id>-<workspace>-runs` | `/opt/RoboFrontier/runs` | Batches, motion, asset cache, receipts, collections, ZIPs |
| `robofrontier-<id>-<workspace>-state` | `/opt/RoboFrontier/.robofrontier` | Per-task Codex homes and sessions, the subscription login, Claude's config |

Do not copy a live SQLite file out of a volume. Deleting a volume deletes its runs; the wrapper
never does.

## Limits

- **No policy environment in the image**, so no batch can be prepared (top of this page).
- **No `continue`** through the wrapper.
- **Seccomp.** Docker's default profile can deny the user namespaces Codex's `native` sandbox
  needs; `seccomp_profile = "unconfined"` drops it for Codex `doctor`, `preflight` and `run`
  only, without `--privileged`.
- **Slurm jobs do not use Docker**; they stage onto node-local scratch ([Slurm](slurm.md)).
- The image has no Blender: Factory rendering runs natively ([Factory replay](../factory/replay.md)).
