# Native Factory Linux and Slurm handoff

New unified-main users should start with [Factory replay and offline
rendering](replay.md). This page documents the underlying
`scripts.factory_server` commands, including their own Slurm render array.
They replay frozen motion, appearance events and reviewed edits using FK and
Blender Cycles. They do not call models, issue robot commands, simulate contact
or produce new benchmark scores. Policy execution has different SQLite and
Slurm requirements: see [policy Slurm staging](../running/slurm.md). Dated native acceptance
is recorded in [Factory server validation](../archive/factory-server-validation.md).

## Install software and data

Create a new checkout on a large filesystem accessible to the compute nodes.
A new machine does not need a copy of a maintainer's worktree. Select the
published branch or commit you intend to reproduce, then install the locked
Python 3.12 environment at the repository root:

```sh
git clone https://github.com/changxuanfan/RoboFrontier.git
cd RoboFrontier
uv sync --locked
```

Integration changes exist only on `integration/unified-main` until publication;
cloning remote `main` before that merge does not obtain them. The earlier native
server handoff was published as `codex/factory-server-handoff`. Record the exact
commit for a reproducible run. Reinstall `.venv` on the server rather than copying
it from a Mac. If the uv cache and checkout are on different filesystems,
`UV_LINK_MODE=copy` avoids repeated hard-link attempts during installation.

The dated acceptance used Blender 5.1.2, FFmpeg and FFprobe, all executable on the
compute node. Set `BLENDER_BIN=/absolute/path/to/blender` and put FFmpeg/FFprobe
on PATH. Linux NVIDIA uses OPTIX; CUDA is another explicit choice. Native macOS
uses METAL. CPU is an explicit diagnostic/rendering choice. A missing requested
GPU backend causes failure instead of silent CPU fallback. The repository does
not distribute cluster drivers or another machine's Python environment.

Blender's system libraries must also be available on the compute node; a working
login-node executable does not prove this. The dated server acceptance initially
failed because `libxkbcommon.so.0` was missing. An administrator can install the
system package, or the site can supply a user-space library directory with
`LD_LIBRARY_PATH=/path/to/site-libs:${LD_LIBRARY_PATH:-}`. The submit command
passes that environment into the job. Run doctor inside an allocation before
long jobs. System-library errors do not justify editing source scenes.

```sh
.venv/bin/python -m scripts.factory_server setup
```

Setup defaults to `runs/factory-data/r14/`. `configs/factory-assets.json` pins the
release, part SHA-256 values, complete archive SHA-256 and data-manifest SHA-256.
Setup downloads the parts, combines them, verifies and restores the package;
users need not manually find a release. For an existing complete offline archive,
add `--archive /path/to/factory.tar.gz`. A custom location uses
`--data-root /shared/path/factory-r14`; use the same option in later commands.
Absolute paths simplify queued execution. Avoid small-quota home directories.

At the originally tested site, `slogin` prohibits data processing. Do not unpack,
verify or prepare on such a login node. Load the site's Slurm module and request
an allowed CPU allocation, for example:

```sh
module load slurm/slurm/23.02.6
srun --partition debug --cpus-per-task 8 --mem 16G --time 01:00:00 \
  .venv/bin/python -m scripts.factory_server setup
```

The same `srun` prefix can wrap preparation. Submission itself is a lightweight
queue operation. Replace module/partition names for your cluster. Each command
releases its allocation when it finishes; no persistent outer agent is needed.

The package contains 36 stations, Mosaic R14, each recording's frozen scene and
assets, motion, events, edits and their semantic verification evidence, cameras
and pre-exported Blender assets. Unlike the roughly 186 MB policy scene package,
this historical playback package downloads about 5.84 GB and restores about
9.8 GB logically; hard links reduce physical use. Allow at least 20 GB free for
initial setup, including the temporary archive. Render frames need additional
space according to resolution and duration. Do not expose this private playback
package to policy models as task input.

The Factory lock is separate from `policy-assets.json` and does not redefine
benchmark physics. Old recordings retain their actual source parameters.
Offline rendering does not turn them into new executions under revised friction.
Mosaic a06-d3 and a08-d3 presentations reuse corresponding d2 recordings, retaining
`recorded_case_id` and physical-equivalence checks. They are not new Level 3
runs or success evidence. Other source qualification flags are also retained.

