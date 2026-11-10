"""The saved compiled scene uses paths relative to its folder."""
import os
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from robofrontier.runtime.pipeline import portable_xml


class PortableSceneTests(unittest.TestCase):
    def test_absolute_asset_paths_become_relative_to_the_saved_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp).resolve()
            xml = ('<mujoco><compiler meshdir="%s" texturedir="relative/tex"/><asset>'
                   '<texture name="t" file="%s"/><mesh name="m" file="robot/link0.stl"/></asset></mujoco>'
                   % (run / 'private/inputs/scene/assets/robot', run / 'private/inputs/scene/assets/label.png'))
            root = ET.fromstring(portable_xml(xml, run / 'private/outputs'))
            self.assertEqual(root.find('compiler').get('meshdir'), os.path.join('..', 'inputs', 'scene', 'assets', 'robot'))
            self.assertEqual(root.find('compiler').get('texturedir'), 'relative/tex')
            self.assertEqual(root.find('asset/texture').get('file'), os.path.join('..', 'inputs', 'scene', 'assets', 'label.png'))
            self.assertEqual(root.find('asset/mesh').get('file'), 'robot/link0.stl')


if __name__ == '__main__': unittest.main()
