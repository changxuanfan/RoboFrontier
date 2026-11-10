"""A served client answers each request as the one-shot command would (E3)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from robofrontier.io import ROOT


class ServeTests(unittest.TestCase):
    def test_requests_are_answered_line_by_line_with_the_command_output(self):
        with tempfile.TemporaryDirectory() as folder:
            connection = Path(folder)/'private/state/connections/A.json'; connection.parent.mkdir(parents=True)
            connection.write_text(json.dumps({'schema_version': 3, 'run_id': 'r', 'actor': 'A', 'url': None, 'token': 't'}))
            requests = [{'call_id': 'one', 'op': 'pending', 'data': {}}, {'call_id': 'two', 'op': 'move', 'data': {}}, 'not json']
            stdin = ''.join((json.dumps(r) if isinstance(r, dict) else r)+'\n' for r in requests)
            out = subprocess.run([sys.executable, '-m', 'robofrontier.runtime.pipeline_client', '--serve', '--connection', str(connection)],
                                 input=stdin, capture_output=True, text=True, cwd=ROOT, timeout=60)
            replies = [json.loads(line) for line in out.stdout.splitlines()]
            self.assertEqual([r['status'] for r in replies], [0, 1, 1])
            self.assertEqual(json.loads(replies[0]['output']), {'pending': []})
            failed = json.loads(replies[1]['output'])
            self.assertEqual((failed['error_code'], failed['call_id']), ('TRANSPORT_UNCERTAIN', 'two'))  # no service URL


if __name__ == '__main__':
    unittest.main()
