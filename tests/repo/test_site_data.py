"""The project page's task data is current with the release and carries only public facts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import site_data

ROOT = Path(__file__).resolve().parents[2]


class SiteTaskDataTests(unittest.TestCase):
    def test_committed_task_data_matches_the_release_and_has_no_private_fields(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(site_data, 'SITE', Path(folder)), \
                patch('mujoco.mj_step', side_effect=AssertionError('No physics')):
            generated = site_data.tasks().read_text()
        self.assertEqual(generated, (ROOT/'site/data/tasks.json').read_text())
        rows = json.loads(generated)['tasks']
        self.assertEqual(len({row['id'] for row in rows}), 36)
        for family in site_data.FAMILIES:
            self.assertEqual(sum(row['family'] == family for row in rows), 9)
        for forbidden in ('code_symbols', 'private/inputs', '/Users/', '/home/', 'oracle_solution'):
            self.assertNotIn(forbidden, generated)


if __name__ == '__main__':
    unittest.main()
