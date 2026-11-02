# Manager runbook

The manager performs engineering setup, fixed platform scheduling, observation
and evidence collection. It does not decide task strategy, select robot scopes,
choose grasps or provide recovery trajectories. The measured team follows its
frozen role files and [collaboration Skill](../prompts/skills/robot-collaboration/SKILL.md).
See [architecture](architecture.md) for state and evidence boundaries.

Initial policy roles start in clean independent sessions. Do not fork an
engineering conversation containing Oracle solutions, previous trial answers or
private object truth. Adaptive delegates inherit only their current clean
Controller's permitted history. Cross-run experience requires an explicit
experimental protocol. Public inputs never include engineering reference code,
successful private grasp coordinates, process truth logs or Oracle routes.

## Current command-line operation

The unified command is the normal new-run entry. It needs no LLM manager or
manual directory/session preparation. Install dependencies and the native CLI
for the selected engine; configure credentials locally as described in
[CLI configuration](unified-cli.md). Credentials belong in the environment or
ignored `.env`, never in prompts, TOML, evidence packages or chat.

```sh
.venv/bin/robofrontier bootstrap
.venv/bin/robofrontier doctor --render native
.venv/bin/robofrontier plan --render native --level 1 --min-arms --parallel 4
.venv/bin/robofrontier prepare --render native --level 1 --min-arms --parallel 4 --output runs/policy/NEW
```

Use `--render cpu` for Linux software rendering or the default NVIDIA backend
on an equipped Linux host. Native macOS uses `--render native`; freeze the
intended backend during preparation, not just in doctor. Preparing downloads
and verifies missing pinned assets and freezes a new run. It does not execute
policy inference or start task physics, and refuses to overwrite existing runs.

Inspect the plan and obtain the experiment's required spend authorization before
paid preflight/run. The wrapper creates isolated task state, checks native and
render prerequisites and drives the chosen engine. Follow the actual `run`
syntax in [the CLI guide](unified-cli.md); launch the prepared batch with its
frozen model/provider settings, not settings silently changed afterward.
Requested model/effort is recorded separately from verified platform evidence.

