# Experimental Claude Code / GPT ablation

This adapter is RoboTeam code, not an official OpenAI or Anthropic connector.
Anthropic does not support routing Claude Code to non-Claude models. A passing
preflight qualifies only the measured combination; it does not establish parity
with native Codex or native Claude.

The native Claude Code CLI owns tool execution, persistent sessions, compaction,
and verified adaptive forks. A loopback adapter translates Anthropic Messages to
the public OpenAI Responses API. It does not run the Codex agent loop.
Every upstream inference request selects `gpt-6.1-sol` with high reasoning effort
and `store: false`, using Responses WebSocket events. Unsupported content is rejected explicitly.
Completed tool calls are released only after `response.completed`; failed,
incomplete, interrupted, or wrong-model streams do not emit `message_stop`.

## Authentication and trust

Install the optional [adapter dependencies](../../configs/requirements/chatgpt-plan.txt),
then run the standalone sign-in helper:

```sh
python -m pip install -r configs/requirements/chatgpt-plan.txt
python scripts/chatgpt_plan_auth.py login --credential-file /private/plan/account.json
```

Follow the printed official OpenAI sign-in link. It registers this self-hosted
application and requests explicit `chatgpt.tokens.use.direct` permission. It does
not grant access to existing ChatGPT conversation history. The implementation
checks state, PKCE, ID-token signature, issuer, audience, expiry, nonce, and granted
scopes before saving credentials. Credential files must be outside the checkout
and evidence roots, owner-only on Unix or protected by an equivalent Windows ACL.

For a self-hosted VM, transfer the authorized credential record over SSH, preserve
the VM's own stable host ID, and let that VM alone own later token refreshes. Do
not keep two active refreshers sharing rotating credentials. No credential,
callback code, prompt, image, or tool-result body belongs in transport logs.

The adapter binds only to `127.0.0.1` and requires a random local gateway key.
Claude Code receives that local key, never the OpenAI OAuth token. In profile
receipts, `auth_mode: api_key` describes this local Messages-client authentication;
the upstream provider is `openai_chatgpt_plan`, not OpenAI API-key billing.
The full-mode sandbox must deny access to credentials and loopback connections.
An authorization or quota failure never switches to an API key, GitHub token,
another model, or another account.

```sh
python scripts/claude_chatgpt_gateway.py \
  --credential-file /private/plan/account.json \
  --key-file /private/plan/gateway-key.json --port 18461 \
  --log /private/plan/transport-metadata.jsonl
```

## Experiment profile and validation

### Explicit API-key handoff

`--auth-mode openai_api_key --credential-file /private/api/key.txt` selects OpenAI
API billing explicitly. The file contains only the API key. This mode never reads
subscription OAuth credentials or refreshes tokens, and never falls back to another
credential. It retains the same Responses model, WebSocket transport and native
Claude harness. Keep API secrets within a host credential deny root; Claude receives
only the local gateway key. API access and limits need a live preflight.

For a stopped subscription experiment, preserve its original frozen profile and
session provenance. Run the gateway with `--replay-file` pointing at its existing
protected replay database, and record the operator-authorized billing handoff
separately before continuing the same run directories. The historical profile name
`sol61_chatgpt_plan` does not override the gateway's explicit authentication mode;
health and every transport record report the actual mode. Never edit original
frozen inputs merely to rename this historical profile. Validate old encrypted
history under the new credential before resuming physical work. A rejected history
is a stop, never permission to discard original reasoning or start a fresh task.

WebSocket diagnostics retain close codes, hashed close reasons, connection age,
request-send/response-start flags and request finish times. They never retain raw
peer close reasons, which may contain arbitrary sensitive text. A disconnected
response still releases no partial tool call and is not silently resubmitted.

With `--native-session-index /private/native-session-index.json`, an existing root
session can also replay the native `No response requested.` resume control. The
host-written, owner-only index binds each session ID to its original transcript.
Acceptance requires an exact synthetic non-error event in that transcript and no more
occurrences than the transcript records. A new fork can register dynamically only
through its private host claim: the claimed parent prefix digest, copied native
history, child first input and gated setup status must all verify. The parent may
have advanced since the fork; verification uses the pinned prefix, not its latest
history. Uncertain claims, altered history and unknown sessions remain rejected.
Forks additionally require a recorded provider response in the verified lineage.
A registered root may carry a native control from a cancelled first turn before
any provider output exists. Transcript flushes get a bounded wait; failure to
verify still rejects the request. This does not replace original output items.

