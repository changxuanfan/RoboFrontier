# Experiment three: eight-arm airborne beam handoff, environment preview v1

This is the historical environment and integration record, rather than the
current suite's default task. Eight Franka Panda arms occupy four columns,
with two arms facing across the table in each column. In top view, columns
run left to right as A/B, C/D, E/F, G/H. A/C/E/G are south; B/D/F/H are north.
The beam spans the table width and travels right along its length.

| Parameter | Initial value |
| --- | --- |
| Long table | 3.30 × 2.10 m, tabletop height 0.40 m |
| Adjacent-column base spacing | 0.72 m |
| Facing base spacing | 1.70 m |
| Beam | Length 1.20 m × width 45 mm × height 45 mm |
| Beam mass | 1.458 kg, density 600 kg/m³ |
| Start/end center | World X = −1.25 m, +1.48 m |

`parameters.json` is the geometry authority. Parameter changes require
regenerating the environment; the saved `initial` keyframe contains the complete
settled initialization. The scene has a light-blue background, oak-colored table
and darker wood-grain beam. Number labels, arrows and start/end borders do not
collide. The beam is one rigid body with a freejoint, real contact, gravity and
friction, without attachment or grasp welds.

Build: `.venv/bin/python -m scripts.build_beam_handoff`.

Native preview: `.venv/bin/mjpython -m scripts.view_beam_handoff`. F6 cycles global,
top, alternate global and four column closeups. F7 resets initialization.
macOS may require Fn＋F6/F7.

`task-draft.json` records goals and proposed acceptance rules: carry with two-arm
support; establish receiver support before the sender releases; count drops as
failed attempts and allow recovery only by the sender; finally place within the
right-end region. A/B initially owns custody, which transfers only after a
successful handoff. Falling outside recovery range must be reported as failure;
automatic reset or receiver pickup cannot bypass handoff. Grasp locations,
grouping, order, pose and concurrency are left to the policy.

`validation.json` checks only loading, home IK, initial contacts and settled
stability, rather than grasp/handoff success. Initial preview work used neither
a multimodal agent nor added policy tools; later integration is described below. Two-arm
support is a task rule; physical impossibility of single-arm carrying was not
established.

Two initial Oracle lifts retained dimensions, mass, friction and the original
position-controlled gripper parameters. Both tested grasp heights slipped before
handoff. Closing from the current 45 mm aperture to zero generated about 2.25 N
tendon drive per gripper, rather than its 100 N force limit. The original
engineering report is `runs/beam-handoff-oracle-20261022/README.md`.

The shared controller subsequently gained explicit grasp mode using declared
grasp force/speed. Candidate-graph search first screened initial grasp points,
receiver acquisition, release and withdrawal. Physical attempt-07 retained
original dimensions, mass, friction and NoSlip, completed three airborne
handoffs A/B→C/D→E/F→G/H and finally placed the beam. Cross-arm contact checks
every 2 ms recorded no collisions. All actions totaled 60, over 251.12 s of
simulation. Grasp mode's software drive envelope was 70 N without increasing
the original actuator hard limit. This was an Oracle feasibility reference,
without a GPT trial, real-robot calibration, recovery-policy or all-path
certification. See the original control/planning record at `runs/beam-handoff-grasp-20261022/README.md`.

## Historical policy integration

`task.json` allows `scripts.create_pipeline_run --task` to prepare Single,
Coordinator/Workers, Peer or Adaptive runs; preparation starts neither physics
nor a model. `task-draft.json` remains the design note. Formal rules and thresholds
come from each run's frozen `task.json`. These topology names are historical.

Private evaluation records airborne support, receiver/sender grasp overlap,
custody, drops/sender recovery, cross-arm collisions, and complete entry,
release and stability at the destination. Bilateral positive contact force and
airborne retention are declared support proxies, without establishing the load
borne by each arm. Drops count as failed attempts; valid recovery permits
continuation. Receiver pickup violations, unverified handoff and above-tolerance
collisions fail compliance. Public fixed thresholds govern handoff overlap and
brief contact loss. Policy tools return neither live truth nor scores. Final
table contact is exempt only after complete destination entry with prior support;
an agent's self-reported phase grants no exemption.

The 23 fixed views comprise two global views, top, four pair closeups and each
of eight arms' front/side views. Agents choose observations. Initial geometry
and robot proprioceptive information are public; ongoing object truth and the
Oracle route are private. action_batch guarantees only same-cycle command
start, without simultaneous arrival or stable shared holding. The policy chooses
checks, batches and forks; each role controls only the robots it owns.

2026-10-23 integration update: public task.json includes full scoring consequences
and two planning-risk notes, sharing event definitions with private evaluation.
Optional action_batch sync_group lets different roles submit their own current
commands. Matching participants/deadlines, complete submissions and revalidation
are required before same-cycle start; waiting does not occupy unrelated robots.
Single, Adaptive, Coordinator/Workers and Peer share the execution path.
Coordinator/Meta has no physical control authority. This aligns protocol
capabilities, without qualifying four model policies or real-robot synchronization.
