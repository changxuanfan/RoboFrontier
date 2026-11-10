"""The real Codex host continues a run after it was killed mid-action (local stub model only).

A LOCAL Responses stub plays the Controller: it observes and starts a slow move, the
test kills the host during that move, the world closes by itself, the next segment is
prepared, and the host is started again. It must reopen the same thread and send the
frozen resume message naming the interrupted move. No external inference or
credentials are involved. Skipped when `codex` or `node` is missing.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from robofrontier.runtime.layout import path as run_path
from robofrontier.runtime.segments import try_continue
from robofrontier.runtime.store import RuntimeStore
from robofrontier.tasks.scene import camera_names
from robofrontier.tasks.families import ROOT, prepare
from robofrontier.engines.codex.launch import hidden_skills, launch_config
from test_codex_policy_permissions import STUB
from test_run_segments_integration import wait_until

CASE = 'mosaic-a04-6x12-d1'
BOOTSTRAP, RESUME = 'This is a new, independent RoboFrontier trial', 'The host stopped unexpectedly'


def controller_stub(requests, steps):
    """Each turn replays steps[<marker in its last user message>], then answers DONE."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length']))); requests.append(body)
            items = [x for x in body.get('input', []) if isinstance(x, dict)]
            last_user = max((i for i, x in enumerate(items) if x.get('role') == 'user'), default=-1)
            text = json.dumps(items[last_user]) if last_user >= 0 else ''
            turn = next((v for k, v in steps.items() if k in text), [])
            answered = sum(x.get('type') == 'function_call_output' for x in items[last_user + 1:])
            n = len(requests)
            item = (dict(id='fc_%d' % n, type='function_call', call_id='call_%d' % n, name='robot',
                         arguments=json.dumps(turn[answered]), status='completed') if answered < len(turn) else
                    dict(id='msg_%d' % n, type='message', role='assistant', status='completed',
                         content=[dict(type='output_text', text='DONE', annotations=[])]))
            response = dict(id='resp_%d' % n, object='response', created_at=int(time.time()), status='completed',
                            model=body.get('model'), output=[item],
                            usage=dict(input_tokens=1, output_tokens=1, total_tokens=2,
                                       input_tokens_details={'cached_tokens': 0}, output_tokens_details={'reasoning_tokens': 0}))
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            for i, (kind, data) in enumerate([('response.created', {'response': {**response, 'status': 'in_progress', 'output': []}}),
                                              ('response.output_item.added', {'output_index': 0, 'item': {**item, 'status': 'in_progress'}}),
                                              ('response.output_item.done', {'output_index': 0, 'item': item}),
                                              ('response.completed', {'response': response})]):
                self.wfile.write(('event: %s\ndata: %s\n\n' % (kind, json.dumps({'type': kind, 'sequence_number': i, **data}))).encode())
            self.wfile.flush()
    return Handler


def host_events(run):
    path = run_path(run, 'host_log', 'codex')
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


