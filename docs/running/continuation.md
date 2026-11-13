# Continuing a stopped run (run segments)

A run that stops can continue. The continued part is **the same trial**: the same
run directory, runtime database, workspace and model sessions. Only the physical
world is new, rebuilt approximately from the last recorded motion frame. Both
engines and all four topologies (single, controller-worker, worker-worker,
adaptive) continue the same way. The functions named `segments.*` below are in
`robofrontier/runtime/segments.py`.

- After an **unexpected** stop (a host, world or model session ended without a
  finish, cutoff or STOP) the batch continues the run by itself, **once** per run.
- After that, and after **any** other stop but an integrity abort, an operator
  continues it by hand with `robofrontier continue`, as often as needed.
- A continuation after the **finish** or the **cutoff** is marked `after_score`:
  the score stays the one recorded at that stop, and the continued segment has no
  time limit.

## Segments

A run is one or more segments, numbered from 0. The runtime database records:

- `segment`: the current segment number;
- `segments`: one record per segment, with start and end times, the end
  reason, the restore source (segment, frame and simulation time), downtime and
  the interrupted actions, and for a continuation whether it was `manual`, the
  `stop` it continued and whether it came `after_score`;
- `continuations`: one entry per continuation (segment, manual, stop, after_score);
- `after_score`: set once a continuation follows the finish or the cutoff;
- `downtime_s`: total downtime;
- `active_s`: active running time so far, for runs whose limit counts it (see
  [Time](#time)).

`private/outputs/segments.json` is an exported copy.

## Files

```
private/inputs/segments/<k>/restore-pose.npy    Pose segment k starts from (frozen, bound in the manifest)
private/inputs/segments/<k>/restore-pose.json   Source segment, frame, sim time, held grasps, what is missing
private/outputs/segments/<k>/                   Segment k's own process outputs (k >= 1):
    motion/                                      motion recording (segment 0 keeps private/outputs/motion/)
    <camera>-realtime.mp4                        real-time video
    seal.json, interruption-evaluation*.json     seal and post-mortem evaluation of that segment
```

Everything else continues in place: `private/state/runtime.sqlite` (calls,
actions, messages, work notes, delegations), `workspace/` (`skills.md` and the
policy's own files), `public/` (inputs unchanged, observations and results
appended), the logs, `events.jsonl` and `suite-process.jsonl` (appended, with
segment boundary events), and `private/engine/` (sessions continue).

## When a run continues

`segments.stop_reason` says why the current segment ended, from this segment's
own records, and `segments.STOP_REASONS` what may follow:

| Stop | How it is recognized | Continues by itself | By hand | Scored at this stop |
| --- | --- | --- | --- | --- |
| `unexpected` | none of the below: a dead host or world, a session error, a pause the host gave up on, a live seal after a model failure | once per run | yes | no |
| `finish` | `TEAM_FINISH_PROPOSED` | no | yes, marked `after_score` | yes |
| `cutoff` | `POLICY_WALL_LIMIT` or `POLICY_BUDGET_CLOSED` | no | yes, marked `after_score` | yes |
| `wall_backstop` | `wall_backstop` in the runtime database | no | yes; the backstop counts again from then | no (needs review) |
| `operator_stop` | the run's STOP marker | no | yes; the STOP marker is lifted | no |
| `integrity_abort` | `integrity_valid` false or `INTEGRITY_ABORT` | no | no | no |

`segments.retry_eligibility` also requires, either way:

- the lifecycle is `running`, `interrupted`, `recovery_required` or `ended`
  (not `prepared` or already `resuming`) and the run started;
- the sources and frozen inputs are unchanged;
- no process holds the world lock, so the old host and world are gone;
- a motion frame was recorded.

A continuation by itself further needs more than 60 s of the limit left, by the
run's own clock (see [Time](#time)), none after a continuation past the score, and
no network review hold (`egress_review_hold`, from `NETWORK_CONTINUATION_UNCERTAIN`).
Continuing a held run by hand is the operator's review: preparing the segment lifts
the hold (`REVIEW_HOLD_LIFTED`), since a new world never serves its own resume
request while held.

The Codex batch asks after every host exit, clean or not, and the Claude batch
after every supervisor end except its own wall limit, a STOP, a finished run or a
launch failure; the stop table tells the cases apart.

A world process closes by itself once its parent (the host) is gone, so a
crashed host leaves no orphan holding the world lock.

## Continuing by hand

```sh
.venv/bin/robofrontier continue BATCH                          # every run that may continue
.venv/bin/robofrontier continue BATCH --cases dial-best5-n04-d1  # only these
```

The batch must not be running. Each run gets its next segment
(`segments.prepare_retry` with `manual`); the batch is reopened for exactly
those runs (the others keep their final status) and runs them as
`run --continue` does: under launchd on macOS by default, with `--durable` as a
background service on Linux, or `--foreground` in this process. Named runs that
cannot continue are refused with the reason; without `--cases`, they are listed
under `refused`.

A continuation after the finish or the cutoff copies `evaluation.json`,
`budget-cutoff.json` and `evaluation-window.json` to `scored-*.json` first; a later
finish may rewrite `evaluation.json`, the `scored-` copies stay. The world's budget
guard and the Claude supervisor set no limit and no backstop for such a segment.

## How a run continues

1. **Settle the database** (`segments.prepare_retry`). Every unfinished
   action (running, uncertain, or accepted and not yet started) becomes failed
   with the reason "Interrupted by an unexpected host exit; the world was
   restored from the last recorded pose. Not replayed." Asking for such a call
   by its original ID returns that definite failure, with what was last observed
   of it and how it was settled. Leases of the old dispatcher are released.
   A delegation still being created ends as failed, its arms return to the
   parent and the parent is told.
2. **Freeze the restore source.** The last motion frame of the previous segment
   becomes `restore-pose`, bound in the manifest. The world records held grasps
   in the runtime database every second (`arm_holds`); a grasp is restored only
   from a record at most 5 s older than the frame and only where the gripper
   opening in the pose still matches. The old world's address is removed from the
   connection files; hosts wait for the new world to publish one. For Dial,
   `restore-pose.json` also carries the game record at the frame (`evaluator`:
   valid trials, BEST, success, and whether a scored input was being held),
   read from the shared process log.
3. **Start the world.** Seeing `resuming`, the world process builds the world
   from `restore-pose`; the simulation clock continues from the frame, and
   motion and video go to the segment's folder.
4. **Reopen the sessions.** The host resumes each role's session (Claude with
   `--resume <session ID>`, Codex with `thread/resume`). Both CLIs mark the tool
   call that had no result when the host stopped as interrupted or cancelled.
5. **Resume.** The host sends `resume`; the world records the segment start and
   the downtime and lifts the pause. The host then sends every role still at
   work the frozen resume message (`private/inputs/bootstrap/resume.md`, the
   same for both engines) and dispatches as usual.

Preparation follows a journal kept in the runtime database: if it stops part
way (for example the disk fills), calling it again completes the same segment,
with the same restore frame and end time, and uses no further continuation.

## Who starts the continuation

- **A host or world exits while the batch process lives:** the batch runner
  checks after every run and, if the run may continue, prepares its next segment
  and starts its host again (`robofrontier/batch/codex_batch.py` for Codex,
  `robofrontier/batch/claude_batch.py` for Claude).
- **The batch process died too:** the world processes close by themselves.
  Then run the batch once more; started runs continue in their next segment (by
  the same stop table) and unstarted runs start:

  ```sh
  .venv/bin/robofrontier run BATCH --continue
  ```

- **Only the model process died while the world lives:** no segment; the world
  is untouched. The Codex host restarts the app-server and resumes each thread;
  a Claude role resumes its session once it has no action in flight. Both send
  the frozen `model-restart.md` notice, at most 3 times per run
  (`MAX_MODEL_RESTARTS`).
- **Any other stop:** nothing continues by itself; `robofrontier continue`
  (above). A host that closed on review while its world stayed paused can also be
  recovered in place: [Claude](continuation.md#claude-task-recovery) or
  [Codex](continuation.md#codex-task-recovery) task recovery.

## Testing single-arm recovery: fault injection

`python -m robofrontier.runtime.fault_injection RUN --robot ARM|'*' --action-index N`
freezes one fault before the run starts: the N-th independent action of that arm
(or of any arm, with `*`) times out quickly and, once stopping, stays unsettled
for a set time, so it becomes an uncertain action with local recovery, and
`recover_action` confirms the stop only afterwards. The setting lives in
`private/inputs/fault-injection.json`, which the policy cannot read, is bound in
the manifest, and marks the run's report as fault-injected. Engineering runs
only.

## Known approximations

- Motion is written every 2 s, so the restore point can be up to about 2 s
  before the exit.
- Velocities, contact history and controller state are not kept.
- Process monitoring (collisions, violations) restarts its counts in the new
  segment; reports combine each segment's last snapshot
  (`segments.process_summary`).
- The Dial game is episode history, so it continues: the new evaluator starts
  from the carried trial count, BEST and success, and the display shows that
  BEST at once. An input already scored and still held at the restore frame
  stays the same trial while it is held on: blue support ready at that frame stays
  qualified, and a red knob held there is not a new (premature) contact. Trials scored after the restore
  frame were never physically kept and are not carried. Process logs mark the
  carried part (`carried_valid_trials`); `segments.dial_record` combines
  segments.
- A Relay timber's handovers and drops are episode history too, because completion
  requires a qualified handover. The new evaluator keeps those made up to the restore
  frame (`segments.relay_record`). A timber held at that frame becomes airborne
  again through the ordinary lift check, keeping the custody and dropped state it had
  there: a receiver joining before the frame must qualify again, and a timber dropped
  there may still only be lifted by its holders.
- The two CLIs describe the cut-off tool call differently (Claude: outcome
  unknown; Codex: cancelled); the resume message is authoritative.

## Time

The 24-hour limit (`run_protocol.total_wall_limit_s`) is **the time the trial is
actually running**. A continuation is the same trial, so its time adds to the
time already used. The frozen `run_protocol.clock` says how a run counts it.

### Active time (`clock: active_time_v1`)

Every policy run counts active time. The world owner adds it up tick by tick
(`BudgetGuard` in `robofrontier/runtime/clock.py`). An interval counts only while
the lifecycle is `running`, physics is `running` and dispatch is not paused
(`clock.counting`). It does not count:

- a pause by the experiment manager, the budget cutoff itself, an egress review
  hold;
- a Slurm egress pause or a network-outage pause (below);
- a stall: when the owner's previous tick is more than 5 s ago
  (`clock.STALL_S`), the gap adds nothing and is recorded as an
  `ACTIVE_TIME_STALL` event. Ticks normally come every few milliseconds, so this
  catches a frozen or suspended host and a machine that slept;
- the time between segments, when no owner runs.

The total is saved as `active_s` in the runtime database at least every second,
at the cutoff and when the owner closes. A continued segment or a restarted owner
starts from the saved value; it never recomputes the deadline from wall time, so
a sleep or crash is never counted again. The cutoff fires when `active_s` reaches
the limit. `budget-cutoff.json` and `evaluation.json` record `active_s` /
`budget_active_s` and the clock; a continuation by itself needs at least 60 s of
active time left (`segments.remaining_s`).

`downtime_s` is recorded (segment gaps and pauses) for reports; it does not enter
the limit. The public task does not state the clock, as it does not state
the limit.

The Claude supervisor leaves the end to the world: it ends a run on its own only
60 s of active time past the limit, and waits for an outage or egress pause
instead of sealing the paused run. The Codex host has no limit of its own.

### Wall backstop

Active time does not advance while a world is paused or its host is frozen, so it
alone would never end a run held forever. Policy runs therefore also freeze
`run_protocol.wall_backstop_s` (172,800 s, `WALL_BACKSTOP_S` in `robofrontier/tasks/families.py`;
private, like the limit). The backstop counts wall time since START
(`clock.backstop_elapsed`) **less every outage, egress and usage-limit pause**
(`pause_wall_s` and the current `pause_since_wall` in the runtime database): such a
wait is not the run's fault. If that much counted wall time has passed and the
active-time cutoff has not fired, the world owner stops the run exactly like a
cutoff (dispatch paused, arms braked, the run closed after the braking grace), even
during an operator pause or review hold. The records differ, so the stop
is not a normal end:

- a `POLICY_WALL_BACKSTOP` event (not `POLICY_WALL_LIMIT`) and
  `POLICY_BACKSTOP_CLOSED` (not `POLICY_BUDGET_CLOSED`); `wall_backstop` in the
  runtime database;
- `budget-cutoff.json` with `wall_backstop: true` and `needs_review: true`;
  `evaluation.json` with `termination_reason: wall_backstop`,
  `wall_backstop: true`, `needs_review: true` and `budget_exhausted: false`.

Its result needs review and is not counted. The Claude supervisor reports
`ended_by: wall_backstop` (or reason `wall_backstop` when it had to end a world
that did not close itself 150 s after the backstop) and the run's status is
`needs_review`; both batches mark the job `needs_review` with reason
`wall_backstop`. Run analysis keeps the cutoff's `wall_backstop` flag and
`metrics.compute` sets `excluded: wall_backstop` and `needs_review`; the
`compute` command lists such runs as `EXCLUDED`.

A backstopped run never continues by itself. It continues by hand
(`robofrontier continue`, or the stopped-runtime upgrade path with its
`manual_authorization`). Its continuation moves the backstop's `budget-cutoff.json` and `evaluation.json` aside (with
`-wall-backstop-N` in their names), records `WALL_BACKSTOP_WAIVED`, and the
backstop then counts again from that moment.

### Network-outage pause

A run without a Slurm egress pause (a Mac, a RunPod host, or a Slurm job with direct
egress) has no route watcher to pause its world, so its world owner probes the model
API hosts (`robofrontier/runtime/outage.py`): the host of the run's profile
`base_url` when it has one, else the engine's own, Claude `api.anthropic.com` and
Codex `chatgpt.com` and `auth.openai.com`, all of which must answer. A Slurm job on
the `mac-ssh` route keeps its egress pause (`slurm.egress_pause_s`, by default as
long as the wall backstop). A probe is a
verified TLS handshake on port 443 followed by an HTTP `HEAD /` that must get an
answer (any status), every 5 s, with a 5 s timeout. A bare TCP connection is not
enough: a local VPN tunnel accepts it even when its route to the API is gone. After three consecutive
failures the world pauses exactly like a Slurm egress pause: physics stops
stepping (arms hold mid-motion), dispatch is paused, new policy requests wait with
their original call IDs, and an `OUTAGE_PAUSED` event is written. The time since
the first failed probe of that streak is taken back from `active_s`
(`retracted_active_s` in the event). The first successful probe resumes the same
world (`OUTAGE_RESUMED`), with the same ownership and integrity checks as an
egress resume and no replay; an operator pause made meanwhile is kept
(`OUTAGE_HELD_FOR_REVIEW`). The resume is recorded as `egress_recovery`, so a
turn that failed on the network during the pause gets its one network
continuation per role and pause, as after an egress pause: Codex resends it when
the app-server reports a transport failure, Claude when the CLI's structured API
error names a lost connection or does not say what failed
([Claude network continuation](../engines/claude-code.md#run-status-and-stop)). The resent turn
continues the same session and replays nothing; a second failure in the same
pause, or a failure for another reason within it, holds the run for review.

The probe pauses only a running trial (not before START or after the cutoff). It
is off for runs with a Slurm egress pause and with `ROBOFRONTIER_OUTAGE_PROBE=off` (the test suite sets this). A pause has no
time limit of its own. A probe
that never succeeds, because the world process has no direct route out, never
pauses: after 12 failures it stops and records `OUTAGE_PROBE_UNAVAILABLE`.

<a id="usage-limit-pause"></a>

### Usage-limit pause (every platform)

A subscription's 5-hour or weekly limit lasts until its reset, so it is not retried
like a short rate limit. When a model turn fails on it (`runtime/quota.py`: Claude
Code's "You've hit your … limit · resets …" or "usage limit reached|<time>", Codex's
`usageLimitExceeded` or "try again at/in …"), the host reads the reset time and asks
the world to pause (the `quota-pause` operation of `robofrontier/runtime/cli.py`, `QUOTA_PAUSE_REQUESTED`). The world
pauses exactly as in an outage (`QUOTA_PAUSED`): physics and dispatch held, original
calls kept, the time counted neither as active time nor by the wall backstop. A second
role's request joins the first (the later reset wins). The world resumes by itself a
minute after the reset, or 30 minutes after pausing when no reset time was readable
(`QUOTA_RESUMED`); an operator pause made meanwhile is kept (`QUOTA_HELD_FOR_REVIEW`).
Then each role whose turn failed on the limit continues once in the same session with
the frozen `quota-resume.md` (the network-continuation claim, one per role and pause);
a limit hit again pauses again. It is the same segment: no continuation is used.

The operator is told at the pause and the resume: a line in
`private/outputs/notifications.jsonl` and, on macOS, a desktop notification
(`ROBOFRONTIER_NO_NOTIFY=1` turns that off).

### Capacity retries

A short capacity or rate limit (HTTP 429, overloaded) is retried by the host itself in
the same session, at most 3 times per role (`bootstrap.MAX_CAPACITY_RETRIES`), after
10, 20 and 40 s plus a jitter, with the frozen `capacity-resume.md`; the same on both
engines. When the retries are used up, both hosts pause dispatch
(`DISPATCH_PAUSED`, "Model capacity recovery attempts exhausted"); the run then ends
as an unexpected stop and continues by itself once (see the stop table).

## Reports and archives

- A report's `segments` field gives the segment count, whether the run
  continued, downtime and each segment's record. Tokens and costs add up per
  session; the cost of a turn cut off by the exit is counted as unreported.
- Continued runs count in comparisons as usual and are marked as continued.
- Motion readers and batch collection go through every segment's recording in
  order (`segments.motion_dirs`); the timeline is continuous.
- A run's transcripts are archived only once it can no longer continue
  ([evidence storage](evidence-storage.md#session-transcripts)).

## Claude task recovery

`python -m robofrontier.engines.claude.recover_task` continues one task of a Claude
engineering batch whose host closed while its world was paused. It is the Claude
counterpart of [Codex task recovery](#codex-task-recovery). Its default mode
only reports eligibility.

The typical case: a delegate's native fork misses its setup deadline, the
delegation becomes `needs_review`, dispatch pauses, and the supervisor ends the
task with `dispatch_paused`. The world keeps its lock but no model host remains,
and `run --continue` does not apply, because the batch has already handed the task
back as `needs_review`.

### Read-only inspection

Run from any checkout, against the original one. `SOURCE` is the checkout the
batch runs from, and `PYTHON` is its interpreter.

```sh
python -m robofrontier.engines.claude.recover_task --run-dir "$RUN" --source-root "$SOURCE" --python "$PYTHON"
```

The task may recover only if every one of these holds:

- The batch and the run both record a `needs_review` end with reason
  `dispatch_paused`, `session_error` or `session_unknown`.
- The run's runner lock is free and no native CLI process names one of its sessions.
- No stop was requested and the task has not been recovered before.
- Integrity is valid and the frozen inputs match `SOURCE`.
- No call or physical action is unsettled, and no delegation is still being created.
- Any delegation under review never started: every child is still `pending` and
  no child made a call.
- Recorded grasps are recent, and at least a minute of trial time is left.

### Execute

`SCRATCH` must be a private directory (mode 0700) that the task's frozen access
table denies, for example `$RUN/private/engine/recovery-scratch`.

```sh
python -m robofrontier.engines.claude.recover_task --run-dir "$RUN" --source-root "$SOURCE" \
  --python "$PYTHON" --scratch "$SCRATCH" --execute
```

On macOS, `--execute` first inspects the run, then submits itself as a user launchd job
with Interactive priority under `caffeinate`, logged under
`private/state/control/recovery-durable-<time>/`. It therefore outlives the terminal or the
agent session that started it. `--foreground` runs it in the current process instead,
as on Linux. In order, it:

1. **Seals a live world.** A world that is still alive is sealed through its own
   shutdown (`seal_run` in `robofrontier/runtime/seal.py`): a final observation, then exit. It is never
   killed, and no motion is replayed.
2. **Validates the restore.** It rebuilds the world from the last recorded pose on
   a private copy and checks the pose, zero velocity, simulation time and grasp
   holds, without stepping physics.
3. **Checks again and backs up.** It repeats the inspection and backs up the
   runtime database.
4. **Ends never-started delegations.** Each one ends as failed: its robots return
   to the parent, which is told through the usual `delegation_failed` signal. The
   native fork may exist on disk; it is kept and never resumed or forked again.
5. **Prepares the next segment.** It prepares the segment in the same run
   (`segments.prepare_retry` with the manual sealed-host exception) and checks
   that the call and action ledger is unchanged.
6. **Runs the frozen runner.** It starts the original runner
   (`robofrontier.engines.claude.run.run_task`) from `SOURCE`, with that checkout's
   `.env` and the batch's frozen configuration. That runner restarts the world from
   the restore pose and resumes the Controller and every active delegate in their
   own sessions, each with its frozen resume message.

Everything else follows the [segment contract](continuation.md): it is the same
trial, the restore is approximate (pose only), time between segments does not
count, and the trial's remaining active time still applies.

`private/state/control/recovery.json` records each phase. Its final phase is
`closed` or `needs_review`. Once an attempt starts changing the run (`prepared`),
it is never repeated. An attempt that stopped at a check before that point may be
run again; the record keeps it under `earlier_attempts`. The seal's own
`observe` and `shutdown` calls are not task calls and are left out of the ledger
comparison. The batch waits for a recovery in progress before it closes and
collects.

### Continue again with a runtime upgrade

A run that has already continued, or was recovered before, continues only through
the explicit stopped-runtime upgrade (`runtime_upgrade`). `--upgrade-from` names
the checkout the run is frozen on; `--source-root` is the newer checkout it moves
to; `--reason` is required. Run the command with the newer checkout's interpreter,
given as `--python`, because the upgrade grants the policy read access to that
environment.

```sh
"$NEW/.venv/bin/python" -m robofrontier.engines.claude.recover_task --run-dir "$RUN" \
  --upgrade-from "$OLD" --source-root "$NEW" --python "$NEW/.venv/bin/python" \
  --scratch "$SCRATCH" --reason "Why the runtime changes" --execute
```

The steps are the same, with one addition. After validation and the backup, the
upgrade freezes the new runtime into the run and writes a one-segment
authorization under `private/inputs/runtime-upgrades/<segment>/`. Only robofrontier
source files may change, never prompts, task inputs or documentation. Preparing
the segment consumes the authorization. The task inputs and the call/action ledger
are unchanged.

Keep the new checkout where the run's frozen access table denies it (for example
under `~/.robofrontier/`). That table reads `/` by default and denies only the
checkouts that existed when the batch was prepared.

### Validation

`tests/runtime/test_claude_task_recovery.py` covers:

- read-only inspection;
- refusal of a live session, an unsettled call, a started delegate and a task the
  batch still owns;
- a failed check leaving no segment;
- an execution that seals, returns the robots, prepares segment 1 with the ledger
  unchanged and launches the original runner;
- the batch waiting for a recovery to finish.

The physical restore check is the Codex one, which its tests run on a real Mosaic
scene. These tests make no model calls.

## Codex task recovery

`python -m robofrontier.engines.codex.recover_task` is an explicit, single-task entrypoint.
Its default mode only reports eligibility. It does not restart the allocation,
the shared native app-server, another task, or the batch supervisor. The same
native process remains the sole subscription refresh owner.

The batch's running gateway must support recovery; a checkout change does not
alter a running gateway. A gateway without it rejects the read-only capability
query, and the entrypoint stops before segment preparation, model input or robot
dispatch.
Do not restart a shared engine to work around this rejection. A second native
server also cannot take over a thread while the original server holds its writer
lock; copying sessions to bypass that lock is not this recovery protocol.

### Read-only inspection

Run inside the original allocation, with its original Python environment, Node,
renderer and filesystem layout available. `SOURCE` is the original immutable
runtime, not the synchronized development checkout. `PYTHON` is its interpreter.

```sh
python -m robofrontier.engines.codex.recover_task \
  --run-dir "$RUN" \
  --engine-manifest "$ENGINE/control/manifest.json" \
  --source-root "$SOURCE" \
  --python "$PYTHON"
```

Only an integrity-valid interrupted task with a clean final seal, a dead original
host, a free world lock, unchanged frozen inputs and no unsettled calls/actions
can proceed. A normal finish, STOP, expired budget, previous continuation or
missing recording still blocks recovery. A recorded gateway-channel loss is
required for the manual exception to a seal made while the world was alive.
The gateway must independently report this task closed, with no pending tool or
native acknowledgement. Other tasks' channels cannot use the control queries.

### Execute after inspection

Create `SCRATCH` with mode 0700 inside a root denied by the task's frozen access
table. Supply the actual allocation expiry as Unix seconds. Execution refuses
an allocation too short for the remaining budget plus closure time.

```sh
python -m robofrontier.engines.codex.recover_task \
  --run-dir "$RUN" \
  --engine-manifest "$ENGINE/control/manifest.json" \
  --source-root "$SOURCE" \
  --python "$PYTHON" \
  --scratch "$SCRATCH" \
  --allocation-end "$ALLOCATION_END_UNIX_S" \
  --execute
```

Before changing the original run, execution constructs its restored world on a
private copy and verifies qpos, zero velocity, simulation time and every recent
recorded grasp hold. It performs no physics step or model call in that check.
The recording is a float32 pose recording, not a complete physics checkpoint:
velocity, controller history and contact history are unavailable. The continued
segment records this approximate restoration explicitly.

After another eligibility check, the entrypoint backs up the database, preserves
completed call/action receipts, and prepares segment 1 in the same run. It grants
one short-lived recovery admission bound to this task and its exact original
thread inventory. The gateway consumes the grant before native inspection,
checks that original roles are inactive, and binds a new task channel. Old task
sockets remain retired. Original thread IDs, role/delegation state, call IDs,
workspace and frozen file/network permissions remain in use. No old turn or
physical action is submitted again; the original host sends the frozen segment
resume messages and subsequent model decisions use the normal durable ledger.

Time between segments is not active time, and recovery does not grant a fresh
24 hours. The allocation must cover
the remaining time. `private/state/control/recovery.json` records the separate
recovery lifecycle. The batch supervisor waits for recovery ownership to close
before stopping its engine or collecting evidence. A failed/uncertain recovery
requires review; the entrypoint never automatically repeats it.

### Validation

`tests/runtime/test_codex_task_recovery.py` covers read-only inspection, refusal of old
gateways and unsettled actions, unchanged completed receipts, and a real private
Mosaic pose/grasp reconstruction without advancing physics. Gateway tests cover
single-use authority, active-role refusal, retired sockets and peer containment.
`tests/engines/test_slurm_gateway_native.py` uses the real pinned CLI with synthetic
loopback authentication and inference: 36 independent channels, a closed task
rebound to its original native thread, resumed tools, another fork, transcript
collection, unchanged peer access and one native credential owner. These tests
make no calls to a real model or running physical task.
