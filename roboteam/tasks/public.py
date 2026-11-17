"""Checks of a released task against its scene, and the task's public projection."""
from collections import Counter
from copy import deepcopy

from .scene import validate_scene_asset


def validate(task):
    """A released task whose identity, geometry and protocol match its frozen scene."""
    folder, env = validate_scene_asset(task); case = env['suite_case']
    if task.get('suite_version') != 2 or task['id'] != case['id'] or task['family'] != case['family']:
        raise ValueError('Task identity differs from its scene')
    if len(task['arms']) != case['arms']:
        raise ValueError('Task arm count differs from its scene')
    if task.get('execution_readiness') == 'prepared_policy_trial':
        from .families import validate_policy_task
        validate_policy_task(task)
    elif task.get('execution_readiness') != 'environment_preview_only':
        raise ValueError('Unknown task execution readiness')
    for key in ('objects', 'mechanism', 'goals', 'grid', 'route', 'dials'):
        if task.get(key) != env.get(key, [] if key == 'goals' else None):
            raise ValueError('Task geometry differs from its scene: '+key)
    if task['family'] in ('transport', 'mosaic') and len(task['objects']) != len(task['goals']):
        raise ValueError('Every object needs exactly one goal')
    if task['family'] == 'mosaic':
        if Counter(o['color'] for o in task['objects']) != Counter(g['requires']['color'] for g in task['goals']):
            raise ValueError('Mosaic colors are not conserved')
    if task['family'] == 'transport':
        if Counter(o['identity'] for o in task['objects']) != Counter(g['requires']['identity'] for g in task['goals']):
            raise ValueError('Transport identities are not conserved')
    return task


def public_task(task):
    """What a policy may know of a task: rules, robots, mechanism and target, never live
    object state, the evaluator's goals or the wall limit."""
    # The run protocol (the limit, its clock, the release binding) stays private: the host
    # enforces the limit and policies plan as if time were unlimited.
    keys = ('id', 'family', 'level', 'arms', 'rules', 'objective', 'observation_contract',
            'gripper_profile', 'cameras', 'coordinate_frame')
    result = {k: deepcopy(task[k]) for k in keys}
    if task['family'] != 'dial':
        result['initial_supplies'] = [dict(source=s, color=c, count=n) for (s, c), n in
                                      sorted(Counter((o.get('source'), o.get('color')) for o in task['objects']).items())]
    result['mechanism'] = deepcopy(task['mechanism'])
    for assembly in result['mechanism'].get('payload_assemblies', []): assembly.pop('initial_position_m', None)
    if task['family'] == 'mosaic':
        result['target'] = {k: deepcopy(task['grid'][k]) for k in ('rows', 'columns', 'colors', 'pitch_m', 'cube_side_m', 'pattern', 'pocket_opening_m', 'depth_m')}
        result['target'].update(center_world_m=[0, 0, task['table_height_m']], row1='north', column1='west', reference_image='target-pattern.png')
        for key in ('palette', 'reference'):
            if key in task['grid']: result['target'][key] = deepcopy(task['grid'][key])
    if task['family'] == 'transport':
        result['orders'] = [{k: deepcopy(g[k]) for k in ('goal_id', 'robot', 'requires', 'target_cue') if k in g} for g in task['goals']]
    if task['family'] == 'dial':
        result['dials'] = [{k: deepcopy(g[k]) for k in ('id', 'index', 'nominal_robots')} for g in task['dials']]
    if task['family'] == 'relay':
        result['route_regions'] = deepcopy(task['route'])
        result['completion'] = deepcopy(task['completion'])
    return clean(result)


# Fields of the public task that are the builder's bookkeeping, not the task (T4, D30).
INTERNAL = ('kind', 'suite_version', 'execution_readiness', 'scene_revision', 'task_revision', 'source_scene_sha256',
            'run_protocol')
# Inside the mechanism: version and revision labels, simulator internals, body names and
# engineering notes.
MECHANISM_INTERNAL = ('revision', 'apparatus_revision', 'version', 'feedback_rule_version', 'physics_scope', 'opening',
                      'end_extensions', 'board_outward_shift_from_r10_m', 'timestep_s', 'contact_time_constant_s',
                      'material_calibration_verified', 'return_dynamics_verified', 'beam_body', 'weight_body', 'tray_body',
                      'beam_bodies', 'weight_body_free', 'joint', 'cable_model', 'cable_count', 'cable_to_cable_collision',
                      'collision')
