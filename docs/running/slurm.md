# Running on Slurm

A Slurm batch is one `sbatch` job: one node, one `srun` step. On the login node,
`robofrontier slurm-submit` freezes a submission (committed source, assets, configuration,
receipts, job script) and queues it. On the compute node the job stages that submission onto
node-local scratch, prepares and runs the batch there, and after the step ends copies one
verified evidence ZIP back into the submission folder. Live databases, sessions and temporary
files never touch shared storage.

[`configs/examples/slurm.toml`](../../configs/examples/slurm.toml) is a starting site TOML (36
runs, Codex subscription): copy it to an untracked file (here `site.toml`) and edit it.

## 1. Prerequisites

- A Linux login node and compute nodes that see the same shared storage: the checkout, its
  `.venv`, the engine CLIs and the policy environment. The job installs nothing.
- `sbatch`, `srun`, `squeue` and `scancel` on `PATH`. On the cluster used here run
  `module load slurm` first in every shell.
- Slurm process tracking (cgroup) that follows every descendant of a job step, detached CLI
  processes included.
- Node-local scratch: `SLURM_TMPDIR` or `slurm.scratch_root`. The job accepts only ext2/ext3,
  xfs, btrfs, tmpfs, overlayfs or zfs, and the policy environment refuses runs under `/tmp`, so
  set `slurm.scratch_root` to a node-local folder outside `/tmp`, such as `/var/tmp`.
- The pinned CLI first on `PATH` on the compute nodes (`robofrontier/runtime/versions.py`: Codex
  0.165.0, Claude Code 2.1.316). A shared account's own copy can drift; every run refuses
  another version.
