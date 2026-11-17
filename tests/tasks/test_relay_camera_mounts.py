"""Relay publishes its cameras' mounts, and they are the poses MuJoCo renders from."""
from pathlib import Path
import sys
import tempfile
import unittest

import mujoco
import numpy as np

from roboteam.tasks.families import ROOT, RELEASE, read, prepare

sys.path.insert(0, str(ROOT/'scripts'))
import build_release


class RelayCameraMountTests(unittest.TestCase):
    def assert_mounts_match_scene(self, public, folder):
        """Every camera of the public task has a mount, and each mount is that camera's world
        pose and field of view in the scene compiled from `folder`."""
        model = build_release.compile_scene(folder)
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        mounts = public['static_camera_mounts']
        self.assertEqual([m['id'] for m in mounts], public['cameras'])
        self.assertEqual(len(mounts), model.ncam)
        for mount in mounts:
            with self.subTest(camera=mount['id']):
                self.assertEqual(sorted(mount), ['fixed_world', 'frame', 'id', 'position_m', 'quaternion_wxyz',
                                                 'vertical_fov_deg'])
                camera = model.camera(mount['id']).id
                # Fixed to the world, so the pose of the first frame holds for the whole run.
                self.assertEqual(int(model.cam_bodyid[camera]), 0)
                self.assertEqual(int(model.cam_mode[camera]), int(mujoco.mjtCamLight.mjCAMLIGHT_FIXED))
                self.assertEqual((mount['frame'], mount['fixed_world']), ('world', True))
                # data.cam_xpos and data.cam_xmat are the world pose the renderer reads.
                np.testing.assert_allclose(mount['position_m'], data.cam_xpos[camera], rtol=0, atol=1e-12)
                rotation = np.zeros(9)
                mujoco.mju_quat2Mat(rotation, np.array(mount['quaternion_wxyz']))
                np.testing.assert_allclose(rotation, data.cam_xmat[camera], rtol=0, atol=1e-12)
                self.assertEqual(mount['vertical_fov_deg'], float(model.cam_fovy[camera]))
        return model

    def test_every_released_relay_task_publishes_the_pose_mujoco_gives_each_camera(self):
        cases = read(ROOT/RELEASE)['families']['relay']['gpt']
        self.assertEqual(len(cases), 9)
        for case in cases:
            with self.subTest(case=case['id']):
                folder = ROOT/case['directory']
                public = read(folder/'public/task.json')
                model = self.assert_mounts_match_scene(public, folder)
                # The file holds what the release builder derives from the scene. Floats may
                # differ in their last digit between platforms, so they are compared closely.
                built = build_release.camera_mounts(model, public['cameras'])
                self.assertEqual(len(public['static_camera_mounts']), len(built))
                for kept, made in zip(public['static_camera_mounts'], built):
                    self.assertEqual(kept.keys(), made.keys())
                    for key, value in kept.items():
                        if isinstance(value, list) and value and isinstance(value[0], float):
                            for x, y in zip(value, made[key]): self.assertAlmostEqual(x, y, places=12)
                        elif isinstance(value, float): self.assertAlmostEqual(value, made[key], places=12)
                        else: self.assertEqual(value, made[key])

    def test_a_prepared_relay_run_receives_the_mounts_of_its_own_frozen_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = prepare('relay-a08-d1', Path(tmp)/'relay')
            public = read(run/'public/inputs/task.json')
            self.assert_mounts_match_scene(public, run/'private/inputs/scene')

    def test_a_camera_that_moves_or_is_missing_is_refused(self):
        scene = ('<mujoco><worldbody><camera name="fixed" pos="1 2 3" fovy="40"/>'
                 '<body name="arm" pos="0 0 1"><camera name="on_arm"/><geom size=".1"/></body></worldbody></mujoco>')
        model = mujoco.MjModel.from_xml_string(scene)
        with self.assertRaisesRegex(ValueError, 'not fixed in the world: on_arm'):
            build_release.camera_mounts(model, ['fixed', 'on_arm'])
        with self.assertRaisesRegex(ValueError, 'differs from the compiled scene'):
            build_release.camera_mounts(model, ['fixed'])


if __name__ == '__main__':
    unittest.main()
