import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ScriptChecksTests(unittest.TestCase):
    def test_scripts_guard_evidence_with_raises_not_asserts(self):
        """`python -O` strips assert statements; operator checks must survive it."""
        names = subprocess.run(['git', 'ls-files', 'scripts/*.py'], capture_output=True, text=True, cwd=ROOT,
                               check=True).stdout.split()
        found = [f'{name}:{node.lineno}' for name in names
                 for node in ast.walk(ast.parse((ROOT/name).read_text())) if isinstance(node, ast.Assert)]
        self.assertEqual(found, [])

    def test_movie_validation_still_fails_under_optimization(self):
        code = '''
import json
from unittest import mock
from scripts import export_relay_edited as m
probe = json.dumps({"streams": [{"nb_frames": "9", "r_frame_rate": "30/1"}]})
with mock.patch.object(m.subprocess, "check_output", return_value=probe):
    try:
        m.validate_movie("missing.mp4", 10, 30)
    except ValueError:
        raise SystemExit(0)
raise SystemExit("validate_movie accepted a wrong frame count")
'''
        result = subprocess.run([sys.executable, '-O', '-c', code], cwd=ROOT, capture_output=True, text=True,
                                env={**os.environ, 'PYTHONPATH': str(ROOT)})
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
