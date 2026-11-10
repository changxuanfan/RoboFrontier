"""Active-time runs stop after 48 h of wall time if the 24 h active-time cutoff has not fired.

Such a run is recorded as wall_backstop, needs review, is excluded from analysis and continues
only on an operator's explicit authorization. Runs frozen without the field are unchanged."""
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from robofrontier.runtime import segments as run_segments
from robofrontier.tasks import families as task_families
from robofrontier.runtime.egress_pause import WorldPause
from robofrontier.runtime.outage import OutageMonitor
from robofrontier.runtime.clock import BudgetGuard, backstop_since, protocol, wall_backstop_s
from robofrontier.analysis import extract, metrics
from robofrontier.runtime.service import RuntimeService
from fake_pipeline import fake_capture
from runtime import test_active_time as active
from batch import test_claude_engineering_batch as engineering_batch
from runtime.test_policy_probe import BudgetWorld

ACTIVE = active.ACTIVE
DAY = 86400
BACKSTOP = 2 * DAY


class ProtocolTests(unittest.TestCase):
    def test_new_runs_freeze_a_48h_backstop_and_frozen_runs_have_none(self):
        new = task_families.policy_task('transport-a04-d1')
        self.assertEqual(new['run_protocol']['wall_backstop_s'], BACKSTOP)
        task_families.validate_policy_task(new)
        self.assertEqual(wall_backstop_s(new['run_protocol']), BACKSTOP)
        before = dict(new, run_protocol={k: v for k, v in new['run_protocol'].items() if k != 'wall_backstop_s'})
        task_families.validate_policy_task(before)
        self.assertIsNone(wall_backstop_s(before['run_protocol']))
        old = dict(new, run_protocol={k: v for k, v in new['run_protocol'].items() if k not in ('clock', 'wall_backstop_s')})
        task_families.validate_policy_task(old)
        self.assertIsNone(wall_backstop_s(old['run_protocol']))
        self.assertIsNone(wall_backstop_s({'wall_backstop_s': BACKSTOP}))  # no active clock, no backstop
        with self.assertRaises(ValueError):
            task_families.validate_policy_task(dict(new, run_protocol=dict(new['run_protocol'], wall_backstop_s=60)))
        from robofrontier.tasks.v2 import public_task
        self.assertNotIn('wall_backstop_s', public_task(new)['run_protocol'])

    def test_the_world_owner_reads_the_frozen_backstop(self):
        with tempfile.TemporaryDirectory() as tmp:
            for prepare, expected in ((task_families.prepare, BACKSTOP), (active.old_protocol_prepare, None)):
                run = prepare('transport-a04-d1', Path(tmp)/prepare.__name__)
                s = RuntimeService(run, BudgetWorld, fake_capture)
                try: self.assertEqual(s.policy_budget.wall_backstop_s, expected)
                finally: s.close()


