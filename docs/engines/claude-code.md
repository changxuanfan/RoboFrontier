# Native Claude Code engine

The unified integration retains the native Claude CLI/MCP implementation beside
Codex. It does **not** admit scored Claude tasks. Current four-topology
engineering entries can start real simulation and potentially billable inference
only when explicitly invoked. Provider profiles are candidates, not compatibility
certificates. Native permanent Worker engineering is documented in
[standing teams](#standing-teams); full scored qualification remains a gate. See
the [engine overview](README.md) for the component map, shared request IDs,
recovery and reporting, [providers](providers.md) for the authentication matrix,
and [the current acceptance ledger](../archive/unified-main.md).

## Current startup, time and finish contract

New Single/Adaptive policy inputs use direct Controller START. Once the world is
ready and the Controller's native session is bound, the host persists START and
sends an explicit started prompt. Initial task reading, observation and planning
count toward the task clock. `ready` is an optional capability query; it is not
a readiness barrier. Standing Controller + Worker and Worker-Worker runs bind
all initial roles before one `direct_team_v3` START, then send each an explicit
started task prompt (see [initial roles and START](#initial-roles-and-start)).
Frozen `ready_barrier_v1` runs keep their historical READY/idle startup and must
not be reinterpreted as direct-start experiments.

The default task limit is 86,400 seconds from persisted START. A separately
selected engineering stop does not rewrite that public limit. Normal policy
turns have no separate default timeout; startup, RPC, tool waits and delegate
fork setup still have their own bounds. Host creation time is not a second
24-hour experiment clock. `run-engineering --startup-timeout-s` defaults to
120 seconds; the unified TOML startup default is 600 seconds. Record the entry
and its frozen settings rather than treating these as one parameter.

The shared [policy rules](../../prompts/rules.md) require continued work and
recovery while unfinished. Use `finish` after public evidence supports completion,
or explain publicly supported unrecoverability. The runtime independently checks
actions and delegation closure, and the private scorer evaluates the terminal
world. Accepted finish does not imply success. Ending a CLI turn or returning a
child does not itself finish the task. Dial retains unlock-once completion.

Realtime MP4 is off by default. Observations and motion are still recorded.
Legacy `prepare-draft --record-video` enables MP4 and requires FFmpeg/ffprobe;
engineering sealing checks the stream and decodes its first frame. This is not
full-file decode qualification. Requested video that cannot be verified requires
review; expected absence when disabled is not a task failure.

## Installation

Use the checked-out integration's [README](../../README.md),
[unified CLI guide](../unified-cli.md) and [shared setup](README.md#shared-setup).
The earlier public `codex/claude-code-harness` branch is a historical source;
cloning it does not acquire all newer unified features automatically.

Install Python 3.12, uv and the native Claude CLI on macOS/Linux, using the
Claude Code version pinned in [`docker/Dockerfile`](../../docker/Dockerfile).
Requalify changed versions. A native Claude-only path does not require the Codex
CLI.

```sh
uv sync --locked --extra oracle
claude --version
.venv/bin/robofrontier bootstrap
.venv/bin/robofrontier plan --engine claude --profile haiku --level 1 --min-arms --parallel 4
.venv/bin/robofrontier prepare --engine claude --profile haiku --level 1 --min-arms --parallel 4 --render native --output runs/engineering/claude-current-l1
```

The renderer example is for macOS. On Linux select `--render nvidia` or
`--render cpu`. Preparation restores pinned assets automatically, creates no
world or model session and does not authorize inference. Offline asset
installation is `python -m robofrontier.batch.handoff setup-assets --archive
/path/to/archive` (see [policy assets](README.md#policy-assets)).

## Authentication

The model catalog is `configs/claude-models.json`; every profile and its
credential is listed in the [authentication matrix](providers.md#authentication-matrix).
Create the ignored `.env` without replacing an existing file
([credentials file](README.md#credentials-file)), then edit it locally.

`haiku` and `opus` use `ANTHROPIC_API_KEY`. Other API profiles use their
catalog's credential variable; Qwen additionally uses
`DASHSCOPE_ANTHROPIC_BASE_URL` matching the actual account/region (see
[Claude-compatible endpoints](providers.md#claude-compatible-endpoints)).
Existing process environment values take precedence. Keep keys out of chat,
TOML and Git. API profiles pass only their selected credential/endpoint into the
native CLI; `--bare` avoids reading native OAuth.

### Default subscription token

An engine-only Claude selection defaults to `haiku_subscription_token`: Haiku
5.5 authenticated by the official `claude setup-token` flow. Run the official
command locally:

```sh
claude setup-token
```

Store the returned value as `CLAUDE_CODE_OAUTH_TOKEN` in the ignored local `.env`,
then restrict that file to its owner with `chmod 600 .env`. The script loader
reads literal environment assignments; an already-set process variable takes
precedence. Keep the value out of shell history, source files and evidence.
The official command generates a one-year subscription token. Configured local
MCP servers work with it; Remote Control and claude.ai connectors are unavailable.
See [Anthropic's token instructions](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token).

```sh
robofrontier plan --engine claude
robofrontier prepare --engine claude --render native \
  --cases transport-a04-d1 --output runs/engineering/haiku-token-example
```

The engine-only default applies when neither the user TOML nor the explicit
options select a profile. The legacy Claude planning/preparation script also
defaults to `haiku_subscription_token` when `--models` is omitted. Explicit
`haiku`, `haiku_subscription`, `haiku_subscription_directory`, and
`opus_subscription` selections remain available. Existing frozen runs retain
their selected profile. The repository's overall Codex default is unchanged.

This token is a distinct authentication mode. It does not depend on the
saved-login refresh experiment, and its receipt cannot certify that experiment.
Formal Claude scoring remains closed. Cluster functionality remains available;
cluster execution and full-video rerender are deferred.

### Native saved login

`haiku_subscription` retains native Claude Code saved login. Choose the native
configuration directory explicitly before preparation:

```sh
export ROBOFRONTIER_CLAUDE_HOME="$HOME/.claude"
claude auth login --claudeai
claude auth status --json
robofrontier prepare --engine claude --profile haiku_subscription \
  --topology adaptive --render native --cases transport-a04-d1 \
  --output runs/engineering/haiku-subscription-example
```

`haiku_subscription` uses the default native login namespace. It requires the
selected directory to equal HOME/.claude and leaves CLAUDE_CONFIG_DIR unset.
Claude Code 2.1.312 selects a distinct credential namespace when that variable is
explicitly set, even to the same path. For an account authenticated with an
explicit CLAUDE_CONFIG_DIR, choose `haiku_subscription_directory` and the same
directory used during its native login. The selection is part of the profile
fingerprint; receipts cannot be reused between these namespaces.

The selected absolute directory is frozen in the private launch profile. Keep
the authentication home outside the evidence batch. Preparation, batch admission
and collection reject an authentication home inside that batch. Each role still
uses a host-generated explicit native session ID and its bound robot MCP.
Settings sources and unrelated MCP servers are disabled by command-line options.
Provider API keys and token environment variables are not inherited in this mode.
The unmodified native CLI owns authentication and credential persistence.

Evidence collection copies only the bound native transcripts and their session
sidecars. It excludes the credential/configuration store and unrelated sessions.
A collection marker lets restored provenance use the collected histories on a
machine without the original account. Launching another native turn still
requires the explicitly selected live authentication home.

### Older OAuth token mode

`opus_subscription` retains its older explicit `CLAUDE_CODE_OAUTH_TOKEN` mode for
existing configurations. It disables project/user setting sources and automatic
MCP discovery/tool search, and permits that token only at the official Anthropic
endpoint. It does not copy Claude Desktop login. Native managed login does not
require exporting that token. Its real subscription behavior, credits/cost
reporting and refresh are not qualified; fresh login and a successful
cached-login call do not by themselves verify automatic refresh after token
expiry. The native loopback tests used a synthetic token. Follow the current
[Anthropic authentication documentation](https://code.claude.com/docs/en/authentication)
for account setup; do not share a generated token in chat or Git.

### Doctor and credential hygiene

The engine-specific doctor only checks local CLI/assets, credential presence and
FFmpeg/ffprobe availability. It reports whether credentials are present, not
whether they work. It does not validate authentication, an encoder, model
responses or a complete video. The unified doctor additionally checks a real
renderer; neither calls a provider. A missing local permission should be
resolved in the intended environment rather than bypassed: if a sandbox denies
the provider host or writes under `runs/`, allow it in your own environment
rather than bypassing the sandbox.

The runner redacts exact occurrences of the selected credential (including
JSON-escaped forms) from its event file, summary and stderr tail, and writes
event files with owner-only permissions. This does not sanitize Claude's native
session files or detect transformed/partial secrets; treat the entire run
directory as private and inspect it before sharing.

## Cost allowances and the shared ledger

`--turn-budget-usd` and `--task-budget-usd` are optional and unset by default;
new default engineering runs have no dollar ceiling. Without a turn allowance,
`--max-budget-usd` is not injected into the Claude CLI. Reported cost is still
retained. The run-local budget ledger is shared by the Adaptive Controller
and its children; a child's fork is its first turn. Missing cost without a ceiling is recorded as
unreported rather than zero, and does not alone block a confirmed normal turn.
Unknown execution, uncertain cancellation or failed fork provenance still needs
review regardless of whether a budget exists.

With explicit allowances, the host reserves before launch; reservations and
remaining estimated task funds bound new turns. A task-only allowance would
reserve the entire remainder for one turn and deny every other role, so an
adaptive, hierarchical or peer launch with a task budget needs a per-turn
allowance, and the most roles that can hold a reservation at once (adaptive:
the Controller plus one delegate per arm) times that allowance must fit the
task budget; otherwise the launch is refused before any claim. A wake refused
because the task budget is spent is recorded as not sent and pauses the run
for its budget. Unknown/invalid/overspent cost or unresolved reservations
under an allowance block further allocation. Reservations from uncertain or lost
processes are not automatically released. These are CLI-reported estimates,
not hard provider billing caps, subscription credits or one shared batch budget.

### Native cumulative cost accounting

Claude Code 2.1.312 persists a session-wide cost-state counter in its transcript.
Resuming or forking a session inherits that counter. The runner retains the raw
native total and subtracts only a verified prior native counter to report new
invocation work. The CLI budget remains the unchanged per-invocation allowance;
its semantics differ from the cumulative result counter. Task-wide reservations
cover only new work; inherited history is not charged again. Raw event bytes
remain unchanged.

Missing historical cost bookkeeping permits no deduction: the complete native
counter is kept as a conservative upper bound. Unknown native model cost blocks
another invocation; a counter decrease or inconsistent final native state makes
cost unknown. Neither an old stopped world's budget nor its outcome is repaired.
Native modelUsage metadata remains unmodified and may contain cumulative usage;
it is not an independent invoice or another amount to add to invocation cost.

The genuine bounded engineering trial exposed both cumulative-cost duplication
and confusion about the native CLI ceiling. It completed eight physical actions
and was stopped and sealed before repair. The counter regression uses the actual
native CLI against a synthetic local provider: the sum of fresh text, image,
resume and fork work must equal the final child's inherited cumulative counter.
No genuine provider or credential is used by that regression.

A second native CLI control verifies the budget independently: two fresh/resumed
synthetic requests each fit the same invocation allowance while their reported
cumulative total exceeds it. The first cost fix incorrectly added historical
cost to the native ceiling. A genuine trial exposed that error and exceeded its
US$0.50 sub-allocation, reporting US$0.67155931 before being stopped and sealed.
The corrected budget reconciliation retains uncertain allowances and uses
verified final native counters only for fully closed, known-cost sessions. It
does not rewrite an old task ledger or turn a failed trial into a passing one.

### Verify the imported checkout before paid launches

Engineering launchers that share a virtual environment must verify the imported
checkout before starting a paid process. An external-file invocation resolved
the editable package from the older integration checkout despite a different
working directory. That attempted finish-fix receipt is not source-qualified;
future qualification entrypoints check the actual module root, tracked source
cleanliness and commit, and use an explicit checkout PYTHONPATH.

## Native sessions, tools and internal delegation

`ClaudeSessionHost` owns one role's unique native session, fixed MCP connection,
turn exclusion, explicit resume, evidence and cancellation. Unknown turn outcomes
never automatically start another turn. A host's lifecycle result is not a task
score. Public bootstrap text is packaged from allowlisted frozen inputs because
policy file-reading tools are disabled.

`robofrontier.engines.claude.robot_mcp` is an experimental role-bound MCP server. Its
offline probe checks Claude CLI tool discovery, simulated tool-image forwarding and
fork history against local stub servers. It does not validate real provider image
handling, trusted session provenance, dynamic delegation or production physical
runs. Do not launch it against an actual scored world.

`robot public_image` returns only reference paths explicitly listed by the
current public task, within its public input directory. It also accepts the
listed `target.reference_image`, used for the Mosaic target. Historical public
reference inputs remain PNG and retain their signed bytes; runtime camera
observations use their separately frozen image profile. This distinction does
not authorize rewriting source textures or old reference hashes.

The 2026-10-28 offline Level 1 preparation covered twelve drafts. Three Mosaic
scales each exposed a target image; three Dial scales each exposed three reference
images. A real CLI/local synthetic model check confirmed exact image bytes for
the smallest Mosaic and Dial cases through MCP. It did not test real model
understanding. Opt-in recheck:

```sh
ROBOFRONTIER_MOSAIC_IMAGE=1 .venv/bin/python -m unittest discover -s tests -p 'test_claude_mosaic_image_integration.py' -v
```

### Bash isolation

Permission rules confine the file tools; a separate layer confines Bash. Both come
from the run's frozen access table (`robofrontier/runtime/access.py`). Preparation
freezes the Bash layer in `private/inputs/claude.json` as `bash_isolation`, chosen
on the host that will run it (`landlock_shell.choose`):

- `claude-sandbox`: Claude Code's own sandbox, Seatbelt on macOS and bubblewrap on
  Linux. Runs prepared before this field use it.
- `landlock-v1`: for a Linux host where bubblewrap cannot create namespaces, such
  as a container under Docker's default seccomp profile (RunPod pods). Claude
  Code's sandbox is turned off and every Bash command runs through
  `CLAUDE_CODE_SHELL_PREFIX`, which restricts itself with Landlock to what the
  table grants and denies all TCP connections and binds, then runs the command
  with bash. It needs Landlock ABI 4 (Linux 6.7) and refuses to run a command
  without it. Landlock does not cover UDP, named Unix sockets or, before ABI 6,
  signals.

Preparation fails when neither is available. As with Claude Code's sandbox, only
Bash is confined; the CLI and the robot MCP are harness processes. Claude Code
also starts each stdio MCP server through the prefix, as one shell-quoted string;
the prefix runs exactly the run's own robot MCP strings unconfined and confines
everything else. A Bash command never matches one, because Claude Code wraps it
in its shell snapshot and an eval.
`tests/engines/test_claude_landlock.py` checks the actual confinement on a Linux host
with Landlock and is skipped elsewhere.

### Trusted internal Adaptive fork

General Claude `delegate-bind` remains closed. Transcript-prefix equality by
itself cannot show that a trusted host created a child at the intended time or
bound the correct MCP authority. The internal Adaptive engineering path claims
a delegation, checks the parent's outstanding native tool call and binds the
delegation to that unique unmatched call
([request binding](README.md#new-requests-queries-and-delegation)). It pins the
parent's history at that pending call, then forks each child from the blocked
Controller exactly as the Codex route does: the child's history ends at the
delegate call and its first input is the frozen delegate message.

Claude Code creates a fork only by running its first turn, so the fork is the
child's first turn: `--resume CONTROLLER --fork-session --session-id CHILD` with
the delegate message as its prompt and the role's ordinary tools and robot MCP.
The child UUID is persisted before that turn. Until the batch is activated, a
PreToolUse hook (`runner.gate_settings`) holds every tool call, robot or file,
on gate files under `private/claude-forks/`; the runtime also refuses robot
operations of a delegate that is not active. Setup verifies that the child's
transcript copies the pinned parent history, or its verified compacted projection,
with no later parent row, and that its first input is the delegate message. For a
compacted projection, the latest boundary's preserved-message metadata determines
the exact retained segment and the two reparented edges; the summary and message
contents are still checked. Per-session cwd, slug, branch, and preserved assistant
usage metadata are excluded from that comparison. Unrecognized compaction layouts
fail closed. Setup then binds scope, activates
the batch and opens each gate. A failure closes the gates of children not yet
released, stops them and pauses the run for review; no tool of theirs runs.

The fork turn is the child's first ordinary turn: it is charged to the shared
ledger under the child's turn allowance, and no separate setup turn or setup
allowance exists. The batch's `setup_deadline` (`native_setup_timeout_s`)
bounds verification and the gate; a gate never opens after it. Native
transcript writes can lag; the bounded match wait pauses on timeout/ambiguity.
Unknown, failed or uncertain setup keeps its record and is never automatically
reforked. Role hosts, original transcripts and referenced parent `tool-results`
must stay available during the run.

`fork_setup.py` supplies the creation boundary and `adaptive_setup.py` connects
claiming, forking, provenance, scope binding, activation and the gates.
`ClaudeSessionHost.fork_delegate` creates the role's MCP configuration for a
delegate that is still being created; later turns resume the child's own
session without fork or gate. Host-side evidence does not protect against
another process with the same OS account tampering with files. Runs prepared
before fork-at-call setup keep their tool-free snapshot/fork records; only their
metrics are read now.

The native blocked-parent loopback test
(`tests/engines/test_claude_fork_boundary_integration.py`) forks a child while the parent
waits on MCP: the model receives the parent's history up to the pending call,
the CLI's own error result for that unanswered call, then the delegate message;
the child's robot call waits until its gate opens, and a closed gate refuses it
without reaching the world. This proves a finite native CLI boundary, not
production security, full task qualification or arbitrary provider
compatibility.

`adaptive_dispatch.py` routes deterministic wakes to the bound parent/child
sessions. A missing role, unknown state/send, leftover creation claim or failed
setup pauses instead of guessing. Setup runs in a separate thread; stop cancels
it and prevents new role starts. Accepted requests settle before eligible
capacity recovery; uncertain actions and uncertain fork creation remain blocked.
See [recovery rules](README.md#capacity-and-rate-limit-recovery).

A returned child's authorized report is available to the Controller via
`robot work` with `{"delegate_id":"Delegate_..."}` in `delegate_report`.
The report is model-authored public evidence, not private evaluation. Missing
return, mismatched references or an oversized report does not expose a body.

## Verified native CLI observations, 2026-10-28

The following local observations used Claude CLI 2.1.312. They are reproducibility
facts for that version, not claims about every future CLI release.

1. `--resume P --fork-session` produced a child transcript containing the parent
   message prefix in the same order with the same UUID/content. `sessionId` and
   `promptId` differed; there was no explicit `forkedFrom` field. This is history
   matching, not independent identity or authority proof.
2. Adding `--session-id C` returned the specified child UUID, permitting the host
   to persist the intended child identity before launch.
3. Fork creation requires a CLI turn. Codex can `thread/fork` before binding,
   activation and a first prompt; Claude cannot verify a nonexistent child
   transcript before its creation turn. With CLI 2.1.316 the child transcript
   is written as that turn starts, before the model replies (the model request
   itself can precede the end of the write). A fork taken at a pending tool call
   adds two rows after the parent's: an error result for the unanswered call and
   a short assistant reply, then the turn's prompt. The adaptive path therefore
   makes the delegate message the fork's prompt and holds the child's tools
   behind a PreToolUse hook passed in `--settings` until activation (`--bare`
   skips hooks, so a gated turn uses `--setting-sources ''`).
4. Child history can reference images in the parent's `tool-results/` directory.
   Preserve that directory during execution and include required references in
   collection; deleting it can break inherited visual history.
5. `MCP_TOOL_TIMEOUT` is in milliseconds. A two-second limit rejected a six-second
   sleep; a twenty-second limit allowed a four-second call. `wait_events` can wait
   600 seconds, so the host sets 660,000 ms for transport allowance. The native
   CLI's default timeout was not measured by those tests.
6. With `--bare`, `--tools ''` and `--strict-mcp-config`, the loopback service
   observed only the requested model and the configured robot tool. That finite
   observation does not prove all possible network behavior or provider identity.
7. Without explicit stdin redirection, `claude -p` waited three seconds and
   warned. `run_turn` now passes `stdin=DEVNULL`.

## Standing teams

Claude engineering execution supports all four shared collaboration modes.
`single` and `adaptive` retain their existing hosts. `controller-worker` and
`worker-worker` use native independent Claude sessions, the same role-bound robot
MCP, and the existing runtime's durable mailbox, permissions, action IDs, wake
leases and private evaluator. No Codex session interface is fabricated and no
standing Worker is represented as an Adaptive fork.

These are **engineering entries**, not qualified scored Claude benchmarks. A
configured provider/profile and a local synthetic test do not prove a real
provider's capability, throughput, billing or task success. See the
[acceptance ledger](../archive/unified-main.md) for current evidence.

### Select and prepare

Choose topology and model through the ordinary TOML or CLI. For example, prepare
the four minimum-arm Level 1 tasks without model calls:

```sh
.venv/bin/robofrontier plan --engine claude --profile haiku \
  --topology controller-worker --level 1 --min-arms --parallel 2
.venv/bin/robofrontier prepare --engine claude --profile haiku --render native \
  --topology controller-worker --level 1 --min-arms --parallel 2 \
  --output runs/engineering/claude-standing-l1
```

Use `--render nvidia` on Linux NVIDIA or explicit `--render cpu` for Linux
software rendering. A preparation freezes the chosen mode, provider profile,
shared task inputs, public Claude role prompts and source hashes. Changing TOML
after preparation does not change this batch. Use a new output path to change
settings. Pinned policy assets are installed automatically when needed.

When authorized to spend against the selected credentials, execute:

```sh
.venv/bin/robofrontier run runs/engineering/claude-standing-l1 --engineering
```

Substitute `worker-worker` to prepare peer Workers. The underlying native
`claude_benchmark prepare-draft --topology` spellings remain `hierarchical` and
`peer`; the unified names describe the same roles. Native `run-engineering` also
supports those drafts. Neither entry admits formal scored execution. Provider
preflight remains a separate explicit operation; it is never a side effect of
planning or preparation.

### Initial roles and START

| Mode | Initial native sessions | Robot and finish authority |
| --- | --- | --- |
| Controller + Worker | One Controller plus one Worker per arm | Workers control only their own arms; Controller coordinates and may propose team finish |
| Worker-Worker | One Worker per arm, with no Controller session | Workers control their own arms, communicate directly and may propose team finish |

Controller + Worker routes business messages through Controller. Worker-to-Worker
business messages are rejected in that mode. Worker-Worker allows authorized
peer messages. The runtime, rather than prompt wording alone, enforces these
routes and robot authority. The lead's role kind is `team-controller` and its
actor name is Controller. Runs prepared before the rename record the kind as
`coordinator`; the runtime reads it as `team-controller`.

The host creates all initial native session IDs, binds each role once, and asks
the existing physical owner to START only after every binding is confirmed.
IDs must be distinct. START persists the task's start time; each role then
receives its own public task/skill/role prompt with an explicit started statement.
Reading, model startup turns, observation, planning and subsequent communication
are inside this clock. Initial model replies are not a READY gate.
`ready` remains an optional capability query. Old frozen READY-barrier runs keep
their previous behavior; new standing drafts require `direct_team_v3`.

The host never fills a Worker's plan or decides allocations. Shared collaboration
rules describe standing local authority. Workers remain available after local
completion until the team ends. Their end of a model turn is an idle native
session, not a completed task. Messages, self-selected review deadlines and
saved work can wake that same session again. Controller is also a normal bound
policy role for mailbox and wake purposes.

### Resource and timing implications

A batch's `parallel` limits simultaneous **tasks**, not role CLI processes.
With N arms, a standing task has N or N+1 initial sessions. The four smallest
Level 1 cases have 4, 4, 8 and 4 arms: all four at once mean 20 peer Workers, or
24 roles with Controllers. A 36-task Adaptive resource estimate does not qualify
36 standing tasks. Commission concurrency with actual memory, provider limits
and process observations before increasing it.

The default 0.3-second interval gates initial task-host launches. It is not a
pause between robot operations, a message latency or a guarantee of serial model
turns inside one team. All roles operate independently after START, subject to
shared runtime authority and the provider. Native configuration is per task;
each role has its own native session and transcript within that task's store.

The task deadline is the persisted START plus the frozen limit, normally 24
hours. A separately selected engineering stop does not silently shorten that
public task definition. Status and stop use the same commands as other batches:

```sh
.venv/bin/robofrontier status runs/engineering/claude-standing-l1
.venv/bin/robofrontier stop runs/engineering/claude-standing-l1
```

Stop first cancels every role's model turn and waits, then uses the existing
physical seal. Unknown physical outcomes remain unresolved rather than being
replayed. Inspect seal and final owner status before collecting.

### Errors, budgets and evidence

A lost bind acknowledgement blocks bootstrap instead of rebinding. A lost wake
acknowledgement marks that wake uncertain, pauses dispatch and prevents automatic
resend. An unavailable/mismatched role also pauses the team. Confirmed provider
capacity errors use the existing bounded same-session recovery. One role's
recoverable error cannot hide another role's unknown or fatal outcome.

Standing roles share one task-local cost ledger. Dollar caps are optional and
unset by default. An explicit task allowance must cover simultaneous turn
reservations; it is not a per-role allowance or provider-enforced spending cap.
Unknown costs under configured allowances stay review findings. Model stop and
physical sealing do not invent missing cost or session records.

The normal stopped collection includes all role-bound native transcripts and
linked auxiliaries, motion, action/message/wake records and reports. Collectors
identify roles from runtime metadata, so no Controller is required in peer mode.
The normal ZIP archive, restore and replay path also applies. See
[evidence storage](../running/evidence-storage.md) for locations and retention.

### Measured coverage

The native loopback integration runs actual Claude CLI/MCP with a synthetic
model endpoint and synthetic world. Both topologies verified independent native
sessions, an authorized Worker action, mailbox messages, wake dispatch and
continuation of the same sessions. A confirmed wake may already be `observed`
when inspected; it is not required to remain transiently `sent`.

An explicitly enabled real MuJoCo test then ran each topology on Transport
A04-D1 for 20 seconds after START. Both exercised an RGB observation, a completed
Worker A gripper operation, messages and resumed native roles. Both stopped with
sealed physical state, no unresolved actions and an exited owner. The tests did
not ask a genuine model to solve Transport or claim a success rate.

```sh
PYTHONPATH=tests:scripts .venv/bin/python -m unittest \
  test_claude_standing_team test_claude_standing_team_integration
ROBOFRONTIER_PHYSICS_STANDING=1 PYTHONPATH=tests:scripts \
  .venv/bin/python -m unittest test_claude_standing_physics_smoke
```

The opt-in test needs installed current assets, a renderer and Claude CLI, but
uses only a local synthetic endpoint. It retains stopped physical evidence.
These scoped checks do not qualify all families/scales, concurrent subscription
refresh, production providers, cluster hardware or formal scored execution.

## Engineering run, status and stop

The unified entry uses frozen settings:

```sh
.venv/bin/robofrontier run runs/engineering/claude-current-l1 --engineering
.venv/bin/robofrontier status runs/engineering/claude-current-l1
.venv/bin/robofrontier stop runs/engineering/claude-current-l1
```

Run is potentially billable; invoke only with explicit authorization. The
engine-specific multi-profile entry remains available for engineering inspection:

```sh
.venv/bin/python -m robofrontier.batch.claude_benchmark run-engineering RUN_DIR --parallel 2 --wall-limit-s 1200 --startup-timeout-s 600
.venv/bin/python -m robofrontier.batch.claude_benchmark status-engineering RUN_DIR
.venv/bin/python -m robofrontier.batch.claude_benchmark stop-engineering RUN_DIR
```

The first command is a dry plan unless `--confirm-engineering-spend` is added.
Use optional `--turn-budget-usd`/`--task-budget-usd` only when an allowance is
intended. An engineering wall stop is measured after START, excludes startup
and sealing, and requests orderly stop rather than an exact provider cutoff.
The shorter of the applicable persisted task deadline and engineering stop
controls execution. Waiting longer for startup changes neither allowance nor
physical/model qualification.

The draft prepare command freezes inputs for engineering inspection only; it is
not a scored batch. The engineering run/status/stop commands are experimental;
the real-provider preflight and full runner still require qualification.

The launcher validates a draft, claims it once, starts an independent physical
owner and supervises existing role sessions. It never automatically restarts a
world or an uncertain task. Sealing must explicitly report no unresolved actions;
process exit alone is insufficient. If finish ended the world, a readable private
`evaluation.json` with boolean `task_success` is required for clean engineering
closure. `task_success: false` may be a normally sealed unsuccessful task.
Missing/corrupt evaluation remains `needs_review`.

Batch startup prechecks all tasks, respects concurrency and does not restart
claimed tasks. Useful status values include:

| State | Meaning |
| --- | --- |
| `stopped_before_start` | Stop arrived before a task was launched. |
| `stopped` | Stop skipped unstarted tasks or sealed active tasks. |
| `closed` | Engineering batch closure, not successful task scoring. |
| `needs_review` | At least one task has unresolved execution/sealing/cost evidence; takes precedence over normal closure. |
| `claim_without_status_needs_review` | A launch claim exists without a status file; do not treat it as a fresh unlaunched batch. |
| `supervisor_lost_needs_review` | Supervisor loss needs inspection; claims remain and replay is refused. |

`stop_requested` is marker existence, not confirmation the owner received it.
`claim_record_present` is likewise a file snapshot. Recorded `owner_pid` is not a
live-process check and may be reused by the OS. When Controller state is unknown
or failed, limited `session_evidence` records allowance status, recognized CLI
result subtype and reported turn cost; a number does not reconcile an uncertain
bill or authorize retry. A run with unknown execution, unresolved reservations
or cost uncertainty under an allowance remains review-required even if its
physical world sealed. Historical statuses are never retroactively rewritten.

Ctrl-C/SIGTERM requests batch stop, skips pending launches and waits for active
models/owners to stop and seal. Wait for exit and inspect status. SIGKILL, node
loss or supervisor crashes can leave physical processes; do not infer sealing
or blindly relaunch. A prelaunch cancellation check avoids creating the CLI when
already canceled, and can release its unused reservation. A cancellation racing
with process creation can still launch a request and incur cost; its outcome and
reservation remain uncertain. Role/delegation state still needs inspection.

Only conclusively ended, matching-session structured capacity failures permit
bounded recovery, under the [current recovery checks](README.md#capacity-and-rate-limit-recovery).
Ordinary nonzero exits, unknown actions, uncertain fork creation and unknown
identity remain review-required. Provider retries never replay physical actions.

A run whose protocol counts active time (`run_protocol.clock: active_time_v1`)
also gets the Codex host's network continuation
(`recovery.recover_network`). When the world resumes after a network-outage or
Slurm egress pause it records `egress_recovery`. A role's failed turn found
within that pause (30 s either side) is resent once per role and pause, in the
same session (`--resume`), with the frozen `network-resume.md` notice, after the
role has no robot work in flight and the runtime grants the claim
(`runtime_cli network-recovery`). This applies when the turn's structured API
error names a lost connection (`api_error` `connection_failed`, `no_response`,
`stream_idle_timeout` or `computer_slept`, with no HTTP status) or does not say
what failed. A typed network failure seen before any pause waits up to 30 s for
the world to pause; without a pause it is an ordinary failed turn. A second
failure in the same pause, or a turn that failed for another reason within it
(an authentication error, a turn or budget limit), holds the run for review
(`NETWORK_CONTINUATION_UNCERTAIN`) and is never resent. Nothing is replayed: the
resent turn reads its saved work and original call IDs. Runs frozen without the
clock never resend.

Such runs also have the 48-hour [wall backstop](../running/run-segments.md#wall-backstop).
The world stops the run; the supervisor waits for it to close, reports
`ended_by: wall_backstop` and leaves the run `needs_review` (its result is not
counted). If the world has not ended the run 150 s after the backstop, even
while a pause holds it, the supervisor ends it itself with reason
`wall_backstop`.

## Normal finish and native reply completion

A genuine protocol commissioning witness exercises real observation, delegation,
verified native snapshot/fork, a delegate's physical move, handback, parent
continuation and finish. Its terminal evaluator remains false because this is a
short declared interface fixture, not a solved Transport benchmark. At source
1367d37 the world ends normally, but the supervisor cancels the parent's pending
native final response and leaves its reservation uncertain. That failed
qualification receipt and all raw evidence remain unchanged.

After normal world termination, the supervisor now gives only existing native
turns up to 30 seconds to finish their reply and accounting. It neither dispatches
another turn nor extends physical task execution. Adaptive children and standing
roles are included. An external STOP interrupts this cleanup promptly; a timeout,
unknown turn or failed cost record remains review-required. A recorded normal
world end is checked before treating an exited physical owner as a crash. Normal
engineering closure requires readable terminal evaluation and drained native
turns. The independent task score is never inferred from process closure.

## Reports, frozen inputs and provenance

`robofrontier.batch.report` reads only the current Claude run's role/turn
summaries, not unrelated Codex homes (see
[reports and metric definitions](README.md#reports-and-metric-definitions)). A
CLI-reported model name remains an observation; `all_requested_models_verified`
stays false. It cannot rule out provider mapping or auxiliary requests. JSON
audit reports declare `benchmark_qualified: false`; Markdown also labels the
unqualified state. Task success and permission to claim a scored benchmark are
different facts.

New drafts freeze their actual shared imports `robofrontier/batch/prepare.py`
(with the rest of `robofrontier/`), `benchmark_handoff.py` and `tasks.py`,
alongside native engine code and inputs.
Reprepare after source changes. Older drafts do not gain that check retroactively.
At historical Claude commit `85f9b91`, a merge preview against main `c8b4137` had
no text conflicts; this was not a completed merge or behavioral proof. That
branch descends from Codex handoff and brings its ancestors. Eight engine-neutral,
ten benchmark and 24 Node dispatcher checks passed then; current integration
must use its own source comparison and regressions.

## Provider prechecks and historical evidence

The following records preserve the conditions and limitations of earlier
engineering work. Dates, costs and source commits describe those attempts; they
are not qualification for every later profile, CLI, account or public protocol.
Some original attempts used the historical READY barrier. New direct-start runs
must use their own prepared inputs and evidence.

After `uv sync --locked --extra oracle`, use:

```sh
.venv/bin/python -m robofrontier.batch.claude_benchmark models
.venv/bin/python -m robofrontier.batch.claude_benchmark doctor --models haiku opus kimi qwen glm deepseek
.venv/bin/python -m robofrontier.batch.claude_benchmark plan --models kimi --level 1 --min-arms --parallel 4
.venv/bin/python -m robofrontier.batch.claude_benchmark prepare-draft --models kimi --level 1 --min-arms --output runs/engineering/claude-draft
.venv/bin/python -m robofrontier.batch.claude_benchmark prepare-draft --models opus --level 1 --min-arms --record-video --output runs/engineering/claude-video-draft
.venv/bin/python -m robofrontier.engines.claude.claude_offline_probe
```

### Text, image and resume precheck

Real precheck (spends money; needs a credential and an explicit cap):

```sh
.venv/bin/python -m robofrontier.engines.claude.preflight --profile haiku --max-budget-usd 0.5
.venv/bin/python -m robofrontier.engines.claude.preflight --profile haiku --max-budget-usd 0.5 --confirm-spend
.venv/bin/python -m robofrontier.engines.claude.preflight --profile haiku --max-budget-usd 0.5 --check-fork --confirm-spend
```

Without `--confirm-spend` it only prints the plan. With it, it makes three
calls on one explicit session: a text reply, a robot tool call whose returned
image must be identified, and a resumed turn. The receipt is `receipt.json`
in the output directory; it records CLI version, requested and reported model,
cost and per-check results, never key values. A profile passes only if all
three checks pass within the cap. Choose the intended profile explicitly for
each engineering draft and obtain the relevant precheck evidence for that
profile; a Haiku precheck does not establish Opus or other provider readiness.

The image color is chosen randomly from six colors for each new precheck; the
receipt records the chosen color after the checks. A single correct answer can
still be a lucky guess and does not establish general visual capability. The
earlier Haiku receipt listed below used a fixed green image.
Each local precheck server keeps its own image and request count, so concurrent
checks do not share that state; this is not a provider concurrency guarantee.
The check also requires the CLI event stream to show an `observe` call selecting
the `top` view, a matching non-error tool result containing an image, and an
`observe` request received by the local service. This is still not independent
proof that a real provider processed the image. Older receipts lacking the
new view-request or image-result evidence will not pass `claude_readiness`;
the historical Haiku receipt has not been rerun under these checks.

`--check-fork` adds a fourth paid call: a tool-free native fork of the idle
session that must recall the image color and have a matching native transcript
prefix. The receipt includes a profile fingerprint and whether the fork was
checked. This idle-session check does not establish compatibility with a parent
blocked in a tool call, concurrent delegate execution, or a real robot task.
The cap is based on CLI-reported cost and is not a provider billing limit.

### Blocked-parent fork precheck

For an additional paid check of the adaptive fork boundary:

```sh
.venv/bin/python -m robofrontier.engines.claude.claude_blocked_precheck --profile opus --max-budget-usd 1
.venv/bin/python -m robofrontier.engines.claude.claude_blocked_precheck --profile opus --max-budget-usd 1 --confirm-spend
```

It uses a synthetic local robot service and three CLI turns: initialize the
parent, block the parent at an image tool call, and create a tool-free fork
while that call is blocked. It verifies the native history prefix, releases the
parent, and checks its image response. One turn can generate multiple provider
requests. The two concurrent turn allowances share the remaining estimated
budget. A receipt with `cost_complete: false` does not account for every turn;
neither this check nor the CLI-reported budget proves a provider billing cap,
physical execution, or scored-run qualification. Its fork is a tool-free CLI
probe: it does not exercise the gated delegate fork the adaptive host now uses.

### Receipt comparison

After obtaining both real receipts, compare them with the current profile and
CLI version without making model calls:

```sh
.venv/bin/python -m robofrontier.engines.claude.claude_readiness --profile opus --precheck /path/to/receipt.json --blocked-precheck /path/to/blocked/receipt.json
```

This checks required observations, session relationships, cost completeness,
model/profile fingerprint and CLI version. `precheck_evidence_matches` is only
receipt consistency: it cannot authenticate a receipt, distinguish accounts
sharing the same profile, establish provider model identity, or authorize a
scored benchmark. `formal_execution_available` remains false.

### Recorded precheck and trial results

First Haiku preflight record (historical, before the Opus checks below):

- `haiku` (`claude-haiku-5-5`, CLI 2.1.312) passed on 2026-10-28 with a total
  cost of $0.000541 under a $0.5 cap. Its receipt is local at
  `runs/engineering/claude-precheck/haiku-20261028-194259/receipt.json`
  (`runs/` is gitignored). This covers only that profile, CLI version and cap.
- The first Haiku record did not establish Opus readiness; the later separately
  authorized Opus checks are recorded below. Other providers remain unqualified.

On 2026-10-28, the `opus` profile also passed both real-provider prechecks
using CLI 2.1.312: text, image/tool round trip, resume, idle fork, and fork
while the parent was blocked on an image call. The CLI reported $0.030570
and $0.021293 respectively; these are estimates, not the provider invoice.
The local receipts matched the profile and CLI in `claude_readiness`.
They do not qualify a physical task or a scored run, and the Chinese profiles
remain unverified. Receipts and transcripts are local run artifacts, not part
of the Git handoff.

A subsequent separately authorized, unscored Opus adaptive transport engineering
trial reached READY and received two observation images, but the startup turn
did not end before the 120-second startup timeout. The owner sealed and exited
with no unresolved actions; no physical action had started. The interrupted CLI
turn did not produce a complete cost report, so actual charges require checking
the provider invoice. Its event stream showed continued thinking progress after
the observation; this alone does not establish the cause or a remedy. Do not
replay the claimed run or treat this as a qualified benchmark result.

A separately authorized second Opus engineering trial used a 600-second startup
timeout and a $0.20 CLI turn allowance. Before START, the CLI exited nonzero
with `error_max_budget_usd` and reported $0.4755318 for the turn. This exceeds
the requested per-turn allowance and is not a provider invoice; the ledger
retained the cost as uncertain. The physical owner sealed and exited with no
unresolved actions and no robot actions. This observation demonstrates that
the CLI allowance is not a hard spending cap, and the trial does not qualify a
scored benchmark or explain the earlier interrupted turn's actual cost.
The final CLI event reported per-model aggregate `modelUsage`: 13,707 output
tokens including 13,299 thinking tokens, 39,118 cache-creation input tokens,
and 28,889 cache-read input tokens. Its separate `usage` field contained lower
counts; it should not be mistaken for the aggregate. New summaries retain both
fields and the result subtype as reported, without converting them to a bill.

A separately authorized Haiku 5.5 adaptive transport trial reached START and
made physical tool calls through the real CLI and provider. It reached the
300-second wall limit without a finish call, then sealed and exited with no
unresolved actions. The runtime recorded 14 completed physical actions and one
failed action; two further move requests were rejected before execution. No
delegate was created and no task-success evaluation was produced. The CLI
reported $0.011251435 for the completed startup turn; the interrupted active
turn had unknown cost, requiring provider billing review. This unscored trial
demonstrates live observations and actions, not task completion or full
adaptive qualification.

### Fresh-clone checks

On 2026-10-28, a fresh local clone at commit `aa0473d` independently created
its Python environment with `uv sync --locked --extra oracle`, downloaded the
published `handoff-20261028` asset archive, verified its SHA-256 and restored
3,467 files. It planned and prepared the four minimum-arm Level 1 Opus drafts;
all four frozen-input checks returned no changes. The Claude test suite ran
104 tests successfully with two opt-in physical tests skipped. The clone came
from the local branch, not GitHub, and no real provider or scored run was tested.
The same clone subsequently passed the opt-in four-way physical smoke: four
distinct MuJoCo owners overlapped, camera images reached a synthetic loopback
model, each delegate completed its synthetic motion and returned control, and
all four worlds sealed. This is an engineering integration check, not evidence
of real model capability or scored benchmark qualification.

At commit `0b81cb5`, a new local clone again installed its own dependencies,
downloaded and SHA-256-verified the GitHub Release archive, and restored 3,467
files. It prepared the four minimum-arm Level 1 Opus drafts and verified all
four frozen inputs. Claude-focused discovery completed 123 tests with six
skipped. This was a clone of the local branch, because the Claude branch was
not yet published; it did not call a real provider or run a scored task.

## Historical local integration and physics checks

Early local synthetic model/robot checks verified native session launch, image
forwarding, resume, fixed role connection, READY/START and deterministic
scheduling. They did not prove provider compatibility or real physics. Two old
execution/action tests initially lacked `mosaic/four-arm-10x10/assets`; restoring
the exact main-worktree scene let them pass then. This does not establish all
historical assets for a new clone.

The optional physical checks below use real MuJoCo owners and Claude CLI, but
only a loopback synthetic model with a synthetic key. They make no paid calls
and do not measure model ability. Install current pinned assets and choose a
working graphics environment first. The combined invocation is in
[regression and qualification boundaries](README.md#regression-and-qualification-boundaries).

```sh
ROBOFRONTIER_PHYSICS_SMOKE=1 .venv/bin/python -m unittest discover -s tests -p 'test_claude_physics_smoke.py' -v
ROBOFRONTIER_PHYSICS_BATCH=1 .venv/bin/python -m unittest discover -s tests -p 'test_claude_parallel_physics_smoke.py' -v
ROBOFRONTIER_PHYSICS_FINISH=1 .venv/bin/python -m unittest discover -s tests -p 'test_claude_finish_physics_smoke.py' -v
ROBOFRONTIER_PHYSICS_SIGNAL=1 .venv/bin/python -m unittest discover -s tests -p 'test_claude_signal_physics_smoke.py' -v
```

The single-run check defaults to minimum-arm Level 1 Transport; set
`ROBOFRONTIER_PHYSICS_CASE` for another released case. It verifies images reaching
the synthetic model, Adaptive delegation/return, a synthetic 5 mm A-arm movement,
deadline stop, sealing and owner exit. On 2026-10-28, each minimum-arm Level 1
family passed separately. Setting `ROBOFRONTIER_PHYSICS_VIDEO=1` additionally
checks recorded stream/first-frame decode; the historical Transport check
passed but did not decode the entire video.

The four-way check verified four independent MuJoCo owners alive concurrently,
images, child displacement/return and sealing. It passed at `9f8709d` and again
at `2972dba` after prompt changes. Predetermined synthetic responses are not
real model collaboration or provider concurrency/rate/billing evidence.

The finish check deliberately ended an unfinished centralized Transport case.
Private evaluation correctly reported failure, exported audit retained it and
requested-model identity remained unverified. It checks failure closure and
scorer isolation, not successful completion or scored eligibility.

Single- and four-task SIGTERM checks verified supervisor exit and each owner
seal/exit under the tested timing. After cancellation-reservation changes,
`9d58b2a` passed both checks; its Claude group ran 127 tests with seven optional
checks skipped. A separate supervisor-loss test used fake tasks, retained launch
claims and refused rerun; it does not prove that real physical children stop
or seal after supervisor loss. None of these tests covers every crash, provider
error, interruption boundary or long-run concurrent task.

Real-provider successful task completion, true multi-role stability, current
subscription operation and formal scored qualification remain required. Use the
integration ledger for newer source-specific acceptance; preserved historical
counts and receipts do not certify changed code automatically.
