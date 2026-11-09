"""A local run's world pauses while its model API is unreachable; no real network is used."""
import os
import time
import unittest
from unittest.mock import patch

from robofrontier import network_outage
from robofrontier.egress_pause import WorldPause
from robofrontier.network_outage import OutageMonitor, monitor_for
from robofrontier.policy_probe import BudgetGuard, protocol
import test_active_time as active

ACTIVE = active.ACTIVE


class OutageMonitorTests(unittest.TestCase):
    def test_pauses_after_three_failures_and_resumes_after_one_success(self):
        answers = iter([True, False, False, False, True])
        monitor = OutageMonitor(('api.example',), lambda hosts: next(answers), clock=lambda: 7.)
        self.assertEqual([monitor.step() for _ in range(5)], [False, False, False, True, False])

    def test_a_probe_that_never_succeeded_never_pauses(self):
        monitor = OutageMonitor(('api.example',), lambda hosts: False, unarmed_give_up=4)
        self.assertFalse(any(monitor.step() for _ in range(4)))
        self.assertTrue(monitor.unavailable)
        self.assertEqual(monitor.take_notes()[0][0], 'OUTAGE_PROBE_UNAVAILABLE')

    def test_a_hung_or_raising_probe_counts_as_failed(self):
        def hang(hosts): time.sleep(5); return True
        monitor = OutageMonitor(('api.example',), hang, timeout_s=.05); monitor.armed = True
        self.assertFalse(monitor.step()); self.assertEqual(monitor.failures, 1)
        monitor.probe = lambda hosts: 1/0; monitor.step()
        self.assertEqual(monitor.failures, 2)

    def test_only_local_active_time_policy_runs_probe_their_engine_hosts(self):
        task = {'execution_readiness': 'prepared_policy_trial', 'run_protocol': {'clock': ACTIVE}}
        with patch.dict(os.environ, {network_outage.SWITCH: 'on'}):
            os.environ.pop('SLURM_JOB_ID', None); os.environ.pop('ROBOFRONTIER_EGRESS_PAUSE_FILE', None)
            self.assertEqual(monitor_for(task, {'engine': 'claude'}).hosts, ('api.anthropic.com',))
            self.assertEqual(monitor_for(task, {'engine': 'codex'}).hosts, ('chatgpt.com', 'auth.openai.com'))
            self.assertIsNone(monitor_for({**task, 'run_protocol': {}}, {'engine': 'codex'}))
            with patch.dict(os.environ, {'SLURM_JOB_ID': '1'}): self.assertIsNone(monitor_for(task, {'engine': 'codex'}))
        with patch.dict(os.environ, {network_outage.SWITCH: 'off'}):
            self.assertIsNone(monitor_for(task, {'engine': 'codex'}))


class OutagePauseTests(active.Fixture):
    def setUp(self):
        super().setUp()
        self.answers = []
        self.monitor = OutageMonitor(('api.example',), lambda hosts: self.answers.pop(0))
        self.s.egress_pause = WorldPause(self.s, self.monitor)
        self.s.policy_budget = BudgetGuard(protocol(600, ACTIVE))
        self.s.store.put('physics_state', 'running')

    def probe(self, *answers):
        self.answers.extend(answers)
        for _ in answers: self.monitor.step()
        self.s.pump()

    def test_pause_after_three_failed_probes_then_resume_without_replay(self):
        first = self.s.accept('A', 'move', {'target_m': [.4, 0, .5]}, 'before'); self.s.pump()
        self.probe(True, False, False)
        self.assertTrue(self.s.step_physics()); self.assertEqual(self.events('OUTAGE_PAUSED'), [])
        self.probe(False)
        self.assertEqual(self.s.store.get('physics_state'), 'paused_by_egress')
        self.assertFalse(self.s.step_physics())
        paused = self.events('OUTAGE_PAUSED')[0]
        self.assertEqual((paused['claim'], paused['failed_probes']), ('outage-1', 3))
        held = self.s.accept('B', 'move', {'target_m': [.4, 0, .5]}, 'during'); self.s.pump()
        self.assertFalse(held['done'].is_set()); self.assertEqual(len(self.s.world.executed), 1)
        active = self.s.policy_budget.active
        self.s.pump(); self.assertEqual(self.s.policy_budget.active, active)
        self.probe(True)
        self.assertEqual(self.events('OUTAGE_RESUMED')[0]['claim'], 'outage-1')
        self.assertEqual(self.s.store.get('physics_state'), 'running'); self.assertTrue(self.s.step_physics())
        self.assertEqual([x[1] for x in self.s.world.executed], ['before', 'during'])
        self.assertEqual(self.s.store.get('egress_recovery')['claim'], 'outage-1')
        self.assertFalse(first['done'].is_set())

    def test_failed_probes_before_the_pause_are_taken_back(self):
        guard = self.s.policy_budget; self.ticks(guard, range(31))
        clock = [100.]; self.monitor.clock = lambda: clock[0]
        self.answers.extend([True, False, False, False])
        self.monitor.step(); self.monitor.step(); clock[0] = 110.; self.monitor.step(); self.monitor.step()
        clock[0] = 112.; self.s.pump()
        # The first failed probe began at 100; the pause at 112 takes back those 12 s.
        self.assertEqual(self.events('OUTAGE_PAUSED')[0]['retracted_active_s'], 12.)
        self.assertEqual(self.s.store.get('active_s'), 18)

    def test_operator_pause_survives_the_outage(self):
        self.probe(True, False, False, False)
        self.s.store.put('dispatch_paused', True); self.s.store.event('DISPATCH_PAUSED', 'Meta', {'reason': 'operator'})
        self.probe(True)
        self.assertEqual(self.events('OUTAGE_HELD_FOR_REVIEW')[0]['claim'], 'outage-1')
        self.assertTrue(self.s.store.get('dispatch_paused'))

    def test_no_pause_before_start_or_after_the_cutoff(self):
        self.s.store.put('physics_state', 'paused_by_user')  # the budget cutoff's state
        self.probe(True, False, False, False)
        self.assertEqual(self.events('OUTAGE_PAUSED'), [])


class SupervisorOutageTests(unittest.TestCase):
    supervisor = active.SupervisorActiveTimeTests.supervisor
    running = active.SupervisorActiveTimeTests.running

    def test_an_outage_pause_is_waited_out_not_sealed(self):
        p = self.running(dispatch_paused=True, physics_state='paused_by_egress')
        def tick():
            if self.now == 10: p.store.data.update(dispatch_paused=False, physics_state='running')
            if self.now == 12: p.store.data['lifecycle'] = 'ended'; p.host.state = 'idle'
        result = self.supervisor(p, tick, time_rule=ACTIVE).run()
        self.assertEqual(result['reason'], 'world_ended'); self.assertGreater(p.cycles, 0)


if __name__ == '__main__':
    unittest.main()
