"""Exercise native standing-team orchestration through the real shared runtime."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fake_pipeline import FakeWorld, fake_capture
from robofrontier.engines.claude.budget import BudgetLedger
from robofrontier.engines.claude.standing_team import StandingTeamPolicyHost
from robofrontier.runtime.setup import verify_inputs
from robofrontier.runtime.service import RuntimeService
from robofrontier.batch.claude_prepare import prepare_batch


class RoleHost:
    def __init__(self, run, actor, profile, env, **kwargs):
        self.actor = actor
        self.session_id = str(uuid.uuid4())
        self.state = 'new'
        self.turn_id = None
        self.prompts = []
        self.ledger = kwargs['budget_ledger']
        self.before_send = lambda: None
        self.recovering = False

    def send(self, prompt):
        self.before_send()
        self.prompts.append(prompt)
        self.state = 'active'
        self.turn_id = str(uuid.uuid4())
        return {'threadId': self.session_id, 'turnId': self.turn_id}

    def observe(self):
        return {'actor': self.actor, 'thread_id': self.session_id,
                'status': self.state, 'turn_id': self.turn_id}

    def recover_capacity(self, store):
        return self.recovering

    def adopt(self, session_id):
        self.session_id = session_id; self.state = 'idle'
        return self

    def stop(self):
        self.state = 'idle'

    def wait(self, timeout=5):
        return True


@contextmanager
def standing_fixture(topology, *, factory=RoleHost, endpoint=None, env=None):
    with tempfile.TemporaryDirectory(prefix='claude-standing-') as tmp:
        batch = Path(tmp)/'batch'
        # A local fake model and a fake key: nothing to expose (claude_prepare.exposed_api_keys).
        with patch('robofrontier.batch.claude_prepare.exposed_api_keys', return_value=[]):
            prepare_batch(batch, ['haiku'], cases=['transport-a04-d1'], topology=topology)
        run = batch/'haiku/transport-a04-d1'
        launch = run/'private/inputs/claude.json'
        data = json.loads(launch.read_text())
        if endpoint:
            data['profile'].update(base_url=endpoint, env_key='FAKE_KEY')
            launch.write_text(json.dumps(data))
            manifest = run/'private/inputs/manifest.json'
            frozen = json.loads(manifest.read_text())
            frozen['input_sha256']['private/inputs/claude.json'] = hashlib.sha256(launch.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(frozen))
        profile = data['profile']
        ledger = BudgetLedger.create(run/'private/state/test-budget.sqlite')
        service = RuntimeService(run, FakeWorld, fake_capture)
        def call(connection, op, data, call_id, **kwargs):
            actor = Path(connection).stem
            with service.lock:
                job = service.accept(actor, op, data, call_id)
                service.pump()
                if not job['done'].is_set():
                    raise AssertionError('Synthetic request did not settle')
                return job['result']
        policy = None
        try:
            policy = StandingTeamPolicyHost(run, profile, env or {}, ledger, host_factory=factory, client=call)
            with patch('robofrontier.runtime.pipeline_client.client_call', call):
                yield policy, service, call
        finally:
            if policy is not None:
                policy.stop()
                policy.close()
            service.close()
            ledger.close()


class StandingTeamTests(unittest.TestCase):
    def test_a_continued_segment_resumes_every_role_in_its_own_session(self):
        for topology in ('hierarchical', 'peer'):
            with self.subTest(topology=topology), standing_fixture(topology) as (policy, service, call):
                policy.bind_and_bootstrap()
                sessions = {a: h.session_id for a, h in policy.hosts.items()}
                store = service.store
                # What run_segments.prepare_retry leaves for the next segment.
                store.put('segment', 1); store.put('lifecycle', 'resuming')
                store.put('pending_segment', {'segment': 1, 'previous_ended_at': 0., 'restored_sim_s': 4.0,
                                              'interrupted': {'A': ['A-call_1']}})
                profile = json.loads((policy.run/'private/inputs/claude.json').read_text())['profile']
                with self.assertRaisesRegex(ValueError, 'cannot be restarted'):
                    StandingTeamPolicyHost(policy.run, profile, {}, policy.hosts['A'].ledger, host_factory=RoleHost, client=call)
                resumed = StandingTeamPolicyHost(policy.run, profile, {}, policy.hosts['A'].ledger,
                                                 host_factory=RoleHost, client=call, resume=True)
                try:
                    reply = resumed.resume_segment()
                    self.assertEqual((reply['segment'], store.get('lifecycle')), (1, 'running'))
                    for actor, host in resumed.hosts.items():
                        self.assertEqual(host.session_id, sessions[actor])
                        self.assertEqual(len(host.prompts), 1)
                        self.assertIn('restarted this trial', host.prompts[0])
                    self.assertIn('A-call_1', resumed.hosts['A'].prompts[0])
                    self.assertIn('Yours: none.', resumed.hosts['B'].prompts[0])
                    with self.assertRaisesRegex(ValueError, 'Not a prepared segment'): resumed.resume_segment()
                finally:
                    resumed.stop(); resumed.close()

    def test_all_roles_bind_before_start_and_first_prompt_without_ready(self):
        for topology in ('hierarchical', 'peer'):
            with self.subTest(topology=topology), standing_fixture(topology) as (policy, service, _):
                expected = {'A', 'B', 'C', 'D'} | ({'Controller'} if topology == 'hierarchical' else set())
                self.assertEqual(set(policy.hosts), expected)
                self.assertEqual(verify_inputs(policy.run), [])
                for host in policy.hosts.values():
                    def check():
                        self.assertEqual(service.store.get('lifecycle'), 'running')
                        for actor in expected:
                            self.assertIsNotNone(service.store.agent(actor)['thread_id'])
                            self.assertFalse(service.store.agent(actor)['ready'])
                    host.before_send = check
                    self.assertIs(host.ledger, policy.hosts['A'].ledger)
                policy.bind_and_bootstrap()
                self.assertIsNotNone(service.store.get('start_at'))
                self.assertEqual(len({h.session_id for h in policy.hosts.values()}), len(expected))
                for actor, host in policy.hosts.items():
                    self.assertEqual(len(host.prompts), 1)
                    # The frozen first message, the same one the Codex route sends.
                    self.assertIn('Your role is '+actor+'.', host.prompts[0])
                    self.assertIn('experiment has started for the whole team', host.prompts[0])
                    self.assertIn('with your file tools', host.prompts[0])
                    self.assertNotIn('Await the host START', host.prompts[0])
                    self.assertNotIn('{{', host.prompts[0])
                with self.assertRaisesRegex(ValueError, 'Never repeat'):
                    policy.bind_and_bootstrap()

    def test_mailbox_wakes_bound_recipient_and_preserves_communication_authority(self):
        for topology in ('hierarchical', 'peer'):
            with self.subTest(topology=topology), standing_fixture(topology) as (policy, service, call):
                policy.bind_and_bootstrap()
                for h in policy.hosts.values(): h.state = 'idle'
                recipient = 'Controller' if topology == 'hierarchical' else 'B'
                conn = policy.run/'private/state/connections/A.json'
                sent = call(conn, 'send', {'to':[recipient], 'text':'Measured milestone available'}, 'message-1')
                self.assertIn('message_id', sent)
                result = policy.cycle()
                self.assertTrue(result['dispatched'])
                self.assertEqual(len(policy.hosts[recipient].prompts), 2)
                self.assertIn('wake_id=', policy.hosts[recipient].prompts[-1])
                if topology == 'hierarchical':
                    rejected = call(conn, 'send', {'to':['B'], 'text':'wrong route'}, 'message-2')
                    self.assertIn('error', rejected)
                    ctl = policy.run/'private/state/connections/Controller.json'
                    rejected = call(ctl, 'gripper', {'robot':'A','state':'close','wait':False}, 'wrong-motion')
                    self.assertIn('error', rejected)
                else:
                    self.assertNotIn('Controller', service.store.agents())

    def test_lost_binding_acknowledgement_never_launches_or_rebinds_roles(self):
        with standing_fixture('peer') as (policy, service, call):
            calls = []
            def lost(*args, **kwargs):
                calls.append(args[1]); call(*args, **kwargs)
                raise OSError('Acknowledgement lost after binding')
            policy.client = lost
            with self.assertRaises(OSError): policy.bind_and_bootstrap()
            self.assertEqual(service.store.get('lifecycle'), 'prepared')
            self.assertTrue(any(a['thread_id'] for a in service.store.agents().values()))
            self.assertFalse(any(h.prompts for h in policy.hosts.values()))
            with self.assertRaisesRegex(ValueError, 'Never repeat'): policy.bind_and_bootstrap()
            self.assertEqual(calls, ['bind'])

    def test_lost_wake_acknowledgement_pauses_without_resending(self):
        with standing_fixture('peer') as (policy, service, call):
            policy.bind_and_bootstrap()
            for h in policy.hosts.values(): h.state = 'idle'
            call(policy.run/'private/state/connections/A.json', 'send', {'to':['B'],'text':'new fact'}, 'fact-1')
            host = policy.hosts['B']
            def lost(prompt):
                host.prompts.append(prompt)
                raise OSError('Unknown dispatch outcome')
            host.send = lost
            result = policy.cycle()
            self.assertTrue(result['paused'])
            self.assertEqual(len(host.prompts), 2)
            self.assertEqual(policy.cycle()['dispatched'], [])
            self.assertEqual(len(host.prompts), 2)
            self.assertTrue(any(r['status'] == 'uncertain' for r in service.store.wake_rows()))

    def test_a_wake_refused_by_an_exhausted_task_budget_is_not_sent_and_pauses_for_the_budget(self):
        from robofrontier.engines.claude.budget import BudgetExhausted
        with standing_fixture('peer') as (policy, service, call):
            policy.bind_and_bootstrap()
            for h in policy.hosts.values(): h.state = 'idle'
            call(policy.run/'private/state/connections/A.json', 'send', {'to':['B'],'text':'new fact'}, 'fact-1')
            def refused(prompt):
                raise BudgetExhausted('Budget is exhausted or uncertain')
            policy.hosts['B'].send = refused
            self.assertTrue(policy.cycle()['paused'])
            rows = service.store.wake_rows()
            self.assertTrue(any(r['status'] == 'cancelled' for r in rows))
            self.assertFalse(any(r['status'] == 'uncertain' for r in rows))
            paused = [e for e in service.store.events() if e['kind'] == 'DISPATCH_PAUSED']
            self.assertEqual(paused[-1]['details']['reason'], 'Claude task budget exhausted')

    def test_unknown_role_pauses_and_other_role_recovery_does_not_mask_failure(self):
        with standing_fixture('peer') as (policy, service, _):
            policy.bind_and_bootstrap()
            policy.hosts['A'].state = 'error'; policy.hosts['A'].recovering = True
            policy.hosts['B'].state = 'error'
            self.assertFalse(policy.host.recover_capacity(service.store))
            policy.hosts['B'].recovering = True
            self.assertTrue(policy.host.recover_capacity(service.store))
            policy.hosts['B'].state = 'unknown'
            policy.hosts['A'].recover_capacity = lambda _: self.fail('Unknown teammate must be checked before recovery')
            self.assertFalse(policy.host.recover_capacity(service.store))
            self.assertTrue(policy.cycle()['paused'])

    def test_duplicate_session_factory_is_rejected_before_binding(self):
        class Duplicate(RoleHost):
            def __init__(self, *a, **k):
                super().__init__(*a, **k); self.session_id = 'duplicate'
        with self.assertRaisesRegex(ValueError, 'distinct native session'):
            with standing_fixture('hierarchical', factory=Duplicate):
                self.fail('Must reject duplicate initial sessions')


if __name__ == '__main__':
    unittest.main()
