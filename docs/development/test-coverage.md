# What the runtime checker covers

`scripts/dev/check_runtime.py` is an offline check of the runtime: no model provider is
contacted. This page says what it exercises and what it does not establish. It describes
coverage; a pass is the report the checker writes.

```sh
.venv/bin/python -m scripts.dev.check_runtime --report runs/checks/full.json
.venv/bin/python -m scripts.dev.check_runtime --protocol-only --report runs/checks/protocol.json
```

Both modes also run every Node host test (`tests/**/test_*.js` with `node --test`) and the Meta
dispatcher scenarios (`tests/harness/codex/test_meta_dispatcher.cjs`), check the syntax of every
JavaScript file, of the inline scripts in `roboteam/runtime/world/dashboard.html` and of any
`javascript` code block in `docs/runs/operator-runbook.md` and
`prompts/guides/collaboration/tools.md`, compile every Python file, and check that every
relative link in tracked Markdown resolves inside the checkout.

- **Full** discovers every Python test under `tests/`: fake services, robot kinematics, real
  headless MuJoCo contact checks, media codecs, and installed harness CLIs against local stub model
  endpoints. Tests whose CLI, platform or ignored data is absent skip; read the skipped count rather
  than counting them as passed.
- **`--protocol-only`** runs a fixed list of contract modules with MuJoCo model creation and
  stepping replaced by errors. It covers synthetic task and runtime contracts, private scoring on
  synthetic records, frozen inputs and recovery boundaries. It does not cover contacts,
  rendering or provider behavior. CI runs it in `.github/workflows/tests.yml`, before the tests.

## Contracts the tests cover

- **Inputs and state.** Preparation starts no world or model and never overwrites or migrates an
  existing directory. Edits to frozen inputs or frozen source are detected; new observations are
  not mistaken for tampering. Work notes, mail and deadlines can be reread from SQLite; restarting
  a physical world in place is rejected, with no implicit reset or replay.
- **Messages.** Recipients, delivery batches and acknowledgments persist; duplicate requests do
  not execute twice; each system's communication authority holds. Mail merges at every
  task-role tool boundary, including races around waits, unrelated mail, timeouts, terminal
  returns and executor loss. Empty mail stays quiet; a receive failure neither replays the
  operation nor creates actions.
- **Robot ownership.** One arm cannot be owned twice; actions on distinct arms run concurrently.
  A Single Controller selects the robot per command, moves independent arms concurrently and is
  not serialized. Pose, joint and gripper admission, stop permissions and routing hold across all
  four systems. All four start directly at START; `ready` only queries.
- **Actions and time limits.** Slow actions get deadlines matching their requested travel and
  rates; HTTP polling keeps the original ID. Real headless checks cover opening and rotation past
  long timeouts and holding jaw references after a timeout stop. An unconfirmed stop keeps its
  uncertainty and its robot reserved. Same-role blocking client calls do not hold a file lock for
  their whole duration.
- **Adaptive delegates.** A first delegate result arrives during the parent's event wait, a tool
  return or an idle continuation, without waiting for all delegates. A delegate turn ending
  without `return_task` produces one directed notice and keeps authority. After proper return, a
  new delegate may reuse the arm; the old session cannot run the new assignment. Delegates do not
  message each other. A failed delegate resumes only with a fresh failed native terminal state,
  resolved physical requests and a new directed parent message; repeated recovery failure does not
  loop.
- **Turns and deadlines.** Native session state is kept apart from self-reported work state. Busy
  sessions are not continued; idle wakes merge; chosen recheck deadlines are honored; an idle
  yield during an active run needs an agent-chosen `after_s`. A management pause releases waits
  and says so in results. Note timestamps are independent of executor state.
- **Scoring and evidence.** Final and interrupted evaluation stay private under
  `private/outputs/`. Interrupted geometry that meets a goal is not scored as success; evaluation
  sampling does not restore physics; in an images run, results given to the policy contain no
  object state. Terminal
  completion and process events are separate ([terminal outcome](../benchmark/rules.md#terminal-outcome)).
  Completion images are captured only for explicitly selected cameras. Exports happen at
  termination or close, with infrequent integrity checks, not per-second world checkpoints.
- **Grasp regressions.** After an offset single-arm contact, fingers reopen and normal grasping
  and placing still work; an actuator that cannot open reports failure.
- **Hosts and UI.** The Node scheduling code is tested with fake platform adapters, including
  notification contents and send failures. UI scripts are parsed, not rendered.

## What these checks do not establish

They do not establish that a live team of agents behaves well, that a provider's model works,
that the project installs on another machine, or that arms never collide on paths the tests did
not run. Shared user files are not a security sandbox (the policy's access table is: see
[policy environment](../hosts/policy-environment.md)). Inspecting native state and then sending is
not atomic. A crashed world is not restored in place; a stopped run continues in a new segment
from its last recorded frame ([continuing a stopped run](../runs/continuation.md)).

State and evidence boundaries are in [architecture](architecture.md); operating instructions in
the [operator runbook](../runs/operator-runbook.md); how to run the tests in [testing](testing.md).
