"""The same local top-face points must sample the same source image as MuJoCo."""
import unittest
from scripts.factory_primitive_uv import primitive_uv


class PrimitiveUVTests(unittest.TestCase):
    def test_cylinder_top_and_box_top_have_distinct_mujoco_orientation(self):
        # Blender UV v=1 is the top of the exported image. MuJoCo's cylinder
        # top maps north to image bottom; its box top maps north to image top.
        self.assertEqual(primitive_uv(5, (0., 1., 1.), (0., 0., 1.)), (.5, 0.))
        self.assertEqual(primitive_uv(6, (0., 1., 1.), (0., 0., 1.)), (.5, 1.))
        self.assertEqual(primitive_uv(5, (1., 0., 1.), (0., 0., 1.)), (1., .5))


if __name__ == '__main__':
    unittest.main()
