# Architecture, state and evidence

Shared templates and execution code belong to the project. Inputs, working memory and evidence
belong to one run. Each run freezes what it uses; a new run never loads an earlier run's plans or
lessons.

## Project parts

| Path | Responsibility |
| --- | --- |
| `robofrontier.toml` | Defaults for new runs, validated and frozen at preparation |
| `benchmark/` | The released cases; `benchmark/release.json` selects every run's inputs |
| `prompts/` | Shared rules, role prompts, Skills and the two outer manager prompts |
| `configs/` | Model profiles, harnesses, asset and environment locks, example site TOMLs |
| `robofrontier/` | Run setup, scheduling, native engine hosts, robot tools, MuJoCo world, IK and scoring |
| `scripts/` | Engineering commands: policy environment, release, validation, analysis, media |
| `tests/` | Synthetic contracts, kinematics, physics and native CLI checks |
| `runs/` | Run evidence and engineering outputs, not in Git (`paths.runs_root`) |

The command line is `robofrontier` ([command-line guide](unified-cli.md)); the full folder map is
in [repository layout](repository-layout.md). Oracle runs use the released scenes' Oracle copies
([Oracle](oracle/README.md)); Factory playback uses each recording's own frozen scene
([Factory](factory/replay.md)).

## Engines and topologies

Codex runs native app-server sessions with dynamic robot tools. Claude Code runs native CLI
sessions with robot MCP tools. An outer manager (a shell or any coding agent) operates the batch;
it is not the measured policy and must not supply solutions or private evaluation data. Native
history, forking and transport stay engine-specific; the shared contracts define authority, robot
actions, permitted observations, scoring and evidence.

| Topology | Internal name | Initial policy roles |
| --- | --- | --- |
| `single` | `centralized` | One Controller operates all robots; no delegates |
| `controller-worker` | `hierarchical` | A coordinating Controller and one standing Worker per robot |
| `worker-worker` | `peer` | One standing Worker per robot, coordinating directly |
| `adaptive` | `adaptive` | One Controller that creates and retires temporary delegates as it decides |

