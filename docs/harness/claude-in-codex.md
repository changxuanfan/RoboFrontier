# Claude in Codex (optional adapter)

This adapter lets the Codex harness run Claude Opus 5.5. You need it only for one comparison:
the same model in the other harness. Ordinary Codex runs (`sol`) and ordinary Claude Code runs
(`opus`) do not use it.

It is a local process, the *gateway*, that listens on `127.0.0.1`. Codex sends it the requests
it would send to OpenAI's Responses API, and the gateway translates them into requests to
Anthropic's Messages API and translates the answers back. The Codex CLI still runs the tools,
keeps the sessions, compacts and forks. The gateway runs no agent loop, executes no tool and
stores no conversation.

The adapter is RoboTeam code. OpenAI does not support routing the Codex CLI to Claude, and
Anthropic does not support Codex as a client. A passed preflight admits runs of this exact
combination; it does not make the results equivalent to Claude Code with Claude, or to Codex
with a GPT model: equal effort names do not mean equal computation, the context is capped at
300,000 tokens although the model accepts more, and Codex's prompts were written for GPT
models.

| Limit | |
| --- | --- |
| Model | `claude-opus-5-5` only, with adaptive thinking and the effort Codex asks for. A different model is an error; there is no fallback to another model or credential |
| Hosts | A Mac or a plain Linux host. Slurm and Docker are refused: their loopback interface is not the host's |
| Tool backend | The adapter's tests use the `native` tool backend on macOS. The `landlock-v1` backend and `--tools robot_only` are untested with this model |

## Use it

### 1. Install and start the gateway

The Anthropic SDK is an optional dependency, kept out of the benchmark's own environment:

```sh
python3 -m venv .venv-gateway
.venv-gateway/bin/python -m pip install -r roboteam/harness/adapters/claude_in_codex/requirements.txt
mkdir -p -m 700 ~/.roboteam/secrets ~/.roboteam/codex-claude
```

Put the Anthropic API key, alone, in `~/.roboteam/secrets/anthropic-api-key.txt` with mode 600.
Then start the gateway and leave it running:

```sh
.venv-gateway/bin/python roboteam/harness/adapters/claude_in_codex/gateway.py \
  --anthropic-key-file ~/.roboteam/secrets/anthropic-api-key.txt \
  --key-file ~/.roboteam/secrets/codex-claude-gateway-key.json \
  --log ~/.roboteam/codex-claude/transport-metadata.jsonl \
  --state-dir ~/.roboteam/codex-claude/state
```

