"""A robot_only Claude turn has the robot tool and nothing else.

The command-line checks need no CLI. The integration test runs the real Claude CLI
against a local stub model (nothing reaches a provider) and reads the tool list the
model is actually sent, on a first turn, a resumed session and a fork; it is skipped
when no `claude` binary is installed.
"""
import base64
import http.server
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import uuid

from engines.test_claude_policy_sandbox_integration import cli_version, stub_model
from robofrontier.engines.claude import runner
from robofrontier.engines.claude.robot_mcp import RobotBridge
from robofrontier.engines.claude.runner import ROBOT_TOOL, build_command

PNG = b'\x89PNG\r\n\x1a\n' + b'\0' * 32
# A stand-in robot MCP server: one tool named robot that answers with its own arguments.
SERVER = r'''
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request: continue
    method = request.get('method')
    if method == 'initialize':
        result = {'protocolVersion': request['params'].get('protocolVersion', '2025-03-26'),
                  'capabilities': {'tools': {}}, 'serverInfo': {'name': 'robot', 'version': '0'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'robot', 'description': 'Stand-in robot tool.',
                             'inputSchema': {'type': 'object', 'properties': {'op': {'type': 'string'}}}}]}
    elif method == 'tools/call':
        result = {'content': [{'type': 'text', 'text': 'ROBOT-RAN ' + json.dumps(request['params'].get('arguments'))}]}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
'''


def option(command, name):
    return command[command.index(name) + 1]


class CommandTests(unittest.TestCase):
    def test_robot_only_loads_no_built_in_tool_and_allows_only_the_robot_tool(self):
        command = build_command('claude-opus-5-5', 'high', '/run/mcp.json', None, session_id='s', auth_mode='oauth_token',
                                stream_input=True, system_prompt='rules', robot_only=True)
        self.assertEqual(option(command, '--tools'), '')
        self.assertEqual(option(command, '--allowedTools'), ROBOT_TOOL)
        self.assertEqual(command[command.index('--allowedTools') + 2][:2], '--')  # Nothing else is pre-allowed.
        self.assertEqual(option(command, '--permission-mode'), 'dontAsk')
        self.assertEqual(option(command, '--setting-sources'), '')
        self.assertIn('--strict-mcp-config', command)
        self.assertNotIn('--settings', command)
        self.assertNotIn('--bare', command)
        for tool in runner.POLICY_TOOLS:
            self.assertNotIn(tool, ' '.join(command))

    def test_an_api_key_robot_only_turn_never_uses_bare_which_would_load_file_tools(self):
        command = build_command('claude-opus-5-5', 'high', '/run/mcp.json', 'go', session_id='s', auth_mode='api_key',
                                robot_only=True)
        self.assertNotIn('--bare', command)
        self.assertEqual(option(command, '--setting-sources'), '')

    def test_a_delegate_fork_keeps_its_gate_hook_and_still_gets_no_other_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = {'open': Path(tmp)/'open', 'closed': Path(tmp)/'closed', 'deadline': 4102444800}
            command = build_command('claude-opus-5-5', 'high', '/run/mcp.json', None, session_id='child', fork_from='parent',
                                    auth_mode='oauth_token', stream_input=True, gate=gate, settings_dir=Path(tmp)/'settings',
                                    robot_only=True)
            settings = json.loads(Path(option(command, '--settings')).read_text())
        self.assertEqual(set(settings), {'hooks'})
        self.assertEqual(settings['hooks']['PreToolUse'][0]['matcher'], '*')
        self.assertEqual(option(command, '--tools'), '')
        self.assertEqual(option(command, '--allowedTools'), ROBOT_TOOL)
        self.assertIn('--fork-session', command)

    def test_file_settings_or_a_turn_without_the_robot_tool_are_not_robot_only(self):
        with self.assertRaises(ValueError):
            build_command('claude-opus-5-5', 'high', '/run/mcp.json', 'go', session_id='s', robot_only=True,
                          settings={'permissions': {'deny': []}})
        with self.assertRaises(ValueError):
            build_command('claude-opus-5-5', 'high', '/run/mcp.json', 'go', session_id='s', robot_only=True,
                          enable_robot=False)

    def test_the_run_decides_and_a_full_run_keeps_its_file_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)/'run'; (run/'private/inputs').mkdir(parents=True)
            (run/'private/inputs/policy-access.json').write_text(json.dumps(
                {'schema': 'robofrontier.policy-access.v1', 'filesystem': {str(run/'workspace'): 'write'}, 'network': False}))
            (run/'private/inputs/harness.json').write_text(json.dumps({'topology': 'adaptive'}))
            self.assertFalse(runner.robot_only(run))
            self.assertIsNotNone(runner.turn_settings(run))
            (run/'private/inputs/harness.json').write_text(json.dumps({'topology': 'adaptive', 'tool_mode': 'robot_only'}))
            self.assertTrue(runner.robot_only(run))
            self.assertIsNone(runner.turn_settings(run))
            # Still a run with the frozen policy contract: it keeps one CLI process per session.
            self.assertIsNotNone(runner.policy_settings(run))