class GuardTests(active.Fixture):
    def guard(self, limit=DAY, clock=ACTIVE):
        return BudgetGuard(protocol(limit, clock), wall_backstop_s=BACKSTOP)

    def json(self, name):
        return json.loads((self.run/'private/outputs'/name).read_text())

    def test_fires_at_48h_of_wall_time_with_little_active_time(self):
        guard = self.guard()
        self.ticks(guard, [0, 1, 2], wall=self.start + 100)
        self.ticks(guard, [3], wall=self.start + BACKSTOP - 1); self.assertIsNone(guard.cutoff)
        self.ticks(guard, [4], wall=self.start + BACKSTOP)
        self.assertTrue(guard.backstopped); self.assertLess(guard.active, 10)
        self.assertEqual(self.events('POLICY_WALL_LIMIT'), [])
        event = self.events('POLICY_WALL_BACKSTOP')[0]
        self.assertEqual((event['wall_backstop_s'], event['wall_since_start_s']), (BACKSTOP, BACKSTOP))
        cutoff = self.json('budget-cutoff.json')
        self.assertEqual((cutoff['wall_backstop'], cutoff['needs_review']), (True, True))
        self.assertTrue(self.s.store.get('dispatch_paused'))
        self.ticks(guard, [4.1], wall=self.start + BACKSTOP)
        self.assertTrue(guard.completed)
        report = self.json('evaluation.json')
        self.assertEqual((report['termination_reason'], report['wall_backstop'], report['needs_review'],
                          report['budget_exhausted']), ('wall_backstop', True, True, False))
        self.assertEqual(self.s.store.get('termination_reason'), 'wall_backstop')
        self.assertEqual(self.s.store.get('lifecycle'), 'ended')
        self.assertEqual(len(self.events('POLICY_BACKSTOP_CLOSED')), 1); self.assertEqual(self.events('POLICY_BUDGET_CLOSED'), [])
        self.assertTrue(run_segments.wall_backstopped(self.run))

    def test_does_not_fire_once_the_active_time_cutoff_fired(self):
        guard = self.guard(limit=10)
        self.ticks(guard, range(11), wall=self.start + 100); self.assertIsNotNone(guard.cutoff)
        self.ticks(guard, [10.05], wall=self.start + 3 * DAY)
        self.assertFalse(guard.backstopped); self.assertEqual(self.events('POLICY_WALL_BACKSTOP'), [])
        self.assertNotIn('wall_backstop', self.json('budget-cutoff.json'))
        self.ticks(guard, [10.2], wall=self.start + 3 * DAY)
        self.assertEqual(self.json('evaluation.json')['termination_reason'], 'wall_limit')
        self.assertFalse(run_segments.wall_backstopped(self.run))

    def test_frozen_wall_clock_runs_never_backstop(self):
        guard = self.guard(clock='START_wall_time')
        self.assertIsNone(guard.wall_backstop_s)
        self.ticks(guard, [0, 1], wall=self.start + 3 * DAY)
        # Their own START wall-time deadline ends them, as before.
        self.assertFalse(guard.backstopped); self.assertEqual(self.events('POLICY_WALL_BACKSTOP'), [])
        self.assertEqual(self.json('evaluation.json')['termination_reason'], 'wall_limit')
        self.assertNotIn('wall_backstop', self.json('budget-cutoff.json'))

    def test_counts_from_an_authorized_continuation(self):
        guard = self.guard()
        self.s.store.put('wall_backstop_waived', {'at': self.start + BACKSTOP + 50})
        self.assertEqual(backstop_since(self.s.store), self.start + BACKSTOP + 50)
        self.ticks(guard, [0, 1], wall=self.start + BACKSTOP + 100); self.assertIsNone(guard.cutoff)
        self.ticks(guard, [2], wall=self.start + 2 * BACKSTOP + 50); self.assertTrue(guard.backstopped)


class PausedWorldTests(active.Fixture):
    """The backstop ends even a world held by a network-outage pause that never resumes."""
    def setUp(self):
        super().setUp()
        self.answers = []
        self.monitor = OutageMonitor(('api.example',), lambda hosts: self.answers.pop(0))
        self.s.egress_pause = WorldPause(self.s, self.monitor)
        self.s.policy_budget = BudgetGuard(protocol(DAY, ACTIVE), wall_backstop_s=BACKSTOP)
        self.s.store.put('physics_state', 'running')

    def test_a_held_world_is_stopped_and_closed(self):
        self.answers.extend([True, False, False, False])
        for _ in range(4): self.monitor.step()
        self.s.pump(); self.assertEqual(self.s.store.get('physics_state'), 'paused_by_egress')
        self.s.pump(); self.assertEqual(self.events('POLICY_WALL_BACKSTOP'), [])
        self.s.store.put('start_at', time.time() - BACKSTOP)
        self.s.pump()  # read at most once a second while held
        self.assertEqual(self.events('POLICY_WALL_BACKSTOP'), [])
        self.s.policy_budget.backstop_checked -= 1.
        self.s.pump()
        self.assertEqual(len(self.events('OUTAGE_PAUSE_CLOSED')), 1)
        self.assertEqual(len(self.events('POLICY_WALL_BACKSTOP')), 1)
        self.assertEqual(self.s.store.get('termination_reason'), 'wall_backstop')
        self.assertTrue(self.s.shutdown)
        # The still-failing probe never pauses the ending world again.
        self.assertFalse(self.s.egress_pause.sync())


