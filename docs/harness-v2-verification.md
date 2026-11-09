# Offline harness acceptance scope, document format v3

This describes check coverage, not a claim that the whole current repository has
a passing acceptance report. The harness checker exercises fake sessions/services,
robot kinematics/geometry, and real headless MuJoCo single-arm contact regressions.
The latter step physics and perform simulated grasps without new agent
sessions, GUI windows or video recording. Historical three-arm/nine-cube physical
references, resource searches and interactive changes were recorded at the retired
`runs/autonomous-loop-engineering-20261020/report.md`; they are engineering evidence,
not model-performance evidence. See [repository layout](repository-layout.md) for
retained history and cleanup boundaries.

```sh
uv run python scripts/check_harness.py --report runs/engineering-check.json
```

The default command discovers the whole Python test suite and runs additional
JavaScript, syntax and documentation checks. Missing ignored historical scenes
can cause real failures; do not report those as a passing current release gate.
For the explicit non-physics contract subset, `--protocol-only` installs guards
that forbid MuJoCo model creation and stepping. That subset is not equivalent
to full contact, rendering or provider qualification. Its legacy Beam and spring
Dial fixtures use self-contained primitive XML, small synthetic previews and
FakeWorld measurements; they contain no Panda robots. Their preparation,
public/private boundaries and scoring assertions remain active. They do not
require ignored historical textures, model compilation or an IK solve. Current
36-case scene preparation and actual physical regressions are separate checks.

Optional `--skill-validator PATH --skill-python PYTHON` checks skill formatting.
The external validator is not a runtime dependency. Valid formatting does not
prove better coordination.

## Covered contracts and intended checks

- Separate immutable inputs, dynamic state and outputs. Preparation starts no
  world/model; existing directories are neither overwritten nor migrated.
- Persist explicit recipients, delivery batches and acknowledgments. Duplicate
  requests do not execute actions twice; tree/peer communication authority holds.
- Separate native observed session state from self-reported work state. Do not
  continue busy sessions; merge idle wakes, honor chosen recheck deadlines,
  deduplicate notifications and retain unknown outcomes for review.
- Exclude concurrent ownership of one arm while allowing fake actions on distinct
  arms to be accepted concurrently. Unknown execution remains uncertain.
- Check transport/shared-mosaic authority, pose/joint/continuous-gripper admission,
  stop permissions and routing across four topologies. READY-boundary tests cover
  compatibility protocols; **new runs directly START in all four topologies**,
  and READY only queries capability. Read detailed robot geometry per arm or
  through authorized static-file references.
- Give slow actions execution deadlines matching their bounded requests; HTTP
  polling retains the original ID. Real headless checks cover opening/rotation
  beyond the old 15-second limit and holding jaw references after timeout-stop.
  Unconfirmed stopping retains uncertainty and ownership.
- Single/centralized has one policy session, robot-selection authority,
  cross-arm concurrency, same-arm exclusion, completion-image ownership and
  unknown-action recovery. A single agent is not artificially serialized.
- Adaptive delivers a first delegate result during parent event wait, tool
  return or idle continuation without waiting for all delegates. A native turn
  ending without handback produces a directed, deduplicated notice and retains
  authority. After proper cleanup/return, a new delegate may reuse that arm;
  the old session cannot execute the new assignment.
- Controllers may read compact delegate state and selected notes through
  authorized interfaces. Delegates do not directly exchange business messages.
  Normal completion requires return_task; native turn end does not return control.
  An explicitly saved waiting/available deadline can authorize one continuation
  while scope/execution permit it. Old mail or inherited continuing state does
  not automatically revive an abnormal turn; a fresh parent message may request
  explicit cleanup or continuation.
- A failed delegate resumes only with a fresh failed native terminal state,
  resolved physical requests and a new directed parent message. Missing/nonfailed
  terminal evidence, accepted/running/uncertain actions or state changing before
  send block recovery. Repeated recovery failure does not loop indefinitely.
- Persist successful observation/delivery times. Missing observations revoke idle
  trust; sanitized errors retain causes. Historical research-host continuity was
  a runtime prerequisite, not proof of an independent background service.
- Same-role blocking client calls do not hold a file lock for their entire
  duration. Committed action segments check mail by default at step boundaries;
  policies can choose finite segment-end boundaries. Failure, pause, system
  events, pending execution and intermediate images still return.
- roleStep appends bounded events after ordinary local/native read-only operations,
  preserving original output/errors. Empty mail stays quiet; receive failure
  neither replays the operation nor creates robot actions. Bare native tools
  have no universal event-injection guarantee.
- Final/interrupted evaluation is private under `private/outputs`. Interrupted
  geometry satisfying a goal is not scored as successful task termination.
  Evaluation sampling does not restore physics; policy returns contain no
  private object truth. Terminal completion and process events are separate;
  see [current scoring/start semantics](protocol.md#direct-controller-startup-and-terminal-scoring-v2).
- Capture completion images only for explicit camera selections, or return robot
  state alone. Asynchronous queries retain capture time; retrying one ID does
  not execute the action again.
- After offset single-arm contact, fingers can reopen and normal grasp/placement
  still work; an actuator that cannot open reports failure honestly. Those
  regressions retain their original friction, gripper parameters and NoSlip 10,
  and do not qualify every new contact candidate.
- Idle yield in an active task requires an agent-selected recheck deadline.
  Legacy READY waits, paused and ended states are exempt. Management pause
  releases waits and is explicit in results; READY is no new-start barrier.
- Merge mail at every task-role tool boundary. Exercise before/after-wait races,
  unrelated mail, timeout/continued waits, terminal returns, legacy READY gates,
  optional communication during asynchronous actions, terminal caching and
  executor loss.
- Note timestamps are independent of executor state. Starting an action does
  not make an old note new. Long waits preserve their ID/original deadline;
  pause returns immediately. Selected results/images in the same delivery do
  not silently add observations or actions.
- Work notes, mail and deadlines can be reread from SQLite. Restarting the
  physical service is rejected; there is no implicit reset or automatic replay.
- Do not write per-second complete world checkpoints or rewrite complete logs
  every second. Export on termination/close, with infrequent integrity checks
  plus startup and final checks.
- Detect input/frozen-source edits and honor the public-coordinate switch.
  New observations are not misclassified as immutable-input tampering.
- Test fixed JavaScript scheduling with fake platform adapters, including legacy
  START gates, notification contents and send failures. Parse UI scripts
  statically; parsing alone is not visual/browser acceptance.

## Limits of this evidence

Offline checks do not establish new real Desktop session loops, cross-machine
installation or improved model coordination. A separate physical reference can
show its tested layout/executor completing selected work with overlap; it is
not general multi-arm swept-trajectory certification. Shared user files are
not a security sandbox. Native state inspection followed by sending is not an
atomic operation. Full physical crash/restart recovery is intentionally absent,
not an unpassed feature to enable later without changing the protocol.

Consult the [integration ledger](archive/unified-main.md) for actual test
results, missing assets and native-engine qualification; this catalog is not a
substitute. Architecture and operating instructions are in
[architecture.md](architecture.md) and the [Meta runbook](meta-runbook.md).
