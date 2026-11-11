# Robo World rendering (Factory)

Robo World is the rendered factory hall that holds all 36 workstations. The `robofrontier
factory` commands replay saved robot and object poses in it with Blender Cycles: no actions, IK
or physics are run, and a render does not certify that a task succeeded. They make no model
calls.

| Guide | For |
| --- | --- |
| [Replay and offline rendering](replay.md) | Install the data, configure, prepare, render, import a recording, render the full tour |
| [Linux and Slurm](server.md) | The same commands on a cluster, including the render array |
| [Editable presentation](editorial.md) | Titles, subtitles, camera waypoints and text-only revisions of the tour |

## The data folder

The commands read one recording bundle from the configured data folder, `factory.data_root` in
`robofrontier.toml` (default `runs/factory-data/r14`, relative to the checkout, independent of
`paths.runs_root`). With `factory.source = "release"` it holds the pinned R14 bundle locked in
[`configs/factory-assets.json`](../../configs/factory-assets.json) (`factory.asset_lock`): the
36 stations' recordings with their frozen scenes, assets, motion, appearance events and reviewed
edits, the Robo World scene, cameras and pre-exported Blender assets. It is kept to re-render the
published videos. With `factory.source = "imported"` the folder is a bundle written by
`factory import-motion`.

| Path in the data folder | Contents |
| --- | --- |
| `bundle.json` | The bundle's manifest and file hashes |
| `release.json` | The presentation release: per family speedup and the station recordings and edits |
| `scene/scene.xml` | The Robo World scene with all 36 stations placed |
| `asset/` | The exported Blender meshes and textures |
| `cameras.json` | Fixed desk cameras |
| `inputs/` | The stations' recordings and source scenes |

The bundle is separate from the policy assets (`configs/policy-assets.json`) and does not change
benchmark physics: each recording keeps the scene and physics it was recorded with. In it the
Mosaic `a06` and `a08` Level 3 desks replay their Level 2 recordings (`recorded_case_id`).

## Presentation rules

- Speedups come from `benchmark/release.json`: Transport 20×, Mosaic 30×, Relay 20×, Dial 10×.
  Output is 30 fps from 60 Hz recordings.
- Each desk skips its reviewed idle intervals and loops from its own start after it finishes;
  every loop restores the initial colors before replaying appearance events. All stations update
  before each frame is rendered, so neighboring desks are not synchronized.
- Stations are placed by rigid translation and rotation about the vertical axis; robots and
  payloads keep their scale.
- Edits (`robofrontier.station-edit.v2`) select source frames by their 60 Hz indices and bind the
  source stream and event hashes; the original streams are never rewritten. Cutting frames is
  presentation only, not a contact or task measurement.

## Hall design

The hall is 55 × 50 m with four regions, built from
[`configs/backgrounds/robo_factory.json`](../../configs/backgrounds/robo_factory.json). Levels
run L1 to L3 from top to bottom in plan view and team size grows from left to right. Region
floors use the family colors (Transport blue-gray, Mosaic gray-green, Relay terracotta, Dial
ochre), joined by gray aisles with yellow safety lines; each desk has a station label. Racks, cabinets and supply groups keep at least 0.4 m from planned station bounds. The
exterior view is the image `assets/robo_factory/textures/exterior-daylight-v1.png` (its prompt
is in the sibling `.prompt.txt`); everything else is Blender geometry. Display materials are
tuned for rendering only; source scenes, events and robot joints are unchanged.

Fast mode uses three robot level-of-detail meshes, fixed for the whole camera path by the
nearest camera position; `--profile reference` keeps the original meshes. Task fixtures,
openings, payloads and trajectories are never simplified.

## Lower-level commands

`robofrontier factory` is the supported entry. The modules below work on inputs that already
exist; `video` and `poses` need `--scene` and an explicit resolved `--release`, such as the
`release.json` that `factory prepare` writes into its batch folder.

```sh
.venv/bin/python -m robofrontier.factory.commands build --output runs/factory/my-hall
.venv/bin/python -m robofrontier.factory.commands video \
  --scene runs/factory/my-hall/scene.xml --release BATCH/release.json \
  --camera orbit --duration 8 --device OPTIX --output runs/factory/my-orbit
```

| Command | Use |
| --- | --- |
| `robofrontier.factory.commands build` | Build the Robo World scene into a new `--output` folder from the data folder's release, or `--release` |
| `robofrontier.factory.commands video` | Pose export and Cycles render in one step; `--camera tour`, `orbit` (`--orbit-degrees`, default 60), `desk-front --station CASE_ID` or a preset; `--families`, `--levels` select desks |
| `robofrontier.factory.commands poses` | Pose export only, with the same selection |
| `robofrontier.factory.commands view` | Local browser viewer of a scene (`--scene`), MuJoCo rendering with playback |
| `robofrontier.factory.blender.export` | Export a scene to Blender assets (`--scene`, `--output`) |
| `robofrontier/factory/blender/render.py` | Render an exported asset in Blender (`--asset`, `--animation`, `--desk-cameras`, `--device`, `--samples`, `--profile`, `--lighting-config`, `--camera-config`, `--frame-indices`, `--no-encode`, `--keep-frames`, `--metalrt`) |

`video` defaults to 1280 × 720, `--device METAL`, `--profile fast`, adaptive sampling
(`--noise-threshold 0.1`, `--min-samples 4`) and denoising; pass `--device OPTIX`, `CUDA` or
`CPU` elsewhere, and `--blender` if Blender is not found. Render a separately exported pose file
with Blender:

```sh
blender --background --python-exit-code 1 --python robofrontier/factory/blender/render.py -- \
  --asset ASSET_DIR --animation POSES_DIR/animation.json \
  --output RENDER_DIR --engine cycles --device OPTIX --profile fast --samples 24
```

A render writes poses, per-frame source mappings, the MP4, a log and `report.json`. The MP4 is
decoded in full and its frame count and 30 fps checked before the PNG frames are deleted; a
failed export keeps them, and `--keep-frames` or `--no-encode` keeps them always.
`report.json` records preparation, first-frame, per-frame and encoding times separately.
