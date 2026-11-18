# The tasks

Four task types, each at three team sizes (`small`, `medium`, `large`) and three levels (`l1`
to `l3`): 36 tasks, named `<task type>-<team size>-l<level>`, for example `transport-small-l1`
and `dial-large-l3`. Team size adds arms and work to divide. Level makes the same job physically
or visually harder. In the code and the file names a task is also called a *case*.

The release, [`benchmark/release.json`](../../benchmark/release.json), names every case's
scene, public task and task materials by hash. Each case lives in
`benchmark/<task type>/<case>/`, and `benchmark/<task type>/catalog.json` lists a task type's
cases ([the released files](../../benchmark/README.md)).

| Task type | Cases | What the team does | Level 1 → 3 | Guide |
| --- | --- | --- | --- | --- |
| Transport | `transport-small/medium/large-l1..l3` (4, 8, 12 arms; 12, 24, 36 items) | Deliver each requested cube or cylinder to its place on a destination board | released on the board → both blades in fixed blind slots → the same slots on a spring-supported board | [Transport](transport.md) |
| Mosaic | `mosaic-small/medium/large-l1..l3` (4, 6, 8 arms; 6×12, 9×18, 12×24 = 72, 162, 288 cells) | Build a four-color Tulip pattern, one cube per cell | 70 mm pockets → printed lines → no visible grid | [Mosaic](mosaic.md) |
| Relay | `relay-small/medium/large-l1..l3` (8, 12, 16 arms; 2, 3, 4 timbers) | Carry long timbers to GOAL with at least one airborne handover each | straight beam → arc with a hanging pendant → sprung elbow with a pendant | [Relay](relay.md) |
| Dial | `dial-small/medium/large-l1..l3` (4, 6, 8 dials; 4, 6, 8 arms at Level 1, twice that at Levels 2 and 3) | Find and hold the code, with only a BEST-so-far record as feedback | fixed gear dials → each module held in the air by a second arm → the same with a crank | [Dial](dial.md) |

## What every case shares

- **What the agents see.** The case's public task (`public/task.json`: rules, objective, cameras
  and their mounts, initial geometry, stock, orders or targets, completion rules), the task
  materials in `public/inputs/task/` (the Mosaic target image; Dial previews, camera
  calibration and table geometry) and the task guide (`prompts/guides/<task type>.md`).
  While running they see timestamped RGB images from the cameras they ask for, the state of
  their arms (joint angles, hand pose, gripper opening) and the result of each action. They
  never see the scene file, the evaluator or the state of objects. The
  [ground-truth observation](../benchmark/rules.md#ground-truth-observation) setting replaces
  the images with the simulator's state.
- **Where it stands.** Each task runs at its own desk in one factory hall. The hall and the
  desks of the other 35 tasks appear in the images but stand still and collide with nothing.
- **Physics.** The release physics is written into each scene file, and every action states its
  speed, acceleration or force within the limits of a real Franka Panda ([physics](../benchmark/physics.md)).
  Only robot actuators and real contacts change the world: no resets, welds or state writes.
- **Time.** 24 hours of active time from START; outages, usage-limit pauses and host sleep do
  not count: when the infrastructure pauses a run, the world, the clock and the agents stop
  together. The agents are not told the limit ([time and pauses](../runs/time.md)).
- **Scoring.** The world is scored when the team calls `finish` or at the 24 h cutoff, after
  every arm is stopped and the world has run 1.5 s with the arms still. The score is the
  terminal outcome (`terminal_outcome_v2`); collisions, drops and other process events are
  recorded beside it and do not veto it. Relay's handover rule is part of its completion
  ([terminal outcome](../benchmark/rules.md#terminal-outcome)).
- **Continuing.** A stopped run continues as the same trial, never a new attempt
  ([continuing a stopped run](../runs/continuation.md)).

## Cameras

Every camera is fixed in the world. A task has 14 to 69 of them: two at each arm, four
overviews, and close-ups that depend on the task type.

| Group | Names | What it shows |
| --- | --- | --- |
| At the arms | `A_front`, `A_side`, … | Two per arm: the table in front of the arm, and the arm from its side |
| Overviews | `global`, `global_side`, `global_rear`, `top` | The whole desk from the front and from the side; `global_rear` is `global` turned half a turn about the table centre; `top` looks straight down |
| Transport close-ups | `board_A_close`, …; from Level 2 `plug_close`, `socket_close` | One per target board; one example each of an item's blades and a board's slots |
| Mosaic close-ups | `assembly_01`, … | The build area, in two to four parts |
| Relay close-ups | `payload_close`, `payload_01_close`, …; from Level 2 `payload_01_weight_close`, …; at Level 3 `payload_01_hinge_close`, … | The start area and each timber where it starts; each hanging weight and each hinge where it starts |
| Dial close-ups | `D01_front`, `D01_side`, `D01_high`, `D01_face`, …; `board` | Four per dial: from the front, from the side, from above, and straight down on its face; the BEST display |

| Task type | Small | Medium | Large |
| --- | --- | --- | --- |
| Transport (Level 1 / Levels 2 and 3) | 16 / 18 | 28 / 30 | 40 / 42 |
| Mosaic | 14 | 19 | 24 |
| Relay (Level 1 / Level 2 / Level 3) | 23 / 25 / 27 | 32 / 35 / 38 | 41 / 45 / 49 |
| Dial (Level 1 / Levels 2 and 3) | 29 / 37 | 41 / 53 | 53 / 69 |

A camera does not follow anything: once a timber is carried away, its close-up shows an empty
table. No camera has more than 40% of its image covered by a robot at the start of a task.

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
  (`roboteam/analysis/atomic.py`, `scripts/analysis/run_analysis.py`).
- **Grasp failure rate.** A grasp fails when the gripper closes on a width that does not match
  the object: the grasp command states the expected width, and the gripper stops outside it.
  The rate of a condition is the share of all its grasps that fail.
- **Paired tests.** Every condition runs the same tasks, so two conditions are compared task
  by task with an exact McNemar test, Holm's correction and bootstrap intervals
  (`roboteam/analysis/paired.py`, `scripts/analysis/paired_tests.py`).
