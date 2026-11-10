"""Pin the policy-turn permissions to the real Claude CLI, using a local stub model only.

The stub replays a fixed list of tool calls; nothing is sent to a provider. It
checks that a run-v4 policy writes only workspace/, its working directory (never the run
root, public/, private/ or .agents/), and cannot read answers or credentials, including the
private/ folder of a run prepared beside it after the CLI started. Network access is
configured but not exercised here. Skipped when no `claude` binary is installed.
"""
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

from robofrontier.runtime import access as policy_access
from robofrontier.engines.claude.runner import build_command, build_env, policy_settings, POLICY_TOOLS
from robofrontier.runtime.layout import manifest_record


def stub_model(steps, results, before=None):
    """Replay `steps`; `before(index)` runs just before step `index` is sent to the CLI."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            done = [item for message in body.get('messages', []) if isinstance(message.get('content'), list)
                    for item in message['content'] if isinstance(item, dict) and item.get('type') == 'tool_result']
            if len(done) > len(results): results[:] = done
            index = len(done)
            if before is not None: before(index)
            if index < len(steps):
                name, data = steps[index]
                block, delta, reason = ({'type': 'tool_use', 'id': 'toolu_%d' % index, 'name': name, 'input': {}},
                                        {'type': 'input_json_delta', 'partial_json': json.dumps(data)}, 'tool_use')
            else:
                block, delta, reason = {'type': 'text', 'text': ''}, {'type': 'text_delta', 'text': 'done'}, 'end_turn'
            message = {'id': 'msg_stub', 'type': 'message', 'role': 'assistant', 'model': 'claude-opus-5-5', 'content': [],
                       'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 1}}
            events = [('message_start', {'type': 'message_start', 'message': message}),
                      ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': block}),
                      ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': delta}),
                      ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
                      ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': reason, 'stop_sequence': None},
                                         'usage': {'output_tokens': 1}}),
                      ('message_stop', {'type': 'message_stop'})]
            data = ''.join('event: %s\ndata: %s\n\n' % (name, json.dumps(payload)) for name, payload in events).encode()
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    return Handler


def frozen_settings(run, repo, home):
    """Freeze this run's access table as preparation does, then render it for Claude."""
    path = Path(run) / 'private/inputs/policy-access.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy_access.record(run, repo=repo, home=home, tmp_dirs=(), checkouts=[repo])))
    return policy_settings(run)


