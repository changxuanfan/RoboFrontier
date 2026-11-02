# Continuing a run after an unexpected exit (run segments)

When a host, its world process or the whole batch exits unexpectedly, the run
continues once, automatically. The continued part is **the same trial**: the
same run directory, runtime database, workspace and model sessions, scored as
usual. Only the physical world is new, rebuilt approximately from the last
recorded motion frame. Both engines and all four topologies (centralized,
adaptive, hierarchical, peer) continue the same way.

## Segments

A run is one or more segments. The part before the exit is segment 0 and the
continuation is segment 1; a run continues at most once
(`run_segments.MAX_RETRIES`). The runtime database records:

- `segment`: the current segment number;
- `segments`: one record per segment, with start and end times, the end
  reason, the restore source (segment, frame and simulation time), downtime and
  the interrupted actions;
- `downtime_s`: total downtime.

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

`run_segments.retry_eligibility` allows a continuation only when the world
really died with time left:

- the layout has segments and the run has not continued before;
- the lifecycle is `running`, `interrupted` or `recovery_required`;
- there is no normal end: no finish, wall limit or budget close event, no
  STOP, and no seal made while the world was alive (a seal recorded after the
  world had already died does not count);
- the sources and frozen inputs are unchanged and there was no integrity abort;
- no process holds the world lock, so the old host and world are gone;
- a motion frame was recorded;
- more than 60 s of the wall limit remain, not counting downtime.

The Codex batch asks after every host exit, clean or not, because a host whose
world died seals the run and exits normally; the checks above tell the cases
apart. The Claude batch asks only when its supervisor reported
`owner_unavailable` or `world_interrupted`: a host stop at its own wall limit,
on STOP or after a finish is final, even if its seal could not be recorded.

A world process closes by itself once its parent (the host) is gone, so a
crashed host leaves no orphan holding the world lock.

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
   connection files; hosts wait for the new world to publish one.
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
  and starts its host again (`robofrontier/codex/batch.py` for Codex,
  `robofrontier/claude/engineering_batch.py` for Claude).
- **The batch process died too:** the world processes close by themselves.
  Then run the batch once more; started runs continue in their next segment and
  unstarted runs start:

  ```sh
  .venv/bin/python -m robofrontier.cli run BATCH --continue [--engineering]
  ```

- **Only the model process died while the world lives:** no segment; the world
  is untouched. The Codex host restarts the app-server and resumes each thread;
  a Claude role resumes its session once it has no action in flight. Both send
  the frozen `model-restart.md` notice, at most 3 times per run
  (`MAX_MODEL_RESTARTS`).

## Testing single-arm recovery: fault injection

`python -m robofrontier.fault_injection RUN --robot ARM|'*' --action-index N`
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
  (`run_segments.process_summary`). Dial puzzle progress such as the query
  count is not carried across; dial angles are restored with the pose.
- The two CLIs describe the cut-off tool call differently (Claude: outcome
  unknown; Codex: cancelled); the resume message is authoritative.

## Time

The effective deadline is `start_at + wall limit + downtime_s`: downtime does
not count against the wall limit. Downtime is the new segment's start minus the
previous segment's last activity (the later of the last database event written
while it was alive and the last host log line). Hosts write a few log lines
after the world dies, so downtime is underestimated by a few seconds.

## Reports and archives

- A report's `segments` field gives the segment count, whether the run
  continued, downtime and each segment's record. Tokens and costs add up per
  session; the cost of a turn cut off by the exit is counted as unreported.
- Continued runs count in comparisons as usual and are marked as continued.
- Motion readers and batch collection go through every segment's recording in
  order (`run_segments.motion_dirs`); the timeline is continuous.
- A run's transcripts are archived only once it can no longer continue
  ([evidence storage](evidence-storage.md#session-transcripts)).
