# Docker execution with persistent local volumes

The unified image contains both native policy CLIs, the locked Python environment
and the pinned policy assets. It supports CPU OSMesa and Linux NVIDIA EGL
observations. It does not replace the native Codex or Claude session mechanisms.

The policy image does not install Blender or expose `container factory`. Use the
native [Factory workflow](../factory/replay.md) on a provisioned render host. Docker CPU
MuJoCo observations and Blender Cycles background rendering are separate paths.

Use the repository's command wrapper rather than manually mounting an entire
checkout as a writable runtime directory. The wrapper creates all directories
and two plain local Docker volumes. Active SQLite and original session files stay
inside the Docker host's local filesystem. Only stopped, verified ZIP evidence is
copied back to the operator's worktree.

The implementation is being validated on the integration branch. Offline tests
are not a claim of real model, NVIDIA, Slurm or 36-task resource qualification.

## Build and configure

Install Docker Desktop on macOS or the site's supported Docker engine on Linux.
Run commands from a clean committed checkout installed with uv sync --locked.

~~~bash
robofrontier container build
~~~

Nested help is handled locally before configuration, Docker, credentials or
runtime directories are accessed. This also works with Docker unavailable:

~~~bash
robofrontier container build --help
robofrontier container prepare --help
robofrontier container preflight --help
robofrontier container auth --help
~~~

`container build` accepts no extra arguments. Misspelled options and missing
required native-command arguments are rejected before any Docker work. Auth
help describes the allowed wrapper actions; actual login options are forwarded
to the selected native CLI.

The wrapper supplies git archive HEAD as the build context, excluding ignored
.env, authentication, outputs and run data. The image is tagged with that source
revision. An existing custom image with another revision is rejected. Commit
tracked changes before rebuilding; a build never silently captures uncommitted
experiments or credentials.

The build installs the CLI pins Codex 0.165.0 and Claude Code 2.1.316 (`robofrontier/runtime/versions.py`).
They are reproducibility pins, not a claim that they are the latest releases.
The Python dependency lock is used unchanged. Policy assets are downloaded and
verified during image construction. No model call occurs during build.

The Linux default is NVIDIA EGL. For macOS Docker, explicitly prepare CPU tasks:

~~~toml
# cpu.toml
[render]
device = "cpu"

[container]
workspace = "cpu-bench"
memory_gib = 0
cpus = 0.0
seccomp_profile = "unconfined"
~~~

Docker's default seccomp profile can deny the user namespaces required by the
native Codex sandbox. This was reproduced on macOS Docker Desktop: the local
sandbox probe failed with the default profile and passed with the explicit
`unconfined` setting above. The repository default remains `default`; this option
removes Docker's seccomp filter for Codex doctor/preflight/run containers only.
It does not add `--privileged`, host directories or administrator capabilities,
and does not disable Codex's own workspace sandbox. Treat it as an explicit
container security choice. A site can instead enable the required namespace
operations in its own approved Docker policy. This particular image does not
accept arbitrary host seccomp file paths.

Run the free local check before an explicitly paid provider preflight:

~~~bash
robofrontier --config cpu.toml container doctor
~~~

Doctor checks the selected native CLI, the Codex sandbox when selected, and an
actual MuJoCo RGB context. It does not authenticate or invoke a model. The CLI
also checks native prerequisites before a confirmed provider preflight and
checks both sandbox and rendering before starting a prepared task batch. A
failure blocks model calls; there is no automatic permission escalation or
renderer fallback. Claude's native CLI check does not establish its internal
permission/agent lifecycle qualification.

Zero resource limits add no quota beyond the Docker engine or allocation.
Docker Desktop's VM memory is still a real bound. Defaults request 36 concurrent
tasks; this is not a promise that a small VM can sustain that many simulators,
model sessions and delegates. Supply enough resources or explicitly configure a
smaller test. The wrapper does not silently change requested concurrency.

NVIDIA task execution adds the NVIDIA container GPU request and graphics driver
capabilities. It requires Linux, an NVIDIA device, working host drivers and the
NVIDIA container runtime. Actual GL vendor/renderer verification rejects silent
software fallback. Docker on macOS uses its Linux VM; it does not expose Metal
or the Mac GPU to MuJoCo through this image.

## Prepare and run with commands

Set the selected credential in the ignored local .env or process environment.
The wrapper forwards the selected credential/base-URL variable by name. Secret
values are not included in Docker command arguments, image layers, TOML, command
receipts or exported evidence.

~~~bash
robofrontier --config cpu.toml container plan
robofrontier --config cpu.toml container prepare \
  --output runs/policy/example-l1 --level 1 --min-arms --parallel 4
~~~

Planning and preparation do not call a model. Preparing another directory is an
explicit new run, never an automatic restart of an existing world.

