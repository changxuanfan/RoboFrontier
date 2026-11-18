import json
import tempfile
import unittest
from pathlib import Path

from roboteam.runtime.run.setup import verify_inputs
from roboteam.runtime.world.store import RuntimeStore
from roboteam.tasks.config import ROOT, load_run_settings, load_task, startup_protocol
from team_settings import prepare_run


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_prepare_is_offline_and_copies_task_roles_skill_and_source(self):
        run = prepare_run(self.root / 'run')
        self.assertEqual(verify_inputs(run), [])
        self.assertEqual(json.loads((run / 'public/inputs/task.json').read_text())['id'], load_task()['id'])
        # New runs show letter labels where their videos do.
        self.assertEqual(
            json.loads((run / 'private/inputs/run.json').read_text())['robot_labels'], 'beside-robot-v1'
        )
        store = RuntimeStore(run / 'private/state/runtime.sqlite')
        try:
            self.assertEqual(store.get('lifecycle'), 'prepared')
            self.assertEqual(store.agent('Meta')['kind'], 'manager')
            self.assertEqual(store.agent('Controller')['kind'], 'team-controller')
            self.assertTrue(all(v['thread_id'] is None for v in store.agents().values()))
            self.assertEqual(store.actions(), {})
        finally:
            store.close()
        self.assertIsNone(json.loads((run / 'private/state/connections/A.json').read_text())['url'])
        self.assertTrue((run / 'public/inputs/guide/tools.md').exists())
        # One shared lessons file in the only writable folder, frozen first
        # messages and access table, and Meta's files kept private.
        self.assertEqual(json.loads((run / 'private/inputs/manifest.json').read_text())['layout'], 'run-v6')
        self.assertTrue((run / 'workspace/skills.md').read_text().startswith('# Run skills'))
        self.assertTrue((run / 'public/inputs/rules.md').is_file())
        self.assertFalse((run / 'public/inputs/role_tools.js').exists())
        self.assertFalse((run / 'public/inputs/roles/Meta.md').exists())
        self.assertTrue((run / 'private/inputs/meta/Meta.md').is_file())
        for name in ('system.md', 'A.md', 'Controller.md', 'resume.md', 'model-restart.md'):
            self.assertTrue((run / 'private/inputs/bootstrap' / name).is_file(), name)
        access = json.loads((run / 'private/inputs/policy-access.json').read_text())
        self.assertEqual(access['filesystem'][str(run.resolve() / 'workspace')], 'write')
        self.assertEqual(access['filesystem'][str(run.resolve() / 'private')], 'deny')
        self.assertFalse(access['network'])
        self.assertFalse(access['web_search'])
        self.assertTrue((run / 'private/inputs/frozen-source/roboteam/runtime/tools/scheduling.py').exists())
        self.assertFalse((run / 'private/outputs/global-realtime.mp4').exists())
        before = (run / 'private/inputs/manifest.json').read_bytes()
        with self.assertRaises(ValueError):
            prepare_run(run)
        self.assertEqual((run / 'private/inputs/manifest.json').read_bytes(), before)

    def test_snapshot_tamper_is_reported(self):
        run = prepare_run(self.root / 'run')
        p = run / 'public/inputs/task.json'
        p.write_text('{}')
        self.assertIn('input:public/inputs/task.json', verify_inputs(run))

    def test_private_scene_or_harness_tamper_is_also_detected(self):
        run = prepare_run(self.root / 'run')
        p = run / 'private/inputs/task.json'
        v = json.loads(p.read_text())
        v['level'] = 3
        p.write_text(json.dumps(v))
        self.assertIn('private:task.json', verify_inputs(run))

    def test_invalid_task_rejected_before_directory_creation(self):
        task = load_task()
        task['scene_sha256'] = '0' * 64
        p = self.root / 'bad.json'
        p.write_text(json.dumps(task))
        with self.assertRaises(ValueError):
            prepare_run(self.root / 'run', p)
        self.assertFalse((self.root / 'run').exists())

    def test_frozen_source_is_checked_and_observations_are_not_fixed_inputs(self):
        run = prepare_run(self.root / 'run')
        (run / 'public/observations/new.png').write_bytes(b'not real pixels')
        self.assertEqual(verify_inputs(run), [])
        (run / 'private/inputs/frozen-source/roboteam/runtime/tools/scheduling.py').write_text('# changed')
        self.assertIn('frozen:roboteam/runtime/tools/scheduling.py', verify_inputs(run))

    def test_run_local_experience_is_mutable_and_not_imported_into_next_run(self):
        run = prepare_run(self.root / 'first')
        experience = run / 'public/results/A-experience.md'
        experience.write_text('Observed trial result; applicable only to the tested conditions.\n')
        store = RuntimeStore(run / 'private/state/runtime.sqlite')
        try:
            store.checkpoint_work('A', 'working', 'Experience reference: ' + str(experience))
        finally:
            store.close()
        experience.write_text('Updated after contrary observation; previous inference uncertain.\n')
        self.assertEqual(verify_inputs(run), [])
        fresh = prepare_run(self.root / 'second')
        self.assertEqual(list((fresh / 'public/results').iterdir()), [])
        store = RuntimeStore(fresh / 'private/state/runtime.sqlite')
        try:
            self.assertEqual(store.agent('A')['note'], '')
        finally:
            store.close()
        self.assertEqual(verify_inputs(fresh), [])

    def test_a_folder_not_prepared_by_this_code_is_refused_and_left_alone(self):
        from fake_pipeline import FakeWorld, fake_capture
        from roboteam.runtime.world.service import RuntimeService

        run = self.root / 'foreign'
        (run / 'private').mkdir(parents=True)
        old = run / 'private/manifest.json'
        old.write_text('{"schema_version":2}')
        before = old.read_bytes()
        with self.assertRaises(ValueError):
            RuntimeService(run, FakeWorld, fake_capture)
        self.assertEqual(old.read_bytes(), before)
        self.assertFalse((run / 'private/state').exists())

    def test_eight_workers_prepare_with_same_skill_in_both_systems(self):
        p = ROOT / 'benchmark/transport/transport-medium-l1/task.json'
        # The template marks the passages that depend on the tools and on what a role observes
        # with; a full images run gets those wordings.
        from roboteam.runtime.tools import observation_mode
        from roboteam.runtime.tools.tools_mode import render

        skill = observation_mode.render(
            render(
                (Path(__file__).resolve().parents[3] / 'prompts/guides/collaboration/guide.md').read_text(),
                'full',
            ),
            'images',
        ).encode()
        for system in ('hierarchical', 'decentralized'):
            cfg = load_run_settings()
            cfg['system'] = system
            cfg['startup_protocol'] = startup_protocol(system)
            c = self.root / (system + '.json')
            c.write_text(json.dumps(cfg))
            run = prepare_run(self.root / system, p, c)
            roles = json.loads((run / 'public/inputs/roles.json').read_text())['roles']
            self.assertEqual(sum(v['kind'] == 'worker' for v in roles.values()), 8)
            self.assertEqual('Controller' in roles, system == 'hierarchical')
            self.assertEqual((run / 'public/inputs/guide/guide.md').read_bytes(), skill)
            self.assertEqual(verify_inputs(run), [])

    def test_hierarchical_lead_is_the_controller(self):
        cfg = load_run_settings()
        cfg['system'] = 'hierarchical'
        cfg['startup_protocol'] = startup_protocol('hierarchical')
        config = self.root / 'hierarchical.json'
        config.write_text(json.dumps(cfg))
        run = prepare_run(self.root / 'run-hierarchical', run_settings_path=config)
        roles = json.loads((run / 'public/inputs/roles.json').read_text())
        self.assertEqual(roles['roles']['Controller']['kind'], 'team-controller')
        self.assertTrue((run / 'public/inputs/roles/Controller.md').exists())
        self.assertEqual(verify_inputs(run), [])


if __name__ == '__main__':
    unittest.main()
