"""Measure the fraction of each timber centreline over a Goal rectangle.

Diagnostic only until a versioned task contract opts into these semantics.
"""
import math
import numpy as np


def clipped_fraction(a, b, half):
    """Length fraction of a line segment inside an axis-aligned rectangle."""
    a, b, half = (np.asarray(x, dtype=float) for x in (a, b, half))
    if a.shape != (2,) or b.shape != (2,) or half.shape != (2,) or not np.isfinite([*a, *b, *half]).all() or np.any(half <= 0):
        raise ValueError('Invalid goal segment or rectangle')
    low, high = 0., 1.
    for i in range(2):
        delta = b[i] - a[i]
        if abs(delta) < 1e-14:
            if abs(a[i]) > half[i]: return 0.
            continue
        p, q = sorted(((-half[i] - a[i]) / delta, (half[i] - a[i]) / delta))
        low, high = max(low, p), min(high, q)
        if high <= low: return 0.
    return max(0., high - low)


def timber_fraction(model, data, geom_ids, region, tolerance_m=0.):
    """Length-weighted centreline projection; one entry per physical beam segment.

    Component geoms must be explicitly selected to avoid counting the visual
    mesh and its collision proxies twice. The segment centreline must also be
    at or above the target plane; no upper height limit is imposed.
    """
    yaw = float(region['nominal_yaw_rad']); c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])
    center = np.asarray(region['center_m'], dtype=float)
    if not math.isfinite(tolerance_m) or tolerance_m < 0: raise ValueError('Invalid tolerance')
    half = np.asarray(region['half_size_m'], dtype=float) + tolerance_m
    total = inside = 0.
    for gid in geom_ids:
        aabb = model.geom_aabb[gid]
        # Beam collision boxes are tangent pieces: their longitudinal local Y
        # dimension may be shorter than the transverse 45 mm cross-section.
        # Mesh segments use their longest local bounding-box dimension.
        axis = 1 if int(model.geom_type[gid]) == 6 else int(np.argmax(aabb[3:]))
        half_len = float(aabb[3 + axis])
        if half_len <= 0: raise ValueError('Degenerate timber geometry')
        orientation = data.geom_xmat[gid].reshape(3, 3)
        middle = data.geom_xpos[gid] + orientation @ aabb[:3]
        vector = orientation[:, axis] * half_len
        start3 = rotation.T @ (middle - vector - center)
        end3 = rotation.T @ (middle + vector - center)
        if start3[2] < 0 and end3[2] < 0:
            total += 2 * half_len
            continue
        z0, z1 = 0., 1.
        if start3[2] < 0: z0 = -start3[2] / (end3[2] - start3[2])
        if end3[2] < 0: z1 = -start3[2] / (end3[2] - start3[2])
        start = (start3 + z0 * (end3 - start3))[:2]
        end = (start3 + z1 * (end3 - start3))[:2]
        length = 2 * half_len
        total += length; inside += length * (z1 - z0) * clipped_fraction(start, end, half)
    if total <= 0: raise ValueError('No timber segments')
    return inside / total
