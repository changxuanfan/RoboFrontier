# Job-scoped Codex subscriptions on Slurm

Status: implemented and locally tested with synthetic credentials and a local
Responses fixture. **Not cluster/provider qualified.** No real login or Slurm
submission was performed during development. Existing prepared/running batches
must retain their original source and backend. Publication of this implementation
does not qualify it for cluster/provider execution.

## One allocation, independent tasks

The [example configuration](../../configs/slurm-luna-subscription.example.toml)
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

## Installation and source custody

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

## Provisioning and renewal

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

## Isolation and failure behavior

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
standard descriptors must be pipes. ABI 1 also denies cross-directory rename
and hard-link operations; use a same-directory temporary file for replacement.
The Claude Bash prefix keeps its separate ABI 4 requirement.

No Landlock, missing seccomp or failed confinement is an admission failure.
The actual compute-node worker must still pass doctor before START. Tests using
old ABI masks on a newer local Linux kernel do not qualify an H800 allocation.

A shared-engine failure stops dispatch, seals task worlds and requires review.
This backend disables automatic host/segment redispatch; it does not recreate a
shared manager or repeat unknown turns/actions. API and legacy shared-home
behavior remain unchanged. Engine shutdown kills only its own process group,
then exports bound transcripts by task/thread ownership. Auth, native SQLite,
config and private gateway logs never enter evidence. Unbound fork transcripts
are retained separately for review.

## Qualification before deployment

The explicit provider preflight uses the gateway too when the example's job
scope is selected, requires an admitted Linux Slurm allocation/private stream,
and exercises image/file tools, manual compaction and native fork inheritance.
It does not itself submit a job. Only the full successful preflight writes the
`job_gateway_sha256` receipt required by submission and batch admission; smoke
checks cannot qualify scored trials. Changes invalidate that receipt.

Local checks (no login, scheduler, real provider or physical action):

```sh
.venv/bin/python -m unittest tests.test_slurm_auth tests.test_codex_job_engine tests.test_slurm_gateway_native tests.test_slurm_job
node --test tests/test_codex_job_gateway.js
```

The native fixture uses one installed Codex app-server, 36 concurrent parents,
two rounds of bounded children (72 distinct forks), 108 completed turns and
216 local Responses requests. Synthetic 401 recovery exercises native managed
renewal without stale-refresh rejection. All HTTP endpoints and token values
are fixtures, not a model or account login. Separate tests cover stream leases,
partial writes, missing-generation rollback refusal, owner/fencing checks,
cross-task denials, colliding client IDs and engine failure without redispatch.

The ABI compatibility regression is `tests.test_codex_legacy_sandbox`. Local
Linux checks exercise ABI 1/2 masks and the ordinary worker boundaries. A tiny
synthetic syscall check on slogin-01 (Linux 5.19, actual ABI 2) also passed on
2026-11-04, without models, simulation, assets or scheduler jobs. That login-node
result does not qualify the Linux 5.15 compute nodes; their doctor gate remains
mandatory. No authentication or active trial was used for these checks.

Outstanding deployment checks: actual cluster kernel confinement, real account
admission/renewal and account limits, EGL device identity, 36 renderer memory and
latency, signal/preemption behavior and stopped evidence under the site's
Slurm/cgroup/filesystem setup. Perform bounded qualification before 24-hour runs.
