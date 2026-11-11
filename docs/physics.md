# Physics and robot limits

Every released scene carries its physics in its own `scene.xml`, and every arm and hand action
states its speed, acceleration or force within the limits of a real Franka Panda. Nothing about
contacts or motion is configured at run time. This page lists the values, where they come from,
how the simulation differs from the real robot, and the current validation status.

## Contacts and solver

`scripts/build_release.py physics` writes these values into all 36 released scenes;
`python -m scripts.build_release check` confirms that every scene carries them.

| Setting | Value | Why |
| --- | --- | --- |
| Time step, integrator, solver | 2 ms, `implicitfast`, Newton with 100 iterations | |
| Friction cone | elliptic, impratio 1 | Pushed or released objects stop and stay still |
| NoSlip | 10 iterations, tolerance 1e-9 | Removes the slow drift of resting objects; at 1e-12 a receiving hand could not slide along a held timber |
| Contact stiffness, every collision geom | solref `0.004 1`, solimp `0.95 0.99 0.001 0.5 2` | The stiffest stable at a 2 ms step (time constant twice the step, critical damping); rigid parts sink in by micrometres. One value for the whole scene |
| Sliding friction | finger collision geoms (the 5 pads and the finger body) 0.8; every other surface 0.4 | Rubber pads; wood, plastic and metal on each other. The finger collision geoms have priority 1, so a finger contact uses 0.8; any other contact uses the larger of two 0.4 values |
| Torsional, rolling friction | 0.005 m, 0.0001 m | Small values |
| Round loose parts (cylinders, spheres) | condim 6, rolling 0.1 × radius | They roll a little and stop |
| Dial module disk and stem | condim 6, rolling 0.03 m | A disk leans on its rim and needs it to stop |
| Hand actuator range | ±280 N | The tendon passes half to each finger: 140 N per finger |

What a scene file cannot hold is in `robofrontier/physics/profile.py`: Mosaic objects may always
sleep (its large scenes would otherwise run below real time); in the other families objects sleep
only after every arm has been idle for 2 s, and any action wakes them; Relay settles 30 s before
anything may sleep, so its hanging weights come to rest. Every scene starts at rest under this
physics (`build_release.py settle`). Each run writes `private/outputs/effective-physics.json`,
the options and contact parameters it actually ran with and their hash. A full contact or
constraint buffer or a bad inertia fails the step (`robofrontier/physics/health.py`).

The Oracle keeps the physics its recordings were made with, in its own copy of each case under
`benchmark/oracle/` ([Oracle](oracle/README.md)).

## Robot limits

`robofrontier/physics/franka_limits.py` holds the limits, from the Panda datasheet (2018-05)
and libfranka 0.9.2 `include/franka/rate_limiting.h` (its base values, without the safety
margin). An action that omits any of its rates is refused; there are no defaults. Every value
must be above 0.001 and at most its limit.

| Parameter | Limit |
| --- | --- |
| `speed_m_s`, `acceleration_m_s2` (TCP) | 2.0 m/s, 13 m/s² |
| `angular_speed_rad_s`, `angular_acceleration_rad_s2` (hand turn) | 2.5 rad/s, 25 rad/s² |
| `joint_speed_rad_s` | 2.175 rad/s (joints 1–4), 2.61 rad/s (joints 5–7) |
| `joint_acceleration_rad_s2` | 15, 7.5, 10, 12.5, 15, 20, 20 rad/s² |
| Hand `speed_m_s` | 0.1 m/s total aperture (50 mm/s per finger) |
| Grasp `force_n` | 140 N per finger, as in libfranka; a real hand holds 70 N continuously and more only briefly |

Cartesian moves follow a straight TCP line and the shortest hand turn with trapezoid speed
profiles; every joint stays within its own speed and acceleration, so a long or fast move may be
slower than requested (vertical moves top out near 0.85 m/s, where joint 4 reaches its limit).
Joint moves finish all joints together.

## How the simulation differs from the robot

- Contacts are soft constraints with a 4 ms time constant, not elastic solids. Finger pads do
  not deform; a grasp touches through 5 pad boxes per finger.
- There is no motor heating: 140 N per finger can be held indefinitely.
- No contact force sensor is simulated; `measured_grasp_force_n` is always null.
- A position close (`gripper` with `state: close`) that stops at an object then holds its
  aperture without squeezing, as a real hand does after a blocked move; only a grasp holds an
  object.
- NoSlip drags a held object slightly during fast hand turns (below).

## Validation

`scripts/validate_physics.py` runs each check in the policy runtime's own world, controller and
step settings, and writes `runs/engineering/validate-physics/<time>.json`;
`tests/physics/test_validation.py` runs a fast part of it. Pass criteria: a held object slips
less than 2 mm, ends less than 1° turned in the hand and never turns more than 2°; a resting
object drifts less than 0.2 mm after its first 5 s; a placed cube settles within 1 s; a Dial knob
follows the hand within 5°; a 20 ms control step of each family's largest case computes in less than 20 ms.

The current run (`runs/engineering/validate-physics/20261111-120111.json`) passes 56 of 77 checks:

| Group | Checks | Result |
| --- | --- | --- |
| Every case at rest 60 s | 36 | All pass: no drift after 5 s; Relay weights stay hung |
| Grasped cube, cube and cylinder held still 60 s | 3 | All pass: no slip, no turn |
| Joint 1 turns at 0.5, 1.0 and 2.175 rad/s while holding | 9 | 7 pass (slip 0.3–1.6 mm). Fail: a cube at 2.175 rad/s slips 2.1 mm; a cylinder at 1.0 rad/s ends 1.9° turned |
| Wrist turns (joint 7) at 0.5, 1.0 and 2.61 rad/s while holding | 9 | **All fail**: the object turns 3.8–6.3° in the hand during the turn |
| Cartesian carries at 0.3, 1.0 and 2.0 m/s with a 90° turn | 9 | 1 passes. Cubes slip 2.1–2.5 mm; the cylinder turns up to 3.1° |
| Pick up, set down and release a Transport cube | 1 | Pass: settles at once, no drift |
| Push a cube 6 cm along the table | 1 | Pass: stops with the push |
| Two arms driven into each other at full speed | 1 | Pass: the simulation stays valid |
| Airborne two-arm Relay timber handover at 40 N and 70 N | 2 | 40 N passes (receivers move the timber 0.18 mm when closing, it drops 0.5 mm at release). 70 N fails narrowly: one sender's carry slip is 2.02 mm |
| Dial knob turned 90° at 0.3 and 1.0 rad/s | 2 | 0.3 rad/s passes (0.45° behind the hand); 1.0 rad/s fails (6.5° behind) |
| Step time of each family's largest case | 4 | All pass: 1.5–3.9 ms of computation per 20 ms control step while arms move |

The wrist-turn, carry and Dial failures share one cause: the NoSlip pass drags a held object at a
steady rate once the hand turns faster than about 0.5 rad/s. Without NoSlip the turn stays below
1.7°, but resting objects then creep up to 2.6 mm a minute; impratio, impedance, condim and NoSlip
iterations do not change it, and a 1 ms step halves it. The robot limits stay at the real
Franka values. Whether to accept these failures is an open decision before the release is frozen.

## Freezing the release

`benchmark/release.json` names every case file by hash and carries `release_id`, a hash of the
whole release. `frozen` is empty until the release is frozen, after this validation and the
platform checks pass; after that neither physics nor scenes change.
