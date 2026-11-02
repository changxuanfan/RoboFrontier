# Oracle recovery boundaries

Oracle execution is privileged engineering, not a policy model trajectory. The
following rules apply to new `task-reference` preparations. Frozen historical
executions retain their original source and protocol. `strict-process` keeps
process-clean qualification available without redefining task completion.

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
without turning a nonempty historical list into a permanent execution gate.
Mosaic and Relay recovery retain those events and re-evaluate actual progress.
Mosaic may replan a displaced or replaced completed pairing from current matching;
it records that change and never clears the prior history. Relay's old custody
restriction remains in strict/legacy recovery, while task-reference recovery can
use other legitimate arms through the same ordinary action interface.
Relay scheduling reads `terminal_goal_met` per payload in terminal mode, instead
of using the old process-qualified `completed` field. Carry and final readiness
still require measured support; historical drop flags are not current support
measurements. Final opening/withdrawal retains its real support and route checks.

Unknown action outcomes, active jobs, unresolved ownership, invalid inputs,
STOP/deadlines and numerical physics failures remain fences. Numerical failure is
latched on the Trial; subsequent stepping or recovery submission cannot resume
that trajectory as valid evidence. No world reset, object teleportation,
checkpoint splice or history deletion is permitted.

An interrupted action's historical `uncertain` row is never overwritten. A later
terminal motor result resolves only the same original call ID and robot; a new
ID or an idle arm is insufficient. Controlled-stop feedback is retained as an
event or shutdown feedback, and the report matches it to that original action.
An adapter acknowledgement fence additionally requires explicit owner review:
`OracleRecovery.review_terminal(owner, request_id, review, assisted=...)` accepts
only the adapter's own recorded terminal feedback after the arm is idle. It
records the original uncertainty and review, and marks the request `resolved`.
It does not replay the remaining sequence or turn a failed motor call into a
successful one. Legacy/strict runs retain their original acknowledgement fence.

If a batch loses acknowledgement partway through starting its arms, every
attempted call retains its original ID and an uncertain result. Calls not yet
issued are explicitly `not_started`. The batch is recorded before another ID
can be allocated, so a partially launched batch cannot disappear from evidence.

## Aperture is feedback, not a universal release rule

The Transport reference commonly requests `min(grip_max, cube_size_m + 0.012)`:
72 mm for a 60 mm material. Dial previously also required near-maximum measured
aperture before examining an already separated hand's exit. These command
preferences are not universal task completion criteria.

Dial now requires terminal force-free execution and real separation, then screens
the actual finger configuration through its full-scene exit route. A contacting
hand is still rejected. Relay task-reference release can review a known opening
undershoot or overshoot only when execution is resolved, the force hold has
ended and actual cargo contact is absent. The original motor call stays failed.
The support and full route checks remain in place.
Mosaic likewise permits release reconciliation below its preferred cube-plus-3mm
opening in task-reference mode only after actual separation, finite aperture,
stable payload velocity and physical table/pocket support. Approach clearances
and legacy/strict release checks are not relaxed.

Dial blue-support regrasp measures the rectangular stem's current projection
along the fingers' closing axis instead of choosing a nominal 16 or 20 mm face
from aperture alone. The original 5 mm inner/outer motor tolerances, finite
geometry bounds and actual bilateral airborne-support checks remain unchanged.
An abnormal projection requests geometry review rather than widening tolerances.

## Transport socket release stages

The reference distinguishes carried transport from force-off socket contact and
confirmed physical separation. After a known opening result removes the force
hold, it records `force-off-contact-unconfirmed` and retains this phase across a
failed withdrawal. The `held` label is not silently cleared and the payload is
not subsequently carried virtually with a force-free hand.

For a new task-reference exit, the payload must have measured positive-force
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

## Verification and scope

The regression group includes actual archived-pose FK screening, unchanged source
hashes, retained release phases, unknown-outcome fences, real-separation gates,
legacy/strict process behavior and independent report verdicts. No paid model
calls are required.

A controlled local physics probe (attempt `archived-pose-exit-v8`) initialized archived Transport 8-arm Level-3
event state 73, with newly initialized holding references. It completed the
supported withdrawal and subsequently accepted that material under the original
goal evaluator, without changing the scene or score tolerances. This is a local
recovery witness, not exact episode continuation, a full-order success, or
qualification of a different physics release. The candidate and earlier rejected
attempts remain separate evidence.
