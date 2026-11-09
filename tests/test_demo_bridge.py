"""The legacy single-arm demo's bridge and its GUI-thread request handling, without a window."""
import json
from pathlib import Path
import queue
import tempfile
import types
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from robofrontier.demo import bridge as bridge_module
from robofrontier.demo.app import App
from robofrontier.demo.bridge import Request


class DemoBridgeTests(unittest.TestCase):
    def test_a_request_with_trace_keys_is_answered_and_never_crashes_the_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = []
            episode = types.SimpleNamespace(path=Path(tmp), event=lambda kind, **values: events.append((kind, values)))
            jobs = queue.Queue()
            payload = {'request_id': 'r', 'type': 'x', 'kind': 'k', 'sim_time_s': 1, 'event': 'e'}
            job = Request(payload); jobs.put(job)
            app = types.SimpleNamespace(bridge=types.SimpleNamespace(queue=jobs), remote=None, episode=episode,
                                        sim=types.SimpleNamespace(data=types.SimpleNamespace(time=2.0)))
            app.reply = lambda job, result: App.reply(app, job, result)
            App.poll_bridge(app)
            self.assertTrue(job.done.is_set())
            self.assertIn('error', job.result)
            self.assertEqual(events[0], ('tool_request', {'sim_time_s': 2.0, 'request': payload}))

    def test_a_json_body_that_is_not_an_object_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge_module, 'ROOT', Path(tmp)):
            bridge = bridge_module.Bridge()
            try:
                info = json.loads((Path(tmp)/'.robot-bridge.json').read_text())
                request = urllib.request.Request(info['url'], data=b'[1, 2]', method='POST',
                                                 headers={'X-Robot-Token': info['token'], 'Content-Type': 'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=10)
                self.assertEqual(caught.exception.code, 400)
                self.assertTrue(bridge.queue.empty())
            finally:
                bridge.close()


if __name__ == '__main__': unittest.main()
