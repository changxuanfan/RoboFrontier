# Continuing a stopped run (run segments)

A run that stops can continue. The continued part is **the same trial**: the same
run directory, runtime database, workspace and model sessions. Only the physical
world is new, rebuilt approximately from the last recorded motion frame. Both
engines and all four topologies (centralized, adaptive, hierarchical, peer)
continue the same way.

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

## Files (run-v6)

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
segment boundary events), and `private/engine/` (sessions continue). Runs
prepared before run-v6 never continue.

## When a run continues

`run_segments.stop_reason` says why the current segment ended, from this segment's
own records, and `run_segments.STOP_REASONS` what may follow:

| Stop | How it is recognized | Continues by itself | By hand | Scored at this stop |
| --- | --- | --- | --- | --- |
| `unexpected` | none of the below: a dead host or world, a session error, a pause the host gave up on, a live seal after a model failure | once per run | yes | no |
| `finish` | `TEAM_FINISH_PROPOSED` | no | yes, marked `after_score` | yes |
| `cutoff` | `POLICY_WALL_LIMIT` or `POLICY_BUDGET_CLOSED` | no | yes, marked `after_score` | yes |
| `wall_backstop` | `wall_backstop` in the runtime database | no | yes; the backstop counts again from then | no (needs review) |
| `operator_stop` | the run's STOP marker | no | yes; the STOP marker is lifted | no |
| `integrity_abort` | `integrity_valid` false or `INTEGRITY_ABORT` | no | no | no |

`run_segments.retry_eligibility` also requires, either way:

- the lifecycle is `running`, `interrupted`, `recovery_required` or `ended`
  (not `prepared` or already `resuming`) and the run started;
- the sources and frozen inputs are unchanged;
- no process holds the world lock, so the old host and world are gone;
- a motion frame was recorded.

A continuation by itself further needs more than 60 s of the limit left, by the
run's own clock (see [Time](#time)), and none after a continuation past the score.

The Codex batch asks after every host exit, clean or not, and the Claude batch
after every supervisor end except its own wall limit, a STOP, a finished run or a
launch failure; the stop table tells the cases apart.

A world process closes by itself once its parent (the host) is gone, so a
crashed host leaves no orphan holding the world lock.

## Continuing by hand

```sh
.venv/bin/python -m robofrontier.cli continue BATCH                    # every run that may continue
.venv/bin/python -m robofrontier.cli continue BATCH --cases dial-a07-d1 # only these
```

The batch must not be running. Each run gets its next segment
(`run_segments.prepare_retry` with `manual`); the batch is reopened for exactly
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

