import json
import multiprocessing
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest

from robofrontier.batch.claude_batch import run_batch, status_batch, stop_batch


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name) / 'batch'; self.root.mkdir()
        self.jobs = []
        for i in range(4):
            case = f'case{i}'; run = self.root / 'fake' / case
            (run/'private/inputs').mkdir(parents=True); (run/'private/state').mkdir(parents=True)
            (run/'public/inputs').mkdir(parents=True)
            (run/'public/inputs/roles.json').write_text(json.dumps({'roles': {
                'Meta': {'kind': 'manager'}, 'Controller': {'kind': 'controller', 'robots': ['A1', 'A2']},
                'A1': {'kind': 'worker', 'robot': 'A1'}, 'A2': {'kind': 'worker', 'robot': 'A2'}}}))
            profile = {'provider': 'anthropic', 'model': 'fake', 'effort': 'high', 'env_key': 'FAKE_KEY'}
            (run/'private/inputs/claude.json').write_text(json.dumps({'schema':'robofrontier.claude-launch.v2',
                'profile':profile}))
            (run/'private/inputs/harness.json').write_text(json.dumps({'engine':'claude', 'topology':'centralized',
                                                                       'model':'fake','effort':'high'}))
            self.jobs.append({'profile':'fake', 'case_id':case, 'run_directory':str(run), 'status':'draft'})
        (self.root/'batch.json').write_text(json.dumps({'schema':'robofrontier.claude-batch.v2',
            'status':'prepared_not_started', 'jobs':self.jobs}))
        self.env = {'FAKE_KEY':'secret'}

    def tearDown(self): self.tmp.cleanup()

    def run_case(self, runner, parallel=2):
        return run_batch(self.root, self.env, parallel=parallel, turn_budget_usd=.2, total_budget_usd=1, wall_limit_s=5,
                         runner=runner, verifier=lambda _: [], startup_interval_s=0)

    def test_standing_topologies_pass_shared_batch_preflight(self):
        for job, topology in zip(self.jobs, ('hierarchical', 'peer', 'hierarchical', 'peer')):
            path = Path(job['run_directory'])/'private/inputs/harness.json'
            data = json.loads(path.read_text())
            data.update(topology=topology, startup_protocol='direct_team_v3')
            path.write_text(json.dumps(data))
        seen = []
        def runner(run, *args, **kwargs):
            seen.append(Path(run).name)
            return {'status':'finished','reason':'wall_limit'}
        state = self.run_case(runner)
        self.assertEqual(state['status'], 'closed')
        self.assertEqual(set(seen), {'case0','case1','case2','case3'})

    def test_a_task_cap_concurrent_roles_could_exhaust_fails_preflight_before_any_claim(self):
        path = Path(self.jobs[2]['run_directory'])/'private/inputs/harness.json'
        data = json.loads(path.read_text()); data.update(topology='peer', startup_protocol='direct_team_v3')
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'concurrent roles'):
            run_batch(self.root, self.env, parallel=2, turn_budget_usd=.6, total_budget_usd=1, wall_limit_s=5,
                      runner=lambda *a, **k: self.fail('must not launch'), verifier=lambda _: [], startup_interval_s=0)
        self.assertFalse(any(self.root.rglob('*claim*')))

    def test_every_unchosen_end_asks_the_stop_table(self):
        # A host stop at its own wall limit, on STOP or after the world ended is final, even when
        # its seal is missing; any other end (a dead world, a session error, a pause) asks.
        from unittest.mock import patch
        from robofrontier.batch import claude_batch
        asked = []
        def fake_continue(run, reason):
            asked.append(reason); return False, 'not eligible in this test'
        with patch.object(claude_batch, 'try_continue', fake_continue):
            for reason in claude_batch.FINAL:
                result = claude_batch._run_once_continued(lambda *a, **k: {'reason': reason}, 'run', {})
                self.assertEqual(result['segments'], [])
            result = claude_batch._run_once_continued(lambda *a, **k: {'status': 'finished', 'reason': 'x'}, 'run', {})
            self.assertEqual(result['segments'], [])
            self.assertEqual(asked, [])
            unexpected = ('owner_unavailable', 'world_interrupted', 'dispatch_paused', 'session_error', 'supervisor_error')
            for reason in unexpected:
                result = claude_batch._run_once_continued(lambda *a, **k: {'reason': reason}, 'run', {})
                self.assertFalse(result['segments'][0]['continued'])
            self.assertEqual(len(asked), len(unexpected))

    def test_parallel_limit_all_jobs_and_single_use(self):
        guard = threading.Lock(); counts = {'active':0, 'maximum':0, 'total':0}
        def runner(*args, **kwargs):
            with guard:
                counts['active'] += 1; counts['total'] += 1
                counts['maximum'] = max(counts['active'], counts['maximum'])
            time.sleep(.08)
            with guard: counts['active'] -= 1
            return {'status':'finished', 'reason':'world_ended'}
        state = self.run_case(runner)
        self.assertEqual(counts, {'active':0, 'maximum':2, 'total':4})
        self.assertEqual(state['status'], 'closed')
        self.assertEqual([x['status'] for x in state['jobs']], ['closed']*4)
        self.assertEqual(len(status_batch(self.root)['runs']), 4)
        with self.assertRaisesRegex(ValueError, 'never restart'): self.run_case(runner)

    def test_startup_timeout_is_validated_and_passed_to_every_run(self):
        for invalid in (0, -1, float('nan'), 86401, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, 'startup timeout'):
                    run_batch(self.root,self.env,parallel=1,turn_budget_usd=.2,total_budget_usd=1,
                              wall_limit_s=5,startup_timeout_s=invalid,verifier=lambda _: [])
                self.assertFalse((self.root/'engineering-claim.json').exists())
        seen=[]
        def runner(*args,**kwargs):
            seen.append(kwargs['startup_timeout_s'])
            return {'status':'finished','reason':'world_ended'}
        result=run_batch(self.root,self.env,parallel=2,turn_budget_usd=.2,total_budget_usd=1,
                         wall_limit_s=5,startup_timeout_s=600,runner=runner,verifier=lambda _: [])
        self.assertEqual(seen,[600]*4)
        self.assertEqual(result['startup_timeout_s'],600)

    def test_defaults_have_no_cost_caps_and_use_24_hours(self):
        seen = []
        def runner(*args, **kwargs):
            seen.append(kwargs)
            return {'status': 'finished', 'reason': 'world_ended'}
        state = run_batch(self.root, self.env, parallel=2, runner=runner, verifier=lambda _: [])
        self.assertEqual(state['status'], 'closed')
        self.assertEqual(len(seen), 4)
        for options in seen:
            self.assertIsNone(options['turn_budget_usd'])
            self.assertIsNone(options['total_budget_usd'])
            self.assertEqual(options['wall_limit_s'], 86400)

    def test_stop_marks_active_and_skips_queued(self):
        entered = threading.Event(); finish = threading.Event(); outcome = []
        def runner(*args, **kwargs): entered.set(); finish.wait(3); return {'status':'finished', 'reason':'stop_requested'}
        thread = threading.Thread(target=lambda: outcome.append(self.run_case(runner, parallel=1)))
        thread.start(); self.assertTrue(entered.wait(3))
        self.assertTrue(stop_batch(self.root)['stop_requested'])
        finish.set(); thread.join(3); self.assertFalse(thread.is_alive())
        self.assertEqual(outcome[0]['status'], 'stopped')
        self.assertEqual([j['status'] for j in outcome[0]['jobs']], ['closed'] + ['stopped_before_start']*3)
        self.assertTrue(all((Path(j['run_directory'])/'STOP').exists() for j in self.jobs))

    def test_cli_sigterm_requests_stop_and_waits_for_active_job(self):
        ctx = multiprocessing.get_context('fork')
        entered = ctx.Event()
        def child():
            import robofrontier.batch.claude_batch as batch_module
            original = batch_module.run_batch
            def runner(run, *args, **kwargs):
                assert kwargs['startup_timeout_s'] == 321
                entered.set()
                deadline=time.monotonic()+10
                while not (Path(run)/'STOP').exists() and time.monotonic()<deadline:
                    time.sleep(.02)
                return {'status':'finished','reason':'stop_requested'}
            def launch(*args, **kwargs):
                return original(*args, **kwargs, runner=runner, verifier=lambda _: [])
            batch_module.run_batch=launch
            os.environ['FAKE_KEY']='synthetic'
            batch_module.run_until_signal(self.root, dict(os.environ), parallel=1, turn_budget_usd=.2,
                                          total_budget_usd=1, wall_limit_s=5, startup_timeout_s=321)
        process=ctx.Process(target=child); process.start()
        try:
            self.assertTrue(entered.wait(10))
            os.kill(process.pid, signal.SIGTERM)
            process.join(10)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode,0)
            state=status_batch(self.root)
            self.assertEqual(state['status'],'stopped')
            self.assertEqual(state['startup_timeout_s'],321)
            self.assertEqual([j['status'] for j in state['jobs']],
                             ['closed']+['stopped_before_start']*3)
            self.assertFalse(state['supervisor_live'])
        finally:
            if process.is_alive(): process.kill(); process.join(10)
            process.close()

    def test_failed_run_and_incompatible_profile_are_not_hidden(self):
        def fail(*args, **kwargs): raise RuntimeError('not for user output')
        result = self.run_case(fail)
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['jobs'][0]['error_type'], 'RuntimeError')
        self.assertNotIn('not for user output', json.dumps(result))

    def test_preflight_checks_all_before_start_and_rejects_path_escape(self):
        harness = Path(self.jobs[-1]['run_directory'])/'private/inputs/harness.json'
        data = json.loads(harness.read_text()); data['topology'] = 'unsupported'; harness.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Claude launch profile'):
            self.run_case(lambda *a, **k: self.fail('model call'))
        self.assertFalse((self.root/'engineering-claim.json').exists())
        batch = json.loads((self.root/'batch.json').read_text()); batch['jobs'][0]['run_directory'] = '/tmp/outside'
        (self.root/'batch.json').write_text(json.dumps(batch))
        with self.assertRaisesRegex(ValueError, 'run directory'): stop_batch(self.root)
        self.assertFalse((self.root/'STOP').exists())

    def test_missing_third_party_credential_or_endpoint_blocks_entire_batch(self):
        launch = Path(self.jobs[-1]['run_directory'])/'private/inputs/claude.json'
        original = json.loads(launch.read_text())
        for key, endpoint, error in ((None, 'https://example.invalid', 'credential'),
                                     ('synthetic', None, 'base URL')):
            with self.subTest(missing=error):
                data = json.loads(json.dumps(original))
                data['profile'].update(provider='third-party', env_key='THIRD_PARTY_KEY', base_url=endpoint)
                launch.write_text(json.dumps(data))
                if key is None: self.env.pop('THIRD_PARTY_KEY', None)
                else: self.env['THIRD_PARTY_KEY'] = key
                with self.assertRaisesRegex(ValueError, error):
                    self.run_case(lambda *a, **k: self.fail('No task should start'))
                self.assertFalse((self.root/'engineering-claim.json').exists())
                self.assertTrue(all(not (Path(j['run_directory'])/'private/state/claude-engineering-claim.json').exists()
                                    for j in self.jobs))

    def test_adaptive_draft_is_admitted_to_unqualified_claude_batch(self):
        for job in self.jobs:
            harness = Path(job['run_directory'])/'private/inputs/harness.json'
            data = json.loads(harness.read_text()); data['topology'] = 'adaptive'
            harness.write_text(json.dumps(data))
        calls=[]
        def runner(run, *args, **kwargs):
            calls.append(run)
            return {'status':'finished', 'reason':'world_ended'}
        result=self.run_case(runner)
        self.assertEqual(result['status'], 'closed')
        self.assertFalse(result['scored'])
        self.assertEqual(len(calls), len(self.jobs))

    def test_stale_running_status_is_not_claimed_to_be_live(self):
        (self.root/'engineering-status.json').write_text(json.dumps({'status': 'running'}))
        (self.root/'engineering-supervisor.lock').touch()
        self.assertEqual(status_batch(self.root)['status'], 'supervisor_lost_needs_review')
        self.assertFalse(status_batch(self.root)['supervisor_live'])

    def test_real_supervisor_process_loss_preserves_claim_and_does_not_replay(self):
        self._assert_supervisor_loss(publish_starting=True)

    def test_supervisor_loss_before_starting_snapshot_preserves_claim(self):
        self._assert_supervisor_loss(publish_starting=False)

    def _assert_supervisor_loss(self, *, publish_starting):
        from unittest.mock import patch
        from robofrontier.runtime.setup import write_json
        ctx = multiprocessing.get_context('fork')
        entered = ctx.Event()
        publication = ctx.Event()
        def runner(run, *args, **kwargs):
            (Path(run)/'private/state/claude-engineering-claim.json').write_text('{}')
            entered.set()
            time.sleep(30)
            return {'status':'finished', 'reason':'world_ended'}
        def publish(path, data):
            starting = data['jobs'][0]['status'] == 'starting'
            if starting and not publish_starting:
                # Hold the actual publication seam, not the worker thread.
                publication.set()
                time.sleep(30)
            write_json(path, data)
            if starting:
                publication.set()
        def supervise():
            with patch('robofrontier.batch.claude_batch.write_json', publish):
                self.run_case(runner, 1)
        process = ctx.Process(target=supervise)
        process.start()
        try:
            self.assertTrue(entered.wait(10), 'Test supervisor did not start its fake job')
            self.assertTrue(publication.wait(10), 'Test did not reach its publication boundary')
            self.assertTrue(status_batch(self.root)['supervisor_live'])
            process.terminate()
            process.join(10)
            self.assertFalse(process.is_alive())
            status = status_batch(self.root)
            self.assertEqual(status['status'], 'supervisor_lost_needs_review')
            self.assertFalse(status['supervisor_live'])
            self.assertTrue((self.root/'engineering-claim.json').exists())
            self.assertEqual(status['jobs'][0]['status'], 'starting' if publish_starting else 'queued')
            self.assertTrue(status['runs'][0]['claim_record_present'])
            self.assertTrue(all(not run['claim_record_present'] for run in status['runs'][1:]))
            self.assertTrue(stop_batch(self.root)['stop_requested'])
            stopped = status_batch(self.root)
            self.assertEqual(stopped['status'], 'supervisor_lost_needs_review')
            self.assertTrue(stopped['stop_requested'])
            self.assertTrue(all(item['stop_requested'] for item in stopped['runs']))
            with self.assertRaisesRegex(ValueError, 'never restart'):
                self.run_case(lambda *a, **k: self.fail('unexpected launch'))
        finally:
            if process.is_alive():
                process.kill()
                process.join(10)
            process.close()

    def test_claim_without_status_needs_review_and_cannot_restart(self):
        (self.root/'engineering-claim.json').write_text('{}')
        self.assertEqual(status_batch(self.root)['status'], 'claim_without_status_needs_review')
        with self.assertRaisesRegex(ValueError, 'never restart'):
            self.run_case(lambda *a, **k: self.fail('unexpected launch'))

    def test_stop_before_launch_is_visible_and_blocks_launch(self):
        self.assertFalse(status_batch(self.root)['stop_requested'])
        stop_batch(self.root)
        self.assertEqual(status_batch(self.root)['status'], 'stopped_before_start')
        self.assertTrue(status_batch(self.root)['stop_requested'])
        with self.assertRaisesRegex(ValueError, 'stopped before launch'):
            self.run_case(lambda *a, **k: self.fail('unexpected launch'))
        self.assertFalse((self.root/'engineering-claim.json').exists())

    def test_review_takes_precedence_over_stop(self):
        entered = threading.Event(); finish = threading.Event(); outcome = []
        def runner(*args, **kwargs):
            entered.set(); finish.wait(3)
            return {'status':'needs_review', 'reason':'owner_unavailable'}
        thread = threading.Thread(target=lambda: outcome.append(self.run_case(runner, parallel=1)))
        thread.start(); self.assertTrue(entered.wait(3))
        stop_batch(self.root); finish.set(); thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome[0]['status'], 'needs_review')
        self.assertEqual(outcome[0]['jobs'][1]['status'], 'stopped_before_start')

    def test_invalid_oauth_endpoint_rejects_entire_batch_before_claim(self):
        launch = Path(self.jobs[-1]['run_directory'])/'private/inputs/claude.json'
        data = json.loads(launch.read_text())
        data['profile'].update(auth_mode='oauth_token', env_key='CLAUDE_CODE_OAUTH_TOKEN',
                               base_url='https://other.example')
        launch.write_text(json.dumps(data))
        self.env['CLAUDE_CODE_OAUTH_TOKEN'] = 'synthetic'
        with self.assertRaisesRegex(ValueError, 'Anthropic endpoint'):
            self.run_case(lambda *a, **k: self.fail('unexpected launch'))
        self.assertFalse((self.root/'engineering-claim.json').exists())


if __name__ == '__main__': unittest.main()
