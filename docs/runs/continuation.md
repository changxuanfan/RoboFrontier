# Continuing a stopped run

A run that stops can continue. The continued part is **the same trial**: the same run folder,
runtime database, workspace and model sessions. Only the physical world is new. It is rebuilt
from the last recorded motion frame, so the restore is approximate. Both harnesses and all four
agent systems continue the same way.

- After an **unexpected** stop (a host, a world or a model session ended without a finish, a
  cutoff or a stop request), the batch continues the run by itself, **once** per run.
- After that, and after any other stop except an integrity abort, an operator continues the run
  by hand with `roboteam continue`, as often as needed.
- A continuation after the **finish** or the **cutoff** is marked `after_score`. The score stays
  the one recorded at that stop, and the continued part has no time limit.

Related pages: [time and pauses](time.md) says how the 24-hour limit is counted and when a run
pauses in place without a continuation. [Task recovery](recovery.md) covers a host that closed
while its world stayed paused.

The functions named `segments.*` below are in `roboteam/runtime/run/segments.py`.

## Segments

A **segment** is one uninterrupted stretch of a run, from a world starting to that world
ending. A run that never stops has one segment, numbered 0. Each continuation starts the next
segment. The runtime database (`private/state/runtime.sqlite`) records:

| Key | Content |
| --- | --- |
| `segment` | The current segment number |
| `segments` | One record per segment: start and end times, the end reason, the restore source (segment, frame and simulation time), downtime and the interrupted actions. For a continuation it also says whether it was `manual`, the `stop` it continued and whether it came `after_score` |
| `continuations` | One entry per continuation (segment, manual, stop, after_score) |
| `after_score` | Set once a continuation follows the finish or the cutoff |
| `downtime_s` | Total downtime |
| `active_s` | Active running time so far ([time](time.md)) |

`private/outputs/segments.json` is an exported copy.

## Files

```text
private/inputs/segments/<k>/restore-pose.npy    Pose segment k starts from (frozen, named in the manifest)
private/inputs/segments/<k>/restore-pose.json   Source segment, frame, simulation time, held grasps, what is missing
private/outputs/segments/<k>/                   Segment k's own outputs (k >= 1):
    motion/                                      motion recording (segment 0 keeps private/outputs/motion/)
    <camera>-realtime.mp4                        real-time video, when recording is on
    seal.json, interruption-evaluation*.json     the segment's closing record and its evaluation after the stop
```

