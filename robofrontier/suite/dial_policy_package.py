"""Read-only BEST5 family contract and evidence review; never prepares a run."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import mujoco

from .. import prompt_archive
from ..motion_recording import MotionReader
from ..robot_control import matrix_quat
from ..task_config import physical_control_fingerprint
from ..workstation import Workstation
from .provenance import bundle_manifest, environment_logic_manifest
from .v2 import public_task
from .dial_pose_timeline import PRESENTATION,DIAL_RECORD_HZ


CATALOG = 'benchmark/dial/catalog.json'
SELECTION = 'runs/oracle/dial-best5-recovery-20261026/batch-status.json'
REGISTRY = 'benchmark/dial/best5-r11.json'
# The registry records the guidance by its released path; its bytes now live in the archive.
GUIDANCE = 'prompts/tasks/dial-best5.md'
SHARED_INPUTS = ('prompts/rules.md', 'prompts/roles/adaptive-controller.md',
    'prompts/skills/robot-collaboration/SKILL.md',
    'prompts/skills/robot-collaboration/references/tools.md',
    'prompts/skills/robot-collaboration/references/adaptive.md',
    'prompts/skills/robot-collaboration/references/communication.md',
    'prompts/skills/robot-collaboration/references/motion-check.md',
    'configs/harness-frontier-v2-servo2.json')
BLOCKERS = (
    'Shared runtime must recognize version-bound formal readiness evidence.',
    'Shared preparation must select R11 and freeze the dial family guidance/projection.',
    'Confirm the new GPT experiment protocol and use a fresh policy context.',
)


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def store_relative(path, root):
    """Resolve shared data stores without committing machine-specific root paths."""
    path, root = Path(path).resolve(), Path(root).resolve()
    try:
        return str(path.relative_to(root))
    except ValueError:
        for name in ('runs', 'outputs'):
            try:
                return str(Path(name)/path.relative_to((root/name).resolve()))
            except ValueError:
                pass
    raise ValueError('Evidence outside the repository data stores')


def require_best5(task):
    spec = task.get('mechanism', {}).get('feedback', {})
    if (task.get('family') != 'dial' or task.get('scale', {}).get('scene_revision') != 11
            or spec.get('mode') != 'best_so_far' or spec.get('symbol_count') != 5
            or spec.get('step_deg') != 60 or not spec.get('require_red_grasp')):
        raise ValueError('Expected the R11 BEST5 dial family')


def selected_report(root, selected, pinned):
    """Locate a relocated closed report through its pinned relative identity.

    The original selection bytes may contain the author's absolute data root.
    Never follow that external path or rewrite it: match its complete logical
    suffix, then verify the independent local copy against the registered hash.
    """
    relative=Path(pinned['report'])
    if relative.is_absolute() or '..' in relative.parts or relative.parts[:2]!=('runs','oracle'):
        raise ValueError('Invalid pinned Oracle report path')
    original=Path(selected['report'])
    if original.parts[-len(relative.parts):]!=relative.parts:
        raise ValueError('Selected report differs from pinned logical path')
    path=Path(root)/relative
    if not path.resolve().is_relative_to((Path(root)/'runs').resolve()):
        raise ValueError('Selected report escapes the local evidence store')
    if digest(path)!=pinned['report_sha256']:
        raise ValueError('Selected Oracle report checksum mismatch')
    return path


def same_harness(frozen, current):
    """Admit the reviewed role-label rename, never a drive/limit change."""
    original=deepcopy(frozen)
    if original.get('coordinator')=='Coordinator' and current.get('coordinator')=='Controller':
        original['coordinator']='Controller'
    return original==current


def registry(root):
    root = Path(root)
    catalog, selection = read(root/CATALOG), read(root/SELECTION)
    selected = {c['case_id']: c for c in selection['cases']}
    expected = {f'dial-best5-n{n:02d}-d{level}' for n in (4,6,8) for level in (1,2,3)}
    if set(selected) != expected or {c['id'] for c in catalog['cases']} != expected:
        raise ValueError('The selection and catalog must contain exactly nine R11 cases')
    pinned_registry=read(root/REGISTRY)
    if digest(root/SELECTION)!=pinned_registry['selection_sha256']:
        raise ValueError('Historical Oracle selection checksum mismatch')
    pinned={row['case_id']:row for row in pinned_registry['cases']}
    rows = []
    for case in catalog['cases']:
        registered=pinned[case['id']]
        report_path = selected_report(root,selected[case['id']],registered['oracle_evidence'])
        attempt = report_path.parent
        report = read(report_path)
        reader = MotionReader(attempt/'motion')
        if reader.meta['sample_hz'] != DIAL_RECORD_HZ:
            raise ValueError('Recording cadence differs from the dial contract')
        source = reader.path/'source'
        task = read(source/'task.json')
        require_best5(task)
        if bundle_manifest(source)['sha256'] != report['scene_bundle_sha256']:
            raise ValueError('Frozen source bundle differs from the report')
        evaluation = report['evaluation']
        if (report['case_id'] != case['id'] or not report['passed'] or not evaluation['task_success']
                or evaluation['violations'] or report.get('unresolved_robot_actions')
                or reader.meta['status'] != 'complete'):
            raise ValueError('Selected evidence is not a closed clean success: '+case['id'])
        # Validate the current input independently from the historical witness.
        # An explicitly unqualified physics candidate does not inherit success.
        from ..task_families import resolve_case
        _,_,current=resolve_case(case['id'],root=root)
        if current['directory']!=case['directory']:
            raise ValueError('Dial catalog differs from the released input')
        candidate=root/case['directory']
        scope=registered.get('oracle_evidence_scope')
        candidate_only=(scope=='Historical pre-0.03 physics; not a qualification of this candidate.'
                        and current['qualification']=='rolling_friction_003_candidate_not_full_task_qualified')
        for name in ('task.json','environment.json','scene.xml','workstation.json'):
            if digest(candidate/name)!=registered['source_sha256'][name]:
                raise ValueError('Registered candidate source changed: '+case['id']+'/'+name)
            if digest(source/name) != digest(candidate/name) and not candidate_only:
                raise ValueError('Catalog source differs from evidence: '+case['id']+'/'+name)
        frozen_cfg = attempt/'executor-source/inputs/harness.json'
        if not frozen_cfg.exists():
            frozen_cfg = attempt.parent.parent/'inputs/harness.json'
        if not same_harness(read(frozen_cfg),read(root/'configs/harness-frontier-v2-servo2.json')):
            raise ValueError('Candidate policy control configuration differs from Oracle')
        paths = ('robot_control.py','sim.py','motion_check.py','task_config.py','pipeline.py')
        from ..source_compatibility import historical_digest
        hashes = {'robofrontier/'+p:historical_digest(root, 'robofrontier/'+p, 'dial') for p in paths}
        if physical_control_fingerprint(hashes, read(frozen_cfg)) != report['physical_control_sha256']:
            raise ValueError('Shared physical control code differs from the selected evidence')
        logic_paths = ('evaluate.py','evaluate_v2.py','dial_feedback.py')
        # Current policy terminal scoring is deliberately different. Verify the
        # historical result against its own frozen evaluator, never normalize
        # that scoring change into a claim of current evaluator equivalence.
        logic = {'robofrontier/suite/'+p:digest(attempt/'executor-source/robofrontier/suite'/p)
                 for p in logic_paths}
        if environment_logic_manifest(logic,task)['sha256'] != report['environment_logic_sha256']:
            raise ValueError('Frozen evaluator source differs from the selected evidence')
        assisted = bool(report.get('assisted', report.get('llm_used', False)))
        rows.append(dict(case_id=case['id'], dials=len(task['dials']), level=task['level'],
            arms=len(task['arms']), source_directory=case['directory'],
            source_sha256={name:digest(candidate/name) for name in
                ('scene.xml','task.json','environment.json','workstation.json')},
            oracle_evidence=dict(report=store_relative(report_path,root),report_sha256=digest(report_path),
                recording=store_relative(reader.path,root),motion_index_sha256=digest(reader.path/'stream.json'),
                executor_sha256=report['executor_sha256'],
                physical_control_sha256=report['physical_control_sha256'],
                environment_logic_sha256=report['environment_logic_sha256'],
                assisted=assisted, evidence_kind='privileged_assisted' if assisted else 'pure_program'),
            runtime_readiness='pending_shared_integration'))
        if scope is not None:rows[-1]['oracle_evidence_scope']=scope
    result = dict(schema='robofrontier.dial-family-review.v1', family='dial', revision='best5-r11',
        catalog=CATALOG,catalog_sha256=digest(root/CATALOG),selection=SELECTION,
        selection_sha256=digest(root/SELECTION),presentation=deepcopy(PRESENTATION),
        policy_guidance=GUIDANCE,formal_policy_ready=False,shared_integration_required=list(BLOCKERS),cases=rows)
    if 'physics_revision_note' in pinned_registry:
        result['physics_revision_note']=pinned_registry['physics_revision_note']
    return result


def static_geometry(source):
    """Actual table collision primitives, including ring meshes and holes."""
    source.frame()
    model, data = source.model, source.data
    shapes = {int(v):k.removeprefix('mjGEOM_').lower() for k,v in mujoco.mjtGeom.__members__.items()}
    tables = []
    for geom in source.manifest['geometries']:
        if not geom['id'].startswith('table_') or not geom['collision']:
            continue
        index = geom['source_index']
        row = dict(id=geom['id'],shape=shapes[int(model.geom_type[index])],
            position_m=data.geom_xpos[index].tolist(),
            quaternion_wxyz=matrix_quat(data.geom_xmat[index].reshape(3,3)).tolist(),
            size=model.geom_size[index].tolist())
        if int(model.geom_type[index]) == mujoco.mjtGeom.mjGEOM_MESH:
            mid = int(model.geom_dataid[index])
            va, vn = int(model.mesh_vertadr[mid]), int(model.mesh_vertnum[mid])
            fa, fn = int(model.mesh_faceadr[mid]), int(model.mesh_facenum[mid])
            row['mesh'] = dict(vertices_local_m=model.mesh_vert[va:va+vn].tolist(),
                triangular_faces=model.mesh_face[fa:fa+fn].tolist())
        tables.append(row)
    return dict(tabletop_z_m=read(source.path/'task.json')['table_height_m'],
        table_collision_geometries=tables,units='metres; quaternion wxyz',
        size_convention='MuJoCo primitive half sizes/radii; mesh vertices are in each geom local frame',
        scope='Declared static workstation geometry; no object poses or current contact state')


def public_review(source):
    task = read(source.path/'task.json')
    require_best5(task)
    result = public_task(task)
    result.update(completion=deepcopy(task['completion']),
        static_workstation=dict(tabletop_z_m=task['table_height_m'],
            geometry_reference='table-geometry.json',
            geometry_scope='Actual static collision primitives and meshes, including table openings'),
        workspace_world_m=deepcopy(task['workspace_world_m']),
        task_revision=dict(suite_version=2,scene_revision=11,
            feedback_rule_version=task['completion']['feedback_rule_version'],
            feedback_version=task['mechanism']['feedback']['version']),
        camera_calibration='camera-calibration.json',
        family_guidance='family-guidance.md',task_guide='task-guide.md',
        package_status='review_only; shared runtime integration pending')
    result['process_requirements'] = dict(red_grasp_required=True,
        blue_support_required=task['level']>1,
        minimum_airborne_clearance_m=task['mechanism']['minimum_airborne_clearance_m'] if task['level']>1 else None,
        blue_support_dwell_s=task['mechanism']['blue_support_dwell_s'] if task['level']>1 else None,
        nominal_robot_groups_are_exclusive_assignments=False,
        success_requires_clean_process=True,
        grasp_feedback_scope='Width/drive inference; confirm object retention and support with permitted observations')
    assert_public(result)
    return result


def assert_public(value):
    forbidden = {'code_symbols','secret','password','private_angles_deg','private_support_ready',
        'initial_position_m','initial_center_m','initial_quaternion_wxyz','oracle_evidence',
        'live_object_state','solver_solution'}
    if isinstance(value,dict):
        if forbidden & set(value):
            raise ValueError('Private field in public review: '+str(forbidden & set(value)))
        for child in value.values():
            assert_public(child)
    elif isinstance(value,list):
        for child in value:
            assert_public(child)
    elif isinstance(value,str) and any(p in value for p in ('runs/oracle/','private/inputs/','private/outputs/')):
        raise ValueError('Engineering path in public review')


def task_guide(task):
    lines = ['# '+task['id'], '', task['objective'], '',
        'Read task.json for this case’s static geometry, mechanism, cameras and completion criteria.',
        'Read family-guidance.md before planning manipulation or interpreting BEST/READY.', '', '## Task rules', '']
    lines.extend(f'{i}. {rule}' for i,rule in enumerate(task['rules'],1))
    return '\n'.join(lines)+'\n'


def build_review(root, output, registered):
    from ..run_setup import write_json
    root, output = Path(root), Path(output)
    current = registry(root)
    if current != registered:
        raise ValueError('Family registry no longer matches current evidence/configuration')
    output.mkdir(parents=True,exist_ok=False)
    public_hashes = {}
    for row in current['cases']:
        source = Workstation(root/row['source_directory'])
        task = public_review(source)
        images = ['preview-global.png','preview-global_rear.png','preview-top.png']
        task['initial_reference_images'] = images
        destination = output/row['case_id']/'public'
        write_json(destination/'task.json',task)
        write_json(destination/'table-geometry.json',static_geometry(source))
        write_json(destination/'camera-calibration.json',dict(
            coordinate_frame=task['coordinate_frame'],image_size_pixel=[1280,800],
            cameras=deepcopy(source.manifest['cameras']),
            scope='Declared fixed camera calibration; live robot/object feedback comes from observe'))
        (destination/'task-guide.md').write_text(task_guide(task))
        (destination/'family-guidance.md').write_text((root/prompt_archive.source(GUIDANCE)).read_text())
        from ..task_families import resolve_case
        _,_,spec=resolve_case(row['case_id'],root=root)
        for name in images:
            reference=spec.get('public_files',{}).get(name)
            image=root/reference['path'] if reference else root/row['source_directory']/name
            if reference and digest(image)!=reference['sha256']:
                raise ValueError('Reviewed image checksum mismatch: '+name)
            shutil.copy2(image,destination/name)
        for path in sorted(destination.iterdir()):
            public_hashes[str(path.relative_to(output))] = digest(path)
    write_json(output/'private/family-evidence.json',current)
    write_json(output/'review.json',dict(schema='robofrontier.dial-policy-review.v1',
        formal_policy_ready=False,simulation_started=False,inference_started=False,
        source_registry_sha256=digest(root/REGISTRY),public_files_sha256=public_hashes,
        shared_source_sha256={name:digest(root/name) for name in SHARED_INPUTS},
        guidance_sha256=digest(root/prompt_archive.source(GUIDANCE)),shared_integration_required=list(BLOCKERS),
        scope='Public family input preview, not a prepared runtime or a promoted readiness state'))
    return current


def verify_review(root, output):
    """Verify already-published review files as well as their bound sources."""
    root, output = Path(root), Path(output)
    registered = read(root/REGISTRY)
    if registry(root) != registered or read(output/'private/family-evidence.json') != registered:
        raise ValueError('Review evidence registry changed')
    manifest = read(output/'review.json')
    if manifest['formal_policy_ready'] or manifest['simulation_started'] or manifest['inference_started']:
        raise ValueError('A review cannot claim runtime readiness or execution')
    if manifest['source_registry_sha256'] != digest(root/REGISTRY) or manifest['guidance_sha256'] != digest(root/prompt_archive.source(GUIDANCE)):
        raise ValueError('Family inputs changed')
    for name,expected in manifest['shared_source_sha256'].items():
        if digest(root/name) != expected:raise ValueError('Shared input changed: '+name)
    expected_public = set()
    for row in registered['cases']:
        folder = output/row['case_id']/'public'
        task = read(folder/'task.json')
        assert_public(task)
        source = Workstation(root/row['source_directory'])
        expected_task = public_review(source)
        expected_task['initial_reference_images'] = ['preview-global.png','preview-global_rear.png','preview-top.png']
        if task != expected_task or (folder/'task-guide.md').read_text() != task_guide(task):
            raise ValueError('Public task or guide differs from its source')
        if read(folder/'table-geometry.json') != static_geometry(source):
            raise ValueError('Table geometry differs from source')
        if (folder/'family-guidance.md').read_text() != (root/prompt_archive.source(GUIDANCE)).read_text():
            raise ValueError('Family guidance changed')
        calibration = read(folder/'camera-calibration.json')
        expected_calibration = dict(coordinate_frame=task['coordinate_frame'],image_size_pixel=[1280,800],
            cameras=source.manifest['cameras'],
            scope='Declared fixed camera calibration; live robot/object feedback comes from observe')
        if calibration != expected_calibration:
            raise ValueError('Camera calibration differs from source')
        for path in folder.iterdir():
            name = str(path.relative_to(output))
            expected_public.add(name)
            if manifest['public_files_sha256'].get(name) != digest(path):
                raise ValueError('Public artifact changed: '+name)
    if expected_public != set(manifest['public_files_sha256']):
        raise ValueError('Public review inventory differs')
    return dict(cases_verified=len(registered['cases']),formal_policy_ready=False,public_integrity_verified=True)
