"""Explicit Oracle semantics, separate from immutable scene provenance."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

PROTOCOL_ENV = 'ROBOFRONTIER_ORACLE_PROTOCOL'
PROTOCOL_SCHEMA = 'robofrontier.oracle-protocol.v1'


def uses_terminal_outcome(trial):
    return getattr(trial,'task',{}).get('run_protocol',{}).get('evaluation_semantics') == 'terminal_outcome_v2'


def process_blocks(trial):
    """Legacy and strict commissioning retain their original process gate."""
    return ((getattr(trial, 'oracle_protocol', None) or {}).get('mode') == 'strict-process'
            or not uses_terminal_outcome(trial))


def effective_task(scene, task, protocol):
    """Validate the exact source before overlaying only execution semantics."""
    expected = {'schema', 'mode', 'case_id', 'source_task_sha256', 'source_scene_sha256',
                'evaluation_semantics'}
    if (set(protocol) != expected or protocol['schema'] != PROTOCOL_SCHEMA
            or protocol['mode'] not in ('task-reference', 'strict-process')
            or protocol['evaluation_semantics'] != 'terminal_outcome_v2'
            or protocol['case_id'] != task['id']):
        raise ValueError('Invalid Oracle execution protocol')
    for name, field in (('task.json', 'source_task_sha256'), ('scene.xml', 'source_scene_sha256')):
        if hashlib.sha256((Path(scene)/name).read_bytes()).hexdigest() != protocol[field]:
            raise ValueError('Oracle execution protocol source differs: '+name)
    result = deepcopy(task)
    result.setdefault('run_protocol', {})['evaluation_semantics'] = protocol['evaluation_semantics']
    if task.get('family') == 'relay' and task.get('completion', {}).get('required_airborne_handover'):
        # Oracle witnesses obey the same airborne-handover rule as policy runs.
        from ..task_families import RELAY_HANDOVER_RULE
        result['run_protocol']['relay_completion_rule'] = RELAY_HANDOVER_RULE
    return result


def configure_trial(trial):
    """Only a new frozen launch opts in; native legacy launches stay exact."""
    path = os.environ.get(PROTOCOL_ENV)
    trial.oracle_protocol = None
    if path:
        protocol = json.loads(Path(path).read_text())
        trial.task = effective_task(trial.scene, trial.task, protocol)
        trial.oracle_protocol = protocol
        trial.abort_on_process_violation = process_blocks(trial)


def unresolved_robots(trial, terminal_feedback=()):
    """Match original action IDs to owner-observed terminal motor feedback.

    Historical uncertain rows remain immutable. An unrelated later command or
    an idle arm alone cannot resolve them. Adapter acknowledgement fences need
    explicit owner review even when a motor has subsequently stopped.
    """
    pending=set()
    known=set()
    for action in getattr(trial,'actions',[]):
        for robot,result in action.get('results',{}).items():
            key=(robot,result.get('call_id'))
            if result.get('status')=='uncertain':pending.add(key)
            elif result.get('status') in ('completed','failed') and key[1]:known.add(key)
    for event in getattr(trial,'events',[]):
        if event.get('event') not in ('reference_recovery_terminal_action','oracle_execution_resolved'):
            continue
        result=event.get('result',{})
        if result.get('call_id') and result.get('status') in ('completed','failed'):
            known.add((event.get('robot'),result['call_id']))
    for result in terminal_feedback:
        if result.get('call_id') and result.get('status') in ('completed','failed'):
            known.update(key for key in pending if key[1]==result['call_id'])
    unresolved={robot for robot,ident in pending-known}
    unresolved.update(robot for robot,arm in trial.arms.items()
                      if arm.job is not None or getattr(arm,'uncertainty_reported',False))
    adapter=getattr(trial,'_oracle_recovery_attachment',None)
    if adapter is not None:unresolved.update(adapter.unknown)
    return unresolved


def summarize(trial, report):
    """Expose independent verdicts without promoting failed strategies."""
    if not getattr(trial, 'oracle_protocol', None):
        return
    evaluation = report.get('evaluation', {})
    unresolved = set(report.get('unresolved_robot_actions', []))
    unresolved.update(unresolved_robots(trial,report.get('terminal_cleanup_feedback',())))
    physics_valid = getattr(trial, 'physics_failure', None) is None
    report.update(report_schema='robofrontier.oracle-report.v2',
                  execution_protocol=trial.oracle_protocol,
                  task_goal_met=bool(evaluation.get('task_success')),
                  task_completed=bool(evaluation.get('task_success') and physics_valid and not unresolved),
                  process_clean=not bool(trial.monitor.violations),
                  execution_resolved=not bool(unresolved), physics_valid=physics_valid,
                  strategy_completed=bool(report.get('passed') and not report.get('error')
                                          and not report.get('cleanup_error') and not report.get('interrupted')
                                          and physics_valid and not unresolved),
                  unresolved_robot_actions=sorted(unresolved))
    if not physics_valid:
        report['physics_error'] = trial.physics_failure
    if (unresolved or not physics_valid or report.get('error') or report.get('cleanup_error') or report.get('interrupted')
            or (process_blocks(trial) and trial.monitor.violations)):
        report['passed'] = False
