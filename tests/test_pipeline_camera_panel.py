import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer

from scripts import pipeline_camera_panel as panel


class CameraPanelAccessTests(unittest.TestCase):
    def setUp(self):
        self.captures = []
        def capture():
            self.captures.append(1)
            return {'cameras': ['global'], 'sim_time_s': 1.0, 'captured_at': 2.0}
        cache = {'images': {'global': (b'png', 'image/png')}, 'captured_at': None, 'sim_time_s': None, 'error': None}
        handler = panel.make_handler('secret-key', capture, ['global'], threading.Lock(), cache)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port

    def request(self, method, path, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers.setdefault('Host', f'127.0.0.1:{self.port}')
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        response.read()
        connection.close()
        return response

    def test_requests_without_the_launch_cookie_are_refused(self):
        self.assertEqual(self.request('POST', '/api/refresh').status, 403)
        self.assertEqual(self.request('GET', '/frames/global.png').status, 403)
        self.assertEqual(self.request('GET', '/?k=wrong').status, 403)
        self.assertEqual(self.captures, [])

    def test_the_keyed_page_sets_the_cookie_that_allows_refresh(self):
        page = self.request('GET', '/?k=secret-key')
        self.assertEqual(page.status, 200)
        cookie = page.getheader('Set-Cookie').split(';')[0]
        self.assertIn('SameSite=Strict', page.getheader('Set-Cookie'))
        self.assertEqual(self.request('POST', '/api/refresh', Cookie=cookie).status, 200)
        self.assertEqual(self.captures, [1])
        self.assertEqual(self.request('GET', '/frames/global.png', Cookie=cookie).status, 200)

    def test_foreign_host_or_origin_is_refused_even_with_the_cookie(self):
        cookie = 'robofrontier_panel=secret-key'
        self.assertEqual(self.request('POST', '/api/refresh', Cookie=cookie, Host='evil.example:80').status, 403)
        self.assertEqual(self.request('POST', '/api/refresh', Cookie=cookie, Origin='https://evil.example').status, 403)
        self.assertEqual(self.captures, [])


if __name__ == '__main__':
    unittest.main()
