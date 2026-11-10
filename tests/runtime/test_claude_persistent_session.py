"""PersistentSession against the real Claude CLI and a local stub model (no provider, no credentials).

Skipped when no `claude` binary is installed.
"""
import http.server
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest

from robofrontier.runtime import access as policy_access
from robofrontier.engines.claude.runner import PersistentSession
from robofrontier.runtime.layout import manifest_record

SESSION = '44444444-4444-4444-8444-444444444444'
CHILD = '55555555-5555-4555-8555-555555555555'


class SlowStub(http.server.BaseHTTPRequestHandler):
    """Replies with text; a prompt containing SLOW takes 8 s so the turn can be interrupted."""
    prompts = []
    def log_message(self, *args): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        messages = [m for m in body.get('messages', []) if m.get('role') != 'system']
        last = messages[-1]['content']
        text = last if isinstance(last, str) else ' '.join(str(b.get('text', '')) for b in last if isinstance(b, dict))
        self.prompts.append(text)
        if 'SLOW' in text: time.sleep(8)
        message = {'id': 'm', 'type': 'message', 'role': 'assistant', 'model': 'x', 'content': [], 'stop_reason': None,
                   'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 1}}
        events = [('message_start', {'type': 'message_start', 'message': message}),
                  ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
                  ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'ok'}}),
                  ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
                  ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None},
                                     'usage': {'output_tokens': 1}}),
                  ('message_stop', {'type': 'message_stop'})]
        data = ''.join('event: %s\ndata: %s\n\n' % (n, json.dumps(p)) for n, p in events).encode()
        try:
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        except BrokenPipeError:
            pass


@unittest.skipUnless(shutil.which('claude'), 'Claude Code CLI is not installed')
class PersistentSessionTests(unittest.TestCase):
    def test_turns_share_one_process_interrupt_keeps_it_and_a_dead_process_resumes(self):
        SlowStub.prompts = []
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), SlowStub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        session = PersistentSession(interrupt_grace_s=20)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); run = root / 'repo/runs/b/p/case'
                (run / 'private/inputs').mkdir(parents=True); (run / 'workspace').mkdir()
                # A run with the frozen policy contract; earlier runs keep one process per turn.
                (run / 'private/inputs/manifest.json').write_text(json.dumps(manifest_record('claude')))
                (run / 'private/inputs/policy-access.json').write_text(json.dumps(policy_access.record(
                    run, repo=root/'repo', home=root/'home', tmp_dirs=(), checkouts=[root/'repo'])))
                profile = {'provider': 'anthropic', 'model': 'claude-opus-5-5', 'env_key': 'ANTHROPIC_API_KEY', 'effort': 'high',
                           'base_url': 'http://127.0.0.1:%d' % server.server_port}
                env = {'PATH': os.environ.get('PATH', ''), 'ANTHROPIC_API_KEY': 'local-fake-key'}
                turn = lambda prompt, n, **kw: session(profile, 'claude-opus-5-5', 'high', '{"mcpServers":{}}', prompt, run, env,
                                                       events_name='turn-%d.jsonl' % n, **kw)
                first = turn('FIRST', 1, session_id=SESSION); pid = session.process.pid
                second = turn('SECOND', 2, resume=SESSION)
                self.assertEqual((first['process'], second['process']), ('exited', 'exited'))
                self.assertEqual(session.process.pid, pid)  # same CLI process for both turns
                self.assertEqual({first['summary']['session_id'], second['summary']['session_id']}, {SESSION})
                self.assertTrue((run / 'private/engine/turns/turn-2.jsonl').is_file())
                # The CLI reports the session's cumulative cost; each turn is charged its increase.
                totals = [float(t['summary']['native_session_total_cost_usd']) for t in (first, second)]
                self.assertGreater(totals[1], totals[0])
                self.assertEqual(second['summary']['cost_scope'], 'invocation')
                self.assertAlmostEqual(second['summary']['total_cost_usd'], totals[1]-totals[0], places=9)
                # A stop interrupts the turn; the outcome is unknown but the process survives.
                cancel = threading.Event()
                def stop_once_slow_turn_reaches_model():
                    deadline = time.monotonic() + 30
                    while not any('SLOW' in p for p in SlowStub.prompts) and time.monotonic() < deadline: time.sleep(.05)
                    cancel.set()
                threading.Thread(target=stop_once_slow_turn_reaches_model, daemon=True).start()
                stopped = turn('SLOW please', 3, resume=SESSION, cancel_event=cancel)
                self.assertEqual(stopped['process'], 'cancelled')
                self.assertEqual(stopped['summary']['turn_status'], 'unknown')
                self.assertIsNone(session.process.poll())
                # If the process dies, the next turn starts a new one on the same transcript.
                session.close()
                resumed = turn('AFTER', 4, resume=SESSION)
                self.assertEqual(resumed['process'], 'exited')
                self.assertNotEqual(session.process.pid, pid)
                self.assertEqual(resumed['summary']['session_id'], SESSION)
                self.assertIn('FIRST', ' '.join(SlowStub.prompts))
        finally:
            session.close(); server.shutdown(); server.server_close()

    def test_a_delegate_fork_is_the_first_turn_of_its_process(self):
        SlowStub.prompts = []
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), SlowStub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        parent, child = PersistentSession(), PersistentSession()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); run = root / 'repo/runs/b/p/case'
                (run / 'private/inputs').mkdir(parents=True); (run / 'workspace').mkdir()
                (run / 'private/inputs/manifest.json').write_text(json.dumps(manifest_record('claude')))
                (run / 'private/inputs/policy-access.json').write_text(json.dumps(policy_access.record(
                    run, repo=root/'repo', home=root/'home', tmp_dirs=(), checkouts=[root/'repo'])))
                profile = {'provider': 'anthropic', 'model': 'claude-opus-5-5', 'env_key': 'ANTHROPIC_API_KEY', 'effort': 'high',
                           'base_url': 'http://127.0.0.1:%d' % server.server_port}
                env = {'PATH': os.environ.get('PATH', ''), 'ANTHROPIC_API_KEY': 'local-fake-key'}
                turn = lambda host, prompt, n, **kw: host(profile, 'claude-opus-5-5', 'high', '{"mcpServers":{}}', prompt, run,
                                                          env, events_name='turn-%d.jsonl' % n, **kw)
                turn(parent, 'PARENT', 1, session_id=SESSION)
                gate = {'open': run/'gate-open', 'closed': run/'gate-closed', 'deadline': time.time()+60}
                forked = turn(child, 'CHILD', 2, session_id=CHILD, fork_from=SESSION, gate=gate); pid = child.process.pid
                again = turn(child, 'AGAIN', 3, resume=CHILD)
                self.assertEqual((forked['process'], again['process']), ('exited', 'exited'))
                self.assertEqual({forked['summary']['session_id'], again['summary']['session_id']}, {CHILD})
                self.assertEqual(child.process.pid, pid)
                # The fork inherits the parent's cumulative counter. The live parent has not yet
                # recorded it, so the fork's whole counter is kept as an upper bound, never
                # charged from zero as if it had no history.
                self.assertIsNone(forked['summary']['native_cost_baseline_usd'])
                self.assertEqual(forked['summary']['cost_scope'], 'session_total_upper_bound')
                with self.assertRaisesRegex(ValueError, 'first turn'):
                    turn(child, 'REFORK', 4, session_id=CHILD, fork_from=SESSION, gate=gate)
        finally:
            parent.close(); child.close(); server.shutdown(); server.server_close()


if __name__ == '__main__': unittest.main()
