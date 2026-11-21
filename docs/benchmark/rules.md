# Rules of a run

The rules every run follows between its start and its score: what the agents are given, what
they see, how robot requests are identified, and what decides completion. Each prepared run
freezes its inputs, source and the names of the rules it runs under (`run_protocol` in its
private task), so read an old run by what it recorded. What differs between the harnesses is
in the [harness guides](../harness/README.md). Time is in [time and pauses](../runs/time.md),
and stopped runs in [continuing a stopped run](../runs/continuation.md).

Words used here: the *policy* is the team of agents being measured, and a *role* is one of its
agents. The *host* is the process that runs the roles' sessions for one run. The *world owner*
is the process that steps the physics.

## Start: system prompt, start message, START

- **System prompt.** `private/inputs/bootstrap/system.md` is the policy role statement followed
  by the run's `public/inputs/rules.md`. Claude Code receives it as `--system-prompt`, Codex as
  each thread's `baseInstructions`, delegates included. Both harnesses get the same bytes, and a
  compacted conversation keeps it whole.
- **Start message.** Each initial role's first message (`private/inputs/bootstrap/<role>.md`)
  carries its other public text inputs in full: `task.json`, `roles.json`, its role file, the
  collaboration guide, its tool, motion-check, communication and adaptive references as the system needs, and
  the task materials, each under its absolute path. The files stay readable on disk. The message
  is at most 400,000 bytes. Only the last line differs between harnesses (how to view images).
- **START.** The host prepares the world and gives every initial role its own session. The
  runtime then records one START, and the host sends each role its start message. The frozen
  `startup_protocol` names this: `direct_controller` for the `single-agent` and `adaptive`
  systems, `direct_team` for `hierarchical` and `decentralized`.
  Reading, observing and planning count as task time. A failed or uncertain first delivery is an
  engineering failure for review, never retried in the same world or reported as a task result.
- **`ready`** is an optional query of the role's robots, run limits and static `robot_facts`. It
  does not unlock START.
- **Time.** The public `task.json` states no time limit (`run_protocol.total_wall_limit_s` and
  `run_protocol.clock` are only in the private task), and the rules ask policies to plan as if
  time were unlimited. The host gives each run 24 hours of active time (`active_time_v1`) and
  scores it at that cutoff ([how it is counted](../runs/time.md)).

`public/inputs/rules.md` is the same text in both harnesses. Each harness still passes the
robot tool to its model in its own way, so the harness, its CLI version and the model together
are the experimental condition: equal rules do not make model context or tool behavior equal.

## Observation images

`render.observation_profile = "jpeg_1280x800_q90"` (the default) makes every observation camera
produce a 1280 × 800 JPEG at quality 90. `jpeg_128x80_q95` is the low-resolution condition: each
image is rendered at 1280 × 800 and every 10 × 10 block of pixels is averaged into one before
encoding at quality 95. The run's settings freeze it as `observation_image_profile`, and the
public task states the format and resolution. When a published camera calibration names an image
size, the run gets a copy at the observation resolution and the published file stays as it is.
Video recording has its own resolution.

A released task runs at its desk in the factory hall (`roboteam/sim/hall/world.py`). The hall
and the other 35 desks, each at its task's start, stand still around the desk and take no part
in collisions, so the motion is the same with and without them. Images are drawn from a copy of
the world's model (`roboteam/sim/render/look.py`): colours and textures are converted to linear
light, the hall's key light casts hard shadows, and each image gets one display transform. An
image draws only the hall shapes that can show in it or shade it. The result is the image that
drawing all of them gives: in some views a handful of pixels differ by one level out of 255,
from antialiasing. The arms on the other desks are drawn from simplified meshes. An image takes
10 to 40 ms on a laptop GPU. The live view and the recording are drawn the same way.

## Ground-truth observation

`policy.observation = "ground_truth"` (or `--observation ground_truth`) prepares runs whose roles
get the simulator's state instead of camera images. Everything else is an ordinary run: the same
robot tool, the same actions and timing, the same real-time world, the same scoring. Any harness,
model and system may select it. The default is `images`. The paper's Oracle condition is Codex
with the model entry `sol` and the single-agent system:

```sh
.venv/bin/roboteam prepare --output runs/batches/<batch> --harness codex --model sol \
  --system single-agent --observation ground_truth
```

What a role gets:

