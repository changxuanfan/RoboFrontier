"""Small frame helpers the Oracle's planners share."""
import math

import numpy as np


def rz(angle):
    """The rotation by `angle` radians about the world z axis."""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]])


def axis_rotation(axis, angle):
    """The rotation by `angle` radians about `axis`."""
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    c, s, v = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return np.array([
        [c + x*x*v, x*y*v - z*s, x*z*v + y*s],
        [y*x*v + z*s, c + y*y*v, y*z*v - x*s],
        [z*x*v - y*s, z*y*v + x*s, c + z*z*v],
    ])


def knob_grasp_rotation(module_rotation, twist):
    """A hand rotation that grasps a Dial knob from above its module, twisted about its axis."""
    z = -module_rotation[:, 2]
    y = module_rotation[:, 0]
    return axis_rotation(z, twist) @ np.column_stack((np.cross(y, z), y, z))
