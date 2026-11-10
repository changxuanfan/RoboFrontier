"""Resolve released family inputs and freeze only their permitted public facts.

Historical Oracle registries remain immutable. This release records which scene
and reviewed public projection a new policy trial actually uses.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from ..io import file_sha256 as sha
from ..io import ROOT

RELEASE = 'benchmark/release.json'
LEGACY_PATHS = 'benchmark/legacy-paths.json'
READINESS = 'prepared_policy_trial'


def read(path):
    return json.loads(Path(path).read_text())


def _moved(root):
    path = Path(root)/LEGACY_PATHS
    return read(path if path.is_file() else ROOT/LEGACY_PATHS)['paths']


def current_path(name, root=ROOT):
    """Where a file that a frozen record names by an earlier path lives now."""
    name = str(name)
    moved = _moved(root)
    for old in sorted(moved, key=len, reverse=True):
        if name == old or name.startswith(old+'/'):
            return moved[old]+name[len(old):]
    return name


def oracle_recording(name, root=ROOT):
    """The motion folder a released Oracle row names, on this host.

    Some rows name the checkout they were recorded in; legacy-paths maps those to
    their place under root. The recorded location is still accepted where it exists."""
    mapped = Path(current_path(name, root))
    candidates = list(dict.fromkeys([Path(root)/mapped, Path(name)]))
    for path in candidates:
        if path.is_dir():
            return path
    raise FileNotFoundError('Released Oracle recording is not on this host: '+str(name)
                            +' (looked in '+', '.join(map(str, candidates))+')')


def legacy_bytes(name, root=ROOT):
    """A released file's bytes as recorded before the benchmark/ move; only path text changed."""
    import re
    moved = _moved(root)
    data = (Path(root)/current_path(name, root)).read_bytes()
    back = {new.encode(): old.encode() for old, new in moved.items() if Path(new).parts[0] == 'benchmark'}
    pattern = re.compile(b'(' + b'|'.join(re.escape(n) for n in sorted(back, key=len, reverse=True)) + rb')(?![A-Za-z0-9_.-])')
    return pattern.sub(lambda m: back[m.group(1)], data)


def resolve_case(case_id, purpose='gpt', root=ROOT):
    root = Path(root)
    release = read(root/RELEASE)
    if purpose not in ('gpt', 'oracle'):
        raise ValueError('Unknown task purpose')
    matches = [(name, family, c) for name, family in release['families'].items()
               for c in family[purpose] if c['id'] == case_id]
    if len(matches) != 1:
        raise ValueError('Case must identify exactly one released family input')
    name, family, case = matches[0]
    for path, checksum in case['source_files'].items():
        if sha(root/case['directory']/path) != checksum:
            raise ValueError('Released scene metadata changed: '+case_id+'/'+path)
    return name, family, case


# New Relay runs count a timber as complete only after a qualified airborne handover.
RELAY_HANDOVER_RULE = 'relay-airborne-handover-v1'
RELAY_HANDOVER_DEFINITION = ('A handover qualifies only while the timber is off the table and at least two current holders '
    'keep it: a new arm must hold the timber for at least 0.2 seconds before a current holder lets go. A timber placed in GOAL '
    'without a qualified handover is not complete. Pushing or dragging a timber along the table never counts as transport.')


# New policy runs count their wall limit as active running time (policy_probe.BudgetGuard):
# only time the world is running unpaused counts; host stalls, pauses and network outages
# do not. Runs frozen without this field keep the START wall-clock rule.
ACTIVE_TIME_CLOCK = 'active_time_v1'
# Active time no longer ends a hung run, so those runs also stop once this much wall time has
# passed since START (policy_probe.BudgetGuard). A run stopped this way needs review and is not
# counted. Runs frozen without this field have no backstop.
WALL_BACKSTOP_S = 172800


def protocol_for(case, release_sha256, wall_limit_s=86400):
    import math
    if isinstance(wall_limit_s, bool) or not isinstance(wall_limit_s, (int,float)) or not math.isfinite(wall_limit_s) or not 0 < wall_limit_s <= 86400:
        raise ValueError('Invalid policy wall limit')
    protocol = dict(kind='policy_trial', launch='explicit_manager_start',
        release_sha256=release_sha256, case_id=case['id'],
        source_task_sha256=case['source_files']['task.json'],
        source_scene_sha256=case['source_files']['scene.xml'],
        reference_evidence=case['qualification'], total_wall_limit_s=wall_limit_s,
        clock=ACTIVE_TIME_CLOCK, wall_backstop_s=WALL_BACKSTOP_S, evaluation_semantics='terminal_outcome_v2',
        experience='fresh_run_only', presentation_loop=False)
    if case['id'].startswith('relay-'):
        protocol['relay_completion_rule'] = RELAY_HANDOVER_RULE
    return protocol


