# GitHub PAT model transport

This experimental transport lets a native coding agent use the model endpoints
available to a GitHub Copilot account. The agent remains Codex or Antigravity;
neither Copilot CLI nor GHC API is installed or invoked. The requests still use
the GitHub account's model access, policies, quotas and billing. A PAT is not an
OpenAI API key or a guarantee of access to every model in a catalog.

Use a valid fine-grained PAT with the account permission **Copilot Requests** and
an account with the required Copilot access. Follow GitHub's current
[PAT authentication instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/authenticate-copilot-cli).
Those instructions document CLI authentication; the direct model transport here
is an independently tested integration, not a promise of a stable public API.

Keep the PAT outside the checkout, in a private file or `ROBOFRONTIER_GITHUB_PAT`.
Do not put it in model profiles, TOML, shell arguments, committed files or logs.
On macOS/Linux, restrict the file with `chmod 600 /private/github_token.txt`.
On Windows, restrict its ACL to your account. The examples use placeholder paths.

## Portable connector

Copy just [`github_pat_gateway.py`](../../scripts/github_pat_gateway.py) to the
other computer. It uses the Python standard library only and accepts no token
on the command line:

```sh
python scripts/github_pat_gateway.py --token-file /private/github_token.txt --port 18450
```

Windows PowerShell:

```powershell
python scripts\github_pat_gateway.py --token-file C:\private\github_token.txt --port 18450
```

The listener binds to `127.0.0.1`. Authenticate the client with the same PAT as a
Bearer token. File-backed credentials are reread for every request; update the
client's credential too when rotating the file. An environment-backed token is
fixed for the lifetime of the process. The upstream uses certificate-verified
HTTPS to `api.githubcopilot.com`; credentials are never sent to an arbitrary host.

Forwarded routes, with or without the `/v1` prefix:

| Method | Route | Intended client |
| --- | --- | --- |
| GET | `/models` | Current account catalog |
| POST | `/chat/completions` | OpenAI Chat Completions clients |
| POST | `/responses` | Codex and other Responses clients |
| POST | `/responses/compact` | Passed through if supported by the upstream |
| POST | `/v1beta/models/MODEL:generateContent` | Antigravity native GenAI gateway mode |
| POST | `/v1beta/models/MODEL:streamGenerateContent?alt=sse` | Streaming GenAI gateway mode, including MCP images |

On OpenAI routes, HTTP status, streamed response bytes, tool calls and
`Retry-After` pass through. GenAI routes translate requests and responses to/from
upstream Chat Completions, preserving text, inline images, function arguments,
tool results, reasoning text and token usage. Images attached to a GenAI
`functionResponse` become user image parts after that group of tool results;
they are not replaced by filenames or image descriptions. The native GenAI
client can authenticate with `x-goog-api-key`; Bearer authentication also works.
There is no conversation store, agent loop, tool execution, synthetic successful
response, automatic request replay or fallback to a different account/model.
WebSocket connections and other API routes are not implemented. Disable
WebSockets in a Codex provider that uses the connector.

`GET /healthz` checks only the local listener. To check account access and discover
current model IDs and their protocols, make an actual catalog request:

```sh
python scripts/github_pat_gateway.py --token-file /private/github_token.txt --list-models
```

A model appearing in this list still needs a successful inference test. Choose a
model supporting the protocol your client sends; a Responses-only GPT model is
not automatically a Chat Completions model. `--log-file PATH` records request time,
endpoint, model, HTTP status and transport exception type, never request bodies,
responses, headers or credentials. Without this option no request log is stored.

## Codex: direct Responses provider

Codex can send Responses directly to GitHub, so it does not require the connector
process. The checked-in `sol61_github_pat` profile uses `gpt-6.1-sol` with `high`
effort and host-only `ROBOFRONTIER_GITHUB_PAT`. Its non-secret integration headers
are frozen with the provider profile; the credential remains an environment lookup.
It disables OpenAI subscription authentication and provider WebSockets.

In RoboFrontier, put the variable in the Git-ignored `.env`, or load the private
file into the environment in the shell that runs the commands:

```sh
export ROBOFRONTIER_GITHUB_PAT="$(cat /private/github_token.txt)"
.venv/bin/robofrontier preflight --engine codex --profile sol61_github_pat --tool-mode robot_only --confirm-spend
.venv/bin/robofrontier prepare --engine codex --profile sol61_github_pat --tool-mode robot_only --level 1 --parallel 12 --output runs/policy/codex-l1-pat
.venv/bin/robofrontier run runs/policy/codex-l1-pat --durable
```

