---
name: transport
description: Deliver and insert ordered items into boards with several arms, choosing between airborne handover, tabletop staging and waiting.
---

# Transport

## Flow

Plan useful concurrent work from shared goals and current observations. Compare
direct airborne handover, stable tabletop staging and waiting by total handling
cost, occupied arms, release clearance and risk; there are no mandatory buffers,
routes or robot pairs. Plan reach and staging against the task's actual support boxes,
not the outer table bounding rectangle. Account for the whole sequence from initial grasp through
reorientation, receiving grasp, insertion, jaw opening and withdrawal. Keep
placed items accessible and reverify affected placements after contact.

## Handovers

For a shared or transferred item, plan the relative motion of both tools, not only
their individual paths, and preserve receiver access and sender withdrawal when
choosing a grasp. Before releasing an airborne item, establish the receiver's
support from allowed RGB and robot feedback: a commanded grasp, `is_grasped`,
measured aperture or TCP motion alone does not prove support. When uncertain,
choose an informative view or a bounded verification action.

## Insertion

Reason about seating from the whole item pose and both blade envelopes; touching a
socket is not insertion. On a spring board, use its current observed orientation,
which changes under contact. After a known failure, reason from the actual scene
before regrasping or transferring.
