# Historical MuJoCo / Panda interface review

Recorded review date: **2026-10-19**. These are planning-stage research notes
for the original interactive single-arm application. That review ran no
simulation, installed no software and validated no grasp. It is not the current
benchmark's physical qualification or an instruction to reset a live policy
world. See [physics](../physics.md), [task atlas](../tasks/atlas.md) and
[unified CLI](../unified-cli.md) for current scope.

The linked `stable` documentation and Menagerie `main` can change. Pin MuJoCo
and the Menagerie commit when implementing, then check the actual compiled
model arrays. The recorded model facts and engineering recommendations below
are deliberately distinguished; this translation does not reverify upstream.

## 1. Recorded Panda model facts

Sources: [Menagerie Panda XML](https://github.com/google-deepmind/mujoco_menagerie/blob/main/franka_emika_panda/panda.xml),
[model description](https://github.com/google-deepmind/mujoco_menagerie/blob/main/franka_emika_panda/README.md).

- Standard `panda.xml` has seven arm hinge joints, two finger slide joints and
  eight actuators. The eighth drives both fingers through a tendon, with an
  equality constraint synchronizing them.
- The seven arm `general` actuators implement position PD through `gainprm`
  and `biasprm`. Inputs are joint-position references in radians, not rad/s
  velocity-servo commands.
- The XML defines neither a default keyboard speed nor a general hard joint
  speed cap. Applications must generate reference trajectories. Limiting a
  reference does not guarantee actual `qvel` stays below it: contact forces and
  tracking error affect measured speed.
- Read joint/actuator position ranges from compiled `jnt_range` /
  `actuator_ctrlrange`, rather than hardcoding them only in the input interface:

| Joint | Lower limit, rad | Upper limit, rad | Actuator torque range, N·m |
| --- | ---: | ---: | ---: |
| J1 | -2.8973 | 2.8973 | -87 ... 87 |
| J2 | -1.7628 | 1.7628 | -87 ... 87 |
| J3 | -2.8973 | 2.8973 | -87 ... 87 |
| J4 | -3.0718 | -0.0698 | -87 ... 87 |
| J5 | -2.8973 | 2.8973 | -12 ... 12 |
| J6 | -0.0175 | 3.7525 | -12 ... 12 |
| J7 | -2.8973 | 2.8973 | -12 ... 12 |

These are Menagerie model parameters, not current Franka hardware specifications
or physical-robot safety certification.

- Each finger slides 0 ... 0.04 m, giving about 0.08 m maximum combined opening.
  Gripper control spans 0 ... 255: 0 is a closed-position reference and 255 an
  open-position reference. `forcerange="-100 100"` limits the tendon actuator;
  it does not mean each fingertip applies 100 N.
- Model `home` uses arm
  `q=[0,0,0,-1.57079,0,1.57079,-0.7853]` rad, fingers at 0.04 m and gripper
  ctrl=255. It is an initialization candidate; table tasks must choose a home
  after reachability/collision checks.
- The model uses `implicitfast` and did not explicitly declare a timestep.
  MuJoCo's recorded default was 0.002 s. Set `timestep="0.002"` explicitly
  instead of relying on that default.
  [MJCF option](https://mujoco.readthedocs.io/en/stable/XMLreference.html#option).
- Menagerie's `scene.xml` provides a ground and basic lighting, not the table
  and three free cubes required by the original experiment. Add a project scene
  while preserving upstream model/license provenance. Standard Panda and
  `mjx_panda.xml` differ in gripper, actuators and control ranges; do not mix them.

## 2. Passive viewer and keyboard limitations

Sources: [Python passive viewer](https://mujoco.readthedocs.io/en/stable/python.html#passive-viewer),
[C++ keyboard wrapper](https://github.com/google-deepmind/mujoco/blob/main/python/mujoco/simulate.cc),
[viewer.py](https://github.com/google-deepmind/mujoco/blob/main/python/mujoco/viewer.py).

Recorded fact: macOS `launch_passive` must be launched through MuJoCo's
`mjpython` because of main-thread rendering requirements. The application advances
physics; `sync()` synchronizes GUI and simulation state. Changes to viewer visual
structures must follow its `lock()` contract rather than writing shared data
from arbitrary threads.

Recorded fact: public `key_callback` receives only an integer keycode. The C++
wrapper invokes it only when `IsKeyDownEvent(act)` is true. Python receives no
key-up, action or modifier parameters. This callback alone cannot reliably
maintain multiple held keys; inferring release from timeouts is not equivalent.
Do not obtain the passive viewer's private GLFW window and replace its callbacks.

Engineering recommendation: fixed-duration discrete key actions can use passive
viewer callbacks. Held-key/release behavior, simultaneous joints and focus-loss
stopping favor a small window built with public rendering interfaces, avoiding
global keyboard hooks or OS accessibility permissions.

## 3. Proposed window route: mjv/mjr + GLFW

Sources: [MuJoCo visualization](https://mujoco.readthedocs.io/en/stable/programming/visualization.html),
[rendering](https://mujoco.readthedocs.io/en/stable/programming/rendering.html),
[basic.cc](https://github.com/google-deepmind/mujoco/blob/main/sample/basic.cc),
[GLFW input](https://www.glfw.org/docs/latest/input_guide.html),
[GLFW thread requirements](https://www.glfw.org/docs/latest/intro_guide.html#thread_safety).

Recorded fact: `mjvScene`, `mjvCamera` and `mjv_updateScene` are independent of
the window library; classic OpenGL rendering uses `mjrContext` / `mjr_render`.
The official basic example creates a GLFW window/OpenGL context, advances physics
and renders. GLFW key callbacks provide key/scancode/action/mods, with PRESS,
RELEASE and REPEAT actions, plus a separate focus callback. `glfwGetKey` reads
state recorded from processed events. REPEAT is not an animation clock.

Engineering recommendation: create the window, poll events and render on the
process main thread. Maintain a pressed-key set with PRESS/RELEASE, compute
directional input at a fixed control cadence and ignore OS REPEAT. Clear keys
and revoke motion on lost focus, mode changes, pause and exit. Separate fixed
physics stepping from input/display rates. Combine simultaneous keys into one
seven-dimensional joint vector, canceling opposite directions. Cartesian DLS IK
and joint jog share trajectory limits and one executor; `mj_jacSite` supplies
the end-effector Jacobian.
[Jacobian API](https://mujoco.readthedocs.io/en/stable/APIreference/APIfunctions.html#mj-jacsite).

Normalize the combined Cartesian vector so diagonals are not faster than a
single axis. In joint mode, limit each joint and declare any global scaling.
Record requested values and actual `qvel` in both modes. Contact, singularity
and tracking failures must report actual outcomes rather than equating a request
with achievement.

## 4. Initial state and restoration in the interactive application

Sources: [mj_getState / mj_setState / mj_stateSize](https://mujoco.readthedocs.io/en/stable/APIreference/APIfunctions.html#mj-getstate),
[state flags](https://mujoco.readthedocs.io/en/stable/APIreference/APItypes.html#mjtstate).

Engineering recommendation: explicitly initialize robots, grippers and every
free object, settle, then save `mjSTATE_INTEGRATION`. Before interactive restore,
check model hash, version and vector length; use `mj_setState` and `mj_forward`
to rebuild derived state. Separately retain controller position/velocity
references, gripper reference, mode, speed tier, camera parameters and random
seed. Saving `qpos` alone is insufficient. After adding free cubes, regenerate
the complete initialization instead of reusing a robot-only keyframe length.

In this original application, reset restores a complete initial snapshot; home
is a bounded trajectory during execution. These are different operations.
Simulation is not promised to be bit-identical across MuJoCo versions/platforms.
This planning advice grants no live benchmark reset/restart permission: a lost
policy world is not recreated to continue scoring.

## 5. Video recording

Recorded fact: classic rendering exposes `mjr_readPixels`; Python also provides
an offscreen Renderer. An OpenGL context can be current on only one thread at
a time, and subsequent rendering follows that ownership.
[Python contexts](https://mujoco.readthedocs.io/en/stable/python.html#classic-rendering),
[pixel API](https://mujoco.readthedocs.io/en/stable/APIreference/APIfunctions.html#mjr-readpixels).
MuJoCo produces pixels, not a complete MP4 by itself.

Engineering recommendation: read RGB from the application's rendered framebuffer,
correct vertical orientation and encode with FFmpeg. This records the scene
window without macOS system-screen-recording permission. Keep resolution fixed,
account for Retina framebuffer versus logical window sizes, and bound the
encoding queue so it cannot stall physics. Record simulation time and frame ID;
declare whether video uses simulation or wall time. Preserve JSONL/state evidence
separately, since video is not a trace replacement. A later fixed offscreen
camera stream needs its own macOS context/performance checks.

Current benchmark observation JPGs, compressed motion and optional offline
Factory movies are separate features; this historical recording proposal does
not change their defaults.

## 6. Unverified at the recorded review

These sources supported API selection, not successful desktop-scene grasping.
Cube dimensions/mass/friction, finger contact, home pose, IK gains and trajectory
speed still needed actual tests. The proposed first physical check was open,
approach, close and lift using real contact, without welding, attraction or
teleporting objects. The first stage could use one task/scene, freezing tuned
parameters before a Human/Agent comparison. None of those planning statements
are a current-suite completion claim.
