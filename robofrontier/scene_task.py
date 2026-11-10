"""Released-scene checks, freezing a scene into a run, and its camera names."""
from copy import deepcopy
import hashlib
import json
import ctypes
import math
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def validate_scene_asset(task):
    """Shared static asset checks; task-specific goals are validated separately."""
    from .task_config import check_position
    import re
    folder=(ROOT/task['scene_asset']).resolve()
    if not any(folder.is_relative_to(ROOT/base) for base in ('benchmark', 'configs/environments')) or not folder.is_dir():
        raise ValueError('Use a released scene under benchmark or a generated one under configs/environments')
    if hashlib.sha256((folder/'scene.xml').read_bytes()).hexdigest()!=task['scene_sha256']:
        raise ValueError('Generated scene differs from the requested task')
    env=json.loads((folder/'environment.json').read_text())
    if task['arms']!={s['id']:{'base_position_m':s['base_position_m'],'yaw_rad':s['yaw_rad']} for s in env['stations']}:
        raise ValueError('Robot bases differ from generated scene')
    for name,base in task['arms'].items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',name) or name in ('Meta','Coordinator','Controller','research'):
            raise ValueError('Invalid robot ID')
        check_position(base['base_position_m'])
        if not math.isfinite(base['yaw_rad']):raise ValueError('Invalid base yaw')
    lower,upper=(task['workspace_world_m'][k] for k in ('lower','upper'))
    check_position(lower);check_position(upper)
    if any(a>=b for a,b in zip(lower,upper)):raise ValueError('Invalid world command bounds')
    actual={c.get('name') for c in ET.parse(folder/'scene.xml').findall('worldbody/camera')}
    if len(task['cameras'])!=len(set(task['cameras'])) or set(task['cameras'])!=actual:
        raise ValueError('Camera list differs from generated scene')
    return folder,env


try:  # macOS clonefile(2); absent elsewhere.
    _clonefile=ctypes.CDLL(None,use_errno=True).clonefile
    _clonefile.argtypes=(ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint32)
except (AttributeError,OSError):
    _clonefile=None
FICLONE=0x40049409  # Linux reflink ioctl (Btrfs, XFS, bcachefs).


def _reflink(source,target):
    import fcntl
    with open(source,'rb') as src,open(target,'xb') as dst:
        try:fcntl.ioctl(dst.fileno(),FICLONE,src.fileno())
        except OSError:
            dst.close();os.unlink(target);raise
    shutil.copystat(source,target)


def clone_or_copy(source,target):
    """Copy-on-write clone where the file system supports it (APFS clonefile, Linux
    reflink), else a plain copy.

    A clone takes no extra space yet stays an independent file: writing to a run's
    frozen copy never reaches the source or other runs, unlike a hard link."""
    try:
        if _clonefile is not None:
            if _clonefile(os.fsencode(source),os.fsencode(target),0)==0:
                shutil.copystat(source,target);return target
        elif hasattr(os,'uname') and os.uname().sysname=='Linux':
            _reflink(source,target);return target
    except (OSError,ImportError):pass
    return shutil.copy2(source,target)


def freeze_scene(task,directory):
    """Freeze the actual scene/meshes into the run; preserve relative asset paths."""
    task=deepcopy(task);source=ROOT/task['scene_asset'];dest=directory/'private/inputs/scene'
    root=ET.parse(source/'scene.xml').getroot();compiler=root.find('compiler')
    dest.mkdir(parents=True);shutil.copytree(source/'assets',dest/'assets',copy_function=clone_or_copy)
    if (source/'workstation.json').exists():
        # Keep the exact canonical bytes/hash used by offline factory replay.
        for name in ('scene.xml','workstation.json','environment.json','task.json'):
            clone_or_copy(source/name,dest/name)
    else:
        meshes=(source/compiler.get('meshdir')).resolve()
        shutil.copytree(meshes,dest/'model-assets');compiler.set('meshdir','model-assets')
        ET.indent(root);ET.ElementTree(root).write(dest/'scene.xml',encoding='unicode')
    names=(('target-pattern-draft.png','initial-top.png','initial-top.json')
           if task['kind']=='shared_grid' else ('preview-board.png',) if task['kind']=='spring_dial'
           else ('preview-global.png','preview-global_rear.png','preview-top.png') if task['kind']=='frontier_suite'
           else ('preview-top.png',))
    for name in names:
        if task['kind']=='frontier_suite' and not (source/name).is_file():continue
        shutil.copy2(source/name,directory/'public/inputs'/name)
    if task['kind']=='frontier_suite' and task['family']=='mosaic':shutil.copy2(source/'target-pattern.png',directory/'public/inputs/target-pattern.png')
    for name in ('robot-layout.png','camera-guide.json'):
        if (source/name).is_file():shutil.copy2(source/name,directory/'public/inputs'/name)
    task['scene_asset']='private/inputs/scene/scene.xml'
    task['scene_sha256']=hashlib.sha256((dest/'scene.xml').read_bytes()).hexdigest()
    return task


def camera_names(task):
    return task.get('cameras',['global','global_side']+[a+'_'+s for a in task['arms'] for s in ('front','side')])
