"""Real Claude CLI/MCP standing roles, with synthetic loopback model and world."""
import http.server
import json
import os
import re
import shutil
import threading
import time
import unittest

from engines.test_claude_adaptive_integration import StubModel
from engines.test_claude_standing_team import standing_fixture
from robofrontier.runtime import layout as run_layout
from robofrontier.engines.claude.session_host import ClaudeSessionHost

POST_IDLE_PROMPT = 'RF_NATIVE_POST_IDLE_MAIL'
POST_IDLE_MESSAGE = 'Synthetic post-idle milestone from A'


class StandingModel(StubModel):
    requests = []

    steps = {}
    steps_lock = threading.Lock()
    post_idle_sent = set()

    def choose_tool(self, names, text, blocks, has_result):
        if not names:
            return None, None
        messages = json.dumps(self.request_body.get('messages', []))
        matches = re.findall(r'(?:Your current runtime role is|Your role is) ([A-Za-z][A-Za-z0-9_-]*)', messages)
        if not matches:
            return None, None
        actor = matches[0]
        # Frozen first messages list role files instead of quoting them; the test sets the topology.
        hierarchical = (getattr(type(self), 'topology', None) == 'hierarchical'
                        or 'Controller + Worker mode' in messages or 'Team topology: hierarchical' in messages)
        # This is a scripted endpoint, not a model comprehension test. Claude can
        # coalesce wake text and prior tool results in one user message. Advance
        # a bounded per-role script instead of treating the last block as an RPC
        # boundary; that assumption caused the first fixture to loop on inbox.
        with self.steps_lock:
            if actor == 'A' and POST_IDLE_PROMPT in messages and actor not in self.post_idle_sent:
                self.post_idle_sent.add(actor)
                payload, _ = self.message(actor, hierarchical)
                payload['data']['text'] = POST_IDLE_MESSAGE
                return payload, 'toolu_post_idle_send'
            step = self.steps.get(actor, 0)
            self.steps[actor] = step+1
        if actor == 'A' and step == 0:
            return {'op':'gripper','data':{'state':'close','wait':False}}, 'toolu_gripper'
        if actor == 'A':
            step -= 1
        if step == 0 and actor != 'Controller':
            return self.message(actor, hierarchical)
        phase = step % 3
        if phase == 0:
            return {'op':'inbox','data':{}}, 'toolu_inbox'
        if phase == 1:
            return {'op':'yield','data':{'state':'waiting','note':'Synthetic standing milestone retained','after_s':600}}, 'toolu_yield'
        return None, None

    @staticmethod
    def message(actor, hierarchical):
        recipient = 'Controller' if hierarchical else 'B' if actor == 'A' else 'A'
        return {'op':'send','data':{'to':[recipient],'text':'Synthetic milestone from '+actor}}, 'toolu_send'


