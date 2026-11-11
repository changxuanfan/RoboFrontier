# Claude Code engine

Every policy role is a native Claude Code session (`claude -p`, continued with `--resume`) with
the robot tool served over MCP by `robofrontier/engines/claude/robot_mcp.py`. All four
topologies run: `single`, `adaptive`, `controller-worker` and `worker-worker` (inside a run named
centralized, adaptive, hierarchical and peer). The pinned CLI is Claude Code 2.1.316
(`robofrontier/runtime/versions.py`); runs turn its self-update off (`DISABLE_AUTOUPDATER`). A run
starts only with passed precheck receipts for its profile and that CLI version
([Preflight and receipts](#preflight-and-receipts)). What both engines share is in the
[engine overview](README.md); the [Codex guide](codex.md) has the same sections.

## Install

Follow [shared setup](README.md#shared-setup), then install the pinned CLI and prepare without
model calls:

```sh
npm install --global @anthropic-ai/claude-code@2.1.316
claude --version
.venv/bin/robofrontier plan --engine claude --level 1 --min-arms --parallel 4
.venv/bin/robofrontier prepare --engine claude --render native \
  --level 1 --min-arms --parallel 4 --output runs/policy/claude-l1
```

Use `--render native` on macOS, `--render nvidia` or `--render cpu` on Linux. Preparation
restores pinned assets when needed, freezes the run and starts no world or model session; it
also freezes the Bash isolation chosen on this host, so prepare on the host that will run the
batch. The Codex CLI is not needed. [`configs/examples/mac.toml`](../../configs/examples/mac.toml)
is a complete Mac example.

## Authentication

Profiles are the `claude` section of `configs/models.json`; the
[authentication matrix](README.md#authentication-matrix) lists each one's credential. Put
credentials in `.env` ([credentials file](README.md#credentials-file)). An API-key profile passes
only its own key and endpoint to the CLI; setting sources and unrelated MCP servers are turned off
on the command line in every mode.

### Subscription token (default)

`haiku_subscription_token` (Haiku 5.5) is the default; `opus_subscription` uses the same mode
with Opus. Generate a one-year token locally with the official command and store it in `.env` as
`CLAUDE_CODE_OAUTH_TOKEN`:

```sh
claude setup-token
```

The token is allowed only at the official Anthropic endpoint. The runner moves it out of the CLI's
environment and passes it on a pipe (`CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`), so a policy
shell cannot read it from a parent environment. On Linux a run refuses to start when the token is
in the starting environment of the runner or any ancestor process (`runner.require_hidden_token`):
unset it in the shell or job and keep it only in `.env`, which runs load themselves. On Slurm the
job reads it from the checkout's `.env` ([Slurm guide](../running/slurm.md)). Local MCP servers
work with this token; Remote Control and claude.ai connectors do not. See
[Anthropic's authentication guide](https://code.claude.com/docs/en/authentication).

### Saved login

`haiku_subscription` and `haiku_subscription_directory` use a native Claude Code login. Name its
configuration directory in `ROBOFRONTIER_CLAUDE_HOME` before preparing:

```sh
export ROBOFRONTIER_CLAUDE_HOME="$HOME/.claude"
claude auth login --claudeai
claude auth status --json
.venv/bin/robofrontier prepare --engine claude --profile haiku_subscription \
  --render native --cases transport-a04-d1 --output runs/policy/haiku-login
```

`haiku_subscription` requires `$HOME/.claude` with `CLAUDE_CONFIG_DIR` unset. Claude Code keeps a
separate credential store whenever `CLAUDE_CONFIG_DIR` is set, even to the same path, so for a
login made with `CLAUDE_CONFIG_DIR` choose `haiku_subscription_directory` and set
`ROBOFRONTIER_CLAUDE_HOME` to that directory. The choice is part of the profile fingerprint;
receipts do not carry over between the two. The directory is frozen in the run, must lie outside
the batch, and is never collected: collection copies only the bound transcripts and their
sidecars. No API key or token variable is passed in this mode.

### Doctor and redaction

`robofrontier doctor --engine claude` checks the installed CLI version and a real render. It
does not check credentials or call a model. The runner redacts exact occurrences of the selected
credential from its event file, summary and stderr tail and writes them owner-only; native
session files are not rewritten, so treat a whole run directory as private.

## Isolation

Permission rules confine the file tools; a second layer confines Bash. Both come from the run's
frozen access table (`robofrontier/runtime/access.py`), which closes the checkout, the home
directory, other runs and shared storage. Preparation freezes the Bash layer as `bash_isolation`
in `private/inputs/claude.json`, chosen by `robofrontier/engines/common/landlock.py` (`choose`):

| Host | `bash_isolation` | Mechanism |
| --- | --- | --- |
| macOS | `claude-sandbox` | Claude Code's sandbox (Seatbelt) |
| Linux where `bwrap` and `socat` exist and bubblewrap can create namespaces | `claude-sandbox` | Claude Code's sandbox (bubblewrap) |
| Other Linux, such as a RunPod pod under Docker's default seccomp profile | `landlock-v1` | Every Bash command runs through `CLAUDE_CODE_SHELL_PREFIX`, which restricts itself with Landlock and seccomp to what the table grants, denies TCP connections and binds, then runs the command with bash |

`landlock-v1` needs Landlock ABI 4 (Linux 6.7) and libseccomp; preparation fails when neither
mode is available. Landlock does not cover UDP, named Unix sockets or, before ABI 6, signals.
Without user namespaces `/dev/shm` stays closed, so Python process pools fail inside the policy
shell; other processes stay visible but their environments cannot be read. Only Bash is
confined: the CLI and the robot MCP are harness processes, and the prefix runs exactly the run's
own robot MCP command lines unconfined. `tests/engines/test_claude_landlock.py` checks the
confinement on a Linux host with Landlock. On RunPod, put the Node.js and CLI folders on `PATH`
([RunPod guide](../running/runpod.md)).

## Preflight and receipts

A run needs two passed receipts for its profile, recorded with the installed CLI version and
model configuration; `robofrontier run` picks the latest of each and refuses on any mismatch
(`engines/claude/claude_readiness.py`). One command makes both, with real spend:

```sh
.venv/bin/robofrontier preflight --engine claude --profile haiku_subscription_token \
  --max-budget-usd 1 --confirm-spend
```

Without `--confirm-spend` it makes no call and reports `not_run`. `--max-budget-usd` is required
and caps each of the two checks by CLI-reported cost, not provider billing.

1. **Basic** (`engines/claude/preflight.py`): on one session, a text reply; a robot `observe`
   call for the `top` view whose returned image color (one of six, chosen at random) the model
   must name; a resumed turn; and a tool-free fork of the idle session that must recall the color
   and have a matching transcript prefix. Receipt:
   `<runs_root>/engineering/claude-precheck/<id>/receipt.json`.
2. **Blocked parent** (`engines/claude/claude_blocked_precheck.py`), run only when the basic one
   passed: initialize a parent, block it at an image tool call, fork while it is blocked, verify
   the history prefix, release the parent and check its image answer. Receipt:
   `<runs_root>/engineering/claude-blocked-precheck/<id>/receipt.json`.

`--smoke-only` runs the basic check without the fork and skips the blocked one; it does not make
a run eligible. A receipt records CLI version, requested and reported model, profile
fingerprint, cost and per-check results, never credentials. Each check can also be run on its own
(`--output DIR` chooses the receipt folder), and two receipts can be compared without model calls:

```sh
.venv/bin/python -m robofrontier.engines.claude.preflight --profile haiku --max-budget-usd 0.5 --check-fork --confirm-spend
.venv/bin/python -m robofrontier.engines.claude.claude_blocked_precheck --profile haiku --max-budget-usd 1 --confirm-spend
.venv/bin/python -m robofrontier.engines.claude.claude_readiness --profile haiku \
  --precheck PATH/receipt.json --blocked-precheck PATH/receipt.json
.venv/bin/python -m robofrontier.engines.claude.claude_offline_probe   # local stubs, no model
```

A receipt for one profile says nothing about another, and a matching receipt does not prove which
model the provider served.

## Run, status and stop

```sh
.venv/bin/robofrontier run runs/policy/claude-l1        # launchd on macOS; --durable on Linux
.venv/bin/robofrontier status runs/policy/claude-l1
.venv/bin/robofrontier stop runs/policy/claude-l1
.venv/bin/robofrontier continue runs/policy/claude-l1   # by hand, as the same trials
```

`run` makes paid calls. It checks the receipts, the frozen configuration and every run's input
inventory, claims each run once, starts an independent physical owner per run and supervises the
role sessions, at most `batch.parallel` runs at a time. The startup timeout is
`batch.startup_timeout_s` (600 s). Ctrl-C or SIGTERM stops the batch like `stop`: queued runs do
not start, active runs stop their model turns and seal. `stop` writes stop markers; check the seal
and status afterwards. SIGKILL or node loss can leave processes behind: inspect before relaunching.

| Status | Meaning |
| --- | --- |
| `stopped_before_start` | Stop arrived before the run launched |
| `stopped` | Stop skipped unstarted runs or sealed active ones |
| `closed` | Every run closed; says nothing about task success |
| `needs_review` | Unresolved execution, sealing or cost evidence; overrides normal closure |
| `claim_without_status_needs_review` | A launch claim exists without a status file |
| `supervisor_lost_needs_review` | The supervisor was lost; claims stay and replay is refused |

A clean closure after `finish` needs a readable private `evaluation.json` with a boolean
`task_success` (`false` is a normal unsuccessful run) and drained native turns. `stop_requested`
and `claim_record_present` are file snapshots; `owner_pid` is not a liveness check. A run that
reaches the 48 h [wall backstop](../running/continuation.md#wall-backstop) is stopped, reported
with `ended_by: wall_backstop` and left `needs_review`; if the world has not ended it 150 s after
the backstop, the supervisor ends it.

## Sessions and delegation

`ClaudeSessionHost` (`session_host.py`) owns one role's native session: a host-generated session
ID, a fixed robot MCP connection, one turn at a time, explicit resume and cancellation. An unknown
turn outcome never starts another turn automatically. `robot public_image` returns only reference
images listed by the public task, including `target.reference_image` for Mosaic.

**Adaptive delegate fork.** The host claims the delegation, binds it to the Controller's one
unanswered `delegate` tool call ([request binding](README.md#new-requests-queries-and-delegation))
and pins the parent history at that call. Each child is then created by its first turn,
`--resume CONTROLLER --fork-session --session-id CHILD`, with the frozen delegate message as the
prompt and the role's ordinary tools; the child UUID is persisted first. Until the batch is
activated a PreToolUse hook (`runner.gate_settings`) holds every tool call on gate files under
`private/claude-forks/`, and the runtime refuses robot operations of an inactive delegate. Setup
verifies that each child's transcript copies the pinned parent history (or its verified compacted
projection) with no later parent row and that its first input is the delegate message; an
unrecognized compaction layout fails. It then binds scope, activates the batch and opens the
gates. The batch's `setup_deadline` (`native_setup_timeout_s`, 120 s) bounds verification; a gate
never opens after it. Any failure closes the remaining gates, stops those children and pauses the
run for review; a failed or uncertain setup is never reforked. The fork turn is the child's first
ordinary turn and is charged like one. Later turns resume the child's own session.
`tests/engines/test_claude_fork_boundary_integration.py` exercises this against the real CLI.

`adaptive_dispatch.py` routes wakes to the bound sessions; a missing role, unknown send or leftover
claim pauses instead of guessing. The Controller reads a returned child's report with `robot work`
and `{"delegate_id":"Delegate_..."}` (`delegate_report`). General `delegate-bind` from outside the
host stays refused.

## Standing teams

`controller-worker` and `worker-worker` give every initial role its own native session with the
same robot MCP, the runtime's mailbox, permissions, action IDs and wake leases. No standing Worker
is an Adaptive fork.

| Mode | Initial sessions | Authority |
| --- | --- | --- |
| `controller-worker` | One Controller plus one Worker per arm | Workers move only their own arms; messages route through the Controller, which may propose team finish |
| `worker-worker` | One Worker per arm | Workers move their own arms, message each other and may propose team finish |

The runtime enforces the routes and robot authority. The lead's role kind is `team-controller`.
The host binds every initial session, then the owner persists one START (`direct_team_v3`) and
each role receives its started prompt. A Worker's ended turn is an idle session; messages, review
deadlines and saved work wake it again.

`batch.parallel` counts runs, not CLI processes: a standing run has N or N+1 sessions for N arms.
The four smallest level-1 cases (4, 4, 8 and 4 arms) together mean 20 Workers, or 24 roles with
Controllers. Raise concurrency only after checking memory and provider limits. A lost bind
acknowledgement blocks bootstrap; a lost wake acknowledgement marks the wake uncertain and pauses
dispatch without resending. Stop cancels every role's turn, then seals.

```sh
.venv/bin/robofrontier prepare --engine claude --topology controller-worker --render native \
  --level 1 --min-arms --parallel 2 --output runs/policy/claude-standing-l1
```

## Recovery

- **Capacity errors**: bounded same-session resume ([capacity recovery](README.md#capacity-recovery)).
- **Network outage**: in a run whose clock is `active_time_v1`, a turn that failed within a
  network-outage or Slurm egress pause (30 s either side) with an `api_error` of
  `connection_failed`, `no_response`, `stream_idle_timeout` or `computer_slept` and no HTTP
  status, or with no stated cause, is resent once per role and pause with `--resume` and the
  frozen `network-resume.md`, after the role's robot work settles and the runtime grants the
  claim (`runtime_cli network-recovery`). A second failure in the same pause, or another failure
  type within it, holds the run for review (`NETWORK_CONTINUATION_UNCERTAIN`).
- **Unexpected stop**: the run continues by itself once
  ([continuation](../running/continuation.md#when-a-run-continues),
  [Claude task recovery](../running/continuation.md#claude-task-recovery)).
- Ordinary nonzero exits, unknown actions, uncertain fork creation and unknown identity need
  review. Nothing replays a physical action.

## Cost and context

`robofrontier run` sets no dollar allowance. Reported cost is kept per turn; missing cost is
recorded as unreported, not zero. The allowances exist as the `turn_budget_usd` and
`total_budget_usd` arguments of `robofrontier.engines.claude.run.run_task`. With them, every turn
reserves before launch against one task ledger shared by all roles; a multi-role topology with a
task allowance needs a per-turn allowance, and the most roles that can hold a reservation at once
times it must fit the task allowance, or the launch is refused. Unknown, invalid or overspent
cost, or an unresolved reservation, blocks further turns. These are CLI-reported estimates, not
billing caps.

Claude Code 2.1.316 keeps a session-wide cost counter in the transcript that resume and fork
inherit. The runner subtracts the verified previous counter to get each invocation's own cost;
without a verified previous counter it keeps the whole counter as an upper bound, and a counter
that decreases makes cost unknown.

Compaction: the runner sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to the frozen
`auto_compact_token_limit` plus Claude Code's 33,000-token summary buffer, so it compacts at the
same 267,000 tokens as Codex.

## Evidence and reports

Stopped collection copies every role-bound transcript and its tool-result and sidecar files,
motion, action, message and wake records and reports; roles come from runtime metadata, so peer
mode needs no Controller. Real-time MP4 is off by default (`render.record_realtime_video`); with
it on, FFmpeg and ffprobe are required and sealing checks the stream. See
[evidence storage](../running/evidence-storage.md) and
[reports](README.md#reports-and-metric-definitions). A reported model name is an observation:
`all_requested_models_verified` stays false. A prepared run freezes its source beside its inputs;
prepare again after source changes.
