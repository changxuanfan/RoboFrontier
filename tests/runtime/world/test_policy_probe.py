import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fake_pipeline import FakeWorld, fake_capture
from roboteam.runtime.time.clock import BudgetGuard, protocol, validate_protocol
from roboteam.runtime.world.service import RuntimeService
from team_settings import prepare_run


class BudgetWorld(FakeWorld):
    def __init__(self, *args):
        super().__init__(*args)
        self.arms = {r: SimpleNamespace(job=None, grasp_force=50.0) for r in self.task['arms']}
        self.stops = []
        self.success = False
        self.closed_trial = False

    def start_action(self, actor, call_id, command):
        super().start_action(actor, call_id, command)
        self.arms[actor].job = call_id

    def request_stop(self, robot, ident):
        self.stops.append((robot, ident))

    def complete(self, actor, status='failed'):
        super().complete(actor, status)
        self.arms[actor].job = None

    def evaluate(self):
        return dict(task_success=self.success)

    def end_trial(self):
        self.closed_trial = True


class PolicyProbeTests(unittest.TestCase):
    def test_protocol_rejects_false_readiness_or_bad_clock(self):
        for key, value in [
            ('oracle_readiness_claimed', True),
            ('wall_limit_s', float('nan')),
            ('wall_limit_s', True),
            ('clock', 'sim_time'),
        ]:
            p = protocol()
            p[key] = value
            with self.assertRaises(ValueError):
                validate_protocol(p)

    def fixture(self, root):
        run = Path(root) / 'run'
        prepare_run(run)
        service = RuntimeService(run, BudgetWorld, fake_capture)
        for actor in ('Controller', 'A', 'B', 'C', 'D'):
            service.store.update_agent(actor, ready=True, thread_id=actor)
        service.store.start()
        return run, service

    def test_cutoff_rejects_new_motion_brakes_and_does_not_credit_late_success(self):
        with tempfile.TemporaryDirectory() as root:
            run, s = self.fixture(root)
            try:
                job = s.accept('A', 'move', {'target_m': [0.4, 0, 0.5]}, 'existing')
                s.pump()
                guard = BudgetGuard(protocol(10), stall_s=1e9)
                start = s.store.get('start_at')
                guard.tick(s, start, 100)
                guard.tick(s, start + 10, 110)
                self.assertEqual(s.world.stops, [('A', 'existing')])
                self.assertEqual(s.world.arms['A'].grasp_force, 50.0)
                new = s.accept('B', 'move', {'target_m': [0.4, 0, 0.5]}, 'late')
                s.pump()
                self.assertIn('paused', new['result']['error'])
                self.assertFalse(guard.completed)
                s.world.complete('A')
                s.pump()
                s.world.success = True
                guard.tick(s, start + 10.3, 110.3)
                report = json.loads((run / 'private/outputs/evaluation.json').read_text())
                self.assertFalse(report['task_success'])
                self.assertTrue(report['post_stop_evaluation']['task_success'])
                self.assertEqual(job['result']['execution']['status'], 'failed')
                self.assertEqual(s.store.get('lifecycle'), 'ended')
            finally:
                s.close()

    def test_budget_is_inert_before_start_and_after_early_finish(self):
        with tempfile.TemporaryDirectory() as root:
            run, s = self.fixture(root)
            try:
                start = s.store.get('start_at')
                guard = BudgetGuard(protocol(600))
                s.store.put('lifecycle', 'prepared')
                guard.tick(s, start + 86400, 86400)
                self.assertIsNone(guard.cutoff)
                s.store.put('lifecycle', 'ended')
                guard.tick(s, start + 86401, 86401)
                self.assertIsNone(guard.cutoff)
                self.assertFalse((run / 'private/outputs/budget-cutoff.json').exists())
            finally:
                s.close()

    def test_unsettled_stop_is_saved_as_unknown_without_motion_replay(self):
        with tempfile.TemporaryDirectory() as root:
            run, s = self.fixture(root)
            try:
                s.accept('A', 'move', {'target_m': [0.4, 0, 0.5]}, 'existing')
                s.pump()
                guard = BudgetGuard(protocol(1), grace_s=2)
                start = s.store.get('start_at')
                guard.tick(s, start, 0)
                guard.tick(s, start + 1, 1)
                guard.tick(s, start + 3, 3)
                self.assertEqual(s.store.actions()['existing']['status'], 'uncertain')
                self.assertEqual(len(s.world.executed), 1)
                self.assertTrue(s.shutdown)
                report = json.loads((run / 'private/outputs/evaluation.json').read_text())
                self.assertEqual(report['unresolved_action_ids'], ['existing'])
                self.assertFalse(report['task_success'])
            finally:
                s.close()
