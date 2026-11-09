# Runtime protocol notes

Short notes on runtime protocol versions that apply to newly prepared runs. Each
section is independent. Existing prepared runs keep their frozen inputs, source
and original protocol; use the matching frozen version rather than changing
their recorded configuration or reinterpreting them as runs of a newer version.
Engine-specific behavior is in the [engine guides](engines/README.md).

## Observation images

New runs freeze `observation_image_profile: jpeg_896x560_q85` in their harness.
Every observation camera produces an 896 × 560 JPEG at quality 85. The public
task describes the observation format and resolution. Video recording has its
own resolution and is unchanged.

A run with no profile uses the legacy `png_1280x800` profile. To prepare a new
run with PNG observations, set that explicit profile in its harness
configuration. Readers accept both JPEG and PNG; public reference assets keep
their existing formats. A previously prepared run retains its frozen inputs and
source; use the matching frozen version rather than changing its recorded
configuration or assuming it can be resumed with different code.

When a published camera calibration specifies an image size, a run-specific copy
is created with the observation resolution while the original published asset
remains intact. Image generation and storage remain in their existing
transaction scope.

## SQLite writer contention

RuntimeStore uses SQLite WAL and a 30-second busy timeout. A non-nested
`BEGIN IMMEDIATE` that returns the ordinary `SQLITE_BUSY` code is attempted at
most four times, with 0.25 seconds between attempts. The total SQLite waiting
budget is approximately 120.75 seconds. Warning logs go to standard logging
rather than the contested database, including elapsed time, attempts and
outcome. Nested savepoints, errors inside a transaction, commit, extended busy
codes and other errors are not replayed. Existing transaction rollback and
action call-ID semantics remain in effect.

The default local HTTP client timeout includes one maximum SQLite begin wait
plus the normal 45-second response allowance. Callers that explicitly set a
timeout retain their chosen value. Connection startup, multiple sequential
acquisitions, other callers and external transport deadlines may still fail
independently; a timeout does not establish whether an action executed.
Reconcile or query its original call ID.

The Claude shared budget ledger uses the same writer-acquisition policy.
Existing runs retain their frozen source and should be handled with their
matching frozen code.

## Direct Controller startup and terminal scoring v2

### Direct Controller startup

New policy drafts use `direct_controller_v2`: after the physical owner is ready
and the single Controller session is bound, the host starts the world and clock,
then sends its first task prompt. Reading, observations and reasoning count
toward the configured wall limit. A failed or uncertain first delivery is an
engineering failure requiring review; it must not be reported as a task success
or retried in the same world. Existing prepared runs keep their frozen inputs
and original protocol.

### Terminal outcome

Policy runs declare `terminal_outcome_v2` in the frozen run protocol. Placement
tasks require the existing geometric, release, stability and assignment
predicates; Dial uses its solved state. Relay requires every timber to have had
a qualified airborne handover (`relay-airborne-handover-v1`, declared in the run
protocol) and to be released with at least 70 percent of its centreline above the
GOAL outline (`relay-timber-goal-70pct-v1`; earlier tasks keep the 50 mm boundary
rule with table support). Runs prepared before that protocol field keep the same
placement check without the handover requirement. Dropped flags and recorded
violations do not independently veto terminal completion. Reports
retain `strict_task_success`, process compliance and violations; Relay retains
`legacy_process_goals_met`, `legacy_completed_payloads`, drops and handover
records. A violation entry is deduplicated by kind and key, not a verified count
of separate collision episodes. Failed actions and unresolved actions remain
distinct from process violations. An interrupted or unresolved physical run is
not promoted to success.

Dial success is latched once a simultaneous valid correct input unlocks the
device; a later change to the dials does not undo it. This is an unlock event,
rather than a requirement that the final dial positions remain correct.

### Contact and drop metrics

`robot_contact_episodes` separately reports sampled contact episodes for
inter-robot and self-robot body pairs using the existing collision thresholds
(penetration greater than 0.2 mm and 1 mm respectively). Contact gaps of at most
50 ms of simulation time are joined. The report includes the maximum sampling
gap and per-pair counts; it counts observed body-pair episodes, not unique
physical impacts, and short missed contacts or multiple body pairs per impact
can change the number. Legacy deduplicated violations and drop metrics are
preserved; none of these counts changes terminal success.

Relay `drops` is the existing state-machine detection, not a complete count of
every physical drop; it depends on established airborne, support and contact
states. Transport, Mosaic and Dial do not provide a validated general drop
counter in this evaluator. An absent metric means not provided, not zero events.
Dial's red-operation support violations are detected only before unlock; the
success latch is unaffected by later dial changes. Other events and their
detection coverage are task-specific.

### Shared policy contract and comparability

`public/inputs/policy-rules.md` is the common policy contract supplied to Codex
and Claude; hosts retain different native tool transports. Its content and the
actual model-facing inputs are frozen per run. The CLI model-plus-harness
combination remains part of the experimental condition; equal task rules do not
prove equal model context or tool behavior.

This changes both model-visible startup and scoring; compare results only after
recording the protocol and scoring version. Historic results are not rewritten.
Policy preparation applies versioned terminal-scoring public overlays to the
reviewed legacy projections and applicable family guidance, and records hashes
of the resulting files. The published source release remains unchanged.