The coordinating Controller does not get its Workers' action authority. A Single Controller
names the robot in each command and can move independent arms concurrently. An Adaptive run may
alternate between no delegates and several in one task; using none does not change its topology.
Standing teams bind one native session per initial role. Both engines run all four topologies
([Claude standing teams](engines/claude-code.md#standing-teams)).

## START and time

Single and Adaptive runs use `direct_controller_v2`, standing teams `direct_team_v3`: the host
binds every initial role to its own native session, persists one START, then sends each role its
start message ([protocol](protocol.md#start-system-prompt-start-message-start)). Reading and
observing count as task time. `ready` is an optional capability query, not a START gate.

The task limit is `batch.task_wall_limit_s`, 86,400 s of active running time from START, counted
in the run store; host stops, pauses and network outages do not count
([time](running/continuation.md#time)). The run is scored at that cutoff. `batch.startup_timeout_s`
bounds preparation separately. An operator's stop is not the task limit. Oracle elapsed limits
include planning and review pauses and are not a policy clock.

`batch.startup_interval_s` (0.3 s) spaces the launches of run hosts, never robot actions or model
turns. Codex API homes are created serially before parallel launch, one per run. Credentials are
never copied from a desktop login or another user.

## Run directory (`run-v6`)

```text
public/inputs/task.json            frozen public task
public/inputs/rules.md             frozen shared rules (also in the system prompt)
public/inputs/roles.json           roles and communication topology
public/inputs/roles/<role>.md      role instructions
public/inputs/skill/               the robot-collaboration Skill and its references
public/inputs/family/              family Skill and materials
public/inputs/environment.md       the policy environment; policy-env.sh is sourced before each Claude command
public/observations/               timestamped RGB observations
public/results/                    reports returned by roles
workspace/                         the policy's only writable folder and working directory
workspace/skills.md                the run's shared lessons file
private/inputs/task.json           full task and scene inputs
private/inputs/harness.json        engineering parameters
private/inputs/effective-config.json, manifest.json    resolved settings; format, model and input hashes
private/inputs/policy-access.json  the frozen access table and environment hash
private/inputs/bootstrap/          system prompt and start, resume and delegate messages
private/inputs/frozen-source/      frozen code, prompts and runbook docs
private/inputs/scene/              frozen MJCF, textures and meshes
private/inputs/meta/               the Meta manager's role file and runbook
private/inputs/segments/<k>/       restore pose of segment k
private/state/runtime.sqlite       the authoritative run database
private/state/connections/         role authentication and service addresses
private/state/client-state/        submitted requests, results and delivery receipts
private/state/control/             STOP marker, status snapshot, locks
private/outputs/                   evaluation.json, seal.json, report.json, motion/, events, exports
private/outputs/segments/<k>/      segment k's own motion, video and evaluation
private/logs/                      owner, host, server and supervisor logs
private/engine/                    CLI and MCP configuration, per-turn evidence, transcripts
```

A batch folder holds `batch.json`, `effective-config.json`, `profiles/`, `control/` (STOP,
status snapshot, locks, `durable/`), `logs/` and one `<profile>/<case>/` run per selected case
(`batch-v2`). The layouts are defined in `robofrontier/runtime/layout.py`; a run records its
layout in its manifest, and frozen runs keep theirs.

`public` and `private` define the evidence contract; the operating-system boundary is the
access table ([policy environment](running/policy-environment.md#what-a-policy-can-reach)):
a policy writes only `workspace/` and `/tmp`, reads `public/` and its environment, and cannot
reach the rest of the run, other runs, the checkout, the home folder or shared storage. Roles use
their own authenticated connections. Engineering object truth is never a policy observation.

SQLite stores ownership, calls, messages, work and lifecycle facts. A copy of it is neither
complete evidence nor a world restart. Live SQLite and CLI state stay on node-local storage;
monitoring reads atomic JSON or the service API, never a database opened across Docker or a
shared filesystem.

## State and its writers

| State | Writer | When |
| --- | --- | --- |
| Frozen inputs and source snapshots | Preparation | Once before launch |
| Role notes, self-reported state, review deadlines | Agent through tools | Material decisions, before ending a turn |
| Mail, delivery batches, acknowledgments, notices | Harness | Communication events |
| Call IDs and accepted / running / terminal / unknown outcomes | Execution service | Request and action transitions |
| Native session observations | Engine driver | Timestamped platform observations |
| Images and optional real-time video | Observation and recording service | Requested observations or configured sampling |
| Exports and summaries | Export and collection code | Closure, failure handling or explicit export |
| Completion and process events | Independent evaluator | Task-specific sampling and final evaluation |

Each role records plans, commitments, evidence references, blockers and its next decision in its
own `work` note in the run database. Verified lessons for the run go in `workspace/skills.md`,
which every role shares. Other roles read selected notes; the harness does not inject everything
into every context. Single keeps its own notes, standing Workers keep their work, and Adaptive
delegates hand findings back in their `return_task` report. Learning across runs needs an explicit
experiment with recorded provenance.

## Observations and actions

At startup a role has its role, the task, the rules, the Skill and the tool reference in its start
message. `ready` returns compact static `robot_facts`; `robot_model` gives detailed geometry and
`observe` proprioception and selected RGB views. Reach bounds are admitted commands, not safe
regions, current occupancy or task assignments.

New requests omit the outer `call_id`; to query an action, send a new `job` request with its ID
in `data.call_id`; retry an uncertain request only under its original ID with identical contents
([robot requests and IDs](protocol.md#robot-requests-and-ids)). A transport error does not show
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

The Skill defines coordination and authority; the harness is not a task planner. Standing roles
prepare independently within scope; shared resources and joint commitments need coordination. Meta
performs engineering setup and fixed platform operations without deciding task strategy.

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
selected work and permitted native history. A confirmed failed delegate whose physical requests
are all resolved may continue once for a new parent message. `dispatcher_health` in the run store
records successful observations, cycles, deliveries and redacted errors.

## Scoring, finishing and evidence

Completion is independent of an agent's claim: under `terminal_outcome_v2` the task's final
conditions decide it, and collisions, drops and other process events are reported separately
([terminal outcome](protocol.md#terminal-outcome)). Agents keep observing, recovering and acting
while the task is unfinished, and propose `finish` when it is complete or permitted evidence shows
recovery is impossible. An accepted incomplete finish is reported as incomplete.

Sealing takes the database and physical-owner locks and writes `private/outputs/seal.json`, final
observations and event exports. The settled score is `private/outputs/evaluation.json`; a normal
finish can keep a private `evaluation-window.json`, an interruption `interruption-evaluation.json`
and its window. These are neither policy inputs nor checkpoints. Simulation duration is counted
from the START simulation time.

The engines own the native session history; host events and robot evidence complement it, and
live session files are append-only. Observations are JPEG 896 × 560 at quality 85; offline video
size is independent. Motion keeps actual times, float32 poses, appearance events and lossless
XOR/ZIP compression; the float64-to-float32 conversion is the one lossy step
([evidence storage](running/evidence-storage.md)).

Process memory, controller state, queues and model context are not a restartable physics
checkpoint. A stopped run continues in a new segment of the same trial, with the world rebuilt
approximately from its last recorded frame ([continuation](running/continuation.md)).

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
