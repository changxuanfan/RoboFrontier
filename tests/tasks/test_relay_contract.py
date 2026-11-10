"""Current Goal acceptance and metadata agree without erasing legacy rules."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from pathlib import Path
import json
import tempfile
import numpy as np
import mujoco

from robofrontier.tasks.relay import final_task, is_current
from tests.tasks import test_relay_goal_support as support_fixture


class RelayContractTests(unittest.TestCase):
    def world(self):
        model, data, relay = support_fixture.GoalSupportTests().world()
        mon = relay.mon
        mon.task.update(family='relay', level=1)
        mon.task = final_task(mon.task)
        mon.violations = []
        mon.bilateral = lambda *args, **kwargs:set()
        mon.bottom = lambda geoms:.8
        mon.velocity = lambda body:np.ones(6) * 10
        mon.released = lambda geoms:True
        mon.violation = lambda *args, **kwargs:mon.violations.append(args)
        for state in relay.states.values():
            state.update(airborne=True, landed=True, transitions=[dict(senders=['A','B'], receivers=['C','D'])])
        data.time=10
        return model,data,relay

    def test_metadata_is_final_idempotent_and_keeps_geometry(self):
        _,_,relay=self.world();task=relay.mon.task;original=deepcopy(task)
        self.assertEqual(final_task(task),task)
        self.assertEqual(task,original)
        self.assertTrue(is_current(task))
        self.assertNotIn('max_timber_release_gap_m',task['completion'])
        self.assertEqual(task['completion']['max_release_gap_m'],.03)
        self.assertFalse(any('R17' in r or '20mm' in r for r in task['rules']))

    def test_real_grounded_stack_completes_without_velocity_or_duration_gate(self):
        _,_,relay=self.world();relay.sample()
        self.assertTrue(relay.mon.result_cache['task_success'])
        self.assertEqual(relay.mon.result_cache['completed_payloads'],2)

    def test_terminal_scoring_keeps_legacy_process_result_separate(self):
        _,_,relay=self.world()
        relay.mon.task['run_protocol']={'evaluation_semantics':'terminal_outcome_v2'}
        relay.states['p1'].update(landed=False, transitions=[], dropped=True)
        relay.mon.violations=[{'kind':'inter_robot_contact','key':'A / B'}]
        relay.sample();result=relay.mon.result_cache
        self.assertTrue(result['terminal_goal_met'])
        self.assertTrue(result['task_success'])
        self.assertFalse(result['legacy_process_goals_met'])
        self.assertFalse(result['strict_task_success'])
        self.assertEqual(result['terminal_completed_payloads'],2)

    def test_edge_tolerance_applies_to_whole_geometry(self):
        model,data,relay=self.world()
        for name in ['p1','p2']:data.joint(name+'_free').qpos[0]=.349
        mujoco.mj_forward(model,data);relay.sample()
        self.assertTrue(relay.mon.result_cache['task_success'])
        for name in ['p1','p2']:data.joint(name+'_free').qpos[0]=.351
        mujoco.mj_forward(model,data);relay.sample()
        self.assertFalse(relay.mon.result_cache['task_success'])

    def test_release_support_and_real_handover_still_required(self):
        _,_,relay=self.world();relay.mon.released=lambda geoms:False;relay.sample()
        self.assertFalse(relay.mon.result_cache['task_success'])
        relay.mon.released=lambda geoms:True
        relay.states['p1']['transitions']=[];relay.sample()
        self.assertFalse(relay.mon.result_cache['task_success'])

    def test_air_gap_does_not_count_as_grounded_final_state(self):
        model,data,relay=self.world();data.joint('p1_free').qpos[2]=1.2
        mujoco.mj_forward(model,data);relay.sample()
        self.assertFalse(relay.mon.result_cache['task_success'])


if __name__=='__main__':unittest.main()
