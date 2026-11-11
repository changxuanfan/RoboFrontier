# Policy engines: Codex, Claude Code and Antigravity

The three engines run the same released tasks (`benchmark/release.json`) with the same frozen inputs,
rules, robot tool text, runtime, START timing, terminal scoring and evidence formats. Each role
is a native session of the engine's own CLI. The engine guides cover setup and behavior
specific to each CLI.

| Guide | Contents |
| --- | --- |
| [Codex](codex.md) | app-server sessions, Codex homes, tool backends, receipts |
| [Claude Code](claude-code.md) | `claude -p` sessions over MCP, authentication modes, Bash isolation, prechecks, cost ledger |
| [Antigravity](antigravity.md) | Persistent `agy` sessions, native static checkpoint configuration, brokered tools, native forks and current validation limits |
| [Providers](#providers) | Profiles, the authentication matrix, third-party endpoints |
| [Unified CLI](../unified-cli.md) | Configuration and the `robofrontier` commands |
| [Runtime protocol](../protocol.md) | Observation images, START, terminal scoring, robot tool errors |

A run gets 24 h of active time from START and is scored at the cutoff; accepting `finish`
starts evaluation, it does not establish success. After an unexpected stop a run continues by
itself once; `robofrontier continue` continues it by hand
([continuation](../running/continuation.md)).

## Outer manager and evaluated policy

The commands (prepare, run, status, stop, collect) can be driven from a shell or from any
coding agent; no outer agent is needed, and the outer session's model has no effect on the run.
The frozen engine and profile select the measured model. The manager prompts
([Codex](../../prompts/managers/codex.md), [Claude Code](../../prompts/managers/claude.md)) and
the [manager runbook](../meta-runbook.md) define the manager's authority: engineering
operations only, never task strategy, robot actions or changed inputs. A manager that injects
either invalidates the run.

## Shared setup

Install Python 3.12, uv, Node.js and the CLI of the engine you will use, at the version pinned in
`robofrontier/runtime/versions.py` (Codex 0.165.0, Claude Code 2.1.316, Antigravity 1.5.5).
`prepare` and `run` refuse any other version.

```sh
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap
.venv/bin/python -m robofrontier.batch.handoff init-env
```

New runs use the frozen [policy Python environment](../running/policy-environment.md) by default.

### Credentials file

`init-env` creates the Git-ignored `.env` from `.env.example` with mode 600 and refuses to
overwrite an existing one (by hand: `cp .env.example .env && chmod 600 .env`). Fill in only the
variables of the profiles you use; the [authentication matrix](#authentication-matrix) names them.
The loader reads literal `KEY=value` lines without running shell syntax, and a variable already
set in the process environment wins. Never put a credential in TOML, a model catalog, a command
line, a commit or a chat. A remote host needs its own `.env`; SSH does not forward it.

### Policy assets

`bootstrap` downloads the archive named in `configs/policy-assets.json`, checks its SHA-256,
restores every referenced scene and Panda asset with hash checks, and reuses files that are
already correct; `prepare` does the same when needed. A wrong or conflicting file fails
verification; never substitute an approximate asset or edit an expected hash. On a host without
network access, copy the archive over and run:

```sh
.venv/bin/python -m robofrontier.batch.handoff setup-assets --archive /path/to/archive.tar.gz
```

The Factory recording package is separate and not needed for policy runs.

## Codex and Claude Code component map

Antigravity uses the shared Python policy hosts, batch supervisor and robot MCP
implementation with Claude Code. Its persistent CLI transport and native fork
verification are in `robofrontier/engines/antigravity/`. See the
[Antigravity guide](antigravity.md) for isolation and preflight details.

| Component | Codex | Claude Code |
| --- | --- | --- |
| Profiles | `codex` section of `configs/models.json` | `claude` section of `configs/models.json` |
| Preparation | `robofrontier/batch/codex_batch.py` | `robofrontier/batch/claude_prepare.py` |
| Batch supervision | `robofrontier/batch/codex_batch.py` | `robofrontier/batch/claude_batch.py`, `engines/claude/supervisor.py` |
| One policy turn | app-server `turn/start` (`codex_policy_host.js`, `codex_rpc.js`) | `claude -p` (`engines/claude/runner.py`, `session_host.py`) |
| Robot tool | app-server dynamic `robot` tool | role-bound MCP server `engines/claude/robot_mcp.py` |
| Per-task host | `engines/codex/codex_policy_host.js` | `policy_host.py`, `adaptive_policy_host.py`, `standing_team.py` |
| Scheduling | `engines/codex/meta_dispatcher.js` | `dispatch.py`, `adaptive_dispatch.py`, `standing_team.py` |
| Delegate fork | `thread/fork` with lineage hashes | `--resume --fork-session` checked by `provenance.py`, `fork_setup.py`, `adaptive_setup.py` |
| Shell isolation | Codex sandbox, or `landlock-v1` broker | Claude Code sandbox, or `landlock-v1` shell prefix |
| Paid compatibility check | `robofrontier preflight` (one receipt) | `robofrontier preflight` (two receipts) |
| Capacity recovery | `codex_policy_host.js` | `engines/claude/recovery.py` |
| Host events | `private/outputs/codex-host.jsonl` | `private/outputs/claude-host.jsonl` |

All three engines share the robot tool description `robofrontier/engines/common/robot_tool.json`,
the runtime under `robofrontier/runtime/`, the access table `robofrontier/runtime/access.py`,
metrics `robofrontier/batch/metrics.py` and reports `robofrontier/batch/report.py`.

## New requests, queries and delegation

Omit the outer `call_id` for a new request and keep the ID the result returns. To query an
earlier action, send a new `job` request with the old ID in `data.call_id`. To retry a request
whose outcome is uncertain, resend it under its original ID with exactly the same operation and
arguments, and confirm the old outcome before choosing another physical action. A known ID
conflict is a rejection; an uncertain transport outcome is not. Error payloads are in
[robot tool error feedback](../protocol.md#robot-tool-error-feedback).

A Claude MCP request ID is not the native `tool_use.id`. Before an automatic delegation the host
finds the one unanswered native tool call in the Controller's transcript whose parameters match
exactly, waiting at most ten seconds for the transcript to catch up, and persists the binding
under `private/state/claude-tool-bindings/` before forking. Missing or ambiguous evidence rejects
the delegation.

Delegate creation gives the same result on both engines: the child's history ends at the
parent's pending `delegate` call, its first input is the frozen
`private/inputs/bootstrap/delegate.md` filled in for that child, and it runs no tool before the
runtime activates the batch. Codex forks a snapshot thread and then each child from it, and
sends the message after activation. Claude Code can fork only by running a first turn, so each
child forks directly from the blocked Controller with the delegate message as that turn, and a
hook holds every tool call until activation
([Claude delegate fork](claude-code.md#sessions-and-delegation)).

## Capacity recovery

The same rule on both hosts (`MAX_CAPACITY_RETRIES` in `robofrontier/runtime/bootstrap.py`):
after a turn fails with a structured capacity error, the host resumes the same session with the
frozen `capacity-resume.md` at most three consecutive times, 10, 20 and 40 s apart plus a 0-5 s
jitter fixed by the session ID; a completed turn resets the count. Claude counts only a
conclusively exited CLI whose session matches and whose error code is `rate_limit`,
`rate_limit_error`, `overloaded_error` or `server_overloaded`; "429" in text does not count.
Accepted or running robot requests settle first; unknown actions, a fork in progress, a paused
run or a stop request block recovery. Recovery never resubmits motion or recreates a delegate.
When the attempts are used up, dispatch pauses and the run ends as an unexpected stop
([when a run continues](../running/continuation.md#when-a-run-continues)). A plan's usage limit
is not a capacity error: the world pauses until it resets
([usage-limit pause](../running/continuation.md#usage-limit-pause-every-platform)).

Both hosts also resend a turn that failed during a network-outage pause once per role and pause,
in the same session, with the frozen `network-resume.md`
([network-outage pause](../running/continuation.md#network-outage-pause)). After a normal finish,
both give existing turns up to 30 s to write their final reply and accounting.

## Reports and metric definitions

After every writer has stopped, in the environment that ran the batch:

```sh
.venv/bin/python -m robofrontier.batch.report RUN_DIR
```

This writes `RUN_DIR/private/outputs/report.json` with the shared `host_metrics`. For Codex,
`--codex-home PATH` names the session home; otherwise the report uses the collected session
mapping, then the run's `codex-home.json`, then the environment default.

| Field | Meaning |
| --- | --- |
| `usage.input_tokens` | Total input. Claude adds uncached input, cache reads and cache writes; Codex's input already includes cached input. |
| `cached_input_tokens` | Cache reads; `cache_hit_rate` is reads over total input. |
| `cache_write_input_tokens` | Claude's cache creation; `null` for Codex, which does not report it. |
| `output_tokens` | Reported output; thinking tokens are not added again. |
| `reported_cost_usd` | Sum of reported costs. Missing cost is not zero; no price is assumed. |
| `usage_complete`, `cost_complete` | Whether the evidence covers every turn. |
| `known_usage_subtotals` | Known usage only. |
| `by_actor`, `rows` | Per-role totals and deduplicated rows; `row_unit` says whether a row is a Claude CLI turn or a Codex usage update. |
| `model_process_seconds_sum` | Sum of turn durations, tool waits and CLI overhead included. |
| `model_process_wall_seconds_union` | Union of those intervals. |
| `tool_seconds_sum` | Host tool durations; overlaps model time. |
| `fork_setup_seconds_sum` | Codex fork RPC time; for Claude, from a child's first turn starting until its copied history is verified. |

Claude uses `modelUsage` (falling back to `usage`, never both). It is a running total per
session, so each turn counts its difference from the previous turn. Requests after a session's
last result, such as a background task waking an idle CLI, are added from the transcripts as
`after_last_result` rows and summed in `usage_after_last_result`; a compaction there leaves
`usage_complete` false. Codex counts `last` for the first update and cumulative differences
after it. Model, tool and setup times overlap: do not add them. These are host observations,
not a provider invoice.

## Engine differences

| | Codex | Claude Code |
| --- | --- | --- |
| Turn interface | app-server JSON-RPC | one `claude -p` process per turn, `--resume` to continue |
| Delegate fork | snapshot thread, then `thread/fork`; message sent after activation | first turn is the fork; tools held by a hook until activation |
| Compaction | at `auto_compact_token_limit` (267,000) | `CLAUDE_CODE_AUTO_COMPACT_WINDOW` set to that limit plus Claude Code's 33,000-token buffer |
| Compatibility receipts | one, per profile | two (basic and blocked-parent), per profile |
| Dollar allowance | none | optional, unset by `robofrontier run` |
| Task limit | `batch.task_wall_limit_s` | the same, at most 86,400 s |

Both freeze `context_window` 300,000 and `auto_compact_token_limit` 267,000 from
`configs/models.json`. Equal effort names do not mean equal computation across engines.

## Offline checks

See [development checks](../development/testing.md). The engine tests are under
`tests/engines/` and `tests/batch/`:

```sh
.venv/bin/python -m scripts.run_tests engines batch
```

The opt-in physical Claude group runs real MuJoCo worlds and the real Claude CLI against a local
synthetic model service, with no paid provider; it needs the assets and a graphics backend:

```sh
PYTHONPATH=tests ROBOFRONTIER_PHYSICS_SMOKE=1 ROBOFRONTIER_PHYSICS_BATCH=1 ROBOFRONTIER_PHYSICS_FINISH=1 \
  .venv/bin/python -m unittest engines.test_claude_physics_smoke engines.test_claude_parallel_physics_smoke \
  engines.test_claude_finish_physics_smoke
```

They cover generated IDs, native fork and return, resumed actions, scoring after `finish` (the
synthetic task is left unfinished, so evaluation must fail) and collection.

## Providers

### Catalogs and profiles

Profiles are the `codex` and `claude` sections of `configs/models.json`; a run freezes its
engine's section as `private/inputs/models.json`. A profile names a model, effort, provider
endpoint and credential variable. Being in the catalog does not make a profile compatible: its
preflight receipt does. Each batch has one profile.

### Authentication matrix

Defaults: the repository default is Codex `luna` (`gpt-6-luna`, effort `high`) with
`OPENAI_API_KEY`. `--engine claude` with no profile in the user TOML or on the command line
selects `haiku_subscription_token`.

| Engine | Authentication | Profiles | Credential or setting |
| --- | --- | --- | --- |
| Codex | OpenAI API key | `luna` | `OPENAI_API_KEY` |
| Codex | OpenLux API key | `openlux-luna`, `openlux-terra` | `OPENLUX_API_KEY` |
| Codex | ChatGPT login | `luna_subscription`, `sol61_subscription`, `terra61_subscription`, `astra` | Login in the Codex home ([Codex authentication](codex.md#authentication)) |
| Codex | Third-party Responses API | `deepseek`, `qwen`, `glm`, `kimi` | `DEEPSEEK_API_KEY`; `DASHSCOPE_API_KEY` + `DASHSCOPE_BASE_URL`; `ZAI_API_KEY`; `KIMI_API_KEY` |
| Claude | Subscription token (`claude setup-token`) | `haiku_subscription_token`, `opus_subscription` | `CLAUDE_CODE_OAUTH_TOKEN` |
| Claude | Saved login, default directory | `haiku_subscription` | `ROBOFRONTIER_CLAUDE_HOME` = `$HOME/.claude`, `CLAUDE_CONFIG_DIR` unset |
| Claude | Saved login, explicit directory | `haiku_subscription_directory` | `ROBOFRONTIER_CLAUDE_HOME` = the `CLAUDE_CONFIG_DIR` used at login |
| Antigravity | Saved Google login | `flash_subscription` | Native `agy` account ([Antigravity authentication](antigravity.md#authentication)) |
| Antigravity | Gemini API key | `flash_api` | `GEMINI_API_KEY` |
| Antigravity | Gemini-compatible service | `flash_service` | `ANTIGRAVITY_SERVICE_API_KEY`, `ANTIGRAVITY_SERVICE_BASE_URL` |
| Claude | Anthropic API key | `haiku`, `opus` | `ANTHROPIC_API_KEY` |
| Claude | Third-party Anthropic-compatible API | `kimi`, `kimi_code`, `qwen`, `glm`, `deepseek` | `KIMI_API_KEY`; `KIMI_CODE_API_KEY`; `DASHSCOPE_API_KEY` + `DASHSCOPE_ANTHROPIC_BASE_URL`; `ZAI_API_KEY`; `DEEPSEEK_API_KEY` |

The catalog is authoritative when this table and it differ.

### Codex Responses endpoints

The harness writes a process-local provider entry for third-party Codex profiles and never edits
the global Codex configuration. Its shape, for DeepSeek:

```toml
[model_providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com"
env_key = "DEEPSEEK_API_KEY"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
```

Kimi uses `https://api.moonshot.cn/v1`, Zhipu `https://open.bigmodel.cn/api/v1`; Qwen reads its
workspace endpoint from `DASHSCOPE_BASE_URL`, which must be that account's Responses-compatible
base URL (for example `https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`).
The runner needs the Responses API; a Chat Completions endpoint or `wire_api = "chat"` does not
work. See the [Codex configuration reference](https://developers.openai.com/codex/config-reference/).

### Claude-compatible endpoints

Each Claude third-party profile carries its Anthropic-compatible `base_url` in the catalog; Qwen
reads it from `DASHSCOPE_ANTHROPIC_BASE_URL`, which must match the account's region. `kimi`
(Moonshot API) and `kimi_code` (Kimi Code plan) use different keys and endpoints. Check the
provider's terms for unattended parallel use before a paid check; do not mix coding-plan and
pay-as-you-go keys.

### Local checks and preflight

```sh
.venv/bin/robofrontier doctor --engine codex --profile kimi --render native
.venv/bin/robofrontier plan --engine codex --profile kimi --level 1 --min-arms --parallel 4
```

`doctor` checks the installed CLI, its sandbox or tool backend and a real render; it calls no
model and does not check credentials. The paid checks are per engine:
[Codex preflight](codex.md#preflight-and-receipts), [Claude prechecks](claude-code.md#preflight-and-receipts).
A changed model, endpoint, effort, catalog or CLI version needs a new receipt.

### Selection and concurrency

| Selection | Runs per profile |
| --- | ---: |
| `--level 1 --min-arms` | 4 |
| `--level 1` | 12 |
| all levels | 36 |

Minimum-arm level 1 selects Transport 4, Mosaic 4, Relay 8 and Dial 4 arms (Dial's `n04` counts
dials). `batch.parallel` counts whole runs; delegates, standing Workers and forks add sessions and
model requests inside each run, so CPU, memory, rendering and the provider's rate limits bound
throughput, not the setting. Concurrent batches add up. Every run of a Dial case uses the fixed
code in `benchmark/release.json`, so all profiles face the same puzzles.