## Short commissioning run

Inside a GPU allocation, inspect software and the requested device:

```sh
.venv/bin/python -m scripts.factory_server doctor --device OPTIX
```

To queue the inspection from a login node:

```sh
srun --partition YOUR_GPU_PARTITION --gres gpu:1 --cpus-per-task 4 \
  --mem 16G --time 00:20:00 \
  .venv/bin/python -m scripts.factory_server doctor --device OPTIX
```

A login node without a GPU cannot verify compute-node GPU availability. An
explicit `--device CPU` can check the CPU path, followed by the short GPU job
below. Doctor does not render video or call a model.

This example selects the minimum-arm Level 1 case in each family and front/side
views: eight one-second previews. Production defaults are 1920 x 1080, 30 fps
and 64 samples; this diagnostic deliberately reduces resolution and sampling.

```sh
.venv/bin/python -m scripts.factory_server prepare \
  --output runs/factory/smoke \
  --cases transport-a04-d1 mosaic-a04-6x12-d1 relay-a08-d1 dial-best5-n04-d1 \
  --duration-s 1 --width 640 --height 360 --samples 8 --device OPTIX

.venv/bin/python -m scripts.factory_server submit \
  --plan runs/factory/smoke/plan.json --partition YOUR_PARTITION \
  --parallel 2 --cpus 20 --memory 64G --time 01:00:00 --dry-run
```

Review generated sbatch options, then remove `--dry-run` to submit. Resources
and partitions depend on the site; the example does not guarantee immediate GPU
allocation. Some sites require the Slurm module before submission.

The command creates an array with one GPU per render item. `--parallel` limits
simultaneous renders, not model concurrency. The checkout, Python environment,
data and `BLENDER_BIN` must be accessible on compute nodes. The template does not
embed personal accounts or a fixed Lustre path. Its Slurm wall time includes
preparation, rendering, encoding and stage-out; it is unrelated to policy START.

After submission, `squeue -j JOB_ID` shows pending reasons.
`QOSMaxJobsPerUserLimit` means the account's concurrent-job quota is full;
`Resources` means requested resources are unavailable. Neither means rendering
failed. The array concurrency is only a batch ceiling and remains subject to
account limits. Never cancel other users' jobs on a shared account.

## Full desk videos and presentation

Omit `--duration-s` to render full reviewed clips. Without filters, 36 stations
and two views produce 72 render items:

```sh
.venv/bin/python -m scripts.factory_server prepare \
  --output runs/factory/full --device OPTIX
.venv/bin/python -m scripts.factory_server submit \
  --plan runs/factory/full/plan.json --partition YOUR_PARTITION --parallel 2
```

Use `--families transport relay`, `--levels 1 2`, `--views front` or explicit
`--cases CASE_ID ...` to narrow selection. Preparation checks the full data
package. Each render item checks its own source recording, scene, assets and
camera rather than repeatedly reading other tasks' large recordings. Desk mode
uses fixed cameras and each source's independent reviewed edits. No state or
appearance event is physically re-solved.

The presentation is a separate job, defaulting to 210.5 seconds, with a full
Factory camera path and explicitly recorded playback restarts:

```sh
.venv/bin/python -m scripts.factory_server prepare \
  --output runs/factory/promo --mode promo --device OPTIX
.venv/bin/python -m scripts.factory_server submit \
  --plan runs/factory/promo/plan.json --partition YOUR_PARTITION --parallel 1
```

Its camera plan, `reset-events.json` and per-frame source mapping are retained.
This is edited presentation playback, not a synchronized end-to-end multitask
experiment. New promo plans also freeze an editable English camera/title/subtitle
project. Use `project --output NEW_PROJECT` to create a working copy and
`prepare --project NEW_PROJECT/project.json` to freeze edits. The shared
[editorial guide](editorial.md) documents the shipped full-length project,
SRT/style changes, camera changes, retained raw/final media, and the separate
`edit-video` text-only path. A short preview or text edit of a historical movie
does not establish delivery of a full newly rendered current-source movie.

