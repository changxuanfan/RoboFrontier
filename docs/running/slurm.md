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
[acceptance ledger](../archive/unified-main.md) for source identities and open gates.

## Prerequisites

For the new, locally tested job-scoped Codex subscription backend, see
[Slurm subscriptions](slurm-subscription.md). It requires separate live
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
travels in the environment like an API key. Claude runs remain explicitly
unqualified engineering drafts and require --engineering. Where the cluster cannot
reach Anthropic, Claude may use the managed Mac route (`slurm.egress_mode = "mac-ssh"`,
see [Slurm subscriptions](slurm-subscription.md#managed-mac-egress)) without a
credential store; the CLI then receives only that route's `HTTPS_PROXY`/`NO_PROXY`.
With `slurm.egress_pause_s` above 0, start the Mac connector with `--engine claude`
so outage detection probes `api.anthropic.com`, the host Claude actually uses.
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
retired. The four-task engineering selection is available as [`luna-l3-cpu.toml`](../../configs/examples/luna-l3-cpu.toml);
copy it to an untracked site TOML and review the allocation settings first.
