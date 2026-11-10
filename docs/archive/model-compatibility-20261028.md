# Historical snapshot: eight Chinese vision providers and Codex compatibility

Recorded review date: **2026-10-28, Asia/Hong_Kong**. This English edition retains
the original source links, numerical tables, uncertainties and engineering
judgments. It does not reverify current vendor prices, model availability or
private account quotas. The original research used vendor sources for robot
images, dynamic function tools, multi-turn tool results, long history,
compaction and fork. It considered ordinary realtime pay-as-you-go APIs, not
Coding Plan, M Plan, Token Plan, Step Plan, Batch or third-party resale prices.
It made no paid inference calls, read no keys and checked no private quota.

## Recorded compatibility assessment

Compatibility meant integration evidence and required engineering, not robot
success rate. The four configured Chinese providers were Kimi, Qwen, GLM and
DeepSeek; the other four were candidates. None of these eight had completed a
real API preflight in that handoff checkout. The table is a dated assessment,
not a claim that current code or an account supports every listed model.

| Model | Recorded Codex integration assessment | State and checks identified in the snapshot |
| --- | --- | --- |
| `kimi-k3.1-pro` | Strong: native Responses and a Codex guide | Existing `kimi` profile; verify image tool returns, long continuation, compaction/fork and actual reasoning parameters. [Guide](https://platform.kimi.com/docs/guide/codex-kimi) |
| `deepseek-flash` | Strong: native Responses and a Codex guide | Existing `deepseek` profile; recorded alias V4.1-Flash-1017 had vision, unlike the recorded V4 Pro listing. [Guide](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/), [model source](https://api-docs.deepseek.com/quick_start/pricing/) |
| `MiniMax-M3.1-Flash` | Strong: detailed Codex model catalog instructions | Not configured; declared text/image and reasoning support with low/medium/high/xhigh/max, excluding none. Tool loops and image results still required tests. [Guide](https://platform.minimax.cn/docs/m-plan/codex) |
| `qwen3.8-max-0902` | Relatively strong: Responses images/functions | Existing `qwen` profile; account region/workspace URL required. Session cache needed a header; context above approximately 80% could be automatically truncated. [Interface](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses) |
| `glm-5.3-flash` | Relatively strong: Responses images/functions | Existing `glm` profile; Responses used `/api/v1`, not Chat's `/api/paas/v4`. Verify account model access and multimodal tool results. [Interface](https://docs.bigmodel.cn/cn/guide/develop/responses/introduction) |
| `doubao-seed-2-1-pro-260915` | Relatively strong, with subscription/pay-as-you-go endpoint distinctions | Not configured; the Codex guide used a Coding Plan endpoint, which did not establish pay-as-you-go quota. Preserve encrypted reasoning across turns and test full history. [Codex](https://docs.volcengine.com/docs/ark/coding-plan-personal-ai-codex?lang=zh), [reasoning](https://docs.volcengine.com/docs/ark/deep-thinking?lang=zh) |
| `mimo-v2.6-pro` | Strong official support, but a declared catalog difference | Not configured; the vendor catalog used `use_responses_lite=true` while the generated provider configuration forced false. Custom tools reportedly needed lite, requiring dynamic-tool verification first. [Guide](https://mimo.mi.com/docs/en-US/tokenplan/integration/codex-configuration), [catalog](https://example-files.cnbj1.mi-fds.com/example-files/configs/model-catalogs.json) |
| `step-5-preview` | Official integration, with robot workflow compatibility unverified | Not configured; Codex instructions used Step Plan. Ordinary pay-as-you-go also exposed `/v1/responses`, with documented function, `tool_choice=auto` and string tool results; image returns/custom/freeform were not established. [Codex](https://platform.stepfun.com/docs/zh/guides/developer/integrations/codex.md), [Responses](https://platform.stepfun.com/docs/zh/api-reference/responses/responses-create.md) |

The providers were not assumed to implement the same protocol subset. Custom
provider/environment/header configuration did not make every image/tool field
valid at a vendor endpoint. The snapshot linked the
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-advanced).

The engineering audit referenced [launch configuration](../../robofrontier/engines/codex/launch.py),
[profiles](../../configs/models.json), [catalog seed](../../configs/codex-model-template.json)
and [preflight](../../robofrontier/engines/codex/codex_preflight.js). Those files can evolve; consult
Git history for the version behind this dated record. The raw catalog seed is
not the generated provider catalog: launch overrides must be inspected too.

The original gaps were:

- Smoke checked user-attached image, function call and a text tool result; full
  preflight added manual compaction and fork. It did not establish that a real
  provider accepted an image returned by a tool and then continued acting. An
  offline stub was not a substitute.
- The configuration did not explicitly declare
  `supports_reasoning_summaries=true` or force the corresponding option. The
  MiMo/MiniMax guides related that flag to sending `reasoning.effort`; actual
  requests needed inspection rather than trusting a local high/max label.
- The recorded context budget was 272,000 and automatic compaction threshold
  245,000. This did not mean every turn sent 272K tokens. Full-window loading and
  automatic compaction under load were not stress-tested.

The proposed engineering order was to verify the existing four, then prioritize
MiniMax; resolve MiMo lite/dynamic tools; distinguish Doubao pay-as-you-go
endpoints; and first establish Step image-tool returns. This was an engineering
judgment, not a model-quality ranking. Task ability needed identical frozen
inputs, comparable budgets and complete usage evidence.

## Recorded pay-as-you-go prices

Prices are per **1,000,000 tokens**. DeepSeek is USD; all other rows are the
recorded China-region CNY prices. No exchange-rate conversion is implied.
Image encoding and reasoning/output tokens could also incur charges.

| Model / region | Uncached input | Cache-hit input | Output | Source |
| --- | ---: | ---: | ---: | --- |
| Kimi K3.1 Pro / China | CNY 13 | CNY 1.30 | CNY 68 | [Kimi](https://platform.kimi.com/) |
| Qwen3.8-Max-0902 / Beijing | CNY 12 | CNY 1.5 implicit; CNY 1 explicit | CNY 36 | [Qwen](https://help.aliyun.com/zh/model-studio/qwen3-8-max) |
| GLM-5.3-Flash / China | CNY 0.8 | CNY 0.23 | CNY 2.8 | [Zhipu](https://docs.bigmodel.cn/cn/guide/start/pricing) |
| DeepSeek Flash / off-peak | USD 0.15 | USD 0.003 | USD 0.60 | [DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/) |
| DeepSeek Flash / peak | USD 0.30 | USD 0.006 | USD 1.20 | [DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/) |
| Doubao Seed 2.1 Pro **260915** / Beijing | CNY 6 | CNY 1.20 | CNY 30 | [Ark](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh) |
| MiMo V2.6 Pro / China | CNY 3 | CNY 0.025 | CNY 6 | [MiMo](https://mimo.mi.com/docs/pricing) |
| MiniMax M3.1 Flash / China | CNY 1 | CNY 0.10 | CNY 4 | [MiniMax](https://platform.minimax.cn/docs/pricing/overview.md) |
| Step 5 Preview / China | CNY 7 | CNY 0.70; eligible existing users CNY 0.35 | CNY 20 | [StepFun](https://platform.stepfun.com/docs/zh/guides/pricing/details.md) |

Recorded DeepSeek peak hours were Monday-Friday Hong Kong 09:00-12:00 and
14:00-18:00, excluding Chinese public holidays; other times were off-peak.
[Time rules](https://api-docs.deepseek.com/quick_start/pricing/).

The recorded Step existing-user discount required a previous ordinary
pay-as-you-go Step 5 Preview call before 2026-10-14 00:30 Beijing time, not merely
an old registration. [Announcement](https://platform.stepfun.com/docs/zh/announcements/step-5-preview-price-adjustment.md).

No older model's context surcharge was copied into this table: the recorded
Doubao 260915 rate covered 0-1024K input, versus older 260628's 256K; MiMo V2.6
Pro listed no long-context surcharge; MiniMax M3's 512K tier was not M3.1 Flash.
[Ark model list](https://docs.volcengine.com/docs/ark/model-list?lang=zh),
[MiMo pricing](https://mimo.mi.com/docs/pricing),
[MiniMax pricing](https://platform.minimax.cn/docs/pricing/overview.md).

## Recorded cache writing, storage and activation

| Provider | Writing/storage/TTL | Harness limitation identified in the snapshot |
| --- | --- | --- |
| Kimi | Automatic prefix caching; default five minutes, one-hour option; displayed CNY 13/M writing did not specify TTL and one-hour Pro writing was not verified | Ordinary input/write/read categories were mutually exclusive, not CNY 13 + CNY 13 for the same token. [Billing](https://platform.kimi.com/docs/guide/context-caching) |
| Qwen | Automatic implicit cache with no fixed TTL; explicit creation CNY 15/M, hits CNY 1/M and five-minute hit renewal | No Session header configured, although implicit hits could still occur. `x-dashscope-session-cache: enable` activated Session; this model preferred explicit caching. [Cache](https://help.aliyun.com/zh/model-studio/context-cache), [Session](https://help.aliyun.com/zh/model-studio/compatibility-with-openai-responses-api) |
| GLM | Automatic implicit cache; temporarily free storage; no fixed TTL or separate writing price published | Repeated prefixes of at least 500 tokens were recommended; actual usage needed inspection. [Cache](https://docs.bigmodel.cn/cn/guide/capabilities/cache), [billing](https://docs.bigmodel.cn/cn/guide/start/pricing) |
| DeepSeek | Automatic cache; no separate writing/storage fee; inactive entries usually cleared after hours to days | Best effort, without guaranteed hits or fixed TTL. [Cache](https://api-docs.deepseek.com/guides/kv_cache/) |
| Doubao | Automatic implicit cache with free storage; explicit storage CNY 0.017/M tokens/hour, rounding up to one hour, maximum seven days | New input charged at ordinary input rate; explicit mode required `caching` and was mutually exclusive with implicit mode. [Cache](https://docs.volcengine.com/docs/ark/context-cache?lang=zh) |
| MiMo | Cache writing temporarily free; no published fixed TTL or separate storage price | Permanent free writing was not established. [Pricing](https://mimo.mi.com/docs/pricing) |
| MiniMax | Automatic prefix cache for at least 512 input tokens; new input at ordinary rate, no separate writing/storage line | No fixed TTL published; only actual hits justified cached pricing. [Cache](https://platform.minimax.cn/docs/api-reference/text-prompt-caching.md) |
| Step | Automatic prefix cache in 256-token blocks; first write at ordinary input price, no extra cache purchase | LRU eviction, no fixed TTL; identical images/videos, tools and results could participate. [Cache](https://platform.stepfun.com/docs/zh/guides/developer/prompt-cache.md) |

The review found no explicit general guarantee for these public pay-as-you-go
APIs that cached tokens did not count toward TPM. A price discount was not a TPM
discount; dedicated PTU/reserved throughput/subscription terms were not applied.
Actual hits required original response usage, not merely matching system text.

## Recorded RPM, TPM and simultaneous requests

RPM is requests per minute; TPM is the token rate quota; simultaneous requests
are outstanding requests that have not finished. Unpublished/unverified does not
mean unlimited or guarantee that an account receives a listed baseline.

| Model / ordinary pay-as-you-go account | Simultaneous requests | RPM | TPM | Scope and source |
| --- | ---: | ---: | ---: | --- |
| Kimi K3.1 Pro | Funding tier; figures unverified | Same | Same, plus TPD | User-wide across models/keys; the dynamic table could not be read in the review. Consult the console. [Source](https://platform.kimi.com/docs/pricing/limits) |
| Qwen3.8-Max-0902 / Beijing | Unpublished | No figure given | **1,500,000** | Main account + model, shared by workspaces/keys; the recorded three-month-spending tiers had the same snapshot baseline. [Source](https://help.aliyun.com/zh/model-studio/quota-management) |
| GLM-5.3-Flash | Account tier + model; console authoritative | Unpublished | Unpublished | Forum figures/Coding Plan project counts were not substituted. [Source](https://docs.bigmodel.cn/cn/api/rate-limit) |
| DeepSeek Flash | **2,500/account** | Unpublished | Unpublished | From request issuance through response completion, all keys shared; exceeding quota returned 429. [Source](https://api-docs.deepseek.com/quick_start/rate_limit/) |
| Doubao 260915 / Beijing | Unpublished; low funding could limit it | **500** | **1,000,000** | Shared across main/subaccounts and same-model endpoints; a public maximum was not a capacity guarantee. [Models](https://docs.volcengine.com/docs/ark/model-list?lang=zh), [FAQ](https://docs.volcengine.com/docs/ark/modelark-faq?lang=zh) |
| MiMo V2.6 Pro | No figure published | **100** | **10,000,000** | Same-account/same-model aggregate across keys. [Source](https://mimo.mi.com/docs/en-US/quick-start/model) |
| MiniMax M3.1 Flash / free | Unpublished | **20** | **1,000,000** | Shared by main/subaccounts. [Source](https://platform.minimax.cn/docs/guides/rate-limits.md) |
| MiniMax M3.1 Flash / funded | Unpublished | **200** | **10,000,000** | TPM included input/output; increases could be requested. [Source](https://platform.minimax.cn/docs/guides/rate-limits.md) |
| Step 5 Preview / V0 individual | **5** | **100** | **500,000** | Other funding tiers below. [Source](https://platform.stepfun.com/docs/zh/guides/pricing/rate-limits.md) |

The fixed Qwen snapshot did not inherit the rolling `qwen3.8-max` alias's
5/10/20-million TPM tiers. Regions also differed: some overseas/global deployments
listed 30,000 RPM and 150,000 TPM separately.
[Regional model source](https://help.aliyun.com/zh/model-studio/qwen3-8-max).

Recorded Step individual tiers used cumulative cash funding, excluding vouchers;
enterprises contacted sales. Limits could change with load and accounts required
identity verification. [Rate-limit source](https://platform.stepfun.com/docs/zh/guides/pricing/rate-limits.md).

| Step tier | Cumulative cash funding, CNY | Simultaneous requests | RPM | TPM |
| --- | --- | ---: | ---: | ---: |
| V0 | <100 | 5 | 100 | 500,000 |
| V1 | 100-499 | 20 | 400 | 2,000,000 |
| V2 | 500-1,999 | 30 | 600 | 3,000,000 |
| V3 | 2,000-9,999 | 40 | 800 | 4,000,000 |
| V4 | >=10,000 | 130 | 2,600 | 13,000,000 |

## Interpreting quotas for experiment concurrency

One Level 1 task can create multiple native Codex sessions. Four tasks, four CLI
processes, four robot arms and four simultaneous API requests are different
counts. An API connection quota alone cannot determine experiment concurrency.

The recorded engineering recommendation was account-wide request admission,
RPM/TPM budgeting and 429 backoff. The harness primarily limited task concurrency;
it did not implement a complete account-wide API limiter. Independent task
retries could jointly hit a shared limit. More keys for the same account usually
did not create more quota.

A rough bound was `requests/minute <= min(RPM, TPM / mean rate-counted tokens per request)`.
Simultaneous requests also depended on response duration. Providers could
pre-reserve maximum output, enforce per-second limits or adjust quotas, so this
was not a throughput promise. Kimi and Doubao reservation rules needed explicit
checks. [Kimi](https://platform.kimi.com/docs/introduction),
[Doubao](https://docs.volcengine.com/docs/ark/activation-management?lang=en),
[Qwen](https://help.aliyun.com/zh/model-studio/rate-limit).

For example, at an assumed 100K rate-counted tokens/request, 500K TPM supported
approximately five requests/minute even with a nominal 100 RPM allowance. This
was arithmetic, not measured benchmark token usage.

The proposed sequence was one task/provider to verify image-tool returns,
continuation and compaction/fork, then four minimum-arm Level 1 tasks while
recording turn tokens, latency, cache hits and 429s before increasing concurrency.
The recorded Step V0 five connections/500K TPM especially needed consideration;
unpublished connection limits at other vendors did not establish stable 12-task
operation. GLM/MiniMax's recorded CNY input/output prices were low and MiMo's hit
price was low, but comparison still needed misses, output, cache writes and
actual success. DeepSeek's USD billing remained separate. These are historical
judgments, not current model recommendations.

See the [handoff guide](../engines/providers.md) for current commands. This edition
changes research text only, not profiles, CLI configuration, formal experiments
or an earlier Harness session's running state.
