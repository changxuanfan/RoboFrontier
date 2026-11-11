# Slurm: frozen submission, node-local execution, verified stage-out

This is the unified integration entry. It replaces the old Luna sbatch script,
which placed active runtime files in the shared checkout. The implementation
has offline tests and bounded real-cluster receipts. On 2026-11-02, job `428877`
at source `29e1211` completed four Single native Claude/physics owners, actual
NVIDIA H800 task observations and ordinary A +5 mm actions through the production
stage/execute/collect/ZIP/stage-out flow. All 1,728 returned files verified through
restoration without restarting their worlds. Active databases stayed node-local;
audit read only hash-verified stopped copies. Peak started tasks was four, with
three overlapping motor actions. The model endpoint was a scripted HTTPS service,
with zero real-provider calls. This qualifies that four-case normal lifecycle.
At source `8b273ab`, jobs `428931` and `428948` also run all 36 Adaptive owners,
each with a native Delegate, H800 observations, a completed A +5 mm action and
verified handback. Each has 72 distinct bound native sessions and 36 overlapping
started tasks. Actual Slurm batch USR1 requests seal the owners with no unresolved
action; job/batch/step finish 0:0. All 18,239 returned files from `428948` verify
through restoration without physics. Its step peak RSS is 23,538,708 KiB with
36 CPUs and 128 GiB requested. The scripted HTTPS endpoint makes no real-provider
calls. Both returns retain needs_review and incomplete collection because active
model-turn cancellation leaves accounting uncertain; resolved physical actions
do not clear that review. This is bounded Adaptive capacity and USR1 stage-out
evidence, without full-task/model-success, 24-hour-load, standing-team capacity,
SIGKILL/power-loss or genuine provider/subscription claims.
The earlier job `428862` remains a minimal EGL/JPEG probe. See the
acceptance ledger (`docs/archive/unified-main.md`, in the [archive tag](../history.md)) for source identities and open gates.

## Prerequisites

For the new, locally tested job-scoped Codex subscription backend, see
[Slurm subscriptions](slurm.md). It requires separate live
qualification; the existing API and engineering qualification below does not
qualify that backend.

Use a Linux login node with a clone of this branch, a committed clean tracked
checkout, the locked Python environment, the selected native CLI, and Slurm's
sbatch/srun commands. The compute nodes must see the login node's Python
environment and its installed native CLI on PATH. This entry does not install
packages or contact the asset release server on a compute node.

The cluster must track **all descendants of each job step**, including detached
CLI processes, using an appropriately configured Slurm process tracker/cgroup.
The batch shell starts the model/simulator processes in an srun step and performs
stage-out only after that step returns. Additional world/supervisor lock checks
reject stage-out if a writer is still live.

Use the site's documented SLURM_TMPDIR, or set slurm.scratch_root to an existing
node-local scratch directory. The program rejects network/unknown filesystem
types. Filesystem type checking does not replace your administrator's storage
policy; verify that the chosen directory is genuinely node-local. A generic
TMPDIR or a directory under the shared checkout is not used as a fallback.

Live runtime SQLite, per-task CODEX_HOME, temporary files, native sessions, motion,
and observations live in that node-local directory. WAL remains enabled there.
No live database is opened by the submission monitor or copied across a Docker
or network filesystem boundary.

## Configure once

Defaults are Luna high, official API, adaptive, 36 requested concurrent tasks,
a 24-hour task clock from each task's persisted START, and 0.3 seconds between
initial host launches. The default render device is NVIDIA EGL on Linux.
The initial host launch interval does not slow robot calls or every file access.

Create an untracked site.toml, for example:

~~~toml
[slurm]
partition = "YOUR_PARTITION"
account = "YOUR_ACCOUNT"
gpus = 1
cpus_per_task = 36
memory_gib = 128
time_limit_s = 90000
stop_warning_s = 600
~~~

