# Architecture, state and evidence

How a run is built: which process does what, where state lives and who may write it. The words
used here (policy, role, host, world, session, segment, seal) are defined in the
[documentation index](../README.md#terms).

Shared templates and code belong to the project. Inputs, working notes and evidence belong to
one run. Each run freezes what it uses; a new run never loads an earlier run's plans or
lessons.

## Processes of one run

| Process | What it does |
| --- | --- |
| World owner | Steps the physics in real time, executes robot actions, draws the images, counts active time and scores the task. One per run; it holds the world lock. It also serves the run's local HTTP service: every robot tool call arrives there, is checked against the caller's role and is recorded in the run database |
| Host | Starts the roles' sessions in the harness CLI, passes their robot tool calls to the world's service and wakes idle roles |
| Role sessions | The agents: one session of the harness CLI per role |
| Batch supervisor | Starts each run's processes, watches them, continues a run after an unexpected stop, and collects evidence at the end |

## Project parts

| Path | Responsibility |
| --- | --- |
| `roboteam.toml` | Defaults for new runs, validated and frozen at preparation |
| `benchmark/` | The released cases; `benchmark/release.json` selects every run's inputs |
| `prompts/` | Shared rules, role prompts and guides |
| `models.json` | Models, one section per harness |
| `roboteam/` | Run setup, scheduling, the harness hosts, the robot tool, MuJoCo world, IK and scoring |
| `scripts/` | Engineering commands: policy environment, release, validation, analysis, media |
| `tests/` | Tests of the runtime's rules, kinematics, physics and the installed harness CLIs |
| `runs/` | Run evidence and engineering outputs, not in Git (`paths.runs_root`) |

The command line is `roboteam` ([command-line guide](../cli.md)); the full folder map is
in [repository layout](repository-layout.md).

## Harnesses and systems

Codex runs each role as an app-server thread and gives it the robot tool as a tool of that
thread. Claude Code runs each role as a CLI session and gives it the robot tool through an MCP
server. An outer manager (a person, a shell script or any coding agent) operates the batch; it
is not the measured policy and must not supply solutions or private evaluation data. Session
history, forking and the connection to the model differ by harness. Who may do what, the robot
actions, the permitted observations, scoring and evidence are the same.

| Agent system (`policy.system`) | Initial policy roles |
| --- | --- |
| `adaptive` | One Controller that creates and retires temporary delegates as it decides |
| `single-agent` | One Controller operates all robots; no delegates |
| `hierarchical` | A coordinating Controller and one standing Worker per robot |
| `decentralized` | One standing Worker per robot, coordinating directly |

A `hierarchical` Controller coordinates and cannot move its Workers' arms. A `single-agent`
Controller names the arm in each command and can move independent arms at the same time. An
`adaptive` run may alternate between no delegates and several in one task; using none does not
change its system. `hierarchical` and `decentralized` teams have one session per initial role
for the whole run. Both harnesses run all four systems
([Claude standing teams](../harness/claude-code.md#standing-teams)).

## START and time

The host gives every initial role its own session, the runtime records one START, and the host
then sends each role its start message
([rules](../benchmark/rules.md#start-system-prompt-start-message-start)). Reading and observing
count as task time. `ready` is an optional query of a role's robots and limits; it does not
unlock START.

The task limit is `batch.task_wall_limit_s`, 86,400 s of active running time from START, counted
in the run database; host stops, pauses and network outages do not count
([time and pauses](../runs/time.md)). The run is scored at that cutoff. `batch.startup_timeout_s`
bounds preparation separately. An operator's stop is not the task limit.

`batch.startup_interval_s` (0.3 s) spaces the launches of run hosts, never robot actions or model
turns. Codex API homes are created serially before parallel launch, one per run. Credentials are
never copied from a desktop login or another user.

## Run directory

```text
public/inputs/task.json            frozen public task
public/inputs/rules.md             frozen shared rules (also in the system prompt)
public/inputs/roles.json           roles and agent system
public/inputs/roles/<role>.md      role instructions
public/inputs/guide/               the robot-collaboration guide and its references
public/inputs/task/                task guide (guide.md) and materials
public/inputs/environment.md       the policy environment; policy-env.sh is sourced before each Claude command
public/observations/               timestamped RGB observations
public/results/                    reports returned by roles
workspace/                         the policy's only writable folder and working directory
workspace/skills.md                the run's shared lessons file
private/inputs/task.json           full task and scene inputs
private/inputs/run.json            run settings
private/inputs/effective-config.json, manifest.json    resolved settings; format, model and input hashes
private/inputs/models.json         the harness's section of models.json
private/inputs/release.json, release-materials/        the release record and the case's released materials
private/inputs/policy-access.json  the frozen access table and environment hash
private/inputs/policy-tools.json   the tools mode (full or robot_only)
private/inputs/bootstrap/          system prompt and start, resume and delegate messages
private/inputs/frozen-source/      frozen code, prompts and runbook docs
private/inputs/scene/              frozen MJCF, textures and meshes
private/inputs/meta/               the Meta manager's role file and runbook
private/inputs/segments/<k>/       restore pose of segment k
private/state/runtime.sqlite       the run database
private/state/budget.sqlite        Claude Code: the cost records of each turn
private/state/connections/         role authentication and service addresses
private/state/client-state/        submitted requests, results and delivery receipts
private/state/control/             STOP marker, status snapshot, locks
private/outputs/                   evaluation.json, seal.json, report.json, motion/, events, exports
private/outputs/segments/<k>/      segment k's own motion, video and evaluation
private/logs/                      owner, host, server and supervisor logs
private/harness/                    CLI and MCP configuration, per-turn evidence, transcripts
```

A batch folder holds `batch.json`, `effective-config.json`, `models/`, `control/` (STOP,
status snapshot, locks, `durable/`), `logs/` and one `<model>/<case>/` run per selected case.
The layouts are defined in `roboteam/runtime/run/layout.py`.

`public` and `private` define the evidence contract; the operating-system boundary is the
access table ([policy environment](../hosts/policy-environment.md#what-a-policy-can-reach)):
a policy writes only `workspace/` and `/tmp`, reads `public/` and its environment, and cannot
reach the rest of the run, other runs, the checkout, the home folder or shared storage. Each
role has its own authenticated connection to the world's service. The state of objects is never
given to a policy, except in a run prepared with
[ground-truth observation](../benchmark/rules.md#ground-truth-observation).

SQLite stores ownership, calls, messages, work and lifecycle facts. A copy of it is neither
complete evidence nor a world restart. Live SQLite and CLI state stay on node-local storage;
monitoring reads atomic JSON or the service API, never a database opened across Docker or a
shared filesystem.

## State and its writers

| State | Writer | When |
| --- | --- | --- |
| Frozen inputs and source snapshots | Preparation | Once before launch |
| Role notes, self-reported state, review deadlines | Agent through tools | Material decisions, before ending a turn |
| Mail, delivery batches, acknowledgments, notices | Runtime | Communication events |
| Call IDs and accepted / running / terminal / unknown outcomes | Execution service | Request and action transitions |
| Native session observations | Harness driver | Timestamped platform observations |
| Images and optional real-time video | Observation and recording service | Requested observations or configured sampling |
| Exports and summaries | Export and collection code | Closure, failure handling or explicit export |
| Completion and process events | Independent evaluator | Task-specific sampling and final evaluation |

Each role records plans, commitments, evidence references, blockers and its next decision in its
own `work` note in the run database. Verified lessons for the run go in `workspace/skills.md`,
which every role shares. Other roles read selected notes; the runtime does not inject everything
into every context. Single keeps its own notes, standing Workers keep their work, and Adaptive
delegates hand findings back in their `return_task` report. Learning across runs needs an explicit
experiment with recorded provenance.

## Observations and actions

At startup a role has its role, the task, the rules, the collaboration guide and the tool
reference in its start message. `ready` returns compact static `robot_facts`; `robot_model`
gives detailed geometry and `observe` the state of the role's arms and the camera images it
selects (in a ground-truth run, no images; the `state` operation gives the simulator's state
instead). Reach bounds are admitted commands, not safe regions, current occupancy or task
assignments.

New requests omit the outer `call_id`; to query an action, send a new `job` request with its ID
in `data.call_id`; retry an uncertain request only under its original ID with identical contents
([robot requests and IDs](../benchmark/rules.md#robot-requests-and-ids)). A transport error does not show
that nothing ran, and provider recovery never replays physical actions under fresh IDs.

Action time budgets come from distance, angle, aperture and the requested rates and are recorded
at acceptance. At a timeout the controller brakes. A stop that has not settled stays running with
`phase: stopping` and diagnostics (actual and reference velocities, unmet stability conditions,
target error); the robot stays reserved while the agent investigates or calls `recover_action`,
and independent robots continue. An unavailable execution acknowledgment stays uncertain and
isolates its robot without ending the world; it is never treated as success or replayed.
`wait:false` returns while the action keeps running under its ID. Mutual exclusion is per robot.

`wait_events` has an agent-chosen total deadline within the run's bounds; HTTP slices reuse the
original ID without renewing it. Mail, events, expiry or lifecycle changes end the wait. Client
locks protect request and receipt updates, not a whole wait or movement.

## Scheduling and Adaptive handback

The collaboration guide defines coordination and authority; the runtime is not a task planner.
Roles prepare independently within their scope; shared resources and joint commitments need
coordination. Meta, the runtime's own engineering manager, performs setup and fixed operations
such as delivering wakes. It makes no task decisions.

After START, agents choose to continue, wait for events, or save work and end a turn. Messages,
availability changes, self-chosen deadlines and pending work can justify a continuation; normal
waiting does not cause fixed-rate model polling. An idle session can plan and communicate during a
non-blocking action but cannot issue a second command to the same robot. A role that yields
`waiting` or `available` during an active run supplies its own finite `after_s`; the scheduler
invents no review period and does not read free-text notes as plans.

An Adaptive assignment defines one temporary delegate's identity and scope. `return_task` writes
its report, returns authority and posts a notice in one transaction; the report is agent-authored,
not evaluator truth. Delegates do not message each other, and a returned delegate takes no new
assignment. Standing Workers stay available after finishing local work.

If a delegate turn stops before handback, the Controller gets one deduplicated notice; it implies
neither success nor release of authority. The Controller can read compact `delegate_status`,
selected work and the delegate's session history where permitted. A confirmed failed delegate whose physical requests
are all resolved may continue once for a new parent message. `dispatcher_health` in the run store
records successful observations, cycles, deliveries and redacted errors.

## Scoring, finishing and evidence

Completion is independent of an agent's claim: under `terminal_outcome_v2` the task's final
conditions decide it, and collisions, drops and other process events are reported separately
([terminal outcome](../benchmark/rules.md#terminal-outcome)). Agents keep observing, recovering and acting
while the task is unfinished, and propose `finish` when it is complete or permitted evidence shows
recovery is impossible. An accepted incomplete finish is reported as incomplete.

Sealing closes a world in order: it takes the database and world locks, blocks new actions,
takes final observations and writes `private/outputs/seal.json` and the event exports. The
settled score is `private/outputs/evaluation.json`; a normal finish can keep a private
`evaluation-window.json`, an interruption `interruption-evaluation.json` and its window. These
are neither policy inputs nor checkpoints. Simulation duration is counted from the START
simulation time.

Each harness keeps its own session history; host events and robot evidence complement it, and
live session files are append-only. Observations are JPEG 1280 × 800 at quality 90 by default.
Motion keeps actual times, float32 poses, appearance events and lossless
XOR/ZIP compression; the float64-to-float32 conversion is the one lossy step
([evidence storage](../runs/evidence-storage.md)).

Process memory, controller state, queues and model context are not a restartable physics
checkpoint. A stopped run continues in a new segment of the same trial, with the world rebuilt
approximately from its last recorded frame ([continuing a stopped run](../runs/continuation.md)).

## Robot adapter and batches

The Panda adapter supports TCP position and orientation, joint targets, aperture and speed
commands, expected-width and force grasps, and same-owner controlled stopping. It supplies no
tactile object IDs or grasp planner. Other robots, navigation or assembly mechanisms need adapter
and evaluator work, not a different goal string. `robot_model` and `check_motion` are optional,
advisory tools: sampled checks neither approve nor reject a `move`, and they report their source
state, horizon, sampling and coverage gaps rather than proving collision-free motion.

The Relay evaluator judges support, overlap before release, custody, recovery, cross-arm contact
and the final GOAL placement through physics. Support is a declared proxy, not a per-arm load
sensor.

A finite `action_batch` uses the existing ownership and execution. One owner submits its group,
or several owners sign their own commands under a shared `sync_group` roster with a non-renewing
deadline. Only submitted robots are reserved. Completion revalidates every member before the owner
starts them ahead of the next physics step. Missing signatures, withdrawal, pause, shutdown or
failed validation cancel unstarted commands. A database rollback cannot undo motor effects: an
unknown start keeps control and needs recovery. A member failure brakes the remaining arm moves
while keeping established holds and gripper tracking. This is neither rigid-payload control nor
trajectory synchronization. Parent and member IDs and outcomes stay in the existing calls and
actions; unresolved signed operations block the affected handback only. Actions stay blocked after
finish, and late mail is kept for audit without restarting the team.
