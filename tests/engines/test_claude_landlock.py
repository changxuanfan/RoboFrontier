"""Landlock Bash isolation for Claude runs on hosts where Claude Code's sandbox cannot run."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from robofrontier.runtime import layout as run_layout
from robofrontier.engines.common import landlock as landlock_shell
from robofrontier.engines.claude.runner import confine


def tree(base):
    """A host with a repository holding a run, as the access table sees it."""
    repo = base/'repo'; run = repo/'runs/b/p/case'
    for folder in ('src', 'runs/other/private', 'runs/b/p/case/public/inputs', 'runs/b/p/case/private/state',
                   'runs/b/p/case/private/engine/config/shell-snapshots', 'runs/b/p/case/workspace', 'outside/data'):
        (repo/folder if folder != 'outside/data' else base/folder).mkdir(parents=True)
    (repo/'src/answer.py').write_text('answer')
    (run/'private/state/truth.json').write_text('truth')
    (run/'public/inputs/task.json').write_text('task')
    (repo/'runs/other/private/x').write_text('other')
    (base/'outside/data/ok.txt').write_text('ok')
    table = {str(base): 'read', str(repo): 'deny', str(run): 'read', str(run/'private'): 'deny',
             str(run/'workspace'): 'write'}
    return repo, run, table


class AllowlistTests(unittest.TestCase):
    def test_simultaneous_rules_writes_use_distinct_temporary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'rules.json'
            barrier = threading.Barrier(2)
            replace = landlock_shell.os.replace
            errors = []
            def synchronized_replace(source, destination):
                barrier.wait(timeout=5)
                replace(source, destination)
            def write():
                try:
                    landlock_shell.write_rules(path, [('/tmp', 'read')])
                except Exception as error:
                    errors.append(error)
            with patch.object(landlock_shell.os, 'replace', synchronized_replace):
                threads = [threading.Thread(target=write) for _ in range(2)]
                for thread in threads: thread.start()
                for thread in threads: thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(json.loads(path.read_text())['rules'], [['/tmp', 'read']])
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_the_most_specific_entry_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); repo, run, table = tree(base)
            rules = dict(landlock_shell.allowlist(table))
            self.assertEqual(rules[str(base/'outside')], 'read')
            self.assertEqual(rules[str(run/'public')], 'read')
            self.assertEqual(rules[str(run/'workspace')], 'write')
            # Nothing inside the repository except the run's public side, and never private/.
            for path in rules:
                inside = Path(path) == repo or repo in Path(path).parents
                self.assertFalse(inside and run not in Path(path).parents, path)
                self.assertFalse(Path(path) == run/'private' or run/'private' in Path(path).parents, path)
            self.assertNotIn(str(repo), rules); self.assertNotIn(str(run), rules)
            extra = dict(landlock_shell.allowlist(table, read=[run/'private/engine/config/shell-snapshots'],
                                                  write=landlock_shell.DEVICES))
            self.assertEqual(extra[str(run/'private/engine/config/shell-snapshots')], 'read')
            self.assertEqual(extra['/dev/null'], 'write')

    def test_a_link_beside_a_denied_folder_gets_no_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); repo, run, table = tree(base)
            (base/'alias').symlink_to(repo)                 # /root/RoboFrontier -> /workspace/RoboFrontier
            (base/'data-link').symlink_to(base/'outside')   # its target keeps its own rule
            rules = dict(landlock_shell.allowlist(table))
            self.assertNotIn(str(base/'alias'), rules)
            self.assertNotIn(str(base/'data-link'), rules)
            self.assertEqual(rules[str(base/'outside')], 'read')

    def test_entries_that_agree_with_their_folder_do_not_split_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); repo = base/'repo'; repo.mkdir()
            temporary = base/'tmp'; (temporary/'job123').mkdir(parents=True); (temporary/'other').mkdir()
            # A policy shell plants a link in the shared temporary folder before a later turn renders rules.
            (temporary/'planted').symlink_to(repo)
            table = {str(base): 'read', str(repo): 'deny', str(temporary): 'write', str(temporary/'job123'): 'write'}
            rules = landlock_shell.allowlist(table)
            self.assertIn((str(temporary), 'write'), rules)
            self.assertFalse(any('planted' in path or path == str(temporary/'other') for path, _ in rules), rules)
            self.assertFalse(any(Path(path) == repo or repo in Path(path).parents for path, _ in rules), rules)


    def test_a_folder_with_only_closed_files_can_still_be_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); tools = base/'bin'; tools.mkdir(); (base/'home').mkdir()
            for name in ('true', 'python3'): (tools/name).write_text('')
            # /usr/bin with the system Python closed: listed, its other files readable.
            rules = landlock_shell.allowlist({str(base): 'read', str(tools/'python3'): 'deny'})
            self.assertIn((str(tools), 'list'), rules)
            self.assertIn((str(tools/'true'), 'read'), rules)
            self.assertNotIn(str(tools/'python3'), dict(rules))
            # A closed folder below keeps its parent unlisted, since listing reaches below.
            rules = landlock_shell.allowlist({str(base): 'read', str(base/'home'): 'deny'})
            self.assertNotIn((str(base), 'list'), rules)

    def test_write_never_makes_a_named_socket(self):
        fs = landlock_shell.handled_fs(4)
        self.assertFalse(landlock_shell.access_for('write', fs) & landlock_shell.MAKE_SOCK)
        self.assertEqual(landlock_shell.access_for('list', fs), landlock_shell.READ_DIR)

class ConfineTests(unittest.TestCase):
    def prepared(self, base, isolation):
        repo, run, table = tree(base)
        (run/'private/inputs').mkdir()
        (run/'private/inputs/policy-access.json').write_text(json.dumps({'filesystem': table, 'network': False}))
        launch = {'schema': 'robofrontier.claude-launch.v2'}
        if isolation: launch['bash_isolation'] = isolation
        (run/'private/inputs/claude.json').write_text(json.dumps(launch))
        return run

    def test_roles_can_prepare_isolation_concurrently(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.prepared(Path(tmp).resolve(), 'landlock-v1')
            settings = {'sandbox': {'enabled': True}}
            barrier = threading.Barrier(8)
            replace = landlock_shell.os.replace
            errors, prefixes = [], []
            def synchronized_replace(source, destination):
                barrier.wait(timeout=10)
                replace(source, destination)
            def prepare():
                try:
                    _, env = confine(run, settings, run/'private/engine/config')
                    prefixes.append(Path(env['CLAUDE_CODE_SHELL_PREFIX']))
                except Exception as error:
                    errors.append(error)
            with patch.object(landlock_shell.os, 'replace', synchronized_replace):
                threads = [threading.Thread(target=prepare) for _ in range(8)]
                for thread in threads: thread.start()
                for thread in threads: thread.join(timeout=20)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(len(prefixes), 8)
            self.assertEqual(len(set(prefixes)), 1)
            self.assertTrue(prefixes[0].stat().st_mode & 0o111)
            self.assertIn('"$@"', prefixes[0].read_text())
            self.assertEqual(json.loads((prefixes[0].parent/'rules.json').read_text())['schema'],
                             landlock_shell.SCHEMA)

    def test_earlier_runs_and_claude_sandbox_runs_keep_claude_codes_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            for isolation in (None, 'claude-sandbox'):
                run = self.prepared(Path(tmp).resolve()/str(isolation), isolation)
                settings = {'permissions': {'deny': ['x']}, 'sandbox': {'enabled': True}}
                self.assertEqual(confine(run, settings, run/'private/engine/config'), (settings, {}))
            self.assertEqual(confine(run, None, run/'private/engine/config'), (None, {}))

    def test_a_landlock_run_turns_the_sandbox_off_and_prefixes_bash(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.prepared(Path(tmp).resolve(), 'landlock-v1')
            settings = {'permissions': {'deny': ['Read(//x/**)']}, 'sandbox': {'enabled': True}}
            confined, env = confine(run, settings, run/'private/engine/config')
            self.assertEqual(confined['permissions'], settings['permissions'])
            self.assertEqual(confined['sandbox'], {'enabled': False})
            prefix = Path(env['CLAUDE_CODE_SHELL_PREFIX'])
            self.assertTrue(prefix.is_relative_to(run/'private'))
            self.assertIn(str(Path(landlock_shell.__file__).resolve()), prefix.read_text())
            rules = json.loads((prefix.parent/'rules.json').read_text())
            self.assertEqual(rules['schema'], landlock_shell.SCHEMA)
            self.assertIn([str(run/'private/engine/config/shell-snapshots'), 'read'], rules['rules'])
            self.assertEqual(rules['unconfined'], [])
            # Claude Code starts each robot MCP through the prefix too; its exact string runs unconfined.
            servers = run_layout.path(run, 'engine_mcp', 'claude'); servers.mkdir(parents=True, exist_ok=True)
            for actor in ('A', 'Controller'):
                (servers/(actor+'.json')).write_text(json.dumps({'mcpServers': {'robot': {
                    'command': '/v/bin/python', 'args': ['-m', 'robofrontier.engines.claude.robot_mcp', '--connection',
                                                         '/r un/%s.json' % actor], 'env': {}}}}))
            confine(run, settings, run/'private/engine/config')
            rules = json.loads((prefix.parent/'rules.json').read_text())
            self.assertEqual(rules['unconfined'], [
                "/v/bin/python -m robofrontier.engines.claude.robot_mcp --connection '/r un/A.json'",
                "/v/bin/python -m robofrontier.engines.claude.robot_mcp --connection '/r un/Controller.json'"])
            with self.assertRaisesRegex(ValueError, 'Unknown Bash isolation'):
                (run/'private/inputs/claude.json').write_text(json.dumps({'bash_isolation': 'none'}))
                confine(run, settings, run/'private/engine/config')

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS keeps Claude Code\'s Seatbelt sandbox')
    def test_macos_keeps_claude_codes_sandbox(self):
        self.assertEqual(landlock_shell.choose(), 'claude-sandbox')


@unittest.skipUnless(landlock_shell.abi() >= landlock_shell.NETWORK_ABI, 'Needs Linux Landlock ABI 4')
class LandlockShellTests(unittest.TestCase):
    """The actual confinement, on a Linux host with Landlock."""

    def run_shell(self, rules, command):
        return subprocess.run([sys.executable, '-I', landlock_shell.__file__, str(rules), command],
                              capture_output=True, text=True, timeout=60)

    def test_bash_reads_writes_and_connects_only_as_the_table_allows(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); repo, run, table = tree(base)
            table['/'] = 'read'
            rules = base/'rules.json'
            landlock_shell.write_rules(rules, landlock_shell.allowlist(table, write=landlock_shell.DEVICES))
            ok = lambda command: self.assertEqual(self.run_shell(rules, command).returncode, 0, command)
            refused = lambda command: self.assertNotEqual(self.run_shell(rules, command).returncode, 0, command)
            ok('cat %s && cat %s >/dev/null' % (run/'public/inputs/task.json', base/'outside/data/ok.txt'))
            ok('echo note > %s && cat %s' % (run/'workspace/note.txt', run/'workspace/note.txt'))
            refused('cat %s' % (run/'private/state/truth.json'))
            refused('cat %s' % (repo/'src/answer.py'))
            refused('cat %s' % (repo/'runs/other/private/x'))
            refused('ls %s' % repo)
            refused('echo x > %s' % (run/'public/inputs/new.txt'))
            refused('echo x > %s' % (base/'outside/data/new.txt'))
            with socket.socket() as server:
                server.bind(('127.0.0.1', 0)); server.listen(1)
                port = server.getsockname()[1]
                refused("exec 3<>/dev/tcp/127.0.0.1/%d" % port)
            self.assertFalse((run/'public/inputs/new.txt').exists())

    def test_a_rule_naming_a_link_never_grants_its_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); repo, run, table = tree(base)
            table['/'] = 'read'
            (run/'workspace/link').symlink_to(repo)
            rules = base/'rules.json'
            landlock_shell.write_rules(rules, landlock_shell.allowlist(table, write=landlock_shell.DEVICES)
                                       + [(str(run/'workspace/link'), 'write')])
            self.assertNotEqual(self.run_shell(rules, 'cat %s' % (repo/'src/answer.py')).returncode, 0)
            self.assertNotEqual(self.run_shell(rules, 'echo x > %s' % (repo/'src/new.py')).returncode, 0)
            self.assertFalse((repo/'src/new.py').exists())

    def test_only_the_exact_robot_server_string_runs_unconfined(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); repo, run, table = tree(base)
            table['/'] = 'read'
            exact = 'cat %s' % (repo/'src/answer.py')
            rules = base/'rules.json'
            landlock_shell.write_rules(rules, landlock_shell.allowlist(table, write=landlock_shell.DEVICES), [exact])
            self.assertEqual(self.run_shell(rules, exact).stdout, 'answer')
            for near in (exact + ' ', ' ' + exact, exact + '; true', 'eval ' + repr(exact)):
                self.assertNotIn('answer', self.run_shell(rules, near).stdout, near)

    def test_it_refuses_rules_it_does_not_know(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = Path(tmp)/'rules.json'; rules.write_text(json.dumps({'schema': 'other', 'rules': []}))
            self.assertEqual(self.run_shell(rules, 'true').returncode, 126)


if __name__ == '__main__':
    unittest.main()
