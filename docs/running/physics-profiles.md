# Physics profiles

A harness may set `physics_profile`; `configs/harnesses/policy.json` sets
`realtime-v2`. A run that sets none is untouched, and a run freezes its choice with its
other inputs. A profile changes results compared with
full physics, so results of different profiles are not comparable and one batch must
not mix them. Runs frozen with `realtime-v1` keep it; their results are a separate
physics version from `realtime-v2` runs.

`robofrontier oracle prepare --physics-profile NAME` freezes a profile into an Oracle
harness. Oracle worlds (`suite.oracle.Trial`) apply it the same way policy worlds do.

## `realtime-v2`

`realtime-v1`'s sleep rules, and in every family:

| Setting | Value |
|---|---|
| Friction cone | Elliptic |
| `impratio` | 1 |
| `noslip_tolerance`, `noslip_iterations` | 1e-9, 10 |
| Fingers | Own their contacts: `priority` 1, `condim` 4 |
| Scene parts that are not robots | Friction 1, 0.005, 0.0001 |
| Static parts | `condim` 4 or more |
| Moving parts | `condim` 4 |
| Cylinders and spheres of loose bodies | `condim` 6, rolling friction 0.1 x radius |

Two task values stay because they act in recorded contacts:

- Relay hooks and weight eyes keep friction 0.5 and 0.002, which lets a hook slide into
  its eye.
- Dial module disks and stems keep `condim` 6 and rolling 0.03. A module leans on its
  disk rim, which can roll; at 0.02 or less a pushed module sometimes kept moving
  (up to 22 mm/min), at 0.03 one push in 100 left 0.1 mm/min.

The other task values (Dial parts 0.8, Transport blades 0.45, the Relay weight shaft
0.7) never act: the table and fingers carry 1, and MuJoCo uses the larger value of the
two geoms in a contact.

Why (measured 2026-11-09 on recorded states with the arms held, no sleep):

- With `realtime-v1`'s pyramidal cone, resting objects creep at a constant velocity:
  Dial modules 0.5-12 mm/min after a push, Transport items 2-4 mm/min. With elliptic
  cones and noslip 1e-9 at 10 iterations the largest drift is about 0.01 mm/min (0.02 for
  a knocked Relay beam). Fewer iterations or a looser tolerance leave objects drifting
  (1e-8: 0.09 mm/min, 1e-6: 0.7 mm/min).
- noslip 1e-12 drifts no less, but in Relay a receiving hand then could not slide along a
  held beam on approach and lifted it out of the carriers' grip (3 drops in Relay a16-d3,
  none at 1e-10, 1e-9, 1e-8 or 1e-6).
- `impratio` 10 and 100 stop resting objects as well, but in Oracle runs `impratio` 10
  made Transport about 30% slower and Dial need more attempts.
- A lying Transport cylinder rolls about 35 mm and stops within 1 s. With the scenes'
  0.03 it barely rolled; without rolling friction (`condim` 4) it never stopped.
- About 1% of pushed Mosaic tiles and Transport cubes end on an edge and tip on slowly
  (up to about 2 mm/min) while arms are busy; sleep stops them once the arms are idle. Rolling
  friction on boxes removed this, but it changed how packed Mosaic stock settles and
  lifts, and the Mosaic Oracle then stopped on three a08 cases, so boxes stay at `condim` 4.
- Policy-loop worlds (task monitor and motion recording included) with every arm moving
  step in 4.0-6.1 ms per 20 ms on the hardest case of each family, 3.3-5.0x real time;
  `realtime-v1` takes 4.7-6.7 ms. No step exceeded 20 ms outside 0.1% in Mosaic, the same
  under both profiles.
- Oracle references on all 36 cases (12 minutes each, this profile): no invalid
  physics; 14 of 343 gripper openings stopped short (`Requested opening not reached`:
  Dial 5 of 38, Transport 9 of 153; `realtime-v1` Dial 3 of 18, Transport 7 of 110), an
  outcome the Oracle already treats as known and frees the hand from. Two Relay drops
  were counted: one where `realtime-v1` drops too, and one at a terminal release, where the
  beam is let go just before the goal supports it and then lands.
- Relay Oracle completion is fragile under every profile: in 40-minute runs each profile
  completed one of four cases, and the others stopped at planner dead ends.

## `realtime-v1`

The default before `realtime-v2`.

| Family | Objects sleep | `noslip_tolerance` |
|---|---|---|
| Mosaic | Always | Default |
| Transport | When every arm has been idle for 2 s | 1e-12 |
| Dial | When every arm has been idle for 2 s | 1e-12, and 10 iterations instead of 20 |
| Relay | Same, and only 30 s after the world starts | Default |

- Any action restores full physics before its first step.
- In Dial, fingers take priority in their own contacts with `condim=4`. A grip then
  drops rolling friction, which costs most of a heavy step, while modules keep
  `condim=6` against the table so they still stop after release.
- The extra forward at the end of each 20 ms step skips noslip. This does not change
  states or scores and saves about 2-7% of the time.
- Forces and contact wake a sleeping object on the same step.
- The default `noslip_tolerance` of 1e-6 lets resting objects drift at 1-2 mm per
  simulated minute with no rotation. This is solver error, so a sleeping object does
  not follow it.
- MuJoCo omits contacts between sleeping bodies from `data.contact`. Scoring that asks
  what supports an object uses `Monitor.scene_contacts`, which recomputes them.

The main loop still follows the wall clock, so a world never runs faster than real
time. Rendering reads recorded poses and does not depend on a profile.
