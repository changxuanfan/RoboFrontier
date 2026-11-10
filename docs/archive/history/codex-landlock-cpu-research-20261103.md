# Codex on a CPU container without namespaces

Research date: 2026-11-03. Target: RoboFrontier, Codex CLI 0.165.0, GPT-6.1 Sol through native ChatGPT authentication. This note records a tested research prototype and remaining integration requirements; it does not qualify a formal benchmark run.

Integration update, 2026-11-04: the production runner now exposes the explicit
`runtime.codex_tool_backend = "landlock-v1"` option in configuration schema 5.
See [the current engine guide](../../engines/codex.md). The production worker adds
capability dropping and restrictions on io_uring, queued signals, process-memory
inspection and process-group escape to the research prototype below. Its native
subscription transport uses HTTP/SSE while retaining native authentication.
The target's production protocol check exercised eight concurrent roles, fork and
resume, inspected the exact three-tool inventory and rejected eleven forged native
calls. The final physical engineering validation started sixteen concurrent runs
and 116 initial roles across all four topologies; every role used the robot tool,
and all sixteen runs sealed successfully after an operator stop, with no unresolved
actions or host errors. The earlier 180-second-cutoff validation retains two
`needs_review` records for physical actions that had not settled within the budget
stop grace; those records were not relabeled or replayed. These are startup,
isolation and lifecycle checks, not evidence of 24-hour stability or task success.

## Finding

The target-CPU research prototype passed both offline protocol/isolation tests and a minimal real GPT-6.1 Sol subscription image/tool, manual-compaction and fork test. It retains native Codex sessions while replacing model-accessible filesystem tools with a host-owned Landlock broker. Keep the existing named permission profile. Disable native shell and image tools, remove the native patch handler through the frozen model catalog, and expose separately named dynamic tools. Every command or image read from those tools must execute inside an independently enforced per-run boundary. No `danger-full-access`, `externalSandbox`, or legacy-Landlock override is necessary for this design.

The source, offline and live-probe evidence support integrating this path. This remains a research prototype, rather than a production runner backend or qualified formal benchmark configuration. Multi-role concurrency, complete task lifecycle, long-duration operation and a backend-aware production qualification receipt remain untested.

## Target-CPU offline experiment

The report was read directly over SSH from `/workspace/RoboFrontier/runs/engineering/codex-landlock-research-20261103/report.json` on the target CPU. The adjacent `probe.py`, `client.js`, `executor.py`, `launch.json`, `models.json`, `rules.json`, `requests.json` and logs retain the actual experiment configuration and protocol evidence.

- Real Codex CLI 0.165.0 communicated with a local Responses stub through 28 requests. External model calls: **0**. Client exit code: **0**; report `passed: true`.
- The complete advertised model tool inventory was **`policy_shell` only**. The final configuration retained the native named permission profile, with no external-sandbox or full-access selection.
- All eleven deliberate native-call attempts were rejected: `shell_command`, `exec_command`, `write_stdin`, function-form `apply_patch`, `view_image`, `read_file`, `list_dir`, `js`, `spawn_agent`, namespaced `collaboration.spawn_agent`, and freeform `apply_patch`. The native-execution sentinel file was not created.
- The parent dynamic shell call, its isolation-check call, and the forked-thread shell call each exited **0**. The fork's parent was verified.
- All eighteen kernel/isolation assertions passed: public task reads; role-workspace writes; private temporary writes; rejection of own private inputs, repository source, another run, authentication home, credential backup, symlink access, parent environment, parent file descriptors, public-input writes and outside-workspace writes; rejection of Unix, TCP and UDP socket creation; a sanitized environment; and confinement inherited by descendants. For assertions about forbidden accesses, `true` means the expected denial occurred.

The worker loads the trusted rules and libseccomp, installs additional syscall restrictions, calls the existing Claude `restrict()` implementation, then executes a non-login Bash with only `PATH`, `LANG` and a private `TMPDIR` in its environment. The host closes inherited descriptors. The frozen access table also denies `/proc` and uses the run's private temporary directory rather than general `/tmp` write access.

The first inventory probe found built-in collaboration tools even though `features.multi_agent=false` had been set: the model template's V2 metadata took precedence. The final probe additionally used `agents.enabled=false`, `features.multi_agent_v2=false`, `multi_agent_version: "disabled"`, and disabled the question tool. Both code-mode features were explicitly disabled. This is why exact tool-inventory admission is necessary.

These results establish the tested paths on this container. They do not establish that every kernel IPC or process-control primitive is blocked. In particular, the current worker's explicit deny list does not cover every `pidfd` signal, queued-signal or `io_uring` operation; production hardening needs an explicit policy and tests for those surfaces before claiming broad malicious-process containment.

## Minimal real subscription experiment