class SupervisorTests(unittest.TestCase):
    supervisor = active.SupervisorActiveTimeTests.supervisor
    running = active.SupervisorActiveTimeTests.running

    def test_a_world_held_past_the_backstop_is_ended_by_the_host(self):
        from robofrontier.engines.claude.supervisor import ACTIVE_CLOSE_WAIT_S
        p = self.running(dispatch_paused=True, physics_state='paused_by_egress', active_s=10.)
        result = self.supervisor(p, lambda: None, time_rule=ACTIVE, wall_backstop_s=100).run()
        self.assertEqual((result['reason'], result['wall_backstop']), ('wall_backstop', True))
        self.assertEqual(self.now, 100 + ACTIVE_CLOSE_WAIT_S + 30)

    def test_the_worlds_backstop_end_is_reported_as_such(self):
        p = self.running(active_s=10.)
        def tick():
            if self.now == 5: p.store.data.update(wall_backstop={'at': 5}, dispatch_paused=True)
            if self.now == 8: p.store.data['lifecycle'] = 'ended'; p.host.state = 'idle'
        result = self.supervisor(p, tick, time_rule=ACTIVE, wall_backstop_s=100).run()
        self.assertEqual((result['reason'], result['ended_by'], result['wall_backstop']),
                         ('world_ended', 'wall_backstop', True))

    def test_not_after_the_active_time_cutoff_fired(self):
        from robofrontier.engines.claude.supervisor import CentralizedSupervisor
        p = self.running(); p.store.data.update(lifecycle='running', start_at=0)
        supervisor = CentralizedSupervisor(p, lambda: True, time_rule=ACTIVE, wall_backstop_s=100,
                                           wall_clock=lambda: 10_000)
        self.assertTrue(supervisor._backstop_overdue())
        supervisor._wall_limit_reached = lambda: True
        self.assertFalse(supervisor._backstop_overdue())

    def test_frozen_wall_clock_runs_ignore_the_backstop(self):
        p = self.running()
        result = self.supervisor(p, lambda: None, wall_backstop_s=1).run()
        self.assertEqual((result['reason'], result['wall_backstop']), ('wall_limit', False))


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.run = task_families.prepare('transport-a04-d1', Path(self.tmp.name)/'run')
        from robofrontier.runtime.store import RuntimeStore
        self.store = RuntimeStore(self.run/'private/state/runtime.sqlite'); self.addCleanup(self.store.close)
        self.store.put('lifecycle', 'ended'); self.store.put('start_at', time.time() - BACKSTOP)
        self.store.put('wall_backstop', {'at': time.time(), 'segment': 0})
        outputs = self.run/'private/outputs'; outputs.mkdir(parents=True, exist_ok=True)
        (outputs/'budget-cutoff.json').write_text(json.dumps({'cutoff_unix_s': 1., 'wall_backstop': True}))
        (outputs/'evaluation.json').write_text(json.dumps({'termination_reason': 'wall_backstop'}))

    def test_refused_without_an_operator_authorization(self):
        self.assertEqual(run_segments.retry_eligibility(self.run, self.store), (False, run_segments.BACKSTOP_REFUSAL))
        with self.assertRaisesRegex(ValueError, 'wall-time backstop'):
            run_segments.prepare_retry(self.run, self.store, 'operator')
        # An authorization is checked by the existing stopped-runtime path, not waved through.
        ok, why = run_segments.retry_eligibility(self.run, self.store,
                                                 manual_authorization='private/inputs/runtime-upgrades/1/authorization.json')
        self.assertFalse(ok); self.assertNotEqual(why, run_segments.BACKSTOP_REFUSAL)

    def test_a_backstop_end_is_a_stopped_segment_for_the_upgrade_path(self):
        from robofrontier.runtime import upgrade as runtime_upgrade
        self.store.put('physics_state', 'finished'); self.store.put('dispatch_paused', True)
        self.store.put('integrity_valid', True)
        # It gets past the lifecycle gate to the next check (the released world lock here).
        with self.assertRaisesRegex(Exception, '(?i)process still owns|seal'):
            runtime_upgrade.stopped(self.run, self.store)
        self.store.put('wall_backstop', None)
        with self.assertRaisesRegex(ValueError, 'fully stopped'):
            runtime_upgrade.stopped(self.run, self.store)

    def test_an_authorized_continuation_sets_the_backstop_records_aside(self):
        run_segments._waive_backstop(self.run, self.store, 'grant')
        outputs = self.run/'private/outputs'
        self.assertFalse((outputs/'budget-cutoff.json').exists())
        self.assertTrue((outputs/'budget-cutoff-wall-backstop-0.json').exists())
        self.assertTrue((outputs/'evaluation-wall-backstop-0.json').exists())
        self.assertIsNone(self.store.get('wall_backstop'))
        self.assertEqual(self.store.get('wall_backstop_waived')['authorization'], 'grant')
        self.assertFalse(run_segments.wall_backstopped(self.run))


class FakeRun:
    def __init__(self, files): self.files = files
    def find(self, *names): return next((n for n in names if n in self.files), None)
    def read(self, name): return self.files[name]


