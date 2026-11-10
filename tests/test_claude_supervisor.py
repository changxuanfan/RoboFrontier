import unittest
from unittest.mock import patch

from robofrontier.engines.claude.supervisor import CentralizedSupervisor


class Store:
    def __init__(self): self.data = {'lifecycle': 'prepared', 'dispatch_paused': False}; self.ready = False
    def get(self, key, default=None): return self.data.get(key, default)
    def agent(self, actor): return {'ready': self.ready}


class Host:
    def __init__(self): self.state = 'new'; self.stopped = False
    def observe(self): return {'status': self.state}
    def wait(self, timeout=None): return self.observe()


class Dispatcher:
    def __init__(self): self.calls = []
    def admin(self, op, data): self.calls.append((op, data)); return {'sealed': True}


class Policy:
    def __init__(self):
        self.store = Store(); self.host = Host(); self.dispatcher = None; self.binds = 0; self.cycles = 0
    def bind_and_bootstrap(self):
        self.binds += 1; self.dispatcher = Dispatcher(); self.host.state = 'active'
    def start_when_ready(self): self.store.data.update(lifecycle='running', start_at=self.now())
    def cycle(self): self.cycles += 1; return {'paused': False}
    def stop(self): self.host.stopped = True; self.host.state = 'unknown'


