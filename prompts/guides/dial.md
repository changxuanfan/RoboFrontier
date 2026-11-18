---
name: dial
description: Operate spring dials and movable modules with paired support, and interpret BEST/READY feedback as evidence.
---

# Dial

<!-- observation:images -->
The robot `ready` tool reports robot capabilities; it is unrelated to the dial
apparatus READY indicator. Before judging table-edge or ring-cutout clearance,
read the geometry reference in `static_workstation`, and use `camera_calibration`
to relate views to the common frame.
<!-- /observation -->
<!-- observation:ground_truth -->
The robot `ready` tool reports robot capabilities; it is unrelated to the dial
apparatus READY indicator. Before judging table-edge or ring-cutout clearance,
read the geometry reference in `static_workstation`. `state` gives every module's
pose and every dial's hinge angle in the common frame.
<!-- /observation -->

## Feedback as evidence

<!-- observation:images -->
Bind each BEST/READY reading to the timestamped RGB configuration that produced
it, keeping intended settings separate from disk positions you can verify. A
<!-- /observation -->
<!-- observation:ground_truth -->
Bind each BEST/READY reading (`evaluator.display` in `state`) to the dial angles of
the same reading, keeping intended settings separate from disk positions you can verify. A
<!-- /observation -->
commanded wrist angle describes the tool; the dial's angle belongs to the movable
white disk's frame, which you update after slip or reorientation. An unchanged
BEST does not tell you whether the current input is equal or worse, or which dial
is correct: keep that uncertainty in your note and choose the next experiment from
the observed configuration. Passing through an intermediate stable configuration
can create a valid trial before the commanded target is reached. A contradiction
can come from your assumptions or from execution or observation error.

## Support and manipulation

Derive red operation and blue support from reach, grasp access and commitments;
nominal robot groups describe layout. For a movable module, establish and observe
independent blue-handle support before red contact, and keep the module clear of
external supports. Choose support contact and bearing direction for load moments;
support must resist the partner's reaction forces while preserving approach,
articulation and withdrawal. After support loss, stop the affected operation and
reassess the geometry before re-establishing it.

For an eccentric crank, plan the translating grip point and tool orientation
together in the apparatus frame, and compare approaches with their next
operations: continued turning, partner support, opening and withdrawal. Observe
at useful milestones, since small contact errors change that frame. Keep useful
held settings while other work progresses, counting spring load, drift and the
cost of an occupied gripper.

## Recovery

<!-- observation:images -->
After a failed move or opening, use the original action's terminal feedback and
selected RGB to distinguish an admission failure, a settled failure and an unknown
outcome. Confirm actual opening and separation before retreating or changing a
<!-- /observation -->
<!-- observation:ground_truth -->
After a failed move or opening, use the original action's terminal feedback and
`state` to distinguish an admission failure, a settled failure and an unknown
outcome. Confirm actual opening and separation before retreating or changing a
<!-- /observation -->
supporting grasp; keep sustained support while it is needed.
