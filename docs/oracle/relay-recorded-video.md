# Relay: one edited trajectory across backgrounds at 20x

This describes the historical 2026-10-27 export of nine recorded cases. It did
not rerun an Oracle, integrate task physics or reset a live world. Current
imports and compressed recordings use the [Factory workflow](../factory/replay.md);
legacy packages retain their frozen source and original verdicts.

## Three sampling rates

- Original physics: 2-ms integration steps, 500 Hz.
- Original pose recording: 60-Hz float32 qpos, including joints, grippers,
  timber and independent weights.
- Editing decisions: reviewed 20-Hz samples with 0.25-s/2-s windows. Exported
  video: 30 fps at 20x effective simulation time.

Video selects states directly from original 60-Hz rows. Motion analysis is in
`scripts/analyze_relay_motion.py`, track/simple-background export is in
`scripts/export_relay_edited.py`, and Relay time mapping is in
`robofrontier/relay_motion_edit.py`. Factory films use the separate Cycles entry;
these scripts do not become a new Factory task-physics simulator.

## Edit the trajectory before changing the background

Each case under the historical local
`outputs/oracle/relay-edited-tracks-20261027/` contains:

| File | Contents |
| --- | --- |
| `edit.json` | Source scene hash, completion cutoff, retained intervals, reviewed thresholds and visual-review provenance |
| `track.npz` | Original 60-Hz states in retained intervals, source times/frame numbers, edited times, row durations and interval IDs |
| `source/` | Exact frozen model, joint/geometry registry and assets matching qpos |
| `events.jsonl` | All appearance events up to completion; events inside removed waits apply before the next displayed frame |
| `initial-rgba.json` | Initial appearance |
| `source-chunks.json` | Original chunk inventory, hashes and extraction-time verification |

The exporter does not reclassify stillness from Factory pixels. Reviewed 20-Hz
Boolean decisions become half-open source-time intervals, with each sample's
cell bounded by the midpoints to adjacent samples. Original 60-Hz rows are
selected from retained cells. qpos is copied, not reconstructed from commands,
interpolated across cuts or advanced through physics. Original recordings keep
all waits; only the derived package removes them.

Effective arm and beam motion are combined with OR. Numerical noise, whole-scene
stillness and weight-only swings reuse the same edit decisions reviewed across
960 visual segments. Genuine events such as timber slipping remain. Thresholded
engineering analysis cannot guarantee detection of arbitrarily small motion
below sample/recording resolution. Long passive timber/spring oscillations
without progress still need better classification; do not claim all were removed.
The historical delivery handled cases individually. A joint player with
independent table clocks was then pending; a player must preserve each table's
speed and hold its final state after its own timeline ends.

`edited_time_s` in `track.npz` starts at zero and excludes removed waits;
`source_time_s` retains the jumps. Accumulated `duration_s` gives effective
length. Original sampling lies on a 2-ms clock with approximately 16/18-ms row
gaps: compute speed from actual time differences, not a fixed frame interval,
and never bridge cut boundaries. `context_qpos` and `context_source_time_s`
retain original first/last evidence poses.

New derived packages use `robofrontier.relay-motion-edit.v1`. Already delivered
`robofrontier.motion-edit.v1` packages are not rewritten; readers identify them
through complete Relay field validation. Mosaic's older schema of the same
name is a different frame-reference format, not a Relay trajectory package.

## Frozen-source migration boundaries

`source/workstation.json` supplies stable body/geom identities and qpos layout.
Each Factory visual model uses its package's exact frozen source; do not mix
beam revisions. Unnamed robot geometry uses the registry's `source_index`.
A registry label such as `A_link0:geom0` is not a native MuJoCo geom name.

Source forward kinematics produces all body poses. Apply one common translation
and vertical-axis rotation to the table, all robots, objects and cameras, without
scaling. Transform world-space free bodies and robot roots correctly; joint
angles remain local. Table materials, lights and static Factory background may
change while source/edited times remain unchanged. Moving selected bases or
the table independently, scaling apparatus or changing physics is outside this
rigid migration contract.

Factory playback uses mocap bodies to display recorded FK poses with zero task
dynamics. It does not revalidate task physics or establish that neighboring
static workstations completed their tasks. Every output frame checks all visible
source/target geom positions and rotation matrices with a 1e-6 limit. A source
scene hash mismatch rejects playback.

## Frame mapping at 20x

`video_rows` selects one recorded state every `20/30` seconds of the continuous
edited clock, without qpos interpolation. Every background uses identical row
numbers. First and last evidence poses add one frame each, a total of 2/30 s.
Video duration is `ceil(effective_simulation_seconds * 30 / 20) / 30 + 2/30`.
Fast playback may omit short actions from displayed frames even though the full
track preserves them. The same package can later be rendered more slowly.

The historical
`outputs/oracle/relay-20x-20261027/<case>/frame-map.csv` is shared by both
backgrounds. It records video frame/playback time, source simulation time,
edited time, track row, original 60-Hz frame and interval ID. `render.json`
records the derived track hash, Factory hash, speed, fps, geometry errors,
complete decoding and video hash. Preserve original paired videos/frame maps.

## Legacy reusable commands

These require the original local inputs and new output directories; clone does
not download these historical experimental records. They are not commands to
resume a live task. The `render` command below outputs the simple background.
Factory video uses `python -m scripts.factory video` through the current
[Factory workflow](../factory/replay.md).

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. \
  .venv/bin/python -m scripts.export_relay_edited prepare \
  outputs/oracle/relay-active-only-20261027 \
  --output outputs/oracle/relay-edited-tracks-20261027

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. \
  .venv/bin/python -m scripts.export_relay_edited factory \
  outputs/oracle/relay-edited-tracks-20261027 \
  --output outputs/robo-factory/relay-recorded-20261027

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. \
  .venv/bin/python -m scripts.export_relay_edited render \
  outputs/oracle/relay-edited-tracks-20261027 \
  --output outputs/oracle/relay-20x-20261027
```

A changed scene needs a new output and a newly assembled exact-source model.
Encoders write partial files first, promote only after full decode/frame-count
checks, and compare the render plan before reusing existing results. Preserve
original videos and source trajectories.
