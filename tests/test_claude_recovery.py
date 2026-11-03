"""Real host/store recovery against deterministic CLI results; no paid calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_claude_session_host import make_run, PROFILE
from robofrontier.claude.session_host import ClaudeSessionHost
from robofrontier.claude.runner import summarize
from robofrontier.claude.budget import BudgetLedger
from robofrontier.runtime_store import RuntimeStore


class CapacityRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.run = make_run(self.tmp.name)
        self.calls = []; self.prompts = []; self.failures = 1
        def runner(*args, **kw):
            self.calls.append(kw); fail = len(self.calls) <= self.failures
            self.prompts.append(args[4])
            return {'process': 'exited', 'exit_code': 1 if fail else 0, 'summary': {
                'session_id': kw.get('resume') or kw['session_id'], 'turn_status': 'failed' if fail else 'ended',
                'result_subtype': 'error_during_execution' if fail else 'success',
                'capacity_error_code': 'rate_limit' if fail else None, 'malformed_lines': 0,
                'total_cost_usd': None}}
        self.runner = runner
        self.host = ClaudeSessionHost(self.run, 'Controller', PROFILE, {}, runner=runner)
        self.store = RuntimeStore(self.run/'private/state/runtime.sqlite')
        cfg = json.loads((Path(__file__).resolve().parents[1]/'configs/harnesses/policy.json').read_text())
        cfg.update(engine='claude'); self.store.initialize('run', cfg, ['A'])
        self.store.update_agent('Controller', ready=True, thread_id=self.host.session_id); self.store.start()
        native = self.run/'private/claude-config/projects/local'/(self.host.session_id+'.jsonl')
        native.parent.mkdir(parents=True)
        native.write_text(json.dumps({'uuid':'u1','sessionId':self.host.session_id,
                                      'message':{'role':'user','content':'task'}})+'\n')

    def tearDown(self):
        self.host.wait(3); self.store.close(); self.tmp.cleanup()

    def fail_turn(self):
        self.host.send('task'); self.assertEqual(self.host.wait(3)['status'], 'error')

    def test_wait_and_resume_same_session_without_replaying_robot_work(self):
        self.fail_turn()
        self.assertTrue(self.host.recover_capacity(self.store, now=0))
        self.assertEqual(len(self.calls), 1)
        from robofrontier.claude.recovery import capacity_delay
        delay = capacity_delay(0, self.host.session_id)
        self.assertTrue(10 <= delay < 15)
        self.assertTrue(self.host.recover_capacity(self.store, now=delay-.01))
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.host.recover_capacity(self.store, now=delay))
        self.assertEqual(self.host.wait(3)['status'], 'idle')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1]['resume'], self.host.session_id)
        self.assertIsNone(self.calls[1]['session_id'])
        self.assertIn('already STARTED', self.prompts[1])
        self.assertEqual(self.host.capacity_retry_count, 0)

    def test_unknown_execution_stop_or_paused_world_never_retries(self):
        self.fail_turn()
        with patch.object(self.store, 'actions', return_value={'x': {'status':'uncertain'}}):
            self.assertFalse(self.host.recover_capacity(self.store, now=100))
        (self.run/'STOP').touch()
        self.assertFalse(self.host.recover_capacity(self.store, now=100))
        (self.run/'STOP').unlink(); self.store.put('dispatch_paused', True)
        self.assertFalse(self.host.recover_capacity(self.store, now=100))
        self.assertEqual(len(self.calls), 1)

    def test_isolated_robot_does_not_prevent_model_resuming_to_investigate(self):
        self.fail_turn()
        for action in ({'status':'uncertain','isolated':True},
                       {'status':'running','local_recovery':True,'phase':'stopping'}):
            with self.subTest(action=action), patch.object(self.store, 'actions', return_value={'x':action}):
                self.host.capacity_retry_due=None
                self.assertTrue(self.host.recover_capacity(self.store, now=0))
                self.assertTrue(self.host.recover_capacity(self.store, now=100))
                self.assertEqual(self.host.wait(3)['status'],'idle')
                self.assertEqual(self.calls[-1]['resume'],self.host.session_id)
                if action.get('isolated'):
                    self.host.state='error';self.host.retryable_capacity=True

    def test_accepted_request_must_settle_before_retry(self):
        self.fail_turn(); self.store.begin_call('old', 'Controller', 'move', {})
        self.assertTrue(self.host.recover_capacity(self.store, now=0))
        self.assertTrue(self.host.recover_capacity(self.store, now=100))
        self.assertEqual(len(self.calls), 1)
        self.store.finish_call('old', {'call_id':'old'})
        self.assertTrue(self.host.recover_capacity(self.store, now=101))
        self.host.wait(3); self.assertEqual(len(self.calls), 2)

    def test_retries_are_bounded_for_consecutive_failures(self):
        self.failures = 10; self.fail_turn()
        for n in range(3):
            self.assertTrue(self.host.recover_capacity(self.store, now=n*100))
            self.assertTrue(self.host.recover_capacity(self.store, now=n*100+60))
            self.assertEqual(self.host.wait(3)['status'], 'error')
        self.assertFalse(self.host.recover_capacity(self.store, now=1000))
        self.assertEqual(len(self.calls), 4)

    def test_unknown_capped_cost_blocks_but_uncapped_missing_cost_does_not(self):
        for capped in (True, False):
            ledger = BudgetLedger.create(self.run/('capped.sqlite' if capped else 'uncapped.sqlite'), 1 if capped else None)
            try:
                host = ClaudeSessionHost(self.run, 'Controller', PROFILE, {}, runner=self.runner,
                                         budget_ledger=ledger, max_budget_usd=.2 if capped else None)
                self.failures = 100
                host.send('task'); value = host.wait(3)
                self.assertEqual(value['status'], 'unknown' if capped else 'error')
                self.assertEqual(value['retryable_capacity'], not capped)
            finally: ledger.close()

    def test_only_structured_capacity_errors_are_classified(self):
        final = {'type':'result','subtype':'error_during_execution','session_id':'s','is_error':True}
        def classify(error):
            return summarize([json.dumps(error), json.dumps(final)])['capacity_error_code']
        self.assertEqual(classify({'type':'assistant','isApiErrorMessage':True,'error':'rate_limit'}), 'rate_limit')
        self.assertIsNone(classify({'type':'assistant','message':{'content':'429 overloaded'}}))
        self.assertIsNone(classify({'type':'assistant','isApiErrorMessage':True,'error':'authentication_failed'}))

    def test_missing_native_history_or_other_terminal_reason_never_retries(self):
        self.fail_turn()
        with patch('robofrontier.claude.recovery.transcript_rows', return_value=[]):
            self.assertFalse(self.host.recover_capacity(self.store, now=0))
        with patch('robofrontier.claude.recovery.transcript_rows', return_value=[{'uuid':'foreign','sessionId':'other'}]):
            self.assertFalse(self.host.recover_capacity(self.store, now=0))
        original=self.runner
        def budget_error(*args, **kw):
            result=original(*args, **kw)
            result['summary']['result_subtype']='error_max_budget_usd'
            return result
        self.host.state='idle'; self.host.runner=budget_error; self.failures=100
        self.host.send('task'); self.host.wait(3)
        self.assertFalse(self.host.retryable_capacity)


if __name__ == '__main__': unittest.main()


class ModelLossTests(unittest.TestCase):
    """A CLI that dies mid-turn resumes the same session; the run allows three in total."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.run = make_run(self.tmp.name)
        (self.run/'private/inputs/bootstrap').mkdir(parents=True, exist_ok=True)
        (self.run/'private/inputs/bootstrap/model-restart.md').write_text('MODEL RESTART NOTICE')
        self.calls = []; self.prompts = []; self.lost = 1
        def runner(*args, **kw):
            self.calls.append(kw); self.prompts.append(args[4])
            if len(self.calls) <= self.lost:
                # Killed from outside: exited without a result event.
                return {'process': 'exited', 'exit_code': -9, 'summary': {'session_id': None, 'turn_status': 'unknown'}}
            return {'process': 'exited', 'exit_code': 0, 'summary': {
                'session_id': kw.get('resume') or kw['session_id'], 'turn_status': 'ended',
                'result_subtype': 'success', 'malformed_lines': 0, 'total_cost_usd': .01}}
        self.host = ClaudeSessionHost(self.run, 'Controller', PROFILE, {}, runner=runner)
        self.store = RuntimeStore(self.run/'private/state/runtime.sqlite')
        cfg = json.loads((Path(__file__).resolve().parents[1]/'configs/harnesses/policy.json').read_text())
        cfg.update(engine='claude'); self.store.initialize('run', cfg, ['A'])
        self.store.update_agent('Controller', ready=True, thread_id=self.host.session_id); self.store.start()

    def tearDown(self):
        self.host.wait(3); self.store.close(); self.tmp.cleanup()

    def test_lost_cli_resumes_the_same_session_with_the_frozen_notice(self):
        self.host.send('task'); self.assertEqual(self.host.wait(3)['status'], 'error')
        self.assertTrue(self.host.cli_lost)
        self.assertTrue(self.host.recover_capacity(self.store))
        self.assertEqual(self.host.wait(3)['status'], 'idle')
        self.assertEqual(self.prompts[1], 'MODEL RESTART NOTICE')
        self.assertEqual(self.calls[1]['resume'], self.host.session_id)
        self.assertEqual(self.store.get('model_restarts'), 1)

    def test_the_run_allowance_is_shared_and_never_exceeded(self):
        from robofrontier.policy_bootstrap import MAX_MODEL_RESTARTS
        for _ in range(MAX_MODEL_RESTARTS):
            self.assertIsNotNone(self.store.claim_model_restart('B', 'codex', MAX_MODEL_RESTARTS))
        self.host.send('task'); self.assertEqual(self.host.wait(3)['status'], 'error')
        self.assertFalse(self.host.recover_capacity(self.store))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.store.get('model_restarts'), MAX_MODEL_RESTARTS)
