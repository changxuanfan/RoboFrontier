"""A Claude turn that failed on the network during an outage pause is resent once, as Codex does.

Real runtime store, world pause and session host; the CLI is a deterministic fake. Only runs
whose protocol counts active time (clock active_time_v1) do this."""
import json
import time
import unittest
from unittest.mock import patch

from robofrontier.engines.claude import recovery
from robofrontier.engines.claude.runner import summarize
from robofrontier.engines.claude.session_host import ClaudeSessionHost
from robofrontier.runtime.egress_pause import WorldPause
from robofrontier.runtime.outage import OutageMonitor
from robofrontier.runtime.clock import BudgetGuard, protocol
from test_claude_session_host import PROFILE
import test_active_time as active

NETWORK = {'type': 'assistant', 'is_api_error_message': True, 'error': 'server_error', 'api_error': 'connection_failed'}
AUTH = {'type': 'assistant', 'is_api_error_message': True, 'error': 'authentication_failed'}


def turn(session, error=None):
    """A CLI record of one turn: ended, or failed after `error` (None: failed with no API error)."""
    lines = [] if error is False else [json.dumps(dict(error, session_id=session))] if error else []
    result = {'type': 'result', 'session_id': session, 'subtype': 'success',
              'is_error': error is not False, 'total_cost_usd': .01}
    lines.append(json.dumps(result))
    return {'process': 'exited', 'exit_code': 0, 'summary': summarize(lines)}


