# Manager runbook

The manager (a person, a shell script or an outer coding agent) prepares, launches, watches,
stops and collects batches. It never decides task strategy, chooses robots, scopes, grasps or
recovery moves, or changes frozen inputs; the measured team follows its frozen role files and the
[collaboration skill](../prompts/skills/robot-collaboration/SKILL.md). Ready-made prompts for an
outer agent: [Codex](../prompts/managers/codex.md), [Claude Code](../prompts/managers/claude.md).
State and evidence boundaries are in the [architecture](architecture.md).

## Keep the policy's inputs clean

Initial roles start in clean, independent sessions. Never fork an engineering conversation that
contains Oracle solutions, earlier trials' answers or private object positions into a policy
session. Adaptive delegates inherit only their own Controller's history. Public inputs never
include reference code, private grasp coordinates, truth logs or Oracle routes; a test that
derives a grasp or route from simulator truth is Oracle evidence and stays out of policy inputs.

## Operate a batch

Follow the [unified CLI](unified-cli.md):

```sh
.venv/bin/robofrontier bootstrap
.venv/bin/robofrontier doctor --render native
.venv/bin/robofrontier plan --render native --level 1 --min-arms --parallel 4
.venv/bin/robofrontier prepare --render native --level 1 --min-arms --parallel 4 --output runs/policy/NEW
.venv/bin/robofrontier preflight --confirm-spend      # paid; Claude Code also needs --max-budget-usd
.venv/bin/robofrontier run runs/policy/NEW
.venv/bin/robofrontier status runs/policy/NEW
```

1. Inspect the plan and get spend authorization before `preflight` and `run`.
2. Prepare on the host that will run the batch, with the backend it will use; `prepare` refuses an
   existing output folder.
3. Watch `status` (an atomic JSON snapshot). Never open another process's database across a Docker
   or shared-filesystem boundary; a live process or lock alone does not show healthy progress.
4. `stop` requests a stop; read the seal and `needs_review` fields afterwards.
5. A run that stopped unexpectedly continues by itself once; continue others with
   `robofrontier continue` only when asked ([continuation](running/continuation.md)).

The task limit is 24 h of active time from START, scored at the cutoff. Do not shorten it for a
test in the public task; use `batch.task_wall_limit_s` in a new batch or an engineering stop. A
stop is not a success and not a physical checkpoint.

## What the runtime does on its own

- **Wakes.** Ordinary mail never interrupts an active native turn; robot results carry bounded
  inbox delivery. An idle session is woken once for addressed mail, a system event, a due review
  time or saved pending work. If a send is uncertain, the dispatcher inspects the session and
  wake ID instead of resending. Only one dispatcher holds the lease; outside input to a session is
  an intervention and must be recorded.
- **Requests.** New requests omit the outer ID; queries name the old ID in `job` data; an uncertain
  request is retried only under its original ID
  ([requests and queries](engines/README.md#new-requests-queries-and-delegation)).
- **Integrity.** Inputs are checked at launch, START, finish and periodically; a changed input
  invalidates the run, pauses scheduling and stops known actions. A lost physical owner is never
  replaced by a new world for the same run.
- **Delegates.** The Controller chooses `delegate` scopes. Codex forks a snapshot of the Controller
  and then each delegate; Claude Code forks each delegate from the blocked Controller at the
  pending call and holds its tools until activation ([Claude delegate fork](engines/claude-code.md#sessions-and-delegation)).
  Lineage is verified before authority is granted; unknown creation or wrong lineage becomes
  `needs_review` and is never reforked automatically. `native_setup_timeout_s` (120 s) bounds fork
  setup, not the delegate's work.
- **Handback.** `return_task` writes the delegate's report atomically, then commits the handback and
  a short notification; the Controller reads the full report on demand. A delegate seen idle or
  failed before handback produces one notice to its Controller; it does not release authority.
  Only the Controller proposes team finish.
- **Pause.** A business pause is a message the delegate handles at a message boundary, reporting
  its actual action state; it keeps ownership. An engineering pause is separate.

## Low-level runtime operations

For a run outside a managed batch, the runtime CLI seals a world and exports committed events:

```sh
.venv/bin/python -m robofrontier.runtime.cli --run-dir runs/EXISTING seal --data '{"timeout_s":30}'
.venv/bin/python -m robofrontier.runtime.cli --run-dir runs/EXISTING export --data '{"path":"/ABSOLUTE/OUTPUT.jsonl"}'
```

Sealing blocks new actions, waits for running ones, requests fresh final images and closure from
the owner, then checks the world lock. Unresolved actions or a surviving owner give a failed seal
that keeps all evidence; if the owner is already gone, unsettled actions are marked unknown and no
world or evaluation is constructed. A normal finish keeps its evaluation. Each run segment writes
its own `seal.json`, which records closure, fresh final observations, unknown actions and video
readability. Do not seal a world that is only paused.

Collected evidence includes task sessions, motion and records, never authentication stores
([evidence storage](running/evidence-storage.md), [verification boundaries](harness-verification.md)).
