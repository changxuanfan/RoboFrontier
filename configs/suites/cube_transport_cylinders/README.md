# Legacy Cube Transport v4: cubes and cylinders

This is the current output collection of the **legacy offline generator**, not
the current 36-case benchmark. Use the [task atlas](../../../docs/tasks/atlas.md)
and unified CLI for current policy runs. The 3-6-arm cases use six-color cubes;
7-12 arms replace v2 spheres with same-color cylinders. Stations A-F initially
hold three red, blue, green, orange, purple or cyan cubes; G-L hold three
cylinders in the same color order. Each station has three goals. Same-color,
same-shape items are interchangeable; see [tasks.md](tasks.md) for complete orders.

Native MuJoCo cylinders serve both visualization and collision: diameter 4 cm,
height 4 cm, mass 50 g, initially upright. Body origin and center of mass are
at the geometric center. Layout, demand assignment/distance proportions,
initial coordinates, slots and cameras preserve the earlier configuration;
only shape requirements change. Ten sizes each have three order seeds that
change orders, not geometry. One exception: at three arms, `line-03` seed-1 and
seed-2 orders are identical, in this collection and in the earlier sphere
collection (`configs/tasks/cube_transport/`), so that size has only two distinct
order sets (its three `references/summary.csv` rows carry the same counts). The generator
reverses the slot order for both seeds at three arms and its per-row shuffle of
three items happens to match for seeds 1 and 2; the frozen files are kept as
generated.

The background is pale blue and table warm wood. Each arm has front/side views,
plus global/global_side/top views, totaling 2N+3 cameras. `startup.md` /
`startup.json` identify stations, neighbors, initial stock and cameras without
a solution. A-L preview labels use fixed bases and remain outside the viewport.

## Published physics and validation

The table is 0.4 m high, the step 0.002 s, and gravity 9.81 m/s². Friction
`[1,0.005,0.0001]`, condim 4, NoSlip 10, Panda actuators and gripper strength
retain the original settings. There is no attraction, body fixation, hidden
cradle or added rolling resistance. A fallen cylinder can roll; a flat base
does not guarantee every pick/place succeeds. These historical settings are
separate from the current suite's [physics release](../../../docs/physics.md).

The original report recorded successful loading, support, spacing, initial
penetration, point IK / endpoint contacts and one-second settling at every
size, with maximum settling displacement about 0.075 mm. This is not swept-path
or multi-arm collision acceptance.

Known-pose local checks used a program and robot IK, without a multimodal agent: a three-arm
A cube, seven-arm G red cylinder and 12-arm L cyan cylinder. All three recorded
passes. Cylinder final XY errors were about 3.08 mm and 0.14 mm, respectively,
with bilateral grip, lift, release and stable upright placement. The original
`validation/object-fixtures.json` and videos record that scope; they are not
full transport, simultaneous-arm or RGB-model evidence. Such ignored historical
assets may require their original archive and are not supplied by the current
36-case policy bundle.

Task completion retains color/shape matching, a distinct item per slot, XY error
at most 2 cm, Z error at most 1 cm, linear speed at most 1 cm/s, table support,
release from robots, and a continuous one-second window with gaps at most 25 ms.
No task orientation criterion was added. The separate local grasp check records
orientation and additionally requires final cylinder tilt below 15 degrees.

Offline references are feasible schedule upper bounds and lower bounds under
capacity/dependency abstractions, not minimum continuous physical time. Phases
are neither tool calls nor simulated seconds. This shape replacement changed
no communication harness or planning skill and launched no model experiment.
The new offline scenes were not connected to the old pipeline action service.

## Files and reproduction

```text
configs/environments/cube_transport_cylinders/<environment>/
  environment.json / scene.xml / assets/
  startup.md / startup.json
configs/tasks/cube_transport_cylinders/<environment>/seed-0.json ... seed-2.json
configs/suites/cube_transport_cylinders/
  README.md / tasks.md / manifest.json
  previews/       Initial images and camera/label metadata
  validation/     Point checks, settling, local grasp results and videos
  references/     Abstract schedules, lower bounds and distance counts
```

With the original offline scene/Panda dependencies available:

```sh
.venv/bin/python -m scripts.generate_cube_transport
.venv/bin/python -m scripts.verify_transport_objects --record
.venv/bin/python -m unittest tests.test_cube_transport -v
.venv/bin/mjpython -m scripts.view_cube_transport --count 7
```

The viewer applies the saved `initial` keyframe and runs physics, with no
keyboard control or automatic video recording. On non-macOS systems use the
same environment's Python in place of `mjpython`. Partial generation overwrites
this collection's summary/manifest subset; generate every size for a full
publication. Raw cameras are 1280×900 and bordered previews 1536×1152; calibration
and viewport offsets are in `startup.json`.

The earlier sphere collection keeps its scenes in `configs/environments/cube_transport/`
and its order seeds in `configs/tasks/cube_transport/`; the tests check that this
collection keeps those orders. The cones collection, the two collections' catalogs
and their archived generator sources were removed on 2026-11-03 and are kept at the
Git tag `archive/pre-prune-20261103`. Do not overwrite historical results.

## Historical full Oracle program reference, 6-12 arms

The seed-0 reference recorded full-scene passes for seven sizes, from 18/18 to
36/36 goals; all cylinders finished nearly upright. Six arms used the original
motion timing. After default-timing losses/grasp failures, 7-12 arms passed with
slower timing. Mass, friction, actuator gains and force limits were unchanged;
failed attempts were retained. This is neither a common-speed scale comparison
nor a model score.

The original report is
`runs/program-transport-cylinders-v4-20261021/report.md`, an ignored data-root
artifact rather than a guaranteed clone-time file. Its videos replay actual
trajectories at 12× speed, with encoding and scene/trajectory provenance checked.
Other order seeds had not been rerun. These are historical recorded results,
not a new physical qualification of this integration.
