# Dial (BEST5)

Each dial module has a knob with six marks (0–5, 60° apart) and a secret digit 1–5; the code is
fixed per case. The team turns every knob to a nonzero mark and holds them all at once; the
panel's BEST digit shows the largest number of correct dials any one complete valid input has
had in the episode, and READY turns green when the current input is valid (every dial within 4°
of a nonzero mark, grasped, still for 0.25 s). The task is solved when one held input is
entirely correct.

| Level | Modules |
| --- | --- |
| 1 (`d1`) | Gear dials on the table |
| 2 (`d2`) | Free modules: a second arm holds each blue handle with the module 20 mm clear of every support |
| 3 (`d3`) | As level 2, with a single-sided crank to turn |

Scales: 4, 6 or 8 dials (4, 6, 8 arms at level 1; twice that at levels 2 and 3).

## Earlier revisions, Oracle evidence and tools

The sections below keep the detail written while each revision was built; numbers such as
R13 or R14 name those revisions.

### Current catalogs and historical artifacts

| Content | Path |
| --- | --- |
| Nine-case model catalog | `benchmark/dial/catalog.json` |
| Specification, defaults, frozen evidence registry | `benchmark/dial/best5-r11.json` |
| Policy-specific guidance | `prompts/skills/dial/SKILL.md` (earlier: `prompts/archive/tasks/dial-best5.md` in the tag `archive/pre-cleanup-20261110`) |
| Original shared integration requests | `benchmark/dial/integration-requests.json` |
| Historical review package and progress-aware edits | `outputs/engineering/dial-family-current/` |
| Delivered nine simple-background videos | `outputs/oracle/dial-nine-videos-20261027/` |
| Delivered nine Factory videos and matching scenes | `outputs/robo-factory/dial-best5-edited-10x-20261027/` |

Output/recording paths are preserved provenance, not contents of a plain clone.
New checkouts restore current pinned policy assets through `robofrontier bootstrap`.
The optional Factory recording bundle is a separate resource.

### Rules and completion

| Dials | Level 1 arms | Level 2 arms | Level 3 arms |
| --- | --- | --- | --- |
| 4 | 4 | 8 | 8 |
| 6 | 6 | 12 | 12 |
| 8 | 8 | 16 | 16 |

Each secret symbol is 1..5; zero is invalid; detents are 60 degrees apart. The
table is 0.8 m high and each white disk is 0.3 m in diameter. Read each frozen
case for its actual tabletop outline, openings, bases, scoreboard, and cameras.
Level 1 modules are fixed. Levels 2/3 require independent blue support, an actual
red grasp, and the whole module airborne; Level 3 uses an eccentric crank.
The complete eligibility conditions come from that case's public task.

BEST is the highest match count among valid inputs in the episode. The device's
READY indicates the current input's physical eligibility, not password correctness
or the harness START gate. Stable intermediate configurations settle automatically;
a new valid input remains an attempt even when BEST does not improve.

**Unlock once means complete.** Success is latched when the correct eligible input
is achieved; later angle changes do not undo that solved state. This is the
intentional Dial completion contract, unlike a final cube placement that can be
disturbed. New policy `terminal_outcome_v2` reports solved/completion separately
from process violations and retains strict compliance as an additional field.
Unlocking does not erase collisions, support-loss records, or other events.
Recorded violations do not themselves stop the policy. Historical evaluators
and Oracle reports retain their original stricter pass criteria.

Public input contains permitted static specifications, RGB observations, and
robot feedback. Oracle answers and live object truth are private. Initial
prompts and shared roles/skills come from the frozen harness, not a historical
review package's private evidence index.

The original family presentation settings remain in `dial_pose_timeline.py::PRESENTATION`.
Current Factory presentation uses source motion at 60 Hz, **10x at 30 fps**, and
independent per-station looping with appearance reset. Legacy hold-final-state
is still supported. Presentation time is not a policy or physics deadline.

### Review and replay tools

The family audit (`check_dial_family.py`), the policy-package checker
(`build_dial_policy_package.py`) and the motion editor (`edit_dial_recording.py`) were removed on 2026-11-10 (restore from tag `archive/pre-cleanup-20261110`; see the [cleanup log](../cleanup-20261110.md)).

These tools do not create policy runtime, role connections, or model sessions.
They bind reports, assets, controller/evaluator fingerprints, and regenerated
public projections. Historical reports/inputs remain byte-identical; do not
bulk-rewrite `oracle_verified` or old status fields. Use a new review directory.

Each review's public portion includes its task, generated task guide, family
guidance, camera calibration, initial reference image, and optional
`table-geometry.json`. Ring-shaped tables retain their real holes and segmented
or mesh geometry. Private evidence indexes are engineering-only.

Simple-background rendering (`render_dial_oracle.py`, also removed on
2026-11-10) used the frozen source and edit. Current
[Factory commands](../factory/replay.md) provide the complex-background Cycles path;
`python -m robofrontier.factory.commands video` remains the lower-level entry. The historical
Classic final-video entry is retired; source frames and delivered videos remain.

`run_blind_dial_oracle.py` is an explicit Legacy engineering Oracle entry using
R11 and `configs/harnesses/oracle.json`. Its native no-budget behavior
is not the unified Oracle's default 24-hour engineering deadline. The batch
runner `run_best5_dial_batch.py` and the local diagnostic
`commission_best5_dials.py` were removed on 2026-11-10. The shoulder-clamp
experiment entry is retired,
while real model shoulder geometry remains. Historical readers serve old evidence.

### Source edits and independent playback cursors

`dial_motion_edit.py` classifies original qpos, action progress, process events,
and appearance events. It preserves valid inputs, support changes, failures,
recovery, completion context, and unknown evidence. Multi-scale classification
can detect long repeated oscillation without effective drive or center drift.
A force setpoint is not measured contact force; classification does not prove
zero force. The nine original recordings did not establish a large sustained
oscillation segment safe to remove; that capability has independent fixtures.

`DialReplayTrack.at(global_frame)` returns the station's source frame/time,
original float32 qpos, and accumulated appearance changes. On first use or a
backward cursor, `appearance_reset` requires restoring that station's initial
RGBA before applying events. Stations' cursors remain independent. The shared
Factory timeline updates all stations, then renders once under the independent
presentation clock. Motion compression must preserve those states, timestamps,
and events; it is separate from editorial interval removal.

### Integration and evidence preservation

Dial-specific edit/render modules retain Dial names. The original integration
requests avoided replacing generic rendering modules wholesale; shared changes
cover GPU pose synchronization, station transforms/subsets, terminal-state
ownership, and uncertain-operation fences. Review common ancestry and merge
small changes rather than overwriting whole shared files with a family branch.

`oracle/dial.py` holds the Oracle's four layers, each built on the one before
(BaselineManipulator, Manipulator, HoldingManipulator, BestManipulator), with geometry
helpers in `oracle/geometry.py`. Do not remove an implementation merely because
its name looks old. Preserve both original recording batches, failed/interrupted
attempts, recovery provenance, private pairings, frozen source, and required
assets. Delivered videos keep their actual edit/scene/frame maps; new manifests
do not imply that old videos were rerendered.

Historical detail is in the Oracle continuation (`docs/archive/history/dial-oracle-continuation-20261027.md`, in the [archive tag](../history.md)),
old handoff (`docs/archive/history/dial-oracle-handoff-20261026.md`, in the [archive tag](../history.md)), and
render history (`docs/archive/history/dial-motion-render-history-20261027.md`, in the [archive tag](../history.md)). Their pauses,
pending tasks, and local paths are historical, not current operator instructions.
Use current review receipts and the integration ledger for acceptance scope.
