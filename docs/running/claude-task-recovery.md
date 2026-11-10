# Recover one Claude engineering task

`python -m robofrontier.engines.claude.recover_task` continues one task of a Claude
engineering batch whose host closed while its world was paused. It is the Claude
counterpart of [Codex task recovery](codex-task-recovery.md). Its default mode
only reports eligibility.

The typical case: a delegate's native fork misses its setup deadline, the
delegation becomes `needs_review`, dispatch pauses, and the supervisor ends the
task with `dispatch_paused`. The world keeps its lock but no model host remains,
and `run --continue` does not apply, because the batch has already handed the task
back as `needs_review`.

## Read-only inspection

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
- The run has not continued yet: a run continues at most once.
- No call or physical action is unsettled, and no delegation is still being created.
- Any delegation under review never started: every child is still `pending` and
  no child made a call.
- Recorded grasps are recent, and at least a minute of trial time is left.

## Execute

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
   shutdown (`run_seal.seal_run`): a final observation, then exit. It is never
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
   (`run_segments.prepare_retry` with the manual sealed-host exception) and checks
   that the call and action ledger is unchanged.
6. **Runs the frozen runner.** It starts the original runner
   (`claude.engineering_run.run_engineering`) from `SOURCE`, with that checkout's
   `.env` and the batch's frozen configuration. That runner restarts the world from
   the restore pose and resumes the Controller and every active delegate in their
   own sessions, each with its frozen resume message.

Everything else follows the [segment contract](run-segments.md): it is the same
trial, the restore is approximate (pose only), time between segments does not
count, and the trial's remaining active time still applies.

`private/state/control/recovery.json` records each phase. Its final phase is
`closed` or `needs_review`. Once an attempt starts changing the run (`prepared`),
it is never repeated. An attempt that stopped at a check before that point may be
run again; the record keeps it under `earlier_attempts`. The seal's own
`observe` and `shutdown` calls are not task calls and are left out of the ledger
comparison. Batches prepared from this version wait for a recovery in
progress before they close and collect. An older batch closes without waiting, so
collect its evidence once the recovered task has ended.

## Continue again with a runtime upgrade

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

## Validation

`tests/test_claude_task_recovery.py` covers:

- read-only inspection;
- refusal of a live session, an unsettled call, a started delegate and a task the
  batch still owns;
- a failed check leaving no segment;
- an execution that seals, returns the robots, prepares segment 1 with the ledger
  unchanged and launches the original runner;
- the batch waiting for a recovery to finish.

The physical restore check is the Codex one, which its tests run on a real Mosaic
scene. These tests make no model calls.
