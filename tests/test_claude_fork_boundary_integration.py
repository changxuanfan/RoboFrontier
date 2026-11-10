"""Actual CLI, local fake model, and a delegate forked while its parent waits at an MCP call."""
import http.server
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
import uuid

from PIL import Image
from robofrontier.engines.claude.provenance import first_input, fork_provenance, history, transcript_rows
from robofrontier.engines.claude.runner import run_turn
from robofrontier.engines.claude.session_host import ClaudeSessionHost
from robofrontier.runtime.bootstrap import DELEGATE


def conversation(body):
    # The CLI may send its own system-role entries among the messages.
    return [m for m in body.get('messages', []) if m.get('role') != 'system']


def text_of(content):
    if isinstance(content, str): return content
    return ''.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text')


class Model(http.server.BaseHTTPRequestHandler):
    """Calls the robot tool for a new prompt and answers in text after a tool result."""
    requests = []
    def log_message(self, *args): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append((time.time(), body))
        tools = [t['name'] for t in body.get('tools', []) if 'robot' in t.get('name', '')]
        last = (conversation(body) or [{}])[-1].get('content', '')
        result = isinstance(last, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in last)
        if tools and not result:
            content = [{'type': 'tool_use', 'id': 'toolu_' + uuid.uuid4().hex[:12], 'name': tools[0],
                        'input': {'op': 'observe', 'data': {}, 'views': ['top']}}]
        else:
            content = [{'type': 'text', 'text': 'done'}]
        reason = 'tool_use' if content[0]['type'] == 'tool_use' else 'end_turn'
        message = {'id': 'msg', 'type': 'message', 'role': 'assistant', 'model': 'claude-opus-5-5', 'content': [],
                   'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 10, 'output_tokens': 4}}
        item = content[0]
        start = {'type': 'tool_use', 'id': item['id'], 'name': item['name'], 'input': {}} if reason == 'tool_use' else item
        delta = ({'type': 'input_json_delta', 'partial_json': json.dumps(item['input'])} if reason == 'tool_use'
                 else {'type': 'text_delta', 'text': ''})
        events = [('message_start', {'type': 'message_start', 'message': message}),
                  ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': start}),
                  ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': delta}),
                  ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
                  ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': reason, 'stop_sequence': None},
                                     'usage': {'output_tokens': 4}}),
                  ('message_stop', {'type': 'message_stop'})]
        data = ''.join('event: %s\ndata: %s\n\n' % (n, json.dumps(p)) for n, p in events).encode()
        try:
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError): pass


