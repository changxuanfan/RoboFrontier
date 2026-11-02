> Legacy README snapshot from before the 2026-10-27 cleanup. Commands and claims
> below describe that historical checkout, not the unified CLI or current release
> qualification. See the [current README](../../../README.md). The old interactive
> executable is now `robofrontier-demo`; `robofrontier` selects the unified CLI.

# RoboFrontier: historical project state

At this snapshot, Frontier V2 comprised four families and 36 environments:
Transport, Mosaic, airborne Relay and a dial codebreaker. The environment draft
used nine Transport R13 cases plus 27 R10 cases, 80-cm tables and 2-ms steps;
older versions remained available. R13 had local manipulation and two-arm
serial/parallel comparisons, not a full Oracle run. Existing same-configuration
R10 evidence completed **18/36** cases, which did not establish efficiency or
transfer to changed versions. Static construction and local success were not
whole-task passes.

A separately authorized minimum-scale GPT probe ran **12 tasks**, Adaptive,
`gpt-6.1-sol/high`, at most 20 minutes after START per task; two fully passed.
All model/physics processes ended and all 12 original-speed videos passed full
decode. This was not 36-case Oracle certification. Oracle grasp points and
engineering experience were not supplied to the policies. Its retired local
results/video directory was
`outputs/gpt/frontier-v2-minimum-20m-20261025/README.md`, not distributed here.

- [36-environment catalog](../../tasks/README.md).
- [Transport R11 scope and static checks](transport-r11.md).
- [Transport R12 goal-spacing changes](transport-r12.md).
- [Transport R13 whiteboard shortened by 20 mm](transport-r13.md).
- [R13 commissioning and real serial/parallel comparisons](transport-r13-units.md).
- [R10, Factory V6, replay and run layout](../plans/suite-v2/implementation-r10.md).
- [Frozen 36-case R10 inputs](../../../configs/suites/frontier-v2-r10.json).
- Retired R10 pd1000-v1 Oracle index: `runs/oracle/suite-v2-r10-closure-20261025/coverage-current.json`.
- Retired passed/failed Oracle videos: `outputs/oracle/review-20261025/index.html`.
- Retired parallel-Oracle review: `runs/oracle/suite-v2-r10-servo2-20261025/review.md`.
- Retired original legacy-driver results: `runs/oracle/suite-v2-r10-20261025/summary.json`.
- Retired Factory preview: `outputs/robo-factory/v6-cycles-final/interior_diagonal.png`.

The older pilots and keyboard exercise below did not automatically qualify the
then-current 36 environments:

- [Next iteration and gates](../next-iteration-plan.md).
- Retired trial04 efficiency review: `runs/trial04-efficiency-audit-20261020/report.md`;
  fixes: `runs/efficiency-fixes-20261020/report.md`.
- [Architecture and context](../../architecture.md).
- [Meta setup and management](../../meta-runbook.md).
- [Harness acceptance scope](../../harness-v2-verification.md).
- [Controller/Worker skill](../../../prompts/skills/robot-collaboration/SKILL.md).
- [Four-arm 10x10 Mosaic](../../../configs/environments/mosaic/four-arm-10x10/README.md).
- [Eight-arm opposing-pair beam environment](../../../configs/environments/beam_handoff/facing-08/README.md).
- [Command semantics and grasp-force audit](../robot-command-reality-audit-20261022.md):
  shared multi-arm tools added grasp mode; the keyboard exercise kept position control.
- [3–12-arm cube/cylinder standalone catalog](../../../configs/suites/cube_transport_cylinders/README.md).
- Earlier cube/sphere catalog: `benchmarks/cube_transport/README.md`, removed from the tree; it is kept at tag `archive/pre-prune-20261103`.
- [Historical pilots and diagnostics](.).

Historical preparation: `uv run python scripts/create_pipeline_run.py runs/NEW`.
Offline checks: `uv run python scripts/check_harness.py`. Neither created model
sessions or robot actions; starting physics was a separate explicit step.

## Original single-arm keyboard exercise

A local MuJoCo demo used one fixed-base Panda, seven arm DoFs, a two-finger
parallel gripper and three free cubes. Keyboard input moved the end effector;
IK and upstream position actuators drove the robot. Grasps relied on contact
and friction.

