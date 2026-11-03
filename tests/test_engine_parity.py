"""Both engines receive the same frozen policy inputs; only the declared engine line differs."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robofrontier import policy_access, policy_bootstrap
from robofrontier.task_config import ROOT
from robofrontier.task_families import prepare

HARNESS = json.loads((ROOT/'configs/harnesses/policy.json').read_text())
STARTUP = {'centralized': 'direct_controller_v2', 'adaptive': 'direct_controller_v2',
           'hierarchical': 'direct_team_v3', 'peer': 'direct_team_v3'}


def snapshot(run):
    """Every policy-visible input and frozen message, with the run directory abstracted."""
    run = Path(run)
    files = {}
    for folder in ('public/inputs', 'private/inputs/bootstrap', 'workspace'):
        for path in sorted((run/folder).rglob('*')):
            if path.is_file():
                data = path.read_bytes().replace(str(run.resolve()).encode(), b'RUN').replace(str(run).encode(), b'RUN')
                files[str(path.relative_to(run))] = data
    return files


def prepared(root, engine, case='transport-a04-d1'):
    """A prepared run of `case` for `engine` with the frozen policy harness."""
    path = Path(root)/(engine+'-harness.json')
    path.write_text(json.dumps(dict(HARNESS, engine=engine)))
    return prepare(case, Path(root)/engine, path)


class EngineParityTests(unittest.TestCase):
    def prepare_pair(self, tmp, case, topology):
        runs = {}
        for engine in ('codex', 'claude'):
            harness = dict(HARNESS, engine=engine, topology=topology, startup_protocol=STARTUP[topology])
            path = Path(tmp)/(engine+'-'+topology+'.json')
            path.write_text(json.dumps(harness))
            runs[engine] = prepare(case, Path(tmp)/engine/topology/case, path)
        return runs

    def assert_same_inputs(self, runs):
        codex, claude = snapshot(runs['codex']), snapshot(runs['claude'])
        self.assertEqual(sorted(codex), sorted(claude))
        engine_lines = {line.encode() for line in policy_bootstrap.ENGINE_LINES.values()}
        for name in codex:
            if codex[name] == claude[name]:
                continue
            # A frozen first message may differ only in its last, engine-specific line.
            self.assertTrue(name.startswith('private/inputs/bootstrap/'), name)
            a, b = codex[name].rstrip(b'\n').rsplit(b'\n', 1), claude[name].rstrip(b'\n').rsplit(b'\n', 1)
            self.assertEqual(a[0], b[0], name)
            self.assertEqual({a[1], b[1]}, engine_lines, name)
        for run in runs.values():
            access = json.loads((run/'private/inputs/policy-access.json').read_text())
            self.assertEqual(policy_access.mode(access['filesystem'], run/'workspace/notes.md'), 'write')
            self.assertEqual(policy_access.mode(access['filesystem'], run/'public/inputs/task.json'), 'read')
            self.assertEqual(policy_access.mode(access['filesystem'], run/'private/inputs/task.json'), 'deny')
            self.assertEqual(policy_access.mode(access['filesystem'], ROOT/'robofrontier/pipeline.py'), 'deny')
            self.assertFalse(access['network'])
            self.assertFalse(access['web_search'])

    def test_every_family_gets_identical_inputs_on_both_engines(self):
        with tempfile.TemporaryDirectory() as tmp, patch('mujoco.mj_step', side_effect=AssertionError('No physics')):
            for case in ('transport-a04-d1', 'mosaic-a04-6x12-d1', 'relay-a08-d1', 'dial-best5-n04-d1'):
                with self.subTest(case=case):
                    self.assert_same_inputs(self.prepare_pair(tmp, case, 'adaptive'))

    def test_every_topology_gets_identical_inputs_on_both_engines(self):
        with tempfile.TemporaryDirectory() as tmp, patch('mujoco.mj_step', side_effect=AssertionError('No physics')):
            for topology in ('centralized', 'hierarchical', 'peer'):
                with self.subTest(topology=topology):
                    runs = self.prepare_pair(tmp, 'transport-a04-d1', topology)
                    self.assert_same_inputs(runs)
                    roles = json.loads((runs['codex']/'public/inputs/roles.json').read_text())['roles']
                    for actor, info in roles.items():
                        if info['kind'] != 'manager':
                            text = (runs['codex']/'private/inputs/bootstrap'/(actor+'.md')).read_text()
                            self.assertIn(policy_bootstrap.STARTUP[STARTUP[topology]], text)
                            self.assertIn(policy_bootstrap.READABLE, text)

    def test_the_start_message_carries_the_inputs_and_the_system_prompt_the_rules(self):
        with tempfile.TemporaryDirectory() as tmp, patch('mujoco.mj_step', side_effect=AssertionError('No physics')):
            run = self.prepare_pair(tmp, 'mosaic-a04-6x12-d1', 'adaptive')['codex']
            public = run/'public/inputs'
            text = (run/'private/inputs/bootstrap/Controller.md').read_text()
            for relative in ('task.json', 'roles.json', 'roles/Controller.md', 'skill/SKILL.md',
                             'skill/references/tools.md', 'skill/references/motion-check.md',
                             'skill/references/communication.md', 'skill/references/adaptive.md'):
                self.assertIn('--- '+str(public/relative)+' ---\n'+(public/relative).read_text().rstrip('\n'), text)
            rules = (public/'rules.md').read_text().rstrip('\n')
            self.assertNotIn(rules, text)
            self.assertEqual((run/'private/inputs/bootstrap/system.md').read_text(), policy_bootstrap.system_prompt(run))
            self.assertIn(rules, policy_bootstrap.system_prompt(run))
            # The host keeps the wall limit; no policy input states it.
            private = json.loads((run/'private/inputs/task.json').read_text())['run_protocol']
            self.assertIn('total_wall_limit_s', private)
            self.assertNotIn('total_wall_limit_s', json.loads((public/'task.json').read_text())['run_protocol'])
            for path in list(public.rglob('*.md'))+list(public.rglob('*.json'))+[run/'private/inputs/bootstrap/Controller.md']:
                self.assertNotIn('total_wall_limit_s', path.read_text(), path)

    def test_resume_message_is_one_frozen_template_for_both_engines(self):
        with tempfile.TemporaryDirectory() as tmp, patch('mujoco.mj_step', side_effect=AssertionError('No physics')):
            root = Path(tmp).resolve()
            runs = {engine: prepared(root, engine) for engine in ('claude', 'codex')}
            record = {'restored_sim_s': 12.345, 'interrupted': {'Controller': ['Controller-call_1']}}
            texts = {e: policy_bootstrap.fill_resume(r, 'Controller', record) for e, r in runs.items()}
            self.assertEqual(texts['claude'], texts['codex'])
            self.assertIn('12.35', texts['claude']); self.assertIn('Controller-call_1', texts['claude'])
            self.assertIn('Yours: none.', policy_bootstrap.fill_resume(runs['codex'], 'Delegate_x', record))
            for run in runs.values():
                self.assertEqual((run/'private/inputs/bootstrap/resume.md').read_text(), policy_bootstrap.RESUME)


class PolicyAccessTests(unittest.TestCase):
    def test_the_most_specific_path_wins_and_credentials_stay_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, repo = Path(tmp)/'home', Path(tmp)/'repo'
            run = repo/'runs/policy/batch/p/case'
            (run/'workspace').mkdir(parents=True)
            with patch.dict('os.environ', {'CODEX_HOME': str(Path(tmp)/'codex-auth'),
                                           'ROBOFRONTIER_CLAUDE_HOME': str(Path(tmp)/'claude-auth')}):
                table = policy_access.table(run, repo=repo, home=home, tmp_dirs=[tmp+'/scratch'], checkouts=[repo, Path(tmp)/'worktree'])
            mode = lambda path: policy_access.mode(table, path)
            self.assertEqual(mode(run/'workspace/skills.md'), 'write')
            self.assertEqual(mode(run/'public/inputs/task.json'), 'read')
            self.assertEqual(mode(run/'private/state/runtime.sqlite'), 'deny')
            self.assertEqual(mode(repo/'runs/policy/batch/p/other/public/results/x'), 'deny')
            self.assertEqual(mode(repo/'.env'), 'deny')
            self.assertEqual(mode(Path(tmp)/'worktree/scripts/oracle.py'), 'deny')
            for secret in (home/'.codex/auth.json', home/'.claude/.credentials.json', home/'.ssh/id_ed25519',
                           home/'.robofrontier/codex-home/auth.json', Path(tmp)/'codex-auth/auth.json',
                           Path(tmp)/'claude-auth/.credentials.json'):
                self.assertEqual(mode(secret), 'deny', secret)
            self.assertEqual(mode(Path(tmp)/'scratch/a.py'), 'write')
            self.assertEqual(mode(Path('/usr/bin/python3')), 'read')


if __name__ == '__main__':
    unittest.main()


class EngineRenderingTests(unittest.TestCase):
    """Each engine renders the same frozen access table and system prompt natively."""

    def prepared(self, tmp, engine):
        harness = dict(HARNESS, engine=engine)
        path = Path(tmp)/(engine+'.json')
        path.write_text(json.dumps(harness))
        return prepare('transport-a04-d1', Path(tmp)/engine, path)

    def test_claude_policy_turns_get_confined_file_tools_and_the_frozen_system_prompt(self):
        from robofrontier.claude.runner import build_command, policy_settings, policy_system_prompt, policy_cwd
        with tempfile.TemporaryDirectory() as tmp, patch('mujoco.mj_step', side_effect=AssertionError('No physics')):
            run = self.prepared(tmp, 'claude')
            settings = policy_settings(run)
            # Absolute rules (//path). Claude has no most-specific-wins, so the repository
            # holding the run is denied around it: its source is denied, the run is not.
            deny = settings['permissions']['deny']
            self.assertIn('Read(//'+str((run/'private').resolve()).lstrip('/')+'/**)', deny)
            self.assertIn('Edit(//'+str((run/'public').resolve()).lstrip('/')+'/**)', deny)
            # This run lies outside the repository, so the whole checkout is denied.
            self.assertIn('Read(//'+str(ROOT.resolve()).lstrip('/')+'/**)', deny)
            self.assertFalse(any(rule.startswith('Read(//'+str(run.resolve()).lstrip('/')+'/**') for rule in deny))
            self.assertIn(str((run/'workspace').resolve()), settings['sandbox']['filesystem']['allowWrite'])
            self.assertEqual(settings['sandbox']['network']['allowedDomains'], [])
            cmd = build_command('m', 'high', 'mcp.json', 'go', session_id='s', settings=settings,
                                system_prompt=policy_system_prompt(run), prompt_via_stdin=True)
            tools = cmd[cmd.index('--tools')+1].split(',')
            self.assertEqual(set(tools), {'Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep'})
            self.assertNotIn('--bare', cmd)
            self.assertEqual(cmd[cmd.index('--setting-sources')+1], '')
            system = cmd[cmd.index('--system-prompt')+1]
            # The system prompt is the role statement followed by the run's rules, which a
            # compacted conversation therefore keeps.
            self.assertEqual(system, policy_bootstrap.system_prompt(run))
            self.assertTrue(system.startswith(policy_bootstrap.SYSTEM_PROMPT))
            self.assertIn((run/'public/inputs/rules.md').read_text().rstrip('\n'), system)
            self.assertIn('Plan and act as if time were unlimited.', system)
            self.assertEqual(policy_cwd(run), run/'workspace')
            # A delegate's fork turn gets the same tools and prompt, plus the gate that holds
            # them until the runtime activates it.
            gate = {'open': run/'g-open', 'closed': run/'g-closed', 'deadline': 4102444800}
            fork = build_command('m', 'high', 'mcp.json', 'go', session_id='c', fork_from='p', settings=settings,
                                 system_prompt=policy_system_prompt(run), prompt_via_stdin=True, gate=gate)
            self.assertEqual(fork[fork.index('--tools')+1], cmd[cmd.index('--tools')+1])
            self.assertEqual(fork[fork.index('--system-prompt')+1], system)
            forked = json.loads(fork[fork.index('--settings')+1])
            self.assertEqual(forked['permissions'], settings['permissions'])
            self.assertIn('PreToolUse', forked['hooks'])

    def test_codex_runs_under_the_frozen_permission_profile_without_web_search(self):
        from robofrontier.codex.launch import launch_config, profile
        with tempfile.TemporaryDirectory() as tmp, patch('mujoco.mj_step', side_effect=AssertionError('No physics')):
            run = self.prepared(tmp, 'codex')
            launch = launch_config(profile('luna'), run/'private/inputs', run)
            args = ' '.join(launch['args'])
            self.assertIn('default_permissions="robofrontier"', args)
            self.assertIn('permissions.robofrontier.network.enabled=false', args)
            self.assertIn(json.dumps(str((run/'private').resolve()))+'="deny"', args)
            self.assertIn(json.dumps(str((run/'workspace').resolve()))+'="write"', args)
            self.assertIn('web_search="disabled"', args)
            self.assertIn('project_doc_max_bytes=0', args)
            catalog = json.loads((run/'private/inputs/models.json').read_text())
            self.assertEqual(catalog['models'][0]['base_instructions'], policy_bootstrap.system_prompt(run))
            self.assertEqual(launch['context_window'], 272000)
            self.assertEqual(launch['auto_compact_token_limit'], 258400)
