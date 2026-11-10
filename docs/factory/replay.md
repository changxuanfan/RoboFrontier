# Factory replay and offline rendering

Factory reconstructs saved robot/object poses in a complex background. It does
not rerun policy actions or integrate task physics, and rendering a recording
does not certify that its task succeeded. A recording keeps its own frozen scene,
asset hashes, timestamps and appearance events. New policy physics must not be
silently applied to an old recording.

The unified entry is `robofrontier factory`. It calls the same checked Factory
bundle, preparation, replay and Cycles implementation as the native engineering
entry. It never calls a model or uses policy API credentials.

## Install software and data

Install the repository Python environment with `uv sync --locked --extra oracle`.
Production rendering also needs Blender with Cycles, ffmpeg and ffprobe. Configure
an executable Blender path or expose it through `BLENDER_BIN`/PATH. On macOS the
native default search also checks the usual application installation.

The optional Factory data package is pinned in `configs/factory-assets.json`.
It is separate from the policy asset package: policy bootstrap does not download
historical motion/video inputs. The current Factory package includes 36 stations,
Mosaic R14, frozen recordings, reviewed station edits and shared visual assets.
Its split archive is approximately 5.84 GB; allow at least 20 GB of available
storage for download, reconstruction and installation. Full verification checks
more than 123,000 paths and can take several minutes on a busy machine.

```sh
.venv/bin/robofrontier factory setup
```

Setup downloads only if the configured data root is absent, verifies part and
archive hashes, restores portable paths and verifies all referenced data. An
existing data root must match the configured release lock; setup will not replace
a different bundle. An offline installer can supply the reassembled archive:

```sh
.venv/bin/robofrontier factory setup --archive /path/to/factory.tar.gz
```

Preparation and recording import automatically perform required data setup.
`factory verify` and `factory doctor` inspect existing bytes without triggering a
large download. Neither command reads an active policy SQLite database.

## Configure once

Factory and policy observation settings have separate sections in the same TOML:

```toml
# factory-local.toml
[factory]
device = "OPTIX"
blender = "/path/to/blender"
data_root = "runs/factory-data/r14"
source = "release"
width = 1920
height = 1080
samples = 64
mode = "desks"
views = ["front", "side"]
duration_s = 0.0
import_speedup = 0.0
parallel = 1
```

Repository-relative data/asset-lock paths resolve from the checkout root. The
root defaults target Linux NVIDIA OPTIX. Use `CUDA` for an explicitly selected
CUDA backend, `METAL` on native macOS, or `CPU` for CPU Cycles rendering. Requesting
a GPU backend does not authorize a silent CPU fallback.

`factory.width`/`height` control offline video, independently of policy JPEG
observations. Both dimensions must be positive and even. `duration_s=0` keeps the
full reviewed timeline; a positive value explicitly caps a diagnostic preview.
Changing this option does not change any benchmark wall limit. Presentation uses
the bundle's reviewed 30 fps rather than inventing new source samples.

`import_speedup` applies only to a newly imported recording; `0` (the default)
uses the family's release speedup, as on the simple background (Mosaic 30x).
Import keeps only meaningful motion: pass `--timeline` with the `motion-cut.json`
that `scripts/render_policy_videos.py` wrote for the run, so the Factory video
shows exactly the states of the checked simple-background video. Without it,
import applies the same motion rule (`robofrontier/motion_cut.py`): an arm joint,
finger or object must move in one direction, so jitter, drift and settling count
as still, however visible. `--keep-idle` keeps the full clock. Existing release recordings retain the
release's reviewed cadence and station edits. A speedup is
presentation metadata, not additional physical execution or a new score.

```sh
.venv/bin/robofrontier --config factory-local.toml factory verify
.venv/bin/robofrontier --config factory-local.toml factory doctor
```

Factory doctor verifies data and checks Blender/Cycles device availability,
ffmpeg, ffprobe and dependency versions. It is distinct from the policy `doctor`,
which checks the native model CLI/sandbox and MuJoCo observation renderer.

## Prepare and execute

Prepare one front and side job for every selected station:

```sh
.venv/bin/robofrontier --config factory-local.toml factory prepare \
  --output runs/factory/all-desks
```

The common `[selection]` section and explicit family/case/level/minimum-arm flags
filter the recordings in this bundle. Selection does not swap in the current
policy scene. For example, prepare four minimum-arm Level 1 station views:

```sh
.venv/bin/robofrontier --config factory-local.toml factory prepare \
  --level 1 --min-arms --views front --output runs/factory/l1-front
```

Preparation freezes the effective configuration, actual device, source bundle
identity, release, render dimensions, sample count, frame counts and rendering
code hashes in `plan.json` and its checksum. It does not launch Blender. Choose
a new output directory for a changed plan; editing a prepared JSON invalidates
its checksum. Later edits to the operator's TOML do not change this plan.

Run one job by its explicit index, then inspect the batch:

```sh
.venv/bin/robofrontier factory run runs/factory/l1-front/plan.json --index 0
.venv/bin/robofrontier factory status runs/factory/l1-front/plan.json
```

