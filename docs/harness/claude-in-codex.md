# Experimental Codex / Claude ablation

This adapter is RoboTeam code, not an official OpenAI or Anthropic connector. OpenAI does
not support routing the Codex CLI to Claude, and Anthropic does not support Codex as a client.
A passing preflight qualifies only the measured combination; it does not establish parity with
native Claude Code or with Codex on a GPT model.

The native Codex CLI owns tool execution, sessions, compaction and forks. A loopback process,
[`roboteam/harness/adapters/claude_in_codex/gateway.py`](../../roboteam/harness/adapters/claude_in_codex/gateway.py), translates the
Responses requests Codex sends into Anthropic Messages requests and the streamed answer back.
It does not run an agent loop, execute tools or store conversations. Every upstream request
selects `claude-opus-5-5` with adaptive thinking and the effort Codex asked for (`high` in the
benchmark), through the official `anthropic` Python SDK. A different requested model is an
error. There is no model fallback, no credential fallback, no server-side `fallbacks`
parameter and no automatic replay. What cannot be translated is rejected with an explicit
error, never dropped.

## Credentials and trust

Two different keys are involved, and they never mix:

| Key | Holder | Where it lives |
| --- | --- | --- |
| Anthropic API key | The gateway process only | An owner-only file given with `--anthropic-key-file`, or `ANTHROPIC_API_KEY` in the gateway's own environment |
| Local gateway key | Codex (as `ROBOTEAM_CLAUDE_GATEWAY_KEY`) and the gateway | A random key in the owner-only `--key-file`, created on first start |

