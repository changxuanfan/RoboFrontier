# Getting started

Install, configure, run and hand off RoboFrontier experiments. This guide was the long
form of the repository README; the README now introduces the benchmark, and the
[project page](https://changxuanfan.github.io/RoboFrontier/) shows tasks, videos and results.

**Integration status:** the reviewed engineering integration and unified commands are
published on `main`. Read the [acceptance ledger](archive/unified-main.md) for source-pinned
verification, follow-up repairs and open gates. Claude scored execution remains closed; all
four Claude topologies have engineering entries. Full historical checks require legacy assets
and closed recordings beyond the policy asset bundle; see the [testing guide](development/testing.md).
Model profiles are configuration choices, not universal provider compatibility certificates.

## Start here

| Goal | Guide |
| --- | --- |
| Configure, prepare and run a benchmark | [Unified CLI and TOML](unified-cli.md) |
| Run on Linux Docker or macOS Docker Desktop | [Docker execution](running/docker.md) |
| Queue a job with node-local runtime state | [Slurm submission](running/slurm.md) |
| Replay motion and render Factory backgrounds | [Factory workflow](factory/replay.md) |
| Edit the full Factory camera plan and English video titles/subtitles | [Editable video project](factory/editorial.md) |
| Browse the 36 current tasks and initial scenes | [Project page](https://changxuanfan.github.io/RoboFrontier/) |
| See which integration gates have passed | [Acceptance and source provenance](archive/unified-main.md) |
| Read the policy's role and tool contract | [Robot collaboration skill](../prompts/skills/robot-collaboration/SKILL.md) |
| Read completion and recovery rules | [Shared policy rules](../prompts/rules.md) |
| Run privileged references and interpret recovery checks | [Oracle execution](oracle/README.md) and [recovery boundaries](oracle/recovery.md) |

Current source, documentation and historical prose use English. Frozen legacy
inputs retain their original filenames, language, protocol and source;
current documentation must not reinterpret an old result as a new-protocol run.

## Install and verify assets

Use a repository checkout and Python 3.12. Install uv, Node.js and the native CLI
for the selected policy engine. The integration checks use Codex 0.165.0 and
Claude Code 2.1.312; these are observed reproducibility pins, not claims about the
latest upstream releases. The Docker image installs both pinned CLIs itself.

```sh
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap
.venv/bin/robofrontier plan
```

`bootstrap` downloads the policy archive pinned in `configs/policy-assets.json`,
verifies its SHA-256 and restores every referenced asset with hash verification.
It reuses already verified files. `prepare` performs the same required asset
setup automatically. Cloning Git alone cannot execute an installation step.
Neither bootstrap, planning nor preparation calls a model.

The asset lock also records one reviewed metadata-compatible release: nine
historical Mosaic edit references now use a pinned original video index. Every
other release field and all asset bytes remain unchanged. Bootstrap authenticates
both the exact revised release and its unchanged-field projection before reusing
the original archive. The task atlas retains its original capture-release hash;
this metadata change did not regenerate its images or alter task physics.

For an offline machine, download the archive named by the checked-in asset lock
on a connected machine, transfer it, and run:

```sh
.venv/bin/python -m robofrontier.batch.handoff setup-assets \
  --archive /path/to/the-pinned-policy-assets.tar.gz
.venv/bin/python -m robofrontier.batch.tasks check --purpose gpt --assets
```

Do not substitute a similarly named asset package or rebuild missing labels
approximately. A changed scene or asset hash identifies a different input. The
larger optional Factory recording bundle has its own release lock and installer;
ordinary policy preparation does not download it.

## Defaults and configuration

The single public settings file is [robofrontier.toml](../robofrontier.toml). A
partial user TOML overrides named defaults; explicit CLI options override those
settings. Unknown options and invalid values fail before execution. Each prepared
batch freezes its resolved configuration and input hashes. Editing TOML later
does not change an existing batch.

The new-run defaults are:

- Native Codex, official OpenAI API, Luna, reasoning effort `high`.
- Adaptive topology, all 36 current cases and 36 concurrent host slots.
- A 0.3-second interval between initial host launches, after serialized native
  initialization. This interval does not delay robot calls or model turns.
- A separate 86,400-second task limit measured from each persisted START.
- Linux NVIDIA EGL observations and CPU MuJoCo dynamics.
- JPEG observations at 896 x 560, quality 85; realtime MP4 recording disabled.
- Automatic stopped-evidence collection and a verified ZIP archive; originals
  retained unless an operator explicitly performs a separate reviewed cleanup.

The requested concurrency is not a hardware or provider capacity guarantee.
Account for simulator/session/delegate memory, CPU, GPU contexts, local disk and
provider rate limits. OOM or an unsealed tool outcome is an engineering issue,
not an automatic model task failure.

Store API keys in the ignored `.env` or process environment. Never put credentials
in TOML or commit them. Existing keys and Desktop authentication are not copied
into another user's checkout. The selected engine's catalog is
the engine's section of `configs/models.json`. OpenLux and third-party
profiles need their own compatibility checks; provider routing groups are not
selected by changing a task's model prompt.

## Run from commands

On an equipped Linux NVIDIA host, first check local execution prerequisites:

```sh
.venv/bin/robofrontier doctor
```

Doctor checks the selected native CLI, the Codex workspace sandbox when selected,
and a real RGB renderer. It does not authenticate or call a model. On macOS use
`doctor --render native` and prepare with `--render native`. For Linux CPU
rendering use `--render cpu`; on macOS the CPU path runs inside Linux Docker.
Render backend mismatches fail instead of silently falling back.

After setting `OPENAI_API_KEY`, explicitly authorize a provider compatibility
preflight, then prepare and run the full default batch:

```sh
.venv/bin/robofrontier preflight --confirm-spend
.venv/bin/robofrontier prepare --output runs/policy/example-36
.venv/bin/robofrontier run runs/policy/example-36
```

Preflight and run make real, potentially billable model calls. A smoke-only
provider receipt does not qualify a scored run. A provider/catalog/CLI mismatch
requires another explicit preflight. Local sandbox prerequisites are checked
before confirmed preflight; local sandbox and frozen rendering are checked before
task hosts start.

To prepare four minimum-arm Level 1 tasks instead, choose a new directory:

```sh
.venv/bin/robofrontier prepare --level 1 --min-arms --parallel 4 \
  --output runs/policy/example-l1
```

Preparing does not launch this batch. Use the same `run` command when ready.
Every task has its own START and clock; preparation and session setup precede
START, while initial reading, observation and planning count as task time.

Monitor or stop from another terminal:

```sh
.venv/bin/robofrontier status runs/policy/example-36
.venv/bin/robofrontier stop runs/policy/example-36
```

Status reads an atomic supervisor snapshot. Stop requests orderly closure; inspect
the final sealing/collection result before treating it as complete. A disconnected
native session or uncertain physical request is not automatically restarted or
replayed. Short engineering stops are separate from the published task deadline.

## Four collaboration modes

| Mode | Initial roles and authority |
| --- | --- |
| `single` | One Controller controls all arms and creates no delegates. |
| `controller-worker` | One coordinating Controller and one permanent Worker per arm; each Worker controls its assigned arm. |
| `worker-worker` | One permanent Worker per arm; Workers coordinate directly with peers. |
| `adaptive` | One Controller controls all arms and dynamically chooses whether, when and how many bounded delegates to create or retire. |

All new unified batches directly START after their required initial native
sessions are bound. Each role receives an explicit started prompt. `ready` is an optional
capability query; it is not a model-readiness gate. Old `ready_barrier_v1` inputs
keep their frozen legacy behavior. Direct START does not change robot ownership.

Claude exposes all four modes as explicit engineering drafts, including native
standing Workers with independent sessions. See [Claude standing teams](engines/claude-code.md#standing-teams)
for commands, resource implications and measured coverage. Formal scored Claude
lifecycle qualification remains an integration gate. Use the engine-specific guide rather than assuming that a
Codex app-server tool/fork interface exists in Claude Code. API and native
subscription authentication are separate paths. In particular, isolated Codex
API homes do not imply qualified concurrent subscription-token refresh.

## Completion, recovery and timing

The independent scorer determines task completion from published conditions.
Process events such as supported drop/collision detections are reported
separately and do not automatically veto terminal completion. Dial retains its
unlock latch: unlocking completes the puzzle. These rules do not grant an agent
access to private evaluation state or Oracle solutions.

A Controller should keep observing, acting and recovering while the task remains
unfinished. `finish` is an end proposal accepted only after closure conditions;
it is appropriate for completion or publicly supported unrecoverability. Accepting
it does not imply a successful score. Ending a normal model turn or returning a
delegate does not itself end the experiment. Hosts enforce deadline and stop
requests independently of a supervising agent.

For a new robot request, omit the outer `call_id`; the host returns a generated
identifier. Query an existing action with a new `job` request and its original ID
in `data.call_id`. An uncertain result may be retried only under its original ID
and identical payload. A rejected ID conflict and an uncertain transport result
have different meanings; neither permits blind repetition of physical actions.

## Runtime data and handoff

A batch lives under the path supplied to `prepare`, with one run per profile/case.
Each run contains frozen public/private inputs, observations, tool/host events,
runtime state and motion under `private/outputs/motion/`. Live runtime SQLite and
Codex state must be on a node-local filesystem. Never monitor an active Docker
SQLite database from macOS or place active WAL databases on Lustre/NFS.

For new API batches, each task uses a private Codex home beneath
`.robofrontier/codex/`. Its `sessions/` directory contains the native Controller
and delegate transcripts. The run's `codex-home.json` records its exact home.
Legacy `.codex-luna/` and shared-home recordings remain separate legacy layouts.
`codex-host.jsonl` is the harness event log; it does not replace native session
JSONL files.

After writers stop, automatic collection places portable evidence under
`runs/exports/` and creates a sibling ZIP. Review collection completeness and
sealing issues. The archive deduplicates identical payloads and replaces inline
session image Base64 with reversible image-object references. Restoration verifies
hashes and reconstructs original transcript bytes. Live native logs are not edited
in place. Creating a ZIP alone does not reclaim the originals' disk space.

Motion retains timestamps, appearance changes and the existing float32 states;
XOR and ZIP compression add no further numeric loss. The original conversion to
float32 is declared and is not lossless relative to float64 simulation state.
Historical uncompressed motion remains a compatibility obligation. JPEG
observation settings are separate from later video resolution.

## Oracle, Factory and media

See [contact physics and commissioning](physics.md) for released parameters,
candidate scope, reproducible zero-model checks and remaining physical gates.

Mosaic R15 (71 mm grid pitch) is the default. Relay's independent revision
identifiers are unrelated to Mosaic's. The current release still uses its pinned
rolling-friction candidate; recommended new Transport/Dial physics are not a
published replacement until their full operational gates pass. See the acceptance
ledger before comparing results across revisions.

Factory replay must use each recording's own frozen scene and assets. It reads
saved states for visual reconstruction rather than rerunning recorded actions in
new physics. Optional production rendering uses Blender Cycles with explicit CPU,
Metal, CUDA or OPTIX selection; silent device fallback is not an acceptance path.

Factory has a unified configuration/command entry:

```sh
.venv/bin/robofrontier factory setup
.venv/bin/robofrontier factory doctor --device CPU
```

The `[factory]` section controls its independent video/device settings; prepared
plans freeze the effective configuration. See the [Factory guide](factory/replay.md)
for closed-recording import, full tour, CPU/GPU rendering and queue submission.
Native Oracle planning, frozen preparation and bounded supervision also have a
unified entry:

```sh
.venv/bin/robofrontier oracle plan --level 1 --min-arms
.venv/bin/robofrontier oracle prepare --cases mosaic-a04-6x12-d1 \
  --output runs/oracle/my-r14-check --mosaic-max-goals 2
.venv/bin/robofrontier oracle run runs/oracle/my-r14-check
```

Use `--render native` during preparation on macOS or `--render cpu` for Linux
software rendering. Commit the executor before preparation. The `[oracle]`
engineering clock includes planning/review time and is separate from a model
benchmark's START clock. The [Oracle guide](oracle/README.md) documents native
recovery, evidence and the distinction between commissioning and full success.
All four families have passed current compressed-motion Factory import and
all-frame replay checks, with small CPU video previews. The editable
[full-length English video project](factory/editorial.md) is tracked and has
passed CPU/Metal preview and media round trips. The original full movie is
published in the [Factory tour release](https://github.com/changxuanfan/RoboFrontier/releases/tag/factory-tour-media-20261102); a new current-source full render is deferred. New full physical
Oracle qualification remains open. The
[project page](https://changxuanfan.github.io/RoboFrontier/) shows the 36 current
public tasks. Existing Oracle intervention records and historical source identities must
be preserved; assisted execution is not automatically an autonomous benchmark.

## Repository map

| Path | Purpose |
| --- | --- |
| `benchmark/` | The released tasks: four families, nine cases each, and `release.json` |
| `robofrontier.toml` | Public defaults for newly prepared unified batches |
| `robofrontier/` | Simulation, native hosts, runtime protocol and evidence interfaces |
| `prompts/` | Every text a model reads: rules, roles, skills and the two manager prompts |
| `configs/` | Model catalogs, harnesses, asset locks, and scene revisions not yet released |
| `scripts/`, `tests/` | Engineering commands and regression checks |
| `docs/` | Guides by topic and dated history |
| `assets/` | Shared art |
| `docker/` | The container image |
| `runs/`, `outputs/` | Ignored runtime evidence and media; back up separately from Git |
| `.robofrontier/` | Ignored private native state and container command receipts |

The full layout and where new files go: [repository layout](repository-layout.md).

A standalone wheel without the repository catalogs/assets is not a qualified
distribution.