1. **Settle the database** (`run_segments.prepare_retry`). Every unfinished
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
  .venv/bin/python -m robofrontier.cli run BATCH --continue
  ```

- **Only the model process died while the world lives:** no segment; the world
  is untouched. The Codex host restarts the app-server and resumes each thread;
  a Claude role resumes its session once it has no action in flight. Both send
  the frozen `model-restart.md` notice, at most 3 times per run
  (`MAX_MODEL_RESTARTS`).
- **Any other stop:** nothing continues by itself; `robofrontier continue`
  (above). A host that closed on review while its world stayed paused can also be
  recovered in place: [Claude](claude-task-recovery.md) or
  [Codex](codex-task-recovery.md) task recovery.

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
  (`run_segments.process_summary`).
- The Dial game is episode history, so it continues: the new evaluator starts
  from the carried trial count, BEST and success, and the display shows that
  BEST at once. An input already scored and still held at the restore frame
  stays the same trial while it is held on: blue support ready at that frame stays
  qualified, and a red knob held there is not a new (premature) contact. Trials scored after the restore
  frame were never physically kept and are not carried. Process logs mark the
  carried part (`carried_valid_trials`); `run_segments.dial_record` combines
  segments, including runs continued before this existed (their later segment
  counted from zero, so its trials are added and BEST is the maximum).
- A Relay timber's handovers and drops are episode history too, because completion
  requires a qualified handover. The new evaluator keeps those made up to the restore
  frame (`run_segments.relay_record`). A timber held at that frame becomes airborne
  again through the ordinary lift check, keeping the custody and dropped state it had
  there: a receiver joining before the frame must qualify again, and a timber dropped
  there may still only be lifted by its holders.
- The two CLIs describe the cut-off tool call differently (Claude: outcome
  unknown; Codex: cancelled); the resume message is authoritative.

## Time

The 24-hour limit (`run_protocol.total_wall_limit_s`) is **the time the trial is
actually running**. A continuation is the same trial, so its time adds to the
time already used. The frozen `run_protocol.clock` says how a run counts it.

### Active time (`clock: active_time_v1`, every new policy run)

The world owner adds up active time tick by tick (`policy_probe.BudgetGuard`).
An interval counts only while the lifecycle is `running`, physics is `running`
and dispatch is not paused (`policy_probe.counting`). It does not count:

- a pause by the experiment manager, the budget cutoff itself, an egress review
  hold;
- a Slurm egress pause or a network-outage pause (below);
- a stall: when the owner's previous tick is more than 5 s ago
  (`policy_probe.STALL_S`), the gap adds nothing and is recorded as an
  `ACTIVE_TIME_STALL` event. Ticks normally come every few milliseconds, so this
  catches a frozen or suspended host and a machine that slept;
- the time between segments, when no owner runs.

The total is saved as `active_s` in the runtime database at least every second,
at the cutoff and when the owner closes. A continued segment or a restarted owner
starts from the saved value; it never recomputes the deadline from wall time, so
a sleep or crash is never counted again. The cutoff fires when `active_s` reaches
the limit. `budget-cutoff.json` and `evaluation.json` record `active_s` /
`budget_active_s` and the clock; a continuation by itself needs at least 60 s of
active time left (`run_segments.remaining_s`).

`downtime_s` is still recorded (segment gaps and pauses) for reports; it no longer
enters the limit. The public task does not state the clock, as it does not state
the limit.

The Claude supervisor leaves the end to the world: it ends a run on its own only
60 s of active time past the limit, and waits for an outage or egress pause
instead of sealing the paused run. The Codex host never had its own limit.

### Wall backstop

Active time does not advance while a world is paused or its host is frozen, so it
alone would never end a run held forever. New policy runs therefore also freeze
`run_protocol.wall_backstop_s` (172,800 s, `task_families.WALL_BACKSTOP_S`;
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
backstop then counts again from that moment. Runs frozen without the field
(every START-wall-time run, and active-time runs frozen before it) have no
backstop.

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
enough: a local VPN tunnel accepts it even when its route to the API is gone, which
on 2026-11-10 let eight runs fail their turns instead of pausing. After three consecutive
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
([Claude network continuation](../engines/claude-code.md#engineering-run-status-and-stop)). The resent turn
continues the same session and replays nothing; a second failure in the same
pause, or a failure for another reason within it, holds the run for review.

The probe pauses only a running trial (not before START or after the cutoff). It
is off for runs with a Slurm egress pause, for frozen START-wall-time runs, and
with `ROBOFRONTIER_OUTAGE_PROBE=off` (the test suite sets this). A pause has no
time limit of its own. A probe
that never succeeds, because the world process has no direct route out, never
pauses: after 12 failures it stops and records `OUTAGE_PROBE_UNAVAILABLE`.

### Usage-limit pause (every platform)

A subscription's 5-hour or weekly limit lasts until its reset, so it is not retried
like a short rate limit. When a model turn fails on it (`runtime/quota.py`: Claude
Code's "You've hit your … limit · resets …" or "usage limit reached|<time>", Codex's
`usageLimitExceeded` or "try again at/in …"), the host reads the reset time and asks
the world to pause (`runtime_cli quota-pause`, `QUOTA_PAUSE_REQUESTED`). The world
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

### START wall time (frozen runs without `clock`)

Runs frozen before the active-time clock keep their terms exactly. The effective
deadline is `start_at + wall limit + downtime_s`: downtime does not count against
the wall limit. Downtime is the new segment's start minus the previous segment's
last activity (the later of the last database event written while it was alive
and the last host log line), plus Slurm egress pauses. Hosts write a few log lines
after the world dies, so downtime is underestimated by a few seconds. A stall or a
sleep inside a segment counts.

## Reports and archives

- A report's `segments` field gives the segment count, whether the run
  continued, downtime and each segment's record. Tokens and costs add up per
  session; the cost of a turn cut off by the exit is counted as unreported.
- Continued runs count in comparisons as usual and are marked as continued.
- Motion readers and batch collection go through every segment's recording in
  order (`run_segments.motion_dirs`); the timeline is continuous.
- A run's transcripts are archived only once it can no longer continue
  ([evidence storage](evidence-storage.md#session-transcripts)).
