# Runtime protocol

The rules every policy run follows between preparation and scoring. Each prepared run freezes
its inputs, source and protocol identifiers; read a frozen run with the protocol it records.
Engine-specific behavior is in the [engine guides](engines/README.md); time and continuation in
[continuation](running/continuation.md).

## Start: system prompt, start message, START

- **System prompt.** `private/inputs/bootstrap/system.md` is the policy role statement followed
  by the run's `public/inputs/rules.md`. Claude Code receives it as `--system-prompt`, Codex as
  each thread's `baseInstructions`, delegates included. Both engines get the same bytes, and a
  compacted conversation keeps it whole.
- **Start message.** Each initial role's first message (`private/inputs/bootstrap/<role>.md`)
  carries its other public text inputs in full: `task.json`, `roles.json`, its role file, the
  Skill, its tool, motion-check, communication and adaptive references as the topology needs, and
  the family materials, each under its absolute path. The files stay readable on disk. The message
  is at most 400,000 bytes. Only the last line differs between engines (how to view images).
- **START.** Single and Adaptive runs use `direct_controller_v2`; Controller + Worker and
  Worker-Worker runs use `direct_team_v3`. The host prepares the world, binds every initial role
  to its own native session, persists one START and then sends each role its start message.
  Reading, observing and planning count as task time. A failed or uncertain first delivery is an
  engineering failure for review, never retried in the same world or reported as a task result.
- **`ready`** is an optional query of the role's robots, run limits and static `robot_facts`. It
  does not unlock START.
- **Time.** The public `task.json` states no time limit (`run_protocol.total_wall_limit_s` and
  `run_protocol.clock` are only in the private task), and the rules ask policies to plan as if
  time were unlimited. The host gives each run 24 hours of active time (`active_time_v1`) and
  scores it at that cutoff ([how it is counted](running/continuation.md#time)).

`public/inputs/rules.md` is the one policy contract both engines receive; the hosts keep their
own native tool transports. The CLI, model and harness together are the experimental condition:
equal rules do not make model context or tool behavior equal.

## Observation images

`render.observation_profile = "jpeg_896x560_q85"` (the default) makes every observation camera
produce an 896 × 560 JPEG at quality 85; `png_1280x800` is the other choice. The run's harness
freezes it as `observation_image_profile`, and the public task states the format and resolution.
When a published camera calibration names an image size, the run gets a copy at the observation
resolution and the published file stays as it is. Video recording has its own resolution.

## Robot requests and IDs

For a new robot request on either engine, omit the outer `call_id`; the host generates one and
returns it. To query an earlier physical action, send a new request
`{"op":"job","data":{"call_id":"ACTION_ID"}}` with no outer `call_id`: the query gets its own ID
and `data.call_id` names the action. To retry a request whose result is uncertain, resend it under
its original outer ID with exactly the same operation and data. Never replay an uncertain physical
action under a new ID. How the Claude host binds IDs to native tool calls is in
[new requests, queries and delegation](engines/README.md#new-requests-queries-and-delegation).

A blocking action that is still running after 600 s returns as pending under its original ID (an
engine may give up on a tool call sooner); the action keeps running and `job` follows it.

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
PYTHONPATH=tests:scripts .venv/bin/python -m unittest runtime.test_tool_errors \
  runtime.test_pipeline_client runtime.test_runtime_store engines.test_claude_tool_errors
node --test tests/engines/test_tool_errors.js
```

## IK failure detail

A `move`, `check_motion` candidate or `action_batch` member whose pose has no verified IK
solution is rejected before execution with its `error` and an `ik_detail`:

| Field | Meaning |
| --- | --- |
| `closest_found_tcp_m`, `position_error_m`, `rotation_error_rad` | The closest TCP pose the solver found and how far it is from the request |
| `horizontal_distance_from_base_m` | The target's and that pose's horizontal distance from the robot base |
| `orientation` | The orientation used: the requested `quaternion_wxyz`, or the current one kept |
| `home_orientation` | Whether the same position solves with the robot's home hand orientation, and that quaternion |

The solver searches locally from the current joint references, so these are solver facts, not a
proof of the reach limit or a suggested target. No object state is used. The extra
home-orientation solve runs only after a rejection (`robofrontier/physics/robot_control.py`).

## Terminal outcome

Policy runs declare `terminal_outcome_v2` in the frozen run protocol. The task's final conditions
decide completion:

- **Transport and Mosaic:** the geometric, release, stability and assignment predicates of each
  goal.
- **Relay:** every timber has had a qualified airborne handover (`relay-airborne-handover-v1`)
  and is released with at least 70 percent of its centreline above the GOAL outline
  (`relay-timber-goal-70pct-v1`).
- **Dial:** success latches when a simultaneous valid correct input unlocks the device; later dial
  changes do not undo it.

Dropped flags and recorded violations do not veto completion. Reports keep
`strict_task_success`, process compliance and violations; Relay reports also keep
`legacy_process_goals_met`, `legacy_completed_payloads`, drops and handover records. A violation
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

## SQLite writer contention

The run store uses SQLite WAL with a 30-second busy timeout. A non-nested `BEGIN IMMEDIATE` that
returns plain `SQLITE_BUSY` is tried at most four times, 0.25 s apart, about 120.75 s in all.
Warnings go to standard logging, not the contested database, with elapsed time, attempts and
outcome. Nested savepoints, errors inside a transaction, commits, extended busy codes and other
errors are not retried (`robofrontier/runtime/sqlite_busy.py`).

The local HTTP client's default timeout is that maximum wait plus 45 s; a caller's explicit
timeout is kept. A timeout does not establish whether an action ran: reconcile or query its
original ID. The Claude budget ledger uses the same writer policy.
