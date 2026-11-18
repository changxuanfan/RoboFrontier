# GPT in Claude Code (optional adapter)

This adapter lets the Claude Code harness run GPT-6.1 Sol. You need it only for one comparison:
the same model in the other harness. Ordinary Claude Code runs (`opus`) and ordinary Codex runs
(`sol`) do not use it.

It is a local process, the *gateway*, that listens on `127.0.0.1`. Claude Code sends it the
requests it would send to Anthropic's Messages API, and the gateway translates them into
requests to OpenAI's Responses API and translates the answers back. The Claude Code CLI still
runs the tools, keeps the sessions, compacts and forks. The gateway does not run Codex's agent
loop.

The adapter is RoboTeam code. Anthropic does not support routing Claude Code to models that are
not Claude. A passed preflight admits runs of this exact combination; it does not make the
results equivalent to Codex with GPT-6.1 Sol, or to Claude Code with Claude.

| Limit | |
| --- | --- |
| Model | `gpt-6.1-sol` only, at effort `high`, with `store: false`, over the Responses WebSocket interface. There is no fallback to another model, account or credential |
| OpenAI account | A ChatGPT plan that you authorize for this use (the default), or an OpenAI API key (`--auth-mode openai_api_key`) |
| Gateway check | Unlike [Claude in Codex](claude-in-codex.md), the harness does not check that the gateway is running before a run. Check it yourself (step 2) |

## Use it

### 1. Install and sign in

The adapter's dependencies are optional and kept out of the benchmark's own environment:

```sh
python3 -m venv .venv-gateway
.venv-gateway/bin/python -m pip install -r roboteam/harness/adapters/gpt_in_claude/requirements.txt
mkdir -p -m 700 ~/.roboteam/chatgpt-plan
.venv-gateway/bin/python roboteam/harness/adapters/gpt_in_claude/auth.py login \
  --credential-file ~/.roboteam/chatgpt-plan/account.json
```

Follow the printed OpenAI sign-in link. It registers this self-hosted application and asks for
the `chatgpt.tokens.use.direct` permission. It does not give access to your ChatGPT
conversation history. Before saving the credential, the helper checks the state, PKCE, the ID
token's signature, issuer, audience, expiry and nonce, and the granted scopes.
`auth.py status --credential-file FILE` shows the saved state.

Keep the credential file outside every checkout and evidence folder, readable by you only.
`~/.roboteam/` is closed to the agents by the access table. Let one machine own the credential:
two gateways that refresh the same rotating token will invalidate each other.

To bill an OpenAI API key instead, skip the sign-in, put the key alone in a file and start the
gateway with `--auth-mode openai_api_key --credential-file FILE`. This mode never reads or
refreshes a ChatGPT plan credential.

### 2. Start the gateway

```sh
.venv-gateway/bin/python roboteam/harness/adapters/gpt_in_claude/gateway.py \
  --credential-file ~/.roboteam/chatgpt-plan/account.json \
  --key-file ~/.roboteam/chatgpt-plan/gateway-key.json \
  --log ~/.roboteam/chatgpt-plan/transport-metadata.jsonl
curl -s http://127.0.0.1:18461/health
```

