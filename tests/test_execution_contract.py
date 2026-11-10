"""Cross-scene/mode interface invariants and terminal servo behavior.

Protocol tests use actual robot geometry but a synthetic executor; physical
slow-motion/contact checks live separately in test_gripper_physics.
"""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np

from fake_pipeline import FakeWorld, fake_capture
from test_motion_check import robot_fixture
from robofrontier.delegation import Delegations
from robofrontier.pipeline import World
from robofrontier.robot_control import matrix_quat
from robofrontier.run_setup import prepare_run
from robofrontier.runtime_service import RuntimeService
from robofrontier.task_config import ROOT, load_harness


class TerminalServoTests(unittest.TestCase):
    def setUp(self):
        self.world=robot_fixture();self.arm=self.world.arms['A'];self.cfg=load_harness()

    def test_default_action_timeout_allows_more_time_than_previous_15_second_base(self):
        q=self.arm.qref.copy();q[0]+=.2
        cmd=self.world.validate_action('A','move',{'joint_rad':q.tolist(),'joint_speed_rad_s':.8},self.cfg)
        self.assertGreaterEqual(cmd['timing']['timeout_sim_s'],30.0)

    def test_live_nonsettling_stop_reports_the_unmet_conditions(self):
        from robofrontier.stop_diagnostics import stop_diagnostics
        a=self.arm;cmd=self.world.validate_action('A','move',{'joint_rad':a.qref.tolist()},self.cfg)
        a.start('move',cmd,0);a.request_stop(.1,'Action timeout; stopped at current reference')
        a.velocity[:]=.02;self.world.data.qvel[a.dofs]=.04
        result=a.poll(3.2,15)
        self.assertEqual(result['status'],'uncertain')  # Internal executor notification.
        self.world.data.time=3.2
        target=(self.world.data.qpos[a.qids]+.005).tolist()
        detail=stop_diagnostics(self.world,'A','move',{'parameters':{'joint_rad':target}})
        self.assertGreater(detail['max_reference_joint_speed_rad_s'],detail['reference_speed_limit_rad_s'])
        self.assertGreater(detail['max_actual_joint_speed_rad_s'],detail['actual_speed_limit_rad_s'])
        self.assertIn('reference_joint_speed',detail['unmet_conditions'])
        self.assertIn('actual_joint_speed',detail['unmet_conditions'])
        self.assertAlmostEqual(detail['max_joint_target_error_rad'],.005)
        self.assertEqual(detail['joint_target_tolerance_rad'],.004)
        self.assertEqual(a.job,'move')

    def test_accepted_slow_motion_has_enough_budget_for_reference_travel(self):
        w=self.world;a=self.arm
        jaw=w.validate_action('A','gripper',{'state':'close','speed_m_s':.005},self.cfg)
        self.assertAlmostEqual(jaw['timing']['estimated_reference_s'],16.)
        self.assertGreater(jaw['timing']['timeout_sim_s'],16.2)
        rotation=np.array([[0,-1,0],[1,0,0],[0,0,1]])@a.rotation
        pose=w.validate_action('A','move',{'quaternion_wxyz':matrix_quat(rotation).tolist(),'angular_speed_rad_s':.05},self.cfg)
        self.assertGreater(pose['timing']['timeout_sim_s'],np.pi/2/.05)
        q=a.qref.copy();q[0]+=.2
        joint=w.validate_action('A','move',{'joint_rad':q.tolist(),'joint_speed_rad_s':.01},self.cfg)
        self.assertGreaterEqual(joint['timing']['estimated_reference_s'],19.99)
        before=w.data.qpos.copy();limited={**self.cfg,'max_action_timeout_sim_s':16}
        with self.assertRaisesRegex(ValueError,'maximum execution budget'):
            w.validate_action('A','gripper',{'state':'close','speed_m_s':.005},limited)
        np.testing.assert_array_equal(before,w.data.qpos);self.assertIsNone(a.job)

    def test_a_move_without_ik_solution_reports_what_the_solver_found(self):
        from robofrontier.robot_control import IKNoSolution, IK_MESSAGE, quat_matrix
        w=self.world;a=self.arm;before=w.data.qpos.copy()
        # Too far at that height with the current hand: the closest pose found falls short.
        with self.assertRaises(IKNoSolution) as caught:
            w.validate_action('A','move',{'target_m':[.635,-.395,.895]},self.cfg)
        far=caught.exception.detail
        self.assertEqual(str(caught.exception),IK_MESSAGE)
        self.assertGreater(far['position_error_m'],.0025)
        reach=far['horizontal_distance_from_base_m']
        self.assertLess(reach['closest_found'],reach['target'])
        self.assertIn('kept the current hand orientation',far['orientation']['source'])
        self.assertFalse(far['home_orientation']['solvable'])
        # Within reach but with the hand flipped: the home orientation it reports solves it.
        target=(w.data.site_xpos[a.site]+np.array([0,0,-.1])).tolist()
        flipped=matrix_quat(quat_matrix([0,0,1,0])@a.home_rotation).tolist()
        with self.assertRaises(IKNoSolution) as caught:
            w.validate_action('A','move',{'target_m':target,'quaternion_wxyz':flipped},self.cfg)
        tilted=caught.exception.detail
        self.assertEqual(tilted['orientation']['source'],'requested quaternion_wxyz')
        self.assertTrue(tilted['home_orientation']['solvable'])
        w.validate_action('A','move',{'target_m':target,'quaternion_wxyz':tilted['home_orientation']['quaternion_wxyz']},self.cfg)
        # Both were rejected before execution.
        np.testing.assert_array_equal(before,w.data.qpos);self.assertIsNone(a.job)

    def test_timeout_stops_reference_and_retains_job_until_settled(self):
        a=self.arm;command=self.world.validate_action('A','gripper',{'state':'close'},self.cfg)
        command['timing']['timeout_sim_s']=.1;a.start('jaw',command,0)
        a.control(.02);reference=a.observe()['gripper_width_m']*255/.08
        self.assertIsNone(a.poll(.12,15))
        self.assertTrue(a.stopping);self.assertEqual(a.job,'jaw');self.assertAlmostEqual(a.grip_goal,reference)
        result=None
        for tick in np.arange(.14,.70,.02):
            a.control(.02);result=a.poll(float(tick),15)
            if result:break
        self.assertIsNotNone(result)
        self.assertEqual(result['status'],'failed');self.assertIn('timeout',result['reason'])
        self.assertIsNone(a.job)
        for _ in range(50):a.control(.02)
        self.assertAlmostEqual(a.gripper,reference);self.assertAlmostEqual(a.grip_goal,reference)

    def test_nonsettling_stop_keeps_ownership_unresolved_and_cannot_reset_deadline(self):
        a=self.arm;a.start('jaw',self.world.validate_action('A','gripper',{'state':'close'},self.cfg),0)
        a.request_stop(.1);a.request_stop(2.9)
        self.assertEqual(a.stop_started_at,.1)
        self.world.data.joint('A_finger_joint1').qvel[0]=.01
        result=a.poll(3.2,15)
        self.assertEqual(result['status'],'uncertain');self.assertEqual(a.job,'jaw')
        self.assertTrue(a.stopping);self.assertIsNone(a.poll(3.4,15))
        with self.assertRaisesRegex(ValueError,'already has an execution'):
            self.world.validate_action('A','gripper',{'state':'open'},self.cfg)

    def test_local_recovery_waits_for_proven_stop_and_keeps_original_failed(self):
        a=self.arm;command=self.world.validate_action('A','move',{'joint_rad':a.qref.tolist()},self.cfg)
        a.start('original',command,0);a.request_stop(.1,'Action timeout; stopped at current reference')
        a.velocity[:]=.1
        self.assertEqual(a.poll(3.2,15)['status'],'uncertain')
        self.assertIsNone(a.recover_stopped('original'))
        with self.assertRaises(ValueError):a.recover_stopped('different')
        a.velocity[:]=0;self.world.data.qvel[a.dofs]=0
        for _ in range(5):self.assertIsNone(a.poll(3.2,15))
        self.assertIsNone(a.recover_stopped('original'))
        for tick in (3.22,3.24,3.26):self.assertIsNone(a.poll(tick,15))
        result=a.recover_stopped('original')
        self.assertEqual(result['status'],'failed');self.assertEqual(result['call_id'],'original');self.assertIsNone(a.job)

    def test_direct_abort_freezes_jaw_reference(self):
        a=self.arm;a.start('jaw',self.world.validate_action('A','gripper',{'state':'close'},self.cfg),0)
        a.control(.02);reference=a.observe()['gripper_width_m']*255/.08;a.end('failed','engineering stop')
        for _ in range(50):a.control(.02)
        self.assertAlmostEqual(a.gripper,reference)


