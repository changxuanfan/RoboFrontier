import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robofrontier.cli import _frozen_configuration, plan, prepare, preflight
from robofrontier.configuration import load_configuration, rendering_environment
from robofrontier.runtime.setup import verify_inputs



# These tests prepare batches without the engine CLIs installed; the pinned version check
# itself is tested in runtime.test_versions.
def setUpModule():
    from unittest.mock import patch
    from robofrontier.runtime import versions
    global _versions
    _versions = patch.object(versions, 'engine_version', side_effect=lambda engine, run=None: versions.ENGINES[engine])
    _versions.start()


def tearDownModule():
    _versions.stop()


class UnifiedConfigurationTests(unittest.TestCase):
    def test_claude_engine_defaults_to_setup_token_without_replacing_explicit_profiles(self):
        from robofrontier.batch.claude_prepare import profile
        config = load_configuration(overrides={'policy': {'engine': 'claude'}})
        self.assertEqual(config['policy']['profile'], 'haiku_subscription_token')
        self.assertEqual(plan(config)['model'], 'claude-haiku-5-5')
        selected = profile(config['policy']['profile'])
        self.assertEqual((selected['auth_mode'], selected['env_key']),
                         ('oauth_token', 'CLAUDE_CODE_OAUTH_TOKEN'))
        for name in ('haiku', 'haiku_subscription', 'haiku_subscription_directory'):
            with self.subTest(profile=name):
                explicit = load_configuration(overrides={'policy': {'engine': 'claude', 'profile': name}})
                self.assertEqual(explicit['policy']['profile'], name)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'claude.toml'
            path.write_text('[policy]\nengine="claude"\n')
            self.assertEqual(load_configuration(path)['policy']['profile'], 'haiku_subscription_token')
            path.write_text('[policy]\nengine="claude"\nprofile="haiku"\n')
            self.assertEqual(load_configuration(path)['policy']['profile'], 'haiku')

    def test_default_plan_is_offline_and_selects_all_released_tasks(self):
        result = plan(load_configuration())
        self.assertEqual((result['task_count'], result['parallel']), (36, 36))
        self.assertEqual((result['model'], result['effort'], result['topology']),
                         ('gpt-6-luna', 'high', 'adaptive'))
        self.assertEqual((result['startup_interval_s'], result['task_wall_limit_s']), (.3, 86400))
        self.assertEqual(result['model_calls'], 0)
        self.assertFalse(result['simulator_started'])

    def test_partial_toml_and_explicit_options_override_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'custom.toml'
            path.write_text('[batch]\nparallel=8\n[selection]\nlevel=1\nmin_arms=true\n')
            config = load_configuration(path, {'batch': {'parallel': 4}})
            self.assertEqual(config['batch']['parallel'], 4)
            self.assertEqual(plan(config)['task_count'], 4)
            self.assertEqual(config['render']['device'], 'nvidia')

    def test_old_operator_toml_uses_its_own_defaults_shape(self):
        for version in (1,2,3):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as temporary:
                path=Path(temporary)/'old.toml'
                path.write_text(f'schema_version={version}\n[batch]\nparallel=2\n')
                config=load_configuration(path)
                self.assertEqual(config['schema_version'],version)
                self.assertEqual(config['batch']['parallel'],2)
                self.assertEqual('factory' in config,version>=2)
                self.assertEqual('oracle' in config,version>=3)
                if version==3:self.assertNotIn('evaluation_mode',config['oracle'])
                with self.assertRaises(ValueError):
                    load_configuration(path,{'oracle':{'evaluation_mode':'task-reference'}})

    def test_invalid_options_fail_before_installation_or_launch(self):
        cases = [{'batch': {'paralell': 3}}, {'batch': {'parallel': True}},
                 {'batch': {'startup_interval_s': float('nan')}},
                 {'batch': {'startup_interval_s': -.1}}, {'batch': {'task_wall_limit_s': 0}},
                 {'policy': {'topology': 'adpative'}}, {'policy': {'profile': '../secret'}},
                 {'selection': {'families': ['dial', 'dial']}},
                 {'evidence': {'delete_sources': True}},
                 {'evidence': {'auto_collect': False, 'auto_archive': True}}]
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                load_configuration(overrides=overrides)

    def test_preflight_without_spend_confirmation_never_calls_a_provider(self):
        from unittest.mock import patch
        with patch('subprocess.run') as launch:
            report=preflight(load_configuration())
            self.assertEqual(report['status'],'not_run')
            self.assertEqual(report['model_calls'],0)
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
        config = load_configuration(overrides={'render': {'device': 'native'},
            'selection': {'cases': ['transport-a04-d1']}, 'batch': {'parallel': 1}})
        with tempfile.TemporaryDirectory() as temporary:
            batch = Path(temporary)/'batch'
            prepare(batch, config)
            self.assertEqual(_frozen_configuration(batch), config)
            document = json.loads((batch/'batch.json').read_text())
            run = Path(document['jobs'][0]['run_directory'])
            self.assertEqual(verify_inputs(run), [])
            harness = json.loads((run/'private/inputs/harness.json').read_text())
            self.assertEqual(harness['startup_timeout_s'], 600)
            self.assertEqual(harness['startup_protocol'], 'direct_controller_v2')
            document['execution']['startup_interval_s'] = 0
            (batch/'batch.json').write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'frozen configuration'):
                _frozen_configuration(batch)

    def test_standing_team_batches_freeze_direct_team_start(self):
        for topology in ('controller-worker', 'worker-worker'):
            with self.subTest(topology=topology), tempfile.TemporaryDirectory() as temporary:
                config = load_configuration(overrides={'policy': {'topology': topology},
                    'selection': {'cases': ['transport-a04-d1']}, 'batch': {'parallel': 1}})
                batch = Path(temporary)/'batch'
                prepare(batch, config)
                job = json.loads((batch/'batch.json').read_text())['jobs'][0]
                run = Path(job['run_directory'])
                harness = json.loads((run/'private/inputs/harness.json').read_text())
                self.assertEqual(harness['startup_protocol'], 'direct_team_v3')
                roles = json.loads((run/'public/inputs/roles.json').read_text())['roles']
                self.assertEqual(set(roles), {'Meta', 'Controller', 'A', 'B', 'C', 'D'} if topology == 'controller-worker' else {'Meta', 'A', 'B', 'C', 'D'})
                self.assertEqual(verify_inputs(run), [])

    def test_claude_standing_prepare_freezes_role_prompts_and_direct_start(self):
        for topology in ('controller-worker', 'worker-worker'):
            with self.subTest(topology=topology), tempfile.TemporaryDirectory() as tmp:
                config = load_configuration(overrides={
                    'policy': {'engine':'claude','profile':'haiku','topology':topology},
                    'render': {'device':'native'}, 'selection': {'cases':['transport-a04-d1']}})
                batch = Path(tmp)/'batch'
                # Preparing only; no key is used (claude_prepare.exposed_api_keys).
                with patch('robofrontier.batch.claude_prepare.exposed_api_keys', return_value=[]):
                    prepare(batch, config)
                data = json.loads((batch/'batch.json').read_text())
                self.assertEqual(data['status'], 'prepared_not_started')
                self.assertEqual(data['model_calls'], 0)
                run = Path(data['jobs'][0]['run_directory'])
                harness = json.loads((run/'private/inputs/harness.json').read_text())
                self.assertEqual(harness['startup_protocol'], 'direct_team_v3')
                roles = json.loads((run/'public/inputs/roles.json').read_text())['roles']
                self.assertEqual(set(roles), {'Meta','A','B','C','D'} |
                    ({'Controller'} if topology == 'controller-worker' else set()))
                for actor, value in roles.items():
                    if value['kind'] == 'manager': continue
                    # Each role's frozen first message, shared with the Codex route.
                    self.assertTrue((run/'private/inputs/bootstrap'/f'{actor}.md').is_file())
                self.assertEqual(verify_inputs(run), [])
                self.assertEqual(_frozen_configuration(batch), config)



if __name__ == '__main__':
    unittest.main()
