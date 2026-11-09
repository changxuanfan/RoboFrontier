# Architecture, state and evidence

Shared templates and execution code belong to the project. Inputs, working
memory and evidence belong to one run. Each run freezes its version; previous
runs' plans and experience are not automatically loaded into a new experiment.

## Project boundaries

| Path | Responsibility |
| --- | --- |
| `robofrontier.toml` | Operator settings, validated and frozen at preparation |
| `prompts/` | Shared rules and manager, Controller and Worker templates |
| `prompts/skills/robot-collaboration/` | Agent instructions and authoritative tool/communication references |
| `configs/` | Versioned catalogs, asset locks and engineering settings |
| `robofrontier/` | State, scheduling, native engine hosts, tools, MuJoCo and IK |
| `scripts/` | Native entries, preparation, diagnostics, collection and rendering |
| `tests/` | Synthetic contracts, kinematics and identified physical/native CLI checks |
| `assets/` | Web and presentation assets |
| `docs/` | Current contracts and guides; `history/` retains Legacy provenance |
| `vendor/` | Upstream robot models and source information |
| `runs/` | Ignored run-local evidence and engineering outputs |

Use `python -m robofrontier.cli`; see [CLI configuration](unified-cli.md).
The root `config.json` is a Legacy single-arm demonstration, not a second
benchmark-wide configuration. Current task inputs are selected through
`benchmark/release.json`. Historical Oracle witnesses and new
policy inputs have separate purposes and qualification records. New unified
Oracle executions select current released scenes; Factory playback uses each
recording's own frozen source. See [Oracle](oracle/README.md), [Factory](factory/replay.md)
and the [integration ledger](archive/unified-main.md).

## Native engines and topologies

Codex uses native app-server sessions and dynamic robot tools. Claude Code uses
native CLI sessions and robot MCP tools. An outer manager can be a shell or any
coding agent. It is not the measured policy and must not supply solutions or
private evaluator information. Native history, forking and transport remain
engine-specific. Shared contracts define authority, robot actions, permitted
observations, scoring and evidence.

| Public topology | Internal name | Initial policy roles |
| --- | --- | --- |
| Single | `centralized` | One Controller operates all robots; no subagents |
| Controller + Worker | `hierarchical` | A coordinating Controller and one persistent Worker per robot |
| Worker-Worker | `peer` | One persistent Worker per robot, coordinating directly |
| Adaptive | `adaptive` | One Controller creates and returns temporary delegates as it decides |

