import unittest

from roboteam.analysis import paired


class PairedTests(unittest.TestCase):
    def test_exact_mcnemar_and_holm(self):
        self.assertEqual(paired.mcnemar_exact(0, 8), 2 / 2**8)
        self.assertEqual(paired.mcnemar_exact(5, 6), 1.0)
        self.assertEqual(paired.mcnemar_exact(0, 0), 1.0)
        self.assertEqual(paired.holm([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06])
        self.assertEqual(paired.holm([0.5, 0.9]), [1.0, 1.0])

    def test_compare_counts_tasks_only_one_condition_completes(self):
        results = {
            'A': {'t1': (True, 1.0), 't2': (True, 2.0), 't3': (False, 24.0)},
            'B': {'t1': (True, 2.0), 't2': (False, 24.0), 't3': (False, 24.0)},
        }
        (row,) = paired.compare(results, 'A', ['B'])
        self.assertEqual((row['only_reference'], row['only_condition'], row['p']), (1, 0, 1.0))
        self.assertEqual(paired.speedup(results, 'B', 'A'), 2.0)

    def test_bootstrap_resamples_within_each_type(self):
        types = {'x1': 'x', 'x2': 'x', 'y1': 'y', 'y2': 'y'}
        results = {
            'A': {'x1': (True, 1.0), 'x2': (True, 1.0), 'y1': (False, 24.0), 'y2': (False, 24.0)},
            'B': {t: (True, 2.0) for t in types},
        }
        self.assertEqual(paired.completed_interval(results, types, 'A', resamples=200), (2, 2))
        self.assertEqual(paired.speedup_interval(results, types, 'B', 'A', resamples=200), (2.0, 2.0))


if __name__ == '__main__':
    unittest.main()
