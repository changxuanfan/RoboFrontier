"""Action contract, authority and scratch-state regressions."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from fake_pipeline import FakeWorld, fake_capture
from test_motion_check import robot_fixture
from robofrontier.robot_control import quat_matrix, matrix_quat, rotation_vector, advance_rotation
from robofrontier.motion_check import RobotGeometry, prepare_check, state_id
from robofrontier.run_setup import prepare_run
from robofrontier.runtime_service import RuntimeService
from robofrontier.task_config import load_harness


class ActionContractTests(unittest.TestCase):
    def setUp(self):self.world=robot_fixture();self.cfg=load_harness()

    def test_half_turn_is_not_zero_error_and_negative_quaternion_is_equivalent(self):
        target=np.diag([-1.,-1.,1.])
        self.assertAlmostEqual(np.linalg.norm(rotation_vector(target,np.eye(3))),np.pi)
        step=advance_rotation(np.eye(3),target,.1)
        self.assertAlmostEqual(np.linalg.norm(rotation_vector(step,np.eye(3))),.1)
        np.testing.assert_allclose(quat_matrix(matrix_quat(step)),quat_matrix(-matrix_quat(step)))
        for q in ([0,0,0,0],[1,0,float('nan'),0],[1,0,0],[1e308,1e308,0,0]):
            with self.assertRaises(ValueError):quat_matrix(q)

    def test_invalid_actions_do_not_change_live_state(self):
        w=self.world;before=w.data.qpos.copy()
        bad=[('gripper',{'width_m':.09}),('gripper',{'width_m':.05,'state':'open'}),
             ('gripper',{'state':'open','speed_m_s':float('nan')}),
             ('move',{'joint_rad':[0]*7,'target_m':[.4,0,.7]}),
             ('move',{'joint_rad':[100]*7}),('move',{'quaternion_wxyz':[0,0,0,0]}),
             ('move',{'delta_m':[0,0,0],'speed_m_s':float('inf')})]
        for op,p in bad:
            with self.assertRaises(ValueError):w.validate_action('A',op,p,self.cfg)
        np.testing.assert_array_equal(before,w.data.qpos)
        self.assertIsNone(w.arms['A'].job)

    def test_orientation_candidates_are_read_only_and_model_id_is_static(self):
        w=self.world;arm=w.arms['A'];original=w.data.qpos.copy()
        model_id=RobotGeometry(w.model,w.arms).describe(w,self.cfg)['model_id'];old_state=state_id(w)
        rot=np.array([[0.,-1,0],[1,0,0],[0,0,1]])@arm.rotation
        with patch('mujoco.mj_step',side_effect=AssertionError('No dynamics in screening')):
            report=list(prepare_check(w,{'motions':[{'actor':'A','quaternion_wxyz':matrix_quat(rot).tolist(),'angular_speed_rad_s':.4}],
                                          'horizon_s':.1,'sample_dt_s':.1},self.cfg))[-1]
        self.assertIn(report['assessment'],('no_conflict_found','conflict'))
        np.testing.assert_array_equal(original,w.data.qpos)
        self.assertEqual(old_state,state_id(w))
        arm.rotation_goal=rot
        self.assertNotEqual(old_state,state_id(w))
        self.assertEqual(model_id,RobotGeometry(w.model,w.arms).describe(w,self.cfg)['model_id'])
        self.assertNotIn('private_object',json.dumps(report))

    def test_stop_braking_has_its_own_deadline_and_holds_gripper_reference(self):
        w=self.world;arm=w.arms['A'];command=w.validate_action('A','move',{'delta_m':[0,0,.01]},self.cfg)
        w.start_action('A','long-move',command);arm.job_start=0;arm.velocity[:]=.1
        arm.gripper=120;arm.grip_goal=0
        arm.request_stop(14.99)
        self.assertEqual(arm.grip_goal,120)
        self.assertIsNone(arm.poll(15.01,15))
        self.assertTrue(arm.stopping)


    def test_opposing_finger_motion_cannot_be_mistaken_for_a_settled_stop(self):
        w=self.world;arm=w.arms['A'];command=w.validate_action('A','gripper',{'state':'close'},self.cfg)
        w.start_action('A','closing',command);arm.request_stop(0)
        for suffix,velocity in [('finger_joint1',.01),('finger_joint2',-.01)]:
            w.data.joint('A_'+suffix).qvel[0]=velocity
        for tick in range(10):self.assertIsNone(arm.poll(tick*.02,15))
        self.assertTrue(arm.stopping)

    def settled_gripper(self,initial,target,actual):
        arm=self.world.arms['A']
        for suffix in ('finger_joint1','finger_joint2'):
            arm.data.joint('A_'+suffix).qpos[0]=initial/2
            arm.data.joint('A_'+suffix).qvel[0]=0
        command=self.world.validate_action('A','gripper',{'width_m':target},self.cfg)
        self.world.start_action('A','aperture',command)
        arm.gripper=arm.grip_goal
        for suffix in ('finger_joint1','finger_joint2'):
            arm.data.joint('A_'+suffix).qpos[0]=actual/2
        result=None
        for tick in range(32):
            result=arm.poll(tick*.02,15)
            if result:return result
        self.fail('Settled gripper did not report a terminal result')

    def test_opening_overshoot_is_failed_even_when_reference_arrives(self):
        result=self.settled_gripper(.04,.052,.08)
        self.assertEqual(result['status'],'failed')
        self.assertFalse(result['target_width_reached'])
        self.assertFalse(result['grasp_verified'])

    def test_opening_undershoot_is_failed(self):
        self.assertEqual(self.settled_gripper(.02,.052,.04)['status'],'failed')

    def test_opening_reaches_intermediate_aperture(self):
        result=self.settled_gripper(.04,.052,.0519)
        self.assertEqual(result['status'],'completed')
        self.assertTrue(result['target_width_reached'])

    def test_closing_can_settle_above_target_without_claiming_grasp(self):
        result=self.settled_gripper(.08,0,.04)
        self.assertEqual(result['status'],'completed')
        self.assertFalse(result['target_width_reached'])
        self.assertFalse(result['grasp_verified'])

    def test_aperture_hold_is_not_misclassified_from_old_reference(self):
        # The previous closing reference can still be zero while an object
        # holds the measured aperture at40mm. A40mm hold is not an opening.
        self.world.arms['A'].grip_goal=0
        self.assertEqual(self.settled_gripper(.04,.04,.08)['status'],'failed')


class StopProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.run=Path(self.tmp.name)/'run';prepare_run(self.run)
        self.service=RuntimeService(self.run,FakeWorld,fake_capture);self.count=0
        for actor in ('Controller','A','B','C','D'):
            self.call(actor,'ready');self.call('Meta','bind',{'actor':actor,'thread_id':actor})
            self.service.store.observe_session(actor,'idle',actor,time.time(),'codex.wait_threads')
        self.call('Meta','start')
        self.service.world.request_stop=self.stop_fake
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def stop_fake(self,actor,call):
        self.assertEqual(self.service.world.running[actor],call)
        self.service.world.running.pop(actor)
        self.service.world.finished.append({'call_id':call,'status':'failed','reason':'stopped_by_agent'})
    def call(self,actor,op,data=None,identity=None):
        self.count+=1;j=self.service.accept(actor,op,data or {},identity or f'c{self.count}');self.service.pump();return j

    def test_stop_ownership_original_id_and_other_arm_continues(self):
        a=self.call('A','move',{'target_m':[.4,0,.7],'wait':False},'moving-a')
        self.call('B','move',{'target_m':[.4,.65,.7],'wait':False},'moving-b')
        self.assertIn('error',self.call('A','stop',{'robot':'B','call_id':'moving-b'})['result'])
        self.assertIn('error',self.call('Controller','stop',{'call_id':'moving-a'})['result'])
        stopped=self.call('A','stop',{'call_id':'moving-a'},'stop-a')
        self.assertTrue(stopped['result']['stop_requested'])
        self.assertEqual(self.call('A','job',{'call_id':'moving-a'})['result']['execution']['reason'],'stopped_by_agent')
        self.assertIn('B',self.service.world.running)
        self.assertEqual(stopped['result'],self.call('A','stop',{'call_id':'moving-a'},'stop-a')['result'])
        self.call('A','move',{'target_m':[.4,0,.8],'wait':False},'next-a')
        self.assertFalse(self.call('A','stop',{'call_id':'moving-a'})['result']['stop_requested'])
        self.assertEqual(self.service.world.running['A'],'next-a')

    def test_a_rejected_move_returns_the_ik_detail_and_other_errors_do_not(self):
        from robofrontier.robot_control import IKNoSolution, IK_MESSAGE
        detail={'robot':'A','closest_found_tcp_m':[.5,0,.7],'home_orientation':{'solvable':True}}
        def unreachable(actor,op,data,cfg):raise IKNoSolution(detail)
        self.service.world.validate_action=unreachable
        result=self.call('A','move',{'target_m':[2,0,.7]})['result']
        self.assertEqual(result['error'],IK_MESSAGE);self.assertEqual(result['ik_detail'],detail)
        self.assertNotIn('A',self.service.world.running)
        def other(actor,op,data,cfg):raise ValueError('TCP workspace target outside admitted bounds')
        self.service.world.validate_action=other
        self.assertNotIn('ik_detail',self.call('A','move',{'target_m':[9,0,.7]})['result'])

    def test_gripper_feedback_is_delivered_without_claiming_grasp(self):
        self.call('A','gripper',{'state':'close','wait':False},'closing')
        self.service.world.running.pop('A')
        self.service.world.finished.append({'call_id':'closing','status':'completed',
            'target_width_reached':False,'actual_width_m':.04,'grasp_verified':False})
        self.service.pump()
        result=self.call('A','job',{'call_id':'closing'})['result']['original_result']
        self.assertFalse(result['execution_feedback']['grasp_verified'])
        self.assertFalse(result['execution_feedback']['target_width_reached'])

    def test_grasp_mode_uses_same_role_authority_and_result_channel(self):
        p={'mode':'grasp','width_m':.04,'force_n':50,'wait':False}
        rejected=self.call('Controller','gripper',dict(p,robot='A'))['result']
        self.assertIn('error',rejected)
        result=self.call('A','gripper',p,'force-grasp')['result']
        self.assertEqual(result['execution_status'],'running')
        saved=self.service.store.call('force-grasp','A')
        self.assertEqual(json.loads(saved['parameters'])['mode'],'grasp')
        self.assertEqual(json.loads(saved['parameters'])['force_n'],50)

