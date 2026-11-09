import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_codex_cli


class CodexCliCheckTests(unittest.TestCase):
    def test_check_uses_a_private_codex_home_and_restores_the_environment(self):
        seen = {}
        def fake_run(command, **options):
            seen['env'] = options.get('env')
            seen['launch_home'] = os.environ.get('CODEX_HOME')
            return subprocess.CompletedProcess(command, 1, '', 'stopped by the test')
        with tempfile.TemporaryDirectory() as output, \
                mock.patch.dict(os.environ, {'CODEX_HOME': '/operator/home'}), \
                mock.patch.object(check_codex_cli, 'launch_config', return_value={}), \
                mock.patch.object(check_codex_cli.subprocess, 'run', side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, 'stopped by the test'):
                check_codex_cli.check(output)
            home = Path(output).absolute()/'codex-home'
            self.assertEqual(seen['env']['CODEX_HOME'], str(home))
            self.assertEqual(seen['launch_home'], str(home))
            self.assertTrue(home.is_dir())
            self.assertEqual(os.environ['CODEX_HOME'], '/operator/home')


if __name__ == '__main__':
    unittest.main()
