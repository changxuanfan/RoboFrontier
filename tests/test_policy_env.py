"""A policy environment: its identity, the access table it brings, and each engine's rendering.

scripts/check_policy_env.py exercises a real environment through both real CLIs. These
tests use a small fake environment, so they need neither a build nor a CLI.
"""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from robofrontier import policy_access, policy_bootstrap, policy_env
from robofrontier.claude.runner import confine, policy_settings
from robofrontier.codex.launch import launch_config
from robofrontier.run_layout import manifest_record
from scripts import check_policy_env

CHECKED = [{'engine': 'codex', 'tool_backend': 'landlock-v1', 'cli': 'codex-cli 0.165.0'},
           {'engine': 'claude', 'bash_isolation': 'claude-sandbox', 'cli': '2.1.312 (Claude Code)'}]
STUB = dict(model='offline-protocol', provider='offline_protocol', effort='high', vision=True, context_window=272000,
            auto_compact_token_limit=258400, env_key='ROBOFRONTIER_OFFLINE_STUB_TOKEN', base_url='https://stub.invalid')


def fake_environment(folder):
    root = Path(folder)/'policy-env-fake'
    (root/'python/bin').mkdir(parents=True)
    (root/'wheels').mkdir()
    (root/'python/bin/python3').write_text('fake')
    manifest = {'schema': policy_env.SCHEMA, 'id': root.name, 'python': '3.12.16', 'bin': 'python/bin',
                'core': ['numpy'], 'store': ['networkx'], 'packages': {'numpy': '2.5.4'}}
    manifest['tree_sha256'] = policy_env.tree_sha256(root)
    (root/policy_env.MANIFEST).write_text(json.dumps(manifest))
    policy_env.receipt_path(root).write_text(json.dumps({'schema': policy_env.RECEIPT_SCHEMA, 'passed': True,
                                                         'tree_sha256': manifest['tree_sha256'], 'checked': CHECKED}))
    return root


# Outside /tmp, where Linux refuses a run with an environment (and where CI's temporary folder is).
OUTSIDE_TMP = None if not Path(tempfile.gettempdir()).resolve().is_relative_to(Path('/tmp').resolve()) else '/var/tmp'


class Fixture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=OUTSIDE_TMP)
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name).resolve()
        self.root = fake_environment(self.tmp)
        self.repo = self.tmp/'repo'
        self.home = self.tmp/'home'
        self.run_dir = self.repo/'runs/batch/profile/case'
        for name in ('public/inputs', 'workspace', 'private/inputs'):
            (self.run_dir/name).mkdir(parents=True)

    def freeze(self, system='darwin'):
        with patch.object(policy_access.sys, 'platform', system):
            record = policy_access.record(self.run_dir, environment=self.root, repo=self.repo, home=self.home,
                                          checkouts=[self.repo])
        (self.run_dir/'private/inputs/policy-access.json').write_text(json.dumps(record))
        (self.run_dir/'private/inputs/manifest.json').write_text(json.dumps(manifest_record('codex')))
        return record


