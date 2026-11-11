# Oracle recovery boundaries

Oracle execution is privileged engineering, not a policy model trajectory. These rules
apply to `task-reference` executions (the default `--evaluation-mode`); `strict-process`
additionally requires a clean process history without redefining task completion. A prepared
execution keeps the source and protocol it was frozen with.

## Three independent layers

| Layer | Authority | Recovery consequence |
| --- | --- | --- |
| Task/evaluator | Released targets, geometry, support and release conditions; Dial unlock latching | Recovery must eventually satisfy the same requirements. |
| Actuator feedback | Actual call status, measured aperture, force hold and physical contact | Known failed actions may be reviewed; uncertain actions cannot be blindly replayed. |
| Private Oracle planning | Finite IK search, route margins, candidate budgets and reference matching | A rejected strategy is not proof that the physical task is impossible. |

Do not remove a task requirement to make a reference strategy pass. A 0.3 mm
slot-footprint tolerance and a 0.3 mm signed contact-distance screen measure
different quantities even when their numeric values match. Neither is a general
replacement for the other.

## Process history and execution health

Task-reference execution records collisions, drops and other process events
without turning a nonempty event list into a permanent execution gate.
Mosaic and Relay recovery retain those events and re-evaluate actual progress.
Mosaic may replan a displaced or replaced completed pairing from current matching;
it records that change and never clears the prior history. Under `strict-process`,
Relay recovery keeps the custody restriction; task-reference recovery can use other
legitimate arms through the same ordinary action interface. Relay scheduling reads
`terminal_goal_met` per payload. Carry and final readiness require measured support;
recorded drop flags are not support measurements. Final opening/withdrawal retains its real support and route checks.

Unknown action outcomes, active jobs, unresolved ownership, invalid inputs,
STOP/deadlines and numerical physics failures remain fences. Numerical failure is
latched on the Trial; subsequent stepping or recovery submission cannot resume
that trajectory as valid evidence. No world reset, object teleportation,
checkpoint splice or history deletion is permitted.

An interrupted action's recorded `uncertain` row is never overwritten. A later
terminal motor result resolves only the same original call ID and robot; a new
ID or an idle arm is insufficient. Controlled-stop feedback is retained as an
event or shutdown feedback, and the report matches it to that original action.
An adapter acknowledgement fence additionally requires explicit owner review:
`OracleRecovery.review_terminal(owner, request_id, review, assisted=...)` accepts
only the adapter's own recorded terminal feedback after the arm is idle. It
records the original uncertainty and review, and marks the request `resolved`.
It does not replay the remaining sequence or turn a failed motor call into a
successful one. Under `strict-process` the acknowledgement fence stays closed.

If a batch loses acknowledgement partway through starting its arms, every
attempted call retains its original ID and an uncertain result. Calls not yet
issued are explicitly `not_started`. The batch is recorded before another ID
can be allocated, so a partially launched batch cannot disappear from evidence.

## Aperture is feedback, not a universal release rule

The Transport reference commonly requests `min(grip_max, cube_size_m + 0.012)`:
72 mm for a 60 mm material. Such command preferences are not task completion criteria.

Dial requires terminal force-free execution and real separation, then screens
the actual finger configuration through its full-scene exit route. A contacting
hand is still rejected. Relay task-reference release can review a known opening
undershoot or overshoot only when execution is resolved, the force hold has
ended and actual cargo contact is absent. The original motor call stays failed.
The support and full route checks remain in place.
Mosaic likewise permits release reconciliation below its preferred cube-plus-3mm
opening in task-reference mode only after actual separation, finite aperture,
stable payload velocity and physical table/pocket support. Approach clearances
and `strict-process` release checks are not relaxed.

Dial blue-support regrasp measures the rectangular stem's current projection
along the fingers' closing axis instead of choosing a nominal 16 or 20 mm face
from aperture alone. The 5 mm inner/outer motor tolerances, finite geometry bounds
and bilateral airborne-support checks apply unchanged.
An abnormal projection requests geometry review rather than widening tolerances.

## Transport socket release stages

The reference distinguishes carried transport from force-off socket contact and
confirmed physical separation. After a known opening result removes the force
hold, it records `force-off-contact-unconfirmed` and retains this phase across a
failed withdrawal. The `held` label is not silently cleared and the payload is
not subsequently carried virtually with a force-free hand.

For a task-reference exit, the payload must have measured positive-force
contact with an upward supporting normal on the intended board; sidewall
pressure alone does not qualify. The arm must be known idle and force-free.
Planning keeps the measured object pose and board fixed. Existing finger/payload
pairs retain one phase-wide depth baseline with 50 micrometres of numeric slack,
so successive segments cannot accumulate that allowance. New pairs may not
penetrate; a positive geometric gap is not a collision requiring an additional
arbitrary clearance. Board contacts are remeasured after real passive settling,
then bounded by that measured state throughout the next scratch route. The route
does not move either board or payload to make a fit. The initial envelope and
latest board contacts remain in the JSON release phase. A rejected exit never
falls back to the insertion tolerance. All other arm/world guards retain their
normal checks. This bounded permission does not apply to carried transfer, slot
insertion or final scoring.

Compare identical `mj_geomDistance` pair queries on the live and scratch models.
Expanded planning margins can change the contact manifold: individual contact
point depths from two different manifolds are not an appropriate baseline.
Positive-gap scratch contacts are not themselves new physical intersections.

Actual dynamics still determine whether an issued exit succeeds. Subsequent
segments resample the current world; a missing support, worsened contact,
unknown action or failed motion returns to review. Actual separation is required
before clearing the release phase. Resuming this phase does not replay the
opening command. If the hand separates but the original goal is not accepted,
the reference requests seating recovery instead of declaring success.
Final stationary-goal velocity thresholds are evaluated after release; they are
not an extra prerequisite to withdrawing the hand. Nonfinite state is always
rejected. These finite kinematic samples do not certify continuous collision
avoidance or forecast passive contact dynamics.

## Other conservative reference checks

Transport's workspace-plus-padding stock heuristic requests review in
task-reference mode; it does not claim a general impossibility proof. Any repair
still passes normal workspace and ownership checks. Finite candidate/search
budgets also remain strategy limits. Strict physics commissioning keeps its
tighter residual-drift measurements separate from task completion.

## Verification

The Oracle regression tests cover archived-pose FK screening, unchanged source hashes,
retained release phases, unknown-outcome fences, real-separation gates, `strict-process`
behavior and independent report verdicts. They make no model calls.
