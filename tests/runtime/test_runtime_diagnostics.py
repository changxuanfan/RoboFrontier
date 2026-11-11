import contextlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from robofrontier.runtime import diagnostics as diagnostics
from robofrontier.configuration import load_configuration


class RuntimeDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.config = load_configuration()

    def test_a_failed_sandbox_is_visible_even_if_rendering_works(self):
        with patch.object(diagnostics, '_native_probe', side_effect=RuntimeError('namespace denied')), \
                patch.object(diagnostics, '_render_probe', return_value={'gl_renderer': 'NVIDIA'}):
            report = diagnostics.inspect_runtime(self.config)
        self.assertFalse(report['passed'])
        self.assertEqual(report['model_calls'], 0)
        self.assertIn('namespace denied', report['checks']['native_cli']['error'])
        self.assertTrue(report['checks']['render']['passed'])

    def test_provider_preflight_does_not_require_a_simulator_context(self):
        with patch.object(diagnostics, '_native_probe', return_value={'version': 'test'}), \
                patch.object(diagnostics, '_render_probe') as render:
            self.assertTrue(diagnostics.inspect_runtime(self.config, render=False)['passed'])
        render.assert_not_called()

    def test_native_probe_excludes_keys_and_uses_temporary_auth_directories(self):
        calls = []
        def check(command, **options):
            calls.append((command, options['env'].copy()))
            self.assertNotIn('OPENAI_API_KEY', options['env'])
            self.assertNotIn('ANTHROPIC_API_KEY', options['env'])
            self.assertNotEqual(options['env']['CODEX_HOME'], '/existing/private/home')
            self.assertTrue(Path(options['env']['CODEX_HOME']).is_dir())
            self.assertTrue(Path(options['env']['CLAUDE_CONFIG_DIR']).is_dir())
            return 'version'
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-secret',
                    'ANTHROPIC_API_KEY': 'test-secret', 'CODEX_HOME': '/existing/private/home'}), \
                patch.object(diagnostics, '_checked', side_effect=check):
            diagnostics._native_probe('codex')
        self.assertEqual(calls[1][0][:3], ['codex', 'sandbox', '--'])
        self.assertFalse(Path(calls[0][1]['CODEX_HOME']).parent.exists())

    def test_a_robot_only_codex_run_does_not_need_the_codex_sandbox(self):
        calls = []
        with patch.object(diagnostics, '_checked', side_effect=lambda command, **options: calls.append(command) or 'version'):
            report = diagnostics._native_probe('codex', 'native', True)
        self.assertEqual(calls, [['codex', '--version']])
        self.assertEqual(report, {'version': 'version', 'sandbox_checked': False, 'tool_mode': 'robot_only'})
        seen = []
        config = {**self.config, 'policy': {**self.config['policy'], 'engine': 'codex', 'tool_mode': 'robot_only'}}
        with patch.object(diagnostics, '_native_probe', side_effect=lambda *args: seen.append(args) or {'version': 'v'}):
            self.assertTrue(diagnostics.inspect_runtime(config, render=False)['passed'])
        self.assertEqual(seen[0][2], True)

    def test_renderer_probe_preserves_allocation_visibility_but_not_credentials(self):
        with patch.object(diagnostics.platform, 'system', return_value='Linux'), \
                patch.dict(os.environ, {'CUDA_VISIBLE_DEVICES': '3', 'OPENAI_API_KEY': 'secret',
                    '__EGL_VENDOR_LIBRARY_FILENAMES':'/usr/share/glvnd/egl_vendor.d/10_nvidia.json'}), \
                patch.object(diagnostics, '_checked', return_value='{}') as check:
            diagnostics._render_probe('nvidia')
            env = check.call_args.kwargs['env']
            self.assertEqual(env['CUDA_VISIBLE_DEVICES'], '3')
            self.assertEqual(env['__EGL_VENDOR_LIBRARY_FILENAMES'], '/usr/share/glvnd/egl_vendor.d/10_nvidia.json')
            self.assertNotIn('OPENAI_API_KEY', env)
            diagnostics._render_probe('cpu')
            self.assertEqual(check.call_args.kwargs['env']['CUDA_VISIBLE_DEVICES'], '')

    def test_failed_local_probe_prevents_a_paid_preflight(self):
        from robofrontier.cli import preflight
        with patch.object(diagnostics, 'inspect_runtime', return_value={'passed': False,
                'checks': {'native_cli': {'passed': False, 'error': 'namespace denied'}}}), \
                patch('subprocess.run') as launch:
            with self.assertRaisesRegex(ValueError, 'before model calls'):
                preflight(self.config, confirm_spend=True)
        launch.assert_not_called()

    def test_failed_local_probe_prevents_task_launch(self):
        from robofrontier.cli import run
        with patch('robofrontier.cli._frozen_configuration', return_value=self.config), \
                patch.object(diagnostics, 'require_runtime', side_effect=ValueError('no sandbox')), \
                patch('robofrontier.batch.codex_batch.run_batch') as launch:
            with self.assertRaisesRegex(ValueError, 'no sandbox'):
                run(Path('runs/test'))
        launch.assert_not_called()

    def test_doctor_cli_reports_offline_failure_with_nonzero_exit(self):
        from robofrontier.cli import main
        output = io.StringIO()
        with patch.object(diagnostics, 'inspect_runtime', return_value={'passed': False, 'model_calls': 0}), \
                contextlib.redirect_stdout(output):
            self.assertEqual(main(['doctor']), 2)
        self.assertEqual(json.loads(output.getvalue())['model_calls'], 0)


if __name__ == '__main__':
    unittest.main()