def wait_for(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value: return value
        time.sleep(.05)
    return None


@unittest.skipUnless(shutil.which('claude'), 'Claude CLI is not installed')
class ForkBoundaryTests(unittest.TestCase):
    def test_delegate_forks_at_the_pending_call_and_its_tools_wait_for_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'run'
            roles = run/'public/inputs/roles.json'; roles.parent.mkdir(parents=True)
            roles.write_text(json.dumps({'roles': {'Controller': {'kind':'controller'}}}))
            image = run/'public/observations/top.png'; image.parent.mkdir(parents=True)
            Image.new('RGB', (4,4), 'red').save(image)
            entered = threading.Event(); release = threading.Event(); calls = []
            class World(http.server.BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_POST(self):
                    self.rfile.read(int(self.headers.get('Content-Length', 0)))
                    calls.append(time.time())
                    if len(calls) == 1: entered.set(); release.wait(60)  # the parent's pending call
                    payload = json.dumps({'observation': {'images': {'top': str(image)}}}).encode()
                    try:
                        self.send_response(200); self.end_headers(); self.wfile.write(payload)
                    except (BrokenPipeError, ConnectionResetError): pass
            world = http.server.ThreadingHTTPServer(('127.0.0.1',0), World)
            model = http.server.ThreadingHTTPServer(('127.0.0.1',0), Model)
            for server in (world, model): threading.Thread(target=server.serve_forever, daemon=True).start()
            Model.requests = []
            host = None
            try:
                connection = run/'private/state/connections/Controller.json'; connection.parent.mkdir(parents=True)
                connection.write_text(json.dumps({'run_id':'run','actor':'Controller','schema_version':3,
                    'url':f'http://127.0.0.1:{world.server_port}','token':'fake'}))
                profile = {'model':'claude-opus-5-5','effort':'high','env_key':'FAKE_KEY',
                           'base_url':f'http://127.0.0.1:{model.server_port}'}
                env = {'PATH':os.environ.get('PATH',''),'FAKE_KEY':'fake'}
                config = run/'private/claude-config'
                host = ClaudeSessionHost(run, 'Controller', profile, env, turn_timeout=90)
                host.send('Call robot observe tool.')
                self.assertTrue(entered.wait(30), 'Parent did not reach the blocked MCP call')
                # MCP delivery can precede the transcript flush; fork_setup waits the same way.
                def pending():
                    try: rows = history(transcript_rows(config, host.session_id), host.session_id)
                    except ValueError: return None
                    calls_made = [b['id'] for r in rows for b in (r.get('message') or {}).get('content', [])
                                  if isinstance(b, dict) and b.get('type') == 'tool_use']
                    return (rows, calls_made[-1]) if calls_made else None
                source, pending_id = wait_for(pending, 10) or self.fail('Parent pending call not in its transcript')

                def fork(prompt, gate):
                    child = str(uuid.uuid4()); out = {}
                    worker = threading.Thread(target=lambda: out.update(run_turn(
                        profile, profile['model'], profile['effort'], host.mcp, prompt, run, env, session_id=child,
                        fork_from=host.session_id, gate=gate, timeout=60, events_name=child+'.jsonl')))
                    worker.start()
                    return child, out, worker

                # 1. A gate opened only after the child has already asked for a tool.
                prompt = (DELEGATE.replace('{{ACTOR}}', 'Delegate_0123456789ab')
                          .replace('{{SCOPE}}', json.dumps({'robots':['A'],'goal':'g','done_when':'d','constraints':''},
                                                           separators=(',', ':'))))
                gate = {'open': run/'D.gate-open', 'closed': run/'D.gate-closed', 'deadline': time.time()+60}
                child, record, worker = fork(prompt, gate)
                first = wait_for(lambda: next((b for _, b in Model.requests
                                               if text_of(conversation(b)[-1]['content']) == prompt), None))
                self.assertIsNotNone(first, 'The child never sent its first input to the model')
                messages = conversation(first)
                # The model sees the parent's history up to its pending call, the CLI's own
                # placeholder result for that unanswered call, then the delegate message.
                at = next(i for i, m in enumerate(messages) if m['role'] == 'assistant' and any(
                    isinstance(b, dict) and b.get('id') == pending_id for b in m['content']))
                after = [b for m in messages[at+1:] for b in (m['content'] if isinstance(m['content'], list) else [])]
                self.assertEqual([b.get('tool_use_id') for b in after if b.get('type') == 'tool_result'], [pending_id])
                self.assertEqual(text_of(messages[-1]['content']), prompt)
                self.assertIn('mcp__robot__robot', [t['name'] for t in first['tools']])
                # The model request can precede the end of the transcript write; setup polls too.
                def verified():
                    try: return fork_provenance(host.session_id, child, config, at=source)
                    except ValueError: return None
                proof = wait_for(verified, 10)
                self.assertIsNotNone(proof, 'Child history does not copy the parent at its pending call')
                copy = history(transcript_rows(config, child), child)
                self.assertEqual(proof['source_ordinal'], len(source))
                self.assertEqual(first_input(copy[len(source):]), prompt)
                # The model has asked for the robot; the hook holds it while the gate is shut.
                def asked():
                    try: rows = history(transcript_rows(config, child), child)[len(source):]
                    except ValueError: return False
                    return any(isinstance(b, dict) and b.get('type') == 'tool_use'
                               for r in rows for b in ((r.get('message') or {}).get('content') or []))
                self.assertTrue(wait_for(asked), 'The child did not ask for its tool')
                time.sleep(1.5)
                self.assertEqual(len(calls), 1, 'A gated child reached the world')
                opened = time.time(); gate['open'].touch()
                worker.join(60)
                self.assertEqual(record['exit_code'], 0, record.get('stderr_tail'))
                self.assertEqual(record['summary']['session_id'], child)
                self.assertEqual(len(calls), 2); self.assertGreater(calls[1], opened)

                # 2. A closed gate refuses the call; nothing reaches the world.
                closed = {'open': run/'E.gate-open', 'closed': run/'E.gate-closed', 'deadline': time.time()+60}
                closed['closed'].touch()
                refused, record, worker = fork(prompt, closed)
                worker.join(60)
                self.assertEqual(record['exit_code'], 0, record.get('stderr_tail'))
                self.assertEqual(len(calls), 2)
                results = [b for r in history(transcript_rows(config, refused), refused)[len(source):]
                           for b in ((r.get('message') or {}).get('content') or []) if isinstance(b, dict)
                           and b.get('type') == 'tool_result' and b.get('tool_use_id') != pending_id]
                self.assertTrue(results and results[0].get('is_error'))
                self.assertIn('not run', json.dumps(results[0]))
                fork_provenance(host.session_id, refused, config, at=source)
                self.assertEqual(host.observe()['status'], 'active')
            finally:
                release.set()
                if host:
                    host.wait(30)
                    if host.observe()['status']=='active': host.stop(); host.wait(10)
                for server in (model,world): server.shutdown(); server.server_close()


if __name__ == '__main__': unittest.main()
