"""Per-mesh corrections for shapes that smooth shading or coincident faces would spoil."""
import re

import numpy as np


def keeps_hard_edges(name):
    """Timber corners and arrow tips are real edges, not a curved surface."""
    return '_beam_' in name or name.endswith('_tip')


def shares_shaft_surface(name):
    """A Relay arrow's shaft overlaps its tip at the same height, which renders black."""
    return re.search(r'__relay_direction_\d+_tip$', name) is not None


def thicken_thin_axis(vertices, factor=1.6):
    """Lift a flat mesh's faces clear of a coplanar neighbour, keeping its center."""
    vertices = np.array(vertices, dtype=float)
    axis = int(np.argmin(np.ptp(vertices, axis=0)))
    middle = (vertices[:, axis].min()+vertices[:, axis].max())/2
    vertices[:, axis] = middle+(vertices[:, axis]-middle)*factor
    return vertices