For API projects with a measured token-per-minute limit, `--tokens-per-minute`
enables one FIFO admission window shared by all native sessions. At a 300k context,
each dispatched request conservatively reserves 428k tokens (300k input plus the
model's 128k output capacity) for sixty seconds, with at most four in-flight model
requests. Completed retries consume no new reservation. Waiting is cancellable,
does not hold an upstream connection or another native session's lock, and keeps
the Messages SSE alive. It can slow parallel tasks; it does not change their tools,
model context, outputs or fork ancestry. Leave room for other consumers of the same
API project; this process cannot reserve quota against external clients.

`sol61_chatgpt_plan` is a Claude engine profile. Its local key is supplied as
`ROBOTEAM_CHATGPT_GATEWAY_KEY`, with the actual OAuth credential retained only
by the adapter. Full tools, model effort and adaptive topology are frozen through
the ordinary benchmark configuration. The context budget is 300,000 with a
267,000-token compaction threshold. The host also declares
`CLAUDE_CODE_MAX_CONTEXT_TOKENS=300000`: an auto-compact override alone is capped
by the native client's assumed model window (200k for the unknown GPT ID in CLI
2.1.316). Preflight must report `modelUsage.contextWindow=300000`. A native CLI
test with a local-only stub checks that 170k does not compact and that compaction
remains enabled above 267k. A larger account window does not change this budget.

The host supplies only a managed `modelPricing` table for the otherwise unknown
GPT model ID. Dollar figures use short-context OpenAI API-equivalent list rates
for native budget bookkeeping; they are estimates, not subscription invoices,
and do not enable API-key billing. Long-context pricing and subscription quota
accounting are separate from these estimates. Actual upstream usage is retained
in the transport metadata.

Transport metadata stores only hashes of instructions, tools and input-prefix
checkpoints, plus upstream usage and any returned cache diagnostics. Local hashes
identify changes in request history; they do not prove server-side KV-cache reuse.
Caching keeps the provider's implicit defaults. Measure total cached input divided
by total input, alongside native compaction records and request-prefix hashes.

## Exact output replay and cache diagnostics

The gateway saves each completed Responses `output` array in an owner-only
`response-replay.sqlite` beside the credential file, before releasing a tool call
to Claude Code. This is private protocol state containing original model text,
tool arguments and encrypted reasoning; it is not a metadata log. Keep the file
and its SQLite sidecars inside the credential deny root and out of collections,
archives and version control. Back it up with the corresponding private session
state if those sessions must be resumed.

When Claude Code sends assistant history back, the gateway checks its visible
projection against that record and restores the original output items. This
preserves function-argument strings byte for byte, assistant `phase`, item IDs,
message boundaries, refusal blocks, namespace/call linkage and encrypted reasoning.
The gateway does not replace those items with reconstructed Messages equivalents.
The original argument string is also used in tool-call SSE deltas.

Matching first uses the complete preceding input identity. After native compaction
or a fork changes that prefix, only a uniquely matching stored output projection
can be restored; the changed binding is recorded in `replay_prefix_changes`.
Modified, missing or ambiguous history is an explicit protocol error before any
upstream request. It is never silently repaired, guessed or sent as a lossy
fallback. In particular, old sessions created before this replay database existed
cannot regain their original parameter strings or metadata retroactively. Keep
their evidence, but use a fresh validated native session for this adapter revision.

The gateway keeps one authenticated WebSocket per native session. After exact
history verification, an unchanged settings fingerprint and input prefix allow
`previous_response_id` plus only the new input items. Each fork starts its own
connection with the complete verified inherited history; parent and child turns
remain concurrent, including a blocked parent-tool fork. Forks do not share an
ID across connections or serialize behind their parent. This can incur a cold
start for a new branch.

Connection state commits only after durable original-output storage. An identical
retry can reuse that completed response without another inference or duplicate
usage. Cancellation, incomplete responses and ambiguous network failures discard
connection state and never release a partial tool call. Only an explicit
`previous_response_not_found` before response creation triggers one bounded full
history replay. Restart, token rotation, connection lifetime, changed settings and
compaction rebuild context from verified local history. A response ID is never
reused on another connection. Native session files and the private replay database
remain necessary for durable resume; WebSocket state alone is not durable storage.

