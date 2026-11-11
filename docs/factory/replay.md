# Factory replay and offline rendering

`robofrontier factory` replays saved robot and object poses in Robo World and renders them with
Blender Cycles. It never runs actions or physics, never calls a model and never reads policy
credentials. A recording keeps its own frozen scene, asset hashes, timestamps and appearance
events; rendering it does not certify its task outcome.

| Command | What it does |
| --- | --- |
| `setup` | Downloads (if absent), verifies and installs the data folder |
| `verify` | Checks the installed data folder; never downloads |
| `doctor` | `verify` plus Blender, the Cycles device, ffmpeg, ffprobe and dependency versions |
| `prepare` | Freezes a render plan (`plan.json`) for the selected desks or the full tour; does not start Blender |
| `run PLAN --index N` | Renders one job of a plan |
| `status PLAN` | Reports every job's state and video paths (writes `summary.json`) |
| `submit PLAN [--queue]` | Prints, or with `--queue` submits, the Slurm render array |
| `import-motion RECORDING` | Builds a new bundle that shows one closed benchmark recording on its desk |
| `project` | Writes an editable copy of the tour project ([editorial](editorial.md)) |
| `edit-video` | Re-captions an existing uncaptioned tour movie without Blender ([editorial](editorial.md)) |

`setup`, `verify`, `doctor`, `prepare`, `import-motion` and `project` take `--data-root` and
`--source` to override `factory.data_root` and `factory.source`. Put `--config FILE` before
`factory`.

## Install software and data

Install the Python environment with `uv sync --locked`. Rendering needs Blender with Cycles,
ffmpeg and ffprobe; set `factory.blender`, `BLENDER_BIN` or put `blender` on PATH (on macOS the
usual application folder is also searched).

```sh
.venv/bin/robofrontier factory setup
```

Setup installs the pinned R14 bundle into `factory.data_root` (default
`runs/factory-data/r14`, relative to the checkout). It downloads the parts listed in
[`configs/factory-assets.json`](../../configs/factory-assets.json) (about 5.84 GB), checks each
part's and the archive's SHA-256, restores the files and verifies every referenced path. Allow
at least 20 GB free. If the folder exists, setup only verifies it and refuses a different
bundle. With an already assembled archive:

```sh
.venv/bin/robofrontier factory setup --archive /path/to/factory.tar.gz
```

`prepare`, `import-motion` and `project` run setup themselves when the folder is missing.
`verify` and `doctor` never download.

## Configure

Factory settings are the `[factory]` section of the same TOML as the policy settings:

```toml
# factory-local.toml
[factory]
device = "OPTIX"            # OPTIX | CUDA | METAL | CPU
blender = "/path/to/blender"
data_root = "runs/factory-data/r14"
source = "release"          # release | imported
mode = "desks"              # desks | promo
views = ["front", "side"]
width = 1920
height = 1080
samples = 64
duration_s = 0.0            # 0 keeps the full reviewed timeline; positive caps a preview
import_speedup = 0.0        # 0 uses the family speedup from benchmark/release.json
parallel = 1                # Slurm render array concurrency
```

The default device is OPTIX (Linux NVIDIA). Use METAL on macOS and CPU for CPU rendering; a
missing GPU backend fails rather than falling back to CPU. Width and height must be positive and
even; they are independent of policy observation images.

```sh
.venv/bin/robofrontier --config factory-local.toml factory verify
.venv/bin/robofrontier --config factory-local.toml factory doctor
```

## Prepare and render desks

```sh
.venv/bin/robofrontier --config factory-local.toml factory prepare \
  --output runs/factory/all-desks
```

Without filters this makes one job per desk and view: 72 jobs. `--families`, `--cases`,
`--level`, `--min-arms` and `--views` (or `[selection]`) narrow it; for example, the four
smallest Level 1 desks, front view only:

```sh
.venv/bin/robofrontier --config factory-local.toml factory prepare \
  --level 1 --min-arms --views front --output runs/factory/l1-front
```

`prepare` freezes the effective configuration, device, bundle identity, release, dimensions,
samples, frame counts and code hashes into `plan.json` and `plan.sha256`. It needs a new output
folder; later TOML edits do not change a plan, and editing `plan.json` invalidates it.

