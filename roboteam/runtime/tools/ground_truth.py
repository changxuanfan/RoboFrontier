"""The robot tool's `state` operation of a ground_truth run (observation_mode.py).

Reads the live world and returns it; nothing here writes to the model or the data.

    {
      "sim_time_s": 12.34,
      "objects": {"<object id>": {"position_m": [x, y, z], "quaternion_wxyz": [w, x, y, z],
                                  "linear_velocity_m_s": [vx, vy, vz],
                                  "angular_velocity_rad_s": [wx, wy, wz]}},
      "joints": {"<joint name>": [position, velocity]},
      "evaluator": {"started": true, ...}
    }

`objects` are the bodies of the task's `objects`, in the world frame (velocities are those of
the body frame's origin, world-aligned). `joints` are the task scene's named joints: a hinge
in rad and rad/s, a slide in m and m/s; a free or ball joint gives its full position and
velocity vectors ([qpos], [qvel]) instead of two numbers. `evaluator` is what the task's
evaluator currently tracks (tasks/evaluate.py Monitor.result), or {"started": false} before
START.

Dial: the evaluator holds the private code, so its part is an explicit list of what the
task's display shows an images role (BEST and the READY lamp) and of physical facts that
do not depend on the code. Nothing says which dial is right.
"""

import mujoco
import numpy as np

from roboteam.sim.hall.world import HALL_PREFIX

# Statistics for the run's report, not task progress.
_REPORT_ONLY = ('motion_definition', 'samples', 'max_sample_gap_s', 'robot_contact_episodes')
# Dial: evaluator fields that do not depend on the code, under the names a role reads.
_DIAL_PHYSICAL = {
    'private_support_ready': 'support_ready',
    'private_red_hold_ready': 'red_hold_ready',
    'private_clearance_m': 'clearance_m',
}
_DIAL_SHARED = ('process_compliant', 'violations', 'sim_time_s', 'inter_robot_contacts', 'self_contacts')


def _numbers(values):
    return [float(x) for x in values]


def objects(world):
    model, data = world.model, world.data
    result = {}
    velocity = np.zeros(6)
    for item in world.task['objects']:
        body = model.body(item['id']).id
        # Rotational then translational velocity, world-aligned, at the body frame's origin.
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, body, velocity, 0)
        result[item['id']] = {
            'position_m': _numbers(data.xpos[body]),
            'quaternion_wxyz': _numbers(data.xquat[body]),
            'linear_velocity_m_s': _numbers(velocity[3:]),
            'angular_velocity_rad_s': _numbers(velocity[:3]),
        }
    return result


def joints(world):
    model, data = world.model, world.data
    result = {}
    scalar = (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE))
    width = {int(mujoco.mjtJoint.mjJNT_FREE): (7, 6), int(mujoco.mjtJoint.mjJNT_BALL): (4, 3)}
    for index in range(model.njnt):
        name = model.joint(index).name
        if not name or name.startswith(HALL_PREFIX):
            continue
        q, v, kind = int(model.jnt_qposadr[index]), int(model.jnt_dofadr[index]), int(model.jnt_type[index])
        if kind in scalar:
            result[name] = [float(data.qpos[q]), float(data.qvel[v])]
        else:
            nq, nv = width[kind]
            result[name] = [_numbers(data.qpos[q : q + nq]), _numbers(data.qvel[v : v + nv])]
    return result


def evaluator(world):
    monitor = getattr(world, 'suite_sampler', None)
    if monitor is None:
        return {'started': False}
    result = monitor.result()
    if world.task['task_type'] != 'dial':
        return {'started': True, **{k: v for k, v in result.items() if k not in _REPORT_ONLY}}
    game = monitor.game
    shown = {
        'started': True,
        # What the apparatus shows: the number on the display and the READY lamp.
        'display': {'value': game.display, 'mode': game.mode, 'status': game.indicator},
        'solved': bool(game.won),
        'valid_trials': int(game.queries),
        **{k: result[k] for k in _DIAL_SHARED if k in result},
        **{name: result[k] for k, name in _DIAL_PHYSICAL.items() if k in result},
    }
    return shown


def state(world):
    """The reply of `state` for a live world."""
    return {
        'sim_time_s': float(world.data.time),
        'objects': objects(world),
        'joints': joints(world),
        'evaluator': evaluator(world),
    }