The live report was also read directly over SSH from `/workspace/RoboFrontier/runs/engineering/codex-landlock-research-20261103/live/report.json`. Local copies of the offline report (`runs/engineering/codex-landlock-research-20261103/report.json`) and live report (`runs/engineering/codex-landlock-research-20261103/live/report.json`) accompany the research evidence; `runs/` is not tracked in git.

- Requested model: **`gpt-6.1-sol`**, effort **`high`**; authentication mode: **`chatgpt_subscription`**. The report returned **`passed: true`**.
- The parent native thread completed, correctly identified the red probe image, and requested `policy_shell` to execute the eighteen isolation assertions. Its command exited **0**, with every assertion **true**.
- Native manual compaction completed. A native child fork was created and its parent relation verified.
- The forked thread completed, retained the red-image context, and independently requested the same kernel/isolation test through `policy_shell`. Its command also exited **0**, with all eighteen assertions **true**.
- The probe explicitly records **`formal_run: false`** and **`world_started: false`**. It launched no robot world or formal benchmark task.

This establishes that real subscription inference can use the restricted broker on this CPU and that the tested native compaction/fork path remains functional. It does not establish a full context-window limit, automatic compaction threshold, provider-internal model identity, task ability, multi-role concurrency or 24-hour stability. The report records the requested model and actual native-authentication path rather than claiming independent verification of the provider's internal model implementation.

## Why Claude runs and native Codex commands do not

RoboFrontier already selects `landlock-v1` for Claude when bubblewrap cannot create namespaces. It builds `CLAUDE_CODE_SHELL_PREFIX` from the frozen access table. This is project-supplied confinement of model Bash commands; it does not sandbox the trusted Claude process or its robot MCP service. See [Claude confinement](../../../robofrontier/engines/claude/runner.py), [Landlock implementation](../../../robofrontier/engines/common/landlock.py), and [engine documentation](../../engines/claude-code.md).

