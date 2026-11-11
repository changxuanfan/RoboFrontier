import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from robofrontier.engines.claude.policy_host import CentralizedPolicyHost
from robofrontier.runtime.store import RuntimeStore


class FakeHost:
    def __init__(self, run, actor, profile, base_env):
        self.actor = actor; self.session_id = 'test-session'; self.state = 'new'; self.turn = None; self.prompts = []
    def send(self, prompt):
        self.state = 'active'; self.turn = 'turn-1'; self.prompts.append(prompt)
        return {'threadId': self.session_id, 'turnId': self.turn}
    def observe(self): return {'actor': self.actor, 'thread_id': self.session_id, 'status': self.state, 'turn_id': self.turn}
    def stop(self): self.state = 'unknown'; return self.observe()


class PolicyHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.run = Path(self.tmp.name) / 'run'
        public = self.run / 'public/inputs'; public.mkdir(parents=True)
        (public/'task.json').write_text(json.dumps({'family_materials': []}))
        (public/'roles.json').write_text(json.dumps({'topology': 'centralized', 'roles': {'Controller': {'kind': 'controller'}}}))
        frozen=self.run/'private/inputs/bootstrap/Controller.md'; frozen.parent.mkdir(parents=True)
        frozen.write_text('frozen start')
        cfg=json.loads((Path(__file__).resolve().parents[2]/'configs/harnesses/policy.json').read_text())
        cfg.update(startup_protocol='direct_controller_v2', engine='claude', topology='centralized', model='fake', effort='high')
        store=RuntimeStore(self.run/'private/state/runtime.sqlite'); store.initialize('run', cfg, ['A']); store.close()
        self.profile={'model':'fake', 'effort':'high', 'env_key':'FAKE'}
        self.calls=[]
        def client(connection, op, data, call_id, **kwargs):
            self.calls.append(op)
            if op == 'bind':
                store=RuntimeStore(self.run/'private/state/runtime.sqlite')
                store.update_agent(data['actor'], thread_id=data['thread_id']); store.close()
                return {'bound':True}
        self.client=client

    def tearDown(self): self.tmp.cleanup()

    def test_binding_once_starts_before_the_frozen_start_message(self):
        host=CentralizedPolicyHost(self.run, self.profile, {}, host_factory=FakeHost, client=self.client, verifier=lambda _: [])
        admin=[]
        def start(dispatcher, op, data=None):
            admin.append((op, host.host.prompts[:])); dispatcher.store.start(); return {'started': True}
        try:
            with mock.patch('robofrontier.engines.claude.policy_host.ClaudeDispatcher.admin', start):
                host.bind_and_bootstrap()
            self.assertEqual(self.calls, ['bind'])
            self.assertEqual(admin, [('request-start', [])])
            self.assertEqual(host.host.prompts, ['frozen start'])
            with self.assertRaises(ValueError): host.bind_and_bootstrap()
            host.stop()
        finally: host.close()

    def test_missing_frozen_start_message_fails_before_any_session(self):
        (self.run/'private/inputs/bootstrap/Controller.md').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing frozen bootstrap message'):
            CentralizedPolicyHost(self.run, self.profile, {}, host_factory=FakeHost, client=self.client, verifier=lambda _: [])

    def test_unknown_binding_acknowledgement_is_not_retried(self):
        def lost(*args, **kwargs): raise OSError('lost acknowledgement')
        host=CentralizedPolicyHost(self.run, self.profile, {}, host_factory=FakeHost, client=lost, verifier=lambda _: [])
        try:
            with self.assertRaises(OSError): host.bind_and_bootstrap()
            with self.assertRaisesRegex(ValueError, 'Never repeat'): host.bind_and_bootstrap()
        finally: host.close()

    def test_draft_cannot_bypass_engine_topology_or_input_checks(self):
        for verifier in (lambda _: ['input:changed'],):
            with self.assertRaisesRegex(ValueError, 'Frozen inputs changed'):
                CentralizedPolicyHost(self.run, self.profile, {}, host_factory=FakeHost, verifier=verifier)
        with self.assertRaisesRegex(ValueError, 'Profile differs'):
            CentralizedPolicyHost(self.run, {**self.profile, 'model':'wrong'}, {}, host_factory=FakeHost, verifier=lambda _: [])


if __name__ == '__main__': unittest.main()
