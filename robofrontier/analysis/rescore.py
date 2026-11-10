"""Score a finished Mosaic or Transport run's final pose again with the current evaluator.

The run's frozen scene is loaded and every recorded object is put where the motion
recording last saw it. Objects the hands no longer touch count as released and still,
as at the end of a run, and the evaluator then counts the goals held for its stable
duration. This checks that a change to the evaluator keeps the scores of finished runs
(docs/cleanup-20261110.md); it is not a replay of the run's physics.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import mujoco
import numpy as np

from .motion_query import object_poses


def final_time(run):
    evaluation = json.loads((Path(run)/'private/outputs/evaluation.json').read_text())
    return float(evaluation['sim_time_s']), evaluation


def load_frozen_model(run, task):
    """The run's frozen scene, compiled as its world compiled it."""
    import xml.etree.ElementTree as ET
    folder = Path(run)/Path(task['scene_asset']).parent
    root = ET.parse(Path(run)/task['scene_asset']).getroot()
    compiler = root.find('compiler'); compiler.set('meshdir', str((folder/compiler.get('meshdir', '')).resolve()))
    for texture in root.findall('asset/texture'):
        if texture.get('file'): texture.set('file', str(folder/texture.get('file')))
    return mujoco.MjModel.from_xml_string(ET.tostring(root, encoding='unicode'))


def rescore(run):
    """{recorded, rescored} goal counts of the run's final state."""
    from ..tasks.evaluate import Monitor
    run = Path(run)
    task = json.loads((run/'private/inputs/task.json').read_text())
    if task['family'] not in ('mosaic', 'transport'):
        raise ValueError('Rescoring a final pose applies to Mosaic and Transport')
    sim_time, recorded = final_time(run)
    model = load_frozen_model(run, task)
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key('initial').id)
    for name, pose in object_poses(run, sim_time).items():
        joint = model.body(name).jntadr[0]; address = model.jnt_qposadr[joint]
        data.qpos[address:address+3] = pose['position_m']; data.qpos[address+3:address+7] = pose['quaternion_wxyz']
    data.qvel[:] = 0; mujoco.mj_forward(model, data)
    monitor = Monitor(SimpleNamespace(model=model, data=data, task=task, arms={}, directory=run))
    duration = task['completion']['stable_duration_sim_s']
    for t in (sim_time, sim_time+duration):
        data.time = t; monitor.sample_goals()
    result = monitor.result_cache
    return dict(case=task['id'], recorded=dict(matched_goals=recorded.get('matched_goals'), total_goals=recorded.get('total_goals'),
                                               task_success=recorded.get('task_success')),
                rescored=dict(matched_goals=result['matched_goals'], total_goals=result['total_goals'],
                              task_success=result['task_success']))


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('runs', nargs='+', type=Path)
    for run in parser.parse_args(argv).runs:
        print(json.dumps(rescore(run)))


if __name__ == '__main__':
    main()
