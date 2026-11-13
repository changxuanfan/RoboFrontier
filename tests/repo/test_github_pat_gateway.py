"""Real loopback HTTP/streaming checks with a fake upstream; no model calls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import closing
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts.github_pat_gateway import Gateway, MAX_BODY, read_token

TOKEN = 'local-test-pat-not-a-credential'
STREAM = (b'event: response.output_item.done\ndata: {"type":"function_call","name":"robot","arguments":"{}"}\n\n'
          b'event: response.completed\ndata: {"status":"completed"}\n\n')


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.token = self.directory / 'pat.txt'
        self.token.write_text(TOKEN)
        self.requests = []
        self.status, self.stream = 200, STREAM
        self.release_stream = None
        owner = self

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_api(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                owner.requests.append((self.command, self.path, dict(self.headers), body))
                self.send_response(owner.status)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Retry-After', '7')
                self.send_header('Content-Length', str(len(owner.stream)))
                self.end_headers()
                if owner.release_stream is not None:
                    first, rest = owner.stream.split(b'\n', 1)
                    self.wfile.write(first + b'\n')
                    self.wfile.flush()
                    if not owner.release_stream.wait(5):
                        return
                    self.wfile.write(rest)
                else:
                    self.wfile.write(owner.stream)

            do_GET = handle_api
            do_POST = handle_api

        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.gateway = Gateway(('127.0.0.1', 0), self.token, log_file=self.directory / 'metadata.jsonl')
        self.gateway.upstream_connection = lambda: http.client.HTTPConnection('127.0.0.1', self.upstream.server_port, timeout=5)
        self.threads = [threading.Thread(target=s.serve_forever, kwargs={'poll_interval': .02}) for s in (self.upstream, self.gateway)]
        for thread in self.threads:
            thread.start()

    def tearDown(self):
        for server in (self.gateway, self.upstream):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join()
        self.temporary.cleanup()

    def request(self, path='/v1/responses', payload=None, token=TOKEN, method='POST', extra=None):
        body = json.dumps(payload if payload is not None else {'model': 'gpt-6.1-sol', 'stream': True})
        headers = {'Authorization': 'Bearer ' + token, **(extra or {})}
        with closing(http.client.HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=5)) as client:
            client.request(method, path, body=None if method == 'GET' else body, headers=headers)
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def test_responses_stream_and_function_arguments_are_not_rewritten(self):
        payload = {'model': 'gpt-6.1-sol', 'stream': True, 'input': [{'type': 'function_call_output', 'call_id': 'a', 'output': 'private-prompt-canary'}],
                   'tools': [{'type': 'function', 'name': 'robot', 'parameters': {'type': 'object'}}]}
        status, headers, body = self.request(payload=payload)
        self.assertEqual((status, body), (200, STREAM))
        self.assertEqual(headers['Retry-After'], '7')
        method, path, upstream_headers, upstream_body = self.requests[0]
        self.assertEqual((method, path), ('POST', '/responses'))
        self.assertEqual(json.loads(upstream_body), payload)
        self.assertEqual(upstream_headers['Authorization'], 'Bearer ' + TOKEN)
        self.assertEqual(upstream_headers['Copilot-Integration-Id'], 'vscode-chat')
        log = (self.directory / 'metadata.jsonl').read_text()
        self.assertNotIn(TOKEN, log)
        self.assertNotIn('private-prompt-canary', log)
        self.assertNotIn('Authorization', log)

    def test_authentication_and_route_rejection_do_not_contact_upstream(self):
        self.assertEqual(self.request(token='wrong')[0], 401)
        self.assertEqual(self.request(path='/v1/unknown')[0], 404)
        self.assertEqual(self.requests, [])

    def test_stream_bytes_arrive_before_upstream_finishes(self):
        self.release_stream = threading.Event()
        try:
            with closing(http.client.HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=3)) as client:
                client.request('POST', '/responses', json.dumps({'model': 'gpt-6.1-sol', 'stream': True}),
                               {'Authorization': 'Bearer ' + TOKEN})
                response = client.getresponse()
                first = response.readline()
                self.assertEqual(first, STREAM.split(b'\n', 1)[0] + b'\n')
                self.release_stream.set()
                self.assertEqual(first + response.read(), STREAM)
        finally:
            self.release_stream.set()

    def test_models_and_upstream_errors_pass_through_without_retries(self):
        self.status, self.stream = 429, b'{"error":{"message":"quota"}}'
        status, headers, body = self.request(path='/v1/models', method='GET')
        self.assertEqual((status, body), (429, self.stream))
        self.assertEqual(headers['Retry-After'], '7')
        self.assertEqual(len(self.requests), 1)

    def test_chat_images_and_default_helper_parameters_are_preserved(self):
        payload = {'model': 'gemini-3.8-flash', 'reasoning_effort': 'minimal', 'messages': [
            {'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test'}}]}]}
        self.assertEqual(self.request('/chat/completions', payload)[0], 200)
        self.assertEqual(json.loads(self.requests[-1][3]), payload)
        self.gateway.flash_helper = True
        self.request('/chat/completions', payload)
        self.assertEqual(json.loads(self.requests[-1][3])['reasoning_effort'], 'low')
        self.request('/chat/completions', {'model': 'gemini-3.1-flash-lite-preview'})
        self.assertEqual(json.loads(self.requests[-1][3]), {'model': 'gemini-3.8-flash', 'reasoning_effort': 'low'})

    def test_file_rotation_changes_both_accepted_and_forwarded_token(self):
        self.token.write_text('replacement-test-pat')
        self.assertEqual(self.request()[0], 401)
        self.assertEqual(self.request(token='replacement-test-pat')[0], 200)
        self.assertEqual(self.requests[-1][2]['Authorization'], 'Bearer replacement-test-pat')

    def test_bad_json_size_and_chunked_requests_are_rejected(self):
        self.assertEqual(self.request(payload=['not-an-object'])[0], 400)
        self.assertEqual(self.request(extra={'Content-Length': str(MAX_BODY + 1)})[0], 413)
        self.assertEqual(self.request(extra={'Transfer-Encoding': 'chunked'})[0], 400)
        self.assertEqual(self.requests, [])

    def test_transport_error_is_a_502_with_no_fake_stream_completion(self):
        def fail():
            raise OSError('synthetic network failure')
        self.gateway.upstream_connection = fail
        status, _, body = self.request()
        self.assertEqual(status, 502)
        self.assertNotIn(b'response.completed', body)

    def test_unavailable_rotated_file_returns_503(self):
        self.token.unlink()
        self.assertEqual(self.request()[0], 503)

    def test_bom_and_environment_token_reading(self):
        self.token.write_text('\ufeff' + TOKEN + '\n', encoding='utf-8')
        self.assertEqual(read_token(self.token), TOKEN)
        with patch.dict(os.environ, {'ROBOFRONTIER_GITHUB_PAT': TOKEN}):
            self.assertEqual(read_token(), TOKEN)
        self.token.write_text('two\ntokens')
        with self.assertRaises(ValueError):
            read_token(self.token)


if __name__ == '__main__':
    unittest.main()
