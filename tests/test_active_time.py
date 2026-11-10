"""The 24 h limit counts active running time for new runs; frozen runs keep START wall time."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fake_pipeline import fake_capture
from robofrontier import run_segments, task_families
from robofrontier.policy_probe import BudgetGuard, protocol
from robofrontier.run_setup import prepare_run
from robofrontier.runtime_service import RuntimeService
from test_claude_supervisor import Dispatcher, Policy
from test_policy_probe import BudgetWorld

ACTIVE = 'active_time_v1'


class StepWorld(BudgetWorld):
    def step(self): self.time += .02


def old_protocol_prepare(*args, **kwargs):
    """Prepare a run exactly as before the active-time clock: its protocol has no clock."""
    original = task_families.protocol_for
    def without_clock(*a, **k):
        value = original(*a, **k); value.pop('clock'); return value
    with patch.object(task_families, 'protocol_for', without_clock):
        return task_families.prepare(*args, **kwargs)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name).resolve()/'run'; prepare_run(self.run)
        self.s = RuntimeService(self.run, StepWorld, fake_capture); self.addCleanup(self.s.close)
        for actor in ('Controller', 'A', 'B', 'C', 'D'):
            self.s.store.update_agent(actor, ready=True, thread_id=actor)
        self.s.store.start(); self.start = self.s.store.get('start_at')

    def events(self, kind):
        return [json.loads(v) for (v,) in self.s.store.db.execute('SELECT value FROM events WHERE kind=?', (kind,))]

    def ticks(self, guard, monos, wall=None):
        for mono in monos: guard.tick(self.s, self.start if wall is None else wall, mono)


class WallClockGoldenTests(Fixture):
    def test_frozen_run_keeps_the_start_wall_time_deadline_and_records(self):
        self.s.store.put('downtime_s', 100.)
        guard = BudgetGuard(protocol(600))
        guard.tick(self.s, self.start + 50, 1000)
        self.assertEqual(guard.deadline, 1000 + 600 + 100 - 50)
        guard.tick(self.s, self.start + 50, 1649.9); self.assertIsNone(guard.cutoff)
        # A 30 s stall still counts on the wall clock.
        guard.tick(self.s, self.start + 50, 1650); self.assertEqual(guard.cutoff, 1650)
        cutoff = json.loads((self.run/'private/outputs/budget-cutoff.json').read_text())
        self.assertEqual(list(cutoff), ['protocol', 'cutoff_unix_s', 'sim_time_s', 'evaluation'])
        self.assertEqual(cutoff['protocol']['clock'], 'START_wall_time')
        self.assertEqual(self.events('POLICY_WALL_LIMIT'), [{'wall_limit_s': 600, 'sim_time_s': 0.}])
        report = json.loads((self.run/'private/outputs/evaluation.json').read_text())
        self.assertNotIn('budget_active_s', report); self.assertIsNone(self.s.store.get('active_s'))

    def test_a_restarted_owner_after_sleep_counts_the_sleep_on_the_wall_clock(self):
        guard = BudgetGuard(protocol(600))
        guard.tick(self.s, self.start + 10_000, 500)
        self.assertTrue(guard.completed)


class ActiveTimeTests(Fixture):
    def guard(self, limit=600, **kwargs):
        return BudgetGuard(protocol(limit, ACTIVE), **kwargs)

    def test_a_stall_without_ticks_adds_nothing(self):
        guard = self.guard()
        self.ticks(guard, [0, 1, 2])
        self.assertEqual(guard.active, 2)
        self.ticks(guard, [32])
        self.assertEqual(guard.active, 2)
        self.assertEqual(self.events('ACTIVE_TIME_STALL')[0]['gap_s'], 30)
        self.ticks(guard, [33]); self.assertEqual(guard.active, 3)

    def test_a_pause_adds_nothing(self):
        guard = self.guard(); self.ticks(guard, [0, 1]); t = 1
        for key, value in (('dispatch_paused', True), ('physics_state', 'paused_by_egress'),
                           ('physics_state', 'paused_by_user'), ('egress_review_hold', True)):
            with self.subTest(key=key, value=value):
                before = guard.active; prior = self.s.store.get(key)
                self.s.store.put(key, value); self.ticks(guard, [t+1, t+2, t+3])
                self.s.store.put(key, prior); self.ticks(guard, [t+4])
                self.assertEqual(guard.active, before)
                self.ticks(guard, [t+5]); self.assertEqual(guard.active, before + 1)
                t += 5

    def test_a_restarted_owner_after_sleep_does_not_recount(self):
        first = self.guard(persist_s=1.); self.ticks(first, range(11))
        self.assertEqual(self.s.store.get('active_s'), 10)
        # The machine slept for hours; the new owner starts from the saved active time.
        replacement = self.guard()
        self.ticks(replacement, [500, 501], wall=self.start + 10_000)
        self.assertFalse(replacement.completed); self.assertIsNone(replacement.cutoff)
        self.assertEqual(replacement.active, 11)

    def test_cutoff_fires_exactly_at_the_active_limit(self):
        guard = self.guard(10)
        self.ticks(guard, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9.5]); self.assertIsNone(guard.cutoff)
        self.ticks(guard, [10]); self.assertEqual(guard.cutoff, 10)
        self.assertTrue(self.s.store.get('dispatch_paused'))
        cutoff = json.loads((self.run/'private/outputs/budget-cutoff.json').read_text())
        self.assertEqual((cutoff['active_s'], cutoff['protocol']['clock']), (10, ACTIVE))
        self.assertEqual(self.events('POLICY_WALL_LIMIT')[0]['active_s'], 10)
        self.ticks(guard, [10.2]); self.assertTrue(guard.completed)
        report = json.loads((self.run/'private/outputs/evaluation.json').read_text())
        self.assertEqual((report['budget_active_s'], report['budget_clock']), (10, ACTIVE))
        self.assertEqual(self.s.store.get('active_s'), 10)

    def test_close_saves_the_last_second(self):
        guard = self.guard(persist_s=60.); self.s.policy_budget = guard
        self.ticks(guard, [0, .5]); self.assertIsNone(self.s.store.get('active_s'))
        path = self.s.store.path; self.s.close()
        from robofrontier.runtime_store import RuntimeStore
        store = RuntimeStore(path)
        try: self.assertEqual(store.get('active_s'), .5)
        finally: store.close()

    def test_retract_takes_back_only_counted_time(self):
        guard = self.guard(); self.ticks(guard, range(21))
        self.assertEqual(guard.retract(self.s, 5), 5); self.assertEqual(self.s.store.get('active_s'), 15)
        self.assertEqual(guard.retract(self.s, 100), 15); self.assertEqual(guard.active, 0)


class SupervisorActiveTimeTests(unittest.TestCase):
    def supervisor(self, policy, sleep, **kwargs):
        from robofrontier.claude.supervisor import CentralizedSupervisor
        self.now = 0
        def tick(seconds): self.now += seconds; sleep()
        policy.now = lambda: self.now
        return CentralizedSupervisor(policy, lambda: True, clock=lambda: self.now, wall_clock=lambda: self.now, sleep=tick,
                                     poll_s=1, startup_timeout_s=3, wall_limit_s=4, **kwargs)

    def running(self, **data):
        p = Policy()
        def bind():
            p.dispatcher = Dispatcher(); p.host.state = 'active'
            p.store.data.update(lifecycle='running', start_at=0, **data)
        p.bind_and_bootstrap = bind
        return p

    def test_wall_time_past_the_limit_does_not_end_an_active_time_run(self):
        p = self.running(active_s=0.)
        def tick():
            if self.now >= 20: p.store.data['active_s'] = 4 + 60
        result = self.supervisor(p, tick, time_rule=ACTIVE).run()
        self.assertEqual((result['reason'], self.now), ('wall_limit', 20))
        self.assertEqual(self.supervisor(self.running(), lambda: None).run()['reason'], 'wall_limit')
        self.assertEqual(self.now, 4)


class ProtocolAndEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_new_runs_freeze_the_active_clock_and_old_ones_still_validate(self):
        new = task_families.policy_task('transport-a04-d1')
        self.assertEqual(new['run_protocol']['clock'], ACTIVE)
        task_families.validate_policy_task(new)
        old = dict(new, run_protocol={k: v for k, v in new['run_protocol'].items() if k != 'clock'})
        task_families.validate_policy_task(old)
        with self.assertRaises(ValueError):
            task_families.validate_policy_task(dict(new, run_protocol=dict(new['run_protocol'], clock='START_wall_time')))
        from robofrontier.suite.v2 import public_task
        self.assertNotIn('clock', public_task(new)['run_protocol'])

    def store(self, run):
        from robofrontier.runtime_store import RuntimeStore
        store = RuntimeStore(run/'private/state/runtime.sqlite'); self.addCleanup(store.close)
        store.put('lifecycle', 'running'); return store

    def test_continuation_needs_remaining_active_time(self):
        run = task_families.prepare('transport-a04-d1', self.root/'new'); store = self.store(run)
        # Twice the limit has passed on the wall clock, but little of it was active.
        store.put('start_at', time.time() - 2*86400); store.put('active_s', 600.)
        self.assertEqual(run_segments.retry_eligibility(run, store)[1], 'no recorded motion frame')
        self.assertEqual(run_segments.remaining_s(run, store), 86400 - 600)
        store.put('active_s', 86400 - run_segments.MIN_REMAINING_S / 2)
        self.assertIn('of the wall limit left', run_segments.retry_eligibility(run, store)[1])

    def test_frozen_run_continuation_keeps_the_wall_formula(self):
        run = old_protocol_prepare('transport-a04-d1', self.root/'old'); store = self.store(run)
        self.assertNotIn('clock', json.loads((run/'private/inputs/task.json').read_text())['run_protocol'])
        store.put('start_at', 1000.); store.put('downtime_s', 25.); store.put('active_s', 5.)
        self.assertEqual(run_segments.used_s(run, store, ended_at=1600.), 575.)
        store.put('start_at', time.time() - 86400 + run_segments.MIN_REMAINING_S / 2)
        self.assertIn('of the wall limit left', run_segments.retry_eligibility(run, store)[1])


if __name__ == '__main__':
    unittest.main()
