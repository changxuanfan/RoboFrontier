# Task recovery

Task recovery continues **one run** whose model host closed while its world stayed paused, and
which the batch has already handed back as `needs_review`. `roboteam continue` and
`run --continue` do not apply to such a run while the paused world still holds its lock. Each
harness has its own command. Both only report eligibility unless `--execute` is given, and
neither repeats a recovery automatically.

| Harness | Command | Applies to |
| --- | --- | --- |
| Claude Code | `python -m roboteam.harness.claude.recover_task` | A run of a Claude batch on any host |
| Codex | `python -m roboteam.harness.codex.recover_task` | A run of a Codex Slurm subscription job, whose roles share one job gateway |

A recovered run follows the rules of every [continuation](continuation.md): it is the same
trial, the restore is approximate (pose only), the time between segments does not count, and
only the trial's remaining active time is left ([time](time.md)).

In the commands below, `RUN` is the run folder, `SOURCE` is the checkout the batch runs from
and `PYTHON` is that checkout's interpreter (`SOURCE/.venv/bin/python`).

## Claude task recovery

The typical case: a delegate's fork misses its setup deadline, the delegation becomes
`needs_review`, dispatch pauses, and the supervisor ends the run with `dispatch_paused`. The
world keeps its lock, but no model host remains.

### Inspect

```sh
.venv/bin/python -m roboteam.harness.claude.recover_task --run-dir "$RUN" \
  --source-root "$SOURCE" --python "$PYTHON"
```

This changes nothing. The run may recover only if all of these hold:

- The batch and the run both record a `needs_review` end with reason `dispatch_paused`,
  `session_error` or `session_unknown`.
- The run's runner lock is free and no Claude Code process names one of its sessions.
- No stop was requested and the run has not been recovered before.
- Integrity is valid and the frozen inputs match `SOURCE`.
- No call or physical action is unsettled, and no delegation is still being created.
- Any delegation under review never started: every child is still `pending` and no child made a
  call.
- Recorded grasps are recent, and at least a minute of trial time is left.

### Execute

`SCRATCH` must be a private folder (mode 0700) that the run's agents cannot reach, for example
`$RUN/private/harness/recovery-scratch`.

```sh
.venv/bin/python -m roboteam.harness.claude.recover_task --run-dir "$RUN" \
  --source-root "$SOURCE" --python "$PYTHON" --scratch "$SCRATCH" --execute
```

On macOS, `--execute` first inspects the run, then submits itself as a user launchd job with
Interactive priority under `caffeinate`, logged under
`private/state/control/recovery-durable-<time>/`, so it outlives the terminal that started it.
`--foreground` runs it in the current process instead, as on Linux. In order, it:

1. **Closes a live world.** A world that is still alive is sealed through its own shutdown
   (`seal_run` in `roboteam/runtime/world/seal.py`): a final observation, then exit. It is never
   killed, and no motion is replayed.
2. **Validates the restore.** It rebuilds the world from the last recorded pose on a private
   copy and checks the pose, zero velocity, simulation time and grasp holds, without stepping
   physics.
3. **Checks again and backs up.** It repeats the inspection and backs up the runtime database.
4. **Ends delegations that never started.** Each ends as failed. Its robots return to the
   parent, which is told through the usual `delegation_failed` signal. The child's session may
   exist on disk; it is kept and never resumed or forked again.
5. **Prepares the next segment** in the same run (`segments.prepare_retry`) and checks that the
   record of calls and actions is unchanged.
6. **Runs the frozen runner.** It starts the original runner
   (`roboteam.harness.claude.run.run_task`) from `SOURCE`, with that checkout's `.env` and the
   batch's frozen configuration. The runner restarts the world from the restore pose and
   resumes the Controller and every active delegate in their own sessions, each with the frozen
   resume message.

`private/state/control/recovery.json` records each phase. Its final phase is `closed` or
`needs_review`. Once an attempt starts changing the run (`prepared`), it is never repeated. An
attempt that stopped at a check before that point may be run again; the record keeps it under
`earlier_attempts`. The batch waits for a recovery in progress before it closes and collects.

Tests: `tests/harness/claude/test_claude_task_recovery.py`. They make no model calls.

## Codex task recovery

A Codex Slurm subscription job runs one shared Codex app-server behind a job gateway, and each
run talks to it over its own channel ([Slurm](../hosts/slurm.md)). This command recovers one
run that lost its channel. It does not restart the allocation, the shared app-server, another
run or the batch supervisor.

The job's running gateway must support recovery. A gateway that does not rejects the first
query, and the command stops before it prepares a segment, sends model input or dispatches a
robot call. Do not restart a shared gateway to work around this. A second app-server cannot
take over a thread while the original holds its writer lock, and copying sessions to get past
that lock is not this recovery.

### Inspect

Run inside the original allocation, with its original Python environment, Node.js, renderer and
filesystem layout. `SOURCE` is the job's own frozen source, not a development checkout.
`HARNESS` is the job gateway's folder.

```sh
.venv/bin/python -m roboteam.harness.codex.recover_task \
  --run-dir "$RUN" \
  --harness-manifest "$HARNESS/control/manifest.json" \
  --source-root "$SOURCE" \
  --python "$PYTHON"
```

The run may recover only if all of these hold:

- Its lifecycle is `interrupted`, physics is stopped, dispatch is paused and integrity is valid.
- Its last segment closed cleanly: sealed, with a fresh final observation, no unresolved action
  and no capture or shutdown error.
- The host log records the loss of the gateway channel, and the original host process is gone.
- No call or action is unsettled, no batch stop was requested, the frozen inputs are unchanged
  and a motion frame was recorded.
- The gateway itself reports this run closed, with no pending tool call or acknowledgement.

### Execute

Create `SCRATCH` with mode 0700 in a folder the run's agents cannot reach. Give the
allocation's real end as Unix seconds; the command refuses an allocation too short for the
remaining time plus closure.

```sh
.venv/bin/python -m roboteam.harness.codex.recover_task \
  --run-dir "$RUN" \
  --harness-manifest "$HARNESS/control/manifest.json" \
  --source-root "$SOURCE" \
  --python "$PYTHON" \
  --scratch "$SCRATCH" \
  --allocation-end "$ALLOCATION_END_UNIX_S" \
  --execute
```

Before it changes the run, the command builds the restored world on a private copy and checks
the joint positions, zero velocity, simulation time and every recent recorded grasp hold. It
steps no physics and calls no model in that check.

After another eligibility check it backs up the database, keeps the completed call and action
records, and prepares the next segment in the same run. It then grants one short-lived recovery
admission tied to this run and its exact original threads. The gateway uses the grant once,
checks that the original roles are inactive, and opens a new channel for the run; the old
channel stays retired. Thread IDs, roles, delegations, call IDs, the workspace and the frozen
file and network permissions stay in use. No old turn or physical action is submitted again.
The host sends the frozen resume messages, and later model decisions go through the normal
record of calls.

`private/state/control/recovery.json` records the recovery. The batch supervisor waits for it
to close before it stops the gateway or collects evidence. A failed or uncertain recovery needs
review; the command never repeats it.

Tests: `tests/harness/codex/test_codex_task_recovery.py`, and
`tests/harness/codex/test_slurm_gateway_native.py` with the installed CLI against a local stub.
They make no model calls.
