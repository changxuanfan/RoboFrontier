"""Small frame helpers the Oracle's planners share."""
import math

import numpy as np


def rz(angle):
    """The rotation by `angle` radians about the world z axis."""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]])
