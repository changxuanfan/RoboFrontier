# The tasks

Four families, each at three scales (the number of arms) and three levels (how hard the
mechanism is): 36 cases. The release (`benchmark/release.json`, with `release_id`) names every
case's scene, its public task and family materials by hash; each case lives in
`benchmark/<family>/<case>/`. A run receives only the public task (`public/task.json`), the
family materials and the family Skill (`prompts/skills/<family>/SKILL.md`), never the scene file
or the evaluator.

| Family | Cases | What the team does | Level 1 → 3 | Guide |
| --- | --- | --- | --- | --- |
| Transport | `transport-a04/a08/a12-d1..d3` (4, 8, 12 arms; 12, 24, 36 items) | Deliver each requested cube or cylinder to its destination board | placed on the board → two blades into blind slots → the same on a spring-supported board | [Transport](transport.md) |
| Mosaic | `mosaic-a04-6x12`, `a06-9x18`, `a08-12x24`, `d1..d3` (72, 162, 288 cubes) | Build a four-color Tulip pattern, one cube per cell | 70 mm pockets → printed lines → no visible grid | [Mosaic](mosaic.md) |
| Relay | `relay-a08/a12/a16-d1..d3` (8, 12, 16 arms; 2, 3, 4 timbers) | Carry long timbers to GOAL with at least one airborne handover each | straight beam → arc with a hanging pendulum → sprung elbow with a pendulum | [Relay](relay.md) |
| Dial | `dial-best5-n04/n06/n08-d1..d3` (4, 6, 8 dials) | Find and hold the code, with only a BEST-so-far record as feedback | gear dials → blue support held in the air → crank dials, support held | [Dial](dial-best5.md) |

## What every case shares

- **Physics.** The release physics is in each scene file, and every action states its speed,
  acceleration or force within the limits of a real Franka Panda ([physics](../physics.md)).
- **Time.** 24 hours of active running time; outages, usage-limit pauses and host sleep do not
  count. The policy is not told the limit ([continuation](../running/continuation.md#time)).
- **Scoring.** Terminal: the world is scored when the team calls `finish` or at the cutoff,
  after 1.5 s with every arm still. Process events (collisions, drops) are recorded beside the
  score and do not veto it, except where a family's rule says so (Relay handovers)
  ([protocol](../protocol.md)).
- **Continuing.** A stopped run continues as the same trial, never a new attempt
  ([continuation](../running/continuation.md)).

The Oracle (a privileged reference that solved every case) ran on the scenes it was developed
on, which are kept unchanged in `benchmark/oracle/<case>/`; see the [Oracle](../oracle/README.md).
Earlier scene revisions and their records are in the tag `archive/pre-cleanup-20261110`
([history](../history.md)).