## Robot tool error feedback

New runs distinguish a typed `CALL_ID_CONFLICT` from `TRANSPORT_UNCERTAIN`.
This changes error feedback, not robot authority, action execution, scoring,
or the existing call-ID guard. No failure automatically creates another ID,
replays a command, restarts a world, or extends the deadline.

`CALL_ID_CONFLICT` has `request_status: rejected` and
`original_call_status: unknown`. Only the newly conflicting request was
rejected; the request already associated with that ID may have executed or
may still be running. Inspect own `pending` records and, for own physical
actions, `job` with the original action ID. A new ID is appropriate only for
an intentionally new request after reconciling existing work. Other roles'
requests and parameters are not disclosed.

The client detects local conflicts before submitting a changed request. The
server returns HTTP 409 JSON for a typed conflict in its task-wide call
table. The client validates the schema and matching ID, saves that explicit
rejection separately, and does not list it as unresolved execution. Repeating
that rejected request locally raises the same conflict without resubmission.
The old request and its result remain unchanged.

Timeouts, lost replies, malformed output, unknown error codes and mismatched
IDs produce `TRANSPORT_UNCERTAIN` with `request_status: unknown`. This is a
conservative result-unconfirmed category, not proof of a network root cause.
It does not establish that an operation failed to execute. The durable request
remains available for reconciliation under its original ID.

Codex validates the failed client's JSON and reconstructs an allowlisted
response; raw stderr and command lines are not returned to the policy. The
Claude MCP bridge uses the same typed Python exception and safe payloads.
Successful tools continue to use their existing results. Optional image
handling remains independent in branches that already include that fix.

Use a fresh prepared run after updating. Existing runs retain their frozen
source and inputs; do not edit or reinterpret them as runs of this version.
This change does not qualify multi-role startup, long-term concurrency,
network-filesystem storage, or task-solving performance.

Offline checks (no paid model calls or physical simulation):

```sh
PYTHONPATH=tests:. .venv/bin/python -m unittest tests.test_tool_errors tests.test_pipeline_client tests.test_runtime_store
node --test tests/test_tool_errors.js
# Claude branch additionally:
PYTHONPATH=tests:. .venv/bin/python -m unittest tests.test_claude_tool_errors
```

### CLI request ID and action ID

For a new Codex robot request, omit the outer `call_id` and retain the response's
`call_id`. Claude MCP requires a unique stable outer ID for each new `move`,
`gripper`, `action_batch`, `delegate`, and `stop`; other requests may omit it.
To query an earlier physical action, call
`{"op":"job","data":{"call_id":"ACTION_ID"}}` with no outer `call_id`.
The new query receives its own request ID; `data.call_id` names the original
action. If the original request itself must be retried after an uncertain
result, use its original outer ID and exactly the same operation and data.
Do not assign a new ID to replay an uncertain physical action. How the Claude
host generates and binds IDs is described in
[new requests, queries and delegation](engines/README.md#new-requests-queries-and-delegation).

## Start message, system prompt and wall limit

New runs give every policy role its inputs without depending on file reads, and
keep the rules through context compaction. Both engines receive the same bytes.

- **System prompt.** `private/inputs/bootstrap/system.md` is the policy role
  statement followed by this run's `public/inputs/rules.md`. Claude Code receives
  it as `--system-prompt`, Codex as each thread's `baseInstructions`, delegates
  included. A compacted conversation keeps it whole.
- **Start message.** Each initial role's first message carries its other public
  text inputs in full (`task.json`, `roles.json`, its role file, the Skill, its
  tool, motion-check, communication and adaptive references as the topology needs,
  and the family materials), each under its absolute path. The files stay
  readable on disk. The message is limited to 400,000 bytes.
- **Wall limit.** The public `task.json` no longer states
  `run_protocol.total_wall_limit_s` (nor, for new runs, `run_protocol.clock`);
  the private task keeps them and the host enforces the limit as before
  ([how it is counted](running/run-segments.md#time)). The rules ask policies to plan as if time were
  unlimited, and a policy can no longer estimate the time left from its inputs.

Earlier runs keep their frozen system prompt, start message and public task.

## IK failure detail

A `move`, `check_motion` candidate or `action_batch` member whose pose has no
verified IK solution is still rejected before execution with the same `error`.
The response now also carries `ik_detail`:

| Field | Meaning |
| --- | --- |
| `closest_found_tcp_m`, `position_error_m`, `rotation_error_rad` | The closest TCP pose the solver found and how far it is from the request |
| `horizontal_distance_from_base_m` | The target's and that pose's horizontal distance from the robot base |
| `orientation` | The orientation used: the requested `quaternion_wxyz`, or the current one kept |
| `home_orientation` | Whether the same position solves with the robot's home hand orientation, and that quaternion |

The solver searches locally from the current joint references, so these are
solver facts, not a proof of the reach limit or a suggested target. No object
state is used. The extra home-orientation solve runs only after the rejection;
accepted moves and execution are unchanged (`robofrontier/robot_control.py`,
reviewed in `benchmark/source-compatibility.json`).
