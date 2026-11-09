import tempfile
import unittest
from pathlib import Path

from scripts.run_best5_dial_batch import supervise


class PilotGateTests(unittest.TestCase):
    def batch(self, allow):
        started, results = [], []
        def run(case):
            started.append(case)
            return dict(case_id=case, passed=case != 'pilot')
        with tempfile.TemporaryDirectory() as base:
            code = supervise(['pilot', 'b', 'c'], run, lambda active: None, results, Path(base), 2, allow)
            self.assertTrue((Path(base)/'pilot-needs-review.json').exists())
        return code, sorted(started)

    def test_a_failed_pilot_stops_the_batch(self):
        self.assertEqual(self.batch(False), (1, ['pilot']))

    def test_an_explicit_override_runs_the_remaining_cases(self):
        self.assertEqual(self.batch(True), (1, ['b', 'c', 'pilot']))


if __name__ == '__main__':
    unittest.main()
