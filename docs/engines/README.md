# Policy engines: native Codex and Claude Code

The two engines execute the same public robot tasks and share runtime authority,
START timing, terminal-outcome scoring, process records and evidence formats.
Their native session and tool interfaces are different. This guide covers what
the two engines share and where they differ. Use the
[architecture](../architecture.md) for shared contracts and the
[acceptance ledger](../archive/unified-main.md) for actual integration evidence.

| Guide | Contents |
| --- | --- |
| [Codex engine](codex.md) | Native app-server policy execution, the retained `scripts.benchmark` interface, Luna on Linux CPU and Slurm |
| [Claude engine](claude-code.md) | Native Claude CLI/MCP engineering entries, authentication, cost ledger, standing teams, prechecks and historical evidence |
| [Providers](providers.md) | Model catalogs and profiles, the authentication matrix, third-party endpoints, preflight and multi-model batches |
| [Runtime protocol notes](../protocol.md) | Observation images, SQLite writer contention, direct START and terminal scoring, robot tool errors |

This guide describes newly prepared runs in the unified integration. Existing
frozen inputs and sessions are not migrated automatically. The normal task clock
is 24 hours from persisted START; an engineering stop is separate. Evaluation is
independent of policy execution: accepting `finish` begins closure/evaluation and
does not establish task success.

## Current status