The frozen configuration controls execution. `--blender` is an explicit operational
executable override; actual device/software evidence remains part of the attempt.
`--scratch /local/path` chooses temporary rendering storage. The run preserves a
unique attempt, checks pose/frame counts and fully decodes the resulting video.
Only then does it write a completion marker with hashes. Interrupted or failed
attempts retain their logs and have no successful completion marker.

An already verified complete job is reused instead of rendered again. An
incomplete render can have another explicit attempt; this is visual replay,
not replay of uncertain physical actions. Changes to frozen source/code require
a newly prepared plan. Status can still inspect a historical plan after local
source changes; it is not permission to execute it with different code.

## Import a new closed benchmark recording

First stop the producer and collect/restore its evidence. The recording directory
must contain a closed, nonempty `stream.json`, chunks, events and frozen source.
Do not mount or read another OS's actively written SQLite file to obtain it.

```sh
.venv/bin/robofrontier --config factory-local.toml factory import-motion \
  /path/to/restored/run/private/outputs/motion \
  --output runs/factory/my-recording-data
```

Import validates source identity, composes that desk using the recording's own
source and leaves the other desks as static background. It creates an uncut
presentation with explicit speedup, not an inferred Oracle edit or success label.
It does not alter the recording. The returned `next_prepare` arguments show how
to prepare this new bundle:

```sh
.venv/bin/robofrontier --config factory-local.toml factory prepare \
  --source imported --data-root runs/factory/my-recording-data \
  --output runs/factory/my-recording-render
```

`source="imported"` means an existing checksummed local recording export. It
prevents the published base asset installer from being applied over that new
bundle. The imported bundle is verified and then frozen into a render plan; it
is not falsely identified as the original published Factory release.

Only compatible published task identities and supported recording schemas can
be imported. A legacy recording with another scene identity must use its own
compatible scene/source path; never rename it to bypass a mismatch. The existing
motion reader handles declared XOR-compressed float32 streams; historical producer
formats need their explicitly supported reader or frozen legacy tools.

## Full editable presentation

The full tour is 210.5 seconds at 30 fps. It visits the complete Factory; selection
filters are rejected instead of silently producing a different full tour:

```sh
.venv/bin/robofrontier --config factory-local.toml factory prepare \
  --mode promo --output runs/factory/full-tour
```

No 30–45 second alternate cut is added by this entry. A diagnostic cap is an
explicit preview, not a replacement deliverable. New full-tour plans freeze an
editable English project containing camera waypoints, SRT title/subtitle tracks,
font/license and style. The tracked default is
[`tour-project.json`](../../assets/robo_factory/tour-project.json). Use `--project`
to freeze your own edited copy. Read the [editorial guide](editorial.md)
for project creation, camera changes, text-only movie revisions, output locations,
validation, and the distinction between media validation and scene qualification.

## Slurm render jobs

Factory uses the same `[slurm]` resource section but freezes it in the Factory
plan. `factory.parallel` limits simultaneous render array jobs; it is independent
of `batch.parallel` for policy experiments. For CPU renders set `slurm.gpus=0`.
CUDA/OPTIX plans use one GPU per job and require `slurm.gpus=1`. Metal is native
macOS and is rejected for the Slurm path.

```toml
[slurm]
partition = "your-render-partition"
account = ""
qos = ""
gpus = 1
cpus_per_task = 20
memory_gib = 64
time_limit_s = 86400
stop_warning_s = 600
```

Inspect the exact submission first; it does not queue by default:

```sh
.venv/bin/robofrontier factory submit runs/factory/full-tour/plan.json
.venv/bin/robofrontier factory submit runs/factory/full-tour/plan.json --queue
```

Only the second command invokes sbatch. Empty partition/account/qos omit those
flags, using site defaults. A warning before allocation expiry forwards stop to
the renderer and preserves an interrupted attempt. The worker stages temporary
rendering in `SLURM_TMPDIR`, or its documented local temporary fallback, then
checksums results before stage-out. Factory rendering does not use a live policy
database; policy jobs instead use the stricter [node-local Slurm flow](../running/slurm.md).
Real site GPU/process tracking and resource acceptance remain hardware-specific.

## Data, outputs and legacy operation

Keep `plan.json`, its checksum, frozen release and successful/failed attempt
records. Each job stores `attempt-*/render/factory.mp4`, render reports, pose inputs
and `render.log`; a complete marker references their verified hashes. Native
policy sessions remain in policy evidence, not in the Factory video directory.
The full motion/frozen assets are needed for another view or background; an MP4
alone is not an editable recording.

Plans without a frozen unified configuration (made by the removed
`scripts.factory_server`) are refused; prepare them again with
`robofrontier factory prepare`. The unified entry does not silently append new
defaults to old plans.
The optional package preserves historical source physics and qualification labels;
its older recordings are not relabeled as executions of a new physical release.

Current Docker policy images do not include Blender or expose the Factory command
through `container`; use native Factory commands or an explicitly provisioned
render host. This remains separate from the already tested Docker MuJoCo CPU
observation path. See the [integration ledger](../archive/unified-main.md) for
real checks and remaining cross-background/hardware acceptance.
