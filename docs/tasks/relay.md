# Relay tasks and entry points

Relay has nine released cases. Historical Oracle records report completion of
nine cases and 27 beams under the user's final-goal review, retaining failures,
recovery and assistance labels. That statement is provenance, not a new run or
qualification of changed physics. Use the exact frozen scene and task revision
when comparing results.

## Released geometry

| Arms | Layout | Assemblies per case | Initial endpoint chord, L2/L3 |
| --- | --- | --- | --- |
| 8 | Two straight rows | 2 | 1.15 m |
| 12 | 90-degree arc, seven outer/five inner | 3 | 1.15 m |
| 16 | Semicircle, ten outer/six inner | 4 | 1.20 m |

Each scale has Levels 1, 2 and 3. Tables are 0.80 m high. The 16-arm radial row
spacing is 1.40 m; the 12-arm outer/inner radii are 3.46/2.16 m. Level 1 retains
its own apparatus and arrangement. Level 2 uses a 63-degree circular-arc timber.
Level 3 uses a 31.5-degree deflection, 148.5-degree interior angle and passive
out-of-plane springs with limits of +/-25 degrees. On Levels 2 and 3, a fixed eye
attaches directly to the timber underside 100 mm along it from the endpoint,
without a mounting stem, and interlinks with the pendant's eye. The wooden shaft
is 170 mm and its weight is 600 g. Frozen model geometry is authoritative.

## Current policy completion and process records

New policy runs use `terminal_outcome_v2`. Move every assembly from its own
initial position toward the common GOAL; returning it to START is unnecessary.
Controllers choose teams, grasp points, handover locations and schedules.
Independent operations may overlap within role ownership and collision limits.

Final placement may include cargo contact and stacking. Under the current
`relay-timber-goal-70pct-v1` rule, each timber must have at least 70 percent of
its centreline length in the vertical space above the painted GOAL outline, and
every robot must have released it. Table support, direct or through other
cargo, is not required, and there is no speed threshold or stationary-duration
test. Only physical timber segments count, never a pendant, ring or shaft; the
measured fraction is reported per payload as `timber_inside_fraction`.

Tasks prepared before this rule keep the earlier `relay-final-goal-50mm-v1`
rule: the complete assembly within GOAL with at most 50 mm outward tolerance on
each boundary, released and actually supported. A low release may begin when
the lowest assembly part is at most 30 mm above the table; opening the gripper
alone does not establish landing or completion.

New runs also declare `relay-airborne-handover-v1`: a timber counts as complete
only after a qualified airborne handover. A new arm must hold the timber for at
least 0.2 seconds while at least two current holders keep it off the table, and
then a current holder must let go. Pushing or dragging a timber along the table
never qualifies. Off the table means the lowest assembly part is more than 2 mm
above the tabletop and nothing connects the timber to the table, directly or through
other cargo; the receiver's 0.2 seconds restart whenever that stops. A change of
holders while the timber rests in GOAL is recorded with `airborne: false`
(`grounded-regrasp-v1`) and never counts. Handover rows written by this evaluator
carry `protocol: qualified-members-v3` and `airborne: true`; rows of earlier logs
(`qualified-members-v2`) did not check the table, so they may include such regrasps.
Each payload reports `airborne_handover_met`. Runs prepared before
this rule keep their placement-only terminal outcome, and no agent in those runs was
told a handover was required.

Collisions, drops, unsupported transfers and recovery violations remain process
records. They are not an automatic veto on an otherwise valid terminal outcome.
Models may recover through ordinary robot actions. Reset,
respawn, direct object-state writes, welds and history erasure are unavailable.
See [shared START and scoring semantics](../protocol.md#direct-controller-startup-and-terminal-scoring-v2).

`robofrontier/suite/relay_contract.py` defines the current
`relay-timber-goal-70pct-v1` contract (and recognizes the earlier
`relay-final-goal-50mm-v1`); `robofrontier/suite/relay_goal_fraction.py` measures
the centreline fraction. `robofrontier/task_families.py` applies the
new-run terminal overlay and freezes the corresponding public guidance. Do not
publish the older clean-process vetoes as the current policy completion rule. Old
recordings retain their original contract and native verdict.

## Execution and reference code

Use the [unified CLI](../unified-cli.md) for native model runs and the
[Oracle interface](../oracle/README.md) for privileged references. Unified Oracle execution
has a configurable 24-hour engineering limit from owner launch, separate from
the policy's START clock. An Oracle monitor's engineering corrections are not
an autonomous model result.

Legacy `scripts/run_relay_nine_oracles.py` reads nine cases from
`benchmark/relay/catalog.json` and
`configs/harness-frontier-v2-servo2.json`. Its old default has no total deadline;
individual action deadlines, STOP and uncertain-result protection remain.
`run_relay_live_oracle.py` handles individual reference executions. Local static
input inspection invokes neither a model nor task physics:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. \
  .venv/bin/python -m scripts.run_relay_nine_oracles --check-inputs
```

| Module, under `robofrontier/` unless stated | Responsibility |
| --- | --- |
| `suite/relay_contract.py` | Base rules, projections, input checks and default native paths |
| `suite/relay_oracle_v2.py`, `suite/relay_pipeline.py` | Private reference planning and parallel execution frontiers |
| `suite/relay_live_recovery.py` | Typed legacy recovery with request/execution evidence |
| `suite/relay_user_goal_policy.py`, `suite/relay_contact_escape.py`, `suite/relay_donor_staging.py` | Goal release, bounded contact escape and donor clearing |
| `suite/relay_observation_state.py` | Privileged readonly state evidence |
| `suite/relay_scene.py`, `suite/relay_underslung.py`, `suite/rigid_relay.py` | Geometry and retained builders |
| `relay_video_motion.py`, `relay_motion_edit.py` | Background-independent motion analysis and time mapping |
| `scripts/analyze_relay_motion.py` | Derive editing decisions; no additional old 16-fps export |
| `scripts/export_relay_edited.py` | Derived 60-Hz tracks and 20x/30-fps simple-background videos; Factory video uses Cycles |

## Historical data and handoff

The following local records are not included by Git clone and do not establish
new current-source qualification:

- Completion selection: `runs/oracle/relay-r16-38b5423-20261026-171651/USER-GOAL-ALL-NINE-COMPLETE.json`.
- Level 1 originals: `runs/oracle/relay-nine-ab1abec-20261026-032833/`.
- Levels 2/3 originals: `runs/oracle/relay-r16-38b5423-20261026-171651/`.
- Videos/frame maps: `outputs/oracle/relay-20x-20261027/report.md`.
- Independent edited tracks: `outputs/oracle/relay-edited-tracks-20261027/`.
- Retained dependencies and retired-source manifest: `runs/engineering/relay-cleanup-20261027/manifest.json`.

Original 60-Hz streams, appearance events, failure/recovery/control-correction
hashes, reports and videos remain evidence. See [recording and replay](../oracle/relay-recorded-video.md),
[merge notes](../archive/plans/suite-v2/relay-merge-handoff.md) and the
[current task-family entry](README.md). Historical Factory presentations use
independent per-table loops at 20x/30 fps; static neighboring tables do not imply
simultaneous task completion.
