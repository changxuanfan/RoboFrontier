# Policy engines: native Codex and Claude Code

The two engines execute the same public robot tasks and share runtime authority,
START timing, terminal-outcome scoring, process records and evidence formats.
Their native session and tool interfaces are different. This guide covers what
the two engines share and where they differ. Use the
[architecture](../architecture.md) for shared contracts and the
acceptance ledger (`docs/archive/unified-main.md`, in the [archive tag](../history.md)) for actual integration evidence.

| Guide | Contents |
| --- | --- |
| [Codex engine](codex.md) | Native app-server policy execution, Luna on Linux CPU and Slurm |
| [Claude engine](claude-code.md) | Native Claude CLI/MCP engineering entries, authentication, cost ledger, standing teams, prechecks and historical evidence |
| [Providers](README.md#providers) | Model catalogs and profiles, the authentication matrix, third-party endpoints, preflight and multi-model batches |
| [Runtime protocol notes](../protocol.md) | Observation images, SQLite writer contention, direct START and terminal scoring, robot tool errors |

This guide describes newly prepared runs in the unified integration. Existing
frozen inputs and sessions are not migrated automatically. The normal task clock
is 24 hours from persisted START; an engineering stop is separate. Evaluation is
independent of policy execution: accepting `finish` begins closure/evaluation and
does not establish task success.

## Current status

New Single/Adaptive runs use direct Controller START; both engines use direct
team START for initial standing-team roles. `ready` is a capability query in
those runs. Claude exposes all four engineering topologies. Native permanent
Workers are documented in [Claude standing teams](claude-code.md#standing-teams);
formal scored Claude execution remains unavailable.

Current policy selection is Transport R14, Mosaic R15 (71 mm grid pitch), Relay's
final goal policy and BEST5 Dial R11 (see the [task index](../tasks/README.md)).
Select scenes through `benchmark/release.json`, never by a newer-looking revision
name on another source branch. Frozen historical recordings retain
their own source, colors and physical parameters; new code must not silently
apply current physics or scoring to an old recording.

## Outer manager and evaluated policy

An outer Desktop session, another coding agent, or a shell can invoke and monitor
the commands: prepare, launch, inspect engineering errors, stop and collect. It
need not use the same model or engine as the evaluated policy, and selecting the
Claude policy engine does not require the outer manager to be Claude Desktop. No
outer agent session is needed at all. The measured policy runs in independent
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
.venv/bin/python -m robofrontier.batch.handoff init-env
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
[authentication matrix](README.md#authentication-matrix). API credentials are
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
.venv/bin/python -m robofrontier.batch.handoff setup-assets \
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
| Provider/model catalog | `configs/models.json`; launch configuration writes `codex.json` | `the `claude` section of `configs/models.json``; `robofrontier/batch/claude_prepare.py` | Profiles alone do not establish provider compatibility. |
| Task selection/freeze | `benchmark_common.select_cases`, shared preparation | Same selection/preparation; `engine: claude` in new harness/manifest | Shared tasks, separate engine qualification. |
| One policy turn | app-server `turn/start` | `claude -p`, `robofrontier/engines/claude/runner.py` | Native turn lifecycle is not task success. |
| Robot tools | app-server dynamic `robot` tool | Role-bound MCP in `robot_mcp.py` | Actual provider image handling requires its own evidence. |
| Per-task host | `robofrontier/engines/codex/codex_policy_host.js` | `policy_host.py`, `adaptive_policy_host.py`, `standing_team.py` | All four Claude topologies remain engineering only. |
| Scheduling | `robofrontier/engines/codex/meta_dispatcher.js` | `dispatch.py`, `adaptive_dispatch.py`, `standing_team.py` | Both use shared deterministic runtime rules; Claude engineering does not run through a fabricated Codex tool object. |
| Session observation source | `codex.wait_threads`, `codex.app-server` | `claude.host` | `SESSION_SOURCES` is restricted by selected engine. |
| Fork history | Native ordinal/prefix hashes in the task's Codex home | Native transcript UUID sequence/content in `provenance.py` | Prefix equality alone does not establish trusted creation or role authority. |
| Source freeze | Benchmark launch and native host/RPC scripts | Claude launcher/catalog and imported shared Python modules | Current freeze checks do not retroactively protect old drafts. |
| Supervision | Preflight/run/status/stop | Precheck and engineering run/status/stop | A matching receipt does not authorize a scored Claude task. |
| Local doctor | Unified CLI selects native engine | Native Claude doctor also checks local credentials/assets/tools | Presence is not successful authentication; no model is called. |
| Evidence/reporting | Native sessions plus host/motion/tool records | Native transcripts/tool-results plus host/motion/tool records | Shared metrics preserve engine-specific units and missing fields. |

## Files and responsibilities

| Area | Files | Responsibility |
| --- | --- | --- |
| Claude tool IDs | `robofrontier/engines/claude/robot_mcp.py` | Generate/return new request IDs, retain an ID across retransmission of the same MCP request, and return structured conflict/uncertain errors |
| Claude delegation identity | `request_identity.py`, `fork_setup.py` | Bind the generated delegation ID to one unmatched native tool call, then fork each child at that call and verify its copied history |
| Public tool instructions | `robofrontier/engines/common/robot_tool.json`, `prompts/skills/robot-collaboration/references/tools.md` | Distinguish new requests, status queries and retries of uncertain requests; retain explicit-ID compatibility |
| Claude provider errors | `recovery.py`, `runner.py`, `session_host.py` | Recognize structured capacity failures and retain original-session recovery, backoff and retry evidence |
| Claude scheduling | `supervisor.py`, `dispatch.py`, `adaptive_dispatch.py`, `standing_team.py` | Recover within the existing deadline; a recovering role does not claim ordinary wakes while other runnable roles continue |
| Shared reporting | `robofrontier/batch/metrics.py`, `robofrontier/batch/report.py` | Emit common `host_metrics`; resolve isolated Codex homes and collected session maps |
| Host timing | `robofrontier/engines/codex/codex_policy_host.js`, Claude `runner.py` and `robot_mcp.py` | Record turn/tool/fork setup intervals without adding another image Base64 log |

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
20 and 40 seconds plus a jitter (`bootstrap.MAX_CAPACITY_RETRIES`). A successful turn resets
the consecutive count. Recovery sends the frozen `capacity-resume.md` to the original session,
the same text the Codex host sends; it does not resubmit motion or recreate a delegate. When the
attempts are used up, both hosts pause dispatch, and the run ends as an unexpected stop that
continues by itself once ([stop table](../running/continuation.md#when-a-run-continues)). A plan's
usage limit is not a capacity error: the world pauses until it resets
([usage-limit pause](../running/continuation.md#usage-limit-pause-every-platform)). Cancellation,
process crashes and unknown outcomes are not this recoverable error class.
Synthetic error tests cannot establish every real provider failure behavior.

## Reports and metric definitions

After all writers stop, run in the original execution environment:

```sh
.venv/bin/python -m robofrontier.batch.report RUN_DIR
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

Claude prefers `modelUsage`, aggregated across the turn's models, and uses `usage`
only as a fallback; the two are not added. `modelUsage` is a running total for the
session, so each turn counts its difference from the session's previous turn, and a
lower counter starts again from zero. Requests after a session's last reported result,
such as a background task waking an idle CLI, are added from the run's transcripts as
`after_last_result` rows and summarized in `usage_after_last_result`. A compaction in
that stretch leaves `usage_complete` false, because transcripts omit its tokens. Older
summary-only records are
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
the [authentication matrix](README.md#authentication-matrix) and the
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
node --test tests/engines/test_codex_rpc.js tests/engines/test_tool_errors.js tests/engines/test_codex_wall_limit.js
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
Claude qualification remain separate acceptance requirements.

## Providers

For running, see the [unified CLI](../unified-cli.md), [Docker](../running/docker.md),
[Slurm](../running/slurm.md) and [evidence storage](../running/evidence-storage.md) guides.
Engine-specific details are
in the [Codex](codex.md) and [Claude](claude-code.md) guides; installation, the `.env`
file and policy assets are in [shared setup](README.md#shared-setup).

### Catalogs and profiles

The native Codex catalog is `configs/models.json`; Claude has
`the `claude` section of `configs/models.json``. Profiles are candidates, not provider-availability
or compatibility certificates. The dated
pricing research (`docs/archive/model-pricing-20261028.md`, in the [archive tag](../history.md)) and
compatibility comparison (`docs/archive/model-compatibility-20261028.md`, in the [archive tag](../history.md)) are
historical research, not current price/rate-limit guarantees. Candidate models
not in the catalog cannot be launched merely because they appear in those tables.

Native Codex and Claude Code use their respective supported authentication flows.
An official API profile and a subscription/OAuth profile are different choices;
a subscription in one product is not a transferable API credential for every
engine/provider. A coding subscription does not establish the pay-as-you-go API
permissions, image support, Responses transport, or tools required here.
Cross-provider model names do not establish image, tool, fork, compression,
budget or authentication compatibility. Perform the matching native preflight;
keep the actual requested/observed configuration with the evidence.

A provider's flagship label is not our measured ranking. A text-only model is
not silently combined with a different vision model under one score. Verify the
actual account/profile through preflight; catalog configuration alone is not
qualification.

### Authentication matrix

Defaults:

- The repository's overall default is the Codex `luna` profile
  (`gpt-6-luna`, effort `high`) through `OPENAI_API_KEY`.
- An engine-only Claude selection (`--engine claude` with no profile in the user
  TOML or explicit options) defaults to `haiku_subscription_token`. The legacy
  Claude planning/preparation script also defaults to it when `--models` is
  omitted. Explicit profiles remain exact, and existing frozen runs retain their
  selected profile.

These profiles have separate compatibility receipts.

| Engine | Authentication mode | Profiles | Credential or setting | Details |
| --- | --- | --- | --- | --- |
| Codex | OpenAI API key | `luna` | `OPENAI_API_KEY` | [Codex catalog](codex.md#model-catalog-and-defaults) |
| Codex | Native ChatGPT login | `luna_subscription` (also `sol61_subscription`, `terra61_subscription` in the catalog) | Codex native store in a dedicated or explicitly shared Codex home | [Codex authentication](codex.md#authentication-and-codex-homes) |
| Codex | Third-party API key (Responses) | `deepseek`, `qwen`, `glm`, `kimi` | `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY` + `DASHSCOPE_BASE_URL`, `ZAI_API_KEY`, `KIMI_API_KEY` | [Codex Responses endpoints](#codex-responses-endpoints) |
| Codex | OpenLux API key | `openlux-luna`, `openlux-terra` | `OPENLUX_API_KEY` | OpenLux Terra (`docs/archive/openlux-terra.md`, in the [archive tag](../history.md)) |
| Claude | Long-lived subscription token from `claude setup-token` | `haiku_subscription_token` (default) | `CLAUDE_CODE_OAUTH_TOKEN` | [Claude authentication](claude-code.md#default-subscription-token) |
| Claude | Older explicit OAuth token mode | `opus_subscription` | `CLAUDE_CODE_OAUTH_TOKEN` | [Claude authentication](claude-code.md#authentication) |
| Claude | Native saved login, default namespace | `haiku_subscription` | `ROBOFRONTIER_CLAUDE_HOME` = `HOME/.claude`, `CLAUDE_CONFIG_DIR` unset | [Saved login](claude-code.md#native-saved-login) |
| Claude | Native saved login, explicit directory | `haiku_subscription_directory` | `ROBOFRONTIER_CLAUDE_HOME` = the `CLAUDE_CONFIG_DIR` used at login | [Saved login](claude-code.md#native-saved-login) |
| Claude | Anthropic API key | `haiku`, `opus` | `ANTHROPIC_API_KEY` | [Claude authentication](claude-code.md#authentication) |
| Claude | Third-party API key (Anthropic-compatible) | `kimi`, `kimi_code`, `qwen`, `glm`, `deepseek` | The catalog's credential variable; Qwen also `DASHSCOPE_ANTHROPIC_BASE_URL` | [Claude-compatible endpoints](#claude-compatible-endpoints) |

The table reflects the catalog files when this guide was written; the catalogs
are authoritative. Relevant `.env` credential names include:

```dotenv
OPENAI_API_KEY=
OPENLUX_API_KEY=
ANTHROPIC_API_KEY=
KIMI_API_KEY=
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=
ZAI_API_KEY=
DEEPSEEK_API_KEY=
```

Claude's `kimi_code` uses `KIMI_CODE_API_KEY`, and Claude's Qwen profile uses
`DASHSCOPE_ANTHROPIC_BASE_URL`; `CLAUDE_CODE_OAUTH_TOKEN` holds a Claude
subscription token. Never commit keys, put them in model JSON or command
arguments, or share them in chat. Use `benchmark_handoff init-env` to create a
private template if absent (see [credentials file](README.md#credentials-file)).

### Codex Responses endpoints

The following is the **2026-10-28 catalog/documentation snapshot**, retained for
provenance rather than a current model ranking or provider availability promise:

| Provider | Catalog vision candidate | Original documentation |
| --- | --- | --- |
| DeepSeek | `deepseek-flash`; the referenced V4 Pro was text-only, with V4.1 Flash identified as the visual candidate | [Model/pricing documentation](https://api-docs.deepseek.com/quick_start/pricing/), [Codex integration](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/) |
| Qwen | Fixed `qwen3.8-max-0902` snapshot | [Vision](https://help.aliyun.com/zh/model-studio/vision-model), [Responses](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses) |
| Zhipu | `glm-5.3-flash` native-multimodal candidate; the referenced GLM-5.3 was text-only | [Text model](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3), [Vision candidate](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash), [Responses](https://docs.bigmodel.cn/cn/guide/develop/responses/introduction) |
| Kimi | `kimi-k3.1-pro` | [Model guide](https://platform.kimi.com/docs/guide/kimi-k3-1-pro-quickstart), [Codex integration](https://platform.kimi.com/docs/guide/codex-kimi) |

For a third-party provider, the native process-local configuration has this
shape; the harness generates it rather than replacing global configuration:

```toml
[model_providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com"
env_key = "DEEPSEEK_API_KEY"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
```

The retained Kimi endpoint is `https://api.moonshot.cn/v1` with `KIMI_API_KEY`;
Zhipu uses `https://open.bigmodel.cn/api/v1` with `ZAI_API_KEY`; Qwen uses the
operator's workspace endpoint and `DASHSCOPE_API_KEY`. For Qwen, set
`DASHSCOPE_BASE_URL` to the actual workspace/region Responses-compatible base
URL supplied by the provider, such as
`https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`, rather
than assuming an ordinary Chat Completions endpoint is interchangeable.

The matching catalog, provider address, image modalities, tool mode, and context
settings are frozen. Simply changing `-m` or having a Chat Completions endpoint
does not prove that Codex can receive images or call robot tools. The supported
runner uses Responses (`wire_api="responses"`); changing `wire_api` to `chat` is
not a compatibility fix. Image declarations alone do not establish that image
content actually reaches the model. Configured third-party endpoints still
require real account-specific verification. See the
[official configuration reference](https://developers.openai.com/codex/config-reference/).

### Claude-compatible endpoints

Claude third-party profiles use their catalog's credential variable and
Anthropic-compatible endpoint. The Anthropic-compatible Qwen endpoint,
`DASHSCOPE_ANTHROPIC_BASE_URL`, must match your actual account and region.
`kimi` and `kimi_code` are distinct candidates with different credential
variables and endpoints. A configured URL or model name is not provider
qualification.

Check current provider account terms, allowed batch use, model mapping, endpoint,
vision/tool support, quota and pricing before paid prechecks. An editor-compatible
coding plan does not automatically authorize unattended parallel benchmarks.
Do not mix coding-plan and pay-as-you-go keys/endpoints. Historical source links:
[Qwen Claude Code integration](https://help.aliyun.com/zh/model-studio/claude-code),
[DeepSeek Claude Code integration](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/),
[Kimi Code integration](https://www.kimi.com/code/docs/en/third-party-tools/claude-code.html).

### Local checks and preflight

Run local checks before a paid test:

```sh
.venv/bin/robofrontier doctor --engine codex --profile kimi --render native
.venv/bin/python -m robofrontier.engines.codex.check_codex_cli --output runs/engineering/local-cli-check
.venv/bin/robofrontier plan --engine codex --profile kimi --level 1 --min-arms --parallel 4
```

Use `--render cpu` on Linux OSMesa or the default NVIDIA backend on an equipped
Linux host. Doctor checks local prerequisites; it is not proof of account access.
The CLI stub check exercises local native interfaces, images and fork behavior;
it is not a successful call to Kimi/Qwen/GLM/DeepSeek.

With the account owner's authorization, a paid smoke-only test can check a small
synthetic image/tool round trip. A complete paid preflight additionally exercises
manual compaction and fork history/tool use:

```sh
.venv/bin/robofrontier preflight --profile kimi --render native --smoke-only --confirm-spend
.venv/bin/robofrontier preflight --profile kimi --render native --confirm-spend
```

Smoke receipts do not replace complete qualification. These checks do not stress
every context size, establish autonomous compaction under all loads, prove the
provider's actual backing model identity, or qualify every robot task. Change
model, endpoint, effort, catalog or CLI version only with a matching new check.
Native Codex compatibility reports remain under
`runs/engineering/model-smoke/<profile>/report.json` and
`runs/engineering/model-compatibility/<profile>/report.json` respectively.
Claude prechecks are described in
[Claude provider prechecks](claude-code.md#provider-prechecks).

### Qualification and limits

Preflight remains explicit and may consume subscription quota:

```sh
robofrontier preflight --engine claude --profile haiku_subscription \
  --max-budget-usd 0.10 --confirm-spend
```

CLI USD reports are estimates; subscription list-price equivalents are not
provider invoices. Keep API spending, subscription quota and unknown outcomes
separate. Claude task execution requires passed precheck receipts; these profiles
do not open formal scored eligibility. Local shared-home checks do not qualify
Docker, Slurm, 36 simultaneous subscription tasks or every refresh boundary.
The Slurm entry continues to accept API credentials only. See the acceptance ledger (`docs/archive/unified-main.md`, in the [archive tag](../history.md))
for actual source-pinned results.

Official references: [Codex authentication](https://learn.chatgpt.com/docs/auth),
[Codex account refresh](https://learn.chatgpt.com/docs/app-server), and
[Claude Code authentication](https://code.claude.com/docs/en/authentication).

### Multi-model task selection and concurrency

New unified defaults are Luna/high, adaptive, 36 concurrent task hosts and a
24-hour limit from each task's persisted START. Inspect a plan before preparing.

| Selection | Tasks per model | Four model profiles |
| --- | ---: | ---: |
| Level 1, minimum arms in each family | 4 | 16 |
| Level 1, every scale | 12 | 48 |
| All levels and scales | 36 | 144 |

Minimum-arm Level 1 selects Transport 4, Mosaic 4, Relay 8 and Dial 4 arms.
Level 2 selects 4, 4, 8 and 8 respectively. Dial's `n04` denotes dial count,
not necessarily arm count. Selection reads actual task metadata.

For one model's four Level 1 tasks, after matching preflight:

```sh
.venv/bin/robofrontier prepare --engine codex --profile kimi --render native \
  --level 1 --min-arms --parallel 4 --output runs/policy/kimi-l1-small-001
.venv/bin/robofrontier run runs/policy/kimi-l1-small-001
.venv/bin/robofrontier status runs/policy/kimi-l1-small-001
.venv/bin/robofrontier stop runs/policy/kimi-l1-small-001
```

Preparation freezes code, public task inputs, profile/configuration and independent
worlds without launching a model. Task concurrency is not native session count
or provider request concurrency; delegates, turns and forks add model requests.
Concurrent batches add their loads. CPU, RAM, rendering and account RPM/TPM can
all limit throughput. No setting silently guarantees successful 36-way execution.

Each preparation selects one profile. Every run of a Dial case uses that case's fixed code
from `benchmark/release.json`, so all profiles face the same puzzles. Keep the context and
compaction thresholds and the requested effort in reports: identical effort strings do not
prove identical compute.

Finish is subject to action/delegation safety checks and then evaluation; saying
"done" does not prove success. STOP requests a graceful shutdown rather than an
immediate kill. Unstarted tasks can be skipped. A crashed physical world is not
automatically restarted or replayed. Keep unsealed/uncertain outcomes for audit.
Use a fresh directory for another experiment. Level 2 is a new explicit selection,
not an implicit promotion by the runner. Task limits are not payment caps.

The host event file under each task's `private/outputs/` is distinct from native
session JSONL. Tool observations are rendered scene images, not automatic desktop
screenshots. Use the shared stopped-evidence collector/ZIP verifier for sessions,
motion, referenced JPEGs and scoring evidence; see [storage](../running/evidence-storage.md).
Never monitor a live database across Docker/network filesystem boundaries.

### Branches, bundles and worktrees for multi-model work

#### Provenance of the original handoff

The original `codex/multimodel-handoff` branch was created from
`codex/server-benchmark-prep`, commit
`3638e1c351b6e885ac94e3256f5782f8aecd46ee`. Forking a chat did not copy a Git
worktree; the code base was checked separately. The original Harness session's
running experiments remained its responsibility. This is historical provenance,
not a claim that every current integration file equals that original commit.

#### GitHub, branches and offline bundles

The repository is [changxuanfan/RoboFrontier](https://github.com/changxuanfan/RoboFrontier).
A worktree is a directory checked out on a branch. Committing there advances
that branch, not `main`. A branch can be shared without first merging main.
Cloning public code does not grant push permission; writers need the repository
owner's access invitation or their own fork/PR workflow. GitHub access settings
are separate from code, assets and model authentication.

The historical Codex handoff can be cloned explicitly:

```sh
git clone --branch codex/multimodel-handoff \
  https://github.com/changxuanfan/RoboFrontier.git RoboFrontier
cd RoboFrontier
git switch -c experiments/my-model
```

That command selects the historical branch, not the unified integration. Use the
reviewed published ref appropriate to the experiment. For an existing checkout,
inspect `git status --short`, `git branch --show-current` and `git log -1` before
updating. Do not discard local work to force a pull.

An offline Git bundle contains selected Git history/refs; it is not a running
worktree, dependency installer, model login, asset archive or synchronization
service. The original handoff called its bundle `roomscript2.bundle`. A receiver
can clone a verified bundle containing the intended branch:

```sh
git clone --branch codex/multimodel-handoff /path/to/roomscript2.bundle RoboFrontier
```

Later updates require a remote fetch or another bundle. Share only reviewed refs;
ignored credentials/runs do not enter a new bundle merely because they are in a
worktree, but Git history itself must still be reviewed before publication.

#### Worktrees and eventual merge

A linked worktree shares Git history but has its own checked-out branch and
working files. One branch cannot normally be checked out in two linked worktrees
at once. A coworker's independent clone can use a personal branch; a second
worktree in one clone can be created from the intended reviewed base:

```sh
git worktree add -b experiments/kimi-l1 ../RoboFrontier-kimi codex/multimodel-handoff
```

The example preserves the historical Codex base. Choose the reviewed unified
ref when the integration features are required. Worktree creation does not copy
ignored `.env`, Python environments, run directories or untracked assets.
Rebuild dependencies and use verified read-only assets; keep new prepared worlds
and runtime directories independent. Prepare on the target machine/path rather
than moving a frozen executable batch with absolute paths.

Commit only the reviewed code, push your branch, then open a PR. Before merging
into main, verify its branch/status, review the complete diff, resolve conflicts
and run the appropriate checks. Preserve teammates' commits and do not force-push
over their work. Git merges tracked code; ignored assets, credentials, native
sessions and experiment outputs require their own verified handoff. A merged
branch alone does not publish a new asset release or prove the entire integration
qualified.
