# Benchmark

The released RoboFrontier benchmark: four task families with nine cases each. Every policy run
selects its case from [`release.json`](release.json); the [task guides](../docs/tasks/README.md)
describe the tasks and their scoring, and [physics](../docs/physics.md) the physics every scene
carries.

| Family | Cases | What the robots do |
| --- | --- | --- |
| [`transport/`](transport) | `transport-a{04,08,12}-d{1,2,3}` | Deliver ordered items and insert them into boards, by handover or staging |
| [`relay/`](relay) | `relay-a{08,12,16}-d{1,2,3}` | Carry long timbers in relay, with an airborne handover each, and release them over GOAL |
| [`mosaic/`](mosaic) | `mosaic-a04-6x12`, `a06-9x18`, `a08-12x24`, each `d{1,2,3}` | Place correctly colored cubes in every cell of a target pattern |
| [`dial/`](dial) | `dial-best5-n{04,06,08}-d{1,2,3}` | Turn and hold spring dials, using BEST/READY feedback to unlock |

`aNN` is the number of arms, `nNN` the number of dials and `dN` the level.

## Layout

```text
benchmark/
  release.json              every case: scene, task and public files by hash; release_id; frozen;
                            the Oracle rows; private: each Dial case's code
  legacy-paths.json         the current path of every file that records name by an earlier path
  pruned-paths.json         records not in the tree, and the tags that keep them
  <family>/
    catalog.json            the family's case catalog
    <case>/
      scene.xml             the scene, with the release physics written into it
      task.json environment.json workstation.json   (parameters.json, target-pattern.png where used)
      public/task.json      the public task a run receives, exactly
      public/*              the family materials a run receives (Mosaic target pattern, Dial
                            previews, table geometry and camera calibration)
      assets/               meshes and textures, restored from the pinned asset archive (not in Git)
  dial/best5-r11.json       the Dial Oracle evidence the preservation check reads
  oracle/
    <case>/                 the scene each Oracle recording was made on, with its task, public task,
                            compiled physics and validation records
    sources/                the source scenes the Oracle cases derive from (Transport and Mosaic
                            r13, Relay r16 d2/d3), their assets, and the Transport r13 catalog
```

`scripts/build_release.py` writes the release in place: the physics into every scene
(`physics`), each scene's start at rest (`settle`), the Transport letters (`letters`), the Dial
codes (`codes`) and the public files (`public`); `check` confirms the scenes carry the physics.
Each step rewrites the hashes in `release.json` and its `release_id`. Nothing at run time
rebuilds or patches these files. `frozen` is empty until the release is frozen, after the physics
validation and the platform checks; after that nothing here changes.

`assets/` is not in Git: `robofrontier bootstrap` restores it from the archive pinned in
[`../configs/policy-assets.json`](../configs/policy-assets.json) and checks every file's SHA-256.
The Oracle case folders hard-link the released cases' asset files.

Frozen runs, Oracle recordings and review packages name files by the paths they were made with;
`robofrontier.tasks.families.current_path` translates them through `legacy-paths.json`. The nine
Relay Oracle rows name the checkout they were recorded in; `robofrontier.tasks.families.oracle_recording`
finds them under `runs/oracle/`. Scene revisions outside the release are kept in archive tags
([history](../docs/history.md)).
