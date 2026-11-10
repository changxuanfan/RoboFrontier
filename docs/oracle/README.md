# Privileged Oracle execution

An Oracle is engineering reference code with access to the physical scene and
evaluator. It is separate from both native policy engines and their controllers.
An Oracle result is not a multimodal-agent benchmark result. A successful historical witness
does not qualify a changed scene, controller, solver or physics release.

The unified CLI prepares single-use, host-local executions of the four existing
native entries. It freezes current released scenes by identity, Python source,
harness, catalog, effective settings and dependency versions. It does not load
historical recording folders as the default scene or inherit their success.
Legacy native entries remain available with their original timing semantics.

## Unified preparation and supervision

```sh
.venv/bin/robofrontier oracle plan --level 1 --min-arms
.venv/bin/robofrontier oracle prepare --cases mosaic-a04-6x12-d1 \
  --output runs/oracle/r14-two-goals --render native \
  --mosaic-planning-workers 4 --mosaic-max-goals 2 --wall-limit-s 600
.venv/bin/robofrontier oracle run runs/oracle/r14-two-goals
```

An Oracle runs on its own copy of each case (`benchmark/oracle/<case>/`), with the physics its
recordings were made with; the release physics does not apply to it. Plan is read-only. Prepare installs the pinned policy assets when needed and
verifies the selected task, workstation and every asset without advancing
physics. It requires exactly one selected case and a clean committed checkout.
Use another output directory for another attempt. Source is copied before native
execution; later edits to this checkout do not change its Python imports. Frozen
scene paths remain host-local and are reverified before launch. Re-prepare on a
new host instead of editing a prepared execution's absolute paths.

`oracle run` reads the frozen configuration, ignoring later operator TOML edits.
The `[oracle]` wall limit defaults to 86,400 seconds of engineering elapsed time
from launching the native owner, including scene initialization, planning and
review pauses. It is not policy START and is not a model performance comparison.
The supervisor persists launch/deadline timestamps and uses a monotonic elapsed
clock while running. It does not impose a second native wall deadline. After a
stop it sends SIGTERM to the existing owner, allowing `stop_grace_s` (default
120 seconds) for the native owner's cleanup/reporting. An unresponsive process
group is then forcibly killed and retained as incomplete evidence. Cleanup time
does not authorize more task execution.

Other native algorithm options keep their reviewed defaults. The configuration
contains Mosaic scratch-planning and physics-thread counts and an explicit
commissioning goal limit. Transport uses the full-order solver; Relay keeps its
rolling pipeline; Dial keeps its isolated blind BEST-only solver. These are
privileged references, not interchangeable policy agents.

## Task outcome and process qualification

New schema-4 preparations freeze `private/execution-protocol.json` separately
from the original scene. It binds the case ID and exact task/XML SHA-256 values
and selects `terminal_outcome_v2`, the same completion semantics used by current
policy preparations. The original scene contracts, asset locks and scoring
geometry are not rewritten. The supervisor verifies this protocol before launch.

`[oracle].evaluation_mode` defaults to `task-reference`. Recorded process
violations remain evidence, but do not permanently prevent ordinary recovery.
Use `strict-process` for engineering qualification that additionally requires a
clean process history:

```sh
.venv/bin/robofrontier oracle prepare --cases transport-a04-d1 \
  --output runs/oracle/transport-strict --evaluation-mode strict-process
```

Frozen schema-1/2/3 settings and existing prepared Oracle executions retain their
original shapes and protocols. Launch supervision clears an inherited Oracle
protocol environment variable before deciding whether this preparation has its
own verified protocol. Do not edit or upgrade an already prepared execution.
When loading an older operator TOML for a new preparation, defaults are selected
for that schema before merging. New options supplied under an older schema are
errors; selecting schema 4 is an explicit opt-in, not an automatic migration.

New native reports use `robofrontier.oracle-report.v2`. `task_goal_met` records
the evaluator outcome; `task_completed` additionally requires valid physics and
resolved execution. `process_clean`, `execution_resolved`, `physics_valid` and
`strategy_completed` report separate facts. `passed` still requires a successful
full reference execution; a partial commissioning test or failed strategy is
never promoted just because one object reached a goal. Strict mode also requires
clean process history. The unified status copies these verdicts from the native
report instead of recomputing completion from a raw legacy field.

