import hashlib
import json
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from robofrontier.engines.claude.runner import build_command, build_env, gate_settings, run_turn, summarize, ROBOT_TOOL

PROFILE = {'provider': 'kimi', 'model': 'kimi-k3.1-pro', 'env_key': 'KIMI_API_KEY',
           'base_url': 'https://api.moonshot.cn/anthropic', 'effort': 'high'}
SECRET = 'sk-test-kimi-secret'


def fake_claude(directory, body):
    """Write an executable stand-in for the claude CLI; it makes no network calls."""
    path = Path(directory) / 'claude'
    path.write_text('#!' + sys.executable + '\nimport json, os, sys, time\n' + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


SUCCESS_BODY = '''
print(json.dumps({"type": "system", "subtype": "init", "session_id": "s1", "model": "kimi-k3.1-pro"}))
print(json.dumps({"type": "assistant", "session_id": "s1", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "mcp__robot__robot", "input": {}}]}}))
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": "s1", "num_turns": 2,
                  "usage": {"input_tokens": 3, "output_tokens": 4}, "total_cost_usd": 0.01,
                  "result": "turn finished", "key_seen": os.environ.get("ANTHROPIC_API_KEY") == "%s",
                  "other_key_seen": "OPENAI_API_KEY" in os.environ, "base": os.environ.get("ANTHROPIC_BASE_URL")}))
''' % SECRET


class ClaudeRunnerTests(unittest.TestCase):
    def test_large_prompt_reaches_cli_as_complete_stdin(self):
        prompt = '--model is public task text\n' + 'Public geometry and task context.\n' * 10000
        with tempfile.TemporaryDirectory() as tmp:
            binary = fake_claude(tmp, '''
import hashlib
prompt = sys.stdin.buffer.read()
print(json.dumps({'type':'result', 'subtype':'success', 'is_error':False,
                  'result':hashlib.sha256(prompt).hexdigest()}))
''')
            record = run_turn(PROFILE, 'm', 'high', None, prompt, tmp,
                              {'PATH':'/usr/bin:/bin','KIMI_API_KEY':SECRET},
                              binary=str(binary), timeout=5, enable_robot=False)
            self.assertEqual(record['process'], 'exited')
            self.assertEqual(record['summary']['result_text'], hashlib.sha256(prompt.encode()).hexdigest())

    def test_large_unread_stdin_still_allows_timeout_and_cancellation(self):
        for cancellation in (False, True):
            with self.subTest(cancellation=cancellation), tempfile.TemporaryDirectory() as tmp:
                binary = fake_claude(tmp, 'time.sleep(30)\n')
                cancel = threading.Event()
                timer = threading.Timer(.3, cancel.set) if cancellation else None
                if timer:
                    timer.start()
                try:
                    record = run_turn(PROFILE, 'm', 'high', None, 'public context\n' * 25000,
                                      tmp, {'PATH':'/usr/bin:/bin','KIMI_API_KEY':SECRET},
                                      binary=str(binary), timeout=5 if cancellation else .1,
                                      cancel_event=cancel if cancellation else None, enable_robot=False)
                finally:
                    if timer:
                        timer.cancel()
                self.assertEqual(record['process'], 'cancelled' if cancellation else 'timeout')
                self.assertEqual(record['summary']['turn_status'], 'unknown')

    def test_large_stdin_survives_cancel_poll_before_cli_reads(self):
        prompt = 'Public task context.\n' * 15000
        with tempfile.TemporaryDirectory() as tmp:
            binary = fake_claude(tmp, '''
import hashlib
time.sleep(.6)
prompt = sys.stdin.buffer.read()
print(json.dumps({'type':'result', 'subtype':'success', 'is_error':False,
                  'result':hashlib.sha256(prompt).hexdigest()}))
''')
            record = run_turn(PROFILE, 'm', 'high', None, prompt, tmp,
                              {'PATH':'/usr/bin:/bin','KIMI_API_KEY':SECRET},
                              binary=str(binary), timeout=2, cancel_event=threading.Event(),
                              enable_robot=False)
            self.assertEqual(record['process'], 'exited')
            self.assertEqual(record['summary']['result_text'], hashlib.sha256(prompt.encode()).hexdigest())

    def test_command_exposes_only_bound_robot_tool_and_isolates_session(self):
        cmd = build_command('kimi-k3.1-pro', 'high', '/tmp/mcp.json', 'go', session_id='11111111-1111-1111-1111-111111111111')
        self.assertIn('--strict-mcp-config', cmd)
        self.assertIn('--bare', cmd)
        self.assertEqual(cmd[cmd.index('--allowedTools') + 1], ROBOT_TOOL)
        self.assertEqual(cmd[cmd.index('--tools') + 1], '')
        self.assertEqual(cmd[cmd.index('--session-id') + 1], '11111111-1111-1111-1111-111111111111')
        self.assertNotIn('--resume', cmd)
        self.assertNotIn('--fork-session', cmd)
        self.assertEqual(cmd[-2:], ['--', 'go'])
        with self.assertRaises(ValueError): build_command('m', 'extreme', 'x', 'p')
        with self.assertRaises(ValueError): build_command('m', 'high', 'x', 'p', max_budget_usd=0)

    def test_resume_uses_explicit_id_and_never_both_flags(self):
        cmd = build_command('m', 'high', 'x', 'p', resume='22222222-2222-2222-2222-222222222222')
        self.assertEqual(cmd[cmd.index('--resume') + 1], '22222222-2222-2222-2222-222222222222')
        self.assertNotIn('--session-id', cmd)
        with self.assertRaises(ValueError): build_command('m', 'high', 'x', 'p', session_id='a', resume='b')

    def test_delegate_fork_pins_ids_keeps_the_role_tools_and_gates_them(self):
        gate = {'open': '/run/private/claude-forks/D.gate-open', 'closed': '/run/x y/D.gate-closed',
                'deadline': 4102444800}
        cmd = build_command('m', 'high', '/run/role-mcp.json', 'p', session_id='child', fork_from='parent', gate=gate)
        self.assertEqual(cmd[cmd.index('--resume') + 1], 'parent')
        self.assertEqual(cmd[cmd.index('--session-id') + 1], 'child')
        self.assertIn('--fork-session', cmd)
        self.assertEqual(cmd[cmd.index('--mcp-config') + 1], '/run/role-mcp.json')
        self.assertEqual(cmd[cmd.index('--allowedTools') + 1], ROBOT_TOOL)
        # --bare would skip the hook.
        self.assertNotIn('--bare', cmd)
        self.assertEqual(cmd[cmd.index('--setting-sources') + 1], '')
        hook = json.loads(cmd[cmd.index('--settings') + 1])['hooks']['PreToolUse'][0]
        self.assertEqual(hook['matcher'], '*')
        self.assertIn("'/run/x y/D.gate-closed'", hook['hooks'][0]['command'])
        self.assertGreater(hook['hooks'][0]['timeout'], 4102444800 - time.time())
        with self.assertRaises(ValueError): build_command('m', 'high', 'x', 'p', fork_from='parent')
        settings = {'permissions': {'deny': []}}
        cmd = build_command('m', 'high', 'x', 'p', session_id='child', fork_from='parent', gate=gate, settings=settings)
        merged = json.loads(cmd[cmd.index('--settings') + 1])
        self.assertEqual(merged['permissions'], settings['permissions'])
        self.assertIn('PreToolUse', merged['hooks'])
        self.assertEqual(cmd.count('--settings'), 1)

    def test_gate_hook_holds_until_open_and_refuses_when_closed_or_late(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'a folder'; folder.mkdir()
            gate = {'open': folder / 'D.gate-open', 'closed': folder / 'D.gate-closed', 'deadline': time.time() + 20}
            script = gate_settings(gate)['hooks']['PreToolUse'][0]['hooks'][0]['command']
            hook = lambda: subprocess.run(['sh', '-c', script], capture_output=True, text=True, timeout=30)
            threading.Timer(.4, gate['open'].touch).start()
            began = time.monotonic(); done = hook()
            self.assertEqual(done.returncode, 0); self.assertGreater(time.monotonic() - began, .3)
            gate['open'].unlink(); gate['closed'].touch()
            done = hook()
            self.assertEqual(done.returncode, 2); self.assertIn('not run', done.stderr)
            gate['closed'].unlink(); gate['deadline'] = time.time() - 1
            script = gate_settings(gate)['hooks']['PreToolUse'][0]['hooks'][0]['command']
            self.assertEqual(hook().returncode, 2)

    def test_environment_carries_only_own_profile_credential(self):
        base = {'PATH': '/bin', 'KIMI_API_KEY': SECRET, 'OPENAI_API_KEY': 'other', 'ANTHROPIC_API_KEY': 'wrong'}
        env = build_env(PROFILE, base, '/run/config')
        self.assertEqual(env['ANTHROPIC_API_KEY'], SECRET)
        self.assertEqual(env['ANTHROPIC_BASE_URL'], PROFILE['base_url'])
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertEqual(env['CLAUDE_CONFIG_DIR'], '/run/config')
        with self.assertRaisesRegex(ValueError, 'KIMI_API_KEY'):
            build_env(PROFILE, {'PATH': '/bin'}, '/run/config')

    def test_only_a_managed_allocation_route_reaches_the_cli(self):
        base = {'PATH': '/bin', 'KIMI_API_KEY': SECRET, 'HTTPS_PROXY': 'http://user-proxy', 'NO_PROXY': 'x'}
        self.assertNotIn('HTTPS_PROXY', build_env(PROFILE, base, '/run/config'))
        env = build_env(PROFILE, {**base, 'ROBOFRONTIER_EGRESS_INSTANCE': 'a'*32, 'ALL_PROXY': 'http://other'}, '/run/config')
        self.assertEqual((env['HTTPS_PROXY'], env['NO_PROXY']), ('http://user-proxy', 'x'))
        self.assertNotIn('ALL_PROXY', env); self.assertNotIn('ROBOFRONTIER_EGRESS_INSTANCE', env)

    def test_unconfigured_third_party_endpoint_never_launches_cli(self):
        from robofrontier.batch.claude_prepare import profile
        with patch.dict('os.environ', {}, clear=True):
            selected = profile('qwen')
        self.assertIsNone(selected['base_url'])  # Offline inspection is allowed.
        for base_url in (None, ''):
            with self.subTest(base_url=base_url), tempfile.TemporaryDirectory() as tmp:
                selected['base_url'] = base_url
                with patch('robofrontier.engines.claude.runner.subprocess.Popen',
                           side_effect=AssertionError('CLI launched without a provider endpoint')) as launch:
                    with self.assertRaisesRegex(ValueError, 'explicit base URL'):
                        run_turn(selected, selected['model'], selected['effort'], 'mcp.json', 'go',
                                 tmp, {'DASHSCOPE_API_KEY': 'synthetic-unused'}, session_id='s1')
                    launch.assert_not_called()

    def test_anthropic_profile_can_use_native_default_endpoint(self):
        selected = {'provider': 'anthropic', 'env_key': 'ANTHROPIC_API_KEY'}
        env = build_env(selected, {'ANTHROPIC_API_KEY': 'synthetic-unused'}, '/run/config')
        self.assertNotIn('ANTHROPIC_BASE_URL', env)

    def test_summary_never_declares_task_success(self):
        lines = [json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's'}), '{bad json', '']
        summary = summarize(lines)
        self.assertEqual(summary['turn_status'], 'ended')
        self.assertIsNone(summary['task_success'])
        self.assertEqual(summary['malformed_lines'], 1)
        self.assertEqual(summarize([json.dumps({'type': 'result', 'subtype': 'error_max_turns', 'is_error': True})])['turn_status'], 'failed')
        self.assertEqual(summarize([])['turn_status'], 'unknown')

    def test_summary_keeps_aggregate_model_usage_and_failure_subtype(self):
        event={'type':'result','subtype':'error_max_budget_usd','is_error':True,
               'usage':{'output_tokens':302},'modelUsage':{'model':{
                   'outputTokens':13707,'thinkingTokens':13299,'cacheReadInputTokens':28889}},
               'total_cost_usd':.4755318}
        result=summarize([json.dumps(event)])
        self.assertEqual(result['turn_status'],'failed')
        self.assertEqual(result['result_subtype'],'error_max_budget_usd')
        self.assertEqual(result['usage']['output_tokens'],302)
        self.assertEqual(result['model_usage']['model']['outputTokens'],13707)
        self.assertEqual(result['model_usage']['model']['thinkingTokens'],13299)
        self.assertEqual(result['total_cost_usd'],.4755318)

    def test_image_evidence_must_match_the_observe_tool_call(self):
        call={'type':'assistant','message':{'content':[{'type':'tool_use','id':'wanted',
              'name':'mcp__robot__robot','input':{'op':'observe','views':['top']}}]}}
        result={'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'other',
                'content':[{'type':'image'}]}]}}
        def summary(): return summarize([json.dumps(call),json.dumps(result)])
        self.assertEqual(summary()['observe_top_calls'],1)
        self.assertEqual(summary()['observe_top_image_results'],0)
        result['message']['content'][0]['tool_use_id']='wanted'
        self.assertEqual(summary()['observe_top_image_results'],1)
        result['message']['content'][0]['is_error']=True
        self.assertEqual(summary()['observe_top_image_results'],0)

    def test_run_records_events_env_and_tool_use_with_fake_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'run'; run.mkdir()
            conn_cfg = run / 'mcp.json'; conn_cfg.write_text('{}')
            binary = fake_claude(tmp, SUCCESS_BODY)
            base = {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': SECRET, 'OPENAI_API_KEY': 'other'}
            record = run_turn(PROFILE, 'kimi-k3.1-pro', 'high', conn_cfg, 'go', run, base, binary=str(binary), timeout=20)
            self.assertEqual(record['process'], 'exited')
            self.assertEqual(record['exit_code'], 0)
            self.assertEqual(record['summary']['turn_status'], 'ended')
            self.assertEqual(record['summary']['tool_calls'], 1)
            self.assertEqual(record['summary']['session_id'], 's1')
            events = (run / record['events_path']).read_text()
            self.assertIn('"key_seen": true', events)
            self.assertIn('"other_key_seen": false', events)
            self.assertNotIn(SECRET, json.dumps(record))
            self.assertNotIn(SECRET, events.replace('"key_seen": true', ''))

    def test_cancellation_interrupts_cli_and_keeps_outcome_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'run'; run.mkdir()
            config = run / 'mcp.json'; config.write_text('{}')
            binary = fake_claude(tmp, 'time.sleep(30)\n')
            cancel = threading.Event()
            timer = threading.Timer(0.3, cancel.set); timer.start()
            try:
                record = run_turn(PROFILE, 'm', 'high', config, 'go', run,
                                  {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': SECRET},
                                  binary=str(binary), timeout=10, cancel_event=cancel)
            finally:
                timer.cancel()
            self.assertEqual(record['process'], 'cancelled')
            self.assertEqual(record['summary']['turn_status'], 'unknown')
            self.assertIsNone(record['summary']['task_success'])

    def test_unlimited_turn_can_finish_and_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'run'; run.mkdir()
            base = {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': SECRET}
            binary = fake_claude(tmp, 'time.sleep(.15)\nprint(json.dumps({"type":"result", "subtype":"success", "is_error":False}))\n')
            record = run_turn(PROFILE, 'm', 'high', None, 'go', run, base,
                              binary=str(binary), enable_robot=False)
            self.assertEqual(record['process'], 'exited')
            self.assertEqual(record['summary']['turn_status'], 'ended')
            binary = fake_claude(tmp, 'time.sleep(30)\n')
            cancel = threading.Event(); timer = threading.Timer(.2, cancel.set); timer.start()
            try:
                record = run_turn(PROFILE, 'm', 'high', None, 'go', run, base,
                                  binary=str(binary), timeout=None, cancel_event=cancel, enable_robot=False)
            finally:
                timer.cancel()
            self.assertEqual(record['process'], 'cancelled')
            self.assertEqual(record['summary']['turn_status'], 'unknown')

    def test_cancel_as_the_cli_exits_does_not_raise(self):
        # macOS answers killpg with EPERM when only zombies remain in the CLI's group.
        with tempfile.TemporaryDirectory() as tmp:
            binary = fake_claude(tmp, 'time.sleep(1)\n')
            cancel = threading.Event()
            # Not set at the launch check, set at the first poll.
            with patch('robofrontier.engines.claude.runner.os.killpg', side_effect=PermissionError(1, 'Operation not permitted')), \
                    patch.object(cancel, 'is_set', side_effect=[False] + [True] * 100):
                record = run_turn(PROFILE, 'm', 'high', None, 'go', tmp, {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': SECRET},
                                  binary=str(binary), timeout=5, cancel_event=cancel, enable_robot=False)
            self.assertEqual(record['process'], 'cancelled')
            self.assertEqual(record['summary']['turn_status'], 'unknown')

    def test_closing_a_persistent_cli_tolerates_a_zombie_only_group(self):
        from unittest.mock import Mock
        from robofrontier.engines.claude.runner import _stop_process
        process = Mock(pid=12345)
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('claude', 10), 0]
        with patch('robofrontier.engines.claude.runner.os.killpg', side_effect=PermissionError(1, 'Operation not permitted')):
            _stop_process(process)
        self.assertEqual(process.wait.call_count, 2)

    def test_cancellation_before_launch_never_starts_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'run'; run.mkdir()
            config = run / 'mcp.json'; config.write_text('{}')
            cancel = threading.Event(); cancel.set()
            with patch('robofrontier.engines.claude.runner.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(InterruptedError, 'cancelled before launch'):
                    run_turn(PROFILE, 'm', 'high', config, 'go', run,
                             {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': SECRET},
                             cancel_event=cancel)
                spawn.assert_not_called()

    def test_event_and_stderr_redact_credential_before_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'run'; run.mkdir()
            secret = 'fake-"unicode-\u5bc6\u94a5'
            binary = fake_claude(tmp, '''
secret = os.environ['ANTHROPIC_API_KEY']
print(json.dumps({'type':'result', 'subtype':'success', 'is_error':False, 'result':secret}))
sys.stderr.write(secret + 'x' * 990)
''')
            record = run_turn(PROFILE, 'm', 'high', None, 'go', run,
                              {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': secret},
                              binary=str(binary), timeout=10, enable_robot=False)
            events = run / record['events_path']
            self.assertEqual(json.loads(events.read_text())['result'], '[redacted]')
            self.assertEqual(record['summary']['result_text'], '[redacted]')
            self.assertNotIn(secret, json.dumps(record, ensure_ascii=False))
            self.assertNotIn(secret[-5:], record['stderr_tail'])
            self.assertEqual(stat.S_IMODE(events.stat().st_mode), 0o600)

    def test_failed_turn_and_deadline_are_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'run'; run.mkdir()
            conn_cfg = run / 'mcp.json'; conn_cfg.write_text('{}')
            base = {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': SECRET}
            failing = fake_claude(tmp, 'print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True}))\nsys.exit(1)\n')
            record = run_turn(PROFILE, 'm', 'high', conn_cfg, 'go', run, base, binary=str(failing), timeout=20)
            self.assertEqual(record['summary']['turn_status'], 'failed')
            self.assertIsNone(record['summary']['task_success'])
            hanging = fake_claude(tmp, 'time.sleep(30)\n')
            record = run_turn(PROFILE, 'm', 'high', conn_cfg, 'go', run, base, binary=str(hanging), timeout=1)
            self.assertEqual(record['process'], 'timeout')
            self.assertEqual(record['summary']['turn_status'], 'unknown')


class PolicySettingsTests(unittest.TestCase):
    """Policy turns of a run with a frozen access table: its rendered settings and their CLI."""

    def layout(self, tmp):
        t = Path(tmp).resolve()
        repo, home = t/'repo', t/'home'
        run = repo/'runs/batch/profile/case'
        for folder in (run/'workspace', run/'public/inputs', run/'private/inputs', repo/'configs', home):
            folder.mkdir(parents=True, exist_ok=True)
        (repo/'.env').write_text('test fixture')
        return repo, home, run

    def write_access(self, run, access):
        (run/'private/inputs/policy-access.json').write_text(json.dumps(access))

    def test_denied_repository_files_beside_the_run_get_rules_that_cover_the_file_itself(self):
        from robofrontier.runtime import access as policy_access
        from robofrontier.engines.claude.runner import policy_settings
        with tempfile.TemporaryDirectory() as tmp:
            repo, home, run = self.layout(tmp)
            self.write_access(run, {'filesystem': policy_access.table(run, repo=repo, home=home, tmp_dirs=(),
                                                                      checkouts=[repo])})
            settings = policy_settings(run)
            deny = settings['permissions']['deny']
            env = '//'+str(repo/'.env').lstrip('/')
            # gitignore matching: 'path/**' never matches path itself, so a file needs the exact rule.
            self.assertIn('Read(%s)' % env, deny)
            self.assertIn('Edit(%s)' % env, deny)
            configs = '//'+str(repo/'configs').lstrip('/')
            for rule in ('Read(%s/**)', 'Edit(%s/**)'):
                self.assertIn(rule % configs, deny)
            # A bare folder rule is a string prefix: it would close any sibling named configs-*.
            self.assertNotIn('Read(%s)' % configs, deny)
            public = '//'+str(run/'public').lstrip('/')
            self.assertIn('Edit(%s/**)' % public, deny)
            self.assertIn(str(repo/'.env'), settings['sandbox']['filesystem']['denyRead'])
            # The route to the run stays open.
            for folder in (repo, repo/'runs', run):
                self.assertFalse(any(rule.startswith('Read(//'+str(folder).lstrip('/')+')') for rule in deny), folder)

    def test_a_batch_named_like_the_start_of_this_one_does_not_close_this_run(self):
        # 2026-11-11: batch 'opus-l3-20261111' beside 'opus-l3-20261111-b' rendered
        # Read/Edit(//.../opus-l3-20261111), which closed every workspace of the -b batch.
        from robofrontier.runtime import access as policy_access
        from robofrontier.engines.claude.runner import policy_settings
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve(); repo, home = t/'repo', t/'home'
            run = repo/'runs/policy/batch-b/profile/case'
            for folder in (run/'workspace', run/'public/inputs', run/'private/inputs', repo/'runs/policy/batch', home):
                folder.mkdir(parents=True, exist_ok=True)
            self.write_access(run, {'filesystem': policy_access.table(run, repo=repo, home=home, tmp_dirs=(), checkouts=[repo])})
            deny = policy_settings(run)['permissions']['deny']
            sibling = '//'+str(repo/'runs/policy/batch').lstrip('/')
            self.assertIn('Read(%s/**)' % sibling, deny)
            workspace = '/'+str(run/'workspace')
            for rule in deny:
                pattern = rule[rule.index('(')+1:-1]
                if '*' not in pattern:
                    self.assertFalse(workspace.startswith(pattern), rule)

    def test_every_run_private_folder_under_the_denied_repository_is_closed_by_pattern(self):
        # The deny list is rendered once per CLI process; a run prepared later beside this
        # one must still have its private/ closed, so the denied folders holding the run get
        # patterns the CLI matches when a tool runs.
        from robofrontier.runtime import access as policy_access
        from robofrontier.engines.claude.runner import policy_settings
        with tempfile.TemporaryDirectory() as tmp:
            repo, home, run = self.layout(tmp)
            self.write_access(run, {'filesystem': policy_access.table(run, repo=repo, home=home, tmp_dirs=(),
                                                                      checkouts=[repo])})
            settings = policy_settings(run)
            deny = settings['permissions']['deny']
            root = '//'+str(repo).lstrip('/')
            for tool in ('Read', 'Edit'):
                for pattern in ('/**/private', '/**/private/**'):
                    self.assertIn('%s(%s%s)' % (tool, root, pattern), deny)
            self.assertIn(str(repo)+'/**/private', settings['sandbox']['filesystem']['denyRead'])
            self.assertIn(str(repo)+'/**/private/**', settings['sandbox']['filesystem']['denyRead'])
            # Only folders that hold the run get patterns: the home folder is denied whole.
            self.assertFalse(any(str(home).lstrip('/')+'/**' in rule and 'private' in rule for rule in deny))
            # A run below a folder named private would be closed whole by such a pattern, so that root gets none.
            nested = repo/'private/runs/b/case'
            (nested/'private/inputs').mkdir(parents=True)
            self.write_access(nested, {'filesystem': policy_access.table(nested, repo=repo, home=home, tmp_dirs=(),
                                                                         checkouts=[repo])})
            self.assertFalse(any('/**/private' in rule for rule in policy_settings(nested)['permissions']['deny']))

    def test_policy_env_table_renders_deny_and_allow_read(self):
        from robofrontier.engines.claude.runner import policy_settings
        with tempfile.TemporaryDirectory() as tmp:
            repo, home, run = self.layout(tmp)
            table = {'/': 'read', str(home): 'deny', str(repo): 'deny', str(run): 'deny', str(run/'public'): 'read',
                     str(run/'private'): 'deny', str(run/'workspace'): 'write', '/tmp': 'write'}
            self.write_access(run, {'filesystem': table, 'policy_env': {'root': '/env'}})
            settings = policy_settings(run)
            sandbox = settings['sandbox']['filesystem']
            self.assertEqual(sandbox['denyRead'], sorted([str(home), str(repo), str(run), str(run/'private')])
                             + [str(repo)+'/**/private', str(repo)+'/**/private/**'])
            self.assertEqual(sandbox['allowRead'], sorted([str(run/'public'), str(run/'workspace'), '/tmp']))
            self.assertEqual(sandbox['allowWrite'], sorted([str(run/'workspace'), '/tmp']))
            self.assertIn('Read(//'+str(repo/'.env').lstrip('/')+')', settings['permissions']['deny'])

    def test_a_long_deny_list_reaches_the_cli_as_a_private_settings_file(self):
        from robofrontier.runtime import access as policy_access
        from robofrontier.runtime.layout import manifest_record
        with tempfile.TemporaryDirectory() as tmp:
            repo, home, run = self.layout(tmp)
            (run/'private/inputs/manifest.json').write_text(json.dumps(manifest_record('claude')))
            # Thousands of earlier runs beside this one: one argv string would pass Linux's 128 KiB.
            for index in range(5000):
                (run.parent/('earlier-run-with-a-long-descriptive-name-%05d' % index)).touch()
            self.write_access(run, {'filesystem': policy_access.table(run, repo=repo, home=home, tmp_dirs=(),
                                                                      checkouts=[repo])})
            binary = fake_claude(tmp, '''
path = sys.argv[sys.argv.index('--settings') + 1]
settings = json.load(open(path))
print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': json.dumps({
    'longest': max(len(a) for a in sys.argv), 'rules': len(settings['permissions']['deny']),
    'mode': oct(os.stat(path).st_mode & 0o777), 'path': path})}))
''')
            record = run_turn(PROFILE, 'm', 'high', None, 'go', run, {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': SECRET},
                              binary=str(binary), timeout=20)
            self.assertEqual(record['process'], 'exited', record['stderr_tail'])
            seen = json.loads(record['summary']['result_text'])
            self.assertLess(seen['longest'], 4096)
            self.assertGreater(seen['rules'], 4*5000)
            self.assertEqual(seen['mode'], '0o600')
            self.assertIn(run/'private', Path(seen['path']).parents)
            # Settings with the same content share one file.
            run_turn(PROFILE, 'm', 'high', None, 'go', run, {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': SECRET},
                     binary=str(binary), timeout=20)
            self.assertEqual(len(list(Path(seen['path']).parent.glob('settings-*.json'))), 1)


    def test_a_cli_lost_before_the_prompt_is_written_is_a_lost_cli_not_an_unknown_turn(self):
        from robofrontier.runtime import access as policy_access
        from robofrontier.engines.claude.runner import PersistentSession
        from robofrontier.runtime.layout import manifest_record
        with tempfile.TemporaryDirectory() as tmp:
            repo, home, run = self.layout(tmp)
            (run/'private/inputs/manifest.json').write_text(json.dumps(manifest_record('claude')))
            self.write_access(run, {'filesystem': policy_access.table(run, repo=repo, home=home, tmp_dirs=(),
                                                                      checkouts=[repo])})
            binary = fake_claude(tmp, 'sys.exit(3)\n')
            session = PersistentSession()
            # The CLI dies between the liveness check and the prompt write.
            with patch.object(PersistentSession, '_write', side_effect=BrokenPipeError(32, 'Broken pipe')):
                record = session(PROFILE, 'm', 'high', None, 'go', run, {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': SECRET},
                                 session_id='11111111-1111-1111-1111-111111111111', binary=str(binary), timeout=5)
            self.assertEqual(record['process'], 'process_exited')
            self.assertEqual(record['exit_code'], 3)
            self.assertEqual(record['summary']['turn_status'], 'unknown')
            session.close()


if __name__ == '__main__': unittest.main()
