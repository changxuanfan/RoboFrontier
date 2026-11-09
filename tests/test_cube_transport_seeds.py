import itertools
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LegacyOrderSeedTests(unittest.TestCase):
    def test_every_coinciding_order_seed_is_documented(self):
        readme = ' '.join((ROOT/'configs/suites/cube_transport_cylinders/README.md').read_text().split())
        found = []
        for collection in ('cube_transport', 'cube_transport_cylinders'):
            for environment in sorted((ROOT/'configs/tasks'/collection).iterdir()):
                orders = [json.loads((environment/f'seed-{seed}.json').read_text())['orders'] for seed in range(3)]
                for a, b in itertools.combinations(range(3), 2):
                    if orders[a] == orders[b]:
                        found.append((collection, environment.name, a, b))
                        self.assertIn(f'`{environment.name}` seed-{a} and seed-{b} orders are identical', readme)
        self.assertEqual({(name, a, b) for _, name, a, b in found}, {('line-03', 1, 2)})


if __name__ == '__main__':
    unittest.main()