| Option | Meaning |
| --- | --- |
| `--credential-file` | Required. The saved sign-in, or the API key file with `--auth-mode openai_api_key` |
| `--key-file` | Required. Holds the local gateway key; created with a random key on first start |
| `--auth-mode chatgpt_plan\|openai_api_key` | Which OpenAI credential is used, default `chatgpt_plan`. `/health` and every log line report the mode in use |
| `--port` | Loopback port, default 18461 (the one in `models.json`) |
| `--log` | A JSONL file with one line of metadata per request |
| `--replay-file` | Where the gateway keeps the model's original outputs; default `response-replay.sqlite` beside the credential file ([below](#original-outputs-are-replayed-exactly)) |
| `--native-session-index` | A file, written by the host, that maps session IDs to their transcripts ([below](#sessions-and-forks)) |
| `--tokens-per-minute N` | For an API project with a token-per-minute limit: admit requests through one queue shared by all sessions ([below](#errors-and-limits)) |

### 3. Give Claude Code the local key

Claude Code receives only the local gateway key, never the OpenAI credential. Add this line to
the checkout's `.env`, with the value of `"key"` in the key file:

```text
ROBOTEAM_CHATGPT_GATEWAY_KEY=<the key>
```

### 4. Preflight, prepare and run

```sh
.venv/bin/roboteam preflight --harness claude --model sol_chatgpt_plan --max-budget-usd 1 --confirm-spend
.venv/bin/roboteam prepare --harness claude --model sol_chatgpt_plan --level 1 --min-arms \
  --parallel 4 --output runs/policy/claude-gpt-l1
.venv/bin/roboteam run runs/policy/claude-gpt-l1
```

The preflight is the ordinary Claude Code one
([preflight and receipts](claude-code.md#preflight-and-receipts)), and it must report
`modelUsage.contextWindow=300000`. Build and check the
[policy environment](../hosts/policy-environment.md) as for any run. Do not reuse receipts from
another model.

## How it works

### The model entry

`sol_chatgpt_plan` in the `claude` section of `models.json`:

| Field | Value |
| --- | --- |
| `model`, `effort` | `gpt-6.1-sol`, `high` |
| `provider` | `openai_chatgpt_plan` |
| `transport_revision` | `websocket-incremental-v4`; part of the receipt, so a receipt from another adapter revision does not admit a run |
| `base_url` | `http://127.0.0.1:18461`; plain HTTP is accepted only for this provider and only on loopback |
| `env_key` | `ROBOTEAM_CHATGPT_GATEWAY_KEY`: the local gateway key, not an OpenAI credential |
| `context_capacity` | 300,000 |
| `managed_settings.modelPricing` | Prices for the model ID, which Claude Code does not know |

In receipts, `auth_mode: api_key` describes how Claude Code authenticates to the gateway (with
the local key). It does not mean OpenAI API-key billing.

**Context.** The run uses the same 300,000-token window and 267,000-token compaction limit as
every Codex model. The host also sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS=300000`, because Claude
Code 2.1.316 assumes a 200,000-token window for a model ID it does not know, and that would cap
the compaction limit.

**Cost.** The dollar figures Claude Code reports come from the `modelPricing` table: OpenAI's
API list rates for short contexts. They are estimates for the benchmark's cost records, not a
subscription invoice. The usage OpenAI actually reports is kept in the gateway log.

### Trust boundaries

The gateway listens on `127.0.0.1` only and requires the local key. An authorization or quota
failure never switches to an API key, another model or another account. The agents' sandbox
must keep them away from the credential files and from loopback connections, as it does in a
`full` run. No credential, sign-in code, prompt, image or tool result is written to the log.

The host passes each session's ID and, for a fork, its source in the headers
`X-RoboTeam-Session` and `X-RoboTeam-Fork-Source`. They never leave the machine.

### Original outputs are replayed exactly

OpenAI's Responses API expects a conversation's earlier model outputs to come back as they were
produced: item IDs, argument strings, message boundaries and encrypted reasoning. Claude Code
keeps history in Messages form, which cannot carry all of that. The gateway therefore saves
each completed response's `output` array in `response-replay.sqlite` before it releases a tool
call to Claude Code.

When Claude Code sends assistant history back, the gateway checks the visible part against the
saved record and sends OpenAI the original items instead of a reconstruction. This keeps
function-argument strings byte for byte, the assistant `phase`, item IDs, message boundaries,
refusals and encrypted reasoning. History that was changed, is missing or matches more than one
record is an error before any request to OpenAI. It is never repaired, guessed or sent in a
lossy form.

- Matching first uses the whole preceding input. After a compaction or a fork has changed that
  start, only a stored output that matches uniquely is restored; the change is recorded in
  `replay_prefix_changes`.
- A lookup stays inside one session and its recorded ancestors, so identical text in an
  unrelated session cannot select another session's output.
- Claude Code may add a tool schema's declared defaults to saved arguments (for example Edit
  adds `replace_all: false`). The gateway accepts only added fields that match the declared
  defaults exactly; removed fields, changed values and other additions are rejected.

The replay database holds the model's original text, tool arguments and encrypted reasoning.
It is private state, not a log. Keep it and its SQLite side files with the credential file, out
of collections, archives and version control, and back it up with the sessions if they must be
resumed later. A session created without this database cannot be continued through the
adapter.

### Sessions and forks

The gateway keeps one authenticated WebSocket per Claude Code session. While the settings and
the start of the input are unchanged, it sends `previous_response_id` and only the new input
items. A restart, a rotated token, an expired connection, changed settings or a compaction
rebuilds the context from the verified local history. A response ID is never reused on another
connection.

Each fork starts its own connection with the complete inherited history, so a parent and its
children run at the same time, including a fork taken while the parent waits on a tool call.
This can cost a cold start for the new branch.

Connection state is committed only after the original output is stored. An identical retry can
reuse a completed response without another model call. A cancellation, an incomplete response
or an ambiguous network failure discards the connection state and releases no partial tool
call. Only an explicit `previous_response_not_found` before a response starts triggers one
replay of the full history.

When a parent is forked while it waits on a tool call, Claude Code adds its own assistant
message `No response requested.` to the history. The model never produced it. The gateway
accepts exactly that message, records it under `native_controls`, and accepts no other
untracked assistant text. With `--native-session-index`, it also requires the message to be
present in the session's transcript, and it registers a new fork only when the host's fork
record verifies: the parent's history up to the fork, the copied history, the child's first
input and the setup status. An unknown session, an uncertain record or changed history is
rejected.

### The log

Each request adds one line to the `--log` file: hashes of the instructions, the tools and
checkpoints of the input; the usage and cache details OpenAI reported; the transport mode, the
connection generation and the reason for a reset; the numbers of input items sent and in full;
the previous and restored response IDs; `input_transformations`; the service tier; and the
authentication mode. For a WebSocket that closed it keeps the close code, a hash of the close
reason, the connection's age and timing flags, never the raw close reason. Missing cache
details stay unknown; they are not counted as cache hits. To measure caching, divide total
cached input by total input.

### Errors and limits

- A response is released only after `response.completed`. A failed, incomplete, interrupted or
  wrong-model stream produces no `message_stop` and no tool call.
- Requests that the gateway cannot translate are rejected explicitly. The token-count endpoint
  returns 404 rather than an invented count. Temporary 503 answers let Claude Code retry.
- A `subscription_sharing_usage_limit_exceeded` or `insufficient_quota` answer creates a hold
  file beside the log (`chatgpt-plan-quota.json`, or `openai-api-key-quota.json` in API-key
  mode). It blocks new model calls, also after a gateway restart, until you remove it. The
  answer does not say whether the whole plan is used up or when it resets: check the usage page
  of the account first.
- `--tokens-per-minute N` admits requests through one first-in, first-out queue shared by all
  sessions. At a 300,000-token context each request reserves 428,000 tokens (300,000 input plus
  the model's 128,000 output capacity) for sixty seconds, with at most four requests in flight.
  A waiting request holds no connection to OpenAI and can be cancelled. This slows parallel
  runs; it does not change their tools, context, outputs or forks. The gateway cannot reserve
  quota against other users of the same API project.

## Tests

```sh
.venv/bin/python -m scripts.dev.run_tests harness.adapters.test_claude_chatgpt_gateway \
  harness.adapters.test_claude_chatgpt_plan harness.adapters.test_chatgpt_plan_auth \
  harness.adapters.test_chatgpt_plan_websocket
```

The tests cover exact round trips of arguments and phases, refusals and message boundaries,
changed and ambiguous histories, concurrent branches and a restart. With the installed Claude
Code CLI they also run, against a local stand-in for OpenAI, a real tool call, a resume after a
gateway restart, a fork, a fork of a waiting parent, and the compaction boundary (no compaction
at 170,000 tokens, compaction above 267,000). No test contacts OpenAI. They check the
translation; they do not measure a cache-hit rate.

## References

- [OpenAI plan-use registration](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [OpenAI inference
  requirements](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [OpenAI self-hosted VM
  credentials](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [Responses WebSocket continuation](https://developers.openai.com/api/docs/guides/websocket-mode)
- [Preserve original Responses history](https://developers.openai.com/api/docs/guides/preserved-reasoning)
- [Prompt cache diagnostics](https://developers.openai.com/api/docs/guides/prompt-caching/diagnostics)
- [Claude Code gateway protocol](https://code.claude.com/docs/en/llm-gateway-protocol)
- [Claude Code custom model pricing](https://code.claude.com/docs/en/settings-reference#modelpricing)
- [Claude Code custom model context
  windows](https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model-id)
