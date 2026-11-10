"""Cut a recording to its meaningful motion, for both simple and Factory videos.

A half-second window moves when an arm joint turns more than 0.01 rad (the
evaluator's 0.02 rad/s robot-motion rate), a finger moves more than 1 mm, or a
free body moves more than 3 mm or turns more than 3 degrees, and that motion is
directed: its net change is at least half of the path it travelled. Jitter,
drift and settling are therefore still, however visible. Colour events move.
Each moving window keeps one window of context on either side; the first and
last states are always kept. A rendered video can then remove frames that still
show no visible change (refine_with_video). The recording is never changed.
"""
import json
from pathlib import Path
import re

import numpy as np

from .motion_recording import MotionReader, digest
from .motion_timeline import ranges, sample_timeline
from ..runtime.setup import write_json

SCHEMA = 'robofrontier.motion-edit.v1'
WINDOW_S = .5
THRESHOLDS = dict(arm_joint_rad=.01, finger_m=.001, body_m=.003, body_rad=np.radians(3.), directed_fraction=.5)


def _states(reader):
    times, states = [], []
    for chunk in reader.meta['chunks']:
        path = reader.path/chunk['file']
        if digest(path) != chunk['sha256']:
            raise ValueError('Source motion checksum mismatch')
        with np.load(path, allow_pickle=False) as z:
            states.append(np.bitwise_xor(np.bitwise_xor.accumulate(z['xor'], axis=0), z['base']).view('<f4'))
            times.append(z['time_s'])
    return np.concatenate(times), np.concatenate(states).astype(float)


def _angle(a, b):
    a = a/np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-15)
    b = b/np.maximum(np.linalg.norm(b, axis=-1, keepdims=True), 1e-15)
    return 2*np.arccos(np.clip(np.abs(np.sum(a*b, axis=-1)), 0, 1))


def _directed(net, path, threshold):
    return (net > threshold) & (net >= THRESHOLDS['directed_fraction']*np.maximum(path, 1e-15))


def meaningful_keep(recording, window_s=WINDOW_S):
    """Times, the kept-state mask and per-window moving flags of one recording."""
    reader = MotionReader(recording)
    joints = json.loads((reader.path/'source/workstation.json').read_text())['joints']
    times, q = _states(reader)
    if len(times) != reader.meta['frames'] or np.any(np.diff(times) <= 0):
        raise ValueError('Recorded motion clock differs')
    arm = [j['qpos_address'] for j in joints if re.fullmatch(r'[A-Z]_joint[1-7]', j['id'])]
    finger = [j['qpos_address'] for j in joints if re.fullmatch(r'[A-Z]_finger_joint[12]', j['id'])]
    free = [j['qpos_address'] for j in joints if j['type'] == 0]
    step = max(1, round(window_s*reader.meta['sample_hz']))
    starts = np.arange(0, len(times), step)
    moving = np.zeros(len(starts), dtype=bool)
    for k, start in enumerate(starts):
        a = q[start:min(start+step, len(times)-1)+1]
        if len(a) < 2:
            continue
        for columns, threshold in ((arm, THRESHOLDS['arm_joint_rad']), (finger, THRESHOLDS['finger_m'])):
            if columns:
                v = a[:, columns]
                moving[k] |= _directed(np.abs(v[-1]-v[0]), np.abs(np.diff(v, axis=0)).sum(0), threshold).any()
        if free and not moving[k]:
            pos = np.stack([a[:, f:f+3] for f in free], 1)
            moving[k] |= _directed(np.linalg.norm(pos[-1]-pos[0], axis=1),
                                   np.linalg.norm(np.diff(pos, axis=0), axis=2).sum(0), THRESHOLDS['body_m']).any()
            rot = np.stack([a[:, f+3:f+7] for f in free], 1)
            moving[k] |= _directed(_angle(rot[-1], rot[0]), _angle(rot[1:], rot[:-1]).sum(0), THRESHOLDS['body_rad']).any()
    for event in reader.events():
        if event['event'] == 'rgba':
            moving[min(len(starts)-1, int(np.searchsorted(times, event['sim_time_s'], side='right'))//step)] = True
    context = moving.copy()
    context[:-1] |= moving[1:]
    context[1:] |= moving[:-1]
    keep = np.repeat(context, step)[:len(times)]
    keep[0] = keep[-1] = True
    return times, keep, moving


def refine_with_video(keep, source_hz, speed, fps, video_keep):
    """Remove the source states that a dropped video frame stood for.

    The video sampled sample_timeline(keep, ...) states; each one stands for the
    kept states from halfway after the previous sampled state to halfway before
    the next. First and last states stay."""
    keep = np.asarray(keep, dtype=bool).copy()
    retained = np.flatnonzero(keep)
    selected = sample_timeline(keep, source_hz, speed, fps)
    video_keep = np.asarray(video_keep, dtype=bool)
    if len(selected) != len(video_keep):
        raise ValueError('Video frames differ from the sampled timeline')
    position = np.searchsorted(retained, selected)
    edges = np.r_[0, (position[1:]+position[:-1])//2+1, len(retained)]
    for k in np.flatnonzero(~video_keep):
        keep[retained[edges[k]:edges[k+1]]] = False
    keep[0] = keep[-1] = True
    return keep


def write_cut(path, recording, times, keep, evidence):
    """A motion-edit.v1 timeline that simple rendering and Factory import both read."""
    reader = MotionReader(recording)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = path.with_suffix('.npz')
    np.savez_compressed(arrays, source_time_s=times, keep=keep)
    write_json(path, dict(schema=SCHEMA, case_id=reader.meta['case_id'], recording=str(reader.path),
        source_stream_sha256=digest(reader.path/'stream.json'), source_scene_sha256=reader.meta['source_scene_sha256'],
        source_frames=len(times), source_hz=reader.meta['sample_hz'], arrays=arrays.name, arrays_sha256=digest(arrays),
        kept_source_frames=int(keep.sum()), removed_source_frames=int((~keep).sum()),
        keep_intervals=[dict(start_sim_s=float(times[a]), last_sim_s=float(times[b-1])) for a, b in ranges(keep)],
        window_s=WINDOW_S, thresholds=THRESHOLDS, evidence=evidence,
        scope='Presentation cuts of still, jittering or drifting intervals; no resimulation or modified recording'))
    return path
