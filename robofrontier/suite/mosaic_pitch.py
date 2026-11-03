"""Mosaic R15: the released R14 scenes with a 71 mm cell pitch; cubes stay 60 mm.

Only the board changes: it shrinks about its centre, with the Level 1 pocket
walls, floor and the table frame around the opening, or the Level 2 printed
lines, redrawn for the new pitch, and the goals moved to the new cell centres.
Robots, stock, table, cameras, the initial keyframe, colours, pattern, physics
and completion rules are R14's. No physics is stepped.

`build` writes the nine cases into benchmark/mosaic/, the catalog, and the Mosaic
policy entries of benchmark/release.json.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

from . import v2
from ..run_setup import write_json

ROOT = v2.ROOT
SOURCE_CATALOG = 'configs/suites/frontier-mosaic-r14.json'
CATALOG = 'benchmark/mosaic/catalog.json'
RELEASE = 'benchmark/release.json'
QUALIFICATION = 'r15_grid_pitch_71mm_from_r14_static_checks'
STATUS = 'grid_pitch_review_only_no_r15_oracle_qualification'
REVISION = 15
PITCH = .071
WALL = .001
POCKET = PITCH - WALL


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _vec(text):
    return np.array([float(v) for v in text.split()])


def _set(element, key, value):
    element.set(key, v2.vector(np.asarray(value, dtype=float)))


def derive(case, render=True):
    """Write the R15 scene of one R14 case under configs/environments/mosaic/."""
    source = ROOT/case['directory']
    env = json.loads((source/'environment.json').read_text())
    grid = env['grid']; rows, cols, pitch = grid['rows'], grid['columns'], grid['pitch_m']
    w, h, w2, h2 = cols*pitch/2, rows*pitch/2, cols*PITCH/2, rows*PITCH/2
    new_case = dict(case, scene_revision=REVISION, source_scene_revision=case['scene_revision'])
    new_case['directory'] = str(v2.directory(new_case).relative_to(ROOT))
    target = ROOT/new_case['directory']
    if target.exists():
        raise FileExistsError(target)
    root = ET.parse(source/'scene.xml').getroot(); world = root.find('worldbody')
    by_name = {e.get('name'): e for e in world if e.get('name')}

    # Board: pocket walls and floor (Level 1) or printed lines (Level 2).
    for name, element in by_name.items():
        if element.tag != 'geom':
            continue
        kind, _, index = name.rpartition('_')
        if kind in ('pocket_column', 'printed_column', 'pocket_row', 'printed_row'):
            pos, size = _vec(element.get('pos')), _vec(element.get('size'))
            if kind.endswith('column'):
                pos[0] = (int(index)-cols/2)*PITCH; size[1] += h2-h
            else:
                pos[1] = (int(index)-rows/2)*PITCH; size[0] += w2-w
            _set(element, 'pos', pos); _set(element, 'size', size)
    if 'pocket_bottom' in by_name:
        size = _vec(by_name['pocket_bottom'].get('size')); size[:2] += [w2-w, h2-h]
        _set(by_name['pocket_bottom'], 'size', size)

    # Level 1: the table frame fills the table around the smaller opening.
    hx, hy = env['tables'][0]['half_size_m'][:2]
    frames = {'south': ([0, -(h2+hy)/2], [hx, (hy-h2)/2]), 'north': ([0, (h2+hy)/2], [hx, (hy-h2)/2]),
              'west': ([-(w2+hx)/2, 0], [(hx-w2)/2, h2]), 'east': ([(w2+hx)/2, 0], [(hx-w2)/2, h2])}
    for side, (centre, half) in frames.items():
        element = by_name.get('table_frame_'+side)
        if element is not None:
            pos, size = _vec(element.get('pos')), _vec(element.get('size'))
            pos[:2], size[:2] = centre, half; _set(element, 'pos', pos); _set(element, 'size', size)

    for g in env['goals']:
        g['position_m'] = [(g['column']-1-(cols-1)/2)*PITCH, ((rows-1)/2-(g['row']-1))*PITCH, g['position_m'][2]]
    grid['pitch_m'] = PITCH
    if grid.get('pocket_opening_m') is not None:
        grid['pocket_opening_m'] = POCKET
    mechanism = env['mechanism']
    mechanism['outer_base_axis_inset_from_grid_end_m'] = w2-max(abs(s['base_position_m'][0]) for s in env['stations'])
    mechanism['robot_to_grid_edge_m'] += h-h2
    if 'robot_to_grid_edge_m_by_robot' in mechanism:
        mechanism['robot_to_grid_edge_m_by_robot'] = {k: v+h-h2 for k, v in mechanism['robot_to_grid_edge_m_by_robot'].items()}
    mechanism['pitch_revision'] = dict(name='pitch-71mm-r15', source_revision=case['scene_revision'],
        previous_pitch_m=pitch, pitch_m=PITCH, cube_side_m=grid['cube_side_m'],
        pocket_opening_m=grid.get('pocket_opening_m'),
        unchanged='Robots, stock, table, cameras, initial keyframe, colours, pattern and physics')
    env['suite_case'] = deepcopy(new_case)

    target.mkdir(parents=True)
    frozen = json.loads((source/'workstation.json').read_text())
    for asset in frozen['assets']:
        src, dest = source/asset['path'], target/asset['path']
        if checksum(src) != asset['sha256']:
            raise ValueError('Source asset differs: '+asset['path'])
        dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dest)
    for name in ('target-pattern.png', 'target-original.png', 'source-pattern.png'):
        if (source/name).exists():
            shutil.copyfile(source/name, target/name)

    path = target/'scene.xml'; ET.ElementTree(root).write(path, encoding='unicode')
    model = mujoco.MjModel.from_xml_path(str(path)); data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key('initial').id); mujoco.mj_forward(model, data)

    write_json(target/'environment.json', env)
    task = v2.task_for(new_case, env, target)
    # Completion rules reviewed after R14 was generated (the Level 2/3 centre tolerance).
    task['completion'] = json.loads((source/'task.json').read_text())['completion']
    write_json(target/'task.json', task); write_json(target/'public-task.json', v2.public_task(task))
    write_json(target/'parameters.json', dict(physics=env['physics'], mechanism=mechanism, grid=grid,
        scope='Declared geometry/material and engineering parameters; not a task success proof'))
    state = v2.manifest(model, data, new_case, target, env)
    report = static_checks(model, data, env)
    write_json(target/'validation.json', dict(status='static_checks_'+('passed' if report['passed'] else 'failed'),
        oracle_verified=False, policy_verified=False, frozen_input=False, physics_steps=0,
        robot_count=case['arms'], physics_sha256=state['physics_sha256'],
        source_scene_sha256=checksum(source/'scene.xml'), source_revision=case['scene_revision'], **report,
        scope='Static compilation, initial contact and placement screen only; no reach coverage, manipulation, Oracle or policy run'))
    if not report['passed']:
        raise ValueError('R15 static checks failed: '+case['id'])
    v2.validate_task(task)
    write_json(target/'public/reviewed-task.json', reviewed_projection(source, target))
    if render:
        from PIL import Image
        with mujoco.Renderer(model, width=1280, height=800) as renderer:
            for view in ('global', 'global_rear', 'top'):
                renderer.update_scene(data, camera=view)
                Image.fromarray(renderer.render()).save(target/('preview-'+view+'.png'))
    return new_case, report


def reviewed_projection(source, target):
    """R14's reviewed public projection with the R15 grid; nothing else may differ."""
    from .mosaic_policy_package import project_public
    read = lambda folder, name: json.loads((folder/name).read_text())
    completion = json.loads((ROOT/'benchmark/mosaic/r13.json').read_text())['completion']
    result = project_public(read(target, 'task.json'), read(target, 'environment.json'),
                            read(target, 'workstation.json'), read(target, 'public-task.json'), completion)
    previous = read(source, 'public/reviewed-task.json')
    result.update(scene_revision=REVISION, completion=previous['completion'], package_status=STATUS,
                  guidance=deepcopy(previous['guidance']))
    changed = {k for k in set(result) | set(previous) if result.get(k) != previous.get(k)}
    target_changed = {k for k in result['target'] if result['target'][k] != previous['target'].get(k)}
    if changed - {'scene_revision', 'source_scene_sha256', 'target', 'package_status'} or \
            target_changed - {'pitch_m', 'pocket_opening_m'}:
        raise ValueError('R15 public projection differs from R14 beyond the grid')
    return result


