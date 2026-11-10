"""Real installed Codex, synthetic OAuth/Responses, no login or provider calls.

Exercises the implemented engine/gateway/Unix transport, native named profiles,
native fork lineage and completed-child/fork-again rounds. It does not qualify
Linux kernel confinement, GPU rendering or genuine model behavior/capacity.
"""
import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from robofrontier.runtime import access as policy_access
from robofrontier.engines.codex.job_engine import build_manifest, engine
from robofrontier.engines.codex.launch import launch_config, profile
from robofrontier.engines.codex.tool_backend import prepare as prepare_tools
from robofrontier.runtime.setup import write_json
from robofrontier.batch.slurm_auth import CredentialLease, BorrowedAccess

ROOT = Path(__file__).resolve().parents[1]


def jwt(generation):
    claims = {'sub': 'fixture-user', 'email': 'fixture@example.invalid', 'exp': int(time.time())+3600,
              'fixture_generation': generation, 'https://api.openai.com/auth': {
                  'chatgpt_account_id': 'fixture-account', 'chatgpt_user_id': 'fixture-user', 'chatgpt_plan_type': 'pro'}}
    def enc(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    return enc({'alg': 'none', 'typ': 'JWT'})+'.'+enc(claims)+'.c2ln'


@unittest.skipUnless(shutil.which('codex') and shutil.which('node'), 'Native CLI and Node required')
class NativeGatewayTests(unittest.TestCase):
    def test_native_refresh_profiles_parallel_tools_fork_return_and_fork_again(self):
        state = {'generation': 0, 'refreshes': 0, 'stale': 0, 'requests': 0, 'paths': set()}
        lock = threading.Lock()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def reply(self, value, code=200):
                body = json.dumps(value).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                state['paths'].add(self.path)
                if self.path.endswith('/accounts/check'):
                    self.reply({'accounts': [{'id': 'fixture-account', 'workspace_backend_origin': 'https://chatgpt.com',
                                               'account_routing_override': 'NO_CONSTRAINT'}]})
                elif self.path.endswith('/usage'):
                    self.reply({'account_id': 'fixture-account', 'user_id': 'fixture-user', 'plan_type': 'pro',
                                'rate_limit': {'allowed': True, 'limit_reached': False, 'primary_window': {
                                    'used_percent': 1, 'limit_window_seconds': 18000,
                                    'reset_after_seconds': 120, 'reset_at': 2000000000}},
                                'rate_limit_reset_credits': {'available_count': 0}})
                elif self.path.endswith('/rate-limit-reset-credits'):
                    self.reply({'available_count': 0, 'credits': []})
                else:
                    self.reply({'error': 'loopback fixture endpoint only'}, 404)
            def do_POST(self):
                state['paths'].add(self.path)
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
                if self.path == '/oauth/token':
                    with lock:
                        if body.get('refresh_token') != 'fixture-refresh-'+str(state['generation']):
                            state['stale'] += 1
                            self.reply({'error': 'refresh_token_reused'}, 400)
                            return
                        state['generation'] += 1
                        state['refreshes'] += 1
                        generation = state['generation']
                        self.reply({'id_token': jwt(generation), 'access_token': jwt(generation),
                                    'refresh_token': 'fixture-refresh-'+str(generation), 'expires_in': 3600})
                    return
                if not self.path.endswith('/responses'):
                    self.reply({'error': 'loopback fixture endpoint only'}, 404)
                    return
                bearer = self.headers.get('Authorization', '').removeprefix('Bearer ')
                encoded = bearer.split('.')[1]
                generation = json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))['fixture_generation']
                if generation == 0:
                    self.reply({'error': {'message': 'Synthetic expired fixture token', 'type': 'invalid_token'}}, 401)
                    return
                with lock:
                    state['requests'] += 1
                    number = state['requests']
                identifier = 'response-fixture-'+str(number)
                if body.get('input', [])[-1].get('type') == 'function_call_output':
                    item = {'type': 'message', 'role': 'assistant', 'id': 'message-'+str(number),
                            'content': [{'type': 'output_text', 'text': 'Bounded fixture complete.'}]}
                else:
                    item = {'type': 'function_call', 'call_id': 'fixture-call-'+str(number), 'name': 'robot',
                            'arguments': json.dumps({'op': 'inbox', 'data': {}})}
                events = [{'type': 'response.created', 'response': {'id': identifier}},
                          {'type': 'response.output_item.done', 'item': item},
                          {'type': 'response.completed', 'response': {'id': identifier, 'usage': {
                              'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}}}]
                data = ''.join('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n' for event in events).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        class FixtureServer(ThreadingHTTPServer):
            request_queue_size = 128
        server = FixtureServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        address = 'http://127.0.0.1:'+str(server.server_port)
        # Short path also works with macOS's 104-byte Unix socket limit.
        with tempfile.TemporaryDirectory(prefix='rfg-', dir='/tmp') as temporary:
            root = Path(temporary).resolve()
            private = root/'engine'
            private.mkdir(mode=0o700)
            store = root/'credentials'
            store.mkdir(mode=0o700)
            write_json(store/'auth.json', {'auth_mode': 'chatgpt', 'OPENAI_API_KEY': None, 'tokens': {
                'id_token': jwt(0), 'access_token': jwt(0), 'refresh_token': 'fixture-refresh-0', 'account_id': 'fixture-account'},
                'last_refresh': '2000-01-01T00:00:00Z'})
            environment = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG') if k in os.environ}
            environment.update(CODEX_HOME=str(private/'codex'), ROBOFRONTIER_JOB_PRIVATE_ROOT=str(private),
                               ROBOFRONTIER_CREDENTIAL_STORE=str(store),
                               CODEX_REFRESH_TOKEN_URL_OVERRIDE=address+'/oauth/token', NO_PROXY='127.0.0.1,localhost')
            jobs = []
            with CredentialLease(store, private/'codex') as lease, patch.dict(os.environ, environment, clear=True):
                selected = profile('luna_subscription')
                selected.update(tool_backend='landlock-v1', runner_backend='slurm-managed-v1', use_cached_model_metadata=False)
                for index in range(38):
                    run = root/'runs'/str(index)
                    for name in ('private/inputs', 'workspace', 'public'):
                        (run/name).mkdir(parents=True)
                    access = policy_access.record(run, checkouts=[root])
                    access['filesystem']['/proc'] = 'deny'
                    write_json(run/'private/inputs/policy-access.json', access)
                    prepare_tools(run, selected)
                    launch = launch_config(selected, run/'private/inputs', run)
                    for key, value in {'chatgpt_base_url': address, 'analytics.enabled': False,
                                       'model_providers.robofrontier_openai_http.base_url': address+'/v1',
                                       'model_providers.robofrontier_openai_http.name': 'Offline fixture'}.items():
                        launch['args'] += ['-c', key+'='+json.dumps(value)]
                    write_json(run/'private/inputs/codex.json', launch)
                    jobs.append({'run_directory': str(run)})
                try:
                    with engine(jobs[:36], env=environment, timeout_s=35) as (manifest, process):
                        result = subprocess.run(['node', str(ROOT/'tests/slurm_gateway_native_client.js'),
                                                 str(private/'control/manifest.json')],
                                                capture_output=True, text=True, env=environment, timeout=65)
                        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
                        report = json.loads(result.stdout)
                        self.assertEqual((report['parents'], report['children'], report['completed']), (36, 72, 108))
                        self.assertEqual(report['physical_actions'], 0)
                        self.assertTrue(report['single_task_recovery'])
                        self.assertEqual(report['recovery_tools'], 2)
                        self.assertTrue(lease.reconcile())
                        before=(private/'codex/auth.json').read_bytes()
                        borrower=root/'borrower';borrower.mkdir(mode=0o700)
                        borrowed_env={**environment,'CODEX_HOME':str(borrower/'codex'),
                                      'ROBOFRONTIER_JOB_PRIVATE_ROOT':str(borrower),
                                      'ROBOFRONTIER_BORROWED_AUTH':str(store/'current.json')}
                        with BorrowedAccess(store,borrower/'codex') as reader:
                            with engine(jobs[36:],env=borrowed_env,timeout_s=35):
                                attached=subprocess.run(['node',str(ROOT/'tests/slurm_gateway_native_client.js'),
                                                         str(borrower/'control/manifest.json')],
                                                        capture_output=True,text=True,env=borrowed_env,timeout=65)
                                self.assertEqual(attached.returncode,0,attached.stderr[-2000:])
                                self.assertEqual(json.loads(attached.stdout)['parents'],2)
                                self.assertIsNone(process.poll())
                                self.assertFalse(reader.reconcile())
                            self.assertFalse((borrower/'codex/auth.json').exists())
                        self.assertEqual((private/'codex/auth.json').read_bytes(),before)
                    exported = [json.loads((Path(job['run_directory'])/'private/engine/gateway-transcripts/index.json').read_text())
                                for job in jobs[:36]]
                    self.assertEqual(sum(len(row['threads']) for row in exported), 109)
                    self.assertTrue(all(t.get('verified') for row in exported for t in row['threads']))
                    self.assertFalse(any(p.name == 'auth.json' for p in (root/'runs').rglob('*')))
                    # The original native writer is now stopped. Only owned
                    # transcripts enter a new private home; no auth cache copy.
                    owned=json.loads((private/'control/ownership.json').read_text())[:2]
                    cold=root/'cold';cold.mkdir(mode=0o700)
                    cold_env={**environment,'CODEX_HOME':str(cold/'codex'),
                              'ROBOFRONTIER_JOB_PRIVATE_ROOT':str(cold),
                              'ROBOFRONTIER_BORROWED_AUTH':str(store/'current.json')}
                    with BorrowedAccess(store,cold/'codex'):
                        cold_jobs=[]
                        for job,row in zip(jobs[:2],owned):
                            cold_jobs.append({**job,'resume_threads':row['threads']})
                            for thread in row['threads']:
                                matches=list((private/'codex/sessions').rglob('*'+thread+'.jsonl'))
                                self.assertEqual(len(matches),1)
                                target=cold/'codex/sessions'/matches[0].relative_to(private/'codex/sessions')
                                target.parent.mkdir(parents=True,exist_ok=True)
                                shutil.copy2(matches[0],target)
                        with engine(cold_jobs,env=cold_env,timeout_s=35):
                            continued=subprocess.run(['node',str(ROOT/'tests/slurm_cold_resume_client.js'),
                                                      str(cold/'control/manifest.json')],
                                                     capture_output=True,text=True,env=cold_env,timeout=65)
                            self.assertEqual(continued.returncode,0,continued.stderr[-2000:])
                            self.assertTrue(json.loads(continued.stdout)['original_thread_ids_preserved'])
                except Exception:
                    # Only a synthetic, isolated log; no operator credentials.
                    log = private/'control/native.log'
                    if log.is_file():
                        print('Synthetic native diagnostic:', log.read_text()[-1800:])
                    raise
            self.assertGreaterEqual(state['refreshes'], 1)
            self.assertEqual(state['stale'], 0)
            self.assertEqual(state['requests'], 240)
            self.assertEqual(json.loads((store/'current.json').read_text())['auth']['tokens']['refresh_token'],
                             'fixture-refresh-'+str(state['generation']))


if __name__ == '__main__':
    unittest.main()