def expected_protocol(case, protocol, release_sha256):
    """The protocol a task should carry; runs frozen before the handover rule, the
    active-time clock or the wall backstop keep their own terms."""
    expected = protocol_for(case, release_sha256, protocol['total_wall_limit_s'])
    if 'relay_completion_rule' not in protocol:
        expected.pop('relay_completion_rule', None)
    if 'clock' not in protocol:
        expected.pop('clock', None)
    if 'wall_backstop_s' not in protocol:
        expected.pop('wall_backstop_s', None)
    return expected


def policy_task(case_id, root=ROOT, wall_limit_s=86400):
    name, family, case = resolve_case(case_id, root=root)
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
    if (protocol != expected_protocol(case, protocol, sha(Path(root)/RELEASE))
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
    """Copy allowlisted family guidance and overlay its reviewed static facts."""
    if task.get('execution_readiness') != READINESS:
        return None
    root, directory = Path(root), Path(directory)
    family_name, _, case = resolve_case(task['id'], root=root)
    projection = case.get('public_projection')
    review = {}
    if projection:
        if sha(root/projection['path']) != projection['sha256']:
            raise ValueError('Reviewed public task changed')
        review = read(root/projection['path'])
        if review['id'] != task['id'] or review['family'] != family_name:
            raise ValueError('Public projection belongs to another task')
    keys = ('completion', 'workspace_world_m', 'table_height_m', 'table_geometry',
            'static_geometry', 'static_workstation', 'static_camera_mounts',
            'process_requirements', 'task_revision', 'scene_revision',
            'source_scene_sha256', 'initial_supplies', 'target', 'mechanism',
            'rules', 'objective', 'observation_contract', 'gripper_profile', 'dials')
    for key in keys:
        if key in review:
            public[key] = deepcopy(review[key])
    public.setdefault('completion', deepcopy(task['completion']))
    public.setdefault('workspace_world_m', deepcopy(task['workspace_world_m']))
    terminal = task.get('run_protocol', {}).get('evaluation_semantics') == 'terminal_outcome_v2'
    terminal_relay = family_name == 'relay' and terminal
    if terminal and family_name == 'transport':
        acceptance = public['completion'].get('acceptance', {})
        if 'process_compliance_required' in acceptance: acceptance['process_compliance_required'] = False
    if terminal and family_name == 'mosaic':
        if 'process_violations_clear_required' in public['completion']:
            public['completion']['process_violations_clear_required'] = False
    if terminal and family_name == 'dial':
        public['completion']['success_semantics'] = 'Unlock once with a simultaneous valid correct input; success remains latched after later dial changes.'
    if terminal_relay:
        from .relay import RULE_REVISION
        timber_fraction_rule = task.get('completion', {}).get('rule_revision') == RULE_REVISION
        if timber_fraction_rule:
            # A reviewed legacy projection must not overwrite the versioned
            # task's changed completion semantics or policy-facing rules.
            public['completion'] = deepcopy(task['completion'])
            public['rules'] = deepcopy(task['rules'])
        rules = public.get('rules', [])
        handover_rule = task.get('run_protocol', {}).get('relay_completion_rule') == RELAY_HANDOVER_RULE
        removed = ('Inside GOAL, original qualified holders',) if handover_rule else (
            'Airborne transport requires', 'Inside GOAL, original qualified holders', 'Drops and violations remain recorded.')
        public['rules'] = [rule for rule in rules if not rule.startswith(removed)]
        if handover_rule: public['rules'].append(RELAY_HANDOVER_DEFINITION)
        public['rules'].append('Collisions, drops and other process events are recorded separately. Recover using ordinary robot actions; do not reset, respawn or erase history.')
        public['completion']['required_airborne_handover'] = handover_rule
        if handover_rule:
            public['completion']['relay_completion_rule'] = RELAY_HANDOVER_RULE
            public['completion']['scope'] = 'Every timber has had a qualified airborne handover, is at least 70% above painted GOAL and is released; other process events are reported separately.'
        else:
            public['completion']['scope'] = ('Every timber at least 70% above painted GOAL and released; process events are reported separately.'
                                             if timber_fraction_rule else 'All assemblies released, actually supported and inside GOAL tolerance; process events are reported separately.')
    if terminal:
        # Released public projections carry three statements that contradict the
        # current task or address engineers; the private evaluator task is unchanged.
        if terminal_relay and timber_fraction_rule and 'finish' in public.get('mechanism', {}):
            public['mechanism']['finish'] = 'Tabletop destination region; no cradle'
        if family_name == 'mosaic':
            public['rules'] = [rule.split('. ')[0]+'.' if rule.startswith('Build the supplied') else rule
                               for rule in public.get('rules', [])]
        if family_name == 'transport':
            public.get('completion', {}).pop('scope', None)
    family_dir = directory/'public/inputs/family'
    family_dir.mkdir()
    hashes = {}
    # task.json is the only statement of what a terminal run requires; the family
    # Skill (how to do it well) comes from prompts/skills in place of released
    # guidance, which mostly repeated task.json. A relay case without the 70% timber
    # rule keeps its own terminal description.
    current, dropped = {}, set()
    if terminal and family_name in ('relay', 'transport', 'dial', 'mosaic'):
        current = {'skill.md': root/'prompts/skills'/family_name/'SKILL.md'}
        dropped = {'family-guidance.md', 'task-guide.md'}
        if terminal_relay and not timber_fraction_rule:
            current['family-guidance.md'] = root/'prompts/archive/tasks/relay-terminal-v2.md'
    for name, source in case['public_files'].items():
        if Path(name).name != name or sha(root/source['path']) != source['sha256']:
            raise ValueError('Invalid/changed public family file: '+name)
    delivered = (set(case['public_files']) - dropped) | set(current)
    for name in sorted(delivered):
        selected = current.get(name) or root/case['public_files'][name]['path']
        shutil.copyfile(selected, family_dir/name)
        hashes['public/inputs/family/'+name] = sha(selected)
    # The Mosaic target image joins the other family materials.
    target_image = directory/'public/inputs/target-pattern.png'
    if terminal and target_image.is_file() and isinstance(public.get('target'), dict):
        shutil.move(target_image, family_dir/target_image.name)
        public['target']['reference_image'] = 'family/'+target_image.name
        delivered.add(target_image.name)
    if 'family-guidance.md' in delivered:
        public['family_guidance'] = 'family/family-guidance.md'
    public['family_materials'] = sorted('family/'+n for n in delivered)
    for key, name in [('static_workstation', 'table-geometry.json')]:
        if key in public and name in case['public_files']:
            public[key]['geometry_reference'] = 'family/'+name
    if 'camera-calibration.json' in case['public_files']:
        public['camera_calibration'] = 'family/camera-calibration.json'
    if 'task-guide.md' in delivered:
        public['task_guide'] = 'family/task-guide.md'
    if 'skill.md' in delivered:
        public['task_skill'] = 'family/skill.md'
    if 'initial_reference_images' in review:
        images = review['initial_reference_images']
        if any(name not in case['public_files'] for name in images):
            raise ValueError('Unfrozen public reference image')
        public['initial_reference_images'] = ['family/'+name for name in images]
    private_release = directory/'private/inputs/family-release.json'
    shutil.copyfile(root/RELEASE, private_release)
    return dict(release_sha256=sha(private_release), family=family_name, case_id=task['id'],
                qualification=case['qualification'], public_files=hashes,
                public_projection=projection,
                public_overlay=sorted(str(path.relative_to(root)) for path in current.values()) or None)


def prepare(case_id, directory, harness=None, private_puzzle_path=None, wall_limit_s=86400):
    """Prepare only; simulator, role sessions and model inference stay stopped."""
    import tempfile
    from ..runtime.setup import prepare_run
    task = policy_task(case_id, wall_limit_s=wall_limit_s)
    with tempfile.TemporaryDirectory(prefix='robofrontier-policy-') as temporary:
        path = Path(temporary)/'task.json'
        path.write_text(json.dumps(task, ensure_ascii=False)+'\n')
        return prepare_run(directory, path, harness or ROOT/'configs/harnesses/policy.json', private_puzzle_path)


def validate_frozen_policy(task, directory):
    """START checks the actual frozen release and scene, including task metadata."""
    directory = Path(directory)
    release = directory/'private/inputs/family-release.json'
    protocol = task['run_protocol']
    if sha(release) != protocol['release_sha256']:
        raise ValueError('Frozen policy release differs')
    cases = [c for f in read(release)['families'].values() for c in f['gpt']
             if c['id'] == task['id']]
    if len(cases) != 1:
        raise ValueError('Policy case is not in the frozen release')
    case = cases[0]
    if protocol != expected_protocol(case, protocol, sha(release)):
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