The coordinating Controller does not acquire standing Workers' action authority.
Single explicitly selects the robot for each command and can move independent
arms concurrently. Adaptive may alternate between no delegates and several
concurrent delegates in one task. Using no delegates does not change its
configured topology. All four modes have native Claude engineering entries;
standing teams bind one persistent native session per initial role. Their local
CLI/MCP and MuJoCo checks use a synthetic provider, so formal scored execution
remains closed. See [Claude standing teams](engines/claude-code.md#standing-teams).

## Direct START and clocks

New Codex and Claude Single/Adaptive runs use `direct_controller_v2`; standing teams use
`direct_team_v3`. The host creates and binds all initial roles to distinct native
sessions, requests one persisted START, then supplies an explicit started prompt
to every role. Initial reading and observations count toward the task clock.

`ready` is an optional capability query in these protocols. It does not unlock
START; continue after its response without waiting for another START. Frozen
Legacy `ready_barrier_v1` runs retain their readiness/idle-observation barrier
and original continuation behavior. Their inputs are not silently migrated.

The policy limit is `task_wall_limit_s`, normally 86,400 seconds, of active
running time saved in the run store; host stalls, pauses and network outages do
not count. Runs frozen before that clock keep the persisted
`start_at + task_wall_limit_s` deadline ([run segments](running/run-segments.md#time)). Preparation has a separate startup timeout. An external engineering
stop is distinct from the public task limit. Oracle engineering elapsed limits
include planning and review pauses; they are not a second policy START clock.

The default 0.3-second batch gate spaces initial host launches, not individual
file reads, tool calls or robot actions. API task homes are initialized serially
before parallel launch and isolated per task. Native subscription authentication
and refresh have a separate qualification boundary. Credentials are never
silently cloned from Desktop or another user.

## Run directory: format v3

```text
public/inputs/task.json        Frozen permitted static task
public/inputs/common.md        Frozen shared rules
public/inputs/roles.json       Frozen roles and communication topology
public/inputs/roles/*.md       Frozen role instructions and own connection path
public/inputs/skill/           Frozen Skill and protocol references
public/observations/           Timestamped RGB observations
public/results/               Returned reports and optional role-authored experience
public/robot-models/*.json     On-demand static robot descriptions
private/inputs/task.json       Frozen full task and scene inputs
private/inputs/harness.json    Frozen engineering parameters
private/inputs/meta-runbook.md Frozen manager instructions
private/inputs/manifest.json   Format, requested model and source/input hashes
private/inputs/frozen-source/  Frozen code, prompts and Skill bytes
private/inputs/scene/          Frozen MJCF, textures and meshes when needed
private/state/runtime.sqlite  Authoritative run-local execution database
private/state/connections/    Role authentication and service addresses
private/state/client-state/   Submitted requests, results and delivery receipts
private/outputs/              Motion, events, exports, evaluation and sealing evidence
private/inputs/segments/<k>/  Restore pose of segment k after an unexpected exit (docs/running/run-segments.md)
private/outputs/segments/<k>/ Segment k's own motion, video and post-mortem evaluation
```

`public` and `private` define the evidence contract, not operating-system
isolation on a shared account. Workers use their own authenticated connections.
Engineering object truth is not policy observation. Legacy runs retain their
paths and format; tools do not migrate or restart their physical worlds.

SQLite stores ownership, calls, messages, work and lifecycle facts. A copy is
neither complete evidence nor a physical restart. Slurm keeps live SQLite and
CLI state on verified node-local storage. Monitoring uses atomic JSON or the
service API, not a host-side database opened across Docker/shared filesystems.
Collection waits for writers and owner locks; see [Slurm](running/slurm.md).

## State and its writers

| State | Writer | Update boundary |
| --- | --- | --- |
| Frozen inputs and version snapshots | Preparation | Once before launch |
| Role notes, self-reported state and review deadlines | Agent through tools | Material decisions or before ending a turn |
| Mail, delivery batches, acknowledgments and notices | Harness | Communication events |
| Call IDs and accepted/running/terminal/unknown outcomes | Execution service | Request/action transitions |
| Native session observations | Fixed engine driver | Timestamped platform observations |
| Images and optional real-time video | Observation/recording service | Requested observation or configured sampling |
| JSONL exports and summaries | Export/collection code | Closure, failure handling or explicit export |
| Completion and process events | Independent evaluator | Task-specific sampling and final evaluation |

Work notes remain in the existing database. Record plans, commitments, evidence
references, blockers and the next decision in the role's own `work`. Long
experience may use `public/results/<actor>-experience.md` when that engine
provides the permitted file interface. It is an optional derived artifact, not a
new authoritative memory service or modified frozen Skill. Claude tool-only
policies use supported work/report interfaces rather than assuming filesystem
tools exist. Read reports through authorized references or `work` as specified
by the engine's prompt and Skill.

Experience records attempts, observations, applicability and uncertainty and
can be revised. Other roles read selected references; the harness does not
inject all experience into every context. Single retains its own experience,
standing Workers retain their work, and Adaptive delegates hand back useful
findings. Cross-run learning requires an explicit experiment and provenance.

## Context, observations and action boundaries

At startup, read the assigned role, task, shared rules, Skill and tool reference.
Optional `ready` provides compact static `robot_facts` derived from the model and
controller limits. Use `robot_model` for detailed geometry and `observe` for
proprioception and selected RGB views. Reach limits are not whole-arm safe
regions, current occupancy or task assignments.

On continuation, incorporate new events and restore relevant work/mail as needed.
Tool results can deliver bounded inbox batches within the same native turn.
There is no requirement to end a turn after every decision or request every
camera. Saved-note timestamps/revisions differ from current/latest action facts.
Executor updates do not make an old note freshly authored. Teammate statements
remain statements, not verified physical facts.

Legacy `scripts/role_tools.js` helpers provide robot-tool, finite-sequence and
role-step boundaries. `robotTool` returns the requested result and selected
images already present. `job` may return original images with original times;
a missing image does not trigger hidden observation. `robotSequence` executes
only the agent's finite move/gripper list, returning at events, failure,
uncertainty, pause/end or an intermediate image requiring interpretation. It
contains no hidden grasp/transport planner or conditional action queue.
Permitted local analysis can refresh mail at its operation boundary; bare native
tools have no universal project inbox hook.

New requests omit outer `call_id`; the host generates and returns it. To query
an existing action, make a new `job` request with the target ID in `data.call_id`.
For uncertain execution, query or retry the identical request under its original
outer ID. Reusing an ID for different contents is rejected as a conflict. A
transport error does not establish that nothing executed. Model-provider
recovery must never replay physical actions under fresh IDs.

Action budgets derive from distance, angle, aperture and speed and are recorded
at acceptance. Timeout requests controlled stopping. A known live stop that has
not settled remains running with `phase: stopping`; diagnostics expose the actual
and reference velocities, unmet stability conditions and applicable target error.
The affected robot stays reserved while the agent investigates or calls
`recover_action`, and independent robots continue. An unavailable execution
acknowledgement remains uncertain and isolates its robot without ending the live
world; it is never treated as success or replayed. A network timeout is not
physical cancellation. `wait:false` returns while the action remains running
under its original ID, without caching it as terminal. Mutual exclusion applies
per physical robot, leaving other arms and non-conflicting tools available.

`wait_events` has an agent-selected total deadline within configured bounds.
HTTP wait fragments reuse the original ID without renewing that deadline.
Events, total expiry or lifecycle changes cause a business-level return. The
waiter checks mail/actions at physical ticks without a transaction spanning
ticks. Neither waiting nor execution supports cross-process restart. Client
locks protect request/receipt updates, not an entire network wait or movement.

## Scheduling and adaptive handback

The shared Skill defines coordination and authority. The harness is not a task
planner. Standing roles can prepare independently within scope; shared resources
and joint commitments require coordination. Meta performs engineering setup and
fixed platform operations without deciding task strategy.

After direct START, agents choose to continue, wait for events or save work and
end a turn. Messages, availability changes, self-selected deadlines and explicit
pending work can justify continuation. Normal waiting does not trigger immediate
fixed-rate model polling. Ordinary mail does not continuously steer active turns.
An idle session can plan/communicate during a known non-blocking action but
cannot issue a second simultaneous command for the same robot. Blocking requests
and unknown outcomes retain their recovery constraints.

When an active role deliberately yields `waiting` or `available`, it supplies
its own finite `after_s` where required by the frozen contract. This constrains
that chosen turn-ending operation, not every decision. Preparation, pause and
ended states are exempt. The scheduler invents no review period and does not
interpret free-text notes as plans.

An Adaptive assignment defines one temporary delegate's identity and scope.
`return_task` writes its report, returns authority and posts a compact notice
transactionally. The report is agent-authored evidence, not evaluator truth.
Delegates do not communicate directly. A returned session accepts no new
assignment; a new scope needs a new delegate. Standing Workers instead remain
available after local completion.

If a delegate turn stops before handback, timestamped platform evidence produces
a deduplicated Controller notice. It implies neither success nor automatic
release of authority. The Controller can inspect compact `delegate_status`,
selected work and permitted native history. Thread errors and latest-turn
failures are separate facts. A confirmed failed active delegate whose physical
requests are all resolved may continue once for a new parent-directed message
through existing plan/claim/delivery logic. Missing terminal evidence, stale
messages and old deadlines do not justify replay or changed authority.

`dispatcher_health` stays in SQLite metadata and records successful observations,
cycles, delivery and redacted errors. A UI shows timestamps; a background tool
indicator alone does not establish a live independent daemon.

## Scoring, finishing and evidence

Completion is independent of an agent's claim. Under `terminal_outcome_v2`,
task-specific final conditions determine completion; supported collisions, drops
and other process events are reported separately. Dial unlock stays latched.
Agents continue observing, recovering and acting while unfinished. Propose
`finish` when complete or permitted evidence establishes that recovery is no
longer possible. An accepted incomplete finish is reported as incomplete.

Declared `pocket_seating` criteria can include identity/color, unique matching,
whole horizontal containment, bottom support, uprightness, release and a stable
interval. Stricter pose measures can remain diagnostics. Tasks without that
mode keep their original criteria. Private measurements are not live object
truth supplied to the policy. Engineering Oracle process gates do not silently
redefine policy scoring.

Sealing uses existing database/physical-owner locks and writes
`private/outputs/seal.json`, final observations and event exports, without a
second state store. Normal finish can retain a private bounded
`evaluation-window.json`; interruption can retain
`interruption-evaluation.json` and its window. These are neither policy inputs
nor periodic checkpoints. Simulation duration subtracts the START simulation time.

Native engines own original session history. Host events and robot evidence
complement it: a host log does not replace a session JSONL. Live session files
remain append-only. Stopped collection and reversible archive image extraction
are separate steps. Observations use JPEG 896 x 560, quality 85; offline video
size is independent. Motion retains actual times, float32 poses, appearance
events and XOR/ZIP compression. Compression after float32 conversion is
bit-exact; float64-to-float32 conversion and PNG-to-JPEG migration are lossy and
must be identified. See [evidence storage](archive/evidence-storage-validation-20261030.md).

Process memory, integral state, queues and model context are not a complete
restartable physics checkpoint. Interruptions retain unknown actions and
evidence. Starting again requires a new run, not a world reconstructed from a
database, JSONL or video.

## Adapter scope and Legacy shared-payload batches

The Panda adapter supports TCP position/orientation, joint targets, aperture and
speed commands, expected-width/force grasps and same-owner controlled stopping.
Gravity compensation preserves declared actuator/contact bounds. It supplies no
tactile object IDs or grasp planner. Different robots, navigation and assembly
mechanisms require adapter/evaluator work, not just a different goal string.
`robot_model` and `check_motion` are optional advisory tools: sampled checks
neither approve nor reject `move`. They disclose source state, horizon,
sampling and coverage gaps, not continuous collision or future occupancy proofs.

The Legacy beam adapter evaluates support, overlap-before-release, custody,
recovery, cross-arm contact and stable containment through physics. Support is a
declared proxy, not a true per-arm load sensor. Its private sampling and strict
acceptance remain version-specific; current Relay uses its frozen criteria and
terminal-outcome projection.

Finite `action_batch` uses existing ownership and execution. One owner submits
its group, or several owners sign their own commands under a shared `sync_group`
roster and non-renewing deadline. Only submitted robots are reserved. Completion
revalidates all members before the owner starts them ahead of the next physics
advance. Missing signatures, withdrawal, pause, shutdown or failed validation
cancel unstarted commands. Database rollback cannot undo motor effects: unknown
startup keeps control and requires recovery. A member failure brakes remaining
arm moves while preserving established holds and tracking gripper commands.
This provides neither rigid-payload control nor trajectory synchronization.

Parent/member IDs and outcomes remain in existing calls/actions. RPC completion
differs from physical success. Scheduling respects the immutable outer wait flag.
Unresolved signed operations block affected handback, while unrelated scopes
remain available. Cancelled reservations do not count as action overlap. Shared
summaries expose execution facts, not other roles' commands or private mail.
Actions remain blocked after finish; late mail is retained for audit and never
restarts the team.
