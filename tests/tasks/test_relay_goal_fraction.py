import unittest
import json
from unittest.mock import patch
import numpy as np
import mujoco

from robofrontier.tasks.relay_goal_fraction import clipped_fraction, timber_fraction
from robofrontier.tasks.relay import final_task, LEGACY_RULE_REVISION
from tests.tasks.test_relay_goal_support import GoalSupportTests


class GoalFractionTests(unittest.TestCase):
    def test_scoring_result_serializes_numpy_fraction_at_both_sides_of_threshold(self):
        m, d, relay = GoalSupportTests().world(); mon = relay.mon
        mon.task.update(family='relay', level=1)
        mon.task = final_task(mon.task)
        mon.task['run_protocol'] = {'evaluation_semantics':'terminal_outcome_v2'}
        mon.violations = []; mon.bilateral = lambda *args, **kwargs: set()
        mon.bottom = lambda geoms: .8; mon.velocity = lambda body: np.zeros(6)
        mon.violation = lambda *args, **kwargs: None; mon.released = lambda geoms: True
        for state in relay.states.values(): state.update(airborne=True, landed=False, transitions=[])
        for fraction in (np.float64(.5), np.float64(.7), np.float64(.9)):
            with patch('robofrontier.tasks.relay_goal_fraction.timber_fraction', return_value=fraction):
                relay.sample()
            json.dumps(mon.result_cache, allow_nan=False)
            for item in mon.result_cache['payloads'].values():
                self.assertIs(type(item['terminal_goal_met']), bool)
                self.assertIs(type(item['timber_inside_fraction']), float)

    def test_line_clipping(self):
        self.assertAlmostEqual(clipped_fraction([-2, 0], [2, 0], [1, 1]), .5)
        self.assertEqual(clipped_fraction([-2, 2], [2, 2], [1, 1]), 0.)
        self.assertEqual(clipped_fraction([0, 0], [.5, .5], [1, 1]), 1.)

    def test_tangent_box_length_uses_local_y(self):
        m = mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom name="beam" type="box" size=".0225 .019 .0225" pos="0 .39 .9"/></worldbody></mujoco>')
        d = mujoco.MjData(m); mujoco.mj_forward(m, d)
        region = dict(center_m=[0, 0, .8], half_size_m=[.4, .4], nominal_yaw_rad=0.)
        self.assertAlmostEqual(timber_fraction(m, d, [0], region), 29 / 38, places=5)

    def test_below_goal_is_not_above(self):
        m = mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom type="box" size=".01 .1 .01" pos="0 0 .7"/></worldbody></mujoco>')
        d = mujoco.MjData(m); mujoco.mj_forward(m, d)
        region = dict(center_m=[0, 0, .8], half_size_m=[.4, .4], nominal_yaw_rad=0.)
        self.assertEqual(timber_fraction(m, d, [0], region), 0.)

    def test_suspended_released_and_process_violations_are_independent(self):
        m, d, relay = GoalSupportTests().world(); mon = relay.mon
        mon.task.update(family='relay', level=1)
        mon.task = final_task(mon.task)
        mon.task['run_protocol'] = {'evaluation_semantics':'terminal_outcome_v2'}
        mon.violations = [{'kind':'drop'}]
        mon.bilateral = lambda *args, **kwargs: set()
        mon.bottom = lambda geoms: .8
        mon.velocity = lambda body: np.zeros(6)
        mon.violation = lambda *args, **kwargs: None
        mon.released = lambda geoms: True
        for state in relay.states.values():
            state.update(airborne=True, landed=False, transitions=[])
        d.joint('p1_free').qpos[2] = 1.2
        mujoco.mj_forward(m, d); relay.sample()
        self.assertTrue(mon.result_cache['task_success'])
        self.assertFalse(mon.result_cache['payloads']['p1']['goal_table_support'])
        mon.released = lambda geoms: False
        relay.sample(); self.assertFalse(mon.result_cache['task_success'])

    def test_legacy_contract_keeps_original_full_containment_rule(self):
        m, d, relay = GoalSupportTests().world(); mon = relay.mon
        mon.task.update(family='relay', level=1)
        mon.task = final_task(mon.task)
        mon.task['completion']['rule_revision'] = LEGACY_RULE_REVISION
        mon.task['run_protocol'] = {'evaluation_semantics':'terminal_outcome_v2'}
        mon.violations = []; mon.bilateral = lambda *args, **kwargs: set()
        mon.bottom = lambda geoms: .8; mon.velocity = lambda body: np.zeros(6)
        mon.violation = lambda *args, **kwargs: None; mon.released = lambda geoms: True
        for state in relay.states.values(): state.update(airborne=True, landed=False, transitions=[])
        d.joint('p1_free').qpos[2] = 1.2; mujoco.mj_forward(m, d)
        relay.sample(); self.assertFalse(mon.result_cache['task_success'])

    def test_threshold_treats_each_timber_individually(self):
        m, d, relay = GoalSupportTests().world(); mon = relay.mon
        mon.task.update(family='relay', level=1)
        mon.task = final_task(mon.task)
        mon.task['run_protocol'] = {'evaluation_semantics':'terminal_outcome_v2'}
        mon.violations = []; mon.bilateral = lambda *args, **kwargs: set()
        mon.bottom = lambda geoms: .8; mon.velocity = lambda body: np.zeros(6)
        mon.violation = lambda *args, **kwargs: None; mon.released = lambda geoms: True
        for state in relay.states.values(): state.update(airborne=True, landed=False, transitions=[])
        d.joint('p1_free').qpos[1] = .359; mujoco.mj_forward(m, d); relay.sample()
        self.assertTrue(mon.result_cache['task_success'])
        d.joint('p1_free').qpos[1] = .361; mujoco.mj_forward(m, d); relay.sample()
        self.assertFalse(mon.result_cache['task_success'])
        self.assertTrue(mon.result_cache['payloads']['p2']['terminal_goal_met'])


if __name__ == '__main__': unittest.main()