Use `runtime.codex_home_scope = "task"` and a fresh `runtime.codex_home` directory
outside collected run data. Do not copy a subscription `auth.json` into it. On
plain Linux, a durable service must load the credential on its host: the generic
service launcher deliberately does not forward arbitrary secret variables. Use
that host's private `.env` or a service wrapper that reads the private token file.
Only the explicitly authorized preflight calls the provider before the batch
starts; preparation itself makes no inference request.

The preflight exercises real image/function calls, manual context compaction and
fork history. A passed receipt qualifies only its exact profile, catalog, CLI and
tool mode; it is not a context-capacity stress test. Robot only still exposes the
robot tool alone. Do not edit a running checkout or frozen run to change providers.

For Codex outside RoboFrontier, point a normal custom Responses provider at the
connector. The token stays in the environment:

```toml
model = "gpt-6.1-sol"
model_provider = "github_pat_gateway"

[model_providers.github_pat_gateway]
name = "GitHub PAT gateway"
base_url = "http://127.0.0.1:18450/v1"
env_key = "ROBOFRONTIER_GITHUB_PAT"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
```

See the official [Codex gateway requirements](https://learn.chatgpt.com/docs/enterprise/gateway-compatibility).

## Antigravity: GenAI gateway mode with MCP images

With an Antigravity CLI version that supports the
[gateway variables](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway),
run the connector with `--flash-helper`, then launch the native CLI from a shell
with these variables (shown for macOS/Linux):

```sh
export AGY_LLM_GATEWAY_URL=http://127.0.0.1:18450
export AGY_LLM_GATEWAY_API_KEY="$(cat /private/github_token.txt)"
export AGY_LLM_GATEWAY_WIRE_PROTOCOL=genai
export AGY_LLM_GATEWAY_MODELS=gemini-4-argon,gemini-3.8-flash
agy
```

Use **`genai` for image tools**. Antigravity CLI 1.5.5 was observed dropping MCP
image attachments from its OpenAI-mode model requests: the tool completed, but
the model received text only. The same CLI preserves those attachments in its
native GenAI requests, which this connector converts to real Chat Completions
image parts. A direct image API test or successful text tool call alone does not
validate the native tool-image round trip. Validate it by returning an image
containing a random code from an MCP tool and checking both the outgoing image
parts and the model's exact answer. This workaround needs no Copilot CLI, image
captioning model, extra model call or conversation store.

This implements the GenAI subset needed by the native CLI: text and inline
images, function tools, one candidate, common sampling settings, structured JSON
responses and `thinkingLevel`. File URI fetching, audio/video input, cached
content, safety-setting overrides and exact `thinkingBudget` translation are
unsupported and return an error rather than silently discarding input. Upstream
HTTP errors retain their status and retry metadata. An invalid or incomplete
translated stream emits an error without inventing a successful finish.

PowerShell uses `$env:AGY_LLM_GATEWAY_URL = 'http://127.0.0.1:18450'` and the same
other variable names; read the credential with `Get-Content -Raw` and `.Trim()`.
Do not select the native Gemini API-key provider or retain conflicting
`GEMINI_API_KEY` / `GOOGLE_GEMINI_BASE_URL` settings in this gateway session.

The opt-in `--flash-helper` compatibility setting maps internal
`gemini-3.1-flash-lite-preview` requests to `gemini-3.8-flash`/`low`, and changes
Flash `minimal` effort to `low`, which the tested upstream accepts. It does not
disable auxiliary requests or change the main Argon model. Without that flag,
every model name and reasoning parameter is passed through unchanged. No safety
filter or tool-permission switch is changed.

This is a standalone CLI example. The unmerged RoboFrontier Antigravity engine
has its own frozen launch/environment rules and needs explicit gateway support
and a fresh preflight before using this route; adding these shell variables to an
already prepared native-Gemini experiment does not migrate it.

## Migration from GHC API

New deployments need only the standalone file (if a connector is needed), the
native agent and the private PAT. They need no `ghc_api` Python package, OAuth
exchange process, GHC service or bridge key. Stop an old service only after the
replacement has passed inference and native tool-call checks. Preserve existing
experiment evidence; removing a deployment dependency does not require rewriting
historical profiles or deleting other repositories.