See [Oracle recovery boundaries](recovery.md) for the distinction between
task requirements, actuator feedback and private planning checks.

Dial preparation samples a fresh uniform nonzero symbol per dial, just as policy
preparation does. An explicit `--codebook /path/to/puzzle.json` can instead freeze
an evaluator-only puzzle with exactly `{"code_symbols": [...]}`. The private file
is mode 0600 under a mode 0700 directory. Only its path and checksum enter launch
metadata; symbols are not put in the solver command or public task. The native
evaluator and solver remain separate processes. Historical private puzzles are
not required for a new execution and are not recreated as historical witnesses.

From another terminal:

```sh
.venv/bin/robofrontier oracle status runs/oracle/r14-two-goals
.venv/bin/robofrontier oracle stop runs/oracle/r14-two-goals
```

Status reads atomic JSON and an owner lock, never a live SQLite database. STOP
is consumed by the supervisor, so differences between native stop-file locations
do not affect this interface. A stop before launch prevents launch. Every claimed
execution is single-use even after an error; the command never restarts an
uncertain world or blindly replays its last actions. If a supervisor is killed,
its native child can outlive it: inspect the recorded PID before collection.
An unheld owner lock alone is not proof that all writers have stopped.

On a controlled native stop, the recorder captures the actual final live pose
even if it falls between cadence samples. This reads the stopped world and
advances no dynamics. The stream remains `interrupted`; unknown actions are
still unknown. An invalid final pose is not fabricated: the verified prefix is
kept and `final_motion_capture_error` records the missing tail. Legacy interrupted
streams can end before their final event; keep their status and original bytes.

The execution directory retains `oracle.json`, `effective-config.json`,
`oracle-status.json`, `oracle.log`, `private/` frozen inputs/source and `trial/`
native actions, motion, evaluator/report and recovery files. `passed` requires
a successful full native report, a completed task, a clean process exit and no
unresolved actions. Partial commissioning has its own flag; a completed object
layout does not erase a stricter native Oracle rejection. The native report
retains all process events and assistance history. Policy auto-collection flags
do not collect this directory, and a raw Oracle directory is not a policy
collection input. Preserve it until its owner and children have stopped; the
closed `trial/motion` directory can then be imported by Factory.

The supervisor also terminates children left in the execution's process group
after a native owner exits. Such an abnormal exit cannot establish a clean
Oracle success, even if an owner wrote a successful report before leaving its
writers behind. Forced termination preserves evidence; it is not clean sealing.

## Install and select inputs

```sh
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap
```

The policy asset package supplies the current task scenes. Historical reference
recordings and their private review evidence are separate data; bootstrap does
not manufacture those witnesses. A Factory presentation package is not permission
to claim that every historical Oracle has been rerun on current physics.

Mosaic uses `benchmark/mosaic/catalog.json` by default. Case IDs are
reused across revisions, so identify a run by its catalog, scene and executor
hashes as well as its case ID. The runner verifies the selected case, scene hash
and matching catalog/task revision before constructing a physical world. Keep an
old executor with its historical inputs when reproducing a legacy result.

## Mosaic commissioning and full execution

Start with an explicitly partial engineering check:

```sh
.venv/bin/python robofrontier/oracle/run_mosaic_oracle.py \
  --case mosaic-a04-6x12-d1 \
  --output runs/oracle/my-r14-commissioning \
  --planning-workers 4 --physics-workers 0 \
  --max-goals 2 --wall-s 600
```

`--max-goals` is commissioning, even when all selected goals pass. It is not a
full-case success. To attempt the complete task, omit the goal limit, choose a
new output directory and set any intended explicit wall/simulation/action caps.
The native Mosaic entry has no default wall cap. The normal policy benchmark's
86,400-second START deadline is a different protocol.

Commit the executor before physical execution. The native runner rejects a dirty
checkout, records its Git commit and freezes Python code, harness and catalog
before re-executing. It binds imports to that frozen checkout, avoiding a shared
virtual environment silently importing another worktree. Scene assets remain
revisioned inputs, verified separately and frozen with the recording; this is
not a physical restart checkpoint.

Planning workers reconstruct independent scratch models and IK references. They
never own the live physics data or submit robot actions. `--planning-workers 0`
uses available CPUs; a positive number is an explicit process count, bounded by
the number of items. The serial planner remains available with `1`. Worker loss
is reported rather than leaving a silently missing pool result indefinitely.
`planning-status.json` distinguishes elapsed planning from time since progress.

