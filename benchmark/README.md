# Benchmark

The released RoboFrontier benchmark: four task families with nine cases each.
Every new policy run selects its case from [`release.json`](release.json).

| Family | Cases | What the robots do |
| --- | --- | --- |
| [`transport/`](transport) | `transport-a{04,08,12}-d{1,2,3}` | Deliver ordered items and insert them into boards, by handover or staging |
| [`relay/`](relay) | `relay-a{08,12,16}-d{1,2,3}` | Carry long timbers in relay and release each one at least 70% over the GOAL |
| [`mosaic/`](mosaic) | `mosaic-a04-6x12`, `a06-9x18`, `a08-12x24`, each `d{1,2,3}` | Place distinct, correctly colored cubes in every cell of a target pattern |
| [`dial/`](dial) | `dial-best5-n{04,06,08}-d{1,2,3}` | Operate spring dials and movable modules, using BEST/READY feedback to unlock |

`aNN` is the number of arms, `nNN` the number of dials and `dN` the difficulty level.
Task contracts and scoring are described in the [task guides](../docs/tasks/README.md).

## Layout

```text
benchmark/
  release.json              the four families: cases, public files, Oracle references, hashes
  legacy-paths.json         where each released file lived before 2026-11-03
  source-compatibility.json reviewed shared-source changes for historical validation
  <family>/
    catalog.json            the family's generated case catalog
    *.json                  family records: delivery, selection and build provenance
    <case>/
      scene.xml task.json environment.json workstation.json ...
      assets/               meshes and textures, restored from the pinned asset archive
      public/               the reviewed material a policy may see
```

`assets/` and preview images are not in Git. `robofrontier bootstrap` restores
them from the archive pinned in [`../configs/policy-assets.json`](../configs/policy-assets.json)
and checks every file's SHA-256.

Released files are not edited in place. A new revision is generated under
`configs/environments/`, reviewed, and then promoted here with new hashes in
`release.json`. Earlier revisions that a released case or an Oracle recording names
as its source stay in `configs/environments/` as provenance.

Frozen runs, Oracle recordings and the asset archive name files by their earlier
`configs/` paths. `robofrontier.task_families.current_path` translates those names
through `legacy-paths.json`, and `legacy_bytes` returns a moved file's original bytes.
