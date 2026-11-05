# Research: Codex subscription authentication in the Slurm runner

Research date: 2026-11-04, Asia/Hong_Kong. Repository baseline: `685c2c36d61bb696a65c22e5fae1338fb4c3d443`. Native reference: Codex CLI `0.165.0`, upstream tag `rust-v0.165.0`, commit `360319d8dee62d87e2d59fc0c21805d79519cfed`.

Status: research baseline, followed by the local implementation described in [the job-scoped runner guide](../running/slurm-subscription.md). The original research below used source inspection, official documentation and a no-model native protocol probe with synthetic credentials and loopback endpoints. Subsequent implementation tests exercised 36 parents and 72 forks against local synthetic Responses, not a real provider. The backend is not cluster/provider qualified. No real subscription credential was read or refreshed, no login or Slurm job was performed, and the sixteen active Sol trials were not changed. No subagents were used.

## Finding and recommended direction

Queued subscription execution is technically feasible, including automatic native credential refresh, NVIDIA observation rendering and the existing Landlock file-tool boundary. It is not achieved safely by relaxing the current API-only admission check and copying one `auth.json` into every task home.

The recommended candidate is **one managed-auth Codex app-server per single-node Slurm allocation**, serving independent task/role threads through a trusted job gateway. Each task retains its own world owner, scheduler, workspace, private state and frozen access table. One native AuthManager owns the refreshable credential chain. Jobs using that credential stream execute serially; tasks within one allocation remain concurrent. This changes native process topology and must be introduced as a new explicit backend with fresh qualification, not silently substituted for the current per-task app-server arrangement.

An alternative host-supplied token broker could preserve one app-server per task, but the current upstream token-injection interface is experimental and its pinned source explicitly labels it internal. It is not the default recommendation for this version.

## What exists and what blocks it

| Area | Current behavior | Required work |
| --- | --- | --- |
| Submission | `slurm_job.submit()` accepts API credentials only | Add explicit subscription authentication mode/reference; do not silently fall back to paid API auth |
| Runtime homes | Slurm requires node-local task homes; Codex batch rejects native subscription with task-scoped homes | Add a job-scoped native engine home for the new backend; keep task runtime databases separate and node-local |
| Native process | Each PolicyHost spawns its own app-server | Introduce one trusted job gateway with task-scoped transports and ownership checks |
| Refresh | Managed by each native AuthManager | Ensure a single manager owns a given refresh chain, then persist its updated cache |
| Rendering | Linux `nvidia` already selects EGL; `cpu` selects OSMesa | Reuse NVIDIA branch and verify the actually allocated device inside the job |
| File access | `landlock-v1` binds policy tools to each frozen run table | Add all job engine/auth/IPC paths to explicit denies before freezing task inputs |
| Collection | Stopped evidence/session collection excludes auth | Export sessions by bound task/thread IDs; persist auth through a separate private channel |

Sources: [Slurm entry](../../robofrontier/slurm_job.py), [batch admission](../../robofrontier/codex/batch.py), [native host](../../robofrontier/codex/codex_policy_host.js), [configuration/render environment](../../robofrontier/configuration.py), [file-access policy](../../robofrontier/policy_access.py), [existing Slurm guide](../running/slurm.md).

## Authentication facts and scope

