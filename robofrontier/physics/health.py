"""Fail a run on numeric failure instead of continuing a reset world.

Besides bad positions, velocities, accelerations and controls, a full contact or
constraint buffer (MuJoCo then silently drops contacts) and a bad inertia also fail
the step: the world after any of them is no longer the released physics.
"""
import mujoco
import numpy as np

FAILURES = ('mjWARN_BADQPOS', 'mjWARN_BADQVEL', 'mjWARN_BADQACC', 'mjWARN_BADCTRL',
            'mjWARN_CONTACTFULL', 'mjWARN_CNSTRFULL', 'mjWARN_INERTIA')


def require_valid_step(data, previous_time):
    bad = [name for name in FAILURES if data.warning[getattr(mujoco.mjtWarning, name)].number]
    if bad or not np.isfinite(data.time) or data.time <= previous_time or not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all():
        raise RuntimeError('Numerical physics failure; abort without reset/replay: '+','.join(bad))
