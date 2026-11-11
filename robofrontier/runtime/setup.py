"""Prepare immutable inputs and durable runtime, without starting simulation/inference."""
import hashlib
import json
from pathlib import Path
import secrets
import shutil

from .store import RuntimeStore, packed
from ..physics.observation_image import DEFAULT_PROFILE, observation_profile
from ..tasks.provenance import environment_logic_manifest
from . import layout as run_layout, tool_mode
from .bootstrap import SKILLS_HEADER, write_bootstraps
from ..tasks.config import ROOT, load_task, load_harness, public_task,physical_control_fingerprint
from ..io import write_json


# Every robofrontier/**/*.py is frozen for each run; these are an engine's other sources.
ENGINE_SCRIPTS = {
    'codex': ('robofrontier/engines/codex/codex_rpc.js', 'robofrontier/engines/codex/codex_policy_host.js',
              'robofrontier/engines/codex/codex_preflight.js', 'robofrontier/engines/codex/tool_broker.js',
              'robofrontier/engines/codex/gateway_rpc.js', 'robofrontier/engines/codex/job_gateway.js', 'robofrontier/engines/codex/borrowed_auth.js'),
    'claude': (),
    'antigravity': (),
}


def prepare_run(directory, task_path=None, harness_path=None, private_puzzle_path=None):
    directory = Path(directory).resolve()
    if directory.exists():
        raise ValueError('Choose a new run directory; existing runs are never overwritten')
    task, cfg = load_task(task_path), load_harness(harness_path)
    # New runs use one public name; already frozen runs keep their original ID.
    cfg['coordinator'] = 'Controller'
    # Freeze new-run defaults; absent fields in already prepared runs remain legacy.
    cfg.setdefault('observation_image_profile', DEFAULT_PROFILE)
    # Letter labels sit beside each robot, as in this run's videos.
    cfg.setdefault('robot_labels', 'beside-robot-v1')
    image_profile = observation_profile(cfg)
    puzzle=None;puzzle_relative=None
    if task.get('family')=='dial':
        n=len(task['dials'])
        from ..tasks.dial import alphabet
        values_allowed=alphabet(task)
        # Every run of a Dial case uses the case's fixed code from the release; an engineering
        # run may name another.
        from ..tasks.families import dial_code
        puzzle=json.loads(Path(private_puzzle_path).read_text()) if private_puzzle_path else {'code_symbols':dial_code(task['id'])}
        values=puzzle.get('code_symbols')
        if set(puzzle)!={'code_symbols'} or not isinstance(values,list) or len(values)!=n or any(type(x) is not int or x not in values_allowed for x in values):raise ValueError('Expected one configured private nonzero symbol per suite dial')
        puzzle_relative=Path('private/inputs/suite-code.json')
    elif private_puzzle_path is not None:
        raise ValueError('Private puzzle input applies only to Dial')
    directory.mkdir(parents=True)
    for name in ('public/inputs/roles', 'public/observations', 'public/results', 'private/inputs',
                 'private/state/connections', 'private/state/client-state', 'private/outputs', *run_layout.FOLDERS):
        (directory/name).mkdir(parents=True)
    from ..tasks.scene import freeze_scene
    task=freeze_scene(task,directory)
    write_json(directory/'private/inputs/task.json', task)
    if puzzle is not None:
        write_json(directory/puzzle_relative,puzzle)
    public = public_task(task)
    from ..tasks.families import freeze_public
    family_release = freeze_public(task, directory, public)
    from ..tasks.scene import camera_names
    public['cameras'] = camera_names(task)
    for key,name in (('robot_layout_image','robot-layout.png'),('camera_calibration','camera-guide.json')):
        # Like every other task.json reference, relative to public/inputs/.
        if (directory/'public/inputs'/name).is_file():public[key]=name
    public['observation_image'] = {k: image_profile[k] for k in ('width', 'height', 'format')}
    if 'quality' in image_profile: public['observation_image']['quality'] = image_profile['quality']
    # Preserve the signed family asset; publish a run-specific calibration copy
    # only when its original declares an image size. Camera pose/FOV stays fixed.
    calibration_ref = public.get('camera_calibration')
    if calibration_ref:
        calibration_path = directory/'public/inputs'/calibration_ref.removeprefix('public/inputs/')
        if calibration_path.is_file():
            calibration = json.loads(calibration_path.read_text())
            if 'image_size_pixel' in calibration:
                calibration['image_size_pixel'] = [image_profile['width'], image_profile['height']]
                calibration['source_calibration'] = calibration_ref
                calibration['scope'] = str(calibration.get('scope', 'Camera calibration')) + '; image size matches this run observation profile'
                if family_release is not None and calibration_ref == 'family/'+calibration_path.name:
                    # The policy sees one calibration, sized for this run; the signed
                    # release copy moves to private/ and keeps its recorded hash.
                    original = directory/'private/inputs/release-family'/calibration_path.name
                    original.parent.mkdir()
                    shutil.move(calibration_path, original)
                    calibration['source_calibration'] = str(original.relative_to(directory))
                    family_release['public_files'][str(original.relative_to(directory))] = \
                        family_release['public_files'].pop('public/inputs/family/'+calibration_path.name)
                    write_json(calibration_path, calibration)
                else:
                    derived = directory/'public/inputs/observation-camera-calibration.json'
                    write_json(derived, calibration)
                    public['camera_calibration'] = 'observation-camera-calibration.json'
    write_json(directory/'public/inputs/task.json', public)
    write_json(directory/'private/inputs/harness.json', cfg)
    roles = {cfg['manager']: {'kind':'manager'}}
    if cfg['topology'] == 'hierarchical':
        roles[cfg['coordinator']] = {'kind':'team-controller'}
    if cfg['topology'] in ('centralized','adaptive'):
        roles['Controller'] = {'kind':'controller', 'robots':list(task['arms'])}
    else:
        roles.update({a: {'kind':'worker', 'robot':a} for a in task['arms']})
    write_json(directory/'public/inputs/roles.json', {'topology':cfg['topology'], 'manager':cfg['manager'], 'coordinator':cfg['coordinator'] if cfg['topology']=='hierarchical' else None, 'roles':roles})
    templates = ROOT/'prompts'
    # Passages that depend on the role's tools are marked in the templates (tool_mode.render).
    mode = tool_mode.of(cfg)
    rules = tool_mode.render((templates/'rules.md').read_text(), mode).replace('{{RUN_DIR}}',str(directory))
    (directory/'public/inputs/rules.md').write_text(rules)
    shutil.copytree(templates/'skills/robot-collaboration', directory/'public/inputs/skill')
    for template in sorted((directory/'public/inputs/skill').rglob('*.md')):
        text = template.read_text()
        rendered = tool_mode.render(text, mode)
        if rendered != text: template.write_text(rendered)
    # The run's shared lessons file, inside the policy's only writable folder. Its
    # rules live in the frozen Skill, which no role can edit.
    (directory/run_layout.LAYOUTS[run_layout.CURRENT]['skills_file']).write_text(SKILLS_HEADER)
    # Meta is engineering, outside the policy team: its role file and runbook stay private.
    (directory/'private/inputs/meta').mkdir()
    runbook=(ROOT/'docs/meta-runbook.md').read_text()
    for target in ('architecture.md','harness-verification.md'):
        runbook=runbook.replace(']('+target+')','](frozen-source/docs/'+target+')')
    runbook=runbook.replace('](../prompts/','](frozen-source/prompts/')
    (directory/'private/inputs/meta/meta-runbook.md').write_text(runbook)
    python = ROOT/'.venv/bin/python'
    for actor, info in roles.items():
        kind = info['kind']
        filename = {'manager':'meta-manager','team-controller':'team-controller','worker':'worker','controller':'single-controller'}[kind]
        if kind=='controller' and cfg['topology']=='adaptive':filename='adaptive-controller'
        values = {'RUN_DIR':str(directory),'REPO_ROOT':str(ROOT),'PYTHON':str(python), 'ACTOR':actor,
                  'CONNECTION':str(directory/'private/state/connections'/f'{actor}.json'),
                  'TOPOLOGY':cfg['topology'],
                  'FINISH_AUTHORITY':cfg['coordinator'] if cfg['topology']=='hierarchical' else 'any peer Worker' if cfg['topology']=='peer' else 'Controller',
                  'COMMUNICATION_ROUTE':('Coordinate joint commitments and shared resources through '+cfg['coordinator']+'. Worker-to-Worker business messages are unavailable.' if cfg['topology']=='hierarchical' else 'Negotiate affected commitments and shared resources directly with relevant Workers.')}
        text = (templates/'roles'/f'{filename}.md').read_text()
        for key,value in values.items():
            text = text.replace('{{'+key+'}}',value)
        role_file = directory/('private/inputs/meta' if kind=='manager' else 'public/inputs/roles')/f'{actor}.md'
        role_file.write_text(text)
        connection = directory/'private/state/connections'/f'{actor}.json'
        write_json(connection, {'schema_version':3, 'run_id':directory.name, 'url':None,
                                'actor':actor, 'token':secrets.token_urlsafe(24)})
        connection.chmod(0o600)
    store = RuntimeStore(directory/'private/state/runtime.sqlite')
    store.initialize(directory.name, cfg, task['arms'])
    store.close()
    # The Python its scripts use, named by the trusted launcher; earlier-style runs have none.
    from . import policy_env
    if policy_env.selected() is not None and mode != tool_mode.ROBOT_ONLY:
        policy_env.prepare_run(directory, policy_env.selected())
    # One frozen first message per policy role, sent unchanged by either engine.
    write_bootstraps(directory)
    # What the policy may read and write, rendered by each engine's own sandbox.
    from .access import record as access_record
    write_json(directory/'private/inputs/policy-access.json',
               access_record(directory, no_environment=mode == tool_mode.ROBOT_ONLY))
    if cfg.get('engine') == 'antigravity' and mode != tool_mode.ROBOT_ONLY:
        # The brokered file tools of a full run; a robot_only run has none.
        from robofrontier.engines.antigravity.settings import prepare_tools
        prepare_tools(directory)
    paths = list((ROOT/'robofrontier').rglob('*.py'))
    paths += [path for path in (ROOT/'prompts').rglob('*.md') if 'archive' not in path.relative_to(ROOT/'prompts').parts]
    # Freeze only the policy-host scripts of this run's engine, so editing the other
    # engine's host never invalidates a prepared batch. Meta's dispatcher serves both.
    paths += [ROOT/'robofrontier/engines/codex/meta_dispatcher.js']
    paths += [ROOT/name for name in ENGINE_SCRIPTS[cfg.get('engine','codex')]]
    paths += [ROOT/'docs'/name for name in ('meta-runbook.md','architecture.md','harness-verification.md')]
    source_hashes = {}
    for source in paths:
        if not source.is_file():
            continue
        relative = source.relative_to(ROOT)
        dest = directory/'private/inputs/frozen-source'/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest)
        source_hashes[str(relative)] = hashlib.sha256(source.read_bytes()).hexdigest()
    inputs = {}
    for p in sorted((directory/'public/inputs').rglob('*')):
        if p.is_file():inputs[str(p.relative_to(directory))] = hashlib.sha256(p.read_bytes()).hexdigest()
    for p in (directory/'private/inputs/scene').rglob('*'):
        if p.is_file():inputs[str(p.relative_to(directory))]=hashlib.sha256(p.read_bytes()).hexdigest()
    if puzzle is not None:
        p=directory/puzzle_relative
        inputs[str(puzzle_relative)]=hashlib.sha256(p.read_bytes()).hexdigest()
    p=directory/'private/inputs/policy-access.json'
    inputs[str(p.relative_to(directory))]=hashlib.sha256(p.read_bytes()).hexdigest()
    p=directory/'private/inputs/policy-tools.json'
    if p.is_file():
        inputs[str(p.relative_to(directory))]=hashlib.sha256(p.read_bytes()).hexdigest()
    for folder in ('private/inputs/meta','private/inputs/bootstrap','private/inputs/release-family'):
        for p in sorted((directory/folder).glob('*')):
            if p.is_file():inputs[str(p.relative_to(directory))]=hashlib.sha256(p.read_bytes()).hexdigest()
    if family_release is not None:
        p=directory/'private/inputs/family-release.json'
        inputs[str(p.relative_to(directory))]=hashlib.sha256(p.read_bytes()).hexdigest()
    logic=environment_logic_manifest(source_hashes,task) if task.get('kind')=='frontier_suite' else None
    write_json(directory/'private/inputs/manifest.json', {'schema_version':3,'run_id':directory.name,
        **run_layout.manifest_record(cfg.get('engine','codex')),
        'task_sha256':hashlib.sha256(packed(task).encode()).hexdigest(),
        'harness_sha256':hashlib.sha256(packed(cfg).encode()).hexdigest(),
        'source_sha256':source_hashes,'input_sha256':inputs,
        'physical_control_sha256':physical_control_fingerprint(source_hashes,cfg),
        'environment_logic_sha256':logic['sha256'] if logic else None,
        'environment_logic_provenance':logic,
        'engine':cfg.get('engine','codex'),
        'model_requested':cfg['model'],'effort_requested':cfg['effort'],
        'family_release':family_release,
        'observation_contract':task['observation_contract'],
        'manager':'Meta session executes deterministic dispatcher; no independent desktop takeover',
        'isolation':('Role authentication and protocol/integrity checks; policies have the robot tool alone, with no '
                     'shell, code execution or file tool: they read this run\'s public/ folder and extend its shared '
                     'lessons only through that tool'
                     if mode == tool_mode.ROBOT_ONLY else
                     'Role authentication and protocol/integrity checks, plus each engine\'s file sandbox: '
                     + ('policies write only inside workspace/ and /tmp, and read only those, public/, the operating '
                        'system and the frozen Python environment'
                        if json.loads((directory/'private/inputs/policy-access.json').read_text()).get('policy_env') else
                        'policies write only inside workspace/ and temporary folders, and cannot read private/, '
                        'other runs, source code, configuration or credentials')),
        'physical_restart':'unsupported; interrupted worlds require a new run',
        'status':'prepared; no simulator or inference started'})
    return directory


