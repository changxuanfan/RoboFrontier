import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from roboteam.runtime import layout as run_layout


class RunLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run = Path(self.temp.name)/'run'

    def tearDown(self):
        self.temp.cleanup()

    def test_a_run_resolves_its_paths(self):
        self.assertEqual(run_layout.manifest_record(), {'layout': 'run-v6'})
        self.assertEqual(run_layout.path(self.run, 'stop'), self.run/'private/state/control/STOP')
        self.assertEqual(run_layout.path(self.run, 'skills_file'), self.run/'workspace/skills.md')
        self.assertEqual(run_layout.path(self.run, 'host_log'), self.run/'private/logs/host.jsonl')
        self.assertEqual(run_layout.path(self.run, 'segment_inputs'), self.run/'private/inputs/segments')
        self.assertEqual(run_layout.path(self.run, 'segment_outputs'), self.run/'private/outputs/segments')
        self.assertEqual(run_layout.for_store(self.run/'private/state/runtime.sqlite', 'admin_log'),
                         self.run/'private/logs/admin-client.log')
        with self.assertRaises(KeyError):
            run_layout.path(self.run, 'no_such_key')

    def test_a_batch_resolves_its_paths(self):
        batch = Path(self.temp.name)/'batch'
        self.assertEqual(run_layout.batch_record(), {'layout': 'batch-v2'})
        self.assertEqual(run_layout.batch_path(batch, 'stop'), batch/'control/STOP')
        self.assertEqual(run_layout.batch_path(batch, 'codex_init_log'), batch/'logs/codex-initialize.log')

    def test_the_node_hosts_read_the_same_paths_from_the_command_line(self):
        out = subprocess.run([sys.executable, '-m', 'roboteam.runtime.layout', str(self.run)],
                             capture_output=True, text=True, check=True).stdout
        value = json.loads(out)
        self.assertEqual(value['layout'], 'run-v6')
        self.assertEqual(value['paths']['owner_log'], 'private/logs/owner.log')


if __name__ == '__main__':
    unittest.main()
