# Model providers, profiles and authentication

For new work use the [unified CLI](../unified-cli.md), [Docker](../running/docker.md),
[Slurm](../running/slurm.md) and [evidence storage](../running/evidence-storage.md) guides. This
guide was first written while the checkout was integrating
`integration/unified-main`, before that work replaced the published default
branch. The native `scripts.benchmark` entry is retained for Codex compatibility
and has different defaults from the unified entry. Engine-specific details are
in the [Codex](codex.md) and [Claude](claude-code.md) guides; installation, the `.env`
file and policy assets are in [shared setup](README.md#shared-setup).

## Catalogs and profiles

The native Codex catalog is `configs/models.json`; Claude has
`configs/claude-models.json`. Profiles are candidates, not provider-availability
or compatibility certificates. The dated
[pricing research](../archive/model-pricing-20261028.md) and
[compatibility comparison](../archive/model-compatibility-20261028.md) are
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

## Authentication matrix

Defaults:

- The repository's overall default is the Codex `luna` profile
  (`gpt-6-luna`, effort `high`) through `OPENAI_API_KEY`. The retained native
  `scripts.benchmark` CLI still defaults to its historical `astra` selection.
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
| Codex | OpenLux API key | `openlux-luna`, `openlux-terra` | `OPENLUX_API_KEY` | [OpenLux Terra](../archive/openlux-terra.md) |
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

## Codex Responses endpoints

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

## Claude-compatible endpoints

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

## Local checks and preflight

Run local checks before a paid test:

```sh
.venv/bin/robofrontier doctor --engine codex --profile kimi --render native
.venv/bin/python -m scripts.check_codex_cli --output runs/engineering/local-cli-check
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
[Claude provider prechecks](claude-code.md#provider-prechecks-and-historical-evidence).

## Qualification and limits

Preflight remains explicit and may consume subscription quota:

```sh
robofrontier preflight --engine claude --profile haiku_subscription \
  --max-budget-usd 0.10 --confirm-spend
```

CLI USD reports are estimates; subscription list-price equivalents are not
provider invoices. Keep API spending, subscription quota and unknown outcomes
separate. Claude task execution still requires `--engineering`; these profiles
do not open formal scored eligibility. Local shared-home checks do not qualify
Docker, Slurm, 36 simultaneous subscription tasks or every refresh boundary.
The Slurm entry continues to accept API credentials only. See the [acceptance ledger](../archive/unified-main.md)
for actual source-pinned results.

Official references: [Codex authentication](https://learn.chatgpt.com/docs/auth),
[Codex account refresh](https://learn.chatgpt.com/docs/app-server), and
[Claude Code authentication](https://code.claude.com/docs/en/authentication).

## Multi-model task selection and concurrency

New unified defaults are Luna/high, adaptive, 36 concurrent task hosts and a
24-hour limit from each task's persisted START. The retained native
`scripts.benchmark run` default is parallel 9. Always inspect a plan rather than
assuming two entries use identical defaults.

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

For a deliberately shared Dial random instance across multiple Codex profiles,
the native compatibility entry retains one combined preparation:

```sh
.venv/bin/python -m scripts.benchmark prepare --models kimi qwen glm deepseek \
  --level 1 --min-arms --output runs/policy/native-four-model-comparison
.venv/bin/python -m scripts.benchmark run runs/policy/native-four-model-comparison --parallel 4
```

This selects 16 tasks that execute in batches of up to four. Independent
preparations can generate different Dial instances. It is a native compatibility
workflow, not a 144-task unified concurrency setting. Keep profile-specific
context/compaction thresholds and requested effort in reports: identical effort
strings do not prove identical compute. Do not infer current values from the
original handoff's 272,000/245,000 context/compaction snapshot.

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

## Branches, bundles and worktrees for multi-model work

### Provenance of the original handoff

The original `codex/multimodel-handoff` branch was created from
`codex/server-benchmark-prep`, commit
`3638e1c351b6e885ac94e3256f5782f8aecd46ee`. Forking a chat did not copy a Git
worktree; the code base was checked separately. The original Harness session's
running experiments remained its responsibility. This is historical provenance,
not a claim that every current integration file equals that original commit.

### GitHub, branches and offline bundles

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

### Worktrees and eventual merge

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