@unittest.skipUnless(shutil.which('claude'), 'Requires native Claude CLI; synthetic local endpoint only')
class StandingNativeIntegrationTests(unittest.TestCase):
    def test_both_native_topologies_use_distinct_sessions_mailboxes_and_resume(self):
        model = http.server.ThreadingHTTPServer(('127.0.0.1', 0), StandingModel)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        env = {k:os.environ[k] for k in ('PATH','HOME','LANG','LC_ALL','TMPDIR') if k in os.environ}
        env['FAKE_KEY'] = 'synthetic'
        try:
            for topology in ('hierarchical', 'peer'):
                StandingModel.topology = topology
                with self.subTest(topology=topology), standing_fixture(
                        topology, factory=ClaudeSessionHost, endpoint=f'http://127.0.0.1:{model.server_port}',
                        env=env) as (policy, service, _):
                    recipient = 'Controller' if topology == 'hierarchical' else 'B'
                    idle_at_probe_send = []
                    class World(http.server.BaseHTTPRequestHandler):
                        def log_message(self, *args): pass
                        def do_POST(self):
                            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                            if self.path != '/op' or service.tokens.get(data['actor']) != self.headers.get('X-Token'):
                                self.send_error(403); return
                            with service.lock:
                                if data['op'] == 'send' and data['data'].get('text') == POST_IDLE_MESSAGE:
                                    idle_at_probe_send.append(policy.hosts[recipient].observe()['status'] == 'idle')
                                job = service.accept(data['actor'], data['op'], data['data'], data['call_id'], data.get('ack_delivery'))
                                service.pump()
                                for actor in list(service.world.running): service.world.complete(actor)
                                service.pump()
                            if not job['done'].wait(30):
                                result = {'call_id':job['id'],'execution_status':'pending'}
                            else: result = job['result']
                            raw = json.dumps(result).encode()
                            self.send_response(200); self.end_headers()
                            try: self.wfile.write(raw)
                            except (BrokenPipeError, ConnectionResetError): pass
                    world = http.server.ThreadingHTTPServer(('127.0.0.1', 0), World)
                    threading.Thread(target=world.serve_forever, daemon=True).start()
                    try:
                        with StandingModel.steps_lock:
                            StandingModel.steps.clear()
                            StandingModel.post_idle_sent.clear()
                        for actor in service.tokens:
                            path = policy.run/'private/state/connections'/(actor+'.json')
                            data = json.loads(path.read_text()); data['url'] = f'http://127.0.0.1:{world.server_port}'
                            path.write_text(json.dumps(data))
                        policy.bind_and_bootstrap()
                        sessions = {actor:host.session_id for actor,host in policy.hosts.items()}
                        deadline = time.monotonic()+45
                        while time.monotonic() < deadline:
                            result = policy.cycle()
                            if result['paused']: break
                            roles = [v for v in service.store.agents().values() if v['kind'] != 'manager']
                            if (all(h.observe()['status'] == 'idle' for h in policy.hosts.values()) and
                                    all('Synthetic standing milestone' in a['note'] for a in roles) and
                                    not any(service.store.pending(recipient)[key] for key in ('messages','signals'))):
                                break
                            time.sleep(.05)
                        self.assertFalse(service.store.get('dispatch_paused', False),
                                         {a:h.observe() for a,h in policy.hosts.items()})
                        self.assertTrue(all(h.observe()['status'] == 'idle' for h in policy.hosts.values()))
                        agents = {a:v for a,v in service.store.agents().items() if v['kind'] != 'manager'}
                        self.assertTrue(all('Synthetic standing milestone' in a['note'] for a in agents.values()))
                        self.assertFalse(any(service.store.pending(recipient)[key] for key in ('messages','signals')))
                        # Bootstrap mail may all be handled while recipients are
                        # active. Create a distinct native send after verified
                        # idle, then require receipt and resume on the same ID.
                        prior_turn = policy.hosts[recipient].observe()['turn_id']
                        prior_wakes = {row[0] for row in service.store.db.execute(
                            "SELECT id FROM wakes WHERE actor=?", (recipient,))}
                        bootstrap_wakes = service.store.db.execute(
                            "SELECT count(*) FROM wakes WHERE status IN ('sent','observed')").fetchone()[0]
                        bootstrap_pending = {actor:{key:service.store.pending(actor)[key]
                                                    for key in ('messages','signals')} for actor in policy.hosts}
                        ack = policy.hosts['A'].send(POST_IDLE_PROMPT)
                        self.assertEqual(ack['threadId'], sessions['A'])
                        deadline = time.monotonic()+45
                        def probe_received():
                            return service.store.db.execute(
                                "SELECT count(*) FROM messages m JOIN receipts r ON m.seq=r.seq "
                                "WHERE m.sender='A' AND m.text=? AND r.actor=? AND r.acked=1",
                                (POST_IDLE_MESSAGE, recipient)).fetchone()[0]
                        while time.monotonic() < deadline:
                            result = policy.cycle()
                            if result['paused']: break
                            if (probe_received() and all(h.observe()['status'] == 'idle' for h in policy.hosts.values())
                                    and policy.hosts[recipient].observe()['turn_id'] != prior_turn):
                                break
                            time.sleep(.05)
                        self.assertFalse(service.store.get('dispatch_paused', False),
                                         {a:h.observe() for a,h in policy.hosts.items()})
                        self.assertEqual(idle_at_probe_send, [True])
                        self.assertTrue(probe_received())
                        self.assertTrue(all(h.observe()['status'] == 'idle' for h in policy.hosts.values()))
                        self.assertNotEqual(policy.hosts[recipient].observe()['turn_id'], prior_turn)
                        self.assertEqual({actor:host.session_id for actor,host in policy.hosts.items()}, sessions)
                        resumed = [json.loads(row['value']) for row in service.store.db.execute(
                            "SELECT id,value FROM wakes WHERE actor=? AND status IN ('sent','observed')", (recipient,))
                                   if row['id'] not in prior_wakes]
                        self.assertTrue(resumed)
                        self.assertTrue(all(row['thread_id'] == sessions[recipient] for row in resumed))
                        self.assertTrue(service.store.db.execute("SELECT count(*) FROM wakes WHERE status IN ('sent','observed')").fetchone()[0])
                        self.assertTrue(service.world.executed)
                        self.assertEqual(service.world.executed[0][0], 'A')
                        for actor, host in policy.hosts.items():
                            files = list((run_layout.path(policy.run, 'engine_config', 'claude')/'projects').glob('*/'+host.session_id+'.jsonl'))
                            self.assertEqual(len(files), 1, actor)
                            self.assertEqual(agents[actor]['thread_id'], host.session_id)
                        messages = [json.loads(row['recipients']) for row in service.store.db.execute('SELECT recipients FROM messages')]
                        self.assertTrue(messages)
                        if topology == 'hierarchical':
                            self.assertTrue(all(m == ['Controller'] for m in messages), messages)
                        else:
                            self.assertNotIn('Controller', service.store.agents())
                            self.assertTrue(any(m == ['B'] for m in messages))
                        if os.environ.get('ROBOFRONTIER_NATIVE_TEST_RECEIPTS') == '1':
                            print('STANDING_NATIVE_RECEIPT '+json.dumps({
                                'topology':topology, 'bootstrap_wakes':bootstrap_wakes,
                                'bootstrap_pending':bootstrap_pending, 'post_idle_wakes':len(resumed),
                                'idle_at_native_send':idle_at_probe_send, 'recipient_acked':bool(probe_received()),
                                'same_sessions':{actor:host.session_id for actor,host in policy.hosts.items()} == sessions,
                                'scope':'Native CLI/MCP with synthetic loopback model/world; no real provider inference'}))
                    finally:
                        policy.stop()
                        world.shutdown(); world.server_close()
        finally:
            model.shutdown(); model.server_close()


if __name__ == '__main__':
    unittest.main()
