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

from scripts.github_pat_gateway import Gateway, MAX_BODY, genai_to_chat, json_schema, read_token, usage_metadata

TOKEN = 'local-test-pat-not-a-credential'
STREAM = (b'event: response.output_item.done\ndata: {"type":"function_call","name":"robot","arguments":"{}"}\n\n'
          b'event: response.completed\ndata: {"status":"completed"}\n\n')


class GatewayTests(unittest.TestCase):
    def test_opaque_reasoning_state_is_rejected_instead_of_silently_discarded(self):
        for field in ('thoughtSignature', 'thought_signature'):
            with self.assertRaisesRegex(ValueError, 'thought signatures'):
                genai_to_chat({'contents': [{'role': 'model', 'parts': [
                    {'text': 'prior answer', field: 'opaque-state'}]}]}, 'gemini-test', True)

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
        self.recorded = threading.Event()
        record = self.gateway.record
        def recorded(value):
            record(value)
            self.recorded.set()
        self.gateway.record = recorded
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
        before = len(self.requests)
        self.recorded.clear()
        body = json.dumps(payload if payload is not None else {'model': 'gpt-6.1-sol', 'stream': True})
        headers = {'Authorization': 'Bearer ' + token, **(extra or {})}
        with closing(http.client.HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=5)) as client:
            client.request(method, path, body=None if method == 'GET' else body, headers=headers)
            response = client.getresponse()
            result = response.status, dict(response.getheaders()), response.read()
            if len(self.requests) > before:
                self.assertTrue(self.recorded.wait(2))
            return result

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

    def test_genai_mcp_images_and_parallel_tool_results_reach_the_model(self):
        self.stream = json.dumps({'choices': [{'message': {'content': '371802'}, 'finish_reason': 'stop'}],
                                  'usage': {'prompt_tokens': 40, 'completion_tokens': 6, 'total_tokens': 46}}).encode()
        payload = {'systemInstruction': {'parts': [{'text': 'Read tool images.'}]}, 'contents': [
            {'role': 'user', 'parts': [{'text': 'Read the code.'}]},
            {'role': 'model', 'parts': [{'functionCall': {'name': 'camera', 'args': {'view': 1}}},
                                        {'functionCall': {'name': 'camera', 'args': {'view': 2}}}]},
            {'role': 'user', 'parts': [
                {'functionResponse': {'name': 'camera', 'response': {'output': 'first'}, 'parts': [
                    {'inlineData': {'mimeType': 'image/png', 'data': 'image-one'}}]}},
                {'functionResponse': {'name': 'camera', 'response': {'output': 'second'}, 'parts': [
                    {'inlineData': {'mimeType': 'image/jpeg', 'data': 'image-two'}}]}}]}],
            'tools': [{'functionDeclarations': [{'name': 'camera', 'parameters': {
                'type': 'OBJECT', 'properties': {'view': {'type': 'INTEGER'}}, 'required': ['view']}}]}],
            'generationConfig': {'thinkingConfig': {'thinkingLevel': 'HIGH'}, 'maxOutputTokens': 100}}
        status, _, body = self.request('/v1beta/models/gemini-4-argon:generateContent', payload,
                                       extra={'Authorization': '', 'x-goog-api-key': TOKEN})
        self.assertEqual(status, 200)
        output = json.loads(body)
        self.assertEqual(output['candidates'][0]['content']['parts'], [{'text': '371802'}])
        self.assertEqual(output['usageMetadata']['totalTokenCount'], 46)
        request = json.loads(self.requests[-1][3])
        self.assertEqual(self.requests[-1][1], '/chat/completions')
        self.assertEqual([m['role'] for m in request['messages']], ['system', 'user', 'assistant', 'tool', 'tool', 'user'])
        self.assertEqual([m['tool_call_id'] for m in request['messages'] if m['role'] == 'tool'], ['call_1_0', 'call_1_1'])
        urls = [part['image_url']['url'] for part in request['messages'][-1]['content'] if part['type'] == 'image_url']
        self.assertEqual(urls, ['data:image/png;base64,image-one', 'data:image/jpeg;base64,image-two'])
        self.assertEqual((request['reasoning_effort'], request['max_completion_tokens']), ('high', 100))
        self.assertEqual(request['tools'][0]['function']['parameters']['properties']['view']['type'], 'integer')
        log = (self.directory / 'metadata.jsonl').read_text()
        self.assertNotIn('image-one', log)
        self.assertNotIn(TOKEN, log)

    def test_genai_stream_preserves_reasoning_usage_and_fragmented_tool_arguments(self):
        chunks = [
            {'choices': [{'delta': {'reasoning_content': 'Inspecting the scene.'}}]},
            {'choices': [{'delta': {'content': 'Reading image.'}}]},
            {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call_x', 'function': {'name': 'camera', 'arguments': '{"view":'}}]}}]},
            {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '2}'}}]}, 'finish_reason': 'tool_calls'}]},
            {'choices': [], 'usage': {'prompt_tokens': 50, 'completion_tokens': 10, 'total_tokens': 60}}]
        self.stream = b''.join(('data: ' + json.dumps(chunk) + '\n\n').encode() for chunk in chunks) + b'data: [DONE]\n\n'
        status, _, body = self.request('/v1beta/models/gemini-4-argon:streamGenerateContent?alt=sse',
                                       {'contents': [{'role': 'user', 'parts': [{'text': 'Read.'}]}]})
        self.assertEqual(status, 200)
        events = [json.loads(line[6:]) for line in body.decode().splitlines() if line.startswith('data: ')]
        self.assertEqual(events[0]['candidates'][0]['content']['parts'], [{'text': 'Inspecting the scene.', 'thought': True}])
        final = events[-1]
        self.assertEqual(final['candidates'][0]['content']['parts'], [
            {'functionCall': {'id': 'call_x', 'name': 'camera', 'args': {'view': 2}}}])
        self.assertEqual(final['candidates'][0]['finishReason'], 'STOP')
        self.assertEqual(final['usageMetadata']['totalTokenCount'], 60)

    def test_genai_stream_does_not_invent_success_after_truncation(self):
        self.stream = b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        status, _, body = self.request('/v1beta/models/gemini-4-argon:streamGenerateContent', {'contents': []})
        self.assertEqual(status, 200)
        self.assertIn(b'"error"', body)
        self.assertNotIn(b'finishReason', body)
        self.assertNotIn(b'STOP', body)

    def test_genai_invalid_auth_and_unsupported_inputs_never_contact_upstream(self):
        path = '/v1beta/models/gemini-4-argon:generateContent'
        self.assertEqual(self.request(path, {}, token='wrong')[0], 401)
        self.assertEqual(self.request(path, {'contents': [{'parts': [{'fileData': {'fileUri': 'file:///private'}}]}]})[0], 400)
        self.assertEqual(self.request(path, {'safetySettings': [{'category': 'any'}]})[0], 400)
        self.assertEqual(self.request(path, {'generationConfig': {'thinkingConfig': {'thinkingBudget': 100}}})[0], 400)
        self.assertEqual(self.requests, [])

    def test_schema_conversion_preserves_property_names_and_default_values(self):
        converted = json_schema({'type': 'OBJECT', 'propertyOrdering': ['nullable'], 'properties': {
            'nullable': {'type': 'STRING', 'minLength': '1', 'nullable': True},
            'propertyOrdering': {'type': 'OBJECT', 'default': {'type': 'STRING'}}}})
        self.assertEqual(converted['properties']['nullable']['type'], ['string', 'null'])
        self.assertEqual(converted['properties']['nullable']['minLength'], 1)
        self.assertEqual(converted['properties']['propertyOrdering']['default'], {'type': 'STRING'})

    def test_genai_helpers_keep_flash_low_and_upstream_errors_remain_errors(self):
        self.gateway.flash_helper = True
        self.status, self.stream = 429, b'{"error":{"message":"quota"}}'
        status, headers, body = self.request('/v1beta/models/gemini-3.8-flash:streamGenerateContent',
            {'contents': [], 'generationConfig': {'thinkingConfig': {'thinkingLevel': 'MINIMAL'}}})
        self.assertEqual((status, body, headers['Retry-After']), (429, self.stream, '7'))
        self.assertEqual(json.loads(self.requests[-1][3])['reasoning_effort'], 'low')

    def test_genai_auxiliary_empty_system_instruction_is_omitted(self):
        # Native auxiliary monitors send this empty instruction. The upstream
        # rejects an empty OpenAI system message with invalid_request_body.
        request = genai_to_chat({'systemInstruction': {'role': 'user', 'parts': [{'text': ''}]},
                                 'contents': [{'role': 'user', 'parts': [{'text': 'Review the request.'}]}]},
                                'gemini-3.8-flash', True)
        self.assertEqual(request['messages'], [{'role': 'user', 'content': [{'type': 'text', 'text': 'Review the request.'}]}])

    def test_native_api_key_mixed_model_turn_keeps_tool_response_and_image(self):
        request = genai_to_chat({'contents': [{'role': 'model', 'parts': [
            {'functionCall': {'name': 'camera', 'args': {}, 'id': 'view-1'}},
            {'functionResponse': {'name': 'camera', 'id': 'view-1', 'response': {'output': 'Frame'},
                'parts': [{'inlineData': {'mimeType': 'image/png', 'data': 'image'}}]}}]}]}, 'gemini-4-argon', True)
        self.assertEqual([message['role'] for message in request['messages']], ['assistant', 'tool', 'user'])
        self.assertEqual(request['messages'][1]['tool_call_id'], 'view-1')
        self.assertEqual(request['messages'][2]['content'][-1]['image_url']['url'], 'data:image/png;base64,image')

    def test_parallel_image_results_split_across_native_contents_are_not_rejected(self):
        request = genai_to_chat({'contents': [
            {'role': 'model', 'parts': [{'functionCall': {'id': 'a', 'name': 'camera', 'args': {}}},
                                        {'functionCall': {'id': 'b', 'name': 'camera', 'args': {}}}]},
            {'role': 'model', 'parts': [{'functionResponse': {'id': 'b', 'name': 'camera', 'response': {},
                'parts': [{'inlineData': {'mimeType': 'image/png', 'data': 'second'}}]}}]},
            {'role': 'user', 'parts': [{'functionResponse': {'id': 'a', 'name': 'camera', 'response': {},
                'parts': [{'inlineData': {'mimeType': 'image/png', 'data': 'first'}}]}}]}]}, 'gemini-4-argon', True)
        self.assertEqual([m['role'] for m in request['messages']], ['assistant', 'tool', 'tool', 'user'])
        self.assertEqual([m['tool_call_id'] for m in request['messages'][1:3]], ['b', 'a'])
        self.assertEqual([part['image_url']['url'] for part in request['messages'][-1]['content'] if part['type'] == 'image_url'],
                         ['data:image/png;base64,second', 'data:image/png;base64,first'])

    def test_reasoning_tokens_are_not_counted_twice_in_genai_usage(self):
        result = usage_metadata({'prompt_tokens': 100, 'completion_tokens': 80, 'total_tokens': 180,
                                 'completion_tokens_details': {'reasoning_tokens': 60},
                                 'prompt_tokens_details': {'cached_tokens': 20}})
        self.assertEqual(result, {'promptTokenCount': 100, 'candidatesTokenCount': 20, 'thoughtsTokenCount': 60,
                                  'totalTokenCount': 180, 'cachedContentTokenCount': 20})
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            usage_metadata({'completion_tokens': 5, 'completion_tokens_details': {'reasoning_tokens': 6}})

    def test_refusal_text_is_preserved_for_both_response_modes(self):
        self.stream = json.dumps({'choices': [{'message': {'content': None, 'refusal': 'Request declined.'}, 'finish_reason': 'stop'}]}).encode()
        _, _, body = self.request('/v1beta/models/gemini-4-argon:generateContent', {'contents': []})
        self.assertEqual(json.loads(body)['candidates'][0]['content']['parts'], [{'text': 'Request declined.'}])
        self.stream = b'data: {"choices":[{"delta":{"refusal":"Request declined."},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        _, _, body = self.request('/v1beta/models/gemini-4-argon:streamGenerateContent', {'contents': []})
        self.assertIn(b'Request declined.', body)

    def test_json_error_instead_of_sse_is_not_mistaken_for_success(self):
        self.stream = b'{"error":{"code":"overloaded","message":"synthetic-secret-response"}}\n'
        status, _, body = self.request('/v1beta/models/gemini-4-argon:streamGenerateContent', {'contents': []})
        self.assertEqual(status, 502)
        self.assertIn(b'"error"', body)
        self.assertNotIn(b'finishReason', body)
        self.assertTrue(self.recorded.wait(2))
        log = (self.directory / 'metadata.jsonl').read_text()
        self.assertNotIn('synthetic-secret-response', log)

    def test_empty_200_stream_is_a_real_502_before_any_client_output(self):
        self.stream = b'data: [DONE]\n\n'
        status, _, body = self.request('/v1beta/models/gemini-4-argon:streamGenerateContent', {'contents': []})
        self.assertEqual(status, 502)
        self.assertIn(b'Invalid or incomplete', body)
        self.assertTrue(self.recorded.wait(2))
        row = json.loads((self.directory / 'metadata.jsonl').read_text())
        self.assertEqual((row['http'], row['downstream_http'], row['failure_phase']), (200, 502, 'upstream_stream_read'))
        self.assertNotIn('stream_complete', row)

    def test_upstream_connection_reset_after_partial_output_remains_a_stream_error(self):
        class Response:
            status = 200
            def getheader(self, name, default=None):
                return 'text/event-stream' if name == 'Content-Type' else default
            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n'
                yield b'\n'
                raise ConnectionResetError('synthetic-private-upstream-detail')
        class Connection:
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        self.gateway.upstream_connection = Connection
        status, _, body = self.request('/v1beta/models/gemini-4-argon:streamGenerateContent', {'contents': []})
        self.assertEqual(status, 200)
        self.assertIn(b'partial', body)
        self.assertIn(b'Upstream model transport interrupted', body)
        self.assertNotIn(b'finishReason', body)
        log = (self.directory / 'metadata.jsonl').read_text()
        row = json.loads(log)
        self.assertEqual((row['error_type'], row['failure_phase']), ('ConnectionResetError', 'upstream_stream_read'))
        self.assertNotIn('synthetic-private-upstream-detail', log)


if __name__ == '__main__':
    unittest.main()
