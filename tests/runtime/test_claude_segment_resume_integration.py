"""The real Claude route continues a run after its host was killed mid-action (loopback stub model).

The engine runner runs in a child process. A stub model plays the Controller: it observes
and starts a slow move, the test kills the child's process group during that move, the
world closes by itself, the next segment is prepared, and the runner is started again.
It must resume the same Claude session and send the frozen resume message naming the
interrupted move. No provider requests or genuine credentials are used.
"""
import hashlib
import http.server
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

from engines.test_claude_adaptive_integration import StubModel
from runtime.test_run_segments_integration import wait_until
from robofrontier.runtime.layout import path as run_path
from robofrontier.runtime.segments import try_continue
from robofrontier.runtime.store import RuntimeStore
from robofrontier.tasks.scene import camera_names
from robofrontier.batch.claude_prepare import prepare_batch

ROOT = Path(__file__).resolve().parents[2]
CASE = 'mosaic-a04-6x12-d1'
RESUME = 'The host stopped unexpectedly'
CHILD = ('import json,os,sys;from robofrontier.engines.claude.run import run_task;'
         "env={'PATH':os.environ['PATH'],'HOME':os.environ['HOME'],'FAKE_KEY':'synthetic',"
         # The rendering backend, as robofrontier run passes it (EGL on a Linux GPU host).
         "**{k:os.environ[k] for k in ('MUJOCO_GL','PYOPENGL_PLATFORM') if k in os.environ}};"
         'print(json.dumps(run_task(sys.argv[1],env,wall_limit_s=600,startup_timeout_s=90,poll_s=.1)))')


class SlowMoveModel(StubModel):
    requests = []
    camera = robot = None

    def choose_tool(self, names, text, blocks, has_result):
        if not names or RESUME in text: return None, None
        if has_result:
            if blocks[-1].get('tool_use_id') == 'toolu_observe':
                return {'op': 'move', 'data': {'robot': self.robot, 'delta_m': [0, 0, .08], 'acceleration_m_s2': 2., 'angular_speed_rad_s': .6, 'angular_acceleration_rad_s2': 5., 'speed_m_s': .01}}, 'toolu_move'
            return None, None
        if 'experiment has started' in text:
            return {'op': 'observe', 'data': {'cameras': [self.camera]}}, 'toolu_observe'
        return None, None


@unittest.skipUnless(shutil.which('claude'), 'Claude Code CLI is not installed')
class ClaudeSegmentResumeTests(unittest.TestCase):
    def test_killed_host_resumes_the_same_session_with_the_resume_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve() / 'batch'
            # A local fake model with a fake key: nothing to expose (claude_prepare.exposed_api_keys).
            with patch('robofrontier.batch.claude_prepare.exposed_api_keys', return_value=[]):
                prepare_batch(base, ['opus'], cases=[CASE], topology='centralized')
            run = base / 'opus' / CASE
            task = json.loads((run / 'private/inputs/task.json').read_text())
            SlowMoveModel.camera, SlowMoveModel.robot = camera_names(task)[0], sorted(task['arms'])[0]
            SlowMoveModel.requests.clear()
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), SlowMoveModel)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            launch = run / 'private/inputs/claude.json'
            data = json.loads(launch.read_text())
            data['profile'].update(base_url='http://127.0.0.1:%d' % server.server_port, env_key='FAKE_KEY')
            launch.write_text(json.dumps(data))
            manifest = run / 'private/inputs/manifest.json'; frozen = json.loads(manifest.read_text())
            frozen['input_sha256']['private/inputs/claude.json'] = hashlib.sha256(launch.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(frozen))
            log = (base / 'host.log').open('a'); self.addCleanup(log.close)
            child = lambda: subprocess.Popen([sys.executable, '-c', CHILD, str(run)], cwd=ROOT, stdout=log, stderr=log,
                                             env=dict(os.environ, PYTHONPATH=str(ROOT)), start_new_session=True)
            store = lambda: RuntimeStore(run / 'private/state/runtime.sqlite')

            def moving():
                s = store()
                try: return [i for i, a in s.actions().items() if a['status'] == 'running']
                finally: s.close()
            try:
                host = child()
                running = wait_until(moving, timeout=180, message='the slow move to start')
                time.sleep(1)
                # The whole host, including its Claude CLI, dies; the world has its own session.
                os.killpg(host.pid, signal.SIGKILL); host.wait()
                continued, why = try_continue(run, 'host killed by test')
                self.assertTrue(continued, why)
                s = store()
                try: session = s.agent('Controller')['thread_id']
                finally: s.close()
                host = child()
                seen = lambda: [r for r in SlowMoveModel.requests if RESUME in json.dumps(r.get('messages', []))]
                wait_until(seen, timeout=180, message='the resumed Controller turn')
                run_path(run, 'stop').write_text('test done\n')
                host.wait(timeout=120)
            finally:
                server.shutdown(); server.server_close()
            body = json.dumps(seen()[0]['messages'])
            self.assertIn(running[0], body)
            # The resumed turn carries the whole earlier conversation of the same session.
            self.assertIn('experiment has started', body)
            self.assertIn('toolu_move', body)
            transcripts = list((run_path(run, 'engine_config') / 'projects').rglob(session + '.jsonl'))
            self.assertEqual(len(transcripts), 1)
            self.assertIn(RESUME, transcripts[0].read_text())
            s = store()
            try:
                self.assertEqual([x['index'] for x in s.get('segments')], [0, 1])
                self.assertEqual(s.actions()[running[0]]['status'], 'failed')
                self.assertEqual(s.agent('Controller')['thread_id'], session)
            finally: s.close()


if __name__ == '__main__': unittest.main()