def static_checks(model, data, env):
    """Initial contacts, cube spacing and cubes fully on the table, outside the board."""
    side = env['grid']['cube_side_m']; hx, hy = env['tables'][0]['half_size_m'][:2]
    w, h = env['grid']['columns']*PITCH/2, env['grid']['rows']*PITCH/2
    cubes = np.array([o['initial_position_m'][:2] for o in env['objects']])
    gaps = np.linalg.norm(cubes[:, None]-cubes[None], axis=2) + np.eye(len(cubes))*9
    penetrations = [dict(geom1=model.geom(c.geom1).name, geom2=model.geom(c.geom2).name, depth_m=float(-c.dist))
                    for c in data.contact[:data.ncon] if c.dist < -.001]
    edge = float(min((hx-np.abs(cubes[:, 0])).min(), (hy-np.abs(cubes[:, 1])).min())-side/2)
    on_board = int(np.sum((np.abs(cubes[:, 0]) < w+side/2) & (np.abs(cubes[:, 1]) < h+side/2)))
    report = dict(initial_penetrations_over_1mm=penetrations, min_cube_centre_spacing_m=float(gaps.min()),
                  min_cube_to_table_edge_m=edge, cubes_over_board=on_board)
    report['passed'] = not penetrations and report['min_cube_centre_spacing_m'] >= side+.005 and edge >= .01 and not on_board
    return report


def build(render=True):
    """Write the nine R15 cases, their catalog and the release entries."""
    source = json.loads((ROOT/SOURCE_CATALOG).read_text())
    cases = [derive(c, render)[0] for c in source['cases']]
    write_json(ROOT/CATALOG, dict(schema_version=2, case_count=len(cases), scene_revision=REVISION,
        status='71 mm grid pitch from R14; static checks passed; no R15 Oracle or policy run', cases=cases))
    path = ROOT/RELEASE; release = json.loads(path.read_text())
    family = release['families']['mosaic']; by_id = {c['id']: c for c in cases}
    family['catalog'] = dict(path=CATALOG, sha256=checksum(ROOT/CATALOG))
    for entry in family['gpt']:
        case = by_id[entry['id']]; folder = ROOT/case['directory']
        entry['directory'] = case['directory']
        entry['source_files'] = {name: checksum(folder/name) for name in entry['source_files']}
        entry['qualification'] = QUALIFICATION
        entry['public_projection'] = dict(path=case['directory']+'/public/reviewed-task.json',
                                          sha256=checksum(folder/'public/reviewed-task.json'))
    write_json(path, release)
    return cases
