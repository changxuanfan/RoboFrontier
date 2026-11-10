import ast
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ScriptChecksTests(unittest.TestCase):
    def test_scripts_guard_evidence_with_raises_not_asserts(self):
        """`python -O` strips assert statements; operator checks must survive it."""
        names = subprocess.run(['git', 'ls-files', 'scripts/*.py'], capture_output=True, text=True, cwd=ROOT,
                               check=True).stdout.split()
        found = [f'{name}:{node.lineno}' for name in names
                 for node in ast.walk(ast.parse((ROOT/name).read_text())) if isinstance(node, ast.Assert)]
        self.assertEqual(found, [])


if __name__ == '__main__':
    unittest.main()
