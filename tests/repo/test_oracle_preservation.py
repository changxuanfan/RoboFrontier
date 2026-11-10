"""The Oracle's protected files are unchanged, at their moved paths or in git
(scripts/check_oracle_preservation.py). It hashes the whole retained dataset (about 175,000
files, several minutes), so it runs only with ROBOFRONTIER_PRESERVATION_CHECK=1 and the local
snapshot outputs/final/preservation.json."""
import os
import unittest

from robofrontier.tasks.families import ROOT


@unittest.skipUnless(os.environ.get('ROBOFRONTIER_PRESERVATION_CHECK') == '1' and
                     (ROOT/'outputs/final/preservation.json').is_file(), 'opt-in; needs the local snapshot')
class OraclePreservationTests(unittest.TestCase):
    def test_every_protected_file_is_preserved(self):
        from scripts.check_oracle_preservation import check
        result = check()
        self.assertEqual(result['failed'], [])
        self.assertTrue(result['passed'])


if __name__ == '__main__': unittest.main()
