import json
import tempfile
import unittest
from pathlib import Path

from scripts import verify_frontier_v2 as script


class PreflightReceiptTests(unittest.TestCase):
    def test_each_selection_gets_its_own_receipt_with_its_filter(self):
        with tempfile.TemporaryDirectory() as root:
            dial = script.write_preflight([dict(case_id='dial-1', passed=True)], 'dial', None, root)
            mosaic = script.write_preflight([dict(case_id='mosaic-1', passed=False)], 'mosaic', None, root)
            cases = script.write_preflight([dict(case_id='dial-1', passed=True)], None, ['dial-1'], root)
            self.assertEqual(len({dial, mosaic, cases}), 3)
            self.assertFalse(json.loads(mosaic.read_text())['passed'])
            self.assertEqual(json.loads(mosaic.read_text())['selection'], dict(family='mosaic', cases=None))
            self.assertEqual(json.loads(cases.read_text())['selection'], dict(family=None, cases=['dial-1']))
            self.assertEqual(script.write_preflight([], None, None, root).name, 'oracle-preflight.json')


if __name__ == '__main__':
    unittest.main()
