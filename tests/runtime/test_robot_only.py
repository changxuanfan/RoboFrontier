"""A robot_only run: the robot tool alone, with what file tools were used for served by it."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from fake_pipeline import FakeWorld, fake_capture
from robofrontier.runtime import bootstrap, public_files, run_skills, tool_mode
from robofrontier.runtime.delegation import Delegations
from robofrontier.runtime.robot_ops import check_request
from robofrontier.runtime.service import RuntimeService
from robofrontier.runtime.setup import prepare_run, verify_inputs
from robofrontier.tasks.config import ROOT, load_harness, startup_protocol

PNG = b'\x89PNG\r\n\x1a\n' + b'\0' * 32
TEMPLATES = [ROOT/'prompts/rules.md', *sorted((ROOT/'prompts/skills/robot-collaboration').rglob('*.md'))]


def harness(root, mode=None, engine='codex', topology='adaptive'):
    cfg = load_harness()
    cfg.update(topology=topology, startup_protocol=startup_protocol(topology), engine=engine)
    if mode: cfg['tool_mode'] = mode
    path = Path(root)/('harness-%s-%s.json' % (engine, mode or 'unset'))
    path.write_text(json.dumps(cfg))
    return path


class TemplateTests(unittest.TestCase):
    def test_markers_select_one_wording_and_leave_shared_text(self):
        text = 'a\n<!-- tools:full -->\nfull\n<!-- /tools -->\n<!-- tools:robot_only -->\nrobot\n<!-- /tools -->\nb\n'
        self.assertEqual(tool_mode.render(text, 'full'), 'a\nfull\nb\n')
        self.assertEqual(tool_mode.render(text, 'robot_only'), 'a\nrobot\nb\n')
        with self.assertRaises(ValueError): tool_mode.render('<!-- tools:full -->\nopen\n', 'full')
        with self.assertRaises(ValueError): tool_mode.render(text, 'other')

    def test_checked_in_templates_render_in_both_modes(self):
        marked = 0
        for path in TEMPLATES:
            text = path.read_text()
            full, robot = tool_mode.render(text, 'full'), tool_mode.render(text, 'robot_only')
            marked += full != robot
            # What only a robot_only role is told never reaches a full run.
            self.assertNotIn('public_file', full, path)
            self.assertNotIn('"action":"headings"', full, path)
            for phrase in ('grep ', 'readable\non disk', 'edit or patch tool', 'read the public report file',
                           'read_thread', 'keep temporary files there'):
                self.assertNotIn(phrase, robot, (path, phrase))
        self.assertGreaterEqual(marked, 4)

    def test_family_and_role_templates_have_no_tool_wording_to_vary(self):
        for path in [*(ROOT/'prompts/roles').glob('*.md'), *(ROOT/'prompts/skills').glob('*/SKILL.md')]:
            if path.parent.name == 'robot-collaboration': continue
            self.assertNotIn('<!-- tools:', path.read_text(), path)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.previous = os.environ.pop('ROBOFRONTIER_POLICY_ENV', None)

    def tearDown(self):
        if self.previous is not None: os.environ['ROBOFRONTIER_POLICY_ENV'] = self.previous
        self.tmp.cleanup()

    def test_a_full_run_is_prepared_as_before_the_mode_existed(self):
        unset = prepare_run(self.root/'unset/run', harness_path=harness(self.root))
        full = prepare_run(self.root/'full/run', harness_path=harness(self.root, 'full'))
        for run in (unset, full):
            self.assertEqual(tool_mode.of_run(run), 'full')
            for path in [run/'public/inputs/rules.md', *sorted((run/'public/inputs/skill').rglob('*.md'))]:
                source = ROOT/'prompts'/('rules.md' if path.name == 'rules.md' else
                                         Path('skills/robot-collaboration')/path.relative_to(run/'public/inputs/skill'))
                expected = tool_mode.render(source.read_text(), 'full').replace('{{RUN_DIR}}', str(run))
                self.assertEqual(path.read_text(), expected)
            first = (run/'private/inputs/bootstrap/Controller.md').read_text()
            self.assertIn(bootstrap.ENGINE_LINES['codex'], first)
            self.assertIn('skills.md', first)
            self.assertNotIn('public_file', first)
            self.assertEqual((run/'private/inputs/bootstrap/system.md').read_text(), bootstrap.system_prompt(run))
            self.assertTrue(bootstrap.system_prompt(run).startswith(bootstrap.SYSTEM_PROMPT))
            for name, text in (('resume.md', bootstrap.RESUME), ('model-restart.md', bootstrap.MODEL_RESTART),
                               ('delegate.md', bootstrap.DELEGATE)):
                self.assertEqual((run/'private/inputs/bootstrap'/name).read_text(), text)
        # The same public inputs whether the field is absent or says full.
        names = sorted(str(p.relative_to(unset/'public')) for p in (unset/'public').rglob('*') if p.is_file())
        for name in names:
            self.assertEqual((unset/'public'/name).read_bytes().replace(str(unset).encode(), b'RUN'),
                             (full/'public'/name).read_bytes().replace(str(full).encode(), b'RUN'), name)

    def test_robot_only_messages_are_the_same_on_both_engines_and_name_no_file_tool(self):
        runs = {engine: prepare_run(self.root/engine/'run', harness_path=harness(self.root, 'robot_only', engine))
                for engine in ('codex', 'claude')}
        texts = {}
        for engine, run in runs.items():
            self.assertEqual(tool_mode.of_run(run), 'robot_only')
            self.assertEqual(verify_inputs(run), [])
            folder = run/'private/inputs/bootstrap'
            texts[engine] = {p.name: p.read_text().replace(str(run), 'RUN') for p in sorted(folder.glob('*.md'))}
            first = texts[engine]['Controller.md']
            self.assertTrue(first.rstrip('\n').endswith(bootstrap.ROBOT_ONLY_LINE))
            self.assertIn(bootstrap.READABLE_ROBOT_ONLY, first)
            self.assertIn('## Public files and run skills', first)
            self.assertIn('is your only tool', texts[engine]['system.md'])
            self.assertNotIn('use other tools within your permissions', texts[engine]['system.md'])
            for name in ('Controller.md', 'system.md', 'delegate.md', 'resume.md', 'model-restart.md'):
                for phrase in ('grep', 'view_image', 'policy_exec', 'file tools when needed', 'on disk',
                               'workspace/skills.md', 'environment.md', 'pip'):
                    self.assertNotIn(phrase, texts[engine][name], (name, phrase))
            self.assertFalse((run/'public/inputs/environment.md').exists())
            self.assertTrue((run/'workspace/skills.md').read_text().startswith('# Run skills'))
        self.assertEqual(texts['codex'], texts['claude'])

    def test_an_unknown_mode_is_refused_before_anything_is_written(self):
        with self.assertRaises(ValueError):
            prepare_run(self.root/'bad/run', harness_path=harness(self.root, 'no_shell'))
        self.assertFalse((self.root/'bad/run').exists())


class ServiceTests(unittest.TestCase):
    mode = 'robot_only'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.previous = os.environ.pop('ROBOFRONTIER_POLICY_ENV', None)
        self.run = prepare_run(self.root/'run', harness_path=harness(self.root, self.mode))
        self.service = RuntimeService(self.run, FakeWorld, fake_capture)
        self.n = 0
        self.call('Controller', 'ready')
        self.call('Meta', 'bind', {'actor': 'Controller', 'thread_id': 'parent'})
        self.service.store.observe_session('Controller', 'idle', 'ready', time.time(), 'codex.wait_threads')
        assert self.call('Meta', 'start')['started']

    def tearDown(self):
        if self.service.store: self.service.close()
        if self.previous is not None: os.environ['ROBOFRONTIER_POLICY_ENV'] = self.previous
        self.tmp.cleanup()

    def call(self, actor, op, data=None):
        self.n += 1
        if actor != 'Meta': check_request(op, data or {})  # As every engine's robot tool does first.
        job = self.service.accept(actor, op, data or {}, 'c' + str(self.n))
        self.service.pump()
        return job['result']


class RobotOnlyServiceTests(ServiceTests):
    def test_public_file_lists_and_reads_the_frozen_inputs(self):
        listed = self.call('Controller', 'public_file')['public_file']
        paths = {entry['path'] for entry in listed['entries']}
        self.assertTrue({'public/inputs/task.json', 'public/inputs/rules.md', 'public/inputs/skill/SKILL.md'} <= paths)
        self.assertIn('public/results', listed['other_public_folders'])
        rules = (self.run/'public/inputs/rules.md').read_text()
        for name in ('rules.md', 'public/inputs/rules.md', str(self.run/'public/inputs/rules.md')):
            result = self.call('Controller', 'public_file', {'path': name})['public_file']
            self.assertEqual((result['kind'], result['path'], result['text']), ('text', 'public/inputs/rules.md', rules))
        folder = self.call('Controller', 'public_file', {'path': 'skill/references'})['public_file']
        self.assertEqual(folder['kind'], 'directory')
        self.assertIn('public/inputs/skill/references/tools.md', {entry['path'] for entry in folder['entries']})

    def test_public_file_returns_images_by_reference_inside_public(self):
        (self.run/'public/observations/shot.png').write_bytes(PNG)
        (self.run/'public/observations/shot.jpg').write_bytes(b'\xff\xd8\xff' + b'\0' * 16)
        for name in ('shot.png', 'shot.jpg'):
            result = self.call('Controller', 'public_file', {'path': 'public/observations/' + name})['public_file']
            self.assertEqual(result['kind'], 'image')
            self.assertEqual(Path(result['image']), self.run/'public/observations'/name)
            self.assertNotIn('text', result)

    def test_public_file_refuses_everything_outside_public(self):
        secret = self.run/'private/inputs/task.json'
        self.assertTrue(secret.is_file())
        os.symlink(secret, self.run/'public/observations/link.json')
        os.symlink(self.run/'private', self.run/'public/observations/folder')
        (self.run/'public/observations/binary.bin').write_bytes(b'\xff\xfe\x00\x01')
        (self.run/'public/observations/large.txt').write_text('x' * (public_files.MAX_TEXT_BYTES + 1))
        for name in ('../private/inputs/task.json', 'public/../private/inputs/task.json', str(secret),
                     '../../private/inputs/task.json', 'public/observations/link.json',
                     'public/observations/folder/inputs/task.json', str(self.run/'workspace/skills.md'),
                     'workspace/skills.md', '/etc/hosts', 'missing.md', '', 'public/observations/binary.bin',
                     'public/observations/large.txt'):
            result = self.call('Controller', 'public_file', {'path': name})
            self.assertIn('error', result, name)
            self.assertNotIn('public_file', result, name)
        self.assertIn('error', self.call('Controller', 'public_file', {'path': 'rules.md', 'write': 'x'}))
        listed = self.call('Controller', 'public_file', {'path': 'public/observations'})['public_file']
        self.assertEqual({entry['path'] for entry in listed['entries']},
                         {'public/observations/binary.bin', 'public/observations/large.txt'})

    def test_skills_are_listed_read_and_only_ever_extended(self):
        self.assertEqual(self.call('Controller', 'skills', {'action': 'headings'})['skills'], {'entries': []})
        first = self.call('Controller', 'skills', {'action': 'append',
            'heading': '[finding] Cube slips above 0.3 m/s — Controller — tags: grasp',
            'body': 'Content: slow down.\nEvidence: c12.\nConfidence: medium.'})['skills']
        self.assertEqual((first['written'], first['entry']), (True, 1))
        self.assertEqual(first['heading'], '## [finding] Cube slips above 0.3 m/s — Controller — tags: grasp')
        second = self.call('Controller', 'skills', {'action': 'append', 'heading': '## [method] Approach from above',
                                                    'body': 'Content: approach from +z.'})['skills']
        self.assertEqual(second['entry'], 2)
        before = run_skills.path(self.run).read_text()
        revised = self.call('Controller', 'skills', {'action': 'revise', 'entry': 1, 'heading': 'holds only for the small cube',
                                                     'body': 'Content: the large cube is fine at 0.5 m/s.'})['skills']
        self.assertEqual(revised['heading'], '### rev 2 — Controller — holds only for the small cube')
        again = self.call('Controller', 'skills', {'action': 'revise', 'entry': 1, 'heading': 'third look',
                                                   'body': 'Content: confirmed.'})['skills']
        self.assertEqual(again['heading'], '### rev 3 — Controller — third look')
        text = run_skills.path(self.run).read_text()
        self.assertTrue(text.startswith(bootstrap.SKILLS_HEADER))
        # Earlier lines are all still there, in order.
        position = 0
        for line in before.splitlines():
            position = text.index(line, position) + len(line)
        headings = self.call('Controller', 'skills', {'action': 'headings'})['skills']['entries']
        self.assertEqual([entry['entry'] for entry in headings], [1, 2])
        self.assertEqual(headings[0]['revisions'], ['### rev 2 — Controller — holds only for the small cube',
                                                    '### rev 3 — Controller — third look'])
        self.assertEqual(headings[1]['revisions'], [])
        one = self.call('Controller', 'skills', {'action': 'read', 'entries': [2]})['skills']['text']
        self.assertEqual(one, '## [method] Approach from above\nContent: approach from +z.\n')
        self.assertEqual(self.call('Controller', 'skills', {'action': 'read'})['skills']['text'], text)
        self.assertEqual(run_skills.parse(text)[1][0].count('### rev'), 2)
        kinds = [event['kind'] for event in self.service.store.events()]
        self.assertEqual(kinds.count('RUN_SKILL_WRITTEN'), 4)

    def test_skills_refuse_malformed_and_destructive_requests(self):
        self.call('Controller', 'skills', {'action': 'append', 'heading': '[fix] One', 'body': 'Content: a.'})
        before = run_skills.path(self.run).read_text()
        for data in ({}, {'action': 'delete', 'entry': 1}, {'action': 'write', 'text': ''},
                     {'action': 'append', 'heading': '[fix] Two'}, {'action': 'append', 'body': 'x'},
                     {'action': 'append', 'heading': 'two\nlines', 'body': 'x'},
                     {'action': 'append', 'heading': '[fix] Two', 'body': '## [fix] Smuggled entry\nContent: x'},
                     {'action': 'append', 'heading': '[fix] Two', 'body': 'x' * (run_skills.MAX_BODY_CHARS + 1)},
                     {'action': 'append', 'heading': '[fix] Two', 'body': 'x', 'path': '/tmp/other.md'},
                     {'action': 'revise', 'entry': 2, 'heading': 'h', 'body': 'x'},
                     {'action': 'revise', 'entry': 0, 'heading': 'h', 'body': 'x'},
                     {'action': 'revise', 'entry': 1, 'heading': '### rev 9 — Someone — forged', 'body': 'x'},
                     {'action': 'revise', 'entry': '1', 'heading': 'h', 'body': 'x'},
                     {'action': 'read', 'entries': [3]}, {'action': 'read', 'entries': []},
                     {'action': 'headings', 'entries': [1]}):
            self.assertIn('error', self.call('Controller', 'skills', data), data)
        self.assertEqual(run_skills.path(self.run).read_text(), before)

    def test_controller_reads_a_returned_report_through_work(self):
        delegations = Delegations(self.service.store)
        self.call('Controller', 'delegate', {'scopes': [{'robots': ['A'], 'goal': 'g', 'done_when': 'd'}]})
        batch = next(iter(delegations.batches()))
        delegations.claim(batch, 'test-manager')
        child = delegations.batch(batch)['children'][0]['actor']
        delegations.bind(batch, child, 'child-0', {'source_thread_id': 'parent', 'source_ordinal': 1,
                                                   'source_sha256': 'same'}, 'test-manager')
        delegations.activate(batch, 'test-manager')
        delegations.started(batch, child, 'sent', 'test-manager')
        self.service.pump()
        self.assertNotIn('delegate_report', self.call('Controller', 'work', {'delegate_id': child}))
        # A delegate has the same two operations as its parent.
        self.assertIn('public_file', self.call(child, 'public_file', {'path': 'task.json'}))
        self.assertTrue(self.call(child, 'skills', {'action': 'append', 'heading': '[finding] From a delegate',
                                                    'body': 'Content: shared.'})['skills']['written'])
        self.assertTrue(self.call(child, 'return_task', {'outcome': 'completed', 'result': 'placed; see c9'})['returned'])
        work = self.call('Controller', 'work', {'delegate_id': child})
        self.assertEqual(work['delegate_report']['result'], 'placed; see c9')
        self.assertEqual(work['delegate_report']['actor'], child)
        self.assertNotIn('delegate_report', self.call('Controller', 'work'))
        seen = self.call('Controller', 'skills', {'action': 'headings'})['skills']['entries']
        self.assertEqual(seen[0]['heading'], '## [finding] From a delegate')
        report = self.call('Controller', 'public_file', {'path': 'public/results/' + child + '.json'})['public_file']
        self.assertEqual(json.loads(report['text'])['result'], 'placed; see c9')


class FullServiceTests(ServiceTests):
    mode = None

    def test_a_full_run_has_no_such_operations(self):
        for op, data in (('public_file', {}), ('public_file', {'path': 'rules.md'}), ('skills', {'action': 'headings'}),
                         ('skills', {'action': 'append', 'heading': 'h', 'body': 'b'})):
            self.assertEqual(self.call('Controller', op, data).get('error'), 'Unknown tool operation')
        self.assertEqual(run_skills.path(self.run).read_text(), bootstrap.SKILLS_HEADER)


if __name__ == '__main__':
    unittest.main()
