# Claude engineering batch manager prompt

Give this prompt to a coding agent with terminal and repository access. The
outer session can use any model. Claude CLI and the frozen profile select the
inner measured model. This native entry is for unqualified engineering drafts;
it does not produce formally qualified benchmark scores. Read
[handoff status](../../docs/engines/claude-code.md) before using it.

```text
Act as the outer manager for a RoboFrontier Claude engineering batch. First read
docs/engines/claude-code.md and docs/unified-cli.md.

Parameters:
- models: [opus]
- families: [transport, mosaic, relay, dial]
- level: 1
- scale: min-arms
- topology: adaptive
- record_video: false
- parallel: 4
- mode: plan
- output: runs/engineering/opus-l1-small-001
- precheck_budget_usd: unspecified
- check_fork: true
- check_blocked_fork: false
- turn_budget_usd: null
- task_budget_usd: null
- wall_limit_s: 86400
- startup_timeout_s: 600

1. Inspect the checkout, Git commit, worktree state and current release registry.
   Report scene versions. Manage this batch only, leaving other sessions' runs
   with their original operators.
2. Run robofrontier.batch.claude_benchmark doctor for the selected profiles, CLI and assets.
   Report missing credential variable names only. If .env is absent, copy the
   empty .env.example template with mode 0600; preserve existing .env and
   credentials. Doctor establishes no account/provider compatibility claim.
3. Run robofrontier.batch.claude_benchmark plan with the requested models, families, level,
   scale and parallelism. Pass --min-arms only when requested. Report each exact
   case, arm count and inner model. For mode=plan, stop here.
4. For mode=precheck, use robofrontier.engines.claude.preflight --profile PROFILE
   --max-budget-usd BUDGET --confirm-spend for each selected profile only when
   real provider spend has been authorized and a positive precheck estimate is
   specified. Add --check-fork when requested. Keep every receipt and report its
   result. Missing authorization, budget, credentials or a compatible endpoint
   leaves the paid step pending; finish offline work and report missing items.
   This checks text, native image/tool round trips and continuation. An idle
   fork check does not qualify a blocked parent's fork or a full physical task.
   When check_blocked_fork=true and its additional spend is authorized, run
   robofrontier.engines.claude.claude_blocked_precheck separately and retain the independent receipt.
   robofrontier.engines.claude.claude_readiness checks whether both receipts match the profile and
   CLI; a match does not grant formal benchmark qualification.
5. For mode=engineering, continue only within authorization for these models and
   this engineering batch. Turn/task budgets default to null; omit their flags
   rather than inventing dollar limits. Explicit limits must be positive. The
   wall limit defaults to 86400 seconds from START; an engineering short-test
   stop may be earlier without rewriting the frozen public task limit.
   Prepare a new directory using robofrontier.batch.claude_benchmark prepare-draft with
   matching selection, topology and output. Add --record-video only when
   requested, checking FFmpeg/ffprobe first. Permanent-worker Claude modes remain
   unavailable; use single or adaptive drafts. Verify batch.json case/profile
   selection before execution. Retain an existing directory instead of reusing
   it. An engineering draft is not a scored/preflight-qualified benchmark.
6. Run robofrontier.batch.claude_benchmark run-engineering OUTPUT --parallel N
   --wall-limit-s W --startup-timeout-s S --confirm-engineering-spend in a
   persistent terminal. Add --turn-budget-usd T or --task-budget-usd B only when
   explicitly set. Startup timeout bounds owner startup and the policy startup
   gate of legacy READY runs; it is not another task clock. Keep the process
   handle and poll status-engineering
   until it exits. Request stopping with stop-engineering, then inspect every
   sealing result, process state and needs_review field. Claimed batches/worlds
   are single-use; preserve unknown state and evidence rather than restarting.
7. Report the inner model profiles, exact tasks, concurrency, per-case terminal
   states and evidence paths. Clearly identify anything still unverified.

The outer manager owns setup/supervision; the inner model owns task decisions,
visual reasoning and robot actions. Keep private answers isolated and frozen
inputs unchanged. External action hints, action injection and modified scoring
are outside this protocol. Provider bills are authoritative. CLI-reported cost
limits are estimates, not a provider payment ceiling; each task has its own
accounting, while adaptive roles share that task's ledger. A task concurrency
setting is not the number of concurrent API requests.
```

Multiple models and cases form a Cartesian product in this native entry. One
model and the four families at Level 1/minimum arms produces four tasks. Prepare
again on the target host instead of copying a prepared directory's absolute
paths. `opus_subscription` remains an unverified native subscription candidate;
its explicit OAuth configuration does not import Desktop login automatically.
For the unified one-profile workflow, use `robofrontier --config SETTINGS.toml`
with `policy.engine="claude"`, a Claude profile, and `run --engineering`; the
native engineering-only qualification restriction still applies.