class AccessTableTests(Fixture):
    def test_only_public_workspace_and_the_environment_are_open_beneath_closed_folders(self):
        table = self.freeze()['filesystem']
        for path, expected in ((self.run_dir/'public/inputs/task.json', 'read'), (self.run_dir/'workspace/a', 'write'),
                               (self.root/'python/bin/python3', 'read'), (self.run_dir/'private/inputs/x', 'deny'),
                               (self.run_dir/'root.txt', 'deny'), (self.run_dir.parent/'other/private/x', 'deny'),
                               (self.repo/'configs/x', 'deny'), (self.home/'Documents/x', 'deny'), ('/tmp/x', 'write'),
                               ('/var/folders/x', 'deny'), ('/opt/homebrew/bin/python3', 'deny'), ('/usr/local/bin/x', 'deny'),
                               ('/Users/someone/x', 'deny'), ('/Volumes/x', 'deny'), ('/Library/Keychains/x', 'deny'),
                               ('/usr/bin/true', 'read'), ('/System/Library/x', 'read')):
            self.assertEqual(policy_access.mode(table, path), expected, path)
        self.assertEqual(sorted(path for path, value in table.items() if value == 'write'),
                         sorted([str(self.run_dir/'workspace'), str(Path('/tmp').resolve())]))

    def test_record_freezes_the_environment_and_a_changed_environment_refuses(self):
        record = self.freeze()
        self.assertEqual(record['schema'], 'robofrontier.policy-access.v2')
        self.assertEqual(record['policy_env']['id'], self.root.name)
        self.assertEqual(record['policy_env']['variables']['TMPDIR'], str(self.run_dir/'workspace/.tmp'))
        self.assertFalse(record['network'] or record['web_search'])
        (self.root/'python/bin/python3').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'changed since'):
            self.freeze()

    def test_the_rest_of_the_batch_stays_closed_even_when_scratch_is_under_tmp(self):
        scratch = Path(tempfile.mkdtemp(prefix='rf-', dir='/tmp')).resolve()
        self.addCleanup(lambda: __import__('shutil').rmtree(scratch, ignore_errors=True))
        run = scratch/'runs/profile/case-a'
        with patch.object(policy_access.sys, 'platform', 'darwin'):
            table = policy_access.record(run, environment=self.root, repo=self.repo, home=self.home, checkouts=[self.repo])['filesystem']
        self.assertEqual(policy_access.mode(table, scratch/'runs/profile/case-b/private/x'), 'deny')
        self.assertEqual(policy_access.mode(table, scratch/'runs/other-profile/case-a/x'), 'deny')
        self.assertEqual(policy_access.mode(table, run/'workspace/x'), 'write')
        self.assertEqual(policy_access.mode(table, '/tmp/x'), 'write')

    def test_an_environment_without_a_passed_check_refuses(self):
        receipt = policy_env.receipt_path(self.root)
        passed = receipt.read_text()
        for broken in ('{"passed": false}', '{"passed": true, "tree_sha256": "other"}', 'not json'):
            receipt.write_text(broken)
            with self.assertRaisesRegex(ValueError, 'check_policy_env'):
                self.freeze()
        receipt.unlink()
        with self.assertRaisesRegex(ValueError, 'check_policy_env'):
            self.freeze()
        receipt.write_text(passed)
        self.freeze()

    def test_a_check_from_before_engine_combinations_must_be_rerun(self):
        receipt = policy_env.receipt_path(self.root)
        current = json.loads(receipt.read_text())
        receipt.write_text(json.dumps({key: current[key] for key in ('passed', 'tree_sha256')}))
        with self.assertRaisesRegex(ValueError, 'predates.*rerun scripts/check_policy_env.py'):
            self.freeze()
        with patch.dict(os.environ, {policy_env.ENV_VAR: str(self.root)}), \
                self.assertRaisesRegex(ValueError, 'predates.*rerun scripts/check_policy_env.py'):
            policy_env.require_combination('codex', 'landlock-v1')

    def test_only_the_engine_sandbox_and_cli_the_check_ran_are_admitted(self):
        versions = {'codex': 'codex-cli 0.165.0', 'claude': '2.1.312 (Claude Code)'}
        version = lambda binary, env=None, timeout_s=30: versions[binary]
        with patch.dict(os.environ, {policy_env.ENV_VAR: str(self.root)}), patch.object(policy_env, 'cli_version', version):
            policy_env.require_combination('codex', 'landlock-v1')
            policy_env.require_combination('claude', 'claude-sandbox')
            for engine, mode in (('codex', 'native'), ('claude', 'landlock-v1')):
                with self.assertRaisesRegex(ValueError, 'has not checked.*' + mode):
                    policy_env.require_combination(engine, mode)
            versions['codex'] = 'codex-cli 0.166.0'
            with self.assertRaisesRegex(ValueError, 'has not checked.*0.166.0'):
                policy_env.require_combination('codex', 'landlock-v1')
        with patch.dict(os.environ):
            os.environ.pop(policy_env.ENV_VAR, None)
            policy_env.require_combination('codex', 'native')

    def test_preparing_a_batch_refuses_a_combination_the_check_did_not_run(self):
        from robofrontier.codex.batch import prepare_batch
        with patch.dict(os.environ, {policy_env.ENV_VAR: str(self.root)}):
            with self.assertRaisesRegex(ValueError, 'has not checked.*native'):
                prepare_batch(self.tmp/'batch', ['astra'], cases=['dial-best5-n04-d1'])
        self.assertFalse((self.tmp/'batch').exists())

    def test_a_cli_that_hangs_or_is_missing_has_no_version(self):
        with tempfile.TemporaryDirectory() as folder:
            hung = Path(folder)/'hung'
            hung.write_text('#!/bin/sh\nsleep 60\n')
            hung.chmod(0o755)
            self.assertIsNone(policy_env.cli_version(str(hung), timeout_s=1))
            self.assertIsNone(policy_env.cli_version(str(Path(folder)/'absent')))

    def test_linux_refuses_a_run_or_tmpdir_under_tmp(self):
        scratch = Path(tempfile.mkdtemp(prefix='rf-', dir='/tmp')).resolve()
        self.addCleanup(lambda: __import__('shutil').rmtree(scratch, ignore_errors=True))
        run = scratch/'runs/profile/case-a'
        record = lambda run: policy_access.record(run, environment=self.root, repo=self.repo, home=self.home,
                                                  checkouts=[self.repo])
        with patch.object(policy_access.sys, 'platform', 'linux'):
            with patch.dict(os.environ, {'TMPDIR': str(self.tmp/'temporary')}):
                with self.assertRaisesRegex(ValueError, 'keep the run folder outside /tmp'):
                    record(run)
                record(self.run_dir)
            with patch.dict(os.environ, {'TMPDIR': str(scratch/'tmp')}), \
                    self.assertRaisesRegex(ValueError, 'keep TMPDIR outside /tmp'):
                record(self.run_dir)
            with patch.dict(os.environ, {'TMPDIR': '/tmp/'}):
                record(self.run_dir)
        with patch.object(policy_access.sys, 'platform', 'darwin'):
            with patch.dict(os.environ, {'TMPDIR': str(scratch/'tmp')}):
                record(run)

    def test_linux_closes_its_own_folders(self):
        with patch.object(policy_access.sys, 'platform', 'linux'):
            record = policy_access.record(self.run_dir, environment=self.root, repo=self.repo,
                                          home=self.home, checkouts=[self.repo])
        for path in ('/home/someone/x', '/raid/someone/x', '/var/tmp/x'):
            self.assertEqual(policy_access.mode(record['filesystem'], path), 'deny', path)

    def test_without_the_flag_every_run_keeps_the_earlier_table(self):
        with patch.dict(os.environ):
            os.environ.pop(policy_env.ENV_VAR, None)
            record = policy_access.record(self.run_dir, repo=self.repo, home=self.home, tmp_dirs=(), checkouts=[self.repo])
        self.assertEqual(record['schema'], 'robofrontier.policy-access.v1')
        self.assertNotIn('policy_env', record)
        self.assertEqual(record['filesystem'][str(self.run_dir)], 'read')


