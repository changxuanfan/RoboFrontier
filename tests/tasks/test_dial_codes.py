"""Every Dial case has one fixed private code, and a run uses it without exposing it."""
import json
import tempfile
import unittest
from pathlib import Path

from robofrontier.tasks.dial import alphabet
from robofrontier.tasks.families import dial_code, prepare, read, ROOT, RELEASE


class DialCodeTests(unittest.TestCase):
    def test_every_dial_case_has_a_valid_code(self):
        release = read(ROOT/RELEASE)
        for case in release['families']['dial']['gpt']:
            task = read(ROOT/case['directory']/'task.json')
            code = dial_code(case['id'])
            self.assertEqual(len(code), len(task['dials']))
            self.assertTrue(set(code) <= set(alphabet(task)))

    @unittest.skipUnless((ROOT/'benchmark/dial/dial-best5-n04-d1/assets').is_dir(), 'Generated scene assets missing')
    def test_a_prepared_run_uses_the_release_code_privately(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)/'run'
            prepare('dial-best5-n04-d1', run)
            stored = json.loads((run/'private/inputs/suite-code.json').read_text())
            self.assertEqual(stored, {'code_symbols': dial_code('dial-best5-n04-d1')})
            for path in (run/'public').rglob('*'):
                if path.is_file() and path.suffix in ('.json', '.md', '.txt'):
                    self.assertNotIn('dial_codes', path.read_text(), path)


if __name__ == '__main__':
    unittest.main()
