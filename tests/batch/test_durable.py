import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from robofrontier.batch import mac as durable
from robofrontier.runtime import layout as run_layout


class DurableTests(unittest.TestCase):
    def test_service_runs_the_unified_command_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            (batch/'batch.json').write_text(json.dumps({'status': 'prepared_not_started', 'jobs': [], **run_layout.batch_record()}))
            plist = durable.service(batch, python='/py', environment={'PATH': '/bin'})
            self.assertEqual(plist['ProgramArguments'], [durable.CAFFEINATE, '-ims', '/py', '-m', 'robofrontier.cli', 'run', str(batch),
                                                         '--foreground'])
            self.assertTrue(plist['StandardOutPath'].startswith(str(batch/'control/durable')))
            self.assertFalse(plist['KeepAlive'])
            self.assertFalse(any('KEY' in k or 'TOKEN' in k for k in durable.PASSED_ENVIRONMENT))

    def test_only_a_fresh_batch_is_submitted_once(self):
        with tempfile.TemporaryDirectory() as tmp, patch('sys.platform', 'darwin'), \
                patch('subprocess.run') as launchctl:
            launchctl.return_value.returncode = 0
            batch = Path(tmp)
            (batch/'batch.json').write_text(json.dumps({'status': 'running', 'jobs': [], **run_layout.batch_record()}))
            with self.assertRaisesRegex(ValueError, 'freshly prepared'):
                durable.submit(batch)
            (batch/'batch.json').write_text(json.dumps({'status': 'prepared_not_started', 'jobs': [], **run_layout.batch_record()}))
            self.assertEqual(durable.submit(batch)['label'], durable.service_label(batch.resolve()))
            with (batch/'control/durable/service.plist').open('rb') as source:
                self.assertEqual(plistlib.load(source)['ProcessType'], 'Interactive')
            with self.assertRaises(FileExistsError):
                durable.submit(batch)

    def test_each_continuation_gets_its_own_job(self):
        with tempfile.TemporaryDirectory() as tmp, patch('sys.platform', 'darwin'), \
                patch('subprocess.run') as launchctl:
            launchctl.return_value.returncode = 0
            batch = Path(tmp)
            (batch/'batch.json').write_text(json.dumps({'status': 'running', 'jobs': [], **run_layout.batch_record()}))
            labels = [durable.submit(batch, continuing=True)['label'] for _ in range(2)]
            base = durable.service_label(batch.resolve())
            self.assertEqual(labels, [base+'.continue-1', base+'.continue-2'])
            with (batch/'control/durable/continue-2/service.plist').open('rb') as source:
                plist = plistlib.load(source)
            self.assertIn('--continue', plist['ProgramArguments']); self.assertIn('--foreground', plist['ProgramArguments'])
            self.assertEqual(plist['ProcessType'], 'Interactive')


class RunDefaultTests(unittest.TestCase):
    """A fresh macOS batch runs under launchd with Interactive priority unless --foreground is given."""

    def dispatch(self, argv, platform):
        from robofrontier import cli
        with patch('sys.platform', platform), patch('robofrontier.batch.mac.submit', return_value={'label': 'x'}) as submit, \
                patch('robofrontier.cli.run', return_value={'status': 'ok'}) as run, \
                patch('robofrontier.batch.prepare.load_env'), patch('builtins.print'):
            cli.main(argv)
        return submit, run

    def test_macos_defaults_to_the_interactive_service(self):
        submit, run = self.dispatch(['run', 'runs/x'], 'darwin')
        submit.assert_called_once_with(Path('runs/x'), continuing=False)
        run.assert_not_called()

    def test_macos_continues_under_the_interactive_service_too(self):
        submit, run = self.dispatch(['run', 'runs/x', '--continue'], 'darwin')
        submit.assert_called_once_with(Path('runs/x'), continuing=True)
        run.assert_not_called()

    def test_foreground_and_linux_run_in_this_process(self):
        for argv, platform in ((['run', 'runs/x', '--foreground'], 'darwin'), (['run', 'runs/x', '--continue', '--foreground'], 'darwin'),
                               (['run', 'runs/x'], 'linux'), (['run', 'runs/x', '--continue'], 'linux')):
            submit, run = self.dispatch(argv, platform)
            submit.assert_not_called()
            run.assert_called_once()

    def test_durable_and_foreground_are_exclusive(self):
        with self.assertRaises((ValueError, SystemExit)):
            self.dispatch(['run', 'runs/x', '--durable', '--foreground'], 'darwin')


if __name__ == '__main__':
    unittest.main()