class ShellTests(Fixture):
    def test_shell_file_leaves_only_the_frozen_variables(self):
        values = policy_env.variables(self.root, self.run_dir)
        script = (policy_env.shell_text(values) + 'for name in %s; do printf "%%s=%%s\\n" "$name" "$(eval echo \\$$name)"; done\n'
                  '/usr/bin/env | /usr/bin/cut -d= -f1\n' % ' '.join(values))
        for shell in ('/bin/sh', '/bin/bash', '/bin/zsh'):
            if not Path(shell).exists():
                continue
            done = subprocess.run([shell, '-c', script], capture_output=True, text=True, check=True,
                                  env={'SECRET_TOKEN': 'x', 'PYTHONPATH': '/elsewhere', 'PATH': '/usr/bin:/bin', 'SPACED': 'a b'})
            self.assertIn('PATH=%s:/usr/bin:/bin' % (self.root/'python/bin'), done.stdout)
            names = set(done.stdout.splitlines())
            for name in ('SECRET_TOKEN', 'PYTHONPATH', 'SPACED'):
                self.assertNotIn(name, names, shell)

    def test_values_are_quoted_for_the_shell(self):
        self.assertIn('export A=' + shlex.quote("it's $x"), policy_env.shell_text({'A': "it's $x"}))


