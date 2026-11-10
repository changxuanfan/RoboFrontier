# Contact physics and release qualification

This document distinguishes the current released scenes from engineering
candidates. No candidate is enabled merely because it passes a unit test or a
passive settling probe. Scene XML, source metadata, asset locks and the policy
release registry must agree before a new default can be published. Historical
recordings always replay with their own frozen inputs.

## Current release

The installed policy lock still selects `policy-assets-rolling003-20261029.tar.gz`.
Mosaic uses R14. The current Transport material cylinders and Dial module disks
and stems use `condim=6` with a rolling-friction length of 0.03 m. This does not
mean every object or contact in every family uses those values. Other geoms,
explicit contact pairs and table parameters retain their own published settings.
The Transport contact cone remains MuJoCo's pyramidal default.

The current task families use a 0.002-second physics step, Newton solving with
100 iterations, and NoSlip iterations of 10 for Transport/Mosaic/Relay or 20
for Dial. A numeric contact audit must inspect compiled parameters and effective
contacts, not infer them solely from a geometry's friction string.

## What the parameters mean

A friction triple describes sliding, torsional and rolling resistance. Sliding
friction is dimensionless; torsional and rolling friction have length units in
MuJoCo. See the official [contact model and friction units](https://mujoco.readthedocs.io/en/stable/computation/#condim).
`0.001` means 1 mm of rolling-friction length, not a generic coefficient
of 0.001. Larger resistance can reduce motion but can also impede intended
rolling and alter grasp/release behavior. Increasing every friction number is
not a general physical fix.

`condim=6` allows three translational and three rotational contact dimensions
(with different solver representations for elliptic and pyramidal cones).
It does not attach an object to the table or guarantee that it will stop.
The friction cone, contact geometry, solver tolerance, NoSlip settings, actuator
contact and explicit pair overrides also matter. NoSlip is a numerical solver
setting, not an extra material friction coefficient.

A newly pushed object can move after release because it still has momentum.
The acceptance concern is unphysical sustained drift, instability or failure to
settle under a controlled initial condition. Gravity on a tilted support,
contact with another object or a force-holding gripper are external influences;
those cases must not be mislabeled as spontaneous zero-force sliding.

## Candidate scope

| Family | Candidate direction | Release status |
| --- | --- | --- |
| Transport | Elliptic cone; only primary material cylinders at `condim=6`, rolling 0.001 m; preserve sliding/torsional settings | Operational qualification incomplete |
| Dial | Elliptic cone; module disks/stems retain rolling 0.03 m; preserve hinges, springs and grips | Further operation qualification required |
| Mosaic | Retain the published contact configuration while extending regression coverage | No new candidate released |
| Relay | Retain published assembly contacts; isolated weight/ring improvements cannot substitute for full assembly checks | No new candidate released |

Changing the global cone also affects contacts beyond cylinders. Cube work,
boards, robot contacts and all task levels therefore need regression coverage.
A 1 mm result on one cylinder cannot qualify every family or all possible poses.

## Reproducible Transport commissioning

Install the Oracle dependency extra and pinned policy assets first. Commit the
source being tested; the command refuses dirty source. It freezes the executor
and creates an independent scene with declared changes, without editing the
release registry, source assets, API configuration or model sessions.

The commissioning script, `scripts/commission_transport_contacts.py`, was
removed on 2026-11-10 (restore from tag `archive/pre-cleanup-20261110`; see the [cleanup log](cleanup-20261110.md)). Its historical invocation was:

```text
commission_transport_contacts --case transport-a12-d2 --object I_item2 --variant elliptic-1mm --operation delivery --wall-s 180 --output runs/engineering/transport-contacts/I-item2-ellipse-1mm
```

For controlled comparisons, run the same case, object and operation with
`--variant released` and `--variant elliptic-30mm`, each in a new output directory.
Select an actual material cylinder: the four-arm Transport scene contains cubes
and is not a cylinder commissioning case. `--operation pickup-release` instead
attempts pickup and replacement near the initial pose using the generic native
reference. A finite planning rejection is not evidence of physical impossibility.

This is privileged mechanical engineering, with zero model inference. It uses
normal bounded Panda commands in one live world, including the existing native
Transport route, handover and socket routines for `delivery`. It adds no object
state writes, attachment or reset. A single-job run reserves its own world;
it is not a measurement of full-task concurrency or an optimal logistics plan.

The independent fixture checks every compiled model array and option before
simulation, allowing only the declared cone and selected rolling changes.
Candidate metadata records parent/current scene hashes and a compiled summary
extended with cone and NoSlip tolerance. Its fingerprint is distinct from the
Legacy summary; old manifests are not rewritten or rehashed. All original
metadata and declared assets are checked again after execution.

Outputs include:

- `candidate-scene/`: portable candidate XML, metadata, assets and receipt;
- `trial/`: native action/process records, source snapshot and compressed motion;
- `result.json`: scope, selected job, errors, unresolved actions and settling data;
- the adjacent `_executor_launches/` directory: the exact frozen executor.

`passed` remains false because this is not a full task attempt. `local_passed`
requires the selected original goal to remain accepted after settling, no process
violations, no unresolved actions, unchanged original inputs, final two-second
linear speed below 0.01 mm/s and angular speed below 0.0001 rad/s. Pickup/release
instead requires actual separation and return within 20 mm of the initial pose.
The five-second settling window and thresholds are engineering checks, not new
benchmark completion tolerances. A failed report and its motion remain evidence.
No failed or uncertain movement is automatically restarted.

## Operational evidence so far

On 2026-11-01, isolated native tests used the released `transport-a12-d2` scene
and identical selected jobs. All results below are partial engineering attempts,
not scored policy trials or full-case Oracle success.

| Selected operation | Released pyramidal / 30 mm | Elliptic / 30 mm | Elliptic / 1 mm |
| --- | --- | --- | --- |
| `H_item3` via `G-F-D-C-B` to `B_slot2` | Finite regrasp route rejected | Donor payload contact remained after unloading | Reached final socket routine; contact remained after withdrawal |
| `I_item2` directly to `I_slot2` | Original goal accepted; settling check passed | Not tested in this comparison | Original goal accepted; settling check passed |

The difficult five-arm chain did not complete under any of the three tested
settings. The different rejection points do not establish a causal explanation
or prove that the 1 mm candidate fixes the full task. The direct job provides a
positive pick/insert/release/settle witness, while full transfer acceptance
remains open. The earlier generic pickup/replacement probe grasped and lifted
`H_item3`, then rejected a return route; it remains a failed commissioning probe.

Raw local evidence is under
`runs/engineering/main-integration-physics-20261101/`. The initial probe's executor
was frozen by bytes as a run-local entry. The maintained command additionally
requires final goal retention after settling and preserves typed stop exceptions.
Its own native verification is recorded separately in the integration ledger.
Do not relabel earlier probe results as validation of later source changes.

## Remaining release gates

Retain the existing release until repeatable pickup, handover, release, seating
and post-release settling are qualified for the selected candidate. Extend
coverage across sizes, levels, disturbance axes, relevant poses and the intended
Linux runtime. Verify Dial turns/spring return, Mosaic seating/tilted blocks and
Relay hanging/hook/weight/ring behavior under their own contracts. Audit finite
states and warnings as well as task outcomes.

After qualification, regenerate matching task/workstation fingerprints and
public metadata, create a new pinned asset package, test fresh installation,
and update policy/Factory defaults together. Old streams retain their original
frozen assets. Passive tests, successful rendering, model ability and a changed
friction number are separate claims and must not be substituted for these gates.
