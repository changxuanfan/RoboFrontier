"""Opt-in standing-team native CLI/MuJoCo checks using a local scripted endpoint."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import unittest

from test_claude_parallel_physics_smoke import CompactRequests
from test_claude_standing_team_integration import StandingModel
from robofrontier.batch.engineering_batch import run_batch
from robofrontier.runtime.store import RuntimeStore
from robofrontier.batch.claude_benchmark import prepare_draft


class PhysicalStandingModel(StandingModel):
    requests = CompactRequests()
    observed = set()

    def choose_tool(self, names, text, blocks, has_result):
        messages = json.dumps(self.request_body.get('messages', []))
        matches = re.findall(r'Your current runtime role is ([A-Za-z][A-Za-z0-9_-]*)', messages)
        if names and matches and matches[0] == 'A':
            with self.steps_lock:
                if 'A' not in self.observed:
                    self.observed.add('A')
                    return {'op':'observe','data':{'cameras':['global']},'views':['global']}, 'toolu_observe'
        return super().choose_tool(names, text, blocks, has_result)


@unittest.skipUnless(os.environ.get('ROBOFRONTIER_PHYSICS_STANDING') == '1' and shutil.which('claude'),
                     'Opt-in requires Claude CLI, current scene assets and a native renderer')
class StandingPhysicsSmokeTests(unittest.TestCase):
    def test_both_topologies_run_real_world_mailboxes_images_actions_and_seal(self):
        for topology in ('hierarchical', 'peer'):
            with self.subTest(topology=topology):
                directory = Path(tempfile.mkdtemp(prefix='claude-standing-physics-'))
                server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), PhysicalStandingModel)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                PhysicalStandingModel.steps.clear()
                PhysicalStandingModel.observed.clear()
                PhysicalStandingModel.requests.clear()
                try:
                    batch = directory/'batch'
                    prepare_draft(batch, ['haiku'], cases=['transport-a04-d1'], topology=topology)
                    run = batch/'haiku/transport-a04-d1'
                    launch = run/'private/inputs/claude.json'
                    data = json.loads(launch.read_text())
                    data['profile'].update(base_url=f'http://127.0.0.1:{server.server_port}', env_key='FAKE_KEY')
                    launch.write_text(json.dumps(data))
                    manifest = run/'private/inputs/manifest.json'
                    frozen = json.loads(manifest.read_text())
                    frozen['input_sha256']['private/inputs/claude.json'] = hashlib.sha256(launch.read_bytes()).hexdigest()
                    manifest.write_text(json.dumps(frozen))
                    env = {k:os.environ[k] for k in ('PATH','HOME','LANG','LC_ALL','TMPDIR','MUJOCO_GL') if k in os.environ}
                    env['FAKE_KEY'] = 'synthetic'
                    result = run_batch(batch, env, parallel=1, wall_limit_s=20, startup_timeout_s=180,
                                       startup_interval_s=0)
                    self.assertFalse(result['scored'])
                    self.assertIn(result['status'], ('closed','needs_review'))
                    detail = json.loads((run/'private/outputs/claude-engineering-status.json').read_text())
                    self.assertEqual(detail['reason'], 'wall_limit', detail)
                    self.assertTrue(detail['seal']['sealed'], detail)
                    self.assertEqual(detail['seal']['unresolved_action_ids'], [])
                    self.assertFalse(detail['owner_alive'], detail)
                    self.assertTrue(any(PhysicalStandingModel.requests), 'No robot image reached the local endpoint')
                    store = RuntimeStore(run/'private/state/runtime.sqlite')
                    try:
                        agents = {a:v for a,v in store.agents().items() if v['kind'] != 'manager'}
                        expected = {'A','B','C','D'} | ({'Controller'} if topology == 'hierarchical' else set())
                        self.assertEqual(set(agents), expected)
                        self.assertEqual(len({a['thread_id'] for a in agents.values()}), len(expected))
                        self.assertTrue(all(not a['ready'] for a in agents.values()))
                        self.assertTrue(all('Synthetic standing milestone' in a['note'] for a in agents.values()))
                        actions = list(store.actions().values())
                        self.assertEqual(len(actions), 1, actions)
                        self.assertEqual(actions[0]['arm'], 'A')
                        self.assertEqual(actions[0]['status'], 'completed')
                        self.assertTrue(store.db.execute('SELECT count(*) FROM messages').fetchone()[0])
                        self.assertTrue(store.db.execute("SELECT count(*) FROM wakes WHERE status IN ('sent','observed')").fetchone()[0])
                    finally:
                        store.close()
                    print('Stopped native standing-team evidence retained:', directory, flush=True)
                finally:
                    server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
