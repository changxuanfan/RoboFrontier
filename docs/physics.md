# Physics and robot limits

Every released scene carries its physics in its own `scene.xml`, and every arm and hand
action states its speed, acceleration or force within the limits of a real Franka Panda.
Nothing about contacts or motion is configured at run time. This page lists the values,
where they come from, how the simulation differs from the real robot, and how the release
was checked.

## Contacts and solver

`scripts/build_release.py physics` wrote these values into all 36 scenes. The compiled
models equal the earlier scenes with these values applied, array for array.

| Setting | Value | Why |
| --- | --- | --- |
| Time step, integrator, solver | 2 ms, `implicitfast`, Newton with 100 iterations | Unchanged from the scenes as built |
| Friction cone | elliptic, impratio 1 | Pushed or released objects stop and stay still |
| NoSlip | 10 iterations, tolerance 1e-9 | Removes the slow drift of resting objects; at 1e-12 a receiving hand could not slide along a held timber |
| Contact stiffness, every collision geom | solref `0.004 1`, solimp `0.95 0.99 0.001 0.5 2` | The stiffest stable at a 2 ms step; rigid parts sink in by micrometres. One value for the whole scene |
| Sliding friction | finger collision geoms (the 5 pads and the finger body) 0.8; every other surface 0.4 | Rubber pads; wood, plastic and metal on each other. The finger collision geoms have priority 1, so a finger contact uses 0.8; any other contact uses the larger of two 0.4 values |
| Torsional, rolling friction | 0.005 m, 0.0001 m | Small values, as before |
| Round loose parts (cylinders, spheres) | condim 6, rolling 0.1 × radius | They roll a little and stop |
| Dial module disk and stem | condim 6, rolling 0.03 m | A disk leans on its rim and needs it to stop |
| Hand actuator range | ±280 N | Passes 140 N to each finger |

What a scene file cannot hold stays in `robofrontier/physics/profile.py`: Mosaic objects
may always sleep (its large scenes would otherwise run below real time); in the other
families objects sleep only after every arm has been idle for 2 s; Relay settles 30 s
before anything may sleep. Each run writes `private/outputs/effective-physics.json`, the
options and contact parameters it actually ran with and their hash. A full contact or
constraint buffer or a bad inertia fails the step (`physics/health.py`).

The Oracle keeps the physics its recordings were made with, in its own copy of each case
under `benchmark/oracle/` ([Oracle](oracle/README.md)).

## Robot limits

`robofrontier/physics/franka_limits.py` holds the limits, from the Panda datasheet
(2018-05) and libfranka 0.9.2 `rate_limiting.h`. An action that omits any of its rates is
refused; there are no defaults. Every value must lie above 0.001.

| Parameter | Limit |
| --- | --- |
| `speed_m_s`, `acceleration_m_s2` (TCP) | 2.0 m/s, 13 m/s² |
| `angular_speed_rad_s`, `angular_acceleration_rad_s2` (hand turn) | 2.5 rad/s, 25 rad/s² |
| `joint_speed_rad_s` | 2.175 rad/s (joints 1–4), 2.61 rad/s (joints 5–7) |
| `joint_acceleration_rad_s2` | 15, 7.5, 10, 12.5, 15, 20, 20 rad/s² |
| Hand `speed_m_s` | 0.1 m/s total aperture (50 mm/s per finger) |
| Grasp `force_n` | 140 N per finger, as in libfranka; a real hand holds 70 N continuously and more only briefly |

Cartesian moves follow a straight TCP line and the shortest hand turn with trapezoid speed
profiles; every joint stays within its own speed and acceleration, so a long or fast move
may be slower than requested (vertical moves top out near 0.85 m/s, where joint 4 reaches
its limit). Joint moves finish all joints together. The controller of earlier releases,
whatever speed was asked, moved the TCP at about 0.058 m/s at most; results before this
release are not comparable.

## How the simulation differs from the robot

- Contacts are soft constraints with a 4 ms time constant, not elastic solids. Finger pads
  do not deform; a grasp touches through 5 pad boxes per finger.
- There is no motor heating: 140 N per finger can be held indefinitely.
- No contact force sensor is simulated; `measured_grasp_force_n` is always null.
- A position close (`gripper` with `state: close`) that stops at an object then holds its
  aperture without squeezing, as a real hand does after a blocked move; only a grasp holds
  an object.
- NoSlip drags a held object slightly during fast wrist turns (below).

## Validation

`scripts/validate_physics.py` runs each check in the policy runtime's own world and
controller; `tests/physics/test_validation.py` runs a fast part of it. Results of the first
full run (2026-11-11):

| Check | Result |
| --- | --- |
| All 36 cases at rest 60 s | Pass: no drift after 5 s; Relay weights stay hung. The six Relay d2/d3 scenes now start at rest (they moved 4–9 mm in their first seconds; `build_release.py settle`) |
| A grasped cube or cylinder held still 60 s | Pass: no slip, no turn |
| Joint 1 turns at 0.5 and 1.0 rad/s while holding | Pass (slip 0.5–1.1 mm) |
| Pick up, set down and release a Transport cube | Pass: settles at once, no drift |
| Push a cube 6 cm along the table | Pass: stops with the push |
| Two arms driven into each other at full speed | Pass: the simulation stays valid |
| Airborne two-arm Relay timber handover | Pass at 40 N: receivers move the timber 0.08–0.18 mm when closing, it drops 0.5 mm at release, slip about 2 mm |
| Dial knob turned 90° at 0.3 rad/s | Pass: 0.45° behind the hand |
| Step time of each family's largest case | Pass: 1.3–3.7 ms per 20 ms step |
| Wrist turns (joint 7) at 0.5–2.6 rad/s while holding | **Fail**: the object turns 3.7–6.3° in the hand, about 0.1–0.2° at 0.3 rad/s |
| Cartesian carries at 0.3–2 m/s with a 90° turn | **Fail** (narrowly): 2.1–2.5 mm slip, up to 1.5° left over (limits 2 mm, 1°) |
| Dial knob turned at 1.0 rad/s | **Fail**: 6.5° behind the hand |

The failures share one cause: the NoSlip pass drags a held object at a steady rate once the
hand turns faster than about 0.5 rad/s. Without NoSlip the turn stays below 1.7°, but resting
objects then creep up to 2.6 mm a minute; impratio, impedance, condim and NoSlip iterations
change nothing, and a 1 ms step halves it. The limits were not lowered for it; this is an
open decision before the release is frozen.

## Freezing the release

`benchmark/release.json` names every case file by hash and carries `release_id`, a hash of
the whole release. `frozen` stays empty until the release is frozen, after this validation
and the platform checks pass; after that neither physics nor scenes change.
