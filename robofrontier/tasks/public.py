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
    keys = ('kind', 'id', 'suite_version', 'family', 'level', 'arms', 'rules', 'objective', 'observation_contract',
            'gripper_profile', 'cameras', 'coordinate_frame', 'execution_readiness')
    result = {k: deepcopy(task[k]) for k in keys}
    # The host enforces the wall limit; policies plan as if time were unlimited, so it stays
    # private, with the clock a released policy trial counts it by and its wall backstop.
    if 'run_protocol' in task:
        private = ('total_wall_limit_s', 'clock', 'wall_backstop_s')
        result['run_protocol'] = {k: deepcopy(v) for k, v in task['run_protocol'].items() if k not in private}
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
    return result
