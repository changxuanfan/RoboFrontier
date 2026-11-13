"""Real CLI transport and sandbox regression probes against a local Gemini stub."""
import http.server
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest

from robofrontier.engines.antigravity.driver import Driver, summarize
from robofrontier.engines.antigravity.gateway import Gateway
from robofrontier.engines.antigravity.hook import decision
from robofrontier.engines.antigravity.profile import validate
from robofrontier.runtime import access, policy_env
from robofrontier.runtime.setup import write_json


class ProfileTests(unittest.TestCase):
    def test_service_accepts_https_and_only_loopback_http(self):
        profile = {'model': 'flash', 'effort': 'low', 'auth_mode': 'api_key', 'env_key': 'RF_TEST_KEY'}
        for endpoint in ('https://example.com', 'http://localhost:18450', 'http://127.0.0.1:18450', 'http://[::1]:18450'):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(validate({**profile, 'base_url': endpoint+'/'})['base_url'], endpoint)
        for endpoint in ('http://example.com', 'http://localhost.example.com', 'http://127.0.0.1.example.com',
                         'http://0.0.0.0', 'http://192.168.1.2'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate({**profile, 'base_url': endpoint})

    def test_loopback_exception_does_not_allow_embedded_credentials_query_or_fragment(self):
        profile = {'model': 'flash', 'effort': 'low', 'auth_mode': 'api_key', 'env_key': 'RF_TEST_KEY'}
        for endpoint in ('http://user:password@localhost', 'http://localhost?key=synthetic', 'http://localhost#fragment'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate({**profile, 'base_url': endpoint})

    def test_subscription_cannot_be_redirected_to_a_service(self):
        with self.assertRaises(ValueError):
            validate({'model': 'flash', 'effort': 'low', 'auth_mode': 'native_login', 'base_url': 'https://example.com'})

    def test_model_text_cannot_trigger_capacity_recovery(self):
        value = summarize([{'event': 'result', 'result': {'conversation_id': 'same', 'status': 'SUCCESS',
            'response': 'rate_limit server_overloaded'}}], 'same')
        self.assertIsNone(value['capacity_error_code'])
        self.assertEqual(value['turn_status'], 'ended')

    def test_generic_quota_error_is_not_assumed_to_be_capacity(self):
        value = summarize([{'event': 'result', 'result': {'conversation_id': 'same', 'status': 'ERROR',
            'error': {'code': 'RESOURCE_EXHAUSTED'}}}], 'same')
        self.assertIsNone(value['capacity_error_code'])

    def test_file_hook_rejects_workspace_symlink_to_private(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            (run/'workspace').mkdir()
            (run/'private').mkdir()
            (run/'workspace/link').symlink_to(run/'private', target_is_directory=True)
            result = decision(run, {'tool_name': 'write_file', 'tool_input': {'Path': str(run/'workspace/link/x')}})
            self.assertEqual(result['decision'], 'deny')


class Stub:
    def __init__(self, response=None, usage=None):
        self.requests = []
        self.headers = []
        self.response = response
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(body)
                owner.headers.append(dict(self.headers))
                parts = owner.response(body) if owner.response else [{'text': 'READY'}]
                value = {'candidates': [{'content': {'role': 'model', 'parts': parts},
                    'finishReason': 'STOP', 'index': 0}],
                    'usageMetadata': (usage(body) if usage else
                        {'promptTokenCount': 11, 'candidatesTokenCount': 2, 'totalTokenCount': 13})}
                payload = ('data: ' + json.dumps(value) + '\r\n\r\n').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return 'http://127.0.0.1:' + str(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def fixture(run):
    for folder in ('workspace', 'public/inputs', 'private/inputs/bootstrap', 'private/state'):
        (run/folder).mkdir(parents=True, exist_ok=True)
    root = policy_env.apply_default()
    policy_env.prepare_run(run, root)
    write_json(run/'private/inputs/policy-access.json', access.record(run, environment=root, unchecked=True))
    (run/'private/inputs/bootstrap/system.md').write_text('You are a RoboFrontier policy agent. Keep the task contract.\n')


@unittest.skipUnless(os.environ.get('ROBOFRONTIER_ANTIGRAVITY_INTEGRATION') == '1' and shutil.which('agy'),
                     'opt-in real agy CLI against a local service; no provider calls')
class NativeTests(unittest.TestCase):
    def test_full_preflight_with_native_blocked_parent_and_fork(self):
        import functools
        from unittest.mock import patch
        from robofrontier.engines.antigravity import preflight
        def response(body):
            contents = body.get('contents', [])
            users = [' '.join(p.get('text', '') for p in c.get('parts', []))
                     for c in contents if c.get('role') == 'user' and any('text' in p for p in c.get('parts', []))]
            # Restart/fork notices are separate user-role messages in the native
            # wire format. The scripted model responds to the last actual request.
            text = next((t for t in reversed(users) if '<USER_REQUEST>' in t), '')
            parts = contents[-1].get('parts', []) if contents else []
            if 'Reply with exactly the word ready' in text:
                return [{'text': 'ready'}]
            if 'Without tools' in text or 'without tools' in text:
                return [{'text': 'red green'}]
            if parts and 'functionResponse' in parts[-1]:
                return [{'text': 'parent done' if 'parent done' in text else 'red green'}]
            return [{'functionCall': {'name': 'mcp_robofrontier_robot', 'args': {
                'op': 'observe', 'data': {}, 'views': ['top'], 'toolSummary': 'Read compatibility image'}}}]
        stub = Stub(response)
        selected = {'model': 'gemini-3.8-flash-low', 'effort': 'low', 'auth_mode': 'api_key',
                    'env_key': 'RF_TEST_KEY', 'base_url': 'https://generativelanguage.googleapis.com'}
        try:
            with tempfile.TemporaryDirectory(prefix='rf-agy-preflight-') as folder, \
                    patch.object(preflight, 'runs_root', return_value=Path(folder).resolve()), \
                    patch.object(preflight, 'profile', return_value=selected), \
                    patch.object(preflight.preflight_probe, 'choose', return_value=('red', 'green')), \
                    patch.object(preflight, 'Driver', functools.partial(Driver,
                        gateway_factory=lambda base, key: Gateway(stub.url, key))), \
                    patch.dict(os.environ, {'RF_TEST_KEY': 'fake'}):
                report = preflight.run_precheck('local-stub-only')
                self.assertTrue(report['passed'], report)
        finally:
            stub.close()

    def test_model_service_receives_exactly_the_frozen_system_prompt(self):
        from robofrontier.engines.antigravity.provenance import steps
        from robofrontier.runtime.bootstrap import SYSTEM_PROMPT
        from robofrontier.configuration import ROOT
        stub = Stub()
        self.addCleanup(stub.close)
        with tempfile.TemporaryDirectory(prefix='rf-agy-system-') as folder:
            run = Path(folder).resolve()
            fixture(run)
            # What a prepared run freezes: the role statement, then the released rules.
            system = SYSTEM_PROMPT + '\n' + (ROOT/'prompts/rules.md').read_text().rstrip('\n') + '\n'
            self.assertGreater(system.count('\n'), 10)
            (run/'private/inputs/bootstrap/system.md').write_text(system)
            selected = {'model': 'gemini-3.8-flash-low', 'effort': 'low', 'auth_mode': 'api_key',
                        'env_key': 'RF_TEST_KEY', 'base_url': 'https://generativelanguage.googleapis.com'}
            make = lambda actor, session=None: Driver(run, actor, selected, {**os.environ, 'RF_TEST_KEY': 'fake'},
                session=session, gateway_factory=lambda base, key: Gateway(stub.url, key))
            def received():
                return '\n'.join(p.get('text', '') for p in stub.requests[-1]['systemInstruction']['parts'])
            driver = make('Controller')
            self.addCleanup(driver.close)
            sid = driver.open()
            for name in ('one', 'two'):
                driver(selected, selected['model'], 'low', None, 'Input ' + name, run, {}, events_name=name+'.jsonl', timeout=30)
                # Only the file's final newline is dropped.
                self.assertEqual(received(), system.rstrip('\n'))
                driver.close()
                driver.open()
            child = make('ForkProbe', driver.fork(len(steps(driver.home, sid))-1))
            self.addCleanup(child.close)
            child.open()
            child(selected, selected['model'], 'low', None, 'Fork input', run, {}, events_name='fork.jsonl', timeout=30)
            self.assertEqual(received(), system.rstrip('\n'))
            for session in (sid, child.session):
                receipt = json.loads((run/'private/engine/context'/(session+'.json')).read_text())
                self.assertEqual(receipt['system_prompt'], 'frozen_system_prompt_only')

    def test_tool_hook_refuses_the_native_tools_the_cli_still_declares(self):
        # (tool mode, native call, refused). manage_task list/status is allowed in a full run.
        cases = (('robot_only', 'manage_task', {'Action': 'list'}, True),
                 ('robot_only', 'list_resources', {'ServerName': 'robofrontier'}, True),
                 ('full', 'manage_task', {'Action': 'kill', 'TaskId': 'x'}, True),
                 ('full', 'manage_task', {'Action': 'list'}, False))
        for mode, name, args, refused in cases:
            with self.subTest(mode=mode, tool=name, args=args), tempfile.TemporaryDirectory(prefix='rf-agy-hook-') as folder:
                def response(body, name=name, args=args):
                    if any('functionResponse' in p for p in body['contents'][-1]['parts']):
                        return [{'text': 'done'}]
                    return [{'functionCall': {'name': name, 'args': args}}]
                stub = Stub(response)
                run = Path(folder).resolve()
                fixture(run)
                write_json(run/'private/inputs/harness.json',
                           {'engine': 'antigravity', **({'tool_mode': mode} if mode != 'full' else {})})
                driver = Driver(run, 'Controller', {'model': 'gemini-3.8-flash-low', 'effort': 'low',
                    'auth_mode': 'api_key', 'env_key': 'RF_TEST_KEY', 'base_url': 'https://generativelanguage.googleapis.com'},
                    {**os.environ, 'RF_TEST_KEY': 'fake'}, gateway_factory=lambda base, key: Gateway(stub.url, key))
                try:
                    driver(driver.profile, driver.profile['model'], 'low', None, 'probe', run, {},
                           events_name='turn.jsonl', timeout=30)
                    results = [p['functionResponse']['response'] for c in stub.requests[-1]['contents']
                               for p in c['parts'] if 'functionResponse' in p]
                    self.assertEqual(len(results), 1)
                    self.assertEqual('denied by pre-tool hook' in json.dumps(results[0]), refused, results[0])
                finally:
                    driver.close()
                    stub.close()

    def test_reported_usage_crossing_limit_creates_native_checkpoint(self):
        for reported, expected in ((260000, False), (267001, True)):
            with self.subTest(reported=reported), tempfile.TemporaryDirectory(prefix='rf-agy-context-') as folder:
                run = Path(folder).resolve()
                fixture(run)
                stub = Stub(usage=lambda body: {
                    'promptTokenCount': reported if len(stub.requests) == 1 else 20,
                    'candidatesTokenCount': 2, 'totalTokenCount': reported+2 if len(stub.requests) == 1 else 22})
                driver = Driver(run, 'Controller', {'model': 'gemini-3.8-flash-low', 'effort': 'low',
                    'auth_mode': 'api_key', 'env_key': 'RF_TEST_KEY', 'base_url': 'https://generativelanguage.googleapis.com'},
                    {**os.environ, 'RF_TEST_KEY': 'fake'}, gateway_factory=lambda base, key: Gateway(stub.url, key))
                try:
                    for i in range(2):
                        result = driver(driver.profile, driver.profile['model'], 'low', None, 'hello '+str(i),
                            run, {}, events_name=str(i)+'.jsonl', timeout=30)
                        self.assertEqual(result['summary']['turn_status'], 'ended')
                    trajectory = driver.rpc('GetCascadeTrajectory', {'cascadeId': driver.session})['trajectory']
                    self.assertEqual(any(s['type'] == 'CORTEX_STEP_TYPE_CHECKPOINT' for s in trajectory['steps']), expected)
                finally:
                    driver.close()
                    stub.close()

    def test_id_before_input_persistent_resume_and_host_only_credential(self):
        stub = Stub()
        self.addCleanup(stub.close)
        with tempfile.TemporaryDirectory(prefix='rf-agy-') as folder:
            run = Path(folder).resolve()
            fixture(run)
            selected = {'model': 'gemini-3.8-flash-low', 'effort': 'low', 'auth_mode': 'api_key',
                        'env_key': 'RF_TEST_KEY', 'base_url': 'https://generativelanguage.googleapis.com'}
            driver = Driver(run, 'Controller', selected, {**os.environ, 'RF_TEST_KEY': 'host-secret-sentinel'},
                gateway_factory=lambda base, key: Gateway(stub.url, key))
            self.addCleanup(driver.close)
            sid = driver.open()
            self.assertTrue(sid)
            self.assertEqual(stub.requests, [])
            self.assertNotIn('host-secret-sentinel', json.dumps(driver.environment()))
            first = driver(selected, selected['model'], 'low', None, 'First input', run, {}, events_name='one.jsonl', timeout=30)
            second = driver(selected, selected['model'], 'low', None, 'Second input', run, {}, events_name='two.jsonl', timeout=30)
            self.assertEqual(first['summary']['turn_status'], 'ended')
            context = json.loads((run/'private/engine/context'/(sid+'.json')).read_text())
            self.assertEqual(context['effective_auto_compact_token_limit'], 267000)
            self.assertFalse(context['provider_context_capacity_verified'])
            self.assertEqual(second['summary']['session_id'], sid)
            self.assertEqual(len(stub.requests), 2)
            self.assertEqual(next(v for k, v in stub.headers[0].items() if k.lower() == 'x-goog-api-key'), 'host-secret-sentinel')
            driver.close()
            driver.open()
            self.assertEqual(driver.session, sid)
            third = driver(selected, selected['model'], 'low', None, 'Third input', run, {}, events_name='three.jsonl', timeout=30)
            self.assertEqual(third['summary']['turn_status'], 'ended')
            from robofrontier.engines.antigravity.provenance import steps
            forked = driver.fork(len(steps(driver.home, sid))-1)
            child = Driver(run, 'ForkProbe', selected, {**os.environ, 'RF_TEST_KEY': 'host-secret-sentinel'},
                session=forked, gateway_factory=lambda base, key: Gateway(stub.url, key))
            self.addCleanup(child.close)
            child.open()
            fourth = child(selected, selected['model'], 'low', None, 'Fork input', run, {}, events_name='four.jsonl', timeout=30)
            self.assertEqual(fourth['summary']['turn_status'], 'ended')
            self.assertEqual(json.loads((run/'private/engine/context'/(forked+'.json')).read_text())
                             ['effective_auto_compact_token_limit'], 267000)


if __name__ == '__main__':
    unittest.main()
