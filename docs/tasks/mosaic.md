# Mosaic

The team builds a four-color Tulip pattern (cream, navy, coral, sage), background cells
included, with one 60 mm cube per cell on a 71 mm pitch. The pattern matrix and the reference
image are in world orientation (row 1 north). Stock allocations to stations do not restrict
which arm uses an item.

| Level | Grid | Scales |
| --- | --- | --- |
| 1 (`d1`) | 70 mm square pockets | 6×12 cells with 4 arms, 9×18 with 6, 12×24 with 8 |
| 2 (`d2`) | 3 mm red printed lines | the same |
| 3 (`d3`) | No visible grid | the same |

Every cell needs the right color, inside its cell and released.

## Earlier revisions, Oracle evidence and tools

The sections below keep the detail written while each revision was built; numbers such as
R13 or R14 name those revisions.

### Current selection and Legacy sources

New policy and unified Oracle executions select the current **R15** released
scene through `benchmark/release.json`. R15 (2026-11-03) is R14 with a **71 mm**
grid pitch; cubes stay 60 mm. Only the board changed: the Level 1 pocket walls,
floor and the table frame around the opening, the Level 2 printed lines, and the
goal cell centres. Robots, stock and its locally mixed colors, the table, cameras,
the initial keyframe, the pattern and the completion rules are R14's; the Level 3
scene file is byte-identical to R14. Its builder, `scripts/build_mosaic_pitch.py`, was removed on 2026-11-10 (restore from tag `archive/pre-cleanup-20261110`; see the [cleanup log](../cleanup-20261110.md)).
R14 (81 mm) is only in the archive tag `archive/pre-cleanup-20261110`. New Factory imports use the actual
policy/Oracle recording's own frozen scene, source hashes, motion, and events.

The historical purpose files `benchmark/mosaic/delivery.json` and
`benchmark/mosaic/selection.json` (in the tag `archive/pre-cleanup-20261110`) record the
original R13 Oracle/R14 future-policy split. They do not affect new-run selection. The nine original
complete Oracle witnesses and their Factory recordings use R13 stock colors;
their independent audits covered 1,566/1,566 cells. Preserve those recordings
with their original source instead of replaying their poses into R14 colors.
That delivery metadata (schema `robofrontier.mosaic-delivery.v2`) has a `timeline_index`
pointing to the checksum-pinned original video index; the removed `prepare_factory_edits`
script (2026-11-10) resolved cases through it and verified the index and edit hashes.
Original non-English filenames stay in the immutable evidence, not current
configuration strings. No historical file is renamed or rewritten.
New R14 Oracle attempts have separate qualification; the old success does not
transfer automatically. See [Oracle execution](../oracle/README.md) and the
integration ledger (`docs/archive/unified-main.md`, in the [archive tag](../history.md)).

At its original release, R14 changed stock color identities/RGB only: stock
positions/count, total color inventory, target pattern, robots, tabletop, cameras,
and geometry matched R13. Current rolling-friction assets are a separate physical
revision identified by the release lock. Three levels at one scale share a stock
color arrangement. Sampling found same-arm pick/place geometry to different
same-color goals for about 70%-73% of each arm's nearby stock; this is design
availability evidence, not a required assignment, complete carrying path,
handover count, or parallel-efficiency result.

### Static specification

| Arms | Pattern and goals per level | Outer table width x depth |
| --- | --- | --- |
| 4 | 6 x 12 / 72 | 2.465 x 2.66175 m |
| 6 | 9 x 18 / 162 | 3.0725 x 3.41125 m |
| 8 | 12 x 24 / 288 | 3.68 x 3.3435 m |

Table height is 0.8 m, cube side 60 mm, and grid pitch 71 mm. Use the case's
published bases, workspaces, and camera calibration. Level 1 pockets are part
of the real table; an outer bounding rectangle does not imply continuous support.

The palette is cream `#FFF4DA`, navy `#173F73`, coral `#F03F5B`, and sage `#16A16E`.
The target matrix/reference image is already north-up: row 1 lies toward +Y and
column 1 toward -X. Background-colored cells are goals too. Stock-source labels
identify inventory origin without exclusive arm ownership.

- **Level 1:** square pockets with 70 mm clear openings, 20 mm deep; evaluate the
  full rotated cube footprint and actual seating.
- **Level 2:** 3 mm printed red lines; cubes still need real stable support.
- **Level 3:** no visible grid; the declared pattern and coordinate system remain
  the placement reference.

### Completion and process reporting

