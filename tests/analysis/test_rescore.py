"""The current evaluator gives finished runs the scores they were given (T6)."""
import os
import unittest
from pathlib import Path

from robofrontier.analysis.rescore import rescore
from robofrontier.io import ROOT

# Run data never lives in the repository; this check runs where the finished runs are.
RUNS = Path(os.environ.get('ROBOFRONTIER_RESCORE_RUNS', ROOT/'runs/compare/opus-mosaic-l3-20261110/opus_subscription'))


@unittest.skipUnless(RUNS.is_dir(), 'Finished runs to rescore are not on this host')
class RescoreTests(unittest.TestCase):
    def test_finished_runs_keep_their_goal_counts(self):
        runs = sorted(p for p in RUNS.iterdir() if (p/'private/outputs/evaluation.json').is_file())
        self.assertTrue(runs)
        for run in runs:
            with self.subTest(run=run.name):
                result = rescore(run)
                self.assertEqual(result['rescored'], result['recorded'])


if __name__ == '__main__':
    unittest.main()