## Native execution and output

Use `--device METAL` when preparing for native macOS, or explicit `--device CPU`
for CPU rendering. Slurm is optional:

```sh
.venv/bin/python -m scripts.factory_server run --plan runs/factory/local/plan.json --index 0
.venv/bin/python -m scripts.factory_server status --plan runs/factory/local/plan.json
```

First create `local` with `prepare`; every preparation needs a new output path.
Data can be relocated and prepared again. An existing plan binds input locations
and source hashes on that machine, so do not hand-edit it after relocation or
source/parameter changes. Keep old plans and results, and prepare a new batch.

```text
batch/
├── plan.json, plan.sha256, release.json
├── logs/                         Slurm logs
├── jobs/CASE--VIEW/
│   ├── complete.json             Only after video checks and stage-out pass
│   └── attempt-UNIQUE-ID/
│       ├── poses/                Source-state mapping, cameras and poses
│       ├── render/factory.mp4
│       ├── render/report.json
│       ├── editorial/            Promo: final movie, report and frozen project
│       ├── render.log
│       └── attempt.json
└── summary.json                  Generated by status, including video paths
```

Rendering uses `SLURM_TMPDIR`, `TMPDIR` or `/tmp`, then verifies copies returned
to the batch. This path has no live SQLite database. Slurm sends a signal 180
seconds before termination to attempt cleanup. SIGKILL, node loss or failed
stage-out can leave unsealed attempts. Retain local paths from logs and do not
mark those attempts successful. Local storage and cleanup policy depend on the
site; resource requests need enough time and space for finalization.

Render PNGs are deleted only after full raw MP4 decode and frame-count/30-fps
checks. A failed Cycles render keeps existing frames; a later subtitle failure
may follow that cleanup, but retains the verified raw MP4 and failed-attempt
evidence. Source texture PNGs, motion and policy observation JPGs are not deleted.
Original temporary paths remain in reports as
provenance; use actual batch files and `complete.json` for analysis.

Re-running the same index verifies and skips an already complete video. Failed
or interrupted work uses a new attempt directory. It does not overwrite old
videos, resume a half-running Blender process or combine different plans.
`status` identifies items needing another attempt; `squeue`/`sacct` remain the
authority for queued/running cluster jobs.

## Import a new benchmark recording

Wait until every original writer has stopped. Import
`private/outputs/motion/`, not the image or session directory:

```sh
.venv/bin/python -m scripts.factory_server import-motion \
  --recording /path/to/run/private/outputs/motion \
  --output runs/factory-data/my-recording --speedup 1
.venv/bin/python -m scripts.factory_server prepare \
  --data-root runs/factory-data/my-recording \
  --output runs/factory/my-recording --device OPTIX
```

The published 36 case IDs are supported; Mosaic source display must be R14.
Import rebuilds the relevant station from the recording's own frozen inputs and
exports a new Blender asset; other desks become static background. Without
`--keep-idle` or `--timeline` it keeps `robofrontier.motion_cut`'s meaningful
motion and cuts idle stretches; `--keep-idle` keeps every recorded state (an
all-retained edit), and `--timeline` follows a motion edit such as the
`motion-cut.json` from `scripts/render_policy_videos.py`. Omitting `--speedup`
plays at the family's release speedup. Import never infers task success or
borrows an Oracle completion prefix. Missing source
assets, an active recording, a task mismatch or failed motion validation cause
rejection. `MotionReader` supports older motion formats. Restore an evidence
archive into ordinary files before importing its motion directory.

## Maintainer packaging

`export` creates a portable directory from explicit scene, release, cameras,
asset and source-root inputs. `pack` verifies every file and writes tar.gz.
The package retains original edit and motion bytes; identical files share hard
links. `robofrontier.factory.bundle.split_archive` creates part metadata, pinned after
publication in `configs/factory-assets.json`. Publish changed data under a new
name and hashes; keep older releases for historical reproduction. Do not change
the policy `current.json` to switch Factory data.

The Factory option in evidence replay checks uses independent sampled MuJoCo
images/FK. Production videos use Cycles. Neither integrates physics, and sampled
image success does not establish full-video or task-score acceptance.
