# Transport: current specification and evidence

The current geometry is the **R14 half-opening** family, with nine cases in
`benchmark/transport/catalog.json`. Specification and acceptance metadata
are in `benchmark/transport/half-opening-r14.json`; policy guidance is
`prompts/archive/tasks/transport.md`. New experiments use the released entries selected
by `benchmark/release.json` and the [unified CLI](../unified-cli.md).
The current policy asset lock also identifies the
[rolling-friction revision](#rolling-friction-003-engineering-candidate-2026-10-29);
R14 geometry alone does not prove equality of all physical parameters.

## Geometry and objectives

| Property | Four arms | Eight arms | Twelve arms |
| --- | --- | --- | --- |
| Targets per level | 12 | 24 | 36 |
| Outer table side | 1.938 m | 2.720 m | 3.536 m |
| Table height | 0.8 m | 0.8 m | 0.8 m |
| Central opening | Solid tabletop | 0.476 x 0.476 m | 0.833 x 0.833 m |

Real collision boxes define tabletop support; the central opening is unsupported.
Public task inputs describe supports, table height, workspaces, robot bases,
static camera mounts, stock identities, orders, mechanisms, and completion rules.
Camera mounts specify world or body-local frames. A moving camera's local mount
coordinates are not its current world pose.

Materials are 60 mm cubes or cylinders with 60 mm diameter and height. Each white
board is 143 x 396 mm, target-center pitch is 120 mm, and an 84 mm color/shape cue
identifies each target. Paired metal blades are 2.5 x 12 x 24 mm, spaced 24 mm
center-to-center. Their blind sockets have 4.5 x 15 mm openings and 26 mm depth;
the board is 32 mm thick. These sockets are distinct from the central table hole.

- **Level 1:** place the correctly identified stock object entirely inside its
  permitted target footprint, upright, released, and stable.
- **Level 2:** use the fixed white board; fully insert both blades into the real
  matching blind sockets, seat the object, release it, and leave it stable.
- **Level 3:** use the same sockets on a passive z/roll/pitch spring board. Judge
  insertion and seating in the board's current local frame.

Each goal requires one continuous simulation second of qualification. Numeric
position, insertion, orientation, and support tolerances come from the bound
family acceptance settings and frozen evaluator. Do not substitute Relay's
50 mm goal-region tolerance for Transport's placement/socket requirements.

Stock/board letters identify inventory and orders, not permanent robot ownership.
The policy chooses airborne handovers, stable tabletop staging, waiting, and
parallel work. Establish receiving support before release and protect completed
placements. End-point IK alone does not establish collision-free transit.

New policy runs use `terminal_outcome_v2`: completion is reported independently
of collisions, drops, and other process events. The stricter process-compliant
result remains separately available. A recorded violation does not by itself
stop the policy or prevent it from attempting recovery. Frozen historical
Oracle evaluators retain their original criteria; their reports are not rewritten.

## Historical evidence and current qualification

The original nine R13 independent physical witnesses passed 216/216 placements:
three frozen-program and six engineering-assisted runs. Their reports, failures,
timings, executors, and full 60 Hz motion remain preserved under the index
`benchmark/transport/r13-qualified.json`.

The original R14 release compiled the changed collision geometry and checked
that it differed only in the table openings. In six opening-bearing recordings,
1,998,263 source states did not contact newly added tabletop material. That
geometric compatibility check advanced no physics and was not a new full R14
execution. Later rolling-friction assets and commissioning attempts have their
own fingerprints and evidence. Historical qualification must not be inherited
by a changed scene, controller, or contact candidate. Current integration
acceptance and outstanding full-task gates are in the
[integration ledger](../archive/unified-main.md) and [Oracle guide](../oracle.md).

## Restore current assets or build a review package

For a new checkout, run `robofrontier bootstrap`. It restores the pinned released
assets without requiring historical Oracle folders. Policy preparation also
verifies needed assets automatically; no model is called during preparation.

The following retained builder is for historical family reconstruction/review,
not the normal fresh-clone bootstrap:

```sh
PYTHONPATH=. .venv/bin/python scripts/build_transport_policy_package.py --assets-only
PYTHONPATH=. .venv/bin/python scripts/build_transport_policy_package.py \
  --output outputs/transport-r14-review-001 --no-previews
```

It requires its bound source assets, copies them with independent inodes, and
refuses drifted existing assets. A full review build uses a new output directory
and can generate initial previews; `--no-previews` omits them. It creates no
policy roles, credentials, sessions, or physical run. The retained
`build_frontier_v2.py` does not select this R14 family; use the current registry
for new policy runs and this family-specific builder for historical review.

## Source edits and Factory replay

`robofrontier/suite/transport_motion_edit.py` consumes original states, actions,
and process events; `transport_motion_signals.py` provides motion signals and
optional visual checks. `scripts/edit_transport_recordings.py` writes
`robofrontier.transport-source-edit.v1` edits without changing the original stream.
Current readers also accept compressed motion; see [evidence storage](../evidence-storage.md).

Retain a whole-table interval whenever an arm, gripper, or object has meaningful
motion. Editorial classification removes idle intervals and repetitive motion
without progress, including large long-period oscillation, while preserving slow
directed motion, continuous rotation, actual falling transitions, action
boundaries, and progress. It uses source states/events rather than requiring a
prior render. Editorial interval removal is separate from lossless evidence
compression: the full original timeline remains available.

The family presentation is **20x at 30 fps**. Each station has an independent
active-time cursor through `TransportEdit.at_video_time(T, speed=20)`. Update all
stations before drawing one Factory frame. Current multi-station presentation
loops each station independently and resets its appearance. The Legacy
single-station player can still hold its final state. Rigid station translation
and rotation about the vertical axis are allowed; internal geometry and scale
must remain source-compatible.

R14 already contains the half-size central opening: its source-relative opening
scale is 1. Historical R13 recordings used a 0.5 opening display scale. The
renderer distinguishes those sources instead of halving an R14 opening again.
Use each recording's frozen geometry and contact parameters, not a replacement
scene with a familiar family name. See the [Factory workflow](../factory.md).

## Preserved delivery locations

These are historical paths relative to their original data root, not files
promised by a fresh Git clone. Historical worktrees sometimes linked `runs/` and
`outputs/` to another checkout; new execution does not require those symlinks.

| Artifact | Historical path |
| --- | --- |
| Public family release and audit | `outputs/oracle/transport-continuation-20261026/transport-policy-r14-release/` |
| Source-native edits and generator snapshot | `outputs/oracle/transport-continuation-20261026/transport-source-edits-v2/` |
| Original physical witnesses and all attempts | `runs/oracle/transport-continuation-20261026/full/` |
| Eighteen 20x front/rear videos | `outputs/oracle/transport-continuation-20261026/motion-only-20x/` |

The historical nine-front-video shortcut is under the same continuation output;
its original basename, expressed as a JSON Unicode escape for an English-only
source document, is `"\u5168\u90e8\u4e5d\u9879\u4efb\u52a1\u89c6\u9891"`.
Previously delivered videos retain their reviewed edits, `motion-timelines/`,
and `motion-only-nine/audit-v4/`. The source-native edit retained 1,096,132 states
and skipped 1,035,753 for presentation, projecting about 15 minutes 14 seconds
across nine front views at 20x/30 fps. That calculation did not itself rerender
the videos. One-off builders and prior plans remain historical provenance.

## Rolling-friction 0.03 engineering candidate (2026-10-29)

This policy physics revision sets Transport cylinder collision geoms to
`condim=6`, rolling friction `0.03`, and Dial module disk/stem collision geoms
to `condim=6`, rolling friction `0.03`. Dial modules without a stem modify the
disk only. Table friction, Mosaic blocks, Relay objects and other contact
parameters are unchanged. This changes the physical environment: identify runs
by their frozen scene and task-release hashes. Do not combine scores with
previous physical revisions as if they were the same benchmark. Historical
Oracle success and prior compiled-physics parity are not inherited.

Earlier in-memory engineering probes on `transport-a12-d2` H_item3 found that
0.03 reduced post-release movement relative to 0.01 in some force/direction
tests; 0.03 did not prevent large movements in all tests. One side-cylinder
pickup and lift passed. In `dial-best5-n04-d2`, one 0.03 module force probe
and a lift/knob-capture probe were favorable, and a hinge spring-return probe
still worked. These are limited, case-specific probes, not complete model runs.
Transport insertion, handovers, full Dial turns, other forces and long-duration
cross-platform behavior remain unqualified. This release is for further
engineering tests; it does not establish a formally validated benchmark.

For an independent finite passive Transport check, prepare fresh jobs and run:

```sh
python -m scripts.tasks prepare-batch --output runs/engineering/transport-stability --families transport
python -m scripts.check_transport_cylinder_stability --batch runs/engineering/transport-stability/batch.json
```

This check uses simulation time, starts no model, and does not execute a task.
Do not modify existing frozen experiment inputs; prepare a fresh batch.
