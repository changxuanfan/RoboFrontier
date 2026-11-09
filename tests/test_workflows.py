import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT/'.github/workflows').glob('*.yml'))


class WorkflowTests(unittest.TestCase):
    def test_every_action_is_pinned_to_a_commit_with_its_version(self):
        uses = [(path.name, line.strip()) for path in WORKFLOWS for line in path.read_text().splitlines()
                if re.match(r'\s*(-\s+)?uses:', line)]
        self.assertTrue(uses)
        loose = [entry for entry in uses
                 if not re.fullmatch(r'(-\s+)?uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+', entry[1])]
        self.assertEqual(loose, [])


if __name__ == '__main__':
    unittest.main()