New Single/Adaptive runs use direct Controller START; both engines use direct
team START for initial standing-team roles. `ready` is a capability query in
those runs. Historical `ready_barrier_v1` inputs retain their old READY/idle
barrier. Claude exposes all four engineering topologies. Native permanent
Workers are documented in [Claude standing teams](claude-code.md#standing-teams);
formal scored Claude execution remains unavailable.

Current policy selection retains Transport R14, Mosaic R14, Relay's final goal
policy and BEST5 Dial R11 (see the [task index](../tasks/README.md)). Mosaic R15
drafts are not a default; do not import a Mosaic R15 draft because another
source branch has a newer-looking name. Frozen historical recordings retain
their own source, colors and physical parameters; new code must not silently
apply current physics or scoring to an old recording.

## Outer manager and evaluated policy

An outer Desktop session, another coding agent, or a shell can invoke and monitor
the commands: prepare, launch, inspect engineering errors, stop and collect. It
need not use the same model or engine as the evaluated policy, and selecting the
Claude policy engine does not require the outer manager to be Claude Desktop. No
outer LLM session is needed at all. The measured policy runs in independent
native sessions; an outer chat does not have to remain inside a tool turn.

The selected engine profile and frozen runtime configuration determine the
actual policy, not the manager's chat model. The
[manager prompt](../../prompts/managers/codex.md) defines the manager's
authority: it performs engineering operations, not private task strategy or
physical recovery. Policy decisions, task images and robot actions belong to the
evaluated roles. An outer manager that changes inputs or injects strategy can
invalidate a run; command-based orchestration alone does not establish
independence.

## Shared setup

The tools target POSIX macOS/Linux environments with file locks. Install Python
3.12, uv, Node.js and the native CLI for the selected engine. The pinned CLI
versions are the `CODEX_VERSION` and `CLAUDE_CODE_VERSION` build arguments in
[`docker/Dockerfile`](../../docker/Dockerfile); they are observed reproducibility
pins, not claims about the latest upstream releases. The unified Docker image
installs both pinned CLIs. A native Claude-only path does not require the Codex
CLI. Requalify changed CLI versions. The original multi-model handoff used Codex
`0.164.0-alpha.11.1` as a historical test pin; do not treat its provider receipt
as valid for another installed CLI. Graphics and sandbox prerequisites must be
verified on the execution machine.

```sh
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap
.venv/bin/python -m scripts.benchmark_handoff init-env
```

### Credentials file

`init-env` creates the ignored `.env` only if absent, with mode 600. Do not
replace an existing `.env` with the template; edit it locally. Equivalent
manual creation is `cp .env.example .env` followed by `chmod 600 .env`, or this
command, which refuses to overwrite an existing file:

```sh
.venv/bin/python -c 'import os; from pathlib import Path; fd = os.open(".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.write(fd, Path(".env.example").read_bytes()); os.close(fd)'
```

The loader reads literal values rather than executing shell syntax; existing
process environment values take precedence. Do not `source` an unreviewed file
or transfer someone else's native login. Never commit keys, put them in model
JSON, TOML or command arguments, or share them in chat. An empty template value
is neither a login nor a compatibility check. Configure only the selected
profiles; the variable for each profile is in the
[authentication matrix](providers.md#authentication-matrix). API credentials are
local per user: a local manager controlling SSH does not automatically forward
its environment or keys to the remote process.

### Policy assets

Policy bootstrap automatically restores the approximately 186 MB pinned
archive, checks its SHA-256, and verifies referenced assets. Preparation also
installs/verifies the package if needed; a plain `git clone` cannot run an
installation step. The package is `policy-assets-rolling003-20261029.tar.gz` in
the [handoff-20261028 release](https://github.com/changxuanfan/RoboFrontier/releases/tag/handoff-20261028),
SHA-256 `1bb7420c38c44b7e2f469d3789a1c0096a4f5cf6d377894d1ae2c1b0a8de2d31`;
`configs/policy-assets.json` records the exact archive and hash. It supplies the
required 36-task scene assets and Panda upstream source/licenses, not user
authentication, experiment results or prepared worlds.

Release and asset upload dates need not match. Correct installed files are
reused; `already_complete` does not imply a new download/cache file. A
conflicting file or wrong package fails verification rather than being
approximated or relabeled. Do not replace a missing asset with an approximate
texture, alter an expected fingerprint, or silently substitute another asset
revision. For an offline machine, transfer the pinned package and run:

```sh
.venv/bin/python -m scripts.benchmark_handoff setup-assets \
  --archive /path/to/policy-assets-rolling003-20261029.tar.gz
```

A receiver can also download that named asset with their own authorized `gh`
installation. Any private-repository access requirement is determined by the
repository's actual settings. The separate multi-gigabyte Factory recording
package has its own lock/installer; it is not needed for policy execution and is
not downloaded by ordinary policy bootstrap.

## Component map

| Component | Native Codex | Native Claude Code | Qualification boundary |
| --- | --- | --- | --- |
| Provider/model catalog | `configs/models.json`; launch configuration writes `codex.json` | `configs/claude-models.json`; `scripts/claude_benchmark.py` | Profiles alone do not establish provider compatibility. |
| Task selection/freeze | `benchmark_common.select_cases`, shared preparation | Same selection/preparation; `engine: claude` in new harness/manifest | Shared tasks, separate engine qualification. |
| One policy turn | app-server `turn/start` | `claude -p`, `robofrontier/claude/runner.py` | Native turn lifecycle is not task success. |
| Robot tools | app-server dynamic `robot` tool | Role-bound MCP in `robot_mcp.py` | Actual provider image handling requires its own evidence. |
| Per-task host | `robofrontier/codex/codex_policy_host.js` | `policy_host.py`, `adaptive_policy_host.py`, `standing_team.py` | All four Claude topologies remain engineering only. |
| Scheduling | `scripts/meta_dispatcher.js` | `dispatch.py`, `adaptive_dispatch.py`, `standing_team.py` | Both use shared deterministic runtime rules; Claude engineering does not run through a fabricated Codex tool object. |
| Session observation source | `codex.wait_threads`, `codex.app-server` | `claude.host` | `SESSION_SOURCES` is restricted by selected engine. |
| Fork history | Native ordinal/prefix hashes in the task's Codex home | Native transcript UUID sequence/content in `provenance.py` | Prefix equality alone does not establish trusted creation or role authority. |
| Source freeze | Benchmark launch and native host/RPC scripts | Claude launcher/catalog and imported shared Python modules | Current freeze checks do not retroactively protect old drafts. |
| Supervision | Preflight/run/status/stop | Precheck and engineering run/status/stop | A matching receipt does not authorize a scored Claude task. |
| Local doctor | Unified CLI selects native engine | Native Claude doctor also checks local credentials/assets/tools | Presence is not successful authentication; no model is called. |
| Evidence/reporting | Native sessions plus host/motion/tool records | Native transcripts/tool-results plus host/motion/tool records | Shared metrics preserve engine-specific units and missing fields. |

## Files and responsibilities

| Area | Files | Responsibility |
| --- | --- | --- |
| Claude tool IDs | `robofrontier/claude/robot_mcp.py` | Generate/return new request IDs, retain an ID across retransmission of the same MCP request, and return structured conflict/uncertain errors |
| Claude delegation identity | `request_identity.py`, `fork_setup.py` | Bind the generated delegation ID to one unmatched native tool call, then fork each child at that call and verify its copied history |
| Public tool instructions | `prompts/archive/claude/controller.md`, `prompts/skills/robot-collaboration/references/tools.md` | Distinguish new requests, status queries and retries of uncertain requests; retain explicit-ID compatibility |
| Claude provider errors | `recovery.py`, `runner.py`, `session_host.py` | Recognize structured capacity failures and retain original-session recovery, backoff and retry evidence |
| Claude scheduling | `supervisor.py`, `dispatch.py`, `adaptive_dispatch.py`, `standing_team.py` | Recover within the existing deadline; a recovering role does not claim ordinary wakes while other runnable roles continue |
| Shared reporting | `robofrontier/run_metrics.py`, `scripts/export_run_report.py` | Emit common `host_metrics`; resolve isolated Codex homes and collected session maps |
| Host timing | `robofrontier/codex/codex_policy_host.js`, Claude `runner.py` and `robot_mcp.py` | Record turn/tool/fork setup intervals without adding another image Base64 log |

The engine-specific modules remain native implementations. Both engines fork a
delegate at the parent's pending `delegate` call and give it the same frozen
first message; how each native host creates that fork still differs (see
[engine differences](#engine-differences)).

## New requests, queries and delegation

Omit the outer `call_id` for an ordinary new request, then retain the generated ID
from the result. To query an existing action, send a new `job` request with the
old action ID in `data.call_id`. If retrying an uncertain original request is
necessary, use its original outer ID and exactly the same operation/arguments.
Confirm the old outcome before choosing another physical action. A known ID
conflict means rejection; an uncertain transport outcome does not prove rejection.
The typed error payloads are described in
[robot tool error feedback](../protocol.md#robot-tool-error-feedback).

A Claude MCP JSON-RPC request ID is not the native `tool_use.id`. Before an
automatic delegation, the host reads the Controller's native record and finds
the unique unanswered tool call whose parameters match exactly. It persists this
association under `private/state/claude-tool-bindings/` before submission and
checks it again before forking. Native transcripts can lag behind an MCP request;
matching waits at most ten seconds. Missing or ambiguous evidence rejects the
submission rather than guessing provenance. The explicit delegation-ID path
remains compatible. Preserve parent/child transcripts and tool-result directories.
The fork itself is described under
[internal Adaptive delegation](claude-code.md#native-sessions-tools-and-internal-delegation).

## Capacity and rate-limit recovery

This section describes the Claude host layer. The Codex host's equivalent rules
are in [Codex time, capacity recovery and context](codex.md#time-capacity-recovery-and-context).

Candidate recovery requires all of the following: the CLI has conclusively
exited; its returned session matches the original; the result subtype is
`error_during_execution`; and its structured code is `rate_limit`,
`rate_limit_error`, `overloaded_error` or `server_overloaded`. The string "429" in
model prose or stderr is insufficient. The native CLI may already have retried;
this host layer acts only after the CLI returns a recognized failure.

Before recovery, check native history, run state, stop markers, actions and
delegations. Accepted/executing requests must settle first. Unknown actions,
fork creation in progress, uncertain identity, a paused run or a stop request
prevent automatic recovery. When an explicit dollar allowance is set, a turn
whose cost is unknown still requires review.

At most three extra attempts follow consecutive capacity failures, after 10,
20 and 40 seconds. A successful turn resets the consecutive count. Defaults live
in `recovery.py`; host construction can lower the attempt count. Waiting does not
block the supervisor or extend START time. Recovery sends a continuation to the
original session; it does not resubmit motion or recreate a delegate. Exceeding
the limit or failing the checks retains stop/seal/review behavior. Cancellation,
process crashes and unknown outcomes are not this recoverable error class.
Synthetic error tests cannot establish every real provider failure behavior.

## Reports and metric definitions

After all writers stop, run in the original execution environment:

```sh
.venv/bin/python -m scripts.export_run_report RUN_DIR
```

The output is `RUN_DIR/private/outputs/report.json`; common statistics are in
`host_metrics`. For historical Codex logs, `--codex-home PATH` selects a home
explicitly. Otherwise the resolver prefers collected session mappings, then
run/batch `codex-home.json`, and finally the environment default. An unavailable
known batch home never authorizes substituting sessions from another home.
Collected mappings take priority over stale paths to the original server.

| Field | Meaning and missing-data handling |
| --- | --- |
| `usage.input_tokens` | Total input. Claude sums uncached input, cache reads and cache writes; Codex reported input already includes cached input. |
| `cached_input_tokens` | Cache-read input; `cache_hit_rate` is reads divided by total input. |
| `cache_write_input_tokens` | Claude-reported cache creation. This Codex interface does not separately report it, so its value is `null`. |
| `output_tokens` | CLI/app-server reported output; do not add thinking tokens a second time. |
| `reported_cost_usd` | Subtotal of reported costs. Missing cost is not zero; no assumed price is applied. |
| `usage_complete`, `cost_complete` | Whether fields are complete in the observed evidence scope. Unfinished turns, damaged logs and incomplete older evidence remain incomplete. |
| `known_usage_subtotals` | Known usage only; incomplete turns prevent interpretation as a complete total. |
| `by_actor`, `rows` | Per-role aggregates and deduplicated details. `row_unit` distinguishes Claude CLI turns from Codex usage updates; row counts are not equivalent API request counts. |
| `model_process_seconds_sum` | Sum of turn durations, including tool waits and CLI overhead. |
| `model_process_wall_seconds_union` | Union of those intervals, avoiding double-counting overlapping wall time. |
| `tool_seconds_sum` | Host tool durations, which may overlap model-process time. |
| `fork_setup_seconds_sum` | Codex native fork RPC time; for Claude, the time from starting a child's first turn until its copied history was verified. Claude runs from before fork-at-call setup report their tool-free snapshot/fork turns here instead. |

Claude prefers final `modelUsage`, aggregated across the turn's models, and uses
`usage` only as a fallback; the two are not added. Older summary-only records are
labeled `legacy_policy_only` and may omit setup. For Codex, the first usage update
uses `last` to exclude inherited parent usage; subsequent updates use cumulative
differences, with duplicate updates removed. These are host observations, not a
recalculation of full transcript history or a provider invoice.

Missing fields are `null`. Check completeness, evidence scope and original logs.
Model, tool and setup times overlap and include waits; summing them does not give
elapsed time percentages or pure API latency. Native host events live in
`private/outputs/codex-host.jsonl` or `claude-host.jsonl`. They supplement, rather
than replace, native sessions, motion, private evaluation and archive validation.
See [evidence storage](../running/evidence-storage.md) for collection and archives.

## Engine differences

Normal policy turns have no separate default timeout, while bounded startup,
RPC and delegate fork setup still have limits. Engine-native prompts,
compaction, context inheritance and creation work can differ. Shared elapsed,
usage and tool metrics report these differences; they do not erase them. Equal
effort names do not establish equal computation across providers or engines.

Delegate creation behaves the same on both engines: the child's history ends at
the parent's pending `delegate` call, its first input is the frozen
`private/inputs/bootstrap/delegate.md` filled for that child, and it runs no tool
before the runtime activates the batch. The native mechanism differs. Codex
calls `thread/fork` (first a snapshot thread, then each child from it) and sends
the message after activation. Claude Code creates a fork only by running its
first turn, so a Claude child's fork *is* that turn, started with the delegate
message; a hook holds every tool call until activation. Each Claude child forks
directly from the blocked Controller and is verified against the same pinned
history (see [the Claude delegate fork](claude-code.md#trusted-internal-adaptive-fork)).
Claude therefore starts its first model request before activation and Codex
after it; neither runs a tool before.
Claude cost accounting uses a run-local ledger; see
[Claude cost allowances](claude-code.md#cost-allowances-and-the-shared-ledger).

## Real qualification still required

Managed subscription login profiles and evidence isolation are documented in
the [authentication matrix](providers.md#authentication-matrix) and the
engine guides. Their scoped login and refresh checks remain separate from the
real task conditions below.

1. Obtain profile/account/current-CLI evidence for text, image/tool round trip,
   continuation and fork. Adaptive additionally needs a parent blocked in a tool
   call. Check intended batch use, model mapping, visual/tool support, concurrency
   and actual billing. Receipt consistency does not prove provider model identity.
2. With explicit spending authorization, verify a real task's observations,
   actions, delegation, handback, continuation, finish, terminal world state and
   evaluation. Synthetic displacement and process sealing do not establish task
   completion or model ability.
3. Compare frozen task selection, authority, observations, timing and evaluation.
   Record native differences such as compaction or the native fork mechanism
   rather than declaring them identical conditions.
4. Verify startup, stopping, unknown actions, process exceptions and supervisor
   loss under concurrency, retaining their evidence. SIGTERM smoke does not cover
   SIGKILL, power loss or every physical action boundary.
5. Open scored preparation/qualification/batching only after these conditions are
   supported by evidence. `formal_execution_available` remains false for Claude.

Credentials stay outside Git. Real calls and engineering trials need explicit
operator authorization.

## Regression and qualification boundaries

Common offline checks:

```sh
PYTHONPATH=tests:scripts .venv/bin/python -m unittest test_run_metrics test_run_report test_benchmark_collection test_policy_archive
node --test tests/test_codex_rpc.js tests/test_tool_errors.js tests/test_codex_wall_limit.js
```

Claude-specific checks:

```sh
PYTHONPATH=tests:scripts .venv/bin/python -m unittest discover -s tests -p 'test_claude_*.py'
```

The opt-in physical group requires current assets, a working graphics backend
and the observed native Claude CLI. It uses real MuJoCo/CLI processes with a local
synthetic model service, no paid provider, and does not evaluate model ability:

```sh
PYTHONPATH=tests:scripts ROBOFRONTIER_PHYSICS_SMOKE=1 ROBOFRONTIER_PHYSICS_BATCH=1 ROBOFRONTIER_PHYSICS_FINISH=1 ROBOFRONTIER_PHYSICS_SIGNAL=1 .venv/bin/python -m unittest test_claude_physics_smoke test_claude_parallel_physics_smoke test_claude_finish_physics_smoke test_claude_signal_physics_smoke
```

These cover generated IDs, native fork/return, resumed actions, independent
scoring after `finish`, deadline/SIGTERM stop and collection. The synthetic
`finish` case deliberately leaves the task unfinished; evaluation must remain
unsuccessful. It tests scorer isolation, not successful task completion. Real
model task completion, concurrent roles, current provider behavior and scored
Claude qualification remain separate acceptance requirements. Per-check history
is in [Claude historical physics checks](claude-code.md#historical-local-integration-and-physics-checks).

## Historical migration checks

Earlier migration records describe their original stages, not current defaults.
The original stage introduced optional `engine`, preserving absent fields in
already frozen Codex inputs. Runtime session observations became engine-specific.
`runtime_cli.native_fork_provenance` dispatches by engine; Claude reads native
transcripts below the run-local `private/claude-config/projects/`. The shared
Node dispatcher has an adapter seam, but Claude's actual engineering hosts use
their Python dispatchers, not a Codex-shaped emulation.

An early shared-source check at `188fff6` passed 55 run-setup/runtime/report/
delegation/execution-contract/action tests; report imports required
`PYTHONPATH=scripts`. Another early baseline passed scheduling, delegation,
callbacks, benchmark, pipeline, centralized, batching, setup, runtime,
synchronization, handoff and Claude groups. Two execution/action cases lacked
historical scene assets. These dated results neither establish every current
asset nor replace the integration regression ledger.

Early role hosts bound an existing centralized world, loaded public materials
and waited on READY/idle. The first adaptive drafts and synthetic runtime tests
later connected delegation, setup, scheduling and stopping. Subsequent real
MuJoCo/CLI loopback tests exercised those paths. Current direct START supersedes
the old barrier only for new inputs; old recordings keep their original protocol.
See [Claude provider prechecks and historical evidence](claude-code.md#provider-prechecks-and-historical-evidence)
for preserved historical provider prechecks, costs, physical smoke scope and
remaining lifecycle gates.