class AnalysisTests(unittest.TestCase):
    def test_a_backstopped_run_is_excluded_with_its_reason(self):
        cutoff = extract.trial_cutoff(FakeRun({'private/outputs/budget-cutoff.json': json.dumps(
            {'cutoff_unix_s': 5., 'sim_time_s': 1., 'wall_backstop': True, 'evaluation': {'task_success': True}})}), None)
        self.assertTrue(cutoff['wall_backstop'])
        self.assertEqual(metrics.excluded({'cutoff': cutoff}), 'wall_backstop')
        self.assertEqual(metrics.excluded({'evaluation.json': {'wall_backstop': True}}), 'wall_backstop')
        normal = extract.trial_cutoff(FakeRun({'private/outputs/budget-cutoff.json': json.dumps(
            {'cutoff_unix_s': 5., 'sim_time_s': 1.})}), None)
        self.assertIsNone(metrics.excluded({'cutoff': normal, 'evaluation.json': {'termination_reason': 'wall_limit'}}))

    def test_compute_marks_the_run(self):
        d = {'sel': {'id': 'r', 'family': 'transport'}, 'kind': 'dir', 'cutoff': {'unix': 5., 'sim': 1., 'wall_backstop': True}}
        row = metrics.compute(d)
        self.assertEqual((row['excluded'], row['needs_review']), ('wall_backstop', True))

    def test_the_event_fallback_reads_an_unwaived_backstop(self):
        db = sqlite3.connect(':memory:')
        db.execute('create table events (seq integer primary key, created real, kind text, value text)')
        db.execute("insert into events (created, kind, value) values (7, 'POLICY_WALL_BACKSTOP', '{\"sim_time_s\": 2}')")
        cut = extract.trial_cutoff_event(db)
        self.assertEqual((cut['unix'], cut['sim'], cut['wall_backstop']), (7., 2., True))
        db.execute("insert into events (created, kind, value) values (8, 'WALL_BACKSTOP_WAIVED', '{}')")
        self.assertIsNone(extract.trial_cutoff_event(db))


class BatchSummaryTests(unittest.TestCase):
    setUp = engineering_batch.BatchTests.setUp
    tearDown = engineering_batch.BatchTests.tearDown
    run_case = engineering_batch.BatchTests.run_case

    def test_the_batch_marks_a_backstopped_run(self):
        def runner(run_dir, *args, **kwargs):
            if run_dir.endswith('case1'):
                return {'status': 'needs_review', 'reason': 'world_ended', 'wall_backstop': True}
            return {'status': 'finished', 'reason': 'world_ended'}
        state = self.run_case(runner)
        self.assertEqual(state['status'], 'needs_review')
        self.assertEqual([(j['status'], j['reason']) for j in state['jobs']],
                         [('closed', 'world_ended'), ('needs_review', 'wall_backstop'),
                          ('closed', 'world_ended'), ('closed', 'world_ended')])


class CodexBatchSummaryTests(unittest.TestCase):
    def test_the_codex_batch_marks_a_backstopped_run(self):
        import hashlib, os
        from types import SimpleNamespace
        from unittest.mock import patch
        from robofrontier.runtime import preflight_probe
        from robofrontier.batch import codex_batch as benchmark
        from robofrontier.runtime.setup import write_json
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); batch = root/'batch'
            selected = {'provider': 'openai_api', 'env_key': 'RF_TEST_KEY'}
            jobs = []
            for case, backstopped in (('one', True), ('two', False)):
                run = batch/'luna'/case
                write_json(run/'private/inputs/codex.json', {'profile': selected, 'args': []})
                write_json(run/'private/inputs/models.json', {'models': []})
                write_json(run/'private/outputs/budget-cutoff.json', {'cutoff_unix_s': 1., **({'wall_backstop': True} if backstopped else {})})
                jobs.append({'profile': 'luna', 'case_id': case, 'run_directory': str(run), 'status': 'prepared'})
            catalog = (Path(jobs[0]['run_directory'])/'private/inputs/models.json').read_bytes()
            write_json(root/'runs/engineering/model-compatibility/luna/report.json', {
                'passed': True, 'profile_sha256': hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest(),
                'catalog_sha256': hashlib.sha256(catalog).hexdigest(), 'codex_version': 'test-cli',
                'probe_version': preflight_probe.VERSION})
            write_json(batch/'batch.json', {'status': 'prepared_not_started', 'jobs': jobs,
                'execution': {'codex_home_scope': 'task', 'startup_interval_s': 0}})
            with patch.object(benchmark, 'ROOT', root), patch.object(benchmark, 'verify_inputs', return_value=[]), \
                    patch.object(benchmark, 'initialize_codex_home'), \
                    patch.object(benchmark.subprocess, 'check_output', return_value='test-cli'), \
                    patch.object(benchmark.subprocess, 'run'), \
                    patch.object(benchmark.subprocess, 'Popen', return_value=SimpleNamespace(pid=99999, wait=lambda: 0)), \
                    patch.object(benchmark, 'try_continue', return_value=(False, run_segments.BACKSTOP_REFUSAL)), \
                    patch.dict(os.environ, {'RF_TEST_KEY': 'never-persist-this'}):
                benchmark.run_batch(batch, 1)
            state = json.loads((batch/'batch.json').read_text())
            self.assertEqual([(j['status'], j.get('reason')) for j in state['jobs']],
                             [('needs_review', 'wall_backstop'), ('closed', None)])
            self.assertEqual(state['status'], 'needs_review')


if __name__ == '__main__':
    unittest.main()
