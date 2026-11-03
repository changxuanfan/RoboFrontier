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
    *.json                  family records (see below)
    <case>/
      scene.xml task.json environment.json workstation.json ...
      public-task.json      the public projection generated with the scene
      assets/               meshes and textures, restored from the pinned asset archive
      public/               reviewed material that belongs to this case only (Mosaic, Dial)
```

`release.json` lists, for every case, each file a policy may see and its SHA-256.
Each file is stored once:

- Family guidance shared by all nine cases is the archived text it was reviewed
  as, under [`../prompts/archive/`](../prompts/archive/).
- The reviewed public projection is `<case>/public-task.json` where review kept the
  generated one (Transport), and `<case>/public/reviewed-task.json` where review
  changed it (Mosaic, Dial). Relay has none.
- Dial cases keep the previews, table geometry and camera calibration exported from
  their own scene in `public/`. Level 2 and 3 of a size export identical geometry;
  each stays with its scene, as generated scene files do.

## Family records

Beside its `catalog.json`, a family folder keeps the records its tools and
packages read. Each one is frozen: other records and Oracle evidence name it by
hash, so it is never rewritten, only superseded by a new record.

| Record | What it holds | Read by |
| --- | --- | --- |
| `dial/best5-r11.json` | The BEST5 R11 family review: selected Oracle evidence per case, presentation defaults, policy guidance and the integration still required before a formal run | `suite/dial_policy_package.py`, `scripts/check_oracle_preservation.py` |
| `dial/integration-requests.json` | The shared-runtime changes the Dial work asked for, each with its acceptance check | `scripts/check_dial_family.py` |
| `mosaic/r13.json` | The R13 family registry: catalog, harness and evaluator hashes, guidance and readiness per case; the Oracle recordings and Factory replay use R13 | Mosaic Oracle, packaging and Factory tools |
| `mosaic/r14.json` | The R14 local-colour revision, with its R13 baseline by hash. R14 now lives under `configs/environments/mosaic/frontier-v2-r14-*`; the release uses R15, built from R14 by `scripts/build_mosaic_pitch.py` | `suite/mosaic_delivery.py`, `scripts/build_mosaic_local_colors.py` |
| `mosaic/selection.json` | Which registry served which purpose when R14 was prepared: R14 for future policy runs, R13 for Oracle and Factory replay. New runs follow `release.json` | `suite/mosaic_delivery.py` |
| `mosaic/delivery.json` | Delivery purposes, the protected snapshot and the Factory playback setting | `suite/mosaic_delivery.py` |
| `mosaic/builder-compatibility.json` | Historical builder identities whose static public projection is unchanged | `suite/mosaic_policy_package.py` |
| `transport/half-opening-r14.json` | The R14 half-opening physical revision chosen for new runs, with its acceptance audit and witness registry | `scripts/build_transport_policy_package.py`, `scripts/edit_transport_recordings.py` |
| `transport/r13-qualified.json` | The nine qualified R13 Oracle witnesses (216 goals); `half-opening-r14.json` names it by hash | through `half-opening-r14.json` |
| `transport/delivery.json` | The final Transport package, playback, retained folders and protected inventory | No code; the Transport cleanup audit under `runs/oracle/` names it by its earlier path |

Relay has only its catalog.

`assets/` is not in Git: `robofrontier bootstrap` restores it from the archive pinned
in [`../configs/policy-assets.json`](../configs/policy-assets.json) and checks every
file's SHA-256. Preview images at a case's top level are local renders and are not
in Git either; the previews a policy may see are the tracked copies in `public/`.

Released files are not edited in place. A new revision is generated under
`configs/environments/`, reviewed, and then promoted here with new hashes in
`release.json`. Earlier revisions that a released case or an Oracle recording names
as its source stay in `configs/environments/` as provenance.

Frozen runs, Oracle recordings, review packages and the asset archive name files
by their earlier paths. `robofrontier.task_families.current_path` translates those names
through `legacy-paths.json`, and `legacy_bytes` returns a moved file's original bytes.
