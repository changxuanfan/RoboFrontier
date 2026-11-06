"""New Relay runs require a qualified airborne handover; frozen runs keep their terms."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from robofrontier import run_segments
from robofrontier.suite.relay_contract import final_task
from robofrontier.task_families import (RELAY_HANDOVER_RULE, expected_protocol, policy_task,
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
    with patch('robofrontier.suite.relay_goal_fraction.timber_fraction', return_value=np.float64(.9)):
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
        with patch('robofrontier.run_segments.current_restore', return_value=(note, Path('/run/pose.npy'))):
            relay.continue_record()
        self.assertEqual(relay.states['p1']['transitions'], [HANDOVER])
        self.assertEqual(relay.states['p1']['drops'], 2)
        self.assertEqual(relay.states['p2']['transitions'], [])

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
