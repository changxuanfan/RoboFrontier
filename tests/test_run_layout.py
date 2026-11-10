import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from robofrontier.runtime import layout as run_layout


class RunLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run = Path(self.temp.name)/'run'
        (self.run/'private/inputs').mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def manifest(self, value):
        (self.run/'private/inputs/manifest.json').write_text(value if isinstance(value, str) else json.dumps(value))

    def test_a_run_without_a_recorded_layout_uses_the_legacy_locations(self):
        self.manifest({'engine': 'claude'})
        self.assertEqual(run_layout.layout(self.run), 'run-v3')
        self.assertEqual(run_layout.path(self.run, 'stop'), self.run/'STOP')
        self.assertEqual(run_layout.path(self.run, 'host_log'), self.run/'private/outputs/claude-host.jsonl')
        self.assertEqual(run_layout.path(self.run, 'host_log', 'codex'), self.run/'private/outputs/codex-host.jsonl')
        with self.assertRaises(KeyError):
            run_layout.path(self.run, 'skills_file')

    def test_a_new_run_resolves_its_recorded_paths(self):
        self.manifest({'engine': 'codex', **run_layout.manifest_record('codex')})
        self.assertEqual(run_layout.layout(self.run), 'run-v6')
        self.assertEqual(run_layout.path(self.run, 'stop'), self.run/'private/state/control/STOP')
        self.assertEqual(run_layout.path(self.run, 'skills_file'), self.run/'workspace/skills.md')
        self.assertEqual(run_layout.paths(self.run)['host_log'], 'private/logs/host.jsonl')
        self.assertEqual(run_layout.for_store(self.run/'private/state/runtime.sqlite', 'admin_log'),
                         self.run/'private/logs/admin-client.log')

    def test_recorded_paths_must_stay_inside_the_run(self):
        record = run_layout.manifest_record('claude')
        for bad in ('/tmp/STOP', '../STOP', 'private/../../STOP', '', 5):
            record['layout_paths']['stop'] = bad
            self.manifest(record)
            with self.assertRaises(run_layout.LayoutError):
                run_layout.path(self.run, 'stop')
        (self.run/'outside').symlink_to(Path(self.temp.name))
        record['layout_paths']['stop'] = 'outside/STOP'
        self.manifest(record)
        with self.assertRaises(run_layout.LayoutError):
            run_layout.path(self.run, 'stop')

    def test_new_runs_record_where_their_segments_live(self):
        record = run_layout.manifest_record('codex')
        self.assertEqual(record['layout_paths']['segment_inputs'], 'private/inputs/segments')
        self.assertEqual(record['layout_paths']['segment_outputs'], 'private/outputs/segments')

    def test_an_unreadable_or_unknown_manifest_fails_instead_of_falling_back(self):
        for broken in ('{not json', '[1, 2]', json.dumps({'layout': 'run-v9', 'layout_paths': {}}),
                       json.dumps({'layout': 'run-v6', 'layout_paths': 'STOP'})):
            self.manifest(broken)
            with self.assertRaises(run_layout.LayoutError):
                run_layout.path(self.run, 'stop')

    def test_batches_resolve_legacy_and_recorded_layouts(self):
        batch = Path(self.temp.name)/'batch'
        batch.mkdir()
        self.assertEqual(run_layout.batch_path(batch, 'stop'), batch/'STOP')
        (batch/'batch.json').write_text(json.dumps({'jobs': []}))
        self.assertEqual(run_layout.batch_path(batch, 'engineering_status'), batch/'engineering-status.json')
        (batch/'batch.json').write_text(json.dumps({'jobs': [], **run_layout.batch_record()}))
        self.assertEqual(run_layout.batch_path(batch, 'stop'), batch/'control/STOP')
        self.assertEqual(run_layout.batch_path(batch, 'codex_init_log'), batch/'logs/codex-initialize.log')
        (batch/'batch.json').write_text('{broken')
        with self.assertRaises(run_layout.LayoutError):
            run_layout.batch_path(batch, 'stop')

    def test_the_node_hosts_read_the_same_paths_from_the_command_line(self):
        self.manifest({'engine': 'codex', **run_layout.manifest_record('codex')})
        out = subprocess.run([sys.executable, '-m', 'robofrontier.runtime.layout', str(self.run)],
                             capture_output=True, text=True, check=True).stdout
        value = json.loads(out)
        self.assertEqual(value['layout'], 'run-v6')
        self.assertEqual(value['paths']['owner_log'], 'private/logs/owner.log')


if __name__ == '__main__':
    unittest.main()
