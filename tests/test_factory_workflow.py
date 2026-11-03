import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robofrontier.cli import main, _frozen_configuration
from robofrontier.configuration import load_configuration, validate_configuration
from robofrontier.factory import bundle
from robofrontier.factory import server
from test_factory_bundle import fixture, tour_fixture


class FactoryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = fixture(self.root)
        self.config = self.root/'settings.toml'
        self.config.write_text('[factory]\nsource="imported"\ndata_root='+json.dumps(str(self.data))+
            '\ndevice="CPU"\nwidth=1280\nheight=720\nsamples=8\n'
            '[slurm]\ngpus=0\ncpus_per_task=2\nmemory_gib=4\ntime_limit_s=600\nstop_warning_s=120\n')

    def cli(self, arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['--config', str(self.config), 'factory', *map(str, arguments)])
        self.assertEqual(code, 0)
        return json.loads(output.getvalue())

    def prepare(self):
        result = self.cli(['prepare', '--output', self.root/'render'])
        return Path(result['plan']), result

    def test_prepare_freezes_video_settings_without_changing_policy_observations(self):
        plan, result = self.prepare()
        document = bundle.read(plan)
        self.assertEqual((document['width'], document['height'], document['samples']), (1280, 720, 8))
        self.assertEqual(document['device'], 'CPU')
        self.assertEqual(document['effective_configuration']['render']['observation_profile'], 'jpeg_896x560_q85')
        self.assertEqual(document['effective_configuration']['batch']['parallel'], 36)
        self.assertEqual(document['effective_configuration']['factory']['parallel'], 1)
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(server.load_plan(plan)[1], document)

    def test_full_promo_defaults_to_210_5_seconds_without_a_hidden_short_cut(self):
        (self.root/'tour').mkdir()
        data = tour_fixture(self.root/'tour')
        result = self.cli(['prepare', '--data-root', data, '--mode', 'promo', '--output', self.root/'promo'])
        plan = bundle.read(result['plan'])
        self.assertEqual((plan['fps'], plan['jobs'][0]['frames']), (30, 6315))
        self.assertIn('editorial', plan)
        self.assertEqual(server.load_plan(result['plan'])[1], plan)

    def test_preview_duration_is_an_explicit_cap(self):
        (self.root/'tour').mkdir()
        data = tour_fixture(self.root/'tour')
        result = self.cli(['prepare', '--data-root', data, '--mode', 'promo', '--duration-s', '.1',
                           '--output', self.root/'preview'])
        self.assertEqual(bundle.read(result['plan'])['jobs'][0]['frames'], 3)

    def test_incomplete_full_tour_does_not_publish_a_partial_plan(self):
        with self.assertRaisesRegex(ValueError,'requires all 36'):
            server.prepare(self.data,self.root/'incomplete',mode='promo',device='CPU')
        self.assertFalse((self.root/'incomplete').exists())
        self.assertFalse(list(self.root.glob('.factory-plan-*')))

    def test_import_progress_keeps_stdout_as_one_json_result(self):
        def noisy_import(*args, **kwargs):
            print(json.dumps({'stage': 'export_blender', 'physics_stepped': False}))
            return {'status': 'verified', 'data_root': str(self.root/'imported')}

        diagnostics = io.StringIO()
        with patch.object(server, 'import_motion', side_effect=noisy_import), \
                contextlib.redirect_stderr(diagnostics):
            result = self.cli(['import-motion', self.root/'closed-recording',
                               '--output', self.root/'imported'])
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['model_calls'], 0)
        self.assertIn('export_blender', diagnostics.getvalue())

    def test_import_defaults_to_the_family_speedup_and_cuts_stationary_intervals(self):
        calls = []
        def record(*args, **kwargs):
            calls.append(kwargs)
            return {'status': 'verified', 'data_root': str(self.root/'imported')}
        with patch.object(server, 'import_motion', side_effect=record):
            self.cli(['import-motion', self.root/'closed-recording', '--output', self.root/'imported'])
            self.cli(['import-motion', self.root/'closed-recording', '--output', self.root/'imported-full',
                      '--speedup', 5, '--keep-idle'])
        self.assertEqual(calls, [dict(speedup=None, keep_idle=False, timeline=None), dict(speedup=5.0, keep_idle=True, timeline=None)])

    def test_promo_filter_error_precedes_installation_and_output_creation(self):
        with patch.object(bundle, 'setup') as install, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.cli(['prepare', '--mode', 'promo', '--level', 1, '--output', self.root/'bad'])
        install.assert_not_called()
        self.assertFalse((self.root/'bad').exists())

    def test_cpu_queue_is_dry_by_default_and_uses_the_frozen_resources(self):
        plan, _ = self.prepare()
        self.config.write_text('[factory]\ndevice="OPTIX"\n[slurm]\ncpus_per_task=99\n')
        with patch.object(server, 'blender_path', return_value='/software/blender'), \
                patch.object(server.subprocess, 'check_output') as submit:
            result = self.cli(['submit', plan])
        submit.assert_not_called()
        self.assertFalse(result['submitted'])
        command = result['command']
        self.assertNotIn('--gres=gpu:1', command)
        self.assertEqual(command[command.index('--cpus-per-task')+1], '2')
        self.assertEqual(command[command.index('--mem')+1], '4G')
        self.assertIn('--signal=B:TERM@120', command)

    def test_queue_submission_requires_the_explicit_flag(self):
        plan, _ = self.prepare()
        with patch.object(server, 'blender_path', return_value='/software/blender'), \
                patch.object(server.subprocess, 'check_output', return_value='12345') as submit:
            result = self.cli(['submit', plan, '--queue'])
        self.assertEqual(result['job_id'], '12345')
        self.assertEqual(submit.call_count, 1)

    def test_release_pin_mismatch_never_installs_over_an_existing_bundle(self):
        lock = self.root/'lock.json'
        bundle.write(lock, {'bundle_sha256': '0'*64})
        self.config.write_text('[factory]\nsource="release"\ndata_root='+json.dumps(str(self.data))+
                               '\nasset_lock='+json.dumps(str(lock))+'\n')
        with patch.object(bundle, 'setup') as install, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.cli(['prepare', '--output', self.root/'bad'])
        install.assert_not_called()
        self.assertFalse((self.root/'bad').exists())

    def test_inspection_never_silently_downloads_a_missing_bundle(self):
        with patch.object(bundle, 'setup') as install, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.cli(['verify', '--data-root', self.root/'missing'])
        install.assert_not_called()

    def test_new_render_plan_cannot_be_silently_reinterpreted_after_edit(self):
        plan, _ = self.prepare()
        document = bundle.read(plan)
        document['effective_configuration']['factory']['width'] = 640
        bundle.write(plan, document)
        with self.assertRaisesRegex(ValueError, 'plan changed'):
            server.load_plan(plan)

    def test_legacy_plan_status_survives_but_execution_uses_its_original_entry(self):
        plan = server.prepare(self.data, self.root/'legacy', device='CPU')['plan']
        self.assertEqual(self.cli(['status', plan])['total'], 2)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli(['run', plan, '--index', 0])

    def test_configuration_rejects_invalid_factory_values(self):
        for settings in ({'width': 1919}, {'samples': 0}, {'duration_s': float('nan')},
                         {'import_speedup': -1}, {'views': [{}]}, {'device': 'automatic'}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                load_configuration(overrides={'factory': settings})

    def test_version_one_frozen_policy_configuration_remains_exact(self):
        from robofrontier.run_setup import write_json
        import hashlib
        config = deepcopy(load_configuration())
        del config['factory']
        del config['oracle']
        config['schema_version'] = 1
        validate_configuration(config)
        write_json(self.root/'effective-config.json', config)
        checksum = hashlib.sha256(json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest()
        write_json(self.root/'batch.json', {'effective_configuration_sha256': checksum,
            'execution': {**config['runtime'], 'startup_interval_s': config['batch']['startup_interval_s']}})
        self.assertEqual(_frozen_configuration(self.root), config)
        self.assertNotIn('factory', config)


if __name__ == '__main__':
    unittest.main()