A provider preflight is a separate, explicitly billable action:

~~~bash
robofrontier --config cpu.toml container preflight --confirm-spend
robofrontier --config cpu.toml container run runs/policy/example-l1
~~~

Use a full matching model compatibility receipt, not a smoke-only receipt.
The run checks its frozen inputs, profile/catalog hashes and native CLI version
before task execution. The container command uses the batch's frozen renderer,
not the current host TOML default, when starting an existing batch.

A Claude run needs passed precheck receipts. Select an actual Claude profile in TOML,
perform its explicitly budgeted preflight, then run the batch.
All four Claude topologies have native engineering entries, including persistent
Controller + Worker and Worker-Worker sessions. See the
[standing-team guide](../engines/claude-code.md#standing-teams). Formal scored qualification
remains closed; local synthetic-provider checks do not qualify a real provider.

Keep batch/output paths relative to runs/. Those paths refer to persistent
container storage. They are not ordinary host paths while the task is running.

## Status, stop and export

~~~bash
robofrontier --config cpu.toml container status runs/policy/example-l1
robofrontier --config cpu.toml container stop runs/policy/example-l1
~~~

Status reads atomic supervisor JSON. Stop writes STOP markers through another
container in the same local volumes; it does not open a writer's SQLite database.

Ctrl-C during a wrapped run requests the same orderly stop, then allows time for
sealing and collection. A disconnected or still-running container is retained
and reported for review. The wrapper never restarts it or exports its active
database. Its name is recorded under:

~~~text
.robofrontier/containers/WORKSPACE/commands/rf-ID.json
~~~

After normal task closure and automatic collection/archiving, the wrapper copies
one ZIP to:

~~~text
runs/container-exports/WORKSPACE/BATCH-PATHHASH.zip
~~~

It checks the exported SHA-256 against the container's terminal command result
before publishing the host file. An identical existing ZIP is reused; a different
file with that name is rejected. Original batch data, sessions and motion remain
inside the local volumes. No automatic destructive cleanup occurs.

A sealed/collected archive does not mean the model succeeded. Inspect independent
per-task evaluations, process events, collection issues and uncertain-action
records. Failed or interrupted trials are not silently relabeled as model
failures or successful tasks.

## Where native sessions and credentials live

Two separate plain local Docker volumes are named from the checkout identity and
container.workspace. Different worktree paths/workspaces get different names:

- runs volume -> /opt/RoboFrontier/runs: prepared batches, motion, asset cache,
  native collected evidence, evaluation and ZIP archives.
- state volume -> /opt/RoboFrontier/.robofrontier: API task Codex homes,
  session rollouts and explicitly configured subscription authentication.

Within the state volume, API task sessions are under
codex/TASK_HASH/sessions/. Each task's Controller and native forks share its home;
different tasks have different homes. All task homes are initialized before the
0.3-second initial-host launch schedule.

The host's ~/.codex, macOS Keychain, ~/.claude and default server login state are
not mounted or cloned. Local Docker volumes are private runtime state, not an
artifact to publish. Do not manually copy an active SQLite file from them.
Deleting a volume deletes its original runtime data; the wrapper never does so.

## Subscription authentication

A native Codex subscription profile requires an explicitly shared home and a
login in this workspace's own persistent subscription directory:

~~~bash
robofrontier --config subscription.toml container auth codex login --device-auth
~~~

Use policy.profile for an actual native Codex profile and
runtime.codex_home_scope = "shared" in subscription.toml. The dedicated container
CODEX_HOME is /opt/RoboFrontier/.robofrontier/subscription. This login is separate
from the operator's host Desktop account. Availability of a subscription model
and account credits still depends on that account. Shared-home refresh and
multi-task subscription qualification remain explicit acceptance work.

For Claude's explicit OAuth-token profile, obtain a token using the native CLI:

~~~bash
robofrontier container auth claude setup-token
~~~

Store the resulting token locally in the declared credential environment variable
and select the corresponding subscription profile. Do not paste it into a prompt,
commit or evidence archive. The runner supplies it to each native CLI through
the environment; Desktop's stored credentials are not copied into run inputs.

Authentication commands are explicit user actions. Building, planning, preparing,
status and stop do not log in or invoke a model automatically.

## Compatibility and limits

Existing frozen data remain readable; new unified runs use this wrapper and
`docker/Dockerfile`. The older `scripts.luna_cpu` entry was removed on 2026-11-10.

The image's Python/CLI/system-library pins, source revision and asset lock define
the executable environment. A later source change requires a new image and new
prepared runs. This is not a standalone wheel distribution or a checkpoint/resume
implementation. Slurm batch execution has its own node-local staging workflow;
do not assume a cluster permits a Docker daemon or that Docker's GPU visibility
matches a Slurm allocation without the site's configuration.
