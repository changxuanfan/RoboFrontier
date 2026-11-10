"""Factory capsules must keep MuJoCo's length, not collapse into spheres."""
import math
from pathlib import Path
import unittest

import numpy as np

from robofrontier.factory.blender.factory_capsule import capsule_vertices


def unit_sphere(rings):
    points = []
    for ring in range(rings + 1):
        polar = math.pi * ring / rings
        for step in range(8):
            azimuth = 2 * math.pi * step / 8
            points.append((math.sin(polar) * math.cos(azimuth), math.sin(polar) * math.sin(azimuth), math.cos(polar)))
    return np.array(points)


class CapsuleTests(unittest.TestCase):
    def test_extent_matches_radius_and_half_length(self):
        # The Dial crank arm: radius 10 mm, half-length 41.5 mm.
        v = capsule_vertices(unit_sphere(13), .01, .0415)
        self.assertAlmostEqual(v[:, 2].max(), .0515)
        self.assertAlmostEqual(v[:, 2].min(), -.0515)
        self.assertLessEqual(np.hypot(v[:, 0], v[:, 1]).max(), .01 + 1e-12)

    def test_wall_is_straight_between_the_caps(self):
        v = capsule_vertices(unit_sphere(13), .01, .0415)
        self.assertFalse(np.any(np.abs(v[:, 2]) < .0415))

    def test_rejects_template_with_equator_vertices(self):
        with self.assertRaises(ValueError):
            capsule_vertices(unit_sphere(12), .01, .0415)

    def test_renderer_template_has_no_equator_vertices(self):
        source = (Path(__file__).parents[1] / 'robofrontier/factory/blender/render.py').read_text()
        self.assertIn('create_uvsphere(bm,u_segments=24,v_segments=13', source)


if __name__ == '__main__':
    unittest.main()
