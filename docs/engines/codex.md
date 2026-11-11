# Codex engine

Every policy role is a native Codex app-server thread (`thread/start`, `turn/start`,
`thread/fork`) with the robot tool as an app-server dynamic tool. All four topologies run:
`single`, `adaptive` (the default), `controller-worker` and `worker-worker`. The pinned CLI is
Codex 0.165.0 (`robofrontier/runtime/versions.py`). A run starts only with a passed compatibility
receipt for its profile, catalog and CLI version ([Preflight and receipts](#preflight-and-receipts)).
What both engines share is in the [engine overview](README.md); the
[Claude Code guide](claude-code.md) has the same sections.

The engine is `robofrontier/engines/codex/`: `launch.py` builds the app-server configuration and
Codex home, `robofrontier/batch/codex_batch.py` prepares and supervises batches, and the Node
`codex_policy_host.js`, `codex_rpc.js`, `codex_preflight.js` and `codex_initialize.js` drive
app-server.

## Install

Follow [shared setup](README.md#shared-setup), then install the pinned CLI and prepare without
model calls:

```sh
npm install --global @openai/codex@0.165.0      # or: npm install --prefix "$PWD/.codex-tools" @openai/codex@0.165.0
codex --version
.venv/bin/robofrontier plan --level 1 --min-arms --parallel 4
.venv/bin/robofrontier prepare --render native \
  --level 1 --min-arms --parallel 4 --output runs/policy/codex-l1
```

With a prefix install, put `$PWD/.codex-tools/node_modules/.bin` first on `PATH`; Slurm
subscription jobs and their preflight refuse to start with another `codex` first on `PATH`. Use
`--render native` on macOS, `--render nvidia` (the default) or `--render cpu` on Linux; CPU
rendering needs Mesa OSMesa (`libosmesa6` on Debian-family systems) and is not available on
macOS. MuJoCo dynamics always run on the CPU. Preparation restores pinned assets when needed,
freezes the run and starts no world or model session. The Claude CLI is not needed.

## Authentication

Profiles are the `codex` section of `configs/models.json`; the
[authentication matrix](README.md#authentication-matrix) lists each one's credential. Model and
provider settings are process-local and never change the user's global Codex configuration.

**API profiles** (`luna`, OpenLux, third-party) read their key from `.env`. With the default
`runtime.codex_home_scope = "task"` each run gets its own Codex home under `.robofrontier/codex/`
(or under `runtime.codex_home`), shared by that run's Controller, snapshots and delegates so fork
lineage stays readable. Homes are initialized one at a time before any task host starts.

**ChatGPT login** (`luna_subscription`, `sol61_subscription`, `terra61_subscription`, `astra`)
uses Codex's own login and needs `runtime.codex_home_scope = "shared"` (task scope refuses these
profiles). The shared home is `runtime.codex_home`, else `CODEX_HOME`, else
`~/.robofrontier/codex-home`, never the personal `~/.codex`. Log in there once; a batch refuses
to start without the login:

```sh
CODEX_HOME=~/.robofrontier/codex-home codex login
CODEX_HOME=~/.robofrontier/codex-home codex login status
```

```toml
# Untracked site TOML for a subscription batch
[policy]
profile = "luna_subscription"

[runtime]
codex_home_scope = "shared"
```

On Slurm, subscription runs use `codex_home_scope = "job"` with `slurm.auth_mode =
"subscription"` and a private `slurm.credential_store`
([Slurm subscription jobs](../running/slurm.md#subscription-jobs),
[`configs/examples/slurm.toml`](../../configs/examples/slurm.toml)).

Every home must lie outside the batch; the access table denies it to the policy. Preparation adds
command-line overrides that disable every MCP server found in the native and project
configuration, and the host and preflight check that none is enabled before inference; the user's
files are not rewritten. A home's location is recorded in each run's `codex-home.json`.

`robofrontier doctor` checks the installed CLI version, the sandbox or tool backend and a real
render. It does not check credentials or call a model.

## Isolation

The frozen access table (`robofrontier/runtime/access.py`) closes the checkout, the home
directory, other runs and shared storage to the policy. `runtime.codex_tool_backend` selects how
model shell, patch and image tools are confined:

| Host | `codex_tool_backend` | Mechanism |
| --- | --- | --- |
| macOS, Linux where Codex's sandbox works | `native` (default) | Codex's own sandbox with named permission profiles; `doctor` runs `codex sandbox` to check it |
| Linux without namespaces, such as a RunPod pod | `landlock-v1` (set explicitly) | Shell, patch and image handlers are replaced by role-bound `policy_exec` and `policy_image`; each call is a fresh subprocess under the access table, Landlock and seccomp |

Under `landlock-v1` the subprocess gets no host credentials or inherited descriptors; `/proc` and
general `/tmp` are denied (temporary files go to `workspace/.tmp`); sockets, io_uring,
process-memory inspection, cross-process signals and namespace operations are denied; capabilities
are dropped. Without user namespaces `/dev/shm` stays closed, so Python process pools fail; other
processes stay visible but their environments cannot be read. The trusted Codex process keeps
authentication, sessions and robot transport. Subscription runs under this backend use a
process-local `OpenAI` provider over HTTP/SSE instead of WebSockets. Docker hosts can instead
allow the native sandbox with `container.seccomp_profile = "unconfined"`
([Docker](../running/docker.md)). [`configs/examples/runpod.toml`](../../configs/examples/runpod.toml)
is a complete RunPod example; put the Node.js and CLI folders on `PATH`
([RunPod guide](../running/runpod.md)).

A receipt pins the backend; a backend change needs a new preflight and newly prepared batches.
The installed-CLI broker test, without inference, inspects the model's tool inventory, rejects
forged native calls and runs fork/resume with eight concurrent roles:

```sh
.venv/bin/python -m robofrontier.engines.codex.check_codex_broker --output runs/engineering/broker-check
```

## Preflight and receipts

```sh
.venv/bin/robofrontier preflight --confirm-spend               # full check, real spend
.venv/bin/robofrontier preflight --confirm-spend --smoke-only  # image/tool round trip only
```

Without `--confirm-spend` it makes no call and reports `not_run`. Pass the same `--config` and
options as for `prepare`. The full check runs image and tool round trips, a manual compaction, and
a fork whose child inherits history and then uses tools. Receipts:
`<runs_root>/engineering/model-compatibility/<profile>/report.json` (full) and
`<runs_root>/engineering/model-smoke/<profile>/report.json` (smoke). Before each run, the batch
checks the full receipt against the frozen profile, provider address, context, effort, catalog
hash, CLI version and tool backend, and refuses on any mismatch; a smoke receipt never qualifies a
run. Local checks of the real CLI against a synthetic Responses service, with no billing:

```sh
.venv/bin/python -m robofrontier.engines.codex.check_codex_cli --output runs/engineering/cli-check
.venv/bin/python -m robofrontier.engines.codex.check_codex_snapshot
```

## Run, status and stop

```sh
.venv/bin/robofrontier run runs/policy/codex-l1        # launchd on macOS; --durable on Linux
.venv/bin/robofrontier status runs/policy/codex-l1
.venv/bin/robofrontier stop runs/policy/codex-l1
.venv/bin/robofrontier continue runs/policy/codex-l1   # by hand, as the same trials
```

`run` makes paid calls. It checks the receipt, the frozen configuration and every run's input
inventory, validates each home's startup configuration without inference, then starts at most
`batch.parallel` task hosts, 0.3 s apart. The physical owner enforces the cutoff: it bars new
actions, brakes, evaluates and seals. An ended world never restarts. Each run's status is
`stopped_before_start`, `closed` (host exited cleanly; says nothing about task success) or
`needs_review` (any other exit, a stop between segments, or the 48 h
[wall backstop](../running/continuation.md#wall-backstop), whose result is not counted). On Slurm, use
`robofrontier slurm-submit` ([Slurm](../running/slurm.md)).

## Sessions and delegation

The host binds real thread IDs and verifies fork lineage by parent ID, source ordinal and history
hashes. Initial sessions are clean. For an Adaptive delegation the host first forks a snapshot
thread of the Controller without running a turn, persists its ID, then forks each delegate from
that snapshot and sends the delegate message after the runtime activates the batch. Each delegate
gets its model and effort explicitly on its first turn. Unknown creation, fork or send
acknowledgements keep their evidence and stop automatic replay.

Do not start a turn by hand in a live run's thread. Codex Desktop's `notLoaded` label does not mean
an app-server stopped; when auditing with `thread/list`, include the app-server and exec sources.
Threads that Codex Desktop creates cannot receive the dynamic `robot` tool;
`python -m robofrontier.engines.codex.desktop_robot_mcp` is a global MCP server that gives them
the same role API by mapping the calling thread (from each call's `_meta`) to its bound role.
Print its Desktop `config.toml` entry with `--print-config` (add `--runs-root` when runs are not
under the default runs root) and register it once; the entry sets
`default_tools_approval_mode = "approve"`.

## Standing teams

`controller-worker` and `worker-worker` start one thread per initial role, with the same roles,
routes, single START (`direct_team_v3`) and mailbox as
[Claude Code standing teams](claude-code.md#standing-teams). Delegates and standing Workers add
model requests inside each run; `batch.parallel` counts runs.

## Recovery

- **Capacity errors**: bounded same-session resume ([capacity recovery](README.md#capacity-recovery)).
  Authentication errors, quota exhaustion and ordinary task errors are not retried as capacity
  errors.
- **Network outage**: as on Claude Code, in a run that counts active time, a turn that failed
  within 30 s of an egress or network-outage pause is continued once per role and pause with the
  frozen `network-resume.md`, after the runtime grants the claim (`network-recovery`) and once the
  role has no robot work in flight. A network or unclassified failure is continued; any other
  failure in that window, or a second one, holds the run for review.
- **Unexpected stop**: the run continues by itself once
  ([continuation](../running/continuation.md#when-a-run-continues),
  [Codex task recovery](../running/continuation.md#codex-task-recovery)). A Slurm `job`-scope
  run never reconnects or replays turns automatically.
- For an uncertain robot operation, query its original request ID
  ([requests and queries](README.md#new-requests-queries-and-delegation)). Nothing replays a
  physical action.

## Cost and context

Codex runs have no dollar allowance; usage comes from app-server usage updates
([reports](README.md#reports-and-metric-definitions)). The catalog sets `context_window` 300,000
and `auto_compact_token_limit` 267,000, frozen per run; a changed catalog needs a new preflight.
The settings do not enlarge the provider's real context.

## Evidence and reports

`private/outputs/codex-host.jsonl` holds host scheduling, tool and timing events; the native
`<session-id>.jsonl` transcripts are under the home's `sessions/` directory, with verified copies
in `private/engine/transcripts/` ([session transcripts](../running/evidence-storage.md#session-transcripts)).
Observations are JPEG 896 x 560 at quality 85 ([observation images](../protocol.md#observation-images));
motion is sampled at 60 Hz for later [Factory rendering](../factory/replay.md); real-time MP4 is off
by default. Collection copies the relevant transcripts without authentication, configuration or
state databases. Read metrics from stopped evidence in the environment that ran the batch, never
from a live database across a container or shared mount. On Slurm, `sacct -j JOB_ID
--format=JobID,State,Elapsed,AllocCPUS,MaxRSS,TotalCPU` reports allocation resources.
