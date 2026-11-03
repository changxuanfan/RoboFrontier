"""Exercise frozen preparation and real child supervision, without inference."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from robofrontier import oracle_workflow as workflow
from robofrontier.configuration import load_configuration, validate_configuration


CASES = ('transport-a04-d1', 'mosaic-a04-6x12-d1', 'relay-a08-d1', 'dial-best5-n04-d1')


class OracleWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def config(self, case=CASES[0], **options):
        return load_configuration(overrides={'selection': {'cases': [case]},
            'render': {'device': 'native' if sys.platform == 'darwin' else 'cpu'}, 'oracle': options})

    def prepare(self, case=CASES[0], **options):
        root = self.root/case
        with patch.object(workflow, '_committed_source', return_value='test-source'):
            workflow.prepare(root, self.config(case, **options))
        return root

    def stub(self, root, report, *, ignore_stop=False):
        program = (
            'import json, pathlib, signal, time\n'
            f'root=pathlib.Path({str(root)!r})\n'
            '(root/"trial").mkdir()\n'
            f'report={report!r}\n'
            'def stop(*_):\n'
            ' report["error"]="stopped by owner"\n'
            ' (root/"trial/report.json").write_text(json.dumps(report))\n'
            ' raise SystemExit(1)\n'
            f'signal.signal(signal.SIGTERM, {"signal.SIG_IGN" if ignore_stop else "stop"})\n'
            '(root/"stub-ready").touch()\n'
        )
        return [sys.executable, '-c', program], dict(os.environ)

    def test_offline_plan_ignores_policy_models_and_does_not_start_physics(self):
        config = load_configuration(overrides={'policy': {'profile': 'unused-oracle-only'}})
        with patch('subprocess.Popen') as launch:
            result = workflow.plan(config)
        self.assertEqual(result['task_count'], 36)
        self.assertEqual(result['model_calls'], 0)
        self.assertFalse(result['physics_stepped'])
        launch.assert_not_called()

    def test_four_native_commands_bind_current_scenes_and_frozen_executor(self):
        for case in CASES:
            with self.subTest(case=case):
                root = self.prepare(case)
                _, manifest, config = workflow._load(root)
                command, env = workflow._command(root, manifest, config)
                self.assertIn(str(root/'private/executor/scripts'/workflow.ENTRIES[manifest['family']]), command)
                self.assertEqual(env['ROBOFRONTIER_ORACLE_FROZEN_ROOT'], str(root/'private/executor'))
                self.assertEqual(env['PYTHONPATH'], str(root/'private/executor'))
                self.assertEqual(command[command.index('--harness')+1], str(root/'private/executor/inputs/harness.json'))
                catalog = json.loads((root/'private/executor/inputs/catalog.json').read_text())
                self.assertEqual(catalog['cases'][0]['directory'], manifest['source_directory'])
                self.assertNotIn('/runs/oracle/', manifest['source_directory'])
                self.assertEqual(catalog['cases'][0]['id'], case)
                self.assertFalse((root/'trial').exists())
                self.assertEqual(manifest['execution_protocol'], 'private/execution-protocol.json')
                self.assertEqual(env['ROBOFRONTIER_ORACLE_PROTOCOL'], str(root/'private/execution-protocol.json'))
                protocol = json.loads((root/'private/execution-protocol.json').read_text())
                self.assertEqual(protocol['mode'], 'task-reference')
                self.assertEqual(protocol['source_task_sha256'], manifest['source_sha256']['task.json'])
                self.assertEqual(protocol['evaluation_semantics'], 'terminal_outcome_v2')
                if manifest['family'] == 'mosaic':
                    self.assertEqual(catalog['scene_revision'], 15)
                if manifest['family'] == 'dial':
                    puzzle = json.loads((root/'private/codebook.json').read_text())
                    self.assertEqual(len(puzzle['code_symbols']), 4)
                    self.assertTrue(set(puzzle['code_symbols']) <= {1, 2, 3, 4, 5})
                    self.assertEqual((root/'private/codebook.json').stat().st_mode & 0o777, 0o600)
                    self.assertNotIn(str(puzzle['code_symbols']), json.dumps(manifest))
                else:
                    self.assertNotIn('--codebook', command)

    def test_configuration_versions_one_and_two_are_not_rewritten(self):
        for version in (1, 2, 3):
            config = deepcopy(load_configuration())
            if version < 3:
                del config['oracle']
            else:
                del config['oracle']['evaluation_mode']
            if version == 1:
                del config['factory']
            config['schema_version'] = version
            before = json.dumps(config, sort_keys=True)
            validate_configuration(config)
            self.assertEqual(json.dumps(config, sort_keys=True), before)

    def test_invalid_oracle_limits_and_cross_family_codebook_are_rejected(self):
        for options in ({'wall_limit_s': 0}, {'stop_grace_s': float('nan')},
                        {'mosaic_planning_workers': -1}, {'mosaic_max_goals': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.config(**options)
        with self.assertRaisesRegex(ValueError, 'only for Dial'):
            workflow.prepare(self.root/'invalid', self.config(), codebook=self.root/'unused')
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            workflow.prepare(self.root/'many', load_configuration())

    def test_legacy_preparation_does_not_inherit_a_new_execution_protocol(self):
        config=self.config()
        config['schema_version']=3
        del config['oracle']['evaluation_mode']
        root=self.root/'legacy'
        with patch.object(workflow,'_committed_source',return_value='test-source'):
            workflow.prepare(root,config)
        _,manifest,frozen_config=workflow._load(root)
        self.assertNotIn('execution_protocol',manifest)
        with patch.dict(os.environ,{'ROBOFRONTIER_ORACLE_PROTOCOL':'/unrelated/protocol.json'}):
            _,env=workflow._command(root,manifest,frozen_config)
        self.assertNotIn('ROBOFRONTIER_ORACLE_PROTOCOL',env)
        self.assertEqual(frozen_config,config)

    def test_strict_process_preparation_is_explicit_and_hash_bound(self):
        root=self.prepare(evaluation_mode='strict-process')
        _,manifest,config=workflow._load(root)
        self.assertEqual(config['oracle']['evaluation_mode'],'strict-process')
        protocol=json.loads((root/manifest['execution_protocol']).read_text())
        self.assertEqual(protocol['mode'],'strict-process')
        self.assertIn('private/execution-protocol.json',manifest['input_sha256'])

    def test_configuration_and_executor_mutation_rejected_before_any_process(self):
        for index, name in enumerate(('private/executor/robofrontier/suite/oracle.py', 'effective-config.json', 'private/execution-protocol.json')):
            root = self.root/str(index)
            with patch.object(workflow, '_committed_source', return_value='test-source'):
                workflow.prepare(root, self.config())
            source = root/name
            source.write_text(source.read_text()+'\n# mutation\n')
            with patch('subprocess.Popen') as launch, self.assertRaisesRegex(ValueError, 'Frozen Oracle input changed'):
                workflow.run(root)
            launch.assert_not_called()
            self.assertFalse((root/'private/claim.json').exists())

    def test_actual_child_success_requires_completed_full_report_and_is_single_use(self):
        root = self.prepare()
        report = {'passed': True, 'evaluation': {'task_success': True}, 'unresolved_robot_actions': []}
        command, env = self.stub(root, report)
        command[-1] += '(root/"trial/report.json").write_text(json.dumps(report))\n'
        with patch.object(workflow, '_command', return_value=(command, env)):
            result = workflow.run(root)
            self.assertTrue(result['passed'])
            self.assertEqual(result['phase'], 'passed')
            with self.assertRaisesRegex(ValueError, 'single-use'):
                workflow.run(root)
        self.assertFalse(workflow.status(root)['owner_lock_held'])

    def test_partial_commissioning_and_unresolved_actions_never_become_full_success(self):
        for index, report in enumerate((
            {'passed': False, 'commissioning_only': True, 'commissioning_passed': True,
             'evaluation': {'task_success': False}},
            {'passed': True, 'evaluation': {'task_success': True}, 'unresolved_robot_actions': ['A']},
        )):
            root = self.root/str(index)
            with patch.object(workflow, '_committed_source', return_value='test-source'):
                workflow.prepare(root, self.config())
            command, env = self.stub(root, report)
            command[-1] += '(root/"trial/report.json").write_text(json.dumps(report))\n'
            with patch.object(workflow, '_command', return_value=(command, env)):
                result = workflow.run(root)
            self.assertFalse(result['passed'])
            self.assertEqual(result['commissioning_passed'], index == 0)

    def test_explicit_stop_requests_cleanup_on_the_original_owner_without_relaunch(self):
        root = self.prepare(wall_limit_s=5, stop_grace_s=2)
        command, env = self.stub(root, {'passed': False})
        command[-1] += 'time.sleep(30)\n'
        def stop_when_started():
            limit = time.monotonic()+5
            while not (root/'stub-ready').exists() and time.monotonic() < limit:
                time.sleep(.01)
            (root/'STOP').touch()
        thread = threading.Thread(target=stop_when_started)
        thread.start()
        with patch.object(workflow, '_command', return_value=(command, env)):
            result = workflow.run(root)
        thread.join(timeout=1)
        self.assertEqual(result['stop_reason'], 'explicit_stop')
        self.assertEqual(result['phase'], 'interrupted')
        self.assertFalse(result.get('forced_kill', False))
        self.assertIn('stopped by owner', (root/'trial/report.json').read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(result['pid'], 0)

    def test_deadline_kills_unresponsive_child_and_preserves_incomplete_state(self):
        root = self.prepare(wall_limit_s=.2, stop_grace_s=.2)
        command, env = self.stub(root, {}, ignore_stop=True)
        command[-1] += 'time.sleep(30)\n'
        with patch.object(workflow, '_command', return_value=(command, env)):
            result = workflow.run(root)
        self.assertTrue(result['forced_kill'])
        self.assertEqual(result['stop_reason'], 'engineering_deadline')
        self.assertEqual(result['returncode'], -signal.SIGKILL)
        self.assertFalse(result['passed'])
        self.assertTrue((root/'private/claim.json').is_file())
        self.assertIsNone(result['report'])

    def test_stop_before_launch_is_not_a_resume_or_a_new_episode(self):
        root = self.prepare()
        (root/'STOP').touch()
        with patch('subprocess.Popen') as launch, self.assertRaisesRegex(ValueError, 'single-use'):
            workflow.run(root)
        launch.assert_not_called()

    def test_missing_pin_and_manifest_case_mismatch_are_rejected(self):
        for index, kind in enumerate(('missing_pin', 'wrong_case')):
            root = self.root/str(index)
            with patch.object(workflow, '_committed_source', return_value='test-source'):
                workflow.prepare(root, self.config())
            manifest = json.loads((root/'oracle.json').read_text())
            if kind == 'missing_pin':
                del manifest['input_sha256']['private/run.json']
            else:
                manifest['case_id'] = 'transport-a12-d3'
            (root/'oracle.json').write_text(json.dumps(manifest))
            with patch('subprocess.Popen') as launch, self.assertRaises(ValueError):
                workflow.run(root)
            launch.assert_not_called()

    def test_native_owner_leaving_a_child_does_not_establish_clean_success(self):
        root = self.prepare(stop_grace_s=.2)
        report = {'passed': True, 'evaluation': {'task_success': True}}
        command, env = self.stub(root, report)
        child = 'import pathlib,time; time.sleep(1); pathlib.Path('+repr(str(root/'late-child-write'))+').touch()'
        command[-1] += ('import subprocess,sys\n'
                        f'subprocess.Popen([sys.executable,"-c",{child!r}])\n'
                        '(root/"trial/report.json").write_text(json.dumps(report))\n')
        with patch.object(workflow, '_command', return_value=(command, env)):
            result = workflow.run(root)
        self.assertTrue(result['descendant_cleanup_required'])
        self.assertFalse(result['passed'])
        time.sleep(1.1)
        self.assertFalse((root/'late-child-write').exists())


if __name__ == '__main__':
    unittest.main()
