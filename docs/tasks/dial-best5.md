# Dial (BEST5)

Each dial module has a knob with six marks (0–5, 60° apart) and a secret digit 1–5. The team
turns every knob to a nonzero mark and holds them all at once. The panel's BEST digit shows the
largest number of correct dials any one complete valid input has had in the episode, never the
current count; READY shows whether the current input is valid. The case is solved when one valid
input is entirely correct.

| Level | Modules | Arms (4, 6, 8 dials) |
| --- | --- | --- |
| 1 (`d1`) | Fixed gear dials on the table | 4, 6, 8 |
| 2 (`d2`) | Free modules: a second arm holds each blue handle with the module at least 20 mm clear of every support while another turns the red knob | 8, 12, 16 |
| 3 (`d3`) | As level 2, turned by a single-sided crank against a stiffer spring | 8, 12, 16 |

The table is 0.8 m high and each white disk 0.3 m across. Each case's public task and family
materials (previews, camera calibration, `table-geometry.json`) give its table outline, bases,
panel and cameras.

## The code

The code is fixed per case: `private.dial_codes` in `benchmark/release.json` holds it, and
every policy run of that case gets the same code. It is evaluator-only and never copied into a
run's public files. Marks 4 and 5 can also be reached at −120° and −60°; ±180° is mark 3.

## Feedback and completion

A **valid input** has every dial within 4° of a nonzero mark, every red knob (Level 3: the
crank grip) grasped by an arm, at Levels 2 and 3 that module held clear by a different arm, and
all of it stable for 0.25 s of simulation.

| Signal | Meaning |
| --- | --- |
| READY grey | The current input is invalid (off-mark, zero, a grasp or support missing) |
| READY amber | Valid, still qualifying |
| READY green | Valid for 0.25 s; the input is a trial and updates BEST |
| BEST | Starts at 0; bright only while READY is green, dim otherwise; an unchanged value can mean equal or worse |

Every new stable valid configuration is a trial, including ones passed through during motion.
**Success latches**: once a valid input is entirely correct the case is solved, and later dial
changes do not undo it. Collisions and support losses before the unlock stay recorded as
process events. `robofrontier/tasks/dial.py` holds the feedback state machine;
`robofrontier/tasks/evaluate.py` (`sample_dial`) decides validity.

## Presentation

Videos play Dial at 10× and 30 fps (`speedup` in `benchmark/release.json`), each station looping
on its own clock. See [Factory replay](../factory/replay.md).
