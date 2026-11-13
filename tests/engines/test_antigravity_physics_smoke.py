"""Opt-in real Antigravity CLI, MCP and MuJoCo; local fake Gemini only."""
import functools
import json
import os
import platform
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from engines.test_antigravity_driver import Stub
from robofrontier.batch.antigravity_prepare import prepare_batch
from robofrontier.configuration import rendering_environment
from robofrontier.engines.antigravity.driver import Driver
from robofrontier.engines.antigravity.gateway import Gateway
from robofrontier.engines.common.run import run_task
from robofrontier.runtime.store import RuntimeStore


@unittest.skipUnless(os.environ.get('ROBOFRONTIER_ANTIGRAVITY_PHYSICS') == '1' and shutil.which('agy'),
                     'opt-in real CLI and MuJoCo against a local model service')
class PhysicsTests(unittest.TestCase):
    def exercise(self, topology, robots=('A',), tool_mode='full'):
        def response(body):
            contents = body.get('contents', [])
            last = contents[-1].get('parts', []) if contents else []
            text = '\n'.join(p.get('text', '') for c in contents if c.get('role') == 'user' for p in c.get('parts', []))
            done = [p['functionResponse'] for c in contents for p in c.get('parts', []) if 'functionResponse' in p]
            child = 'Your current runtime role is Delegate_' in text
            if topology == 'adaptive' and child:
                op, data = ('return_task', {'outcome': 'completed', 'result': 'synthetic evidence'})
            elif topology == 'adaptive':
                op, data = 'delegate', {'scopes': [{'robots': [r], 'goal': 'synthetic', 'done_when': 'synthetic'} for r in robots]}
            elif topology == 'centralized':
                op, data = 'finish', {'note': 'synthetic early finish'}
            else:
                op, data = 'observe', {'cameras': ['global']}
            # One action per turn. A child inherits the parent's pending call but
            # has no response to its own return_task until it has actually run.
            already = any('"'+op+'"' in json.dumps(p.get('functionCall', {}).get('args', {}))
                          for c in contents for p in c.get('parts', []))
            if last and 'functionResponse' in last[-1]:
                return [{'text': 'done'}]
            if topology == 'adaptive' and not child and already:
                op, data = 'work', {}
            args = {'op': op, 'data': data, 'toolSummary': 'Synthetic robot call'}
            if op == 'observe':
                args['views'] = ['global']
            return [{'functionCall': {'name': 'mcp_robofrontier_robot', 'args': args}}]
        declared = []
        def recorded(body):
            declared.append(sorted(f['name'] for t in body.get('tools', []) for f in t.get('functionDeclarations', [])))
            return response(body)
        stub = Stub(recorded)
        scratch = Path(os.environ.get('ROBOFRONTIER_TEST_SCRATCH', str(Path.home()/'.cache/robofrontier-antigravity')))
        scratch.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix='physics-', dir=scratch)).resolve()
        result = None
        try:
            catalog = directory/'models.json'
            catalog.write_text(json.dumps({'profiles': {'stub': {'model': 'gemini-3.8-flash-low', 'effort': 'low',
                'auth_mode': 'api_key', 'env_key': 'RF_STUB_KEY', 'base_url': 'https://generativelanguage.googleapis.com'}}}))
            system = platform.system()
            render = os.environ.get('ROBOFRONTIER_TEST_RENDER', 'native' if system == 'Darwin' else 'cpu')
            env = rendering_environment(render, system, {**os.environ, 'RF_STUB_KEY': 'host-only-synthetic'})
            prepare_batch(directory/'batch', ['stub'], cases=['transport-a04-d1'], topology=topology,
                          catalog=catalog, render_device=render, wall_limit_s=12, tool_mode=tool_mode)
            run = directory/'batch/stub/transport-a04-d1'
            driver = functools.partial(Driver, gateway_factory=lambda base, key: Gateway(stub.url, key))
            with patch('robofrontier.engines.antigravity.session_host.Driver', driver):
                result = run_task(run, env, wall_limit_s=12, startup_timeout_s=90, poll_s=.1)
            self.assertEqual(result['status'], 'finished', {'result': result, 'retained': str(directory)})
            # Every request of every role, forked children included, declares the same tools.
            file_tools = ['mcp_robofrontier_policy_exec', 'mcp_robofrontier_policy_image']
            native = ['list_resources', 'manage_task', 'read_resource']  # Declared by the CLI; refused in robot_only.
            expected = sorted(['mcp_robofrontier_robot', *native, *([] if tool_mode == 'robot_only' else file_tools)])
            self.assertTrue(declared and all(tools == expected for tools in declared), declared[:3])
            if tool_mode == 'robot_only':
                self.assertFalse((run/'private/inputs/policy-tools.json').exists())
            self.assertTrue(result['seal']['sealed'])
            self.assertFalse(result['owner_alive'])
            self.assertEqual(result['seal']['unresolved_action_ids'], [])
            store = RuntimeStore(run/'private/state/runtime.sqlite')
            try:
                if topology == 'adaptive':
                    batches = list(store.get('delegations', {}).values())
                    self.assertEqual(len(batches), 1, str(directory))
                    self.assertEqual(batches[0]['status'], 'finished', {'batch': batches[0], 'retained': str(directory)})
                    # 'observed': the child had already returned when its start was recorded.
                    self.assertTrue(all(c['start_status'] in ('sent', 'observed') for c in batches[0]['children']),
                                    batches[0]['children'])
                    self.assertEqual({store.get('robot_owners')[r] for r in robots}, {'Controller'})
                    for child in batches[0]['children']:
                        fork = json.loads((run/'private/state/antigravity-forks'/(child['actor']+'.json')).read_text())
                        self.assertEqual(fork['status'], 'verified')
                        self.assertEqual(fork['proof']['pending_tool_id'], fork['binding']['tool_id'])
                    self.assertEqual(batches[0]['source_provenance']['pending_tool_id'], fork['binding']['tool_id'])
                elif topology == 'centralized':
                    self.assertEqual(result['reason'], 'world_ended')
                    self.assertFalse(json.loads((run/'private/outputs/evaluation.json').read_text())['task_success'])
                else:
                    self.assertTrue(all(a['thread_id'] for a in store.agents().values() if a['kind'] != 'manager'))
            finally:
                store.close()
        finally:
            stub.close()
            # Keep failed evidence for diagnosis; never remove a possible live owner.
            print('Antigravity physics evidence:', directory)

    def test_single(self):
        self.exercise('centralized')

    def test_adaptive(self):
        self.exercise('adaptive')

    def test_adaptive_two_children(self):
        self.exercise('adaptive', robots=('A', 'B'))

    def test_adaptive_robot_only(self):
        self.exercise('adaptive', robots=('A', 'B'), tool_mode='robot_only')

    def test_single_robot_only(self):
        self.exercise('centralized', tool_mode='robot_only')

    def test_controller_worker(self):
        self.exercise('hierarchical')

    def test_worker_worker(self):
        self.exercise('peer')


if __name__ == '__main__':
    unittest.main()
