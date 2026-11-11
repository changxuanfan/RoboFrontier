# Transport

The team delivers stock items (60 mm wooden cubes and cylinders) from per-station inventories to
destination boards: three requested items per board, identified by source and by a printed
color-and-shape cue. Station letters name inventories and orders, not which arm may handle an
item; any arm may carry any item. Transfers are direct airborne handovers or stable tabletop
staging, as the team chooses.

| Level | Board | Done when |
| --- | --- | --- |
| 1 (`d1`) | Flat board | The item is released inside its target footprint, upright and still |
| 2 (`d2`) | Fixed board with blind slots | Both flat blades of the item are inside the real slots, the item seated, released and still |
| 3 (`d3`) | The same slots on a passive spring-supported board (z, roll, pitch) | As level 2, judged in the board's current frame, with the board still too |

## Geometry

| Property | 4 arms | 8 arms | 12 arms |
| --- | --- | --- | --- |
| Items (targets) | 12 | 24 | 36 |
| Outer table side | 1.938 m | 2.720 m | 3.536 m |
| Central opening | Solid tabletop | 0.476 × 0.476 m | 0.833 × 0.833 m |

The table is 0.8 m high; the central opening is unsupported and is not a socket. Cubes have
60 mm sides; cylinders 60 mm diameter and height. Each white board is 143 × 396 mm with a 120 mm
target pitch; an 84 mm color and shape cue (square for a cube, circle for a cylinder) marks each
target and is not an enlarged tolerance. The paired metal blades are 2.5 × 12 × 24 mm, 24 mm
apart; their blind sockets have 4.5 × 15 mm openings, 26 mm deep, in a 32 mm board. Blades start
pointing up or sideways, so a grasp, any airborne reorientation and the insertion must form one
feasible sequence.

## Completion

The public task's `completion.acceptance` holds every threshold. In short:

| Check | Value |
| --- | --- |
| Released | No robot contact within 0.2 mm |
| Still | Item below 0.01 m/s and 0.1 rad/s for 1 s of simulation; at Level 3 the board too |
| Level 1 | Full shape inside the 70 mm target footprint (0.3 mm allowance), tilt at most 5° |
| Levels 2, 3 | Both full blades inside the slots, blade tops at most 0.5 mm proud, seated within 1.5 mm |
| Assignment | The right source item on every target at the same time, one item per target |

Every item must be delivered and completed placements must stay in place: a placement that is
later knocked out stops counting. `robofrontier/tasks/evaluate.py` (`placement_candidates`)
implements these checks.

## Presentation

Robo World and simple-background videos play Transport at 20× and 30 fps (`speedup` in
`benchmark/release.json`). Each station keeps its own clock and loops independently; motion edits
are read from the recording's own states and events
(`robofrontier/media/edit_transport.py`, `robofrontier/media/transport_motion_signals.py`).
See [Factory replay](../factory/replay.md).
