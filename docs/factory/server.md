# Factory on Linux and Slurm

This page runs the [Factory commands](replay.md) on a Linux cluster, including the Slurm render
array. They replay frozen motion, appearance events and reviewed edits with FK and Blender
Cycles; they make no model calls, issue no robot commands and produce no scores. Policy runs
have their own Slurm flow: see [Slurm](../running/slurm.md).

## Install software and data

Clone onto a large filesystem the compute nodes can read, and install the locked environment
on the server itself (never copy `.venv` from another machine):

```sh
git clone https://github.com/changxuanfan/RoboFrontier.git
cd RoboFrontier
uv sync --locked
```

If the uv cache and the checkout are on different filesystems, set `UV_LINK_MODE=copy`. Blender
(with Cycles), ffmpeg and ffprobe must run on the compute nodes: set
`BLENDER_BIN=/absolute/path/to/blender` (or `factory.blender`) and put ffmpeg and ffprobe on
PATH. Blender's system libraries must be present on the compute node, not just the login node;
a missing one (for example `libxkbcommon.so.0`) can be supplied with
`LD_LIBRARY_PATH=/path/to/site-libs:${LD_LIBRARY_PATH:-}`, which `submit` passes into the job.
Linux NVIDIA uses OPTIX (CUDA is the alternative); a missing GPU backend fails rather than
falling back to CPU.

Run setup inside an allocation where the login node forbids data processing. On the cluster
used here `module load slurm` may be needed before `srun` or `sbatch`:

```sh
module load slurm
srun --partition debug --cpus-per-task 8 --mem 16G --time 01:00:00 \
  .venv/bin/robofrontier factory setup
```

Setup installs into `factory.data_root` (default `runs/factory-data/r14` in the checkout); for
another location pass `--data-root /shared/path/factory-r14` to every later command, or set it in
the TOML. The download is about 5.84 GB and restores about 9.8 GB (hard links reduce the space
used); allow at least 20 GB free, plus room for frames. The bundle is presentation data: never
give it to a policy as task input. The same `srun` prefix can wrap `prepare`; `submit` itself is
a light queue operation.

## Check the device

Inside a GPU allocation:

```sh
srun --partition YOUR_GPU_PARTITION --gres gpu:1 --cpus-per-task 4 \
  --mem 16G --time 00:20:00 \
  .venv/bin/robofrontier factory doctor --device OPTIX
```

A login node without a GPU cannot check a compute node's GPU. `--device CPU` checks the CPU path.
Doctor renders no video.

## Short test render

Eight one-second previews (the smallest Level 1 desk of each family, front and side) at reduced
size and sampling:

```sh
.venv/bin/robofrontier --config site.toml factory prepare \
  --output runs/factory/smoke \
  --cases transport-a04-d1 mosaic-a04-6x12-d1 relay-a08-d1 dial-best5-n04-d1 \
  --duration-s 1 --width 640 --height 360 --samples 8 --device OPTIX
.venv/bin/robofrontier factory submit runs/factory/smoke/plan.json
```

`site.toml` holds the `[slurm]` section (partition, account, qos, `gpus`, `cpus_per_task`,
`memory_gib`, `time_limit_s`, `stop_warning_s`) and `factory.parallel`; `prepare` freezes them
into the plan. Review the printed `sbatch` command, then add `--queue`. The array runs one GPU
per item, at most `factory.parallel` at once. Its Slurm time covers preparation, rendering,
encoding and stage-out.

`squeue -j JOB_ID` shows why a job waits: `QOSMaxJobsPerUserLimit` means the account's job
quota is full, `Resources` that the resources are busy. Neither is a render failure.

## Full desk videos and the tour

Without `--duration-s` the full reviewed clips render; without filters, 36 desks × 2 views make
72 items:

```sh
.venv/bin/robofrontier --config site.toml factory prepare \
  --output runs/factory/full --device OPTIX
.venv/bin/robofrontier factory submit runs/factory/full/plan.json --queue
```

Narrow with `--families`, `--level`, `--views` or `--cases`. Each item checks only its own
recording, scene, assets and camera. The tour is one 210.5 s job:

```sh
.venv/bin/robofrontier --config site.toml factory prepare \
  --output runs/factory/promo --mode promo --device OPTIX
.venv/bin/robofrontier factory submit runs/factory/promo/plan.json --queue
```

It keeps its camera plan, `reset-events.json` and per-frame source mapping, and freezes an
editable project ([editorial](editorial.md)).

## Rendering without Slurm

Prepare with `--device OPTIX`, `CUDA`, `METAL` (macOS) or `CPU`, then run each index:

```sh
.venv/bin/robofrontier factory run runs/factory/local/plan.json --index 0
.venv/bin/robofrontier factory status runs/factory/local/plan.json
```

A plan binds input locations and hashes on its machine; after moving data or changing sources,
prepare a new plan rather than editing one.

## Staging, stops and retries

A job renders in `SLURM_TMPDIR`, else `TMPDIR`, else `/tmp`, then copies the results back and
verifies their checksums. Slurm sends SIGTERM `slurm.stop_warning_s` (default 600 s) before the
time limit; the renderer stops and keeps an interrupted attempt. SIGKILL, node loss or a failed
stage-out leave an attempt without `complete.json`; such attempts are never counted. PNG frames
are deleted only after the raw MP4 passes the decode, frame-count and 30 fps checks; textures,
motion and policy images are never deleted.

Running an index again skips a complete job and starts a new attempt otherwise; old videos are
never overwritten. `status` names the jobs that need another attempt; `squeue` and `sacct` show
queued and running jobs.

## Import a benchmark recording

Wait until every writer has stopped, then import the run's `private/outputs/motion/` (restore an
evidence archive into ordinary files first):

```sh
.venv/bin/robofrontier factory import-motion /path/to/run/private/outputs/motion \
  --output runs/factory-data/my-recording
.venv/bin/robofrontier factory prepare --source imported \
  --data-root runs/factory-data/my-recording \
  --output runs/factory/my-recording --device OPTIX
```

Options and checks are in [replay](replay.md#import-a-closed-benchmark-recording).

## Packaging a bundle

`robofrontier.factory.bundle.export` writes a portable bundle folder from a scene, a resolved
release, cameras, an exported asset and a source root; `bundle.pack` verifies every file and
writes a tar.gz, with identical files hard-linked; `bundle.split_archive` splits it into parts
and writes the part list that `configs/factory-assets.json` pins. Publish a changed bundle under
a new name and new hashes.
