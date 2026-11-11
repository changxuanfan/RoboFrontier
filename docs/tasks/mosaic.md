# Mosaic

The team builds a four-color Tulip pattern (cream, navy, coral, sage), background cells
included, with one 60 mm cube per cell on a 71 mm pitch. The pattern matrix and the target image
(`public/inputs/family/target-pattern.png`) are in world orientation: row 1 toward +Y (north),
column 1 toward −X (west). Stock allocations to stations do not restrict which arm uses an item.

| Level | Grid | Scales |
| --- | --- | --- |
| 1 (`d1`) | 70 mm square pockets, 20 mm deep | 6×12 cells with 4 arms, 9×18 with 6, 12×24 with 8 |
| 2 (`d2`) | 3 mm red printed lines | the same |
| 3 (`d3`) | No visible grid; the declared pattern and coordinates are the reference | the same |

## Geometry

| Arms | Pattern and cells | Outer table width × depth |
| --- | --- | --- |
| 4 | 6 × 12, 72 | 2.465 × 2.662 m |
| 6 | 9 × 18, 162 | 3.073 × 3.411 m |
| 8 | 12 × 24, 288 | 3.680 × 3.344 m |

The table is 0.8 m high. The palette is cream `#FFF4DA`, navy `#173F73`, coral `#F03F5B` and
sage `#16A16E`. The public task states the pitch and pocket size; the Mosaic Skill states no
numbers and says to work the clearance out from the task.

## Completion

Every cell needs a distinct cube of the right color, all qualifying at the same time. The
public task's `completion` block holds the thresholds:

| Check | Value |
| --- | --- |
| Released | No robot contact within 0.2 mm |
| Still | Below 0.01 m/s and 0.1 rad/s for 1 s of simulation |
| Orientation | Cube axes within 8° of the workstation axes, any 90° symmetry |
| Level 1 position | Whole rotated footprint inside the pocket (0.3 mm margin), bottom within 0.8 mm of the pocket floor and touching it |
| Levels 2, 3 position | Center within 6 mm in xy (`mosaic-center-6mm-v1`) and 3 mm in z |

A placement that is later disturbed stops counting. `robofrontier/tasks/evaluate.py`
(`mosaic_candidates`) implements these checks.

## Presentation

Videos play Mosaic at 30× and 30 fps (`speedup` in `benchmark/release.json`), each station
looping on its own clock. See [Factory replay](../factory/replay.md).
