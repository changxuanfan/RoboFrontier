"""Codex/Claude gateway: translation in both directions and real loopback HTTP checks.

The translation tests need only the standard library. The HTTP tests use the official
`anthropic` SDK against a local fake upstream and are skipped where it is not installed
(run them with the optional gateway environment). No model provider is contacted.
"""
from contextlib import closing
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'tests'))
import codex_claude_gateway as gateway  # noqa: E402
from anthropic_upstream_fixture import AnthropicStub, message_events, text, thinking, tool_use, usage  # noqa: E402

LOCAL_KEY = 'local-gateway-key-not-a-credential-0123456789'
UPSTREAM_KEY = 'fake-anthropic-key-for-offline-tests'
PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=='
PICTURE = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': PNG}}
TOOLS = [{'type': 'function', 'name': 'robot', 'description': 'Robot tool', 'strict': False,
          'parameters': {'type': 'object', 'properties': {'op': {'type': 'string'}}}},
         {'type': 'custom', 'name': 'apply_patch', 'description': 'Edit files.',
          'format': {'type': 'grammar', 'syntax': 'lark', 'definition': 'start: "*** Begin Patch"'}},
         {'type': 'namespace', 'name': 'collaboration', 'description': 'Agents.',
          'tools': [{'type': 'function', 'name': 'list_agents', 'description': 'List.', 'strict': False,
                     'parameters': {'type': 'object', 'properties': {}}}]}]


def user(*parts):
    return {'type': 'message', 'role': 'user', 'content': list(parts)}


