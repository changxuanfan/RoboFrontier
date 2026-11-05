import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import mujoco
import numpy as np

from robofrontier.physics_profile import PROFILES, SLEEP, IdleSleep, attach
from robofrontier.motion_query import object_poses
from robofrontier.task_config import load_harness

BOX = '''<mujoco><option timestep="0.002"/><worldbody><geom type="plane" size="1 1 .1"/>
<body><freejoint/><geom type="box" size=".03 .03 .03" mass=".1" pos="0 0 .03"/></body></worldbody></mujoco>'''


def world(family='transport'):
    model = mujoco.MjModel.from_xml_string(BOX)
    arm = SimpleNamespace(job=None)
    return SimpleNamespace(model=model, data=mujoco.MjData(model), arms={'A': arm}, task={'family': family})


class ProfileTests(unittest.TestCase):
    def test_no_profile_changes_nothing(self):
        w = world();before = w.model.opt.noslip_tolerance
        self.assertIsNone(attach(w, {}))
        self.assertEqual(w.model.opt.noslip_tolerance, before)
        self.assertFalse(w.model.opt.enableflags & SLEEP)

    def test_every_family_has_settings(self):
        self.assertEqual(set(PROFILES['realtime-v1']), {'mosaic', 'transport', 'dial', 'relay'})

    def test_mosaic_sleeps_always_and_keeps_solver_settings(self):
        w = world('mosaic');before = w.model.opt.noslip_tolerance
        self.assertIsNone(attach(w, {'physics_profile': 'realtime-v1'}))
        self.assertTrue(w.model.opt.enableflags & SLEEP)
        self.assertEqual(w.model.opt.noslip_tolerance, before)

    def test_idle_sleep_follows_the_arms(self):
        w = world();governor = attach(w, {'physics_profile': 'realtime-v1'})
        self.assertEqual(w.model.opt.noslip_tolerance, 1e-12)
        governor.before_step();self.assertFalse(w.model.opt.enableflags & SLEEP)
        w.data.time = 2.;governor.before_step();self.assertTrue(w.model.opt.enableflags & SLEEP)
        w.arms['A'].job = 'call';governor.before_step();self.assertFalse(w.model.opt.enableflags & SLEEP)
        w.arms['A'].job = None;w.data.time = 3.;governor.before_step();self.assertFalse(w.model.opt.enableflags & SLEEP)
        w.data.time = 4.;governor.before_step();self.assertTrue(w.model.opt.enableflags & SLEEP)

    def test_settling_delays_the_first_sleep(self):
        w = world('relay');governor = attach(w, {'physics_profile': 'realtime-v1'})
        w.data.time = 29.;governor.before_step();self.assertFalse(w.model.opt.enableflags & SLEEP)
        w.data.time = 30.;governor.before_step();self.assertTrue(w.model.opt.enableflags & SLEEP)

    def test_harness_rejects_an_unknown_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = json.loads(Path('configs/harnesses/policy.json').read_text())
            path = Path(folder)/'h.json';path.write_text(json.dumps({**harness, 'physics_profile': 'fast'}))
            with self.assertRaises(ValueError):load_harness(path)


class MotionQueryTests(unittest.TestCase):
    def test_pose_is_the_last_frame_at_or_before_the_time(self):
        with tempfile.TemporaryDirectory() as folder:
            motion = Path(folder)/'private/outputs/motion';(motion/'source').mkdir(parents=True)
            (motion/'source/workstation.json').write_text(json.dumps({'joints': [{'id': 'hinge', 'body': 'door', 'type': 3, 'qpos_address': 0}, {'id': 'box_free', 'body': 'box', 'type': 0, 'qpos_address': 1}]}))
            states = np.array([[0, 1, 2, 3, 1, 0, 0, 0], [0, 4, 5, 6, 1, 0, 0, 0]], dtype='<f4').view('<u4')
            base = states[0].copy();xor = np.zeros_like(states);xor[1] = states[0]^states[1]
            np.savez(motion/'chunk.npz', base=base, xor=xor, time_s=np.array([1., 2.]))
            (motion/'stream.json').write_text(json.dumps({'chunks': [{'file': 'chunk.npz'}]}))
            self.assertEqual(object_poses(folder, 1.5)['box']['position_m'], [1, 2, 3])
            self.assertEqual(object_poses(folder, 2.)['box']['position_m'], [4, 5, 6])
            with self.assertRaises(ValueError):object_poses(folder, .5)


if __name__ == '__main__': unittest.main()
