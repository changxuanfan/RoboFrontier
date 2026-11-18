"""User-authorized low release inside Goal; final stable support remains required."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import mujoco
import numpy as np

from roboteam.sim.robot_control import PandaArm
from roboteam.tasks.evaluate import Monitor
from roboteam.tasks.families import ROOT


def relay_world():
    """The released relay-a08-d1 scene at its initial state, with its evaluator."""
    scene=ROOT/'benchmark/relay/relay-a08-d1'
    t=SimpleNamespace(model=mujoco.MjModel.from_xml_path(str(scene/'scene.xml')),task=json.loads((scene/'task.json').read_text()))
    t.data=mujoco.MjData(t.model)
    mujoco.mj_resetDataKeyframe(t.model,t.data,t.model.key('initial').id);mujoco.mj_forward(t.model,t.data)
    t.arms={a:PandaArm(t.model,t.data,a) for a in t.task['arms']}
    t.monitor=Monitor(t)
    return t


class NearGoalReleaseTests(unittest.TestCase):
    def setUp(self):
        self.t=relay_world();self.relay=self.t.monitor.relay
        self.ident='payload_02';self.relay.states={self.ident:self.relay.states[self.ident]}
        self.state=self.relay.states[self.ident]
        self.state.update(airborne=True,custody={'G','H'},transitions=[dict(senders=['E','F'],receivers=['G','H'],airborne=True)])
        self.t.task['completion'].update(support_via_goal_payload=True,required_airborne_handover=True,
            allow_goal_partial_support=True,allow_near_goal_release=True)
        self.support={'G','H'};self.inside=True;self.contact=False;self.grounded=False;self.gap=.015
        def bottom(geoms):return .8+self.gap
        def grounds(goal_only=True,*args):return {self.ident} if self.grounded or (not goal_only and self.contact) else set()
        patches=[patch.object(self.t.monitor,'bilateral',side_effect=lambda *a,**k:set(self.support)),
            patch.object(self.t.monitor,'bottom',side_effect=bottom),
            patch.object(self.t.monitor,'velocity',return_value=np.zeros(6)),
            patch.object(self.t.monitor,'released',side_effect=lambda *a:not self.support),
            patch.object(self.relay,'inside',side_effect=lambda *a:self.inside),
            patch.object(self.relay,'environment_contact',side_effect=lambda *a:self.contact),
            patch.object(self.relay,'supported_payloads',side_effect=grounds)]
        for p in patches:p.start();self.addCleanup(p.stop)

    def sample(self,stamp,support=None):
        if support is not None:self.support=set(support)
        self.t.data.time=stamp;self.relay.sample()

    def test_pendant_may_touch_inside_goal_while_original_hands_hold_timber(self):
        self.contact=True;self.gap=.3
        self.sample(1.)
        self.assertFalse(self.state['dropped']);self.assertEqual(self.state['drops'],0)
        self.assertFalse(self.t.monitor.result_cache['task_success'])

    def test_low_release_needs_no_prior_table_contact_and_only_completes_after_settling(self):
        self.sample(1.);self.sample(1.02,set());self.sample(1.4)
        self.assertFalse(self.state['dropped'])
        self.assertFalse(self.t.monitor.result_cache['task_success'])
        self.contact=self.grounded=True
        self.sample(1.5);self.sample(3.)
        self.assertTrue(self.t.monitor.result_cache['task_success'])

    def test_high_release_remains_an_unsupported_drop(self):
        self.gap=.3;self.sample(1.);self.sample(1.02,set());self.sample(1.4)
        self.assertTrue(self.state['dropped'])

    def test_leaving_goal_revokes_low_release_permission(self):
        self.sample(1.);self.sample(1.02,set());self.inside=False;self.contact=True
        self.sample(1.4)
        self.assertTrue(self.state['dropped'])

    def test_near_goal_release_does_not_bypass_real_airborne_handover(self):
        self.state['transitions']=[]
        self.sample(1.);self.sample(1.02,set());self.contact=self.grounded=True
        self.sample(1.5);self.sample(3.)
        self.assertFalse(self.t.monitor.result_cache['task_success'])

    def test_a_contract_without_partial_support_counts_goal_contact_as_a_drop(self):
        self.t.task['completion']['allow_goal_partial_support']=False
        self.t.task['completion']['allow_near_goal_release']=False
        self.contact=True;self.gap=.3;self.sample(1.)
        self.assertTrue(self.state['dropped'])


if __name__=='__main__':unittest.main()