All initial roles are bound before direct START. A new Single/Adaptive run
starts its Controller; a standing team starts all bound initial roles under one
task clock. Every role receives explicit started instructions. `ready` only
queries capabilities and does not require another START. Frozen Legacy READY
runs keep their original gate. All four native Claude modes remain explicitly
unqualified engineering paths. Standing modes use distinct persistent native
sessions, not Adaptive delegations; see the
[standing-team guide](engines/claude-code.md#standing-teams). Formal scoring remains closed.

The default public task limit is 24 hours from persisted START. Do not replace
it with a short engineering test duration in the public task. Use the explicit
engineering-stop mechanism when authorizing a short test. A stop is not a model
success or a complete physical checkpoint. Real-time video is optional and off
by default; motion supports later offline video rendering.

For queued execution use [Slurm](running/slurm.md); for Docker use [containers](running/docker.md).
Live databases and native CLI state must stay on local storage. Monitor atomic
status JSON or service APIs rather than opening another process's database
across Docker/shared-filesystem boundaries. A running process, stale lock or
background UI indicator alone does not prove continued healthy execution.

Engineering diagnostics are not a prerequisite that privately solves each task
before the policy runs. Any test deriving a grasp, offset or route from simulator
truth is separate Oracle evidence. Do not transfer its state, trajectories or
reports into policy inputs. Policy exploration uses permitted observations and
counts toward the task's time/actions/failures. Any separate learning stage must
state its budget and retained experience before the experiment.

## Legacy native Desktop scheduling

This section preserves the frozen Desktop research-session workflow. It is not
the default command-line host and cannot be kept alive merely by returning a
final chat response. Use the run's original manifest, tools and protocol when
reviewing a Legacy run; never rewrite its prepared inputs to a new protocol.

The Legacy preparation entries remain:

```sh
uv run python scripts/create_pipeline_run.py runs/NEW --task configs/tasks/three-arm-v1.json
uv run python scripts/check_harness.py --report runs/engineering-check.json
```

A prepared v3 run contains files and a database, but no live world, policy
sessions, video or actions. Its policies read common rules, their task, their own
role and Skill. The manager reads its private runbook and role. Old prepared
packages are not automatically converted by current services.

After authorization, start the single physical owner with
`python -m robofrontier.pipeline --run-dir runs/NEW`. Create the independent
native policy sessions and bind their real thread IDs. For frozen
`ready_barrier_v1` only, policies read their inputs, call READY and yield. The
service requires all initial roles READY/bound with fresh actual idle platform
observations before START. Legacy START saves neutral continuation work; it
does not assign actions or execution order. Direct protocols instead use their
native host's explicit START path; this Legacy dispatcher's readiness option
must not be treated as a new direct-start launcher.

Inside the manager's tool environment, load the run's frozen dispatcher:

```javascript
// @exec: {"yield_time_ms": 1000, "max_output_tokens": 2000}
const quote = s => "'" + s.replaceAll("'", String.fromCharCode(39,92,39,39)) + "'";
const source = await tools.exec_command({
  cmd: "cat " + quote(RUN_DIRECTORY + "/private/inputs/frozen-source/scripts/meta_dispatcher.js"),
  workdir: REPOSITORY, max_output_tokens: 12000
});
if (source.exit_code !== 0) throw new Error("dispatcher unavailable");
const dispatcher = eval(source.output + "\nrunMetaDispatcher;");
await dispatcher({
  runDir: RUN_DIRECTORY, python: PYTHON, cwd: REPOSITORY, tools,
  startWhenReady: true,
  onEvent: e => { if (e.event !== "cycle" || e.cycle % 15 === 0) notify(e); }
});
```

Paths refer to this run's absolute locations. Fake adapters, not real platform
tools, are used in offline checks. After a yielded execution returns a live
cell ID, poll that same cell. Keep the manager tool context active while it owns
Desktop scheduling. A yielded cell does not establish a standalone daemon that
survives the manager's final response. Initial acceptance should cover a returned
delegate while another works, idle Controller continuation and missing handback,
rather than starting a dense full experiment before these boundaries work.

## Fixed scheduling and failure handling

Active native turns are not continued, steered or interrupted by ordinary mail.
Robot results include bounded inbox delivery. Controllers and persistent Workers
may keep working, wait for events or save work and end a turn. Adaptive delegates
normally return their bounded assignment through `return_task`. A self-selected
timed yield is optional continuation, not a mandatory intermediate step.

Legacy project helpers attach inbox handling to their supported tool boundaries.
Permitted local analysis and native read-only operations use the frozen
`roleStep` helper where required; it refreshes mail after that operation without
changing its result, replaying actions or interrupting a native turn. Bare native
tools do not automatically acquire a project inbox hook.

Once a native session is idle, addressed mail, system events, a due self-selected
review or explicitly saved pending work can justify one merged continuation.
A known non-blocking action need not prevent planning/communication, but blocking
requests and uncertain results keep their original recovery rules. Same-arm
mutual exclusion remains. Tool completion, session idle, self-reported
availability and true task completion are different facts.

Recheck native state before claiming a notification. Deduplicate claims and
record results. Delivery or starting a turn does not establish business-level
acceptance. If sending is uncertain, inspect the actual session and wake ID
rather than blindly resending. The existing lease protects against two manager
loops. Platform observation and sending are not atomic: exclusive scheduling
is required, and outside input must be recorded as an intervention and reviewed.

## Stop, sealing and data

SQLite is authoritative for execution state. `work`/`checkpoint`/`yield` update
notes; their checkpoint is not a physical checkpoint. Clients retain request
IDs. New requests omit outer IDs; queries target old IDs through `job` data.
Unknown execution is queried or retried identically under its original ID,
never recreated under a new one. ID conflicts and uncertain transport errors
are separate conditions.

Inputs are checked on launch, START, finish/close and at the configured low-rate
integrity interval. Mutation invalidates the run, pauses scheduling and requests
known-action stopping. Platform observation periods differ from agent review
deadlines. A missing physical owner does not justify creating a replacement
world for the same run; outstanding outcomes remain uncertain.

Use the unified stop/collection flow for its managed batches. For an existing
Legacy pipeline, the engineering sealing entry remains:

```sh
.venv/bin/python -m robofrontier.runtime_cli --run-dir runs/EXISTING seal --data '{"timeout_s":30}'
```

Sealing blocks new actions, waits for existing execution, requests fresh final
images and closure from the original service, then checks the exclusive world
lock. Unresolved execution or a surviving owner produces a failed seal and
retains evidence; it does not silently replay movement or certify a clean stop.
If the owner is already lost, sealing retains database/log evidence and marks
unsettled actions unknown without constructing a world or final evaluation.
A prior normal finish keeps its original evaluation. Do not seal a world that
is merely paused and intended to continue in memory.

Segmented video is finalized and probed after encoder closure. Abnormal exit can
retain complete segments while losing the tail. `seal.json` distinguishes
closure, fresh final observations, unknown actions and video readability. File
existence or a successful first-frame decode does not validate every frame.
A manager cleanup timeout is not an agent planning/action budget.

Explicit committed-event export remains available:

```sh
.venv/bin/python -m robofrontier.runtime_cli --run-dir runs/EXISTING export --data '{"path":"ABSOLUTE_OUTPUT.jsonl"}'
```

Stopped unified collection gathers task-associated native sessions and required
motion/evidence, then optionally creates a verified ZIP. Original sources remain
by default. Authentication stores are not evidence exports. See
[verification boundaries](harness-v2-verification.md) and
[storage validation](archive/evidence-storage-validation-20261030.md).

## Adaptive native forks

The Controller chooses bounded `delegate` scopes. The manager does not choose
robots, assignment size or order. Codex first snapshots the current clean
Controller without running a task turn, then forks the delegate batch from that
one boundary. Snapshot IDs are persisted before lineage inspection. Both parent
links and native history/order/hash are verified before authority is granted.
Each delegate receives its current assignment and explicit first-turn model and
effort; native defaults are not evidence that effort was inherited.

Claude's generic `delegate-bind` stays disabled. Its experimental adaptive host
forks each delegate from the blocked Controller at the same pending call and
sends the same first message; because Claude Code forks by running the child's
first turn, that turn carries the delegate message while a hook holds every
tool call until activation. It verifies each child's copy against the pinned
parent history before granting authority. Unknown creation or wrong lineage
requires review, never an automatic retry. This mechanism has not earned formal
scored qualification (see
[the Claude delegate fork](engines/claude-code.md#trusted-internal-adaptive-fork)).

Initial sessions are named with role/model/run identifiers. Delegate naming is
best-effort UI metadata after identity and initial delivery are confirmed. A
naming failure neither changes authority nor retries session creation. SQLite
stores delegate identities, snapshots and ownership; frozen `roles.json`
describes initial roles only. Connections are mutable runtime credentials, not
an operating-system security boundary against malicious credential reuse.

The Controller's history can change while waiting on delegation. Codex freezes
one batch boundary without requiring parent idle; Claude pins the parent's
history at the pending call and checks every child against it. Physics continues during setup. Completed notices arrive
as they occur, rather than waiting for an entire batch. Only the Controller
proposes team finish. Unknown native creation/delivery becomes `needs_review`,
retaining known IDs, lineage and authority without reforking automatically.

## Delegate termination and recovery

A delegate's current assignment supersedes inherited parent identity.
`return_task` first writes the report atomically, then commits handback and a
compact notification. A failed write returns no authority and sends no completion
notice. Returned sessions leave active polling; old delegate count must not
become recurring polling overhead. Full reports are read on demand, not sent
inside notifications.

An active delegate observed idle/error/needsAttention before handback produces a
deduplicated role/turn notice with saved work, review time and unresolved-action
count. It is a fact, not failure adjudication or automatic authority release.
The parent receives it at permitted tool/wait/idle-continuation boundaries and
distinguishes deliberate waiting from an abnormal stopped turn. A valid saved
waiting deadline can justify continuation when native/execution state permits;
stale mail or inherited pending work cannot automatically recover a failed turn.
Returned scopes require new forks for new assignments.

Business pause is a message-and-own-stop protocol: the Controller requests it,
the delegate handles it at a message boundary and reports actual terminal action
state. Pause does not hand back ownership. The Controller cannot directly stop
a delegate's action through the delegate-owned stop interface. System-level
engineering pause is separate; business messages do not promise immediate
preemption.

Platform system errors and latest-turn failures are stored separately. Only a
freshly confirmed failed active delegate with all physical requests resolved can
continue once for a new Controller-directed message, after another check before
claim. A lone error label, missing terminal evidence or accepted/running/uncertain
actions does not qualify. The same message is not retried in a loop; another
failed turn requires new parent input or engineering review.

Dispatcher health records successful observations, checks, delivery and redacted
errors. Stale time means missing health evidence, regardless of a background
cell's existence. Polling latency includes platform time and does not promise
instant callbacks. The Legacy Desktop dispatcher attempts a status query at
most twice, withdraws stale idle trust on a missing observation and pauses after
three consecutive missing cycles. Existing actions retain their original result
paths; missing state is not guessed idle and forks are not resent.

Optional `native_setup_timeout_s` defaults to 120 seconds for that fork setup
boundary. It limits infrastructure setup, not the delegate's task duration.
Timeout retains known IDs/authority as `needs_review`. Known returned IDs are
persisted before history validation, and every branch must validate before grant.
An already returned result outranks a missing first-delivery receipt; a late
receipt cannot revert a finished scope. Ordinary mail and system events share a
bounded delivery budget and retain undelivered items.
