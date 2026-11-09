import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from robofrontier import durable, run_layout


class DurableTests(unittest.TestCase):
    def test_service_runs_the_unified_command_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            (batch/'batch.json').write_text(json.dumps({'status': 'prepared_not_started', 'jobs': [], **run_layout.batch_record()}))
            plist = durable.service(batch, engineering=True, python='/py', environment={'PATH': '/bin'})
            self.assertEqual(plist['ProgramArguments'], ['/py', '-m', 'robofrontier.cli', 'run', str(batch), '--foreground', '--engineering'])
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


class RunDefaultTests(unittest.TestCase):
    """A fresh macOS batch runs under launchd with Interactive priority unless --foreground is given."""

    def dispatch(self, argv, platform):
        from robofrontier import cli
        with patch('sys.platform', platform), patch('robofrontier.durable.submit', return_value={'label': 'x'}) as submit, \
                patch('robofrontier.cli.run', return_value={'status': 'ok'}) as run, \
                patch('robofrontier.benchmark_common.load_env'), patch('builtins.print'):
            cli.main(argv)
        return submit, run

    def test_macos_defaults_to_the_interactive_service(self):
        submit, run = self.dispatch(['run', 'runs/x', '--engineering'], 'darwin')
        submit.assert_called_once_with(Path('runs/x'), engineering=True)
        run.assert_not_called()

    def test_foreground_continue_and_linux_run_in_this_process(self):
        for argv, platform in ((['run', 'runs/x', '--foreground'], 'darwin'), (['run', 'runs/x', '--continue'], 'darwin'),
                               (['run', 'runs/x'], 'linux')):
            submit, run = self.dispatch(argv, platform)
            submit.assert_not_called()
            run.assert_called_once()

    def test_durable_and_foreground_are_exclusive(self):
        with self.assertRaises((ValueError, SystemExit)):
            self.dispatch(['run', 'runs/x', '--durable', '--foreground'], 'darwin')


if __name__ == '__main__':
    unittest.main()