The legacy comparison ID remains local diagnostic metadata; it is not substituted
for conversation state and cache controls are not forced on an unsupported route.
No change of credentials, model or billing route is allowed. Metadata includes
transport mode, connection generation, reset reason, sent/full input-item counts,
the actual previous response ID, restored response IDs,
`input_transformations` (reasoning removals), service tier and the upstream request
ID. Missing diagnostics remain unknown; they are not reported as cache hits.
Completed upstream usage remains recorded even when local replay-state persistence
or delivery fails.

Offline checks exercise exact argument/phase round trips, refusal and message
boundaries, modified/ambiguous histories, concurrent branches and durable restart.
Pinned native CLI tests use a loopback-only provider fixture for a real tool call,
resume after gateway restart, a native fork and the 300k compaction boundary. They
make no OpenAI inference requests. Passing them verifies the transport invariants,
not an upstream cache hit rate. A live preflight and cache measurement are still
required before claiming the earlier cache loss is resolved.
The profile's `transport_revision: websocket-incremental-v4` participates in its existing
fingerprint, so preflight receipts from the older lossy adapter do not qualify
this revision. Updating code does not start or continue stopped experiments.

The host passes the actual native `--session-id`/`--resume` identity and fork source
through loopback-only `X-RoboTeam-Session` and `X-RoboTeam-Fork-Source`
headers. These headers never go upstream. The replay database resolves history
only inside that session and its recorded ancestors; identical plaintext such as
`READY` in an unrelated session cannot select another session's original output.
Both one-shot and persistent launches set these headers. A fork's ancestry cannot
be rebound, and the native transcript/fork provenance checks remain unchanged.
The schema upgrade preserves unscoped v1 rows for audit but does not use them to
qualify or reconstruct a scoped v2 session.
At a blocked parent-tool fork, Claude Code can append its own `No response
requested.` assistant control message. This is not a provider output. The adapter
accepts that exact native control with recorded fork ancestry and, when a native
session index is configured, a transcript witness and verified host fork claim.
The control may precede the fork's first restored provider output. It is retained
as an explicit control and
records `native_controls`. It does not whitelist arbitrary untracked assistant
text or alter the native fork provenance checks. A real-CLI local-provider fixture
tests this blocked-parent path independently of the ordinary idle fork.

Claude Code may insert a tool schema's declared defaults into persisted arguments
(for example, Edit adds `replace_all: false`). Each response privately records the
original advertised schema defaults. Replay accepts only added fields that exactly
match those declarations, with strict boolean typing; removed fields, changed
supplied values and undeclared additions are rejected. The upstream output and
argument string remain unchanged. Metadata identifies responses needing this
native default completion without logging arguments. The pinned real-CLI test
executes both Read and Edit before resume and fork.

Authenticated unsupported requests are read fully and their connections closed.
The token-count endpoint returns an explicit 404, not an invented token count.
Temporary 503s allow bounded native retry, and cancellation never closes the
upstream chunk parser from a competing thread. Structured error codes are retained,
including admission responses that use `detail` instead of `error`.

A `subscription_sharing_usage_limit_exceeded` response creates an owner-only
`chatgpt-plan-quota.json` hold beside the transport log. It blocks new upstream
inference across gateway restarts. Review the application's limit in ChatGPT
settings Usage before deliberately releasing that hold. The code alone does not
identify a whole-plan limit or a reset time. An explicitly selected new account
uses separate protected credentials and a separate control/log/hold directory.

Before a benchmark can start, require the ordinary real native CLI preflights:
text, image returned by a robot tool, resume, verified fork, and blocked-parent
fork. Do not disable provenance checks or reuse receipts from another profile.
Then prepare the batch and pass the full-tool policy-environment checks. L3 has
12 distinct cases, including all three Mosaic arm counts.

Official references:

- [OpenAI plan-use registration](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [OpenAI inference requirements](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Responses WebSocket continuation](https://developers.openai.com/api/docs/guides/websocket-mode)
- [Preserve original Responses history](https://developers.openai.com/api/docs/guides/preserved-reasoning)
- [Prompt cache diagnostics](https://developers.openai.com/api/docs/guides/prompt-caching/diagnostics)
- [OpenAI self-hosted VM credentials](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [Claude Code gateway protocol](https://code.claude.com/docs/en/llm-gateway-protocol)
- [Claude Code custom model pricing](https://code.claude.com/docs/en/settings-reference#modelpricing)
- [Claude Code custom model context windows](https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model-id)
