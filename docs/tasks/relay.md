# Relay

The team carries red timbers (about 1.2 m long; 2, 3 or 4 of them with 8, 12 or 16 arms) along a
route of worktops from their starting positions to the painted GOAL. Carrying a timber in the air
takes at least two arms, and every timber needs at least one qualified airborne handover before
it counts. Final placement in GOAL is free: timbers may touch or stack.

| Level | Timber |
| --- | --- |
| 1 (`d1`) | A straight beam |
| 2 (`d2`) | A 63° circular arc with a free-hanging pendant (170 mm wooden shaft, 600 g) on its underside |
| 3 (`d3`) | A 31.5° elbow (148.5° interior angle) on passive out-of-plane springs (±25°), with the same pendant |

| Arms | Layout | Timbers |
| --- | --- | --- |
| 8 | Two straight rows | 2 |
| 12 | 90° arc, 7 outer and 5 inner arms | 3 |
| 16 | Semicircle, 10 outer and 6 inner arms | 4 |

Tables are 0.8 m high. Arms grasp the red timber, never the pendant, its eyes or shaft.

## Completion

A timber is complete when, at scoring:

- at least 70 % of its centreline length lies in the vertical space above the GOAL outline
  (`relay-timber-goal-70pct-v1`; only timber segments count, never the pendant), reported as
  `timber_inside_fraction`;
- every arm has released it; table support and stillness are not required; and
- it has a counted airborne handover (`relay-airborne-handover-v1`), reported as
  `airborne_handover_met`.

The case is complete when every timber is. `robofrontier/tasks/relay.py` holds the rule,
`robofrontier/tasks/relay_goal_fraction.py` measures the fraction and the `Relay` class in
`robofrontier/tasks/evaluate.py` tracks custody, handovers and drops.

## Handovers

- **Airborne.** A timber becomes airborne when it is lifted more than 25 mm with at least two
  arms holding it. It is *off the table* while its lowest part is more than 2 mm above the
  tabletop and nothing connects it to the table, directly or through other cargo.
- **Qualified handover.** While the timber is off the table and at least two current holders
  keep it, a new arm must hold it for at least 0.2 s; then a current holder lets go. The change
  is recorded with `protocol: qualified-members-v3` and `airborne: true`. The receiver's 0.2 s
  restart whenever the timber touches the table or the receiver loses contact. A change of
  holders in which a new arm has not qualified is recorded as an `unverified_handover`
  violation and does not count.
- **Never a handover.** Pushing or dragging a timber along the table, and a change of holders
  while it rests in GOAL (recorded as `grounded-regrasp-v1`, `airborne: false`).

## Drops and recovery

An airborne timber is *dropped* when it touches the table or floor outside the allowed GOAL
landing, or when fewer than two arms hold it for more than 0.2 s. Drops are counted in `drops`
and recorded as process events; they do not veto the score.

- The arms that held the timber when it fell may lift it again. Once at least two of them have it
  clear of the table, it is airborne again and its earlier handovers still count.
- If any other arm grasps the dropped timber, a `receiver_recovered_drop` violation is recorded
  and none of that timber's handovers counts, earlier or later, until the arms that held it at
  the drop lift it clear again; only handovers after that lift count.

A continued run keeps each timber's handovers, drops and holders from the moment it stopped
([continuation](../running/continuation.md)).

## Presentation

Videos play Relay at 20× and 30 fps (`speedup` in `benchmark/release.json`), each table looping
on its own clock; neighboring tables in one frame are not synchronized. See
[Factory replay](../factory/replay.md).
