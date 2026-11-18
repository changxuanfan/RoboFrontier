"""Resolve released task type inputs and freeze only their permitted public facts.

The release records which scene and reviewed public projection a policy trial uses.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from ..io import file_sha256 as sha
from ..io import ROOT

RELEASE = 'benchmark/release.json'
READINESS = 'prepared_policy_trial'


def read(path):
    return json.loads(Path(path).read_text())


def resolve_case(case_id, root=ROOT):
    root = Path(root)
    release = read(root/RELEASE)
    matches = [(name, task_type, c) for name, task_type in release['families'].items()
               for c in task_type['policy'] if c['id'] == case_id]
    if len(matches) != 1:
        raise ValueError('Case must identify exactly one released task type input')
    name, task_type, case = matches[0]
    for path, checksum in case['source_files'].items():
        if sha(root/case['directory']/path) != checksum:
            raise ValueError('Released scene metadata changed: '+case_id+'/'+path)
    return name, task_type, case


# New Relay runs count a timber as complete only after a qualified airborne handover.
RELAY_HANDOVER_RULE = 'relay-airborne-handover-v1'
RELAY_HANDOVER_DEFINITION = ('A handover qualifies only while the timber is off the table and at least two current holders '
    'keep it: a new arm must hold the timber for at least 0.2 seconds before a current holder lets go. A timber placed in GOAL '
    'without a qualified handover is not complete; a regrasp of a timber resting on the table is never a handover.')
# A timber may be dropped or pushed. If a receiver picks a dropped timber up, none of its
# handovers counts until the arms that were holding it when it fell lift it again and hand
# it over again (evaluate.Relay).
RELAY_RECOVERY_RULE = ('A timber may be dropped, pushed or dragged. If an arm that was not holding a timber when it '
    'dropped picks it up, none of that timber\'s handovers counts: put it down, let the arms that were holding it when it '
    'dropped lift it again, and hand it over again in the air.')


# A policy run counts its wall limit as active running time (clock.BudgetGuard): only time
# the world is running unpaused counts; host stalls, pauses and network outages do not.
from roboteam.runtime.time.clock import ACTIVE_CLOCK as ACTIVE_TIME_CLOCK
# Active time does not end a hung run, so a run also stops once this much wall time has
# passed since START (clock.BudgetGuard). A run stopped this way needs review and is not
# counted.
WALL_BACKSTOP_S = 172800


def protocol_for(case, release_sha256, wall_limit_s=86400):
    import math
    if isinstance(wall_limit_s, bool) or not isinstance(wall_limit_s, (int,float)) or not math.isfinite(wall_limit_s) or not 0 < wall_limit_s <= 86400:
        raise ValueError('Invalid policy wall limit')
    protocol = dict(kind='policy_trial', launch='explicit_manager_start',
        release_sha256=release_sha256, case_id=case['id'],
        source_task_sha256=case['source_files']['task.json'],
        source_scene_sha256=case['source_files']['scene.xml'],
        total_wall_limit_s=wall_limit_s,
        clock=ACTIVE_TIME_CLOCK, wall_backstop_s=WALL_BACKSTOP_S, evaluation_semantics='terminal_outcome_v2',
        experience='fresh_run_only', presentation_loop=False)
    if case['id'].startswith('relay-'):
        protocol['relay_completion_rule'] = RELAY_HANDOVER_RULE
    return protocol


def dial_code(case_id, root=ROOT):
    """The Dial case's fixed secret code, from the private part of the release."""
    codes = read(Path(root)/RELEASE).get('private', {}).get('dial_codes', {})
    if case_id not in codes:
        raise ValueError('The release has no code for '+case_id)
    return list(codes[case_id])


def policy_task(case_id, root=ROOT, wall_limit_s=86400):
    name, task_type, case = resolve_case(case_id, root=root)
    task = read(Path(root)/case['directory']/'task.json')
    task['execution_readiness'] = READINESS
    task['run_protocol'] = protocol_for(case, sha(Path(root)/RELEASE), wall_limit_s)
    return task


