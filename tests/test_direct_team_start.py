"""Standing teams start from bound sessions, without a model READY turn."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from fake_pipeline import FakeWorld, fake_capture
from robofrontier.run_setup import prepare_run
from robofrontier.runtime_service import RuntimeService
from robofrontier.task_config import load_harness


class DirectTeamStartTests(unittest.TestCase):
    def make_service(self, directory, topology):
        config = load_harness()
        config.update(topology=topology, startup_protocol='direct_team_v3')
        harness = directory/'harness.json'
        harness.write_text(json.dumps(config))
        run = prepare_run(directory/'run', harness_path=harness)
        service = RuntimeService(run, FakeWorld, fake_capture)
        self.addCleanup(service.close)
        counter = 0
        def call(actor, op, data=None):
            nonlocal counter
            counter += 1
            job = service.accept(actor, op, data or {}, 'test-'+str(counter))
            service.pump()
            return job['result']
        return service, call

    def test_all_initial_roles_bind_before_one_start_and_ready_is_optional(self):
        for topology in ('hierarchical', 'peer'):
            with self.subTest(topology=topology), tempfile.TemporaryDirectory() as temporary:
                service, call = self.make_service(Path(temporary), topology)
                policy = {a: v for a, v in service.store.agents().items() if v['kind'] != 'manager'}
                self.assertEqual(set(policy), {'Controller', 'A', 'B', 'C', 'D'} if topology == 'hierarchical' else {'A', 'B', 'C', 'D'})
                self.assertIn('error', call('A', 'gripper', {'state': 'close', 'wait': False}))
                self.assertEqual(service.world.executed, [])
                self.assertIn('error', call('Meta', 'start'))
                for index, actor in enumerate(policy):
                    self.assertTrue(call('Meta', 'bind', {'actor': actor, 'thread_id': 'thread-'+actor})['bound'])
                    if index < len(policy)-1:
                        self.assertIn('error', call('Meta', 'start'))
                before = time.time()
                self.assertTrue(call('Meta', 'start')['started'])
                start = service.store.get('start_at')
                self.assertGreaterEqual(start, before)
                self.assertLessEqual(start, time.time())
                self.assertEqual(service.store.get('lifecycle'), 'running')
                for actor in policy:
                    agent = service.store.agent(actor)
                    self.assertFalse(agent['ready'])
                    self.assertEqual(agent['note'], '')
                    self.assertEqual(agent['work_state'], 'waiting')
                self.assertEqual(call('A', 'gripper', {'state': 'close', 'wait': False})['execution_status'], 'running')
                self.assertTrue(call('B', 'ready')['run_started'])
                self.assertEqual(call('B', 'gripper', {'state': 'open', 'wait': False})['execution_status'], 'running')
                self.assertIn('error', call('Meta', 'start'))
                self.assertEqual(service.store.get('start_at'), start)
                if topology == 'hierarchical':
                    self.assertIn('error', call('Controller', 'gripper', {'robot': 'C', 'state': 'close'}))
                service.close()

    def test_a_refused_start_gate_leaves_the_run_prepared(self):
        from unittest.mock import patch
        for readiness in ('environment_preview_only', 'prepared_policy_trial'):
            with self.subTest(readiness=readiness), tempfile.TemporaryDirectory() as temporary:
                service, call = self.make_service(Path(temporary), 'peer')
                videos = []
                service.video_factory = lambda: videos.append(1)
                for actor in ('A', 'B', 'C', 'D'):
                    call('Meta', 'bind', {'actor': actor, 'thread_id': 'thread-'+actor})
                started = []
                service.world.start_trial = lambda: started.append(1)
                service.task['execution_readiness'] = readiness
                with patch('robofrontier.task_families.validate_frozen_policy',
                           side_effect=ValueError('Frozen policy release differs')):
                    result = call('Meta', 'start')
                self.assertIn('error', result)
                self.assertEqual(service.store.get('lifecycle'), 'prepared')
                self.assertIsNone(service.store.get('start_at'))
                self.assertNotIn('START', [e['kind'] for e in service.store.events()])
                self.assertEqual((videos, started), ([], []))
                self.assertEqual({service.store.agent(a)['work_state'] for a in ('A', 'B', 'C', 'D')} & {'continue'}, set())

    def test_duplicate_native_session_cannot_bind_two_initial_roles_at_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            service, call = self.make_service(Path(temporary), 'peer')
            for actor in ('A', 'B', 'C', 'D'):
                call('Meta', 'bind', {'actor': actor, 'thread_id': 'same-thread'})
            response = call('Meta', 'start')
            self.assertIn('distinct session', response['error'])
            self.assertEqual(service.store.get('lifecycle'), 'prepared')
            self.assertIsNone(service.store.get('start_at'))

    def test_direct_team_protocol_is_rejected_for_controller_only_topology(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = load_harness()
            config.update(topology='adaptive', startup_protocol='direct_team_v3')
            path = Path(temporary)/'harness.json'
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'standing Workers'):
                load_harness(path)


if __name__ == '__main__':
    unittest.main()
