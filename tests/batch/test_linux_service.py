"""A batch runs as a background service on plain Linux (RunPod), with or without systemd."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from robofrontier.batch import linux
from robofrontier.runtime import layout as run_layout


class LinuxServiceTests(unittest.TestCase):
    def batch(self, folder):
        batch = Path(folder)/'batch'; batch.mkdir()
        (batch/'batch.json').write_text(json.dumps({'status': 'prepared_not_started', 'jobs': [], **run_layout.batch_record()}))
        return batch

    def test_without_systemd_a_setsid_daemon_runs_the_foreground_command_once(self):
        started = []
        def popen(argv, **kwargs):
            started.append((argv, kwargs)); return SimpleNamespace(pid=4321)
        with tempfile.TemporaryDirectory() as folder, patch('sys.platform', 'linux'), \
                patch.dict('os.environ', {'PATH': '/bin', 'OPENAI_API_KEY': 'secret'}, clear=True):
            batch = self.batch(folder)
            record = linux.submit(batch, popen=popen, use_systemd=False)
            argv, kwargs = started[0]
            self.assertEqual(argv[-3:], ['run', str(batch.resolve()), '--foreground'])
            self.assertTrue(kwargs['start_new_session'])
            self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
            self.assertEqual((record['manager'], record['pid']), ('setsid', 4321))
            with self.assertRaises(FileExistsError):
                linux.submit(batch, popen=popen, use_systemd=False)
            continued = linux.submit(batch, continuing=True, popen=popen, use_systemd=False)
            self.assertEqual(started[-1][0][-1], '--continue')
            self.assertTrue(continued['continuing'])

    def test_with_systemd_a_transient_user_service_is_started(self):
        calls = []
        def run(argv, **kwargs):
            calls.append(argv); return SimpleNamespace(returncode=0, stdout='', stderr='')
        with tempfile.TemporaryDirectory() as folder, patch('sys.platform', 'linux'):
            batch = self.batch(folder)
            record = linux.submit(batch, run=run, use_systemd=True)
        self.assertEqual(calls[0][:4], ['systemd-run', '--user', '--collect', '--unit'])
        self.assertEqual(record['manager'], 'systemd-user')
        self.assertTrue(record['unit'].endswith('.service'))


if __name__ == '__main__':
    unittest.main()
