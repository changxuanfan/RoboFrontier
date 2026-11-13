"""Old conversation errors must not cause a completed robot turn to be retried."""
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from robofrontier.engines.antigravity.native_turn import completed

FINAL = b'\x08\x0f\x20\x03\xa2\x01\x07\x0a\x05READY'


class NativeCompletionTests(unittest.TestCase):
    def test_historical_error_does_not_poison_a_new_settled_response(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home/'conversations').mkdir()
            driver = SimpleNamespace(home=home, session='test')
            with sqlite3.connect(home/'conversations/test.db') as db:
                db.execute('CREATE TABLE steps(idx INTEGER,step_type INTEGER,status INTEGER,step_payload BLOB)')
                db.executemany('INSERT INTO steps VALUES(?,?,?,?)',
                    [(0, 17, 3, b''), (1, 14, 3, b''), (2, 15, 3, FINAL)])
            proof = completed(driver, 1, 'READY\n')
            self.assertTrue(proof['native_final_response_verified'])
            self.assertEqual(proof['native_error_message_steps'], 0)
            # No new turn cannot be mistaken for a new successful response.
            self.assertIsNone(completed(driver, 3, 'READY'))
            self.assertIsNone(completed(driver, 1, 'a stale response'))
            with sqlite3.connect(home/'conversations/test.db') as db:
                db.execute('UPDATE steps SET status=2 WHERE idx=2')
            self.assertIsNone(completed(driver, 1, 'READY'))


if __name__ == '__main__':
    unittest.main()
