import json
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from robofrontier.engines.claude.runner import build_command, build_env, run_turn
from test_claude_runner import fake_claude
from robofrontier.engines.claude.native_home import config_directory
from robofrontier.batch.claude_benchmark import profile


class NativeLoginTests(unittest.TestCase):
    def test_default_native_login_preserves_the_default_credential_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); native = root/'.claude'; native.mkdir()
            selected = {**self.profile(native), 'native_config_scope':'default'}
            env = build_env(selected, {'PATH':'/bin', 'HOME':str(root),
                'CLAUDE_CONFIG_DIR':'/another/account'}, native)
            self.assertEqual(env['HOME'], str(root))
            self.assertNotIn('CLAUDE_CONFIG_DIR', env)

    def test_default_native_login_rejects_a_different_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            selected = {**self.profile(home), 'native_config_scope':'default'}
            with self.assertRaises(ValueError):
                build_env(selected, {'HOME':str(home)}, home)

    def test_runtime_verifies_fork_history_in_the_frozen_native_home(self):
        from robofrontier.runtime.cli import native_fork_provenance
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); home = root/'native'; project = home/'projects/task'
            project.mkdir(parents=True)
            run = root/'run'; inputs = run/'private/inputs'; inputs.mkdir(parents=True)
            (inputs/'claude.json').write_text(json.dumps({'profile':self.profile(home)}))
            parent, child = str(uuid.uuid4()), str(uuid.uuid4())
            row = {'uuid':str(uuid.uuid4()), 'sessionId':parent,
                   'type':'user', 'message':{'role':'user','content':'public task'}}
            (project/(parent+'.jsonl')).write_text(json.dumps(row)+'\n')
            (project/(child+'.jsonl')).write_text(json.dumps({**row,'sessionId':child})+'\n')
            store = SimpleNamespace(path=run/'private/state/runtime.sqlite',
                                    get=lambda key:{'engine':'claude'})
            proof = native_fork_provenance(store, parent, child)
            self.assertEqual(proof['source_thread_id'], parent)
            self.assertEqual(proof['source_ordinal'], 1)

    def test_native_profile_freezes_explicit_home_but_remains_inspectable_offline(self):
        with patch.dict('os.environ', {}, clear=True):
            selected = profile('haiku_subscription')
            self.assertIsNone(selected['native_config_dir'])
            self.assertEqual(selected['model'], 'claude-haiku-5-5')
            with self.assertRaises(ValueError):
                config_directory('.', selected)
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'ROBOFRONTIER_CLAUDE_HOME': tmp}):
            selected = profile('haiku_subscription')
            self.assertEqual(selected['native_config_dir'], str(Path(tmp).resolve()))

    def test_native_history_location_comes_from_frozen_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); home = root / 'native'; home.mkdir()
            run = root / 'run'; inputs = run / 'private/inputs'; inputs.mkdir(parents=True)
            (inputs / 'claude.json').write_text(json.dumps({'profile': self.profile(home)}))
            self.assertEqual(config_directory(run), home.resolve())

    def profile(self, home):
        return {'provider': 'anthropic', 'model': 'claude-haiku-5-5',
                'effort': 'high', 'auth_mode': 'native_login', 'env_key': None,
                'native_config_dir': str(home)}

    def test_native_login_uses_explicit_home_without_inheriting_provider_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env = build_env(self.profile(home), {'PATH': '/usr/bin:/bin',
                'HOME': '/actual-user', 'ANTHROPIC_API_KEY': 'other-api-key',
                'CLAUDE_CODE_OAUTH_TOKEN': 'other-token', 'OPENAI_API_KEY': 'other-key'}, home)
            self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(home.resolve()))
            self.assertEqual(env['HOME'], '/actual-user')
            self.assertNotIn('ANTHROPIC_API_KEY', env)
            self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN', env)
            self.assertNotIn('OPENAI_API_KEY', env)

    def test_native_login_retains_explicit_ids_and_strict_tool_boundary(self):
        cmd = build_command('claude-haiku-5-5', 'high', 'robot.json', 'hello',
                            session_id='assigned-session', auth_mode='native_login')
        self.assertNotIn('--bare', cmd)
        self.assertEqual(cmd[cmd.index('--setting-sources') + 1], '')
        self.assertEqual(cmd[cmd.index('--session-id') + 1], 'assigned-session')
        self.assertIn('--strict-mcp-config', cmd)
        self.assertEqual(cmd[cmd.index('--tools') + 1], '')

    def test_native_login_rejects_missing_home_and_non_anthropic_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for changes in ({'native_config_dir': None}, {'native_config_dir': 'relative'},
                            {'provider': 'third-party'}, {'base_url': 'https://other.example'}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    build_env({**self.profile(home), **changes}, {'PATH': '/bin'}, home)

    def test_native_login_turn_leaves_auth_files_owned_by_native_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); home = root / 'native'; home.mkdir()
            auth = home / '.credentials.json'; auth.write_text('native-owned sentinel')
            run = root / 'run'
            binary = fake_claude(root, '''
assert 'ANTHROPIC_API_KEY' not in os.environ
assert 'CLAUDE_CODE_OAUTH_TOKEN' not in os.environ
print(json.dumps({'type':'result','subtype':'success','is_error':False,
                  'session_id':'assigned-session','result':'READY','total_cost_usd':.001}))
''')
            record = run_turn(self.profile(home), 'claude-haiku-5-5', 'high', None,
                'Reply READY', run, {'PATH': '/usr/bin:/bin', 'HOME': str(root)},
                session_id='assigned-session', binary=str(binary), enable_robot=False, timeout=5)
            self.assertEqual(record['summary']['result_text'], 'READY')
            self.assertEqual(auth.read_text(), 'native-owned sentinel')
            self.assertFalse((run / 'private/claude-config').exists())
            self.assertFalse(any(run.rglob('.credentials.json')))