@unittest.skipUnless(shutil.which('codex') and shutil.which('node'), 'Codex CLI or node is not installed')
class CodexSegmentResumeTests(unittest.TestCase):
    def test_killed_host_reopens_the_same_thread_and_sends_the_resume_message(self):
        self.continue_after('host')

    def test_a_world_dying_under_a_live_host_continues_too(self):
        self.continue_after('world')

    def continue_after(self, victim):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            t = Path(tmp).resolve(); home = t / 'home'; home.mkdir(); (t / 'codex-home').mkdir()
            requests = []
            # A centralized run: one Controller thread and no delegates.
            harness = json.loads((ROOT / 'configs/harnesses/policy.json').read_text())
            harness.update(engine='codex', topology='centralized', model=STUB['model'], effort=STUB['effort'],
                           record_realtime_video=False)
            (t / 'harness.json').write_text(json.dumps(harness))
            run = prepare(CASE, t / 'batch/stub' / CASE, t / 'harness.json', wall_limit_s=900).resolve()
            task = json.loads((run / 'private/inputs/task.json').read_text())
            arm, camera = sorted(task['arms'])[0], camera_names(task)[0]
            steps = {BOOTSTRAP: [{'op': 'observe', 'data': {'cameras': [camera]}},
                                 {'op': 'move', 'data': {'robot': arm, 'delta_m': [0, 0, .08], 'speed_m_s': .01}}],
                     RESUME: [{'op': 'observe', 'data': {'cameras': [camera]}}]}
            server = ThreadingHTTPServer(('127.0.0.1', 0), controller_stub(requests, steps))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stub = dict(STUB, base_url='http://127.0.0.1:%d' % server.server_port)
            with patch('robofrontier.engines.codex.launch.hidden_skills', lambda: hidden_skills(home=home, repo=t)):
                launch = launch_config(stub, run / 'private/inputs', run_dir=run)
            (run / 'private/inputs/codex.json').write_text(json.dumps(launch))
            import hashlib
            manifest = json.loads((run / 'private/inputs/manifest.json').read_text())
            for name in ('codex.json', 'models.json'):
                manifest['input_sha256']['private/inputs/' + name] = hashlib.sha256((run / 'private/inputs' / name).read_bytes()).hexdigest()
            (run / 'private/inputs/manifest.json').write_text(json.dumps(manifest))
            env = dict(os.environ, CODEX_HOME=str(t / 'codex-home'), HOME=str(home),
                       ROBOFRONTIER_OFFLINE_STUB_TOKEN='local-stub-no-credential')
            log = (t / 'host.log').open('a'); self.addCleanup(log.close)
            command = ['node', str(ROOT / 'robofrontier/engines/codex/codex_policy_host.js'), str(run), str(ROOT), sys.executable]
            try:
                host = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log)
                wait_until(lambda: any(e.get('event') == 'robot_tool_started' and e.get('op') == 'move' for e in host_events(run)),
                           timeout=180, message='the slow move to start')
                time.sleep(2)
                if victim == 'host':
                    host.send_signal(signal.SIGKILL); host.wait()
                else:
                    # The host notices, seals the run with its world already gone and exits.
                    owners = subprocess.run(['pgrep', '-f', 'robofrontier.runtime.pipeline --run-dir ' + str(run)],
                                            capture_output=True, text=True).stdout.split()
                    for pid in owners: os.kill(int(pid), signal.SIGKILL)
                    self.assertEqual(host.wait(timeout=120), 0, (t / 'host.log').read_text()[-2000:])
                    self.assertTrue(any(e.get('event') == 'owner_exited' for e in host_events(run)))
                continued, why = try_continue(run, 'host killed by test')
                self.assertTrue(continued, why)
                store = RuntimeStore(run / 'private/state/runtime.sqlite')
                try:
                    interrupted = store.get('pending_segment')['interrupted']['Controller']
                    thread = store.agent('Controller')['thread_id']
                finally: store.close()
                self.assertEqual(len(interrupted), 1)
                host = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log)
                seen = lambda: [r for r in requests if RESUME in json.dumps(r.get('input', []))]
                wait_until(lambda: len(seen()) >= 2, timeout=180, message='the resumed Controller turn')
                run_path(run, 'stop').write_text('test done\n')
                self.assertEqual(host.wait(timeout=120), 0, (t / 'host.log').read_text()[-2000:])
            finally:
                server.shutdown(); server.server_close()
            events = host_events(run)
            created = [e['thread_id'] for e in events if e.get('event') == 'role_created']
            resumed = [e['thread_id'] for e in events if e.get('event') == 'role_resumed']
            self.assertEqual(created, [thread]); self.assertEqual(resumed, [thread])
            self.assertTrue(any(e.get('event') == 'segment_resumed' and e.get('segment') == 1 for e in events))
            body = json.dumps(seen()[0]['input'])
            self.assertIn(interrupted[0], body)
            # The whole earlier conversation is still in the resumed thread's request.
            self.assertIn(BOOTSTRAP, body)
            store = RuntimeStore(run / 'private/state/runtime.sqlite')
            try:
                self.assertEqual([s['index'] for s in store.get('segments')], [0, 1])
                self.assertEqual(store.actions()[interrupted[0]]['status'], 'failed')
                # STOP sealed the run: a sealed run never continues again.
                self.assertTrue(any(e['kind'] == 'RUN_SEALED' for e in store.events(200)))
                from robofrontier.runtime.segments import retry_eligibility
                self.assertFalse(retry_eligibility(run, store)[0])
            finally: store.close()


if __name__ == '__main__': unittest.main()
