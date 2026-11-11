"""Antigravity delegate setup against the real runtime store, with a stand-in CLI."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from fake_pipeline import FakeWorld, fake_capture
from robofrontier.engines.antigravity import orchestration
from robofrontier.engines.antigravity.driver import ForkUnacknowledged
from robofrontier.engines.antigravity.robot_mcp import binding_path
from robofrontier.runtime.delegation import Delegations
from robofrontier.runtime.service import RuntimeService
from robofrontier.runtime.setup import prepare_run, write_json
from robofrontier.tasks.config import load_harness, startup_protocol


class Runner:
    """The parent's and each child's native transport."""
    def __init__(self, test):
        self.test, self.home = test, Path(test.tmp.name)/'home'

    def fork(self, step):
        self.test.forks += 1
        if self.test.before_fork:
            self.test.before_fork()
        if self.test.unacknowledged:
            raise ForkUnacknowledged(str(uuid.uuid4()))
        return str(uuid.uuid4())

    def input_delivered(self, name, timeout, alive=None):
        self.test.waited.append((name, timeout))
        return self.test.delivered


class Host:
    def __init__(self, test, actor, session):
        self.test, self.actor, self.session_id, self.runner = test, actor, session, Runner(test)
        self.sent, self.stopped = [], False

    def send(self, prompt):
        self.sent.append(prompt)
        return {'threadId': self.session_id, 'turnId': 'turn'}

    def observe(self):
        return {'status': 'active'}

    def stop(self):
        self.stopped = True

    def close_process(self):
        pass


class ForkSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        cfg = load_harness()
        cfg.update(topology='adaptive', startup_protocol=startup_protocol('adaptive'), engine='antigravity')
        (root/'config.json').write_text(json.dumps(cfg))
        self.run = prepare_run(root/'run', harness_path=root/'config.json')
        self.service = RuntimeService(self.run, FakeWorld, fake_capture)
        self.addCleanup(self.service.close)
        self.store = self.service.store
        self.forks, self.before_fork, self.unacknowledged, self.delivered, self.waited = 0, None, False, True, []
        self.parent_session = str(uuid.uuid4())
        self.call('Controller', 'ready', 'c1')
        self.call('Meta', 'bind', 'c2', {'actor': 'Controller', 'thread_id': self.parent_session})
        self.store.observe_session('Controller', 'idle', 'ready', time.time(), 'antigravity.host')
        self.assertTrue(self.call('Meta', 'start', 'c3')['result']['started'])
        self.call('Controller', 'delegate', 'batch', {'scopes': [
            {'robots': [r], 'goal': 'test outcome', 'done_when': 'verified evidence'} for r in ('A', 'B')]})
        write_json(binding_path(self.run, 'batch'), {'session_id': self.parent_session, 'actor': 'Controller',
            'step': 2, 'trajectory': str(uuid.uuid4()), 'tool_id': 'tool-1', 'input_sha256': 'x', 'call_id': 'batch'})
        self.parent = Host(self, 'Controller', self.parent_session)
        self.parent.run, self.parent.profile, self.parent.base_env = self.run, {}, {}
        self.parent.budget_ledger = self.ledger = object()
        self.children = {}
        def child_host(run, actor, profile, env, *, native_session, **options):
            self.children[actor] = Host(self, actor, native_session)
            return self.children[actor]
        proof = lambda home, parent, child, at, **options: {
            'source_thread_id': parent, 'source_ordinal': at, 'source_sha256': 'same'}
        for name, value in (('AntigravitySessionHost', child_host), ('pending', lambda *a: None), ('verify', proof),
                            ('delegate_prompt', lambda run, actor, child: 'You are ' + actor)):
            patcher = patch.object(orchestration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.setup = orchestration.ForkSetup(self.store, self.parent, self.ledger, 'manager')
        self.delegations = Delegations(self.store)

    def call(self, actor, op, call_id, data=None):
        job = self.service.accept(actor, op, data or {}, call_id)
        self.service.pump()
        return job

    def batch(self):
        return self.delegations.batch('batch')

    def test_children_start_only_after_activation_and_delivery(self):
        result = self.setup.establish('batch')
        self.assertEqual(result['status'], 'active')
        batch = self.batch()
        self.assertEqual(batch['status'], 'active')
        self.assertEqual([c['start_status'] for c in batch['children']], ['sent', 'sent'])
        self.assertEqual([h.sent for h in self.children.values()], [['You are ' + a] for a in self.children])
        self.assertEqual(len(self.waited), 2)
        self.assertTrue(all(0 < timeout <= orchestration.INPUT_ACK_S for _, timeout in self.waited))
        for child in batch['children']:
            fork = json.loads((self.run/'private/state/antigravity-forks'/(child['actor']+'.json')).read_text())
            self.assertEqual(fork['status'], 'verified')

    def test_deadline_passing_during_the_last_fork_blocks_activation(self):
        def expire():
            if self.forks == 2:
                # After this child's pre-fork check, as a slow native step would.
                batch = self.batch()
                batch['setup_deadline'] = time.time() + .05
                self.delegations.save(batch)
        self.before_fork = expire
        real = orchestration.ForkSetup.boundary
        def boundary(setup, batch_id, actor):
            # The host's own checks all pass; only the runtime's activation can refuse.
            if self.forks < 2:
                real(setup, batch_id, actor)
        with patch.object(orchestration.ForkSetup, 'boundary', boundary):
            time_passes = threading.Event()
            original = self.setup.admin
            def admin(op, data):
                if op == 'delegate-activate':
                    time_passes.wait(.1)
                return original(op, data)
            self.setup.admin = admin
            result = self.setup.establish('batch')
        self.assertEqual(result, {'status': 'needs_review', 'error_type': 'ValueError'})
        batch = self.batch()
        self.assertEqual(batch['status'], 'needs_review')
        self.assertTrue(self.store.get('dispatch_paused'))
        self.assertTrue(all(not host.sent and host.stopped for host in self.children.values()))
        self.assertTrue(all(self.store.agent(c['actor'])['delegation_state'] == 'creating' for c in batch['children']))

    def test_unacknowledged_fork_keeps_its_child_for_review(self):
        self.unacknowledged = True
        result = self.setup.establish('batch')
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(self.forks, 1)
        first = self.batch()['children'][0]
        fork = json.loads((self.run/'private/state/antigravity-forks'/(first['actor']+'.json')).read_text())
        self.assertEqual(fork['status'], 'unacknowledged')
        self.assertEqual(first['thread_id'], fork['child_session'])
        self.assertFalse(first['verified'])
        self.assertEqual(self.store.agent(first['actor'])['delegation_state'], 'creating')

    def test_undelivered_first_input_is_not_recorded_as_sent(self):
        self.delivered = False
        result = self.setup.establish('batch')
        self.assertEqual(result['status'], 'needs_review')
        batch = self.batch()
        self.assertEqual(batch['status'], 'needs_review')
        self.assertEqual([c['start_status'] for c in batch['children']], ['pending', 'pending'])
        # The first child's delivery was unknown, so the second was never given input.
        self.assertEqual([len(h.sent) for h in self.children.values()], [1, 0])
        self.assertTrue(all(h.stopped for h in self.children.values()))
        self.assertTrue(self.store.get('dispatch_paused'))

    def test_stop_before_activation_grants_nothing(self):
        self.before_fork = lambda: self.forks == 2 and self.setup.cancel_event.set()
        real = orchestration.ForkSetup.boundary
        with patch.object(orchestration.ForkSetup, 'boundary',
                          lambda setup, batch_id, actor: self.forks < 2 and real(setup, batch_id, actor)):
            result = self.setup.establish('batch')
        self.assertEqual(result['status'], 'needs_review')
        self.assertTrue(all(not host.sent for host in self.children.values()))
        self.assertTrue(all(self.store.agent(c['actor'])['delegation_state'] == 'creating'
                            for c in self.batch()['children']))


if __name__ == '__main__':
    unittest.main()