def cli_version():
    """The installed CLI's version, named in failures: the rule matching is the CLI's own."""
    try:
        return subprocess.run(['claude', '--version'], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        return 'unknown (%s)' % error


@unittest.skipUnless(shutil.which('claude'), 'Claude Code CLI is not installed')
class PolicySandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.version = cli_version()

    def _formatMessage(self, msg, standardMsg):
        # Every assertion failure names the CLI version, since matching rules are the CLI's own.
        return 'claude %s: %s' % (self.version, super()._formatMessage(msg, standardMsg))

    def test_policy_tools_work_in_run_but_cannot_reach_answers_credentials_or_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve()
            repo, home = t / 'repo', t / 'home'
            run, other = repo / 'runs/batch/profile/case-a', repo / 'runs/batch/profile/case-b'
            # Prepared under the same runs folder only after the CLI has started (see `later`).
            late = repo / 'runs/later-batch/profile/case-z'
            files = {run / 'public/inputs/task.json': 'PUBLIC-TASK', run / 'private/inputs/task.json': 'OWN-ANSWER',
                     other / 'private/inputs/task.json': 'OTHER-ANSWER', repo / 'configs/task.json': 'REPO-ANSWER',
                     repo / '.env': 'ENV-SECRET', home / '.claude/credentials': 'HOME-SECRET'}
            for path, text in files.items():
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            for name in ('workspace', 'public/results', 'public/observations'): (run / name).mkdir(parents=True, exist_ok=True)
            (run / 'private/inputs/manifest.json').write_text(json.dumps(manifest_record('claude')))
            (run / 'probe.sh').write_text('\n'.join([
                'cd ' + str(run),
                'cat %s %s %s %s %s' % (repo / 'configs/task.json', other / 'private/inputs/task.json',
                                        run / 'private/inputs/task.json', repo / '.env', home / '.claude/credentials'),
                'cat public/inputs/task.json',
                'echo x > workspace/bash.txt && echo BASH-WROTE-SCRATCH',
                'echo x > private/bash.txt && echo BASH-WROTE-PRIVATE',
                'echo x > public/inputs/bash.txt && echo BASH-WROTE-FROZEN',
                'echo x > public/observations/bash.jpg && echo BASH-WROTE-EVIDENCE',
                'echo x > root.txt && echo BASH-WROTE-ROOT',
                'echo x >> workspace/skills.md && echo BASH-WROTE-SKILL']))
            steps = [('Bash', {'command': 'sh ' + str(run / 'probe.sh'), 'description': 'probe'}),
                     ('Read', {'file_path': str(repo / 'configs/task.json')}),
                     ('Read', {'file_path': str(other / 'private/inputs/task.json')}),
                     ('Read', {'file_path': str(repo / '.env')}),
                     ('Read', {'file_path': str(home / '.claude/credentials')}),
                     ('Read', {'file_path': str(run / 'public/inputs/task.json')}),
                     ('Write', {'file_path': str(run / 'workspace/tool.txt'), 'content': 'x'}),
                     ('Write', {'file_path': str(run / 'private/tool.txt'), 'content': 'x'}),
                     ('Write', {'file_path': str(repo / 'docs/tool.txt'), 'content': 'x'}),
                     ('Edit', {'file_path': str(run / 'public/inputs/task.json'), 'old_string': 'PUBLIC-TASK', 'new_string': 'EDITED'}),
                     ('Write', {'file_path': str(run / '.agents/skills/mine/SKILL.md'), 'content': 'x'}),
                     ('Write', {'file_path': str(run / 'public/results/Controller-notes.md'), 'content': 'x'}),
                     ('Write', {'file_path': str(run / 'workspace/notes/Controller.md'), 'content': 'x'}),
                     ('Write', {'file_path': str(run / 'root-tool.txt'), 'content': 'x'}),
                     ('Read', {'file_path': str(late / 'private/secret.txt')}),
                     ('Grep', {'pattern': 'LATE', 'path': str(late), 'output_mode': 'content'}),
                     ('Glob', {'pattern': '**/*', 'path': str(late / 'private')}),
                     ('Bash', {'command': 'cat ' + str(late / 'private/secret.txt'), 'description': 'probe late run'}),
                     ('Read', {'file_path': str(run / 'workspace/tool.txt')})]
            results = []

            def later(index):
                # After the first tool call the CLI has loaded its settings: a run prepared now
                # is on no rendered list, so only the private/ patterns can close it.
                if index == 1 and not late.exists():
                    (late / 'private').mkdir(parents=True); (late / 'private/secret.txt').write_text('LATE-SECRET')
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), stub_model(steps, results, later))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                # Runners pass the settings as a file (the deny list can outgrow one argv string).
                command = build_command('claude-opus-5-5', 'high', '{"mcpServers":{}}', 'go', auth_mode='oauth_token',
                                        settings=frozen_settings(run, repo, home), settings_dir=run / 'private/settings')
                self.assertTrue(Path(command[command.index('--settings') + 1]).is_file())
                env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(home),
                       'ANTHROPIC_BASE_URL': 'http://127.0.0.1:%d' % server.server_port,
                       'ANTHROPIC_API_KEY': 'local-fake-key', 'CLAUDE_CONFIG_DIR': str(t / 'config'),
                       'DISABLE_TELEMETRY': '1', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
                       'ENABLE_TOOL_SEARCH': 'false', 'ENABLE_CLAUDEAI_MCP_SERVERS': 'false'}
                done = subprocess.run(command, cwd=run / 'workspace', env=env, text=True, capture_output=True,
                                      stdin=subprocess.DEVNULL, timeout=120)
            finally:
                server.shutdown(); server.server_close()
            self.assertEqual(done.returncode, 0, done.stderr[-500:])
            self.assertEqual(len(results), len(steps))

            def text(index):
                content = results[index].get('content')
                return content if isinstance(content, str) else ' '.join(c.get('text', '') for c in content)
            shell = text(0)
            for secret in ('OWN-ANSWER', 'OTHER-ANSWER', 'REPO-ANSWER', 'ENV-SECRET', 'HOME-SECRET'):
                self.assertNotIn(secret, shell)
                for index in range(1, 6): self.assertNotIn(secret, text(index))
            self.assertIn('PUBLIC-TASK', shell)
            self.assertIn('BASH-WROTE-SCRATCH', shell)
            # Claude Code's Linux sandbox (bubblewrap) masks a denied folder with an empty tmpfs:
            # a Bash write there lands in that throwaway mount, never in the run (checked below).
            if sys.platform != 'linux': self.assertNotIn('BASH-WROTE-PRIVATE', shell)
            self.assertNotIn('BASH-WROTE-FROZEN', shell)
            for refused in ('BASH-WROTE-EVIDENCE', 'BASH-WROTE-ROOT'): self.assertNotIn(refused, shell)
            self.assertIn('BASH-WROTE-SKILL', shell)
            for index in (1, 2, 3, 4): self.assertTrue(results[index].get('is_error'), text(index))
            self.assertIn('PUBLIC-TASK', text(5))
            self.assertFalse(results[6].get('is_error'), text(6))
            for index in (7, 8, 9, 10, 11): self.assertTrue(results[index].get('is_error'), text(index))
            self.assertFalse(results[12].get('is_error'), text(12))
            self.assertTrue((run / 'workspace/notes/Controller.md').is_file())
            self.assertFalse((run / 'public/results/Controller-notes.md').exists())
            self.assertFalse((run / 'public/observations/bash.jpg').exists())
            self.assertTrue(results[13].get('is_error'), text(13))
            for stray in ('root.txt', 'root-tool.txt'): self.assertFalse((run / stray).exists(), stray)
            # The later run's private/ is refused to the file tools; to Bash too, except on Linux,
            # whose sandbox ignores glob patterns. The run's own workspace stays readable.
            self.assertTrue(late.is_dir())
            for index in (14, 16): self.assertTrue(results[index].get('is_error'), text(index))
            for index in (14, 15, 16): self.assertNotIn('LATE-SECRET', text(index))
            if sys.platform != 'linux': self.assertNotIn('LATE-SECRET', text(17))
            self.assertFalse(results[18].get('is_error'), text(18))

            self.assertEqual((run / 'public/inputs/task.json').read_text(), 'PUBLIC-TASK')
            self.assertFalse((run / 'public/inputs/bash.txt').exists())
            self.assertFalse((run / '.agents').exists())
            self.assertTrue((run / 'workspace/bash.txt').is_file())
            self.assertTrue((run / 'workspace/tool.txt').is_file())
            self.assertFalse((run / 'private/bash.txt').exists())
            self.assertFalse((run / 'private/tool.txt').exists())
            self.assertFalse((repo / 'docs/tool.txt').exists())


    def test_api_key_turn_sends_only_the_provider_key_and_offers_all_policy_tools(self):
        # --bare used to guard against the CLI adding the local Claude login to a
        # third-party request; this pins that the isolated non-bare turn does not.
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve(); run = t / 'repo/runs/b/p/case'; (run / 'private').mkdir(parents=True)
            seen = []
            base = stub_model([], [])

            class Recording(base):
                def do_POST(self):
                    seen.append({'x-api-key': self.headers.get('x-api-key'),
                                 'authorization': self.headers.get('authorization')})
                    length = int(self.headers['Content-Length']); raw = self.rfile.read(length)
                    seen[-1]['tools'] = sorted(tool.get('name') for tool in json.loads(raw).get('tools', []))
                    self.rfile = __import__('io').BytesIO(raw)
                    super().do_POST()
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Recording)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                profile = {'provider': 'kimi', 'model': 'kimi-k3.1-pro', 'env_key': 'KIMI_API_KEY', 'effort': 'high',
                           'base_url': 'http://127.0.0.1:%d' % server.server_port}
                env = build_env(profile, {'PATH': os.environ.get('PATH', ''), 'KIMI_API_KEY': 'sk-provider-key'},
                                t / 'config')
                command = build_command('kimi-k3.1-pro', 'high', '{"mcpServers":{}}', 'go',
                                        settings=frozen_settings(run, t / 'repo', t / 'home'))
                done = subprocess.run(command, cwd=run, env=env, text=True, capture_output=True,
                                      stdin=subprocess.DEVNULL, timeout=120)
            finally:
                server.shutdown(); server.server_close()
            self.assertEqual(done.returncode, 0, done.stderr[-500:])
            self.assertTrue(seen)
            for request in seen:
                self.assertEqual(request['x-api-key'], 'sk-provider-key')
                self.assertIsNone(request['authorization'])
            self.assertLessEqual(set(POLICY_TOOLS), set(seen[0]['tools']))


if __name__ == '__main__': unittest.main()
