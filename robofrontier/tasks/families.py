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
    'without a qualified handover is not complete; a regrasp of a timber resting on the table is never a handover.')
# A timber may be dropped or pushed. If a receiver picks a dropped timber up, none of its
# handovers counts until the arms that were holding it when it fell lift it again and hand
# it over again (evaluate.Relay).
RELAY_RECOVERY_RULE = ('A timber may be dropped, pushed or dragged. If an arm that was not holding a timber when it '
    'dropped picks it up, none of that timber\'s handovers counts: put it down, let the arms that were holding it when it '
    'dropped lift it again, and hand it over again in the air.')


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


def case_specs(root=ROOT):
    """Each released case's catalog row: id, family, level, arm count and scene revision."""
    release = read(Path(root)/RELEASE)
    return [row for family in release['families'].values() for row in read(Path(root)/family['catalog']['path'])['cases']]


FOLDERS = {'transport': 'cube_transport', 'mosaic': 'mosaic', 'relay': 'beam_handoff', 'dial': 'spring_dial'}


def oracle_directory(case, root=ROOT):
    """The Oracle's copy of a released case: the scene its recordings were made with.

    A case row naming an earlier scene revision resolves to that revision's folder,
    where an Oracle recording of it was made (configs/environments)."""
    if isinstance(case, str): return Path(root)/'benchmark/oracle'/case
    revision = case.get('scene_revision', 1)
    prefix = 'frontier-v2-' if revision == 1 else f'frontier-v2-r{revision}-'
    return Path(root)/current_path(f"configs/environments/{FOLDERS[case['family']]}/{prefix}{case['id']}", root)


def dial_code(case_id, root=ROOT):
    """The Dial case's fixed secret code, from the private part of the release."""
    codes = read(Path(root)/RELEASE).get('private', {}).get('dial_codes', {})
    if case_id not in codes:
        raise ValueError('The release has no code for '+case_id)
    return list(codes[case_id])


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
    """Give a run its case's public task and family materials, as the release wrote them.

    `public` is replaced by the case's public/task.json, keeping only this run's own
    protocol and image profile (scripts/build_release.py public). The materials go to public/inputs/family/,
    with the family skill from prompts/skills."""
    if task.get('execution_readiness') != READINESS:
        return None
    root, directory = Path(root), Path(directory)
    family_name, _, case = resolve_case(task['id'], root=root)
    projection = case['public_projection']
    if sha(root/projection['path']) != projection['sha256']:
        raise ValueError('Released public task changed')
    own = {key: public[key] for key in ('observation_image',) if key in public}
    public.clear(); public.update(read(root/projection['path'])); public.update(own)
    family_dir = directory/'public/inputs/family'
    family_dir.mkdir()
    hashes = {}
    sources = {name: root/source['path'] for name, source in case['public_files'].items()}
    for name, source in case['public_files'].items():
        if Path(name).name != name or sha(root/source['path']) != source['sha256']:
            raise ValueError('Invalid/changed public family file: '+name)
    sources['skill.md'] = root/'prompts/skills'/family_name/'SKILL.md'
    for name, source in sorted(sources.items()):
        shutil.copyfile(source, family_dir/name)
        hashes['public/inputs/family/'+name] = sha(source)
    # The scene's own copy of the Mosaic target image is superseded by the family copy.
    target_image = directory/'public/inputs/target-pattern.png'
    if target_image.is_file() and (family_dir/target_image.name).is_file():
        target_image.unlink()
    private_release = directory/'private/inputs/family-release.json'
    shutil.copyfile(root/RELEASE, private_release)
    return dict(release_sha256=sha(private_release), family=family_name, case_id=task['id'],
                public_files=hashes, public_projection=projection)


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
