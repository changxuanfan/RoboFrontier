"""Released scenes carry the release physics; the runtime adds only sleep and settling."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import mujoco
import numpy as np

from robofrontier.physics.profile import FAMILIES, SLEEP, IdleSleep, attach, forward_after_step
from robofrontier.analysis.motion_query import object_poses
from scripts.build_release import (FINGER_FRICTION, MODULE, SURFACE_FRICTION, cases, check_physics, compile_scene,
                                   contact_parameters)

BOX = '''<mujoco><option timestep="0.002"/><worldbody><geom type="plane" size="1 1 .1"/>
<body><freejoint/><geom type="box" size=".03 .03 .03" mass=".1" pos="0 0 .03"/></body></worldbody></mujoco>'''


def world(family='transport'):
    model = mujoco.MjModel.from_xml_string(BOX)
    arm = SimpleNamespace(job=None)
    return SimpleNamespace(model=model, data=mujoco.MjData(model), arms={'A': arm}, task={'family': family})


class StepSettingsTests(unittest.TestCase):
    def test_every_family_has_settings(self):
        self.assertEqual(set(FAMILIES), {'mosaic', 'transport', 'dial', 'relay'})

    def test_attach_changes_no_contact_or_solver_setting(self):
        w = world('dial');before = (w.model.opt.noslip_tolerance, w.model.opt.cone, w.model.geom_friction.copy())
        attach(w)
        self.assertEqual((w.model.opt.noslip_tolerance, w.model.opt.cone), before[:2])
        np.testing.assert_array_equal(w.model.geom_friction, before[2])

    def test_mosaic_sleeps_always(self):
        w = world('mosaic')
        self.assertIsNone(attach(w))
        self.assertTrue(w.model.opt.enableflags & SLEEP)

    def test_idle_sleep_follows_the_arms(self):
        w = world();governor = attach(w)
        self.assertIsInstance(governor, IdleSleep)
        governor.before_step();self.assertFalse(w.model.opt.enableflags & SLEEP)
        w.data.time = 2.;governor.before_step();self.assertTrue(w.model.opt.enableflags & SLEEP)
        w.arms['A'].job = 'call';governor.before_step();self.assertFalse(w.model.opt.enableflags & SLEEP)
        w.arms['A'].job = None;w.data.time = 3.;governor.before_step();self.assertFalse(w.model.opt.enableflags & SLEEP)
        w.data.time = 4.;governor.before_step();self.assertTrue(w.model.opt.enableflags & SLEEP)

    def test_settling_delays_the_first_sleep(self):
        w = world('relay');governor = attach(w)
        w.data.time = 29.;governor.before_step();self.assertFalse(w.model.opt.enableflags & SLEEP)
        w.data.time = 30.;governor.before_step();self.assertTrue(w.model.opt.enableflags & SLEEP)

    def test_end_of_step_forward_restores_noslip(self):
        w = world();w.model.opt.noslip_iterations = 10
        forward_after_step(w)
        self.assertEqual(w.model.opt.noslip_iterations, 10)

    def test_harness_has_no_physics_settings(self):
        harness = json.loads(Path('configs/harnesses/policy.json').read_text())
        self.assertFalse({'physics_profile', 'gripper_position_servo', 'allowed_tcp_speed_m_s'} & set(harness))


class ReleaseContactRuleTests(unittest.TestCase):
    XML = '''<mujoco><worldbody><geom name="table" type="box" size="1 1 .02" condim="3"/>
<body name="A_link0"><body name="A_link1"><joint name="A_joint1"/><geom name="link" type="box" size=".02 .02 .02" condim="3"/>
<body name="A_left_finger"><joint name="A_finger_joint1" type="slide"/><geom name="pad" type="box" size=".01 .01 .01" condim="3"/></body></body></body>
<body name="can" pos=".3 0 .1"><freejoint/><geom name="can" type="cylinder" size=".03 .03" condim="6" friction="1 .005 .03"/>
<geom name="blade" type="box" size=".001 .006 .012" pos="0 0 -.04" friction=".45 .003 .0001" condim="4"/></body>
<body name="payload_01" pos=".6 0 .1"><freejoint/><geom name="payload_01_hook_0" type="capsule" size=".003 .01" friction=".5 .002 .0001" condim="3"/></body>
<body name="D01_module" pos="0 .5 .1"><freejoint/><geom name="D01_module_disk" type="cylinder" size=".15 .004" friction=".8 .005 .03" condim="6"/>
<body name="D01_rotor"><joint name="D01_hinge"/><geom name="D01_hand_grip" type="cylinder" size=".014 .022" friction=".8 .005 .0001" condim="4"/></body></body>
</worldbody></mujoco>'''

    def test_two_friction_values_and_the_kept_rolling_terms(self):
        model = mujoco.MjModel.from_xml_string(self.XML)
        rule = {model.geom(g).name: (c, p, tuple(round(v, 6) for v in f)) for g, (f, c, p) in contact_parameters(model).items()}
        self.assertEqual(rule['pad'], (4, 1, FINGER_FRICTION))
        self.assertEqual(rule['link'], (3, 0, SURFACE_FRICTION))
        self.assertEqual(rule['table'], (4, 0, SURFACE_FRICTION))
        self.assertEqual(rule['can'], (6, 0, (.4, .005, .003)))
        self.assertEqual(rule['blade'], (4, 0, SURFACE_FRICTION))
        self.assertEqual(rule['payload_01_hook_0'], (4, 0, SURFACE_FRICTION))
        self.assertEqual(rule['D01_module_disk'], (6, 0, (.4, .005, .03)))
        self.assertEqual(rule['D01_hand_grip'], (4, 0, SURFACE_FRICTION))


@unittest.skipUnless(all((folder/'assets').is_dir() for folder in cases()),
                     'Generated scene assets missing; run `python -m robofrontier.cli bootstrap`')
class ReleasedScenePhysicsTests(unittest.TestCase):
    def test_every_released_scene_carries_the_release_physics(self):
        for folder in cases():
            with self.subTest(case=folder.name):
                self.assertEqual(check_physics(folder), [])

    def test_released_scene_names_match_the_contact_rule(self):
        # family: (arms, Dial module disks and stems, fingers' collision geoms per arm)
        expected = {'transport-a08-d1': (8, 0), 'mosaic-a04-6x12-d1': (4, 0), 'relay-a08-d2': (8, 0), 'dial-best5-n04-d2': (8, 8)}
        for folder in cases():
            if folder.name not in expected: continue
            with self.subTest(case=folder.name):
                task = json.loads((folder/'task.json').read_text());model = compile_scene(folder)
                touching = [g for g in range(model.ngeom) if model.geom_contype[g] | model.geom_conaffinity[g]]
                modules = [g for g in touching if MODULE.search(model.geom(g).name or '')]
                self.assertEqual((len(task['arms']), len(modules)), expected[folder.name])
                fingers = [g for g in touching if int(model.geom_priority[g]) == 1]
                self.assertTrue(fingers)
                self.assertTrue(all('finger' in model.body(int(model.geom_bodyid[g])).name for g in fingers))


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


class ControlFingerprintTests(unittest.TestCase):
    PATHS = ('physics/robot_control.py', 'physics/kinematics.py', 'physics/motion_check.py', 'tasks/config.py',
             'runtime/pipeline.py', 'physics/profile.py')
    HASHES = {'robofrontier/'+path: str(i)*64 for i, path in enumerate(PATHS)}
    CONFIG = {'action_timeout_sim_s': 30.}

    def test_each_control_file_is_in_the_fingerprint(self):
        from robofrontier.tasks.config import physical_control_fingerprint
        base = physical_control_fingerprint(self.HASHES, self.CONFIG)
        for path in self.HASHES:
            with self.subTest(path=path):
                self.assertNotEqual(physical_control_fingerprint({**self.HASHES, path: 'f'*64}, self.CONFIG), base)
        self.assertNotEqual(physical_control_fingerprint(self.HASHES, {**self.CONFIG, 'action_timeout_sim_s': 20.}), base)


if __name__ == '__main__': unittest.main()
