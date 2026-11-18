# Benchmark

The released RoboTeam benchmark: four task types with nine cases each. Every policy run
selects its case from [`release.json`](release.json); the [task guides](../docs/tasks/README.md)
describe the tasks and their scoring, and [physics](../docs/benchmark/physics.md) the physics every scene
carries.

| Task type | Cases | What the robots do |
| --- | --- | --- |
| [`transport/`](transport) | `transport-{small,medium,large}-l{1,2,3}` | Deliver ordered items and insert them into boards, by handover or staging |
| [`relay/`](relay) | `relay-{small,medium,large}-l{1,2,3}` | Carry long timbers in relay, with an airborne handover each, and release them over GOAL |
| [`mosaic/`](mosaic) | `mosaic-{small,medium,large}-l{1,2,3}` | Place correctly colored cubes in every cell of a target pattern |
| [`dial/`](dial) | `dial-{small,medium,large}-l{1,2,3}` | Turn and hold spring dials, using BEST/READY feedback to unlock |

A case id is `<task type>-<team size>-l<level>`. The number of arms and the workload (items, cells,
timbers or dials) are in the case's `task.json` and in its task type's `catalog.json`, not in the id.

## Layout

```text
benchmark/
  release.json              every case: scene, task and public files by hash; release_id; frozen;
                            private: each Dial case's code
  <task-type>/
    catalog.json            the task type's case catalog
    <case>/
      scene.xml             the scene, with the release physics written into it
      task.json environment.json workstation.json
      public/task.json      the public task a run receives, exactly
      public/*              the task materials a run receives (Mosaic target pattern, Dial
                            previews, table geometry and camera calibration)
      assets/               meshes and textures, restored from the pinned asset archive (not in Git)
  assets.json               the pinned asset archive and its inventory, restored by `roboteam bootstrap`
  hall/                     the factory hall: layout.json, fonts/, textures/, source/
```

`scripts/release/build_release.py` writes the release in place: the physics into every scene
(`physics`), each scene's start at rest (`settle`), the Transport letters (`letters`), the Dial
codes (`codes`) and the public files (`public`); `check` confirms the scenes carry the physics.
Each step rewrites the hashes in `release.json` and its `release_id`. Nothing at run time
rebuilds or patches these files. `frozen` is empty until the release is frozen, after the physics
validation and the platform checks; after that nothing here changes.

`assets/` is not in Git: `roboteam bootstrap` restores it from the archive pinned in
[`assets.json`](assets.json) and checks every file's SHA-256.

[`hall/`](hall) is the factory hall the cases stand in when they are shown together: `layout.json`
(its appearance, layout and shared visual resources, read by `roboteam/sim/hall/build.py`), the
fonts, the Poly Haven source textures and the authored exterior texture. It is not a task type
and no run reads it.
