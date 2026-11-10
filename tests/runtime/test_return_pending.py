"""A waiting action that outlasts an engine's tool-call limit returns as pending (E15)."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from robofrontier.runtime.pipeline_client import client_call


class Pending(BaseHTTPRequestHandler):
    calls = 0
    def do_POST(self):
        Pending.calls += 1; self.rfile.read(int(self.headers.get('Content-Length', 0)))
        body = json.dumps({'call_id': 'm1', 'execution_status': 'pending'}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(body)
    def log_message(self, *args): pass


class ReturnPendingTests(unittest.TestCase):
    def test_a_long_wait_returns_the_original_call_as_pending(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Pending); threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                connection = Path(folder)/'private/state/connections/A.json'; connection.parent.mkdir(parents=True)
                connection.write_text(json.dumps({'schema_version': 3, 'run_id': 'r', 'actor': 'A', 'token': 't',
                                                  'url': f'http://127.0.0.1:{server.server_port}'}))
                result = client_call(connection, 'move', {'delta_m': [0, 0, .01]}, 'm1', log_call_id=False, return_pending_after_s=.05)
        finally:
            server.shutdown()
        self.assertEqual((result['call_id'], result['execution_status'], result['returned_while_pending']), ('m1', 'pending', True))
        self.assertGreaterEqual(Pending.calls, 1)


if __name__ == '__main__':
    unittest.main()