Neither key is accepted on a command line. The gateway refuses to start with
`ANTHROPIC_AUTH_TOKEN` set, ignores `ANTHROPIC_BASE_URL`, and sends the API key only to
`https://api.anthropic.com`. It listens on `127.0.0.1` only and answers model requests only
to a caller that presents the local key. Keep both files, the log and the state folder under
`~/.roboteam/`, which the [access table](codex.md#isolation) closes to the policy, and
out of every checkout and evidence folder. Keep the Anthropic key out of the batch's `.env`
if you can; if it is there for a Claude Code model, the harness removes `ANTHROPIC_API_KEY`
and `ANTHROPIC_AUTH_TOKEN` from the environment of every Codex process it starts for this
model, so Codex holds the local key only.

What a model shell can reach, measured on macOS with the pinned CLI and the native tool
backend: with the frozen `network: false` permission profile a sandboxed command cannot
connect to the gateway port (`curl` exits 7, a TCP connect fails with `Operation not
permitted`), and the launch configuration excludes the local key and the Anthropic variables
from shell environments. The offline native test asserts both. A run prepared with shell
network access switched on would make the port reachable; this transport is not meant for
that configuration. The `landlock-v1` backend denies sockets to its subprocesses but has not
been exercised with this model.

## Start the gateway

The SDK is an optional dependency, kept out of the core environment:

```sh
python3 -m venv .venv-gateway
.venv-gateway/bin/python -m pip install -r roboteam/harness/adapters/claude_in_codex/requirements.txt
mkdir -p -m 700 ~/.roboteam/secrets ~/.roboteam/codex-claude
# Put the Anthropic key, alone, in ~/.roboteam/secrets/anthropic-api-key.txt (chmod 600).

.venv-gateway/bin/python roboteam/harness/adapters/claude_in_codex/gateway.py \
  --anthropic-key-file ~/.roboteam/secrets/anthropic-api-key.txt \
  --key-file ~/.roboteam/secrets/codex-claude-gateway-key.json \
  --log ~/.roboteam/codex-claude/transport-metadata.jsonl \
  --state-dir ~/.roboteam/codex-claude/state
```

| Option | Meaning |
| --- | --- |
| `--port` | Loopback port, default 18470 (the one in the checked-in model) |
| `--cache-ttl 5m\|1h` | Prompt-cache lifetime, default `5m`; see [caching](#prompt-caching-and-the-live-monitor) |
| `--thinking-prefix-mismatch error\|drop_block\|api_default` | What the API does with a replayed thinking block whose history changed, default `error`; see [thinking blocks](#thinking-blocks-compaction-and-forks) |
| `--compaction-tool-choice none\|auto` | `tool_choice` for a request in which Codex declares no tools, default `none` |
| `--state-dir` | Private folder that keeps each session's tool definitions across a gateway restart |
| `--log` | Metadata-only JSONL; without it nothing is stored |

`GET /healthz` checks the local listener only and reports `inference_verified: false`.
`GET /stats` (local key required) returns the cache counters of the
[monitor](#prompt-caching-and-the-live-monitor). The gateway keeps running between batches;
do not restart it while runs are live: an in-flight request fails, and without `--state-dir`
a session's next compaction request is refused.

## Model and launch behavior

`opus_claude_api` in the `codex` section of `models.json`:

| Field | Value |
| --- | --- |
| `model`, `effort`, `vision` | `claude-opus-5-5`, `high`, `true` |
| `provider` | `claude_gateway` (Responses wire API, no OpenAI authentication, no WebSockets) |
| `transport`, `transport_revision` | `loopback_gateway`, `messages-adapter-v1` |
| `base_url` | `http://127.0.0.1:18470/v1` |
| `env_key` | `ROBOTEAM_CLAUDE_GATEWAY_KEY`: the local gateway key, not an Anthropic key |
| `upstream_host` | `api.anthropic.com`, the host the [outage probe](../runs/continuation.md#network-outage-pause) watches |
| `context_capacity` | 1,000,000; the run still uses the catalog's 300,000 window and 267,000 compaction limit |

Plain HTTP is accepted only for a model that declares `transport: loopback_gateway`, and
then only for the literal `http://127.0.0.1:PORT`; every other model still needs HTTPS.
The model and its revision are part of the receipt fingerprint, so a receipt from another
adapter revision does not qualify a run. For this model only, the harness also:

- checks `GET /healthz` before a preflight or a run and refuses to start unless the listener
  reports this model and transport revision, so the local key is not sent to another process;
- tells Codex the model accepts images and, as for every non-OpenAI model, writes the
  per-run model catalog with the shared tool configuration; it additionally turns off the
  `text.verbosity` request control, an OpenAI-only setting the adapter would reject;
- excludes the local key from model shells and strips Anthropic credentials from Codex's
  environment, as described above;
- refuses the container and Slurm entries: their loopback interface is not the host's.

## What is translated, and the limits

| Codex Responses | Anthropic Messages |
| --- | --- |
| `instructions` and the developer messages before any other item | `system` text blocks, cache breakpoint on the last |
| Later developer messages | Text in the user turn at the same position, wrapped in `<system-reminder>` |
| User text and `input_image` (inline data or HTTPS URL) | `text` and `image` blocks |
| `function_call` / `function_call_output` | `tool_use` / `tool_result`; all results of one assistant turn in one user turn, parallel calls kept together |
| Images inside a tool output | `image` blocks inside that `tool_result` |
| Freeform `custom` tool (`apply_patch`) and its calls | A tool with one string field `input`; the grammar is quoted in the description |
| `namespace` tools (`collaboration`) | Tools named `namespace__name`, mapped back on the way out |
| `reasoning` items | The original `thinking` / `redacted_thinking` block, see below |
| `reasoning.effort` | `output_config.effort`, always sent explicitly |
| `max_output_tokens` | `max_tokens`, 64,000 when Codex sends none |
| `tool_choice: auto`, `parallel_tool_calls: false` | `auto`, `disable_parallel_tool_use` |

Rejected with HTTP 400 before any upstream call: another model, non-streaming requests,
`store: true`, `previous_response_id`, forced tool choice, sampling parameters, `text`
controls, reasoning summaries, effort `none`/`minimal`, hosted tools (web search, local
shell, image generation), file inputs, image file IDs, image types other than JPEG, PNG, GIF
and WebP, reasoning items this gateway did not produce, a tool call without its output and
any unknown request field or input item. `POST /v1/responses/compact` and every other route
return 404; Codex 0.165.0 compacts a custom provider through ordinary `/v1/responses`
requests.

Known limits:

- **Developer messages after the first turn** (Codex re-sends its context after compaction
  and adds notices such as `<turn_aborted>`) are user-turn text, not system-authority
  messages. Moving them into `system` would rewrite the prefix of every earlier turn.
- **Freeform tools** lose grammar-constrained decoding: Claude sees the grammar as text.
  A malformed patch is rejected by Codex's own parser and reported back as a tool error.
- **Image `detail`** has no Messages equivalent and is not translated. Images are passed
  as received: the gateway never resizes, trims or drops them. Count, size and resolution
  limits are Anthropic's ([vision guide](https://platform.claude.com/docs/en/build-with-claude/vision));
  an oversized request fails upstream with an explicit error. No limit was measured offline.
- **Schema annotations** such as OpenAI's `"encrypted": true` on the native collaboration
  tools pass through unchanged. Whether the API accepts them is settled only by the live
  preflight.
- **Tool arguments** are replayed as parsed JSON. Key order is kept; a number written as
  `1.50` is replayed as `1.5`, which the API's history check treats as equal.
- **Text is not streamed incrementally.** The whole answer is held until the upstream
  message has ended, then released in order. While waiting, the gateway forwards
  `response.in_progress` keep-alives so Codex's idle timer does not fire.
- **Reasoning text is not shown.** Thinking uses the default display; Codex receives
  reasoning items with an empty summary and opaque content.
- **No conversation store.** Each request must carry its whole history, which Codex does
  with `store: false`.

## Thinking blocks, compaction and forks

Claude Opus 5.5 cannot run without thinking, and its thinking blocks are bound to the model
and to the conversation that produced them: the `system` prompt, the tool set and every
earlier message must come back unchanged, or the block is invalid. The gateway therefore
never edits history.

Each thinking block travels to Codex as one `reasoning` item whose `encrypted_content` holds
the exact block, signature included, behind a version prefix. It is opaque to Codex, not
encrypted. When Codex replays the item the gateway restores the same block at the same
position. A reasoning item from another provider, or a damaged one, is an error; the gateway
never invents, repairs or silently removes a block.

What Codex 0.165.0 does to history, observed with the real CLI against a local stub, and how
that meets the binding rules:

| Codex event | Request Codex sends | Result |
| --- | --- | --- |
| Next request in a turn or a new turn | Previous history plus new items | Append-only: blocks stay valid |
| `thread/fork` (delegate snapshot and children) | The parent's history unchanged up to the pending call, an `aborted` output for it, then the child's input | A branch of an unchanged prefix: the parent's blocks stay valid in the child |
| Compaction request | The whole history plus a summary prompt, with `tools: []` | A changed tool set would unbind every replayed block (and the Messages API needs the tools that the history's calls refer to). The gateway sends the session's own tool definitions again, so the request is append-only, and sets `tool_choice: none` so no tool can be called |
| First request after compaction | Base instructions, earlier user messages without images, the re-sent context and the summary; no assistant or reasoning items | Simple compaction: nothing older is replayed, so there is no block to check |

The session's tool definitions are remembered per Codex session ID (the `session-id` header)
in memory, and in `--state-dir` when given. A tool-less request that replays tool calls for a
session the gateway does not know is refused rather than patched up.

`--compaction-tool-choice none` (the default) reproduces what a GPT model gets from Codex: no
tool can be called while summarizing. Changing `tool_choice` makes that one request miss the
conversation cache; at a 267,000-token limit that is about 1 USD per compaction at list
prices. `auto` keeps the cache hit, but if Claude then calls a tool the gateway fails the
response, because Codex cannot run a tool during compaction.

`--thinking-prefix-mismatch error` (the default) sends
`thinking.block_binding.prefix_mismatch_behavior: "error"` under the
`thinking-binding-controls-2026-08-01` beta on every request, so a history edit that this
analysis missed fails loudly with an HTTP 400 instead of silently losing reasoning, whatever
the account's age. `drop_block` lets the API drop the affected blocks and continue; the log
then records `thinking_blocks_dropped` for that request and the monitor shows the total.
`api_default` sends neither the field nor the beta header.

A summary written at compaction is the only thing later turns have of the earlier reasoning,
as on every Codex model. Codex's own compaction prompt is used unchanged.

## Prompt caching and the live monitor

The cacheable prefix is tools, then `system`, then the conversation. The gateway sorts tools
by name, serializes deterministically, puts nothing volatile into the prefix, places one
explicit breakpoint on the last `system` block and enables automatic caching, which moves a
second breakpoint along the growing conversation. A healthy session reads everything sent
before and writes only what the last step added. Expect misses on the first request of a
session, after compaction (the conversation is new), on a compaction request with
`tool_choice: none`, and whenever two requests of a session start more than the cache
lifetime apart. With `--cache-ttl 1h` both breakpoints use the one-hour lifetime: writes cost
2x instead of 1.25x input, which pays off only if gaps of 5 to 60 minutes are common, for
example a role that waits on a long robot action.

Every request adds one line to the `--log` file: time, duration, HTTP status, outcome, stop
reason, token counts as Anthropic reported them (uncached input, cache read, cache creation
in total and by lifetime, output, thinking), counts of messages, images and tool results,
short hashes of the tools, the system prompt and the two together (`prefix_sha256`), the
Codex session, thread and installation IDs, the fork source, the request kind (`turn` or
`compaction`), the gateway key's label and the upstream request ID. Never prompts, tool
arguments, images, headers or keys.

A request is attributed to a run by `run`: the label of the gateway key it used, or, with the
single default key, `codex-` plus the first eight characters of the Codex installation ID.
With the default `runtime.codex_home_scope = "task"` every run has its own Codex home and
installation ID, so parallel runs are told apart without further setup. To label runs by hand
instead, give the key file as `{"keys": {"label": "key", ...}}`.

Watch the cache while a batch runs, from any terminal:

```sh
.venv/bin/python roboteam/harness/adapters/claude_in_codex/monitor.py ~/.roboteam/codex-claude/transport-metadata.jsonl \
  --batch runs/policy/codex-claude-l1 --min-hit-rate 0.7
.venv/bin/python roboteam/harness/adapters/claude_in_codex/monitor.py LOG --once --json --min-hit-rate 0.7   # for scripts
```

It reprints every five seconds, per run and overall: requests, cache-hit rate (cumulative
and over the last ten minutes, `--window-s`), cache-creation share, input and output tokens
and an estimated cost. `--batch` shows run folder names in place of installation IDs.

- **Hit rate** is `cache_read / (uncached + cache_read + cache_creation)`, the same
  definition as `cache_hit_rate` in the [run report](README.md#reports-and-metric-definitions).
- **Write** is the cache-creation share of input. Near the full conversation size on every
  request means the prefix is being rewritten.
- **Cost** is an estimate from the list prices in the script (input 4 USD, output 20 USD,
  cache read 0.20 USD per million tokens; five-minute writes 1.25x and one-hour writes 2x
  input). It is not a provider invoice.
- `--min-hit-rate` marks a row `WARNING` when its rolling rate is below the threshold after
  `--min-requests` requests in the window (default 20); `--once` then exits with status 2.
  The monitor only reads the log. It never stops, pauses or changes a run.

A low rate usually means a volatile prefix (more than one `prefix_sha256` for a run, a tool
set or system prompt that changes between requests) or gaps longer than the cache lifetime.
A dip right after each compaction is expected.

Inside Codex, usage is reported the way the benchmark already reads it: `input_tokens` is
uncached input plus cache reads plus cache writes, `cached_tokens` is cache reads,
`cache_write_tokens` is cache writes, and output tokens include thinking. The run report's
`cache_hit_rate` therefore has the same meaning as for the Claude Code harness.

## Errors and retries

| Upstream outcome | What Codex receives | Codex 0.165.0 then |
| --- | --- | --- |
| HTTP 401, 403, 404, 413 | The same status and Anthropic's message | Retries three times, then fails the turn |
| HTTP 429, 529 | The same status and `Retry-After` | Waits as told; 429 up to four attempts |
| HTTP 500, 502 (no answer from the API) | The same status | Retries with backoff |
| HTTP 400, including an invalid thinking block | 400 with Anthropic's message | Fails the turn at once |
| Stream error or a stream that ends early | `response.failed` | Retries the request |
| `stop_reason: refusal` | `response.failed` with code `invalid_prompt` and the category | Fails the turn at once, no retry |
| `stop_reason: max_tokens` | `response.incomplete` (`max_output_tokens`) | Fails the turn at once |
| Another model in the answer | `response.failed` | Fails the turn at once |

Nothing from a failed, refused or truncated answer is released: Codex executes a tool call as
soon as it sees one and replays partial output on a retry, so the gateway holds the whole
answer until `message_stop`. The SDK runs with `max_retries=0`; only Codex retries, and only
whole requests. A refusal is never sent to another model.

## Offline checks

```sh
.venv/bin/python -m scripts.dev.run_tests harness.adapters.test_codex_claude_gateway harness.adapters.test_codex_claude_monitor harness.adapters.test_codex_claude_api
PYTHONPATH=tests:tests/helpers .venv-gateway/bin/python -m unittest harness.adapters.test_codex_claude_gateway
```

The first command runs in the core environment: translation in both directions, the monitor
arithmetic, the model rules and, when `.venv-gateway` (or `ROBOTEAM_GATEWAY_PYTHON`)
has the SDK, the native test. That test drives the installed Codex CLI through the gateway
against a local stand-in for the Anthropic API: an image attachment, two parallel tool calls
whose results carry images, reasoning replayed over several turns, a sandboxed shell command,
a freeform patch, a manual compaction and a fork with a pending tool call. The second command
adds the HTTP tests that need the SDK: authentication, status and `Retry-After` mapping,
refusals, truncated and failing streams, and the log. No test contacts a model provider. They
verify the transport invariants; they do not show that Anthropic accepts these requests, that
the cache hits, or how the model behaves.

## Live preflight, prepare and run

Only after the offline checks pass and the spend is approved. Start the gateway as above,
then, in the shell that runs the commands:

```sh
curl -s http://127.0.0.1:18470/healthz
export ROBOTEAM_CLAUDE_GATEWAY_KEY="$(.venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["key"])' \
  ~/.roboteam/secrets/codex-claude-gateway-key.json)"
.venv/bin/roboteam preflight --harness codex --model opus_claude_api --confirm-spend
.venv/bin/roboteam prepare --harness codex --model opus_claude_api --level 1 --min-arms --parallel 4 --output runs/policy/codex-claude-l1
.venv/bin/roboteam run runs/policy/codex-claude-l1
```

A service that does not inherit the shell (launchd on macOS, a durable Linux service) reads
the variable from the checkout's Git-ignored `.env` instead; add a
`ROBOTEAM_CLAUDE_GATEWAY_KEY=` line there. Use the same `--config` and options for
`preflight` and `prepare`, and the default `runtime.codex_home_scope = "task"`.

The preflight is the first real contact with the API. It exercises an image and function
round trip, a manual compaction and a fork whose child inherits history, which are exactly
the cases above. Read its log lines afterwards: every request `completed`, no
`thinking_blocks_dropped`, cache reads on the second and later requests. A passed receipt
qualifies its exact model, catalog, CLI and tool mode; it is not a context-capacity stress
test and says nothing about long sessions.

## Not yet established

- Any live behavior: acceptance of the translated requests (in particular the tool schemas
  and the beta header), cache-hit rates, refusal frequency, rate limits and cost.
- Automatic compaction at 267,000 tokens and behavior near the 64,000-token output limit.
  The offline test compacts by hand in a short session.
- More than one fork level, forks taken after a compaction of the child, and resume after a
  host restart. The transport is stateless apart from the tool memory, but none was run.
- The `landlock-v1` and `robot_only` configurations with this model.
- Comparability: equal effort names do not mean equal computation, the context is capped at
  300,000 tokens although the model accepts more, and Codex's prompts were written for GPT
  models.

Official references:

- [Codex gateway requirements](https://learn.chatgpt.com/docs/enterprise/gateway-compatibility)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
- [Claude refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback)
- [Claude vision limits](https://platform.claude.com/docs/en/build-with-claude/vision)