- Claude Code: `bwrap` and `socat` on the compute-node `PATH` where user namespaces work (Bash
  then runs in Claude Code's bubblewrap sandbox), else Landlock ABI 4 and `libseccomp`.
- NVIDIA drivers with EGL for `render.device = "nvidia"`.

## 2. Install (login node)

```sh
git clone https://github.com/changxuanfan/RoboFrontier.git
cd RoboFrontier
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap
```

Install on Linux; never copy a Mac `.venv`. `slurm-submit` refuses a checkout with uncommitted
tracked changes, since it freezes `git archive HEAD`.

## 3. Credentials

`.env` sits at the checkout root, mode 0600 (`cp .env.example .env && chmod 600 .env`). Three
modes:

| Mode | What to set | How the job gets it |
| --- | --- | --- |
| API key (Codex `luna`, third-party profiles) | The profile's `env_key`, e.g. `OPENAI_API_KEY`, in `.env` | `slurm-submit` loads `.env`; `sbatch --export=ALL` hands it to the job |
| Claude subscription token (`haiku_subscription_token`, `opus_subscription`) | `CLAUDE_CODE_OAUTH_TOKEN` in the checkout's `.env`, **not** exported | `slurm-submit` strips it from the `sbatch` environment and records the `.env` path; the job reads it from there and passes it to the CLI on a pipe |
| Codex subscription (`luna_subscription`) | `slurm.auth_mode = "subscription"` and a credential store (below) | The job takes a lease on the store after allocation |

- A Claude run refuses to start when the token is in a starting environment under bubblewrap:
  unset it in the shell before `slurm-submit`.
- Claude API-key profiles are refused where bubblewrap runs (a policy shell could read the
  CLI's environment); use a subscription-token profile.
- Secret values never enter the job script, source snapshot, configuration or returned ZIP.

<a id="subscription-jobs"></a>

### Codex credential store

`slurm.credential_store` names a directory you own with mode 0700, outside every checkout,
submission and scratch folder, on storage that supports `flock` and atomic rename across nodes.
Provision it once:

1. Log in with a dedicated, file-backed Codex home (not a personal one, not the macOS Keychain):
   `CODEX_HOME=<new empty dir> codex -c 'cli_auth_credentials_store="file"' login`.
2. Copy only its `auth.json` into the store with mode 0600.

From then on only native Codex inside a job refreshes the login. The job takes a nonblocking
`flock` lease, seeds a node-local home from the latest `current.json` generation and writes
each refresh back atomically. Jobs on the same store are serialized with
`--dependency=singleton`. A wrong owner, an outside change to the generation or a failed write
fences the job. A revoked grant, or a node lost right after a refresh, can require a fresh
login; never restore an older `auth.json` over `current.json`.
`robofrontier.batch.slurm_auth.migrate_store(source, destination)` moves a stopped store. A
second batch can borrow an existing job's access without refreshing it:
[access-only attachments](codex-access-attachments.md).

## 4. Site TOML

```toml
schema_version = 9

[policy]
engine = "codex"
profile = "luna"
topology = "adaptive"

[batch]
parallel = 36

[render]
device = "nvidia"            # set it: "auto" would resolve on the login node, not the GPU node

[runtime]
codex_tool_backend = "landlock-v1"
codex_home_scope = "task"    # API mode; "job" with slurm.auth_mode = "subscription"
codex_home = ""

[slurm]
partition = "YOUR_PARTITION"
account = "YOUR_ACCOUNT"
gpus = 1                     # 0 with render.device = "cpu"
cpus_per_task = 36
memory_gib = 128
time_limit_s = 90000         # the allocation; each run's 24 h is separate
stop_warning_s = 600         # USR1 this long before the limit: stop and collect
scratch_root = "/var/tmp"
```

- CPU and memory are requests, not a measured capacity. `slurm-submit` never reduces
  `batch.parallel`.
- `evidence.auto_collect` and `evidence.auto_archive` must stay `true`.
- API mode requires `codex_home_scope = "task"` and an empty `codex_home`; each run gets its own
  node-local Codex home.
- `render.device = "native"` is refused; `"nvidia"` needs `gpus >= 1`. Physics runs on the CPU
  either way.

## 5. Policy environment

Build it once on shared storage, outside `/tmp` and every checkout, then check it on a compute
node, with `--scratch` under the scratch root the batch will use:

```sh
.venv/bin/python -m scripts.build_policy_env --base /shared/robofrontier-env     # login node; prints its root
srun --time=60 --cpus-per-task=4 .venv/bin/python -m scripts.check_policy_env \
  /shared/robofrontier-env/policy-env-<id> --scratch /var/tmp
```

Then, in the shell that runs `slurm-submit`, export the build itself and the shared roots
policies must not read:

```sh
export ROBOFRONTIER_POLICY_ENV=/shared/robofrontier-env/policy-env-<id>
export ROBOFRONTIER_SHARED_DENY_ROOTS='["/shared"]'
```

The job prepares its batch on the node and reads only `ROBOFRONTIER_POLICY_ENV`;
`ROBOFRONTIER_POLICY_ENV_BASE` is not applied there, and without the variable `run` refuses the
prepared runs. Details: [policy environment](policy-environment.md).

## 6. Local check and preflight

```sh
srun --time=10 --gpus=1 .venv/bin/robofrontier --config site.toml doctor   # on a compute node
```

| Engine and mode | Preflight | What `slurm-submit` checks |
| --- | --- | --- |
| Codex API | `.venv/bin/robofrontier --config site.toml preflight --confirm-spend` on the login node | A passed `<runs root>/engineering/model-compatibility/<profile>/report.json`, copied into the submission |
| Codex subscription | The same command inside an allocation (`srun ...`), which needs node-local scratch and, with the Mac route, the connector running | That report with a `job_gateway_sha256` matching the current job gateway |
| Claude | `... preflight --confirm-spend --max-budget-usd 1` | Nothing; see the limit below |

**Limit: Claude batches.** The submission carries only the Codex receipt. A Claude job's `run`
looks for its precheck receipts in the node-local `runs/` and finds none, so `slurm-submit`
cannot start a Claude batch as it stands.

## 7. Submit

```sh
.venv/bin/robofrontier --config site.toml slurm-submit --output runs/submissions/my-batch          # freeze only
.venv/bin/robofrontier --config site.toml slurm-submit --output runs/submissions/my-batch --queue  # freeze and sbatch
```

Without `--queue` nothing is queued and no model is called. The output folder must be new. It
holds:

| File | Content |
| --- | --- |
| `source.tar` | `git archive` of the committed source (never `.env` or run data) |
| `launcher/` | The frozen staging code, independent of later checkout edits |
| `policy-assets.tar.gz` | The verified asset archive |
| `effective-config.json` | The resolved configuration, without secrets |
| `provider-report.json` | The Codex compatibility receipt |
| `job.sbatch`, `submission.json` | Job script; commit, file hashes, credential variable name |
| `queue.json` | The job ID, after `--queue` |

`sbatch` gets `--nodes=1 --ntasks=1`, the CPU, memory, time and GPU requests,
`--signal=B:USR1@<stop_warning_s>`, `--export=ALL` and, when set, partition, account and QOS.
On the node the job uses `<scratch>/robofrontier-<JOB_ID>/` (`source/`, `tmp/`, `config.json`,
`local-job.json`) and refuses to reuse an existing one.

## 8. Monitor and stop

```sh
squeue --job JOB_ID
cat runs/submissions/my-batch/status.json          # supervisor JSON, refreshed about every 5 s
scancel --signal=USR1 --batch JOB_ID                # orderly stop: STOP markers, seal, collect
```

`robofrontier status`, `stop` and `continue` do not apply to a submission folder; the batch
lives on the node. At `stop_warning_s` before the time limit Slurm sends the same USR1. A plain
`scancel`, node failure, out-of-memory kill or SIGKILL can prevent stage-out.

Each run gets 24 h of active time from START, scored at the cutoff. A run that stops
unexpectedly continues by itself once inside the job. There is no continuation by hand: once
the job ends its runs are gone from the node, and a new submission prepares new trials. Size
`time_limit_s` to cover 24 h of active time plus startup and pauses.

## 9. Results

After the `srun` step and all its processes exit, stage-out checks that no writer holds a lock
and publishes `results/` with one rename:

```text
runs/submissions/my-batch/
├── status.json
├── slurm-JOB_ID.log
└── results/
    ├── evidence.zip            # the collected, deduplicated evidence of every run
    ├── execution-result.json
    ├── local-job.json
    └── stage-out.json          # SHA-256 of every returned file, and the outcome
```

When collection fails, `results/` holds the stopped raw run folders and native session JSONL
instead (no Codex auth, config or state), marked `needs_review`. Stage-out never deletes the
node-local folder; if it fails, keep the node-local path it reports and ask the site about
scratch retention. A collected ZIP is not a claim that runs succeeded: read each run's
evaluation and collection issues ([evidence storage](evidence-storage.md)).

## 10. The Mac route (`mac-ssh`)

For a cluster that cannot reach the model API, the job can send its HTTPS through a Mac over
SSH. Only Anthropic and OpenAI/ChatGPT hosts on port 443 pass; TLS stays end to end between the
CLI and the provider.

```toml
[slurm]
egress_mode = "mac-ssh"
egress_root = "/var/tmp/USER/robofrontier-egress"   # private, node-local, outside /tmp and checkouts
egress_wait_s = 120                                  # how long admission waits for the route
egress_pause_s = 172800                              # how long an outage may hold the world; 0 fences at once
```

Once the job is `RUNNING`, keep this running on the Mac (from a checkout whose
`robofrontier/batch/slurm_proxy.py` matches the cluster's):

```sh
.venv/bin/python -m robofrontier.batch.slurm_proxy connect \
  --ssh-host CLUSTER_SSH_ALIAS --job-id JOB_ID --engine codex --pause-grace-s 172800 \
  --remote-script /CLUSTER/CHECKOUT/robofrontier/batch/slurm_proxy.py \
  --remote-python /CLUSTER/CHECKOUT/.venv/bin/python \
  --state-root /var/tmp/USER/robofrontier-egress \
  --srun /CLUSTER/SLURM/bin/srun --slurm-conf /CLUSTER/SLURM/slurm.conf
```

- `--pause-grace-s` must equal `slurm.egress_pause_s`, and a positive grace needs `--engine`
  (`claude` or `codex`, the job's engine), which picks the hosts probed during an outage:
  `api.anthropic.com`, or `chatgpt.com` and `auth.openai.com`.
- `--state-root` is the job's `slurm.egress_root`. The command adds a one-CPU relay step to the
  existing allocation; it queues nothing and holds a Mac sleep assertion while connected.
  Status goes to `~/.robofrontier/slurm-egress/status.json` (`--status-file`).
- Start it within `egress_wait_s` of the job starting, or admission fails before any run's clock
  starts. A Claude job uses the same route without a credential store.
- During an outage the world pauses (physics and dispatch held, time not counted) and resumes
  on the same route. A stale heartbeat, changed relay instance or an outage longer than the
  grace fences the job: it stops the engine and seals the runs, and a restarted tunnel cannot
  un-fence it. Mac shutdown, logout and network loss are therefore dependencies of this route.
- `connect --ssh-config FILE` takes a private OpenSSH config for this route only, for example
  to bind the SSH connection to one interface past a VPN with
  `ProxyCommand python3 -I /path/slurm_proxy.py tcp-pipe --host %h --port %p --interface en0`.

## Limits

- **Claude batches cannot start through `slurm-submit`** (no precheck receipts in the job; see
  section 6).
- **No continuation by hand** of a finished job's runs.
- **No GPU or renderer fallback.** A missing device or driver mismatch is an error; the CUDA
  device index need not equal the EGL device index.
- **Codex on Landlock ABI 1–3** (for example kernel 5.15): seccomp also blocks path truncation
  and `openat2`, and ABI 1 denies cross-directory rename and hard links; replace a file through
  a temporary file in the same folder. Claude's Landlock Bash needs ABI 4.
- **Codex subscription jobs** never redispatch a host or recreate the shared engine after it
  fails; the runs are sealed for review.
- The Mac route's `egress_root` must stay outside `/tmp`, since policies can read and write
  there; preparation refuses it otherwise.
