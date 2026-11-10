"""A run continues in a second segment after its world process is killed (no model calls).

The test prepares a real run, starts its real world process, moves an arm, kills the
process with SIGKILL, prepares segment 1 and starts a new world process. The new world
starts from the last recorded pose with the simulation clock continuing, the action that
was running is recorded as interrupted, and the trial resumes with downtime excluded.
A world whose host disappears closes by itself.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from robofrontier.runtime.pipeline_client import client_call
from robofrontier.runtime.layout import path as run_path
from robofrontier.runtime.segments import motion_dirs, output_dir, owner_released, prepare_retry, retry_eligibility
from robofrontier.runtime.setup import verify_inputs
from robofrontier.runtime.store import RuntimeStore
from robofrontier.tasks.scene import camera_names
from test_engine_parity import prepared

ROOT = Path(__file__).resolve().parents[1]


def owner_command(run):
    return [sys.executable, '-m', 'robofrontier.runtime.pipeline', '--run-dir', str(run), '--hidden']


def wait_until(check, timeout=120, message='condition'):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value: return value
        time.sleep(.2)
    raise AssertionError('Timed out waiting for ' + message)


class SegmentIntegrationTests(unittest.TestCase):
    def store(self, run): return RuntimeStore(run / 'private/state/runtime.sqlite')

    def attached(self, run, segment):
        def ready():
            store = self.store(run)
            try:
                url = json.loads((run / 'private/state/connections/Meta.json').read_text()).get('url')
                return url and store.get('execution_owner_attached') and store.get('segment', 0) == segment
            finally: store.close()
        wait_until(ready, message='world of segment %d' % segment)

    def test_killed_world_continues_from_its_last_pose_in_the_same_run(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            run = prepared(Path(tmp).resolve(), 'codex').resolve()
            meta, controller = (run / 'private/state/connections' / n for n in ('Meta.json', 'Controller.json'))
            log = (run / 'owner-test.log').open('a'); self.addCleanup(log.close)
            owner = subprocess.Popen(owner_command(run), cwd=ROOT, stdout=log, stderr=log)
            try:
                self.attached(run, 0)
                client_call(meta, 'bind', {'actor': 'Controller', 'thread_id': 'thread-1'}, 'bind-1')
                self.assertTrue(client_call(meta, 'start', {}, 'start-1')['started'])
                task = json.loads((run / 'private/inputs/task.json').read_text())
                arm, camera = sorted(task['arms'])[0], camera_names(task)[0]
                tcp = client_call(controller, 'observe', {'cameras': [camera]}, 'obs-1')['observation']['robot'][arm]['tcp_m']
                moving = client_call(controller, 'move', {'robot': arm, 'target_m': [tcp[0], tcp[1], tcp[2] + .08],
                                                          'speed_m_s': .01, 'wait': False, 'cameras': []}, 'move-1')
                self.assertEqual(moving['execution_status'], 'running')
                # Motion is flushed in 2 s chunks; kill once one is on disk and the arm still moves.
                wait_until(lambda: json.loads((run / 'private/outputs/motion/stream.json').read_text())['frames'] > 0,
                           message='a motion chunk')
                self.assertEqual(client_call(controller, 'job', {'call_id': 'move-1'}, 'job-1')['execution']['status'], 'running')
            finally:
                owner.send_signal(signal.SIGKILL); owner.wait()
            store = self.store(run)
            try:
                self.assertEqual(store.get('lifecycle'), 'running')
                self.assertEqual(retry_eligibility(run, store), (True, None))
                note = prepare_retry(run, store, 'world process killed')
                self.assertEqual(note['segment'], 1)
                self.assertEqual(verify_inputs(run), [])
                action = store.actions()['move-1']
                self.assertEqual(action['status'], 'failed'); self.assertTrue(action['interrupted_by_segment'])
                self.assertEqual(store.get('pending_segment')['interrupted'], {'Controller': ['move-1']})
                self.assertEqual(store.get('lifecycle'), 'resuming')
                restored_sim = note['source_sim_s']
            finally: store.close()

            # The second world is started by a parent that then disappears, like a host crash.
            parent = subprocess.Popen([sys.executable, '-c', 'import subprocess,sys,time;'
                                       'p=subprocess.Popen(sys.argv[1:]);time.sleep(3600)', *owner_command(run)],
                                      cwd=ROOT, stdout=log, stderr=log)
            try:
                self.attached(run, 1)
                answer = client_call(meta, 'resume', {}, 'resume-1')
                self.assertTrue(answer['resumed']); self.assertEqual(answer['segment'], 1)
                self.assertIn('move-1', answer['messages']['Controller'])
                self.assertIn('%.2f' % restored_sim, answer['messages']['Controller'])
                observed = client_call(controller, 'observe', {'cameras': [camera]}, 'obs-2')['observation']
                self.assertGreaterEqual(observed['sim_time_s'], restored_sim)
                self.assertLess(observed['sim_time_s'], restored_sim + 30)
                store = self.store(run)
                try:
                    self.assertEqual(store.get('lifecycle'), 'running')
                    segments = store.get('segments')
                    self.assertEqual([s['index'] for s in segments], [0, 1])
                    self.assertGreater(segments[1]['downtime_s'], 0)
                    self.assertEqual(store.get('downtime_s'), segments[1]['downtime_s'])
                finally: store.close()
                self.assertEqual(motion_dirs(run), [run / 'private/outputs/motion', output_dir(run, 1) / 'motion'])
                # A new action works in the continued world.
                again = client_call(controller, 'move', {'robot': arm, 'target_m': [tcp[0], tcp[1], tcp[2] + .02],
                                                         'speed_m_s': .05, 'wait': True, 'cameras': []}, 'move-2')
                self.assertEqual(again['execution']['status'], 'completed')
            finally:
                parent.send_signal(signal.SIGKILL); parent.wait()
            # Its host is gone: the world closes by itself and records the interruption.
            def closed():
                store = self.store(run)
                try: return store.get('lifecycle') == 'interrupted'
                finally: store.close()
            wait_until(closed, timeout=60, message='world to close after its host vanished')
            # Closing finishes once the world lock is released; only then are its files final.
            wait_until(lambda: owner_released(run), timeout=60, message='world process to exit')
            store = self.store(run)
            try:
                self.assertTrue(any(e['kind'] == 'HOST_LOST' for e in store.events(50)))
                self.assertEqual(retry_eligibility(run, store), (False, 'already continued once'))
            finally: store.close()
            self.assertTrue((output_dir(run, 1) / 'interruption-evaluation.json').is_file())


if __name__ == '__main__': unittest.main()
