"""New Relay runs require a qualified airborne handover; frozen runs keep their terms."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from robofrontier.runtime import segments as run_segments
from robofrontier.tasks.relay import final_task
from robofrontier.tasks.families import (RELAY_HANDOVER_RULE, expected_protocol, policy_task,
                                        protocol_for, resolve_case, sha, RELEASE, ROOT)
from tests.test_relay_goal_support import GoalSupportTests

HANDOVER = dict(sim_time_s=5.0, senders=['A', 'B'], receivers=['B', 'C'], retained=['B'], released=['A'], joined=['C'],
                protocol='qualified-members-v2')
RELEASE_ONLY = dict(sim_time_s=6.0, senders=['A', 'B', 'C'], receivers=['A', 'B'], retained=['A', 'B'], released=['C'], joined=[],
                    protocol='qualified-members-v2')


def score(handovers, rule=RELAY_HANDOVER_RULE):
    """Two timbers fully inside GOAL and released, with the given handovers on each."""
    _, _, relay = GoalSupportTests().world()
    mon = relay.mon
    mon.task.update(family='relay', level=1)
    mon.task = final_task(mon.task)
    mon.task['run_protocol'] = {'evaluation_semantics': 'terminal_outcome_v2'}
    if rule: mon.task['run_protocol']['relay_completion_rule'] = rule
    mon.violations = []
    mon.bilateral = lambda *args, **kwargs: set()
    mon.bottom = lambda geoms: .8
    mon.velocity = lambda body: np.zeros(6)
    mon.violation = lambda *args, **kwargs: None
    mon.released = lambda geoms: True
    for ident, state in relay.states.items():
        state.update(airborne=True, landed=False, transitions=list(handovers.get(ident, [])))
    with patch('robofrontier.tasks.relay_goal_fraction.timber_fraction', return_value=np.float64(.9)):
        relay.sample()
    return mon.result_cache


class HandoverScoringTests(unittest.TestCase):
    def test_placement_without_a_handover_is_not_complete(self):
        result = score({})
        self.assertFalse(result['task_success'])
        self.assertEqual(result['terminal_completed_payloads'], 0)
        self.assertFalse(result['payloads']['p1']['airborne_handover_met'])

    def test_every_timber_needs_its_own_handover(self):
        result = score({'p1': [HANDOVER]})
        self.assertFalse(result['task_success'])
        self.assertEqual(result['terminal_completed_payloads'], 1)

    def test_a_release_without_a_new_arm_is_not_a_handover(self):
        self.assertFalse(score({'p1': [RELEASE_ONLY], 'p2': [RELEASE_ONLY]})['task_success'])

    def test_handovers_complete_the_task_despite_process_events(self):
        result = score({'p1': [HANDOVER], 'p2': [HANDOVER]})
        self.assertTrue(result['task_success'])
        self.assertTrue(result['payloads']['p2']['airborne_handover_met'])

    def test_a_frozen_run_without_the_rule_keeps_its_terminal_result(self):
        result = score({}, rule=None)
        self.assertTrue(result['task_success'])
        self.assertNotIn('airborne_handover_met', result['payloads']['p1'])


class Scenario:
    """Drive the real Relay.sample at 20 ms with scripted support, table contact and GOAL membership."""
    def __init__(self, inside=True):
        _, self.data, self.relay = GoalSupportTests().world()
        mon = self.mon = self.relay.mon
        mon.task.update(family='relay', level=1)
        mon.task = final_task(mon.task)
        mon.task['run_protocol'] = {'evaluation_semantics': 'terminal_outcome_v2', 'relay_completion_rule': RELAY_HANDOVER_RULE}
        mon.violations = []
        self.support, self.grounded, self.inside = set(), False, inside
        mon.bilateral = lambda *args, **kwargs: set(self.support)
        mon.bottom = lambda geoms: .8 if self.grounded else .9
        mon.velocity = lambda body: np.zeros(6)
        mon.violation = lambda kind, **kwargs: mon.violations.append(kind)
        mon.released = lambda geoms: not self.support
        self.relay.inside = lambda state: self.inside
        self.relay.environment_contact = lambda geoms: self.grounded
        self.relay.supported_payloads = lambda *args, **kwargs: {'p1', 'p2'} if self.grounded else set()
        self.t = 10.

    def lifted(self, custody=('A', 'B')):
        for state in self.relay.states.values():
            state.update(airborne=True, custody=set(custody), landed=False, transitions=[])
        return self

    def run(self, support, seconds, grounded=None, inside=None):
        self.support = set(support)
        if grounded is not None: self.grounded = grounded
        if inside is not None: self.inside = inside
        for _ in range(int(round(seconds/.02))):
            self.t += .02; self.data.time = self.t
            with patch('robofrontier.tasks.relay_goal_fraction.timber_fraction', return_value=np.float64(.9)):
                self.relay.sample()
        return self

    @property
    def result(self): return self.mon.result_cache

    def state(self, ident='p1'): return self.relay.states[ident]


class AirborneHandoverTests(unittest.TestCase):
    """Every handover happens off the table (task_families.RELAY_HANDOVER_DEFINITION)."""
    def test_a_regrasp_of_a_timber_resting_on_the_goal_table_is_not_a_handover(self):
        s = Scenario().lifted()
        s.run({'A', 'B'}, .1, grounded=True).run({'A', 'B', 'C'}, .3).run({'B', 'C'}, .1).run(set(), .1)
        self.assertFalse(s.result['task_success'])
        self.assertEqual(s.result['terminal_completed_payloads'], 0)
        self.assertFalse(s.result['payloads']['p1']['airborne_handover_met'])
        regrasp = s.result['payloads']['p1']['handovers'][-1]
        self.assertEqual((regrasp['joined'], regrasp['airborne'], regrasp['protocol']), (['C'], False, 'grounded-regrasp-v1'))
        self.assertEqual(s.mon.violations, [])

    def test_the_same_exchange_in_the_air_is_a_handover(self):
        s = Scenario().lifted()
        s.run({'A', 'B'}, .1).run({'A', 'B', 'C'}, .3).run({'B', 'C'}, .1).run({'B', 'C'}, .1, grounded=True).run(set(), .1)
        self.assertTrue(s.result['task_success'])
        handover = s.result['payloads']['p1']['handovers'][-1]
        self.assertEqual((handover['joined'], handover['airborne'], handover['protocol']), (['C'], True, 'qualified-members-v3'))
        self.assertEqual(s.result['payloads']['p1']['handover_protocol'], 'qualified-members-v3')

    def test_touching_the_table_restarts_the_receivers_qualification(self):
        s = Scenario().lifted()
        s.run({'A', 'B', 'C'}, .16).run({'A', 'B', 'C'}, .04, grounded=True).run({'A', 'B', 'C'}, .1, grounded=False).run({'B', 'C'}, .04)
        self.assertEqual(s.state()['transitions'], [])
        self.assertEqual(s.state()['custody'], {'A', 'B'})
        self.assertIn('unverified_handover', s.mon.violations)

    def test_a_release_on_the_goal_table_is_recorded_without_a_violation(self):
        s = Scenario().lifted(('A', 'B', 'C'))
        s.run({'A', 'B', 'C'}, .1, grounded=True).run({'A', 'B'}, .04)
        release = s.state()['transitions'][-1]
        self.assertEqual((release['released'], release['joined'], release['airborne']), (['C'], [], False))
        self.assertEqual(s.mon.violations, [])

    def test_another_arm_lifting_a_dropped_timber_earns_no_handover(self):
        s = Scenario(inside=False).lifted()
        s.run({'A', 'B'}, .1).run({'A', 'B'}, .04, grounded=True).run(set(), .1)
        self.assertTrue(s.state()['dropped'])
        s.run({'C', 'D'}, .1, grounded=True).run({'C', 'D'}, .5, grounded=False).run({'C', 'D', 'B'}, .3)
        s.run({'C', 'D'}, .1, inside=True).run(set(), .1, grounded=True)
        self.assertTrue(s.state()['dropped'])
        self.assertEqual(s.state()['transitions'], [])
        self.assertIn('receiver_recovered_drop', s.mon.violations)
        self.assertFalse(s.result['payloads']['p1']['airborne_handover_met'])
        self.assertFalse(s.result['task_success'])

    def test_receiver_evidence_from_before_a_drop_does_not_survive_it(self):
        s = Scenario(inside=False).lifted()
        s.run({'A', 'B', 'C'}, .1).run({'A', 'B', 'C'}, .3, grounded=True)
        self.assertTrue(s.state()['dropped'])
        s.run({'A', 'B', 'C'}, .04, grounded=False)
        self.assertFalse(s.state()['dropped'])
        s.run({'B', 'C'}, .04)
        self.assertEqual(s.state()['transitions'], [])
        self.assertIn('unverified_handover', s.mon.violations)


class ProtocolTests(unittest.TestCase):
    def test_only_relay_tasks_carry_the_rule(self):
        self.assertEqual(policy_task('relay-a08-d1')['run_protocol']['relay_completion_rule'], RELAY_HANDOVER_RULE)
        self.assertNotIn('relay_completion_rule', policy_task('transport-a04-d1')['run_protocol'])

    def test_a_frozen_relay_protocol_without_the_rule_stays_valid(self):
        _, _, case = resolve_case('relay-a08-d1')
        release = sha(Path(ROOT)/RELEASE)
        old = protocol_for(case, release); old.pop('relay_completion_rule')
        self.assertEqual(expected_protocol(case, old, release), old)
        new = protocol_for(case, release)
        self.assertEqual(expected_protocol(case, new, release), new)


class RestartTests(unittest.TestCase):
    def test_a_continued_evaluator_keeps_the_earlier_handover(self):
        _, _, relay = GoalSupportTests().world()
        relay.mon.w = type('World', (), {'directory': Path('/run')})()
        note = {'evaluator': {'relay_payloads': {'p1': {'handovers': [HANDOVER], 'drops': 2}, 'gone': {'handovers': [], 'drops': 0}}}}
        with patch('robofrontier.runtime.segments.current_restore', return_value=(note, Path('/run/pose.npy'))):
            relay.continue_record()
        self.assertEqual(relay.states['p1']['transitions'], [HANDOVER])
        self.assertEqual(relay.states['p1']['drops'], 2)
        self.assertEqual(relay.states['p2']['transitions'], [])

    def continued(self, item):
        s = Scenario()
        for state in s.relay.states.values(): state.update(airborne=False, custody=set())
        s.relay.mon.w = type('World', (), {'directory': Path('/run')})()
        note = {'evaluator': {'relay_payloads': {'p1': item, 'p2': item}}}
        with patch('robofrontier.runtime.segments.current_restore', return_value=(note, Path('/run/pose.npy'))):
            s.relay.continue_record()
        return s

    def test_a_handover_under_way_at_the_restore_frame_can_still_complete(self):
        s = self.continued({'handovers': [], 'drops': 0, 'custody': ['A', 'B'], 'dropped': False})
        s.run({'A', 'B', 'C'}, .3)
        self.assertEqual(s.state()['custody'], {'A', 'B'})
        s.run({'B', 'C'}, .1)
        self.assertEqual(s.state()['transitions'][-1]['joined'], ['C'])
        self.assertTrue(s.state()['transitions'][-1]['airborne'])

    def test_a_timber_dropped_at_the_restore_frame_stays_dropped_for_other_arms(self):
        s = self.continued({'handovers': [], 'drops': 1, 'custody': ['A', 'B'], 'dropped': True})
        s.run({'C', 'D'}, .3)
        self.assertEqual((s.state()['custody'], s.state()['dropped'], s.state()['transitions']), ({'A', 'B'}, True, []))
        self.assertIn('receiver_recovered_drop', s.mon.violations)
        s.run({'A', 'B'}, .1)
        self.assertFalse(s.state()['dropped'])
        self.assertEqual(s.state()['drops'], 1)

    def test_a_record_without_custody_keeps_the_lifting_team(self):
        s = self.continued({'handovers': [], 'drops': 0})
        s.run({'C', 'D'}, .1)
        self.assertEqual((s.state()['custody'], s.state()['dropped']), ({'C', 'D'}, False))

    def test_custody_and_drop_state_come_from_the_latest_segment(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            self.log(run,
                     [(5.0, {'p1': {'handovers': [HANDOVER], 'drops': 1, 'custody': ['B', 'C'], 'dropped': False}})],
                     [(10.0, {'p1': {'handovers': [HANDOVER], 'drops': 2, 'custody': ['B', 'C'], 'dropped': True}})])
            record = run_segments.relay_record(run)
        self.assertEqual(record['p1'], {'handovers': [HANDOVER], 'drops': 2, 'custody': ['B', 'C'], 'dropped': True})

    def log(self, run, *blocks):
        path = run/'private/outputs/suite-process.jsonl'; path.parent.mkdir(parents=True)
        lines = []
        for block in blocks:
            lines.append(json.dumps({'schema': 'robofrontier.suite-process.v2'}))
            for t, payloads in block:
                lines.append(json.dumps({'type': 'event', 'sim_time_s': t, 'result': {'payloads': payloads}}))
        path.write_text('\n'.join(lines)+'\n')

    def test_handovers_and_drops_carry_across_segments_without_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            self.log(run,
                     [(5.0, {'p1': {'handovers': [HANDOVER], 'drops': 1}}), (90.0, {'p1': {'handovers': [HANDOVER, RELEASE_ONLY], 'drops': 2}})],
                     [(10.0, {'p1': {'handovers': [HANDOVER], 'drops': 1}, 'p2': {'handovers': [], 'drops': 0}})])
            record = run_segments.relay_record(run, 20.0)
        self.assertEqual(record['p1'], {'handovers': [HANDOVER], 'drops': 1})
        self.assertEqual(record['p2'], {'handovers': [], 'drops': 0})

    def test_other_families_have_no_relay_record(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder); path = run/'private/outputs/suite-process.jsonl'; path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'type': 'event', 'sim_time_s': 1.0, 'result': {'valid_trials': 1}})+'\n')
            self.assertIsNone(run_segments.relay_record(run))


if __name__ == '__main__':
    unittest.main()
