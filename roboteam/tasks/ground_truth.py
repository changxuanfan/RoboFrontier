"""The ground-truth files of a ground_truth run (runtime/tools/observation_mode.py).

Such a run's roles read, under public/inputs/ground-truth/, what an ordinary role never
gets: the task as the evaluator has it (every object with its initial pose, every goal with
its exact target, the mechanism and the completion rule) and the task's MuJoCo scene with
its assets, so a role can load the scene in the simulator of its Python environment. The
scene is the task's own; the factory hall around it is not included.

The Dial code is not part of a task: it lives in the release's private block and reaches a
run only as private/inputs/suite-code.json. Nothing here reads either, and a task that
carried a code would be refused.
"""

import re
import shutil
from copy import deepcopy
from pathlib import Path

from roboteam.io import write_json

FOLDER = 'public/inputs/ground-truth'
# Relative to public/inputs/, as the public task names its other references.
REFERENCE = {
    'folder': 'ground-truth',
    'task': 'ground-truth/task.json',
    'scene': 'ground-truth/scene.xml',
    'scope': 'The task as the evaluator has it and its MuJoCo scene (keyframe "initial"), without '
    'the factory hall. Live state comes from the robot tool\'s state operation.',
}
# Run bookkeeping (the wall limit stays with the host) and the wording an images role is
# given: the role's rules and objective are those of its public task.
DROPPED = (
    'run_protocol',
    'execution_readiness',
    'rules',
    'objective',
    'observation_contract',
    'cameras',
    'view_camera',
    'recording_camera',
)
_SECRET_KEY = re.compile(r'code_symbols|dial_code|secret|password', re.I)


def _refuse_secrets(value, where='task'):
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                raise ValueError(
                    'A task field that may hold a private code cannot be published: ' + where + '.' + key
                )
            _refuse_secrets(item, where + '.' + str(key))
    elif isinstance(value, list):
        for item in value:
            _refuse_secrets(item, where)


def task_definition(task):
    """The task a ground_truth role may read: the prepared private task without run
    bookkeeping, with its scene named relative to the ground-truth folder."""
    result = {key: deepcopy(value) for key, value in task.items() if key not in DROPPED}
    result['scene_asset'] = 'scene.xml'
    _refuse_secrets(result)
    return result


def freeze(task, directory):
    """Write the ground-truth folder of a prepared run from its frozen private scene."""
    from roboteam.tasks.scene import clone_or_copy

    directory = Path(directory)
    source = directory / Path(task['scene_asset']).parent
    target = directory / FOLDER
    target.mkdir(parents=True)
    clone_or_copy(source / 'scene.xml', target / 'scene.xml')
    for name in ('assets', 'model-assets'):
        if (source / name).is_dir():
            shutil.copytree(source / name, target / name, copy_function=clone_or_copy)
    write_json(target / 'task.json', task_definition(task))
    return target


def public_view(public):
    """The public task of a ground_truth role: what it has instead of camera images.

    Camera names, image sizes, calibration and reference images are left out, and the
    observation contract names the ground truth. Everything else is the released public task."""
    result = deepcopy(public)
    for key in (
        'cameras',
        'camera_calibration',
        'observation_image',
        'initial_reference_images',
        'robot_layout_image',
    ):
        result.pop(key, None)
    if isinstance(result.get('target'), dict):
        result['target'].pop('reference_image', None)
    images = ('.png', '.jpg', '.jpeg')
    if isinstance(result.get('task_materials'), list):
        result['task_materials'] = [
            name
            for name in result['task_materials']
            if not (isinstance(name, str) and (name.endswith(images) or 'camera' in Path(name).name))
        ]
    result['observation_contract'] = {
        'initial_geometry_public': True,
        'live_object_truth_for_policy': True,
        'policy': [
            'Ground-truth object poses and velocities, joint state and evaluator progress (robot op state)',
            'The task definition and MuJoCo scene under ground-truth/',
            'Robot proprioception and geometry',
            'Action feedback',
        ],
        'camera_images': False,
    }
    result['ground_truth'] = dict(REFERENCE)
    return result
