"""Frozen semantics and independent completion/health verdicts."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from robofrontier.suite import oracle_protocol as protocol


class OracleProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scene = Path(self.temp.name)
        self.task = {'id': 'case', 'completion': {'stable_duration_sim_s': 1.}}
        (self.scene/'task.json').write_text(json.dumps(self.task))
        (self.scene/'scene.xml').write_text('<mujoco/>')
        self.protocol = dict(schema=protocol.PROTOCOL_SCHEMA, mode='task-reference', case_id='case',
            source_task_sha256=hashlib.sha256((self.scene/'task.json').read_bytes()).hexdigest(),
            source_scene_sha256=hashlib.sha256((self.scene/'scene.xml').read_bytes()).hexdigest(),
            evaluation_semantics='terminal_outcome_v2')

    def test_overlay_preserves_source_bytes_and_task_requirements(self):
        before = {p.name: p.read_bytes() for p in self.scene.iterdir()}
        actual = protocol.effective_task(self.scene, self.task, self.protocol)
        self.assertNotIn('run_protocol', self.task)
        self.assertEqual(actual['completion'], self.task['completion'])
        self.assertEqual({p.name: p.read_bytes() for p in self.scene.iterdir()}, before)
        self.assertFalse(protocol.process_blocks(NS(task=actual)))
        self.assertTrue(protocol.process_blocks(NS(task=actual, oracle_protocol={'mode': 'strict-process'})))

    def test_changed_source_wrong_case_and_unknown_semantics_are_rejected(self):
        for change in ({'case_id': 'other'}, {'evaluation_semantics': 'unknown'},
                       {'mode': 'ignore-collisions'}, {'source_scene_sha256': '0'*64}, {'extra': True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                protocol.effective_task(self.scene, self.task, dict(self.protocol, **change))

    def test_overlay_preserves_other_frozen_protocol_fields(self):
        self.task['run_protocol']={'evaluation_semantics':'legacy','total_wall_limit_s':86400.}
        (self.scene/'task.json').write_text(json.dumps(self.task))
        self.protocol['source_task_sha256']=hashlib.sha256((self.scene/'task.json').read_bytes()).hexdigest()
        actual=protocol.effective_task(self.scene,self.task,self.protocol)
        self.assertEqual(actual['run_protocol'],dict(evaluation_semantics='terminal_outcome_v2',total_wall_limit_s=86400.))
        self.assertEqual(self.task['run_protocol']['evaluation_semantics'],'legacy')

    def test_relay_oracle_task_requires_the_airborne_handover_rule(self):
        from robofrontier.task_families import RELAY_HANDOVER_RULE
        for family, required, expected in (('relay', True, RELAY_HANDOVER_RULE), ('relay', False, None),
                                           ('transport', True, None), ('mosaic', None, None), ('dial', None, None)):
            with self.subTest(family=family, required=required):
                self.task.update(family=family)
                self.task['completion'].pop('required_airborne_handover', None)
                if required is not None:
                    self.task['completion']['required_airborne_handover'] = required
                (self.scene/'task.json').write_text(json.dumps(self.task))
                self.protocol['source_task_sha256'] = hashlib.sha256((self.scene/'task.json').read_bytes()).hexdigest()
                actual = protocol.effective_task(self.scene, self.task, self.protocol)
                self.assertEqual(actual['run_protocol'].get('relay_completion_rule'), expected)
                self.assertEqual(actual['completion'], self.task['completion'])
                self.assertNotIn('run_protocol', self.task)

    def test_native_launch_without_protocol_keeps_original_step_default(self):
        trial = NS(scene=self.scene, task=deepcopy(self.task), abort_on_process_violation=False)
        with patch.dict(os.environ, {}, clear=True):
            protocol.configure_trial(trial)
        self.assertFalse(trial.abort_on_process_violation)
        self.assertNotIn('run_protocol', trial.task)

    def test_terminal_completion_is_separate_from_process_history(self):
        trial = NS(task=protocol.effective_task(self.scene, self.task, self.protocol),
                   oracle_protocol=self.protocol, arms={}, actions=[],
                   monitor=NS(violations=[{'kind': 'robot_contact'}]))
        report = {'passed': True, 'evaluation': {'task_success': True}}
        protocol.summarize(trial, report)
        self.assertTrue(report['passed'])
        self.assertTrue(report['task_completed'])
        self.assertFalse(report['process_clean'])
        self.assertTrue(report['execution_resolved'])
        strict = deepcopy(report)
        trial.oracle_protocol = dict(self.protocol, mode='strict-process')
        protocol.summarize(trial, strict)
        self.assertFalse(strict['passed'])
        self.assertTrue(strict['task_completed'])

    def test_unknown_execution_or_invalid_physics_cannot_pass(self):
        for problem in ('unknown', 'physics'):
            with self.subTest(problem=problem):
                trial = NS(task={}, oracle_protocol=self.protocol, actions=[],
                           arms={'A': NS(job=None, uncertainty_reported=problem == 'unknown')},
                           physics_failure='Numerical physics failure' if problem == 'physics' else None,
                           monitor=NS(violations=[]))
                report = {'passed': True, 'evaluation': {'task_success': True}}
                protocol.summarize(trial, report)
                self.assertFalse(report['passed'])
                self.assertFalse(report['task_completed'])
                self.assertFalse(report['strategy_completed'])
                self.assertEqual(report['physics_valid'], problem != 'physics')
                self.assertEqual(report['execution_resolved'], problem != 'unknown')

    def test_goal_completion_does_not_promote_a_failed_strategy(self):
        trial=NS(task={},oracle_protocol=self.protocol,arms={},actions=[],monitor=NS(violations=[]))
        report={'passed':False,'error':'No finite reference continuation','evaluation':{'task_success':True}}
        protocol.summarize(trial,report)
        self.assertTrue(report['task_completed'])
        self.assertFalse(report['passed'])
        self.assertFalse(report['strategy_completed'])

    def test_original_terminal_feedback_resolves_history_without_erasing_it(self):
        action={'results':{'A':{'call_id':'original','status':'uncertain'}}}
        result={'call_id':'original','status':'failed','reason':'Stopped by owner'}
        trial=NS(task={},oracle_protocol=self.protocol,arms={'A':NS(job=None)},
                 actions=[action],events=[{'event':'reference_recovery_terminal_action',
                    'robot':'A','result':result}],monitor=NS(violations=[]))
        report={'passed':True,'evaluation':{'task_success':True}}
        protocol.summarize(trial,report)
        self.assertTrue(report['execution_resolved'])
        self.assertTrue(report['task_completed'])
        self.assertEqual(action['results']['A']['status'],'uncertain')
        trial.events[0]['result']=dict(result,call_id='different')
        protocol.summarize(trial,report)
        self.assertFalse(report['execution_resolved'])

    def test_cleanup_feedback_only_resolves_the_original_call(self):
        trial=NS(task={},oracle_protocol=self.protocol,arms={'A':NS(job=None)},
                 actions=[{'results':{'A':{'call_id':'original','status':'uncertain'}}}],
                 monitor=NS(violations=[]))
        for ident,status,expected in [('different','completed',False),('original','uncertain',False),
                                       ('original','failed',True)]:
            with self.subTest(ident=ident,status=status):
                report={'passed':False,'evaluation':{'task_success':True},
                        'terminal_cleanup_feedback':[{'call_id':ident,'status':status}]}
                protocol.summarize(trial,report)
                self.assertEqual(report['execution_resolved'],expected)


if __name__ == '__main__':
    unittest.main()
