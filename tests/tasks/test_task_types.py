import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roboteam.runtime.run.setup import verify_inputs
from roboteam.tasks.task_types import (
    RELEASE,
    ROOT,
    policy_task,
    prepare,
    read,
    resolve_case,
    validate_frozen_policy,
    validate_policy_task,
)


class TaskTypeReleaseTests(unittest.TestCase):
    def test_asset_audit_detects_missing_changed_and_unsafe_paths(self):
        import hashlib

        from roboteam.launch.tasks import check_case_assets

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scene = root / 'scene'
            (scene / 'assets').mkdir(parents=True)
            file = scene / 'assets/a'
            file.write_bytes(b'original')
            digest = hashlib.sha256(b'original').hexdigest()
            manifest = scene / 'workstation.json'

            def save(path):
                manifest.write_text(json.dumps({'assets': [{'path': path, 'sha256': digest}]}))

            case = {'id': 'test', 'directory': 'scene'}
            save('assets/a')
            self.assertEqual(check_case_assets(case, root)['changed'], [])
            file.write_bytes(b'altered')
            self.assertEqual(len(check_case_assets(case, root)['changed']), 1)
            file.unlink()
            self.assertEqual(len(check_case_assets(case, root)['missing']), 1)
            save('../outside')
            with self.assertRaisesRegex(ValueError, 'Invalid asset path'):
                check_case_assets(case, root)

    def test_the_release_has_36_exact_sources(self):
        release = read(ROOT / RELEASE)
        rows = [c for f in release['families'].values() for c in f['policy']]
        self.assertEqual(len(rows), 36)
        self.assertEqual(len({c['id'] for c in rows}), 36)
        for c in rows:
            resolve_case(c['id'])
        mosaic = release['families']['mosaic']
        self.assertEqual(
            read(ROOT / mosaic['policy'][0]['directory'] / 'task.json')['scale']['scene_revision'], 15
        )

    def test_prepared_task_is_not_an_inherited_oracle_pass_and_detects_edits(self):
        task = policy_task('transport-a04-d1')
        validate_policy_task(task)
        self.assertFalse(task['oracle_verified'])
        self.assertEqual(task['run_protocol']['total_wall_limit_s'], 86400)
        task['completion']['stable_duration_sim_s'] = 0
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            validate_policy_task(task)

    def test_each_task_type_freezes_guidance_public_facts_and_private_release(self):
        cases = ['transport-a04-d1', 'mosaic-a04-6x12-d1', 'relay-a08-d1', 'dial-best5-n04-d1']
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch('mujoco.mj_step', side_effect=AssertionError('No physics')),
        ):
            for case in cases:
                run = prepare(case, Path(tmp) / case)
                self.assertEqual(verify_inputs(run), [])
                public = read(run / 'public/inputs/task.json')
                task = read(run / 'private/inputs/task.json')
                validate_frozen_policy(task, run)
                task['run_protocol']['experience'] = 'reuse_oracle'
                with self.assertRaisesRegex(ValueError, 'protocol differs'):
                    validate_frozen_policy(task, run)
                task = read(run / 'private/inputs/task.json')
                self.assertIn('completion', public)
                self.assertIn('workspace_world_m', public)
                _, _, spec = resolve_case(case)
                # A run receives the case's released public task with only its own protocol and
                # image profile added, and every listed task material plus the task guide.
                released = read(ROOT / spec['public_projection']['path'])
                self.assertEqual(
                    {k: v for k, v in public.items() if k not in ('run_protocol', 'observation_image')},
                    released,
                )
                for name in spec['public_files']:
                    self.assertTrue((run / 'public/inputs/family' / name).is_file(), name)
                self.assertTrue((run / 'public/inputs' / public['task_skill']).is_file())
                self.assertNotIn('family_guidance', public)
                if case.startswith('relay-'):
                    self.assertTrue(public['completion']['required_airborne_handover'])
                    self.assertNotIn('relay_completion_rule', public['completion'])
                    self.assertTrue(any('picks it up, none of that timber' in r for r in public['rules']))
                    self.assertFalse(any('never counts as transport' in r for r in public['rules']))
                    self.assertNotIn('rule_revision', public['completion'])
                if case.startswith('transport-'):
                    self.assertFalse(public['completion']['acceptance']['process_compliance_required'])
                if case.startswith('mosaic-'):
                    self.assertFalse(public['completion']['process_violations_clear_required'])
                    self.assertEqual(public['target']['reference_image'], 'family/target-pattern.png')
                if case.startswith('dial-'):
                    self.assertIn('latched', public['completion']['success_semantics'])
                rules = (run / 'public/inputs/rules.md').read_text()
                self.assertIn('`ready` is optional', rules)
                self.assertIn('chooses direct control or bounded delegation', rules)
                # The frozen scene is an independent file (a clone where supported), never a
                # hard link: a write to one run must not reach the source or other runs.
                self.assertEqual((run / 'private/inputs/scene/task.json').stat().st_nlink, 1)
                self.assertFalse(
                    any(
                        p.name in ('private-code.json', 'actions.json', 'process.jsonl')
                        for p in (run / 'public').rglob('*')
                    )
                )
                material = run / 'public/inputs' / public['task_skill']
                material.write_text('changed')
                self.assertIn('input:' + str(material.relative_to(run)), verify_inputs(run))
                scene = run / 'private/inputs/scene/task.json'
                scene.write_text('{}')
                with self.assertRaisesRegex(ValueError, 'scene metadata'):
                    validate_frozen_policy(task, run)

    def test_each_task_type_starts_frozen_evaluator_and_recording_without_steps(self):
        from roboteam.runtime.world.pipeline import World

        cases = ['transport-a04-d1', 'mosaic-a04-6x12-d1', 'relay-a08-d1', 'dial-best5-n04-d1']
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch('mujoco.mj_step', side_effect=AssertionError('No physics')),
        ):
            for case in cases:
                with self.subTest(case=case):
                    run = prepare(case, Path(tmp) / case)
                    world = World(run, read(run / 'private/inputs/task.json'))
                    try:
                        world.start_trial()
                        self.assertIsNotNone(world.suite_sampler)
                        self.assertEqual(world.motion_recorder.meta['sample_hz'], 30)
                        self.assertEqual(world.time, 0.0)
                    finally:
                        world.close()

    def test_policy_harness_records_motion_at_its_frozen_rate(self):
        from roboteam.runtime.world.pipeline import World
        from roboteam.tasks.config import load_run_settings

        self.assertEqual(read(ROOT / 'roboteam/runtime/run/defaults.json')['motion_hz'], 30)
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch('mujoco.mj_step', side_effect=AssertionError('No physics')),
        ):
            run = prepare(
                'mosaic-a04-6x12-d1',
                Path(tmp) / 'run',
                run_settings=ROOT / 'roboteam/runtime/run/defaults.json',
            )
            self.assertEqual(read(run / 'private/inputs/run.json')['motion_hz'], 30)
            world = World(run, read(run / 'private/inputs/task.json'))
            try:
                world.start_trial()
                self.assertEqual(world.motion_recorder.meta['sample_hz'], 30)
                self.assertEqual(world.suite_sampler.log_format, 'events-10s')
                header = json.loads((run / 'private/outputs/suite-process.jsonl').read_text().splitlines()[0])
                self.assertEqual(
                    (header['schema'], header['snapshot_interval_s']), ('roboteam.suite-process.v2', 10.0)
                )
            finally:
                world.close()
            # Run settings without motion_hz and process_log record at 60 Hz with full logs.
            plain_cfg = {
                k: v
                for k, v in read(ROOT / 'roboteam/runtime/run/defaults.json').items()
                if k not in ('motion_hz', 'process_log')
            }
            plain_path = Path(tmp) / 'plain.json'
            plain_path.write_text(json.dumps(plain_cfg))
            plain = prepare('mosaic-a04-6x12-d1', Path(tmp) / 'plain', run_settings=plain_path)
            world = World(plain, read(plain / 'private/inputs/task.json'))
            try:
                world.start_trial()
                self.assertEqual(world.motion_recorder.meta['sample_hz'], 60)
                self.assertEqual(world.suite_sampler.log_format, 'full')
            finally:
                world.close()
            bad = Path(tmp) / 'bad.json'
            for value in (0, -30, True, float('nan')):
                bad.write_text(
                    json.dumps({**read(ROOT / 'roboteam/runtime/run/defaults.json'), 'motion_hz': value})
                )
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'motion sampling'):
                    load_run_settings(bad)
            for value in ('every-step', 'events-5s', 'events-10'):
                bad.write_text(
                    json.dumps({**read(ROOT / 'roboteam/runtime/run/defaults.json'), 'process_log': value})
                )
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'process log format'):
                    load_run_settings(bad)
            # Every Monitor format, and only those, is accepted (task_config keeps the list literal).
            from roboteam.tasks.evaluate import PROCESS_LOG_FORMATS

            self.assertEqual(sorted(PROCESS_LOG_FORMATS), ['events-10s', 'events-1s', 'events-60s', 'full'])
            for value in PROCESS_LOG_FORMATS:
                bad.write_text(
                    json.dumps({**read(ROOT / 'roboteam/runtime/run/defaults.json'), 'process_log': value})
                )
                with self.subTest(value=value):
                    self.assertEqual(load_run_settings(bad)['process_log'], value)


