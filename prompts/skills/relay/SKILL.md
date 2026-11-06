---
name: relay
description: Carry long assemblies with several arms in relay, plan supported handovers and verify release at the goal.
---

# Relay

## Shared payloads

Plan the relative motion of all supporting tools as well as their individual
paths. A same-cycle start does not guarantee matched arrival or prevent internal
loads. Choose support contacts and bearing direction for load moments, not jaw
aperture alone; if a lift changes the payload pose unexpectedly, reassess that
geometry before repeating the motion. Treat support and manipulation as coupled
work: control coupled robots directly together, or give them to one bounded
delegate, rather than splitting coupled support across independent scopes.

## Handovers

Choose teams, the route and handover points from reach, observations and the
cost of each regrasp. Preserve receiver access and sender withdrawal when choosing
a grasp. Before releasing an existing hold, establish the receiver's support from
allowed RGB and robot evidence; width-based grasp feedback alone is insufficient.
Update the shared reference after slip or reorientation.

Every timber needs a qualified airborne handover before it can count as complete, so
plan one for each timber even when a single team could reach GOAL. Keep at least two
current holders on the timber while the new arm takes hold, and hold that overlap for
at least 0.2 seconds before a current holder lets go. Dragging or pushing a timber
along the table does not count, and neither does a handover made after a drop until
the last sending team has recovered the timber.

## At the goal

Check each assembly separately against the completion rule from permitted views,
and confirm that every robot has released it and the jaws have cleared it before
proposing completion. After a drop or collision, reason from the actual scene and
recover with ordinary actions.