COMPLETION_INTERNAL = ('rule_revision', 'relay_completion_rule')
# The rules and objectives as the release states them (rewritten 2026-11-11; the earlier
# wording is in git history).
OBJECTIVES = {
    'transport': 'Deliver every requested item to its place on its destination board, seated, released and still. '
                 'How the robots share the work is your choice.',
    'mosaic': 'Build the target pattern: one released cube in every cell, in the color the pattern gives. '
              'How the robots share the work is your choice.',
    'relay': 'Carry every timber to GOAL with at least one airborne handover each, and release it there. '
             'How the robots share the work is your choice.',
    'dial': 'Unlock the code: find the correct nonzero input and hold it on every dial at once, using only the BEST '
            'record as feedback. How the robots share the work is your choice.',
}
RULES = {
    'Build the supplied Tulip reference, including background cells, one released cube per pixel.':
        'Build the supplied Tulip pattern, background cells included: one released cube in each cell.',
    'The supplied pattern matrix and reference image already have their final world orientation; do not apply the historical rotation or mirror again.':
        'The pattern matrix and the reference image are already in world orientation (row 1 north, column 1 west); use them as given.',
    'Airborne transport requires at least two actual beam grasps. Establish receiving support before releasing a sender. Every assembly must undergo a real qualified airborne handover; the receiving team may retain an existing holder.':
        'Carrying a timber in the air takes at least two arms holding it. Every timber must have at least one qualified airborne handover (below); the receiving team may keep an arm that already holds it. Establish the receivers\' hold before a sender lets go.',
    'Any final placement in GOAL is allowed, including cargo contact and stacking. Oracle packing centers and contact-free separation are not task requirements.':
        'Any final placement in GOAL is allowed, including timbers touching or stacked on each other.',
    'Drops and violations remain recorded. Only the last established sending team may recover a dropped assembly; a receiver cannot pick it up to bypass an airborne handover. No reset, respawn or history erasure.':
        None,
    'A timber may be dropped, pushed or dragged. If an arm that was not holding a timber when it dropped picks it up, none of that timber\'s handovers counts: put it down, let the arms that were holding it when it dropped lift it again, and hand it over again in the air.':
        'A timber that falls may be lifted again by the arms that held it when it fell. If any other arm picks it up, none of that timber\'s handovers counts until it is put down, lifted again by those arms and handed over again in the air. Pushing or dragging a timber along the table is allowed but is never a handover.',
}


def _spaced(text):
    """Some texts were written without spaces between words and numbers ('within4degrees',
    'and600g'). Only sentences are changed, never identifiers."""
    import re
    if ' ' not in text: return text
    text = re.sub(r'(?<=[a-z])(?=[+-]?\d)', ' ', text)
    text = re.sub(r'(?<=\d)(?=[a-z]{2,})', ' ', text)
    text = re.sub(r'(?<=\d)[,;](?=\d)', lambda m: m.group(0)+' ', text)
    return re.sub(r'(?<=[,;])(?=[+-]?\d)', ' ', text)


def _sentences(value):
    if isinstance(value, dict): return {k: _sentences(v) for k, v in value.items()}
    if isinstance(value, list): return [_sentences(v) for v in value]
    return _spaced(value) if isinstance(value, str) else value


def _drop(value, names):
    if isinstance(value, dict):
        return {k: _drop(v, names) for k, v in value.items() if k not in names and v is not None}
    if isinstance(value, list):
        return [_drop(v, names) for v in value]
    return value


def clean(public):
    """The public task without bookkeeping, engineering notes or labels, and with the release's
    rule wording. Applied once when the release's public files are written (build_release.py
    public); idempotent."""
    result = {k: deepcopy(v) for k, v in public.items() if k not in INTERNAL}
    family = result['family']
    if 'mechanism' in result:
        result['mechanism'] = _sentences(_drop(result['mechanism'], MECHANISM_INTERNAL))
        if result['mechanism'].get('cube_material') == 'Solid wood; inherited nominal density':
            result['mechanism']['cube_material'] = 'Solid wood'
    if isinstance(result.get('completion'), dict):
        result['completion'] = _drop(result['completion'], COMPLETION_INTERNAL)
    result['objective'] = OBJECTIVES[family]
    rules = []
    for rule in result['rules']:
        rule = RULES.get(rule, rule)
        if rule is None: continue
        rules.append(_spaced(rule))
    result['rules'] = rules
    return result