- **`state`**, a robot operation that only reads. It returns the simulation time; for every task
  object its position, quaternion (wxyz), linear and angular velocity; every joint of the task
  scene as `[position, velocity]` by name (arms, fingers, dial hinges, board springs; a free or
  ball joint gives its full position and velocity vectors); and what the evaluator currently
  tracks: progress, goals met, violations and completion (`{"started": false}` before START).
- **`public/inputs/ground-truth/`**: `task.json`, the task as the evaluator has it (objects, goals,
  exact targets, mechanism, completion rule), and `scene.xml` with its `assets/`, the task's
  MuJoCo scene. The factory hall is not included. The public `task.json` names the folder as
  `ground_truth`.
- **A simulator**: the `mujoco` variant of the [policy Python
  environment](../hosts/policy-environment.md#the-mujoco-variant), the ordinary environment plus
  the `mujoco` package at the benchmark's own version.

What it does not get:

- **No camera images.** `observe` returns robot feedback only. No image is rendered or written,
  for an action's completion either. A `cameras` or `views` selection and `public_image` are
  refused, and the public task names no camera, calibration or reference image. The video
  recording and the live view are for people and stay as they are.
- **No way to change the world except robot actions.** `state` never writes. A role's own
  simulations run on its own copy.
- **Nothing private.** The run's `private/` folder, the wall limit and the benchmark's code stay
  closed, as in every run.

**The Dial code stays private in every run.** The code lives in the private part of
`benchmark/release.json` and reaches a run only as `private/inputs/suite-code.json`. The
ground-truth task file holds no code. For Dial, `state` gives the dial angles (as joint state)
and what the display shows an images role: the BEST value and the READY status, with the solved
flag, the count of valid trials, each module's support and clearance, and the violations. It
never gives the code or which dial is right.

`ground_truth` with `tools = "robot_only"` is refused: the role needs its code tools. A
ground_truth run freezes `"observation": "ground_truth"` in `private/inputs/run.json`. Codex
keeps a separate preflight receipt, `<model>.ground_truth/`. The prompt passages that differ are
marked in the templates with `<!-- observation:images -->` and `<!-- observation:ground_truth
-->` (`roboteam/tasks/observation_mode.py`). Tests:
`tests/runtime/tools/test_ground_truth.py`,
`tests/launch/test_observation_mode_configuration.py` and
`tests/runtime/sandbox/test_policy_env_variant.py`.

## Robot requests and IDs

For a new robot request on either harness, omit the outer `call_id`; the host generates one and
returns it. To query an earlier physical action, send a new request
`{"op":"job","data":{"call_id":"ACTION_ID"}}` with no outer `call_id`: the query gets its own ID
and `data.call_id` names the action. To retry a request whose result is uncertain, resend it under
its original outer ID with exactly the same operation and data. Never replay an uncertain physical
action under a new ID. How the Claude Code host matches these IDs to the CLI's own tool calls is in
[new requests, queries and delegation](../harness/README.md#new-requests-queries-and-delegation).

A blocking action that is still running after 600 s returns as pending under its original ID (a
harness may give up on a tool call sooner); the action keeps running and `job` follows it.

## Robot tool error feedback

Two typed errors tell a conflict from an unknown outcome. Neither creates an ID, replays a
command, restarts a world or extends the deadline.

| Error | `request_status` | Meaning |
| --- | --- | --- |
| `CALL_ID_CONFLICT` | `rejected` (`original_call_status: unknown`) | Only the new request with a reused ID was rejected. The request first sent under that ID may have run or may still run: check own `pending` records and, for a physical action, `job` with the original ID. A new ID is right only for an intentionally new request after that. Other roles' requests are not disclosed |
| `TRANSPORT_UNCERTAIN` | `unknown` | A timeout, lost reply, malformed output, unknown error code or mismatched ID. It does not show that the operation failed to run; the durable request stays available under its original ID |

The client detects a local conflict before submitting a changed request. The server returns
HTTP 409 JSON for a conflict in its task-wide call table; the client checks the schema and ID,
records the rejection separately and does not list it as unresolved. Codex rebuilds an allowlisted
response from the failed client's JSON, so raw stderr and command lines never reach the policy;
the Claude MCP bridge uses the same typed exception and payloads.

Offline checks (no model calls, no physics):

```sh
PYTHONPATH=tests:tests/helpers .venv/bin/python -m unittest runtime.tools.test_tool_errors \
  runtime.tools.test_pipeline_client runtime.world.test_runtime_store harness.claude.test_claude_tool_errors
node --test tests/harness/codex/test_tool_errors.js
```

## IK failure detail

Inverse kinematics (IK) finds the joint angles that put the hand at a requested pose. The hand's
reference point is the tool centre point (TCP). A `move`, `check_motion` candidate or
`action_batch` member whose pose has no verified IK solution is rejected before execution with
its `error` and an `ik_detail`:

| Field | Meaning |
| --- | --- |
| `closest_found_tcp_m`, `position_error_m`, `rotation_error_rad` | The closest TCP pose the solver found and how far it is from the request |
| `horizontal_distance_from_base_m` | The target's and that pose's horizontal distance from the robot base |
| `orientation` | The orientation used: the requested `quaternion_wxyz`, or the current one kept |
| `home_orientation` | Whether the same position solves with the robot's home hand orientation, and that quaternion |

The solver searches locally from the current joint references, so these are solver facts, not a
proof of the reach limit or a suggested target. No object state is used. The extra
home-orientation solve runs only after a rejection (`roboteam/sim/robot_control.py`).

## Terminal outcome

A run is scored by the state of the world at its end (`terminal_outcome_v2` in the frozen
`run_protocol`). The task's final conditions decide completion:

- **Transport and Mosaic:** the geometric, release, stability and assignment predicates of each
  goal.
- **Relay:** every timber has had a qualified airborne handover (`relay-airborne-handover-v1`)
  and is released with at least 70 percent of its centreline above the GOAL outline
  (`relay-timber-goal-70pct-v1`).
- **Dial:** success latches when a simultaneous valid correct input unlocks the device; later dial
  changes do not undo it.

Dropped flags and recorded violations do not veto completion. Reports keep
`strict_task_success`, process compliance and violations; Relay reports also keep
`process_goals_met`, `process_completed_payloads`, drops and handover records. A violation
entry is deduplicated by kind and key, not a count of separate collisions. Failed and unresolved
actions are reported apart from process violations. An interrupted or unresolved run is never
promoted to success, and an accepted `finish` is not a success verdict.

### Contact and drop metrics

`robot_contact_episodes` reports sampled contact episodes for inter-robot and self-robot body
pairs, using the collision thresholds (penetration above 0.2 mm and 1 mm). Contact gaps of at
most 50 ms of simulation time are joined. The report gives per-pair counts and the largest
sampling gap; it counts body-pair episodes, not physical impacts. None of these counts changes
terminal success.

Relay `drops` comes from its airborne, support and contact state machine and is not a complete
count of physical drops. Transport, Mosaic and Dial have no validated general drop counter: an
absent metric means not measured, not zero. Dial's red-operation support violations are detected
only before unlock.

## Fixed runtime rules

Some rules of a run are numbers in `roboteam/runtime/run/defaults.json`. No setting of
`roboteam.toml` and no command option changes them, and every prepared run freezes them in
`private/inputs/run.json`. Changing the file changes what is measured.

| Rule | Value | Field |
| --- | --- | --- |
| Time one action may take before it times out | 30 simulated seconds plus 1.5 times its estimated duration, at most 600 | `action_timeout_sim_s`, `max_action_timeout_sim_s` |
| Longest message between roles | 8,000 characters | `max_message_chars` |
| Most messages and bytes delivered to a role at once | 32 messages, 32,768 bytes | `max_batch_messages`, `max_batch_bytes` |
| Review deadline a role may save (`after_s`); the upper end also bounds a synchronization timeout | 1 to 600 seconds | `min_check_interval_s`, `max_check_interval_s` |
| Clearance below which the motion check reports a planned move | 0.02 m, over a preview of at most 15 s | `motion_check` |
| Rate of the motion recording and of a recorded video | 30 per simulated second | `motion_hz`, `video_fps` |

The time limit of a run is not in this file: it is `batch.task_wall_limit_s`
(`--wall-limit`), 24 hours by default and at most ([time and pauses](../runs/time.md)).

## Database write contention

Each run keeps its state in one SQLite database (`private/state/runtime.sqlite`) in WAL mode with
a 30-second busy timeout. A non-nested `BEGIN IMMEDIATE` that
returns plain `SQLITE_BUSY` is tried at most four times, 0.25 s apart, about 120.75 s in all.
Warnings go to standard logging, not the contested database, with elapsed time, attempts and
outcome. Nested savepoints, errors inside a transaction, commits, extended busy codes and other
errors are not retried (`roboteam/runtime/world/sqlite_busy.py`).

The local HTTP client's default timeout is that maximum wait plus 45 s; a caller's explicit
timeout is kept. A timeout does not establish whether an action ran: reconcile or query its
original ID. The Claude budget ledger uses the same writer policy.
