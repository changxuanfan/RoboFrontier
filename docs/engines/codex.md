# Native Codex engine

For new experiments, use the [unified CLI](../unified-cli.md) and its versioned
TOML. This guide explains the native Codex path, the retained
`python -m scripts.benchmark` interface, and Luna execution on Linux CPU and
Slurm. See the [Linux guide](../running/server-benchmark.md) for environment choices,
the [engine overview](README.md) for what Codex shares with Claude and for
[shared setup](README.md#shared-setup), and [providers](providers.md) for
catalogs, credentials and third-party endpoints.

The engine lives in `robofrontier/codex/`: `launch.py` builds the app-server
configuration and native home, `batch.py` prepares and supervises batches (and
backs `python -m scripts.benchmark`), and the Node `codex_policy_host.js`,
`codex_rpc.js`, `codex_preflight.js` and `codex_initialize.js` drive app-server.
Selection and `.env` loading shared with Claude are in
`robofrontier/benchmark_common.py`.

Each model/case has an independent run, MuJoCo world, SQLite state, authenticated
connections, policy history, and work notes. Adaptive is the default: only its
Controller decides when and how to delegate within the task. The host does not
choose grasp/placement routes. Single, Controller + Worker, and Worker-Worker
have their own authority and initial-role contracts. New runs use explicit
[direct START](../unified-cli.md#startup-in-all-four-modes); capability `ready`
does not require a waiting turn.

Parallelism counts whole tasks. Adaptive delegates and standing Workers add
model requests within each task. For a shared prepared multi-model batch, each
Dial case uses the same newly sampled private puzzle across models, with
independent worlds and work notes. A new batch samples a new puzzle. Task
parallelism is not a provider quota guarantee.

## Model catalog and defaults

Profiles are in `configs/models.json`. The unified default is `luna`,
`gpt-6-luna/high`, through `OPENAI_API_KEY`. The retained native CLI still defaults
to its historical `astra` selection and parallelism; do not confuse that with
the unified TOML. Process-local model/provider settings do not overwrite the
user's global Codex defaults or sign-in.

Third-party Codex profiles (DeepSeek, Qwen, Zhipu, Kimi), their process-local
`[model_providers]` configuration, endpoints and the dated catalog snapshot are in
[providers: Codex Responses endpoints](providers.md#codex-responses-endpoints).

## Authentication and Codex homes

Native subscription profiles use Codex's own authentication rather than pretending
a subscription credit is an API key. `luna_subscription` selects GPT-6 Luna
through native Codex ChatGPT authentication. The isolated API-home path does not
clone OAuth state. Use the native CLI to sign in and inspect its status:

```sh
codex login
codex login status
```

Subscription batches share one dedicated home, `~/.robofrontier/codex-home`
(or `CODEX_HOME` when set), never the personal `~/.codex`, so personal
configuration, MCP servers, apps and sessions stay out of trials. Log in there
once with `CODEX_HOME=~/.robofrontier/codex-home codex login`; a batch refuses to
start without that login. The policy permission profile denies the home.

An explicitly shared local home can instead be selected in an ignored site
configuration:

```toml
[policy]
engine = "codex"
profile = "luna_subscription"

[runtime]
codex_home_scope = "shared"
codex_home = "~/.codex"
```

Credentials remain in Codex's native store. Preparation writes command-line
overrides that disable MCP servers found in native and project configuration
layers. Before inference, the native subscription host and preflight verify
that the effective configuration has no enabled inherited MCP server. The
benchmark supplies its assigned dynamic tools. A later configuration change
that introduces another server fails this admission check. User configuration
files are not rewritten. Names that cannot be safely expressed through the CLI
override syntax require a separate native home.

The native account refresh probe uses `account/read` with `refreshToken: true`,
then verifies authenticated access and persistence in a new app-server process.
That probe makes no model turn. A passing probe is separate from image/tool,
compaction, fork, concurrency and task qualification. Concurrent subscription
refresh/isolation remains a separate qualification boundary; see
[qualification and limits](providers.md#qualification-and-limits).

New API runs isolate Codex homes per task. That task's Controller, snapshots,
and delegates share its home to retain native lineage. Different tasks have
different homes. The resolved home is recorded in the run's Codex home marker;
original transcripts are under its `sessions/` directory, and run-v6 runs also
keep verified copies in `private/engine/transcripts/`
([evidence storage](../running/evidence-storage.md#session-transcripts)). Legacy
shared-home runs keep their recorded location. Collection preserves the relevant
native traces without exporting authentication/config/state databases.

## Preflight, preparation, and launch

### Linux containers without namespaces

Select `runtime.codex_tool_backend = "landlock-v1"` explicitly on Linux when the
container cannot run the native namespace sandbox. The default remains `native`.
The [Sol L3 CPU example](../../configs/examples/sol61-l3-cpu.toml) uses this backend
with subscription authentication, four tasks, high effort and a 24-hour task limit.
Keep the dedicated authentication home outside collected evidence.

The backend replaces model-accessible shell, patch and image handlers with
role-bound `policy_exec` and `policy_image`. Each call starts a fresh subprocess
under the frozen access table, Landlock and seccomp. The subprocess receives no
host credentials or inherited descriptors; `/proc` and general `/tmp` are denied,
and temporary writes use `workspace/.tmp`. Sockets, io_uring, process-memory
inspection, cross-process signals and privileged namespace operations are denied;
worker capabilities are dropped. Images are opened inside that boundary. The
trusted native Codex process retains authentication, sessions and robot transport.
Native named permissions remain configured; this mode does not select full access.
Subscription runs use a process-local `OpenAI` provider entry with native
authentication and HTTP/SSE transport, avoiding rejected WebSocket handshakes in
this container. Credentials remain in Codex's native store; no token is copied
into provider settings. The broker host allows up to 120 seconds for engineering
sealing, without extending the persisted task deadline or replaying actions.

Doctor exercises real allowed and denied file/socket operations. The live preflight
also checks the two broker tools, images, compaction and inherited fork tools;
its receipt pins the backend source, model metadata and CLI version. A changed
backend requires another preflight and newly prepared batches. Native and broker
receipts are not interchangeable. Run the installed-CLI protocol/adversarial test
without external inference using:

```sh
.venv/bin/python -m scripts.check_codex_broker --output runs/engineering/NEW_BROKER_CHECK
```

This test inspects the actual model tool inventory, rejects forged native calls,
and exercises fork/resume and eight concurrent roles. Separate physical engineering
runs still establish role startup, robot transport and shutdown on the target host.

Prefer the unified commands, which use current TOML defaults:

```sh
.venv/bin/robofrontier bootstrap
.venv/bin/robofrontier plan
.venv/bin/robofrontier doctor
# Billable provider compatibility check, separately authorized.
.venv/bin/robofrontier preflight --confirm-spend
.venv/bin/robofrontier prepare --output runs/policy/NEW_BATCH
.venv/bin/robofrontier run runs/policy/NEW_BATCH
```

Use the explicit Linux CPU or macOS native renderer when appropriate; the default
is Linux NVIDIA. A prepared batch keeps its frozen backend. Preparation calls
no model, starts no physical world, and requires a new output directory.

The retained native interface is useful for reproducing its original workflows:

```sh
.venv/bin/python -m scripts.benchmark models
# Billable: images, tools, manual compaction and native fork checks.
.venv/bin/python -m scripts.benchmark preflight --models astra
.venv/bin/python -m scripts.benchmark prepare --models astra \
  --families mosaic --output runs/policy/NEW_NATIVE_BATCH
.venv/bin/python -m scripts.benchmark run runs/policy/NEW_NATIVE_BATCH --parallel 9
.venv/bin/python -m scripts.benchmark status runs/policy/NEW_NATIVE_BATCH
.venv/bin/python -m scripts.benchmark stop runs/policy/NEW_NATIVE_BATCH
```

Omitting family/case filters prepares all 36 cases per selected model. The native
entry accepts up to 36 task slots, but local CPU, memory, disk, rendering, native
sessions, delegates, and provider capacity remain real bounds. Prepare a new
batch after changing execution source or frozen inputs; never restart a previously
started physical world to reuse its result directory.

Execution checks the compatibility receipt against the actual profile, provider
address, context, effort, generated model metadata, and native CLI version. The
full check exercises image/tool round trips, manual compaction, and inherited
fork history followed by tools. It does not establish the complete context window,
automatic compaction threshold, provider's internal model identity, task ability,
or long-term stability. A smoke-only receipt does not qualify a scored run.

The current release selects policy Mosaic R15. Historical Oracle/Factory
recordings retain their frozen R13 source colors. Unified new Oracle executions
select current released scenes independently. A revision in another worktree
does not silently enter this registry or replace historical evidence.

## Time, capacity recovery, and context

The public default is 24 hours from each task's persisted START, including policy
reading, reasoning, tools, communication, fork setup, and capacity waits. The
physical service enforces its deadline: bar new actions, request braking, evaluate
the cutoff, and seal recording. Settling after the deadline is not timely success.
The host does not add a second fixed deadline from process creation. Startup
readiness and an operator's engineering stop are separate. Slurm allocations
must cover startup and cleanup as well as task execution. Ended worlds never
silently restart.

Explicit failed capacity/rate-limited turns wait at least ten seconds and can
continue the same native session only under the safe runtime conditions. They
do not replay robot motion, reset the world, or extend the deadline. Authentication,
quota exhaustion, and ordinary task errors are not blindly retried as capacity
errors. Unknown creation/fork/send acknowledgements retain evidence and stop
automatic replay. For uncertain physical operations, query the original request
ID; the request/query/retry rules are in
[new requests, queries and delegation](README.md#new-requests-queries-and-delegation).

`configs/models.json` sets a 300,000-token context window and a 267,000-token
automatic compaction threshold for both engines; each run freezes them. Claude
Code compacts at `CLAUDE_CODE_AUTO_COMPACT_WINDOW` minus its 33,000-token summary
buffer, so its window is set to 300,000 to land on the same threshold. Earlier
runs used 272,000 and 258,400. A changed catalog needs a new model preflight
before Codex batches start. Settings do not enlarge the provider's real context.
System/output reservations and the native catalog's effective-window allowance
can change the displayed available size. Preserve the actual requested/reported values, tokenizer,
compaction behavior, effort, response model identity, and date. Equal effort
names do not establish equal computation across providers or engines.

## Images, motion, and later video

The policy receives real selected-camera RGB through MuJoCo and its explicit
OpenGL backend. Tools return JSON and selected image content; a file path alone
does not prove the model saw an image. Current observations use JPEG
896 x 560 at quality 85 ([observation images](../protocol.md#observation-images)).
Hidden service operation does not continuously draw a preview; real-time video
encoding is optional and disabled by default.

The recorder samples physical state at 60 Hz, independently of screenshots,
including arm/object motion and appearance events. Sampling at physical substeps
does not preserve arbitrary changes above that bandwidth. Current float32/XOR
compression retains states and timestamps; old streams remain readable. Removing
idle or unproductive intervals is an editable presentation derivative and does
not overwrite the original evidence. Native session collection externalizes
image payloads into shared objects for portable archives; it does not change
what was sent to the API. See [evidence storage](../running/evidence-storage.md).

Later [Factory rendering](../factory/replay.md) replays recorded motion without dynamics,
with independent 30 fps/1080p or configured output quality. It need not use the
model-observation resolution. Each recording uses matching frozen geometry,
parameters, appearance events, and edits.

## Native sessions and Desktop

The host uses native `thread/start`, `turn/start`, and `thread/fork`, binds real
session IDs, and verifies fork lineage through parent ID, source ordinal, and
history hashes. Initial task sessions are clean; only an authorized in-task
delegate inherits its own Controller's allowed current-task history.

Status reports native IDs and observed states. A separate Desktop's `notLoaded`
label does not establish that an app-server stopped. Do not manually start a
competing turn in a live task's session. Desktop visibility can depend on source,
provider, sign-in, and project filters; automatic visibility of every third-party
session is not qualified, and the host does not forge Desktop private databases.
When auditing native `thread/list`, include the relevant app-server/exec sources
rather than assuming the interactive default covers every session. See the
[official app-server guide](https://developers.openai.com/codex/app-server/).

Threads that Codex Desktop creates cannot receive the CLI host's dynamic `robot`
tool. `python -m robofrontier.desktop_robot_mcp` is one global MCP stdio server
that gives them the same role API: it maps the calling thread, which Codex puts in
each call's `_meta`, to the role bound to that thread in a run's runtime database.
The model never names its role or sees a connection file. Print the entry for the
Desktop `config.toml` with `--print-config` (add `--runs-root` when runs are not
under `runs/`) and register it once. The entry sets
`default_tools_approval_mode = "approve"`; without it every call waits for a person.

Local real-CLI checks use a synthetic Responses service without external billing:

```sh
.venv/bin/python -m scripts.check_codex_cli --output runs/engineering/NEW_CLI_CHECK
.venv/bin/python -m scripts.check_codex_snapshot
```

A passed offline check is evidence for its exact protocol/version, not acceptance
of every external provider or a formal task score. Current check scope is in the
[integration ledger](../archive/unified-main.md). Role permissions and
authenticated tools define the benchmark interface; they are not a claim of
operating-system containment against malicious policy code.

## Luna on Linux CPU and Slurm

This section was written for the unified `integration/unified-main` checkout
before it replaced the published default branch. Start with the
[unified CLI](../unified-cli.md) and use the [Slurm staging guide](../running/slurm.md)
for queue execution. The native `scripts.luna_cpu` wrapper remains a
compatibility entry, with different Codex home behavior; it is not the new
cluster submission mechanism.

New-run defaults select Luna/high, official OpenAI API authentication, adaptive
organization, all 36 R14 task selections and 36 requested concurrent task hosts.
CPU rendering is an explicit override of the unified Linux NVIDIA default.
MuJoCo dynamics always use CPU; Linux CPU images use Mesa OSMesa/llvmpipe.
Adaptive delegates may create more native sessions/model requests than tasks.
No outer agent session is needed to prepare, launch, monitor, stop or collect.

A task's default 86,400-second limit starts at its persisted START, separately
for every task. The host does not impose another fixed 24 hours from process
creation. The initial launch interval is 0.3 seconds. Startup timeout, scheduler
allocation lifetime and cleanup allowance are separate. A 36-task capacity or
long-running provider qualification has not been demonstrated on your cluster.

### Install and verify

Follow [shared setup](README.md#shared-setup) for Python, uv, Node.js, `.env` and
policy assets. Linux CPU rendering additionally needs Mesa OSMesa and an
operating environment that supports the native Codex sandbox. Configure software
according to the site's rules; a site may not provide Docker or permit
installing system packages. Without a global Codex install, install the pinned
CLI locally (the version must match `CODEX_VERSION` in
[`docker/Dockerfile`](../../docker/Dockerfile), currently `0.165.0`). Job-scoped
(Slurm subscription) batches and their preflight refuse to start with any other
`codex` first on `PATH`:

```sh
uv sync --locked --extra oracle
npm install --prefix "$PWD/.codex-tools" @openai/codex@0.165.0
export PATH="$PWD/.codex-tools/node_modules/.bin:$PATH"
cp .env.example .env
chmod 600 .env
# Edit OPENAI_API_KEY locally; do not print or commit its value.
.venv/bin/robofrontier bootstrap
.venv/bin/robofrontier doctor --render cpu
```

On Debian-family systems, `libosmesa6` supplies the relevant software GL
library. Doctor checks local CLI, sandbox and actual rendering prerequisites
without calling a model. Native macOS does not support this OSMesa mode: use
`--render native` for Mac rendering, or use the [Linux container flow](../running/docker.md)
for CPU OSMesa.

### Configure and run without Slurm

Create an operator TOML on a filesystem local to the executing machine:

```toml
# luna-cpu-site.toml
[render]
device = "cpu"

[slurm]
gpus = 0
```

The root defaults supply Luna/high, adaptive, 36 tasks, 36 concurrent slots and a
24-hour task clock. For a 12-hour task, set `batch.task_wall_limit_s = 43200.0` in
the appropriate `[batch]` table. The scheduler allocation must also cover setup,
execution and stage-out. This task clock is not a monetary cap.

```sh
.venv/bin/robofrontier --config luna-cpu-site.toml plan
.venv/bin/robofrontier --config luna-cpu-site.toml preflight --confirm-spend
.venv/bin/robofrontier --config luna-cpu-site.toml prepare \
  --output runs/policy/luna-all-36
.venv/bin/robofrontier run runs/policy/luna-all-36
```

Only run a paid preflight/execution with the account owner's authorization. A
small smoke receipt does not replace the required complete provider receipt.
Preparation itself freezes inputs and calls no model. Use a new output directory
for each batch. A changed CLI/model/provider/configuration needs a matching new
preflight. The foreground runner waits for its batch; it is not detached merely
because a chat tool returned. Use an appropriate persistent process/job manager.

For a small Level 1 engineering selection, add `--level 1 --min-arms --parallel 4`
to `prepare` and inspect the four-task plan first. Change task duration in TOML,
not by editing a frozen task or altering source hashes.

```sh
.venv/bin/robofrontier status runs/policy/luna-all-36
.venv/bin/robofrontier stop runs/policy/luna-all-36
```

The 24 hours are a maximum, not a requirement to keep a completed task alive.
Controller may finish after completion or a publicly justified unrecoverable
state, once actions/delegates are resolved. Finish triggers evaluation; a claim
of success alone cannot pass the scorer. Incomplete or interrupted tasks retain
that outcome. No automatic physical-world restart or replay follows a crash.

### Queue on Slurm

Active SQLite WAL files, Codex homes/sessions, temporary data, observations and
motion must live on verified **node-local storage**, not Lustre/NFS. Shared
storage can hold the committed source, read-only assets and stopped stage-out
packages. Do not write large data into quota-limited home directories. The
[Slurm guide](../running/slurm.md) specifies node-local filesystem checks,
descendant-process tracking, API credential handling, stop warnings and verified
stage-out. Real allocation, x86_64/NVIDIA and site-specific capacity
qualification remain open.

From the Linux login node, after the explicit preflight and site resource review:

```sh
.venv/bin/robofrontier --config luna-cpu-site.toml slurm-submit \
  --output runs/submissions/luna-all-36
.venv/bin/robofrontier --config luna-cpu-site.toml slurm-submit \
  --output runs/submissions/another-luna-all-36 --queue
squeue -u "$USER"
```

The first example only freezes a submission. The second freezes a different new
submission and explicitly queues it. Do not reuse the same output directory to
submit a second experiment. The snapshot pins committed source, settings,
launcher and verified assets. It does not rely on later checkout edits. Resource
requests are not proof that 36 tasks plus delegates fit available memory/API
limits. Slurm time includes setup and cleanup, independently of task START.

The old sbatch entries and their `RF_BATCH_OUTPUT`, `RF_WALL_LIMIT_S` and
`RF_PARALLEL` workflow are retired; use `slurm-submit`.

### Four maximum-arm Level 3 tasks

Copy [`configs/examples/luna-l3-cpu.toml`](../../configs/examples/luna-l3-cpu.toml) to
an untracked site TOML and review partition/account/CPU/memory/scratch settings:

```sh
cp configs/examples/luna-l3-cpu.toml l3-cpu-site.toml
.venv/bin/robofrontier --config l3-cpu-site.toml plan
```

| Family | Task | Arms |
| --- | --- | ---: |
| Transport | `transport-a12-d3` | 12 |
| Mosaic | `mosaic-a08-12x24-d3` | 8 |
| Relay | `relay-a16-d3` | 16 |
| BEST5 Dial | `dial-best5-n08-d3` | 16 |

The example requests exactly these four tasks, parallel 4, Luna/high/adaptive,
CPU observations, one hour per task after START, and a two-hour Slurm allocation
ceiling. Other resource requests inherit the root defaults until you edit them;
they are not measured requirements. For a 30-minute task cap, set
`batch.task_wall_limit_s = 1800.0`. Keep setup/stage-out allowance in the allocation.
Use the same explicit preflight and `slurm-submit --queue` flow as above. This
engineering selection is not a replacement for the 36-task/24-hour defaults.

### Evidence and resource metrics

New unified API runs isolate task-native Codex state; the batch records actual
home/session paths. The native Luna compatibility wrapper instead records its
batch home in `codex-home.json`, generally under
`.codex-luna/<batch-name>-<path-hash>/sessions/`. Neither location is the shared
server user's default `~/.codex` unless explicitly configured that way. Docker
uses persistent local volumes and exports stopped results; inspect that flow's
own recorded paths rather than guessing a host path.

`private/outputs/codex-host.jsonl` contains host scheduling/tool/timing events,
not the complete native session. Native `<session-id>.jsonl` traces retain model
turn evidence. Motion, frozen source, process events and referenced JPEGs have
separate output paths. Realtime MP4 is off by default; later offline video can
use another resolution/background. The [evidence guide](../running/evidence-storage.md)
explains compression, image references, collection manifests, verified ZIPs,
restore and provenance. Collection copies originals; it does not silently delete
source evidence or turn engineering errors into model failures.

Inspect metrics in the same execution context, using stopped evidence when a
command opens SQLite. Do not read a live container database from the Mac host,
or an active node database across a shared mount. Native compatibility commands
include `scripts.luna_cpu usage`, `performance` and `collect`. Usage deduplicates
recorded responses and reports missing traces; it is not the provider bill.
Completed-response TPM is not a provider admission/rate-limit counter. Model
turn duration includes tool waits; action and model intervals overlap and must
not be summed as disjoint cost/time categories. Owner counters are not a complete
continuous CPU/RSS profiler. Where configured, Slurm can report:

```sh
sacct -j JOB_ID --format=JobID,State,Elapsed,AllocCPUS,MaxRSS,TotalCPU
```

Site accounting determines metric scope. Inspect missing sessions/evaluations,
unsealed outcomes and stage-out receipts before sharing a collected package.
A backup is a separately retained verified copy, not merely an ignored run folder.

### Native compatibility commands

For a local Linux filesystem and an existing compatible environment, the native
wrapper retains `setup-assets`, `doctor`, `preflight`, `prepare`, `submit`, `run`,
`status`, `stop`, `usage`, `performance`, `collect`, and `l3-max-test`. Its profiles
include `luna`, `openlux-luna` and `openlux-terra` (see
[OpenLux Terra](../archive/openlux-terra.md)); changing profile changes the
required API key and provider preflight. It does not stage live state to Slurm
scratch. Prefer the unified entry for new task-isolated/concurrent deployments.

The following remains a model-free way to inspect the legacy L3 preparation:

```sh
.venv/bin/python -m scripts.luna_cpu l3-max-test --prepare-only \
  --output runs/policy/legacy-l3-draft
```

Its native one-hour default, optional `--wall-limit-s`, parallel-4 selection and
private `codex-home.json` marker remain compatibility behavior. An already
prepared directory is executed with its separate native `run` command after a
matching preflight, not by invoking `l3-max-test` over it again. Never move a
prepared live batch between machines/absolute paths or mix native and unified
configuration markers. Old Docker commands/image defaults are documented as
Legacy; new work should use the frozen [Docker commands](../running/docker.md).