Codex supports file-backed managed ChatGPT auth and device-code login. Native managed auth owns renewal; a queued process can reuse its cached grant. The official advanced workflow requires preserving the updated cache, warns against concurrent/multi-machine reuse of one copy, and assumes trusted private automation. It also explicitly excludes public/open-source repository workflows. This proposal is for a private, operator-controlled HPC deployment, not a credential-enabled public CI workflow; that deployment must still fit the documented scope. Technical feasibility is not a claim that every deployment is officially endorsed. [Authentication](https://learn.chatgpt.com/docs/auth), [advanced managed-auth workflow](https://learn.chatgpt.com/docs/auth/ci-cd-auth).

The app-server exposes managed `chatgpt` authentication and the `chatgptDeviceCode` flow. Its external `chatgptAuthTokens` interface delegates renewal to the client and has an approximately ten-second refresh-response deadline. [App-server authentication](https://learn.chatgpt.com/docs/app-server#auth-endpoints).

The pinned source additionally marks `LoginAccountParams::ChatgptAuthTokens` as unstable/internal. Its ordinary managed-auth refresh lock is an in-process `Arc<Semaphore>`; file persistence truncates/writes `auth.json`. These are not a distributed lock and transactional credential store shared by independent app-server processes. Guarded disk reload helps recovery but does not justify assuming concurrent refresh copies are safe. Sources: [upstream account protocol](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server-protocol/src/protocol/v2/account.rs), [AuthManager](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/login/src/auth/manager.rs), [file storage](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/login/src/auth/storage.rs).

### Options considered

| Option | Assessment |
| --- | --- |
| Copy the same refreshable cache into sixteen isolated homes | Reject as the default: independent rotations can make later copies stale; shutdown copies can overwrite newer credentials |
| Sixteen native app-servers share one mutable auth file/home | Does not establish serialized native refresh; also shares mutable session/config state. Not qualified for the new Slurm entry |
| One native app-server, independent task threads/worlds | Preferred candidate: keeps renewal inside one native AuthManager; requires a real task-routing adapter and new fault-domain tests |
| Separate independently bootstrapped grant for every task slot | Possible conservative alternative, but needs distinct interactive bootstrap/credential streams and serialization of each stream; not sixteen copies of one grant |
| Broker plus external-token app-server mode | Experimental alternative only; source/documentation status and timeout must be accepted and independently qualified before use |
| Put an OAuth access token in an API-key environment variable | Does not preserve the current native managed-auth/renewal contract; no recommendation to substitute it |

## Queue and credential lifecycle

1. **Bootstrap once in a short allocation.** A dedicated CPU job runs native `codex login --device-auth` with file storage and a private home. The operator completes the code in their browser. No browser or direct SSH session is needed on the compute node. The code is generated after the job starts, so time spent queued does not consume its validity window. If the account disallows device login, use the documented trusted-machine cache-transfer route. No real bootstrap was executed during this research.
2. **Store a private credential-stream reference.** Keep its cache outside the repository, submissions, run workspaces and evidence. Use a private directory/file and no token-valued command-line arguments, environment exports or queue metadata. A public configuration may carry an opaque reference, never the cache contents. Queue preparation freezes code/settings, not a soon-to-be-stale token snapshot.
3. **Serialize allocations sharing that stream.** A stable Slurm job name plus `--dependency=singleton` is a candidate scheduler guard; add an operator-storage lock/fencing check at admission. Verify the target site's dependency and shared-filesystem locking behavior. The lock covers bootstrap/renewal/write-back too, not just model turns. A different independent login stream may have its own lifecycle, while account usage limits remain shared. Slurm defines singleton in terms of the same user and job name. [Scheduler dependency reference](https://slurm.schedmd.com/sbatch.html#OPT_dependency).
4. **Load the latest generation only after allocation starts.** Acquire the stream lease, check owner/account and file format, then seed a fresh job-local engine home on verified node-local storage. Read the current persisted generation, not an original bootstrap seed saved with an older submission.
5. **Admit authentication before task START.** Verify managed ChatGPT mode and the intended account/workspace. Use a bounded authenticated account/rate-limit check; do not treat a local logged-in status as proof that the credential can renew or reach the provider. In this pinned version `account/read` invokes the refresh helper but can continue to read cached account state after refresh failure, so its mere JSON-RPC success is insufficient evidence. Native source: `refresh_token_if_requested()` and `get_account()` in the account processor.
6. **Admit hardware and isolation before START.** Verify EGL/device identity, task permission profiles and actual tool inventories, then start the worlds through the ordinary persisted START path. Queue time and bootstrap waiting must not start a trial's 24-hour clock.
7. **Let native Codex renew.** Use the current managed ChatGPT provider behavior, including the existing `robofrontier_openai_http` SSE alias. Remove inherited API-key overrides. Do not implement an OAuth refresh HTTP client in RoboFrontier or redirect subscription requests into an API-key billing path. Preserve `gpt-6.1-sol` and the selected `high` effort.
8. **Persist native-produced updates during the job.** A trusted supervisor watches/reconciles only that owner's auth file. Read a complete valid file after its write has settled; bind it to the expected credential owner; commit a new private generation using temporary-file write, fsync, atomic replacement and a fencing/generation check. Never publish tokens or token-bearing exception bodies into run logs. Periodically reconcile in case filesystem notifications coalesce.
9. **Close and write back.** On normal completion or the existing USR1/TERM path, stop new model dispatch, settle/seal worlds using existing stop semantics, close the native server, persist its final valid credential generation, and only then release the stream lease. Closing a process is sufficient; do not log out/revoke the grant at every job end. Evidence stage-out remains separate from credential persistence.

This gives automatic reuse after queueing and native renewal during ordinary execution. It does not promise perpetual authentication. A revoked/expired grant requires a fresh bootstrap. Native rotation followed immediately by node loss can also lose an unpersisted new cache: filesystem watching reduces this window but cannot make the server's token rotation and remote durable storage one atomic transaction. Such a failure must be reported as requiring reauthentication, rather than restoring an old seed and repeatedly submitting duplicate work.

## Job-local layout

Illustrative proposed layout; it is not the current staging schema:

```text
private persistent credential store (outside repository/evidence)
  sol61-hpc/current-auth.json + private generation/lease metadata

$SLURM_TMPDIR/robofrontier-JOB_ID/
  engine/codex/                 # one native engine home, auth + native session DB
  engine/control/               # trusted gateway control endpoints
  source/runs/policy/batch/
    MODE/PROFILE/CASE/
      public/                   # that task's observations and public inputs
      workspace/                # that task's policy files
      private/state/            # separate task runtime SQLite/world ownership
```

All active SQLite files and native session state remain node-local. The shared durable credential store contains credential state only, not a shared live SQLite home. A credential update is never placed in `evidence.zip`, `source.tar`, the stage-out fallback tree, or a policy-visible result.

## Task isolation with a shared native server

The new gateway is a trusted host component, not a model tool. Each run gets a bound client channel; the gateway registers ownership of parent, snapshot and delegate thread IDs before any turn starts. It rewrites transport request IDs so simultaneous per-run counters cannot collide, routes results/events to the correct host, and rejects cross-run thread, interrupt, fork or response attempts. Fork ownership derives from the verified parent and persisted delegation, never from a model-supplied run path. Unknown/unbound tool calls fail closed.

Keep a distinct named permission profile for every run, generated from its frozen table. Pass that profile explicitly on thread start/resume/fork; do not pass the legacy `sandbox` option alongside it because the native API treats them as alternatives. Do not build a union profile that lets every thread access all task workspaces. The gateway must prevent a client from selecting another task's valid profile. Native source: [`ThreadStartParams` and fork/resume parameters](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server-protocol/src/protocol/v2/thread.rs).

Preserve the actual Landlock worker path: the host binds the run, the worker closes inherited descriptors, clears its environment, applies seccomp and Landlock, drops capabilities, then interprets the operation. Permit only the verified `robot`, `policy_exec` and `policy_image` inventory. Existing native shell, code execution, apply-patch, browser, plugins, MCP inheritance and native multi-agent tools remain disabled. The native controller/fork protocol remains host-managed as in the current runner; no prompt can request a different file-access table.

Explicitly deny the persistent credential root, job engine/auth directories, trusted IPC directories, all checkouts, other task files and `/proc` before policy tables are frozen. The default table permits reading many unrelated host paths, so placing a new credential path outside the checkout without adding a deny would be a real omission. Mode 0600 alone does not isolate same-UID policy code. Existing code: [policy table](../../robofrontier/policy_access.py), [worker](../../robofrontier/codex/tool_worker.py), [tool broker/admission](../../robofrontier/codex/tool_broker.js).

GPU driver access belongs to the trusted world/render process. It does not require giving policy tools broader filesystem, network, process-memory or IPC access. Site Landlock ABI/seccomp support must be tested inside a compute allocation; the existing CPU container's receipt is not a receipt for the H800 node.

One shared native server expands the model-host failure domain across tasks. Its failure must stop new dispatch and follow existing sealing/recovery semantics; it must not automatically recreate turns, replay motions or change original action IDs. Per-task world processes and durable action stores are retained so this boundary is explicit.

## NVIDIA rendering

The observation path already supports `render.device="nvidia"`: it selects `MUJOCO_GL=egl`, `PYOPENGL_PLATFORM=egl`, disables forced software mode and rejects a renderer that is not NVIDIA. Reuse that path for MuJoCo observations; Factory Blender/Cycles is a separate offline rendering pipeline. Physics remains on CPU. See [rendering environment](../../robofrontier/configuration.py), [world renderer](../../robofrontier/pipeline.py), [backend validation](../../robofrontier/render_backend.py).

Request a GPU through the site's supported Slurm GRES syntax and preserve the allocation's device environment. Slurm can remap GPU indices within a job. Installed MuJoCo 3.16.0 EGL code enumerates EGL devices and optionally selects `MUJOCO_EGL_DEVICE_ID`; it does not consult `CUDA_VISIBLE_DEVICES` in that selector. Consequently do not assume that CUDA logical device 0 equals EGL device 0. Verify the allocated GPU's identity/device visibility and actual EGL renderer inside the allocation, including a nonzero physical GPU allocation case. [Slurm GPU management](https://slurm.schedmd.com/gres.html#GPU_Management).

Keep camera parameters, image resolution, quality and task physics fixed for the comparison. Test 1, 4 and 16 simultaneous contexts for memory, rendering latency and world throughput; do not infer 16-context capacity from one successful H800 frame. Existing real-cluster receipts establish earlier H800/EGL rendering and synthetic-model lifecycle checks, not this subscription gateway or its rate limits. See [recorded Slurm qualification](../running/slurm.md).

## Proposed implementation seams

| File/module | Proposed responsibility |
| --- | --- |
| `configuration.py` | New explicit subscription/credential-reference mode and job-scoped engine option, schema-versioned; retain current API/task defaults |
| `slurm_job.py` | Bootstrap/submission reference, stream serialization, late credential admission, local engine directory, private persistence and stop ordering |
| New `slurm_auth.py` | Private cache validation, owner/generation checks, leases and durable write-back; no custom OAuth token exchange |
| New `codex/job_gateway.js` | One native app-server, thread ownership/routing, request-ID remapping and permitted per-task RPC surface |
| `codex_rpc.js` | Injectable transport so a PolicyHost can use a gateway client instead of spawning its own process |
| `codex_policy_host.js` | Bind to the task channel; retain role/delegation and durable action semantics; distinguish closing a client from closing the shared server |
| `codex/batch.py` / `codex/launch.py` | Explicit job-mode admission, stable per-run named profiles, one model catalog, managed-auth provider identity and updated receipts |
| `policy_access.py` / tool admission | Deny all new private engine/credential/IPC roots; verify actual inventory and per-run permissions before inference |
| collection / stage-out | Export only each run's owned transcripts and immutable evidence; never recursively copy the engine home |

Do not merely remove the API-only/task-home checks: they currently enforce assumptions this design changes. The new backend needs its own fingerprint/receipt and fresh frozen runs. Existing prepared runs and the active sixteen CPU trials must keep their original source/configuration.

## What was tested locally

The research probe used installed CLI 0.165.0 with an isolated temporary home, synthetic JWT/cache values, a loopback OAuth server and loopback account-routing fixture. Four managed-refresh requests rotated the fixture credential chain without stale-token rejection; the native file retained the latest generation with mode 0600. One app-server created two different parent threads with the requested `run_a` and `run_b` permission profiles. No `turn/start` or model endpoint request occurred. Temporary credential state was removed when the probe exited.

An empty-parent fork was correctly rejected because no rollout existed; this no-model probe therefore does **not** qualify real fork lineage, the new gateway, kernel isolation, long-running concurrency, GPU rendering, actual provider refresh or Slurm execution. Early fixture failures were corrected locally (catalog instructions and account-routing metadata); no production module was changed.

Reproduction and result: probe script `runs/engineering/slurm-subscription-research-20261104/probe_native.py` and result `runs/engineering/slurm-subscription-research-20261104/native-probe-result.json`, kept with the local research evidence because `runs/` is not tracked in git. Run the probe locally; its identities and tokens are fixtures, not authentication inputs for a real job.

## Acceptance sequence before deployment

1. Offline unit/integration checks for credential generation/fencing, invalid/partial native writes, stale seed rollback, wrong-owner rejection and token-free logs/archives. Simulate expiry/revocation against mock endpoints, not the active account or system clock.
2. Real native protocol tests for two then sixteen task channels, concurrent identical request IDs, fork/resume ownership, unknown-thread rejection, cross-run profile selection, forbidden native tool calls and shared-server failure. No robot action may be dispatched twice.
3. Linux allocation tests of the actual Landlock/seccomp worker against own-private/other-task/auth/IPC/proc paths, symlinks, descriptors, inherited environment and child processes. Test that trusted EGL access works while policy access stays denied. Unsupported isolation is an admission failure.
4. Short queued device-login/auth-only admission on a dedicated credential stream, plus durable refresh/write-back and the next queued job reading that refreshed generation. Do not seed tests from the running CPU batch's credential copy. Verify compute-node egress, account/workspace selection, storage locks and singleton behavior.
5. Fresh bounded genuine-model image/tool/compaction/fork checks using the exact Sol profile and new backend. Authenticate and validate the GPU first; then exercise one, four and sixteen worlds, including a normal physical action and delegate handback. These are future provider calls, not part of this research.
6. USR1/TERM stop, shared-server crash, failed credential write-back and interrupted collection. Verify final auth persistence, stopped evidence, original action IDs and no replay. Explicitly retain the hard-node-loss credential window as an operational limitation.
7. A separately labeled long run for natural renewal, capacity/429 behavior, GPU memory and stage-out. A successful short probe does not qualify a 24-hour sixteen-task experiment.

The outstanding work is implementation and cluster/provider qualification, not obtaining another interactive shell on a compute node. The initial login can itself be queued, and subsequent accepted jobs can reuse and renew native-managed authentication automatically within the serialized credential stream.