class BridgeTests(unittest.TestCase):
    """What the robot MCP returns for a robot_only run's public_file results."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.run = Path(self.tmp.name).resolve()/'run'
        (self.run/'private/state/connections').mkdir(parents=True); (self.run/'public/inputs').mkdir(parents=True)
        connection = self.run/'private/state/connections/Controller.json'
        connection.write_text(json.dumps({'actor': 'Controller', 'run_id': 'run'}))
        (self.run/'public/inputs/target.png').write_bytes(PNG)
        (self.run/'private/secret.png').write_bytes(PNG)
        self.answer = {}
        self.bridge = RobotBridge(self.run, connection, invoke=lambda *args, **kwargs: dict(self.answer))

    def tearDown(self): self.tmp.cleanup()

    def content(self, op, data):
        return self.bridge.call({'op': op, 'data': data})['content']

    def test_text_is_returned_beside_the_result_as_it_is(self):
        self.answer = {'public_file': {'path': 'public/inputs/rules.md', 'kind': 'text', 'text': '# Rules\n"quoted" line\n'}}
        content = self.content('public_file', {'path': 'rules.md'})
        self.assertEqual([item['type'] for item in content], ['text', 'text'])
        self.assertEqual(content[1]['text'], '# Rules\n"quoted" line\n')
        self.assertNotIn('text', json.loads(content[0]['text'])['public_file'])

    def test_an_image_is_returned_as_an_image_and_never_from_outside_public(self):
        self.answer = {'public_file': {'path': 'public/inputs/target.png', 'kind': 'image',
                                       'image': str(self.run/'public/inputs/target.png')}}
        content = self.content('public_file', {'path': 'target.png'})
        self.assertEqual(content[1], {'type': 'image', 'data': base64.b64encode(PNG).decode(), 'mimeType': 'image/png'})
        self.answer = {'public_file': {'path': 'x', 'kind': 'image', 'image': str(self.run/'private/secret.png')}}
        content = self.content('public_file', {'path': 'x'})
        self.assertEqual([item['type'] for item in content], ['text', 'text'])
        self.assertIn('could not be loaded', content[1]['text'])

    def test_a_report_the_runtime_already_inlined_is_kept(self):
        self.answer = {'delegate_report': {'actor': 'Delegate_0123456789ab', 'result': 'from the runtime'},
                       'delegate_status': {}}
        result = json.loads(self.content('work', {'delegate_id': 'Delegate_0123456789ab'})[0]['text'])
        self.assertEqual(result['delegate_report']['result'], 'from the runtime')

    def test_skills_and_public_file_pass_the_shared_operation_check(self):
        self.answer = {'skills': {'entries': []}}
        self.assertIn('entries', self.content('skills', {'action': 'headings'})[0]['text'])
        with self.assertRaises(ValueError): self.content('read_file', {'path': 'x'})


@unittest.skipUnless(shutil.which('claude'), 'Claude Code CLI is not installed')
class RealCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.version = cli_version()

    def _formatMessage(self, msg, standardMsg):
        return 'claude %s: %s' % (self.version, super()._formatMessage(msg, standardMsg))

    def test_the_model_is_sent_only_the_robot_tool_on_start_resume_and_fork(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve(); run = t/'repo/runs/b/p/case'
            for name in ('workspace', 'public/inputs', 'private'): (run/name).mkdir(parents=True)
            (run/'public/inputs/task.json').write_text('PUBLIC-TASK')
            (t/'server.py').write_text(SERVER)
            mcp = t/'mcp.json'
            mcp.write_text(json.dumps({'mcpServers': {'robot': {'command': sys.executable, 'args': [str(t/'server.py')]}}}))
            steps = [('Bash', {'command': 'touch ' + str(run/'workspace/bash.txt'), 'description': 'probe'}),
                     ('Read', {'file_path': str(run/'public/inputs/task.json')}),
                     ('Write', {'file_path': str(run/'workspace/tool.txt'), 'content': 'x'}),
                     ('Edit', {'file_path': str(run/'public/inputs/task.json'), 'old_string': 'PUBLIC', 'new_string': 'EDITED'}),
                     ('Glob', {'pattern': '**/*', 'path': str(run)}),
                     ('Grep', {'pattern': 'PUBLIC', 'path': str(run)}),
                     (ROBOT_TOOL, {'op': 'ready'})]
            results, seen = [], []
            base = stub_model(steps, results)

            class Recording(base):
                def do_POST(self):
                    raw = self.rfile.read(int(self.headers['Content-Length']))
                    seen.append(sorted(tool.get('name') for tool in json.loads(raw).get('tools', [])))
                    self.rfile = io.BytesIO(raw)
                    super().do_POST()
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Recording)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(t/'home'),
                   'ANTHROPIC_BASE_URL': 'http://127.0.0.1:%d' % server.server_port,
                   'ANTHROPIC_API_KEY': 'local-fake-key', 'CLAUDE_CONFIG_DIR': str(t/'config'),
                   'DISABLE_TELEMETRY': '1', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
                   'ENABLE_TOOL_SEARCH': 'false', 'ENABLE_CLAUDEAI_MCP_SERVERS': 'false'}
            (t/'home').mkdir()
            parent, child = str(uuid.uuid4()), str(uuid.uuid4())
            gate = {'open': t/'gate-open', 'closed': t/'gate-closed', 'deadline': 4102444800}
            gate['open'].write_text('')

            def turn(**session):
                command = build_command('claude-opus-5-5', 'high', str(mcp), 'go', auth_mode='oauth_token',
                                        system_prompt='Offline check.', robot_only=True,
                                        settings_dir=t/'settings', **session)
                done = subprocess.run(command, cwd=run/'workspace', env=env, text=True, capture_output=True,
                                      stdin=subprocess.DEVNULL, timeout=180)
                self.assertEqual(done.returncode, 0, done.stderr[-800:] or done.stdout[-800:])
            try:
                turn(session_id=parent)
                first = len(seen)
                self.assertEqual(len(results), len(steps))
                turn(resume=parent)
                resumed = len(seen)
                turn(session_id=child, fork_from=parent, gate=gate)
            finally:
                server.shutdown(); server.server_close()
            self.assertGreater(first, 0); self.assertGreater(resumed, first); self.assertGreater(len(seen), resumed)
            for tools in seen:
                self.assertEqual(tools, [ROBOT_TOOL])

            def text(index):
                content = results[index].get('content')
                return content if isinstance(content, str) else ' '.join(c.get('text', '') for c in content)
            for index in range(6):
                self.assertTrue(results[index].get('is_error'), text(index))
                self.assertNotIn('PUBLIC-TASK', text(index))
            self.assertFalse(results[6].get('is_error'), text(6))
            self.assertIn('ROBOT-RAN', text(6))
            self.assertEqual((run/'public/inputs/task.json').read_text(), 'PUBLIC-TASK')
            self.assertEqual(sorted(p.name for p in (run/'workspace').iterdir()), [])


@unittest.skipUnless(shutil.which('claude'), 'Claude Code CLI is not installed')
class AdaptiveChainTests(unittest.TestCase):
    def test_delegate_fork_and_return_with_the_robot_tool_alone(self):
        """The adaptive integration test (real CLI, runtime and robot MCP; stub model and
        world) on a run prepared robot_only: the Controller delegates, the gated fork returns
        its task, and every request of parent and child offers the robot tool alone."""
        import engines.test_claude_adaptive_integration as base
        prepare = base.prepare_run
        prepared = []

        def robot_only_run(directory, harness_path=None, **options):
            config = json.loads(Path(harness_path).read_text())
            config['tool_mode'] = 'robot_only'
            Path(harness_path).write_text(json.dumps(config))
            run = prepare(directory, harness_path=harness_path, **options)
            prepared.append(runner.robot_only(run))
            return run
        with mock.patch.object(base, 'prepare_run', robot_only_run):
            base.AdaptiveIntegrationTests('test_cli_runtime_delegate_fork_and_return').test_cli_runtime_delegate_fork_and_return()
        self.assertEqual(prepared, [True])
        offered = [sorted(tool['name'] for tool in request.get('tools', [])) for request in base.StubModel.requests]
        self.assertGreaterEqual(len(offered), 4)
        for tools in offered:
            self.assertEqual(tools, [ROBOT_TOOL])
        delegate = [request for request in base.StubModel.requests
                    if 'Your current runtime role is Delegate_' in json.dumps(request.get('messages', []))]
        self.assertTrue(delegate)
        first = json.dumps(delegate[0]['messages'])
        self.assertIn('robot op skills', first)
        self.assertNotIn('skills.md before acting', first)


if __name__ == '__main__':
    unittest.main()
