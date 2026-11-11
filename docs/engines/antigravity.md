# Antigravity engine

The adapter runs pinned Antigravity CLI 1.5.5 (`agy`, distinct from `gemini`).
It supports centralized, hierarchical, peer and adaptive policies using the
released tasks and existing runtime. Python orchestration, supervision, recovery,
robot MCP handling and accounting lifecycle are shared with Claude Code under
`robofrontier/engines/common/`. Linux file tools use the same Landlock worker as
Codex. The native transport and fork provenance remain engine specific.

## Install

Follow [shared setup](README.md#shared-setup), then install the pinned standalone
binary. The installer checks a platform-specific SHA-512 before extraction:

```sh
.venv/bin/python -m scripts.install_antigravity --output "$HOME/.local/bin/agy"
agy --version
```

Supported packages are macOS ARM64, Linux x86-64 and Linux ARM64. Platform package
availability alone does not establish that a particular sandbox or provider works.
Use native rendering on Mac and CPU or NVIDIA rendering on Linux.

## Authentication

Profiles live in the `antigravity` section of `configs/models.json`:

| Profile | Authentication | Endpoint |
| --- | --- | --- |
| `flash_subscription` | Native Antigravity account login | Native subscription service |
| `flash_api` | Host reads `GEMINI_API_KEY` | Official Gemini API |
| `flash_service` | Host reads `ANTIGRAVITY_SERVICE_API_KEY` | HTTPS Gemini-compatible `ANTIGRAVITY_SERVICE_BASE_URL` |

Native login is a separate mode: API keys and endpoint overrides are rejected in
that profile. On macOS the adapter uses a private HOME with fixed configuration,
disables the default swarm plugin, and shares only the real OS Keychain directory
and `com.apple.security*.plist` lookup preferences through symlinks. This preserves
native login without copying tokens or importing personal rules, plugins, hooks or
MCP servers. It does not change the user's global configuration. An empty HOME
alone loses the Keychain lookup path and fails authentication.

Linux native login currently requires an authenticated, clean existing CLI home;
ambient customizations are rejected. Native login on an unauthenticated remote
node remains an explicit provisioning requirement. This is separate from Slurm's
currently supported API submission path.

API/service credentials remain in the host relay. The CLI receives only a random
placeholder credential for its private loopback listener. Policy tools cannot
access that listener, the CLI home, parent environments or the repository. The
relay forbids redirects and suppresses provider error bodies that might echo
credentials. A service must implement Gemini's API and tool/image semantics;
an arbitrary OpenAI-compatible endpoint is insufficient.

## Isolation

The custom agent exposes the robot MCP and brokered `policy_exec`/`policy_image`
tools, plus native `manage_task`. Native shell/filesystem tools are absent and
also rejected by permission rules and a pre-tool hook. Each MCP call is authorized
against its native conversation ID and the runtime's active role binding; the
model cannot select another role or robot connection.

On Mac the file broker builds a Seatbelt profile from the frozen access table.
On Linux it uses the shared Codex Landlock/seccomp worker. The CLI reads its
configuration from a private directory and file tools run in the policy
workspace. This lets Landlock grant creation of new files in the workspace
without granting write access to CLI configuration. Run the actual environment
probe on each execution host:

```sh
.venv/bin/python -m scripts.check_policy_env /path/to/policy-env-ID \
  --engine antigravity --scratch /path/to/run-storage
```

Landlock's process visibility and process-pool limitations are the same as the
Codex broker's, and are recorded by that probe. A lifetime pipe and a separate
guardian stop policy commands when their MCP owner exits, including SIGKILL.

## Preflight and receipts

The unified command requires explicit authorization for provider calls:

```sh
.venv/bin/robofrontier preflight --engine antigravity \
  --profile flash_subscription --confirm-spend
```

The full check covers text, a random robot-image challenge, native resume, a
blocked-parent native fork, exact inherited-prefix verification, child recall
without tools and parent continuation. A smoke check does not qualify a run.
Receipts bind the profile, CLI version and adapter implementation. Changing any
of these requires a new receipt. CLI usage does not report dollar cost, so a
precise dollar allowance is unsupported; missing cost stays null.

## Run, status and stop

```sh
.venv/bin/robofrontier prepare --engine antigravity --profile flash_api \
  --render native --cases transport-a04-d1 --output runs/policy/agy-example
.venv/bin/robofrontier run runs/policy/agy-example
.venv/bin/robofrontier status runs/policy/agy-example
.venv/bin/robofrontier stop runs/policy/agy-example
```

Preparation starts no model or world. Run requires matching provider and sandbox
receipts and uses the shared single-claim and sealing rules. Slurm stages API
preflight receipts with the frozen source. Its existing Codex subscription
credential lease is not an Antigravity credential store; native Antigravity login
is currently rejected by that submission path. Do not describe this as verified
Antigravity subscription support on Slurm.

## Sessions and delegation

The transport is persistent stream-JSON. A zero-input bootstrap establishes the
authenticated local control endpoint. The host creates the policy conversation
with its immutable checkpoint configuration, then attaches the CLI to that ID
before returning it for runtime role binding. No model input is sent during this
setup. Later turns reuse that conversation; process recovery resumes its ID.

Adaptive forks bind the pending native tool call by conversation, trajectory,
step and exact arguments. A write-ahead receipt precedes the fork RPC; an unknown
outcome pauses dispatch and is never automatically reforked. The child inherits
the exact prefix, the pending tool is canceled and the native fork notice is
verified. No child prompt or tool runs before the batch activates. These notices
are native behavior and remain observable differences from Codex.

## Recovery

The shared recovery state machine never replays robot actions to fix transport
errors. Only precise native structured capacity subtypes qualify for capacity
retry. Generic `RESOURCE_EXHAUSTED` is ambiguous and does not qualify. Native
quota/network classification needs provider-specific live validation; model text
and HTTP-looking text are never evidence of a retryable failure.

The native CLI also aggregates errors over the whole conversation: a recovered
network error can leave later successful turns marked `ERROR`. The adapter records
the native step boundary before input and checks the new persisted suffix for a
settled, text-only final response that exactly matches the CLI response. Only
that native proof can override the cumulative status. Missing, active, canceled,
tool-calling or mismatched final responses cannot qualify; original events remain
in evidence. This prevents unnecessary retries of already completed robot turns.

## Cost and context

Context capacity and automatic compaction are separate. The canonical requested
capacity is 300,000 tokens and the compaction budget is 267,000. The CLI's default
effective checkpoint budget was read back as 256,000 in local probes.

The adapter sets `agentConfig.cascadeConfig.checkpointConfig.maxTokenLimit=267000`
and `useModelReportedTokenCount=true` through the pinned CLI's local
`StartCascade` RPC. This is an internal interface, not a documented `agy` flag.
It reads back the static configuration before any policy input and the effective
executor configuration after successful turns, failing on a mismatch. Resume and
fork preserve this static configuration. Receipts are stored under
`private/engine/context/` and are collected with the run.

Local fake-service tests exercise both a below-budget report (260,000) and an
over-budget report (267,001). Only the latter creates a native `CHECKPOINT`, with
`TRUNCATION_REASON_MAX_TOKEN_LIMIT`. This verifies control of the native budget;
it does not establish a provider's actual hard context capacity or behavior with
a real 267k-token conversation. `CheckpointConfig.contextWindow` is a string
model-option selector; writing `"300000"` there is not proof of 300k capacity.

System suffixes, user time/wrappers, native tool schemas (`toolSummary`,
`manage_task`) and native fork/restart notices remain explicit differences. A
common task/runtime contract does not imply byte-identical model input.

## Evidence and reports

The host copies only its own native transcripts and SQLite session databases.
Collection and Slurm fallback exclude the native CLI home. Usage is recorded as
per-turn deltas from native cumulative counters; missing costs remain null.
The standard collect/report/archive commands apply to Antigravity batches.

Opt-in tests use the real pinned CLI and a local fake Gemini service, so they do
not establish provider quality, subscription eligibility or real task success:

```sh
ROBOFRONTIER_ANTIGRAVITY_INTEGRATION=1 PYTHONPATH=tests \
  .venv/bin/python -m unittest engines.test_antigravity_driver
ROBOFRONTIER_ANTIGRAVITY_PHYSICS=1 PYTHONPATH=tests \
  .venv/bin/python -m unittest engines.test_antigravity_physics_smoke
```

The physics tests exercise all four topologies with the real MuJoCo owner,
native CLI, MCP routing and run sealing. Their scripted actions intentionally do
not solve the task. A successful engineering smoke is not a successful benchmark
trial or a passed live provider preflight.

### Validation on 2026-11-11

| Check | Result | Scope |
| --- | --- | --- |
| Full Mac repository regression | 1,832 tests, no failed modules | Normal platform and opt-in skips apply |
| Native transport/auth/completion probes | 10 passed | Real CLI with local fake service; private authentication setup and stale-error handling |
| Four Mac topology physics smokes | All passed, also run concurrently | Real CLI, MCP, MuJoCo, native fork and sealing; scripted model service |
| Mac subscription `flash_subscription` preflight | All 8 checks passed | Real native account and Gemini; random image, resume, blocked-parent fork, recall and parent continuation |
| Mac subscription MuJoCo smoke | Foreground and launchd both closed with complete archives | 30-second engineering runs through `prepare` and `run`; foreground archive restored and checked |
| Real Gemini API / third-party API service | Not verified | No live API key supplied; local protocol tests do not qualify a provider |
| RunPod | 51 sandbox checks, 7 CLI tests and all four topology smokes passed | Real CLI, NVIDIA EGL and MuJoCo with a local fake Gemini service. This pod needed the generic EGL loader and OpenGL libraries. |
| Slurm | Queued | Job 432846 requests one GPU and a 48-hour time limit. Node and provider qualification are pending. |

The live subscription receipt is profile and implementation specific. Neither
these checks nor its model label establish provider identity cryptographically,
performance, task-solving quality, 300k hard capacity or absence of every bug.