class SupervisorTests(unittest.TestCase):
    def test_normal_finish_drains_the_existing_turn_before_cancelling(self):
        p=Policy();completed=[]
        def tick():
            completed.append(True);p.host.state='idle'
        supervisor=self.supervisor(p,tick)
        def bind():
            p.dispatcher=Dispatcher();p.host.state='active'
            p.store.data.update(lifecycle='ended',start_at=0)
        p.bind_and_bootstrap=bind
        original=p.stop
        def stop():
            self.assertTrue(completed,'Normal finish killed the CLI before its final response')
            original()
        p.stop=stop
        result=supervisor.run()
        self.assertIsNone(result['error_type'],result)
        self.assertTrue(completed)
        self.assertEqual(result['reason'],'world_ended')
        self.assertTrue(result['finish_turns_drained'])

    def test_finish_wait_is_bounded_and_stop_interrupts_it(self):
        for stop_at,expected_wait in ((None,2),(1,1)):
            with self.subTest(stop_at=stop_at):
                p=Policy()
                supervisor=self.supervisor(p,lambda:None,finish_turn_grace_s=2,
                    stop_requested=lambda:stop_at is not None and self.now>=stop_at)
                def bind():
                    p.dispatcher=Dispatcher();p.host.state='active'
                    p.store.data.update(lifecycle='ended',start_at=0)
                p.bind_and_bootstrap=bind
                result=supervisor.run()
                self.assertEqual(self.now,expected_wait)
                self.assertFalse(result['finish_turns_drained'])
                self.assertTrue(p.host.stopped)

    def test_adaptive_child_final_response_is_also_drained(self):
        from types import SimpleNamespace
        p=Policy();child=Host();child.state='active'
        p.setup=SimpleNamespace(hosts={'Delegate_A':child})
        supervisor=self.supervisor(p,lambda:setattr(child,'state','idle'))
        def bind():
            p.dispatcher=Dispatcher();p.host.state='idle'
            p.store.data.update(lifecycle='ended',start_at=0)
        p.bind_and_bootstrap=bind
        result=supervisor.run()
        self.assertEqual(self.now,1)
        self.assertTrue(result['finish_turns_drained'])

    def test_normal_owner_exit_does_not_hide_the_recorded_terminal_world(self):
        p=Policy();supervisor=self.supervisor(p,lambda:setattr(p.host,'state','idle'))
        def bind():
            p.dispatcher=Dispatcher();p.host.state='active'
            p.store.data.update(lifecycle='ended',start_at=0)
        p.bind_and_bootstrap=bind
        supervisor.owner_alive=lambda:p.dispatcher is None
        result=supervisor.run()
        self.assertEqual(result['reason'],'world_ended')
        self.assertTrue(result['finish_turns_drained'])

    def supervisor(self, policy, sleep, **kwargs):
        self.now = 0
        def tick(seconds): self.now += seconds; sleep()
        policy.now = lambda: self.now
        return CentralizedSupervisor(policy, lambda: True, clock=lambda: self.now, wall_clock=lambda: self.now, sleep=tick,
                                     poll_s=1, startup_timeout_s=3, wall_limit_s=4, **kwargs)

    def test_the_worlds_wall_limit_pause_is_a_normal_end_without_a_reply_drain(self):
        # The world's guard pauses dispatch, stops the arms, then ends the run. The pause
        # seen in between is that end, and the cut-off turn owes no final reply.
        import sqlite3
        p = Policy(); p.store.db = sqlite3.connect(':memory:')
        p.store.db.execute('CREATE TABLE events(kind TEXT)')
        def bind():
            p.dispatcher = Dispatcher(); p.host.state = 'active'
            p.store.data.update(lifecycle='running', start_at=0)
        p.bind_and_bootstrap = bind
        steps = []
        def tick():
            steps.append(1)
            if len(steps) == 1:
                p.store.data['dispatch_paused'] = True
                p.store.db.execute("INSERT INTO events VALUES ('POLICY_WALL_LIMIT')")
            elif len(steps) == 3:
                p.store.data['lifecycle'] = 'ended'
        result = self.supervisor(p, tick, finish_turn_grace_s=30).run()
        self.assertEqual((result['reason'], result['ended_by']), ('world_ended', 'wall_limit'))
        self.assertIsNone(result['finish_turns_drained'])
        # Without the guard's record, a pause is still a review stop.
        p2 = Policy()
        def bind2():
            p2.dispatcher = Dispatcher(); p2.host.state = 'active'
            p2.store.data.update(lifecycle='running', start_at=0, dispatch_paused=True)
        p2.bind_and_bootstrap = bind2
        self.assertEqual(self.supervisor(p2, lambda: None).run()['reason'], 'dispatch_paused')

    def test_ready_then_start_dispatch_wall_limit_and_seal(self):
        p = Policy()
        def tick(): p.host.state = 'idle'; p.store.ready = True
        supervisor = self.supervisor(p, tick)
        result = supervisor.run()
        self.assertEqual(result['reason'], 'wall_limit')
        self.assertTrue(result['started']); self.assertGreater(p.cycles, 0)
        self.assertTrue(p.host.stopped); self.assertEqual(p.dispatcher.calls[0][0], 'seal')
        with self.assertRaises(ValueError): supervisor.run()

    def test_startup_timeout_never_starts_or_dispatches(self):
        p = Policy(); result = self.supervisor(p, lambda: None).run()
        self.assertEqual(result['reason'], 'startup_timeout')
        self.assertFalse(result['started']); self.assertEqual(p.cycles, 0)
        self.assertTrue(p.host.stopped)

    def test_direct_start_counts_time_spent_sending_first_turn(self):
        p = Policy()
        supervisor = self.supervisor(p, lambda: None)
        def bind():
            p.binds += 1
            p.dispatcher = Dispatcher()
            p.store.data['lifecycle'] = 'running'
            p.store.data['start_at'] = self.now
            self.now += 3
            p.host.state = 'active'
        p.bind_and_bootstrap = bind
        p.start_when_ready = lambda: self.fail('direct start must not wait for READY')
        result = supervisor.run()
        self.assertEqual(result['reason'], 'wall_limit')
        self.assertEqual(self.now, 4)
        self.assertEqual(p.cycles, 1)

    def test_direct_start_uses_persisted_time_not_host_creation_or_bootstrap(self):
        p = Policy()
        supervisor = self.supervisor(p, lambda: None)
        def bind():
            p.binds += 1; p.dispatcher = Dispatcher()
            self.now = 100
            p.store.data.update(lifecycle='running', start_at=100)
            self.now = 103
            p.host.state = 'active'
        p.bind_and_bootstrap = bind
        result = supervisor.run()
        self.assertEqual(result['reason'], 'wall_limit')
        self.assertEqual(self.now, 104)
        self.assertEqual(p.cycles, 1)

    def test_missing_persisted_start_fails_closed(self):
        p = Policy()
        supervisor = self.supervisor(p, lambda: None)
        def bind():
            p.dispatcher = Dispatcher(); p.store.data['lifecycle'] = 'running'
            p.host.state = 'active'
        p.bind_and_bootstrap = bind
        result = supervisor.run()
        self.assertEqual(result['reason'], 'supervisor_error')
        self.assertEqual(result['error_type'], 'ValueError')
        self.assertEqual(p.cycles, 0)

    def test_capacity_backoff_never_extends_original_deadline(self):
        p=Policy(); retries=[]
        supervisor=self.supervisor(p,lambda:None)
        def bind():
            p.dispatcher=Dispatcher();p.store.data.update(lifecycle='running',start_at=0)
            p.host.state='error'
        p.bind_and_bootstrap=bind
        def recover(store): retries.append(self.now);return True
        p.host.recover_capacity=recover
        result=supervisor.run()
        self.assertEqual(result['reason'],'wall_limit')
        self.assertEqual(retries,[0,1,2,3])
        self.assertEqual(self.now,4)

    def test_unknown_turn_stops_without_resending(self):
        p = Policy()
        result = self.supervisor(p, lambda: setattr(p.host, 'state', 'unknown')).run()
        self.assertEqual(result['reason'], 'session_unknown')
        self.assertEqual(p.binds, 1); self.assertEqual(p.cycles, 0)

    def test_unknown_budget_failure_preserves_bounded_session_evidence(self):
        p=Policy()
        p.host.observe=lambda: {'status':p.host.state,'budget_status':'uncertain',
                               'last_result_subtype':'error_max_budget_usd',
                               'last_turn_reported_cost_usd':.4755318}
        result=self.supervisor(p,lambda: setattr(p.host,'state','unknown')).run()
        self.assertEqual(result['reason'],'session_unknown')
        self.assertEqual(result['session_evidence'],{'budget_status':'uncertain',
            'last_result_subtype':'error_max_budget_usd','last_turn_reported_cost_usd':.4755318})
        self.assertTrue(p.host.stopped)

    def test_owner_loss_and_stop_before_binding_still_try_seal(self):
        p = Policy()
        supervisor = CentralizedSupervisor(p, lambda: False)
        with patch('robofrontier.runtime.seal.seal_run', return_value={'sealed': True}) as seal:
            result = supervisor.run()
        self.assertEqual(result['reason'], 'owner_unavailable')
        self.assertEqual(p.binds, 0); seal.assert_called_once()

    def test_seal_failure_is_reported_not_overwritten_as_success(self):
        p = Policy()
        def tick():
            p.host.state = 'unknown'
            def fail(*args): raise ValueError('unresolved physical action')
            p.dispatcher.admin = fail
        result = self.supervisor(p, tick).run()
        self.assertEqual(result['reason'], 'session_unknown')
        self.assertIsNone(result['seal']); self.assertEqual(result['seal_error_type'], 'ValueError')


if __name__ == '__main__': unittest.main()