class ReleaseRecordTests(unittest.TestCase):
    def test_the_release_pins_no_harness_and_the_asset_pin_follows_it(self):
        # Each run freezes its own run.json and run_settings_sha256; the release's own
        # harness pin could go stale with nothing enforcing it.
        from roboteam.tasks.task_types import sha

        self.assertNotIn('harness', sorted(read(ROOT / RELEASE)))
        assets = read(ROOT / 'benchmark/assets.json')
        self.assertEqual(assets['release_sha256'], sha(ROOT / RELEASE))
        # The archive may come from an earlier revision that changed task files only; restoring
        # checks every scene and Panda file against this release's hashes (handoff.restore_assets).
        self.assertTrue(assets['archive_release_sha256'])


class FrozenReleaseTests(unittest.TestCase):
    def test_the_release_is_frozen_with_its_own_id(self):
        # build_release.index_release recomputes release_id from every case file and refuses a
        # change once frozen; here the record and the files must agree.
        from scripts.release import build_release

        release = read(ROOT / RELEASE)
        self.assertTrue(release['frozen'])
        self.assertEqual(release['frozen']['release_id'], release['release_id'])
        self.assertTrue(
            (ROOT / 'runs/engineering/validate-physics' / release['frozen']['physics_validation']).name
        )
        with self.assertRaises(SystemExit):
            build_release.require_unfrozen()


if __name__ == '__main__':
    unittest.main()
