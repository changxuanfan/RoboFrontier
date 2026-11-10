"""Runs use the pinned engine and library versions and refuse others (E6)."""
import re
import subprocess
import unittest
from types import SimpleNamespace

from robofrontier.io import ROOT
from robofrontier.runtime import versions


def cli(output):
    return lambda *args, **kwargs: SimpleNamespace(stdout=output)


class VersionTests(unittest.TestCase):
    def test_the_pins_match_the_lock_file_and_the_docker_image(self):
        lock = (ROOT/'uv.lock').read_text()
        for name, version in versions.LIBRARIES.items():
            self.assertIn(f'name = "{name}"\nversion = "{version}"', lock)
        docker = (ROOT/'docker/Dockerfile').read_text()
        self.assertIn('CLAUDE_CODE_VERSION='+versions.ENGINES['claude'], docker)
        self.assertIn('CODEX_VERSION='+versions.ENGINES['codex'], docker)

    def test_a_different_engine_version_is_refused(self):
        self.assertEqual(versions.engine_version('claude', cli('2.1.316 (Claude Code)\n')), '2.1.316')
        self.assertEqual(versions.engine_version('codex', cli('codex-cli 0.165.0\n')), '0.165.0')
        with self.assertRaisesRegex(ValueError, 'claude 2.1.317'):
            versions.require('claude', cli('2.1.317 (Claude Code)'))
        self.assertEqual(versions.require('codex', cli('codex-cli 0.165.0'))['codex'], '0.165.0')

    def test_claude_runs_without_self_update(self):
        self.assertEqual(versions.ENGINE_ENVIRONMENT['claude'], {'DISABLE_AUTOUPDATER': '1'})


if __name__ == '__main__':
    unittest.main()
