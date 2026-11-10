"""Capsule geometry for the factory renderer.

MuJoCo stores a capsule as (radius, half-length along local z). The unit mesh is
a UV sphere with no vertices on its equator, so each hemisphere can move apart
as one rigid cap and the band between them becomes the straight wall.
"""
import numpy as np


def capsule_vertices(unit, radius, half_length):
    unit = np.asarray(unit, dtype=float)
    if half_length > 0 and np.any(np.abs(unit[:, 2]) < 1e-9):
        raise ValueError('Capsule template must have no vertices on its equator')
    vertices = unit * radius
    vertices[:, 2] += np.sign(unit[:, 2]) * half_length
    return vertices
