# OpenLux GPT-6.1 Terra

The `openlux-terra` catalog profile requests `gpt-6.1-terra` at `high` effort
through `https://api.openlux.ai/v1`, using the native Codex Responses runner.
Selecting it does not change the repository's default Luna profile. A model
name and endpoint do not prove upstream model identity, vision, tools, native
forks or compaction support. Validate the actual account and token with a paid
preflight before execution. The configured 272000-token context and 245000-token
compaction threshold are engineering settings, not verified capacity limits.

## Credentials and group selection

Set the token's allowed groups and priorities in the OpenLux console. Put only
the credential in the local ignored `.env` file:

```dotenv
OPENLUX_API_KEY=fill_locally
```

Do not commit credentials or put them in command arguments or chat. An existing
process environment variable takes precedence over `.env`. This profile uses one
token. Group selection, priority and fallback depend on that token's server-side
configuration; the harness does not implement or verify a two-group failover.

## Unified native command flow

Install locked dependencies, assets and the pinned native CLI as described in
[the unified CLI guide](../unified-cli.md). Create an operator TOML, for example
`openlux.toml`:

```toml
[policy]
engine = "codex"
profile = "openlux-terra"
effort = "high"
topology = "adaptive"

[render]
device = "nvidia"

[selection]
level = 1
min_arms = true

[batch]
parallel = 4
```

Use `device = "native"` for macOS or `"cpu"` for Linux Mesa OSMesa. The remaining
settings inherit repository defaults: task-local API homes, a 0.3-second initial
host-launch interval, and 24 hours per task from persisted START. The example
selects four minimum-arm Level 1 cases. Omitting the selection and parallel
sections restores all 36 tasks and 36 slots; that is not a capacity guarantee.

```sh
.venv/bin/robofrontier bootstrap
.venv/bin/robofrontier --config openlux.toml plan
.venv/bin/robofrontier --config openlux.toml doctor
.venv/bin/robofrontier --config openlux.toml prepare --output runs/policy/openlux-l1
```

Those commands do not invoke a language model. Doctor does create a local RGB
context. Preflight and run are separate, billable operations:

```sh
.venv/bin/robofrontier --config openlux.toml preflight --confirm-spend
.venv/bin/robofrontier run runs/policy/openlux-l1
```

A successful full compatibility receipt checks the configured provider's image,
tool, manual compaction and native fork paths. It does not qualify the maximum
automatic context size, upstream model identity, resource capacity or every task.
A smoke-only receipt is insufficient for a benchmark run. Profile/catalog and
native CLI identity changes invalidate existing compatibility receipts.

Monitor or stop through the command interface; do not inspect a live SQLite
file across storage/container boundaries:

```sh
.venv/bin/robofrontier status runs/policy/openlux-l1
.venv/bin/robofrontier stop runs/policy/openlux-l1
```

New runs automatically collect and ZIP stopped evidence by default, retaining
originals. Inspect collection issues and uncertain actions; a sealed archive is
not proof of task success. Preflight reports are under
`runs/engineering/model-compatibility/openlux-terra/`; task home markers and
collected session indexes identify the actual native session files. These are
research records, not public assets to upload without review.

## Docker and Slurm

Use the same profile TOML with the [Docker wrapper](../running/docker.md), which builds
committed source and stores active runtime/session data in local Docker volumes.
Use the frozen, node-local [Slurm flow](../running/slurm.md) for queue execution. Neither
entry should put active SQLite files directly on Lustre/NFS. Real cluster,
NVIDIA and provider resource qualification remain separate acceptance gates.

The earlier `scripts.luna_cpu` and `scripts.portable_benchmark` commands are
legacy interfaces documented in the [Luna CPU guide](../engines/codex.md#luna-on-linux-cpu-and-slurm). Their old short-test limits, batch-shared homes
and manual privileged Docker invocation are not the unified configuration.
Do not submit the retired Luna sbatch scripts to switch this profile; use the
current Slurm submission command and site-specific settings instead.