class SettleCountTests(unittest.TestCase):
    """A move ends after 12 in-tolerance samples, a gripper after 10 settled ones, a stop after 3.

    The world does not step here, so the arm holds still at its goal; each poll time
    stands for one 20 ms simulation tick."""
    def setUp(self):
        self.world=robot_fixture();self.arm=self.world.arms['A'];self.cfg=load_harness()

    def profile(self,name):
        from robofrontier.physics_profile import attach
        self.world.task={'family':'transport'};attach(self.world,{'physics_profile':name})

    def begin(self,op):
        w=self.world;a=self.arm
        if op=='gripper':
            a.start('jaw',w.validate_action('A','gripper',{'width_m':a.observe()['gripper_width_m']},self.cfg),0.)
            a.gripper=a.grip_goal
        else:
            command=w.validate_action('A','move',{'joint_rad':a.qref.tolist()},self.cfg)
            w.data.qpos[a.qids]=command['joint_goal'];a.start('move',command,0.)
            if op=='stop':a.request_stop(0.)
        return a

    def ticks_until_done(self,a,polls_per_tick=1):
        for tick in range(100):
            for _ in range(polls_per_tick):
                result=a.poll(.02*tick,15)
                if result:return tick+1,result['status']
        return None

    def test_each_action_ends_after_its_settle_count(self):
        # A gripper sample counts once its fingers have been still for 0.18 s (10 ticks).
        for op,expected in (('move',(12,'completed')),('gripper',(19,'completed')),('stop',(3,'failed'))):
            with self.subTest(op=op):
                self.setUp()
                self.assertEqual(self.ticks_until_done(self.begin(op)),expected)

    def test_an_out_of_tolerance_sample_restarts_the_move_count(self):
        a=self.begin('move');goal=self.world.data.qpos[a.qids].copy()
        for tick in range(11):self.assertIsNone(a.poll(.02*tick,15))
        self.world.data.qpos[a.qids[0]]+=.01
        self.assertIsNone(a.poll(.22,15))
        self.world.data.qpos[a.qids]=goal
        for tick in range(12,23):self.assertIsNone(a.poll(.02*tick,15))
        self.assertEqual(a.poll(.46,15)['status'],'completed')

    def test_realtime_v2_counts_each_simulation_tick_once(self):
        for op,ticks in (('move',12),('gripper',19),('stop',3)):
            with self.subTest(op=op):
                self.setUp();self.profile('realtime-v2')
                a=self.begin(op)
                self.assertEqual(a.poll_stability,'per-tick')
                for _ in range(30):self.assertIsNone(a.poll(0.,15))
                self.assertEqual(self.ticks_until_done(a,polls_per_tick=5)[0],ticks)

    def test_without_realtime_v2_every_poll_still_counts(self):
        # Finished runs keep their terms: realtime-v1 and no profile count polls, not ticks.
        for name in (None,'realtime-v1'):
            for op,ticks in (('move',3),('gripper',11),('stop',1)):
                with self.subTest(profile=name,op=op):
                    self.setUp()
                    if name:self.profile(name)
                    a=self.begin(op)
                    self.assertEqual(a.poll_stability,'per-call')
                    self.assertEqual(self.ticks_until_done(a,polls_per_tick=5)[0],ticks)


class SceneTopologyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.worlds={}
        from robofrontier.task_families import policy_task
        cls.mosaic_task=cls.root/'mosaic-task.json';cls.mosaic_task.write_text(json.dumps(policy_task('mosaic-a04-6x12-d1')))
        for name,task_path in [('transport',None),('mosaic',cls.mosaic_task)]:
            run=prepare_run(cls.root/('geometry-'+name),task_path)
            task=json.loads((run/'private/inputs/task.json').read_text())
            cls.worlds[name]=World(run,task)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_both_tasks_all_modes_share_facts_commands_and_ownership(self):
        for scene,geometry in self.worlds.items():
            for mode in ('hierarchical','peer','centralized','adaptive'):
                with self.subTest(scene=scene,mode=mode):self.check_mode(scene,geometry,mode)

    def check_mode(self,scene,geometry,mode):
        class ContractWorld(FakeWorld):
            def robot_facts(self,cfg):return geometry.robot_facts(cfg)
            def robot_model(self,cfg):return geometry.robot_model(cfg)
            def validate_action(self,actor,op,data,cfg):
                if actor in self.running:raise ValueError('Arm busy')
                return geometry.validate_action(actor,op,data,cfg)
            def request_stop(self,actor,call):
                assert self.running.pop(actor)==call
                self.finished.append({'call_id':call,'status':'failed','reason':'stopped_by_agent'})
        cfg=load_harness();cfg['topology']=mode
        path=self.root/(scene+'-'+mode+'.json');path.write_text(json.dumps(cfg))
        task_path=self.mosaic_task if scene=='mosaic' else None
        run=prepare_run(self.root/(scene+'-'+mode),task_path,path)
        s=RuntimeService(run,ContractWorld,fake_capture);n=[0]
        def call(actor,op,data=None,identity=None):
            n[0]+=1;job=s.accept(actor,op,data or {},identity or 'c'+str(n[0]));s.pump();return job
        def ok(job):
            self.assertIsNotNone(job['result']);self.assertNotIn('error',job['result']);return job['result']
        try:
            policies=[a for a,v in s.store.agents().items() if v['kind']!='manager']
            for actor in policies:
                ready=ok(call(actor,'ready'));self.assertFalse(any(k.startswith('workspace_') for k in ready['limits']))
                self.assertEqual(ready['robot_facts'],geometry.robot_facts(cfg))
                self.assertGreater(ready['execution_timing']['max_timeout_sim_s'],15)
                ok(call('Meta','bind',{'actor':actor,'thread_id':'synthetic-'+actor}))
                s.store.observe_session(actor,'idle','synthetic-ready',time.time(),'codex.wait_threads')
            viewer=policies[0]
            summary=ok(call(viewer,'robot_model'))['robot_model']
            self.assertLess(len(json.dumps(summary).encode()),8000)
            report=Path(summary['result_ref']);full=json.loads(report.read_text())
            self.assertEqual(set(full['robots']),set(geometry.arms));self.assertNotIn('objects',full)
            self.assertNotIn('bodies',summary['robots']['A'])
            stamp=report.stat().st_mtime_ns
            selected=ok(call(viewer,'robot_model',{'robot':'A'}))['robot_model']
            self.assertEqual(set(selected['robots']),{'A'});self.assertIn('bodies',selected['robots']['A'])
            self.assertLess(len(json.dumps(selected).encode()),20000)
            self.assertEqual(selected['model_id'],full['model_id']);self.assertEqual(stamp,report.stat().st_mtime_ns)
            self.assertIn('error',call(viewer,'robot_model',{'robot':'missing'})['result'])
            owner='Controller' if mode in ('centralized','adaptive') else 'A'
            self.assertIn('error',call(owner,'gripper',{'robot':'A','width_m':.05})['result'])
            ok(call('Meta','start'))
            owner_b='Controller' if mode in ('centralized','adaptive') else 'B'
            first=ok(call(owner,'gripper',{'robot':'A','width_m':.05,'wait':False},'action-A'))
            ok(call(owner_b,'gripper',{'robot':'B','width_m':.06,'wait':False},'action-B'))
            self.assertEqual(set(s.world.running),{'A','B'});self.assertIn('execution_timing',first['execution'])
            self.assertIn('error',call('Meta','stop',{'robot':'A','call_id':'action-A'})['result'])
            ok(call(owner,'stop',{'robot':'A','call_id':'action-A'}));self.assertIn('B',s.world.running)
            s.world.complete('B');s.pump()
            a=geometry.arms['A']
            for p in ({'target_m':a.observe()['tcp_m'],'quaternion_wxyz':a.observe()['tcp_quaternion_wxyz']},
                      {'joint_rad':a.observe()['joint_rad'],'joint_speed_rad_s':.2}):
                ok(call(owner,'move',{'robot':'A','wait':False,**p}));s.world.complete('A');s.pump()
            if mode=='hierarchical':
                self.assertIn('error',call('A','send',{'to':['B'],'text':'route test'})['result'])
                ok(call('A','send',{'to':['Controller'],'text':'route test'}))
            elif mode=='peer':ok(call('A','send',{'to':['B'],'text':'route test'}))
            elif mode=='adaptive':
                pending=call('Controller','delegate',{'scopes':[{'robots':['A'],'goal':'offline only','done_when':'synthetic return'}]},'batch')
                d=Delegations(s.store);d.claim('batch','test');child=d.batch('batch')['children'][0]
                d.bind('batch',child['actor'],'synthetic-child',{'source_thread_id':'synthetic-Controller','source_ordinal':42,'source_sha256':'same'},'test')
                d.activate('batch','test');d.started('batch',child['actor'],'sent','test');s.pump();ok(pending)
                self.assertIn('error',call('Controller','gripper',{'robot':'A','state':'open'})['result'])
                ok(call(child['actor'],'gripper',{'robot':'A','width_m':.05,'wait':False}))
                self.assertIn('error',call(child['actor'],'return_task',{'outcome':'completed','result':'too soon'})['result'])
                s.world.complete('A');s.pump()
                ok(call(child['actor'],'return_task',{'outcome':'completed','result':'synthetic, no task physics'}))
                self.assertEqual(d.owners()['A'],'Controller')
            # A nonsettling executor cannot silently free this robot or finish.
            ok(call(owner,'gripper',{'robot':'A','width_m':.05,'wait':False},'unsettled'))
            s.world.finished.append({'call_id':'unsettled','status':'uncertain','reason':'Injected nonsettling stop'})
            s.pump();self.assertEqual(s.store.actions()['unsettled']['status'],'uncertain')
            self.assertEqual(s.store.get('lifecycle'),'running')
            self.assertTrue(s.store.actions()['unsettled']['isolated'])
            self.assertIn('error',call(owner,'gripper',{'robot':'A','state':'open'})['result'])
            self.assertIn('error',call('Controller' if mode=='hierarchical' else owner,'finish')['result'])
        finally:s.close()
