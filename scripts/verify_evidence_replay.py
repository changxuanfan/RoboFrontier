"""Compare restored evidence, all motion states/events and sampled renders.

No inference, commands, IK or physics stepping. Requires MuJoCo, Pillow and
NumPy. Three distributed samples do not constitute a full video or a successful
benchmark result.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import struct

import mujoco
import numpy as np
from PIL import Image

from roboteam.media.motion_recording import MotionReader
from roboteam.physics.workstation import Workstation
from roboteam.batch.collect import digest
from roboteam.batch.archive_policy_batch import safe, verify_collection


def simple_frames(recording, indices):
    reader = MotionReader(recording)
    source = Workstation(recording/'source')
    source.model.geom_rgba[:] = reader.meta['initial_rgba']
    ids = {g['id']:g['source_index'] for g in source.manifest['geometries']}
    events = iter(reader.events())
    event = next(events, None)
    images = []
    with mujoco.Renderer(source.model, width=480, height=300) as renderer:
        for _, stamp, state in reader.selected_frames(indices):
            while event is not None and event['sim_time_s'] <= stamp+1e-9:
                if event['event'] == 'rgba':
                    for name, color in event['geoms'].items():
                        source.model.geom_rgba[ids[name]] = color
                event = next(events, None)
            source.data.qpos[:] = state
            source.data.time = stamp
            mujoco.mj_kinematics(source.model, source.data)
            mujoco.mj_comPos(source.model, source.data)
            mujoco.mj_camlight(source.model, source.data)
            renderer.update_scene(source.data, camera='global')
            images.append(renderer.render().copy())
    return images


def verify_evidence(original, restored, output):
    original, restored, output = Path(original).resolve(), Path(restored).resolve(), Path(output).resolve()
    if not original.is_dir() or not restored.is_dir() or original == restored:
        raise ValueError('Choose two existing, distinct collection directories')
    report_source = verify_collection(original, allow_incomplete=True)
    if not (restored/'collection.json').is_file():
        raise ValueError('Restored collection manifest is missing')
    markers = sorted(original.glob('batch/**/private/outputs/motion/stream.json'))
    if not markers:
        raise ValueError('No Motion recordings found; no replay validation was performed')
    runs = [safe(original,job['run']) for job in report_source['jobs']]
    expected = {run/'private/outputs/motion/stream.json' for run in runs}
    if not expected or len(expected) != report_source['job_count'] or set(markers) != expected:
        raise ValueError('Motion coverage differs from collection jobs; missing recordings cannot pass replay validation')
    if output.exists() or output.is_relative_to(original) or output.is_relative_to(restored):
        raise ValueError('Choose a new diagnostic output outside evidence directories')
    a = {p.relative_to(original).as_posix():p for p in original.rglob('*') if p.is_file()}
    b = {p.relative_to(restored).as_posix():p for p in restored.rglob('*') if p.is_file()}
    if a.keys() != b.keys():
        raise ValueError('Restored file inventory differs')
    for name in a:
        if digest(a[name]) != digest(b[name]):
            raise ValueError('Restored bytes differ: '+name)
    output.mkdir(parents=True)
    report = {'files_verified':len(a), 'physics_steps_executed':0, 'cases':[],
              'scope':'All file bytes and motion states/events; three sampled images per scene, same renderer. No full task video or score qualification.'}
    for marker in markers:
        left = marker.parent
        right = restored/left.relative_to(original)
        x,y = MotionReader(left),MotionReader(right)
        count = 0
        h = hashlib.sha256()
        for p,q in itertools.zip_longest(x.frames(),y.frames()):
            if p is None or q is None or struct.pack('<d',p[0]) != struct.pack('<d',q[0]) or p[1].tobytes() != q[1].tobytes():
                raise ValueError('Motion state/time differs: '+str(left))
            h.update(struct.pack('<d',p[0]));h.update(p[1].tobytes());count+=1
        if count != x.meta['frames'] or count != y.meta['frames'] or count == 0:
            raise ValueError('Motion frame count differs or recording is empty')
        if list(x.events()) != list(y.events()):
            raise ValueError('Motion events differ')
        indices = sorted({0,count//2,count-1})
        images_a, images_b = simple_frames(left,indices),simple_frames(right,indices)
        if any(not np.array_equal(i,j) for i,j in zip(images_a,images_b)):
            raise ValueError('Simple-scene pixels differ')
        name = left.relative_to(original/'batch').parts
        label = '--'.join(name[:-3])
        for i,image in enumerate(images_b):
            Image.fromarray(image).save(output/(label+f'-simple-{i}.jpg'),quality=85)
        row = {'case_id':x.meta['case_id'],'recording':left.relative_to(original).as_posix(),
               'frames_verified':count,'state_time_sha256':h.hexdigest(),
               'appearance_events_exact':True,'simple_scene_pixels_exact':True,'sample_indices':indices}
        report['cases'].append(row)
        print(json.dumps(row),flush=True)
    report['total_frames_verified'] = sum(c['frames_verified'] for c in report['cases'])
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original',type=Path)
    parser.add_argument('restored',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(verify_evidence(args.original,args.restored,args.output),indent=2))


if __name__=='__main__':main()
