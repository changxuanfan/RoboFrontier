import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from robofrontier.batch import container as runtime
from robofrontier.configuration import load_configuration


class ContainerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = load_configuration(overrides={'render': {'device': 'cpu'}})

    def test_nested_build_help_never_contacts_docker(self):
        from robofrontier.cli import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(runtime.subprocess, 'run',
                side_effect=AssertionError('help attempted Docker execution')):
            with self.assertRaises(SystemExit) as raised:
                main(['container', 'build', '--help'])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn('usage:', output.getvalue())
        self.assertIn('build', output.getvalue())

    def test_nested_help_is_available_without_configuration_or_docker(self):
        from robofrontier.cli import main
        for arguments in (['build', '-h'], ['plan', '--help'], ['prepare', '--help'],
                          ['preflight', '--help'], ['run', '--help'],
                          ['auth', '--help'], ['auth', 'codex', 'login', '--help']):
            with self.subTest(arguments=arguments), contextlib.redirect_stdout(io.StringIO()), \
                    patch('robofrontier.cli.load_configuration', side_effect=AssertionError('read config')), \
                    patch.object(runtime.subprocess, 'run', side_effect=AssertionError('contacted Docker')):
                with self.assertRaises(SystemExit) as raised:
                    main(['--config', str(self.root/'missing.toml'), 'container', *arguments])
                self.assertEqual(raised.exception.code, 0)

    def test_invalid_nested_syntax_fails_before_configuration_or_docker(self):
        from robofrontier.cli import main
        for arguments in (['build', '--mistyped'], ['build', 'unexpected'],
                          ['prepare', '--outpt', 'runs/new'], ['run'], ['auth', 'shell']):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()), \
                    patch('robofrontier.cli.load_configuration', side_effect=AssertionError('read config')), \
                    patch.object(runtime.subprocess, 'run', side_effect=AssertionError('contacted Docker')):
                with self.assertRaises(SystemExit) as raised:
                    main(['container', *arguments])
                self.assertEqual(raised.exception.code, 2)

    def test_direct_wrapper_help_and_invalid_build_skip_docker(self):
        for arguments, code in ((['build', '--help'], 0), (['prepare', '--help'], 0),
                                (['build', '--mistyped'], 2)):
            with self.subTest(arguments=arguments), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(runtime.subprocess, 'run', side_effect=AssertionError('contacted Docker')):
                with self.assertRaises(SystemExit) as raised:
                    runtime.execute(arguments, self.config, root=self.root)
                self.assertEqual(raised.exception.code, code)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_public_configuration_roundtrips_without_environment_expansion(self):
        self.assertEqual(tomllib.loads(runtime._toml(self.config)), self.config)

    def command(self, arguments, config=None, credentials=None):
        return runtime._command(arguments, config or self.config, 'image', {'runs': 'runs', 'state': 'state'},
                                'container', self.root/'settings.toml', credentials or {})

    def test_commands_use_named_volumes_and_never_put_api_values_in_arguments(self):
        with patch.object(runtime.platform, 'system', return_value='Darwin'):
            command = self.command(['run', 'runs/policy/batch'], credentials={'OPENAI_API_KEY': 'SECRET_VALUE'})
        self.assertIn('type=volume,src=runs,dst=/opt/RoboFrontier/runs', command)
        self.assertIn('type=volume,src=state,dst=/opt/RoboFrontier/.robofrontier', command)
        self.assertIn('OPENAI_API_KEY', command)
        self.assertNotIn('SECRET_VALUE', ' '.join(command))
        self.assertNotIn('--gpus', command)
        self.assertIn('--sig-proxy=false', command)

    def test_credential_forwarding_is_scoped_to_selected_provider(self):
        credentials = runtime._credential_environment(self.config, {
            'OPENAI_API_KEY': 'openai', 'OPENLUX_API_KEY': 'other', 'HOME': '/private'})
        self.assertEqual(credentials, {'OPENAI_API_KEY': 'openai'})

    def test_nested_sandbox_permission_is_explicit_and_never_privileged(self):
        self.assertNotIn('--security-opt', self.command(['run', 'runs/policy/batch']))
        config = load_configuration(overrides={'render': {'device': 'cpu'},
            'container': {'seccomp_profile': 'unconfined'}})
        command = self.command(['run', 'runs/policy/batch'], config)
        self.assertIn('seccomp=unconfined', command)
        self.assertNotIn('--privileged', command)
        self.assertNotIn('--cap-add', command)
        self.assertNotIn('--security-opt', self.command(['prepare'], config))
        config['policy'].update(engine='claude', profile='haiku')
        self.assertNotIn('--security-opt', self.command(['run', 'runs/policy/batch'], config))

    def test_render_mode_requires_hardware_only_for_real_task_execution(self):
        config = load_configuration(overrides={'render': {'device': 'nvidia'}})
        with patch.object(runtime.platform, 'system', return_value='Darwin'):
            self.assertNotIn('--gpus', self.command(['plan'], config))
            with self.assertRaisesRegex(ValueError, 'requires Linux'):
                self.command(['run', 'runs/policy/batch'], config)
        with patch.object(runtime.platform, 'system', return_value='Linux'):
            self.assertIn('--gpus', self.command(['run', 'runs/policy/batch'], config))

    def test_run_reads_frozen_render_settings_from_the_container_volume(self):
        with patch.object(runtime.subprocess, 'check_output', return_value=json.dumps(self.config)) as read:
            result = runtime._frozen_settings(['run', 'runs/policy/batch'], load_configuration(),
                                              'image', {'runs': 'runs', 'state': 'state'})
        self.assertEqual(result['render']['device'], 'cpu')
        self.assertIn('/opt/RoboFrontier/runs/policy/batch/effective-config.json', read.call_args.args[0])
        self.assertIn('--rm', read.call_args.args[0])
        for path in ('/host/batch', '../batch', 'runs/../batch'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'relative paths'):
                runtime._batch_argument(['run', path])

    def test_existing_custom_or_network_volumes_are_rejected(self):
        with patch.object(runtime.subprocess, 'run'), patch.object(runtime.subprocess, 'check_output',
                return_value=json.dumps({'Driver': 'local', 'Options': {'type': 'nfs'}})):
            with self.assertRaisesRegex(ValueError, 'plain local'):
                runtime._ensure_volumes({'runs': 'runs', 'state': 'state'})

    def test_verified_archive_export_is_atomic_and_idempotent(self):
        content = b'exact archive bytes'
        receipt = {'archive': '/opt/RoboFrontier/runs/exports/batch.zip',
                   'archive_sha256': hashlib.sha256(content).hexdigest()}
        def copy(command, **kwargs):
            Path(command[-1]).write_bytes(content)
        destination = self.root/'new/exports'
        with patch.object(runtime.subprocess, 'run', side_effect=copy) as copied:
            result = runtime._export_archive('stopped', receipt, destination)
            again = runtime._export_archive('stopped', receipt, destination)
        self.assertEqual(result, again)
        self.assertEqual(result.read_bytes(), content)
        self.assertEqual(copied.call_count, 1)
        result.write_bytes(b'different')
        with self.assertRaisesRegex(ValueError, 'different exported'):
            runtime._export_archive('stopped', receipt, destination)

    def test_corrupt_export_never_publishes_output(self):
        receipt = {'archive': '/opt/RoboFrontier/runs/exports/batch.zip', 'archive_sha256': '0'*64}
        def corrupt(command, **kwargs):
            Path(command[-1]).write_bytes(b'corrupt')
        destination = self.root/'exports'
        with patch.object(runtime.subprocess, 'run', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                runtime._export_archive('stopped', receipt, destination)
        self.assertFalse((destination/'batch.zip').exists())
        self.assertEqual(list(destination.iterdir()), [])

    def execute(self, running=False, receipt=None):
        with patch.object(runtime.shutil, 'which', return_value='/docker'), \
                patch.object(runtime, '_image', return_value=('image', 'commit')), \
                patch.object(runtime, '_ensure_image'), patch.object(runtime, '_ensure_volumes'), \
                patch.object(runtime, '_running', return_value=running), \
                patch.object(runtime, '_copy_result', return_value=receipt or {'model_calls': 0}), \
                patch.object(runtime.subprocess, 'Popen', return_value=SimpleNamespace(wait=lambda: 0)), \
                patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='daemon')) as control:
            result = runtime.execute(['plan'], self.config, root=self.root)
        return result, control

    def test_one_command_prepares_local_metadata_and_only_removes_a_stopped_container(self):
        result, control = self.execute()
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['status'], 'closed')
        records = list((self.root/'.robofrontier/containers/default/commands').glob('*.json'))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())['source_commit'], 'commit')
        self.assertEqual(control.call_args.args[0][:2], ['docker', 'rm'])

    def test_a_slow_stop_after_ctrl_c_still_records_the_retained_container(self):
        def run(command, **options):
            if command[:2] in (['docker', 'stop'], ['docker', 'exec']):
                raise subprocess.TimeoutExpired(command, options.get('timeout'))
            return SimpleNamespace(returncode=0, stdout='daemon')
        waits = iter([KeyboardInterrupt(), KeyboardInterrupt()])
        def wait(timeout=None):
            raise next(waits)
        with patch.object(runtime.shutil, 'which', return_value='/docker'), \
                patch.object(runtime, '_image', return_value=('image', 'commit')), \
                patch.object(runtime, '_ensure_image'), patch.object(runtime, '_ensure_volumes'), \
                patch.object(runtime, '_running', return_value=True), \
                patch.object(runtime.subprocess, 'Popen', return_value=SimpleNamespace(wait=wait)), \
                patch.object(runtime.subprocess, 'run', side_effect=run):
            result = runtime.execute(['plan'], self.config, root=self.root)
        self.assertEqual(result['status'], 'still_running_needs_review')
        self.assertTrue(result['interrupted'])
        records = list((self.root/'.robofrontier/containers/default/commands').glob('*.json'))
        self.assertEqual(json.loads(records[0].read_text())['status'], 'still_running_needs_review')

    def test_live_or_disconnected_container_is_retained_without_copy_or_restart(self):
        result, control = self.execute(running=True)
        self.assertEqual(result['status'], 'still_running_needs_review')
        self.assertEqual(result['exit_code'], 2)
        self.assertEqual([call.args[0][:2] for call in control.call_args_list], [['docker', 'version']])

    def test_authentication_uses_persistent_private_state_without_printing_a_key(self):
        with patch.object(runtime.sys.stdin, 'isatty', return_value=False):
            command = self.command(['auth', 'codex', 'login', '--device-auth'])
        self.assertIn('CODEX_HOME=/opt/RoboFrontier/.robofrontier/subscription', command)
        self.assertEqual(command[-3:], ['cli_auth_credentials_store="file"', 'login', '--device-auth'])
        self.assertNotIn('--result-file', command)
        with self.assertRaisesRegex(ValueError, 'Supported auth'):
            self.command(['auth', 'shell', 'something'])

    def test_engine_only_selection_uses_that_engines_default_profile(self):
        settings = runtime._settings(['plan', '--engine', 'claude'], load_configuration())
        self.assertEqual(settings['policy']['profile'],
                         load_configuration(overrides={'policy': {'engine': 'claude'}})['policy']['profile'])
        self.assertEqual(settings['policy']['profile'], 'haiku_subscription_token')
        runtime._credential_environment(settings, {})
        explicit = runtime._settings(['plan', '--engine', 'claude', '--profile', 'haiku_subscription_token'], load_configuration())
        self.assertEqual(explicit['policy']['profile'], 'haiku_subscription_token')
        self.assertEqual(runtime._settings(['plan', '--engine', 'codex'], load_configuration()), load_configuration())

    def test_invalid_container_options_fail_during_configuration_resolution(self):
        for value in ({'workspace': '../escape'}, {'workspace': 'MixedCase'},
                      {'memory_gib': -1}, {'cpus': float('nan')}, {'image': 'name with spaces'},
                      {'seccomp_profile': 'privileged'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_configuration(overrides={'container': value})

    def test_cli_publishes_an_offline_result_receipt(self):
        from robofrontier.cli import main
        output = self.root/'result.json'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--result-file', str(output), 'plan']), 0)
        result = json.loads(output.read_text())
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['task_count'], 36)


if __name__ == '__main__':
    unittest.main()
