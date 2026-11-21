# Codex harness

In the Codex harness every role is a thread of the Codex *app-server*, the mode of the Codex
CLI that other programs drive over JSON-RPC (`thread/start`, `turn/start`, `thread/fork`). The
robot tool is a tool the app-server adds to each thread. All four systems run: `adaptive` (the
default), `single-agent`, `hierarchical` and `decentralized`. The pinned CLI is Codex 0.165.0
(`roboteam/runtime/run/versions.py`). A run starts only with a passed preflight receipt for its
model, model catalog and CLI version ([preflight and receipts](#preflight-and-receipts)). What
both harnesses share is in the [harness overview](README.md); the
[Claude Code guide](claude-code.md) has the same sections.

The code is in `roboteam/harness/codex/`: `launch.py` builds the app-server configuration and
the Codex home (the folder where Codex keeps its sessions and login),
`roboteam/launch/codex_batch.py` prepares and supervises batches, and the Node.js files under
`host/` (`policy_host.js`, `rpc.js`, `preflight.js`, `initialize.js`) drive the app-server.

## Install

Follow [shared setup](README.md#shared-setup), then install the pinned CLI and prepare without
model calls:

```sh
npm install --global @openai/codex@0.165.0      # or: npm install --prefix "$PWD/.harness-cli" @openai/codex@0.165.0
codex --version
.venv/bin/roboteam plan --level 1 --min-arms --parallel 4
.venv/bin/roboteam prepare --level 1 --min-arms --parallel 4 --output runs/batches/codex-l1
```

With a prefix install, put `$PWD/.harness-cli/node_modules/.bin` first on `PATH`; Slurm
subscription jobs and their preflight refuse to start with another `codex` first on `PATH`.
`--render` may be left out: the default picks `native` on macOS, `nvidia` on Linux with an
NVIDIA GPU and `cpu` otherwise. CPU rendering needs Mesa OSMesa (`libosmesa6` on Debian and Ubuntu
systems) and is not available on macOS. Physics always runs on the CPU. Preparation restores
pinned assets when needed, freezes the run and starts no world or model session. The Claude CLI
is not needed.

## Authentication

Models are the `codex` section of `models.json`; the
[authentication matrix](README.md#authentication-matrix) lists each one's credential. Model and
provider settings are process-local and never change the user's global Codex configuration.

**API models** (`sol`, the default; `luna`; third-party) read their key from `.env`. With the default
`runtime.codex_home_scope = "task"` each run gets its own Codex home under `.roboteam/codex/`
(or under `runtime.codex_home`), shared by that run's Controller, snapshots and delegates so fork
lineage stays readable. Homes are initialized one at a time before any task host starts.

**Claude through a local adapter** (`opus_claude_api`) is experimental: Codex talks to a local
process that holds the Anthropic key and translates between the two APIs. See
[Claude in Codex](claude-in-codex.md) before using it.

**ChatGPT login** (`sol_subscription`, `luna_subscription`, `terra_subscription`, `astra_subscription`)
uses Codex's own login and needs `runtime.codex_home_scope = "shared"` (task scope refuses these
models). The shared home is `runtime.codex_home`, else `CODEX_HOME`, else
`~/.roboteam/codex-home`, never the personal `~/.codex`. Log in there once; a batch refuses
to start without the login:

```sh
CODEX_HOME=~/.roboteam/codex-home codex login
CODEX_HOME=~/.roboteam/codex-home codex login status
```

```toml
# Untracked site TOML for a subscription batch
[policy]
model = "sol_subscription"

[runtime]
codex_home_scope = "shared"
```

On Slurm, subscription runs use `codex_home_scope = "job"` with `slurm.auth_mode =
"subscription"` and a private `slurm.credential_store`
([Slurm credential store](../hosts/slurm.md#codex-credential-store),
[`docs/hosts/examples/slurm.toml`](../hosts/examples/slurm.toml)).

Every home must lie outside the batch; the access table closes it to the agents. Preparation
adds command-line overrides that switch off every MCP server found in the user's and the
project's Codex configuration, and the host and preflight check that none is enabled before the
first model call. The user's files are not rewritten. A home's location is recorded in each
run's `private/harness/codex-home.json`.

`roboteam doctor` checks the installed CLI version, the sandbox or tool backend and a real
render. It does not check credentials or call a model.

## Isolation

Each run freezes an access table (`roboteam/runtime/sandbox/access.py`): the list of folders the
agents' tools may read or write. It closes the checkout, the home folder, other runs and shared
storage. `runtime.codex_tool_backend` selects how the model's shell, patch and image tools are
kept inside it. The default `auto` picks by host:

| Host | Tool backend | Mechanism |
| --- | --- | --- |
| macOS; any host with `tools = "robot_only"` | `native` | Codex's own sandbox with a named permission profile. `doctor` runs `codex sandbox` to check it |
| Linux, including Slurm and Docker | `landlock-v1` | Codex's shell, patch and image tools are replaced by the tools `policy_exec` and `policy_image`. Each call runs as a new subprocess that restricts itself to the access table with Landlock and seccomp |

Under `landlock-v1` the subprocess gets no host credentials and no inherited file descriptors.
`/proc` is closed; sockets, io_uring, reading another process's memory, signals to other
processes and namespace operations are refused; capabilities are dropped. `/tmp` stays open and
each command gets its own empty `/dev/shm`. Where the host forbids user namespaces, `/dev/shm`
stays closed, so Python process pools fail there; other processes stay visible, but their
environments cannot be read. The Codex process itself, which the benchmark trusts, keeps the
login, the sessions and the connection to the robot tool. Subscription runs under this backend
reach OpenAI over HTTP with server-sent events instead of WebSockets.
[`docs/hosts/examples/linux.toml`](../hosts/examples/linux.toml) is a complete Linux example
([Linux guide](../hosts/linux.md)).

A receipt records the tool backend; changing the backend needs a new preflight and newly
prepared batches. This check of the installed CLI, with no model call, inspects the tool list
the model would get, rejects forged calls to Codex's own tools and runs fork and resume with
eight roles at once:

```sh
.venv/bin/python -m roboteam.harness.codex.checks.broker --output runs/checks/broker-check
```

## Preflight and receipts

```sh
.venv/bin/roboteam preflight --confirm-spend               # full check, real spend
.venv/bin/roboteam preflight --confirm-spend --smoke-only  # image/tool round trip only
```

Without `--confirm-spend` it makes no call and reports `not_run`. Pass the same `--config` and
options as for `prepare`. The full check runs image and tool round trips, a manual compaction, and
a fork whose child inherits history and then uses tools. Receipts:
`<runs root>/receipts/codex/compatibility/<model>/report.json` (full) and
`<runs root>/receipts/codex/smoke/<model>/report.json` (smoke). A robot-only or ground-truth
batch has its own receipt, in `<model>.robot_only/` or `<model>.ground_truth/`. Before each run, the batch
checks the full receipt against the frozen model, provider address, context, effort, catalog
hash, CLI version and tool backend, and refuses on any mismatch; a smoke receipt never qualifies a
run. Local checks of the real CLI against a synthetic Responses service, with no billing:

```sh
.venv/bin/python -m roboteam.harness.codex.checks.cli --output runs/checks/cli-check
.venv/bin/python -m roboteam.harness.codex.checks.snapshot
```

## Run, status and stop

```sh
.venv/bin/roboteam run runs/batches/codex-l1        # launchd on macOS; --durable on Linux
.venv/bin/roboteam status runs/batches/codex-l1
.venv/bin/roboteam stop runs/batches/codex-l1
.venv/bin/roboteam continue runs/batches/codex-l1   # by hand, as the same trials
```

`run` makes paid calls. It checks the receipt, the frozen configuration and every run's input
inventory, validates each home's startup configuration without inference, then starts at most
`batch.parallel` runs, 0.3 s apart. The world owner enforces the cutoff: it refuses new
actions, brakes the arms, scores the task and closes. An ended world never restarts. Each run's status is
`stopped_before_start`, `closed` (host exited cleanly; says nothing about task success) or
`needs_review` (any other exit, a stop between segments, or the 48 h
[wall backstop](../runs/time.md#wall-backstop), whose result is not counted). On Slurm, use
`roboteam slurm-submit` ([Slurm](../hosts/slurm.md)).

## Sessions and delegation

The host records each role's thread ID and checks every fork by parent ID, position and history
hashes. Initial sessions start empty. For an `adaptive` delegation the host first forks a
*snapshot* thread of the Controller without running a turn and records its ID. It then forks
each delegate from that snapshot and sends the delegate message once the runtime has activated
the delegation. Each delegate
gets its model and effort explicitly on its first turn. Unknown creation, fork or send
acknowledgements keep their evidence and stop automatic replay.

Do not start a turn by hand in a live run's thread.

### Codex Desktop threads (optional)

Batches do not need this. A thread that the Codex Desktop app creates cannot receive the
app-server's `robot` tool. `roboteam/harness/codex/desktop_robot_mcp.py` is an MCP server that
gives such a thread the same robot tool: it reads the calling thread from each tool call and
uses the connection of the role that this thread is bound to in a run's database. A thread that
is bound to no role gets nothing. Print the entry for the Desktop app's `config.toml` and add
it once:

```sh
.venv/bin/python -m roboteam.harness.codex.desktop_robot_mcp --print-config
```

Add `--runs-root DIR` when runs are not under the default runs root. The entry sets
`default_tools_approval_mode = "approve"`, because a tool call would otherwise wait for a
person.

## Standing teams

`hierarchical` and `decentralized` start one thread per initial role, with the same roles,
message routes, single START and message delivery as
[Claude Code standing teams](claude-code.md#standing-teams). Delegates and standing Workers add
model requests inside each run; `batch.parallel` counts runs.

## Recovery

- **Capacity errors**: bounded same-session resume ([capacity recovery](README.md#capacity-recovery)).
  Authentication errors, quota exhaustion and ordinary task errors are not retried as capacity
  errors.
- **Network outage**: as on Claude Code, a turn that failed within 30 s of a
  [network-outage pause](../runs/time.md#network-outage-pause) is continued once per role and
  pause with the frozen `network-resume.md` message, once the role has no robot action in
  flight. A network or unclassified failure is continued; any other
  failure in that window, or a second one, holds the run for review.
- **Unexpected stop**: the run continues by itself once
  ([continuation](../runs/continuation.md#when-a-run-continues),
  [Codex task recovery](../runs/recovery.md#codex-task-recovery)). A Slurm `job`-scope
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

`private/logs/host.jsonl` holds host scheduling, tool and timing events; the native
`<session-id>.jsonl` transcripts are under the home's `sessions/` directory, with verified
copies in `private/harness/transcripts/` ([session
transcripts](../runs/evidence-storage.md#session-transcripts)). Observations are JPEG 1280 × 800
at quality 90 ([observation images](../benchmark/rules.md#observation-images)). Motion is
recorded 30 times per simulated second. Video recording is off by default. Collection copies the
relevant transcripts without authentication, configuration or state databases. Read metrics from
stopped evidence in the environment that ran the batch, never from a live database across a
container or shared mount.
