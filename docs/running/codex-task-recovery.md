# Recover one managed Codex task

`python -m robofrontier.engines.codex.recover_task` is an explicit, single-task entrypoint.
Its default mode only reports eligibility. It does not restart the allocation,
the shared native app-server, another task, or the batch supervisor. The same
native process remains the sole subscription refresh owner.

The gateway and frozen policy host must have supported recovery when the batch
was prepared and started. Synchronizing a checkout does not upgrade an already
running gateway. An older gateway rejects the read-only capability query, and
the entrypoint stops before segment preparation, model input or robot dispatch.
Do not restart a shared engine to work around this rejection. A second native
server also cannot take over a thread while the original server holds its writer
lock; copying sessions to bypass that lock is not this recovery protocol.

## Read-only inspection

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

## Execute after inspection

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

Downtime follows the existing segment contract: it does not consume the trial's
wall budget. Recovery does not grant a fresh 24 hours. The allocation must cover
the remaining time. `private/state/control/recovery.json` records the separate
recovery lifecycle. The batch supervisor waits for recovery ownership to close
before stopping its engine or collecting evidence. A failed/uncertain recovery
requires review; the entrypoint never automatically repeats it.

## Validation

`tests/test_codex_task_recovery.py` covers read-only inspection, refusal of old
gateways and unsettled actions, unchanged completed receipts, and a real private
Mosaic pose/grasp reconstruction without advancing physics. Gateway tests cover
single-use authority, active-role refusal, retired sockets and peer containment.
`tests/test_slurm_gateway_native.py` uses the real pinned CLI with synthetic
loopback authentication and inference: 36 independent channels, a closed task
rebound to its original native thread, resumed tools, another fork, transcript
collection, unchanged peer access and one native credential owner. These tests
make no calls to a real model or running physical task.
