"""Motion parameters for tests. Every arm and hand action states them (physics/franka_limits.py)."""

MOVE = {'speed_m_s': .06, 'acceleration_m_s2': 2., 'angular_speed_rad_s': .6, 'angular_acceleration_rad_s2': 5.}
JOINT = {'joint_speed_rad_s': .9, 'joint_acceleration_rad_s2': 2.}
GRIPPER = {'speed_m_s': .08}


def move(**parameters):
    """A Cartesian move with the test motion parameters; given ones replace them."""
    return {**MOVE, **parameters}


def joint(**parameters):
    return {**JOINT, **parameters}


def gripper(**parameters):
    return {**GRIPPER, **parameters}


def filled(op, p):
    """The action with the test motion parameters it does not state."""
    p = dict(p)
    if op == 'gripper': p.setdefault('speed_m_s', GRIPPER['speed_m_s'])
    elif 'joint_rad' in p: [p.setdefault(k, v) for k, v in JOINT.items()]
    else: [p.setdefault(k, v) for k, v in MOVE.items()]
    return p
