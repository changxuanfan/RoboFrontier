"""Exercise recovery boundaries without moving a physical world."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import numpy as np

from robofrontier.oracle.dial import Manipulator
from robofrontier.oracle.mosaic_run import require_known_idle
from robofrontier.oracle.mosaic import check_process
from robofrontier.oracle.trial import ProcessViolation, Trial
from robofrontier.oracle.transport_grasp_safety import requires_contact_recovery
from robofrontier.oracle.transport_socket_motion import SocketPlanningError
from robofrontier.oracle.transport_socket_motion import exit_contact_allowed, exit_contact_envelope, finish_socket_release, sample_clear


def terminal_task():
    return {'run_protocol': {'evaluation_semantics': 'terminal_outcome_v2'}}


class OracleTerminalRecoveryTests(unittest.TestCase):
    def test_dial_regrasp_uses_measured_stem_projection_with_unchanged_tolerance(self):
        from robofrontier.oracle.dial import BestManipulator
        angle=.008
        stem_rotation=np.array([[1.,0.,0.],[0.,np.cos(angle),-np.sin(angle)],
                                [0.,np.sin(angle),np.cos(angle)]])
        size=np.array([.008,.010,.150])
        trial=NS(task={'level':3},arms={'H':NS(grasp_force=70.,site=0,
                     observe=lambda:{'gripper_width_m':.0205})},
                 model=NS(geom=lambda _:NS(size=size)),
                 data=NS(geom=lambda _:NS(xmat=stem_rotation.ravel()),site_xmat=np.eye(3).reshape(1,9)),
                 monitor=NS(dial_ready=[True]),execute=Mock(),wait=Mock(),event=Mock())
        manipulator=object.__new__(BestManipulator);manipulator.t=trial
        entry={'id':'dial','index':0,'nominal_robots':['G','H']}
        manipulator.requalify_blue_pressure([entry])
        command=trial.execute.call_args.args[1]['H'][1]
        self.assertAlmostEqual(command['width_m'],2*float(abs(stem_rotation[1])@size))
        self.assertEqual(command['epsilon_inner_m'],.005)
        self.assertEqual(command['epsilon_outer_m'],.005)

    def test_numeric_failure_is_latched_before_any_further_physics_step(self):
        trial=Trial.__new__(Trial);trial.physics_failure='Numerical physics failure; invalid trajectory'
        with patch('mujoco.mj_step') as step:
            with self.assertRaisesRegex(RuntimeError,'Numerical physics failure'):
                trial.step()
        step.assert_not_called()

    def test_recorded_violation_does_not_block_known_idle_terminal_recovery(self):
        event = {'kind': 'robot_contact', 'sim_time_s': 1.}
        trial = NS(task=terminal_task(), monitor=NS(violations=[event]),
                   arms={'A': NS(job=None)}, actions=[])
        require_known_idle(trial)
        check_process(trial)
        self.assertEqual(trial.monitor.violations, [event])

    def test_legacy_and_explicit_strict_runs_retain_process_gate(self):
        for task in ({}, terminal_task()):
            trial = NS(task=task, oracle_protocol={'mode': 'strict-process'},
                       monitor=NS(violations=[{'kind': 'robot_contact'}]), arms={}, actions=[])
            with self.assertRaises(ProcessViolation):
                require_known_idle(trial)

    def test_terminal_recovery_still_rejects_uncertain_execution(self):
        trial = NS(task=terminal_task(), monitor=NS(violations=[]),
                   arms={'A': NS(job=None, uncertainty_reported=True)}, actions=[])
        with self.assertRaisesRegex(RuntimeError, 'Unknown or in-flight'):
            require_known_idle(trial)

    def test_separated_dial_hand_uses_actual_aperture_geometry(self):
        arm = NS(job=None, grasp_force=None, grip_max=.08, site=0,
                 qids=np.arange(7), observe=lambda: {'gripper_width_m': .06})
        trial = NS(arms={'A': arm}, monitor=NS(released=lambda _: True),
                   data=NS(site_xpos=np.zeros((1, 3)), qpos=np.zeros(7)),
                   pose_command=Mock(return_value=('move', {'joint_rad': [0.] * 7})),
                   pose_clear=Mock(return_value=True), execute=Mock(), event=Mock())
        manipulator = object.__new__(Manipulator)
        manipulator.t = trial
        manipulator.grips = {'dial': {'robot': 'A'}}
        manipulator.red_geoms = lambda _: {1}
        with patch('robofrontier.oracle.trial.joint_edge_clear',
                   side_effect=lambda start, end, check, step: check(end)):
            manipulator.clear_released_crank({'id': 'dial'}, np.zeros(3), np.eye(3))
        trial.pose_clear.assert_called()
        trial.execute.assert_called_once()

    def test_dial_contact_is_not_reclassified_as_release_by_width(self):
        trial=NS(arms={'A':NS(job=None,grasp_force=None)},monitor=NS(released=lambda _:False))
        manipulator=object.__new__(Manipulator);manipulator.t=trial
        manipulator.grips={'dial':{'robot':'A'}};manipulator.red_geoms=lambda _:{1}
        with self.assertRaisesRegex(RuntimeError,'real separation'):
            manipulator.clear_released_crank({'id':'dial'},np.zeros(3),np.eye(3))

    def test_dial_actuator_does_not_reject_a_retained_historical_event(self):
        from robofrontier.oracle.dial import BaselineManipulator as BaseManipulator
        manipulator=object.__new__(BaseManipulator)
        manipulator.t=NS(task=terminal_task(),monitor=NS(violations=[{'kind':'contact'}]))
        self.assertFalse(manipulator.rule_failure())
        manipulator.t.task={}
        self.assertTrue(manipulator.rule_failure())

    def test_relay_drop_history_does_not_override_current_measured_support(self):
        from robofrontier.oracle.relay_oracle import support_lost
        state=dict(dropped=True,rod_geoms={1})
        trial=NS(task=terminal_task(),wait=Mock(),
                 monitor=NS(relay=NS(states={'part':state}),bilateral=lambda *_,**__:{'A','B'}))
        self.assertFalse(support_lost(trial,'part',['A','B']))
        trial.wait.assert_not_called();self.assertTrue(state['dropped'])
        trial.monitor.bilateral=lambda *_,**__:set()
        self.assertTrue(support_lost(trial,'part',['A','B']))
        trial.wait.assert_called_once_with(.12)

    def test_relay_frontier_uses_terminal_per_payload_outcome(self):
        from robofrontier.oracle import relay_pipeline
        frontier=relay_pipeline.Frontier('part',0,0,phase='verify')
        trial=NS(task=terminal_task(),relay_frontiers=[frontier],
                 monitor=NS(result=lambda:{'payloads':{'part':{'completed':False,'terminal_goal_met':True}}}))
        with patch.object(relay_pipeline,'snapshot'):
            relay_pipeline.finalize_frontier(trial)
            self.assertEqual(frontier.phase,'done')
            trial.task={};frontier.phase='verify'
            relay_pipeline.finalize_frontier(trial)
        self.assertEqual(frontier.phase,'verify')

    def test_socket_withdrawal_routes_to_contact_review_not_ordinary_retry(self):
        error = SocketPlanningError('socket-withdraw', {'fraction': 0., 'distance_m': -.00058})
        self.assertTrue(requires_contact_recovery(error))

    def test_mosaic_replans_a_displaced_goal_without_reusing_a_still_matched_item(self):
        from robofrontier.oracle.mosaic import protected_remaining_inputs
        task=terminal_task();task['goals']=[{'goal_id':name} for name in ('lost','kept','todo')]
        trial=NS(task=task,event=Mock(),env={'objects':[{'id':name} for name in ('a','b','c')]},
                 monitor=NS(result=lambda:{'assignments':{'kept':'b'}}))
        goals,objects,current=protected_remaining_inputs(trial,{'lost':'a','kept':'b'})
        self.assertEqual([g['goal_id'] for g in goals],['lost','todo'])
        self.assertEqual([o['id'] for o in objects],['a','c'])
        self.assertEqual(current,{'kept':'b'});trial.event.assert_called_once()

    def test_relay_known_opening_undershoot_needs_real_separation(self):
        from robofrontier.oracle.relay_oracle import observed_wider_release
        trial=NS(task=terminal_task(),arms={'A':NS(job=None,grasp_force=None)})
        feedback=dict(status='failed',reason='Requested opening not reached',direction='opening',actual_width_m=.066)
        with patch('robofrontier.oracle.relay_oracle.arm_payload_contact',return_value=False):
            self.assertTrue(observed_wider_release(trial,'part','A',feedback,.072))
            self.assertFalse(observed_wider_release(trial,'part','A',dict(feedback,status='uncertain'),.072))
            trial.task={}
            self.assertFalse(observed_wider_release(trial,'part','A',feedback,.072))
        trial.task=terminal_task()
        with patch('robofrontier.oracle.relay_oracle.arm_payload_contact',return_value=True):
            self.assertFalse(observed_wider_release(trial,'part','A',feedback,.072))

    def test_contact_exit_does_not_allow_new_pairs_or_deeper_penetration(self):
        envelope = {(1, 2): -.00058}
        self.assertTrue(exit_contact_allowed(envelope, 2, 1, -.00058))
        self.assertTrue(exit_contact_allowed(envelope, 1, 2, -.0002))
        self.assertFalse(exit_contact_allowed(envelope, 1, 2, -.0007))
        self.assertFalse(exit_contact_allowed(envelope, 1, 3, -.00001))
        self.assertTrue(exit_contact_allowed(envelope, 1, 3, .00687))
        self.assertTrue(exit_contact_allowed(envelope, 1, 3, .000128))

    def test_socket_board_rejection_cannot_fall_back_to_insertion_tolerance(self):
        for envelope in ({}, {(1, 2): -.0001}):
            with self.subTest(envelope=envelope):
                trial=NS(_reference_planning_only=True,_live_data=object(),held={},
                    data=NS(joint=lambda _:NS(qpos=np.zeros(7))),
                    model=NS(geom_bodyid=np.zeros(3,int),body=lambda _:NS(id=0,name='board')),
                    screen_model=object(),screen_data=NS(contact=[NS(geom=(1,2),dist=-.0002)]),
                    pose_clear=lambda *args,**kw:True,arms={'A':None},
                    monitor=NS(geoms={'part':{1}},descendant_geoms=lambda _:{2},geom_owner=np.array([-1,-1,-1])))
                with patch('mujoco.mj_forward'),patch('mujoco.mj_geomDistance',return_value=-.0002):
                    clear,why=sample_clear(trial,'A','part',np.zeros(7),np.zeros(3),np.eye(3),'board',exit_contacts=envelope)
                self.assertFalse(clear)
                self.assertEqual(why['reason'],'exit_board_contact_worsened')

    def socket_contact_trial(self,normal):
        return NS(arms={'A':NS(job=None,grasp_force=None)},
            monitor=NS(geoms={'part':{1}},descendant_geoms=lambda _:{2},velocity=lambda _:np.zeros(6)),
            model=NS(geom_bodyid=np.zeros(3,int),body=lambda _:NS(id=0,name='board'),
                     opt=NS(gravity=np.array([0.,0.,-9.81]))),
            data=NS(contact=[NS(geom=(1,2),dist=0.,frame=np.r_[normal,np.zeros(6)])]),
            socket_release_phases={'A':dict(object='part',board='board',phase='force-off-contact-unconfirmed')})

    def test_sidewall_pressure_does_not_establish_supported_socket_exit(self):
        trial=self.socket_contact_trial([1.,0.,0.])
        def contact_force(model,data,index,force):force[0]=1.
        with patch('mujoco.mj_contactForce',side_effect=contact_force), \
             patch('mujoco.mj_geomDistance',return_value=-.0001):
            with self.assertRaisesRegex(SocketPlanningError,'supported_socket_exit_required'):
                exit_contact_envelope(trial,'A','part','board')

    def test_socket_exit_baseline_is_shared_across_segments(self):
        trial=self.socket_contact_trial([0.,0.,-1.])
        # Passive settling during withdrawal is not a final-goal violation.
        trial.monitor.velocity=lambda _:np.array([0.,.09,0.,0.,0.,-.012])
        trial.model.geom_bodyid=np.arange(4)
        trial.model.body=lambda ident:NS(id=0,name='A_left_finger' if ident==3 else 'board')
        trial.data.contact.append(NS(geom=(1,3),dist=0.,frame=np.r_[[1.,0.,0.],np.zeros(6)]))
        def contact_force(model,data,index,force):force[0]=1.
        with patch('mujoco.mj_contactForce',side_effect=contact_force), \
             patch('mujoco.mj_geomDistance',side_effect=[-.00058,-.0001,-.00062,-.00014,-.00066,-.00018]):
            first=exit_contact_envelope(trial,'A','part','board')
            second=exit_contact_envelope(trial,'A','part','board')
            self.assertEqual(first[(1,3)],second[(1,3)])
            self.assertEqual(second[(1,2)],-.00062)
            with self.assertRaisesRegex(SocketPlanningError,'exit_contact_worsened'):
                exit_contact_envelope(trial,'A','part','board')
        import json
        json.dumps(trial.socket_release_phases,allow_nan=False)

    def test_mosaic_can_reconcile_real_release_without_a_preferred_opening(self):
        from robofrontier.oracle.mosaic_run import MosaicReview
        trial=NS(task=terminal_task(),held={'A':'part'},
                 arms={'A':NS(grasp_force=None,observe=lambda:{'gripper_width_m':.02})},
                 monitor=NS(released=lambda _:True,geoms={'part':{1}},velocity=lambda _:np.zeros(6)),
                 model=NS(body=lambda _:NS(id=0),geom=lambda _:NS(name='table_top')),
                 data=NS(contact=[NS(geom=(1,2),dist=0.)]),event=Mock())
        trial.task['cube_size_m']=.04
        review=object.__new__(MosaicReview);review.trial=trial
        review._reconcile_released('A')
        self.assertNotIn('A',trial.held)

    def test_relay_terminal_release_uses_current_support_not_old_drop_flag(self):
        from robofrontier.oracle import relay_oracle as relay
        task=terminal_task();task.update(completion={'allow_goal_payload_contact':True},
                                         mechanism={'cross_section_m':[.03,.03]})
        trial=NS(task=task,held={'A':'part','B':'part'},wait=Mock(),event=Mock(),
                 execute=Mock(return_value={a:{'status':'completed'} for a in ('A','B')}),
                 move_free=Mock(),pose_command=Mock(return_value=('move',{})),
                 home={a:(np.zeros(3),np.eye(3)) for a in ('A','B')},
                 home_q={a:np.zeros(7) for a in ('A','B')},
                 monitor=NS(relay=NS(states={'part':{'dropped':True}})))
        with patch.object(relay,'final_support',return_value=True), \
             patch.object(relay,'terminal_contact_names',return_value=['part']), \
             patch.object(relay,'withdrawal_target',return_value=(np.zeros(3),np.eye(3))):
            relay.release(trial,'part',['A','B'],terminal=True)
        self.assertEqual(trial.move_free.call_count,2)
        self.assertTrue(trial.monitor.relay.states['part']['dropped'])

    def test_failed_socket_withdrawal_retains_phase_and_does_not_reopen(self):
        arm = NS(job=None, grasp_force=None, site=0)
        trial = NS(arms={'A': arm}, held={'A': 'part'},
                   socket_released_payload={'A': 'part'},
                   socket_release_phases={'A': {'phase': 'force-off-contact-unconfirmed'}},
                   data=NS(site_xpos=np.zeros((1, 3)), site_xmat=np.eye(3).reshape(1, 9),
                           body=lambda _: NS(xmat=np.eye(3).ravel())),
                   move=Mock(side_effect=SocketPlanningError('socket-withdraw', {})),
                   execute=Mock(), event=Mock(), wait=Mock())
        with self.assertRaises(SocketPlanningError):
            finish_socket_release(trial, 'A', 'part', 'board')
        self.assertEqual(trial.socket_released_payload, {'A': 'part'})
        self.assertEqual(trial.held, {'A': 'part'})
        self.assertIn('A', trial.socket_release_phases)
        trial.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