def developer(value):
    return {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': value}]}


def words(value):
    return {'type': 'input_text', 'text': value}


def request(items, **fields):
    body = {'model': 'claude-opus-5-5', 'stream': True, 'store': False, 'input': items, 'tools': TOOLS,
            'tool_choice': 'auto', 'parallel_tool_calls': True, 'reasoning': {'effort': 'high'},
            'include': ['reasoning.encrypted_content'], 'prompt_cache_key': 'thread', 'client_metadata': {'a': 'b'}}
    body.update(fields)
    return {key: value for key, value in body.items() if value is not None}


def answer(blocks, stop_reason=None, info=None, **options):
    """Feed one synthetic Anthropic stream through the reply builder."""
    reply = gateway.Reply(info or gateway.translate_request(request([user(words('hi'))]))[1])
    stop_reason = stop_reason or ('tool_use' if blocks and blocks[-1]['type'] == 'tool_use' else 'end_turn')
    for _, event in message_events(blocks, stop_reason, **options):
        reply.feed(event)
    return reply


class RequestTranslationTests(unittest.TestCase):
    def test_static_prefix_becomes_system_and_later_developer_text_stays_in_place(self):
        params, info = gateway.translate_request(request(
            [developer('BASE'), developer('RULES'), user(words('env')), user(words('hello'), {
                'type': 'input_image', 'image_url': 'data:image/png;base64,' + PNG, 'detail': 'high'}),
             {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'answer'}]},
             developer('LATER RULE'), user(words('again'))], instructions='INSTRUCTIONS'))
        self.assertEqual(params['system'], [{'type': 'text', 'text': 'INSTRUCTIONS'}, {'type': 'text', 'text': 'BASE'},
                                            {'type': 'text', 'text': 'RULES', 'cache_control': {'type': 'ephemeral'}}])
        self.assertEqual(params['messages'], [
            {'role': 'user', 'content': [{'type': 'text', 'text': 'env'}, {'type': 'text', 'text': 'hello'}, PICTURE]},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': 'answer'}]},
            {'role': 'user', 'content': [{'type': 'text', 'text': '<system-reminder>\nLATER RULE\n</system-reminder>'},
                                         {'type': 'text', 'text': 'again'}]}])
        self.assertEqual((params['model'], params['max_tokens'], params['output_config']),
                         ('claude-opus-5-5', 64000, {'effort': 'high'}))
        self.assertEqual(params['thinking'], {'type': 'adaptive', 'block_binding': {'prefix_mismatch_behavior': 'error'}})
        self.assertEqual((params['betas'], params['tool_choice'], params['cache_control']),
                         ([gateway.BINDING_BETA], {'type': 'auto'}, {'type': 'ephemeral'}))
        self.assertEqual(info['counts']['images'], 1)
        for absent in ('temperature', 'top_p', 'top_k', 'fallbacks', 'stop_sequences'):
            self.assertNotIn(absent, params)

    def test_tools_are_name_sorted_and_freeform_and_namespaced_tools_keep_a_way_back(self):
        params, info = gateway.translate_request(request([user(words('hi'))]))
        self.assertEqual([tool['name'] for tool in params['tools']], ['apply_patch', 'collaboration__list_agents', 'robot'])
        patch = params['tools'][0]
        self.assertEqual(patch['input_schema']['required'], ['input'])
        self.assertIn('start: "*** Begin Patch"', patch['description'])
        self.assertEqual(params['tools'][2]['input_schema'], TOOLS[0]['parameters'])
        self.assertEqual(info['names'], {'robot': ('function', None, 'robot'), 'apply_patch': ('custom', None, 'apply_patch'),
                                         'collaboration__list_agents': ('function', 'collaboration', 'list_agents')})
        reordered, _ = gateway.translate_request(request([user(words('hi'))], tools=TOOLS[::-1]))
        self.assertEqual(gateway.canonical(reordered), gateway.canonical(params))
        self.assertEqual(sum('cache_control' in tool for tool in params['tools']), 1)  # no system: last tool marks the prefix
        with self.assertRaises(gateway.ProtocolError):
            gateway.translate_request(request([user(words('hi'))], tools=[{'type': 'web_search'}]))
        with self.assertRaises(gateway.ProtocolError):
            gateway.translate_request(request([user(words('hi'))], tools=[TOOLS[0], TOOLS[0]]))

    def test_parallel_calls_and_image_results_form_one_assistant_and_one_user_turn(self):
        first, second = thinking('c2ln+/a=='), thinking('c2ln+/b==', 'visible summary')
        items = [developer('BASE'), user(words('go')),
                 {'type': 'reasoning', 'id': 'rs_1', 'summary': [], 'content': None, 'encrypted_content': gateway.seal(first)},
                 {'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [{'type': 'output_text', 'text': 'two calls'}]},
                 {'type': 'reasoning', 'id': 'rs_2', 'summary': [], 'encrypted_content': gateway.seal(second)},
                 {'type': 'function_call', 'call_id': 'toolu_a', 'name': 'robot', 'arguments': '{"op": "look", "n": 1.50}'},
                 {'type': 'function_call', 'call_id': 'toolu_b', 'namespace': 'collaboration', 'name': 'list_agents', 'arguments': ''},
                 {'type': 'custom_tool_call', 'call_id': 'toolu_c', 'name': 'apply_patch', 'input': '*** Begin Patch'},
                 {'type': 'function_call_output', 'call_id': 'toolu_a', 'output': [
                     words('camera'), {'type': 'input_image', 'image_url': 'data:image/png;base64,' + PNG, 'detail': 'high'}]},
                 {'type': 'function_call_output', 'call_id': 'toolu_b', 'output': 'aborted'},
                 {'type': 'custom_tool_call_output', 'call_id': 'toolu_c', 'output': 'Success.'},
                 developer('<turn_aborted>'), user(words('next'))]
        params, info = gateway.translate_request(request(items))
        self.assertEqual(params['messages'][1], {'role': 'assistant', 'content': [
            first, {'type': 'text', 'text': 'two calls'}, second,
            {'type': 'tool_use', 'id': 'toolu_a', 'name': 'robot', 'input': {'op': 'look', 'n': 1.5}},
            {'type': 'tool_use', 'id': 'toolu_b', 'name': 'collaboration__list_agents', 'input': {}},
            {'type': 'tool_use', 'id': 'toolu_c', 'name': 'apply_patch', 'input': {'input': '*** Begin Patch'}}]})
        self.assertEqual(params['messages'][2], {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'toolu_a', 'content': [{'type': 'text', 'text': 'camera'}, PICTURE]},
            {'type': 'tool_result', 'tool_use_id': 'toolu_b', 'content': 'aborted'},
            {'type': 'tool_result', 'tool_use_id': 'toolu_c', 'content': 'Success.'},
            {'type': 'text', 'text': '<system-reminder>\n<turn_aborted>\n</system-reminder>'},
            {'type': 'text', 'text': 'next'}]})
        self.assertEqual(info['counts'], {'images': 1, 'tool_results': 3, 'thinking_blocks': 2, 'tool_calls': 3,
                                          'messages': 3, 'tools': 3})

    def test_history_that_cannot_be_represented_is_rejected_not_dropped(self):
        call = {'type': 'function_call', 'call_id': 'toolu_a', 'name': 'robot', 'arguments': '{}'}
        output = {'type': 'function_call_output', 'call_id': 'toolu_a', 'output': 'ok'}
        cases = {
            'foreign reasoning': [user(words('a')), {'type': 'reasoning', 'encrypted_content': 'gAAAA-openai'}, user(words('b'))],
            'reasoning without content': [user(words('a')), {'type': 'reasoning', 'summary': []}, user(words('b'))],
            'damaged reasoning': [user(words('a')), {'type': 'reasoning', 'encrypted_content': gateway.OPAQUE + '!!'}, user(words('b'))],
            'call without output': [user(words('a')), call, user(words('b'))],
            'output without call': [user(words('a')), output],
            'unanswered call at the end': [user(words('a')), call],
            'ends with the assistant': [user(words('a')), {'type': 'message', 'role': 'assistant', 'content': 'x'}],
            'starts with the assistant': [{'type': 'message', 'role': 'assistant', 'content': 'x'}, user(words('a'))],
            'hosted tool item': [user(words('a')), {'type': 'web_search_call', 'id': 'ws'}, user(words('b'))],
            'local shell item': [user(words('a')), {'type': 'local_shell_call', 'call_id': 'c'}, user(words('b'))],
            'file part': [user({'type': 'input_file', 'file_id': 'file_1'})],
            'image by file id': [user({'type': 'input_image', 'file_id': 'file_1'})],
            'unsupported image type': [user({'type': 'input_image', 'image_url': 'data:image/tiff;base64,AAAA'})],
            'plain http image': [user({'type': 'input_image', 'image_url': 'http://example.com/a.png'})],
            'image in a developer message': [developer('x'), {'type': 'message', 'role': 'developer', 'content': [
                {'type': 'input_image', 'image_url': 'data:image/png;base64,' + PNG}]}, user(words('a'))],
            'arguments that are not an object': [user(words('a')), {**call, 'arguments': '[1]'}, output],
            'arguments that are not JSON': [user(words('a')), {**call, 'arguments': '{"op": '}, output],
            'empty input': [],
        }
        for name, items in cases.items():
            with self.subTest(case=name), self.assertRaises(gateway.ProtocolError):
                gateway.translate_request(request(items))

    def test_request_controls_without_a_messages_equivalent_are_rejected(self):
        items = [user(words('hi'))]
        for fields in ({'model': 'claude-opus-5'}, {'model': 'gpt-6.1-sol'}, {'model': 'claude-opus-5-5-20261001'},
                       {'stream': False}, {'store': True}, {'text': {'verbosity': 'low'}},
                       {'text': {'format': {'type': 'json_schema'}}}, {'reasoning': {'effort': 'minimal'}},
                       {'reasoning': {'effort': 'none'}}, {'reasoning': None}, {'reasoning': {'effort': 'high', 'summary': 'auto'}},
                       {'tool_choice': 'required'}, {'tool_choice': {'type': 'function', 'name': 'robot'}},
                       {'previous_response_id': 'resp_1'}, {'temperature': 0.2}, {'top_p': 0.9}, {'truncation': 'auto'},
                       {'include': ['file_search_call.results']}, {'max_output_tokens': 0}, {'service_tier': 'priority'}):
            with self.subTest(fields=fields), self.assertRaises(gateway.ProtocolError):
                gateway.translate_request(request(items, **fields))
        params, _ = gateway.translate_request(request(items, max_output_tokens=32000, reasoning={'effort': 'xhigh'},
                                                      parallel_tool_calls=False))
        self.assertEqual((params['max_tokens'], params['output_config'], params['tool_choice']),
                         (32000, {'effort': 'xhigh'}, {'type': 'auto', 'disable_parallel_tool_use': True}))

    def test_cache_markers_follow_the_ttl_and_the_translation_is_deterministic(self):
        items = [developer('BASE'), user(words('hi'))]
        params, info = gateway.translate_request(request(items), cache_ttl='1h')
        marker = {'type': 'ephemeral', 'ttl': '1h'}
        self.assertEqual((params['system'][-1]['cache_control'], params['cache_control']), (marker, marker))
        self.assertEqual(json.dumps(params).count('"cache_control"'), 2)
        again, other = gateway.translate_request(request(items, prompt_cache_key='another', client_metadata={'turn': 2}),
                                                 cache_ttl='1h')
        self.assertEqual(gateway.canonical(again), gateway.canonical(params))
        self.assertEqual(other['prefix_sha256'], info['prefix_sha256'])
        changed = gateway.translate_request(request([developer('BASE 2'), user(words('hi'))]))[1]
        self.assertNotEqual(changed['prefix_sha256'], info['prefix_sha256'])
        self.assertEqual(changed['tools_sha256'], info['tools_sha256'])

    def test_thinking_binding_mode_is_always_explicit_unless_left_to_the_api(self):
        items = [user(words('hi'))]
        dropped, _ = gateway.translate_request(request(items), mismatch='drop_block')
        self.assertEqual(dropped['thinking']['block_binding'], {'prefix_mismatch_behavior': 'drop_block'})
        default, _ = gateway.translate_request(request(items), mismatch='api_default')
        self.assertEqual(default['thinking'], {'type': 'adaptive'})
        self.assertNotIn('betas', default)

    def test_a_request_without_tools_reuses_the_sessions_exact_tools(self):
        """Codex compacts with `tools: []`; a changed tool set would unbind every replayed thinking block."""
        block = thinking('c2ln')
        history = [developer('BASE'), user(words('go')), {'type': 'reasoning', 'encrypted_content': gateway.seal(block)},
                   {'type': 'function_call', 'call_id': 'toolu_a', 'name': 'robot', 'arguments': '{}'},
                   {'type': 'function_call_output', 'call_id': 'toolu_a', 'output': 'ok'}]
        normal, info = gateway.translate_request(request(history))
        compact = request(history + [user(words('CONTEXT CHECKPOINT COMPACTION'))], tools=[], parallel_tool_calls=False)
        with self.assertRaisesRegex(gateway.ProtocolError, 'no\\s+record of the session'):
            gateway.translate_request(compact)
        memory = (info['tools'], info['names'])
        params, restored = gateway.translate_request(compact, session_tools=memory)
        strip = lambda tools: [{k: v for k, v in tool.items() if k != 'cache_control'} for tool in tools]
        self.assertEqual(strip(params['tools']), strip(normal['tools']))
        self.assertEqual(params['system'], normal['system'])
        # Everything already sent is repeated; the summary request only appends to the last user turn.
        self.assertEqual(params['messages'][:-1], normal['messages'][:-1])
        self.assertEqual(params['messages'][-1]['content'][:1], normal['messages'][-1]['content'])
        self.assertEqual(params['messages'][1]['content'][0], block)
        self.assertEqual(params['tool_choice'], {'type': 'none'})
        self.assertNotIn('cache_control', params)  # nothing reads a compaction request's prefix again
        self.assertEqual((restored['tools_restored'], restored['tools_declared'], restored['prefix_sha256']),
                         (True, False, info['prefix_sha256']))
        kept, _ = gateway.translate_request(compact, session_tools=memory, compaction_tool_choice='auto')
        self.assertEqual(kept['tool_choice'], {'type': 'auto', 'disable_parallel_tool_use': True})
        self.assertEqual(kept['cache_control'], {'type': 'ephemeral'})
        bare, _ = gateway.translate_request(request([user(words('hi'))], tools=[]))
        self.assertNotIn('tools', bare)
        self.assertNotIn('tool_choice', bare)