def validate_policy_task(task, root=ROOT):
    protocol = task.get('run_protocol', {})
    if (protocol.get('kind') != 'policy_trial'
            or protocol.get('launch') != 'explicit_manager_start'
            or protocol.get('experience') != 'fresh_run_only'
            or protocol.get('presentation_loop') is not False
            or not isinstance(protocol.get('total_wall_limit_s'), (int, float))):
        raise ValueError('Invalid released policy protocol')
    _, _, case = resolve_case(task['id'], root=root)
    if (protocol != protocol_for(case, sha(Path(root)/RELEASE), protocol['total_wall_limit_s'])
            or protocol.get('case_id') != task['id']
            or protocol.get('source_task_sha256') != case['source_files']['task.json']
            or protocol.get('source_scene_sha256') != task['scene_sha256']
            or task.get('oracle_verified') is not False):
        raise ValueError('Policy source/release binding differs')
    original = read(Path(root)/case['directory']/'task.json')
    expected = deepcopy(original)
    expected['execution_readiness'] = READINESS
    expected['run_protocol'] = protocol
    if task != expected:
        raise ValueError('Policy task changed outside its execution protocol')
    return protocol


def freeze_public(task, directory, public, root=ROOT):
    """Give a run its case's public task and task materials, as the release wrote them.

    `public` is replaced by the case's public/task.json, keeping only this run's own
    protocol and image profile (scripts/release/build_release.py public). The materials go to public/inputs/family/,
    with the task guide from prompts/guides."""
    if task.get('execution_readiness') != READINESS:
        return None
    root, directory = Path(root), Path(directory)
    task_type_name, _, case = resolve_case(task['id'], root=root)
    projection = case['public_projection']
    if sha(root/projection['path']) != projection['sha256']:
        raise ValueError('Released public task changed')
    own = {key: public[key] for key in ('observation_image',) if key in public}
    public.clear(); public.update(read(root/projection['path'])); public.update(own)
    task_type_dir = directory/'public/inputs/family'
    task_type_dir.mkdir()
    hashes = {}
    sources = {name: root/source['path'] for name, source in case['public_files'].items()}
    for name, source in case['public_files'].items():
        if Path(name).name != name or sha(root/source['path']) != source['sha256']:
            raise ValueError('Invalid/changed public task type file: '+name)
    sources['skill.md'] = root/'prompts/guides'/(task_type_name+'.md')
    for name, source in sorted(sources.items()):
        shutil.copyfile(source, task_type_dir/name)
        hashes['public/inputs/family/'+name] = sha(source)
    # The scene's own copy of the Mosaic target image is superseded by the task type copy.
    target_image = directory/'public/inputs/target-pattern.png'
    if target_image.is_file() and (task_type_dir/target_image.name).is_file():
        target_image.unlink()
    private_release = directory/'private/inputs/release.json'
    shutil.copyfile(root/RELEASE, private_release)
    return dict(release_sha256=sha(private_release), task_type=task_type_name, case_id=task['id'],
                public_files=hashes, public_projection=projection)


def prepare(case_id, directory, run_settings=None, private_puzzle_path=None, wall_limit_s=86400):
    """Prepare only; simulator, role sessions and model inference stay stopped."""
    import tempfile
    from roboteam.runtime.run.setup import prepare_run
    task = policy_task(case_id, wall_limit_s=wall_limit_s)
    with tempfile.TemporaryDirectory(prefix='roboteam-policy-') as temporary:
        path = Path(temporary)/'task.json'
        path.write_text(json.dumps(task, ensure_ascii=False)+'\n')
        return prepare_run(directory, path, run_settings, private_puzzle_path)


def validate_frozen_policy(task, directory):
    """START checks the actual frozen release and scene, including task metadata."""
    directory = Path(directory)
    release = directory/'private/inputs/release.json'
    protocol = task['run_protocol']
    if sha(release) != protocol['release_sha256']:
        raise ValueError('Frozen policy release differs')
    cases = [c for f in read(release)['families'].values() for c in f['policy']
             if c['id'] == task['id']]
    if len(cases) != 1:
        raise ValueError('Policy case is not in the frozen release')
    case = cases[0]
    if protocol != protocol_for(case, sha(release), protocol['total_wall_limit_s']):
        raise ValueError('Frozen policy protocol differs')
    source = directory/Path(task['scene_asset']).parent
    for name, expected in case['source_files'].items():
        if sha(source/name) != expected:
            raise ValueError('Frozen policy scene metadata differs: '+name)
    original = read(source/'task.json')
    original.update(scene_asset=task['scene_asset'], execution_readiness=READINESS,
                    run_protocol=protocol)
    if original != task:
        raise ValueError('Frozen policy task differs from its released scene')
    return protocol