```sh
.venv/bin/robofrontier factory run runs/factory/l1-front/plan.json --index 0
.venv/bin/robofrontier factory status runs/factory/l1-front/plan.json
```

`run` takes `--blender` to override the executable and `--scratch DIR` for temporary frames. Each
run is a new `attempt-*` folder; the job's `complete.json` is written only after the pose and
frame counts are checked and the MP4 is decoded in full. A job that already has a valid
`complete.json` is skipped; a failed or interrupted attempt keeps its log, and running the index
again starts a new attempt. A plan whose source code changed must be prepared again.

## Import a closed benchmark recording

Stop the run and collect or restore its evidence first. The recording folder is the run's
`private/outputs/motion/`, closed and nonempty (`stream.json`, chunks, `events.jsonl`,
`source/`).

```sh
.venv/bin/robofrontier --config factory-local.toml factory import-motion \
  /path/to/run/private/outputs/motion \
  --timeline /path/to/motion-cut.json \
  --output runs/factory-data/my-recording
.venv/bin/robofrontier --config factory-local.toml factory prepare \
  --source imported --data-root runs/factory-data/my-recording \
  --output runs/factory/my-recording
```

Import checks that the recording's case is one of the 36 released cases, composes that desk
from the recording's own `source/` and leaves the other desks as static background. It never
alters the recording or infers a task outcome.

| Option | Effect |
| --- | --- |
| `--timeline FILE` | Keep exactly the states of the `motion-cut.json` that `robofrontier/media/render.py` wrote for this run, so the Robo World video matches the checked simple-background video |
| (neither) | Keep the meaningful motion found by `robofrontier/media/motion_cut.py`: an arm joint, finger or object moving in one direction; jitter, drift and settling count as still |
| `--keep-idle` | Keep every recorded state |
| `--speedup X` | Playback speed; default `factory.import_speedup`, else the family speedup |

The command's result includes `next_prepare`, the arguments for the `prepare` above.
`source = "imported"` keeps setup from installing the release bundle over the new folder.

## Full tour

```sh
.venv/bin/robofrontier --config factory-local.toml factory prepare \
  --mode promo --output runs/factory/full-tour
```

The tour is 210.5 s at 30 fps over the whole hall; selection filters are refused in this mode.
The plan freezes an editable English project (camera waypoints, title and subtitle tracks, font
and style), by default
[`assets/robo_factory/tour-project.json`](../../assets/robo_factory/tour-project.json), or your
copy with `--project`. See the [editorial guide](editorial.md).

## Slurm render jobs

`submit` uses the `[slurm]` section, frozen into the plan by `prepare`. `factory.parallel` caps
simultaneous array jobs, independent of `batch.parallel`. CUDA and OPTIX jobs take one GPU and
need `slurm.gpus = 1`; CPU jobs need `slurm.gpus = 0`; METAL is refused.

```sh
.venv/bin/robofrontier factory submit runs/factory/full-tour/plan.json
.venv/bin/robofrontier factory submit runs/factory/full-tour/plan.json --queue
```

Only the second command calls `sbatch`. Empty `partition`, `account` and `qos` omit those flags.
Slurm signals the job `slurm.stop_warning_s` before its time limit; the renderer stops and keeps
an interrupted attempt. See [Linux and Slurm](server.md).

## Outputs

```text
PLAN_DIR/
  plan.json  plan.sha256  release.json
  logs/                          Slurm logs
  jobs/CASE--VIEW/               (promo: jobs/promo/)
    complete.json                only after the video checks and stage-out pass
    attempt-ID/
      poses/                     source-state mapping, cameras, poses, reset events
      render/factory.mp4  render/report.json
      editorial/                 promo only: captioned movie, report, frozen project
      render.log  attempt.json
  summary.json                   written by status
```

PNG frames are deleted only after the raw MP4 is decoded and its frame count and 30 fps
checked. Another view or background needs the recording and its frozen assets; an MP4 alone
cannot be re-rendered. The Docker policy image has no Blender; render on a host with Blender
installed.