class ResponseTranslationTests(unittest.TestCase):
    def test_blocks_become_items_and_replay_restores_them_exactly(self):
        raw = '{"op": "look",\n  "n": 1.50}'
        blocks = [thinking('c2ln+/a=='), text('calling'), thinking('c2ln+/b==', 'summary text'),
                  tool_use('toolu_a', 'robot', {'op': 'look', 'n': 1.5}, raw=raw),
                  tool_use('toolu_b', 'collaboration__list_agents', {}, raw=''),
                  tool_use('toolu_c', 'apply_patch', {'input': '*** Begin Patch\n'})]
        reply = answer(blocks, identity='msg_1')
        output = reply.items()
        self.assertEqual([item['type'] for item in output],
                         ['reasoning', 'message', 'reasoning', 'function_call', 'function_call', 'custom_tool_call'])
        self.assertEqual(output[1]['content'], [{'type': 'output_text', 'text': 'calling', 'annotations': []}])
        self.assertEqual((output[3]['call_id'], output[3]['name'], output[3]['arguments']), ('toolu_a', 'robot', raw))
        self.assertEqual((output[4]['namespace'], output[4]['name'], output[4]['arguments']), ('collaboration', 'list_agents', '{}'))
        self.assertEqual((output[5]['name'], output[5]['input']), ('apply_patch', '*** Begin Patch\n'))
        self.assertEqual(output[0]['summary'], [])
        self.assertNotIn('c2ln+/a==', json.dumps(output[0]))  # opaque to Codex
        # Codex sends the items back followed by the tool outputs.
        outputs = [{'type': 'function_call_output', 'call_id': 'toolu_a', 'output': 'ok'},
                   {'type': 'function_call_output', 'call_id': 'toolu_b', 'output': 'ok'},
                   {'type': 'custom_tool_call_output', 'call_id': 'toolu_c', 'output': 'ok'}]
        params, _ = gateway.translate_request(request([user(words('go'))] + output + outputs))
        self.assertEqual(params['messages'][1]['content'], [
            {key: value for key, value in block.items() if key != '_raw'} for block in blocks])

    def test_usage_counts_cache_reads_and_writes_as_input(self):
        reply = answer([text('ok')], counts=usage(uncached=100, read=900, created=50, output=20, thinking_tokens=7))
        self.assertEqual(reply.responses_usage(), {
            'input_tokens': 1050, 'input_tokens_details': {'cached_tokens': 900, 'cache_write_tokens': 50},
            'output_tokens': 20, 'output_tokens_details': {'reasoning_tokens': 7}, 'total_tokens': 1070})
        self.assertEqual(reply.usage_record(), {
            'input_tokens': 100, 'cache_read_input_tokens': 900, 'cache_creation_input_tokens': 50,
            'cache_creation_5m_input_tokens': 50, 'cache_creation_1h_input_tokens': 0, 'output_tokens': 20,
            'thinking_tokens': 7})

    def test_only_a_cleanly_finished_answer_is_released(self):
        call = tool_use('toolu_a', 'robot', {'op': 'look'})
        cases = [
            (answer([text('partial')], 'refusal', stop_details={'type': 'refusal', 'category': 'cyber'}), 'failed', 'invalid_prompt'),
            (answer([thinking('s'), call], 'max_tokens'), 'incomplete', 'max_output_tokens'),
            (answer([text('x')], 'model_context_window_exceeded'), 'failed', 'context_length_exceeded'),
            (answer([text('x')], 'pause_turn'), 'failed', 'invalid_prompt'),
            (answer([text('x')], truncate=True), 'failed', 'server_error'),
            (answer([text('x')], model='claude-opus-5'), 'failed', 'invalid_prompt'),
            (answer([call], 'end_turn'), 'failed', 'server_error'),
            (answer([text('x')], 'tool_use'), 'failed', 'server_error'),
            (answer([tool_use('toolu_a', 'robot', {}, raw='{"op": "lo')]), 'failed', 'server_error'),
            (answer([tool_use('toolu_a', 'robot', {}, raw='[1, 2]')]), 'failed', 'server_error'),
            (answer([tool_use('toolu_a', 'apply_patch', {}, raw='{"patch": "x"}')]), 'failed', 'server_error'),
        ]
        for reply, kind, code in cases:
            with self.subTest(code=code, stop=reply.stop_reason), self.assertRaises(gateway.Failure) as caught:
                reply.items()
            self.assertEqual((caught.exception.kind, caught.exception.code), (kind, code))
        event, data = gateway.failure_event('resp_1', gateway.Failure('invalid_prompt', 'declined'))
        self.assertEqual((event, data['response']['status'], data['response']['error']['code'], data['response']['output']),
                         ('response.failed', 'failed', 'invalid_prompt', []))
        event, data = gateway.failure_event('resp_1', gateway.Failure('max_output_tokens', 'm', 'incomplete', 'max_output_tokens'))
        self.assertEqual((event, data['response']['incomplete_details']), ('response.incomplete', {'reason': 'max_output_tokens'}))

    def test_unsupported_upstream_content_and_undeclared_tool_use_fail(self):
        for block in ({'type': 'server_tool_use', 'id': 'srvtoolu_1', 'name': 'web_search', 'input': {}},
                      {'type': 'fallback', 'from': {'model': 'claude-opus-5-5'}, 'to': {'model': 'claude-opus-5'}}):
            with self.subTest(block=block['type']), self.assertRaises(gateway.Failure):
                answer([block])
        without_tools = gateway.translate_request(request([user(words('hi'))], tools=[]))[1]
        with self.assertRaisesRegex(gateway.Failure, 'declared none'):
            answer([tool_use('toolu_a', 'robot', {})], info=without_tools).items()
        self.assertEqual(answer([text('  \n'), text('kept')]).items()[0]['content'][0]['text'], 'kept')
        self.assertEqual(len(answer([text(' ')]).items()), 0)

    def test_completed_stream_releases_each_item_whole_and_ends_with_completed(self):
        reply = answer([thinking('s'), text('hello'), tool_use('toolu_a', 'robot', {'op': 'look'}, raw='{"op":"look"}')])
        events = list(gateway.completed_events('resp_1', reply.items(), reply.responses_usage()))
        self.assertEqual([name for name, _ in events], [
            'response.output_item.added', 'response.output_item.done',
            'response.output_item.added', 'response.content_part.added', 'response.output_text.delta',
            'response.output_text.done', 'response.content_part.done', 'response.output_item.done',
            'response.output_item.added', 'response.function_call_arguments.delta',
            'response.function_call_arguments.done', 'response.output_item.done', 'response.completed'])
        self.assertEqual(events[9][1]['delta'], '{"op":"look"}')
        final = events[-1][1]['response']
        self.assertEqual((final['status'], final['model'], len(final['output']), final['usage']['input_tokens']),
                         ('completed', 'claude-opus-5-5', 3, 1050))

    def test_stream_error_codes_follow_what_codex_retries(self):
        self.assertEqual(gateway.stream_code('overloaded_error'), 'server_overloaded')
        self.assertEqual(gateway.stream_code('rate_limit_error'), 'rate_limit_exceeded')
        self.assertEqual(gateway.stream_code('api_error'), 'server_error')
        self.assertEqual(gateway.stream_code('invalid_request_error'), 'invalid_prompt')


