"""Released-scene checks, freezing a scene into a run, and its camera names."""

import hashlib
import json
import math
import shutil
import xml.etree.ElementTree as ET
from copy import deepcopy

from ..io import ROOT, clone_or_copy


def validate_scene_asset(task):
    """Shared static asset checks; task-specific goals are validated separately."""
    import re

    from .config import check_position

    folder = (ROOT / task['scene_asset']).resolve()
    if not folder.is_relative_to(ROOT / 'benchmark') or not folder.is_dir():
        raise ValueError('Use a released scene under benchmark/')
    if hashlib.sha256((folder / 'scene.xml').read_bytes()).hexdigest() != task['scene_sha256']:
        raise ValueError('Generated scene differs from the requested task')
    env = json.loads((folder / 'environment.json').read_text())
    if task['arms'] != {
        s['id']: {'base_position_m': s['base_position_m'], 'yaw_rad': s['yaw_rad']} for s in env['stations']
    }:
        raise ValueError('Robot bases differ from generated scene')
    for name, base in task['arms'].items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) or name in ('Meta', 'Controller', 'research'):
            raise ValueError('Invalid robot ID')
        check_position(base['base_position_m'])
        if not math.isfinite(base['yaw_rad']):
            raise ValueError('Invalid base yaw')
    lower, upper = (task['workspace_world_m'][k] for k in ('lower', 'upper'))
    check_position(lower)
    check_position(upper)
    if any(a >= b for a, b in zip(lower, upper)):
        raise ValueError('Invalid world command bounds')
    actual = {c.get('name') for c in ET.parse(folder / 'scene.xml').findall('worldbody/camera')}
    if len(task['cameras']) != len(set(task['cameras'])) or set(task['cameras']) != actual:
        raise ValueError('Camera list differs from generated scene')
    return folder, env


def freeze_scene(task, directory):
    """Freeze the actual scene/meshes into the run; preserve relative asset paths."""
    task = deepcopy(task)
    source = ROOT / task['scene_asset']
    dest = directory / 'private/inputs/scene'
    root = ET.parse(source / 'scene.xml').getroot()
    compiler = root.find('compiler')
    dest.mkdir(parents=True)
    shutil.copytree(source / 'assets', dest / 'assets', copy_function=clone_or_copy)
    if (source / 'workstation.json').exists():
        # Keep the exact canonical bytes/hash used by offline factory replay.
        for name in ('scene.xml', 'workstation.json', 'environment.json', 'task.json'):
            clone_or_copy(source / name, dest / name)
    else:
        meshes = (source / compiler.get('meshdir')).resolve()
        shutil.copytree(meshes, dest / 'model-assets')
        compiler.set('meshdir', 'model-assets')
        ET.indent(root)
        ET.ElementTree(root).write(dest / 'scene.xml', encoding='unicode')
    if task['task_type'] == 'mosaic':
        shutil.copy2(source / 'public/target-pattern.png', directory / 'public/inputs/target-pattern.png')
    for name in ('robot-layout.png', 'camera-guide.json'):
        if (source / name).is_file():
            shutil.copy2(source / name, directory / 'public/inputs' / name)
    task['scene_asset'] = 'private/inputs/scene/scene.xml'
    task['scene_sha256'] = hashlib.sha256((dest / 'scene.xml').read_bytes()).hexdigest()
    return task


def camera_names(task):
    return task.get(
        'cameras', ['global', 'global_side'] + [a + '_' + s for a in task['arms'] for s in ('front', 'side')]
    )
