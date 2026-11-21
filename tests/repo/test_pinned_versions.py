"""Each pinned version is written once in code; every other mention must agree with it.

roboteam/runtime/run/versions.py holds the harness CLI versions and the library versions,
pyproject.toml holds the ruff version. The Dockerfile, the lock file and the guides repeat
them for the reader; this test fails on any that was not updated.
"""

import re
import tomllib
import unittest
from pathlib import Path

from roboteam.runtime.run import versions

ROOT = Path(__file__).resolve().parents[2]
# How the guides name a harness CLI with its version.
MENTIONS = {
    'claude': r'(?:claude-code@|Claude Code |CLAUDE_CODE_VERSION=)(\d+\.\d+\.\d+)',
    'codex': r'(?:@openai/codex@|Codex |CODEX_VERSION=)(\d+\.\d+\.\d+)',
}


def guides():
    files = [
        ROOT / 'README.md',
        *sorted((ROOT / 'docs').rglob('*.md')),
        *sorted((ROOT / '.github').rglob('*.md')),
    ]
    # The changelog is history: it may name versions of earlier releases.
    return [path for path in files if path.name != 'changelog.md']


class PinnedVersionTests(unittest.TestCase):
    def test_the_container_image_installs_the_pinned_clis(self):
        dockerfile = (ROOT / 'docker/Dockerfile').read_text()
        for harness, pattern in MENTIONS.items():
            self.assertEqual(set(re.findall(pattern, dockerfile)), {versions.HARNESSES[harness]}, harness)

    def test_the_guides_name_the_pinned_clis(self):
        wrong = []
        for path in guides():
            text = path.read_text()
            for harness, pattern in MENTIONS.items():
                for found in re.finditer(pattern, text):
                    if found.group(1) != versions.HARNESSES[harness]:
                        line = text.count('\n', 0, found.start()) + 1
                        wrong.append(f'{path.relative_to(ROOT)}:{line} says {found.group(0)}')
        self.assertEqual(wrong, [], 'pinned: ' + str(versions.HARNESSES))

    def test_the_lock_file_has_the_pinned_libraries(self):
        locked = {
            package['name']: package['version']
            for package in tomllib.loads((ROOT / 'uv.lock').read_text())['package']
        }
        for name, version in versions.LIBRARIES.items():
            self.assertEqual(locked.get(name), version, name)

    def test_ruff_is_named_only_in_pyproject(self):
        project = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        self.assertTrue(any(entry.startswith('ruff==') for entry in project['dependency-groups']['dev']))
        files = [*guides(), *sorted((ROOT / '.github/workflows').glob('*.yml'))]
        wrong = [str(path.relative_to(ROOT)) for path in files if re.search(r'ruff@\d', path.read_text())]
        self.assertEqual(wrong, [], 'use .venv/bin/ruff, which uv sync installs at the pinned version')


if __name__ == '__main__':
    unittest.main()