class RenderingTests(Fixture):
    def test_codex_gets_the_table_and_only_the_frozen_variables(self):
        record = self.freeze()
        out = self.tmp/'out'
        out.mkdir()
        with patch('robofrontier.codex.launch.hidden_skills', lambda: []):
            args = launch_config(STUB, out, run_dir=self.run_dir)['args']
        settings = [args[i + 1] for i, value in enumerate(args) if value == '-c']
        for expected in ('allow_login_shell=false', 'shell_environment_policy.inherit="none"',
                         'shell_environment_policy.set.TMPDIR=' + json.dumps(record['policy_env']['variables']['TMPDIR'])):
            self.assertIn(expected, settings)
        self.assertTrue(any(s.startswith('permissions.robofrontier.filesystem=') and json.dumps(str(self.run_dir)) + '="deny"' in s
                            for s in settings))

    def test_claude_gets_the_table_as_written_and_the_variables_only_in_shells(self):
        self.freeze()
        settings, extra = confine(self.run_dir, policy_settings(self.run_dir), self.tmp/'config')
        files = settings['sandbox']['filesystem']
        self.assertIn(str(self.run_dir), files['denyRead'])
        self.assertIn(str(self.run_dir/'public'), files['allowRead'])
        self.assertIn(str(self.root), files['allowRead'])
        self.assertNotIn('/', files['allowRead'])
        self.assertEqual(sorted(files['allowWrite']), sorted([str(self.run_dir/'workspace'), str(Path('/tmp').resolve())]))
        self.assertNotIn(str(Path('/tmp').resolve()), files['denyRead'])
        self.assertEqual(extra, {'CLAUDE_ENV_FILE': str(self.run_dir/'public/inputs/policy-env.sh')})

    def test_earlier_runs_render_as_before(self):
        record = policy_access.record(self.run_dir, environment=None, repo=self.repo, home=self.home, tmp_dirs=(),
                                      checkouts=[self.repo])
        (self.run_dir/'private/inputs/policy-access.json').write_text(json.dumps(record))
        settings, extra = confine(self.run_dir, policy_settings(self.run_dir), self.tmp/'config')
        self.assertNotIn('allowRead', settings['sandbox']['filesystem'])
        self.assertEqual(extra, {})


class RunFilesTests(Fixture):
    def test_preparation_makes_the_folders_and_the_guide_the_first_message_carries(self):
        values = policy_env.prepare_run(self.run_dir, self.root)
        for name in ('HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'MPLCONFIGDIR'):
            self.assertTrue(Path(values[name]).is_dir())
            self.assertTrue(Path(values[name]).is_relative_to(self.run_dir/'workspace'))
        guide = (self.run_dir/'public/inputs/environment.md').read_text()
        for expected in ('3.12.16', 'numpy 2.5.4', 'networkx', 'pip install NAME', 'Operation not permitted'):
            self.assertIn(expected, guide)
        self.assertNotIn('policy-env-fake', guide)
        self.assertNotEqual(policy_bootstrap.READABLE, policy_bootstrap.READABLE_ENV)


class RouteTests(Fixture):
    def config(self, root):
        return {'slurm': {'egress_mode': 'mac-ssh', 'egress_root': root}}

    def test_a_route_under_tmp_is_refused_only_for_a_run_with_an_environment(self):
        with patch.dict(os.environ, {policy_env.ENV_VAR: str(self.root)}):
            with self.assertRaisesRegex(ValueError, 'outside /tmp'):
                policy_env.require_private_route(self.config('/tmp/route'))
            policy_env.require_private_route(self.config('/var/tmp/route'))
            policy_env.require_private_route({'slurm': {'egress_mode': 'direct', 'egress_root': '/tmp/route'}})
        with patch.dict(os.environ):
            os.environ.pop(policy_env.ENV_VAR, None)
            policy_env.require_private_route(self.config('/tmp/route'))


class PinnedCliTests(unittest.TestCase):
    def cli(self, folder, output):
        path = Path(folder)/'codex'
        path.write_text('#!/bin/sh\necho %s\n' % shlex.quote(output))
        path.chmod(0o755)
        return {'PATH': folder + ':/usr/bin:/bin'}

    def test_only_the_pinned_codex_cli_is_accepted(self):
        from robofrontier.codex.job_engine import ROOT as source, require_pinned_cli
        pinned = re.search(r'CODEX_VERSION=(\S+)', (Path(source)/'docker/Dockerfile').read_text()).group(1)
        with tempfile.TemporaryDirectory() as folder:
            require_pinned_cli(self.cli(folder, 'codex-cli ' + pinned))
            with self.assertRaisesRegex(ValueError, pinned):
                require_pinned_cli(self.cli(folder, 'codex-cli 999.0.0'))
            with self.assertRaisesRegex(ValueError, pinned):
                require_pinned_cli({'PATH': folder + '/absent'})

    def test_a_hung_cli_or_an_unpinned_dockerfile_is_refused_clearly(self):
        import time
        from robofrontier.codex import job_engine
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'codex'
            path.write_text('#!/bin/sh\nsleep 60\n')
            path.chmod(0o755)
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, 'found none'):
                job_engine.require_pinned_cli({'PATH': folder + ':/usr/bin:/bin'}, timeout_s=1)
            self.assertLess(time.monotonic() - started, 30)
            (Path(folder)/'docker').mkdir()
            (Path(folder)/'docker/Dockerfile').write_text('FROM ubuntu\nARG CODEX_VERSION\n')
            with patch.object(job_engine, 'ROOT', Path(folder)), \
                    self.assertRaisesRegex(ValueError, 'no longer pins the Codex CLI'):
                job_engine.require_pinned_cli({'PATH': folder + ':/usr/bin:/bin'})