class CredentialFileTests(unittest.TestCase):
    def test_keys_stay_in_private_files_and_only_the_api_or_a_loopback_test_server_is_an_upstream(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'gateway-key.json'
            gateway.create_key_file(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertGreaterEqual(len(gateway.load_keys(path)['default']), 32)
            with self.assertRaises(FileExistsError):
                gateway.create_key_file(path)
            path.write_text(json.dumps({'keys': {'task-a': LOCAL_KEY, 'task-b': LOCAL_KEY + 'b'}}))
            self.assertEqual(sorted(gateway.load_keys(path)), ['task-a', 'task-b'])
            for bad in ({'keys': {'a': LOCAL_KEY, 'b': LOCAL_KEY}}, {'key': 'short'}, {'keys': {'bad label': LOCAL_KEY}}, {}):
                path.write_text(json.dumps(bad))
                with self.subTest(bad=sorted(bad)), self.assertRaises(ValueError):
                    gateway.load_keys(path)
            path.write_text(json.dumps({'key': LOCAL_KEY}))
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'owner only'):
                gateway.load_keys(path)
            secret = Path(folder)/'anthropic-key.txt'
            secret.write_text(UPSTREAM_KEY + '\n')
            secret.chmod(0o600)
            self.assertEqual(gateway.read_secret(secret, 'key'), UPSTREAM_KEY)
            for content in ('', 'two words', 'PASTE_ANTHROPIC_API_KEY_HERE'):
                secret.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    gateway.read_secret(secret, 'key')
        self.assertEqual(gateway.upstream_url('https://api.anthropic.com'), 'https://api.anthropic.com')
        self.assertEqual(gateway.upstream_url('http://127.0.0.1:9000'), 'http://127.0.0.1:9000')
        for url in ('https://example.com', 'http://127.0.0.1.example.com:9000', 'http://localhost:9000',
                    'https://api.anthropic.com.example.com', 'http://127.0.0.1:9000/v1?x=1', 'http://10.0.0.1:9000'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                gateway.upstream_url(url)

    def test_the_command_line_takes_no_credential_and_refuses_a_second_one(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch('sys.stderr'):
            arguments = ['--key-file', str(Path(folder)/'key.json'), '--port', '0']
            with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': UPSTREAM_KEY, 'ANTHROPIC_AUTH_TOKEN': 'second'}):
                with self.assertRaises(SystemExit):
                    gateway.main(arguments)
            with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit):
                gateway.main(arguments)
            for flag in ('--api-key', '--anthropic-key', '--token'):
                with self.subTest(flag=flag), self.assertRaises(SystemExit):
                    gateway.main(arguments + [flag, UPSTREAM_KEY])
            self.assertFalse((Path(folder)/'key.json').exists())


def sse(raw):
    events = []
    for chunk in raw.decode().split('\n\n'):
        lines = dict(line.split(': ', 1) for line in chunk.splitlines() if ': ' in line)
        if 'data' in lines:
            events.append((lines['event'], json.loads(lines['data'])))
    return events


@unittest.skipUnless(importlib.util.find_spec('anthropic'), 'needs the optional anthropic SDK (requirements-codex-claude.txt)')
class GatewayHttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.answer = {'blocks': [thinking('c2ln'), text('hello')], 'usage': usage()}
        self.upstream = AnthropicStub(lambda body, headers: self.answer)
        self.log = self.directory/'metadata.jsonl'
        # Ambient SDK settings must not redirect the request or supply another credential.
        self.ambient = mock.patch.dict(os.environ, {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:9',
                                                    'ANTHROPIC_API_KEY': 'ambient-key-unused'})
        self.ambient.start()
        self.gateway = gateway.Gateway(('127.0.0.1', 0), UPSTREAM_KEY, {'task-a': LOCAL_KEY, 'task-b': LOCAL_KEY + 'b'},
                                       log=self.log, upstream=self.upstream.url, state_dir=self.directory/'state')
        self.thread = threading.Thread(target=self.gateway.serve_forever, kwargs={'poll_interval': .02})
        self.thread.start()

    def tearDown(self):
        self.gateway.shutdown()
        self.gateway.server_close()
        self.thread.join()
        self.upstream.close()
        self.ambient.stop()
        self.temporary.cleanup()

    def call(self, method='POST', path='/v1/responses', body=None, key=LOCAL_KEY, headers=None):
        with closing(http.client.HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=20)) as connection:
            sent = {'Content-Type': 'application/json', **(headers or {})}
            if key:
                sent['Authorization'] = 'Bearer ' + key
            connection.request(method, path, body=None if body is None else json.dumps(body), headers=sent)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def records(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_listener_is_loopback_only_and_requires_the_local_key(self):
        self.assertEqual(self.gateway.server_address[0], '127.0.0.1')
        with self.assertRaises(ValueError):
            gateway.Gateway(('0.0.0.0', 0), UPSTREAM_KEY, {'default': LOCAL_KEY}, upstream=self.upstream.url)
        status, _, body = self.call('GET', '/healthz', key=None)
        self.assertEqual((status, json.loads(body)), (200, {'ready': True, 'model': 'claude-opus-5-5',
                                                            'transport_revision': 'messages-adapter-v1',
                                                            'inference_verified': False}))
        for key in (None, 'wrong-key', UPSTREAM_KEY):
            for method, path in (('POST', '/v1/responses'), ('GET', '/stats'), ('GET', '/v1/models')):
                with self.subTest(key=key, path=path):
                    status, _, body = self.call(method, path, body=request([user(words('hi'))]) if method == 'POST' else None, key=key)
                    self.assertEqual(status, 401)
                    self.assertNotIn(UPSTREAM_KEY, body.decode())
        self.assertEqual(self.upstream.requests, [])
        self.assertEqual(json.loads(self.call('GET', '/v1/models')[2])['data'][0]['id'], 'claude-opus-5-5')
        self.assertEqual(self.call('POST', '/v1/responses/compact', body={})[0], 404)
        self.assertEqual(self.call('POST', '/v1/chat/completions', body={})[0], 404)

    def test_streamed_answer_reaches_codex_complete_with_usage_and_one_log_record(self):
        metadata = {'installation_id': '268d6efc-adc7-4f6e-9810-3e9abbac8787', 'request_kind': 'turn',
                    'forked_from_thread_id': 'thread-parent'}
        status, headers, raw = self.call(body=request([developer('BASE SECRET PROMPT'), user(words('hello PROMPT TEXT'))]),
                                         headers={'session-id': 'thread-1', 'thread-id': 'thread-1',
                                                  'x-codex-turn-metadata': json.dumps(metadata)})
        self.assertEqual((status, headers['Content-Type']), (200, 'text/event-stream'))
        events = sse(raw)
        self.assertEqual(events[0][0], 'response.created')
        self.assertEqual(events[-1][0], 'response.completed')
        final = events[-1][1]['response']
        self.assertEqual([item['type'] for item in final['output']], ['reasoning', 'message'])
        self.assertEqual(final['usage']['input_tokens_details'], {'cached_tokens': 900, 'cache_write_tokens': 50})
        self.assertEqual([number for number in (data['sequence_number'] for _, data in events)], list(range(1, len(events)+1)))
        sent = self.upstream.requests[0]
        self.assertTrue(sent['path'].startswith('/v1/messages'))
        self.assertEqual(sent['headers'].get('x-api-key') or sent['headers']['authorization'].removeprefix('Bearer '), UPSTREAM_KEY)
        self.assertNotIn(LOCAL_KEY, json.dumps(sent['headers']))
        self.assertEqual(sent['headers']['x-stainless-retry-count'], '0')
        record, = self.records()
        self.assertEqual((record['status'], record['http'], record['stop_reason'], record['key_label'], record['run']),
                         ('completed', 200, 'end_turn', 'task-a', 'task-a'))
        self.assertEqual((record['codex_session'], record['codex_installation'], record['request_kind'], record['codex_forked_from']),
                         ('thread-1', metadata['installation_id'], 'turn', 'thread-parent'))
        self.assertEqual(record['usage'], {'input_tokens': 100, 'cache_read_input_tokens': 900, 'cache_creation_input_tokens': 50,
                                           'cache_creation_5m_input_tokens': 50, 'cache_creation_1h_input_tokens': 0,
                                           'output_tokens': 20, 'thinking_tokens': 7})
        self.assertEqual((record['upstream_request_id'], record['upstream_model'], len(record['prefix_sha256'])),
                         ('req_stub', 'claude-opus-5-5', 16))
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)
        written = self.log.read_text()
        for private in (UPSTREAM_KEY, LOCAL_KEY, 'PROMPT', 'hello', 'c2ln', 'Bearer'):
            self.assertNotIn(private, written)
        stats = json.loads(self.call('GET', '/stats')[2])
        self.assertEqual((stats['overall']['requests'], round(stats['labels']['task-a']['cache_hit_rate'], 4)),
                         (1, round(900/1050, 4)))

    def test_keepalives_flow_while_the_whole_answer_is_held_back(self):
        with mock.patch.object(gateway, 'KEEPALIVE_S', 0):
            _, _, raw = self.call(body=request([user(words('hi'))]))
        names = [name for name, _ in sse(raw)]
        self.assertIn('response.in_progress', names)
        self.assertLess(max(index for index, name in enumerate(names) if name == 'response.in_progress'),
                        names.index('response.output_item.added'))
        self.assertEqual((names[0], names[-1]), ('response.created', 'response.completed'))

    def test_runs_are_told_apart_by_key_label_or_codex_installation(self):
        self.call(body=request([user(words('a'))]), key=LOCAL_KEY + 'b')
        self.assertEqual(self.records()[-1]['run'], 'task-b')
        single = gateway.Gateway(('127.0.0.1', 0), UPSTREAM_KEY, {'default': LOCAL_KEY}, log=self.log, upstream=self.upstream.url)
        thread = threading.Thread(target=single.serve_forever, kwargs={'poll_interval': .02})
        thread.start()
        try:
            with closing(http.client.HTTPConnection('127.0.0.1', single.server_port, timeout=20)) as connection:
                connection.request('POST', '/v1/responses', body=json.dumps(request([user(words('a'))])), headers={
                    'Authorization': 'Bearer ' + LOCAL_KEY,
                    'x-codex-turn-metadata': json.dumps({'installation_id': 'abcdef12-0000', 'session_id': 'bad value\n'})})
                connection.getresponse().read()
        finally:
            single.shutdown()
            single.server_close()
            thread.join()
        record = self.records()[-1]
        self.assertEqual((record['run'], record['key_label'], record['codex_session']), ('codex-abcdef12', 'default', None))

    def test_upstream_http_errors_keep_their_status_and_retry_after_without_a_gateway_retry(self):
        for status, kind, retry in ((401, 'authentication_error', None), (403, 'permission_error', None),
                                    (429, 'rate_limit_error', '7'), (500, 'api_error', None), (529, 'overloaded_error', '3'),
                                    (400, 'invalid_request_error', None)):
            with self.subTest(status=status):
                self.upstream.requests.clear()
                self.answer = {'status': status, 'error': {'type': kind, 'message': 'stub ' + kind},
                               'headers': {'retry-after': retry} if retry else {}}
                got, headers, body = self.call(body=request([user(words('hi'))]))
                document = json.loads(body)
                self.assertEqual((got, document['error']['type'], headers.get('Retry-After')), (status, kind, retry))
                self.assertIn('stub ' + kind, document['error']['message'])
                self.assertEqual(len(self.upstream.requests), 1)
                record = self.records()[-1]
                self.assertEqual((record['status'], record['http'], record['upstream_error']), ('upstream_error', status, kind))
                self.assertNotIn('usage', record)

    def test_unreachable_upstream_is_a_gateway_error_not_a_synthetic_answer(self):
        self.upstream.close()
        self.upstream = AnthropicStub(lambda body, headers: self.answer)  # tearDown closes this one
        status, _, body = self.call(body=request([user(words('hi'))]))
        self.assertEqual((status, json.loads(body)['error']['type']), (502, 'api_connection_error'))
        self.assertEqual(self.records()[-1]['status'], 'upstream_error')

    def test_refused_truncated_and_failing_streams_never_complete_or_release_output(self):
        call = tool_use('toolu_a', 'robot', {'op': 'move'})
        cases = (
            ({'blocks': [thinking('s'), call], 'stop_reason': 'refusal', 'stop_details': {'type': 'refusal', 'category': 'bio'}},
             'response.failed', 'invalid_prompt', 'failed'),
            ({'blocks': [thinking('s'), call], 'stop_reason': 'max_tokens'}, 'response.incomplete', None, 'incomplete'),
            ({'blocks': [thinking('s'), call], 'truncate': True}, 'response.failed', 'server_error', 'failed'),
            ({'blocks': [thinking('s'), call], 'stream_error': {'type': 'overloaded_error', 'message': 'Overloaded'}},
             'response.failed', 'server_overloaded', 'failed'),
            ({'blocks': [text('other model')], 'model': 'claude-opus-5'}, 'response.failed', 'invalid_prompt', 'failed'),
        )
        for answer_, event, code, status in cases:
            with self.subTest(event=event, code=code):
                self.upstream.requests.clear()
                self.answer = answer_
                got, _, raw = self.call(body=request([user(words('hi'))]))
                events = sse(raw)
                names = [name for name, _ in events]
                self.assertEqual(got, 200)
                self.assertEqual(names[-1], event)
                self.assertNotIn('response.completed', names)
                self.assertFalse([name for name in names if name.startswith('response.output_item')])
                self.assertEqual(events[-1][1]['response']['output'], [])
                if code:
                    self.assertEqual(events[-1][1]['response']['error']['code'], code)
                self.assertEqual(len(self.upstream.requests), 1)  # never replayed by the gateway
                self.assertEqual(self.records()[-1]['status'], status)
        refused = next(record for record in self.records() if record.get('stop_reason') == 'refusal')
        self.assertEqual((refused['refusal_category'], refused['failure']), ('bio', 'invalid_prompt'))
        self.assertIn('usage', refused)

    def test_untranslatable_requests_are_refused_before_any_upstream_call(self):
        for body in (request([user(words('hi'))], model='gpt-6.1-sol'),
                     request([user({'type': 'input_file', 'file_id': 'f'})]),
                     request([user(words('hi'))], previous_response_id='resp_1')):
            status, _, raw = self.call(body=body)
            self.assertEqual((status, json.loads(raw)['error']['type']), (400, 'invalid_request_error'))
        with closing(http.client.HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=20)) as connection:
            connection.request('POST', '/v1/responses', body='{not json', headers={'Authorization': 'Bearer ' + LOCAL_KEY})
            self.assertEqual(connection.getresponse().status, 400)
        self.assertEqual(self.upstream.requests, [])
        self.assertEqual({record['failure'] for record in self.records()}, {'protocol'})

    def test_a_sessions_tools_survive_for_its_compaction_request_and_a_gateway_restart(self):
        history = [developer('BASE'), user(words('go'))]
        self.call(body=request(history), headers={'session-id': 'thread-1'})
        compact = request(history + [user(words('CONTEXT CHECKPOINT COMPACTION'))], tools=[])
        status, _, _ = self.call(body=compact, headers={'session-id': 'thread-1'})
        self.assertEqual(status, 200)
        normal, restored = (entry['body'] for entry in self.upstream.requests[-2:])
        strip = lambda tools: [{k: v for k, v in tool.items() if k != 'cache_control'} for tool in tools]
        self.assertEqual(strip(restored['tools']), strip(normal['tools']))
        self.assertEqual(restored['tool_choice'], {'type': 'none'})
        self.assertTrue(self.records()[-1]['tools_restored'])
        # A request that replays tool calls for a session this process never saw is an error...
        called = history + [{'type': 'function_call', 'call_id': 'toolu_a', 'name': 'robot', 'arguments': '{}'},
                            {'type': 'function_call_output', 'call_id': 'toolu_a', 'output': 'ok'}]
        self.assertEqual(self.call(body=request(called, tools=[]), headers={'session-id': 'thread-unknown'})[0], 400)
        # ...while the private state folder carries a known session across a restart.
        self.gateway.sessions.clear()
        self.assertEqual(self.call(body=request(called, tools=[]), headers={'session-id': 'thread-1'})[0], 200)
        self.assertEqual({path.stat().st_mode & 0o777 for path in (self.directory/'state').iterdir()}, {0o600})


if __name__ == '__main__':
    unittest.main()