The historical default was `configs/noslip.json` (`noslip-10-v1`), enabling
10 NoSlip postprocessing iterations while retaining friction, gripper strength,
mass and speed. `config.json` retained original settings. Contact variants needed
separate records. NoSlip addressed slow slip in that case, not every grasp pose.
An RGB attempt lifted the randomized blue cube for over 38 s; evidence was in
`docs/history/noslip-validation-20261019.md`, separate from earlier failures and
the fixed-coordinate reference controller.

## Historical installation and window controls

The original checkout provided `Launch Demo.command` or `uv run robofrontier`.
These are historical commands; use the current demo entry when reproducing the
exercise in the unified repository. The original setup first installed
[uv](https://docs.astral.sh/uv/) and FFmpeg. On another machine, its commands were:

```sh
uv sync --locked
uv run python scripts/fetch_robot.py
uv run robofrontier
```

That version was checked on Apple Silicon macOS, Python 3.12.6 and MuJoCo 3.16.0,
with `.venv` and `uv.lock`. Focus the simulation and use an English keyboard.
macOS may require Fn for function keys assigned to brightness/media controls.

| Operation | Keys |
| --- | --- |
| Planar translation | Arrows; up is -X, away from the front camera; down +X, left -Y, right +Y |
| Raise/lower TCP | W/S |
| Gripper yaw | A/D |
| Open/close | O/P |
| Slow/normal/fast | `[` / `]` |
| End-effector/seven-joint mode | Tab |
| Front/side camera | C; world-relative controls stay unchanged |
| Restore identical initial state | Backspace, labeled Delete on Mac |
| Debug physics pause/resume | Space |
| Start/stop recording | F9 |
| Show/hide help | F1 |
| Save and exit | Esc |

Normal TCP speed was 3 cm/s, slow 1 cm/s, fast 6 cm/s. Holding a key continued
motion; release decelerated and held while physics continued. Losing focus
cleared motion input and held position without freezing gravity. Multi-axis
translation was bounded by the combined speed. The yellow TCP marker identified
the finger pinch center. Operators aligned in front view, checked height from
the side, lowered opposite fingers around a cube, closed with P and raised with
W. Backspace restored the exact initial state after failure; that reset was a
demo operation, not permission to reset a benchmark episode.

| Joint | Positive/negative keys |
| --- | --- |
| J1 | Q/A |
| J2 | W/S |
| J3 | E/D |
| J4 | R/F |
| J5 | T/G |
| J6 | Y/H |
| J7 | U/J |

Multiple joints could move together; opposite keys for one joint canceled.
Keyboard hardware could limit combinations. Normal reference speed was 15 deg/s,
slow/fast 5/30 deg/s, with 60 deg/s^2 reference acceleration. The upper-right
feedback displayed actual speed; position servos did not guarantee actual speed
was bounded by the reference.

## IK and imported robot

- `scripts/fetch_robot.py` fetched Google DeepMind MuJoCo Menagerie's Panda MJCF,
  67 referenced meshes and license. The pin was
  `62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35`; hashes were in `vendor/panda/SOURCE.json`.
- `robofrontier/scene.py` assembled the fixed base, table, cubes, cameras and TCP
  site in memory without rewriting upstream files. Each episode saved `scene.xml`.
- MuJoCo supplied forward kinematics and Jacobians. The small numerical damped
  least-squares IK solver in `robofrontier/sim.py` used robot configuration,
  kinematics and desired TCP pose, not live cube truth.
- Keyboard input produced small TCP targets, IK produced bounded joint
  references, and upstream position actuators drove MuJoCo contact physics.
- No attachment, grasp weld or live object-position write performed the grasp.
  IK did not identify cubes, align the gripper or choose closing time.

## Configuration, logs and video

`config.json` contained table/cube dimensions, mass, friction, speed, workspace,
initial TCP and cameras. Defaults were 2-ms physics, 100-Hz control and a 1-s
settle before recording the initial state. Reset restored full integration and
controller references. Each launch/reset created `runs/<date-time>/`:

- `metadata.json`: settings, model hash, versions, source and initial references.
- `scene.xml`: fully assembled scene.
- `initial.npz`: initial simulation and controller state.
- `trace.jsonl`: approximately 10-Hz inputs, robot/object/physics state and video
  events; demo diagnostics, not a formal per-action research protocol.
- `recording-XX.mp4`: F9-controlled 1280x800, 30-FPS camera video with status,
  encoded directly from MuJoCo pixels without macOS screen-recording permission.

Video used wall time; logs retained simulation and wall clocks. Encoding was
asynchronous with a bounded queue and recorded failures/drops. Reset ended the
old recording to keep initial states separate. No standalone replay UI existed.

## Historical verification scope

```sh
uv run python scripts/verify_demo.py
uv run python scripts/verify_demo.py --config configs/noslip.json --hold-seconds 30
```

The NoSlip reference lifted the blue cube about 12 cm from the same initial
state three consecutive times, holding each for 30 s with about 0.05-mm drift.
`runs/verification-noslip.json` was reference-controller physics evidence, not
vision-model/GPT performance. Original `runs/verification.json` recorded 30 s
idle without evident drift/divergence; full reset; simultaneous two-joint motion,
hold/mode switching; bounded target accumulation during downward input; three
blue-cube lifts of about 9.5 cm with about 4.6 s contact hold; and native-window,
screenshot and H.264 encoding checks.

The demo had keyboard and RGB/proprioceptive tool control in one continuing
world, using `Simulation.control()`. It did not yet implement a standalone GPT
API client, MCP registration, experiment matrix or statistical evaluation.

## Historical local Codex bridge

```sh
uv run robofrontier --bridge --blind --record
```

`--blind` randomized cubes at initialization without returning their coordinates.
Policies used RGB and robot proprioception; two fixed cameras matched the C-key
views. Internal full state was diagnostic only. Policies were prohibited from
reading `metadata.json`, `scene.xml`, `initial.npz` or private `trace.jsonl` for
object truth. This was an experimental restriction, not OS-level isolation.
A second terminal or command tool could invoke:

```sh
uv run python -m robofrontier.client observe
uv run python -m robofrontier.client move --dy -0.002 --duration 0.5
uv run python -m robofrontier.client move --dx 0.06 --duration 1 --speed fast
uv run python -m robofrontier.client gripper close
uv run python -m robofrontier.client wait --duration 1
uv run python -m robofrontier.client record stop
```

Each move selected slow/normal/fast TCP and joint references, retaining the
60-deg/s^2 joint acceleration limit. Duration was 0.1–4 s; displacement limits
were TCP speed times duration, approximately 4/12/24 cm maximum per step.
Gripper/wait actions remained at most 2 s and yaw at most 10 degrees. Fast
served clear high approaches; slow served final alignment. Results reported
actual position, without exact displacement guarantees, after 0.35 s of
bounded deceleration/settle and front/side capture. Physics continued during
model deliberation. This was a bounded-velocity interface, not a precise pose
planner.

The server bound loopback only. Ignored `.robot-bridge.json` held its token;
HTTP threads queued requests and the GUI thread executed physics/rendering.
`--request-id` allowed explicit IDs; same-ID/same-argument retries returned the
cached result without replay. Space interrupted tool motion. No object-state,
depth, automatic-pick or implicit reset endpoint existed. Later launches wrote
public requests/results separately to `policy.jsonl`, apart from private truth.
The first RGB attempt was documented in `docs/history/rgb-attempt-20261019.md`;
its result was distinct from fixed-coordinate reference success.

Joint exploration offered basic limits and target-error checks, not global
collision avoidance. Collisions remained physical; demo reset could recover a
bad posture. These simulation settings were not real-hardware control settings.

## Primary references

- [Menagerie Panda](https://github.com/google-deepmind/mujoco_menagerie/tree/main/franka_emika_panda).
- [MuJoCo Python API](https://mujoco.readthedocs.io/en/stable/python.html).
- [MuJoCo visualization](https://mujoco.readthedocs.io/en/stable/programming/visualization.html).
- Further local notes: `docs/mujoco-official-notes.md`, `docs/vla-action-spaces.md`.

The historical eight-arm beam's formal adapter input was
[task.json](../../../configs/environments/beam_handoff/facing-08/task.json), using the
shared runtime. Private task evaluation and generic synchronized submission were
implemented in beam_task/action_batch. This was engineering integration, not GPT
performance or permission to substitute Oracle playback for a model result.
See the [environment guide](../../../configs/environments/beam_handoff/facing-08/README.md).