These CPU and memory values are resource **requests**, not a measured guarantee
that this allocation can sustain 36 tasks and every model's delegates. Check
scratch capacity, memory, CPU, API rate limits, and the site's allocation policy.
The program does not silently reduce the requested task concurrency.

For CPU rendering, use:

~~~toml
[render]
device = "cpu"

[slurm]
gpus = 0
~~~

The physics engine runs on CPU in both render modes. NVIDIA EGL affects image
rendering. CPU mode selects OSMesa/llvmpipe. Missing hardware or a driver mismatch
is an error, rather than a silent switch to a different rendering backend.

Set the selected API credential in the login environment or local ignored .env.
The CLI loads it into the inherited sbatch environment. Secret values are not
written into the job script, source snapshot, configuration, or returned ZIP.
The site's normal Slurm environment/spool protections still apply. Do not share
.env, authentication directories, or a raw dump of your job environment.

Subscription caches are not staged by this entry. The Claude subscription token
(`CLAUDE_CODE_OAUTH_TOKEN`, profile `haiku_subscription_token`) is long-lived and
travels in the environment like an API key. Claude runs need passed precheck receipts, as Codex runs need theirs. Where the cluster cannot
reach Anthropic, Claude may use the managed Mac route (`slurm.egress_mode = "mac-ssh"`,
see [Slurm subscriptions](slurm.md#managed-mac-egress)) without a
credential store; the CLI then receives only that route's `HTTPS_PROXY`/`NO_PROXY`.
With `slurm.egress_pause_s` above 0 (the default, 172,800 s), start the Mac connector
with `--engine claude` and the same `--pause-grace-s`, so outage detection probes
`api.anthropic.com`, the host Claude actually uses.
Claude's own Bash sandbox needs `bwrap` and `socat` on the compute-node PATH. On Linux
it masks a denied folder with an empty tmpfs, so a Bash write there appears to succeed
but is discarded with the sandbox; reads stay denied and nothing reaches the run.
All four native Claude modes have engineering entries; see
[standing teams](../engines/claude-code.md#standing-teams). Their local lifecycle checks do not
establish real-cluster or provider qualification.

## Preflight and submit

A real provider preflight is a separate, explicitly billable action:

~~~bash
robofrontier --config site.toml preflight --confirm-spend
~~~

For Claude, select a Claude profile and specify its explicit preflight budget
estimate. A smoke-only receipt does not qualify scored Codex runs. The execution
runner still checks the selected profile hash, generated model catalog, and
installed native CLI version before starting tasks. A receipt from another
model/configuration or CLI version must not be reused.

Commit tracked technical changes before preparing a source snapshot. Ignored
.env and run data are excluded from Git's snapshot.

~~~bash
robofrontier --config site.toml slurm-submit \
  --output runs/submissions/luna-all-36 --queue
~~~

Without --queue, this command only freezes the submission. It makes zero model
calls and does not start a simulator. Asset download may occur on the login node.
Do not prepare on macOS and reuse its recorded Python executable on Linux:
prepare and submit on the target cluster.

A frozen submission contains:

- source.tar: the committed tracked code and release metadata;
- launcher/: the frozen staging implementation, independent of later checkout edits;
- policy-assets.tar.gz: the verified archive pinned by that snapshot;
- effective-config.json: fully resolved public settings, without secrets;
- provider-report.json: the Codex compatibility receipt, when applicable;
- job.sbatch and submission.json: job script, source commit, and file hashes;
- queue.json: the returned job ID after successful sbatch submission.

The compute node stages this input into:

~~~text
$SLURM_TMPDIR/robofrontier-JOB_ID/
├── config.json
├── local-job.json
├── tmp/
└── source/
    ├── .robofrontier/codex/TASK_HASH/sessions/
    └── runs/
        ├── asset-cache/
        ├── policy/batch/PROFILE/CASE/
        ├── state-assets/
        └── exports/
~~~

Each task gets an API-authenticated local Codex home. That task's Controller and
native forks share the same home. Different tasks use different homes. Every
home is initialized serially before initial task hosts are launched through the
single 0.3-second launch gate. This avoids claiming that launch staggering alone
solves shared configuration/database races.

## Monitor and stop

Use squeue and the submission's atomic status.json:

~~~bash
squeue --job JOB_ID
cat runs/submissions/luna-all-36/status.json
~~~

The snapshot is published about every five seconds and may lag the live task.
It contains supervisor JSON only, not SQLite reads. Original run paths in the
snapshot refer to node-local paths until stage-out finishes.

To request an orderly stop while leaving time for sealing and collection:

~~~bash
scancel --signal=USR1 --batch JOB_ID
~~~

The batch shell translates this into STOP markers for all tasks. At the normal
allocation warning, Slurm sends the same signal. The task clock is not rewritten:
allocation expiry and an operator stop are external engineering interruptions.

A normal scancel, node failure, OOM kill, or SIGKILL can prevent the warning and
stage-out from completing. This implementation is not a checkpoint/resume
system and cannot promise recovery of an ephemeral node's last writes. Do not
automatically reconstruct a physical world or retry uncertain robot actions.

## Returned evidence

After the srun execution step and all its tracked processes exit, stage-out
checks owner/supervisor locks and publishes results/ by one atomic rename:

~~~text
runs/submissions/luna-all-36/
├── status.json
├── slurm-JOB_ID.log
└── results/
    ├── evidence.zip
    ├── execution-result.json
    ├── local-job.json
    └── stage-out.json
~~~

The normal result is one deduplicated evidence ZIP. It contains the collected
task evidence, native session traces, motion, frozen assets, observation image
objects, and evaluation records. Live Codex authentication/state databases are
not copied. JPEG and motion encodings remain those of the recording; stage-out
does not change physical trajectories or rerender observations.

stage-out.json contains SHA-256 hashes for every returned payload. A collected
archive is **not** a claim that all tasks succeeded. Read each independent final
evaluation, process events, sealing outcome, and collection issues.

If collection failed, the fallback returns the stopped raw task directories,
state-asset cache, and native session JSONL files for review. It excludes Codex
auth/config/state files, retains node-local sources, and reports needs_review.
This fallback can be larger than the regular deduplicated ZIP. It is an audit
recovery path, not a silently certified or resumable benchmark result.

No stage-out path deletes the node-local source. The cluster may remove scratch
after the allocation ends, so verify the shared results and their hashes before
releasing an allocation manually. If stage-out fails, preserve the reported
node-local directory and ask the site administrator about its retention policy.

The old sbatch entries, which created active databases in shared storage, are
retired. The four-task level-3 selection is in [`runpod.toml`](../../configs/examples/runpod.toml);
copy it to an untracked site TOML and review the allocation settings first.

## Subscription jobs

Status: implemented and locally tested with synthetic credentials and a local
Responses fixture. **Not cluster/provider qualified.** No real login or Slurm
submission was performed during development. Existing prepared/running batches
must retain their original source and backend. Publication of this implementation
does not qualify it for cluster/provider execution.

### One allocation, independent tasks

The [example configuration](../../configs/examples/slurm.toml)
selects exactly `gpt-6-luna`, high effort, adaptive, 36 concurrent tasks and one
NVIDIA GPU. A submission is one `sbatch`, one node and one `srun` step, not 36
Slurm jobs. The allocation runs one managed-auth Codex app-server through a
trusted gateway. Each task retains its own world process, runtime database,
workspace, role/delegation state and named filesystem permissions. Model
inference remains remote; the GPU renders MuJoCo observations and does not
accelerate the CPU dynamics.

One H800 is a reasonable initial rendering allocation, not a verified 36-world
capacity promise. Validate 1, 4, 16 and 36 simultaneous actual task renderers,
including Mosaic, and measure GPU memory, capture latency and simulation
throughput. Faster model responses can increase screenshot demand. The example
requests 72 Slurm CPUs and 128 GiB RAM as initial budgets; confirm the site's CPU
accounting and node capacity. Renderer, CPU and subscription capacity are
independent limits. There is no silent software-rendering or paid-API fallback.

### Installation and source custody

Use the existing native Linux Slurm environment: Python 3.12, `uv sync --locked`,
the pinned Codex CLI and Node on compute-node PATH, NVIDIA drivers/EGL and
libseccomp. Live SQLite, native sessions and temporary files stay on verified
node-local scratch. Shared storage holds immutable assets, submissions, private
durable credentials and returned evidence. Reinstall the Python environment on
Linux; do not transfer a Mac virtual environment. Request the GPU through Slurm
and verify EGL uses the allocated device; CUDA logical IDs need not equal EGL
device IDs.

After implementation and qualification are merged, freeze the exact published
main commit. The submitted source and launcher do not change while queued. Do
not update a running or already prepared experiment to this backend.

### Provisioning and renewal

An initialized stopped stream can move with
`robofrontier.batch.slurm_auth.migrate_store(source, destination)`. Both refresh leases
are exclusive during the transfer. The destination parent must already be private;
the destination must be new. The latest generation is fsynced and verified before
the source's current cache and obsolete bootstrap are removed. The old initialized
marker remains, so an older runner refuses that retired reference instead of
recreating a second refresh authority. Stop all native/access-only consumers first,
qualify cross-node flock and rename on the destination, then update the operator
configuration to the new reference. No native login or refresh is performed by
the migration. Keep durable caches and logs off quota-constrained shared homes.

The operator may authenticate once in a dedicated, file-backed `CODEX_HOME` on
Mac and securely transfer only `auth.json` to the private credential directory,
or later use a short queued device-login job. Neither operation is performed by
this runner automatically. Mac Keychain state is not a portable auth.json. Do
not copy personal homes, session databases or the active CPU batch's credentials.
[Official cache-transfer guidance](https://learn.chatgpt.com/docs/auth).

Use a canonical directory owned by the operator with mode 0700, outside every
checkout, node-local job directory and submission/evidence directory. Provision
its initial `auth.json` with mode 0600. No credential contents belong in the
TOML, repository, command arguments or Slurm metadata. Do not run the Mac seed
and cluster copies concurrently. This is for private, controlled automation;
follow the documented managed-auth deployment scope.
[Official renewal guidance](https://learn.chatgpt.com/docs/auth/ci-cd-auth).

Admission acquires a nonblocking `flock` lease **after allocation**, loads the
latest `current.json` generation and seeds one fresh node-local native home.
An initialized store never falls back to its old bootstrap seed. Jobs using the
same reference also request Slurm `singleton` with a stable hashed job name.
Validate shared-filesystem lock/rename durability and scheduler behavior at the
site. Tasks within that allocation remain concurrent.

Only native Codex exchanges/refreshes tokens. The supervisor checks owner and
generation, persists complete native cache updates with fsync/atomic replacement,
and reconciles after native writers stop, before releasing the lease. A wrong
owner, external generation change or durable persistence failure fences the
stream/job. Partial native writes are retried by the watcher; an invalid final
cache fails closure. Stopping closes the native process; it does not log out.

A revoked/expired grant or node loss immediately after token rotation can still
require manual reauthentication. There is no transaction spanning remote token
rotation and shared-storage persistence. Never restore an old bootstrap to fix
that condition. Provision a fresh independent credential stream deliberately.

### Isolation and failure behavior

The explicit backend is `slurm-managed-v1`, with `runtime.codex_home_scope="job"`
and `landlock-v1`. Each thread start/resume/fork is pinned to its task's frozen
profile, cwd, model and provider. The default shared profile denies filesystem
access, rather than granting a union of task permissions. Unknown threads,
cross-task reads/forks/interrupts/tool replies and profile/config overrides are
rejected. Local request IDs are translated through the one native RPC transport.

Robot calls and file tools remain host-bound. Native shell, apply-patch, browser,
MCP, plugins and native multi-agent tools stay disabled. Policy file workers close
inherited descriptors, clear the environment, apply Landlock/seccomp and drop
capabilities. Their frozen tables explicitly deny authentication/control roots,
other checkouts/tasks, `/proc` and `/dev`; the trusted worker adds only writable
`/dev/null` and read-only `/dev/urandom` for runtimes' entropy fallback. Rendering
remains outside the policy worker. Same-UID mode 0600 files
alone are not this isolation boundary.

For a job-local Python environment under a denied temporary/source root, the
frozen table grants read-only access to its interpreter configuration and package
library directory. It does not grant the environment root or other temporary
files. A runtime inside a credential/control directory is rejected.

The Codex file worker supports filesystem Landlock ABI 1 or later, paired with
mandatory seccomp. On ABI 1/2, seccomp additionally blocks path truncation,
read-only/invalid-mode `O_TRUNC`, and `openat2` (ENOSYS for safe openat fallback).
Ordinary workspace overwrites and descriptor truncation remain available under
Landlock's write checks. Metadata-changing syscalls are restricted and inherited
standard descriptors must be pipes or connected anonymous Unix streams (the
Node/libuv implementation of piped stdio). Regular files, named Unix endpoints
and network sockets are rejected. ABI 1 also denies cross-directory rename
and hard-link operations; use a same-directory temporary file for replacement.
The Claude Bash prefix keeps its separate ABI 4 requirement.

No Landlock, missing seccomp or failed confinement is an admission failure.
The actual compute-node worker must still pass doctor before START. Tests using
old ABI masks on a newer local Linux kernel do not qualify an H800 allocation.

### Managed Mac egress

Schema 7 adds an explicit job-scoped `mac-ssh` route. Schema 8 adds
`slurm.egress_pause_s`, how long a route outage may hold the world: by default 172,800 s
(the 48 h wall backstop), as on every other platform; 0 fences at once.
The Mac connector's `--pause-grace-s` must match that setting, and a positive grace
also requires `--engine claude` or `--engine codex` (the job's engine). Older frozen schemas keep
their exact configuration shape and do not acquire a new proxy automatically.
Configure a private canonical reference outside source, scratch, submissions and
credential stores:

```toml
schema_version = 7

[slurm]
auth_mode = "subscription"
egress_mode = "mac-ssh"
egress_root = "/ABSOLUTE/PRIVATE/robofrontier-egress"
egress_wait_s = 120
```

After the allocation is RUNNING, the operator keeps this command on the Mac:

```sh
python -m robofrontier.batch.slurm_proxy connect \
  --ssh-host CLUSTER_SSH_ALIAS --job-id EXISTING_JOB_ID \
  --remote-script /CLUSTER/CHECKOUT/robofrontier/batch/slurm_proxy.py \
  --state-root /ABSOLUTE/PRIVATE/robofrontier-egress \
  --remote-python /CLUSTER/PYTHON/bin/python3.12 \
  --srun /CLUSTER/SLURM/bin/srun \
  --slurm-conf /CLUSTER/SLURM/slurm.conf \
  --status-file ~/.robofrontier/slurm-egress/status.json
```

The installed helper must match the Mac module's SHA-256. This command attaches
one one-CPU/one-GiB relay step to the existing allocation; it does not call sbatch,
request another GPU, authenticate Codex or start model/physics tasks. The Slurm
execute/preflight entry waits for its own allocation/node's healthy route before
taking the native credential lease. Start the Mac command promptly; admission
fails after `egress_wait_s` instead of consuming a task's clock while waiting.

The compute helper serves authenticated HTTP CONNECT on loopback. Native proxy
passwords are generated inside the allocation and remain in 0600 readiness files
under the 0700 state root, then in the trusted native process environment. They
never enter source snapshots, configuration, command arguments or status output.
Only OpenAI/ChatGPT and Anthropic HTTPS destinations are accepted. A Claude job
uses the same route, pause and fencing without a credential store: its token stays
in the job environment and no lease is taken. End-to-end TLS remains
between native Codex and OpenAI; the relay forwards encrypted bytes. Native
ChatGPT authentication, renewal and the credential lease remain on Slurm.

The trusted runtime enables `features.respect_system_proxy` for this explicit
route. It does not enable policy networking. Frozen file tables deny the egress
root, and admission rejects a task that can read it. Isolated workers clear proxy
environment variables, deny network socket creation and retain Landlock/seccomp.
[Native-client proxy scope](https://learn.chatgpt.com/docs/enterprise/managed-configuration).

SSH uses server-alive checks; both relay ends exchange two-second heartbeats.
Each stream has independent socket draining and a 128 KiB byte-credit window in
each direction. A slow native consumer or remote endpoint therefore cannot block
the control decoder, starve other streams or create an unbounded payload queue.
The shared writer prioritizes ping/pong over queued uploads and uses 8 KiB
payload chunks. FIFO writer locks can otherwise place heartbeat replies behind
many image uploads even when each destination drains independently. Private
transport counters record byte totals and maximum control/write waits without
retaining payloads.
A separate 512 KiB channel-wide wire-credit window bounds payloads buffered
inside SSH and Slurm, beyond the Python writer. Channel credit returns at frame
decode, independently of destination draining; per-stream credit still returns
after socket delivery. A bounded, coalescing credit writer sends channel receipts
outside the receive loop. Awaiting their delivery inside that loop can deadlock
both readers when both SSH/Slurm pipes reach their write high-water marks:
neither reader consumes the bytes needed for either writer to drain. Heartbeat
priority alone cannot break that cycle. Closing the relay cancels and reaps the
credit writer; a writer failure closes its channel and propagates to the reader.
Control frames bypass both payload windows. This bounds
control latency without reducing every stream to the speed of a stalled peer.
Stream admission limits reject the individual connection without closing the
shared route. Private Mac status includes a sanitized failure code and peak
stream count; it never includes proxy passwords or TLS payloads. Failure snapshots
retain the active write wait and pending receipt bytes before cancellation; a
maximum of completed writes alone cannot reveal a write that never drained.

Readiness is an ephemeral allocation lease. Place its private root on canonical
node-local scratch, and configure the connector and trusted job supervisor with
that same root. Each heartbeat currently performs a synchronous atomic write and
fsync: a shared home quota error can terminate the route, and a shared-filesystem
stall can block its event loop. Node-local placement removes that shared-home
dependency; it is not a substitute for fixing transport backpressure. Keep native
credential generations and collected evidence on separately qualified durable
storage. Changing this placement is an explicit operator deployment, never an
automatic change to a frozen running experiment.
Readiness readers reopen an inode unlinked by atomic heartbeat replacement and
validate the replacement normally. They still reject hardlinks, unsafe modes,
missing records, stale heartbeats and changed identities. A fenced job saves a
fixed-reason diagnostic in its private engine directory.
The Mac controller holds an idle/system-sleep assertion while connected. A
missing/stale heartbeat, listener mismatch or changed relay instance fences the
current owner, sets `EGRESS_ERROR`, stops its native engine and requests ordinary
task sealing. It never recreates the engine or replays a model turn/robot action.
Restarting the tunnel creates a fresh instance and cannot un-fence an existing
run. Preserve uncertain evidence and review it before a new run. Mac shutdown,
logout and network loss are therefore operational dependencies of this route.

Stopping the controller closes only its SSH/relay step and sleep assertion. The
allocation remains held until its normal expiry or an explicit operator release.
Readiness is removed on normal closure; abrupt loss becomes stale within twelve
seconds. Keep the published helper immutable while connected. A private launchd
job may own the Mac command independently of a terminal; avoid automatic restart
of an interrupted experiment.
Relay shutdown closes active clients before awaiting listener shutdown and bounds
best-effort close frames. A broken pipe cannot indefinitely retain the private
compute ownership lock after the route has been fenced.

#### Temporary outage recovery

With a positive grace, the compute relay stays on the original listener and
publishes fresh `ready`/`paused` lease state on node-local scratch. A stale Mac
round trip or a failed upstream probe pauses admission. The Mac probes TLS
connectivity to the hosts the job's engine uses: `api.anthropic.com` for
`--engine claude`; `chatgpt.com` and `auth.openai.com` for `--engine codex`
(all of them must answer). These come from the same table in
`robofrontier/batch/slurm_proxy.py` (`ENGINE_ROUTES`) that decides which destinations
the relay forwards, and the private Mac status lists them. Probes run every
four seconds (each host bounded to three seconds); only three consecutive failed
probes mark the route down, and one successful probe marks it up again. A failed
dial or a reset read on one stream fails only that stream; it never pauses the
route. The relay never reissues an HTTP request body. New CONNECT requests wait within the existing bounded route.
SSH server-alive tolerances cover the configured grace rather than terminating
the TCP connection after fifteen seconds.

The trusted job watcher creates an instance-bound `EGRESS_PAUSED` claim. Each
pause gets a fresh claim plus the watcher's fixed token and a `pause_id` that rises
by one per pause. A world that slept through a short resume and then reads a higher
`pause_id` from the same watcher treats it as one continuing pause
(`EGRESS_PAUSE_CONTINUED`); any other new claim still fences the job. Worlds frozen
before this rule ignore the added fields and keep the earlier behavior. The
gateway holds new turns/forks while status reads remain available, and bound RPC
deadlines include the explicit pause grace. The dispatcher waits instead of
exiting on this infrastructure pause. Each new runtime retains its one live world,
qpos/qvel/controllers and action IDs, stops stepping physics and holds queued
policy calls. It discards elapsed simulation accumulator time rather than stepping
to catch up. A pause after START is recorded as infrastructure downtime; trial,
wait and setup clocks account for that pause. No delegate-scope deadline is added.

Same-instance recovery requires authenticated local health, original endpoint,
unchanged scene/input integrity, world/robot/thread ownership and existing action
receipts. A fork already acknowledged before pause may finish binding only under
its original trusted gateway ownership. Operator pauses remain held for review.
Unknown ownership, a changed listener/instance, stream EOF, credential failure or
grace expiry fences execution; no new engine or world is created automatically,
and no old turn input or physical request is replayed. A confirmed failed native
network turn correlated with the recorded pause may receive one fresh, frozen
continuation notice in its original session after its action receipts settle.
That claim is durable per role/outage; an unknown continuation acknowledgement
freezes that world for review rather than sending it again. Returned delegates
are never reanimated. In particular, this recovers a temporarily stalled
existing SSH/TCP channel, not a newly established SSH session after its old process
has exited. Mac logout, process death and unrecoverable connection loss still
require explicit review. New pause behavior is opt-in and must not be hot-patched
into already frozen historical trials. Admission explicitly rejects historical
tasks whose frozen runtime lacks the pause/dispatcher/RPC support.

A stopped historical run can acquire support only through an explicit operator
runtime upgrade (`robofrontier.runtime.upgrade.upgrade`), after its clean seal,
settled action ledger, native transcript custody and absence of live hosts have
been checked. Hold its supervisor/recovery locks. The upgrade archives the parent
manifest and frozen source under `private/inputs/runtime-upgrades/<next segment>`;
both remain hashed in the new manifest. Public inputs, policy prompts, scene,
model, workspace and settled calls are retained. A new network recovery notice is
frozen, and changed runtime sources are recorded separately. No normal finish,
unsettled call or integrity abort can be overridden.

The returned manifest-bound authorization must be passed explicitly as
`manual_authorization` to `run_segments.prepare_retry`. It binds the run, original
segment, source version and exact call/action ledger to precisely the next
segment. Consuming it does not raise the automatic retry limit; another outage
requires another explicit review. A partially written migration or consumed grant
fails closed. Validate private clones, file isolation and physical restore first.
Restoring a stopped world remains approximate, unlike a short outage in a live
world: missing velocity/controller/contact history cannot be reconstructed.

On macOS, inspect the route to the cluster jump host before treating a small
transfer benchmark as a bandwidth limit. A system VPN can send cluster SSH over
a distant exit even when the cluster is local. `connect --ssh-config` accepts a
private operator-owned OpenSSH config scoped to this controller. Its jump host
can use the immutable helper as a `ProxyCommand`:

```sshconfig
Host cluster-jump
    ProxyCommand /path/to/python3 -I /private/immutable/slurm_proxy.py tcp-pipe --host %h --port %p --interface en0
Host *
    Include /path/to/operator/ssh/config
```

`tcp-pipe` binds only that SSH TCP socket to the selected macOS interface. It
does not modify system routes, disable a VPN or change the Mac relay's OpenAI
connections. Keep host-key verification enabled and compare memory-only upload
and download benchmarks before deploying the scoped route.

A shared-engine failure stops dispatch, seals task worlds and requires review.
This backend disables automatic host/segment redispatch; it does not recreate a
shared manager or repeat unknown turns/actions. API and legacy shared-home
behavior remain unchanged. Engine shutdown kills only its own process group,
then exports bound transcripts by task/thread ownership. Auth, native SQLite,
config and private gateway logs never enter evidence. Unbound fork transcripts
are retained separately for review.

### Qualification before deployment

The explicit provider preflight uses the gateway too when the example's job
scope is selected, requires an admitted Linux Slurm allocation/private stream,
and exercises image/file tools, manual compaction and native fork inheritance.
It does not itself submit a job. Only the full successful preflight writes the
`job_gateway_sha256` receipt required by submission and batch admission; smoke
checks cannot qualify scored trials. Changes invalidate that receipt.

Local checks (no login, scheduler, real provider or physical action):

```sh
.venv/bin/python -m unittest tests.batch.test_slurm_auth tests.engines.test_codex_job_engine tests.engines.test_slurm_gateway_native tests.batch.test_slurm_job
node --test tests/engines/test_codex_job_gateway.js
```

The native fixture uses one installed Codex app-server, 36 concurrent parents,
two rounds of bounded children (72 distinct forks), 108 completed turns and
216 local Responses requests. Synthetic 401 recovery exercises native managed
renewal without stale-refresh rejection. All HTTP endpoints and token values
are fixtures, not a model or account login. Separate tests cover stream leases,
partial writes, missing-generation rollback refusal, owner/fencing checks,
cross-task denials, colliding client IDs and engine failure without redispatch.

The ABI compatibility regression is `tests.engines.test_codex_landlock_old_abi`. Local
Linux checks exercise ABI 1/2 masks and the ordinary worker boundaries. A tiny
synthetic syscall check on slogin-01 (Linux 5.19, actual ABI 2) also passed on
2026-11-04, without models, simulation, assets or scheduler jobs. That login-node
result does not qualify the Linux 5.15 compute nodes; their doctor gate remains
mandatory. No authentication or active trial was used for these checks.

Outstanding deployment checks: actual cluster kernel confinement, real account
admission/renewal and account limits, EGL device identity, 36 renderer memory and
latency, signal/preemption behavior and stopped evidence under the site's
Slurm/cgroup/filesystem setup. Perform bounded qualification before 24-hour runs.
