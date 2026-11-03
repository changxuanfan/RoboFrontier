"""Landlock Bash isolation for Claude runs on hosts where Claude Code's sandbox cannot run."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

from robofrontier.claude import landlock_shell
from robofrontier.claude.runner import confine


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


class ConfineTests(unittest.TestCase):
    def prepared(self, base, isolation):
        repo, run, table = tree(base)
        (run/'private/inputs').mkdir()
        (run/'private/inputs/policy-access.json').write_text(json.dumps({'filesystem': table, 'network': False}))
        launch = {'schema': 'robofrontier.claude-launch-draft.v1'}
        if isolation: launch['bash_isolation'] = isolation
        (run/'private/inputs/claude.json').write_text(json.dumps(launch))
        return run

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

    def test_it_refuses_rules_it_does_not_know(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = Path(tmp)/'rules.json'; rules.write_text(json.dumps({'schema': 'other', 'rules': []}))
            self.assertEqual(self.run_shell(rules, 'true').returncode, 126)


if __name__ == '__main__':
    unittest.main()
