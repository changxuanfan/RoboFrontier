import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from robofrontier.factory.workstations import colour_compatible_signature


class FactorySourceCompatibilityTest(unittest.TestCase):
    def test_only_colour_changes_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def signature(xml, asset=b'asset'):
                (root/'scene.xml').write_text(xml)
                (root/'assets').mkdir(exist_ok=True)
                (root/'assets/mesh.obj').write_bytes(asset)
                return colour_compatible_signature(SimpleNamespace(path=root, manifest={"case":{"family":"mosaic"}}))
            baseline = signature('<mujoco><worldbody><geom name="A_stock01_geom" rgba="1 0 0 1" size="1"/></worldbody></mujoco>')
            self.assertEqual(baseline, signature('<mujoco><worldbody><geom name="A_stock01_geom" rgba="0 1 0 1" size="1"/></worldbody></mujoco>'))
            self.assertNotEqual(baseline, signature('<mujoco><worldbody><geom name="A_stock01_geom" rgba="1 0 0 1" size="2"/></worldbody></mujoco>'))
            self.assertNotEqual(baseline, signature('<mujoco><worldbody><geom name="A_stock01_geom" rgba="1 0 0 1" size="1"/></worldbody></mujoco>', b'other'))