Everything else continues in place: `private/state/runtime.sqlite` (calls, actions, messages,
work notes, delegations), `workspace/` (`skills.md` and the policy's own files), `public/`
(inputs unchanged, observations and results appended), the logs, `events.jsonl` and
`suite-process.jsonl` (appended, with segment boundary events), and `private/harness/` (the
sessions continue).

## When a run continues

`segments.stop_reason` says why the current segment ended, from this segment's own records.
`segments.STOP_REASONS` says what may follow:

| Stop | How it is recognized | Continues by itself | By hand | Scored at this stop |
| --- | --- | --- | --- | --- |
| `unexpected` | None of the below: a dead host or world, a session error, a pause the host gave up on, a live seal after a model failure | Once per run | Yes | No |
| `finish` | `TEAM_FINISH_PROPOSED` | No | Yes, marked `after_score` | Yes |
| `cutoff` | `POLICY_WALL_LIMIT` or `POLICY_BUDGET_CLOSED` | No | Yes, marked `after_score` | Yes |
| `wall_backstop` | `wall_backstop` in the runtime database ([wall backstop](time.md#wall-backstop)) | No | Yes; the backstop counts again from then | No (needs review) |
| `operator_stop` | The run's STOP marker | No | Yes; the STOP marker is lifted | No |
| `integrity_abort` | `integrity_valid` false or `INTEGRITY_ABORT`: a frozen input or source file changed | No | No | No |

`segments.retry_eligibility` also requires, either way:

- the lifecycle is `running`, `interrupted`, `recovery_required` or `ended` (not `prepared` or
  already `resuming`) and the run started;
- the sources and frozen inputs are unchanged;
- no process holds the world lock, so the old host and world are gone;
- a motion frame was recorded.

A continuation by itself needs three more things: more than 60 s of the limit left by the run's
own clock ([time](time.md)), no earlier continuation after the score, and no network review
hold. A network review hold (`egress_review_hold`, set with `NETWORK_CONTINUATION_UNCERTAIN`)
means a turn failed twice around one network pause and a person should look. Continuing a held
run by hand is that review: preparing the segment lifts the hold (`REVIEW_HOLD_LIFTED`).

The Codex batch asks whether a run may continue after every host exit, clean or not. The Claude
batch asks after every supervisor end except a stop request, its own wall limit, the wall
backstop, a world that ended, a launch error, a startup timeout and a finished run. The stop
table tells the cases apart.

A world process closes by itself once its parent (the host) is gone, so a crashed host leaves
no orphan holding the world lock.

## Continuing by hand

```sh
.venv/bin/roboteam continue runs/policy/my-batch                        # every run that may continue
.venv/bin/roboteam continue runs/policy/my-batch --cases dial-small-l1  # only these
```

The batch must not be running. Each run gets its next segment (`segments.prepare_retry` with
`manual`). The batch is reopened for exactly those runs; the others keep their final status. It
then runs as `run --continue` does: under launchd on macOS by default, with `--durable` as a
background service on Linux, or with `--foreground` in this process. Named runs that cannot
continue are refused with the reason. Without `--cases`, they are listed under `refused`.

A continuation after the finish or the cutoff first copies `evaluation.json`,
`budget-cutoff.json` and `evaluation-window.json` to `scored-*.json`. A later finish may
rewrite `evaluation.json`; the `scored-` copies stay. Such a segment has no time limit and no
wall backstop.

## How a run continues

1. **Settle the database** (`segments.prepare_retry`). Every unfinished action (running,
   uncertain, or accepted and not yet started) becomes failed with the reason "Interrupted by
   an unexpected host exit; the world was restored from the last recorded pose. Not replayed."
   Asking for such a call by its original ID returns that failure, with what was last observed
   of it and how it was settled. Leases of the old dispatcher are released. A delegation still
   being created ends as failed: its arms return to the parent, and the parent is told.
2. **Freeze the restore source.** The last motion frame of the previous segment becomes
   `restore-pose`, named in the manifest. The world records held grasps in the runtime database
   every second (`arm_holds`). A grasp is restored only from a record at most 5 s older than
   the frame, and only where the gripper opening in the pose still matches. The old world's
   address is removed from the connection files; hosts wait for the new world to publish one.
   For Dial, `restore-pose.json` also carries the game record at the frame (`evaluator`: valid
   trials, BEST, success, and whether a scored input was being held), read from the process
   log. If a segment ends before any motion frame is written, its own restore pose may stand
   in, but only when the source frame, time, scene, case and saved pose all match the previous
   recording exactly. No substitute frame is created; missing, changed or inconsistent restore
   records are errors.
3. **Start the world.** Seeing `resuming`, the world process builds the world from
   `restore-pose`. The simulation clock continues from the frame, and motion and video go to
   the segment's folder.
4. **Reopen the sessions.** The host resumes each role's session (Claude with
   `--resume <session ID>`, Codex with `thread/resume`). Both CLIs mark the tool call that had
   no result when the host stopped as interrupted or cancelled.
5. **Resume.** The host sends `resume`. The world records the segment start and the downtime
   and lifts the pause. The host then sends every role still at work the frozen resume message
   (`private/inputs/bootstrap/resume.md`, the same for both harnesses) and dispatches as usual.

Preparation follows a journal kept in the runtime database. If it stops part way (for example
the disk fills), calling it again completes the same segment, with the same restore frame and
end time, and uses no further continuation.

## Who starts the continuation

| What stopped | What happens |
| --- | --- |
| A host or a world, while the batch process lives | The batch checks after every run. If the run may continue, it prepares the next segment and starts the host again (`roboteam/launch/codex_batch.py`, `roboteam/launch/claude_batch.py`) |
| The batch process too | The world processes close by themselves. Run the batch once more with `--continue` (below): started runs continue in their next segment by the same stop table, and runs that never started start |
| Only the model process, while the world lives | No new segment; the world is untouched. The Codex host restarts its app-server and resumes each thread. A Claude role resumes its session once it has no action in flight. Both send the frozen `model-restart.md` notice, at most 3 times per run (`MAX_MODEL_RESTARTS`) |
| Anything else | Nothing continues by itself. Use `roboteam continue`, or [task recovery](recovery.md) for a host that closed on review while its world stayed paused |

```sh
.venv/bin/roboteam run runs/policy/my-batch --continue
```

## Known approximations

- Motion is written every 2 s, so the restore point can be up to about 2 s before the exit.
- Velocities, contact history and controller state are not kept.
- Process monitoring (collisions, violations) restarts its counts in the new segment. Reports
  combine each segment's last snapshot (`segments.process_summary`).
- The Dial game is history of the whole trial, so it continues. The new evaluator starts from
  the carried trial count, BEST and success, and the display shows that BEST at once. An input
  already scored and still held at the restore frame stays the same trial while it is held:
  blue support that was ready at that frame stays qualified, and a red knob held there is not
  a new contact. Trials scored after the restore frame were never physically kept and are not
  carried. Process logs mark the carried part (`carried_valid_trials`);
  `segments.dial_record` combines segments.
- A Relay timber's handovers and drops are history of the whole trial too, because completion
  requires a qualified handover. The new evaluator keeps those made up to the restore frame
  (`segments.relay_record`). A timber held at that frame becomes airborne again through the
  ordinary lift check, with the holders and the dropped state it had there. A receiver that
  joined before the frame must qualify again, and a timber dropped there may still only be
  lifted by the arms that held it.
- The two CLIs describe the cut-off tool call differently (Claude: outcome unknown; Codex:
  cancelled). The resume message is authoritative.

## Reports and archives

- A report's `segments` field gives the segment count, whether the run continued, the downtime
  and each segment's record. Tokens and costs add up per session. The cost of a turn cut off by
  the exit is counted as unreported.
- Continued runs count in comparisons as usual and are marked as continued.
- Motion readers and batch collection go through every segment's recording in order
  (`segments.motion_dirs`). The timeline is continuous.
- A run's transcripts are archived only once it can no longer continue
  ([evidence storage](evidence-storage.md#session-transcripts)).
