import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def flat(value, prefix=''):
    out = {}
    for key, item in value.items():
        if isinstance(item, dict):
            out.update(flat(item, prefix+key+'.'))
        else:
            out[prefix+key] = item
    return out


class ConfigsReadmeTests(unittest.TestCase):
    def test_frontier_v2_harness_row_names_every_difference_from_the_default(self):
        default = flat(json.loads((ROOT/'configs/harness.json').read_text()))
        v2 = flat(json.loads((ROOT/'configs/harness-frontier-v2.json').read_text()))
        differences = {key for key in default.keys() | v2.keys() if default.get(key) != v2.get(key)}
        row = next(line for line in (ROOT/'configs/README.md').read_text().splitlines()
                   if line.startswith('| `harness-frontier-v2.json`'))
        first = row.split('The first differs from `harness.json`')[1].split(';')[0]
        self.assertEqual(set(re.findall(r'`([a-z_.]+)`', first)), differences)


if __name__ == '__main__':
    unittest.main()