class NetworkResendTests(active.Fixture):
    def setUp(self):
        super().setUp()
        self.answers = []
        self.monitor = OutageMonitor(('api.example',), lambda hosts: self.answers.pop(0))
        self.s.egress_pause = WorldPause(self.s, self.monitor)
        self.s.policy_budget = BudgetGuard(protocol(600, active.ACTIVE))
        self.s.store.put('physics_state', 'running')
        self.turns = []; self.calls = []; self.prompts = []
        def runner(*args, **kw):
            self.calls.append(kw); self.prompts.append(args[4])
            session = kw.get('resume') or kw['session_id']
            return turn(session, self.turns.pop(0) if self.turns else False)
        self.host = ClaudeSessionHost(self.run, 'A', PROFILE, {}, runner=runner)
        self.addCleanup(self.host.wait, 3)
        self.s.store.update_agent('A', thread_id=self.host.session_id)
        self.notice = (self.run/'private/inputs/bootstrap/network-resume.md').read_text()

    def probe(self, *answers):
        self.answers.extend(answers)
        for _ in answers: self.monitor.step()
        self.s.pump()

    def fail(self, error):
        self.turns.append(error)
        if self.host.state == 'new': self.host.send('task')
        else: self.host.state = 'idle'; self.host.send('continue')
        self.assertEqual(self.host.wait(3)['status'], 'error')

    def recover(self, clock=active.ACTIVE):
        with patch.object(recovery, '_active_time', return_value=clock == active.ACTIVE):
            return self.host.recover_capacity(self.s.store)

    def outage(self):
        self.probe(True, False, False, False)
        self.assertEqual(self.s.store.get('physics_state'), 'paused_by_egress')

    def test_network_failure_during_an_outage_is_resent_once_after_resume(self):
        self.outage(); self.fail(NETWORK)
        self.assertEqual(recovery.failure_kind(self.host.last_result['summary']), 'network')
        # While the world is paused nothing is resent: the claim needs the resume record.
        self.assertFalse(self.recover()); self.assertEqual(len(self.calls), 1)
        self.probe(True)
        self.assertEqual(self.s.store.get('egress_recovery')['claim'], 'outage-1')
        self.assertTrue(self.recover())
        self.assertEqual(self.host.wait(3)['status'], 'idle')
        self.assertEqual(self.prompts[1], self.notice)
        self.assertEqual((self.calls[1]['resume'], self.calls[1]['session_id']), (self.host.session_id, None))
        self.assertEqual(self.events('NETWORK_CONTINUATION_CLAIMED')[0]['thread_id'], self.host.session_id)
        # The run goes on: the world runs and dispatch is not held.
        self.assertEqual(self.s.store.get('lifecycle'), 'running')
        self.assertFalse(self.s.store.get('dispatch_paused')); self.assertTrue(self.s.step_physics())

    def test_a_second_failure_in_the_same_outage_is_held_not_resent(self):
        self.outage(); self.fail(NETWORK); self.probe(True)
        self.assertTrue(self.recover()); self.host.wait(3)
        self.fail(NETWORK)
        self.assertTrue(self.recover())
        self.assertEqual(len(self.calls), 3)  # task, one continuation, the failed continue; no resend
        self.assertTrue(self.s.store.get('egress_review_hold')); self.assertTrue(self.s.store.get('dispatch_paused'))
        self.assertEqual(len(self.events('NETWORK_CONTINUATION_UNCERTAIN')), 1)
        self.assertFalse(self.recover())

    def test_a_non_network_failure_after_an_outage_is_flagged_for_review(self):
        self.outage(); self.fail(AUTH); self.probe(True)
        self.assertEqual(recovery.failure_kind(self.host.last_result['summary']), 'other')
        self.assertTrue(self.recover())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.events('NETWORK_CONTINUATION_CLAIMED'), [])
        self.assertEqual(len(self.events('NETWORK_CONTINUATION_UNCERTAIN')), 1)
        self.assertTrue(self.s.store.get('egress_review_hold'))

    def test_an_unclassified_failure_during_the_outage_counts_as_network(self):
        self.outage(); self.fail(None); self.probe(True)
        self.assertIsNone(recovery.failure_kind(self.host.last_result['summary']))
        self.assertTrue(self.recover()); self.assertEqual(self.host.wait(3)['status'], 'idle')
        self.assertEqual(self.prompts[1], self.notice)

    def test_a_network_failure_before_the_pause_waits_for_it(self):
        self.fail(NETWORK)
        self.assertTrue(self.recover())  # within NETWORK_WAIT_S: the probes have not paused yet
        self.outage(); self.probe(True)
        self.assertTrue(self.recover()); self.assertEqual(self.host.wait(3)['status'], 'idle')
        self.assertEqual(len(self.calls), 2)

    def test_a_network_failure_without_any_pause_is_an_ordinary_failure(self):
        self.fail(NETWORK); self.host.failed_at = time.time() - recovery.NETWORK_WAIT_S - 1
        self.assertFalse(self.recover())
        self.assertEqual(len(self.calls), 1); self.assertIsNone(self.s.store.get('egress_review_hold'))

    def test_a_role_with_robot_work_in_flight_waits(self):
        self.outage(); self.fail(NETWORK); self.probe(True)
        self.s.store.begin_call('old', 'A', 'move', {})
        self.assertTrue(self.recover()); self.assertEqual(len(self.calls), 1)
        self.s.store.finish_call('old', {'call_id': 'old'})
        self.assertTrue(self.recover()); self.host.wait(3); self.assertEqual(len(self.calls), 2)

    def test_runs_frozen_without_the_active_clock_are_unchanged(self):
        # A run frozen before the active-time clock has none in its protocol: the
        # real check reads START wall time.
        path = self.run/'private/inputs/task.json'
        task = json.loads(path.read_text()); task['run_protocol'].pop('clock', None); path.write_text(json.dumps(task))
        self.outage(); self.fail(NETWORK); self.probe(True)
        self.assertFalse(recovery._active_time(self.run))
        self.assertFalse(self.host.recover_capacity(self.s.store))
        self.assertFalse(self.recover(clock='START_wall_time'))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.events('NETWORK_CONTINUATION_CLAIMED'), [])
        self.assertIsNone(self.s.store.get('egress_review_hold'))


class ClassificationTests(unittest.TestCase):
    def kind(self, *events):
        return recovery.failure_kind(summarize([json.dumps(e) for e in events]
                                               + [json.dumps({'type': 'result', 'subtype': 'success', 'is_error': True})]))

    def test_only_typed_connection_errors_without_status_are_network(self):
        for name in sorted(recovery.NETWORK_API_ERRORS):
            self.assertEqual(self.kind(dict(NETWORK, api_error=name)), 'network')
        self.assertEqual(self.kind(dict(NETWORK, api_error_status=503)), 'other')
        self.assertEqual(self.kind(AUTH), 'other')
        self.assertIsNone(self.kind({'type': 'assistant', 'is_api_error_message': True, 'error': 'server_error'}))
        self.assertIsNone(self.kind({'type': 'assistant', 'message': {'content': 'Connection error.'}}))
        # The transcript's own spelling is read the same way.
        self.assertEqual(self.kind({'type': 'assistant', 'isApiErrorMessage': True, 'error': 'server_error',
                                    'apiError': 'no_response'}), 'network')


if __name__ == '__main__':
    unittest.main()