`--physics-workers N` explicitly enables MuJoCo internal worker threads in the
single live world. Zero leaves the pool disabled. More threads or processes do
not prove greater throughput, especially with multiple Oracle worlds. Endpoint
screens are candidates; they do not prove collision-free travel, successful
grasps or task completion.

## Review, assistance and stopping

The owner publishes atomic `runner-status.json` and `planning-status.json`.
At a supported known execution boundary, Mosaic review publishes privileged
state in `review/observation.json`. Its `world_id` and `review_id` identify the
current world and review epoch. Recovery requests and results remain under
`review/requests/` and `review/results/`; rejected requests are retained.

A supervising human or coding session can inspect this engineering evidence and
submit a supported bounded recovery. Such an intervention is recorded as
assistance. It does not modify the frozen solver, reset the scene, remove old
events or transfer physics ownership. Known held payloads must be completed or
physically reconciled before rematching. Uncertain/in-flight actions cannot be
blindly replayed. Requests have idempotent IDs bound to their original content.

An acknowledged request is not proof that a physical recovery succeeded. Read
the resulting action feedback and independent evaluator, retaining failed
commands and review history. Legacy frozen Oracle references can have stricter
process-violation continuation gates than terminal-outcome policy scoring. New
task-reference reports separate those process events from completion; an Oracle
stop is not a policy scorer automatically ending an agent.

Create a `STOP` file in that trial's output directory, or send SIGTERM to its
owner, to request controlled termination. Preserve its report, unresolved action
status and motion before collecting it. Killing the process or losing a node can
leave an incomplete tail and cannot be called a sealed success. Do not replace a
running executor's source or synthesize a restart from visual motion.

The cache diagnostic reads the trial's archived solver to determine whether its
own code prunes stale graph metadata. It does not treat a comment, another
function, or the current checkout's behavior as authority for an older executor.
The diagnosis alone never authorizes motion or certifies a safe recovery.

## Evidence and Factory replay

Retain the frozen executor snapshot, catalog/harness, `report.json`, controller
actions, process/trace events, review requests/results, source assets and motion.
Report `assisted`/`oracle_mode` and commissioning scope without dropping their
provenance. A source-bound concurrent execution needs equivalent inputs and its
own physical validation; borrowing a source does not borrow its success flag or
erase assistance in the source's history.

Closed `robofrontier.motion.v1` recordings can be imported using the
[Factory workflow](../factory/replay.md). That composes the desk from the recording's own
source and replays saved poses without physics. Video completion remains separate
from Oracle acceptance. Compression does not authorize stripping events, source
identity, intervention evidence or unresolved actions.

## Curated integration scope

Fresh current-scene Transport L1 and L2 references at source `f9d532d` each
complete 12/12 goals in one world, with all independent v2 verdicts true, valid
physics and no inter-robot contacts or unresolved actions. No model or external
repair input is used. Their suite/controller/scoring/scene bytes are unchanged
in final closure code `8bd989a`, which has complete macOS/Linux and native physics
regressions. This qualifies those two references, not every Transport case or a
changed physical release; earlier failed worlds remain stopped and retained.

The first R14 curation takes the reviewed endpoint-worker, checkout-binding and
input-identity changes through source commit `a49880f`, plus the frozen-executor
cache diagnostic correction from `76d87ed`. Main also checks the task revision
against the catalog and makes R14 the native default. The 71-mm Mosaic R15 scenes,
15-percent color experiments, R15 selector and experimental source-order/scope
changes were not imported. Relay's independent revision numbers are unrelated.
On 2026-11-03 the release moved to a new grid-only Mosaic R15 (71 mm pitch, see
[Mosaic](../tasks/mosaic.md)); it is not that unimported draft and has no Oracle run.

Focused tests cover actual R14 serial/parallel endpoint equivalence, unchanged
live state, worker initialization failures, frozen imports, revision mismatches,
changed stock colors, protected goals, recovery ownership and uncertain actions.
Passing these tests does not establish every full-case Oracle or a new physical
release. See the integration ledger (`docs/archive/unified-main.md`, in the [archive tag](../history.md)) for actual
checks and remaining unified-entry and operational gates.
