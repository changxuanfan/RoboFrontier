from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robofrontier.suite import mosaic_policy_package as package_module
from robofrontier.suite.mosaic_policy_package import ROOT, _same_harness, _verify_builder, _verify_recorded_evaluator
from robofrontier.suite.mosaic_delivery import COVERAGE, _coverage_report, _design_file
from robofrontier.suite.provenance import environment_logic_manifest


class HistoricalMosaicProvenanceTests(unittest.TestCase):
    def test_role_rename_does_not_admit_control_limit_or_engine_changes(self):
        frozen = {'coordinator': 'Coordinator', 'action_timeout_sim_s': 30,
                  'allowed_tcp_speed_m_s': [.1, .2], 'gripper_position_servo': 'pd1000-v1'}
        current = dict(deepcopy(frozen), coordinator='Controller')
        self.assertTrue(_same_harness(frozen, current))
        self.assertTrue(_same_harness(frozen, deepcopy(frozen)))
        for field, value in (('coordinator', 'Unreviewed'), ('action_timeout_sim_s', 31),
                             ('allowed_tcp_speed_m_s', [.1, .3]), ('engine', 'claude')):
            changed = deepcopy(current)
            changed[field] = value
            with self.subTest(field=field):
                self.assertFalse(_same_harness(frozen, changed))
        self.assertEqual(frozen['coordinator'], 'Coordinator')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trial = Path(self.temp.name)
        self.sources = {}
        for name, code in (('evaluate.py', 'OLD_PROCESS_RULE = True\n'),
                           ('evaluate_v2.py', 'OLD_GEOMETRY = 1\n')):
            relative = 'robofrontier/suite/'+name
            path = self.trial/'executor-source'/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code)
            self.sources[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.task = {'family': 'mosaic'}
        manifest = environment_logic_manifest(self.sources, self.task)
        self.report = {'environment_logic_sha256': manifest['sha256'],
                       'environment_logic_provenance': manifest}

    def test_historical_evaluator_does_not_require_current_rule_equivalence(self):
        # Frozen sources stand alone: no current scorer is consulted/executed.
        _verify_recorded_evaluator(self.trial, self.sources, self.report, self.task)

    def test_changed_frozen_evaluator_is_rejected_with_original_report_retained(self):
        path = self.trial/'executor-source/robofrontier/suite/evaluate.py'
        path.write_text('OLD_PROCESS_RULE = False\n')
        with self.assertRaisesRegex(ValueError, 'Pinned source differs'):
            _verify_recorded_evaluator(self.trial, self.sources, self.report, self.task)

    def test_changed_provenance_or_aggregate_fingerprint_is_rejected(self):
        report = deepcopy(self.report)
        report['environment_logic_provenance']['sources']['robofrontier/suite/evaluate.py'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Recorded evaluator differs'):
            _verify_recorded_evaluator(self.trial, self.sources, report, self.task)
        report = deepcopy(self.report)
        report['environment_logic_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Frozen evaluator manifest differs'):
            _verify_recorded_evaluator(self.trial, self.sources, report, self.task)

    def test_registered_old_builder_rechecks_unchanged_public_boundary(self):
        receipt = json.loads((ROOT/'benchmark/mosaic/builder-compatibility.json').read_text())
        recorded = receipt['historical_builders'][0]['source_sha256']
        _verify_builder(recorded, ROOT)
        with self.assertRaisesRegex(ValueError, 'Review builder changed'):
            _verify_builder('0'*64, ROOT)
        tree = ast.parse(Path(package_module.__file__).read_text())
        guard = next(node for node in tree.body if isinstance(node, ast.Assign) and
                     any(isinstance(target, ast.Name) and target.id == 'FORBIDDEN_PUBLIC_KEYS' for target in node.targets))
        guard.value = ast.Set(elts=[ast.Constant('qpos')])
        changed = self.trial/'changed_builder.py'
        changed.write_text(ast.unparse(tree))
        with patch.object(package_module, '__file__', str(changed)):
            with self.assertRaisesRegex(ValueError, 'Review builder changed'):
                _verify_builder(recorded, ROOT)

    def test_design_reference_relocates_only_known_names_in_local_evidence(self):
        relative = 'runs/engineering/mosaic-local-colours-r14-20261027/a04-plan.json'
        target = self.trial/relative
        target.parent.mkdir(parents=True)
        target.write_text('local exact copy')
        old = '/Users/fanchangxuan/Repos/roomscript2/'+relative
        self.assertEqual(_design_file(old, self.trial), target)
        self.assertEqual(_design_file(relative, self.trial), target)
        self.assertEqual(_design_file(str(target), self.trial), target)
        for reference in ('/unrelated/'+relative, relative.replace('a04-plan', 'unknown'),
                          relative.replace('a04-plan.json', '../outside.json')):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                _design_file(reference, self.trial)

    def test_design_reference_rejects_external_symlink(self):
        relative = 'runs/engineering/mosaic-local-colours-r14-20261027/a04-plan.json'
        target = self.trial/relative
        target.parent.mkdir(parents=True)
        outside = self.trial/'outside.json'
        outside.write_text('external')
        target.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'escapes local evidence'):
            _design_file(relative, self.trial)

    def test_coverage_certificate_is_bound_to_plan_and_scene_not_just_confirmed_flags(self):
        root = self.trial/'checkout'
        source = root/'configs/environments/mosaic/test'
        source.mkdir(parents=True)
        scene = source/'scene.xml'
        scene.write_text('frozen geometry')
        report = root/COVERAGE/'test-case/report.json'
        report.parent.mkdir(parents=True)
        report.write_text('{"confirmed": true}')
        plan = {'source_cases': [{'id': 'test-case', 'directory': str(source.relative_to(root)),
                                 'scene_sha256': hashlib.sha256(scene.read_bytes()).hexdigest(),
                                 'coverage_sha256': hashlib.sha256(report.read_bytes()).hexdigest()}]}
        self.assertEqual(_coverage_report('test-case', plan, source, root), {'confirmed': True})
        report.write_text('{"confirmed": true, "changed": true}')
        with self.assertRaisesRegex(ValueError, 'Pinned source differs'):
            _coverage_report('test-case', plan, source, root)
        with self.assertRaisesRegex(ValueError, 'Coverage source does not match'):
            _coverage_report('different-case', plan, source, root)