| Condition | Bound criterion |
| --- | --- |
| Coverage | One distinct correctly colored cube per cell; every cell simultaneously qualified |
| Release | No cube/robot contact at distance <= 0.2 mm |
| Stability | Linear speed < 0.01 m/s and angular speed < 0.1 rad/s for one continuous simulation second |
| Orientation | Cube-axis alignment error <= 8 degrees, including its 90-degree symmetry equivalents |
| Level 2/3 position | xy center error <= 6 mm (`mosaic-center-6mm-v1`; tasks prepared earlier keep 5 mm); z center error <= 3 mm |
| Level 1 position | Full rotated footprint inside the pocket with 0.3 mm margin; bottom-height error <= 0.8 mm; seating contact <= 0.2 mm |
| Process | Report collisions, drops, recovery, and strict compliance independently from current policy completion |

New policy `terminal_outcome_v2` reports the terminal placement outcome even
when process violations were recorded. It retains a separate strict result;
a violation does not itself stop the agent. Frozen historical Oracle evaluations
keep their stricter original semantics. Cube position, grasp offset, release,
and retraction are separate checks. Later contact can invalidate a completed
placement. End-point IK alone does not verify a complete safe or concurrent path.
The online policy changes the world through authorized actuators and real
contacts, using permitted RGB, proprioception, and action feedback.

### Current preparation and retained family commands

Run `robofrontier bootstrap` to restore the pinned current assets, then use
[unified preparation](../unified-cli.md). The historical delivery check and
review packager (`scripts/mosaic.py` with `robofrontier/suite/mosaic_delivery.py`)
were removed on 2026-11-10 (restore from tag `archive/pre-cleanup-20261110`; see the
[cleanup log](../cleanup-20261110.md)).

That check inspected the R14 policy entries (or, with `--purpose oracle`, the R13
witnesses) without creating a run or calling a model; it was a review export, not a
geometry rebuild or policy launch.

The historical R14 package is
`outputs/policy-packages/mosaic-r14-local-colours-20261027`; its `previews/index.html`
contains nine color diagrams and eighteen real initial screenshots. Colored
cells in the diagrams are the target reference. The R13 review package is
`outputs/policy-packages/mosaic-r13-20261027`.

A new policy run receives the public task, the target image and the current
Mosaic skill, `prompts/skills/mosaic/SKILL.md`. The public task states the grid:
its rules name the 71 mm pitch and 70 mm pockets, and its target gives the same
numbers. The skill states no numbers; it says to work out the pocket clearance
from the task. Earlier releases listed `prompts/archive/tasks/mosaic-r15.md` (R14's
supplement titled R15) as family guidance, which terminal runs do not deliver.
R14 and R13 records keep their own supplements and the archived
`prompts/archive/skills/mosaic-r13/SKILL.md` (both in the tag `archive/pre-cleanup-20261110`). Old prompts and builders remain
provenance for their review packages. Private pairings,
joint witnesses, Oracle truth/actions/recovery experience, and engineering
manifests must not enter a new policy's context.

### Video, source edits, and Factory

Historical videos are under `outputs/oracle/mosaic-continuation-20261026/videos`,
with nine current-at-delivery videos at **30x, 30 fps** from original 60 Hz motion.
Their exact frame maps and full-rate retained intervals live in the original
edit subdirectory. Its historical basename, represented as JSON Unicode escapes,
is `"\u8f68\u8ff9\u526a\u8f91\u65f6\u95f4\u8868"`. Earlier speed variants, full
timelines, and original motion remain retained; this page does not claim they
were rerendered with later physics or colors.

Presentation edits can be reused across backgrounds by reading selected original
states without advancing physics. Move a whole station rigidly in the horizontal
plane while preserving internal geometry and dimensions. Each new policy
recording uses its own source scene, events, and edit table, not an Oracle's
pairings or timing as an assumed replacement. Compressed and Legacy motion
readers share this replay contract; see [Factory](../factory/replay.md).

Each station independently skips its own unneeded intervals and uses its own
playback speed. Update all stations before rendering one 30 fps frame. Current
multi-station presentation loops each station to its own beginning and resets
appearance. Legacy hold-final-state remains readable. Mosaic's 30x affects only
presentation, not physics time or another family's playback speed.

The shared timeline and source-level editing use `station-edit.v2`. Original
edit tables and the historical review of 135 candidates/five slow-motion
segments remain preserved. Classification protects directed movement and semantic
events; missing measured contact-force data cannot establish zero force. See
[Factory design](../factory/README.md). The
Legacy merge handoff (`docs/archive/plans/suite-v2/mosaic-merge-handoff.md`, in the [archive tag](../history.md)) records the
original asset materialization, public-input loading, and shared merge gates;
its pending-state statements do not override current integration evidence.
