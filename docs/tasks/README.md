# The tasks

Four families, each at three scales (team sizes) and three levels (how hard the mechanism is):
36 cases. The release, [`benchmark/release.json`](../../benchmark/release.json) with its
`release_id`, names every case's scene, public task and family materials by hash; each case lives
in `benchmark/<family>/<case>/`, and each family's cases are listed in
`benchmark/<family>/catalog.json`.

| Family | Cases | What the team does | Level 1 → 3 | Guide |
| --- | --- | --- | --- | --- |
| Transport | `transport-a04/a08/a12-d1..d3` (4, 8, 12 arms; 12, 24, 36 items) | Deliver each requested cube or cylinder to its place on a destination board | released on the board → both blades in fixed blind slots → the same slots on a spring-supported board | [Transport](transport.md) |
| Mosaic | `mosaic-a04-6x12`, `a06-9x18`, `a08-12x24`, `d1..d3` (4, 6, 8 arms; 72, 162, 288 cells) | Build a four-color Tulip pattern, one cube per cell | 70 mm pockets → printed lines → no visible grid | [Mosaic](mosaic.md) |
| Relay | `relay-a08/a12/a16-d1..d3` (8, 12, 16 arms; 2, 3, 4 timbers) | Carry long timbers to GOAL with at least one airborne handover each | straight beam → arc with a hanging pendant → sprung elbow with a pendant | [Relay](relay.md) |
| Dial | `dial-best5-n04/n06/n08-d1..d3` (4, 6, 8 dials; 4, 6, 8 arms at Level 1, twice that at Levels 2 and 3) | Find and hold the code, with only a BEST-so-far record as feedback | fixed gear dials → each module held in the air by a second arm → the same with a crank | [Dial](dial-best5.md) |

## What every case shares

- **What a policy sees.** The case's public task (`public/task.json`: rules, objective, cameras
  and their mounts, initial geometry, stock, orders or targets, completion rules), the family
  materials in `public/inputs/family/` (the Mosaic target image; Dial previews, camera
  calibration and table geometry) and the family Skill (`prompts/skills/<family>/SKILL.md`).
  While running it sees timestamped RGB images from the cameras it asks for, robot
  proprioception and action feedback. It never sees the scene file, the evaluator or live
  object state.
- **Physics.** The release physics is written into each scene file, and every action states its
  speed, acceleration or force within the limits of a real Franka Panda ([physics](../physics.md)).
  Only robot actuators and real contacts change the world: no resets, welds or state writes.
- **Time.** 24 hours of active time from START; outages, usage-limit pauses and host sleep do
  not count: when the infrastructure pauses a run, the world, the clock and the agents stop
  together. The policy is not told the limit ([time](../running/continuation.md#time)).
- **Scoring.** The world is scored when the team calls `finish` or at the 24 h cutoff, after
  every arm is stopped and the world has run 1.5 s with the arms still. The score is the
  terminal outcome (`terminal_outcome_v2`); collisions, drops and other process events are
  recorded beside it and do not veto it. Relay's handover rule is part of its completion
  ([protocol](../protocol.md#terminal-outcome)).
- **Continuing.** A stopped run continues as the same trial, never a new attempt
  ([continuation](../running/continuation.md)).

## Metrics

Agents may retry, so a task that ends correctly can still contain many failures. Beside the
outcome, a run is described by how often its steps and grasps failed and by what it cost in
time and input tokens.

- **Completion.** A task is completed when its final state is correct. Counting the tasks
  completed within 3, 6, 12 and 24 hours shows how fast a condition works.
- **Atomic failure rate.** An atomic step is the smallest unit of progress: in Mosaic one cube
  placed on its cell, in Transport one item delivered to its target or handed to another arm,
  in Relay one arm taking hold of a timber in a handover, in Dial one knob turned to a new
  position. A step fails if any attempt at it goes wrong, even if it is completed later. The
  rate of a run is the share of its steps that fail at least once. Failures are read from the
  records of the robot tool and the simulator, never from the agents' reports
  (`roboteam/analysis/atomic.py`, `scripts/run_analysis.py`).
- **Grasp failure rate.** A grasp fails when the gripper closes on a width that does not match
  the object: the grasp command states the expected width, and the gripper stops outside it.
  The rate of a condition is the share of all its grasps that fail.
- **Paired tests.** Every condition runs the same tasks, so two conditions are compared task
  by task with an exact McNemar test, Holm's correction and bootstrap intervals
  (`roboteam/analysis/paired.py`, `scripts/paired_tests.py`).

The Oracle (the reference condition with ground-truth positions) uses its own copy of each case in
`benchmark/oracle/<case>/`; see the [Oracle](../oracle/README.md).
