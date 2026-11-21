import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roboteam.cli import _frozen_configuration, plan, preflight, prepare
from roboteam.configuration import load_configuration, rendering_environment
from roboteam.runtime.run.setup import verify_inputs


# These tests prepare batches without the harness CLIs installed; the pinned version check
# itself is tested in runtime.run.test_versions.
def setUpModule():
    from unittest.mock import patch

    from roboteam.runtime.run import versions

    global _versions
    _versions = patch.object(
        versions, 'harness_version', side_effect=lambda harness, run=None: versions.HARNESSES[harness]
    )
    _versions.start()


def tearDownModule():
    _versions.stop()


class UnifiedConfigurationTests(unittest.TestCase):
    def test_each_harness_defaults_to_its_api_key_model_entry_without_replacing_explicit_model_entries(self):
        from roboteam.harness.codex.launch import model_entry as codex_model_entry
        from roboteam.launch.claude_prepare import model_entry

        config = load_configuration(overrides={'policy': {'harness': 'claude'}})
        self.assertEqual(config['policy']['model'], 'opus')
        self.assertEqual(plan(config)['model'], 'claude-opus-5-5')
        selected = model_entry(config['policy']['model'])
        self.assertEqual(
            (selected.get('auth_mode', 'api_key'), selected['env_key']), ('api_key', 'ANTHROPIC_API_KEY')
        )
        self.assertEqual(load_configuration()['policy']['model'], 'sol')
        self.assertEqual(
            load_configuration(overrides={'policy': {'harness': 'codex'}})['policy']['model'], 'sol'
        )
        selected = codex_model_entry('sol')
        self.assertEqual(
            (selected['model'], selected['provider'], selected['env_key']),
            ('gpt-6.1-sol', 'openai_api', 'OPENAI_API_KEY'),
        )
        for name in ('haiku', 'opus_subscription', 'haiku_subscription', 'haiku_subscription_directory'):
            with self.subTest(model_entry=name):
                explicit = load_configuration(overrides={'policy': {'harness': 'claude', 'model': name}})
                self.assertEqual(explicit['policy']['model'], name)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'claude.toml'
            path.write_text('[policy]\nharness="claude"\n')
            self.assertEqual(load_configuration(path)['policy']['model'], 'opus')
            path.write_text('[policy]\nharness="claude"\nmodel="haiku"\n')
            self.assertEqual(load_configuration(path)['policy']['model'], 'haiku')

    def test_default_plan_is_offline_and_selects_all_released_tasks(self):
        result = plan(load_configuration())
        self.assertEqual((result['task_count'], result['parallel']), (36, 36))
        self.assertEqual(
            (result['model'], result['effort'], result['system']), ('gpt-6.1-sol', 'high', 'adaptive')
        )
        self.assertEqual((result['startup_interval_s'], result['task_wall_limit_s']), (0.3, 86400))
        self.assertEqual(result['model_calls'], 0)
        self.assertFalse(result['simulator_started'])

    def test_partial_toml_and_explicit_options_override_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'custom.toml'
            path.write_text('[batch]\nparallel=8\n[selection]\nlevel=1\nmin_arms=true\n')
            config = load_configuration(path, {'batch': {'parallel': 4}})
            self.assertEqual(config['batch']['parallel'], 4)
            self.assertEqual(plan(config)['task_count'], 4)
            # The default `auto` is resolved for this host before anything is frozen.
            from roboteam.configuration import detected_render_device

            self.assertEqual(config['render']['device'], detected_render_device())

    def test_every_option_sets_its_one_setting(self):
        import contextlib
        import io

        from roboteam.cli import main

        out = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict('os.environ', {}, clear=False),
            contextlib.redirect_stdout(out),
        ):
            code = main(
                ['--runs-root', temporary, 'config', '--wall-limit', '1800', '--record-video']
                + [
                    '--observation-profile',
                    'jpeg_128x80_q95',
                    '--parallel',
                    '2',
                    '--cases',
                    'transport-small-l1',
                ]
            )
            root = str(Path(temporary).resolve())
        config = json.loads(out.getvalue())
        self.assertFalse(code)
        self.assertEqual(config['batch']['task_wall_limit_s'], 1800)
        self.assertEqual(config['batch']['parallel'], 2)
        self.assertEqual(config['render']['observation_profile'], 'jpeg_128x80_q95')
        self.assertIs(config['render']['record_realtime_video'], True)
        self.assertEqual(config['selection']['cases'], ['transport-small-l1'])
        self.assertEqual(config['paths']['runs_root'], root)

    def test_a_time_limit_over_24_hours_is_refused_for_both_harnesses(self):
        for harness in ('codex', 'claude'):
            with self.assertRaisesRegex(ValueError, 'at most 86400'):
                load_configuration(
                    None, {'policy': {'harness': harness}, 'batch': {'task_wall_limit_s': 90000.0}}
                )

    def test_auto_rendering_follows_the_host(self):
        from roboteam.configuration import detected_render_device

        self.assertEqual(detected_render_device('Darwin'), 'native')
        with patch('pathlib.Path.exists', return_value=False), patch('shutil.which', return_value=None):
            self.assertEqual(detected_render_device('Linux'), 'cpu')
        with patch('shutil.which', return_value='/usr/bin/nvidia-smi'):
            self.assertEqual(detected_render_device('Linux'), 'nvidia')

    def test_only_the_current_schema_version_is_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'site.toml'
            path.write_text('[batch]\nparallel=2\n')
            self.assertEqual(load_configuration(path)['batch']['parallel'], 2)
            for version in (1, 10, 12):
                path.write_text(f'schema_version={version}\n[batch]\nparallel=2\n')
                with self.assertRaisesRegex(ValueError, 'schema_version'):
                    load_configuration(path)
            with self.assertRaises(ValueError):
                load_configuration(overrides={'oracle': {'evaluation_mode': 'task-reference'}})

    def test_invalid_options_fail_before_installation_or_launch(self):
        cases = [
            {'batch': {'paralell': 3}},
            {'batch': {'parallel': True}},
            {'batch': {'startup_interval_s': float('nan')}},
            {'batch': {'startup_interval_s': -0.1}},
            {'batch': {'task_wall_limit_s': 0}},
            {'policy': {'system': 'adpative'}},
            {'policy': {'model': '../secret'}},
            {'selection': {'task_types': ['dial', 'dial']}},
            {'evidence': {'delete_sources': True}},
            {'evidence': {'auto_collect': False, 'auto_archive': True}},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                load_configuration(overrides=overrides)

    def test_preflight_without_spend_confirmation_never_calls_a_provider(self):
        from unittest.mock import patch

        with patch('subprocess.run') as launch:
            report = preflight(load_configuration())
            self.assertEqual(report['status'], 'not_run')
            self.assertEqual(report['model_calls'], 0)
            launch.assert_not_called()

    def test_renderer_selection_never_silently_falls_back(self):
        cpu = rendering_environment('cpu', 'Linux', {'CUDA_VISIBLE_DEVICES': '2', 'SECRET': 'retained'})
        self.assertEqual(cpu['MUJOCO_GL'], 'osmesa')
        self.assertEqual(cpu['CUDA_VISIBLE_DEVICES'], '')
        gpu = rendering_environment('nvidia', 'Linux', cpu)
        self.assertEqual(gpu['MUJOCO_GL'], 'egl')
        self.assertNotIn('GALLIUM_DRIVER', gpu)
        native = rendering_environment('native', 'Darwin', cpu)
        self.assertNotIn('MUJOCO_GL', native)
        with self.assertRaisesRegex(ValueError, 'requires Linux'):
            rendering_environment('nvidia', 'Darwin', {})
        with self.assertRaisesRegex(ValueError, 'requires macOS'):
            rendering_environment('native', 'Linux', {})

    def test_prepare_freezes_effective_settings_and_rejects_later_edits(self):
        config = load_configuration(
            overrides={
                'render': {'device': 'native'},
                'selection': {'cases': ['transport-small-l1']},
                'batch': {'parallel': 1},
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            batch = Path(temporary) / 'batch'
            prepare(batch, config)
            self.assertEqual(_frozen_configuration(batch), config)
            document = json.loads((batch / 'batch.json').read_text())
            run = Path(document['jobs'][0]['run_directory'])
            self.assertEqual(verify_inputs(run), [])
            run_settings = json.loads((run / 'private/inputs/run.json').read_text())
            self.assertEqual(run_settings['startup_timeout_s'], 600)
            self.assertEqual(run_settings['startup_protocol'], 'direct_controller')
            document['execution']['startup_interval_s'] = 0
            (batch / 'batch.json').write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'frozen configuration'):
                _frozen_configuration(batch)

    def test_standing_team_batches_freeze_direct_team_start(self):
        for system in ('hierarchical', 'decentralized'):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                config = load_configuration(
                    overrides={
                        'policy': {'system': system},
                        'selection': {'cases': ['transport-small-l1']},
                        'batch': {'parallel': 1},
                    }
                )
                batch = Path(temporary) / 'batch'
                prepare(batch, config)
                job = json.loads((batch / 'batch.json').read_text())['jobs'][0]
                run = Path(job['run_directory'])
                run_settings = json.loads((run / 'private/inputs/run.json').read_text())
                self.assertEqual(run_settings['startup_protocol'], 'direct_team')
                roles = json.loads((run / 'public/inputs/roles.json').read_text())['roles']
                self.assertEqual(
                    set(roles),
                    {'Meta', 'Controller', 'A', 'B', 'C', 'D'}
                    if system == 'hierarchical'
                    else {'Meta', 'A', 'B', 'C', 'D'},
                )
                self.assertEqual(verify_inputs(run), [])

    def test_claude_standing_prepare_freezes_role_prompts_and_direct_start(self):
        for system in ('hierarchical', 'decentralized'):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as tmp:
                config = load_configuration(
                    overrides={
                        'policy': {'harness': 'claude', 'model': 'haiku', 'system': system},
                        'render': {'device': 'native'},
                        'selection': {'cases': ['transport-small-l1']},
                    }
                )
                batch = Path(tmp) / 'batch'
                # Preparing only; no key is used (claude_prepare.exposed_api_keys).
                with patch('roboteam.launch.claude_prepare.exposed_api_keys', return_value=[]):
                    prepare(batch, config)
                data = json.loads((batch / 'batch.json').read_text())
                self.assertEqual(data['status'], 'prepared_not_started')
                self.assertEqual(data['model_calls'], 0)
                run = Path(data['jobs'][0]['run_directory'])
                run_settings = json.loads((run / 'private/inputs/run.json').read_text())
                self.assertEqual(run_settings['startup_protocol'], 'direct_team')
                roles = json.loads((run / 'public/inputs/roles.json').read_text())['roles']
                self.assertEqual(
                    set(roles),
                    {'Meta', 'A', 'B', 'C', 'D'} | ({'Controller'} if system == 'hierarchical' else set()),
                )
                for actor, value in roles.items():
                    if value['kind'] == 'manager':
                        continue
                    # Each role's frozen first message, shared with the Codex route.
                    self.assertTrue((run / 'private/inputs/bootstrap' / f'{actor}.md').is_file())
                self.assertEqual(verify_inputs(run), [])
                self.assertEqual(_frozen_configuration(batch), config)


if __name__ == '__main__':
    unittest.main()
