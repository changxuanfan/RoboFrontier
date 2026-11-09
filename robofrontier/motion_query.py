"""Object poses at a simulation time, read from a run's motion recording.

Logs of format events-60s leave poses out because the recording already holds them,
30 times per second; events-10s logs keep them every 10 s as a backup. The values are
float32, as recorded.
"""
import json
from pathlib import Path

import numpy as np


def recordings(run):
    """Motion folders of a run in segment order."""
    outputs = Path(run)/'private/outputs'
    folders = [outputs/'motion'] if (outputs/'motion/stream.json').is_file() else []
    segments = outputs/'segments'
    if segments.is_dir():
        numbered = sorted((p for p in segments.iterdir() if p.name.isdigit()), key=lambda p: int(p.name))
        folders += [p/'motion' for p in numbered if (p/'motion/stream.json').is_file()]
    return folders


def _state_at(folder, sim_time):
    """The last recorded state at or before sim_time, as (time, state), or None."""
    meta = json.loads((folder/'stream.json').read_text())
    found = None
    for chunk in meta['chunks']:
        with np.load(folder/chunk['file'], allow_pickle=False) as z:
            times = z['time_s']
            if times[0] > sim_time: break
            index = int(np.searchsorted(times, sim_time, side='right'))-1
            bits = np.bitwise_xor(np.bitwise_xor.accumulate(z['xor'][:index+1], axis=0)[-1], z['base'])
            found = float(times[index]), bits.view('<f4').astype(float)
    return found


def object_poses(run, sim_time):
    """{body name: {position_m, quaternion_wxyz, sim_time_s}} of free bodies, at or before sim_time."""
    best = None
    for folder in recordings(run):
        state = _state_at(folder, sim_time)
        if state is not None: best = folder, *state
    if best is None: raise ValueError('No recorded motion at or before this time')
    folder, time_s, state = best
    joints = json.loads((folder/'source/workstation.json').read_text())['joints']
    poses = {}
    for joint in joints:
        if joint['type'] == 0:
            address = joint['qpos_address']
            poses[joint['body']] = {'position_m': state[address:address+3].tolist(),
                                    'quaternion_wxyz': state[address+3:address+7].tolist(), 'sim_time_s': time_s}
    return poses
