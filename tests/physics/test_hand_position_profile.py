"""The hand driver: encoder position tracking and force-mode isolation."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from robofrontier.tasks.config import load_harness
from single_arm_scene import make_world
from motion import filled


class HandPositionProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.directory=Path(self.temp.name)
        self.cfg=load_harness()

    def tearDown(self):self.temp.cleanup()

    def world(self):
        return make_world(self.directory,harness=self.cfg)

    def command(self,w,op,parameters):
        command=w.validate_action('B',op,filled(op,parameters),self.cfg);w.start_action('B','profile-'+op,command)
        deadline=w.time+command['timing']['timeout_sim_s']+4.
        while w.time<deadline:
            w.step();done=w.poll_actions(15.)
            if done:
                self.assertEqual(done[0]['status'],'completed',done[0]);return done[0]
        self.fail('Bounded controller did not settle')

    def test_position_servo_tracks_intermediate_and_full_empty_opening(self):
        w=self.world();a=w.arms['B']
        self.assertAlmostEqual(w.model.actuator_biasprm[a.grip,1],-1000.)
        self.assertEqual(w.model.actuator_forcerange[a.grip].tolist(),[-70.,70.])
        self.command(w,'gripper',dict(width_m=0.,speed_m_s=.04))
        for width in (.052,.08):
            result=self.command(w,'gripper',dict(width_m=width,speed_m_s=.02))
            self.assertTrue(result['target_width_reached'])
            self.assertLess(abs(a.observe()['gripper_width_m']-width),.002)

    def test_force_grasp_then_position_release_restores_distinct_damping(self):
        w=self.world();a=w.arms['B'];position_parameters=tuple(x.copy() for x in a.grip_position_parameters)
        physical=[w.model.body_mass.copy(),w.model.dof_damping.copy(),w.model.geom_friction.copy()]
        for target in ([.42,0.,.52],[.42,0.,.42]):
            self.command(w,'move',dict(target_m=target,speed_m_s=.06))
        self.command(w,'gripper',dict(mode='grasp',width_m=.04,force_n=50.,speed_m_s=.02,epsilon_inner_m=.008,epsilon_outer_m=.008))
        self.assertEqual(a.grasp_phase,'hold')
        self.assertAlmostEqual(w.model.actuator_biasprm[a.grip,2],-10.)
        with self.assertRaises(ValueError):a.configure_hand_position_servo()
        self.command(w,'move',dict(target_m=[.42,0.,.54],speed_m_s=.06))
        self.assertGreater(w.data.joint('cube_free').qpos[2],.49)
        self.command(w,'move',dict(target_m=[.42,0.,.42],speed_m_s=.04))
        result=self.command(w,'gripper',dict(mode='move',width_m=.08,speed_m_s=.02))
        self.assertTrue(result['target_width_reached']);self.assertIsNone(a.grasp_force)
        for actual,expected in zip((w.model.actuator_gainprm[a.grip],w.model.actuator_biasprm[a.grip],w.model.actuator_ctrlrange[a.grip],w.model.actuator_forcerange[a.grip]),position_parameters):
            np.testing.assert_array_equal(actual,expected)
        for actual,expected in zip((w.model.body_mass,w.model.dof_damping,w.model.geom_friction),physical):
            np.testing.assert_array_equal(actual,expected)

    def test_active_reconfiguration_rejected(self):
        w=self.world();a=w.arms['B']
        command=w.validate_action('B','gripper',filled('gripper',dict(width_m=0.)),self.cfg)
        w.start_action('B','active',command)
        with self.assertRaises(ValueError):a.configure_hand_position_servo()


if __name__=='__main__':unittest.main()