Codex's native Linux backend deliberately rejects legacy Landlock for a filesystem-restricted policy because it cannot isolate app-server sockets. The exact version's check is in [linux_run_main.rs, lines 380–387](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/linux-sandbox/src/linux_run_main.rs#L380-L387). [Official permissions guidance](https://learn.chatgpt.com/docs/permissions) documents this limitation. Changing that check or silently disabling the native sandbox would not establish an equivalent boundary.

The reported target probes show `unshare -Ur true` denied with `EPERM`, while Landlock ABI 4 is available. Kernel user-namespace enablement is already on. This is an outer-container compatibility limitation, rather than inability to authenticate or call GPT.

## Verified source behavior in Codex 0.165.0

The official `rust-v0.165.0` tag resolves to commit `360319d8dee62d87e2d59fc0c21805d79519cfed`. All source links below pin that commit.

| Surface | Relevant behavior |
| --- | --- |
| Shell | `features.shell_tool=false` returns before registering both `exec_command` and `write_stdin`. A disabled model shell type also prevents registration. [Source](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/tools/spec_plan.rs#L1242-L1275). |
| Image reads | `features.view_image=false` prevents registration of `ViewImageHandler`. [Source](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/tools/spec_plan.rs#L1439-L1454). |
| Patches | `apply_patch_tool_type: null` in effective model metadata makes `is_some()` false, preventing registration of `ApplyPatchHandler`. Disabling shell alone does not disable patches. [Source](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/tools/spec_plan.rs#L1425-L1428). |
| Forged calls | An unregistered tool name returns an unsupported-call error before a handler runs. Removing only a tool's advertisement is weaker than preventing its registration. [Source](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/tools/registry.rs#L725-L746). |
| Dynamic names | External tools named `exec_command` or `shell_command` in the default namespace are explicitly skipped. Use names such as `policy_exec` and `policy_image`. [Source](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/tools/registry.rs#L539-L556). |
| Forked tools | Dynamic tools are persisted in session metadata and restored from conversation history when not explicitly supplied. [Source](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/session/mod.rs#L849-L855). |
| Forked configuration | Normal `thread/fork` can reload configuration through the process configuration manager. Put safety-critical overrides in app-server startup arguments, not only `thread/start.config`. [Source](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/request_processors/thread_processor.rs#L5583-L5610). |
| Built-in subagents | `features.multi_agent=false` does not override model metadata selecting V2. Use `agents.enabled=false`, `features.multi_agent_v2=false` and frozen `multi_agent_version: "disabled"`. The explicit agents switch forces the disabled version before model metadata is consulted. [Source](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/config/mod.rs#L1663-L1689). |
| User questions | `tools.experimental_request_user_input.enabled=false` removes this utility tool when the benchmark intends a strict robot/broker-only inventory. [Source](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/config/mod.rs#L2782-L2789). |

The [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) documents the shell and image feature switches. The [app-server documentation](https://learn.chatgpt.com/docs/app-server) documents experimental dynamic tools, `item/tool/call`, persistence on resume, and `externalSandbox`. The latter declares an existing external sandbox; it supplies no new filesystem isolation itself.

## Minimal broker design

1. Add an explicit, frozen Codex tool-execution backend for this host. Keep the native backend as the default on compatible hosts. Do not turn a failed native doctor into an unconditional pass: the selected broker backend needs its own actual confinement probe.
2. At app-server process startup, disable native shell, image, shell snapshots, personal apps/plugins, built-in subagents, and goals. Retain disabled web search, disabled Node REPL, a direct tool mode and disabled inherited MCP servers. Freeze `apply_patch_tool_type: null`; prevent a personal model cache from replacing this metadata.
3. Register only host-owned `policy_exec`, `policy_image` and the existing bound robot tool, plus any explicitly reviewed utility tools. The host derives the run and role from the calling native thread; tool arguments must not select another run, credential home or permission table.
4. Spawn a fresh isolated subprocess for each filesystem operation. Landlock enforces the run's frozen read/write table. Supply a minimal environment and close inherited file descriptors. Do not pass Codex/Claude credentials, private robot connections or app-server handles to it.
5. Read an image and encode its bytes inside that isolated process. Merely checking a path and then opening it in the unrestricted Node host introduces an avoidable enforcement gap. Do the same for file reads, writes and helper-code execution.
6. Keep native Codex's trusted authentication and session machinery outside the broker. The model's robot tool continues through the existing role-bound host, as it does for Claude. This preserves the distinction between trusted harness access and model-controlled process access.

The model's available native filesystem surface must be established from an actual outgoing model request. Source switches are not a substitute for an inventory. Reject an unexpected tool surface before starting a formal run, and test direct, namespaced and freeform attempts to invoke disabled handlers.

In particular, `tool_mode: null` falls back to the process's code-mode features; set both `features.code_mode=false` and `features.code_mode_only=false` to pin Direct mode. [Source](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/tools/mod.rs#L64-L74).

## Boundary requirements and limitations

Landlock ABI 4 supplies filesystem and TCP restrictions, but does not by itself provide the newer signal or Unix-socket scopes. [Linux's Landlock documentation](https://docs.kernel.org/userspace-api/landlock.html) describes its rules, inherited restrictions and special-filesystem limits. An additional seccomp layer can deny socket creation/connection and other selected cross-process syscalls; seccomp itself is only one mechanism in a larger sandbox. [Kernel seccomp documentation](https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html) describes filter inheritance and that distinction.

For the actual target, explicitly prove that broker children cannot contact app-server Unix sockets or gain privileged file descriptors. Closing inherited descriptors and cleaning environment variables is necessary. Address `/proc` access and process-memory inspection as well: the shared access table currently starts with `/` readable, while `/tmp` is writable. Landlock restrictions concern file-content access and mutations; they are not a promise to hide all metadata. Describe the supported boundary as the tested benchmark isolation contract, not containment of every possible malicious native process.

During setup, a credential backup had been placed at `/workspace/.robofrontier-auth`, outside the checkout denied by the frozen table. It was moved to `/workspace/RoboFrontier/.robofrontier/credential-backups/sol61`, under the denied repository tree, and the former backup file was removed. The offline credential-backup denial assertion passed. Existing snapshots do not acquire new deny entries automatically. This was an actual discovered path omission, independent of the namespace failure.

## Required qualification

- Actual target-CPU confinement: allow public task inputs, role workspace reads/writes and approved temporary files; deny repository/source, private evaluation/XML, other runs and credential locations. Exercise symlinks, relative traversal, inherited descriptors, parent-process paths and child processes.
- Network/control isolation: deny TCP and UDP communication and app-server Unix-socket access. Distinguish a kernel-enforced denial from a missing target or an invalid test address.
- Real installed Codex with a local Responses stub: inspect exact tool schemas; perform successful broker calls; deliberately emit forbidden native calls and check rejection without side effects; repeat in forked and resumed threads. No external inference is required for this layer.
- Live subscription compatibility: the minimal actual image/tool, manual-compaction and fork probe above passed. The production backend still needs a matching compatibility receipt with its final frozen configuration and runtime evidence; the research report must not be substituted for that receipt.
- Multi-role engineering run: prove concurrent role tools remain in their assigned runs and roles, then check clean shutdown and evidence collection.

Changing executable source, launch metadata or the access table requires newly prepared formal run directories. Do not modify the already prepared sixteen runs in place or rewrite their manifests to make them appear equivalent.

## Other route considered

Codex also contains a native `exec-server` that provides process and filesystem services to a separate app-server. A per-run Landlock-restricted executor could retain native tools, but it requires proof that every file operation routes through that executor and that its authenticated control transport is inaccessible to model commands. See the versioned [exec-server README](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/exec-server/README.md). This is a larger integration surface than a small dynamic-tool broker and is not the first implementation recommendation.