class CheckTests(unittest.TestCase):
    def test_every_attempt_has_an_expected_outcome_and_a_difference_is_reported(self):
        self.assertFalse(set(check_policy_env.MUST_WORK) & set(check_policy_env.MUST_FAIL))
        good = {**dict.fromkeys(check_policy_env.MUST_WORK, 'ok'), **dict.fromkeys(check_policy_env.MUST_FAIL, 'denied')}
        self.assertEqual(check_policy_env.differences(good), [])
        self.assertEqual(check_policy_env.differences({**good, 'read_private': 'ok'}), ['read_private should be denied'])
        self.assertEqual(check_policy_env.differences({**good, 'tempfile': 'denied'}), ['tempfile should work'])
        self.assertEqual(check_policy_env.differences({**good, 'tempfile': 'denied'}, ('tempfile',)), [])
        self.assertIn('venv should work', check_policy_env.differences({k: v for k, v in good.items() if k != 'venv'}))

    def test_a_receipt_admits_exactly_what_the_check_ran(self):
        self.assertEqual(check_policy_env.isolation('codex'), 'landlock-v1' if sys.platform == 'linux' else 'native')
        with tempfile.TemporaryDirectory() as folder:
            root = fake_environment(folder)
            manifest = policy_env.load(root)
            version = lambda binary, env=None, timeout_s=30: binary + ' 1.0'
            with patch.object(policy_env, 'cli_version', version), patch.dict(os.environ, {policy_env.ENV_VAR: str(root)}):
                record = check_policy_env.receipt_record(manifest, {'codex': 'native', 'claude': 'claude-sandbox'})
                policy_env.receipt_path(root).write_text(json.dumps(record))
                policy_env.require_combination('codex', 'native')
                policy_env.require_combination('claude', 'claude-sandbox')
                with self.assertRaisesRegex(ValueError, 'has not checked'):
                    policy_env.require_combination('codex', 'landlock-v1')
        self.assertEqual(record['checked'][0], {'engine': 'claude', 'bash_isolation': 'claude-sandbox', 'cli': 'claude 1.0'})

    def test_a_wrapper_failure_counts_even_when_the_script_itself_succeeded(self):
        finished = check_policy_env.policy_env_probe.FINISHED
        self.assertTrue(check_policy_env.shell_succeeded([{'content': finished}]))
        self.assertFalse(check_policy_env.shell_succeeded([{'content': 'x'}]))
        self.assertFalse(check_policy_env.shell_succeeded([{'content': finished, 'is_error': True}]))
        self.assertFalse(check_policy_env.shell_succeeded([{'content': finished + ' operation not permitted: /tmp/cwd'}]))


if __name__ == '__main__':
    unittest.main()