| Option | Meaning |
| --- | --- |
| `--key-file` | Required. Holds the local gateway key; created with a random key on first start |
| `--anthropic-key-file` | The Anthropic API key. Without it the gateway reads `ANTHROPIC_API_KEY` from its own environment |
| `--port` | Loopback port, default 18470 (the one in `models.json`) |
| `--log` | A JSONL file with one line of metadata per request; without it nothing is stored |
| `--state-dir` | A private folder that keeps each session's tool definitions across a gateway restart |
| `--cache-ttl 5m\|1h` | Prompt-cache lifetime, default `5m` ([caching](#prompt-caching-and-the-monitor)) |
| `--thinking-prefix-mismatch error\|drop_block\|api_default` | What the API does with a replayed thinking block whose history changed, default `error` ([thinking blocks](#thinking-blocks-compaction-and-forks)) |
| `--compaction-tool-choice none\|auto` | `tool_choice` for a request in which Codex declares no tools, default `none` |

Do not restart the gateway while runs are live: a request in flight fails, and without
`--state-dir` a session's next compaction request is refused.

### 2. Give Codex the local key

Two keys are involved, and they never mix:

| Key | Holder | Where it lives |
| --- | --- | --- |
| Anthropic API key | The gateway only | `--anthropic-key-file`, or `ANTHROPIC_API_KEY` in the gateway's own environment |
| Local gateway key | Codex and the gateway | The `--key-file`; Codex reads it from `ROBOTEAM_CLAUDE_GATEWAY_KEY` |

Fill in the `ROBOTEAM_CLAUDE_GATEWAY_KEY=` line of the checkout's `.env` with the value of
`"key"` in the key file. Runs read `.env` themselves, so a background batch finds it there.

Keep both key files, the log and the state folder under `~/.roboteam/`, which the access table
closes to the agents, and out of every checkout and evidence folder.

### 3. Preflight, prepare and run

```sh
curl -s http://127.0.0.1:18470/healthz
.venv/bin/roboteam preflight --harness codex --model opus_claude_api --confirm-spend
.venv/bin/roboteam prepare --harness codex --model opus_claude_api --level 1 --min-arms \
  --parallel 4 --output runs/policy/codex-claude-l1
.venv/bin/roboteam run runs/policy/codex-claude-l1
```

Use the same `--config` and options for `preflight` and `prepare`, and keep the default
`runtime.codex_home_scope = "task"`. `preflight` makes paid calls: an image and a tool round
trip, a manual compaction and a fork whose child inherits history. Afterwards read the gateway
log: every request should be `completed`, with no `thinking_blocks_dropped`, and with cache
reads on the second and later requests. A receipt covers its exact model, model catalog, CLI
and tool mode. It says nothing about long sessions.

### 4. Watch the prompt cache (optional)

```sh
.venv/bin/python roboteam/harness/adapters/claude_in_codex/monitor.py \
  ~/.roboteam/codex-claude/transport-metadata.jsonl \
  --batch runs/policy/codex-claude-l1 --min-hit-rate 0.7
```

The monitor only reads the log. It never stops, pauses or changes a run.
[Prompt caching and the monitor](#prompt-caching-and-the-monitor) explains its columns.

## How it works

### The model entry

`opus_claude_api` in the `codex` section of `models.json`:

| Field | Value |
| --- | --- |
| `model`, `effort`, `vision` | `claude-opus-5-5`, `high`, `true` |
| `provider` | `claude_gateway` (Responses wire API, no OpenAI authentication, no WebSockets) |
| `transport`, `transport_revision` | `loopback_gateway`, `messages-adapter-v1` |
| `base_url` | `http://127.0.0.1:18470/v1` |
| `env_key` | `ROBOTEAM_CLAUDE_GATEWAY_KEY`: the local gateway key, not an Anthropic key |
| `upstream_host` | `api.anthropic.com`, the host the [outage probe](../runs/time.md#network-outage-pause) watches |
| `context_capacity` | 1,000,000; the run still uses the 300,000-token window and the 267,000-token compaction limit of every Codex model |

Plain HTTP is accepted only for a model that declares `transport: loopback_gateway`, and then
only for the literal `http://127.0.0.1:PORT`. The model and its revision are part of the
receipt, so a receipt from another adapter revision does not admit a run. For this model only,
the harness also:

- checks `GET /healthz` before a preflight or a run and refuses to start unless the listener
  reports this model and transport revision, so the local key is not sent to another process;
- tells Codex that the model accepts images and turns off the `text.verbosity` request control,
  an OpenAI-only setting the gateway would reject;
- removes `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from the environment of every Codex
  process it starts, so Codex holds the local key only, and keeps the local key out of the
  agents' shells.

### Trust boundaries

The gateway listens on `127.0.0.1` only and answers model requests only to a caller that
presents the local key. Neither key is accepted on a command line. The gateway refuses to start
with `ANTHROPIC_AUTH_TOKEN` set, ignores `ANTHROPIC_BASE_URL` and sends the API key only to
`https://api.anthropic.com`. (A hidden `--upstream-base-url` option points it at a local
stand-in on `127.0.0.1` for tests.)

A run's frozen permission profile has `network: false`, so a command in an agent's sandboxed
shell cannot connect to the gateway port, and the launch settings keep the local key and the
Anthropic variables out of shell environments. A run prepared with shell network access
switched on would make the port reachable; do not use this adapter that way.

`GET /healthz` checks the local listener only and reports `inference_verified: false`.
`GET /stats` (local key required) returns the cache counters the monitor shows.

### What is translated

| Codex Responses | Anthropic Messages |
| --- | --- |
| `instructions` and the developer messages before any other item | `system` text blocks, with a cache breakpoint on the last |
| Later developer messages | Text in the user turn at the same position, wrapped in `<system-reminder>` |
| User text and `input_image` (inline data or HTTPS URL) | `text` and `image` blocks |
| `function_call` / `function_call_output` | `tool_use` / `tool_result`; all results of one assistant turn in one user turn, parallel calls kept together |
| Images inside a tool output | `image` blocks inside that `tool_result` |
| A freeform `custom` tool (`apply_patch`) and its calls | A tool with one string field `input`; the grammar is quoted in the description |
| `namespace` tools | Tools named `namespace__name`, mapped back on the way out |
| `reasoning` items | The original `thinking` / `redacted_thinking` block ([below](#thinking-blocks-compaction-and-forks)) |
| `reasoning.effort` | `output_config.effort`, always sent explicitly |
| `max_output_tokens` | `max_tokens`; 64,000 when Codex sends none |
| `tool_choice: auto` or `none`, `parallel_tool_calls: false` | The same choice, `disable_parallel_tool_use` |

Rejected with HTTP 400 before any call to Anthropic: another model, non-streaming requests,
`store: true`, `previous_response_id`, forced tool choice, sampling parameters, `text` controls,
reasoning summaries, effort `none` or `minimal`, hosted tools (web search, local shell, image
generation), file inputs, image file IDs, inline images that are not JPEG, PNG, GIF or WebP, an
unknown image `detail` value, reasoning items this gateway did not produce, a tool call without
its output, and any unknown request field or input item. Five request fields that carry no
content for the model are accepted and ignored: `prompt_cache_key`, `client_metadata`,
`metadata`, `user` and `safety_identifier`.

`GET /v1/models` returns the one model. Any other route returns 404, including
`POST /v1/responses/compact`: Codex 0.165.0 compacts through ordinary `/v1/responses` requests.
A request without the local key gets 401.

Known limits:

- **Developer messages after the first turn** (Codex sends its context again after compaction
  and adds notices such as `<turn_aborted>`) become user-turn text, not system messages. Moving
  them into `system` would rewrite the start of every earlier turn.
- **Freeform tools** lose grammar-constrained decoding: Claude sees the grammar as text. A
  malformed patch is rejected by Codex's own parser and reported back as a tool error.
- **Image `detail`** has no Messages equivalent and is not translated. Images are passed as
  received: the gateway never resizes, trims or drops them. Count, size and resolution limits
  are Anthropic's ([vision guide](https://platform.claude.com/docs/en/build-with-claude/vision));
  an oversized request fails at Anthropic with an explicit error.
- **Tool arguments** are replayed as parsed JSON. Key order is kept; a number written as `1.50`
  is replayed as `1.5`.
- **Text is not streamed piece by piece.** The whole answer is held until the Anthropic message
  has ended, then released in order. While waiting, the gateway forwards `response.in_progress`
  keep-alives so that Codex's idle timer does not fire.
- **Reasoning text is not shown.** Codex receives reasoning items with an empty summary and
  opaque content.
- **No conversation store.** Each request must carry its whole history, which Codex does with
  `store: false`.

### Thinking blocks, compaction and forks

Claude Opus 5.5 always thinks, and its thinking blocks are tied to the model and to the
conversation that produced them: the `system` prompt, the tool set and every earlier message
must come back unchanged, or the block is invalid. The gateway therefore never edits history.

Each thinking block travels to Codex as one `reasoning` item whose `encrypted_content` holds
the exact block, signature included, behind a version prefix. Codex does not read it. When
Codex sends the item back, the gateway restores the same block at the same position. A
reasoning item from another provider, or a damaged one, is an error; the gateway never invents,
repairs or silently removes a block.

| Codex event | Request Codex sends | Result |
| --- | --- | --- |
| Next request in a turn, or a new turn | The previous history plus new items | Append-only: blocks stay valid |
| `thread/fork` (a delegate snapshot and its children) | The parent's history unchanged up to the pending call, an `aborted` output for it, then the child's input | A branch of an unchanged start: the parent's blocks stay valid in the child |
| Compaction request | The whole history plus a summary prompt, with `tools: []` | A changed tool set would invalidate every replayed block. The gateway sends the session's own tool definitions again, so the request is append-only, and sets `tool_choice: none` so no tool can be called |
| First request after compaction | Base instructions, earlier user messages without images, the context sent again and the summary; no assistant or reasoning items | Nothing older is replayed, so there is no block to check |

The gateway remembers each session's tool definitions by Codex session ID (the `session-id`
header), in memory and in `--state-dir` when given. A request without tools that replays tool
calls of a session the gateway does not know is refused.

`--compaction-tool-choice none` (the default) reproduces what a GPT model gets from Codex: no
tool can be called while summarizing. Changing `tool_choice` makes that one request miss the
conversation cache. `auto` keeps the cache hit, but if Claude then calls a tool the gateway
fails the response, because Codex cannot run a tool during compaction.

`--thinking-prefix-mismatch error` (the default) sends
`thinking.block_binding.prefix_mismatch_behavior: "error"` under the
`thinking-binding-controls-2026-08-01` beta on every request, so a changed history fails with
an HTTP 400 instead of silently losing reasoning. `drop_block` lets the API drop the affected
blocks and continue; the log then records `thinking_blocks_dropped` for that request, and the
monitor's `--json` summary gives the total. `api_default` sends neither the field nor the beta
header.

A summary written at compaction is all that later turns have of the earlier reasoning, as with
every Codex model. Codex's own compaction prompt is used unchanged.

### Prompt caching and the monitor

The cacheable start of a request is the tools, then `system`, then the conversation. The
gateway sorts tools by name, serializes them the same way every time, puts nothing that changes
into that start, places one explicit breakpoint on the last `system` block and enables
automatic caching, which moves a second breakpoint along the growing conversation. A healthy
session reads everything sent before and writes only what the last step added.

Expect cache misses on the first request of a session, after compaction, on a compaction
request with `tool_choice: none`, and whenever two requests of a session start more than the
cache lifetime apart. With `--cache-ttl 1h` both breakpoints use the one-hour lifetime: writes
cost 2 times input instead of 1.25 times, which pays off only if gaps of 5 to 60 minutes are
common, for example a role that waits on a long robot action.

Every request adds one line to the `--log` file: time, duration, HTTP status, outcome, stop
reason, token counts as Anthropic reported them (uncached input, cache read, cache creation in
total and by lifetime, output, thinking), counts of messages, images and tool results, short
hashes of the tools, the system prompt and the two together (`prefix_sha256`), the Codex
session, thread and installation IDs, the fork source, the request kind (`turn` or
`compaction`), the gateway key's label and Anthropic's request ID. It never holds prompts, tool
arguments, images, headers or keys.

A request is attributed to a run by its `run` field: the label of the gateway key it used, or,
with the single default key, `codex-` plus the first eight characters of the Codex installation
ID (`unknown` when Codex sent none). With `runtime.codex_home_scope = "task"` every run has its
own Codex home and installation ID, so parallel runs are told apart without further setup. To
label runs by hand, give the key file as `{"keys": {"label": "key", ...}}`.

The monitor prints, every five seconds, per run and overall: requests, cache-hit rate
(cumulative and over the last ten minutes, `--window-s`), cache-creation share, input and
output tokens and an estimated cost. `--batch` shows run folder names in place of installation
IDs. `--once --json` prints one summary for scripts.

| Column | Meaning |
| --- | --- |
| Hit rate | `cache_read / (uncached + cache_read + cache_creation)`, the same definition as `cache_hit_rate` in the [run report](README.md#reports-and-metric-definitions) |
| Write | The cache-creation share of input. Near the full conversation size on every request means the cached start is being rewritten |
| Cost | An estimate from the list prices in the script (input 4 USD, output 20 USD, cache read 0.20 USD per million tokens; five-minute writes 1.25 times and one-hour writes 2 times input). It is not a provider invoice |

`--min-hit-rate` marks a row `WARNING` when its rate over the window is below the threshold
after `--min-requests` requests (default 20); `--once` then exits with status 2. A low rate
usually means that the cached start changes between requests (more than one `prefix_sha256`
for a run) or that gaps are longer than the cache lifetime. A dip right after each compaction
is expected.

Inside Codex, usage is reported the way the benchmark already reads it: `input_tokens` is
uncached input plus cache reads plus cache writes, `cached_tokens` is cache reads,
`cache_write_tokens` is cache writes, and output tokens include thinking.

### Errors and retries

| Outcome at Anthropic | What Codex receives |
| --- | --- |
| HTTP 401, 403, 404, 413 | The same status and Anthropic's message |
| HTTP 429, 529 | The same status and `Retry-After` |
| HTTP 500, 502 (no answer from the API) | The same status |
| HTTP 400, including an invalid thinking block | 400 with Anthropic's message |
| A stream error, or a stream that ends early | `response.failed` |
| `stop_reason: refusal` | `response.failed` with code `invalid_prompt` and the category |
| `stop_reason: max_tokens` | `response.incomplete` (`max_output_tokens`) |
| Another model in the answer | `response.failed` |

Nothing from a failed, refused or truncated answer is released: Codex executes a tool call as
soon as it sees one, so the gateway holds the whole answer until `message_stop`. The SDK runs
with `max_retries=0`; only Codex retries, and only whole requests. A refusal is never sent to
another model.

## Tests

```sh
.venv/bin/python -m scripts.dev.run_tests harness.adapters.test_codex_claude_gateway \
  harness.adapters.test_codex_claude_monitor harness.adapters.test_codex_claude_api
PYTHONPATH=tests:tests/helpers .venv-gateway/bin/python -m unittest harness.adapters.test_codex_claude_gateway
```

The first command runs in the benchmark's own environment: translation in both directions, the
monitor's arithmetic and the model rules. When `.venv-gateway` (or `ROBOTEAM_GATEWAY_PYTHON`)
has the SDK and `codex` and `node` are on `PATH`, it also drives the installed Codex CLI through
the gateway against a local stand-in for the Anthropic API: an image attachment, two parallel
tool calls whose results carry images, reasoning replayed over several turns, a sandboxed shell
command, a freeform patch, a manual compaction and a fork with a pending tool call. The second
command adds the HTTP tests that need the SDK: authentication, status and `Retry-After`
mapping, refusals, truncated and failing streams, and the log.

No test contacts a model provider. They check the translation. They do not show that Anthropic
accepts the requests, that the cache hits or how the model behaves; the paid preflight is the
first real contact with the API.

## References

- [Codex gateway requirements](https://learn.chatgpt.com/docs/enterprise/gateway-compatibility)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
- [Claude refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback)
- [Claude vision limits](https://platform.claude.com/docs/en/build-with-claude/vision)