def verify_inputs(directory, *, source_root=None):
    directory = Path(directory)
    try:
        manifest = json.loads((directory/'private/inputs/manifest.json').read_text())
    except (OSError,ValueError):
        return ['manifest:unreadable']
    if not isinstance(manifest,dict):
        return ['manifest:invalid']
    if manifest.get('schema_version') != 3:
        return ['manifest:unsupported_schema']
    if not all(isinstance(manifest.get(k),dict) for k in ('source_sha256','input_sha256')) or not all(isinstance(manifest.get(k),str) for k in ('task_sha256','harness_sha256')):
        return ['manifest:invalid']
    changed = []
    for filename,key in [('task.json','task_sha256'),('harness.json','harness_sha256')]:
        try:
            actual=hashlib.sha256(packed(json.loads((directory/'private/inputs'/filename).read_text())).encode()).hexdigest()
        except (OSError,ValueError):
            actual=None
        if actual!=manifest[key]:changed.append('private:'+filename)
    for relative,digest in manifest['source_sha256'].items():
        p = (Path(source_root) if source_root is not None else ROOT)/relative
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            changed.append('source:'+relative)
        frozen=directory/'private/inputs/frozen-source'/relative
        if not frozen.is_file() or hashlib.sha256(frozen.read_bytes()).hexdigest()!=digest:
            changed.append('frozen:'+relative)
    for relative,digest in manifest['input_sha256'].items():
        p = directory/relative
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            changed.append('input:'+relative)
    return changed
